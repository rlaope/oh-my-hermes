"""Whether the round-end consistency check can pay off for the Python a turn edited.

The check (`hooks/verify_hooks.ROUND_END_CHECKLIST`) costs one more round of the turn, and it pays
off only when something outside the edited files has to change with the edit. This module decides,
deterministically and from the disk alone, whether such a thing exists:

1. ``snapshot_before_edit`` (``pre_tool_call``, before any gate):
   - At the turn's first tool call of any kind, it records a bounded ``(mtime, size)`` index of the
     workspace's ``.py`` / ``.pyi`` files.
   - Before each ``patch`` / ``write_file`` of such a file, it keeps the file's text, once per turn
     (``""`` for a file that does not exist yet).
   - A file that changed since the index before its first snapshot (a ``sed``, ``execute_code`` or a
     delegated child's edit) is marked as having no turn-start text.
   - No index is taken for a session whose platform never gets the check (``note_turn_posture``, from
     ``pre_llm_call``), or for a root whose last index ran over budget within ``OVER_BUDGET_SECONDS``.
   - Residual: Hermes blocks a tool call whose ``pre_tool_call`` times out, so no call this hook
     missed that way runs, and an index missed at one call is taken at the next. The one gap is a
     host-internal exception in ``_dispatch_pre_tool_call_hooks``, which never blocks the call. If it
     hits the turn's first tool call and that tool changes a Python file, the index is taken at the
     next call, after the change, and the change is not seen.
2. ``round_end_trigger`` (``pre_verify``, attempt 0):
   - It re-indexes the workspace to find every Python file the turn changed, by any tool.
   - It diffs each kept snapshot against the disk, and finds the definitions the changed lines touch
     with stdlib ``ast``. Module and class level are read, including ``if`` / ``try`` / ``with``
     bodies.
   - It scans the other files for one of four signals:

     - ``copy``: a touched top-level definition is also defined at the top level of another file;
     - ``renamed``: a definition the edit removed is still named in another Python file or a config
       file (``.toml`` ``.cfg`` ``.ini`` ``.yaml`` ``.yml`` ``.json``);
     - ``signature``: a touched function's parameters or return annotation changed, or a class's
       constructor shape did (``__init__`` / ``__new__`` / ``__call__``, annotated fields, abstract
       methods), and the function or class is named in another file;
     - ``line_copy``: a non-trivial line the edit replaced or removed also appears elsewhere.

No signal means the check is skipped. Every other outcome fires it as it fired before this module:

- a changed source file that is not Python;
- a Python file changed this turn without a turn-start snapshot (``opaque_edit``);
- a changed file that does not parse;
- a non-trivial change that touches no definition, import or docstring (``unattributed``);
- an index or scan over its entry or time budget, or a root cached as over budget;
- a Python file or a directory under the root that is a symlink leaving it (``outside_link``);
- a session that had no index taken because its platform never gets the check, if it is asked anyway;
- an unedited Python file too large or unreadable to rule out;
- any error.

State is per process and per session, reset when a new turn id reaches ``pre_tool_call`` and consumed
at the turn's first stop. Nothing here raises into a hook.
"""

from __future__ import annotations

import ast
import difflib
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Final, NamedTuple

from . import lsp_nav
from .lsp_nav import LspNavError, inside
from .tools.lsp_nav_tool import _workspace_root, workspace_relative

