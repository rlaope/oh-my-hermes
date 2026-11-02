"""Changed test expectations in a turn whose request asked for behaviour to stay the same.

A model that changes behaviour by mistake can make the old test pass again by rewriting what the
test expects, and then stop on a green run. The round-end consistency check asks about copies and
call sites, not about this, and in the 2026-10-31 head-to-head Haiku 4.5 did exactly that on every
failed ``I-KWARG`` run: the task said what ``fetch`` returns stays the same, and the model renamed a
key in the returned dict and the same key in ``tests/test_http_client.py``.

``round_end_note`` (``pre_verify``, attempt 0) names such an edit, and only when all of these hold:

- this turn's request asked for behaviour to stay the same (``note_request``, from ``pre_llm_call``:
  a closed phrase list, `_KEEPS_BEHAVIOUR`, in a clause `_SCOPED_KEEP` does not narrow);
- the request neither names the test file (its path, file name or module name) or the test, nor
  asks to update a test or states a result the code must now give (`_ASKS_TEST_EDIT`, unless a
  negation right before it takes it back): an edit the task asked for is not questioned;
- the turn also changed a Python file that is not a test;
- a test file that existed at the turn's start lost an expected value: a literal constant inside an
  ``assert`` statement or the compared arguments of a unittest ``self.assert*`` call is gone, counted
  over every test file the turn changed (so an assertion moved between test files loses nothing). A
  subscript key is how a value is reached, not an expected value, and a unittest message is not one
  either. A test that only gained assertions, a renamed test, or a renamed identifier inside an
  assertion loses none.

The turn-start text is the snapshot ``consistency_trigger`` keeps; a test file changed without one is
not judged. Only the facts above are kept from the request, never its text. Nothing here raises into a
hook.
"""

from __future__ import annotations

import ast
import logging
import os
import re
import threading
from collections import Counter, OrderedDict
from typing import Final, NamedTuple

from .consistency_trigger import turn_snapshots

MAX_NOTE_ROWS: Final = 3
MAX_SOURCE_CHARS: Final = 160
MAX_NAMED_TOKENS: Final = 64
MAX_FILE_BYTES: Final = 512_000
_MAX_SESSIONS: Final = 64
# The request asks for behaviour to be kept, in so many words: a keep phrase, a refusal to change the
# tests, or a result that must stay what it is ("must return the same dict as before").
_KEEPS_BEHAVIOUR: Final = re.compile(
    r"\b(?:stays?|remains?) the same\b|\bunchanged\b|\bwithout changing\b|\bno behaviou?r change"
    r"|\b(?:keeps?|keeping|preserves?|preserving) (?:its |their |the |existing |current )*behaviou?r\b"
    r"|\bsame behaviou?r\b"
    r"|\b(?:do not|don't|dont|never|must not|mustn't|should not|shouldn't) (?:\w+ ){0,2}"
    r"(?:change|update|modify|edit|touch|rewrite|alter) (?:(?:the|any|its|their|existing|current) )*"
    r"(?:tests?|assertions?)\b"
    r"|\breturns? (?:the same|exactly|what it)\b"
)
# A keep phrase in a clause that scopes it to part of the request ("everything else stays the same",
# "leave the other keys unchanged", "keep the existing behaviour for callers that ...") keeps nothing
# about the part the request does change.
_SCOPED_KEEP: Final = re.compile(
    r"\b(?:else|other|others|rest|remaining|except|besides|apart from|aside from)\b"
    r"|\bfor (?:\w+ ){1,2}(?:that|who|which|where|whose|with)\b"
)
_CLAUSE_BREAK: Final = re.compile(r"[.;!?]\s+|,\s+|\s+(?:and|but)\s+")
# The request asks for a test to be changed (a change verb shortly before the test or its expectation),
# or states a result the code must now give ("must return 90", "change it to return a dataclass"):
# either way a changed expectation is what was asked for. A match negated by the words before it
# ("do not change the tests") asks for nothing.
_ASKS_TEST_EDIT: Final = re.compile(
    r"\b(?:update|change|fix|adjust|edit|rewrite|correct|modify|refresh|revise)(?:s|d|ed)? "
    r"(?:(?!(?:add|adds|adding|write|new)\b)[\w'-]+ ){0,3}"
    r"(?:tests?|assertions?|expectations?|expected values?)\b"
    r"|\b(?:to|now|should|must) return\b(?! (?:the same|exactly|what it)\b)"
)
_NEGATED_BEFORE: Final = re.compile(r"(?:\b(?:not|never|without|no)|n't)\s+(?:\w+\s+){0,2}$")
# Positional arguments a unittest assertion compares; a positional past them is its message.
_UNARY_ASSERTS: Final = frozenset({"assertTrue", "assertFalse", "assertIsNone", "assertIsNotNone"})
# Words of the request that could name a test file or a test: any token with `test` in it.
_TEST_TOKEN: Final = re.compile(r"[\w./-]*test[\w./-]*")
_TEST_DIRS: Final = frozenset({"test", "tests", "testing"})

