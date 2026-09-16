"""Per-turn reconciliation reminder for an open plan todo.

A model that declares a plan (todo init) and then answers "all done" in
chat while the checklist still shows open items leaves the HUD lying to
the user ('작업 다됐다는데 투두는 이렇게 남아있네'). No keyword trigger
can catch every phrasing of a completion claim, but an OPEN plan is a
state, not a phrasing — so while one exists, every turn's context
carries one compact line that binds completion claims to the checklist.
The reminder is awareness (instruction), never state and never
evidence; it stops the moment the plan is all done or cleared.

While the reader's stall finding stands, the same line also carries how
long the checklist has been unchanged. That covers the other half of the
failure: a plan does not only part ways with the session by being
contradicted, it parts ways by being left behind while the session talks
about something else.

The same turn-shaped gap exists one level out: a dispatched unit ends,
the session reports it, and the turn ends without the result being
verified or the plan updated. So the reminder also carries any finished
dispatch the plan has not written down (`dispatch_outcomes`), each with
the verb it owes, plus `DISPATCH_COMPLETION_RULE`. Same boundary: the
lines are instruction and a pointer at a record, never evidence that a
unit did anything.

The per-turn line has one structural limit: it is read at the start of a
turn, so nothing observes a turn that ENDS with open items, and continuation
then waits for the person. `plan_continuation_reading` is the same policy
delivered at the one moment a host offers -- `pre_verify`, where a returned
directive starts the next turn instead of describing the current one. Same
gate (`open_plan_position`), same rules, same boundary: it reports what the
plan record says and asserts nothing about what the next turn does. It also
hands back the plan's write stamp, which is how the hook decides whether the
run is still moving and therefore whether more of the host's turn-end budget
may be spent on it (`hooks/nudge_budget.py`).

Both surfaces were right when the session stalled and wrong when the PERSON
steered: "unless something is blocking it, advance the next item" argues with
the person while the session does what they just asked for, and the person is
what is blocking it. A plan-level `deferred_reason` is where that gets
recorded, and `plan_deferral_reason` is the single place either surface asks
whether it holds. Nothing here reads the conversation to decide it -- the
record declares it, the way the item-level block does, and for the same reason
(`recorded_blocked_reason`). Its liveness is decided in `runtime_reader`
against a digest of the items, so resuming the plan lapses it; a blocked next
item still wins over it, being the stronger statement about why nothing moved.
"""
from __future__ import annotations

from typing import Any

from .dispatch_outcomes import unacknowledged_outcomes
from .runtime_reader import (
    DECLARED_TODO_STATUSES,
    TODO_UNCHANGED_STATUSES,
    read_omh_todo,
    todo_unchanged_text,
)

try:  # Match a continuation claim on the router's own fold when OMH is installed.
    from omh.routing.visual_qa_cues import contains_cue_phrase as _contains_cue_phrase
except ImportError:  # pragma: no cover - standalone plugin hosts keep the local fold.
    _contains_cue_phrase = None

_MAX_ACTIVE_TEXT_CHARS = 80
# The reminder is one compact block, not a report: three outcome lines plus a
# count of the rest is enough to make the event impossible to miss without
# turning the per-turn context into a dispatch board.
_MAX_OUTCOME_LINES = 3

# The TUI has shown a stopped checklist to the PERSON since the in-flight
# liveness signal landed; the session driving that checklist never saw the
# finding anywhere. A plan that sits with one item active for hours while the
# session answers about other things and ends its turns is the observed
# failure, and it is not a completion claim, so the rule below cannot catch
# it. This sentence states what the reader observed and asks for one sentence
# of accounting. It rides a turn that is already happening and starts
# nothing, which is exactly why it is a context line and not a driver.
TODO_UNCHANGED_RULE = (
    "The checklist standing still is an observation, not evidence that the work "
    "failed: say where the plan stands, and if nothing is blocking it, move it."
)

# The half that was missing. The reconciliation rule below guards a COMPLETION
# CLAIM -- it fires when the model says it is done while items are open. It has
# nothing to say about the far more common way a plan dies: the model answers
# whatever arrived, reports, and ends the turn with the list untouched. A real
# run spent 36 minutes that way, and an earlier one ended with 3 of 5 phases
# pending while every notification got a courteous status reply.
#
# `omh_todo` exists to carry a goal ACROSS turns. A checklist that only ever
# catches a contradiction is a detector, not a plan. So this line states the
# obvious thing nobody was saying: open items mean the work is not finished.
#
# The termination criterion is explicit and it is what keeps this bounded --
# this is a long loop with a stop condition, not an unbounded one. It ends when
# every item is done, or when an item carries a `blocked_reason`. It does not
# end because a turn happened to produce a paragraph.
TODO_CONTINUATION_RULE = (
    "Open items mean this plan is not finished. Unless something is blocking "
    "it, advance the next item in this turn rather than ending on a status "
    "report. This stops when every item is done or an item carries an "
    "omh_todo blocked_reason -- not when a turn has produced an answer."
)

