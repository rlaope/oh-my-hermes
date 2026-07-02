from __future__ import annotations

import hashlib
import re
from typing import Any, Final

from .self_improvement_store_contract import (
    SELF_IMPROVEMENT_STORE_ROUTING_SCHEMA_VERSION,
    self_improvement_store_destination_details,
    self_improvement_store_destinations,
)
from .workflow_learning_errors import WorkflowLearningError


SELF_IMPROVEMENT_STORE_ROUTE_RECORD_SCHEMA_VERSION: Final = "self_improvement_store_route_record/v1"
STORE_ROUTE_REF_PREFIX: Final = "omh-learning-store-route"
PENDING_STORE_ROUTE_STATUS: Final = "pending_review"
REVIEW_DECISIONS: Final = ("approve_destination", "change_destination", "discard")
_RESOLVED_STATUS_BY_DECISION: Final = {
    "approve_destination": "approved",
    "change_destination": "changed",
    "discard": "discarded",
}
_SAFE_ROUTE_ID_RE: Final = re.compile(r"^[a-zA-Z0-9_.:-]+$")
_FORBIDDEN_ROUTE_RECORD_KEYS: Final = {
    "message",
    "rawmessage",
    "prompt",
    "rawprompt",
    "rawtext",
    "bodytext",
    "transcript",
    "conversation",
    "stdout",
    "stderr",
    "reviewnote",
    "rawreviewnote",
    "notetext",
}


def self_improvement_store_route_ref(route_id: str) -> str:
    return f"{STORE_ROUTE_REF_PREFIX}:{safe_self_improvement_store_route_id(route_id)}"


def safe_self_improvement_store_route_id(route_id: str) -> str:
    value = str(route_id).strip()
    if not value or not _SAFE_ROUTE_ID_RE.fullmatch(value):
        raise WorkflowLearningError("store route id is invalid")
    return value


def build_self_improvement_store_route_record(
    routing: dict[str, Any],
    *,
    source_ref: str = "",
    title: str = "",
) -> dict[str, Any]:
    _validate_store_routing(routing)
    destination = _routing_destination(routing)
    now = _utc_now()
    record = {
        "schema_version": SELF_IMPROVEMENT_STORE_ROUTE_RECORD_SCHEMA_VERSION,
        "record_type": "self_improvement_store_route",
        "route_id": _store_route_id(routing, source_ref=source_ref),
        "created_at": now,
        "updated_at": now,
        "status": PENDING_STORE_ROUTE_STATUS,
        "title": _clean_title(title) or f"Review self-improvement store route to {destination}",
        "source_ref": _clean_metadata(source_ref),
        "routing": routing,
        "destination_review": destination_review(destination),
        "review_gate": {
            "required": True,
            "decision": "pending",
            "allowed_decisions": list(REVIEW_DECISIONS),
            "reviewer_ref": "",
            "reviewed_at": "",
            "review_note_stored": False,
        },
        "writes_observed": False,
        "wrapper_actions": [
            "review_self_improvement_store_route",
            "approve_store_route",
            "change_store_route_destination",
            "discard_store_route",
            "show_learning_review_queue",
            "show_status",
        ],
        "not_evidence_yet": [
            "memory write",
            "skill patch",
            "wiki write",
            "failure retrospective accepted",
            "automation created",
            "destination artifact write",
            "CI",
            "merge",
        ],
        "claim_boundary": (
            "Self-improvement store route records persist metadata-only routing review state. "
            "They do not write memory, patch skills, update a wiki, create automation, accept a retrospective, "
            "or prove future behavior changed."
        ),
    }
    validate_self_improvement_store_route_record(record)
    return record


def reviewed_self_improvement_store_route_record(
    record: dict[str, Any],
    *,
    decision: str,
    destination: str = "",
    reviewer_ref: str = "operator",
    review_note: str = "",
) -> dict[str, Any]:
    validate_self_improvement_store_route_record(record)
    if decision not in REVIEW_DECISIONS:
        raise WorkflowLearningError("store route review decision is invalid")
    final_destination = _review_destination(record, decision=decision, destination=destination)
    now = _utc_now()
    reviewed = {
        **record,
        "updated_at": now,
        "status": _RESOLVED_STATUS_BY_DECISION[decision],
        "destination_review": destination_review(
            final_destination,
            initial_destination=str(_object(record["destination_review"])["initial_destination"]),
        ),
        "review_gate": _review_gate(decision, reviewer_ref=reviewer_ref, reviewed_at=now, review_note=review_note),
    }
    validate_self_improvement_store_route_record(reviewed)
    return reviewed


