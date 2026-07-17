from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


PRODUCT_EVIDENCE_LOOP_SCHEMA_VERSION = "product_evidence_loop/v1"
PRODUCT_EVIDENCE_LOOP_DECISIONS = (
    "maintain",
    "research",
    "experiment",
    "implementation_candidate",
)
REFERENCE_AVAILABILITIES = ("not_supplied", "reference_supplied")
REFERENCE_PROVENANCES = (
    "hermes_reference",
    "user_supplied_reference",
    "local_record_reference",
)

_DECISION_SCOPE_ID_PATTERN = re.compile(r"^scope_[A-Fa-f0-9]{16,64}$")
_REFERENCE_ID_PATTERN = re.compile(r"^ref_[A-Fa-f0-9]{16,64}$")
_SOURCE_DESCRIPTOR_NAMES = ("research", "feedback", "supplied_data")


def _reference_descriptor(*, availability: str, reference_id: str, provenance: str, label: str) -> dict[str, str]:
    if availability not in REFERENCE_AVAILABILITIES:
        raise ValueError(f"{label} availability is invalid")
    if availability == "not_supplied":
        if reference_id or provenance:
            raise ValueError(f"{label} not_supplied metadata must be empty")
        return {"availability": availability, "reference_id": "", "provenance": ""}
    if not _REFERENCE_ID_PATTERN.fullmatch(reference_id):
        raise ValueError(f"{label} reference_id is invalid")
    if provenance not in REFERENCE_PROVENANCES:
        raise ValueError(f"{label} provenance is invalid")
    return {"availability": availability, "reference_id": reference_id, "provenance": provenance}


def build_product_evidence_loop(
    *,
    decision_scope_id: str,
    proposed_next_decision: str,
    research_availability: str = "not_supplied",
    research_reference_id: str = "",
    research_provenance: str = "",
    feedback_availability: str = "not_supplied",
    feedback_reference_id: str = "",
    feedback_provenance: str = "",
    supplied_data_availability: str = "not_supplied",
    supplied_data_reference_id: str = "",
    supplied_data_provenance: str = "",
    causal_identification_availability: str = "not_supplied",
    causal_identification_reference_id: str = "",
    causal_identification_provenance: str = "",
) -> dict[str, object]:
    if not _DECISION_SCOPE_ID_PATTERN.fullmatch(decision_scope_id):
        raise ValueError("decision_scope_id is invalid")
    if proposed_next_decision not in PRODUCT_EVIDENCE_LOOP_DECISIONS:
        raise ValueError("proposed_next_decision is invalid")
    source_descriptors = {
        "research": _reference_descriptor(
            availability=research_availability,
            reference_id=research_reference_id,
            provenance=research_provenance,
            label="research",
        ),
        "feedback": _reference_descriptor(
            availability=feedback_availability,
            reference_id=feedback_reference_id,
            provenance=feedback_provenance,
            label="feedback",
        ),
        "supplied_data": _reference_descriptor(
            availability=supplied_data_availability,
            reference_id=supplied_data_reference_id,
            provenance=supplied_data_provenance,
            label="supplied_data",
        ),
    }
    causal_identification_reference = _reference_descriptor(
        availability=causal_identification_availability,
        reference_id=causal_identification_reference_id,
        provenance=causal_identification_provenance,
        label="causal_identification",
    )
    return {
        "schema_version": PRODUCT_EVIDENCE_LOOP_SCHEMA_VERSION,
        "status": "prepared_not_observed",
        "decision_scope_id": decision_scope_id,
        "source_descriptors": source_descriptors,
        "epistemic_status_policy": {
            "claim_state": "unassessed_prepared",
            "required_separation": ["observed_facts", "inferences", "hypotheses", "causal_claims"],
            "evaluation_owner": "hermes",
        },
        "causal_claim_status": "unavailable_not_established",
        "causal_identification_reference": causal_identification_reference,
        "proposed_next_decision": proposed_next_decision,
        "decision_status": "suggested_not_accepted",
        "decision_rules": [
            "The next decision is caller-proposed and requires Hermes evaluation with observed evidence.",
            "A prepared card cannot accept a roadmap, implementation plan, handoff, or execution.",
        ],
        "stop_conditions": [
            "Required source evidence is unavailable or outside the declared decision scope.",
            "The requested claim exceeds the observed evidence or stated causal identification method.",
            "Raw source content, prompts, transcripts, or private data would be required in this metadata-only card.",
        ],
        "not_evidence_until_observed": [
            "source_retrieval",
            "feedback_analysis",
            "data_analysis",
            "causal_identification",
            "decision_acceptance",
            "implementation_handoff",
            "execution",
        ],
        "claim_boundary": (
            "This prepared product evidence loop records opaque source references and a caller-proposed next decision only. "
            "It does not retrieve, inspect, analyze, verify, calculate, establish causality, accept a decision, plan implementation, "
            "prepare a handoff, or execute work."
        ),
    }


