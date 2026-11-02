"""Cross-file impact check: new language-server errors in the files that import what a turn edited.

Hermes checks diagnostics on the file an edit wrote and nothing else, so a changed
signature, return shape or keyword leaves its callers broken without a word. Opt in
with env ``OMH_IMPACT_CHECK`` or the profile setting
``plugins.entries.omh.settings.impact_check``; off, every entry point returns at once.

1. ``baseline_before_edit`` (``pre_tool_call``): on a turn's first ``patch`` /
   ``write_file`` of an existing ``.py`` file, find up to ``MAX_IMPORTERS`` workspace
   files that import it (stdlib ``ast`` scan) and record their current errors.
2. ``round_end_note`` (``pre_verify``, attempt 0): re-check those importers against the
   disk and return a short ``path:line: message`` note when an error appeared that the
   baseline did not have; ``""`` when nothing is new or nothing can be said.

Errors are compared as (code, message) counts per file, not by position, so an error
that only moved when the model edited that importer is not reported as new. A file the
server gave no verdict for is skipped, never reported clean or broken. State is
per-process and per session, reset when a new turn id reaches ``pre_tool_call``.
"""

from __future__ import annotations

import ast
import logging
import os
import re
import sys
import threading
import time
from collections import Counter
from typing import Any, Final

from . import lsp_bridge, lsp_nav, runtime_paths
from .lsp_bridge import BridgeError
from .lsp_nav import LspNavError
from .tools.lsp_nav_tool import _lsp_tools_enabled, _workspace_root, workspace_relative

IMPACT_ENV: Final = "OMH_IMPACT_CHECK"
IMPACT_SETTING: Final = "impact_check"
MAX_IMPORTERS: Final = 30
MAX_SCAN_FILES: Final = 2000
MAX_SCAN_BYTES: Final = 512_000
MAX_NOTE_LINES: Final = 15
# Both checks run inside host hooks that Hermes bounds by `plugins.hook_callback_timeout` (30 s by
# default, 0..600 configurable). `pre_tool_call` fails closed on it: an overrun refuses the edit and
# suppresses OMH's whole callback for 60 s. So each check's total -- importer scan, server spawn,
# syncs and waits -- is a fixed share of the configured timeout (8 s and 10 s at the default), and
# the check is skipped when that share is too small to be useful. A baseline that runs out records
# nothing for that edit; the next edit of the file retries, so a retry after a timeout can miss the
# change the first edit made.
HOST_HOOK_TIMEOUT_DEFAULT: Final = 30.0
BASELINE_SHARE: Final = 8.0 / 30.0
ROUND_END_SHARE: Final = 10.0 / 30.0
_MIN_BUDGET: Final = 2.0
_MIN_WAIT: Final = 1.0
_MAX_SESSIONS: Final = 64
_MESSAGE_CHARS: Final = 200
_EDIT_TOOLS: Final = frozenset({"patch", "write_file"})
# Updates only: a deleted or moved module stays open in the server, so its importers would
# still resolve against the old copy and the check would wrongly stay silent.
_V4A_HEADER: Final = re.compile(r"^\*\*\*\s*Update\s+File:\s*(.+)$", re.MULTILINE)
_ON: Final = ("1", "true", "on", "yes")
_SEVERITY_ERROR: Final = 1

_LOG = logging.getLogger("omh.impact_check")
_lock = threading.Lock()
# session -> {"turn": str, "root": str, "edited": set[str], "baseline": {importer: Counter | None}}
_sessions: dict[str, dict[str, Any]] = {}


def enabled() -> bool:
    """True when env ``OMH_IMPACT_CHECK`` or the profile setting ``impact_check`` is on; read failures are off."""
    if os.environ.get(IMPACT_ENV, "").strip().lower() in _ON:
        return True
    try:
        text = (runtime_paths.default_hermes_home() / "config.yaml").read_text(encoding="utf-8")
        value = runtime_paths.plugin_setting_text(text, IMPACT_SETTING)
    except Exception:  # noqa: BLE001 - fail closed: an unreadable config leaves the check off
        return False
    return value is not None and value.strip().lower() in _ON


