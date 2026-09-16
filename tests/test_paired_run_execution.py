from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Lock
import unittest

from omh.coding.hermes_child_receipts import ReceiptVerificationError
from omh.coding.paired_run_dispatch import ApprovalState
from omh.coding.paired_run_execution import (
    CrashDetailState,
    ExecutionState,
    PairedRunCleanupFailure,
    PairedRunExecutionLimits,
    PairedRunExecutionOutcome,
    PairedRunRunnerFailure,
    PairedRunWorkspaceFailure,
    crash_reason_for,
    execute_paired_run_plan,
)
from omh.coding.paired_run_execution_model import MAX_CRASH_DETAIL_CHARS
from paired_run_execution_support import plan as _plan
from paired_run_execution_support import receipt as _receipt
from paired_run_execution_support import workspace as _workspace


class PairedRunExecutionTests(unittest.TestCase):
    def test_dry_run_and_missing_approval_never_create_workspace_or_run(self) -> None:
        for plan in (_plan(dry_run=True), _plan(approval=ApprovalState.REQUIRED)):
            with self.subTest(plan=plan):
                calls: list[str] = []
                report = execute_paired_run_plan(
                    plan,
                    workspace_factory=lambda cell: calls.append(cell.workspace_id),
                    runner=lambda cell, workspace: calls.append("runner"),
                    cleaner=lambda cell, workspace: calls.append("cleaner"),
                )
                self.assertEqual(calls, [])
                self.assertFalse(report.fan_in_ready)
                self.assertEqual(report.receipts, ())

    def test_serializes_shared_resources_and_preserves_identity(self) -> None:
        plan = _plan()
        active = 0
        maximum = 0
        lock = Lock()
        seen = []
        with TemporaryDirectory() as raw:
            home = (Path(raw) / ".omh").resolve()

            def runner(cell, workspace):
                nonlocal active, maximum
                self.assertEqual(workspace.workspace_id, cell.workspace_id)
                seen.append(cell)
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                with lock:
                    active -= 1
                return PairedRunExecutionOutcome(ExecutionState.SUCCEEDED, _receipt(home, cell, cell.workspace_id))

            report = execute_paired_run_plan(
                plan,
                workspace_factory=_workspace,
                runner=runner,
                cleaner=lambda cell, workspace: True,
            )
        self.assertEqual(maximum, 1)
        self.assertEqual(seen, list(plan.cells))
        self.assertTrue(report.fan_in_ready)
        self.assertEqual([item.state for item in report.receipts], [ExecutionState.SUCCEEDED] * 4)
        self.assertEqual(report.plan.cells, tuple(replace(cell, terminal_state=report.plan.cells[index].terminal_state) for index, cell in enumerate(plan.cells)))

    def test_enforces_global_executor_and_provider_limits_with_wave_barriers(self) -> None:
        plan = _plan(provider_limit=2, shared_resource_key=None)
        barrier = Barrier(2)
        active = 0
        maximum = 0
        lock = Lock()
        with TemporaryDirectory() as raw:
            home = (Path(raw) / ".omh").resolve()

            def runner(cell, workspace):
                nonlocal active, maximum
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                barrier.wait(timeout=2)
                with lock:
                    active -= 1
                return PairedRunExecutionOutcome(
                    ExecutionState.SUCCEEDED, _receipt(home, cell, cell.workspace_id))

            report = execute_paired_run_plan(
                plan, workspace_factory=_workspace, runner=runner,
                cleaner=lambda cell, workspace: True,
                limits=PairedRunExecutionLimits(2, {"hermes": 2}, {"provider-a": 2}),
            )
        self.assertEqual(maximum, 2)
        self.assertTrue(report.fan_in_ready)

    def test_terminal_failures_cleanup_and_runner_crashes_are_distinguished(self) -> None:
        plan = _plan()
        states = iter((
            ExecutionState.FAILED, ExecutionState.TIMED_OUT,
            ExecutionState.CANCELLED, ExecutionState.RATE_LIMITED,
        ))
        with TemporaryDirectory() as raw:
            home = (Path(raw) / ".omh").resolve()

            def runner(cell, workspace):
                state = next(states)
                status = {
                    ExecutionState.FAILED: "failed",
                    ExecutionState.TIMED_OUT: "timed_out",
                    ExecutionState.CANCELLED: "cancelled",
                }.get(state, "failed")
                return PairedRunExecutionOutcome(state, _receipt(home, cell, cell.workspace_id, status))

            report = execute_paired_run_plan(
                plan, workspace_factory=_workspace, runner=runner,
                cleaner=lambda cell, workspace: (
                    (_ for _ in ()).throw(PairedRunCleanupFailure())
                    if workspace.workspace_id == plan.cells[0].workspace_id else True
                ),
            )
        self.assertEqual(
            [item.state for item in report.receipts],
            [ExecutionState.CLEANUP_FAILED, ExecutionState.TIMED_OUT,
             ExecutionState.CANCELLED, ExecutionState.RATE_LIMITED],
        )
        crashed = execute_paired_run_plan(
            _plan(), workspace_factory=_workspace,
            runner=lambda cell, workspace: (_ for _ in ()).throw(PairedRunRunnerFailure("crash")),
            cleaner=lambda cell, workspace: True,
        )
        self.assertEqual({item.state for item in crashed.receipts}, {ExecutionState.CRASHED})

    def test_unexpected_runner_error_is_crashed_and_cleaned(self) -> None:
        cleaned: list[str] = []

        def runner_bug(cell, workspace):
            raise AssertionError("runner bug")

        report = execute_paired_run_plan(
            _plan(),
            workspace_factory=_workspace,
            runner=runner_bug,
            cleaner=lambda cell, workspace: (
                cleaned.append(workspace.workspace_id) or True
            ),
        )

        self.assertEqual(
            {item.state for item in report.receipts},
            {ExecutionState.CRASHED},
        )
        self.assertTrue(
            all(item.cleanup_succeeded for item in report.receipts)
        )
        self.assertEqual(
            set(cleaned),
            {cell.workspace_id for cell in report.plan.cells},
        )

    def test_unexpected_cleaner_error_is_cleanup_failed(self) -> None:
        def cleaner_bug(cell, workspace):
            raise AssertionError("cleaner bug")

        report = execute_paired_run_plan(
            _plan(),
            workspace_factory=_workspace,
            runner=lambda cell, workspace: PairedRunExecutionOutcome(
                ExecutionState.PARTIAL,
                None,
            ),
            cleaner=cleaner_bug,
        )

        self.assertEqual(
            {item.state for item in report.receipts},
            {ExecutionState.CLEANUP_FAILED},
        )
        self.assertTrue(
            all(
                item.cleanup_succeeded is False
                for item in report.receipts
            )
        )

    def test_crashed_cell_carries_what_raised_it_across_the_boundary(self) -> None:
        # #1592 lost a diagnosis cycle here: a ReceiptVerificationError naming a
        # short integrity key reached the caller as an opaque CRASHED cell, and
        # the coherent first hypothesis drawn from the surviving evidence was
        # wrong. Each fault kind must be readable from the cell it produced.
        faults = (
            ReceiptVerificationError("Hermes child observation integrity key is invalid"),
            PairedRunRunnerFailure("hermes child exited before sealing a receipt"),
            AssertionError("runner bug"),
        )
        for error in faults:
            with self.subTest(fault=type(error).__name__):
                report = execute_paired_run_plan(
                    _plan(),
                    workspace_factory=_workspace,
                    runner=lambda cell, workspace, raised=error: (_ for _ in ()).throw(raised),
                    cleaner=lambda cell, workspace: True,
                )
                expected = {
                    "error_type": type(error).__name__,
                    "detail": str(error),
                    "detail_state": "retained",
                }
                self.assertEqual(
                    {item.state for item in report.receipts}, {ExecutionState.CRASHED}
                )
                self.assertEqual(
                    {
                        (
                            item.crash_reason.error_type,
                            item.crash_reason.detail,
                            item.crash_reason.detail_state,
                        )
                        for item in report.receipts
                    },
                    {(expected["error_type"], expected["detail"], CrashDetailState.RETAINED)},
                )
                self.assertEqual(
                    [cell["crash_reason"] for cell in report.metadata()["cells"]],
                    [expected] * len(report.receipts),
                )

        workspace_failure = execute_paired_run_plan(
            _plan(),
            workspace_factory=lambda cell: (_ for _ in ()).throw(
                PairedRunWorkspaceFailure("worktree parent was removed")
            ),
            runner=lambda cell, workspace: self.fail("runner ran without a workspace"),
            cleaner=lambda cell, workspace: self.fail("cleaner ran without a workspace"),
        )
        self.assertEqual(
            {item.crash_reason.label for item in workspace_failure.receipts},
            {"PairedRunWorkspaceFailure: worktree parent was removed"},
        )

    def test_cleanup_failure_records_its_cause_without_overwriting_the_runners(self) -> None:
        crashed_then_uncleaned = execute_paired_run_plan(
            _plan(),
            workspace_factory=_workspace,
            runner=lambda cell, workspace: (_ for _ in ()).throw(AssertionError("runner bug")),
            cleaner=lambda cell, workspace: (_ for _ in ()).throw(OSError("worktree is busy")),
        )
        self.assertEqual(
            {item.crash_reason.label for item in crashed_then_uncleaned.receipts},
            {"AssertionError: runner bug"},
        )
        uncleaned = execute_paired_run_plan(
            _plan(),
            workspace_factory=_workspace,
            runner=lambda cell, workspace: PairedRunExecutionOutcome(ExecutionState.PARTIAL, None),
            cleaner=lambda cell, workspace: (_ for _ in ()).throw(OSError("worktree is busy")),
        )
        self.assertEqual(
            {item.state for item in uncleaned.receipts}, {ExecutionState.CLEANUP_FAILED}
        )
        self.assertEqual(
            {item.crash_reason.label for item in uncleaned.receipts},
            {"OSError: worktree is busy"},
        )

    def test_crash_detail_is_bounded_redacted_and_withheld_when_sensitive(self) -> None:
        overlong = crash_reason_for(RuntimeError("x" * (MAX_CRASH_DETAIL_CHARS + 50)))
        self.assertEqual(len(overlong.detail), MAX_CRASH_DETAIL_CHARS)
        self.assertTrue(overlong.detail.endswith("..."))

        rooted = crash_reason_for(
            OSError("/Users/someone/work/repo/src/omh/cli.py is unreadable")
        )
        self.assertEqual(rooted.detail, ".../src/omh/cli.py is unreadable")

        control = crash_reason_for(ValueError("line one\x1b[2Jline\x00two"))
        self.assertEqual(control.detail, "line one [2Jline two")

        secret = crash_reason_for(RuntimeError("child env carried api_key=sk-abc123"))
        self.assertEqual(secret.detail, "")
        self.assertEqual(secret.detail_state, CrashDetailState.WITHHELD)
        self.assertEqual(secret.label, "RuntimeError (withheld detail)")

        silent = crash_reason_for(RuntimeError())
        self.assertEqual(silent.detail, "")
        self.assertEqual(silent.detail_state, CrashDetailState.EMPTY)
        self.assertEqual(silent.label, "RuntimeError (empty detail)")

    def test_authenticated_matching_terminal_receipts_resume_once_and_mismatches_rerun(self) -> None:
        plan = _plan()
        with TemporaryDirectory() as raw:
            home = (Path(raw) / ".omh").resolve()
            initial = execute_paired_run_plan(
                plan, workspace_factory=lambda cell: cell.workspace_id,
                runner=lambda cell, workspace: PairedRunExecutionOutcome(
                    ExecutionState.SUCCEEDED, _receipt(home, cell, cell.workspace_id)),
                cleaner=lambda cell, workspace: True,
            )
            previous = initial.receipts
            calls: list[str] = []
            resumed = execute_paired_run_plan(
                plan, workspace_factory=lambda cell: calls.append(cell.workspace_id),
                runner=lambda cell, workspace: self.fail("runner must not execute resumed cell"),
                cleaner=lambda cell, workspace: self.fail("cleaner must not execute resumed cell"),
                prior_receipts=previous,
            )
            self.assertEqual(calls, [])
            self.assertTrue(all(item.reused for item in resumed.receipts))
            changed = replace(previous[0], cell=replace(plan.cells[0], model="changed"))
            rerun = execute_paired_run_plan(
                plan, workspace_factory=lambda cell: cell.workspace_id,
                runner=lambda cell, workspace: PairedRunExecutionOutcome(
                    ExecutionState.SUCCEEDED, _receipt(home, cell, "rerun-" + cell.workspace_id)),
                cleaner=lambda cell, workspace: True,
                prior_receipts=(changed, *previous[1:]),
            )
        self.assertFalse(rerun.receipts[0].reused)
        self.assertTrue(all(item.authenticated for item in rerun.receipts))

    def test_unauthenticated_or_replayed_receipts_never_authorize_resume(self) -> None:
        plan = _plan()
        forged = PairedRunExecutionOutcome(ExecutionState.SUCCEEDED, None, cell=plan.cells[0])
        report = execute_paired_run_plan(
            plan, workspace_factory=lambda cell: cell.workspace_id,
            runner=lambda cell, workspace: PairedRunExecutionOutcome(ExecutionState.SUCCEEDED, None),
            cleaner=lambda cell, workspace: True, prior_receipts=(forged,),
        )
        self.assertEqual(report.receipts[0].state, ExecutionState.UNAUTHENTICATED)
        self.assertFalse(report.receipts[0].authenticated)

        with TemporaryDirectory() as raw:
            home = (Path(raw) / ".omh").resolve()
            initial = execute_paired_run_plan(
                plan, workspace_factory=lambda cell: cell.workspace_id,
                runner=lambda cell, workspace: PairedRunExecutionOutcome(
                    ExecutionState.SUCCEEDED, _receipt(home, cell, cell.workspace_id)),
                cleaner=lambda cell, workspace: True,
            )
            replayed = replace(initial.receipts[1], receipt=initial.receipts[0].receipt)
            calls: list[str] = []
            resumed = execute_paired_run_plan(
                plan, workspace_factory=lambda cell: calls.append(cell.workspace_id) or cell.workspace_id,
                runner=lambda cell, workspace: PairedRunExecutionOutcome(
                    ExecutionState.SUCCEEDED, _receipt(home, cell, "fresh-" + cell.workspace_id)),
                cleaner=lambda cell, workspace: True,
                prior_receipts=(initial.receipts[0], replayed, *initial.receipts[2:]),
            )
        self.assertIn(plan.cells[0].workspace_id, calls)
        self.assertIn(plan.cells[1].workspace_id, calls)
        self.assertFalse(resumed.receipts[0].reused)
        self.assertFalse(resumed.receipts[1].reused)


if __name__ == "__main__":
    unittest.main()
