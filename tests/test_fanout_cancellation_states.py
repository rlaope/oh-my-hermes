"""Fanout cancellation: four states, not one word and not `failed` (issue #1360).

A stopped batch used to answer with `interrupted` for everything it had not
finished and `failed` for the unit it had killed. Those are four different facts
an operator acts on differently, and this module holds them apart: the unit that
was running, the one nobody heard back from, the ones that never spawned, and
the ones held behind a cancelled dependency.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from omh.coding.fanout import build_fanout_contract
from omh.coding.fanout_artifacts import write_fanout_contract
from omh.coding.fanout_dispatch import (
    CANCELLED_UNIT_STATUSES,
    UNIT_STATUS_BLOCKED_BY_CANCELLED_DEPENDENCY,
    UNIT_STATUS_CANCELLED,
    UNIT_STATUS_CANCELLED_OUTCOME_UNKNOWN,
    UNIT_STATUS_NOT_STARTED_CANCELLED,
    _blocked,
    _cancellation_rollup,
    _dependency_failed,
    _dependency_satisfied,
    dispatch_fanout,
)
from omh.coding.fanout_journal import (
    RESUME_HOLD_REPLAY_UNSAFE,
    RESUME_RERUN_CANCELLED,
    RESUME_RERUN_NOT_ATTEMPTED,
    RESUME_UNSKIP_DEPENDENT,
    TERMINAL_CANCELLED,
    TERMINAL_NOT_ATTEMPTED,
    TERMINAL_SKIPPED_BY_DEPENDENCY,
    plan_fanout_resume,
    build_fanout_run_journal,
    journal_unit_entry,
)
from omh.system.paths import OmhPaths


_GOAL = "cancellation drill"
_UNITS = [
    {"unit_id": "one", "title": "One", "owner": "codex", "file_scope": ["src/one/"]},
    {"unit_id": "two", "title": "Two", "owner": "codex", "file_scope": ["src/two/"]},
]


def _paths(tmp: str) -> OmhPaths:
    root = Path(tmp)
    return OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")


def _make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"],
        cwd=str(repo),
        check=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, sha


def _ready(paths, profile, **kwargs):
    return {"status": "ready", "profile": profile}


class CancelledDependencyTests(unittest.TestCase):
    def test_a_cancelled_dependency_is_never_a_satisfied_prerequisite(self) -> None:
        for status in sorted(CANCELLED_UNIT_STATUSES):
            with self.subTest(status=status):
                self.assertFalse(_dependency_satisfied({"status": status}))
                self.assertTrue(_dependency_failed({"status": status}))

    def test_a_dependent_of_a_cancelled_unit_says_so_in_its_own_status(self) -> None:
        unit = {"unit_id": "two", "depends_on": ["one"]}
        entry = _blocked(unit, {"one": {"status": UNIT_STATUS_CANCELLED}})

        self.assertEqual(entry["status"], UNIT_STATUS_BLOCKED_BY_CANCELLED_DEPENDENCY)
        self.assertEqual(entry["blocked_on"], ["one"])
        self.assertFalse(entry["integration_ready"])

    def test_a_dependent_of_a_failed_unit_keeps_the_ordinary_blocked_status(self) -> None:
        """The new status is about cancellation only; a failure still reads as one."""
        entry = _blocked({"unit_id": "two", "depends_on": ["one"]}, {"one": {"status": "failed"}})

        self.assertEqual(entry["status"], "blocked_by_dependency")


class CancellationRollupTests(unittest.TestCase):
    def test_the_rollup_sorts_every_unit_into_exactly_one_bucket(self) -> None:
        rollup = _cancellation_rollup(
            [
                {"unit_id": "a", "status": UNIT_STATUS_CANCELLED},
                {"unit_id": "b", "status": UNIT_STATUS_CANCELLED_OUTCOME_UNKNOWN},
                {"unit_id": "c", "status": UNIT_STATUS_NOT_STARTED_CANCELLED},
                {"unit_id": "d", "status": UNIT_STATUS_BLOCKED_BY_CANCELLED_DEPENDENCY},
                {"unit_id": "e", "status": "completed"},
            ]
        )

        self.assertEqual(rollup["cancelled"], ["a"])
        self.assertEqual(rollup["outcome_unknown"], ["b"])
        self.assertEqual(rollup["never_started"], ["c"])
        self.assertEqual(rollup["blocked_by_cancelled_dependency"], ["d"])

    def test_the_rollup_is_metadata_only(self) -> None:
        rollup = _cancellation_rollup([{"unit_id": "a", "status": UNIT_STATUS_CANCELLED, "output_tail": "secret"}])

        self.assertEqual(
            sorted(rollup),
            ["blocked_by_cancelled_dependency", "cancelled", "claim_boundary", "never_started", "outcome_unknown"],
        )
        self.assertNotIn("secret", str(rollup))
        self.assertIn("not execution, verification", rollup["claim_boundary"])


class CancelledJournalTests(unittest.TestCase):
    def test_a_terminated_unit_journals_as_cancelled_with_no_failure_class(self) -> None:
        row = journal_unit_entry(
            {"unit_id": "a", "owner": "codex", "status": UNIT_STATUS_CANCELLED, "exit_code": -15}
        )

        self.assertEqual(row["terminal_state"], TERMINAL_CANCELLED)
        self.assertEqual(row["failure_class"], "")
        self.assertEqual(row["failure_label"], "")

    def test_the_other_three_cancellation_states_journal_distinctly(self) -> None:
        cases = {
            UNIT_STATUS_CANCELLED_OUTCOME_UNKNOWN: TERMINAL_CANCELLED,
            UNIT_STATUS_NOT_STARTED_CANCELLED: TERMINAL_NOT_ATTEMPTED,
            UNIT_STATUS_BLOCKED_BY_CANCELLED_DEPENDENCY: TERMINAL_SKIPPED_BY_DEPENDENCY,
        }
        for status, expected in cases.items():
            with self.subTest(status=status):
                row = journal_unit_entry({"unit_id": "a", "owner": "codex", "status": status})
                self.assertEqual(row["terminal_state"], expected)

    def test_resume_is_deterministic_across_the_cancellation_states(self) -> None:
        summary = {
            "fanout_id": "f1",
            "merge_order": ["a", "b", "c"],
            "units": [
                # A probe that measured a clean worktree is what makes a
                # terminated unit re-dispatchable; without one it is held below.
                {
                    "unit_id": "a",
                    "owner": "codex",
                    "status": UNIT_STATUS_CANCELLED,
                    "exit_code": -15,
                    "recovery": {"outcome": "no_changes"},
                },
                {"unit_id": "b", "owner": "codex", "status": UNIT_STATUS_NOT_STARTED_CANCELLED},
                {
                    "unit_id": "c",
                    "owner": "codex",
                    "status": UNIT_STATUS_BLOCKED_BY_CANCELLED_DEPENDENCY,
                    "blocked_on": ["a"],
                },
            ],
        }
        journal = build_fanout_run_journal(summary)
        order = ["a", "b", "c"]
        depends_on = {"a": [], "b": [], "c": ["a"]}

        plan = plan_fanout_resume(journal, order=order, depends_on=depends_on)
        actions = {str(row["unit_id"]): str(row["action"]) for row in plan["decisions"]}

        self.assertEqual(actions["a"], RESUME_RERUN_CANCELLED)
        self.assertEqual(actions["b"], RESUME_RERUN_NOT_ATTEMPTED)
        self.assertEqual(actions["c"], RESUME_UNSKIP_DEPENDENT)
        # Re-planning the same journal gives the same answer.
        self.assertEqual(
            plan["decisions"],
            plan_fanout_resume(journal, order=order, depends_on=depends_on)["decisions"],
        )

    def test_a_terminated_unit_whose_worktree_nobody_measured_is_held(self) -> None:
        """Fail-closed, exactly as for a failure: a resume never rebuilds over unmeasured work.

        An interrupted batch skips the recovery probe entirely, so this is the
        state a real cancelled unit is in, and holding it is the answer.
        """
        summary = {
            "fanout_id": "f1",
            "merge_order": ["a"],
            "units": [{"unit_id": "a", "owner": "codex", "status": UNIT_STATUS_CANCELLED, "exit_code": -15}],
        }
        journal = build_fanout_run_journal(summary)

        plan = plan_fanout_resume(journal, order=["a"], depends_on={"a": []})

        self.assertEqual(str(plan["decisions"][0]["action"]), RESUME_HOLD_REPLAY_UNSAFE)
        self.assertEqual(str(plan["decisions"][0]["prior_state"]), TERMINAL_CANCELLED)


class InterruptedRunningUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        from omh.coding.fanout_dispatch import _INTERRUPT_FLAG

        _INTERRUPT_FLAG.clear()

    def test_a_signal_killed_unit_records_cancelled_rather_than_a_model_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            root = Path(tmp)
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
            spawned: list[str] = []

            def runner(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                spawned.append(argv[0])
                if len(spawned) == 1:
                    # The group terminator's signature: a negative exit code.
                    return subprocess.CompletedProcess(list(argv), -15, "", "")
                raise KeyboardInterrupt

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                concurrency=1,
                runner=runner,
                readiness=_ready,
            )

            statuses = {entry["unit_id"]: entry["status"] for entry in summary["units"]}
            self.assertEqual(statuses["one"], UNIT_STATUS_CANCELLED)
            killed = next(entry for entry in summary["units"] if entry["unit_id"] == "one")
            self.assertTrue(killed["interrupted"])
            self.assertNotIn("failure_kind", killed)
            self.assertFalse(killed["process_succeeded"])
            self.assertFalse(killed["integration_ready"])
            self.assertEqual(summary["cancellation"]["cancelled"], ["one"])


if __name__ == "__main__":
    unittest.main()
