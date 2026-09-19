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
from pathlib import Path
from typing import Any
import json
import time

from .. import runtime_paths
# The one file-locking and atomic-write implementation in this bundle, reused
# here for the same reason `approval_bypass` reuses it: a second one would be
# a second thing to get right on Windows.
from ..awareness_delivery import _awareness_delivery_lock, _write_delivery_record
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
#
# `_PLAN_LINE_TURNS` below is the third map and the exception to that last
# property, for the reason written at `plan_line_turns_on_record`: it spends a
# budget on a completion-claim GUARD rather than on a nudge, so an evicted or
# untracked row has to restore the guard, not drop it.
# The counter names, here rather than at the module that reads them, because
# the line below has to name the durable ones and two spellings of one string
# in two files is a drift nobody notices until a budget stops persisting.
MUTATIONS_FIELD = "file_mutations"
DIRECT_READS_FIELD = "direct_reads"
PLAN_NUDGES_FIELD = "plan_nudges"
DELEGATION_NUDGES_FIELD = "delegation_nudges"
PLAN_LATCH_FIELD = "plan_declared"
DELEGATION_LATCH_FIELD = "lane_routed"

# What survives the process, and why only these four. `MAX_ENGAGEMENT_NUDGES`
# is two per kind per SESSION, and the map above is per PROCESS -- so a plugin
# host that restarts mid-session hands the session a fresh budget. Measured on
# 2026-09-19: session `20260919_140745_db409e` received four delegation nudges
# against a budget of two, in a 2+2 split bracketing a mid-session `omh
# update`, and `8da9b8` received three. So the two counters that bound the
# spend, and the two latches that end it, are written to a file keyed by
# session and read back once per session.
#
# The work counters are deliberately NOT durable. Losing them across a restart
# restarts a session's progress toward a threshold, which delays a nudge and
# never adds one -- the direction every eviction rule in this module fails in
# -- and persisting them would put a file write on every watched tool call
# instead of on the handful that actually spend something.
DURABLE_ENGAGEMENT_FIELDS = frozenset(
    {PLAN_NUDGES_FIELD, DELEGATION_NUDGES_FIELD, PLAN_LATCH_FIELD, DELEGATION_LATCH_FIELD}
)

ENGAGEMENT_NUDGE_SCHEMA_VERSION = "omh_engagement_nudges/v1"
ENGAGEMENT_NUDGE_FILE = "engagement-nudges.json"
# Distinct `(tool, argument digest)` pairs one session may hold. The threshold
# it feeds is five and the budget is two, so the cap is never the number that
# decides anything; it exists because a session can issue unboundedly many
# distinct searches and this map must not grow with them. Past the cap the
# count saturates, which reads as "at least 64 different reads" -- true, and
# far past every threshold here.
MAX_DISTINCT_DIRECT_READS = 64
# Whether this session's durable counters have been read off disk yet. It
# buys one thing, and only one: the store is read once per session instead of
# on every call that checks a budget. Correctness does not rest on it --
# every writer of a durable field writes through, so re-reading would find
# the same numbers -- which is why it is a marker and not a lock.
#
# It lives INSIDE the counts row rather than in a map beside it so that it is
# evicted with the counters it describes. Kept separately, a row evicted from
# the bounded map below while its marker survived would read as loaded and
# empty, which restores a spent budget: the one direction eviction here must
# not fail in. Never a counter; `engagement_count` is only ever asked for the
# fields above.
_LOADED_MARKER = "loaded_from_store"

_ENGAGEMENT_COUNTS: "OrderedDict[str, dict[str, int]]" = OrderedDict()

# Distinct direct reads per session, as an ordered set of digests. A loop
# repeating one search adds one member and then nothing, which is the whole
# point: five identical searches are one search, and must not spend a budget
# meant for a search pass (#1701).
_DISTINCT_DIRECT_READS: "OrderedDict[str, OrderedDict[str, bool]]" = OrderedDict()

# Session ids the host reported as delegated children (`subagent_start`'s
# `child_session_id`). A child runs under its OWN session id, so per-session
# keying alone does not separate it from the orchestrator, and the tool-result
# seam the nudges ride carries no agent identity at all. This is the only
# record-based way this bundle can tell the two apart.
_DELEGATED_SESSIONS: "OrderedDict[str, bool]" = OrderedDict()

# The third thing, and the one whose eviction fails the OTHER way. The value
# is `(plan stamp, turns already rendered against it)`: the reconciliation
# rule spends a per-plan turn budget and must come back in full the moment the
# plan record is written again, so the stamp is kept beside the count rather
# than the count alone.
_PLAN_LINE_TURNS: "OrderedDict[str, tuple[str, int]]" = OrderedDict()


