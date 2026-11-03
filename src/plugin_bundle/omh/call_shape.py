"""Python's argument-binding rules over ``ast``, for the round-end checks that judge a call site.

A leaf module: stdlib only, no other bundle import, so every check can import it without a cycle.

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
    if any(isinstance(arg, ast.Starred) for arg in call.args) or any(kw.arg is None for kw in call.keywords):
        return None
    ordered = signature.positional_only + signature.positional
    if len(call.args) > len(ordered) and not signature.var_positional:
        return f"takes {len(ordered)} positional arguments but {len(call.args)} were given"
    bound = set(ordered[:len(call.args)])
    for keyword in call.keywords:
        name = keyword.arg or ""
        if name in signature.positional_only and signature.var_keyword:
            continue  # a positional-only name passed by keyword goes to `**kwargs`
        if name in bound:
            return f"got multiple values for argument '{name}'"
        if name in signature.positional or name in signature.keyword_only:
            bound.add(name)
        elif not signature.var_keyword:
            if name in signature.positional_only:
                return f"got a positional-only argument passed as keyword: '{name}'"
            return f"got an unexpected keyword argument '{name}'"
    missing = [name for name in ordered if name not in bound and name not in signature.defaulted]
    if missing:
        return f"missing required positional argument '{missing[0]}'"
    missing = sorted(signature.required_keywords - bound)
    if missing:
        return f"missing required keyword-only argument '{missing[0]}'"
    return ""


def expected_to_fail(tree: ast.Module) -> set[int]:
    """The ``id()`` of every call in ``tree`` that a test writes to fail."""
    guarded: set[int] = set()

    def mark(nodes: list[ast.AST]) -> None:
        for node in nodes:
            guarded.update(id(item) for item in ast.walk(node) if isinstance(item, ast.Call))

    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith)) and any(
                _raises_call(item.context_expr) for item in node.items):
            mark(list(node.body))
        elif isinstance(node, ast.Call) and _raises_call(node):
            mark(list(node.args[1:]) + [kw.value for kw in node.keywords])
        elif isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
            if any(_catches_type_error(handler) for handler in getattr(node, "handlers", [])):
                mark(list(node.body))
    return guarded


def _raises_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
    return name in _RAISES


def _catches_type_error(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    caught = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any((item.attr if isinstance(item, ast.Attribute) else getattr(item, "id", "")) in _BROAD
               for item in caught)


__all__ = ["Shape", "bind", "expected_to_fail", "shape"]
