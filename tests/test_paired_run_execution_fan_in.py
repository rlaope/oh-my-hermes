from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from omh.coding.hermes_child_receipts import ReceiptVerificationError
from omh.coding.paired_run_execution import (
    ExecutionState,
    PairedRunExecutionFanInError,
    PairedRunExecutionOutcome,
    build_paired_run_execution_decision,
    crash_reason_for,
    execute_paired_run_plan,
)
from omh.coding.paired_run_execution_validation import terminal_state
from omh.quality.paired_run_model import (
    ArmRole,
    ArmSpec,
    BehaviorVerdict,
    InfrastructureStatus,
    PairedRunRequest,
    RunResultInput,
    TaskSpec,
)
from paired_run_execution_support import plan as build_plan
from paired_run_execution_support import receipt, workspace


def _execute(home: Path, *, provider_limit: int = 1, shared_key: str | None = "repo-lock"):
    plan = build_plan(provider_limit=provider_limit, shared_resource_key=shared_key)
    return execute_paired_run_plan(
        plan,
        workspace_factory=workspace,
        runner=lambda cell, current: PairedRunExecutionOutcome(
            ExecutionState.SUCCEEDED, receipt(home, cell, cell.workspace_id)
        ),
        cleaner=lambda cell, current: True,
    )


def _request(report) -> PairedRunRequest:
    cells = report.plan.cells
    tasks = tuple(sorted({cell.task_id for cell in cells}))
    return PairedRunRequest(
        report.plan.decision_id,
        None,
        ArmSpec("base", "hermes", "model-base", ()),
        ArmSpec("variant", "hermes", "model-variant", ("skill-a",)),
        tuple(
            TaskSpec(
                task_id, f"criteria-{task_id[-1]}", next(
                    cell.input_digest for cell in cells if cell.task_id == task_id
                )
            )
            for task_id in tasks
        ),
        len(cells),
        900,
        "revision-1",
        "2026-09-04T00:00:00Z",
        tuple(
            RunResultInput(
                item.cell.task_id,
                item.cell.arm,
                InfrastructureStatus.OBSERVED,
                BehaviorVerdict.PASS if item.cell.arm is ArmRole.BASELINE else BehaviorVerdict.FAIL,
                item.receipt,
            )
            for item in report.receipts
        ),
    )


def _report_with_first(report, outcome: PairedRunExecutionOutcome):
    cell = replace(report.plan.cells[0], terminal_state=terminal_state(outcome.state))
    return replace(
        report,
        plan=replace(report.plan, cells=(cell, *report.plan.cells[1:])),
        receipts=(outcome, *report.receipts[1:]),
    )