PYTHON_SUFFIXES: Final = (".py", ".pyi")
# Files a `renamed` name can be load-bearing in without being Python: entry points, tool and CI
# configuration. Prose (.md, .rst, .txt) is left out: docs and changelogs name old APIs on purpose.
CONFIG_SUFFIXES: Final = (".toml", ".cfg", ".ini", ".yaml", ".yml", ".json")
MAX_SNAPSHOT_FILES: Final = 32
MAX_SNAPSHOT_BYTES: Final = 4_000_000
MAX_FILE_BYTES: Final = 512_000
# Directory entries visited per walk (files and directories alike, pruned trees not counted).
MAX_SCAN_ENTRIES: Final = 5000
# The turn-start index runs inside `pre_tool_call`; the verdict (re-index plus scan) inside `pre_verify`.
INDEX_SECONDS: Final = 0.5
SCAN_SECONDS: Final = 2.0
_DEADLINE_EVERY: Final = 64
# A root whose index ran over budget is not walked again for this long, in this process: later turns
# fire the check without paying for a walk that will not finish.
OVER_BUDGET_SECONDS: Final = 300.0
# Pruned like `lsp_nav` (VCS, virtualenvs, caches, hidden directories). Build outputs hold copies of
# the source that are not the source, but `build` and `dist` are also ordinary names for a scripts
# directory or a namespace subpackage, so each is pruned only on the shape a build tool leaves
# (`_build_output`): a `build` holding a setuptools/distutils work directory or no Python file in
# its first two levels (a CMake or JS build tree), a `dist` holding no top-level Python file.
_SKIP_DIRS: Final = lsp_nav._SKIP_DIRS
_BUILD_WORK_EXACT: Final = frozenset({"lib"})
_BUILD_WORK_PREFIXES: Final = ("lib.", "bdist.", "temp.", "__editable__")
# Subdirectories of a `build` listed when looking for Python one level down; past this many it is
# scanned as source rather than spend the index's time deciding.
_BUILD_PEEK_DIRS: Final = 64
# A replaced line shorter than this (after collapsing whitespace) is too common to call a copy.
MIN_COPY_LINE_CHARS: Final = 30
_MAX_SESSIONS: Final = 64
_EDIT_TOOLS: Final = frozenset({"patch", "write_file"})
_V4A_HEADER: Final = re.compile(r"^\*\*\*\s*(?:Update|Add|Delete)\s+File:\s*(.+)$", re.MULTILINE)
_V4A_MOVE: Final = re.compile(r"^\*\*\*\s*Move\s+File:\s*(.+?)\s*->\s*(.+)$", re.MULTILINE)
# Top-level names many unrelated modules define; one of them defined elsewhere is not a copy.
_COMMON_NAMES: Final = frozenset({"main", "log", "LOG", "logger", "LOGGER", "app"})
_CONSTRUCTOR_METHODS: Final = frozenset({"__init__", "__new__", "__call__"})
# Platforms `pre_verify` never gives the check (`verify_hooks._NO_CHECKLIST_PLATFORMS`, kept equal by a test).
NO_CHECK_PLATFORMS: Final = frozenset({"subagent"})
# Statement bodies read as if their definitions sat at the enclosing level.
_BLOCK_FIELDS: Final = ("body", "orelse", "finalbody")

_LOG = logging.getLogger("omh.consistency_trigger")
_lock = threading.Lock()
# root -> (monotonic time, (reason, detail)) of its last index that could not finish.
_over_budget: "OrderedDict[str, tuple[float, tuple[str, str]]]" = OrderedDict()
# session -> False when the session's platform never gets the check (`note_turn_posture`).
_posture: "OrderedDict[str, bool]" = OrderedDict()
# session -> {"turn", "root", "index": {realpath: (mtime_ns, size)} | None, "before": {realpath: str},
#             "opaque": set[str], "bytes": int}
_sessions: "OrderedDict[str, dict[str, Any]]" = OrderedDict()


class Verdict(NamedTuple):
    fire: bool
    reason: str
    detail: str = ""


class _Budget(Exception):
    """A walk ran past its entry count or deadline."""


class _OutsideLink(Exception):
    """A Python file or a directory under the root is a symlink that leaves it."""


