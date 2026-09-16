"""Per-turn memory of the plan stamp a continuation nudge was last issued on.

`pre_verify` fires up to `agent.max_verify_nudges` times in one turn (3 by
default, enforced by the host). The hook's first form spent exactly one of
them: it returned `None` for every `attempt > 0`, per the host docs'
idempotency guidance. That guidance is right about the failure it names -- a
hook that always continues nags to the bound whether or not anything is
happening -- and wrong as a policy for a plan, because it ends a five-item run
one item per turn and waits for the person in between.

The budget is safe to spend on exactly one condition: the run is MOVING. So
the gate here is not the attempt number, it is whether the plan record was
written again between this attempt and the previous nudge in the same turn. An
advancing plan keeps its budget; a plan that did not move spends one nudge and
the turn ends -- which is the case the idempotency guidance was protecting, now
stated as the condition it actually meant.

Where the memory lives, and why it is a module global. The host calls the hook
as a plain function with the documented kwargs and hands a plugin no object to
hang per-turn state on; `attempt` returning to 0 is the only turn boundary a
hook can observe, and the host resets it per turn. So the memory is here, with
the two properties that make a global safe for it:

- keyed by `session_id`, so two sessions served by one process cannot decide
  each other's turns, and a session with no id is not tracked at all (it keeps
  the one-nudge budget -- a shared untracked row would measure one session's
  turn against another session's plan, and losing two nudges is by far the
  cheaper failure);
- bounded, because a host outlives every session it runs and a map keyed by
  session id only grows. Eviction fails toward the behaviour that shipped
  before this gate existed: a session whose baseline was evicted is refused at
  `attempt > 0`, so it spends exactly the one nudge it used to. The direction
  is the point -- an evicted row must not fall back toward MORE nudging.

Nothing here raises. Hermes wraps the whole `pre_verify` call in
`except Exception` and logs at debug, so a handler that raised would end the
turn with no trace -- the exact symptom the directive exists to fix.
"""
from __future__ import annotations

from collections import OrderedDict

# The plan record's stamp is written by `todo_store` and read back by
# `dispatch_outcomes`, which already owns the one tolerant parse of it (a naive
# string gets UTC, anything unparseable is `None`). Importing it is deliberate:
# a second parser here would let the two disagree about the same field, the way
# a second copy of any rule in this bundle does.
from ..dispatch_outcomes import _parse_timestamp
# The bound the plan record applies to this same string, so a key here and the
# record's own `session_ref` always describe the same reference.
from ..todo_store import MAX_TODO_SESSION_REF_CHARS

# Enough that a host serving several sessions at once keeps every live one, far
# short of a map that grows for the process's lifetime. The number is not load
# bearing; the bound is.
MAX_TRACKED_SESSIONS = 64

_LAST_NUDGE_STAMPS: "OrderedDict[str, str]" = OrderedDict()


def plan_nudge_allowed(*, session_id: object, attempt: int, stamp: object) -> bool:
    """Whether the open-plan directive may be issued at this attempt.

    ``stamp`` is the plan record's own write time as the reader projected it,
    and it is recorded as the baseline whenever this answers ``True`` -- so the
    next attempt in the same turn is measured against the plan the previous
    nudge was issued on, not against the start of the turn.

    The first attempt always passes: it is the nudge the plan directive already
    spends, and it is also where the turn's baseline comes from. Later attempts
    pass only while the plan keeps being written.
    """
    key = _session_key(session_id)
    stamp_text = _stamp_text(stamp)
    if attempt == 0:
        # Recorded even when the caller has nothing to say (a finished plan, a
        # next item recorded blocked, an unreadable home). The turn can still be
        # continued by another hook, and when it is, attempt 1 has to be able to
        # tell a plan that moved since from one that never had a baseline.
        if key:
            _remember(key, stamp_text)
        return True
    if not key:
        return False
    if not _advanced(stamp_text, _LAST_NUDGE_STAMPS.get(key)):
        return False
    _remember(key, stamp_text)
    return True


def _advanced(stamp: str, previous: str | None) -> bool:
    """Whether the plan was written again since ``previous``.

    ``None`` is no baseline, not an old one: an attempt with no recorded first
    nudge in this turn cannot show movement and must not invent it.

    A stamp that does not parse is not movement -- corruption must not buy a
    nudge. A previous stamp that does not parse is the other question, and the
    opposite answer: it is every state where the plan had nothing readable to
    compare against and now does (no plan at the first nudge, a record repaired
    mid-turn), which is movement. A stamp that went backwards is not.
    """
    if previous is None:
        return False
    current = _parse_timestamp(stamp)
    if current is None:
        return False
    earlier = _parse_timestamp(previous)
    return earlier is None or current > earlier


def _session_key(session_id: object) -> str:
    if not isinstance(session_id, str):
        return ""
    return session_id.strip()[:MAX_TODO_SESSION_REF_CHARS]


