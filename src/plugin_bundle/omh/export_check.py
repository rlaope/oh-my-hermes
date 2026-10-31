"""Dangling exports: names a module the turn edited exports or imports that no longer exist.

A rename that updates a module's import line but not its ``__all__`` leaves a string naming a
function that is gone. No test that imports the new name notices, and a type checker reports
nothing by default, so the model stops with the stale entry in place. ``round_end_note`` reads each
``.py`` file the turn edited with the standard library's ``ast`` and names, as ``path:line`` rows:

- an ``__all__`` entry the module neither defines nor imports (nor, in a package
  ``__init__.py``, ships as a submodule);
- a top-level ``from module import name`` whose module is a workspace file that no longer binds
  ``name``. An absolute import is resolved only from the project root (the nearest ancestor holding
  a project marker) or a ``src/`` directly under it. When a same-named module also sits beside an
  importer that is not in a package (a script's or a pytest test module's own ``sys.path`` entry,
  or a namespace package's sibling), the name is stale only when both lack it. A standard-library
  name is never resolved.

Always on: it reads the edited files and the workspace modules their imports resolve to, never runs a
language server or a process, stops at a deadline sized like the impact check's share of the host
hook timeout, and says nothing unless such a name exists. A module whose names it cannot know is
skipped: a star import, a module-level ``__getattr__``, ``globals()`` / ``exec`` / ``vars()`` /
``locals()`` writes, ``setattr`` on a module, ``sys.modules[__name__]``, ``enum.global_enum`` or
``Enum._convert_``, a package that edits its own ``__path__``, or an ``__all__`` that is not a
literal list. So is any file that does not parse.
"""

from __future__ import annotations

import ast
import logging
import os
import sys
import time
import warnings
from pathlib import PurePath
from typing import Final

from .impact_check import host_hook_timeout
from .tools.lsp_nav_tool import workspace_relative

MAX_FILES: Final = 50
MAX_FILE_BYTES: Final = 512_000
MAX_NOTE_ROWS: Final = 10
_ANCESTOR_LIMIT: Final = 10
_PROJECT_MARKERS: Final = (".git", "pyproject.toml", "setup.py", "setup.cfg")
_INSTALL_ROOTS: Final = frozenset({"site-packages", "dist-packages"})
_COMPILED_SUFFIXES: Final = (".so", ".pyd", ".pyi", ".pyc")
# The check's share of `plugins.hook_callback_timeout` (2 s at the 30 s default), as impact_check
# sizes its own; past it the rows found so far are returned.
DEADLINE_SHARE: Final = 2.0 / 30.0
# Names every module has without binding them.
_IMPLICIT_NAMES: Final = frozenset({
    "__annotations__", "__builtins__", "__cached__", "__dict__", "__doc__", "__file__", "__loader__",
    "__name__", "__package__", "__path__", "__spec__",
})
# Bare calls that can write names into the module: `globals()[...]`, `exec(...)`.
_BARE_BINDERS: Final = frozenset({"exec", "globals"})
# Bare calls that write into the module's namespace only at module level (in a function they are
# that function's locals).
_MODULE_LEVEL_BINDERS: Final = frozenset({"locals", "vars"})
# Called by any spelling: `enum.global_enum` and `Enum._convert_` copy members into a module.
_ENUM_BINDERS: Final = frozenset({"_convert_", "global_enum"})

_LOG = logging.getLogger("omh.export_check")


class _Unknown(Exception):
    """The module binds names this reader cannot see; nothing is said about it."""


def round_end_note(session_id: str, changed_paths: object, reported: str = "", root: str | None = None) -> str:
    """``pre_verify`` attempt 0: the note naming dangling exports in this turn's edited files, or ``""``.

    ``reported`` is the impact note of the same message. Its ``path:line`` rows are left out here:
    an edited importer's stale ``from x import name`` is also a language-server error there, and
    one line is named once. ``root`` is the workspace root this turn's tools resolved against, the
    one the impact note's paths are relative to; without it a path is shown whole.
    """
    try:
        started = time.monotonic()
        deadline = started + host_hook_timeout() * DEADLINE_SHARE
        rows: list[tuple[str, int, str]] = []
        check = _Check(root, deadline)
        files = _edited_python_files(changed_paths)
        for path in files:
            if time.monotonic() >= deadline:
                check.timed_out = True
                break
            rows.extend(check.file_rows(path))
        named = _named_lines(reported)
        rows = [row for row in rows if f"{row[0]}:{row[1]}" not in named]
        if files:
            # `deadline=1`: the check stopped at its deadline and `rows` counts a partial result.
            _LOG.info("export_check round_end session=%s files=%d rows=%d deadline=%d ms=%d", session_id, len(files),
                      len(rows), check.timed_out, (time.monotonic() - started) * 1000)
        return format_note(rows)
    except Exception as exc:  # noqa: BLE001 - a broken check says nothing rather than fail the turn
        _LOG.warning("export_check round_end session=%s failed=%s", session_id, type(exc).__name__)
        return ""