def snapshot_before_edit(kwargs: dict[str, Any], tool_input: object) -> None:
    """``pre_tool_call``: index the workspace at the turn's first call; snapshot Python files before edits."""
    try:
        session_id = str(kwargs.get("session_id", "") or kwargs.get("task_id", "") or "")
        if not session_id:
            return
        state = _turn_state(session_id, kwargs)
        tool_name = kwargs.get("tool_name")
        if tool_name not in _EDIT_TOOLS or not isinstance(tool_input, dict):
            return
        root = state["root"]
        for requested in _edit_targets(str(tool_name), tool_input):
            if not requested.endswith(PYTHON_SUFFIXES):
                continue
            path = _resolve(requested, root)
            if path is None:
                continue
            with _lock:
                if path in state["before"] or path in state["opaque"]:
                    continue
            index = state["index"]
            if index is not None and _stat(path) != index.get(path):
                # Changed since the turn began, by something that was not a patch or write_file:
                # the text on disk now is not the turn's starting text.
                with _lock:
                    state["opaque"].add(path)
                continue
            text = _read(path, missing="")
            with _lock:
                if text is None or len(state["before"]) >= MAX_SNAPSHOT_FILES \
                        or state["bytes"] + len(text) > MAX_SNAPSHOT_BYTES:
                    continue
                if path not in state["before"]:
                    state["before"][path] = text
                    state["bytes"] += len(text)
    except Exception as exc:  # noqa: BLE001 - never fail the call; a missing snapshot fires the check
        _LOG.warning("consistency_trigger snapshot failed=%s", type(exc).__name__)


def round_end_trigger(session_id: str, code_paths: tuple[str, ...]) -> Verdict:
    """``pre_verify`` attempt 0: whether the consistency check should fire for this turn's changed source
    files (``code_paths``). Consumes the session's state."""
    with _lock:
        state = _sessions.pop(session_id, None) if session_id else None
    started = time.monotonic()
    try:
        verdict = _decide(state, code_paths, started + SCAN_SECONDS)
    except Exception as exc:  # noqa: BLE001 - an undecidable turn fires the check, as before this module
        verdict = Verdict(True, "error", type(exc).__name__)
    _LOG.info("consistency_trigger session=%s fire=%s reason=%s detail=%s ms=%d", session_id, verdict.fire,
              verdict.reason, verdict.detail, (time.monotonic() - started) * 1000)
    return verdict


def turn_root(session_id: object) -> str | None:
    """The workspace root this session's tools resolved against this turn, without consuming its state."""
    if not isinstance(session_id, str) or not session_id:
        return None
    with _lock:
        state = _sessions.get(session_id)
        return state["root"] if state is not None else None


def discard_snapshots(session_id: object) -> None:
    """Drop the session's state without reading it (the turn's first stop did not need a verdict)."""
    if isinstance(session_id, str) and session_id:
        with _lock:
            _sessions.pop(session_id, None)


def note_turn_posture(session_id: object, platform: object) -> None:
    """``pre_llm_call``: remember whether this session's platform can get the check at all, so
    ``pre_tool_call`` (which is given no platform) spends no index on one that cannot. Only the platform
    rule `pre_verify` itself applies is used (`verify_hooks._NO_CHECKLIST_PLATFORMS`); the coding posture
    is not re-derived here, because a wrong guess would quietly turn every verdict into a fail-open."""
    if not isinstance(session_id, str) or not session_id:
        return
    with _lock:
        _posture[session_id] = str(platform or "") not in NO_CHECK_PLATFORMS
        _posture.move_to_end(session_id)
        while len(_posture) > _MAX_SESSIONS:
            _posture.popitem(last=False)


def reset() -> None:
    """Forget every session's state and every cached over-budget root (tests)."""
    with _lock:
        _sessions.clear()
        _over_budget.clear()
        _posture.clear()


