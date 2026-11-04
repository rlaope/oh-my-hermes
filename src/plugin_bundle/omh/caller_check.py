"""Call sites a turn's signature change left broken, found with the standard library's ``ast``.

A model that adds a required parameter or renames a keyword updates the callers its search finds
and stops. The one it misses is the caller that reaches the function under another name, most
often through a package re-export (``from .pricing import compute_fee as fee`` in ``__init__.py``,
``from pkg import fee`` in the caller). The round-end consistency check fires on such an edit but
names no line, and the language-server impact check that would name it is opt-in. In the
2026-11-02 and 2026-10-31 head-to-heads every OMH ``I-SIGNATURE`` failure was that caller.

``round_end_note`` (``pre_verify``, attempt 0) names a call only when it can prove it no longer
binds:

- the function is a module-level ``def`` of a file this turn changed that has a turn-start snapshot
  (``consistency_trigger.turn_snapshots``), defined exactly once and undecorated both before and
  after the edit, and nothing else in its module binds its name;
- its parameters changed;
- the call is in the edited module or in a workspace file that imports it, found by
  ``impact_check.find_importers`` (which follows a package ``__init__`` re-export one level), and
  reaches the function through a name that file binds exactly once, by that import or ``def``:
  ``f(...)``, ``alias(...)``, ``module.f(...)``, ``pkg.reexported(...)``;
- the call has no ``*args`` or ``**kwargs`` of its own, and binds under the turn-start signature
  but not under the current one (Python's own argument-binding rules: positional count, keyword
  names, positional-only names, required parameters, a value given twice);
- the call is not one written to fail: it sits in no ``try`` body whose handlers catch ``TypeError``
  (or ``Exception``, ``BaseException``, or everything), no ``with`` block over a ``raises`` /
  ``assertRaises`` / ``assertRaisesRegex`` call, and no argument of such a call. A test that pins
  "the old keyword is rejected" calls the function the old way on purpose.

Everything it cannot prove is silent: a dynamic call, a star import, a name bound twice, a
decorated or conditional definition, a file that does not parse, an unresolved import. It runs no
language server and no process, stops at a deadline sized like the export check's share of the host
hook timeout, and returns the rows found by then. Nothing here raises into a hook.
"""

from __future__ import annotations

import ast
import logging
import os
import time
from typing import Final, NamedTuple

from .consistency_trigger import turn_snapshots
from .impact_check import _imports_from as imports_from
from .impact_check import find_importers, host_hook_timeout, module_names
from .tools.lsp_nav_tool import workspace_relative

MAX_FUNCTIONS: Final = 8
MAX_IMPORTERS: Final = 30
MAX_FILE_BYTES: Final = 512_000
MAX_NOTE_ROWS: Final = 10
MAX_SOURCE_CHARS: Final = 120
MAX_SIGNATURE_CHARS: Final = 160
# The check's share of `plugins.hook_callback_timeout` (2 s at the 30 s default), as the export
# check sizes its own; past it the rows found so far are returned.
DEADLINE_SHARE: Final = 2.0 / 30.0

# Calls that expect an exception: `pytest.raises`, unittest's `assertRaises` / `assertRaisesRegex`, and
# a handler catching what a bad call raises.
_RAISES_CALLS: Final = frozenset({"raises", "assertRaises", "assertRaisesRegex"})
_CATCHES_TYPE_ERROR: Final = frozenset({"TypeError", "Exception", "BaseException"})

_LOG = logging.getLogger("omh.caller_check")


class _Shape(NamedTuple):
    """What a call must satisfy: the parameters by kind, and which of them have a default."""

    positional_only: tuple[str, ...]
    positional: tuple[str, ...]  # positional-or-keyword
    defaulted: frozenset[str]    # positional parameters with a default
    var_positional: bool
    keyword_only: tuple[str, ...]
    required_keywords: frozenset[str]
    var_keyword: bool


class _Changed(NamedTuple):
    path: str
    name: str
    old: _Shape
    new: _Shape
    rendered: str  # `name(params)` as the module now defines it