# What the turn-end directive adds to the rule above. The message arrives as a
# synthetic user turn, so it has to say what it is: a read of the plan record,
# never a claim that an item ran.
PLAN_CONTINUATION_BOUNDARY = (
    "This directive reports what the plan record says; it is not evidence that "
    "any item ran, passed, or was verified."
)

# What the plan line says INSTEAD of the continuation rule while the record
# says the person steered elsewhere. It replaces the whole ask rather than
# softening it: a line that both reports a redirection and asks to advance the
# next item is the argument this field exists to end. The stall half goes with
# it -- a deferred plan standing still is the expected state, not a finding.
TODO_DEFERRED_RULE = (
    "The person redirected this session and the plan records it, so this line "
    "is not asking you to advance the next item. Do what they asked for. The "
    "deferral lapses by itself the moment the item list changes, so resuming "
    "the plan needs no clearing step -- and if an item genuinely cannot "
    "proceed, that is an omh_todo blocked_reason on the item, not this."
)

TODO_RECONCILIATION_RULE = (
    "Before claiming this work is finished, reconcile the checklist with "
    "omh_todo: mark completed items done, keep exactly one item active, and "
    "either finish the remaining items or say which stay open and why. A "
    "completion claim in chat while the HUD checklist shows open items is a "
    "visible contradiction. Todo updates are declarations, never execution "
    "evidence."
)

# The chain a finished dispatch owes. Written as an obligation for THIS turn
# because the failure it replaces was structurally polite: a status report,
# then the turn ended, and the unit's result sat unverified while the next
# item never started.
DISPATCH_COMPLETION_RULE = (
    "A finished dispatch is an event to act on in this turn: verify its "
    "result, record the outcome on the plan (done or blocked with reason), "
    "then run the recovery or the next item. Do not announce continuation "
    "you have not started."
)

# Closing phrasings that promise a next step. Matched only to ask whether the
# step was actually armed -- never to suppress the sentence.
CONTINUATION_CLAIM_PHRASES = (
    "계속 진행",
    "이어서 진행",
    "will continue",
    "continuing",
    "proceeding with",
)

CONTINUATION_CLAIM_FINDING = (
    "The previous turn announced a continuation but nothing resumed: the plan "
    "did not change, or a finished dispatch is still unacknowledged. Start the "
    "next step in this turn -- verify the finished result, record it on the "
    "plan, then dispatch or advance -- or say plainly that the work is stopped "
    "and why. A promise to continue is not a continuation."
)


def open_todo_reminder(
    *,
    omh_home: str = "",
    hermes_home: str = "",
    session_ref: str = "",
    outcomes: list[dict[str, Any]] | None = None,
) -> str:
    """The per-turn plan line, plus any dispatch outcome nobody wrote down.

    ``session_ref`` is the session whose turn is starting; its own plan is
    the one a completion claim must reconcile against, never another
    session's. ``outcomes`` lets a caller that already read them (the hook
    also needs the count for its honesty check) hand them in rather than
    making this scan the runtime a second time on the same turn.
    """
    lines: list[str] = []
    head = _open_plan_line(omh_home=omh_home, hermes_home=hermes_home, session_ref=session_ref)
    if head:
        lines.append(head)
    lines.extend(
        _dispatch_outcome_lines(
            unacknowledged_outcomes(omh_home, hermes_home, session_ref)
            if outcomes is None
            else outcomes
        )
    )
    return "\n".join(lines)


def plan_is_established(todo: dict[str, Any]) -> bool:
    """Whether this plan is declared AND still has work in it.

    The single place the string ``"established"`` is compared.
    """
    return todo.get("status") == "established"


def plan_is_declared(todo: dict[str, Any]) -> bool:
    """Whether a plan record exists for this session right now, open or finished.

    A different question from ``plan_is_established``, and the reason the two
    are separate: the engagement nudge asks whether the model declared a plan,
    and a plan that was declared and then completed still means it did. Reading
    that through ``established`` alone would un-latch the nudge the moment a
    plan finished and start asking for another one -- the projection writes
    ``all_done`` for exactly that state.

    It is still only a snapshot. ``read_omh_todo`` retires a finished plan to
    ``absent`` after ALL_DONE_TODO_LINGER_SECONDS, so this cannot answer "did
    this session ever declare one" and the nudge's own latch remembers that.

    A record field, never a text match -- the rule ``recorded_blocked_reason``
    below carries, for the reason written there: a matcher was deleted from
    this module for getting ordinary strings wrong in both directions.
    """
    return str(todo.get("status", "")) in DECLARED_TODO_STATUSES


