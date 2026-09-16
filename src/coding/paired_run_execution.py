"""Execute an already-committed paired-run dispatch plan through injected seams."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import replace
from threading import BoundedSemaphore, Lock

from .paired_run_dispatch_model import PairedRunDispatchCell, PairedRunDispatchPlan
from .paired_run_dispatch_planner import record_terminal_state
from .paired_run_execution_model import (
    CrashDetailState,
    ExecutionState,
    PairedRunCleanupFailure,
    PairedRunCrashReason,
    PairedRunExecutionLimits,
    PairedRunExecutionOutcome,
    PairedRunExecutionReport,
    PairedRunRunnerFailure,
    PairedRunWorkspace,
    PairedRunWorkspaceFailure,
    crash_reason_for,
)
from .paired_run_execution_validation import (
    inferred_limits,
    receipt_authenticates,
    resume_index,
    terminal_state,
    validate_limits,
)
from .paired_run_execution_fan_in import (
    PairedRunExecutionFanInError,
    build_paired_run_execution_decision,
)

WorkspaceFactory = Callable[[PairedRunDispatchCell], PairedRunWorkspace]
Runner = Callable[[PairedRunDispatchCell, PairedRunWorkspace], PairedRunExecutionOutcome]
Cleaner = Callable[[PairedRunDispatchCell, PairedRunWorkspace], bool]

__all__ = [
    "Cleaner",
    "CrashDetailState",
    "ExecutionState",
    "PairedRunCleanupFailure",
    "PairedRunCrashReason",
    "PairedRunExecutionFanInError",
    "PairedRunExecutionLimits",
    "PairedRunExecutionOutcome",
    "PairedRunExecutionReport",
    "PairedRunRunnerFailure",
    "PairedRunWorkspace",
    "PairedRunWorkspaceFailure",
    "Runner",
    "WorkspaceFactory",
    "build_paired_run_execution_decision",
    "crash_reason_for",
    "execute_paired_run_plan",
]


def execute_paired_run_plan(
    plan: PairedRunDispatchPlan,
    *,
    workspace_factory: WorkspaceFactory,
    runner: Runner,
    cleaner: Cleaner,
    prior_receipts: Iterable[PairedRunExecutionOutcome] = (),
    limits: PairedRunExecutionLimits | None = None,
) -> PairedRunExecutionReport:
    """Run every dependency-free cell, leaving fan-in blocked on any untrusted row.

    The caller owns all side-effect seams. This function writes nothing and
    exposes no merge operation; its return value is metadata-only.
    """
    if not plan.launch_authorized:
        return PairedRunExecutionReport(plan, ())
    if any(cell.terminal_state is not None for cell in plan.cells):
        raise ValueError("execution requires a pristine committed paired-run plan")
    configured = limits or inferred_limits(plan.cells)
    validate_limits(configured, plan.cells)
    resumed = resume_index(plan.cells, tuple(prior_receipts))
    records: dict[str, PairedRunExecutionOutcome] = dict(resumed)
    pending = tuple(cell for cell in plan.cells if cell.workspace_id not in resumed)
    locks = _locks(configured, pending)
    for wave in _waves(pending):
        with ThreadPoolExecutor(max_workers=configured.global_concurrency) as pool:
            futures = [
                pool.submit(_execute_cell, cell, workspace_factory, runner, cleaner, locks)
                for cell in wave
            ]
            for future in futures:
                cell, outcome = future.result()
                records[cell.workspace_id] = outcome
    completed = plan
    ordered = tuple(records[cell.workspace_id] for cell in plan.cells)
    for outcome in ordered:
        completed = record_terminal_state(
            completed, outcome.cell.workspace_id, terminal_state(outcome.state)
        )
    return PairedRunExecutionReport(completed, ordered)


def _execute_cell(
    cell: PairedRunDispatchCell,
    workspace_factory: WorkspaceFactory,
    runner: Runner,
    cleaner: Cleaner,
    locks: dict[str, dict[str, Lock | BoundedSemaphore]],
) -> tuple[PairedRunDispatchCell, PairedRunExecutionOutcome]:
    workspace: PairedRunWorkspace | None = None
    created = False
    try:
        with ExitStack() as held:
            held.enter_context(locks["global"]["all"])
            held.enter_context(locks["executor"][cell.executor])
            held.enter_context(locks["provider"][cell.provider])
            if cell.shared_resource_key is not None:
                held.enter_context(locks["shared"][cell.shared_resource_key])
            workspace = workspace_factory(cell)
            created = True
            proposed = runner(cell, workspace)
        outcome = _authenticated_outcome(cell, proposed)
    except PairedRunWorkspaceFailure as exc:
        outcome = PairedRunExecutionOutcome(
            ExecutionState.CRASHED,
            None,
            cell=cell,
            cleanup_succeeded=exc.cleanup_succeeded,
            crash_reason=crash_reason_for(exc),
        )
    except PairedRunRunnerFailure as exc:
        outcome = PairedRunExecutionOutcome(
            ExecutionState.CRASHED, None, cell=cell, crash_reason=crash_reason_for(exc)
        )
    except Exception as exc:
        # The injected runner is an external boundary. Classify its failure so
        # this cell still reaches cleanup and sibling cells still terminate, and
        # record what raised so the crash is readable without reconstructing it.
        outcome = PairedRunExecutionOutcome(
            ExecutionState.CRASHED,
            None,
            cell=cell,
            crash_reason=crash_reason_for(exc),
        )
    if not created:
        return cell, outcome
    if workspace is None:
        raise RuntimeError("created paired-run workspace is missing")
    cleanup_reason: PairedRunCrashReason | None = None
    try:
        cleaned = cleaner(cell, workspace)
    except PairedRunCleanupFailure as exc:
        cleaned = False
        cleanup_reason = crash_reason_for(exc)
    except Exception as exc:
        # Cleanup failures are terminal evidence, not permission to abort the
        # matrix while other isolated cells are still running.
        cleaned = False
        cleanup_reason = crash_reason_for(exc)
    if cleaned is not True:
        outcome = replace(
            outcome,
            state=ExecutionState.CLEANUP_FAILED,
            cleanup_succeeded=False,
            # A runner that already crashed owns the cause; the cleaner's
            # failure is downstream of it and must not overwrite it.
            crash_reason=outcome.crash_reason or cleanup_reason,
        )
    else:
        outcome = replace(outcome, cleanup_succeeded=True)
    return cell, outcome


def _authenticated_outcome(
    cell: PairedRunDispatchCell,
    proposed: PairedRunExecutionOutcome,
) -> PairedRunExecutionOutcome:
    if not isinstance(proposed, PairedRunExecutionOutcome):
        return PairedRunExecutionOutcome(ExecutionState.CRASHED, None, cell=cell)
    if not isinstance(proposed.state, ExecutionState):
        return PairedRunExecutionOutcome(ExecutionState.CRASHED, None, cell=cell)
    if proposed.cell is not None and proposed.cell != cell:
        return PairedRunExecutionOutcome(
            ExecutionState.UNAUTHENTICATED, proposed.receipt, cell=cell
        )
    outcome = replace(proposed, cell=cell, reused=False)
    authenticated = receipt_authenticates(outcome, cell)
    if proposed.state is ExecutionState.SUCCEEDED and not authenticated:
        return replace(outcome, state=ExecutionState.UNAUTHENTICATED, authenticated=False)
    return replace(outcome, authenticated=authenticated)


def _waves(cells: tuple[PairedRunDispatchCell, ...]) -> tuple[tuple[PairedRunDispatchCell, ...], ...]:
    grouped: dict[int, list[PairedRunDispatchCell]] = defaultdict(list)
    for cell in cells:
        grouped[cell.launch_wave].append(cell)
    return tuple(tuple(grouped[index]) for index in sorted(grouped))


def _locks(
    limits: PairedRunExecutionLimits,
    cells: tuple[PairedRunDispatchCell, ...],
) -> dict[str, dict[str, Lock | BoundedSemaphore]]:
    return {
        "global": {"all": BoundedSemaphore(limits.global_concurrency)},
        "executor": {
            name: BoundedSemaphore(limit)
            for name, limit in limits.executor_concurrency.items()
        },
        "provider": {
            name: BoundedSemaphore(limit)
            for name, limit in limits.provider_concurrency.items()
        },
        "shared": {
            key: Lock()
            for key in {cell.shared_resource_key for cell in cells}
            if key is not None
        },
    }
