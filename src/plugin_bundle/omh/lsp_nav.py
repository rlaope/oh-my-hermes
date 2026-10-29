"""Pure helpers for the opt-in `omh-lsp` tools: positions, symbol lookup, WorkspaceEdit apply.

No Hermes import: everything here is testable without the host. LSP positions are
0-based UTF-16 code units (Hermes' client advertises `positionEncodings: ["utf-16"]`).
Hermes syncs documents as `Path.read_text` decodes them (BOM dropped, universal
newlines), so a position's line is counted on `\\r\\n` / `\\r` / `\\n` only and a
position at end of line sits before the line ending.
"""

from __future__ import annotations

import keyword
import os
import re
import tempfile
from typing import Any
from urllib.parse import quote, unquote

_BOM = "\ufeff"
_LINE_SPLIT = re.compile(r"(\r\n|\r|\n)")
_IDENT_CHAR = re.compile(r"[A-Za-z0-9_]")
_RESOURCE_KINDS = frozenset({"create", "rename", "delete"})


class LspNavError(Exception):
    """Base for failures the handlers answer with a failure code."""

    code = "lsp_nav_error"


class UnsupportedEdit(LspNavError):
    code = "unsupported_edit"


class OverlapError(LspNavError):
    code = "unsupported_edit"


class ScopeMismatch(LspNavError):
    code = "scope_mismatch"


class StaleFile(LspNavError):
    code = "stale_file"


# ---- positions -------------------------------------------------------------


def utf16_col(line_text: str, py_index: int) -> int:
    """UTF-16 code-unit column of Python index ``py_index`` in ``line_text``."""
    prefix = line_text[: max(0, py_index)]
    return sum(2 if ord(ch) > 0xFFFF else 1 for ch in prefix)


def py_index(line_text: str, utf16_col: int) -> int:
    """Python index of UTF-16 column ``utf16_col``; clamped to the line length.

    A column inside a surrogate pair rounds up to the next character.
    """
    units = 0
    for index, ch in enumerate(line_text):
        if units >= utf16_col:
            return index
        units += 2 if ord(ch) > 0xFFFF else 1
    return len(line_text)


def split_lines(text: str) -> list[tuple[str, str]]:
    """``[(content, line_ending), ...]`` counting only ``\\r\\n``, ``\\r`` and ``\\n`` as breaks.

    The last entry has an empty ending; a text ending in a newline yields a final
    ``("", "")`` line, matching how an LSP server counts lines.
    """
    parts = _LINE_SPLIT.split(text)
    return [(parts[i], parts[i + 1] if i + 1 < len(parts) else "") for i in range(0, len(parts), 2)]


def find_symbol_column(line_text: str, symbol: str, occurrence: int = 1) -> int | None:
    """Python index of the first char of the Nth whole-identifier ``symbol`` on the line, else None.

    Only whole identifiers count (not bordered by ``[A-Za-z0-9_]``). A substring match
    would point the server at a different symbol: ``LIMIT`` inside ``LIMIT_ALIAS`` or
    ``MAX_LIMIT`` made a repeated rename rewrite ``LIMIT_ALIAS`` and report success.
    """
    if not symbol or occurrence < 1:
        return None
    starts: list[int] = []
    at = line_text.find(symbol)
    while at != -1:
        starts.append(at)
        at = line_text.find(symbol, at + 1)

    def whole(start: int) -> bool:
        end = start + len(symbol)
        before = start > 0 and _IDENT_CHAR.match(line_text[start - 1]) is not None
        after = end < len(line_text) and _IDENT_CHAR.match(line_text[end]) is not None
        return not before and not after

    whole_starts = [s for s in starts if whole(s)]
    if len(whole_starts) >= occurrence:
        return whole_starts[occurrence - 1]
    return None


def valid_identifier(name: str, suffix: str) -> bool:
    """A rename target the language accepts: Python rules for .py/.pyi, else non-empty, no whitespace."""
    if not isinstance(name, str) or not name:
        return False
    if suffix.lower() in (".py", ".pyi"):
        return name.isidentifier() and not keyword.iskeyword(name)
    return not any(ch.isspace() for ch in name)


# ---- URIs and paths --------------------------------------------------------


def path_to_uri(path: str) -> str:
    return "file://" + quote(os.path.abspath(path), safe="/:")


def uri_to_path(uri: str) -> str:
    if not uri.startswith("file://"):
        return uri
    return os.path.normpath(unquote(uri[len("file://"):]))


