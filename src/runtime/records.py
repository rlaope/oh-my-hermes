from __future__ import annotations

import hashlib
from typing import Any

from ..coding_contracts import CODING_EXECUTOR_HANDOFF_TARGETS, EXECUTOR_HANDOFF_SCHEMA_VERSION
from ..local_store import utc_now


SCHEMA_VERSION = 1
RUN_STATUSES = ("started", "prepared", "completed", "blocked", "failed", "unknown")
PRIVACY_MODES = ("metadata_only",)
RUN_ARTIFACT_KINDS = ("workflow_run", "prepared_coding_delegation")
RUN_PHASES = ("runtime", "prepared", "unknown")
RUN_OBSERVATION_STATUSES = ("unknown", "observed", "not_observed", "prepared_not_observed")
DELEGATION_RESULTS = ("completed", "blocked", "failed", "not_available", "not_observed")
OBSERVED_RESULTS = ("completed", "blocked", "failed")
UNOBSERVED_RESULTS = ("not_available", "not_observed")
EVENT_LEVELS = ("debug", "info", "warning", "error")
WRAPPER_COMPLETION_STATUSES = ("started", "completed", "blocked", "failed", "unknown")
REVIEW_STATUSES = ("not_required", "pending", "passed", "failed", "blocked", "not_observed")
CI_STATUSES = ("not_required", "pending", "passed", "failed", "blocked", "not_observed")
CI_CHECK_STATUSES = ("passed", "failed", "blocked", "pending", "not_required")
MERGE_STATUSES = ("not_ready", "ready", "merged", "blocked", "not_observed")
ROUTE_ACTIONS = ("dispatch", "clarify", "fallback")
ROUTE_CONFIDENCES = ("low", "medium", "high")
ROUTING_RECOMMENDATION_KEYS = ("skill", "score", "confidence", "matched")
CODING_DELEGATION_SCHEMA_VERSION = "coding_delegation/v1"
CODING_DELEGATION_RECORD_TYPE = "coding_delegation"
CODING_DELEGATION_ACTIONS = ("delegate", "clarify", "fallback")
CODING_DELEGATION_INTENTS = ("coding", "cleanup", "review", "planning", "diagnostics", "docs", "unknown")
CODING_DELEGATION_STATUSES = ("prepared_not_observed",)
CODING_SOURCE_METADATA_KEYS = ("source_event_id", "channel_ref", "user_ref", "timestamp")
CODING_RECOMMENDATION_KEYS = ("skill", "score", "confidence", "matched")
CODING_DELEGATION_RECORD_KEYS = (
    "schema_version",
    "record_type",
    "updated_at",
    "source",
    "action",
    "intent",
    "recommended_workflow",
    "recommended_harness",
    "executor_profile",
    "review_required",
    "review_workflow",
    "message_sha256",
    "message_length",
    "source_metadata",
    "recommendation_evidence",
    "executor_handoff",
    "acceptance_criteria",
    "verification",
    "status",
)
CODING_EXECUTOR_HANDOFF_SCHEMA_VERSION = EXECUTOR_HANDOFF_SCHEMA_VERSION
CODING_EXECUTOR_TARGETS = CODING_EXECUTOR_HANDOFF_TARGETS
CODING_EXECUTOR_HANDOFF_KEYS = (
    "schema_version",
    "executor_target",
    "handoff_mode",
    "status",
    "recording_contract",
    "dispatch_contract",
    "prompt_template",
    "scope",
    "non_goals",
    "acceptance_criteria",
    "verification",
    "review",
)
WRAPPER_SESSION_SCHEMA_VERSION = "wrapper_session/v1"
WRAPPER_SESSION_RECORD_TYPE = "wrapper_session"
WRAPPER_SESSION_STATUSES = (
    "plan_presented",
    "clarifying",
    "routed",
    "plan_accepted",
    "revision_requested",
    "cancelled",
    "handoff_prepared",
)
WRAPPER_SESSION_DECISIONS = ("none", "plan_accepted", "plan_revision_requested", "plan_cancelled")
WRAPPER_SESSION_SOURCE_METADATA_KEYS = CODING_SOURCE_METADATA_KEYS
WRAPPER_SESSION_ROUTE_KEYS = ("action", "selected_skill", "selected_harness", "confidence", "score")
WRAPPER_SESSION_PLAN_KEYS = ("status", "recommended_workflow", "recommended_harness")
WRAPPER_SESSION_AUTHORITY_SESSION_OWNS = (
    "chat_continuity",
    "route_summary",
    "plan_decision",
    "linked_run_id",
)
WRAPPER_SESSION_AUTHORITY_RUN_LEDGER_OWNS = (
    "prepared_handoff",
    "dispatch",
    "executor_result",
    "verification",
    "review",
    "ci",
    "merge_readiness",
    "merge",
)
WRAPPER_SESSION_STATUS_DECISIONS = {
    "plan_presented": "none",
    "clarifying": "none",
    "routed": "none",
    "plan_accepted": "plan_accepted",
    "revision_requested": "plan_revision_requested",
    "cancelled": "plan_cancelled",
    "handoff_prepared": "plan_accepted",
}
WRAPPER_SESSION_RECORD_KEYS = (
    "schema_version",
    "record_type",
    "session_id",
    "thread_key",
    "source",
    "source_metadata",
    "message_sha256",
    "message_length",
    "created_at",
    "updated_at",
    "status",
    "decision",
    "route",
    "plan",
    "current_run_id",
    "redaction_policy",
    "authority",
)


