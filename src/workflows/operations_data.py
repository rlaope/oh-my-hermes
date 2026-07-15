from __future__ import annotations

from copy import deepcopy
from typing import Any


OPERATIONS_DATA_HARNESS_SCHEMA_VERSION = "operations_data_harness/v1"
OPERATIONS_DATA_SHAPES = ("structured", "unstructured", "mixed")
OPERATIONS_ANALYSIS_MODES = ("descriptive", "relational", "causal")

_COLLECTION_REQUIREMENTS = {
    "structured": ("source_provenance", "schema_or_column_inventory", "row_scope_and_filter_record"),
    "unstructured": ("source_provenance", "corpus_scope", "extraction_or_annotation_method_record"),
    "mixed": ("source_provenance", "schema_or_column_inventory", "corpus_scope", "structured_to_unstructured_join"),
}

_RELATIONSHIP_CLAIMS = {
    "descriptive": "descriptive_only",
    "relational": "association_only",
    "causal": "causal_not_established",
}


def build_operations_data_harness(*, data_shape: str, analysis_mode: str) -> dict[str, object]:
    if data_shape not in OPERATIONS_DATA_SHAPES:
        raise ValueError(f"unsupported operations data shape: {data_shape}")
    if analysis_mode not in OPERATIONS_ANALYSIS_MODES:
        raise ValueError(f"unsupported operations analysis mode: {analysis_mode}")
    causal_requirements = (
        "temporal_order",
        "confounder_assessment",
        "comparison_or_identification_strategy",
        "selection_and_missingness_review",
        "mechanism_plausibility",
        "sensitivity_check",
    )
    return {
        "schema_version": OPERATIONS_DATA_HARNESS_SCHEMA_VERSION,
        "data_shape": data_shape,
        "analysis_mode": analysis_mode,
        "status": "prepared_not_observed",
        "collection_requirements": list(_COLLECTION_REQUIREMENTS[data_shape]),
        "stages": [
            "scope_question_and_decision",
            "record_source_provenance_and_access_boundary",
            "record_schema_corpus_and_join_assumptions",
            "prepare_collection_and_quality_checks",
            "prepare_analysis_method_and_uncertainty_checks",
            "assess_relationship_claim_boundary",
            "report_observed_results_and_remaining_gaps",
        ],
        "relationship_claim": _RELATIONSHIP_CLAIMS[analysis_mode],
        "causal_requirements": list(causal_requirements) if analysis_mode == "causal" else [],
        "misinterpretation_examples": [
            "A shared movement in temperature and revenue is an association, not evidence that temperature caused revenue.",
            "A text-to-row join can add selection or labeling bias even when both sources are accurate on their own.",
        ],
        "stop_conditions": [
            "Required provenance, permission, schema, corpus, or join evidence is unavailable.",
            "The requested relationship claim exceeds the supplied method or observed evidence.",
            "Raw private data, secrets, or unredacted transcripts would be needed for a metadata-only artifact.",
        ],
        "claim_boundary": (
            "This prepared operations-data harness does not collect data, access a source, extract text, join rows, run a query, "
            "calculate a statistic, establish causality, or prove a decision. Observed data and method evidence are required for results."
        ),
    }


def validate_operations_data_harness(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["operations data harness must be an object"]
    required = {
        "schema_version",
        "data_shape",
        "analysis_mode",
        "status",
        "collection_requirements",
        "stages",
        "relationship_claim",
        "causal_requirements",
        "misinterpretation_examples",
        "stop_conditions",
        "claim_boundary",
    }
    errors: list[str] = []
    if set(value) != required:
        errors.append("operations data harness keys are invalid")
    data_shape = value.get("data_shape")
    analysis_mode = value.get("analysis_mode")
    if not isinstance(data_shape, str) or data_shape not in OPERATIONS_DATA_SHAPES:
        errors.append("operations data harness data_shape is invalid")
    if not isinstance(analysis_mode, str) or analysis_mode not in OPERATIONS_ANALYSIS_MODES:
        errors.append("operations data harness analysis_mode is invalid")
    if errors:
        return errors
    expected = build_operations_data_harness(data_shape=data_shape, analysis_mode=analysis_mode)
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            errors.append(f"operations data harness {key} is invalid")
    return errors


def compact_operations_data_harness(value: Any) -> dict[str, object]:
    if not isinstance(value, dict) or validate_operations_data_harness(value):
        return {}
    return deepcopy(value)
