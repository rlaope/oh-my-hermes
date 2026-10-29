"""`lsp_definition` / `lsp_references` / `lsp_rename`: opt-in semantic navigation tools.

They drive Hermes' own LSP service (pyright for Python) through `omh.lsp_bridge`.
Registered under the dedicated toolset `omh-lsp` and hidden behind a `check_fn`
(env `OMH_LSP_TOOLS` or the profile setting `plugins.entries.omh.settings.lsp_tools`),
so normal sessions pay no schema cost. Handlers return JSON strings and never raise.
Position, symbol and edit rules live in the pure module `omh.lsp_nav`.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .. import lsp_bridge, lsp_nav, runtime_paths
from ..lsp_bridge import BridgeError
from ..lsp_nav import LspNavError

LSP_TOOLSET = "omh-lsp"
_PREVIEW_CAP = 200

_COMMON = {
    "path": {"type": "string", "description": "File path relative to the workspace root"},
    "line": {"type": "integer", "minimum": 1, "description": "1-based line containing the symbol"},
    "symbol": {"type": "string", "description": "The identifier as written on that line"},
    "occurrence": {"type": "integer", "minimum": 1, "default": 1, "description": "Nth match of symbol on the line"},
}

OMH_LSP_DEFINITION_SCHEMA = {
    "name": "lsp_definition",
    "description": "Go to the definition of the symbol at path:line via the language server.",
    "parameters": {
        "type": "object", "additionalProperties": False, "required": ["path", "line", "symbol"],
        "properties": dict(_COMMON),
    },
}

OMH_LSP_REFERENCES_SCHEMA = {
    "name": "lsp_references",
    "description": (
        "Every semantic use of the symbol at path:line across the workspace, including its "
        "declaration and imports/aliases; skips strings and unrelated same-name symbols."
    ),
    "parameters": {
        "type": "object", "additionalProperties": False, "required": ["path", "line", "symbol"],
        "properties": dict(_COMMON),
    },
}

OMH_LSP_RENAME_SCHEMA = {
    "name": "lsp_rename",
    "description": (
        "Rename the symbol at path:line everywhere it is used (imports, re-exports, all files) "
        "via the language server. All-or-nothing; apply=false previews."
    ),
    "parameters": {
        "type": "object", "additionalProperties": False, "required": ["path", "line", "symbol", "new_name"],
        "properties": {
            **_COMMON,
            "new_name": {"type": "string", "description": "New identifier"},
            "apply": {"type": "boolean", "default": True, "description": "false = preview only"},
        },
    },
}

_ON = ("1", "true", "on", "yes")


def _lsp_tools_enabled() -> bool:
    """`check_fn`: True when env `OMH_LSP_TOOLS` or the active profile's
    `plugins.entries.omh.settings.lsp_tools` setting is on.

    The gateway builds tool definitions in its own process, so a client's env never
    reaches this check; the profile setting is read from the profile's `config.yaml`
    text. Any read failure is off.
    """
    if os.environ.get("OMH_LSP_TOOLS", "").strip().lower() in _ON:
        return True
    try:
        text = (runtime_paths.default_hermes_home() / "config.yaml").read_text(encoding="utf-8")
        value = runtime_paths.plugin_setting_text(text, "lsp_tools")
    except Exception:
        return False
    return value is not None and value.strip().lower() in _ON


def _workspace_root(task_id: object) -> str | None:
    """The session's workspace root as Hermes' own file tools resolve it (``TERMINAL_CWD`` fallback)."""
    try:
        from tools.file_tools_paths import _resolve_base_dir

        return str(_resolve_base_dir(str(task_id or "default"), container_paths=False))
    except Exception:
        return os.environ.get("TERMINAL_CWD")


class _Fail(Exception):
    def __init__(self, code: str, hint: str, **extra: Any) -> None:
        super().__init__(hint)
        self.code, self.hint, self.extra = code, hint, extra


def _fail(code: str, hint: str, **extra: Any) -> str:
    return json.dumps({"ok": False, "error": code, "hint": hint, **extra}, ensure_ascii=False)


def _root_for(kwargs: dict[str, object]) -> str:
    root = _workspace_root(kwargs.get("task_id"))
    return os.path.realpath(root if root else os.getcwd())


def _positive_int(args: dict[str, Any], name: str, default: int | None = None) -> int:
    value = args.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _Fail("invalid_argument", f"{name} must be a positive integer")
    return value


def _target(args: dict[str, Any], root: str) -> tuple[str, dict[str, Any], str]:
    """Resolve the file and the symbol position: ``(abs_path, position_params, line_text)``."""
    requested = str(args.get("path", "") or "")
    try:
        path = lsp_nav.resolve_path(requested, root)
    except LspNavError as exc:
        raise _Fail("scope_mismatch", str(exc)) from None
    if not os.path.isfile(path):
        similar = lsp_nav.similar_files(root, requested)
        raise _Fail(
            "not_found", f"{requested} does not exist; paths are relative to the workspace root {root}",
            similar_files=similar,
        )
    line = _positive_int(args, "line")
    occurrence = _positive_int(args, "occurrence", 1)
    symbol = args.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip():
        raise _Fail("invalid_argument", "symbol must be a non-empty string")
    symbol = symbol.strip()
    with open(path, "rb") as handle:
        text, _ = lsp_nav.decode(handle.read())
    lines = lsp_nav.split_lines(text)
    if line > len(lines):
        raise _Fail("symbol_not_found", f"line {line} is past the end of the file ({len(lines)} lines)")
    line_text = lines[line - 1][0]
    column = lsp_nav.find_symbol_column(line_text, symbol, occurrence)
    if column is None:
        raise _Fail("symbol_not_found", f"{symbol!r} (occurrence {occurrence}) is not on line {line}: {line_text.strip()!r}")
    position = {
        "textDocument": {"uri": lsp_nav.path_to_uri(path)},
        "position": {"line": line - 1, "character": lsp_nav.utf16_col(line_text, column)},
    }
    return path, position, line_text


def _ready(path: str) -> None:
    _, reason = lsp_bridge.available()
    if reason is not None:
        raise _Fail("lsp_unavailable", reason)
    if not lsp_bridge.in_git_worktree(path):
        raise _Fail("no_workspace", "Hermes LSP runs only inside a git worktree; the workspace must be a git repo (git init)")


_OPEN_CAP = 200


def _send(path: str, method: str, params: dict[str, Any], open_paths: list[str] | None = None,
          open_texts: dict[str, str] | None = None) -> Any:
    try:
        if open_texts is not None:
            return lsp_bridge.request(path, lambda: (method, params), list(open_texts), lsp_bridge.REQUEST_TIMEOUT,
                                      open_texts=open_texts)
        return lsp_bridge.request(path, lambda: (method, params), open_paths or [path], lsp_bridge.REQUEST_TIMEOUT)
    except BridgeError as exc:
        raise _Fail(exc.code, exc.hint) from None


def _snapshot(root: str, path: str, extra: list[str] = ()) -> tuple[dict[str, bytes], dict[str, str]]:
    """Read the target, up to ``_OPEN_CAP`` workspace files of its kind and ``extra`` ONCE.

    The texts are what the server is given; the bytes are what a later write must still
    find on disk. A rename edit is applied only to bytes the server actually saw, so a
    file changed by anyone between this read and the write is refused as ``stale_file``.
    """
    paths = lsp_nav.workspace_files(root, os.path.splitext(path)[1] or ".py", path, _OPEN_CAP)
    for item in extra:
        if item not in paths:
            paths.append(item)
    raw: dict[str, bytes] = {}
    texts: dict[str, str] = {}
    for item in paths:
        try:
            with open(item, "rb") as handle:
                data = handle.read()
            texts[item] = lsp_nav.decode(data)[0]
        except (OSError, LspNavError):
            continue  # unreadable or not UTF-8: never synced, so never a valid rename target
        raw[item] = data
    return raw, texts


_LINE_CACHE_CAP = 64


def _locations_payload(result: Any, root: str) -> dict[str, Any]:
    cache: dict[str, list[tuple[str, str]]] = {}
    locations: list[dict[str, Any]] = []
    outside = 0
    seen: set[tuple[str, int, int]] = set()
    for uri, line0, char0 in lsp_nav.normalize_locations(result):
        abs_path = os.path.realpath(lsp_nav.uri_to_path(uri))
        if not lsp_nav.inside(abs_path, root):
            outside += 1
            continue
        if abs_path not in cache and len(cache) < _LINE_CACHE_CAP:
            try:
                with open(abs_path, "rb") as handle:
                    cache[abs_path] = lsp_nav.split_lines(lsp_nav.decode(handle.read())[0])
            except (OSError, LspNavError):
                cache[abs_path] = []
        lines = cache.get(abs_path, [])
        line_text = lines[line0][0] if 0 <= line0 < len(lines) else ""
        key = (abs_path, line0, char0)
        if key in seen:
            continue
        seen.add(key)
        locations.append({
            "path": os.path.relpath(abs_path, root),
            "line": line0 + 1,
            "column": lsp_nav.py_index(line_text, char0) + 1,
            "text": line_text.strip(),
        })
    locations.sort(key=lambda loc: (loc["path"], loc["line"], loc["column"]))
    payload: dict[str, Any] = {"ok": True, "locations": locations, "count": len(locations)}
    if outside:
        payload["outside_root"] = outside
    return payload


def _navigate(args: dict[str, Any], kwargs: dict[str, object], method: str, extra: dict[str, Any],
              open_workspace: bool = False) -> str:
    try:
        root = _root_for(kwargs)
        path, position, _ = _target(args, root)
        _ready(path)
        open_paths = None
        if open_workspace:
            # pyright answers references from open documents only (measured live).
            open_paths = lsp_nav.workspace_files(root, os.path.splitext(path)[1] or ".py", path, _OPEN_CAP)
        result = _send(path, method, {**position, **extra}, open_paths)
        if result is None or result == []:
            return _fail("no_result", "the language server returned nothing for this symbol")
        return json.dumps(_locations_payload(result, root), ensure_ascii=False)
    except _Fail as exc:
        return _fail(exc.code, exc.hint, **exc.extra)
    except LspNavError as exc:
        return _fail(exc.code, str(exc))
    except Exception as exc:  # noqa: BLE001 - never raise to the host
        return _fail("unexpected_error", type(exc).__name__)


def lsp_definition_handler(args: dict[str, Any], **kwargs: object) -> str:
    return _navigate(args, kwargs, "textDocument/definition", {})


def lsp_references_handler(args: dict[str, Any], **kwargs: object) -> str:
    return _navigate(args, kwargs, "textDocument/references", {"context": {"includeDeclaration": True}},
                     open_workspace=True)


def _preview_edits(root: str, targets: dict[str, list[dict[str, Any]]], expected: dict[str, bytes]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, edits in targets.items():
        path = os.path.realpath(lsp_nav.uri_to_path(key))
        lines = lsp_nav.split_lines(lsp_nav.decode(expected[path])[0])
        for edit in edits:
            rng = edit.get("range") or {}
            start, end = rng.get("start") or {}, rng.get("end") or {}
            line0 = int(start.get("line", 0))
            old = ""
            if 0 <= line0 < len(lines) and int(end.get("line", line0)) == line0:
                content = lines[line0][0]
                old = content[lsp_nav.py_index(content, int(start.get("character", 0))):
                              lsp_nav.py_index(content, int(end.get("character", 0)))]
            rows.append({"path": os.path.relpath(path, root), "line": line0 + 1, "old": old,
                         "new": str(edit.get("newText", ""))})
    rows.sort(key=lambda row: (row["path"], row["line"]))
    return rows[:_PREVIEW_CAP]


_DONE_HINT = ("one lsp_rename updates every reference in the workspace; do not rename the remaining "
              "references one by one")


def _already_renamed(args: dict[str, Any], root: str) -> str | None:
    """The answer for a rename whose line already holds ``new_name`` instead of ``symbol``.

    A model that renames reference by reference asks again for lines an earlier call already
    rewrote; a bare symbol_not_found made it retry (measured: 42 repeats in one run). Saying the
    work is done ends that loop without writing anything.
    """
    new_name = args.get("new_name")
    if not isinstance(new_name, str) or not new_name:
        return None
    try:
        if not lsp_nav.valid_identifier(new_name, os.path.splitext(str(args.get("path", "") or ""))[1]):
            return None  # an invalid name gets invalid_name, never "already done"
        path = lsp_nav.resolve_path(str(args.get("path", "") or ""), root)
        line = _positive_int(args, "line")
        with open(path, "rb") as handle:
            lines = lsp_nav.split_lines(lsp_nav.decode(handle.read())[0])
    except (_Fail, LspNavError, OSError):
        return None
    if not 1 <= line <= len(lines) or lsp_nav.find_symbol_column(lines[line - 1][0], new_name) is None:
        return None
    return json.dumps({
        "ok": True, "applied": False, "already_renamed": True, "files": [], "total_edits": 0,
        "hint": f"line {line} already uses {new_name!r}: nothing to do; {_DONE_HINT}",
    }, ensure_ascii=False)


def lsp_rename_handler(args: dict[str, Any], **kwargs: object) -> str:
    try:
        root = _root_for(kwargs)
        new_name = args.get("new_name")
        requested = str(args.get("path", "") or "")
        if not isinstance(new_name, str) or not lsp_nav.valid_identifier(new_name, os.path.splitext(requested)[1]):
            return _fail("invalid_name", f"{new_name!r} is not a valid identifier for {os.path.basename(requested)}")
        try:
            path, position, _ = _target(args, root)
        except _Fail as exc:
            if exc.code == "symbol_not_found":
                done = _already_renamed(args, root)
                if done is not None:
                    return done
            raise
        apply = args.get("apply", True)
        if not isinstance(apply, bool):
            return _fail("invalid_argument", "apply must be a boolean")
        _ready(path)
        raw, texts = _snapshot(root, path)
        if path not in texts:
            return _fail("unsupported_edit", f"{os.path.relpath(path, root)} is not readable UTF-8")
        if _send(path, "textDocument/prepareRename", position, open_texts={path: texts[path]}) is None:
            return _fail("no_result", "not a renameable symbol here")
        expected: dict[str, bytes] = {}
        targets: dict[str, list[dict[str, Any]]] = {}
        for attempt in (1, 2):
            edit = _send(path, "textDocument/rename", {**position, "newName": new_name}, open_texts=texts)
            if edit is None:
                return _fail("no_result", "the language server returned no rename edit")
            targets = {k: v for k, v in lsp_nav.workspace_edit_targets(edit).items() if v}
            if not targets:
                return _fail("no_result", "the language server returned an empty rename edit")
            unsynced = []
            for key in targets:
                target = os.path.realpath(lsp_nav.uri_to_path(key))
                if not lsp_nav.inside(target, root):
                    raise lsp_nav.ScopeMismatch(f"edit targets {target}, outside the workspace root")
                if target not in raw:
                    unsynced.append(target)
            if not unsynced:
                expected = {os.path.realpath(lsp_nav.uri_to_path(key)): raw[os.path.realpath(lsp_nav.uri_to_path(key))]
                            for key in targets}
                break
            if attempt == 2:
                raise lsp_nav.StaleFile(
                    f"{os.path.relpath(unsynced[0], root)} could not be synced with the language server")
            raw, texts = _snapshot(root, path, unsynced)  # sync the files the server reached on its own, then ask again
        plans = lsp_nav.plan_workspace_edit(root, targets, expected)
        if not apply:
            files = [{"path": os.path.relpath(p, root), "edits": n} for p, _, n in plans]
            return json.dumps({
                "ok": True, "applied": False, "files": files, "total_edits": sum(n for _, _, n in plans),
                "edits": _preview_edits(root, targets, expected),
            }, ensure_ascii=False)
        written = lsp_nav.apply_workspace_edit(root, targets, expected)
        lsp_bridge.notify_changed(path, [os.path.join(root, rel) for rel, _ in written])
        return json.dumps({
            "ok": True, "applied": True, "files": [{"path": rel, "edits": n} for rel, n in written],
            "total_edits": sum(n for _, n in written),
            "hint": f"done: every reference was renamed; {_DONE_HINT}",
        }, ensure_ascii=False)
    except _Fail as exc:
        return _fail(exc.code, exc.hint, **exc.extra)
    except LspNavError as exc:
        return _fail(exc.code, f"{exc}; nothing written")
    except Exception as exc:  # noqa: BLE001 - never raise to the host
        return _fail("unexpected_error", type(exc).__name__)


__all__ = [
    "OMH_LSP_DEFINITION_SCHEMA",
    "OMH_LSP_REFERENCES_SCHEMA",
    "OMH_LSP_RENAME_SCHEMA",
    "LSP_TOOLSET",
    "_lsp_tools_enabled",
    "_workspace_root",
    "lsp_definition_handler",
    "lsp_references_handler",
    "lsp_rename_handler",
]