def host_hook_timeout() -> float:
    """The profile's `plugins.hook_callback_timeout` as Hermes resolves it: default 30 s when unset,
    unreadable or negative; 0 (no host bound) is treated as the default so OMH still bounds itself."""
    try:
        text = (runtime_paths.default_hermes_home() / "config.yaml").read_text(encoding="utf-8")
        value = runtime_paths.config_scalar_text(text, ("plugins", "hook_callback_timeout"))
        timeout = float(value) if value is not None else HOST_HOOK_TIMEOUT_DEFAULT
    except (OSError, ValueError, runtime_paths.RuntimeBindingError):
        return HOST_HOOK_TIMEOUT_DEFAULT
    if timeout <= 0:
        return HOST_HOOK_TIMEOUT_DEFAULT
    return min(timeout, 600.0)


def budgets() -> tuple[float, float]:
    """(baseline, round-end) seconds; a share below ``_MIN_BUDGET`` is 0, which skips that check."""
    host = host_hook_timeout()
    shares = (host * BASELINE_SHARE, host * ROUND_END_SHARE)
    return tuple(share if share >= _MIN_BUDGET else 0.0 for share in shares)  # type: ignore[return-value]


def edit_targets(tool_name: object, args: object) -> list[str]:
    """The ``.py`` paths a ``patch`` / ``write_file`` call names (``path``, or V4A ``*** Update File:`` headers)."""
    if tool_name not in _EDIT_TOOLS or not isinstance(args, dict):
        return []
    paths: list[str] = []
    if tool_name == "patch" and args.get("mode") == "patch":
        body = args.get("patch")
        if isinstance(body, str):
            paths = [match.group(1).strip() for match in _V4A_HEADER.finditer(body)]
    elif isinstance(args.get("path"), str):
        paths = [args["path"]]
    return [path for path in paths if path.endswith(".py")]


_SOURCE_ROOT_MARKERS: Final = ("pyproject.toml", "setup.py", "setup.cfg")


def _source_root(directory: str, root: str) -> bool:
    """Whether absolute imports plausibly start at ``directory``: the workspace root, a ``src``
    directory, or a directory holding project metadata or a git checkout."""
    return (directory == root or os.path.basename(directory) == "src"
            or any(os.path.exists(os.path.join(directory, marker)) for marker in (*_SOURCE_ROOT_MARKERS, ".git")))


