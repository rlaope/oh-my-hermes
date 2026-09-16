"""Build observed paired-run decisions from authenticated execution evidence."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from ..quality.paired_run_decision import build_paired_run_decision
from ..quality.paired_run_model import (
    ArmRole,
    BehaviorVerdict,
    InfrastructureStatus,
    PairedRunDecision,
    PairedRunRequest,
    RunResultInput,
    TaskSpec,
)
from ..quality.paired_run_receipt_binding import (
    ExpectedEvaluationBinding,
    evaluation_binding_errors,
)
from ..quality.paired_run_values import exposure_digest
from .hermes_child_receipts import (
    ReceiptVerificationError,
    is_verified_receipt,
    load_hermes_child_receipt,
)
from .paired_run_dispatch_model import PairedRunDispatchCell
from .paired_run_execution_model import (
    ExecutionState,
    PairedRunExecutionOutcome,
    PairedRunExecutionReport,
)
from .paired_run_execution_validation import normalized_cell, receipt_authenticates, terminal_state


class PairedRunExecutionFanInError(ValueError):
    """Execution evidence does not close the paired-run decision barrier."""

    def __init__(self, blockers: tuple[str, ...]) -> None:
        super().__init__(*blockers)
        self.blockers = blockers


def build_paired_run_execution_decision(
    request: PairedRunRequest,
    report: PairedRunExecutionReport,
    receipt_context: Path,
) -> PairedRunDecision:
    """Reduce a fully authenticated execution matrix into an observed decision.

    Behavioral verdicts must be explicit request values. Execution state, exit
    codes, and process output never determine behavior.
    """
    blockers = _fan_in_blockers(request, report, receipt_context)
    if blockers:
        raise PairedRunExecutionFanInError(blockers)
    return build_paired_run_decision(request, receipt_context)


def _fan_in_blockers(
    request: PairedRunRequest,
    report: PairedRunExecutionReport,
    receipt_context: Path,
) -> tuple[str, ...]:
    task_by_id = {task.task_id: task for task in request.tasks}
    expected = {
        (task.task_id, role)
        for task in request.tasks
        for role in (ArmRole.BASELINE, ArmRole.VARIANT)
    }
    rows = _result_index(request.results)
    cells = _cell_index(report.plan.cells)
    outcomes = _outcome_index(report.receipts)
    blockers: list[str] = []
    if not report.plan.launch_authorized:
        blockers.append("report: paired-run launch was not authorized")
    for key, count in Counter((cell.task_id, cell.arm) for cell in report.plan.cells).items():
        if count > 1:
            blockers.append(f"{_cell_label(cells.get(key), key)}: duplicate execution cell")
    for key, count in Counter((row.task_id, row.arm) for row in request.results).items():
        if count > 1:
            blockers.append(f"{_cell_label(cells.get(key), key)}: duplicate observed result")
    workspace_ids = {cell.workspace_id for cell in report.plan.cells}
    for item in report.receipts:
        if item.cell is None:
            blockers.append("report: missing execution identity")
        elif item.cell.workspace_id not in workspace_ids:
            blockers.append(f"{item.cell.workspace_id}: stale execution identity")
    if report.plan.decision_id != request.decision_id:
        blockers.append("report: decision_id does not match request")
    for key in sorted(expected, key=_cell_order):
        cell = cells.get(key)
        label = _cell_label(cell, key)
        if cell is None:
            blockers.append(f"{label}: missing execution cell")
            continue
        if _cell_identity_error(cell, task_by_id.get(key[0]), request):
            blockers.append(f"{label}: stale execution identity")
            continue
        row = rows.get(key)
        if (
            row is None
            or row.infrastructure_status is not InfrastructureStatus.OBSERVED
            or row.behavior_verdict is BehaviorVerdict.NOT_OBSERVED
        ):
            blockers.append(f"{label}: missing observed result")
            continue
        if cell.terminal_state is None:
            blockers.append(f"{label}: missing terminal state")
            continue
        items = outcomes.get(cell.workspace_id, ())
        if len(items) != 1:
            reason = "missing execution outcome" if not items else "duplicate execution outcome"
            blockers.append(f"{label}: {reason}")
            continue
        task = task_by_id.get(key[0])
        if task is None:
            blockers.append(f"{label}: stale execution identity")
            continue
        reason = _outcome_error(cell, row, task, request, items[0], receipt_context)
        if reason is not None:
            blockers.append(f"{label}: {reason}")
    for key, cell in cells.items():
        if key not in expected:
            blockers.append(f"{cell.workspace_id}: stale execution identity")
    return tuple(blockers)


def _result_index(
    results: tuple[RunResultInput, ...],
) -> dict[tuple[str, ArmRole], RunResultInput]:
    indexed: dict[tuple[str, ArmRole], RunResultInput] = {}
    for item in results:
        key = (item.task_id, item.arm)
        if key not in indexed:
            indexed[key] = item
    return indexed


def _cell_index(
    cells: tuple[PairedRunDispatchCell, ...],
) -> dict[tuple[str, ArmRole], PairedRunDispatchCell]:
    indexed: dict[tuple[str, ArmRole], PairedRunDispatchCell] = {}
    for cell in cells:
        key = (cell.task_id, cell.arm)
        if key not in indexed:
            indexed[key] = cell
    return indexed


def _outcome_index(
    outcomes: tuple[PairedRunExecutionOutcome, ...],
) -> dict[str, tuple[PairedRunExecutionOutcome, ...]]:
    indexed: dict[str, tuple[PairedRunExecutionOutcome, ...]] = {}
    for item in outcomes:
        if item.cell is None:
            continue
        workspace_id = item.cell.workspace_id
        indexed[workspace_id] = (*indexed.get(workspace_id, ()), item)
    return indexed


def _cell_order(key: tuple[str, ArmRole]) -> tuple[str, str]:
    return key[0], key[1].value


def _cell_label(
    cell: PairedRunDispatchCell | None,
    key: tuple[str, ArmRole],
) -> str:
    return cell.workspace_id if cell is not None else f"{key[0]}/{key[1].value}"


def _cell_identity_error(
    cell: PairedRunDispatchCell,
    task: TaskSpec | None,
    request: PairedRunRequest,
) -> bool:
    if task is None:
        return True
    arm = request.baseline if cell.arm is ArmRole.BASELINE else request.variant
    return (
        cell.input_digest != task.input_digest
        or cell.execution_revision != request.execution_revision
        or cell.executor != arm.executor
        or cell.model != arm.model
    )


def _outcome_error(
    cell: PairedRunDispatchCell,
    row: RunResultInput,
    task: TaskSpec,
    request: PairedRunRequest,
    outcome: PairedRunExecutionOutcome,
    receipt_context: Path,
) -> str | None:
    if outcome.cell is None or normalized_cell(outcome.cell) != normalized_cell(cell):
        return "stale execution identity"
    if outcome.state is not ExecutionState.SUCCEEDED:
        return _execution_state_error(outcome)
    if cell.terminal_state is not terminal_state(outcome.state):
        return "stale terminal state"
    if outcome.cleanup_succeeded is not True:
        return "cleanup is incomplete"
    if outcome.receipt is None:
        return "missing authenticated receipt"
    if row.receipt != outcome.receipt:
        return "receipt does not match successful execution"
    if not outcome.authenticated or not receipt_authenticates(outcome, cell):
        return "unauthenticated execution outcome"
    if not is_verified_receipt(outcome.receipt):
        return "unauthenticated persisted receipt"
    try:
        persisted = load_hermes_child_receipt(receipt_context, outcome.receipt.run_id)
    except ReceiptVerificationError:
        return "persisted receipt could not be verified"
    if persisted != outcome.receipt:
        return "persisted receipt does not match execution receipt"
    return _binding_error(cell, row, task, request)


def _execution_state_error(outcome: PairedRunExecutionOutcome) -> str:
    """Name the cause a contained cell recorded, not only the state it produced.

    A blocker that reports the shape of the result sends the reader back to
    reconstruct the fault from surviving evidence. When the cell carried its
    exception across the containment boundary, say so here.
    """
    state = f"{outcome.state.value} execution state"
    if outcome.crash_reason is None:
        return state
    return f"{state}: {outcome.crash_reason.label}"


def _binding_error(
    cell: PairedRunDispatchCell,
    row: RunResultInput,
    task: TaskSpec,
    request: PairedRunRequest,
) -> str | None:
    receipt = row.receipt
    if receipt is None:
        return "missing authenticated receipt"
    arm = request.baseline if cell.arm is ArmRole.BASELINE else request.variant
    errors = evaluation_binding_errors(
        receipt.evaluation_binding,
        ExpectedEvaluationBinding(
            task.task_id,
            task.acceptance_criteria_ref,
            task.input_digest,
            cell.arm.value,
            arm.executor,
            arm.model,
            exposure_digest(tuple(sorted(arm.exposed_skills))),
            request.execution_revision,
            request.max_dispatch_seconds,
        ),
    )
    return errors[0] if errors else None
