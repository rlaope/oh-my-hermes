"""Builder and validation facade for paired-run decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from .paired_run_aggregation import aggregate_results
from .paired_run_model import (
    AggregationScope,
    ArmRole,
    ArmSpec,
    DECISION_SCHEMA_V2,
    InfrastructureStatus,
    PairedRunDecision,
    PairedRunRequest,
    PairedRunValidationError,
    RecordedResult,
    RunResultInput,
)
from .paired_run_receipt_binding import (
    ExpectedEvaluationBinding,
    evaluation_binding_errors,
    receipt_reference_uniqueness_errors,
)
from .paired_run_provenance import receipt_provenance_errors
from .paired_run_values import (
    MAX_DISPATCH_SECONDS,
    exposure_digest,
    is_digest,
    task_set_digest,
)

# New decisions are always built as v2; v1 documents still parse.
SCHEMA_VERSION: Final = DECISION_SCHEMA_V2
CLAIM_BOUNDARY: Final = "behavior_from_signed_local_omh_dispatch_observation"


def _recorded(result: RunResultInput) -> RecordedResult:
    receipt = result.receipt
    return RecordedResult(
        result.task_id,
        result.arm,
        result.infrastructure_status,
        result.behavior_verdict,
        receipt.receipt_ref if receipt is not None else None,
        receipt.run_id if receipt is not None else None,
        receipt.observed_at if receipt is not None else None,
        receipt.status if receipt is not None else None,
        receipt.elapsed_seconds if receipt is not None else None,
    )


def build_paired_run_decision(
    request: PairedRunRequest,
    receipt_context: Path | None = None,
) -> PairedRunDecision:
    errors: list[str] = []
    if request.max_total_runs <= 0:
        errors.append("max_total_runs must be positive")
    if (
        isinstance(request.max_dispatch_seconds, bool)
        or not isinstance(request.max_dispatch_seconds, int)
        or not 0 < request.max_dispatch_seconds <= MAX_DISPATCH_SECONDS
    ):
        errors.append("max_dispatch_seconds must be a positive bounded integer")
    if not request.tasks or len({item.task_id for item in request.tasks}) != len(request.tasks):
        errors.append("tasks must be non-empty with unique task_id values")
    if any(not is_digest(item.input_digest) for item in request.tasks):
        errors.append("each task requires a lowercase sha256 input_digest")
    expected = {
        (task.task_id, role)
        for task in request.tasks
        for role in (ArmRole.BASELINE, ArmRole.VARIANT)
    }
    actual = [(item.task_id, item.arm) for item in request.results]
    if set(actual) != expected or len(actual) != len(expected):
        errors.append("results must contain the full task/arm matrix exactly once")
    attempted = sum(
        item.infrastructure_status is not InfrastructureStatus.NOT_OBSERVED
        for item in request.results
    )
    if attempted > request.max_total_runs:
        errors.append("attempted result rows exceed max_total_runs")
    errors.extend(_request_binding_errors(request))
    for arm in (request.baseline, request.variant):
        if (
            len(set(arm.exposed_skills)) != len(arm.exposed_skills)
            or any(not skill for skill in arm.exposed_skills)
        ):
            errors.append("each arm requires unique non-empty exposed skill values")
    if errors:
        raise PairedRunValidationError(tuple(errors))
    baseline = ArmSpec(
        request.baseline.arm_id,
        request.baseline.executor,
        request.baseline.model,
        tuple(sorted(request.baseline.exposed_skills)),
    )
    variant = ArmSpec(
        request.variant.arm_id,
        request.variant.executor,
        request.variant.model,
        tuple(sorted(request.variant.exposed_skills)),
    )
    tasks = tuple(sorted(
        request.tasks,
        key=lambda item: (
            item.task_id,
            item.acceptance_criteria_ref,
            item.input_digest,
        ),
    ))
    recorded = tuple(sorted(
        (_recorded(item) for item in request.results),
        key=lambda item: (item.task_id, item.arm.value),
    ))
    task_digest = task_set_digest(tasks)
    baseline_digest = exposure_digest(baseline.exposed_skills)
    variant_digest = exposure_digest(variant.exposed_skills)
    candidate = PairedRunDecision(
        SCHEMA_VERSION,
        request.decision_id,
        request.supersedes_decision_ref,
        baseline,
        variant,
        tasks,
        task_digest,
        request.max_total_runs,
        request.max_dispatch_seconds,
        request.execution_revision,
        request.recorded_at,
        recorded,
        aggregate_results(
            recorded,
            AggregationScope(task_digest, baseline_digest, variant_digest),
        ),
        CLAIM_BOUNDARY,
    )
    from .paired_run_validation import _parse_structural_paired_run_decision

    parsed = _parse_structural_paired_run_decision(candidate.to_json())
    if provenance_errors := receipt_provenance_errors(parsed, receipt_context):
        raise PairedRunValidationError(provenance_errors)
    return parsed


def _request_binding_errors(request: PairedRunRequest) -> tuple[str, ...]:
    tasks = {task.task_id: task for task in request.tasks}
    arms = {
        ArmRole.BASELINE: request.baseline,
        ArmRole.VARIANT: request.variant,
    }
    errors: list[str] = []
    refs: list[str] = []
    for result in request.results:
        if result.infrastructure_status is InfrastructureStatus.NOT_OBSERVED:
            continue
        receipt = result.receipt
        task = tasks.get(result.task_id)
        if receipt is None or task is None:
            errors.append("attempted result receipt requires a complete evaluation binding")
            continue
        arm = arms[result.arm]
        refs.append(receipt.receipt_ref)
        errors.extend(evaluation_binding_errors(
            receipt.evaluation_binding,
            ExpectedEvaluationBinding(
                task.task_id,
                task.acceptance_criteria_ref,
                task.input_digest,
                result.arm.value,
                arm.executor,
                arm.model,
                exposure_digest(tuple(sorted(arm.exposed_skills))),
                request.execution_revision,
                request.max_dispatch_seconds,
            ),
        ))
    errors.extend(receipt_reference_uniqueness_errors(tuple(refs)))
    return tuple(errors)


def parse_paired_run_decision(
    document: str,
    receipt_context: Path | None = None,
) -> PairedRunDecision:
    from .paired_run_validation import parse_paired_run_decision as parse

    return parse(document, receipt_context)


def validate_paired_run_decision(
    document: str,
    receipt_context: Path | None = None,
) -> tuple[str, ...]:
    try:
        parse_paired_run_decision(document, receipt_context)
    except PairedRunValidationError as exc:
        return exc.errors
    return ()