def build_run_record(metadata: dict[str, Any], run_id: str) -> dict[str, Any]:
    status = metadata.get("status", "unknown")
    if status not in RUN_STATUSES:
        raise ValueError(f"unsupported run status: {status}")
    privacy = metadata.get("privacy", "metadata_only")
    if privacy not in PRIVACY_MODES:
        raise ValueError(f"unsupported privacy mode: {privacy}")
    skill = str(metadata.get("skill", "unknown"))
    harness = str(metadata.get("harness", "unknown"))
    created_at = str(metadata.get("created_at") or utc_now())
    artifact_kind = str(metadata.get("artifact_kind", "workflow_run"))
    phase = str(metadata.get("phase", "runtime"))
    observation_status = str(metadata.get("observation_status", "unknown"))
    if artifact_kind not in RUN_ARTIFACT_KINDS:
        raise ValueError(f"unsupported run artifact_kind: {artifact_kind}")
    if phase not in RUN_PHASES:
        raise ValueError(f"unsupported run phase: {phase}")
    if observation_status not in RUN_OBSERVATION_STATUSES:
        raise ValueError(f"unsupported run observation_status: {observation_status}")
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": created_at,
        "updated_at": created_at,
        "skill": skill,
        "harness": harness,
        "trigger": metadata.get("trigger", ""),
        "status": status,
        "artifact_kind": artifact_kind,
        "phase": phase,
        "observation_status": observation_status,
        "privacy": privacy,
        "inputs_summary": metadata.get("inputs_summary", ""),
        "outputs_summary": metadata.get("outputs_summary", ""),
        "verification_summary": metadata.get("verification_summary", ""),
    }


def build_event_record(event: dict[str, Any]) -> dict[str, Any]:
    item = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": event.get("timestamp") or utc_now(),
        "event": event.get("event", "event"),
        "level": event.get("level", "info"),
        "message": event.get("message", ""),
    }
    if "data" in event:
        item["data"] = event["data"]
    return item


def validate_delegation_result(observed: bool, result: str) -> None:
    if observed and result not in OBSERVED_RESULTS:
        raise ValueError("observed delegation requires result completed, blocked, or failed")
    if not observed and result not in UNOBSERVED_RESULTS:
        raise ValueError("unobserved delegation requires result not_available or not_observed")


def build_delegation_record(delegation: dict[str, Any]) -> dict[str, Any]:
    result = delegation.get("result", "not_observed")
    if result not in DELEGATION_RESULTS:
        raise ValueError(f"unsupported delegation result: {result}")
    observed = bool(delegation.get("observed", False))
    validate_delegation_result(observed, result)
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": utc_now(),
        "requested": bool(delegation.get("requested", False)),
        "observed": observed,
        "participants": list(delegation.get("participants", [])),
        "result": result,
        "evidence_refs": list(delegation.get("evidence_refs", [])),
        "message": delegation.get("message", ""),
    }


def build_wrapper_record(wrapper: dict[str, Any]) -> dict[str, Any]:
    status = wrapper.get("completion_status", "unknown")
    if status not in WRAPPER_COMPLETION_STATUSES:
        raise ValueError(f"unsupported wrapper completion status: {status}")
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": utc_now(),
        "prompt_dispatched": bool(wrapper.get("prompt_dispatched", False)),
        "hermes_response_observed": bool(wrapper.get("hermes_response_observed", False)),
        "verification_observed": bool(wrapper.get("verification_observed", False)),
        "completion_status": status,
        "unobserved_gaps": list(wrapper.get("unobserved_gaps", [])),
        "message": wrapper.get("message", ""),
    }


def build_review_record(review: dict[str, Any]) -> dict[str, Any]:
    status = str(review.get("status", "not_observed"))
    if status not in REVIEW_STATUSES:
        raise ValueError(f"unsupported review status: {status}")
    required = bool(review.get("required", status != "not_required"))
    observed = bool(review.get("observed", status not in {"pending", "not_observed"}))
    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(review.get("run_id", "")),
        "updated_at": str(review.get("updated_at") or utc_now()),
        "required": required,
        "observed": observed,
        "status": status,
        "reviewer": str(review.get("reviewer", "")),
        "evidence_refs": _compact_string_list(review.get("evidence_refs", [])),
        "summary": str(review.get("summary", "")),
    }
    errors = validate_review_record(record)
    if errors:
        raise ValueError(errors[0])
    return record


def build_ci_record(ci: dict[str, Any]) -> dict[str, Any]:
    status = str(ci.get("status", "not_observed"))
    if status not in CI_STATUSES:
        raise ValueError(f"unsupported CI status: {status}")
    required = bool(ci.get("required", status != "not_required"))
    observed = bool(ci.get("observed", status not in {"pending", "not_observed"}))
    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(ci.get("run_id", "")),
        "updated_at": str(ci.get("updated_at") or utc_now()),
        "required": required,
        "observed": observed,
        "status": status,
        "provider": str(ci.get("provider", "")),
        "checks": _compact_ci_checks(ci.get("checks", [])),
        "evidence_refs": _compact_string_list(ci.get("evidence_refs", [])),
        "summary": str(ci.get("summary", "")),
    }
    errors = validate_ci_record(record)
    if errors:
        raise ValueError(errors[0])
    return record


def build_merge_record(merge: dict[str, Any]) -> dict[str, Any]:
    status = str(merge.get("status", "not_observed"))
    if status not in MERGE_STATUSES:
        raise ValueError(f"unsupported merge status: {status}")
    observed = bool(merge.get("observed", status in {"ready", "merged", "blocked"}))
    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(merge.get("run_id", "")),
        "updated_at": str(merge.get("updated_at") or utc_now()),
        "observed": observed,
        "ready": bool(merge.get("ready", status in {"ready", "merged"})),
        "merged": bool(merge.get("merged", status == "merged")),
        "status": status,
        "target_branch": str(merge.get("target_branch", "")),
        "merge_commit": str(merge.get("merge_commit", "")),
        "evidence_refs": _compact_string_list(merge.get("evidence_refs", [])),
        "summary": str(merge.get("summary", "")),
    }
    errors = validate_merge_record(record)
    if errors:
        raise ValueError(errors[0])
    return record