_LOG = logging.getLogger("omh.test_expectation_check")
_lock = threading.Lock()
# session -> what this turn's request said (`_Request`).
_requests: "OrderedDict[str, _Request]" = OrderedDict()


class _Request(NamedTuple):
    keeps_behaviour: bool
    asks_test_edit: bool
    named: frozenset[str]


def note_request(session_id: object, user_message: object) -> None:
    """``pre_llm_call``: keep, for this session's turn, whether its request asked for behaviour to stay
    the same, whether it asked to change a test, and which test-like words it used."""
    try:
        if not isinstance(session_id, str) or not session_id:
            return
        text = " ".join(str(user_message or "").lower().split())
        named = frozenset(token.strip("./-") for token in _TEST_TOKEN.findall(text)[:MAX_NAMED_TOKENS])
        request = _Request(_keeps_behaviour(text), _asks_test_edit(text), named)
        with _lock:
            _requests[session_id] = request
            _requests.move_to_end(session_id)
            while len(_requests) > _MAX_SESSIONS:
                _requests.popitem(last=False)
    except Exception as exc:  # noqa: BLE001 - never fail the turn; no record means no note
        _LOG.warning("test_expectation_check note_request failed=%s", type(exc).__name__)


def _keeps_behaviour(text: str) -> bool:
    """A keep phrase in a clause no scope word narrows."""
    return any(_KEEPS_BEHAVIOUR.search(clause) and not _SCOPED_KEEP.search(clause)
               for clause in _CLAUSE_BREAK.split(text))


def _asks_test_edit(text: str) -> bool:
    """An ask to change a test, or a stated new result, that no negation right before it takes back."""
    return any(not _NEGATED_BEFORE.search(text[:match.start()]) for match in _ASKS_TEST_EDIT.finditer(text))


def round_end_note(session_id: str, root: str | None = None) -> str:
    """``pre_verify`` attempt 0: the note naming changed test expectations, or ``""``."""
    try:
        reason, rows = _decide(session_id, root)
        # One line per stop, whatever the outcome, so a turn with no note shows why it had none.
        _LOG.info("test_expectation_check session=%s fire=%s reason=%s rows=%d", session_id, bool(rows), reason, len(rows))
        return format_note(rows)
    except Exception as exc:  # noqa: BLE001 - a broken check says nothing rather than fail the turn
        _LOG.warning("test_expectation_check round_end session=%s failed=%s", session_id, type(exc).__name__)
        return ""


def _decide(session_id: str, root: str | None) -> tuple[str, list[tuple[str, int, str]]]:
    with _lock:
        request = _requests.get(session_id) if session_id else None
    if request is None:
        return "no_request", []
    if not request.keeps_behaviour:
        return "no_keep_request", []
    if request.asks_test_edit:
        return "test_edit_asked", []
    snapshots = turn_snapshots(session_id)
    changed = {path: after for path, before in snapshots.items()
               if (after := _read(path)) is not None and after != before}
    if not any(not _is_test_file(path, root) for path in changed):
        return "no_code_change", []
    # Expected values are pooled over every test file the turn changed, so an assertion moved from one
    # test file to another (or into a new one) loses nothing.
    named = False
    old: list[tuple[str, str, str, ast.AST, list[tuple[str, str]]]] = []
    gained: Counter[tuple[str, str]] = Counter()
    for path in sorted(changed):
        if not _is_test_file(path, root):
            continue
        if _named(path, request.named, root):
            named = True
            continue
        before, after = snapshots[path], changed[path]
        try:
            old_tree = ast.parse(before) if before else None
            new_tree = ast.parse(after)
        except (SyntaxError, ValueError):
            continue
        gained.update(value for test, _node, values in _expectations(new_tree) if test.lower() not in request.named
                      for value in values)
        if old_tree is not None:
            old += [(_relative(path, root), before, test, node, values) for test, node, values in _expectations(old_tree)
                    if test.lower() not in request.named]
    lost = Counter(value for *_rest, values in old for value in values) - gained
    rows: list[tuple[str, int, str]] = []
    for where, before, _test, node, values in old:
        if not any(lost[value] for value in values):
            continue
        source = " ".join((ast.get_source_segment(before, node) or "").split())
        if len(source) > MAX_SOURCE_CHARS:
            source = source[:MAX_SOURCE_CHARS - 3] + "..."
        rows.append((where, node.lineno, source))
        for value in values:
            if lost[value]:
                lost[value] -= 1
    return ("lost_expectation" if rows else "test_named" if named else "kept_expectations"), rows