def open_plan_position(todo: dict[str, Any]) -> tuple[int, int] | None:
    """``(done, total)`` while this plan has open work, else ``None``.

    The single place the question "does this plan have open work" is decided.
    The per-turn context line and the turn-end continuation directive are the
    same policy read at two moments -- the line rides a turn that is already
    happening, the directive starts the next one -- so a second copy of this
    condition would let the two disagree about the same plan.
    """
    if not plan_is_established(todo):
        return None
    counts = todo.get("counts") if isinstance(todo.get("counts"), dict) else {}
    done = counts.get("done")
    total = counts.get("total")
    if not isinstance(done, int) or not isinstance(total, int) or total <= 0 or done >= total:
        return None
    return done, total


def next_open_item(todo: dict[str, Any]) -> dict[str, Any]:
    """The item record a continuation would advance: the active one, else the first pending.

    The record, not its text: the stop criterion below reads a field, and
    text is only ever needed for rendering.
    """
    items = todo.get("items") if isinstance(todo.get("items"), list) else []
    return _first_item(items, "active") or _first_item(items, "pending") or {}


def _first_item(items: list[Any], state: str) -> dict[str, Any] | None:
    return next(
        (item for item in items if isinstance(item, dict) and item.get("state") == state),
        None,
    )


def item_display_text(item: dict[str, Any] | None) -> str:
    """One item's text, truncated for display.

    Truncation belongs here and nowhere else. It used to happen on the way
    OUT of the item lookup, which put a display bound in front of a decision:
    the blocked check saw the first 80 characters of a field capped at 200,
    so a genuinely blocked item whose reason sat past the window read as
    open, and an item truncated mid-phrase could read as blocked.
    """
    if not isinstance(item, dict):
        return ""
    return str(item.get("text", "") or "")[:_MAX_ACTIVE_TEXT_CHARS]


def recorded_blocked_reason(item: dict[str, Any] | None) -> str:
    """The reason an item records for not proceeding, or ``""``.

    ``TODO_CONTINUATION_RULE`` says the plan stops when an item is *recorded*
    blocked with its reason, and a record is not a substring. An earlier form
    of this inferred the state from the item text and was wrong in both
    directions on ordinary input: "verify the retry is not blocked on the
    session limit" read as blocked, while "차단됨: 소유자 승인 대기" and
    "waiting on the owner's review" did not. Every marker that would fix the
    second widens the first, so the plan schema owns the state instead
    (``blocked_reason`` in `todo_store`) and this only reads it.

    ANY non-empty reason counts, including one that says nothing is wrong
    ("none", "n/a", "없음"). That is deliberate, and it is the narrow form of
    the question the matcher got wrong: deciding which wordings are REAL
    blocks needs a list of reasons that do not count, and that list cannot be
    completed in one language let alone four -- the same hole that made text
    inference unfixable. So the field's presence is the declaration and the
    writer owns it. The guard against filling it in speculatively is the tool
    description, which says to omit the field and send it only for an item
    that cannot proceed; a plan un-declares by removing it.
    """
    if not isinstance(item, dict):
        return ""
    reason = item.get("blocked_reason", "")
    # A non-string is corruption, not a declaration, and corruption must not
    # stop a plan. `7` and `{"a": 1}` stringify to something truthy, and
    # reading that as a block is the silent stop this surface exists to end;
    # malformed data fails toward continuing. This does not soften the
    # sentinel rule above: "none" counts because a STRING is a declaration and
    # the writer owns it, while `7` is not a declaration in any language.
    return reason.strip() if isinstance(reason, str) else ""


def plan_deferral_reason(todo: dict[str, Any]) -> str:
    """The reason the person steered this plan elsewhere, while it still holds.

    The projection has already decided liveness: `runtime_reader` fills this
    field only while the recorded digest still matches the items it read, so a
    deferral that has lapsed arrives here as absence and nothing downstream has
    to know the difference. That split is deliberate -- the digest comparison
    lives with the items it compares, and this stays the one question both
    surfaces ask.

    A non-string is read as absent, the same call `recorded_blocked_reason`
    makes and for the same reason: a hand-written record can carry anything,
    `7` stringifies to something truthy, and reading corruption as a
    declaration would stop a plan silently. Malformed data fails toward the
    plan continuing.
    """
    if not isinstance(todo, dict):
        return ""
    reason = todo.get("deferred_reason", "")
    return reason.strip() if isinstance(reason, str) else ""


