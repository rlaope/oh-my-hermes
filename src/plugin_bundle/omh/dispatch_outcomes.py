"""Finished dispatches the session's own plan has not acknowledged yet.

A dispatched unit ending is an event, not a notification to summarize. The
2026-09-11 incident had a supervising session answer each completion with a
status report and end the turn: the result was never verified, the plan was
never updated, and the next item never started. Nothing on the session's
context said a dispatch had ended and nobody had written it down.

This module is that missing statement. It joins two records the runtime
already keeps -- the fanout dispatch summary (which units finished, when, and
how) and the session's todo (what the session says it is doing) -- and reports
the units that finished AFTER the plan was last touched and that no plan item
mentions. Reading only; it never advances a unit, writes a record, or reports
what a run did. `next` names the verb the supervisor owes the outcome, and
naming it is the whole point: "a dispatch ended" with no verb reads as news.

Tolerant by construction. `unit_state` is written by the run-state lane and
may be absent on a summary this reader finds; every field is optional and an
unreadable or half-written summary is skipped rather than raised.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
import stat
from pathlib import Path
from typing import Any

try:  # The shared unit vocabulary, whenever the OMH package is importable.
    from omh.coding.unit_execution_state import (
        UNIT_EXECUTION_STATES,
        UNIT_STATE_FAILED,
        UNIT_STATE_VERIFIED,
        UNIT_STUCK_STATES,
    )
except ImportError:  # pragma: no cover - standalone plugin hosts have no omh package.
    # Deliberately NOT a local copy of the state names: a second list is the
    # parallel vocabulary the shared module exists to prevent, and it would
    # drift the moment a state is added there. A host with no `omh` package
    # also has no `omh coding fanout` to write a dispatch summary, so there is
    # no unit here whose state these could have classified. `None` rather than
    # `""` because an absent `unit_state` reads as `""` -- a sentinel that
    # matched it would route every stateless unit to `advance_next_item`.
    UNIT_EXECUTION_STATES: tuple[str, ...] = ()
    UNIT_STUCK_STATES: frozenset[str] = frozenset()
    UNIT_STATE_VERIFIED = None
    UNIT_STATE_FAILED = None

from .fanout_scan import RECENT_FANOUT_DIR_LIMIT, newest_fanout_dirs, path_mtime
from .runtime_reader import (
    # The hardened read (symlink-refusing, size-bounded, confined to the home
    # root) every other bundle reader uses. Restating it here would fork a
    # security-relevant reader for one more caller.
    _read_hud_json,
    _expand_path,
    default_omh_home,
    read_omh_todo,
)

DISPATCH_OUTCOME_SCHEMA_VERSION = "omh_dispatch_outcome/v1"

# The dispatch summary this reader trusts; a mismatch is skipped, never
# guessed at.
_FANOUT_DISPATCH_SCHEMA_VERSION = "fanout_dispatch_summary/v1"
_FANOUT_ID_RE = re.compile(r"^fanout-[0-9a-f]{12}$")

# Bounds. The reminder runs on every turn, so the scan keeps only the newest
# few fanouts (by dispatch-summary mtime) and reads a bounded number of unit
# rows out of each -- the same shape `_hud_local_fanout_record` uses, tighter,
# because this surface only ever renders a handful of lines. The directory
# bound now lives in `fanout_scan` because the running-work board shares it;
# re-exported here so importers of this module's name keep working.
UNIT_ROW_LIMIT = 64
OUTCOME_LIMIT = 20
# An outcome older than this is history, not an unanswered event: a plan left
# open overnight must not resurrect yesterday's dispatches every turn.
OUTCOME_MAX_AGE_SECONDS = 24 * 60 * 60

# Verbs. Exactly one is owed per finished unit, and which one is decided by
# what the summary observed -- never by the executor's own report.
NEXT_VERIFY_RESULT = "verify_result"
NEXT_RECORD_BLOCKED = "record_blocked"
NEXT_ADVANCE_NEXT_ITEM = "advance_next_item"
NEXT_RUN_RECOVERY = "run_recovery"

# Failure kinds that retrying under the same conditions cannot clear: the
# account said no, or the credentials did. These are recorded as blocked with
# their reason, never re-dispatched.
_BLOCKED_FAILURE_KINDS = frozenset({"limit_shaped", "auth_shaped"})



def unacknowledged_outcomes(
    omh_home: str = "",
    hermes_home: str = "",
    session_ref: str = "",
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Finished dispatch units this session's plan has not written down.

    Returns newest first, bounded by `OUTCOME_LIMIT`. Empty whenever there is
    no established plan to acknowledge against, nothing finished since the
    plan was last touched, or every finished unit is already named on it.
    Never raises: a reminder that could fail the turn it decorates would be
    worse than a missing line.
    """
    moment = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        todo = read_omh_todo(omh_home or None, hermes_home or None, session_ref=session_ref)
    except (OSError, ValueError, TypeError):
        return []
    # A finished plan still owes its dispatches an answer -- that is exactly
    # the "all done" claim the incident produced -- so `all_done` counts.
    # `absent` and `stale` do not: with no plan of this session's own, every
    # run on the machine would read as unacknowledged.
    if todo.get("status") not in {"established", "all_done"}:
        return []
    plan_updated_at = _parse_timestamp(todo.get("updated_at"))
    if plan_updated_at is None:
        return []
    acknowledged = _acknowledged_text(todo)

    home = _expand_path(omh_home) if omh_home else default_omh_home()
    outcomes: list[dict[str, Any]] = []
    for fanout_dir in _recent_fanout_dirs(home):
        summary = _read_hud_json(fanout_dir / "dispatch_summary.json", root=home)
        if summary.get("schema_version") != _FANOUT_DISPATCH_SCHEMA_VERSION:
            continue
        raw_units = summary.get("units")
        if not isinstance(raw_units, list):
            continue
        for entry in raw_units[:UNIT_ROW_LIMIT]:
            outcome = _outcome_for_unit(
                entry,
                fanout_id=fanout_dir.name,
                plan_updated_at=plan_updated_at,
                now=moment,
                acknowledged=acknowledged,
            )
            if outcome is not None:
                outcomes.append(outcome)
    outcomes.sort(key=lambda outcome: str(outcome.get("finished_at", "")), reverse=True)
    return outcomes[:OUTCOME_LIMIT]