def format_note(rows: list[tuple[str, int, str]]) -> str:
    if not rows:
        return ""
    shown = rows[:MAX_NOTE_ROWS]
    lines = ["OMH test check: the request asked for behaviour to stay the same, and this turn changed what an "
             "existing test expects:"]
    lines += [f"{path}:{line}: was `{source}`" for path, line, source in shown]
    if len(shown) < len(rows):
        lines.append(f"... and {len(rows) - len(shown)} more")
    lines.append("Unless the request asked for that change, put the expected values back and change the code "
                 "until the original test passes.")
    return "\n".join(lines)


def reset() -> None:
    """Forget every session's request (tests)."""
    with _lock:
        _requests.clear()


def _expectations(tree: ast.AST) -> list[tuple[str, ast.AST, list[tuple[str, str]]]]:
    """Every ``assert`` statement and ``self.assert*(...)`` call: (enclosing function name, node,
    the literal constants in it as (type, repr))."""
    found: list[tuple[str, ast.AST, list[tuple[str, str]]]] = []

    def visit(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Assert) or (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                                                 and child.func.attr.startswith("assert")):
                if isinstance(child, ast.Assert):
                    values = _expected_values(child.test)
                else:
                    # The compared arguments only: a `msg=` keyword or a trailing message string is not
                    # an expected value.
                    arity = 1 if child.func.attr in _UNARY_ASSERTS else 2
                    values = [value for argument in child.args[:arity] for value in _expected_values(argument)]
                    values += [value for keyword in child.keywords if keyword.arg != "msg"
                               for value in _expected_values(keyword.value)]
                found.append((function, child, values))
                continue
            visit(child, function)

    visit(tree, "")
    return found


def _expected_values(node: ast.AST) -> list[tuple[str, str]]:
    """The literal constants in an assertion, as (type, repr), leaving out subscript keys: in
    ``quote["total_cents"] == 2 * PRICE`` the key is how the value is reached, not what is expected,
    and a dict turned into a dataclass reaches it as ``quote.total_cents``."""
    values: list[tuple[str, str]] = []
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, ast.Constant):
            values.append((type(item.value).__name__, repr(item.value)))
        elif isinstance(item, ast.Subscript):
            stack.append(item.value)
            continue
        stack.extend(ast.iter_child_nodes(item))
    return values


def _is_test_file(path: str, root: str | None) -> bool:
    """``test_*.py``, ``*_test.py``, or a ``.py`` file under a ``test`` / ``tests`` / ``testing``
    directory of the workspace (directories above the root do not count)."""
    name = os.path.basename(path)
    if not name.endswith(".py"):
        return False
    parts = _relative(path, root).split("/")
    return name.startswith("test_") or name.endswith("_test.py") or any(part in _TEST_DIRS for part in parts[:-1])


def _named(path: str, named: frozenset[str], root: str | None) -> bool:
    """Whether the request named this test file: its root-relative path, file name, or module name."""
    name = os.path.basename(path).lower()
    candidates = {name, os.path.splitext(name)[0], _relative(path, root).lower()}
    return any(candidate in named for candidate in candidates)


def _relative(path: str, root: str | None) -> str:
    if root:
        try:
            relative = os.path.relpath(path, root)
        except ValueError:
            return path
        if not relative.startswith(".."):
            return relative.replace(os.sep, "/")
    return path


def _read(path: str) -> str | None:
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_FILE_BYTES:
        return None
    return data.decode("utf-8", errors="replace")


__all__ = ["format_note", "note_request", "reset", "round_end_note"]