def round_end_note(session_id: str, root: str | None, reported: str = "") -> str:
    """``pre_verify`` attempt 0: the note naming calls this turn's signature change broke, or ``""``.

    ``reported`` holds the notes already in the same message; a ``path:line`` one of them names is not
    named again. ``root`` is the workspace root this turn's tools resolved against.
    """
    try:
        if not isinstance(root, str) or not root:
            return ""
        started = time.monotonic()
        deadline = started + host_hook_timeout() * DEADLINE_SHARE
        changed = _changed_functions(turn_snapshots(session_id))
        rows: list[tuple[str, int, str]] = []
        files = 0
        for path in sorted({item.path for item in changed}):
            if time.monotonic() >= deadline:
                break
            functions = {item.name: item for item in changed if item.path == path}
            callers = [path, *find_importers(root, path, MAX_IMPORTERS, deadline)]
            files += len(callers)
            exports = _package_exports(callers, path, root, set(functions))
            for caller in callers:
                if time.monotonic() >= deadline:
                    break
                rows.extend(_broken_calls(caller, path, root, functions, exports))
        named = _named_lines(reported)
        rows = [row for row in rows if f"{row[0]}:{row[1]}" not in named]
        # Logged at every first stop, so a stop with nothing to check is told apart from a bundle without it.
        _LOG.info("caller_check round_end session=%s functions=%d files=%d rows=%d deadline=%d ms=%d", session_id,
                  len(changed), files, len(rows), time.monotonic() >= deadline, (time.monotonic() - started) * 1000)
        return format_note(rows)
    except Exception as exc:  # noqa: BLE001 - a broken check says nothing rather than fail the turn
        _LOG.warning("caller_check round_end session=%s failed=%s", session_id, type(exc).__name__)
        return ""


def format_note(rows: list[tuple[str, int, str]]) -> str:
    """A header, at most ``MAX_NOTE_ROWS`` ``path:line: finding`` rows, an overflow count, one ask."""
    if not rows:
        return ""
    ordered = sorted(set(rows))
    shown = ordered[:MAX_NOTE_ROWS]
    lines = ["OMH caller check: a function you changed this turn is still called the old way, and these calls "
             "now fail:"]
    lines += [f"{path}:{line}: {finding}" for path, line, finding in shown]
    if len(shown) < len(ordered):
        lines.append(f"... and {len(ordered) - len(shown)} more")
    lines.append("Update each call to the new signature.")
    return "\n".join(lines)


def _named_lines(note: str) -> set[str]:
    """The ``path:line`` of each row of the other notes."""
    named: set[str] = set()
    for line in note.splitlines() if isinstance(note, str) else ():
        location, _, rest = line.partition(": ")
        path, _, number = location.rpartition(":")
        if rest and path and number.isdigit():
            named.add(location)
    return named


def _changed_functions(snapshots: dict[str, str]) -> list[_Changed]:
    """Module-level functions whose parameters this turn changed, in the files it has snapshots of."""
    changed: list[_Changed] = []
    for path, before in sorted(snapshots.items()):
        if not path.endswith(".py") or not before:
            continue
        after = _read(path)
        if after is None or after == before:
            continue
        old_tree, new_tree = _parse(before), _parse(after)
        if old_tree is None or new_tree is None:
            continue
        old_defs, new_defs = _sole_functions(old_tree), _sole_functions(new_tree)
        for name in sorted(set(old_defs) & set(new_defs)):
            old, new = _shape(old_defs[name].args), _shape(new_defs[name].args)
            if old != new:
                rendered = f"{name}({ast.unparse(new_defs[name].args)})"
                if len(rendered) > MAX_SIGNATURE_CHARS:
                    rendered = rendered[: MAX_SIGNATURE_CHARS - 3] + "..."
                changed.append(_Changed(path, name, old, new, rendered))
                if len(changed) >= MAX_FUNCTIONS:
                    return changed
    return changed