def _turn_state(session_id: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    turn = str(kwargs.get("turn_id", "") or "")
    with _lock:
        state = _sessions.get(session_id)
        if state is not None and state["turn"] == turn:
            return state
    root = os.path.realpath(_workspace_root(kwargs.get("task_id")) or os.getcwd())
    index: dict[str, tuple[int, int]] | None = None
    unindexed: tuple[str, str] = ("", "")
    with _lock:
        eligible = _posture.get(session_id, True)
        cached = _over_budget.get(root)
    if not eligible:
        unindexed = ("no_check_session", "")
    elif cached is not None and time.monotonic() - cached[0] < OVER_BUDGET_SECONDS:
        unindexed = cached[1]
    else:
        try:
            index = _index(root, time.monotonic() + INDEX_SECONDS)
        except (_Budget, _OutsideLink) as exc:
            unindexed = ("outside_link", str(exc)) if isinstance(exc, _OutsideLink) else ("index_budget", str(exc))
            with _lock:
                _over_budget[root] = (time.monotonic(), unindexed)
                _over_budget.move_to_end(root)
                while len(_over_budget) > _MAX_SESSIONS:
                    _over_budget.popitem(last=False)
    with _lock:
        state = _sessions.get(session_id)
        if state is not None and state["turn"] == turn:  # a parallel first call got here first
            return state
        state = {"turn": turn, "root": root, "index": index, "unindexed": unindexed, "before": {},
                 "opaque": set(), "bytes": 0}
        _sessions.pop(session_id, None)
        _sessions[session_id] = state
        while len(_sessions) > _MAX_SESSIONS:
            _sessions.popitem(last=False)
        return state


def _decide(state: dict[str, Any] | None, code_paths: tuple[str, ...], deadline: float) -> Verdict:
    if state is None:
        return Verdict(True, "no_snapshot")
    root = state["root"]
    reported: set[str] = set()
    for item in code_paths:
        path = os.path.realpath(item if os.path.isabs(item) else os.path.join(root, item))
        if not path.endswith(PYTHON_SUFFIXES):
            return Verdict(True, "not_python", os.path.basename(path))
        reported.add(path)
    if state["index"] is None:
        reason, detail = state["unindexed"]
        return Verdict(True, reason or "index_budget", detail)
    try:
        current = _index(root, deadline)
    except _Budget:
        return Verdict(True, "scan_budget", "index")
    except _OutsideLink as exc:
        return Verdict(True, "outside_link", str(exc))
    before_index = state["index"]
    changed = {path for path in set(before_index) | set(current) if before_index.get(path) != current.get(path)}
    changed |= reported
    needles = _Needles()
    for path in sorted(changed):
        if path in state["opaque"] or path not in state["before"]:
            return Verdict(True, "opaque_edit", _relative(path, root))
        after = _read(path, missing="")
        if after is None:
            return Verdict(True, "too_large", _relative(path, root))
        status = _collect(state["before"][path], after, needles)
        if status != "ok":
            return Verdict(True, status, _relative(path, root))
    if needles.empty():
        return Verdict(False, "nothing_changed")
    return _scan(root, changed, needles, deadline)


class _Needles:
    def __init__(self) -> None:
        self.defined: set[str] = set()   # copy: defined at the top level elsewhere
        self.renamed: set[str] = set()   # renamed: named elsewhere, Python or config
        self.signature: set[str] = set()  # signature: named elsewhere
        self.lines: set[str] = set()     # line_copy: appears as a line elsewhere

    def empty(self) -> bool:
        return not (self.defined or self.renamed or self.signature or self.lines)


def _collect(before: str, after: str, needles: _Needles) -> str:
    """Add what this file's edit could have a copy or a reference of elsewhere.

    Returns ``"ok"``, ``"parse_error"`` (either side does not parse) or ``"unattributed"`` (a
    non-trivial changed hunk touches no definition or import, so nothing here can be searched for).
    """
    before_tree, after_tree = _parse(before), _parse(after)
    if before_tree is None or after_tree is None:
        return "parse_error"
    old_lines, new_lines = before.splitlines(), after.splitlines()
    old_defs, new_defs = _definitions(before_tree), _definitions(after_tree)
    old_spans = [span for entries in old_defs.values() for span in entries] + _import_spans(before_tree)
    new_spans = [span for entries in new_defs.values() for span in entries] + _import_spans(after_tree)
    touched_lines: set[int] = set()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        lines = {i1, i1 + 1} if i1 == i2 else set(range(i1 + 1, i2 + 1))
        touched_lines |= lines
        # Attributed when the hunk's old lines sit in a definition or import before the edit, or its
        # new lines in one after it (a definition or import the edit added). A pure insertion is
        # judged by its new lines only: sitting next to a definition does not make it part of one.
        old_side = set() if i1 == i2 else lines
        if not _trivial(old_lines[i1:i2] + new_lines[j1:j2]) and not _covered(old_side, old_spans) \
                and not _covered(set(range(j1 + 1, j2 + 1)), new_spans):
            return "unattributed"
        for line in old_lines[i1:i2]:
            normalized = " ".join(line.split())
            if len(normalized) >= MIN_COPY_LINE_CHARS and not normalized.startswith(("import ", "from ")):
                needles.lines.add(normalized)
    for qualified, entries in old_defs.items():
        name = qualified.rsplit(".", 1)[-1]
        if qualified not in new_defs:
            if not _dunder(name):
                needles.renamed.add(name)
            continue
        if not any(touched_lines.intersection(range(start, end + 1)) for start, end, _node in entries):
            continue
        top = qualified.split(".", 1)[0]
        if not _dunder(top) and top not in _COMMON_NAMES and not top.startswith("test"):
            needles.defined.add(top)
        old_sigs = sorted(_signature(node) for _s, _e, node in entries if _is_function(node))
        new_sigs = sorted(_signature(node) for _s, _e, node in new_defs[qualified] if _is_function(node))
        if old_sigs != new_sigs and not _dunder(name):
            needles.signature.add(name)
    # A constructor's signature, a field or an abstract method changes what callers of the class
    # depend on; callers name the class, not `__init__`, so the class is what is searched for.
    for qualified, entries in old_defs.items():
        new_entries = new_defs.get(qualified)
        classes = [node for _s, _e, node in entries if isinstance(node, ast.ClassDef)]
        new_classes = [node for _s, _e, node in new_entries or () if isinstance(node, ast.ClassDef)]
        if classes and new_classes and sorted(map(_class_shape, classes)) != sorted(map(_class_shape, new_classes)):
            needles.signature.add(qualified.rsplit(".", 1)[-1])
    return "ok"


def _scan(root: str, edited: set[str], needles: _Needles, deadline: float) -> Verdict:
    defined = {name: re.compile(rf"^(?:async[ \t]+def|def|class)[ \t]+{re.escape(name)}\b|^{re.escape(name)}[ \t]*(?::[^=\n]*)?=(?!=)",
                                re.MULTILINE) for name in sorted(needles.defined)}
    named = {name: re.compile(rf"\b{re.escape(name)}\b") for name in sorted(needles.renamed | needles.signature)}
    renamed = {name: named[name] for name in sorted(needles.renamed)}
    suffixes = PYTHON_SUFFIXES + (CONFIG_SUFFIXES if renamed else ())
    try:
        for path in _walk(root, suffixes, deadline):
            if path in edited:
                continue
            where = workspace_relative(path, root)
            python = path.endswith(PYTHON_SUFFIXES)
            text = _read(path)
            if text is None:
                if python:  # cannot rule a reference out
                    return Verdict(True, "unreadable", where)
                continue  # an oversized config is a lockfile or a data dump, not a place a def is named
            if not python:
                for name, pattern in renamed.items():
                    if name in text and pattern.search(text):
                        return Verdict(True, "renamed", f"{name} in {where}")
                continue
            for name, pattern in defined.items():
                if name in text and pattern.search(text):
                    return Verdict(True, "copy", f"{name} in {where}")
            for name, pattern in named.items():
                if name in text and pattern.search(text):
                    reason = "renamed" if name in needles.renamed else "signature"
                    return Verdict(True, reason, f"{name} in {where}")
            if needles.lines:
                lines = {" ".join(line.split()) for line in text.splitlines()}
                if any(line in lines for line in needles.lines):
                    return Verdict(True, "line_copy", where)
    except _Budget as exc:
        return Verdict(True, "scan_budget", str(exc))
    except _OutsideLink as exc:
        return Verdict(True, "outside_link", str(exc))
    return Verdict(False, "no_copy_or_reference")


def _walk(root: str, suffixes: tuple[str, ...], deadline: float):
    """Realpaths of files under ``root`` with ``suffixes`` (sorted walk, pruned by `_SKIP_DIRS` and hidden
    directories). Raises `_Budget` past ``MAX_SCAN_ENTRIES`` entries visited or past ``deadline``, and
    `_OutsideLink` for a Python file or a directory that is a symlink leaving the root: what it points at
    is never read, and a reference could sit there."""
    visited = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if time.monotonic() >= deadline:
            raise _Budget("deadline")
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
                             and not _build_output(dirpath, d))
        for name in dirnames:
            linked = os.path.join(dirpath, name)
            if os.path.islink(linked) and not inside(os.path.realpath(linked), root):
                raise _OutsideLink(workspace_relative(linked, root))
        visited += len(dirnames)
        for filename in sorted(filenames):
            visited += 1
            if visited > MAX_SCAN_ENTRIES:
                raise _Budget("entries")
            if visited % _DEADLINE_EVERY == 0 and time.monotonic() >= deadline:
                raise _Budget("deadline")
            if not filename.endswith(suffixes):
                continue
            path = os.path.realpath(os.path.join(dirpath, filename))
            if not inside(path, root):
                if filename.endswith(PYTHON_SUFFIXES):
                    raise _OutsideLink(workspace_relative(os.path.join(dirpath, filename), root))
                continue
            if os.path.isfile(path):
                yield path