def build_routing_record(routing: dict[str, Any]) -> dict[str, Any]:
    action = routing.get("action", "fallback")
    if action not in ROUTE_ACTIONS:
        raise ValueError(f"unsupported routing action: {action}")
    confidence = routing.get("confidence", "low")
    if confidence not in ROUTE_CONFIDENCES:
        raise ValueError(f"unsupported routing confidence: {confidence}")
    threshold = routing.get("threshold", "high")
    if threshold not in ROUTE_CONFIDENCES:
        raise ValueError(f"unsupported routing threshold: {threshold}")
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": utc_now(),
        "source": str(routing.get("source", "generic")),
        "action": action,
        "selected_skill": str(routing.get("selected_skill", "oh-my-hermes")),
        "selected_harness": str(routing.get("selected_harness", "coding-handling")),
        "candidate_skill": str(routing.get("candidate_skill", "")),
        "candidate_harness": str(routing.get("candidate_harness", "")),
        "confidence": confidence,
        "score": int(routing.get("score", 0)),
        "threshold": threshold,
        "explicit": bool(routing.get("explicit", False)),
        "ambiguous": bool(routing.get("ambiguous", False)),
        "reason": str(routing.get("reason", "")),
        "message_sha256": str(routing.get("message_sha256", "")),
        "message_length": int(routing.get("message_length", 0)),
        "source_event_id": str(routing.get("source_event_id", "")),
        "channel_ref": str(routing.get("channel_ref", "")),
        "user_ref": str(routing.get("user_ref", "")),
        "recommendations": _compact_routing_recommendations(routing.get("recommendations", [])),
    }


def build_coding_delegation_record(delegation: dict[str, Any]) -> dict[str, Any]:
    nested = delegation.get("delegation", {})
    if not isinstance(nested, dict):
        nested = {}
    message = delegation.get("message", "")
    message_text = message if isinstance(message, str) else ""
    record = {
        "schema_version": CODING_DELEGATION_SCHEMA_VERSION,
        "record_type": CODING_DELEGATION_RECORD_TYPE,
        "updated_at": utc_now(),
        "source": str(delegation.get("source", "generic")),
        "action": str(nested.get("action", delegation.get("action", "fallback"))),
        "intent": str(nested.get("intent", delegation.get("intent", "unknown"))),
        "recommended_workflow": str(nested.get("recommended_workflow", delegation.get("recommended_workflow", "oh-my-hermes"))),
        "recommended_harness": str(nested.get("recommended_harness", delegation.get("recommended_harness", "coding-handling"))),
        "executor_profile": str(nested.get("executor_profile", delegation.get("executor_profile", "router"))),
        "review_required": bool(nested.get("review_required", delegation.get("review_required", False))),
        "review_workflow": _optional_string(nested.get("review_workflow", delegation.get("review_workflow"))),
        "message_sha256": str(delegation.get("message_sha256", "")),
        "message_length": int(delegation.get("message_length", len(message_text))),
        "source_metadata": _compact_source_metadata(delegation.get("source_metadata", {})),
        "recommendation_evidence": _compact_coding_recommendations(
            delegation.get("recommendation_evidence", delegation.get("recommendations", []))
        ),
        "acceptance_criteria": _compact_string_list(nested.get("acceptance_criteria", delegation.get("acceptance_criteria", []))),
        "verification": _compact_string_list(nested.get("verification", delegation.get("verification", []))),
        "status": str(delegation.get("status", "prepared_not_observed")),
    }
    executor_handoff = _compact_executor_handoff(delegation.get("executor_handoff"))
    if executor_handoff:
        record["executor_handoff"] = executor_handoff
    if not record["message_sha256"] and message_text:
        record["message_sha256"] = hashlib.sha256(message_text.encode("utf-8")).hexdigest()
    errors = validate_coding_delegation_record(record)
    if errors:
        raise ValueError(errors[0])
    return record


def build_wrapper_session_record(session: dict[str, Any]) -> dict[str, Any]:
    status = str(session.get("status", "plan_presented"))
    if status not in WRAPPER_SESSION_STATUSES:
        raise ValueError(f"unsupported wrapper session status: {status}")
    decision = str(session.get("decision", "none"))
    if decision not in WRAPPER_SESSION_DECISIONS:
        raise ValueError(f"unsupported wrapper session decision: {decision}")
    created_at = str(session.get("created_at") or utc_now())
    record = {
        "schema_version": WRAPPER_SESSION_SCHEMA_VERSION,
        "record_type": WRAPPER_SESSION_RECORD_TYPE,
        "session_id": str(session.get("session_id", "")),
        "thread_key": str(session.get("thread_key", "")),
        "source": str(session.get("source", "generic")),
        "source_metadata": _compact_wrapper_session_source_metadata(session.get("source_metadata", {})),
        "message_sha256": str(session.get("message_sha256", "")),
        "message_length": int(session.get("message_length", 0)),
        "created_at": created_at,
        "updated_at": str(session.get("updated_at") or utc_now()),
        "status": status,
        "decision": decision,
        "route": _compact_wrapper_session_route(session.get("route", {})),
        "plan": _compact_wrapper_session_plan(session.get("plan", {})),
        "current_run_id": str(session.get("current_run_id", "")),
        "redaction_policy": "metadata_only",
        "authority": {
            "session_owns": list(WRAPPER_SESSION_AUTHORITY_SESSION_OWNS),
            "run_ledger_owns": list(WRAPPER_SESSION_AUTHORITY_RUN_LEDGER_OWNS),
        },
    }
    errors = validate_wrapper_session_record(record)
    if errors:
        raise ValueError(errors[0])
    return record