def inside(path: str, root: str) -> bool:
    """True when ``path`` is ``root`` or under it, both compared after realpath."""
    real, real_root = os.path.realpath(path), os.path.realpath(root)
    return real == real_root or real.startswith(real_root.rstrip(os.sep) + os.sep)


def resolve_path(path: str, root: str) -> str:
    """Resolve ``path`` against ``root`` (realpath); a root-relative absolute path falls back.

    Raises ``ScopeMismatch`` for a path outside the root.
    """
    root_abs = os.path.realpath(root)
    resolved = os.path.realpath(os.path.join(root_abs, path))
    if inside(resolved, root_abs):
        return resolved
    if os.path.isabs(path):
        rejoined = os.path.realpath(os.path.join(root_abs, path.lstrip("/\\")))
        if inside(rejoined, root_abs) and os.path.exists(rejoined):
            return rejoined
    raise ScopeMismatch(f"{path!r} resolves outside the workspace root {root_abs}")


_SKIP_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"})


def similar_files(root: str, path: str, limit: int = 5, cap: int = 2000) -> list[str]:
    """Up to ``limit`` root-relative files sharing ``path``'s basename (bounded walk)."""
    name = os.path.basename(path)
    found: list[str] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for filename in sorted(filenames):
            seen += 1
            if filename == name:
                found.append(os.path.relpath(os.path.join(dirpath, filename), root))
                if len(found) >= limit:
                    return found
            if seen >= cap:
                return found
    return found


def workspace_files(root: str, suffix: str, first: str, cap: int = 200) -> list[str]:
    """``first`` plus up to ``cap - 1`` other files under ``root`` ending in ``suffix`` (sorted walk).

    pyright answers `textDocument/references` from open documents only, so a caller
    opens these before asking.
    """
    found = [first]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        for filename in sorted(filenames):
            if not filename.endswith(suffix):
                continue
            path = os.path.realpath(os.path.join(dirpath, filename))
            if path != first and inside(path, root):
                found.append(path)
                if len(found) >= cap:
                    return found
    return found


# ---- results ---------------------------------------------------------------


