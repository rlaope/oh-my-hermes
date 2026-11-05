"""Python's argument-binding rules over ``ast``, for the round-end checks that judge a call site.

A leaf module: stdlib only, no other bundle import, so every check can import it without a cycle.
The caller check names the calls a signature change broke with it; the consistency trigger uses it
to settle calls that bind the same way before and after the change.

- ``shape(arguments)`` reads what a call must satisfy from a ``def``'s ``ast.arguments``.
- ``bind(shape, call)`` applies the binding rules to one ``ast.Call``: ``""`` when it binds, a short
  reason when it does not, and ``None`` when it cannot be proven either way (a ``*x`` or ``**x`` at
  the call).
- ``expected_to_fail(tree)`` finds the calls a test writes to fail: inside ``with ...raises(...)`` /
  ``assertRaises`` / ``assertRaisesRegex``, among a ``raises(...)`` call's arguments, or in a ``try``
  whose handlers catch ``TypeError``, ``Exception`` or ``BaseException`` (a bare ``except`` included).
"""

from __future__ import annotations

import ast
from typing import Final, NamedTuple

# Calls that expect an exception: `pytest.raises`, unittest's `assertRaises` / `assertRaisesRegex`, and
# a handler catching what a bad call raises.
_RAISES: Final = frozenset({"raises", "assertRaises", "assertRaisesRegex"})
_BROAD: Final = frozenset({"TypeError", "Exception", "BaseException"})


class Shape(NamedTuple):
    """What a call must satisfy: the parameters by kind, and which of them have a default."""

    positional_only: tuple[str, ...]
    positional: tuple[str, ...]  # positional-or-keyword
    defaulted: frozenset[str]    # positional parameters with a default
    var_positional: bool
    keyword_only: tuple[str, ...]
    required_keywords: frozenset[str]
    var_keyword: bool


def shape(arguments: ast.arguments) -> Shape:
    names = [arg.arg for arg in arguments.posonlyargs + arguments.args]
    defaulted = frozenset(names[len(names) - len(arguments.defaults):]) if arguments.defaults else frozenset()
    return Shape(
        positional_only=tuple(arg.arg for arg in arguments.posonlyargs),
        positional=tuple(arg.arg for arg in arguments.args),
        defaulted=defaulted,
        var_positional=arguments.vararg is not None,
        keyword_only=tuple(arg.arg for arg in arguments.kwonlyargs),
        required_keywords=frozenset(arg.arg for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults)
                                    if default is None),
        var_keyword=arguments.kwarg is not None,
    )


def bind(signature: Shape, call: ast.Call) -> str | None:
    """``""`` when ``call`` binds to ``signature``, the reason when it does not, ``None`` when unprovable."""
    if any(isinstance(arg, ast.Starred) for arg in call.args) or any(item.arg is None for item in call.keywords):
        return None
    slots = (*signature.positional_only, *signature.positional)
    given = len(call.args)
    if given > len(slots) and not signature.var_positional:
        return f"{given} positional arguments, but it takes {len(slots)}"
    bound = set(slots[:given])
    for item in call.keywords:
        name = item.arg
        if name in signature.positional_only:
            if signature.var_keyword:
                continue  # a positional-only name passed by keyword goes to `**kwargs`
            return f"positional-only `{name}` passed by keyword"
        if name in signature.positional or name in signature.keyword_only:
            if name in bound:
                return f"`{name}` given twice"
            bound.add(name)
        elif not signature.var_keyword:
            return f"unexpected keyword `{name}`"
    missing = [name for name in slots if name not in bound and name not in signature.defaulted]
    missing += [name for name in signature.keyword_only if name in signature.required_keywords and name not in bound]
    if missing:
        return "missing " + ", ".join(f"`{name}`" for name in missing)
    return ""


def expected_to_fail(tree: ast.Module) -> set[int]:
    """The ``id()`` of every call in ``tree`` that a test writes to fail."""
    guarded: set[int] = set()

    def mark(nodes: list[ast.AST]) -> None:
        for node in nodes:
            guarded.update(id(inner) for inner in ast.walk(node) if isinstance(inner, ast.Call))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _leaf(node.func) in _RAISES:
            mark([*node.args, *(item.value for item in node.keywords)])
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            if any(isinstance(item.context_expr, ast.Call) and _leaf(item.context_expr.func) in _RAISES
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
    return any(_leaf(part) in _BROAD for part in parts)


def _leaf(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


__all__ = ["Shape", "bind", "expected_to_fail", "shape"]