# Everything the runtime read below can raise, enumerated rather than
# described, because the one thing this function may not do is raise into a
# host that swallows exceptions: Hermes wraps the whole `pre_verify` call in
# `except Exception` and logs at debug, so a handler that raised would end the
# turn silently -- the exact symptom the directive exists to fix.
#
# Four bases cover the chain, and two of them are not obvious from the call:
# `RuntimeBindingError` subclasses `ValueError` (an unbindable home), and the
# reader's state-root guard raises a plain `RuntimeError` for a symlinked home
# or a symlink loop, as does `TodoStoreError`. An earlier version of this list
# left `RuntimeError` out while a comment asserted it was complete.
_READ_FAILURES = (OSError, RuntimeError, ValueError, TypeError)


def plan_continuation_reading(
    *, omh_home: str = "", hermes_home: str = "", session_ref: str = ""
) -> tuple[str, str]:
    """The turn-end message for a session whose plan still has open work, and its stamp.

    ``TODO_CONTINUATION_RULE`` is already the right sentence delivered at the
    wrong moment: ``_open_plan_line`` renders it into the context of a turn
    that is already happening, so a turn that ends with open items ends
    anyway. This is that rule at the one moment a host lets a plugin start the
    next turn instead. The message is empty whenever the plan itself says stop
    -- no plan, a finished plan, or a next item carrying a `blocked_reason` --
    so the directive never argues with the plan's own stop criterion.

    The second value is the plan record's own `updated_at` as the reader
    projected it, `""` when the read failed or the record carries no stamp. It
    rides back with the message rather than being fetched by a second read,
    because the caller spends its remaining turn-end budget on whether the plan
    MOVED between two attempts, and a stamp read separately could describe a
    different plan than the message does. It is returned even when the message
    is empty: a turn continued by something else still needs a baseline for the
    next attempt to measure against.
    """
    # Dropping the dispatch lines with the plan is not a second F3:
    # `unacknowledged_outcomes` opens with this same `read_omh_todo` call and
    # needs the record it returns -- status, `updated_at` as the baseline, and
    # the item text that says which outcomes are already named -- so a plan
    # read that fails leaves it nothing to report either. Measured across a
    # control and eight faults: no fault yields a row here.
    try:
        todo = read_omh_todo(omh_home or None, hermes_home or None, session_ref=session_ref)
    except _READ_FAILURES:
        return "", ""
    if not isinstance(todo, dict):
        return "", ""
    # Every write through `todo_store` restamps this, so it moves on any plan
    # edit rather than only on a completed item -- which is the notion of
    # progress the caller wants. Marking the next item active, re-scoping the
    # list, or recording a reason are all a run advancing, and none of them
    # changes `done/total`.
    stamp = todo.get("updated_at", "")
    stamp = stamp if isinstance(stamp, str) else ""
    position = open_plan_position(todo)
    item = next_open_item(todo) if position is not None else {}
    lines: list[str] = []
    # The blocked item stops the PLAN line and nothing else. A finished
    # dispatch nobody wrote down is a separate obligation -- it is frequently
    # the thing that unblocks the item -- so gating both on one item's state
    # would bury the event that ends the wait. A live deferral stops the same
    # half on the same terms: the directive arrives as a synthetic user turn,
    # so issuing one while the person is being served would interrupt them
    # with the plan they just stepped away from.
    if position is not None and not recorded_blocked_reason(item) and not plan_deferral_reason(todo):
        done, total = position
        head = f"[OMH plan todo] {done}/{total} done"
        text = item_display_text(item)
        if text:
            head = f"{head} · next: {text}"
        lines.append(f"{head}. {TODO_CONTINUATION_RULE}")
    # Read in its own guard, not folded into the one above: the two lines are
    # independent obligations, so a failed outcome read must not take the plan
    # line with it. `unacknowledged_outcomes` says it never raises and swallows
    # its own read, but it expands the home a second time afterwards, and that
    # expansion is outside its guard.
    try:
        outcomes = unacknowledged_outcomes(omh_home, hermes_home, session_ref)
    except _READ_FAILURES:
        outcomes = []
    lines.extend(_dispatch_outcome_lines(outcomes))
    if not lines:
        return "", stamp
    lines.append(PLAN_CONTINUATION_BOUNDARY)
    return "\n".join(lines), stamp