def validate_self_improvement_store_route_record(record: dict[str, Any]) -> None:
    _require_schema(record, SELF_IMPROVEMENT_STORE_ROUTE_RECORD_SCHEMA_VERSION)
    for key in ("record_type", "route_id", "created_at", "updated_at", "status", "title", "claim_boundary"):
        _require_string(record, key)
    if record.get("record_type") != "self_improvement_store_route":
        raise WorkflowLearningError("store route record_type is invalid")
    if record.get("status") not in {PENDING_STORE_ROUTE_STATUS, "approved", "changed", "discarded"}:
        raise WorkflowLearningError("store route status is invalid")
    _validate_store_routing(_object(record.get("routing")))
    _validate_destination_review(_object(record.get("destination_review")))
    _validate_review_gate(record)
    if record.get("writes_observed") is not False:
        raise WorkflowLearningError("store route record cannot claim observed writes")
    if not _strings(record.get("wrapper_actions")) or not _strings(record.get("not_evidence_yet")):
        raise WorkflowLearningError("store route record requires actions and evidence boundaries")
    _reject_raw_route_record_keys(record)


def destination_review(destination: str, *, initial_destination: str = "") -> dict[str, str]:
    details = self_improvement_store_destination_details(destination)
    return {
        "initial_destination": initial_destination or destination,
        "current_destination": destination,
        "target_workflow": details["target_workflow"],
        "target_record_type": details["target_record_type"],
        "next_action": details["next_action"],
    }


def store_route_current_destination(record: dict[str, Any]) -> str:
    return str(_object(record.get("destination_review")).get("current_destination", ""))


def _validate_destination_review(review: dict[str, Any]) -> None:
    destination = str(review.get("current_destination", ""))
    details = self_improvement_store_destination_details(destination)
    for key in ("initial_destination", "current_destination", "target_workflow", "target_record_type", "next_action"):
        _require_string(review, key)
    for key in ("target_workflow", "target_record_type", "next_action"):
        if review.get(key) != details[key]:
            raise WorkflowLearningError(f"store route destination_review.{key} is inconsistent")


def _validate_review_gate(record: dict[str, Any]) -> None:
    gate = _object(record.get("review_gate"))
    if gate.get("required") is not True:
        raise WorkflowLearningError("store route review gate must be required")
    decision = str(gate.get("decision", ""))
    if decision not in {"pending", *REVIEW_DECISIONS}:
        raise WorkflowLearningError("store route review decision is invalid")
    if record.get("status") == PENDING_STORE_ROUTE_STATUS and decision != "pending":
        raise WorkflowLearningError("pending store route must have pending decision")
    if record.get("status") != PENDING_STORE_ROUTE_STATUS and decision == "pending":
        raise WorkflowLearningError("resolved store route must have a review decision")
    if gate.get("review_note_stored") is not False:
        raise WorkflowLearningError("store route review note text must not be stored")


def _review_destination(record: dict[str, Any], *, decision: str, destination: str) -> str:
    match decision:
        case "approve_destination":
            return store_route_current_destination(record)
        case "change_destination":
            if destination not in set(self_improvement_store_destinations()):
                raise WorkflowLearningError("store route destination is required for change_destination")
            return destination
        case "discard":
            return "discard_transient"
        case _:
            raise WorkflowLearningError("store route review decision is invalid")


def _review_gate(decision: str, *, reviewer_ref: str, reviewed_at: str, review_note: str) -> dict[str, Any]:
    gate: dict[str, Any] = {
        "required": True,
        "decision": decision,
        "allowed_decisions": list(REVIEW_DECISIONS),
        "reviewer_ref": _clean_metadata(reviewer_ref) or "operator",
        "reviewed_at": reviewed_at,
        "review_note_stored": False,
    }
    if review_note:
        gate["review_note_sha256"] = hashlib.sha256(review_note.encode("utf-8")).hexdigest()
        gate["review_note_length"] = len(review_note)
    return gate


