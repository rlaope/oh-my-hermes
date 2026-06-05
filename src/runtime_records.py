from __future__ import annotations

import hashlib
from typing import Any

from .coding_contracts import CODING_EXECUTOR_HANDOFF_TARGETS, EXECUTOR_HANDOFF_SCHEMA_VERSION
from .local_store import utc_now


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


def _compact_string_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return [str(value) for value in values if str(value)]


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
)