def _anchor(path: str, root: str) -> str:
    """The directory names are counted from: the nearest ancestor of ``root`` holding ``.git`` or
    project metadata (so a session started in a sub-directory still sees `pkg.mod`), else ``root``."""
    current = root
    while True:
        if any(os.path.exists(os.path.join(current, marker)) for marker in (*_SOURCE_ROOT_MARKERS, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return root
        current = parent


def module_names(path: str, root: str) -> set[str]:
    """The dotted names ``path`` is imported as from a source root (``_source_root``).

    A bare suffix such as ``types`` from ``app/types.py`` is not one, and neither is a name that is
    a standard-library module: both would match unrelated imports. A sibling's bare import is
    matched separately (``_sibling_name``).
    """
    anchor = _anchor(path, root)
    parts = os.path.relpath(path, anchor).replace(os.sep, "/")[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    names = {".".join(parts[index:]) for index in range(len(parts))
             if parts[index:] and _source_root(os.path.join(anchor, *parts[:index]), anchor)}
    return {name for name in names if name.split(".", 1)[0] not in sys.stdlib_module_names}


def _sibling_name(importer: str, target: str) -> str | None:
    """The bare name a script in ``target``'s own directory imports it by (``import helpers``)."""
    if os.path.dirname(importer) != os.path.dirname(target) or os.path.basename(target) == "__init__.py":
        return None
    return os.path.basename(target)[: -len(".py")]


def _relative_base(importer: str, node: ast.ImportFrom) -> str:
    base = os.path.dirname(importer)
    for _ in range(node.level - 1):
        base = os.path.dirname(base)
    return os.path.join(base, *node.module.split(".")) if node.module else base


def _is_module(path: str, target: str) -> bool:
    return target in (path + ".py", os.path.join(path, "__init__.py"))


def _imports_from(node: ast.ImportFrom, importer: str, target: str, names: set[str]) -> str:
    """``"module"`` when ``node`` imports names out of ``target``, ``"submodule"`` when it imports
    ``target`` itself as a member of its package, ``""`` otherwise."""
    if node.level:
        base = _relative_base(importer, node)
        if _is_module(base, target):
            return "module"
        return "submodule" if any(_is_module(os.path.join(base, alias.name), target) for alias in node.names) else ""
    if node.module in names:
        return "module"
    return "submodule" if any(f"{node.module}.{alias.name}" in names for alias in node.names) else ""


def imports_module(tree: ast.AST, importer: str, target: str, names: set[str], only: set[str] | None = None) -> bool:
    """Whether ``tree`` (the file ``importer``) imports ``target`` (known as ``names``).

    ``only`` narrows a package ``__init__`` target to the names it re-exports: ``from pkg import x``
    counts only for such an ``x``, so importing an unrelated member of the package does not.
    """
    sibling = _sibling_name(importer, target)
    if sibling is not None:
        names = names | {sibling}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name in names for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            kind = _imports_from(node, importer, target, names)
            if kind == "submodule" and only is None:
                return True
            if kind == "module" and (only is None or "*" in only or any(alias.name in only for alias in node.names)):
                return True
    return False


def _reexports(tree: ast.AST, init: str, target: str, names: set[str]) -> set[str]:
    """The names the package ``init`` binds from ``target`` (``from .pricing import fee as f`` -> ``f``)."""
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and _imports_from(node, init, target, names):
            bound.update(alias.asname or alias.name for alias in node.names)
    return bound


def find_importers(root: str, target: str, cap: int = MAX_IMPORTERS, deadline: float | None = None) -> list[str]:
    """Up to ``cap`` workspace ``.py`` files importing ``target``, plus importers of a package
    ``__init__.py`` that re-exports it (one level). Sorted walk, bounded by ``MAX_SCAN_FILES`` and,
    when given, by the ``time.monotonic()`` ``deadline`` (what was found by then is returned)."""
    files = lsp_nav.workspace_files(root, ".py", target, MAX_SCAN_FILES)[1:]
    texts: dict[str, str | None] = {}
    trees: dict[str, ast.AST | None] = {}
    found: list[str] = []
    queue: list[tuple[str, set[str] | None]] = [(target, None)]
    seen = {target}
    while queue and len(found) < cap:
        current, only = queue.pop(0)
        names = module_names(current, root)
        leaves = {name.rsplit(".", 1)[-1] for name in names} | {os.path.basename(current)[: -len(".py")]}
        for path in files:
            if path in seen or len(found) >= cap:
                continue
            if deadline is not None and time.monotonic() >= deadline:
                return found
            if path not in texts:
                texts[path] = _read(path)
            text = texts[path]
            # Cheap pre-filter: a relative `from . import x` need not spell the module's name.
            if text is None or "import" not in text or not (any(leaf in text for leaf in leaves) or "from ." in text):
                continue
            if path not in trees:
                trees[path] = _parse(text)
            tree = trees[path]
            if tree is not None and imports_module(tree, path, current, names, only):
                seen.add(path)
                found.append(path)
                if os.path.basename(path) == "__init__.py" and only is None:
                    exported = _reexports(tree, path, current, names)
                    if exported:
                        queue.append((path, exported))
    return found


def _read(path: str) -> str | None:
    try:
        if os.path.getsize(path) > MAX_SCAN_BYTES:
            return None
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _parse(text: str) -> ast.AST | None:
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


def _errors(diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in diagnostics if isinstance(item, dict) and (item.get("severity") or 1) == _SEVERITY_ERROR]


def _key(item: dict[str, Any]) -> tuple[str, str]:
    code = item.get("code")
    return ("" if code is None else str(code), str(item.get("message") or "").strip())


def forget_other_turn(session_id: str, turn_id: object) -> None:
    """Drop a session's state from an earlier turn; called for every tool call, edit or not, so a
    turn whose first stop never reached ``pre_verify`` cannot lend its baseline to the next one."""
    if not session_id:
        return
    with _lock:
        state = _sessions.get(session_id)
        if state is not None and state["turn"] != str(turn_id or ""):
            del _sessions[session_id]


def _session_state(session_id: str, turn_id: str, root: str) -> dict[str, Any]:
    with _lock:
        state = _sessions.get(session_id)
        if state is None or state["turn"] != turn_id or state["root"] != root:
            state = {"turn": turn_id, "root": root, "edited": set(), "baseline": {}}
            _sessions.pop(session_id, None)
            _sessions[session_id] = state
            while len(_sessions) > _MAX_SESSIONS:
                del _sessions[next(iter(_sessions))]
        return state


def baseline_before_edit(kwargs: dict[str, Any], tool_input: object) -> None:
    """``pre_tool_call``: record the importers' errors before the turn's first edit of each ``.py`` file."""
    session_id = str(kwargs.get("session_id", "") or kwargs.get("task_id", "") or "")
    forget_other_turn(session_id, kwargs.get("turn_id"))
    tool_name = kwargs.get("tool_name")
    if tool_name not in _EDIT_TOOLS:
        return
    targets = edit_targets(tool_name, tool_input)
    if not targets or not session_id or not enabled():
        return
    started = time.monotonic()
    budget = budgets()[0]
    if budget <= 0:
        _LOG.info("impact_check baseline session=%s skipped=hook_timeout_too_small", session_id)
        return
    deadline = started + budget
    claimed: list[str] = []
    pending: list[str] = []
    state: dict[str, Any] | None = None
    try:
        root = os.path.realpath(_workspace_root(kwargs.get("task_id")) or os.getcwd())
        state = _session_state(session_id, str(kwargs.get("turn_id", "") or ""), root)
        _, unavailable = lsp_bridge.available()
        if unavailable is not None:
            # Claimed and kept: without a language server there is nothing to retry on the next edit.
            with _lock:
                state["edited"].update(path for path in (_resolved(item, root) for item in targets) if path)
            _LOG.info("impact_check baseline session=%s skipped=lsp_unavailable", session_id)
            return
        for requested in targets:
            if time.monotonic() >= deadline:
                break
            try:
                path = lsp_nav.resolve_path(requested, root)
            except LspNavError:
                continue
            if not os.path.isfile(path) or not lsp_bridge.in_git_worktree(path):
                continue
            with _lock:
                if path in state["edited"]:
                    continue
                state["edited"].add(path)  # claimed; released below if no baseline is recorded
                room = MAX_IMPORTERS - len(state["baseline"])
            claimed.append(path)
            found = find_importers(root, path, room, deadline) if room > 0 else []
            with _lock:
                # Reserve under the lock: a parallel edit's baseline of the same importer keeps the first.
                for item in found:
                    if item not in state["baseline"] and len(state["baseline"]) < MAX_IMPORTERS:
                        state["baseline"][item] = None
                        pending.append(item)
        if not pending:
            return
        remaining = deadline - time.monotonic()
        if remaining < _MIN_WAIT:
            raise BridgeError("timeout", "no time left after the importer scan")
        # Everything this turn edited so far is synced first, so the baseline and the round-end
        # check judge each importer against the same versions of what it imports.
        with _lock:
            sync = sorted(item for item in state["edited"] if os.path.isfile(item))
        current = lsp_bridge.diagnostics(pending, sync=sync, timeout=remaining)
        with _lock:
            for path in pending:
                found_diags = current.get(path)
                if found_diags is not None:
                    state["baseline"][path] = Counter(_key(item) for item in _errors(found_diags))
        pending_unknown = sum(1 for path in pending if current.get(path) is None)
        _LOG.info("impact_check baseline session=%s importers=%d unknown=%d ms=%d", session_id, len(pending),
                  pending_unknown, (time.monotonic() - started) * 1000)
    except BridgeError as exc:
        _release(state, claimed, pending)
        _LOG.info("impact_check baseline session=%s skipped=%s", session_id, exc.code)
    except Exception as exc:  # noqa: BLE001 - never fail the edit it is watching
        _release(state, claimed, pending)
        _LOG.warning("impact_check baseline session=%s failed=%s", session_id, type(exc).__name__)


def _resolved(requested: str, root: str) -> str | None:
    try:
        return lsp_nav.resolve_path(requested, root)
    except LspNavError:
        return None


def _release(state: dict[str, Any] | None, claimed: list[str], reserved: list[str]) -> None:
    """Un-claim edits and importer slots whose baseline failed, so the turn's next edit tries again."""
    if state is None:
        return
    with _lock:
        state["edited"].difference_update(claimed)
        for path in reserved:
            if state["baseline"].get(path, 0) is None:
                del state["baseline"][path]


def _line(item: dict[str, Any]) -> int:
    value = ((item.get("range") or {}).get("start") or {}).get("line", 0)
    return value + 1 if isinstance(value, int) and not isinstance(value, bool) else 0


def round_end_note(session_id: str, changed_paths: object) -> str:
    """``pre_verify`` attempt 0: the note naming new importer errors, or ``""``. Consumes the session's baseline.

    Silent unless this turn's own ``.py`` edits (``changed_paths``) include a file the baseline was
    taken for: a baseline the turn did not earn says nothing about the turn.
    """
    with _lock:
        state = _sessions.pop(session_id, None) if session_id else None
    if not state:
        return ""
    try:
        root = state["root"]
        sync = []
        for item in changed_paths if isinstance(changed_paths, (list, tuple)) else ():
            if isinstance(item, str) and item.endswith(".py"):
                sync.append(os.path.realpath(item if os.path.isabs(item) else os.path.join(root, item)))
        if not set(sync) & state["edited"]:
            return ""
        known = {path: counts for path, counts in state["baseline"].items()
                 if counts is not None and os.path.isfile(path)}
        if not known or not enabled():
            return ""
        budget = budgets()[1]
        if budget <= 0:
            return ""
        started = time.monotonic()
        current = lsp_bridge.diagnostics(list(known), sync=sync, timeout=budget)
        new: list[tuple[str, int, str]] = []
        for path, baseline in known.items():
            found = current.get(path)
            if found is None:
                continue
            remaining = Counter(baseline)
            for item in sorted(_errors(found), key=_line):
                key = _key(item)
                if remaining[key] > 0:
                    remaining[key] -= 1
                    continue
                message = (key[1].splitlines() or ["error"])[0][:_MESSAGE_CHARS]
                new.append((workspace_relative(path, root), _line(item), message))
        _LOG.info("impact_check round_end session=%s importers=%d new_errors=%d files=%d ms=%d", session_id,
                  len(known), len(new), len({row[0] for row in new}), (time.monotonic() - started) * 1000)
        return format_note(new, recheck_tool=_lsp_tools_enabled())
    except BridgeError as exc:
        _LOG.info("impact_check round_end session=%s skipped=%s", session_id, exc.code)
        return ""
    except Exception as exc:  # noqa: BLE001 - a broken check says nothing rather than fail the turn
        _LOG.warning("impact_check round_end session=%s failed=%s", session_id, type(exc).__name__)
        return ""


def format_note(new: list[tuple[str, int, str]], recheck_tool: bool) -> str:
    """At most ``MAX_NOTE_LINES`` lines: a header, ``path:line: message`` rows, an overflow count, a closing ask."""
    if not new:
        return ""
    rows = sorted(new)
    room = MAX_NOTE_LINES - 2
    shown = rows if len(rows) <= room else rows[: room - 1]
    lines = ["OMH impact check: files that import the code you changed have errors they did not have before "
             "your edit (language server, checked against the disk now; another writer's changes would show "
             "here too):"]
    lines += [f"{path}:{line}: {message}" for path, line, message in shown]
    if len(shown) < len(rows):
        lines.append(f"... and {len(rows) - len(shown)} more")
    # Hermes passes no toolset list to its hooks, so a profile with `lsp_tools` on cannot tell whether
    # this session (a `-t file,terminal` run, a delegated child) has the tool: it is named as optional.
    check = ("re-check them (with `lsp_diagnostics` if your tools include it; enable via `OMH_LSP_TOOLS=1`"
             " or the `lsp_tools` setting)" if recheck_tool
              else "re-run the checks that cover them (or enable `lsp_diagnostics` via `OMH_LSP_TOOLS=1`"
              " or the `lsp_tools` setting)")
    # No final-answer sentence here: `pre_verify` ends the whole message with one closing sentence
    # for this note and the round-end check together (`verify_hooks.ROUND_END_CLOSING`), because
    # whatever the model says after a continue becomes the turn's final answer.
    lines.append(f"Fix these callers (or confirm the break is intended) and {check}.")
    return "\n".join(lines)


__all__ = [
    "IMPACT_ENV",
    "IMPACT_SETTING",
    "MAX_IMPORTERS",
    "MAX_NOTE_LINES",
    "baseline_before_edit",
    "budgets",
    "edit_targets",
    "enabled",
    "find_importers",
    "forget_other_turn",
    "format_note",
    "host_hook_timeout",
    "imports_module",
    "module_names",
    "round_end_note",
]