def _store_route_id(routing: dict[str, Any], *, source_ref: str) -> str:
    signal = _object(routing.get("signal"))
    seed = f"{signal.get('sha256', '')}:{_routing_destination(routing)}:{source_ref}"
    return "sir-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _routing_destination(routing: dict[str, Any]) -> str:
    return str(_object(routing.get("classification")).get("destination", ""))


def _validate_store_routing(routing: dict[str, Any]) -> None:
    _require_schema(routing, SELF_IMPROVEMENT_STORE_ROUTING_SCHEMA_VERSION)
    if routing.get("status") != "prepared":
        raise WorkflowLearningError("self-improvement store routing status must be prepared")
    for key in ("generated_at", "next_action", "claim_boundary"):
        _require_string(routing, key)
    signal = _object(routing.get("signal"))
    if signal.get("raw_text_stored") is not False:
        raise WorkflowLearningError("self-improvement store routing must not store raw signal text")
    for key in ("source_kind", "sha256"):
        _require_string(signal, key)
    if not isinstance(signal.get("length"), int) or signal.get("length") < 0:
        raise WorkflowLearningError("self-improvement store routing signal.length must be a non-negative integer")
    classification = _object(routing.get("classification"))
    details = self_improvement_store_destination_details(str(classification.get("destination", "")))
    for key in ("confidence", "target_workflow", "target_record_type", "next_action"):
        _require_string(classification, key)
        if str(classification.get(key)) != details[key]:
            raise WorkflowLearningError(f"self-improvement store routing classification.{key} is inconsistent")
    if not _strings(classification.get("routing_reasons")):
        raise WorkflowLearningError("self-improvement store routing requires routing reasons")
    destinations = set(self_improvement_store_destinations())
    alternatives = _strings(classification.get("alternative_destinations"))
    if any(item == classification.get("destination") or item not in destinations for item in alternatives):
        raise WorkflowLearningError("self-improvement store routing alternatives are invalid")
    gate = _object(routing.get("review_gate"))
    if gate.get("required") is not True or gate.get("decision") != "pending":
        raise WorkflowLearningError("self-improvement store routing requires a pending review gate")
    if not _strings(gate.get("allowed_decisions")):
        raise WorkflowLearningError("self-improvement store routing review gate decisions must be non-empty")
    wrapper_actions = _strings(routing.get("wrapper_actions"))
    if str(routing.get("next_action", "")) not in set(wrapper_actions):
        raise WorkflowLearningError("self-improvement store routing next_action must be listed in wrapper_actions")
    if routing.get("writes_observed") is not False:
        raise WorkflowLearningError("self-improvement store routing cannot claim observed writes")
    if not _strings(routing.get("not_evidence_yet")):
        raise WorkflowLearningError("self-improvement store routing not_evidence_yet must be non-empty")


def _clean_metadata(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.:/@#-]+", "-", str(value).strip())[:160]


def _clean_title(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip())[:120]


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkflowLearningError("store route object is invalid")
    return value


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _require_schema(value: dict[str, Any], schema_version: str) -> None:
    if value.get("schema_version") != schema_version:
        raise WorkflowLearningError(f"expected schema_version {schema_version}")


def _require_string(value: dict[str, Any], key: str) -> None:
    if not isinstance(value.get(key), str) or not value.get(key):
        raise WorkflowLearningError(f"store route {key} must be a non-empty string")


def _reject_raw_route_record_keys(value: object, *, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]+", "", str(key).casefold())
            current_path = (*path, str(key))
            allowed_raw_flag = current_path == ("routing", "signal", "raw_text_stored")
            if normalized in _FORBIDDEN_ROUTE_RECORD_KEYS or (normalized == "rawtextstored" and not allowed_raw_flag):
                raise WorkflowLearningError(f"store route record contains forbidden raw/private field: {'.'.join(current_path)}")
            _reject_raw_route_record_keys(child, path=current_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_raw_route_record_keys(child, path=(*path, str(index)))


def _utc_now() -> str:
    from ..local_store import utc_now

    return utc_now()