def _named_lines(note: str) -> set[str]:
    """The ``path:line`` of each row of another ``path:line: message`` note."""
    named: set[str] = set()
    for line in note.splitlines() if isinstance(note, str) else ():
        location, _, rest = line.partition(": ")
        path, _, number = location.rpartition(":")
        if rest and path and number.isdigit():
            named.add(location)
    return named


def format_note(rows: list[tuple[str, int, str]]) -> str:
    """A header, at most ``MAX_NOTE_ROWS`` ``path:line: finding`` rows, an overflow count, one ask."""
    if not rows:
        return ""
    ordered = sorted(set(rows))
    shown = ordered[:MAX_NOTE_ROWS]
    lines = ["OMH export check: a file you edited names something that no longer exists:"]
    lines += [f"{path}:{line}: {finding}" for path, line, finding in shown]
    if len(shown) < len(ordered):
        lines.append(f"... and {len(ordered) - len(shown)} more")
    lines.append("Update or remove each stale name.")
    return "\n".join(lines)


def _edited_python_files(changed_paths: object) -> list[str]:
    if not isinstance(changed_paths, (list, tuple)):
        return []
    files = [os.path.realpath(item) for item in changed_paths
             if isinstance(item, str) and os.path.isabs(item) and item.endswith(".py")]
    return sorted({path for path in files if os.path.isfile(path)})[:MAX_FILES]


class _Check:
    """One round-end check: its display root, its deadline, and each file parsed once."""

    def __init__(self, root: str | None, deadline: float) -> None:
        self.root = os.path.realpath(root) if isinstance(root, str) and root else None
        self.deadline = deadline
        self.timed_out = False
        self.trees: dict[str, ast.Module | None] = {}

    def file_rows(self, path: str) -> list[tuple[str, int, str]]:
        tree = self.tree(path)
        if tree is None:
            return []
        shown = self.display(path)
        rows: list[tuple[str, int, str]] = []
        try:
            bound = _bound_names(tree)
            for name, line in _all_entries(tree):
                if name not in bound and not _is_submodule(path, name):
                    rows.append((shown, line, f"`__all__` lists `{name}`, which this module no longer defines or imports"))
        except _Unknown:
            pass
        for node in tree.body:
            if time.monotonic() >= self.deadline:
                self.timed_out = True
                break
            if isinstance(node, ast.ImportFrom):
                rows.extend((shown, line, finding) for line, finding in self.missing_imports(node, path))
        return rows

    def missing_imports(self, node: ast.ImportFrom, importer: str) -> list[tuple[int, str]]:
        """``(line, finding)`` per imported name the target no longer binds; each alias's own line,
        so a parenthesized import names the line pyright names."""
        targets = _module_files(node, importer)
        if not targets:
            return []
        known: list[tuple[str, set[str]]] = []
        for target in targets:
            tree = self.tree(target)
            if tree is None:
                return []
            try:
                known.append((target, _bound_names(tree)))
            except _Unknown:
                return []
        source = "." * node.level + (node.module or "")
        # Two candidates (a sibling and the root's module of one name) disagree on which file the
        # import reads, so a name is stale only when neither has it; the row names the first.
        return [(getattr(alias, "lineno", node.lineno),
                 f"`from {source} import {alias.name}`: {self.display(targets[0])} no longer defines `{alias.name}`")
                for alias in node.names
                if alias.name != "*" and all(alias.name not in bound and not _is_submodule(target, alias.name)
                                             for target, bound in known)]

    def tree(self, path: str) -> ast.Module | None:
        """``path`` parsed once per check; None when it is too large, unreadable or does not parse."""
        if path not in self.trees:
            self.trees[path] = None
            try:
                if os.path.getsize(path) <= MAX_FILE_BYTES:
                    with open(path, encoding="utf-8") as handle:
                        text = handle.read()
                    with warnings.catch_warnings():
                        # An invalid escape in the user's file is theirs to see, not this hook's.
                        warnings.simplefilter("ignore")
                        self.trees[path] = ast.parse(text)
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
                pass
        return self.trees[path]

    def display(self, path: str) -> str:
        """``path`` relative to the workspace root, with `/` separators, as the impact note shows it
        (`workspace_relative`: a path on another Windows drive is shown whole)."""
        if self.root is not None:
            return workspace_relative(path, self.root)
        return PurePath(path).as_posix()


