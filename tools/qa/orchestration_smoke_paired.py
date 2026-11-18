"""Local receipt-backed paired-run exercises for the orchestration smoke CLI."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Lock

from omh.coding.hermes_child_arm_setup import DEFAULT_ARM_TOOLSETS, ArmSetup
from omh.coding.hermes_child_dispatch import HermesChildRequest, HermesChildObservation, dispatch_hermes_child
from omh.coding.hermes_child_evaluation import HermesChildEvaluationContext
from omh.coding.hermes_child_receipts import hermes_child_run_dir, load_hermes_child_receipt, load_or_create_observation_key, write_signed_observation
from omh.coding.paired_run_dispatch import ApprovalState, ArmDispatchTarget, CostTimeBound, DispatchBudgets, NamedConcurrencyBudget, PairedRunDispatchConfig, SharedResourceMode, plan_paired_run_dispatch
from omh.coding.paired_run_execution import ExecutionState, PairedRunExecutionLimits, PairedRunExecutionOutcome, PairedRunWorkspace, build_paired_run_execution_decision, execute_paired_run_plan
from omh.coding.routing_observation import authenticate_child_observation, build_routing_observation
from omh.quality.paired_run_decision import build_paired_run_decision
from omh.quality.paired_run_model import ArmRole, ArmSpec, BehaviorVerdict, InfrastructureStatus, PairedRunRequest, RunResultInput, TaskSpec
from omh.quality.paired_run_values import exposure_digest

_REVISION = "orchestration-contract-revision-1"
_TASKS = tuple(TaskSpec(f"cell-{index}", f"criterion-{index}", f"{index:064x}") for index in range(1, 5))
_PRIVACY_MARKERS = ("orchestration-qa", "SENTINEL-SECRET-MESSAGE-SOURCE", '"message"', '"source_text"', "secret source body")


def _privacy(root: Path) -> dict[str, object]:
    files = tuple(sorted(path for path in root.rglob("*") if path.is_file()))
    contents = "".join(path.read_text(encoding="utf-8", errors="replace") for path in files)
    found = {marker: marker in contents for marker in _PRIVACY_MARKERS}
    return {
        "regular_file_count": len(files),
        "persisted_prompt_absent": not found["orchestration-qa"],
        "persisted_secret_absent": not found["SENTINEL-SECRET-MESSAGE-SOURCE"],
        "diagnostic_payload_absent": not any(found[marker] for marker in _PRIVACY_MARKERS[2:]),
    }


def _request(results: tuple[RunResultInput, ...]) -> PairedRunRequest:
    return PairedRunRequest("orchestration-contract", None, ArmSpec("baseline", "local-baseline", "model-baseline", ()), ArmSpec("variant", "local-variant", "model-variant", ("qa-skill",)), _TASKS, 8, 30, _REVISION, "2026-09-04T00:00:00Z", results)


def _plan(global_limit: int, *, shared: str | None = None):
    initial = _request(tuple(RunResultInput(task.task_id, arm, InfrastructureStatus.NOT_OBSERVED, BehaviorVerdict.NOT_OBSERVED, None) for task in _TASKS for arm in ArmRole))
    budgets = DispatchBudgets(global_limit, (NamedConcurrencyBudget("local-baseline", 1), NamedConcurrencyBudget("local-variant", 1)), (NamedConcurrencyBudget("local", global_limit),), CostTimeBound(8, 60), CostTimeBound(8, 60))
    targets = tuple(ArmDispatchTarget(arm, executor, "local", model, CostTimeBound(1, 5), CostTimeBound(1, 5), shared) for arm, executor, model in ((ArmRole.BASELINE, "local-baseline", "model-baseline"), (ArmRole.VARIANT, "local-variant", "model-variant")))
    config = PairedRunDispatchConfig(ApprovalState.APPROVED, False, SharedResourceMode.SERIALIZE, budgets, targets)
    return plan_paired_run_dispatch(build_paired_run_decision(initial).to_json(), config)


def _event(
    cell,
    executable: Path,
) -> tuple[HermesChildObservation, bool]:
    context = HermesChildEvaluationContext(cell.task_id, f"criterion-{cell.task_id[-1]}", cell.input_digest, cell.arm.value, cell.executor, exposure_digest(() if cell.arm is ArmRole.BASELINE else ("qa-skill",)), cell.execution_revision)
    events: list[HermesChildObservation] = []
    result = dispatch_hermes_child(HermesChildRequest("orchestration-qa", cell.model, "local", "low", "qa-parent", f"receipt-{cell.workspace_id}", 30, hermes=str(executable), evaluation_context=context), dispatch_policy="ask_before_dispatch", confirmed=True, observe=events.append)
    # This smoke has no arm home; it records the setup each arm declares so
    # fan-in's signed arm-setup check sees a matching one.
    skills = () if cell.arm is ArmRole.BASELINE else ("qa-skill",)
    setup = ArmSetup(cell.arm is ArmRole.VARIANT, exposure_digest(skills), DEFAULT_ARM_TOOLSETS)
    return replace(events[-1], arm_setup=setup), not result.cleanup_verified


def _receipt(home: Path, cell, event: HermesChildObservation):
    run_id = f"receipt-{cell.workspace_id}"
    observation = build_routing_observation(route={"selected_model": f"local/{cell.model}", "executor_profile": cell.executor}, child_dispatch=authenticate_child_observation({"status": "completed", "run_id": run_id}), run_id=run_id)
    run_dir = hermes_child_run_dir(home, run_id, create_root=True)
    run_dir.mkdir()
    write_signed_observation(run_dir, observation, event)
    return load_hermes_child_receipt(home, run_id)


def _execute(home: Path, global_limit: int):
    plan = _plan(global_limit)
    executable = home.parent / "local-hermes"
    executable.write_text("#!/bin/sh\ncat >/dev/null\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    observations = {
        cell.workspace_id: _event(cell, executable)
        for cell in plan.cells
    }
    events = {
        workspace_id: observation
        for workspace_id, (observation, _unreaped) in observations.items()
    }
    unreaped_child_groups = sum(
        int(unreaped)
        for _observation, unreaped in observations.values()
    )
    hermes_child_run_dir(home, "bootstrap", create_root=True)
    load_or_create_observation_key(home / "coding" / "hermes-child")
    workspace_root = home.parent / "workspaces"
    active: set[Path] = set()
    peaks = {"global": 0, "provider": 0, "local-baseline": 0, "local-variant": 0}
    counts = dict(peaks)
    lock = Lock()
    barrier = Barrier(global_limit) if global_limit > 1 else None

    def workspace(cell):
        path = workspace_root / cell.workspace_id
        path.mkdir(parents=True)
        with lock:
            active.add(path)
        return PairedRunWorkspace(str(path))

    def runner(cell, workspace_value):
        with lock:
            for key in ("global", "provider", cell.executor):
                counts[key] += 1
                peaks[key] = max(peaks[key], counts[key])
        if barrier is not None:
            barrier.wait(timeout=5)
        with lock:
            for key in ("global", "provider", cell.executor):
                counts[key] -= 1
        return PairedRunExecutionOutcome(ExecutionState.SUCCEEDED, _receipt(home, cell, events[cell.workspace_id]))

    def cleaner(cell, workspace_value):
        path = Path(workspace_value.workspace_id)
        path.rmdir()
        with lock:
            active.remove(path)
        return True

    limits = PairedRunExecutionLimits(global_limit, {"local-baseline": 1, "local-variant": 1}, {"local": global_limit})
    report = execute_paired_run_plan(plan, workspace_factory=workspace, runner=runner, cleaner=cleaner, limits=limits)
    workspace_root.rmdir()
    results = tuple(RunResultInput(item.cell.task_id, item.cell.arm, InfrastructureStatus.OBSERVED, BehaviorVerdict.PASS if item.cell.arm is ArmRole.BASELINE else BehaviorVerdict.FAIL, item.receipt) for item in report.receipts if item.cell is not None)
    return report, _request(results), peaks, active, unreaped_child_groups


def _scope(report, decision) -> tuple[object, ...]:
    identities = tuple((cell.task_id, cell.input_digest, cell.execution_revision, cell.executor, cell.model) for cell in report.plan.cells)
    return decision.outcome, decision.task_set_digest, decision.aggregate, identities


def happy_paired() -> dict[str, object]:
    serial_root: Path | None = None
    with TemporaryDirectory(prefix="omh-orchestration-serial-") as raw:
        serial_root = Path(raw)
        serial_report, serial_request, serial_peaks, serial_active, serial_unreaped = _execute((serial_root / ".omh").resolve(), 1)
        serial_decision = build_paired_run_execution_decision(serial_request, serial_report, (serial_root / ".omh").resolve())
        serial_privacy = _privacy(serial_root)
    parallel_root: Path | None = None
    with TemporaryDirectory(prefix="omh-orchestration-parallel-") as raw:
        parallel_root = Path(raw)
        home = (parallel_root / ".omh").resolve()
        parallel_report, parallel_request, parallel_peaks, parallel_active, parallel_unreaped = _execute(home, 2)
        parallel_decision = build_paired_run_execution_decision(parallel_request, parallel_report, home)
        refs = [item.receipt.receipt_ref for item in parallel_report.receipts if item.receipt is not None]
        identities = [{"workspace": cell.workspace_id, "task": cell.task_id, "input": cell.input_digest, "revision": cell.execution_revision, "executor": cell.executor, "model": cell.model} for cell in parallel_report.plan.cells]
        parallel_privacy = _privacy(parallel_root)
    cleanup = {
        "live_workspaces": len(serial_active | parallel_active),
        "unreaped_child_groups": serial_unreaped + parallel_unreaped,
        "port_cleanup": "not_applicable_no_ports_created",
        "live_temp_paths": int(
            (serial_root is not None and serial_root.exists())
            or (parallel_root is not None and parallel_root.exists())
        ),
    }
    return {"cell_count": len(refs), "receipt_count": len(refs), "receipt_refs": refs, "identities": identities, "serial_peaks": serial_peaks, "parallel_peaks": parallel_peaks, "serial_parallel_scope_equivalent": _scope(serial_report, serial_decision) == _scope(parallel_report, parallel_decision), "decision": parallel_decision.outcome, "filesystem_privacy": {"serial": serial_privacy, "parallel": parallel_privacy}, "cleanup": cleanup, "claim_boundary": parallel_decision.claim_boundary}


def adversarial_paired() -> dict[str, object]:
    root: Path | None = None
    active: set[Path] = set()
    with TemporaryDirectory(prefix="omh-orchestration-adversarial-") as raw:
        root = Path(raw)
        home = (root / ".omh").resolve()
        report, request, _, active, unreaped_child_groups = _execute(home, 2)
        first, cell = report.receipts[0], report.plan.cells[0]
        cases = {"missing": replace(report, receipts=report.receipts[1:]), "stale": replace(report, receipts=(replace(first, cell=replace(cell, model="stale")), *report.receipts[1:])), "mismatched": replace(report, receipts=(replace(first, receipt=report.receipts[1].receipt), *report.receipts[1:])), "unauthenticated": replace(report, receipts=(replace(first, authenticated=False), *report.receipts[1:])), "partial": replace(report, receipts=(replace(first, state=ExecutionState.PARTIAL), *report.receipts[1:])), "timeout": replace(report, receipts=(replace(first, state=ExecutionState.TIMED_OUT), *report.receipts[1:])), "cancel": replace(report, receipts=(replace(first, state=ExecutionState.CANCELLED), *report.receipts[1:])), "crash": replace(report, receipts=(replace(first, state=ExecutionState.CRASHED), *report.receipts[1:])), "rate_limit": replace(report, receipts=(replace(first, state=ExecutionState.RATE_LIMITED), *report.receipts[1:])), "cleanup_failure": replace(report, receipts=(replace(first, cleanup_succeeded=False), *report.receipts[1:]))}
        result: dict[str, object] = {}
        for name, candidate in cases.items():
            try:
                build_paired_run_execution_decision(request, candidate, home)
            except ValueError as error:
                result[name] = f"BLOCK:{error.args[0]}"
        shared = _plan(2, shared="shared")
        result["shared_resource_serialization"] = "HOLD:serialized" if len({item.launch_wave for item in shared.cells}) == len(shared.cells) else "BLOCK:not_serialized"
        result["filesystem_privacy"] = _privacy(root)
    result["cleanup"] = {
        "live_workspaces": len(active),
        "unreaped_child_groups": unreaped_child_groups,
        "port_cleanup": "not_applicable_no_ports_created",
        "live_temp_paths": int(root is not None and root.exists()),
    }
    return result