def _sole_functions(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Undecorated top-level ``def`` statements whose name nothing else in the module binds."""
    if _has_star_import(tree):
        return {}
    counts = _binding_counts(tree)
    found: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.decorator_list \
                and counts.get(node.name) == 1:
            found[node.name] = node
    return found


def _shape(arguments: ast.arguments) -> _Shape:
    positional = [arg.arg for arg in (*arguments.posonlyargs, *arguments.args)]
    defaulted = frozenset(positional[len(positional) - len(arguments.defaults):]) if arguments.defaults else frozenset()
    required = frozenset(arg.arg for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults)
                         if default is None)
    return _Shape(tuple(arg.arg for arg in arguments.posonlyargs), tuple(arg.arg for arg in arguments.args),
                  defaulted, arguments.vararg is not None, tuple(arg.arg for arg in arguments.kwonlyargs), required,
                  arguments.kwarg is not None)


def _bind(shape: _Shape, call: ast.Call) -> str | None:
    """Why ``call`` cannot bind to ``shape`` (``""`` when it binds); None when that cannot be known."""
    if any(isinstance(arg, ast.Starred) for arg in call.args) or any(item.arg is None for item in call.keywords):
        return None
    slots = (*shape.positional_only, *shape.positional)
    given = len(call.args)
    if given > len(slots) and not shape.var_positional:
        return f"{given} positional arguments, but it takes {len(slots)}"
    bound = set(slots[:given])
    for item in call.keywords:
        name = item.arg
        if name in shape.positional_only:
            if shape.var_keyword:
                continue
            return f"positional-only `{name}` passed by keyword"
        if name in shape.positional or name in shape.keyword_only:
            if name in bound:
                return f"`{name}` given twice"
            bound.add(name)
        elif not shape.var_keyword:
            return f"unexpected keyword `{name}`"
    missing = [name for name in slots if name not in bound and name not in shape.defaulted]
    missing += [name for name in shape.keyword_only if name in shape.required_keywords and name not in bound]
    if missing:
        return "missing " + ", ".join(f"`{name}`" for name in missing)
    return ""


def _package_exports(callers: list[str], target: str, root: str, functions: set[str]) -> dict[str, dict[str, str]]:
    """``__init__.py`` -> {exported name: function} for each package among ``callers`` re-exporting one."""
    names = module_names(target, root)
    exports: dict[str, dict[str, str]] = {}
    for path in callers:
        if os.path.basename(path) != "__init__.py" or path == target:
            continue
        text = _read(path)
        tree = _parse(text) if text is not None else None
        if tree is None or _has_star_import(tree):
            continue
        counts = _binding_counts(tree)
        bound: dict[str, str] = {}
        for node in _module_imports(tree):
            if isinstance(node, ast.ImportFrom) and imports_from(node, path, target, names) == "module":
                for alias in node.names:
                    local = alias.asname or alias.name
                    if alias.name in functions and counts.get(local) == 1:
                        bound[local] = alias.name
        if bound:
            exports[path] = bound
    return exports


def _broken_calls(caller: str, target: str, root: str, functions: dict[str, _Changed],
                  exports: dict[str, dict[str, str]]) -> list[tuple[str, int, str]]:
    text = _read(caller)
    tree = _parse(text) if text is not None else None
    if tree is None or text is None or _has_star_import(tree):
        return []
    counts = _binding_counts(tree)
    direct, modules = _callees(tree, caller, target, root, functions, exports)
    if caller == target:
        direct.update({name: name for name in functions})
    direct = {local: name for local, name in direct.items() if counts.get(local) == 1}
    modules = {chain: members for chain, members in modules.items() if counts.get(chain.split(".", 1)[0]) == 1}
    if not direct and not modules:
        return []
    assigned = _assigned_attributes(tree)
    expected_to_fail = _expected_to_fail(tree)
    where = workspace_relative(caller, root)
    rows: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in expected_to_fail:
            continue
        name = ""
        if isinstance(node.func, ast.Name):
            name = direct.get(node.func.id, "")
        elif isinstance(node.func, ast.Attribute):
            chain = _dotted(node.func.value)
            if chain and (chain, node.func.attr) not in assigned:
                name = modules.get(chain, {}).get(node.func.attr, "")
        if not name:
            continue
        changed = functions[name]
        before, now = _bind(changed.old, node), _bind(changed.new, node)
        if before == "" and now:
            source = ast.get_source_segment(text, node) or name
            source = " ".join(source.split())
            if len(source) > MAX_SOURCE_CHARS:
                source = source[: MAX_SOURCE_CHARS - 3] + "..."
            relative = workspace_relative(changed.path, root)
            rows.append((where, node.lineno, f"`{source}`: {now}; it is now `{changed.rendered}` in {relative}"))
    return rows


def _callees(tree: ast.Module, caller: str, target: str, root: str, functions: dict[str, _Changed],
             exports: dict[str, dict[str, str]]) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """The names a call to a changed function can be spelled with in ``caller``.

    Returns ({local name: function}, {dotted module expression: {attribute: function}}), from the
    module-level imports of ``target`` itself and of each package re-exporting from it.
    """
    direct: dict[str, str] = {}
    modules: dict[str, dict[str, str]] = {}
    sources = [(target, {name: name for name in functions})]
    sources += [(package, bound) for package, bound in sorted(exports.items()) if package != caller]
    for source, members in sources:
        names = module_names(source, root)
        for node in _module_imports(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in names:
                        modules[alias.asname or alias.name] = members
            elif isinstance(node, ast.ImportFrom):
                kind = imports_from(node, caller, source, names)
                for alias in node.names:
                    local = alias.asname or alias.name
                    if kind == "module" and alias.name in members:
                        direct[local] = members[alias.name]
                    elif kind == "submodule" and _names_module(node, alias, caller, source, names):
                        modules[local] = members
    return direct, modules


def _names_module(node: ast.ImportFrom, alias: ast.alias, caller: str, source: str, names: set[str]) -> bool:
    """Whether ``alias`` in ``from pkg import x`` is ``source`` itself rather than another member."""
    probe = ast.ImportFrom(module=node.module, names=[alias], level=node.level)
    return imports_from(probe, caller, source, names) == "submodule"


def _module_imports(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    """Imports that bind at module level: the module body and its ``if`` / ``try`` / ``with`` blocks."""
    found: list[ast.Import | ast.ImportFrom] = []
    pending: list[ast.stmt] = list(tree.body)
    while pending:
        node = pending.pop(0)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append(node)
        elif isinstance(node, (ast.If, ast.Try, ast.With)) or type(node).__name__ == "TryStar":
            for field in ("body", "orelse", "finalbody"):
                pending.extend(getattr(node, field, None) or ())
            for handler in getattr(node, "handlers", None) or ():
                pending.extend(handler.body)
    return found


def _binding_counts(tree: ast.Module) -> dict[str, int]:
    """How many places in the file bind each name, in any scope. A ``global`` / ``nonlocal`` counts twice,
    so a name it touches is never taken as bound once."""
    counts: dict[str, int] = {}

    def add(name: str | None, weight: int = 1) -> None:
        if name:
            counts[name] = counts.get(name, 0) + weight

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            add(node.name)
        elif isinstance(node, ast.arg):
            add(node.arg)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                add(alias.asname or alias.name)
        elif isinstance(node, ast.ExceptHandler):
            add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                add(name, 2)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)):
            add(node.name)
        elif isinstance(node, ast.MatchMapping):
            add(node.rest)
    return counts


def _expected_to_fail(tree: ast.Module) -> set[int]:
    """``id()`` of every call written to raise: inside a ``try`` that catches ``TypeError`` or wider, a
    ``with`` over a ``raises`` call, or an argument of a ``raises`` call."""
    guarded: set[int] = set()

    def mark(nodes: list[ast.AST]) -> None:
        for node in nodes:
            guarded.update(id(inner) for inner in ast.walk(node) if isinstance(inner, ast.Call))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _leaf(node.func) in _RAISES_CALLS:
            mark([*node.args, *(item.value for item in node.keywords)])
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            if any(isinstance(item.context_expr, ast.Call) and _leaf(item.context_expr.func) in _RAISES_CALLS
                   for item in node.items):
                mark(list(node.body))
        elif isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
            if any(_catches_type_error(handler.type) for handler in node.handlers):
                mark(list(node.body))
    return guarded


def _catches_type_error(caught: ast.expr | None) -> bool:
    if caught is None:
        return True
    parts = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return any(_leaf(part) in _CATCHES_TYPE_ERROR for part in parts)


def _leaf(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def _assigned_attributes(tree: ast.Module) -> set[tuple[str, str]]:
    """``(module expression, attribute)`` pairs the file assigns or deletes (``pricing.compute_fee = ...``)."""
    found: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            chain = _dotted(node.value)
            if chain:
                found.add((chain, node.attr))
    return found


def _dotted(node: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ""
    parts.append(node.id)
    return ".".join(reversed(parts))


def _has_star_import(tree: ast.Module) -> bool:
    return any(isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names)
               for node in ast.walk(tree))


def _read(path: str) -> str | None:
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def _parse(text: str) -> ast.Module | None:
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None
