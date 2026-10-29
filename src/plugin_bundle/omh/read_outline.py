"""Append a symbol outline, with line ranges, to a truncated read of a large Python file.

The measured failure (#1723): a model that needed line 2318 of a 9,172-line
file read the first window, then kept asking for it. A truncated window tells
the model where it stopped and nothing about where anything else is, so the
model pages: window after window, or the same window again. An outline of the
whole file, with the line range of every class and function, lets it jump to
the right offset in one call instead.

What this pass does, and only this:

1. A ``read_file`` result that parses as a JSON object, carries
   ``truncated: true`` and ``total_lines`` of at least
   ``READ_OUTLINE_MIN_LINES``, and names a Python source file gains ONE key,
   ``READ_OUTLINE_KEY``, spliced in before the closing brace. Every byte the
   host wrote stays where it was; nothing is cut or rewritten.
2. The outline is built from the file on disk with stdlib ``ast``. A file that
   does not parse gets no outline (a partial outline would be guessed line
   numbers), and so does every other language: without a parser the END of a
   block is a guess, and a wrong range sends the model to the wrong offset,
   which is worse than no outline. Only Python is measured
   (``benchmarks/live-model-tools/v1/README.md``, ``bigfile-ab``).
3. Once per file version per session. A second truncated read of the same
   unchanged file already has the outline earlier in context and gets nothing;
   an edit changes the size or mtime, so the next truncated read gets the
   ranges as they now are.

Three gates keep the outline about the file the model read, not a file with
the same name:

* The path resolves through Hermes' own resolver for the call's task
  (``tools.file_tools_paths._resolve_path_for_task``), and only a host path is
  read; a remote (SSH) path is not.
* The file's line count, counted the way ``read_file`` counts it, must equal the
  result's ``total_lines``, and the first line the result returned must match
  the disk. A container path that happens to exist on the host, or a file that
  changed between the read and this hook, fails one of the two and gets nothing.
* Size bounds (``READ_OUTLINE_MAX_BYTES``, ``READ_OUTLINE_MAX_LINES``) keep the
  parse cheap.

The outline names identifiers only: classes, functions, methods and module
constants. Never a value, so a constant holding a secret contributes its name
and nothing else, and only for a file the host already agreed to read.

Small and untruncated reads pass through byte-identical: every early return is
``None``, which the seam reads as "leave the result alone".
"""

from __future__ import annotations

import ast
import json
import os
import re
import threading
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Final, NamedTuple

from . import runtime_paths

READ_OUTLINE_KEY: Final = "omh_read_outline"
READ_OUTLINE_TOOL: Final = "read_file"
READ_OUTLINE_SETTING: Final = "read_outline"
READ_OUTLINE_ENV: Final = "OMH_READ_OUTLINE"
READ_OUTLINE_DEFAULT_ON: Final = True

# Smallest file that gets an outline. Below this the rest of the file is one
# read away, so the outline would cost about as much as the read it saves.
READ_OUTLINE_MIN_LINES: Final = 400
# Outline body lines, header excluded.
READ_OUTLINE_MAX_ENTRIES: Final = 60
READ_OUTLINE_MAX_BYTES: Final = 2 * 1024 * 1024
READ_OUTLINE_MAX_LINES: Final = 50_000
# One outline line; long names are cut with an ellipsis so one entry cannot
# take the budget of several.
_MAX_LINE_CHARS: Final = 100
_PYTHON_SUFFIXES: Final = frozenset({".py", ".pyi", ".pyw"})

MAX_TRACKED_OUTLINE_SESSIONS: Final = 64
MAX_TRACKED_FILES_PER_SESSION: Final = 32

_ON: Final = frozenset({"1", "true", "on", "yes"})
_OFF: Final = frozenset({"0", "false", "off", "no"})
_LINE_PREFIX = re.compile(r"\s*(\d+)\|")
_CONSTANT_NAME = re.compile(r"_?[A-Z][A-Z0-9_]*\Z")

# Resolver failures by exception type. The outline is optional, so a failure
# skips it; the count is where a reader finds out that it did.
read_outline_failures: Counter[str] = Counter()

_emitted_lock = threading.Lock()
# session -> {(resolved path, size, mtime_ns)}: file versions already outlined.
_emitted: "OrderedDict[str, OrderedDict[tuple[str, int, int], None]]" = OrderedDict()


class OutlineEntry(NamedTuple):
    start: int
    end: int
    depth: int
    label: str
    # 0 = top-level class or function, 1 = method or nested class,
    # 2 = module constant. Lower survives the cap first.
    rank: int