def _compact_routing_recommendations(recommendations: Any) -> list[dict[str, Any]]:
    if not isinstance(recommendations, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        matched = item.get("matched", [])
        compact.append(
            {
                "skill": str(item.get("skill", "")),
                "score": int(item.get("score", 0)),
                "confidence": str(item.get("confidence", "low")),
                "matched": [str(value) for value in matched] if isinstance(matched, list) else [],
            }
        )
    return compact


def _compact_coding_recommendations(recommendations: Any) -> list[dict[str, Any]]:
    if not isinstance(recommendations, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        matched = item.get("matched", [])
        compact.append(
            {
                "skill": str(item.get("skill", "")),
                "score": int(item.get("score", 0)),
                "confidence": str(item.get("confidence", "low")),
                "matched": [str(value) for value in matched] if isinstance(matched, list) else [],
            }
        )
    return compact


def _compact_source_metadata(metadata: Any) -> dict[str, str]:
    if not isinstance(metadata, dict):
        return {}
    return {key: str(metadata[key]) for key in CODING_SOURCE_METADATA_KEYS if key in metadata and str(metadata[key])}


def _compact_wrapper_session_source_metadata(metadata: Any) -> dict[str, str]:
    if not isinstance(metadata, dict):
        return {}
    return {
        key: str(metadata[key])
        for key in WRAPPER_SESSION_SOURCE_METADATA_KEYS
        if key in metadata and str(metadata[key])
    }


def _compact_wrapper_session_route(route: Any) -> dict[str, Any]:
    if not isinstance(route, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in WRAPPER_SESSION_ROUTE_KEYS:
        if key not in route:
            continue
        compact[key] = int(route[key]) if key == "score" else str(route[key])
    return compact


def _compact_wrapper_session_plan(plan: Any) -> dict[str, str]:
    if not isinstance(plan, dict):
        return {}
    return {key: str(plan[key]) for key in WRAPPER_SESSION_PLAN_KEYS if key in plan and str(plan[key])}


def _compact_string_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return [str(value) for value in values if str(value)]


def _compact_ci_checks(values: Any) -> list[dict[str, str]]:
    if not isinstance(values, (list, tuple)):
        return []
    checks: list[dict[str, str]] = []
    for value in values:
        if isinstance(value, dict):
            name = str(value.get("name", ""))
            status = str(value.get("status", "pending"))
        else:
            text = str(value)
            name, _, status = text.partition(":")
            status = status or "pending"
        checks.append({"name": name, "status": status})
    return checks


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _compact_executor_handoff(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compact: dict[str, Any] = {
        "schema_version": str(value.get("schema_version", "")),
        "executor_target": str(value.get("executor_target", "")),
        "handoff_mode": str(value.get("handoff_mode", "")),
        "status": str(value.get("status", "")),
        "recording_contract": str(value.get("recording_contract", "")),
        "dispatch_contract": str(value.get("dispatch_contract", "")),
        "prompt_template": str(value.get("prompt_template", "")),
        "scope": _compact_string_list(value.get("scope", [])),
        "non_goals": _compact_string_list(value.get("non_goals", [])),
        "acceptance_criteria": _compact_string_list(value.get("acceptance_criteria", [])),
        "verification": _compact_string_list(value.get("verification", [])),
    }
    review = value.get("review")
    if isinstance(review, dict):
        compact["review"] = {
            "required": bool(review.get("required", False)),
            "workflow": _optional_string(review.get("workflow")),
            "evidence_required": str(review.get("evidence_required", "")),
        }
    return compact


def _require(condition: bool, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)


def validate_run_record(run: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(run.get("schema_version") == SCHEMA_VERSION, errors, "run schema_version is invalid")
    for key in ("run_id", "created_at", "updated_at", "skill", "harness", "status", "privacy"):
        _require(isinstance(run.get(key), str) if key != "schema_version" else True, errors, f"run {key} must be a string")
    _require(run.get("status") in RUN_STATUSES, errors, f"run status is invalid: {run.get('status')!r}")
    _require(run.get("privacy") in PRIVACY_MODES, errors, f"run privacy is invalid: {run.get('privacy')!r}")
    if "artifact_kind" in run:
        _require(isinstance(run.get("artifact_kind"), str), errors, "run artifact_kind must be a string")
        _require(run.get("artifact_kind") in RUN_ARTIFACT_KINDS, errors, f"run artifact_kind is invalid: {run.get('artifact_kind')!r}")
    if "phase" in run:
        _require(isinstance(run.get("phase"), str), errors, "run phase must be a string")
        _require(run.get("phase") in RUN_PHASES, errors, f"run phase is invalid: {run.get('phase')!r}")
    if "observation_status" in run:
        _require(isinstance(run.get("observation_status"), str), errors, "run observation_status must be a string")
        _require(
            run.get("observation_status") in RUN_OBSERVATION_STATUSES,
            errors,
            f"run observation_status is invalid: {run.get('observation_status')!r}",
        )
    if run.get("artifact_kind") == "prepared_coding_delegation":
        _require(run.get("status") == "prepared", errors, "prepared coding delegation run status must be prepared")
        _require(run.get("phase") == "prepared", errors, "prepared coding delegation run phase must be prepared")
        _require(
            run.get("observation_status") == "prepared_not_observed",
            errors,
            "prepared coding delegation run observation_status must be prepared_not_observed",
        )
    for key in ("trigger", "inputs_summary", "outputs_summary", "verification_summary"):
        _require(isinstance(run.get(key, ""), str), errors, f"run {key} must be a string")
    return errors


def validate_event_record(event: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(event.get("schema_version") == SCHEMA_VERSION, errors, "event schema_version is invalid")
    for key in ("timestamp", "event", "level", "message"):
        _require(isinstance(event.get(key), str), errors, f"event {key} must be a string")
    _require(event.get("level") in EVENT_LEVELS, errors, f"event level is invalid: {event.get('level')!r}")
    if "data" in event:
        _require(isinstance(event["data"], dict), errors, "event data must be an object")
    return errors


def validate_delegation_record(delegation: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(delegation.get("schema_version") == SCHEMA_VERSION, errors, "delegation schema_version is invalid")
    _require(isinstance(delegation.get("requested"), bool), errors, "delegation requested must be boolean")
    _require(isinstance(delegation.get("observed"), bool), errors, "delegation observed must be boolean")
    _require(delegation.get("result") in DELEGATION_RESULTS, errors, f"delegation result is invalid: {delegation.get('result')!r}")
    _require(isinstance(delegation.get("participants"), list), errors, "delegation participants must be a list")
    _require(isinstance(delegation.get("evidence_refs"), list), errors, "delegation evidence_refs must be a list")
    try:
        validate_delegation_result(bool(delegation.get("observed")), str(delegation.get("result")))
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def validate_wrapper_record(wrapper: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(wrapper.get("schema_version") == SCHEMA_VERSION, errors, "wrapper schema_version is invalid")
    for key in ("prompt_dispatched", "hermes_response_observed", "verification_observed"):
        _require(isinstance(wrapper.get(key), bool), errors, f"wrapper {key} must be boolean")
    _require(
        wrapper.get("completion_status") in WRAPPER_COMPLETION_STATUSES,
        errors,
        f"wrapper completion_status is invalid: {wrapper.get('completion_status')!r}",
    )
    _require(isinstance(wrapper.get("unobserved_gaps"), list), errors, "wrapper unobserved_gaps must be a list")
    _require(isinstance(wrapper.get("message", ""), str), errors, "wrapper message must be a string")
    return errors


def validate_review_record(review: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    extra_keys = sorted(
        set(review)
        - {"schema_version", "run_id", "updated_at", "required", "observed", "status", "reviewer", "evidence_refs", "summary"}
    )
    _require(not extra_keys, errors, f"review has unsupported keys: {extra_keys}")
    _require(review.get("schema_version") == SCHEMA_VERSION, errors, "review schema_version is invalid")
    for key in ("run_id", "updated_at", "status", "reviewer", "summary"):
        _require(isinstance(review.get(key), str), errors, f"review {key} must be a string")
    _require(isinstance(review.get("required"), bool), errors, "review required must be boolean")
    _require(isinstance(review.get("observed"), bool), errors, "review observed must be boolean")
    _require(review.get("status") in REVIEW_STATUSES, errors, f"review status is invalid: {review.get('status')!r}")
    _require(isinstance(review.get("evidence_refs"), list), errors, "review evidence_refs must be a list")
    for index, value in enumerate(review.get("evidence_refs", []) if isinstance(review.get("evidence_refs"), list) else []):
        _require(isinstance(value, str), errors, f"review evidence_refs[{index}] must be a string")
    if review.get("status") == "not_required":
        _require(review.get("required") is False, errors, "review not_required status requires required=false")
        _require(review.get("observed") is True, errors, "review not_required status must be observed")
    if review.get("observed") is False:
        _require(review.get("status") in {"pending", "not_observed"}, errors, "review observed=false requires pending or not_observed")
    if review.get("status") == "passed":
        _require(review.get("observed") is True, errors, "review passed status requires observed=true")
    return errors


def validate_ci_record(ci: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    extra_keys = sorted(
        set(ci)
        - {"schema_version", "run_id", "updated_at", "required", "observed", "status", "provider", "checks", "evidence_refs", "summary"}
    )
    _require(not extra_keys, errors, f"ci has unsupported keys: {extra_keys}")
    _require(ci.get("schema_version") == SCHEMA_VERSION, errors, "ci schema_version is invalid")
    for key in ("run_id", "updated_at", "status", "provider", "summary"):
        _require(isinstance(ci.get(key), str), errors, f"ci {key} must be a string")
    _require(isinstance(ci.get("required"), bool), errors, "ci required must be boolean")
    _require(isinstance(ci.get("observed"), bool), errors, "ci observed must be boolean")
    _require(ci.get("status") in CI_STATUSES, errors, f"ci status is invalid: {ci.get('status')!r}")
    _require(isinstance(ci.get("checks"), list), errors, "ci checks must be a list")
    checks = ci.get("checks", []) if isinstance(ci.get("checks"), list) else []
    for index, check in enumerate(checks):
        _require(isinstance(check, dict), errors, f"ci checks[{index}] must be an object")
        if not isinstance(check, dict):
            continue
        _require(set(check) == {"name", "status"}, errors, f"ci checks[{index}] must contain only name and status")
        _require(isinstance(check.get("name"), str), errors, f"ci checks[{index}].name must be a string")
        _require(bool(str(check.get("name", "")).strip()), errors, f"ci checks[{index}].name must not be empty")
        _require(check.get("status") in CI_CHECK_STATUSES, errors, f"ci checks[{index}].status is invalid: {check.get('status')!r}")
    _require(isinstance(ci.get("evidence_refs"), list), errors, "ci evidence_refs must be a list")
    for index, value in enumerate(ci.get("evidence_refs", []) if isinstance(ci.get("evidence_refs"), list) else []):
        _require(isinstance(value, str), errors, f"ci evidence_refs[{index}] must be a string")
    if ci.get("status") == "not_required":
        _require(ci.get("required") is False, errors, "ci not_required status requires required=false")
        _require(ci.get("observed") is True, errors, "ci not_required status must be observed")
        invalid_checks = [check for check in checks if isinstance(check, dict) and check.get("status") != "not_required"]
        _require(not invalid_checks, errors, "ci not_required status requires checks to be empty or not_required")
    if ci.get("observed") is False:
        _require(ci.get("status") in {"pending", "not_observed"}, errors, "ci observed=false requires pending or not_observed")
    if ci.get("status") == "passed":
        _require(ci.get("observed") is True, errors, "ci passed status requires observed=true")
        _require(bool(checks), errors, "ci passed status requires at least one check")
        failed = [check for check in checks if isinstance(check, dict) and check.get("status") != "passed"]
        _require(not failed, errors, "ci passed status requires all checks to be passed")
    return errors


def validate_merge_record(merge: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    extra_keys = sorted(
        set(merge)
        - {
            "schema_version",
            "run_id",
            "updated_at",
            "observed",
            "ready",
            "merged",
            "status",
            "target_branch",
            "merge_commit",
            "evidence_refs",
            "summary",
        }
    )
    _require(not extra_keys, errors, f"merge has unsupported keys: {extra_keys}")
    _require(merge.get("schema_version") == SCHEMA_VERSION, errors, "merge schema_version is invalid")
    for key in ("run_id", "updated_at", "status", "target_branch", "merge_commit", "summary"):
        _require(isinstance(merge.get(key), str), errors, f"merge {key} must be a string")
    for key in ("observed", "ready", "merged"):
        _require(isinstance(merge.get(key), bool), errors, f"merge {key} must be boolean")
    _require(merge.get("status") in MERGE_STATUSES, errors, f"merge status is invalid: {merge.get('status')!r}")
    _require(isinstance(merge.get("evidence_refs"), list), errors, "merge evidence_refs must be a list")
    for index, value in enumerate(merge.get("evidence_refs", []) if isinstance(merge.get("evidence_refs"), list) else []):
        _require(isinstance(value, str), errors, f"merge evidence_refs[{index}] must be a string")
    if merge.get("status") == "not_observed":
        _require(merge.get("observed") is False, errors, "merge not_observed status requires observed=false")
        _require(merge.get("ready") is False, errors, "merge not_observed status requires ready=false")
        _require(merge.get("merged") is False, errors, "merge not_observed status requires merged=false")
    if merge.get("status") == "not_ready":
        _require(merge.get("ready") is False, errors, "merge not_ready status requires ready=false")
        _require(merge.get("merged") is False, errors, "merge not_ready status requires merged=false")
    if merge.get("status") == "blocked":
        _require(merge.get("observed") is True, errors, "merge blocked status requires observed=true")
        _require(merge.get("ready") is False, errors, "merge blocked status requires ready=false")
        _require(merge.get("merged") is False, errors, "merge blocked status requires merged=false")
    if merge.get("observed") is False:
        _require(merge.get("status") in {"not_ready", "not_observed"}, errors, "merge observed=false requires not_ready or not_observed")
    if merge.get("status") == "ready":
        _require(merge.get("observed") is True, errors, "merge ready status requires observed=true")
        _require(merge.get("ready") is True, errors, "merge ready status requires ready=true")
        _require(merge.get("merged") is False, errors, "merge ready status requires merged=false")
    if merge.get("status") == "merged":
        _require(merge.get("observed") is True, errors, "merge merged status requires observed=true")
        _require(merge.get("ready") is True, errors, "merge merged status requires ready=true")
        _require(merge.get("merged") is True, errors, "merge merged status requires merged=true")
        _require(
            bool(str(merge.get("merge_commit", ""))) or bool(merge.get("evidence_refs")),
            errors,
            "merge merged status requires merge_commit or evidence_refs",
        )
    return errors


def validate_routing_record(routing: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(routing.get("schema_version") == SCHEMA_VERSION, errors, "routing schema_version is invalid")
    for key in (
        "updated_at",
        "source",
        "action",
        "selected_skill",
        "selected_harness",
        "candidate_skill",
        "candidate_harness",
        "confidence",
        "threshold",
        "reason",
        "message_sha256",
        "source_event_id",
        "channel_ref",
        "user_ref",
    ):
        _require(isinstance(routing.get(key), str), errors, f"routing {key} must be a string")
    _require(routing.get("action") in ROUTE_ACTIONS, errors, f"routing action is invalid: {routing.get('action')!r}")
    _require(routing.get("confidence") in ROUTE_CONFIDENCES, errors, f"routing confidence is invalid: {routing.get('confidence')!r}")
    _require(routing.get("threshold") in ROUTE_CONFIDENCES, errors, f"routing threshold is invalid: {routing.get('threshold')!r}")
    _require(isinstance(routing.get("score"), int), errors, "routing score must be an integer")
    _require(isinstance(routing.get("message_length"), int), errors, "routing message_length must be an integer")
    _require(isinstance(routing.get("explicit"), bool), errors, "routing explicit must be boolean")
    _require(isinstance(routing.get("ambiguous"), bool), errors, "routing ambiguous must be boolean")
    _require(isinstance(routing.get("recommendations"), list), errors, "routing recommendations must be a list")
    for index, recommendation in enumerate(routing.get("recommendations", [])):
        _require(isinstance(recommendation, dict), errors, f"routing recommendations[{index}] must be an object")
        if not isinstance(recommendation, dict):
            continue
        extra_keys = sorted(set(recommendation) - set(ROUTING_RECOMMENDATION_KEYS))
        _require(not extra_keys, errors, f"routing recommendations[{index}] has unsupported keys: {extra_keys}")
        _require(isinstance(recommendation.get("skill"), str), errors, f"routing recommendations[{index}].skill must be a string")
        _require(isinstance(recommendation.get("score"), int), errors, f"routing recommendations[{index}].score must be an integer")
        _require(isinstance(recommendation.get("confidence"), str), errors, f"routing recommendations[{index}].confidence must be a string")
        _require(isinstance(recommendation.get("matched"), list), errors, f"routing recommendations[{index}].matched must be a list")
    return errors


def validate_coding_delegation_record(delegation: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    extra_keys = sorted(set(delegation) - set(CODING_DELEGATION_RECORD_KEYS))
    _require(not extra_keys, errors, f"coding_delegation has unsupported keys: {extra_keys}")
    _require(
        delegation.get("schema_version") == CODING_DELEGATION_SCHEMA_VERSION,
        errors,
        "coding_delegation schema_version is invalid",
    )
    _require(delegation.get("record_type") == CODING_DELEGATION_RECORD_TYPE, errors, "coding_delegation record_type is invalid")
    for key in (
        "updated_at",
        "source",
        "action",
        "intent",
        "recommended_workflow",
        "recommended_harness",
        "executor_profile",
        "message_sha256",
        "status",
    ):
        _require(isinstance(delegation.get(key), str), errors, f"coding_delegation {key} must be a string")
    _require(delegation.get("action") in CODING_DELEGATION_ACTIONS, errors, f"coding_delegation action is invalid: {delegation.get('action')!r}")
    _require(delegation.get("intent") in CODING_DELEGATION_INTENTS, errors, f"coding_delegation intent is invalid: {delegation.get('intent')!r}")
    _require(delegation.get("status") in CODING_DELEGATION_STATUSES, errors, f"coding_delegation status is invalid: {delegation.get('status')!r}")
    _require(isinstance(delegation.get("review_required"), bool), errors, "coding_delegation review_required must be boolean")
    _require(
        delegation.get("review_workflow") is None or isinstance(delegation.get("review_workflow"), str),
        errors,
        "coding_delegation review_workflow must be a string or null",
    )
    _require(isinstance(delegation.get("message_length"), int), errors, "coding_delegation message_length must be an integer")
    if isinstance(delegation.get("message_length"), int):
        _require(delegation["message_length"] >= 0, errors, "coding_delegation message_length must be non-negative")
    _require(_is_sha256(str(delegation.get("message_sha256", ""))), errors, "coding_delegation message_sha256 must be a sha256 hex digest")
    _require(isinstance(delegation.get("source_metadata"), dict), errors, "coding_delegation source_metadata must be an object")
    metadata = delegation.get("source_metadata", {})
    if isinstance(metadata, dict):
        extra_metadata_keys = sorted(set(metadata) - set(CODING_SOURCE_METADATA_KEYS))
        _require(not extra_metadata_keys, errors, f"coding_delegation source_metadata has unsupported keys: {extra_metadata_keys}")
        for key, value in metadata.items():
            _require(isinstance(value, str), errors, f"coding_delegation source_metadata.{key} must be a string")
    _require(isinstance(delegation.get("recommendation_evidence"), list), errors, "coding_delegation recommendation_evidence must be a list")
    for index, recommendation in enumerate(delegation.get("recommendation_evidence", [])):
        _require(isinstance(recommendation, dict), errors, f"coding_delegation recommendation_evidence[{index}] must be an object")
        if not isinstance(recommendation, dict):
            continue
        extra_keys = sorted(set(recommendation) - set(CODING_RECOMMENDATION_KEYS))
        _require(not extra_keys, errors, f"coding_delegation recommendation_evidence[{index}] has unsupported keys: {extra_keys}")
        _require(isinstance(recommendation.get("skill"), str), errors, f"coding_delegation recommendation_evidence[{index}].skill must be a string")
        _require(isinstance(recommendation.get("score"), int), errors, f"coding_delegation recommendation_evidence[{index}].score must be an integer")
        _require(isinstance(recommendation.get("confidence"), str), errors, f"coding_delegation recommendation_evidence[{index}].confidence must be a string")
        _require(isinstance(recommendation.get("matched"), list), errors, f"coding_delegation recommendation_evidence[{index}].matched must be a list")
    for key in ("acceptance_criteria", "verification"):
        _require(isinstance(delegation.get(key), list), errors, f"coding_delegation {key} must be a list")
        if not isinstance(delegation.get(key), list):
            continue
        for index, value in enumerate(delegation[key]):
            _require(isinstance(value, str), errors, f"coding_delegation {key}[{index}] must be a string")
    if "executor_handoff" in delegation:
        errors.extend(validate_coding_executor_handoff(delegation["executor_handoff"]))
    return errors


def validate_wrapper_session_record(session: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    extra_keys = sorted(set(session) - set(WRAPPER_SESSION_RECORD_KEYS))
    _require(not extra_keys, errors, f"wrapper_session has unsupported keys: {extra_keys}")
    _require(session.get("schema_version") == WRAPPER_SESSION_SCHEMA_VERSION, errors, "wrapper_session schema_version is invalid")
    _require(session.get("record_type") == WRAPPER_SESSION_RECORD_TYPE, errors, "wrapper_session record_type is invalid")
    for key in ("session_id", "thread_key", "source", "message_sha256", "created_at", "updated_at", "status", "decision"):
        _require(isinstance(session.get(key), str), errors, f"wrapper_session {key} must be a string")
    _require(str(session.get("session_id", "")).startswith("ws-"), errors, "wrapper_session session_id must start with ws-")
    _require(bool(str(session.get("thread_key", ""))), errors, "wrapper_session thread_key is required")
    _require(session.get("status") in WRAPPER_SESSION_STATUSES, errors, f"wrapper_session status is invalid: {session.get('status')!r}")
    _require(session.get("decision") in WRAPPER_SESSION_DECISIONS, errors, f"wrapper_session decision is invalid: {session.get('decision')!r}")
    if session.get("status") in WRAPPER_SESSION_STATUS_DECISIONS:
        _require(
            session.get("decision") == WRAPPER_SESSION_STATUS_DECISIONS[session["status"]],
            errors,
            "wrapper_session decision must match status",
        )
    _require(isinstance(session.get("message_length"), int), errors, "wrapper_session message_length must be an integer")
    if isinstance(session.get("message_length"), int):
        _require(session["message_length"] >= 0, errors, "wrapper_session message_length must be non-negative")
    _require(_is_sha256(str(session.get("message_sha256", ""))), errors, "wrapper_session message_sha256 must be a sha256 hex digest")
    _require(session.get("redaction_policy") == "metadata_only", errors, "wrapper_session redaction_policy must be metadata_only")
    metadata = session.get("source_metadata")
    _require(isinstance(metadata, dict), errors, "wrapper_session source_metadata must be an object")
    if isinstance(metadata, dict):
        extra_metadata_keys = sorted(set(metadata) - set(WRAPPER_SESSION_SOURCE_METADATA_KEYS))
        _require(not extra_metadata_keys, errors, f"wrapper_session source_metadata has unsupported keys: {extra_metadata_keys}")
        for key, value in metadata.items():
            _require(isinstance(value, str), errors, f"wrapper_session source_metadata.{key} must be a string")
    route = session.get("route")
    _require(isinstance(route, dict), errors, "wrapper_session route must be an object")
    if isinstance(route, dict):
        extra_route_keys = sorted(set(route) - set(WRAPPER_SESSION_ROUTE_KEYS))
        _require(not extra_route_keys, errors, f"wrapper_session route has unsupported keys: {extra_route_keys}")
        if "score" in route:
            _require(isinstance(route["score"], int), errors, "wrapper_session route.score must be an integer")
    plan = session.get("plan")
    _require(isinstance(plan, dict), errors, "wrapper_session plan must be an object")
    if isinstance(plan, dict):
        extra_plan_keys = sorted(set(plan) - set(WRAPPER_SESSION_PLAN_KEYS))
        _require(not extra_plan_keys, errors, f"wrapper_session plan has unsupported keys: {extra_plan_keys}")
        for key, value in plan.items():
            _require(isinstance(value, str), errors, f"wrapper_session plan.{key} must be a string")
    _require(isinstance(session.get("current_run_id"), str), errors, "wrapper_session current_run_id must be a string")
    run_id = str(session.get("current_run_id", ""))
    if session.get("status") == "handoff_prepared":
        _require(bool(run_id), errors, "wrapper_session handoff_prepared requires current_run_id")
    elif isinstance(session.get("current_run_id"), str):
        _require(not run_id, errors, "wrapper_session current_run_id is only allowed for handoff_prepared")
    authority = session.get("authority")
    _require(isinstance(authority, dict), errors, "wrapper_session authority must be an object")
    if isinstance(authority, dict):
        _require(isinstance(authority.get("session_owns"), list), errors, "wrapper_session authority.session_owns must be a list")
        _require(isinstance(authority.get("run_ledger_owns"), list), errors, "wrapper_session authority.run_ledger_owns must be a list")
        forbidden = {"dispatch", "executor_result", "verification", "review", "ci", "merge_readiness", "merge"}
        session_owns = set(authority.get("session_owns", [])) if isinstance(authority.get("session_owns"), list) else set()
        _require(not (session_owns & forbidden), errors, "wrapper_session authority must not assign execution evidence to session")
        _require(
            session_owns == set(WRAPPER_SESSION_AUTHORITY_SESSION_OWNS),
            errors,
            "wrapper_session authority.session_owns must match the wrapper session authority contract",
        )
        run_ledger_owns = set(authority.get("run_ledger_owns", [])) if isinstance(authority.get("run_ledger_owns"), list) else set()
        _require(
            run_ledger_owns == set(WRAPPER_SESSION_AUTHORITY_RUN_LEDGER_OWNS),
            errors,
            "wrapper_session authority.run_ledger_owns must match the run ledger authority contract",
        )
    return errors


def validate_coding_executor_handoff(handoff: Any) -> list[str]:
    errors: list[str] = []
    _require(isinstance(handoff, dict), errors, "coding_delegation executor_handoff must be an object")
    if not isinstance(handoff, dict):
        return errors
    extra_keys = sorted(set(handoff) - set(CODING_EXECUTOR_HANDOFF_KEYS))
    _require(not extra_keys, errors, f"coding_delegation executor_handoff has unsupported keys: {extra_keys}")
    _require(
        handoff.get("schema_version") == CODING_EXECUTOR_HANDOFF_SCHEMA_VERSION,
        errors,
        "coding_delegation executor_handoff schema_version is invalid",
    )
    _require(
        handoff.get("executor_target") in CODING_EXECUTOR_TARGETS,
        errors,
        f"coding_delegation executor_handoff executor_target is invalid: {handoff.get('executor_target')!r}",
    )
    for key in ("handoff_mode", "status", "recording_contract", "dispatch_contract", "prompt_template"):
        _require(isinstance(handoff.get(key), str), errors, f"coding_delegation executor_handoff {key} must be a string")
    _require(
        handoff.get("status") == "prepared_not_observed",
        errors,
        "coding_delegation executor_handoff status must be prepared_not_observed",
    )
    _require(
        "{message}" in str(handoff.get("prompt_template", "")),
        errors,
        "coding_delegation executor_handoff prompt_template must keep {message} placeholder",
    )
    for key in ("scope", "non_goals", "acceptance_criteria", "verification"):
        _require(isinstance(handoff.get(key), list), errors, f"coding_delegation executor_handoff {key} must be a list")
        if isinstance(handoff.get(key), list):
            for index, value in enumerate(handoff[key]):
                _require(isinstance(value, str), errors, f"coding_delegation executor_handoff {key}[{index}] must be a string")
    review = handoff.get("review")
    _require(isinstance(review, dict), errors, "coding_delegation executor_handoff review must be an object")
    if isinstance(review, dict):
        _require(isinstance(review.get("required"), bool), errors, "coding_delegation executor_handoff review.required must be boolean")
        _require(
            review.get("workflow") is None or isinstance(review.get("workflow"), str),
            errors,
            "coding_delegation executor_handoff review.workflow must be a string or null",
        )
        _require(
            isinstance(review.get("evidence_required"), str),
            errors,
            "coding_delegation executor_handoff review.evidence_required must be a string",
        )
    return errors


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


OPTIONAL_RECORD_VALIDATORS = (
    ("routing.json", validate_routing_record),
    ("coding_delegation.json", validate_coding_delegation_record),
    ("delegation.json", validate_delegation_record),
    ("wrapper.json", validate_wrapper_record),
    ("review.json", validate_review_record),
    ("ci.json", validate_ci_record),
    ("merge.json", validate_merge_record),
)