def bump_engagement_count(session_id: object, field: str, *, omh_home: str = "") -> int:
    """Increment one counter for this session and return its new value.

    Returns 0 for a session with no usable id rather than sharing an untracked
    row, for the reason the stamps above give: measuring one session's work
    against another session's plan is worse than not measuring at all.

    A durable field is written through to the store as well, so a plugin-host
    restart cannot hand a session a second budget.
    """
    key = _session_key(session_id)
    if not key:
        return 0
    row = _engagement_row(key, omh_home)
    _ENGAGEMENT_COUNTS.pop(key, None)
    row[field] = int(row.get(field, 0)) + 1
    _ENGAGEMENT_COUNTS[key] = row
    while len(_ENGAGEMENT_COUNTS) > MAX_TRACKED_SESSIONS:
        _ = _ENGAGEMENT_COUNTS.popitem(last=False)
    if field in DURABLE_ENGAGEMENT_FIELDS:
        _persist_engagement_row(key, row, omh_home)
    return row[field]


def engagement_count(session_id: object, field: str, *, omh_home: str = "") -> int:
    """Read one counter, loading this session's durable fields if need be.

    Reading a durable field is what the budget checks do, so the load has to
    happen here as well as on a write -- otherwise the first check after a
    restart reads zero out of an empty process map and spends a nudge the
    session already used.
    """
    key = _session_key(session_id)
    if not key:
        return 0
    if field in DURABLE_ENGAGEMENT_FIELDS:
        return int(_engagement_row(key, omh_home).get(field, 0))
    return int((_ENGAGEMENT_COUNTS.get(key) or {}).get(field, 0))


def latch_engagement(session_id: object, field: str, *, omh_home: str = "") -> None:
    """Record that this session did the thing, for the rest of its life.

    A latch, not a decay: once a plan is declared or a lane is routed, the
    nudge that asked for it has no remaining question to ask.
    """
    _ = bump_engagement_count(session_id, field, omh_home=omh_home)


def record_distinct_direct_read(session_id: object, key: str) -> int:
    """Admit one `(tool, argument digest)` pair and return the distinct count.

    The counter this replaced counted CALLS, so five different greps and one
    grep five times were the same event to it. Measured: session
    `20260919_140745_db409e` issued 203 `search_files` calls, the large
    majority identical, and the delegation nudge spent its whole budget on
    them and was silent for the remaining ~180 (#1701). A loop is not a
    search pass and must not read as one.

    ``key`` is built from the digest the repeat guard already computes for the
    same call, so there is one canonicalization of a call's arguments in this
    bundle and not a second one here.
    """
    session = _session_key(session_id)
    if not session or not key:
        return 0
    seen = _DISTINCT_DIRECT_READS.pop(session, None) or OrderedDict()
    seen.pop(key, None)
    seen[key] = True
    while len(seen) > MAX_DISTINCT_DIRECT_READS:
        _ = seen.popitem(last=False)
    _DISTINCT_DIRECT_READS[session] = seen
    while len(_DISTINCT_DIRECT_READS) > MAX_TRACKED_SESSIONS:
        _ = _DISTINCT_DIRECT_READS.popitem(last=False)
    return len(seen)


def engagement_nudge_store_path(omh_home: str = "") -> Path:
    root = Path(omh_home).expanduser() if omh_home else runtime_paths.default_omh_home()
    return root / "runtime" / ENGAGEMENT_NUDGE_FILE


def _engagement_row(key: str, omh_home: str) -> dict[str, int]:
    """This session's counters, with its durable fields loaded exactly once.

    The file is read on a session's first durable touch and never again in
    this process: after that the map IS the current state, because every
    writer of those fields goes through `bump_engagement_count` and writes
    through. A read that fails leaves the row empty, which restores the
    pre-#1701 behaviour for that session -- a fresh budget -- rather than
    silencing a nudge on an unreadable file.
    """
    row = _ENGAGEMENT_COUNTS.get(key)
    if row is not None and row.get(_LOADED_MARKER):
        return row
    row = dict(row or {})
    row[_LOADED_MARKER] = 1
    for field, value in _read_engagement_store(omh_home).get(key, {}).items():
        if field in DURABLE_ENGAGEMENT_FIELDS:
            row[field] = max(int(row.get(field, 0)), value)
    _ENGAGEMENT_COUNTS.pop(key, None)
    _ENGAGEMENT_COUNTS[key] = row
    while len(_ENGAGEMENT_COUNTS) > MAX_TRACKED_SESSIONS:
        _ = _ENGAGEMENT_COUNTS.popitem(last=False)
    return row