def _build_output(dirpath: str, name: str) -> bool:
    """A `build` or `dist` directory a build tool wrote, not source. A `build` is output when it holds
    a `lib`, `lib.*`, `bdist.*`, `temp.*` or `__editable__*` directory (setuptools and distutils work
    directories), or no Python file in its first two levels (a CMake or JS build tree); a `dist` when
    it holds no top-level `.py` file (wheels, sdists, bundles). Anything else under those names (a
    scripts directory, a namespace subpackage) is scanned."""
    if name not in ("build", "dist"):
        return False
    directory = os.path.join(dirpath, name)
    children = _children(directory)
    if children is None:
        return False
    if name == "dist":
        return not any(child.endswith(PYTHON_SUFFIXES) and not is_dir for child, is_dir in children)
    if any(child == "__init__.py" for child, _ in children):
        return False
    if any(is_dir and (child in _BUILD_WORK_EXACT or child.startswith(_BUILD_WORK_PREFIXES))
           for child, is_dir in children):
        return True
    if any(child.endswith(PYTHON_SUFFIXES) and not is_dir for child, is_dir in children):
        return False
    subdirectories = [child for child, is_dir in children if is_dir]
    if len(subdirectories) > _BUILD_PEEK_DIRS:
        return False
    for child in subdirectories:
        grandchildren = _children(os.path.join(directory, child))
        if grandchildren is None or any(item.endswith(PYTHON_SUFFIXES) and not is_dir
                                        for item, is_dir in grandchildren):
            return False
    return True