class PairedRunExecutionFanInTests(unittest.TestCase):
    def test_forged_terminal_dry_run_cannot_cross_the_decision_barrier(self) -> None:
        with TemporaryDirectory(prefix="omh-fan-in-dry-run-") as raw:
            home = (Path(raw) / ".omh").resolve()
            report = _execute(home)
            request = _request(report)
            candidate = replace(report, plan=replace(report.plan, dry_run=True))
            with self.assertRaises(PairedRunExecutionFanInError) as raised:
                build_paired_run_execution_decision(request, candidate, home)
        self.assertEqual(
            raised.exception.blockers,
            ("report: paired-run launch was not authorized",),
        )

    def test_complete_authenticated_matrix_builds_deterministic_observed_decision(self) -> None:
        with TemporaryDirectory(prefix="omh-fan-in-") as raw:
            serial_home = (Path(raw) / "serial" / ".omh").resolve()
            parallel_home = (Path(raw) / "parallel" / ".omh").resolve()
            serial = _execute(serial_home)
            parallel = _execute(parallel_home, provider_limit=2, shared_key=None)
            first = build_paired_run_execution_decision(
                _request(serial), serial, serial_home
            )
            second = build_paired_run_execution_decision(
                _request(parallel), parallel, parallel_home
            )
        self.assertEqual(first.schema_version, "paired_run_decision/v1")
        self.assertEqual(first.outcome, "baseline_dominates")
        self.assertEqual(first.to_json(), second.to_json())

    def test_successful_cell_requires_an_explicit_observed_result(self) -> None:
        with TemporaryDirectory(prefix="omh-fan-in-result-") as raw:
            home = (Path(raw) / ".omh").resolve()
            report = _execute(home)
            request = _request(report)
            first = report.plan.cells[0]
            missing = RunResultInput(
                first.task_id,
                first.arm,
                InfrastructureStatus.NOT_OBSERVED,
                BehaviorVerdict.NOT_OBSERVED,
                None,
            )
            candidate = replace(request, results=(missing, *request.results[1:]))
            with self.assertRaises(PairedRunExecutionFanInError) as raised:
                build_paired_run_execution_decision(candidate, report, home)
        self.assertEqual(
            raised.exception.blockers,
            (f"{first.workspace_id}: missing observed result",),
        )

    def test_each_invalid_cell_refuses_with_its_exact_blocker(self) -> None:
        with TemporaryDirectory(prefix="omh-fan-in-blockers-") as raw:
            home = (Path(raw) / ".omh").resolve()
            report = _execute(home)
            request = _request(report)
            first = report.receipts[0]
            workspace_id = report.plan.cells[0].workspace_id
            missing = replace(report, receipts=report.receipts[1:])
            stale = _report_with_first(
                report, replace(first, cell=replace(report.plan.cells[0], model="stale"))
            )
            unauthenticated = _report_with_first(report, replace(first, authenticated=False))
            mismatched = _report_with_first(report, replace(first, receipt=report.receipts[1].receipt))
            cases = {
                "missing": (missing, "missing execution outcome"),
                "stale": (stale, "stale execution identity"),
                "unauthenticated": (unauthenticated, "unauthenticated execution outcome"),
                "mismatched": (mismatched, "receipt does not match successful execution"),
            }
            for state in (
                ExecutionState.PARTIAL,
                ExecutionState.CANCELLED,
                ExecutionState.FAILED,
                ExecutionState.RATE_LIMITED,
                ExecutionState.CRASHED,
                ExecutionState.CLEANUP_FAILED,
            ):
                cases[state.value] = (
                    _report_with_first(report, replace(first, state=state)),
                    f"{state.value} execution state",
                )
            cases["cleanup"] = (
                _report_with_first(report, replace(first, cleanup_succeeded=False)),
                "cleanup is incomplete",
            )
            for label, (candidate, reason) in cases.items():
                with self.subTest(label=label):
                    with self.assertRaises(PairedRunExecutionFanInError) as raised:
                        build_paired_run_execution_decision(request, candidate, home)
                    self.assertEqual(raised.exception.blockers, (f"{workspace_id}: {reason}",))

    def test_crashed_cell_names_its_cause_rather_than_the_shape_of_the_result(self) -> None:
        # The blocker a reader saw on #1592 named the invalid combination the
        # crash produced. The cause the cell recorded belongs in it.
        with TemporaryDirectory(prefix="omh-fan-in-cause-") as raw:
            home = (Path(raw) / ".omh").resolve()
            report = _execute(home)
            request = _request(report)
            workspace_id = report.plan.cells[0].workspace_id
            candidate = _report_with_first(
                report,
                replace(
                    report.receipts[0],
                    state=ExecutionState.CRASHED,
                    crash_reason=crash_reason_for(
                        ReceiptVerificationError(
                            "Hermes child observation integrity key is invalid"
                        )
                    ),
                ),
            )
            with self.assertRaises(PairedRunExecutionFanInError) as raised:
                build_paired_run_execution_decision(request, candidate, home)
        self.assertEqual(
            raised.exception.blockers,
            (
                f"{workspace_id}: crashed execution state: ReceiptVerificationError: "
                "Hermes child observation integrity key is invalid",
            ),
        )


if __name__ == "__main__":
    unittest.main()