def _module_files(node: ast.ImportFrom, importer: str) -> tuple[str, ...]:
    """The workspace ``.py`` files ``node`` may import names out of: none when it is not a workspace
    module, one, or a sibling of the importer and the root's module of the same name
    (`_sibling_module`), the import's reader depending on how the importer is run."""
    parts = node.module.split(".") if node.module else []
    if node.level:
        base = os.path.dirname(importer)
        for _ in range(node.level - 1):
            base = os.path.dirname(base)
        found = _existing_module(os.path.join(base, *parts)) if parts else _existing_module(base, package_only=True)
        return (found,) if found is not None else ()
    # An absolute import is resolved only where the project's own packages live: the project root
    # (the nearest ancestor holding a project marker) or a `src/` directly under it. Anything else --
    # an installed package that shares a directory's name, a plugin's own folder -- is not this
    # reader's to judge. A standard-library name is the standard library's.
    if not parts or parts[0] in sys.stdlib_module_names:
        return ()
    project = _project_root(importer)
    if project is None:
        return ()
    for base in (project, os.path.join(project, "src")):
        found = _existing_module(os.path.join(base, *parts))
        if found is not None:
            sibling = _sibling_module(importer, parts)
            return (sibling, found) if sibling is not None and sibling != found else (found,)
    return ()


def _sibling_module(importer: str, parts: list[str]) -> str | None:
    """The module ``parts`` names beside ``importer`` when its directory is not a package: Python puts
    a script's own directory first on ``sys.path``, and pytest's default ``prepend`` mode inserts a
    test module's directory when it holds no ``__init__.py``. So `from conftest import x` in
    `tests/test_a.py` reads `tests/conftest.py`, not the root's. But a directory without
    ``__init__.py`` is also a PEP 420 namespace package, whose modules import the root's
    (`src/ns/mod.py`'s `from config import KEY` reads `src/config.py`), so the sibling is a second
    candidate, never a replacement: a name is stale only when both lack it. It is consulted only
    once the root rule has found a module: on its own, a sibling named like an installed package
    (`scripts/setuptools.py`) is not this reader's to judge."""
    directory = os.path.dirname(importer)
    if os.path.isfile(os.path.join(directory, "__init__.py")):
        return None
    return _existing_module(os.path.join(directory, *parts))


def _project_root(path: str) -> str | None:
    """The nearest ancestor holding a project marker. An installed package's ``site-packages`` (or
    ``dist-packages``) is its own import root and stops the walk: a virtualenv inside a checkout
    does not import from the checkout."""
    directory = os.path.dirname(path)
    for _ in range(_ANCESTOR_LIMIT * 3):
        if os.path.basename(directory) in _INSTALL_ROOTS:
            return directory
        if any(os.path.exists(os.path.join(directory, marker)) for marker in _PROJECT_MARKERS):
            return directory
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent
    return None


def _existing_module(stem: str, package_only: bool = False) -> str | None:
    """A package's ``__init__.py`` before a same-named ``.py`` file, as Python's import system picks."""
    candidates = [os.path.join(stem, "__init__.py")] if package_only else [os.path.join(stem, "__init__.py"), stem + ".py"]
    return next((os.path.realpath(item) for item in candidates if os.path.isfile(item)), None)


def _is_submodule(module: str, name: str) -> bool:
    """A package ``__init__.py`` exports a submodule by name without importing it: a ``.py`` file, a
    package or namespace-package directory, or a compiled module (``name.*.so`` / ``.pyd`` / ``.pyc``,
    or its ``.pyi`` stub)."""
    if os.path.basename(module) != "__init__.py":
        return False
    package = os.path.dirname(module)
    if os.path.isfile(os.path.join(package, name + ".py")) or os.path.isdir(os.path.join(package, name)):
        return True
    try:
        entries = os.listdir(package)
    except OSError:
        return False
    return any(entry.startswith(name + ".") and entry.endswith(_COMPILED_SUFFIXES) for entry in entries)


def _all_entries(tree: ast.Module) -> list[tuple[str, int]]:
    """Every string ``__all__`` is given at module level, with its line; ``_Unknown`` when one is not a literal."""
    entries: list[tuple[str, int]] = []
    for node in _module_statements(tree.body):
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and any(_is_all(target) for target in node.targets):
            value = node.value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and _is_all(node.target):
            value = node.value
        elif (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
              and isinstance(node.value.func, ast.Attribute) and _is_all(node.value.func.value)):
            if node.value.func.attr == "append" and len(node.value.args) == 1:
                value = ast.List(elts=list(node.value.args))
            elif node.value.func.attr == "extend" and len(node.value.args) == 1:
                value = node.value.args[0]
            else:
                raise _Unknown
        else:
            continue
        if not isinstance(value, (ast.List, ast.Tuple)):
            raise _Unknown
        for item in value.elts:
            if not (isinstance(item, ast.Constant) and isinstance(item.value, str)):
                raise _Unknown
            entries.append((item.value, item.lineno))
    return entries


