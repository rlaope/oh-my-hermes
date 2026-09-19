"""Behaviour-triggered nudges toward a declared plan and a routed lane.

The reported defect is that OMH almost never engages on an ordinary prompt:
"간단한 작업이든 큰 작업이든 다양하게 테스트해봤지만 거의 todo나 에이전트 호출을
하지 않더라구요." Everything OMH had for this read the user's WORDS -- route
hints, the awareness matcher, the workflow triggers -- so a session that never
said an OMH word got nothing, and the first-turn primer only makes the model
aware, not active.

So the trigger here is the model's own BEHAVIOUR, taken from the host's tool
calls: how many files it has changed, and how much searching it has done
directly. Nothing in the user's message is consulted at any point. A keyword
trigger is what already exists and it is what is failing.

The shape is taken from oh-my-openagent's `agent-usage-reminder` hook, which
solves the same problem for opencode, and it keeps four of that hook's five
properties:

* the trigger is a tool call, not a phrase;
* the text rides the tool result (`transform_tool_result`), so it costs no
  extra turn and needs no second injection point;
* it is bounded per session (`MAX_ENGAGEMENT_NUDGES`);
* it latches off permanently once the thing happened, rather than decaying.

The fifth, "only nudge the orchestrator", does not transfer as written. Its
opencode form reads the agent name off the session; the Hermes seam carries
`tool_name`, `args`, `result`, `task_id`, `session_id`, `tool_call_id`,
`turn_id`, `api_request_id`, `duration_ms`, `status`, `error_type`,
`error_message` and no agent identity, and a delegated child runs under its own
`session_id`, so per-session keying does not separate it either. The
substitute is `subagent_start`: the host hands over `child_session_id` from the
same code path that creates the child, `nudge_budget` records it, and this
module refuses to nudge a session on that list.

Nothing here raises. Hermes wraps the transform in `except Exception` and logs
at debug (`model_tools._apply_transform_tool_result_hook`), so a handler that
raised would leave no trace at all -- the failure would be invisible rather
than loud. Every decline is counted by reason instead, readable through
`engagement_nudge_declines()`.

The nudges are prepared instruction. Emitting one is not evidence that a plan
was declared, a lane was routed, or any work was done.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Final

from .hooks.nudge_budget import (
    DELEGATION_LATCH_FIELD,
    DELEGATION_NUDGES_FIELD,
    DIRECT_READS_FIELD,
    MUTATIONS_FIELD,
    PLAN_LATCH_FIELD,
    PLAN_NUDGES_FIELD,
    bump_engagement_count,
    engagement_count,
    latch_engagement,
    record_distinct_direct_read,
    session_is_delegated,
)
# The one canonicalization of a tool call's arguments in this bundle. The
# repeat guard computes this same digest for the same call at
# `pre_tool_call`; a second hashing path here would be a second answer to
# "is this the same call", and the two would disagree the first time either
# of them changed.
from .tool_bursts import tool_args_digest

ENGAGEMENT_NUDGE_SCHEMA_VERSION: Final = "omh_engagement_nudge/v1"
# Its own JSON key, the way `code_mode_guidance` adds one: a tool result that
# parses as a JSON object must keep parsing after this module has touched it,
# so the text is a new field there and only appended when the result is plain.
ENGAGEMENT_NUDGE_KEY: Final = "omh_engagement"

# Host tool names, copied from Hermes rather than imported -- the bundle may
# only import from inside itself, and Hermes is a different repository, so no
# parity test can exist for these the way it can for the router vocabulary.
# Each set names its source file so a reader can check it by hand.
#
# `agent/tool_result_classification.py`: FILE_MUTATING_TOOL_NAMES. The host's
# own named set for "this call changed the repository", and deliberately not
# widened to `terminal` or `execute_code`: a session that only ran tests has
# done no work a checklist would track, and both of those are mostly that.
FILE_MUTATING_TOOLS: Final[frozenset[str]] = frozenset({"write_file", "patch"})
# `tools/code_execution_tool.py`: SANDBOX_ALLOWED_TOOLS, minus the mutating and
# shell ones. These are the calls a delegated lane would have made off this
# context -- opencode's `TARGET_TOOLS` (grep, glob, webfetch, exa) mapped onto
# the names Hermes actually registers.
DIRECT_READ_TOOLS: Final[frozenset[str]] = frozenset(
    {"read_file", "search_files", "web_search", "web_extract"}
)
# Routing a lane, either way round: `delegate_task` is Hermes' own subagent
# tool (`tools/delegate_tool.py`) and `omh_delegate_route` is OMH's
# (`metadata.PROVIDED_TOOLS`). Observing either IS the record that the model
# routed -- the tool name the host handed this hook, never a claim it made in
# prose.
DELEGATION_TOOLS: Final[frozenset[str]] = frozenset({"delegate_task", "omh_delegate_route"})

# Counter names in the shared per-session map. Defined at `nudge_budget`,
# which owns the map, the eviction policy and the list of which of these
# survive a process restart -- one spelling, in the file that has to name
# them for that last question.
_MUTATIONS: Final = MUTATIONS_FIELD
_DIRECT_READS: Final = DIRECT_READS_FIELD
_PLAN_NUDGES: Final = PLAN_NUDGES_FIELD
_DELEGATION_NUDGES: Final = DELEGATION_NUDGES_FIELD
_PLAN_LATCH: Final = PLAN_LATCH_FIELD
_DELEGATION_LATCH: Final = DELEGATION_LATCH_FIELD

# Three file-mutating calls. One is a typo fix. Two is an edit and its test --
# the two shapes where a checklist is pure overhead, and the two a person holds
# in their head without help. Three is the first count past both, and it is
# also where the HUD stops being able to show what is left without a plan to
# show. The pinned negative case sits at two.
PLAN_NUDGE_FILE_MUTATION_THRESHOLD: Final = 3
# Five DISTINCT direct search/read calls. Below that it is ordinary
# orientation: open a file, grep once, open what the grep found. At five the
# session has run a search pass that one `explore` lane would have run in a
# single call and off this context window, which is the case the nudge exists
# for. opencode fires on the first such call because its target set is
# grep/glob/webfetch only; Hermes' `read_file` is far more ordinary than that,
# so the threshold carries what its narrower set carried. The pinned negative
# case sits at four.
#
# Distinct, because counting calls made a loop indistinguishable from a search
# pass and let it spend the budget meant for one. Measured: session
# `20260919_140745_db409e` issued 203 `search_files` calls, the large majority
# identical; the nudge fired twice, said "delegate this", and was silent for
# the remaining ~180. The session's actual problem was that it was repeating
# one search that returned nothing, and the only OMH mechanism watching
# searches had no way to know (#1701).
DELEGATION_NUDGE_DIRECT_READ_THRESHOLD: Final = 5
# Two per kind per session. opencode allows three; this text rides a tool
# result on a surface that already spends a first-turn primer, and a nudge the
# model has declined twice is not going to work the third time.
MAX_ENGAGEMENT_NUDGES: Final = 2

PLAN_NUDGE_TEXT: Final = (
    "[OMH plan todo] This session has changed files {count} times and no plan is "
    "declared. Declare one now with omh_todo -- the steps you are actually "
    "taking, exactly one of them active -- so the Hermes TUI shows the person "
    "what is planned and what is left, and so the next turn has something to "
    "reconcile a completion claim against. Todo items are declarations, never "
    "execution evidence."
)
# What the two tools actually do, measured in the host rather than inferred
# from their names. This sentence used to end "omh_delegate_route to pick one,
# or delegate_task for a Hermes subagent, and keep working while it runs", and
# that was wrong about both halves:
#
# * `omh_delegate_route` writes `delegation.*` keys that apply to the NEXT
#   dispatch -- its own evidence boundary in `tools/delegate_route_tool.py`
#   says exactly that. Nothing runs, so there is nothing to work alongside.
# * `delegate_task` does run something, and "keep working while it runs" is
#   the one thing the host tells the model not to do about it. Its schema text
#   reads "Background results are delivered only BETWEEN your turns: finish
#   whatever does not depend on them, then give a one-line status and END YOUR
#   TURN. Never wait or poll" (`tools/delegate_tool.py`, `_DESCRIPTION_HEAD`).
#
# Nor can the model choose how it runs. `run_agent._dispatch_delegate_task`
# passes `background=not (depth > 0)`, so a top-level model delegation is
# always backgrounded and the schema-level `background` is unadvertised and
# ignored; the `background=False` default on the Python signature is for
# direct callers. Measured on hermes-agent 0.21.3 -- Hermes is a different
# repository, so no parity test can hold this the way one holds the router
# vocabulary, and the call sites are named here so a reader can check by hand.
DELEGATION_NUDGE_TEXT: Final = (
    "[OMH delegation] This session has run {count} different search/read calls "
    "directly and routed nothing. A lane does that work in one call and off this "
    "context window: omh_delegate_route picks the model for the next "
    "dispatch, delegate_task spawns the subagent. Never wait or poll on a "
    "dispatched lane -- carry on with what does not depend on it. Routing is "
    "a prepared handoff, never execution, review, CI, or merge evidence."
)

# Why a decline was not a nudge. Counted rather than raised, because the host
# swallows exceptions from this seam: without this, a module that broke would
# be indistinguishable from a session that simply had nothing to say.
_declines: "Counter[str]" = Counter()


def engagement_nudge_declines() -> dict[str, int]:
    """A copy of the decline tally, by reason. Diagnostics, never a gate."""
    return dict(_declines)


def reset_engagement_declines() -> None:
    """Test seam: forget the decline tally. Paired with `reset_nudge_budget`."""
    _declines.clear()


def record_engagement_observer_failure(error_type: str) -> None:
    """Record that the delegated-session observer swallowed a failure.

    `subagent_start` is the only feed for the delegated-session set, and its
    swallow is right: the host already calls it inside its own quiet block, and
    failing to record one child must not interrupt that child's spawn. But a
    swallow with nothing written is observable only as an ABSENCE -- the
    `delegated_session` decline that never happens, which nobody notices
    without already expecting it and counting. Worse, if whatever broke the
    observer also keeps the nudge path away from that session, the two cancel
    and the trace is empty.

    So the REPORT is widened rather than the `except`: one tally entry, in the
    same readout as every other reason this path declined to act, because the
    observer exists only to feed it.
    """
    _declines[f"observer_error:{error_type or 'Unknown'}"] += 1


def annotate_engagement_nudge(
    *,
    tool_name: object,
    result: object,
    args: object = None,
    session_id: str = "",
    omh_home: str = "",
    hermes_home: str = "",
) -> str | None:
    """Return *result* carrying a nudge, or ``None`` to pass through untouched.

    ``args`` is the call's arguments, which the host passes this seam already
    coerced to the tool's schema types. They are read for one purpose: to tell
    the same search twice from two different searches. Nothing is stored but
    the digest.

    Fail-open by seam contract and by construction: every path that is not a
    clean, budgeted, unlatched nudge returns ``None`` after recording why.
    """
    try:
        return _annotate(
            tool_name=tool_name,
            result=result,
            args=args,
            session_id=session_id,
            omh_home=omh_home,
            hermes_home=hermes_home,
        )
    except Exception as exc:  # noqa: BLE001 - see module docstring: the host
        # swallows and debug-logs anything this raises, so a raise here is a
        # silent disappearance. The failure is recorded by type and the tool
        # result passes through unchanged.
        _declines[f"error:{type(exc).__name__}"] += 1
        return None


def _annotate(
    *,
    tool_name: object,
    result: object,
    args: object,
    session_id: str,
    omh_home: str,
    hermes_home: str,
) -> str | None:
    name = str(tool_name or "")
    session = str(session_id or "")

    # Routing is observed before anything else, so a session that delegated on
    # this very call is latched before the call could also be counted as work.
    if name in DELEGATION_TOOLS:
        latch_engagement(session, _DELEGATION_LATCH, omh_home=omh_home)
        _declines["routed_this_call"] += 1
        return None

    if not session:
        # An unkeyed session shares no row (see `bump_engagement_count`), so it
        # can never reach a threshold. Recorded rather than silently skipped.
        _declines["no_session_id"] += 1
        return None
    if session_is_delegated(session):
        _declines["delegated_session"] += 1
        return None

    if name in FILE_MUTATING_TOOLS:
        # Calls, not distinct calls. Writing the same file three times IS
        # three changes to the repository, which is what this threshold
        # counts; the distinctness question belongs to the read side, where
        # the same call twice produces the same answer twice.
        count = bump_engagement_count(session, _MUTATIONS, omh_home=omh_home)
        return _plan_nudge(
            session=session,
            count=count,
            result=result,
            omh_home=omh_home,
            hermes_home=hermes_home,
        )
    if name in DIRECT_READ_TOOLS:
        # The call counter is still kept, and is still the one the declines
        # and any later surface can read for "how much searching happened".
        # It is simply no longer what the threshold reads.
        _ = bump_engagement_count(session, _DIRECT_READS, omh_home=omh_home)
        distinct = record_distinct_direct_read(session, f"{name}:{tool_args_digest(args)}")
        return _delegation_nudge(
            session=session, count=distinct, result=result, omh_home=omh_home
        )

    _declines["tool_not_watched"] += 1
    return None


def _plan_nudge(
    *,
    session: str,
    count: int,
    result: object,
    omh_home: str,
    hermes_home: str,
) -> str | None:
    if count < PLAN_NUDGE_FILE_MUTATION_THRESHOLD:
        _declines["below_work_threshold"] += 1
        return None
    if engagement_count(session, _PLAN_LATCH, omh_home=omh_home):
        _declines["plan_already_declared"] += 1
        return None
    if engagement_count(session, _PLAN_NUDGES, omh_home=omh_home) >= MAX_ENGAGEMENT_NUDGES:
        _declines["plan_budget_spent"] += 1
        return None
    if _plan_declared(session=session, omh_home=omh_home, hermes_home=hermes_home):
        # Latched in the map so the record is read at most a handful of times
        # per session rather than on every mutating call.
        latch_engagement(session, _PLAN_LATCH, omh_home=omh_home)
        _declines["plan_already_declared"] += 1
        return None
    carried = _carry(result, PLAN_NUDGE_TEXT.format(count=count))
    if carried is None:
        _declines["result_not_carryable"] += 1
        return None
    _ = bump_engagement_count(session, _PLAN_NUDGES, omh_home=omh_home)
    return carried


def _delegation_nudge(*, session: str, count: int, result: object, omh_home: str) -> str | None:
    """``count`` is DISTINCT `(tool, argument digest)` pairs, not calls.

    A repeat adds nothing to it, so a loop never reaches the threshold and
    never spends the budget: the whole of #1701 in one substitution.
    """
    if count < DELEGATION_NUDGE_DIRECT_READ_THRESHOLD:
        _declines["below_read_threshold"] += 1
        return None
    if engagement_count(session, _DELEGATION_LATCH, omh_home=omh_home):
        _declines["lane_already_routed"] += 1
        return None
    if engagement_count(session, _DELEGATION_NUDGES, omh_home=omh_home) >= MAX_ENGAGEMENT_NUDGES:
        _declines["delegation_budget_spent"] += 1
        return None
    carried = _carry(result, DELEGATION_NUDGE_TEXT.format(count=count))
    if carried is None:
        _declines["result_not_carryable"] += 1
        return None
    _ = bump_engagement_count(session, _DELEGATION_NUDGES, omh_home=omh_home)
    return carried


def _plan_declared(*, session: str, omh_home: str, hermes_home: str) -> bool:
    """Whether this session has a plan record right now, open or just finished.

    Reads the record through the one predicate that owns the question
    (`todo_reconciliation.plan_is_declared`), never a string the model wrote.
    Deliberately NOT `plan_is_established`: that one means "has work left", so
    latching on it would ask for a second plan the moment the first completed.

    The projection retires a finished plan to `absent` after a while, so this
    answers only "is there a plan now". The permanence lives in the caller's
    latch, which is why this is read at most a handful of times per session
    and never again once it answers True.

    An unreadable home answers "no plan", which costs a nudge and never
    suppresses one. That is the right direction for a best-effort read here:
    the alternative is a broken home silently disabling the nudge forever.
    """
    from .todo_reconciliation import plan_is_declared
    from .runtime_reader import read_omh_todo

    todo = read_omh_todo(omh_home or None, hermes_home or None, session_ref=session)
    return isinstance(todo, dict) and plan_is_declared(todo)


def _carry(result: object, text: str) -> str | None:
    """Put *text* on *result* without breaking a host result that is JSON.

    A JSON object gains its own key, the way `code_mode_guidance` does, because
    appending to a serialized object makes it unparseable. Anything else is
    plain text and the nudge is appended. A JSON value that is not an object
    (a bare list, a number) is declined rather than guessed at.
    """
    if not isinstance(result, str) or not result:
        return None
    try:
        parsed: Any = json.loads(result)
    except (ValueError, TypeError):
        return f"{result}\n\n{text}"
    if not isinstance(parsed, dict):
        return None
    if ENGAGEMENT_NUDGE_KEY in parsed:
        return None
    parsed[ENGAGEMENT_NUDGE_KEY] = text
    try:
        return json.dumps(parsed, ensure_ascii=False)
    except (TypeError, ValueError):
        return None