def _children(directory: str) -> list[tuple[str, bool]] | None:
    """``(name, is_dir)`` per entry of ``directory``, or None when it cannot be listed."""
    try:
        with os.scandir(directory) as entries:
            return [(entry.name, entry.is_dir()) for entry in entries]
    except OSError:
        return None


def _index(root: str, deadline: float) -> dict[str, tuple[int, int]]:
    return {path: stat for path in _walk(root, PYTHON_SUFFIXES, deadline) if (stat := _stat(path)) is not None}


def _stat(path: str) -> tuple[int, int] | None:
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def _definitions(tree: ast.AST) -> dict[str, list[tuple[int, int, ast.AST]]]:
    """Module- and class-level functions, classes and assigned names, including those inside ``if`` /
    ``try`` / ``with`` bodies: qualified name -> every (first line, last line, node) defining it."""
    found: dict[str, list[tuple[int, int, ast.AST]]] = {}

    def visit(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            start = min([node.lineno] + [item.lineno for item in getattr(node, "decorator_list", [])])
            end = getattr(node, "end_lineno", None) or node.lineno
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.setdefault(prefix + node.name, []).append((start, end, node))
                if isinstance(node, ast.ClassDef):
                    visit(node.body, prefix + node.name + ".")
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for name in (item for target in targets for item in _target_names(target)):
                    found.setdefault(prefix + name, []).append((start, end, node))
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.AsyncWith)) or type(node).__name__ == "TryStar":
                for field in _BLOCK_FIELDS:
                    visit(getattr(node, field, None) or [], prefix)
                for handler in getattr(node, "handlers", None) or []:
                    visit(handler.body, prefix)

    visit(getattr(tree, "body", []), "")
    return found