def _descriptor_errors(value: object, *, label: str) -> list[str]:
    if not isinstance(value, dict) or set(value) != {"availability", "reference_id", "provenance"}:
        return [f"{label} descriptor is invalid"]
    availability = value.get("availability")
    reference_id = value.get("reference_id")
    provenance = value.get("provenance")
    if not isinstance(availability, str) or availability not in REFERENCE_AVAILABILITIES:
        return [f"{label} availability is invalid"]
    if not isinstance(reference_id, str) or not isinstance(provenance, str):
        return [f"{label} descriptor is invalid"]
    try:
        expected = _reference_descriptor(
            availability=availability,
            reference_id=reference_id,
            provenance=provenance,
            label=label,
        )
    except ValueError as exc:
        return [str(exc)]
    return [] if value == expected else [f"{label} descriptor is invalid"]


def validate_product_evidence_loop(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["product evidence loop must be an object"]
    required = {
        "schema_version",
        "status",
        "decision_scope_id",
        "source_descriptors",
        "epistemic_status_policy",
        "causal_claim_status",
        "causal_identification_reference",
        "proposed_next_decision",
        "decision_status",
        "decision_rules",
        "stop_conditions",
        "not_evidence_until_observed",
        "claim_boundary",
    }
    errors: list[str] = []
    can_rebuild = True
    if set(value) != required:
        errors.append("product evidence loop keys are invalid")
    decision_scope_id = value.get("decision_scope_id")
    proposed_next_decision = value.get("proposed_next_decision")
    if not isinstance(decision_scope_id, str) or not _DECISION_SCOPE_ID_PATTERN.fullmatch(decision_scope_id):
        errors.append("product evidence loop decision_scope_id is invalid")
        can_rebuild = False
    if not isinstance(proposed_next_decision, str) or proposed_next_decision not in PRODUCT_EVIDENCE_LOOP_DECISIONS:
        errors.append("product evidence loop proposed_next_decision is invalid")
        can_rebuild = False
    source_descriptors = value.get("source_descriptors")
    if not isinstance(source_descriptors, dict) or set(source_descriptors) != set(_SOURCE_DESCRIPTOR_NAMES):
        errors.append("product evidence loop source_descriptors are invalid")
        can_rebuild = False
    else:
        for name in _SOURCE_DESCRIPTOR_NAMES:
            descriptor_errors = _descriptor_errors(source_descriptors[name], label=name)
            errors.extend(descriptor_errors)
            if descriptor_errors:
                can_rebuild = False
    causal_errors = _descriptor_errors(value.get("causal_identification_reference"), label="causal_identification")
    errors.extend(causal_errors)
    if causal_errors:
        can_rebuild = False
    if not can_rebuild:
        return errors
    expected = build_product_evidence_loop(
        decision_scope_id=decision_scope_id,
        proposed_next_decision=proposed_next_decision,
        research_availability=str(source_descriptors["research"]["availability"]),
        research_reference_id=str(source_descriptors["research"]["reference_id"]),
        research_provenance=str(source_descriptors["research"]["provenance"]),
        feedback_availability=str(source_descriptors["feedback"]["availability"]),
        feedback_reference_id=str(source_descriptors["feedback"]["reference_id"]),
        feedback_provenance=str(source_descriptors["feedback"]["provenance"]),
        supplied_data_availability=str(source_descriptors["supplied_data"]["availability"]),
        supplied_data_reference_id=str(source_descriptors["supplied_data"]["reference_id"]),
        supplied_data_provenance=str(source_descriptors["supplied_data"]["provenance"]),
        causal_identification_availability=str(value["causal_identification_reference"]["availability"]),
        causal_identification_reference_id=str(value["causal_identification_reference"]["reference_id"]),
        causal_identification_provenance=str(value["causal_identification_reference"]["provenance"]),
    )
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            errors.append(f"product evidence loop {key} is invalid")
    return errors


def compact_product_evidence_loop(value: Any) -> dict[str, object]:
    if not isinstance(value, dict) or validate_product_evidence_loop(value):
        return {}
    return deepcopy(value)