def annotate_read_outline(
    *,
    tool_name: object,
    args: object,
    result: object,
    session_id: str = "",
    task_id: str = "",
) -> str | None:
    """Return *result* with the outline key spliced in, or ``None`` to pass through."""
    if str(tool_name or "") != READ_OUTLINE_TOOL:
        return None
    if not isinstance(result, str) or not result.endswith("}"):
        return None
    try:
        parsed = json.loads(result)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict) or READ_OUTLINE_KEY in parsed:
        return None
    if parsed.get("truncated") is not True or parsed.get("error"):
        return None
    total_lines = parsed.get("total_lines")
    if isinstance(total_lines, bool) or not isinstance(total_lines, int):
        return None
    if total_lines < READ_OUTLINE_MIN_LINES:
        return None
    path = (args if isinstance(args, dict) else {}).get("path")
    if not isinstance(path, str) or Path(path).suffix.lower() not in _PYTHON_SUFFIXES:
        return None
    content = parsed.get("content")
    shown = _shown_range(content)
    if shown is None or not read_outline_enabled():
        return None
    resolved = _resolve(path, task_id)
    if resolved is None:
        return None
    try:
        stat = os.stat(resolved)
        if stat.st_size > READ_OUTLINE_MAX_BYTES:
            return None
        with open(resolved, "rb") as handle:
            raw = handle.read(READ_OUTLINE_MAX_BYTES + 1)
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace")
    if _line_count(text) != total_lines or total_lines > READ_OUTLINE_MAX_LINES:
        return None
    if not _first_line_matches(text, content, shown[0]):
        return None
    version = (resolved, stat.st_size, stat.st_mtime_ns)
    session = session_id.strip() if isinstance(session_id, str) else ""
    if session and _already_emitted(session, version):
        return None
    entries = python_outline(text)
    if entries is None or len(entries) < 2:
        return None
    outline = render_outline(path=path, total_lines=total_lines, shown=shown, entries=entries)
    if session:
        _remember(session, version)
    # Spliced, not re-serialised: every byte the host (or an earlier pass) wrote stays as it was.
    return f"{result[:-1]}, {json.dumps(READ_OUTLINE_KEY)}: {json.dumps(outline, ensure_ascii=False)}}}"


def read_outline_enabled() -> bool:
    """Env ``OMH_READ_OUTLINE`` first, then the profile setting ``read_outline``, then the default.

    The gateway runs the hook in its own process, so a client's environment
    never reaches it; the profile's ``config.yaml`` is where an operator turns
    this off (``plugins.entries.omh.settings.read_outline: false``). A config
    this reader cannot read keeps the default.
    """
    spelled = os.environ.get(READ_OUTLINE_ENV, "").strip().lower()
    if spelled in _ON:
        return True
    if spelled in _OFF:
        return False
    try:
        config = runtime_paths.default_hermes_home() / "config.yaml"
        value = runtime_paths.plugin_setting_text(config.read_text(encoding="utf-8"), READ_OUTLINE_SETTING)
    except (OSError, ValueError):
        # `RuntimeBindingError` (no profile scope, malformed config) is a ValueError.
        return READ_OUTLINE_DEFAULT_ON
    spelled = (value or "").strip().lower()
    if spelled in _ON:
        return True
    if spelled in _OFF:
        return False
    return READ_OUTLINE_DEFAULT_ON


