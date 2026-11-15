from __future__ import annotations

from pathlib import Path

from omh.coding.hermes_child_receipts import load_hermes_child_receipt
from omh.coding.paired_run_dispatch import (
    ApprovalState,
    ArmDispatchTarget,
    CostTimeBound,
    DispatchBudgets,
    NamedConcurrencyBudget,
    PairedRunDispatchConfig,
    SharedResourceMode,
    plan_paired_run_dispatch,
)
from omh.coding.paired_run_execution import PairedRunWorkspace
from omh.quality.paired_run_decision import build_paired_run_decision
from omh.quality.paired_run_model import (
    ArmRole,
    ArmSpec,
    BehaviorVerdict,
    InfrastructureStatus,
    PairedRunRequest,
    RunResultInput,
    TaskSpec,
)
from omh.quality.paired_run_values import exposure_digest
from paired_run_support import paired_evaluation_binding, write_observed_receipt


def plan(
    *, approval: ApprovalState = ApprovalState.APPROVED, dry_run: bool = False,
    provider_limit: int = 1, shared_resource_key: str | None = "repo-lock",
):
    tasks = (
        TaskSpec("task-a", "criteria-a", "a" * 64),
        TaskSpec("task-b", "criteria-b", "b" * 64),
    )
    decision = build_paired_run_decision(PairedRunRequest(
        "execution-decision", None,
        ArmSpec("base", "hermes", "model-base", ()),
        ArmSpec("variant", "hermes", "model-variant", ("skill-a",)),
        tasks, 4, 900, "revision-1", "2026-09-04T00:00:00Z",
        tuple(RunResultInput(task.task_id, arm, InfrastructureStatus.NOT_OBSERVED,
                             BehaviorVerdict.NOT_OBSERVED, None)
              for task in tasks for arm in ArmRole),
    ))
    budgets = DispatchBudgets(
        2, (NamedConcurrencyBudget("hermes", 2),),
        (NamedConcurrencyBudget("provider-a", provider_limit),),
        CostTimeBound(8, 80), CostTimeBound(8, 80),
    )
    targets = (
        ArmDispatchTarget(ArmRole.BASELINE, "hermes", "provider-a", "model-base", CostTimeBound(1, 10), CostTimeBound(1, 10), shared_resource_key),
        ArmDispatchTarget(ArmRole.VARIANT, "hermes", "provider-a", "model-variant", CostTimeBound(1, 10), CostTimeBound(1, 10), shared_resource_key),
    )
    return plan_paired_run_dispatch(
        decision.to_json(),
        PairedRunDispatchConfig(approval, dry_run, SharedResourceMode.SERIALIZE, budgets, targets),
    )


def workspace(cell) -> PairedRunWorkspace:
    return PairedRunWorkspace(cell.workspace_id)


def arm_setup_record(omh_plugin: bool, skills: tuple[str, ...]) -> dict[str, object]:
    return {"omh_plugin": omh_plugin, "exposure_digest": exposure_digest(tuple(sorted(skills)))}


def receipt(home: Path, cell, run_id: str, status: str = "completed"):
    skills = () if cell.arm is ArmRole.BASELINE else ("skill-a",)
    write_observed_receipt(home, run_id, status, evaluation_binding=paired_evaluation_binding(
        task_id=cell.task_id, criteria_ref=f"criteria-{cell.task_id[-1]}",
        input_digest=cell.input_digest, arm=cell.arm.value, executor=cell.executor,
        model=cell.model, exposed_skills=skills, execution_revision=cell.execution_revision,
    ), arm_setup=arm_setup_record(cell.arm is ArmRole.VARIANT, skills))
    return load_hermes_child_receipt(home, run_id)
