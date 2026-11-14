"""Shared HMAC receipt verification for evidence-bearing paired-run rows."""

from __future__ import annotations

from pathlib import Path

from ..coding.hermes_child_receipts import (
    ReceiptVerificationError,
    load_hermes_child_receipt,
)
from .paired_run_model import (
    ArmRole,
    DECISION_SCHEMA_V1,
    InfrastructureStatus,
    PairedRunDecision,
)
from .paired_run_receipt_binding import (
    ExpectedEvaluationBinding,
    evaluation_binding_errors,
    receipt_reference_uniqueness_errors,
)
from .paired_run_values import exposure_digest


def receipt_provenance_errors(
    decision: PairedRunDecision,
    omh_home: Path | None,
) -> tuple[str, ...]:
    """Return receipt trust errors after re-reading signed local observations."""
    evidence = tuple(
        row
        for row in decision.results
        if row.infrastructure_status is not InfrastructureStatus.NOT_OBSERVED
    )
    if not evidence:
        return ()
    if omh_home is None:
        return ("evidence-bearing decisions require explicit receipt context",)
    refs = tuple(row.receipt_ref for row in evidence if row.receipt_ref is not None)
    if errors := receipt_reference_uniqueness_errors(refs):
        return errors
    tasks = {task.task_id: task for task in decision.tasks}
    arms = {
        ArmRole.BASELINE: decision.baseline,
        ArmRole.VARIANT: decision.variant,
    }
    for row in evidence:
        if (
            row.receipt_ref is None
            or row.receipt_run_id is None
            or row.receipt_observed_at is None
            or row.receipt_status is None
        ):
            return ("receipt provenance is incomplete",)
        try:
            receipt = load_hermes_child_receipt(omh_home, row.receipt_run_id)
        except ReceiptVerificationError:
            return ("receipt provenance could not be verified",)
        if (
            receipt.receipt_ref != row.receipt_ref
            or receipt.run_id != row.receipt_run_id
            or receipt.status != row.receipt_status
            or receipt.observed_at != row.receipt_observed_at
            or (
                decision.schema_version != DECISION_SCHEMA_V1
                and receipt.elapsed_seconds != row.receipt_elapsed_seconds
            )
        ):
            return ("receipt provenance does not match persisted observation",)
        task = tasks[row.task_id]
        arm = arms[row.arm]
        if errors := evaluation_binding_errors(
            receipt.evaluation_binding,
            ExpectedEvaluationBinding(
                task.task_id,
                task.acceptance_criteria_ref,
                task.input_digest,
                row.arm.value,
                arm.executor,
                arm.model,
                exposure_digest(arm.exposed_skills),
                decision.execution_revision,
                decision.max_dispatch_seconds,
            ),
        ):
            return errors
    return ()