def _stamp_text(stamp: object) -> str:
    return stamp if isinstance(stamp, str) else ""


# ---------------------------------------------------------------------------
# Engagement counters: the second thing this module remembers per session.
#
# Kept here rather than in a module of its own because the eviction policy, the
# key derivation, the bound, and above all the reset obligation are one
# question answered once. A second bounded per-session map elsewhere would be a
# second thing a new test has to remember to clear, and the docstring on
# `reset_nudge_budget` is an argument about exactly that.
#
# Only the payload differs from the stamps above. The stamps answer "did the
# plan move since the last nudge in this turn" and live for a turn; these
# answer "how much work has this session done, and has it done the thing yet"
# and live for the session. Same map shape, same 64-row ceiling, same
# fail-toward-fewer-nudges direction on eviction -- an evicted session restarts
# its counts at zero, which delays a nudge and never adds one.
_ENGAGEMENT_COUNTS: "OrderedDict[str, dict[str, int]]" = OrderedDict()

# Session ids the host reported as delegated children (`subagent_start`'s
# `child_session_id`). A child runs under its OWN session id, so per-session
# keying alone does not separate it from the orchestrator, and the tool-result
# seam the nudges ride carries no agent identity at all. This is the only
# record-based way this bundle can tell the two apart.
_DELEGATED_SESSIONS: "OrderedDict[str, bool]" = OrderedDict()


def bump_engagement_count(session_id: object, field: str) -> int:
    """Increment one counter for this session and return its new value.

    Returns 0 for a session with no usable id rather than sharing an untracked
    row, for the reason the stamps above give: measuring one session's work
    against another session's plan is worse than not measuring at all.
    """
    key = _session_key(session_id)
    if not key:
        return 0
    row = _ENGAGEMENT_COUNTS.pop(key, None) or {}
    row[field] = int(row.get(field, 0)) + 1
    _ENGAGEMENT_COUNTS[key] = row
    while len(_ENGAGEMENT_COUNTS) > MAX_TRACKED_SESSIONS:
        _ = _ENGAGEMENT_COUNTS.popitem(last=False)
    return row[field]


def engagement_count(session_id: object, field: str) -> int:
    """Read one counter without creating a row for a session that has none."""
    key = _session_key(session_id)
    if not key:
        return 0
    return int((_ENGAGEMENT_COUNTS.get(key) or {}).get(field, 0))


def latch_engagement(session_id: object, field: str) -> None:
    """Record that this session did the thing, for the rest of its life.

    A latch, not a decay: once a plan is declared or a lane is routed, the
    nudge that asked for it has no remaining question to ask.
    """
    _ = bump_engagement_count(session_id, field)


def note_delegated_session(child_session_id: object) -> None:
    """Remember a session id the host reported as a delegated child.

    Fed by `subagent_start`, whose `child_session_id` the host emits from the
    same code path that creates the child -- so a host that never calls it is
    a host with no children to mistake for orchestrators.
    """
    key = _session_key(child_session_id)
    if not key:
        return
    _ = _DELEGATED_SESSIONS.pop(key, None)
    _DELEGATED_SESSIONS[key] = True
    while len(_DELEGATED_SESSIONS) > MAX_TRACKED_SESSIONS:
        _ = _DELEGATED_SESSIONS.popitem(last=False)


def session_is_delegated(session_id: object) -> bool:
    """Whether this session is a delegated child the host told us about."""
    key = _session_key(session_id)
    return bool(key) and key in _DELEGATED_SESSIONS


def reset_nudge_budget() -> None:
    """Forget every recorded baseline and every engagement count. A test seam.

    This memory is process-global, and the repository has already paid for that
    shape once: `fanout_dispatch._INTERRUPT_FLAG` was set by one test and
    surfaced as a CI-only failure in whichever test the shard planner happened
    to run next, because the planner reorders tests run to run. A suite that
    passes in one local order proves nothing about that.

    So every test that populates this clears it through this function rather
    than by reaching into the module attribute -- the obligation is then
    greppable instead of remembered, and a new test file that forgets it is one
    `reset_nudge_budget` search away from being found.
    """
    _LAST_NUDGE_STAMPS.clear()
    _ENGAGEMENT_COUNTS.clear()
    _DELEGATED_SESSIONS.clear()


def _remember(key: str, stamp: str) -> None:
    _ = _LAST_NUDGE_STAMPS.pop(key, None)
    _LAST_NUDGE_STAMPS[key] = stamp
    # Oldest first: the row least recently nudged is the one whose turn is most
    # likely already over. Losing it costs that session the extra nudges and
    # nothing else -- see the module docstring on which direction eviction
    # fails toward.
    while len(_LAST_NUDGE_STAMPS) > MAX_TRACKED_SESSIONS:
        _ = _LAST_NUDGE_STAMPS.popitem(last=False)
