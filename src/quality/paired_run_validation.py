"""Closed-schema parser for paired-run decision JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from .paired_run_aggregation import aggregate_results, aggregate_shape_errors
from .paired_run_limits import document_limit_errors, payload_limit_errors
from .paired_run_model import (
    AggregationScope,
    ArmRole,
    ArmSpec,
    DECISION_SCHEMA_V1,
    DECISION_SCHEMA_VERSIONS,
    InfrastructureStatus,
    PairedRunDecision,
    PairedRunValidationError,
    TaskSpec,
    aggregate_record,
)
from .paired_run_provenance import receipt_provenance_errors
from .paired_run_result_parsing import parse_result_records
from .paired_run_values import (
    MAX_DISPATCH_SECONDS,
    exposure_digest,
    is_digest,
    task_set_digest,
)
from .paired_run_validation_helpers import (
    append_banned_key_errors as _banned_keys,
    closed_shape_error as _closed,
    safe_ref_error as _safe_ref,
    utc_z_error as _utc_z,
)

_ROOT_KEYS: Final = {
    "schema_version", "decision_id", "supersedes_decision_ref", "baseline", "variant",
    "tasks", "task_set_digest", "max_total_runs", "max_dispatch_seconds",
    "execution_revision", "recorded_at",
    "results", "aggregate", "outcome", "claim_boundary",
}
_ARM_KEYS: Final = {"arm_id", "executor", "model", "exposed_skills", "exposure_digest"}
_TASK_KEYS: Final = {"task_id", "acceptance_criteria_ref", "input_digest"}
__all__ = ["PairedRunValidationError", "parse_paired_run_decision"]


def parse_paired_run_decision(
    document: str,
    receipt_context: Path | None = None,
) -> PairedRunDecision:
    """Parse a decision and re-verify every evidence-bearing receipt."""
    decision = _parse_structural_paired_run_decision(document)
    if errors := receipt_provenance_errors(decision, receipt_context):
        raise PairedRunValidationError(errors)
    return decision


def _parse_structural_paired_run_decision(document: str) -> PairedRunDecision:
    """Parse closed structure for trusted builders before receipt projection."""
    if limit_errors := document_limit_errors(document):
        raise PairedRunValidationError(tuple(limit_errors))
    try:
        payload = json.loads(document)
    except ValueError as exc:
        raise PairedRunValidationError(("document must be valid JSON",)) from exc
    except RecursionError as exc:
        raise PairedRunValidationError(("document exceeds the nesting limit",)) from exc
    errors: list[str] = []
    if not isinstance(payload, dict):
        raise PairedRunValidationError(("document must contain an object",))
    if limit_errors := payload_limit_errors(payload):
        raise PairedRunValidationError(tuple(limit_errors))
    if closure_error := _closed(payload, _ROOT_KEYS, "record"):
        errors.append(closure_error)
    try:
        _banned_keys(payload, errors)
    except RecursionError as exc:
        raise PairedRunValidationError(("document exceeds the nesting limit",)) from exc
    schema_version = payload.get("schema_version")
    if schema_version not in DECISION_SCHEMA_VERSIONS:
        errors.append("schema_version is invalid")
    timed = schema_version != DECISION_SCHEMA_V1
    for field in ("decision_id", "execution_revision"):
        _safe_ref(payload.get(field), field, errors)
    for field in ("outcome", "claim_boundary"):
        if not isinstance(payload.get(field), str) or not payload[field]:
            errors.append(f"{field} must be a non-empty string")
    for field in ("task_set_digest",):
        if not isinstance(payload.get(field), str) or not is_digest(payload[field]):
            errors.append(f"{field} must be a lowercase sha256 digest")
    _utc_z(payload.get("recorded_at"), "recorded_at", errors)
    supersedes = payload.get("supersedes_decision_ref")
    if supersedes is not None:
        _safe_ref(supersedes, "supersedes_decision_ref", errors)
    maximum = payload.get("max_total_runs")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
        errors.append("max_total_runs must be positive")
    dispatch_seconds = payload.get("max_dispatch_seconds")
    if (
        isinstance(dispatch_seconds, bool)
        or not isinstance(dispatch_seconds, int)
        or not 0 < dispatch_seconds <= MAX_DISPATCH_SECONDS
    ):
        errors.append("max_dispatch_seconds must be a positive bounded integer")
    baseline = _arm(payload.get("baseline"), "baseline", errors)
    variant = _arm(payload.get("variant"), "variant", errors)
    tasks = _tasks(payload.get("tasks"), errors)
    results = parse_result_records(payload.get("results"), errors, timed=timed)
    aggregate_payload = payload.get("aggregate")
    errors.extend(aggregate_shape_errors(aggregate_payload, with_speed=timed))
    if errors:
        raise PairedRunValidationError(tuple(errors))
    if baseline is None or variant is None:
        raise PairedRunValidationError(("baseline and variant are required",))
    if isinstance(maximum, bool) or not isinstance(maximum, int):
        raise PairedRunValidationError(("max_total_runs must be positive",))
    if isinstance(dispatch_seconds, bool) or not isinstance(dispatch_seconds, int):
        raise PairedRunValidationError(
            ("max_dispatch_seconds must be a positive bounded integer",)
        )
    if baseline.arm_id == variant.arm_id:
        errors.append("baseline and variant arm_id must differ")
    computed_task_digest = task_set_digest(tasks)
    if payload["task_set_digest"] != computed_task_digest:
        errors.append("task_set_digest does not match tasks")
    for label, arm, source in (
        ("baseline", baseline, payload["baseline"]),
        ("variant", variant, payload["variant"]),
    ):
        if source["exposure_digest"] != exposure_digest(arm.exposed_skills):
            errors.append(f"{label}.exposure_digest does not match exposed_skills")
    expected = {(task.task_id, role) for task in tasks for role in ArmRole}
    actual = [(item.task_id, item.arm) for item in results]
    if set(actual) != expected or len(actual) != len(expected):
        errors.append("results must contain the full task/arm matrix exactly once")
    if tasks != tuple(sorted(
        tasks,
        key=lambda item: (
            item.task_id,
            item.acceptance_criteria_ref,
            item.input_digest,
        ),
    )):
        errors.append("tasks must use canonical task_id and acceptance_criteria_ref order")
    if results != tuple(sorted(results, key=lambda item: (item.task_id, item.arm.value))):
        errors.append("results must use canonical task_id and arm order")
    attempted = sum(
        item.infrastructure_status is not InfrastructureStatus.NOT_OBSERVED
        for item in results
    )
    if attempted > maximum:
        errors.append("attempted result rows exceed max_total_runs")
    baseline_digest = exposure_digest(baseline.exposed_skills)
    variant_digest = exposure_digest(variant.exposed_skills)
    computed = aggregate_results(results, AggregationScope(
        computed_task_digest, baseline_digest, variant_digest,
    ))
    # The speed block is recomputed from the rows like every other aggregate
    # field, so a hand-edited verdict or total never survives a parse.
    expected_aggregate = json.loads(json.dumps(aggregate_record(computed, schema_version)))
    if aggregate_payload != expected_aggregate:
        errors.append("aggregate does not match results")
    if payload["outcome"] != computed.outcome:
        errors.append("outcome does not match results")
    if payload["claim_boundary"] != "behavior_from_signed_local_omh_dispatch_observation":
        errors.append("claim_boundary is invalid")
    if errors:
        raise PairedRunValidationError(tuple(errors))
    return PairedRunDecision(
        payload["schema_version"], payload["decision_id"], supersedes,
        baseline, variant, tasks, computed_task_digest, maximum, dispatch_seconds,
        payload["execution_revision"], payload["recorded_at"], results,
        computed, payload["claim_boundary"],
    )


def _arm(value, label: str, errors: list[str]) -> ArmSpec | None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return None
    start = len(errors)
    if closure_error := _closed(value, _ARM_KEYS, label):
        errors.append(closure_error)
    for field in ("arm_id", "executor", "model"):
        _safe_ref(value.get(field), f"{label}.{field}", errors)
    digest = value.get("exposure_digest")
    if not isinstance(digest, str) or not is_digest(digest):
        errors.append(f"{label}.exposure_digest must be a lowercase sha256 digest")
    skills = value.get("exposed_skills")
    if not isinstance(skills, list) or not all(isinstance(item, str) for item in skills):
        errors.append(f"{label}.exposed_skills must contain strings")
        return None
    for index, skill in enumerate(skills):
        _safe_ref(skill, f"{label}.exposed_skills[{index}]", errors)
    if skills != sorted(set(skills)):
        errors.append(f"{label}.exposed_skills must be sorted and unique")
    if len(errors) != start:
        return None
    return ArmSpec(value["arm_id"], value["executor"], value["model"], tuple(skills))


def _tasks(value, errors: list[str]) -> tuple[TaskSpec, ...]:
    if not isinstance(value, list) or not value:
        errors.append("tasks must be a non-empty list")
        return ()
    tasks: list[TaskSpec] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"tasks[{index}] must be an object")
            continue
        if closure_error := _closed(item, _TASK_KEYS, f"tasks[{index}]"):
            errors.append(closure_error)
        start = len(errors)
        for field in ("task_id", "acceptance_criteria_ref"):
            _safe_ref(item.get(field), f"tasks[{index}].{field}", errors)
        input_digest = item.get("input_digest")
        if not isinstance(input_digest, str):
            errors.append(f"tasks[{index}].input_digest must be a lowercase sha256 digest")
            continue
        if not is_digest(input_digest):
            errors.append(f"tasks[{index}].input_digest must be a lowercase sha256 digest")
            continue
        if len(errors) != start:
            continue
        tasks.append(TaskSpec(
            item["task_id"],
            item["acceptance_criteria_ref"],
            input_digest,
        ))
    if len({item.task_id for item in tasks}) != len(tasks):
        errors.append("task_id values must be unique")
    return tuple(tasks)
