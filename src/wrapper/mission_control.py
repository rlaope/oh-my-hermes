from __future__ import annotations

from typing import Any

from ..adapter_quality import quality_session_control
from ..conformance.checker import check_runtime_run
from ..coding.routing_observation import (
    authenticate_executor_observation,
    build_routing_observation,
    routing_surface_projection,
    validate_routing_observation,
)
from ..paths import OmhPaths
from ..runtime.records import OBSERVED_RESULTS
from .continuity_state import journey_state as _journey_state
from .sessions import build_wrapper_session_status, read_wrapper_session


MISSION_CONTROL_SCHEMA_VERSION = "mission_control/v1"
_SOURCE_BINDING_NOT_RECORDED = "not_recorded"


def build_mission_control(
    paths: OmhPaths,
    session_id: str,
    *,
    routing_observation: dict[str, object] | None = None,
) -> dict[str, object]:
    "Build an executor-neutral, read-only task journey from existing local records."
    try:
        session_status = build_wrapper_session_status(paths, session_id)
    except FileNotFoundError:
        session = read_wrapper_session(paths, session_id)
        if session is None:
            raise
        return _dangling_run_projection(
            session_id,
            session,
            routing_observation=routing_observation,
        )
    run_id = str(session_status.get("current_run_id", ""))
    runtime_status = _mapping(session_status.get("runtime_status"))
    runtime_observation = _mapping(session_status.get("runtime_observation"))
    conformance = check_runtime_run(paths, run_id) if run_id else _prepared_conformance(session_status, runtime_observation)
    journey_state = _journey_state(runtime_status, runtime_observation, session_status)
    recovery = _recovery(journey_state, conformance)
    source_binding = _source_binding()
    quality_evidence = {
        "claim_state": str(conformance["claim_state"]),
        "allowed_claims": list(conformance["allowed_claims"]),
        "blocked_claims": list(conformance["blocked_claims"]),
        "source_binding": source_binding,
    }
    next_action = str(conformance["next_action"])
    observation = routing_observation or _routing_observation(
        session_id=session_id,
        run_id=run_id,
        session_status=session_status,
        runtime_status=runtime_status,
        runtime_observation=runtime_observation,
        next_action=next_action,
    )
    errors = validate_routing_observation(observation)
    if errors:
        raise ValueError("invalid Mission Control routing observation: " + "; ".join(errors))
    routing_projection = routing_surface_projection(observation)
    return {
        "schema_version": MISSION_CONTROL_SCHEMA_VERSION,
        "session_id": session_id,
        "run_id": run_id,
        "owner": _owner(session_status),
        "journey": {"state": journey_state},
        "execution": _execution(runtime_status, runtime_observation),
        "capability_observation": _capability_observation(session_status),
        "adapter_quality": quality_session_control(paths, session_id),
        "recovery": recovery,
        "quality_evidence": quality_evidence,
        "merge_decision": _merge_decision(quality_evidence, next_action),
        "next_action": next_action,
        "safe_summary": str(conformance["safe_summary"]),
        "routing_observation": observation,
        "routing_status_rows": routing_projection["cli_status_rows"],
        "desktop_routing_code_block_text": routing_projection["desktop_code_block_text"],
        "claim_boundary": (
            "Mission Control is a read-only local projection. Prepared handoffs, wrapper state, "
            "and unbound evidence do not prove execution, review, CI, merge readiness, or merge."
        ),
    }


def _routing_observation(
    *,
    session_id: str,
    run_id: str,
    session_status: dict[str, object],
    runtime_status: dict[str, Any],
    runtime_observation: dict[str, Any],
    next_action: str,
) -> dict[str, object]:
    prepared = _mapping(runtime_status.get("prepared"))
    route = _mapping(prepared.get("model_route"))
    executor_status = _mapping(session_status.get("executor_session_status"))
    executor_progress = _mapping(executor_status.get("executor_progress"))
    latest_event = _mapping(executor_progress.get("latest_event"))
    result = str(executor_status.get("result", ""))
    observed = {
        **runtime_observation,
        **executor_progress,
        **latest_event,
        "status": (result if result in OBSERVED_RESULTS else None)
        or latest_event.get("status")
        or runtime_observation.get("status")
        or ("running" if executor_status.get("dispatch") == "observed" else None),
        "owner": executor_status.get("selected_executor_profile")
        or session_status.get("selected_executor_profile"),
        **(
            {"current_action": next_action}
            if latest_event or runtime_observation.get("status") or executor_status.get("dispatch") == "observed"
            else {}
        ),
    }
    return build_routing_observation(
        route=route,
        session_observation=authenticate_executor_observation(observed),
        child_session_id=session_id,
        run_id=run_id,
    )


def _prepared_conformance(session_status: dict[str, object], runtime_observation: dict[str, Any]) -> dict[str, object]:
    next_action = str(runtime_observation.get("next_action") or session_status.get("next_action", "show_status"))
    observed_events = _string_items(runtime_observation.get("observed_events"))
    summary = (
        "A runtime session observation records executor work, but no linked runtime run can support review, CI, or merge claims."
        if "worker_result" in observed_events
        else "A handoff is prepared, but no linked runtime evidence is available."
    )
    return {
        "claim_state": "handoff_prepared",
        "allowed_claims": ["metadata_available", "handoff_prepared"],
        "blocked_claims": [
            {"claim": "execution_observed", "reason": "linked runtime-run evidence is not available"},
            {"claim": "verification_observed", "reason": "linked runtime-run evidence is not available"},
            {"claim": "review_observed", "reason": "linked runtime-run evidence is not available"},
            {"claim": "ci_observed", "reason": "linked runtime-run evidence is not available"},
            {"claim": "merge_ready", "reason": "linked runtime-run evidence is not available"},
        ],
        "next_action": next_action,
        "safe_summary": summary,
    }


