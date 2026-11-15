"""One paired-run cell over the sanctioned Hermes child bridge."""

from __future__ import annotations

import os
from pathlib import Path

from ..quality.paired_run_model import ArmRole, PairedRunDecision
from ..quality.paired_run_values import exposure_digest
from .hermes_child_dispatch import (
    DispatchConfirmationError,
    DispatchRecursionError,
    HermesChildDispatchError,
    HermesChildObservation,
    HermesChildRequest,
    dispatch_hermes_child,
)
from .hermes_child_arm_setup import PairedRunArmHome
from .hermes_child_evaluation import HermesChildEvaluationContext
from .hermes_child_receipts import (
    ReceiptVerificationError,
    hermes_child_run_dir,
    load_hermes_child_receipt,
    observation_key_open_flags,
    write_signed_observation,
)
from .paired_run_dispatch_model import PairedRunDispatchCell
from .paired_run_execution_model import (
    ExecutionState,
    PairedRunExecutionOutcome,
    PairedRunRunnerFailure,
)
from .paired_run_local_models import PairedRunLocalRunnerConfig
from .routing_observation import (
    JsonValue,
    authenticate_child_observation,
    build_routing_observation,
)


def run_hermes_paired_cell(
    decision_id: str,
    cell: PairedRunDispatchCell,
    prompt: str,
    worktree: Path,
    decision: PairedRunDecision,
    config: PairedRunLocalRunnerConfig,
    arm_home: PairedRunArmHome | None = None,
) -> PairedRunExecutionOutcome:
    """Dispatch one digest-checked task and load its process-sealed receipt."""
    task = next(task for task in decision.tasks if task.task_id == cell.task_id)
    arms = {
        ArmRole.BASELINE: decision.baseline,
        ArmRole.VARIANT: decision.variant,
    }
    arm = arms[cell.arm]
    evaluation_context = HermesChildEvaluationContext(
        cell.task_id,
        task.acceptance_criteria_ref,
        cell.input_digest,
        cell.arm.value,
        cell.executor,
        exposure_digest(arm.exposed_skills),
        cell.execution_revision,
    )
    try:
        run_dir = hermes_child_run_dir(
            config.paths.omh_home,
            cell.workspace_id,
            create_root=True,
        )
        run_dir.mkdir(mode=0o700, exist_ok=True)
        reservation = os.open(
            run_dir / "dispatch.reserved",
            observation_key_open_flags(),
            0o600,
        )
        os.close(reservation)
    except (FileExistsError, OSError, ReceiptVerificationError) as exc:
        raise PairedRunRunnerFailure("paired-run child reservation failed") from exc
    terminal: HermesChildObservation | None = None

    def observe(item: HermesChildObservation) -> None:
        nonlocal terminal
        observation = _child_observation(
            config,
            cell,
            decision_id,
            item.status,
        )
        write_signed_observation(
            run_dir,
            observation,
            None if item.status == "prepared" else item,
        )
        if item.status in {"completed", "failed", "timed_out", "cancelled"}:
            terminal = item

    try:
        result = dispatch_hermes_child(
            HermesChildRequest(
                prompt=prompt,
                model=cell.model,
                provider=config.provider,
                reasoning=config.reasoning,
                parent_run_id=decision_id,
                run_id=cell.workspace_id,
                timeout_seconds=config.timeout_seconds,
                hermes=config.hermes,
                cwd=worktree,
                evaluation_context=evaluation_context,
                allow_parallel=True,
                arm_home=arm_home,
            ),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
            observe=observe,
        )
    except (
        DispatchConfirmationError,
        DispatchRecursionError,
        HermesChildDispatchError,
        OSError,
        ValueError,
    ) as exc:
        raise PairedRunRunnerFailure("paired-run Hermes child failed") from exc
    if terminal is None:
        raise PairedRunRunnerFailure(
            "paired-run Hermes child produced no terminal observation"
        )
    try:
        receipt = load_hermes_child_receipt(
            config.paths.omh_home,
            cell.workspace_id,
        )
    except ReceiptVerificationError as exc:
        raise PairedRunRunnerFailure(
            "paired-run Hermes child receipt is invalid"
        ) from exc
    states = {
        "completed": ExecutionState.SUCCEEDED,
        "failed": ExecutionState.FAILED,
        "timed_out": ExecutionState.TIMED_OUT,
        "cancelled": ExecutionState.CANCELLED,
    }
    return PairedRunExecutionOutcome(
        states.get(result.status, ExecutionState.CRASHED),
        receipt,
        cell=cell,
    )


def _child_observation(
    config: PairedRunLocalRunnerConfig,
    cell: PairedRunDispatchCell,
    decision_id: str,
    status: str,
) -> dict[str, JsonValue]:
    route: dict[str, JsonValue] = {
        "selected_model": f"{config.provider}/{cell.model}",
        "selected_reasoning_effort": config.reasoning,
        "role": "agent_maintainer",
        "executor_profile": "hermes_child",
        "chain": [
            {
                "provider": config.provider,
                "model_id": cell.model,
                "reasoning_effort": config.reasoning,
            }
        ],
    }
    dispatch = (
        None
        if status == "prepared"
        else authenticate_child_observation(
            {"status": status, "run_id": cell.workspace_id}
        )
    )
    return build_routing_observation(
        route=route,
        child_dispatch=dispatch,
        parent_session_id=decision_id,
        child_session_id=cell.workspace_id,
        run_id=cell.workspace_id,
    )
