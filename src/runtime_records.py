from __future__ import annotations

from typing import Any

from .local_store import utc_now


SCHEMA_VERSION = 1
RUN_STATUSES = ("started", "completed", "blocked", "failed", "unknown")
PRIVACY_MODES = ("metadata_only",)
DELEGATION_RESULTS = ("completed", "blocked", "failed", "not_available", "not_observed")
OBSERVED_RESULTS = ("completed", "blocked", "failed")
UNOBSERVED_RESULTS = ("not_available", "not_observed")
EVENT_LEVELS = ("debug", "info", "warning", "error")
WRAPPER_COMPLETION_STATUSES = ("started", "completed", "blocked", "failed", "unknown")
ROUTE_ACTIONS = ("dispatch", "clarify", "fallback")
ROUTE_CONFIDENCES = ("low", "medium", "high")
ROUTING_RECOMMENDATION_KEYS = ("skill", "score", "confidence", "matched")


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
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": created_at,
        "updated_at": created_at,
        "skill": skill,
        "harness": harness,
        "trigger": metadata.get("trigger", ""),
        "status": status,
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


OPTIONAL_RECORD_VALIDATORS = (
    ("routing.json", validate_routing_record),
    ("delegation.json", validate_delegation_record),
    ("wrapper.json", validate_wrapper_record),
)
