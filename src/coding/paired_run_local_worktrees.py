"""Detached worktree lifecycle for explicit paired-run execution."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from subprocess import SubprocessError
from tempfile import mkdtemp
from threading import Lock

from ..quality.paired_run_model import ArmRole, PairedRunDecision
from ..runtime.critical_path_health_models import CriticalPathTerminalStatus
from .fanout_dispatch import signal_safe_unit_runner
from .fanout_health_events import FanoutHealthEvents, monotonic_milliseconds
from .paired_run_health_events import write_paired_run_health_event
from .paired_run_dispatch_model import PairedRunDispatchCell, PairedRunDispatchPlan
from .paired_run_execution import execute_paired_run_plan
from .paired_run_execution_model import (
    PairedRunCleanupFailure,
    PairedRunExecutionOutcome,
    PairedRunExecutionReport,
    PairedRunRunnerFailure,
    PairedRunWorkspace,
    PairedRunWorkspaceFailure,
)
from .paired_run_arm_home import ArmHomeRun
from .paired_run_hermes_adapter import run_hermes_paired_cell
from .paired_run_local_models import PairedRunLocalRunnerConfig


def execute_local_paired_plan(
    plan: PairedRunDispatchPlan,
    decision: PairedRunDecision,
    contents: Mapping[str, str],
    config: PairedRunLocalRunnerConfig,
    arm_homes: Mapping[ArmRole, ArmHomeRun] | None = None,
) -> PairedRunExecutionReport:
    """Execute each frozen cell from a distinct detached checkout."""
    worktrees: dict[str, Path] = {}
    reserved_paths: set[Path] = set()
    worktree_lock = Lock()
    invocation_root = Path(
        mkdtemp(
            prefix="omh-paired-run-",
            dir=config.repo_root.parent,
        )
    )
    health = FanoutHealthEvents(
        fanout_id=plan.decision_id,
        revision=decision.execution_revision,
        emit=lambda event: write_paired_run_health_event(
            config.paths,
            plan.decision_id,
            event,
        ),
        clock=monotonic_milliseconds,
        executor="paired_run",
        model="frozen_matrix",
        environment="omh",
    )
    for cell in plan.cells:
        health.queued(
            cell.workspace_id,
            dependencies=(),
            resource_class=cell.executor,
        )

    def workspace_factory(cell: PairedRunDispatchCell) -> PairedRunWorkspace:
        path = invocation_root / cell.workspace_id
        health.started(cell.workspace_id)
        with worktree_lock:
            if path in reserved_paths or path.exists():
                health.finished(cell.workspace_id, terminal_status="failed")
                raise PairedRunWorkspaceFailure(
                    "paired-run worktree reservation collision"
                )
            reserved_paths.add(path)
        try:
            added = _add_worktree(
                config.repo_root, path, cell.execution_revision
            )
        except (OSError, SubprocessError) as exc:
            health.finished(cell.workspace_id, terminal_status="failed")
            cleaned = _cleanup_owned_path(
                health,
                cell,
                config.repo_root,
                path,
                invocation_root,
                reserved_paths,
                worktree_lock,
            )
            raise PairedRunWorkspaceFailure(
                "paired-run worktree creation failed",
                cleanup_succeeded=cleaned,
            ) from exc
        if added != 0:
            health.finished(cell.workspace_id, terminal_status="failed")
            cleaned = _cleanup_owned_path(
                health,
                cell,
                config.repo_root,
                path,
                invocation_root,
                reserved_paths,
                worktree_lock,
            )
            raise PairedRunWorkspaceFailure(
                "paired-run worktree creation failed",
                cleanup_succeeded=cleaned,
            )
        with worktree_lock:
            worktrees[cell.workspace_id] = path
        return PairedRunWorkspace(cell.workspace_id)

    def runner(
        cell: PairedRunDispatchCell,
        workspace: PairedRunWorkspace,
    ) -> PairedRunExecutionOutcome:
        with worktree_lock:
            path = worktrees.get(workspace.workspace_id)
        if path is None or workspace.workspace_id != cell.workspace_id:
            raise PairedRunRunnerFailure("paired-run workspace identity mismatch")
        try:
            outcome = run_hermes_paired_cell(
                plan.decision_id,
                cell,
                contents[cell.task_id],
                path,
                decision,
                config,
                None if arm_homes is None else arm_homes[cell.arm].arm_home,
            )
        except PairedRunRunnerFailure:
            health.finished(cell.workspace_id, terminal_status="failed")
            raise
        health.finished(
            cell.workspace_id,
            terminal_status=_health_status(outcome),
        )
        return outcome

    def cleaner(
        cell: PairedRunDispatchCell,
        workspace: PairedRunWorkspace,
    ) -> bool:
        with worktree_lock:
            path = worktrees.pop(workspace.workspace_id, None)
        if path is None or workspace.workspace_id != cell.workspace_id:
            raise PairedRunCleanupFailure("paired-run workspace identity mismatch")
        return _cleanup_owned_path(
            health,
            cell,
            config.repo_root,
            path,
            invocation_root,
            reserved_paths,
            worktree_lock,
        )

    report = execute_paired_run_plan(
        plan,
        workspace_factory=workspace_factory,
        runner=runner,
        cleaner=cleaner,
    )
    if all(item.cleanup_succeeded is not False for item in report.receipts):
        try:
            invocation_root.rmdir()
        except OSError as exc:
            raise PairedRunCleanupFailure(
                "paired-run invocation root cleanup failed"
            ) from exc
    return report


def _add_worktree(repo: Path, path: Path, revision: str) -> int:
    completed = signal_safe_unit_runner(
        ["git", "worktree", "add", "--detach", str(path), revision],
        cwd=str(repo),
        text=True,
        capture_output=True,
        timeout=120,
    )
    return int(completed.returncode)


def _health_status(
    outcome: PairedRunExecutionOutcome,
) -> CriticalPathTerminalStatus:
    if outcome.state.value == "succeeded":
        return "succeeded"
    if outcome.state.value == "cancelled":
        return "cancelled"
    return "failed"


def _cleanup_path(
    health: FanoutHealthEvents,
    cell: PairedRunDispatchCell,
    repo: Path,
    path: Path,
) -> bool:
    cleanup_id = f"{cell.workspace_id}:cleanup"
    health.queued(
        cleanup_id,
        dependencies=(cell.workspace_id,),
        resource_class="cleanup",
        phase="cleanup",
    )
    health.started(cleanup_id, phase="cleanup")
    try:
        _removed = _remove_worktree(repo, path)
    except (OSError, SubprocessError):
        _removed = -1
    cleaned = not path.exists()
    health.finished(
        cleanup_id,
        terminal_status="succeeded" if cleaned else "failed",
        phase="cleanup",
    )
    return cleaned


def _cleanup_owned_path(
    health: FanoutHealthEvents,
    cell: PairedRunDispatchCell,
    repo: Path,
    path: Path,
    invocation_root: Path,
    reserved_paths: set[Path],
    worktree_lock: Lock,
) -> bool:
    with worktree_lock:
        owned = path.parent == invocation_root and path in reserved_paths
    if not owned:
        raise PairedRunCleanupFailure(
            "paired-run cleanup refused a worktree this invocation did not own"
        )
    cleaned = _cleanup_path(health, cell, repo, path)
    if cleaned:
        with worktree_lock:
            reserved_paths.discard(path)
    return cleaned


def _remove_worktree(repo: Path, path: Path) -> int:
    completed = signal_safe_unit_runner(
        ["git", "worktree", "remove", "--force", str(path)],
        cwd=str(repo),
        text=True,
        capture_output=True,
        timeout=120,
    )
    return int(completed.returncode)
