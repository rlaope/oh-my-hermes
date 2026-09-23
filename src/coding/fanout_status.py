"""Read-only per-unit roster for one fanout, projected from journal events.

This module observes; it never acts. It writes no state file, appends no
observation event, and offers no revive/steer/kill surface: a roster that could
restart a unit would be a control plane, and the only durable evidence this
layer trusts is what the dispatcher already recorded.

Only the observation journal supplies lifecycle and session evidence. Executor
stdout, dispatch summaries, and in-flight markers are NOT evidence inputs for
any lifecycle rung -- `lifecycle_state` still advances on journal events alone,
and nothing below can move it.

One narrowly-scoped exception, added for the supervisor poll loop: the
`unit_state` / `terminal` / `progress` fields answer "is this unit's WORK
moving, and is it over?", which the journal cannot answer while a unit is still
running. Those three come from the in-flight marker while the unit is in flight
and from the dispatch summary record after it exits, and they are kept in their
own keys so no reader can mistake them for a ladder rung. The marker is read
through `inflight.read_inflight_markers` -- the same single reader the status
board uses -- rather than a second parser.

Copy-only session actions additionally require a bounded frozen-contract read
and fresh, read-only workspace and executable observations. The unit rows therefore carry exactly what the journal knows:
which rung of the dispatch ladder has dispatcher-observed backing, who ran it,
where, how stale the last event is, and how many evidence refs it named.

Units are discovered through the `run_ref` convention frozen by
`build_fanout_contract` (`{fanout_id}-{unit_id}`, src/coding/fanout.py), so the
roster needs no contract read to know which runs belong to a fanout.

The journal is read in full, once, and never through `show_run`'s tail-bounded
view: that surface defaults to the last 20 events per run
(`DEFAULT_RUN_HISTORY_LIMIT`), and on a busy run the verification receipt is
exactly the event that falls off the end. A lifecycle conclusion drawn from a
tail would silently under-report a verified unit, so this projection reads every
event (the equivalent of `history_limit=None`) and pays one file read for the
whole roster instead of one per unit.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Callable, Mapping

from ..system.paths import OmhPaths
from ..workflows.observation_journal import (
    canonical_observation_event,
    failure_diagnostic_text,
    project_bound_failure_diagnostic,
    project_run_failure_diagnostic,
    project_run_lifecycle,
    read_observation_events_result,
)
from .fanout_contracts import FANOUT_ID_PATTERN
from .fanout_clarification import clarification_evidence, read_clarification, clarification_path, clarification_state
from .fanout_failure_diagnostics import is_object_list, is_string_map
from .fanout_executor_sessions import (
    duplicate_session_references, observe_session_workspace, project_session_resume,
    read_session_receipt,
)
from .executor_readiness import observe_session_binary
from .fanout_capacity import read_capacity_fields
from .fanout_artifacts import fanout_contract_digest, fanout_dispatch_summary_path
from ..system.local_store import read_json_object_result
from .inflight import read_inflight_markers
from .unit_execution_state import UNIT_STUCK_STATES, is_terminal
from ..workflows.observation_journal import project_run_executor_session
import json

FANOUT_STATUS_SCHEMA_VERSION = "fanout_status_roster/v1"
FANOUT_STATUS_CLAIM_BOUNDARY = (
    "A fanout status roster projects dispatcher-observed journal events; `lifecycle_state` advances on "
    "those alone and never on an executor's own report. The `unit_state` / `terminal` / `progress` keys "
    "are a separate reading of whether the work is moving, taken from the in-flight marker while a unit "
    "runs and the dispatch summary after it exits, and they move no rung. It is not verification, review, "
    "CI, merge-readiness, or merge evidence."
)
# The ladder todo 3 froze for dispatch summaries, restated here as the roster's
# display vocabulary plus the two pre-success rungs a roster must be able to
# show: a unit nobody has dispatched yet, and one dispatched without an
# observed successful result.
FANOUT_UNIT_STATES = (
    "not_dispatched",
    "input_required",
    "dispatched_not_succeeded",
    "process_succeeded",
    "result_schema_valid",
    "unit_verification_observed",
    "integration_ready",
)
_UNKNOWN = "unknown"
# Marker read ceiling for one fanout. `read_inflight_markers` filters by
# fanout id BEFORE this slice, so a busy machine's other fanouts cannot push
# this one's units off the end; the number only bounds a single fanout's own
# unit count, which the contract builder already caps well below it.
_MARKER_READ_LIMIT = 200

_FANOUT_ID_RE = re.compile(FANOUT_ID_PATTERN)
# Journal events that name a dispatched unit. `worker_dispatch` /
# `worker_result` are the legacy spellings; `canonical_observation_event`
# already folds them, so both journal generations land on the same rung.
_DISPATCH_EVENTS = ("executor_dispatch_observed", "worktree_creation_observed")
# Written by the sidecar intake in fanout_dispatch; folded here so the roster
# reports the rung.
_RESULT_VALIDATED_EVENT = "unit_result_validated"


def project_fanout_status(paths: OmhPaths, fanout_id: str, *, unit_id: str | None = None) -> dict[str, Any]:
    """Project one fanout's unit roster from the observation journal.

    Raises `ValueError` naming the id when it is not a fanout id shape, or when
    the journal has never recorded a single event for it: a roster that silently
    rendered an empty table for a typo would report "nothing happened" for a
    fanout that does not exist.
    """
    validated_id = _validated_fanout_id(fanout_id)
    events, read_errors = read_observation_events_result(paths)
    fanout_events = [
        event for event in events if isinstance(event, Mapping) and _names_fanout(event, validated_id)
    ]
    if not fanout_events:
        raise ValueError(f"unknown fanout id: {validated_id} (no journal events name it)")

    events_by_unit: dict[str, list[dict[str, Any]]] = {}
    for event in fanout_events:
        event_unit_id = _unit_id_for_event(event, validated_id)
        if event_unit_id:
            events_by_unit.setdefault(event_unit_id, []).append(dict(event))

    units = [
        _unit_row(unit_id, events_by_unit[unit_id], validated_id)
        for unit_id in sorted(events_by_unit)
    ]
    _apply_merge_order_position(units)
    duplicates = duplicate_session_references(event.get('executor_session') for event in events)
    contract: object = None
    contract_path = fanout_dispatch_summary_path(paths, validated_id).with_name('fanout_contract.json')
    try:
        if not contract_path.is_symlink() and contract_path.stat().st_size <= 1024 * 1024:
            with contract_path.open('rb') as stream:
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) <= 1024 * 1024:
                decode: Callable[[bytes], object] = json.loads
                contract = decode(raw)
    except (OSError, ValueError, RecursionError):
        contract = None  # Legacy journal-only status stays readable; resume is unavailable.
    for unit in units:
        request = read_clarification(clarification_path(paths, validated_id, str(unit['unit_id'])))
        clarification = clarification_evidence(request, events_by_unit[str(unit['unit_id'])])
        if clarification is not None and request is not None:
            unit['clarification'] = clarification
            unit['clarification_state'] = clarification_state(request)
            if clarification['redispatch'] == 'none':
                unit['lifecycle_state'] = 'input_required'
                unit['process_succeeded'] = False
                unit['unit_verification_observed'] = False
                unit['integration_ready'] = False
        unit['resume'] = _resume_for_unit(unit, contract, duplicates)
        current = None
        seen: set[str] = set()
        capacity: dict[str, object] = {}
        for event in events_by_unit[str(unit['unit_id'])]:
            attempt = event.get('attempt_id')
            if isinstance(attempt, str) and attempt != current:
                if attempt in seen:
                    continue
                seen.add(attempt)
                current, capacity = attempt, {}
            if attempt == current and event.get('event') == 'capacity_admission_observed':
                capacity = read_capacity_fields(event)
        unit.update(capacity)
    _apply_unit_progress(paths, validated_id, units)
    if unit_id is not None:
        units = [unit for unit in units if unit['unit_id'] == unit_id]
        if not units:
            raise ValueError(f'unknown unit: {unit_id}')
    roster: dict[str, Any] = {
        "schema_version": FANOUT_STATUS_SCHEMA_VERSION,
        "fanout_id": validated_id,
        "unit_count": len(units),
        "units": units,
        "integration_ready_units": [
            unit["unit_id"] for unit in units if unit["lifecycle_state"] == "integration_ready"
        ],
        "journal_event_count": len(fanout_events),
        # The supervisor poll loop's own stop condition, computed once rather
        # than re-derived by every caller: a fanout with no units is NOT done,
        # because "nothing to wait for" and "everything finished" are different
        # answers and only one of them means the work happened.
        "all_units_terminal": bool(units) and all(bool(unit.get("terminal")) for unit in units),
        "stuck_units": [
            str(unit["unit_id"]) for unit in units if unit.get("unit_state") in UNIT_STUCK_STATES
        ],
        "claim_boundary": FANOUT_STATUS_CLAIM_BOUNDARY,
    }
    if read_errors:
        roster["journal_errors"] = read_errors
    return roster


def render_fanout_status_text(roster: Mapping[str, Any]) -> str:
    """Render the roster as plain English lines, one per unit."""
    fanout_id = str(roster.get("fanout_id", ""))
    units: list[Mapping[str, object]] = [unit for unit in roster.get("units", []) if isinstance(unit, Mapping)]
    lines = [f"Fanout {fanout_id}: {len(units)} unit(s) observed in the journal."]
    if not units:
        lines.append("No unit events recorded yet; nothing has been dispatched under this fanout id.")
    for unit in units:
        lines.append(
            f"- {unit.get('unit_id', _UNKNOWN)}: {unit.get('lifecycle_state', _UNKNOWN)} "
            f"| owner {unit.get('owner', _UNKNOWN)} "
            f"| branch {unit.get('branch', _UNKNOWN)} "
            f"| worktree {unit.get('worktree_path', _UNKNOWN)} "
            f"| last event {unit.get('last_event', _UNKNOWN)} "
            f"{_age_phrase(unit.get('last_event_age_seconds'))} "
            f"| evidence refs {unit.get('evidence_ref_count', 0)}"
        )
        progress_line = _unit_progress_phrase(unit)
        if progress_line:
            lines.append(f"  work: {progress_line}")
        capacity = read_capacity_fields(unit).get('capacity')
        if is_string_map(capacity):
            lines.append(f"  capacity: {capacity['status']}; next action: {capacity['next_action']}")
        session = read_session_receipt(unit.get('executor_session')).receipt
        if session is not None:
            lines.append(f'  session: {session.state} ({session.reason}) {session.reference or ""}')
        resume = unit.get('resume')
        if is_string_map(resume):
            lines.append('  resume: ' + str(resume.get('shell_command') or resume.get('reason')))
        diagnostic = project_bound_failure_diagnostic(
            unit, fanout_id=fanout_id, unit_id=str(unit.get("unit_id", "")),
            run_ref=str(unit.get("run_ref", "")),
        )
        if diagnostic is not None:
            lines.append(f"  diagnostic: {failure_diagnostic_text(diagnostic)}")
    stuck = [str(name) for name in roster.get("stuck_units", []) if name]
    if stuck:
        # Named on its own line, because the per-unit rows scroll and this is
        # the line a supervisor has to act on.
        lines.append(f"Stuck, needs intervention: {', '.join(stuck)}")
    lines.append(str(roster.get("claim_boundary", FANOUT_STATUS_CLAIM_BOUNDARY)))
    return "\n".join(lines)


def _unit_progress_phrase(unit: Mapping[str, object]) -> str:
    """`progress_stalled (no_new_output, 1920s since new output)`, or "".

    Empty when nothing observed the unit's work, so a roster projected from a
    journal that predates progress evidence renders exactly as it did before.
    """
    state = str(unit.get("unit_state", "") or "")
    if not state or state == _UNIT_STATE_UNKNOWN:
        return ""
    progress = unit.get("progress")
    parts: list[str] = []
    if isinstance(progress, Mapping):
        reason = str(progress.get("reason", "") or "")
        if reason:
            parts.append(reason)
        stalled = progress.get("seconds_since_new_output")
        if isinstance(stalled, int) and not isinstance(stalled, bool) and stalled > 0:
            parts.append(f"{stalled}s since new output")
    detail = f" ({', '.join(parts)})" if parts else ""
    return f"{state}{detail}" if unit.get("terminal") else f"{state}{detail}, not terminal"


# `unit_state` when nothing has observed the unit's work yet. Distinct from
# every real state: absent evidence is not `running`, and it is not terminal.
_UNIT_STATE_UNKNOWN = "unknown"
# Where a row's `unit_state` came from, so a reader can tell a live reading
# from a post-exit record from no reading at all.
_PROGRESS_SOURCES = ("inflight_marker", "dispatch_summary", "none")


def _apply_unit_progress(paths: OmhPaths, fanout_id: str, units: list[dict[str, Any]]) -> None:
    """Attach `unit_state`, `terminal`, and `progress` to every roster row.

    The supervisor poll loop (`omh coding fanout status --json`, driven by the
    ulw-maestro skill) needs two things the journal cannot give it: whether a
    still-running unit's WORK is moving, and whether a unit is over. Neither is
    a ladder rung and neither touches `lifecycle_state` -- see the module
    docstring's exception.

    An in-flight marker wins over the dispatch summary for the same unit, the
    same precedence the status board's `SOURCE_ORDER` already uses: a marker
    means this unit is in flight NOW, and a summary row from an earlier
    dispatch of the same id must not report over it.

    Best-effort: an unreadable marker directory or summary leaves every row at
    `unknown`, which is honest and keeps a poll loop waiting rather than
    concluding the work finished.
    """
    from_markers = _marker_progress(paths, fanout_id)
    from_summary = _summary_progress(paths, fanout_id)
    for unit in units:
        row_id = str(unit.get("unit_id", ""))
        observed = from_markers.get(row_id) or from_summary.get(row_id)
        if observed is None:
            state, reason, stalled, source = _UNIT_STATE_UNKNOWN, "", None, "none"
        else:
            state, reason, stalled, source = observed
        unit["unit_state"] = state
        unit["unit_state_source"] = source
        unit["terminal"] = _row_is_terminal(state, source)
        unit["progress"] = {
            "reason": reason,
            # None, never 0, when no assessment recorded one: a zero here
            # would read as "output moved this instant".
            "seconds_since_new_output": stalled,
        }


def _row_is_terminal(state: str, source: str) -> bool:
    """Whether anything will ever move this unit again.

    The SOURCE decides, not the state word alone. `is_terminal` answers for the
    execution vocabulary, where every stuck state is non-terminal because a
    stuck unit is one a supervisor can still act on. A dispatch-summary row is
    different: that file is written once, after the whole dispatch has ended
    (see the write site at the foot of `dispatch_fanout`), so a unit recorded
    in it is over whatever word it carries.

    The case that forces this is the workspace preflight (#1489): a unit
    refused before its spawn is recorded with a stuck `unit_state`, no marker
    and no progress evidence, and nothing exists to move it. Reporting it as
    non-terminal would hang a supervisor's poll loop forever on a unit that
    never started -- the precise failure this whole lane exists to prevent.

    A marker means the unit is in flight NOW, so its state is read literally.
    """
    if source == "dispatch_summary":
        return True
    return is_terminal(state)


def _marker_progress(paths: OmhPaths, fanout_id: str) -> dict[str, tuple[str, str, int | None, str]]:
    """Live progress readings, keyed by unit id, from this fanout's markers."""
    rows: dict[str, tuple[str, str, int | None, str]] = {}
    for marker in read_inflight_markers(paths, fanout_id=fanout_id, limit=_MARKER_READ_LIMIT):
        if not isinstance(marker, Mapping) or marker.get("marker_status") != "present":
            continue
        unit_id = str(marker.get("unit_id", "") or "")
        state = str(marker.get("unit_state", "") or "")
        if not unit_id or not state:
            # A marker written before the first stdout snapshot carries no
            # state. It proves a spawn, not that the work is moving, so it
            # contributes nothing here rather than a fabricated `running`.
            continue
        rows[unit_id] = (
            state,
            str(marker.get("state_reason", "") or ""),
            _non_negative_int(marker.get("stalled_for_seconds")),
            "inflight_marker",
        )
    return rows


def _summary_progress(paths: OmhPaths, fanout_id: str) -> dict[str, tuple[str, str, int | None, str]]:
    """Post-exit progress readings, keyed by unit id, from the dispatch summary."""
    summary, error = read_json_object_result(fanout_dispatch_summary_path(paths, fanout_id))
    if error is not None or not isinstance(summary, Mapping):
        return {}
    entries = summary.get("units")
    if not isinstance(entries, list):
        return {}
    rows: dict[str, tuple[str, str, int | None, str]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        unit_id = str(entry.get("unit_id", "") or "")
        state = str(entry.get("unit_state", "") or "")
        if not unit_id or not state:
            # A record written before this contract existed. Absent, not
            # `unknown`, so the caller's fallback chain stays in one place.
            continue
        progress = entry.get("progress")
        rows[unit_id] = (
            state,
            # `unit_state_reason` is what a dispatched unit's record carries.
            # A unit refused before its spawn never reached that code and
            # carries the preflight's own `reason` instead, so both are read
            # rather than the pre-spawn case rendering with no explanation at
            # all; `failure_kind` is the last resort, and is still a word.
            str(
                entry.get("unit_state_reason", "")
                or entry.get("reason", "")
                or entry.get("failure_kind", "")
                or ""
            ),
            _non_negative_int(progress.get("stalled_for_seconds")) if isinstance(progress, Mapping) else None,
            "dispatch_summary",
        )
    return rows


def _non_negative_int(value: object) -> int | None:
    """A whole-second count, or None. A string marker field parses; junk does not."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def _validated_fanout_id(value: object) -> str:
    fanout_id = str(value or "")
    if not _FANOUT_ID_RE.match(fanout_id):
        raise ValueError(f"invalid fanout id: {fanout_id!r} (expected {FANOUT_ID_PATTERN})")
    return fanout_id


def _names_fanout(event: Mapping[str, Any], fanout_id: str) -> bool:
    run_id = str(event.get("run_id", "") or event.get("target_id", ""))
    return run_id == fanout_id or run_id.startswith(f"{fanout_id}-")


def _unit_id_for_event(event: Mapping[str, Any], fanout_id: str) -> str:
    """The unit a journal event belongs to, or "" for fanout-level events.

    `worker_ref` is the current write site's field. Legacy events predate it, so
    the run id's frozen `{fanout_id}-{unit_id}` suffix is the fallback rather
    than a reason to drop the row.
    """
    worker_ref = str(event.get("worker_ref", "") or "")
    if worker_ref:
        return worker_ref
    run_id = str(event.get("run_id", "") or event.get("target_id", ""))
    prefix = f"{fanout_id}-"
    return run_id[len(prefix):] if run_id.startswith(prefix) else ""


def _unit_row(unit_id: str, events: list[dict[str, Any]], fanout_id: str) -> dict[str, Any]:
    ordered = sorted(events, key=lambda event: str(event.get("observed_at", "")))
    projection = project_run_lifecycle(ordered, run_id=f"{fanout_id}-{unit_id}")
    latest = ordered[-1]
    return {
        "unit_id": unit_id,
        "run_ref": f"{fanout_id}-{unit_id}",
        "lifecycle_state": _lifecycle_state(ordered, projection),
        "process_succeeded": bool(projection.get("execution_observed")),
        "result_schema_valid": _has_observed_event(ordered, _RESULT_VALIDATED_EVENT),
        "unit_verification_observed": bool(projection.get("unit_verification_observed")),
        "owner": _latest_field(ordered, "runtime_profile"),
        # `branch_ref` is an optional journal field. Today's dispatch write site
        # records the worktree path and not the branch, so this reads `unknown`
        # on current journals. It stays a column rather than being filled from
        # the contract's `branch_suggestion`: a suggestion is what was proposed,
        # not what git checked out, and this roster reports only what was seen.
        "branch": _latest_field(ordered, "branch_ref"),
        "worktree_path": _latest_field(ordered, "worktree_ref"),
        "last_event": canonical_observation_event(str(latest.get("event", ""))),
        "last_event_status": str(latest.get("status", "") or _UNKNOWN),
        "last_event_at": str(latest.get("observed_at", "") or _UNKNOWN),
        "last_event_age_seconds": _age_seconds(str(latest.get("observed_at", ""))),
        "evidence_ref_count": _evidence_ref_count(ordered),
        "journal_event_count": len(ordered),
        **project_run_failure_diagnostic(events, run_id=f"{fanout_id}-{unit_id}"),
        **project_run_executor_session(events, run_id=f"{fanout_id}-{unit_id}"),
    }


def _resume_for_unit(unit: Mapping[str, object], contract: object, duplicates: frozenset[str]) -> dict[str, object]:
    read = read_session_receipt(unit.get('executor_session'))
    unavailable: dict[str, object] = {'available': False, 'reason': read.reason,
        'argv': [], 'cwd': None, 'shell_command': None, 'execution_policy': 'copy_only',
        'required_input': None, 'native_resume_state': 'not_tested'}
    receipt = read.receipt
    if receipt is None:
        return unavailable
    binding = receipt.binding
    if not is_string_map(contract) or contract.get('fanout_id') != binding.fanout_id:
        return {**unavailable, 'reason': 'contract_unavailable'}
    if fanout_contract_digest(contract) != binding.contract_digest:
        return {**unavailable, 'reason': 'binding_mismatch'}
    contract_units = contract.get('units')
    if not is_object_list(contract_units) or not any(
        is_string_map(row) and row.get('unit_id') == binding.unit_id
        and row.get('run_ref') == binding.run_ref and row.get('owner') == receipt.capability.executor
        for row in contract_units):
        return {**unavailable, 'reason': 'binding_mismatch'}
    if (
        observe_session_binary(receipt.capability.binary_identity.launch_path)
        != receipt.capability.binary_identity
    ):
        return {**unavailable, 'reason': 'binary_changed'}
    recovery = unit.get('session_recovery_snapshot')
    return dict(project_session_resume(receipt.to_dict(), binding=binding,
        workspace=observe_session_workspace(binding.worktree_path),
        recovery_snapshot=recovery if isinstance(recovery, str) else None,
        duplicate_references=duplicates))


def _lifecycle_state(events: list[dict[str, Any]], projection: Mapping[str, Any]) -> str:
    """The highest rung with dispatcher-observed backing in this unit's events.

    Reported as the highest rung REACHED, not as a claim that every lower rung
    was observed: a unit can carry a verification receipt without a validated
    sidecar. `integration_ready` is never decided here -- it additionally needs
    the whole chain plus a merge-order position only the full roster can see, so
    it is folded afterwards by `_apply_merge_order_position`.
    """
    if projection.get("unit_verification_observed"):
        return "unit_verification_observed"
    if _has_observed_event(events, _RESULT_VALIDATED_EVENT):
        return "result_schema_valid"
    if projection.get("execution_observed"):
        return "process_succeeded"
    if any(_has_observed_event(events, name) for name in _DISPATCH_EVENTS):
        return "dispatched_not_succeeded"
    return "not_dispatched"


def _apply_merge_order_position(units: list[dict[str, Any]]) -> None:
    """Promote verified units to `integration_ready` in roster order.

    Mirrors `_apply_integration_readiness` in fanout_dispatch: a later unit
    cannot become integration eligible while an earlier one still lacks the
    complete dispatcher-observed chain. The journal carries no merge plan, so
    the roster's own deterministic (sorted) unit order is the position, and the
    roster says so rather than implying the contract's merge order.
    """
    position_satisfied = True
    for unit in units:
        chain_complete = bool(
            unit["process_succeeded"]
            and unit["result_schema_valid"]
            and unit["unit_verification_observed"]
        )
        integration_ready = chain_complete and position_satisfied
        if integration_ready:
            unit["lifecycle_state"] = "integration_ready"
        unit["integration_ready"] = integration_ready
        unit["merge_order_position_satisfied"] = position_satisfied
        unit["merge_order_basis"] = "roster_order_not_contract_merge_plan"
        position_satisfied = integration_ready


def _has_observed_event(events: list[dict[str, Any]], name: str) -> bool:
    return any(
        canonical_observation_event(str(event.get("event", ""))) == name
        and str(event.get("status", "observed")) == "observed"
        for event in events
    )


def _latest_field(events: list[dict[str, Any]], key: str) -> str:
    for event in reversed(events):
        value = str(event.get(key, "") or "")
        if value:
            return value
    return _UNKNOWN


def _evidence_ref_count(events: list[dict[str, Any]]) -> int:
    total = 0
    for event in events:
        refs = event.get("evidence_refs")
        if isinstance(refs, list):
            total += sum(1 for ref in refs if str(ref))
    return total


def _age_seconds(observed_at: str) -> int | None:
    moment = _parse_timestamp(observed_at)
    if moment is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - moment).total_seconds()))


def _parse_timestamp(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _age_phrase(age_seconds: object) -> str:
    if not isinstance(age_seconds, int):
        return "(age unknown)"
    if age_seconds < 60:
        return f"({age_seconds}s ago)"
    if age_seconds < 3600:
        return f"({age_seconds // 60}m ago)"
    return f"({age_seconds // 3600}h ago)"