def normalize_locations(result: Any) -> list[tuple[str, int, int]]:
    """``[(uri, line0, utf16_char0), ...]`` from Location, Location[], LocationLink[] or None."""
    if result is None:
        return []
    items = result if isinstance(result, list) else [result]
    out: list[tuple[str, int, int]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        uri = item.get("uri") or item.get("targetUri")
        rng = item.get("range") if "uri" in item else (item.get("targetSelectionRange") or item.get("targetRange"))
        if not isinstance(uri, str) or not isinstance(rng, dict):
            continue
        start = rng.get("start") or {}
        out.append((uri, int(start.get("line", 0)), int(start.get("character", 0))))
    return out


def workspace_edit_targets(edit: Any) -> dict[str, list[dict[str, Any]]]:
    """``{uri: [TextEdit, ...]}`` from a WorkspaceEdit's ``changes`` or ``documentChanges``.

    Raises ``UnsupportedEdit`` on a CreateFile/RenameFile/DeleteFile resource operation.
    """
    if not isinstance(edit, dict):
        raise UnsupportedEdit("workspace edit is not an object")
    targets: dict[str, list[dict[str, Any]]] = {}
    document_changes = edit.get("documentChanges")
    if isinstance(document_changes, list):
        for entry in document_changes:
            if not isinstance(entry, dict):
                raise UnsupportedEdit("malformed documentChanges entry")
            if entry.get("kind") in _RESOURCE_KINDS:
                raise UnsupportedEdit(f"resource operation {entry.get('kind')!r} is not applied")
            uri = (entry.get("textDocument") or {}).get("uri")
            if not isinstance(uri, str):
                raise UnsupportedEdit("documentChanges entry without a textDocument uri")
            targets.setdefault(uri, []).extend(entry.get("edits") or [])
        return targets
    changes = edit.get("changes")
    if isinstance(changes, dict):
        for uri, edits in changes.items():
            targets.setdefault(str(uri), []).extend(edits or [])
    return targets


# ---- applying edits --------------------------------------------------------


def _offsets(text: str) -> tuple[list[int], list[str]]:
    """Start offset and content (without ending) of every line."""
    starts: list[int] = []
    contents: list[str] = []
    at = 0
    for content, ending in split_lines(text):
        starts.append(at)
        contents.append(content)
        at += len(content) + len(ending)
    return starts, contents


def _offset(starts: list[int], contents: list[str], text_len: int, pos: dict[str, Any]) -> int:
    line = int(pos.get("line", 0))
    char = int(pos.get("character", 0))
    if line < 0 or char < 0:
        raise UnsupportedEdit(f"negative position {pos}")
    if line >= len(starts):
        return text_len
    return starts[line] + py_index(contents[line], char)


def apply_text_edits(text: str, edits: list[dict[str, Any]]) -> str:
    """Apply LSP TextEdits to ``text`` (all positions relative to the original text).

    Edits are applied from the end backwards; overlapping ranges raise ``OverlapError``.
    Line endings outside the edited ranges are untouched.
    """
    starts, contents = _offsets(text)
    spans: list[tuple[int, int, str]] = []
    for edit in edits:
        rng = edit.get("range") if isinstance(edit, dict) else None
        if not isinstance(rng, dict):
            raise UnsupportedEdit("text edit without a range")
        start = _offset(starts, contents, len(text), rng.get("start") or {})
        end = _offset(starts, contents, len(text), rng.get("end") or {})
        if end < start:
            raise UnsupportedEdit("text edit range ends before it starts")
        spans.append((start, end, str(edit.get("newText", ""))))
    spans.sort(key=lambda span: (span[0], span[1]), reverse=True)
    for later, earlier in zip(spans, spans[1:]):
        if earlier[1] > later[0]:
            raise OverlapError("overlapping text edits")
    out = text
    for start, end, new in spans:
        out = out[:start] + new + out[end:]
    return out


def decode(data: bytes) -> tuple[str, bool]:
    """``(text, had_bom)``; raises ``UnsupportedEdit`` for non-UTF-8 bytes."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise UnsupportedEdit("file is not UTF-8") from None
    if text.startswith(_BOM):
        return text[1:], True
    return text, False


def plan_workspace_edit(
    root: str, targets: dict[str, list[dict[str, Any]]], expected: dict[str, bytes]
) -> list[tuple[str, bytes, int]]:
    """Validate every target and compute new bytes: ``[(abs_path, new_bytes, n_edits), ...]``.

    Raises ``ScopeMismatch`` for a target outside ``root`` and ``StaleFile`` when a
    target's bytes on disk differ from ``expected``.
    """
    plans: list[tuple[str, bytes, int]] = []
    for key, edits in targets.items():
        path = os.path.realpath(uri_to_path(key))
        if not inside(path, root):
            raise ScopeMismatch(f"edit targets {path}, outside the workspace root")
        try:
            with open(path, "rb") as handle:
                current = handle.read()
        except OSError as exc:
            raise StaleFile(f"cannot read {path}: {type(exc).__name__}") from None
        want = expected.get(path)
        if want is None or current != want:
            raise StaleFile(f"{os.path.relpath(path, root)} changed since the server computed the edit")
        text, bom = decode(current)
        new_text = apply_text_edits(text, edits)
        plans.append((path, ((_BOM if bom else "") + new_text).encode("utf-8"), len(edits)))
    return plans


def _write_atomic(path: str, data: bytes) -> None:
    directory = os.path.dirname(path)
    mode = os.stat(path).st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(prefix=".omh-lsp-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def apply_workspace_edit(
    root: str, targets: dict[str, list[dict[str, Any]]], expected: dict[str, bytes]
) -> list[tuple[str, int]]:
    """Apply a WorkspaceEdit all-or-nothing: ``[(root-relative path, n_edits), ...]``.

    Every target is confined to ``root`` and re-read against ``expected`` and every new
    text is computed before the first write; any failure writes nothing. Each file is
    written through a temp file in its own directory plus ``os.replace``.
    """
    root_abs = os.path.realpath(root)
    plans = plan_workspace_edit(root_abs, targets, expected)
    for path, data, _ in plans:
        _write_atomic(path, data)
    return [(os.path.relpath(path, root_abs), n) for path, _, n in plans]


__all__ = [
    "LspNavError",
    "OverlapError",
    "ScopeMismatch",
    "StaleFile",
    "UnsupportedEdit",
    "apply_text_edits",
    "apply_workspace_edit",
    "decode",
    "find_symbol_column",
    "inside",
    "normalize_locations",
    "path_to_uri",
    "plan_workspace_edit",
    "py_index",
    "resolve_path",
    "similar_files",
    "split_lines",
    "uri_to_path",
    "utf16_col",
    "valid_identifier",
    "workspace_edit_targets",
]