def _target_names(target: ast.AST) -> list[str]:
    """Every name an assignment target binds: plain names, starred names, and nested tuples or lists.
    Attribute and subscript targets bind no module- or class-level name."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for item in target.elts for name in _target_names(item)]
    return []


def _import_spans(tree: ast.AST) -> list[tuple[int, int, ast.AST]]:
    """Imports and docstrings (the first string statement of the module, a class or a function): a
    change there is attributed, and nothing in it is searched for."""
    nodes: list[ast.AST] = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    for owner in [tree] + [node for node in ast.walk(tree)
                           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]:
        body = getattr(owner, "body", None) or []
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            nodes.append(body[0])
    return [(node.lineno, getattr(node, "end_lineno", None) or node.lineno, node) for node in nodes]


def _class_shape(node: ast.ClassDef) -> str:
    """What a caller constructing or subclassing ``node`` depends on: constructor signatures, annotated
    fields (with whether each has a default), and abstract methods."""
    constructors = sorted(f"{item.name}:{_signature(item)}" for item in node.body
                          if _is_function(item) and item.name in _CONSTRUCTOR_METHODS)
    fields = [f"{item.target.id}={item.value is not None}" for item in node.body
              if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)]
    abstract = sorted(item.name for item in node.body if _is_function(item) and any(
        (isinstance(d, ast.Name) and d.id == "abstractmethod")
        or (isinstance(d, ast.Attribute) and d.attr == "abstractmethod") for d in item.decorator_list))
    return f"{constructors}|{fields}|{abstract}"


def _is_function(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))


def _signature(node: ast.AST) -> str:
    args = getattr(node, "args", None)
    returns = getattr(node, "returns", None)
    return f"{type(node).__name__}|{ast.dump(args) if args else ''}|{ast.dump(returns) if returns else ''}"


def _covered(lines: set[int], spans: list[tuple[int, int, ast.AST]]) -> bool:
    return any(start <= line <= end for line in lines for start, end, _node in spans)


def _trivial(lines: list[str]) -> bool:
    """Blank and comment-only lines: nothing a copy or a caller could depend on."""
    return all(not line.strip() or line.strip().startswith("#") for line in lines)


def _dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def _relative(path: str, root: str) -> str:
    """A verdict's path: workspace-relative with `/` on every platform, or the bare name outside it."""
    return workspace_relative(path, root) if inside(path, root) else os.path.basename(path)


def _edit_targets(tool_name: str, args: dict[str, Any]) -> list[str]:
    if tool_name == "patch" and args.get("mode") == "patch":
        body = args.get("patch")
        if not isinstance(body, str):
            return []
        paths = [match.group(1).strip() for match in _V4A_HEADER.finditer(body)]
        for match in _V4A_MOVE.finditer(body):
            paths += [match.group(1).strip(), match.group(2).strip()]
        return paths
    path = args.get("path")
    return [path] if isinstance(path, str) and path else []


def _resolve(requested: str, root: str) -> str | None:
    try:
        return lsp_nav.resolve_path(requested, root)
    except LspNavError:
        return None


def _read(path: str, missing: str | None = None) -> str | None:
    """The file's text; ``missing`` when it does not exist; None when it is too large or unreadable."""
    try:
        if not os.path.isfile(path):
            return missing if not os.path.exists(path) else None
        with open(path, "rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_FILE_BYTES:
        return None
    return data.decode("utf-8", errors="replace")


def _parse(text: str) -> ast.AST | None:
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


__all__ = ["Verdict", "discard_snapshots", "note_turn_posture", "reset", "round_end_trigger", "snapshot_before_edit",
           "turn_root"]