def _is_all(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "__all__"


def _module_statements(body: list[ast.stmt]) -> list[ast.stmt]:
    """Module-level statements, including those inside ``if`` / ``try`` / ``with`` / loop / ``match`` blocks."""
    found: list[ast.stmt] = []
    for node in body:
        found.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for field in ("body", "orelse", "finalbody"):
            nested = getattr(node, field, None)
            if isinstance(nested, list):
                found.extend(_module_statements(nested))
        for handler in getattr(node, "handlers", None) or ():
            found.extend(_module_statements(handler.body))
        for case in getattr(node, "cases", None) or ():
            found.extend(_module_statements(case.body))
    return found


def _bound_names(tree: ast.Module) -> set[str]:
    """Every name the module binds at module level; ``_Unknown`` when it can bind names unseen."""
    names: set[str] = set(_IMPLICIT_NAMES)
    imported = {alias.asname or alias.name.split(".", 1)[0]
                for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            names.update(node.names)
        elif isinstance(node, ast.Call) and _writes_module_names(node, imported):
            raise _Unknown
        elif isinstance(node, ast.ClassDef) and any(
                _dotted_leaf(item.func if isinstance(item, ast.Call) else item) in _ENUM_BINDERS
                for item in node.decorator_list):
            # `@enum.global_enum` copies the enum's members into the module.
            raise _Unknown
        elif isinstance(node, ast.Subscript) and _is_own_module(node):
            # `sys.modules[__name__]` hands this module to code that can set any name on it.
            raise _Unknown
        elif isinstance(node, ast.Name) and node.id == "__path__" and not isinstance(node.ctx, ast.Load):
            # A package that edits its own search path has submodules this reader cannot list.
            raise _Unknown
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "__path__":
            raise _Unknown
    for child in _module_scope_nodes(tree):
        if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and not child.args
                and child.func.id in _MODULE_LEVEL_BINDERS):
            # `vars()` / `locals()` at module level are the module's own namespace.
            raise _Unknown
    for node in _module_statements(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            continue
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                raise _Unknown
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, (ast.Try, ast.TryStar)):
            names.update(handler.name for handler in node.handlers if handler.name)
        elif type(node).__name__ == "TypeAlias":
            names.update(_target_names(node.name))  # type: ignore[attr-defined]
        for target in _statement_targets(node):
            names.update(_target_names(target))
        for child in ast.walk(node):
            if isinstance(child, ast.NamedExpr):
                names.update(_target_names(child.target))
            elif isinstance(child, (ast.MatchAs, ast.MatchStar)) and child.name:
                names.add(child.name)
            elif isinstance(child, ast.MatchMapping) and child.rest:
                names.add(child.rest)
    if "__getattr__" in names:
        # PEP 562: the module answers any name it is asked for.
        raise _Unknown
    return names


def _module_scope_nodes(tree: ast.Module) -> list[ast.AST]:
    """Every node evaluated in the module's own scope: not inside a function, class or lambda body."""
    found: list[ast.AST] = []
    pending: list[ast.AST] = list(tree.body)
    while pending:
        node = pending.pop()
        found.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        pending.extend(ast.iter_child_nodes(node))
    return found


def _dotted_leaf(node: ast.expr) -> str:
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""


def _writes_module_names(call: ast.Call, imported: set[str]) -> bool:
    """A call that can bind names in this module, or set them on a module it imported."""
    leaf = _dotted_leaf(call.func)
    if leaf in _ENUM_BINDERS:
        return True
    if not isinstance(call.func, ast.Name):
        return False  # `env.globals`, `self.exec(...)`: someone else's namespace
    if call.func.id in _BARE_BINDERS:
        return True
    if call.func.id == "setattr" and call.args:
        target = call.args[0]
        # `setattr(self, ...)` sets an attribute; `setattr(module, ...)` sets a module's name.
        # `setattr(sys.modules[__name__], ...)` needs no arm here: `_bound_names` gives up on the
        # `sys.modules[__name__]` subscript wherever it appears.
        return isinstance(target, ast.Name) and target.id in imported
    return False


def _is_own_module(node: ast.Subscript) -> bool:
    """``sys.modules[__name__]``."""
    value, key = node.value, node.slice
    return (isinstance(value, ast.Attribute) and value.attr == "modules" and isinstance(value.value, ast.Name)
            and value.value.id == "sys" and isinstance(key, ast.Name) and key.id == "__name__")


def _statement_targets(node: ast.stmt) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.For, ast.AsyncFor)):
        return [node.target]
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return [item.optional_vars for item in node.items if item.optional_vars is not None]
    return []


def _target_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for item in target.elts for name in _target_names(item)}
    return set()


__all__ = ["MAX_FILES", "MAX_NOTE_ROWS", "format_note", "round_end_note"]
