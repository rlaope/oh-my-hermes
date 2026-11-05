"""In a console session, ask the person to pick through Hermes' `clarify`, not a prose list.

Hermes' `clarify` tool asks the person a question with up to four choices,
and every local console draws it as a picker: the OMH TUI (`tui/prompts.py`),
Hermes' Ink TUI and its CLI. In the owner's TUI sessions of late 2026-10 the
model used it for fewer than half of the turns that stopped on a choice
between named options; the rest ended in prose ("• "머지해": … •
"재실행": …") and asked the person to type a word back. One of them began as
a clarify that timed out after Hermes' 60 minutes, and when the person
returned the model repeated the options in prose, twice: nothing told it to
ask again.

So this module adds one line, on two turns only:

- `CONSOLE_CHOICES_LINE`, on a console session's first turn. Hermes replays
  each turn's injection from `api_content`, so the line stays in the
  session's context after that without being sent again; when the replayed
  rows no longer carry it (a compaction or a resume dropped the first turn's
  injection) it goes out once more (`_line_dropped`). It states the
  presence rule (`native_tool_presence_clause`), because `pre_llm_call` is
  handed no tool list; the model reads its own.
- `TIMED_OUT_LINE`, on the first turn a person opens after a clarify of the
  session timed out, read from the structure of the history: the last
  clarify result since the person last wrote has `outcome` `timed_out`
  (Hermes 2026-10 and later) or `timed_out: true` (earlier). A clarify that
  was answered later, or a turn Hermes opened for itself (a background
  process finishing, a `/loop` wake-up or `/goal` continuation), sends
  nothing.

Both lines only redirect a question the model would ask anyway: a closing
offer of optional further work stays prose, so a misfire costs a picker where
a list would have stood, never a new question. Neither says anything about
the reply's voice. A messaging platform (Discord, Slack, ...) gets neither,
and renders exactly what it rendered before; its `clarify` is a numbered
message, not a picker. Nor does an unattended run on a console platform (a
single-query `hermes -z` or `chat -q`, a kanban task process;
`jev_consent.attended_turn`): there clarify comes back undelivered with
"use your own judgment", and an approval would be decided by the model.

Stdlib only; this ships in the plugin bundle, which may not import `omh`.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Final

from .hermes_session_commands import host_command_turn
from .jev_consent import attended_turn
from .memory_session_lens import OPERATOR_CONSOLE_PLATFORMS
from .native_tools import native_tool_presence_clause
from .turn_authorship import host_synthesized_turn

CLARIFY_TOOL: Final = "clarify"

# The choice shape is the one the OMH TUI draws as a label with a dim description
# under it (`tui/prompts.py`, `CHOICE_DESCRIPTION`); the context goes in the
# reply text before the call, so the picker's question stays one sentence.
CONSOLE_CHOICES_LINE: Final = (
    "[OMH Console Choices] Where a reply would stop for the person to pick between named options or approve an "
    f"action you will not take without their answer, and {native_tool_presence_clause(CLARIFY_TOOL)}, use "
    "clarify, not a prose list: context in your reply first, a one-sentence question, 2-4 choices as "
    "`label — short clause`, recommended first. A closing offer of optional further work stays prose."
)
TIMED_OUT_LINE: Final = (
    "[OMH Console Choices] Your last clarify timed out before the person answered. If their message leaves "
    "that choice open, ask it again through clarify (one short question, 2-4 choices written "
    "`label — one short clause`, recommended first), not a prose list."
)


def _person_row(row: Mapping[str, object]) -> bool:
    """A user row a person wrote: no host `display_kind` on it (`turn_authorship`), and not one of Hermes'
    session-command frames, which carry none (`/loop` wake-ups, `/goal` continuations, `/plan`)."""
    kind = row.get("display_kind")
    if row.get("role") != "user" or (isinstance(kind, str) and host_synthesized_turn(kind)):
        return False
    return not host_command_turn(row.get("content"))


def _since_person_spoke(history: object) -> list[Mapping[str, object]]:
    """The rows after the person's previous message and before this turn's own user row, oldest first.

    This turn's row is the newest user row (`build_turn_context` appends it
    before the hook runs). Rows Hermes wrote for itself in between are kept,
    so a clarify that timed out on a turn a background process opened still
    counts when the person comes back.
    """
    if not isinstance(history, (list, tuple)):
        return []
    rows = [row for row in history if isinstance(row, Mapping)]
    users = [index for index, row in enumerate(rows) if row.get("role") == "user"]
    if not users:
        return []
    end = users[-1]
    start = next((index for index in reversed(users[:-1]) if _person_row(rows[index])), -1)
    return rows[start + 1:end]


def _call_ids(row: Mapping[str, object]) -> set[str]:
    ids: set[str] = set()
    for call in row.get("tool_calls") or ():
        function = call.get("function") if isinstance(call, Mapping) else None
        if isinstance(function, Mapping) and function.get("name") == CLARIFY_TOOL:
            ids.update(value for value in (call.get("id"), call.get("call_id")) if isinstance(value, str) and value)
    return ids


def _timed_out(content: object) -> bool:
    try:
        result = json.loads(content) if isinstance(content, str) else None
    except ValueError:
        return False
    return isinstance(result, Mapping) and (result.get("outcome") == "timed_out" or result.get("timed_out") is True)


def clarify_timed_out_since_person_spoke(history: object) -> bool:
    """Whether the last clarify result since the person last wrote is a timeout."""
    clarify_ids: set[str] = set()
    last: bool | None = None
    for row in _since_person_spoke(history):
        if row.get("role") == "assistant":
            clarify_ids |= _call_ids(row)
        elif row.get("role") == "tool" and row.get("tool_call_id") in clarify_ids:
            last = _timed_out(row.get("content"))
    return bool(last)


def _line_dropped(history: object) -> bool:
    """Whether the host replays injections (a row carries `api_content`) and none carries the line any more.

    True after a compaction or a resume dropped the first turn's injection, so
    the line goes out once more; a host that replays nothing never repeats it.
    Only the host-injected suffix of each row is read, as for the primer, so a
    person quoting the line cannot suppress it.
    """
    if not isinstance(history, (list, tuple)):
        return False
    replayed = False
    for row in history:
        api_content = row.get("api_content") if isinstance(row, Mapping) else None
        if not isinstance(api_content, str):
            continue
        replayed = True
        clean = row.get("content")
        injected = api_content[len(clean):] if isinstance(clean, str) and api_content.startswith(clean) else api_content
        if CONSOLE_CHOICES_LINE in injected:
            return False
    return replayed


def console_choices_line(platform: object, history: object, *, is_first_turn: bool, person_turn: bool) -> str:
    """The line for this turn of a console session a person attends, else "".

    An unattended run on a console platform (a single-query `hermes -z` or
    `chat -q`, a kanban task process) gets nothing: its clarify comes back
    undelivered with "use your own judgment", so an approval the model would
    have stopped for would be decided by the model instead (`attended_turn`).
    `person_turn` is whether a person's own words opened the turn (the hook's
    `request_message`); only such a turn re-asks after a timeout.
    """
    platform_id = str(platform or "").strip().casefold()
    if platform_id not in OPERATOR_CONSOLE_PLATFORMS or not attended_turn(platform_id):
        return ""
    if person_turn and clarify_timed_out_since_person_spoke(history):
        return TIMED_OUT_LINE
    return CONSOLE_CHOICES_LINE if is_first_turn or _line_dropped(history) else ""