def python_outline(text: str) -> list[OutlineEntry] | None:
    """Classes, functions, methods and module constants with their line ranges, or ``None`` on a SyntaxError."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    entries: list[OutlineEntry] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            entries.append(_definition(node, depth=0, rank=0))
            if isinstance(node, ast.ClassDef):
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        entries.append(_definition(member, depth=1, rank=1))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = _constant_targets(node)
            if names:
                end = node.end_lineno or node.lineno
                entries.append(OutlineEntry(node.lineno, end, 0, ", ".join(names), 2))
    return entries


def render_outline(
    *, path: str, total_lines: int, shown: tuple[int, int], entries: list[OutlineEntry]
) -> str:
    """The header plus at most ``READ_OUTLINE_MAX_ENTRIES`` lines, in file order."""
    kept, note = _fit(entries)
    header = (
        f"[OMH outline] {path} has {total_lines:,} lines; this read returned lines "
        f"{shown[0]}-{shown[1]}. Symbols and their line ranges in the whole file, so you can "
        f"read_file the part you need with offset=<first line> and limit=<range length> "
        f"instead of paging through it:"
    )
    body = [_clip(f"{'  ' * entry.depth}{entry.start}-{entry.end} {entry.label}") for entry in kept]
    if note:
        body.append(note)
    return "\n".join([header, *body])


def reset_read_outline_records() -> None:
    """Test seam: forget which file versions were outlined, and the failure counts."""
    with _emitted_lock:
        _emitted.clear()
    read_outline_failures.clear()


def _definition(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, *, depth: int, rank: int) -> OutlineEntry:
    start = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
    end = node.end_lineno or node.lineno
    if isinstance(node, ast.ClassDef):
        kind = "class"
    elif isinstance(node, ast.AsyncFunctionDef):
        kind = "async def"
    else:
        kind = "def"
    return OutlineEntry(start, end, depth, f"{kind} {node.name}", rank)


def _constant_targets(node: ast.Assign | ast.AnnAssign) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names = []
    for target in targets:
        if isinstance(target, ast.Name) and (target.id == "__all__" or _CONSTANT_NAME.match(target.id)):
            names.append(target.id)
    return names


def _fit(entries: list[OutlineEntry]) -> tuple[list[OutlineEntry], str]:
    """Keep the cap: top-level definitions first, then the longest methods, then the longest constants.

    When the top-level definitions alone exceed the cap, consecutive ones are
    merged into groups that still cover the whole file, so the line ranges past
    the cap are never the part that disappears.
    """
    cap = READ_OUTLINE_MAX_ENTRIES
    if len(entries) <= cap:
        return entries, ""
    top = [entry for entry in entries if entry.rank == 0]
    if len(top) >= cap:
        groups = _grouped(top, cap - 1)
        return groups, f"({len(entries) - len(top)} methods and constants not listed; read a range to see them.)"
    room = cap - 1 - len(top)
    rest = sorted((entry for entry in entries if entry.rank > 0), key=lambda entry: (entry.rank, entry.start - entry.end))
    kept = sorted([*top, *rest[:room]], key=lambda entry: (entry.start, entry.depth))
    return kept, f"({len(entries) - len(kept)} shorter methods and constants not listed.)"


def _grouped(top: list[OutlineEntry], slots: int) -> list[OutlineEntry]:
    size = -(-len(top) // slots)
    groups = []
    for index in range(0, len(top), size):
        chunk = top[index:index + size]
        if len(chunk) == 1:
            groups.append(chunk[0])
            continue
        names = ", ".join(entry.label.split(" ")[-1] for entry in chunk)
        groups.append(OutlineEntry(chunk[0].start, max(entry.end for entry in chunk), 0, f"{len(chunk)} defs: {names}", 0))
    return groups


def _clip(line: str) -> str:
    return line if len(line) <= _MAX_LINE_CHARS else line[: _MAX_LINE_CHARS - 1] + "…"


def _shown_range(content: object) -> tuple[int, int] | None:
    """First and last line numbers of the window, from the ``N|`` prefixes ``read_file`` writes."""
    if not isinstance(content, str) or not content:
        return None
    lines = content.split("\n")
    first = _LINE_PREFIX.match(lines[0])
    last = next((match for match in (_LINE_PREFIX.match(line) for line in reversed(lines)) if match), None)
    if first is None or last is None:
        return None
    return int(first.group(1)), int(last.group(1))


def _line_count(text: str) -> int:
    """Lines as ``read_file`` reports them: newlines, plus one for an unterminated last line."""
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _first_line_matches(text: str, content: object, number: int) -> bool:
    """The window's first line equals the disk's line at that number (the host may clip a long line)."""
    if not isinstance(content, str):
        return False
    shown = _LINE_PREFIX.sub("", content.split("\n", 1)[0], count=1)
    lines = text.split("\n")
    if not 1 <= number <= len(lines):
        return False
    disk = lines[number - 1].rstrip("\r")
    if shown == disk:
        return True
    clipped = "... [truncated]"
    return shown.endswith(clipped) and disk.startswith(shown[: -len(clipped)])


def _resolve(path: str, task_id: str) -> str | None:
    """The host path ``read_file`` read for this task, or ``None`` when it is not a host path."""
    try:
        from tools.file_tools_paths import _resolve_path_for_task
    except ImportError:
        # Outside Hermes (tests, standalone): only an absolute path is unambiguous.
        return path if os.path.isabs(path) else None
    try:
        resolved = _resolve_path_for_task(path, str(task_id or "default"))
    except Exception as exc:  # noqa: BLE001 - the host resolver touches terminal config and live envs;
        # an outline is optional, so any failure skips it, counted by type in `read_outline_failures`.
        read_outline_failures[type(exc).__name__] += 1
        return None
    if not isinstance(resolved, Path):
        return None
    return str(resolved)


def _already_emitted(session: str, version: tuple[str, int, int]) -> bool:
    with _emitted_lock:
        return version in (_emitted.get(session) or {})


def _remember(session: str, version: tuple[str, int, int]) -> None:
    with _emitted_lock:
        files = _emitted.pop(session, None)
        if files is None:
            files = OrderedDict()
        files[version] = None
        while len(files) > MAX_TRACKED_FILES_PER_SESSION:
            _ = files.popitem(last=False)
        _emitted[session] = files
        while len(_emitted) > MAX_TRACKED_OUTLINE_SESSIONS:
            _ = _emitted.popitem(last=False)