def _read_engagement_store(omh_home: str) -> dict[str, dict[str, int]]:
    """Every stored session's durable counters, or {} when none can be read."""
    try:
        raw: Any = json.loads(engagement_nudge_store_path(omh_home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    sessions = raw.get("sessions") if isinstance(raw, dict) else None
    rows: dict[str, dict[str, int]] = {}
    for session, item in (sessions.items() if isinstance(sessions, dict) else ()):
        if not isinstance(session, str) or not isinstance(item, dict):
            continue
        counts = {
            field: int(value)
            for field, value in item.items()
            if field in DURABLE_ENGAGEMENT_FIELDS
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
        }
        if counts:
            rows[session] = {**counts, "ts": _row_stamp(item)}
    return rows


def _row_stamp(item: dict[str, Any]) -> int:
    value = item.get("ts")
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _persist_engagement_row(key: str, row: dict[str, int], omh_home: str) -> None:
    """Write this session's durable counters back. Best-effort, like every
    writer in this bundle: losing one costs a session's budget its memory
    across a restart, which is the behaviour that shipped, while raising here
    would break the seam that feeds the model. Nothing else is written -- the
    work counters and the loaded marker stay in the process."""
    path = engagement_nudge_store_path(omh_home)
    counters = {field: int(row.get(field, 0)) for field in sorted(DURABLE_ENGAGEMENT_FIELDS)}
    try:
        with _awareness_delivery_lock(path):
            stored = _read_engagement_store(omh_home)
            stored[key] = {**counters, "ts": int(time.time())}
            # Oldest first, the same LRU the process map uses, so the two
            # cannot disagree about which session is worth remembering.
            if len(stored) > MAX_TRACKED_SESSIONS:
                newest = sorted(stored.items(), key=lambda item: item[1].get("ts", 0), reverse=True)
                stored = dict(newest[:MAX_TRACKED_SESSIONS])
            _write_delivery_record(
                path,
                {
                    "schema_version": ENGAGEMENT_NUDGE_SCHEMA_VERSION,
                    "sessions": stored,
                    "privacy": "metadata_only",
                },
            )
    except (OSError, ValueError, TypeError):
        return


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


def plan_line_turns_on_record(session_id: object, stamp: object) -> int:
    """Turns this session's plan line already rendered against ``stamp``, then count this one.

    Returns the count BEFORE this turn, so the first turn of a plan record
    answers 0. A stamp that differs from the one remembered is a plan that was
    written again, and the count restarts at 0 for it -- the only thing that
    restores the full reconciliation rule, and a record comparison rather than
    anything read out of the conversation.

    A session with no usable id answers 0 every time and stores nothing. That
    is deliberate and it is the opposite direction from the counters above: an
    untracked session keeps the guard in full forever rather than sharing a
    row with another session's plan. Eviction lands in the same place, since
    an evicted row is indistinguishable from a first turn.
    """
    key = _session_key(session_id)
    stamp_text = _stamp_text(stamp)
    if not key:
        return 0
    previous = _PLAN_LINE_TURNS.pop(key, None)
    already = previous[1] if previous is not None and previous[0] == stamp_text else 0
    _PLAN_LINE_TURNS[key] = (stamp_text, already + 1)
    while len(_PLAN_LINE_TURNS) > MAX_TRACKED_SESSIONS:
        _ = _PLAN_LINE_TURNS.popitem(last=False)
    return already


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

    The durable store is NOT cleared, because it is not process state: it
    lives under an OMH home, and a test that wants a fresh one points the
    calls at a fresh home the way every other file-backed test here does.
    Deleting a file this cannot see the path of would be a guess.
    """
    _LAST_NUDGE_STAMPS.clear()
    _ENGAGEMENT_COUNTS.clear()
    _DISTINCT_DIRECT_READS.clear()
    _DELEGATED_SESSIONS.clear()
    _PLAN_LINE_TURNS.clear()


def _remember(key: str, stamp: str) -> None:
    _ = _LAST_NUDGE_STAMPS.pop(key, None)
    _LAST_NUDGE_STAMPS[key] = stamp
    # Oldest first: the row least recently nudged is the one whose turn is most
    # likely already over. Losing it costs that session the extra nudges and
    # nothing else -- see the module docstring on which direction eviction
    # fails toward.
    while len(_LAST_NUDGE_STAMPS) > MAX_TRACKED_SESSIONS:
        _ = _LAST_NUDGE_STAMPS.popitem(last=False)