def _outcome_for_unit(
    entry: Any,
    *,
    fanout_id: str,
    plan_updated_at: datetime,
    now: datetime,
    acknowledged: str,
) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    finished_at_text = str(entry.get("finished_at", "") or "")
    finished_at = _parse_timestamp(finished_at_text)
    if finished_at is None or finished_at <= plan_updated_at:
        return None
    if (now - finished_at).total_seconds() > OUTCOME_MAX_AGE_SECONDS:
        return None
    unit_id = str(entry.get("unit_id", "") or "")
    if not unit_id:
        return None
    run_ref = str(entry.get("run_ref", "") or "") or f"{fanout_id}-{unit_id}"
    if _is_referenced(acknowledged, run_ref) or _is_referenced(acknowledged, unit_id):
        return None
    outcome: dict[str, Any] = {
        "schema_version": DISPATCH_OUTCOME_SCHEMA_VERSION,
        "run_ref": run_ref,
        "unit_id": unit_id,
        "finished_at": finished_at_text,
        "next": _next_verb(entry),
    }
    unit_state = str(entry.get("unit_state", "") or "")
    if unit_state in UNIT_EXECUTION_STATES:
        outcome["unit_state"] = unit_state
    failure_kind = str(entry.get("failure_kind", "") or "")
    if failure_kind:
        outcome["failure_kind"] = failure_kind
    if "unit_state" not in outcome and not failure_kind:
        # Neither lane wrote a state: say which rung the summary observed
        # rather than leaving the row with nothing to read.
        outcome["status"] = str(entry.get("status", "") or "unknown")
    return outcome


def _next_verb(entry: dict[str, Any]) -> str:
    """The one verb this finished unit owes the supervisor.

    Ordered by what cannot wait. A blocked outcome is recorded with its
    reason before anything else happens, because re-dispatching it under the
    same account or the same credentials repeats the failure exactly.
    """
    unit_state = str(entry.get("unit_state", "") or "")
    failure_kind = str(entry.get("failure_kind", "") or "")
    if unit_state in UNIT_STUCK_STATES or failure_kind in _BLOCKED_FAILURE_KINDS:
        return NEXT_RECORD_BLOCKED
    if unit_state == UNIT_STATE_VERIFIED or _bool_field(entry, "unit_verification_observed"):
        return NEXT_ADVANCE_NEXT_ITEM
    if failure_kind or unit_state == UNIT_STATE_FAILED or not _bool_field(entry, "process_succeeded"):
        return NEXT_RUN_RECOVERY
    # Exit 0 with no observed verification. Not success yet: the result record
    # has to be read before the plan can say this item is done.
    return NEXT_VERIFY_RESULT


def _bool_field(entry: dict[str, Any], key: str) -> bool:
    value = entry.get(key)
    return value is True


def _acknowledged_text(todo: dict[str, Any]) -> str:
    """Everything the plan says, folded once, for the reference check."""
    parts = [str(todo.get("title", "") or "")]
    items = todo.get("items")
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            parts.append(str(item.get("text", "") or ""))
            parts.append(str(item.get("phase", "") or ""))
    return " ".join(parts).casefold()


def _is_referenced(acknowledged: str, reference: str) -> bool:
    return bool(reference) and reference.casefold() in acknowledged


def _recent_fanout_dirs(home: Path) -> list[Path]:
    """The newest fanout directories by dispatch-summary mtime, bounded."""
    root = home / "coding" / "fanout"
    try:
        root_stat = root.lstat()
    except OSError:
        return []
    if not stat.S_ISDIR(root_stat.st_mode):
        return []
    listed, dirs, _omitted = newest_fanout_dirs(
        root,
        limit=RECENT_FANOUT_DIR_LIMIT,
        activity_of=_summary_activity,
        name_filter=_FANOUT_ID_RE.fullmatch,
    )
    return dirs if listed else []


def _summary_activity(fanout_dir: Path) -> float | None:
    """When this fanout last wrote a dispatch summary, or None if it never did.

    A fanout with no summary has nothing this reader can report on, so it is
    dropped from the scan rather than ordered into it -- the same condition
    the old `<= 0.0` guard expressed, now stated as an absence. A stamp at or
    before the epoch stays dropped for the same reason it was: it is not a
    time anything wrote.
    """
    activity = path_mtime(fanout_dir / "dispatch_summary.json")
    return activity if activity is not None and activity > 0.0 else None


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