def _owner(session_status: dict[str, object]) -> dict[str, str]:
    executor_status = _mapping(session_status.get("executor_session_status"))
    return {
        "executor": str(
            executor_status.get("selected_executor_profile")
            or session_status.get("selected_executor_profile")
            or "choose"
        ),
        "mode": str(session_status.get("work_owner_mode") or "external_executor"),
    }


def _execution(runtime_status: dict[str, Any], runtime_observation: dict[str, Any]) -> dict[str, object]:
    execution = _mapping(runtime_status.get("execution"))
    observed_events = _string_items(runtime_observation.get("observed_events"))
    return {
        "observed": execution.get("observed") is True or "worker_result" in observed_events,
        "result": str(execution.get("status", "not_observed")),
    }


def _recovery(journey_state: str, conformance: dict[str, object]) -> dict[str, object]:
    next_action = str(conformance["next_action"])
    match journey_state:
        case "executor_dispatched":
            return {"status": "running_observed", "resume_safe": False, "next_action": next_action}
        case "runtime_running_observed":
            return {"status": "running_observed", "resume_safe": False, "next_action": next_action}
        case "executor_cancelled":
            # Its own recovery status. `recovery_blocked` reads as "something is
            # in the way", and the answer to a cancellation is a decision about
            # re-dispatching, not a blocker to clear.
            return {"status": "cancelled_observed", "resume_safe": False, "next_action": next_action}
        case "executor_blocked" | "executor_failed" | "runtime_recovery_blocked" | "invalid_runtime_evidence":
            return {"status": "recovery_blocked", "resume_safe": False, "next_action": next_action}
        case "handoff_prepared":
            return {"status": "not_started", "resume_safe": False, "next_action": next_action}
        case "execution_observed":
            return {"status": "evidence_available", "resume_safe": False, "next_action": next_action}
        case "runtime_execution_observed":
            return {"status": "evidence_available", "resume_safe": False, "next_action": next_action}
        case _:
            return {"status": "recovery_blocked", "resume_safe": False, "next_action": next_action}


def _source_binding() -> dict[str, str]:
    return {
        "status": _SOURCE_BINDING_NOT_RECORDED,
        "reason": "Existing review, CI, and merge records do not yet carry a source tree identity.",
    }


def _merge_decision(quality_evidence: dict[str, object], fallback_action: str) -> dict[str, str]:
    source_binding = _mapping(quality_evidence.get("source_binding"))
    if source_binding.get("status") == _SOURCE_BINDING_NOT_RECORDED:
        return {
            "status": "not_ready",
            "next_action": "record_source_bound_quality_evidence",
            "reason": "Review and CI evidence is not bound to the source tree currently under discussion.",
        }
    return {"status": "not_ready", "next_action": fallback_action, "reason": "Merge readiness is not observed."}


def _capability_observation(session_status: dict[str, object]) -> dict[str, object]:
    executor_status = _mapping(session_status.get("executor_session_status"))
    snapshot = _mapping(executor_status.get("executor_capability_snapshot"))
    capabilities = _mapping(snapshot.get("capabilities"))
    statuses = [str(_mapping(value).get("status", "unknown")) for value in capabilities.values()]
    if "host_observed" in statuses:
        status = "host_observed"
    elif "prepared" in statuses:
        status = "prepared"
    elif "unavailable" in statuses and statuses:
        status = "unavailable"
    else:
        status = "unknown"
    return {
        "status": status,
        "snapshot": snapshot,
        "modality_decision": _mapping(executor_status.get("executor_modality_decision")),
    }


def _dangling_run_projection(
    session_id: str,
    session: dict[str, Any],
    *,
    routing_observation: dict[str, object] | None = None,
) -> dict[str, object]:
    executor = str(session.get("selected_executor_profile") or "choose")
    observation = routing_observation or build_routing_observation(
        route={"executor_profile": executor},
        child_session_id=session_id,
        run_id=str(session.get("current_run_id", "")),
    )
    errors = validate_routing_observation(observation)
    if errors:
        raise ValueError("invalid Mission Control routing observation: " + "; ".join(errors))
    routing_projection = routing_surface_projection(observation)
    return {
        "schema_version": MISSION_CONTROL_SCHEMA_VERSION,
        "session_id": session_id,
        "run_id": str(session.get("current_run_id", "")),
        "owner": {"executor": executor, "mode": str(session.get("work_owner_mode") or "external_executor")},
        "journey": {"state": "invalid_linkage"},
        "execution": {"observed": False, "result": "not_observed"},
        "capability_observation": {"status": "unknown", "snapshot": {}},
        "recovery": {"status": "recovery_blocked", "resume_safe": False, "next_action": "repair_linked_runtime_record"},
        "quality_evidence": {
            "claim_state": "metadata_available",
            "allowed_claims": ["metadata_available"],
            "blocked_claims": [{"claim": "handoff_prepared", "reason": "linked runtime record is missing"}],
            "source_binding": _source_binding(),
        },
        "merge_decision": {
            "status": "not_ready",
            "next_action": "repair_linked_runtime_record",
            "reason": "The wrapper session points to a missing runtime record.",
        },
        "next_action": "repair_linked_runtime_record",
        "safe_summary": "The wrapper session exists, but its linked runtime record is missing.",
        "routing_observation": observation,
        "routing_status_rows": routing_projection["cli_status_rows"],
        "desktop_routing_code_block_text": routing_projection["desktop_code_block_text"],
        "claim_boundary": "Missing runtime records do not prove execution, review, CI, merge readiness, or merge.",
    }


def _string_items(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