def _open_plan_line(*, omh_home: str, hermes_home: str, session_ref: str) -> str:
    todo = read_omh_todo(omh_home or None, hermes_home or None, session_ref=session_ref)
    position = open_plan_position(todo)
    if position is None:
        return ""
    done, total = position
    items = todo.get("items") if isinstance(todo.get("items"), list) else []
    # The context line names the ACTIVE item and stops there; the directive
    # falls back to the first pending one, because it has to say what to
    # advance and a plan between items has no active entry. Deliberate, and
    # pinned as such.
    active = item_display_text(_first_item(items, "active"))
    head = f"[OMH plan todo] {done}/{total} done"
    if active:
        head = f"{head} · active: {active}"
    # A blocked next item wins over a deferral, so the line it produces is
    # unchanged here: the block is the stronger statement about why the plan is
    # not moving, and reporting a redirection over it would hide the thing the
    # reader has to act on. Only an unblocked plan reads as deferred.
    deferred = plan_deferral_reason(todo)
    if deferred and not recorded_blocked_reason(next_open_item(todo)):
        # The reason is rendered whole, not truncated to the item display
        # window: it is the entire content of this variant of the line and is
        # already bounded twice, by the write cap and by the reader's
        # projection of it. Cutting a reason mid-clause can invert what the
        # person asked for, which an item's text cannot do.
        return f"{head} · deferred: {deferred}. {TODO_DEFERRED_RULE} {TODO_RECONCILIATION_RULE}"
    unchanged = todo_unchanged_text(todo)
    if not unchanged:
        return f"{head}. {TODO_CONTINUATION_RULE} {TODO_RECONCILIATION_RULE}"
    stall = todo.get("stall") if isinstance(todo.get("stall"), dict) else {}
    # "no tool call in flight" is only true of the quiet finding. The busy one
    # is the more interesting reading and saying the wrong one would make the
    # line refutable on its face.
    observed = (
        "unchanged {age} while calls kept running".format(age=unchanged)
        if stall.get("status") == "unchanged_while_busy"
        else "unchanged {age}, no tool call in flight".format(age=unchanged)
    )
    return (
        f"{head} · {observed}. "
        f"{TODO_CONTINUATION_RULE} {TODO_RECONCILIATION_RULE} {TODO_UNCHANGED_RULE}"
    )


def _dispatch_outcome_lines(outcomes: list[dict[str, Any]]) -> list[str]:
    if not outcomes:
        return []
    lines = [
        "dispatch {run_ref}/{unit_id} ended {state}; next: {verb}".format(
            run_ref=outcome.get("run_ref", "unknown"),
            unit_id=outcome.get("unit_id", "unknown"),
            state=_outcome_state(outcome),
            verb=outcome.get("next", "verify_result"),
        )
        for outcome in outcomes[:_MAX_OUTCOME_LINES]
    ]
    remaining = len(outcomes) - len(lines)
    if remaining > 0:
        lines.append(f"(+{remaining} more)")
    lines.append(DISPATCH_COMPLETION_RULE)
    return lines


def _outcome_state(outcome: dict[str, Any]) -> str:
    for key in ("unit_state", "failure_kind", "status"):
        value = str(outcome.get(key, "") or "")
        if value:
            return value
    return "unknown"


def continuation_claim_without_resume(
    text: str, *, todo_stall_status: str, unacknowledged: int
) -> str | None:
    """A finding when a turn promises to continue and nothing was started.

    "계속 진행하겠습니다" with no auto-resume armed is the exact closing the
    incident produced. The claim itself is fine; what makes it a finding is
    the state it was made in -- the plan unchanged, or a finished dispatch
    still unacknowledged. Either one is enough, because either one means the
    promised step did not start. Pure: the caller supplies both states, so
    this never reads a file and never decides on its own that a run is stuck.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    # The reader owns which statuses mean "the checklist stopped moving"; a
    # copy of that pair here would let a third one be added there without this
    # guard ever noticing.
    stalled = str(todo_stall_status or "") in TODO_UNCHANGED_STATUSES
    outstanding = isinstance(unacknowledged, int) and unacknowledged > 0
    if not stalled and not outstanding:
        return None
    if not _claims_continuation(text):
        return None
    return CONTINUATION_CLAIM_FINDING


def _claims_continuation(text: str) -> bool:
    if _contains_cue_phrase is not None:
        return bool(_contains_cue_phrase(text, CONTINUATION_CLAIM_PHRASES))
    folded = text.casefold()
    return any(phrase.casefold() in folded for phrase in CONTINUATION_CLAIM_PHRASES)
