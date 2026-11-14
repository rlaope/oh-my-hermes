"""Explicit paired-run boundary with a built-in sanctioned Hermes adapter."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from ..coding.paired_run_dispatch import (
    ApprovalState,
    ArmDispatchTarget,
    CostTimeBound,
    DispatchBudgets,
    NamedConcurrencyBudget,
    PairedRunDispatchConfig,
    PairedRunDispatchPlan,
    PairedRunDispatchPlanError,
    SharedResourceMode,
    plan_paired_run_dispatch,
)
from ..coding.paired_run_execution import PairedRunExecutionReport
from ..coding.paired_run_local_runner import (
    build_paired_run_local_boundary,
    parse_task_file_arguments,
)
from ..coding.paired_run_local_models import (
    PairedRunLocalRunnerConfig,
    PairedRunLocalRunnerError,
)
from ..installer import OmhError
from ..quality.paired_run_decision import parse_paired_run_decision
from ..quality.paired_run_model import ArmRole, PairedRunDecision, PairedRunValidationError
from .common import _paths, _print_json

PairedRunRunnerBoundary = Callable[[PairedRunDispatchPlan], PairedRunExecutionReport]


def cmd_coding_paired_run_dispatch(
    args: argparse.Namespace,
    *,
    runner_boundary: PairedRunRunnerBoundary | None = None,
) -> int:
    """Prepare an inert plan, or pass a confirmed plan to an injected local runner."""
    try:
        decision_document = Path(args.decision).expanduser().read_text(encoding="utf-8")
        decision = parse_paired_run_decision(decision_document)
        config = _dispatch_config(
            decision,
            approved=bool(args.confirm_dispatch),
            dry_run=bool(args.dry_run),
        )
        plan = plan_paired_run_dispatch(decision_document, config)
    except (OSError, PairedRunDispatchPlanError, PairedRunValidationError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    if args.dry_run:
        _print_json(_plan_payload(plan, config))
        return 0
    if not args.confirm_dispatch:
        raise OmhError("paired-run dispatch requires --confirm-dispatch; use --dry-run to inspect the inert plan")
    if runner_boundary is None:
        try:
            task_files = parse_task_file_arguments(
                tuple(getattr(args, "task_file", ()))
            )
            runner_boundary = build_paired_run_local_boundary(
                decision,
                task_files,
                PairedRunLocalRunnerConfig(
                    paths=_paths(args),
                    repo_root=Path(getattr(args, "repo", ".")).expanduser(),
                    provider=str(getattr(args, "provider", "")),
                    hermes=str(getattr(args, "hermes", "hermes")),
                    reasoning=str(getattr(args, "reasoning", "medium")),
                    timeout_seconds=getattr(args, "timeout", 900.0),
                ),
            )
        except PairedRunLocalRunnerError as exc:
            raise OmhError(str(exc)) from exc
    report = runner_boundary(plan)
    _print_json({**_plan_payload(plan, config), "execution": report.metadata()})
    return 0


def _dispatch_config(decision: PairedRunDecision, *, approved: bool, dry_run: bool) -> PairedRunDispatchConfig:
    """Derive conservative local-only limits from the immutable decision."""
    # This command parses the decision immediately above. Its public model is
    # intentionally structural, so these reads preserve that parser's frozen
    # arm, task, and maximum-run constraints instead of accepting CLI overrides.
    baseline = decision.baseline
    variant = decision.variant
    cell_count = len(decision.tasks) * len(ArmRole)
    maximum_concurrency = min(2, cell_count)
    executor_names = tuple(sorted({baseline.executor, variant.executor}))
    targets = (
        _target(ArmRole.BASELINE, baseline.executor, baseline.model),
        _target(ArmRole.VARIANT, variant.executor, variant.model),
    )
    budgets = DispatchBudgets(
        maximum_concurrency,
        tuple(
            NamedConcurrencyBudget(
                name,
                min(
                    maximum_concurrency,
                    len(decision.tasks)
                    * sum(
                        arm.executor == name
                        for arm in (baseline, variant)
                    ),
                ),
            )
            for name in executor_names
        ),
        (NamedConcurrencyBudget("local", maximum_concurrency),),
        CostTimeBound(cell_count, decision.max_dispatch_seconds),
        CostTimeBound(cell_count, decision.max_dispatch_seconds),
    )
    return PairedRunDispatchConfig(
        ApprovalState.APPROVED if approved else ApprovalState.REQUIRED,
        dry_run,
        SharedResourceMode.SERIALIZE,
        budgets,
        targets,
    )


def _target(arm: ArmRole, executor: str, model: str) -> ArmDispatchTarget:
    return ArmDispatchTarget(
        arm,
        executor,
        "local",
        model,
        CostTimeBound(1, 1),
        CostTimeBound(1, 1),
        None,
    )


def _plan_payload(plan: PairedRunDispatchPlan, config: PairedRunDispatchConfig) -> dict[str, object]:
    return {
        "schema_version": "paired_run_cli_dispatch/v1",
        "decision_id": plan.decision_id,
        "approval": plan.approval.value,
        "dry_run": plan.dry_run,
        "launch_authorized": plan.launch_authorized,
        "budgets": _budgets_payload(config.budgets),
        "isolation": _isolation_payload(plan, config.shared_resource_mode),
        "local_runner_boundary": (
            "explicit_confirmed_adapter; hermes reuses the sanctioned child boundary; "
            "paired_run_decision/v2 contains no raw task content"
        ),
        "cells": [
            {
                "task_id": cell.task_id,
                "arm": cell.arm.value,
                "executor": cell.executor,
                "provider": cell.provider,
                "model": cell.model,
                "workspace_id": cell.workspace_id,
                "launch_wave": cell.launch_wave,
            }
            for cell in plan.cells
        ],
        "claim_boundary": plan.claim_boundary,
    }


def _budgets_payload(budgets: DispatchBudgets) -> dict[str, object]:
    return {
        "global_concurrency": budgets.global_concurrency,
        "executor_concurrency": {item.name: item.maximum for item in sorted(budgets.executor_concurrency, key=lambda item: item.name)},
        "provider_concurrency": {item.name: item.maximum for item in sorted(budgets.provider_concurrency, key=lambda item: item.name)},
        "local_bound": _bound_payload(budgets.local_bound),
        "provider_bound": _bound_payload(budgets.provider_bound),
    }


def _bound_payload(bound: CostTimeBound) -> dict[str, int]:
    return {"cost_units": bound.cost_units, "seconds": bound.seconds}


def _isolation_payload(plan: PairedRunDispatchPlan, mode: SharedResourceMode) -> dict[str, object]:
    return {
        "shared_resource_mode": mode.value,
        "shared_resource_keys": sorted({cell.shared_resource_key for cell in plan.cells if cell.shared_resource_key is not None}),
        "launch_waves": sorted({cell.launch_wave for cell in plan.cells}),
    }


def add_coding_paired_run_command(coding_sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    paired_run = coding_sub.add_parser(
        "paired-run",
        help="Operator/agent surface: explicitly inspect or dispatch a committed paired-run decision; normal users stay in Hermes chat.",
    )
    paired_sub = paired_run.add_subparsers(dest="paired_run_command", required=True)
    dispatch = paired_sub.add_parser(
        "dispatch",
        help="Dispatch through the sanctioned Hermes adapter or a caller-injected extension; --dry-run launches nothing.",
    )
    dispatch.add_argument("--decision", required=True, help="Path to a paired_run_decision/v2 (or v1) document.")
    dispatch.add_argument("--dry-run", action="store_true", help="Build and print the inert plan without launching any runner.")
    dispatch.add_argument(
        "--confirm-dispatch",
        action="store_true",
        help="Explicitly authorize the configured local runner adapter.",
    )
    dispatch.add_argument(
        "--task-file",
        action="append",
        default=[],
        help="Task input as TASK_ID=PATH; repeated once per frozen task.",
    )
    dispatch.add_argument(
        "--repo",
        default=".",
        help="Git repository providing the immutable execution revision.",
    )
    dispatch.add_argument(
        "--provider",
        default="",
        help="Hermes provider for the sanctioned local adapter.",
    )
    dispatch.add_argument(
        "--hermes",
        default="hermes",
        help="Hermes executable used by the sanctioned child boundary.",
    )
    dispatch.add_argument(
        "--reasoning",
        default="medium",
        help="Hermes reasoning effort for every frozen cell.",
    )
    dispatch.add_argument(
        "--timeout",
        type=float,
        default=900.0,
        help="Per-cell timeout, capped by the frozen decision.",
    )
    dispatch.add_argument("--json", action="store_true", help="Emit the machine payload.")
    dispatch.set_defaults(func=cmd_coding_paired_run_dispatch)
