"""Run journal, crash-consistent write, and the resume rule read off it.

Four properties, in the order a resume depends on them:

* One dispatch summary projects to one journal row per unit, and the row's
  terminal state is derived from what was observed -- not from the status
  string alone, which cannot tell a unit that never spawned from one that
  spawned and failed.
* A write that dies mid-flight leaves the PREVIOUS journal byte-identical.
  The whole surface is worthless otherwise: a resume that reads a truncated
  journal is a resume that re-dispatches units it should have held.
* The resume matrix. A succeeded unit is never re-run; a failure with no
  observed side effect is; a failure that left work behind is NOT, with the
  reason named; and a dependent skipped behind a blocker is un-skipped exactly
  when that blocker is being attempted again.
* The verdict survives being carried through a run that did not re-run the
  unit, and a held unit costs nothing at dispatch time -- no spawn, and no
  telemetry event, so the live reporter cannot double-report it.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import (  # noqa: E402
    fanout_run_journal_path,
    write_fanout_contract,
)
from omh.coding.fanout_dispatch import dispatch_fanout  # noqa: E402
from omh.coding.fanout_journal import (  # noqa: E402
    FANOUT_RESUME_PLAN_SCHEMA_VERSION,
    FANOUT_RUN_JOURNAL_SCHEMA_VERSION,
    FAILURE_CLASS_DECLINED_CONCLUSIVE,
    JOURNAL_CORRUPT,
    JOURNAL_FANOUT_MISMATCH,
    JOURNAL_MISSING,
    JOURNAL_SCHEMA_UNSUPPORTED,
    RESUME_HOLD_BLOCKED_DEPENDENCY,
    RESUME_HOLD_DECLINED,
    RESUME_HOLD_REPLAY_UNSAFE,
    RESUME_HOLD_SUCCEEDED,
    RESUME_RERUN_FAILED,
    RESUME_RERUN_NOT_ATTEMPTED,
    RESUME_UNSKIP_DEPENDENT,
    TERMINAL_DECLINED,
    TERMINAL_FAILED,
    TERMINAL_NOT_ATTEMPTED,
    TERMINAL_SKIPPED_BY_DEPENDENCY,
    TERMINAL_SUCCEEDED,
    FanoutJournalError,
    build_fanout_run_journal,
    plan_fanout_resume,
    read_fanout_run_journal,
    write_fanout_run_journal,
)
from omh.coding.fanout_repair import REPAIR_IN_FLIGHT_STATUS  # noqa: E402
from omh.coding.fanout_retry import (  # noqa: E402
    CLASS_TERMINAL_FAILURE,
    REPLAY_SAFE,
    REPLAY_UNSAFE_SIDE_EFFECTS,
)
from omh.runtime.artifacts import show_run  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402

_GOAL = "split the sample feature across agents"
_UNITS = [
    {"unit_id": "core", "title": "Core work", "owner": "codex", "file_scope": ["src/core/"]},
    {"unit_id": "docs", "title": "Docs work", "owner": "claude-code", "file_scope": ["docs/"]},
    {
        "unit_id": "tests",
        "title": "Test work",
        "owner": "codex",
        "file_scope": ["tests/"],
        "depends_on": ["core"],
    },
]
_ORDER = ["core", "docs", "tests"]
_DEPENDS_ON = {"core": [], "docs": [], "tests": ["core"]}


def _summary(*units: dict[str, object], **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "fanout_id": "fanout-1",
        "base_sha": "abc123",
        "merge_order": [str(unit["unit_id"]) for unit in units],
        "units": list(units),
    }
    payload.update(overrides)
    return payload


def _succeeded(unit_id: str) -> dict[str, object]:
    return {
        "unit_id": unit_id,
        "run_ref": f"run-{unit_id}",
        "owner": "codex",
        "status": "completed",
        "exit_code": 0,
        "process_succeeded": True,
        "unit_result": {"unit_id": unit_id},
    }


def _failed(unit_id: str, *, recovery: str | None = "no_changes") -> dict[str, object]:
    entry: dict[str, object] = {
        "unit_id": unit_id,
        "run_ref": f"run-{unit_id}",
        "owner": "codex",
        "status": "failed",
        "exit_code": 1,
        "process_succeeded": False,
    }
    if recovery is not None:
        entry["recovery"] = {"outcome": recovery}
    return entry


def _blocked(unit_id: str, *, blocked_on: list[str]) -> dict[str, object]:
    return {
        "unit_id": unit_id,
        "run_ref": f"run-{unit_id}",
        "owner": "codex",
        "status": "blocked_by_dependency",
        "process_succeeded": False,
        "blocked_on": blocked_on,
    }


def _declined(
    unit_id: str, *, reason: str = "target_not_found", recovery: str | None = "no_changes"
) -> dict[str, object]:
    """A unit whose validated sidecar reported a conclusive negative answer.

    `result_schema_valid` is set because only the dispatcher's own observation
    that the sidecar validated -- never the raw claim alone -- may promote a
    unit to `declined`; see `_unit_result_declined`.
    """
    entry: dict[str, object] = {
        "unit_id": unit_id,
        "run_ref": f"run-{unit_id}",
        "owner": "codex",
        "status": "failed",
        "exit_code": 3,
        "process_succeeded": False,
        "result_schema_valid": True,
        "unit_result": {"unit_id": unit_id, "process_status": "process_declined", "decline_reason": reason},
    }
    if recovery is not None:
        entry["recovery"] = {"outcome": recovery}
    return entry


def _interrupted(unit_id: str) -> dict[str, object]:
    return {
        "unit_id": unit_id,
        "run_ref": f"run-{unit_id}",
        "owner": "codex",
        "status": "interrupted",
        "process_succeeded": False,
    }


def _rows(journal: dict) -> dict[str, dict]:
    return {row["unit_id"]: row for row in journal["units"]}


def _actions(plan: dict) -> dict[str, str]:
    return {entry["unit_id"]: entry["action"] for entry in plan["decisions"]}


def _reason(plan: dict, unit_id: str) -> str:
    return next(entry["reason"] for entry in plan["decisions"] if entry["unit_id"] == unit_id)


class JournalProjectionTests(unittest.TestCase):
    def test_an_in_flight_repair_skip_remains_not_attempted_when_resumed(self) -> None:
        entry = {"unit_id": "core", "run_ref": "run-core", "owner": "codex", "status": REPAIR_IN_FLIGHT_STATUS}
        journal = build_fanout_run_journal(_summary(entry))
        row = _rows(journal)["core"]
        self.assertEqual(row["terminal_state"], TERMINAL_NOT_ATTEMPTED)
        self.assertTrue(row["replay_safe"])
        self.assertEqual(row["side_effect"], "no_spawn_observed")
        plan = plan_fanout_resume(journal, order=["core"], depends_on={"core": []})
        self.assertEqual(_actions(plan), {"core": RESUME_RERUN_NOT_ATTEMPTED})
        self.assertEqual(plan["selected_units"], ["core"])

    def test_each_terminal_state_is_derived_from_what_was_observed(self) -> None:
        journal = build_fanout_run_journal(
            _summary(
                _succeeded("core"),
                _failed("docs"),
                _blocked("tests", blocked_on=["docs"]),
                _interrupted("lint"),
            )
        )
        rows = _rows(journal)
        self.assertEqual(rows["core"]["terminal_state"], TERMINAL_SUCCEEDED)
        self.assertEqual(rows["docs"]["terminal_state"], TERMINAL_FAILED)
        self.assertEqual(rows["tests"]["terminal_state"], TERMINAL_SKIPPED_BY_DEPENDENCY)
        self.assertEqual(rows["tests"]["blocked_on"], ["docs"])
        self.assertEqual(rows["lint"]["terminal_state"], TERMINAL_NOT_ATTEMPTED)

    def test_a_unit_that_never_spawned_is_replay_safe_and_one_that_wrote_is_not(self) -> None:
        journal = build_fanout_run_journal(
            _summary(
                _interrupted("core"),
                _failed("docs", recovery="recovery_available"),
                _failed("tests", recovery=None),
            )
        )
        rows = _rows(journal)
        # No exit code means no process, so there is nothing a replay destroys.
        self.assertTrue(rows["core"]["replay_safe"])
        self.assertEqual(rows["core"]["side_effect"], "no_spawn_observed")
        self.assertEqual(rows["core"]["replay_verdict"], REPLAY_SAFE)
        # A worktree the probe found changes in blocks the replay ...
        self.assertFalse(rows["docs"]["replay_safe"])
        self.assertEqual(rows["docs"]["replay_verdict"], REPLAY_UNSAFE_SIDE_EFFECTS)
        # ... and so does a worktree nobody could measure at all.
        self.assertFalse(rows["tests"]["replay_safe"])

    def test_a_result_artifact_blocks_a_replay_even_with_a_clean_worktree(self) -> None:
        entry = _failed("core")
        entry["unit_result"] = {"unit_id": "core"}
        row = _rows(build_fanout_run_journal(_summary(entry)))["core"]
        self.assertFalse(row["replay_safe"])
        self.assertEqual(row["replay_verdict"], REPLAY_UNSAFE_SIDE_EFFECTS)

    def test_the_failure_class_is_read_from_the_retry_decision_not_re_derived(self) -> None:
        entry = _failed("core")
        entry["retry"] = {
            "decisions": [
                {"failure_class": "transient_transport", "failure_label": "socket_hang_up"},
            ]
        }
        row = _rows(build_fanout_run_journal(_summary(entry)))["core"]
        self.assertEqual(row["failure_class"], "transient_transport")
        self.assertEqual(row["failure_label"], "socket_hang_up")

    def test_a_failure_the_retry_ladder_never_saw_falls_back_to_the_exit_code(self) -> None:
        row = _rows(build_fanout_run_journal(_summary(_failed("core"))))["core"]
        self.assertEqual(row["failure_class"], CLASS_TERMINAL_FAILURE)

    def test_an_interrupted_batch_is_recorded_on_the_journal(self) -> None:
        journal = build_fanout_run_journal(_summary(_interrupted("core"), interrupted=True))
        self.assertTrue(journal["interrupted"])

    def test_a_declined_unit_gets_its_own_terminal_state_distinct_from_failed(self) -> None:
        # #H: a negative but CONCLUSIVE outcome ("the target does not exist")
        # must not be shoehorned into `failed`, which implies a retry might
        # help. The journal's own `declined_conclusive` class is used instead
        # of `fanout_retry`'s `terminal_failure`, because the retry ladder
        # never asked whether the answer was conclusive -- it only asked
        # whether it was transient.
        row = _rows(build_fanout_run_journal(_summary(_declined("core"))))["core"]
        self.assertEqual(row["terminal_state"], TERMINAL_DECLINED)
        self.assertNotEqual(row["terminal_state"], TERMINAL_FAILED)
        self.assertEqual(row["failure_class"], FAILURE_CLASS_DECLINED_CONCLUSIVE)
        self.assertEqual(row["decline_reason"], "target_not_found")

    def test_a_declined_unit_is_never_promoted_from_an_unvalidated_self_report(self) -> None:
        # Mirrors `fanout_unit_results`' own rule: only the dispatcher's own
        # observation that a sidecar validated may promote a claim. A stray
        # `process_declined` sitting under an entry the dispatcher never
        # validated must not read as a decline.
        entry = _failed("core")
        entry["unit_result"] = {"unit_id": "core", "process_status": "process_declined", "decline_reason": "x"}
        row = _rows(build_fanout_run_journal(_summary(entry)))["core"]
        self.assertEqual(row["terminal_state"], TERMINAL_FAILED)
        self.assertEqual(row["decline_reason"], "")

    def test_a_succeeded_exit_outranks_a_stray_declined_self_report(self) -> None:
        entry = _succeeded("core")
        entry["result_schema_valid"] = True
        entry["unit_result"] = {"unit_id": "core", "process_status": "process_declined", "decline_reason": "x"}
        row = _rows(build_fanout_run_journal(_summary(entry)))["core"]
        self.assertEqual(row["terminal_state"], TERMINAL_SUCCEEDED)


class JournalRoundTripTests(unittest.TestCase):
    def test_a_written_journal_reads_back_identically(self) -> None:
        journal = build_fanout_run_journal(
            _summary(_succeeded("core"), _failed("docs"), _blocked("tests", blocked_on=["docs"]))
        )
        with TemporaryDirectory() as tmp:
            path = write_fanout_run_journal(Path(tmp) / "run_journal.json", journal)
            self.assertEqual(read_fanout_run_journal(path), journal)
            self.assertEqual(journal["schema_version"], FANOUT_RUN_JOURNAL_SCHEMA_VERSION)
            self.assertEqual(journal["merge_order"], ["core", "docs", "tests"])

    def test_reading_refuses_every_unusable_journal_with_a_reason_code(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = [
                (root / "absent.json", None, JOURNAL_MISSING),
                (root / "garbage.json", "{not json", JOURNAL_CORRUPT),
                (root / "array.json", "[]", JOURNAL_CORRUPT),
                (
                    root / "old.json",
                    json.dumps({"schema_version": "fanout_run_journal/v0", "units": []}),
                    JOURNAL_SCHEMA_UNSUPPORTED,
                ),
                (
                    root / "shape.json",
                    json.dumps(
                        {
                            "schema_version": FANOUT_RUN_JOURNAL_SCHEMA_VERSION,
                            "units": [{"unit_id": "core"}],
                        }
                    ),
                    JOURNAL_CORRUPT,
                ),
            ]
            for path, text, reason_code in cases:
                if text is not None:
                    path.write_text(text, encoding="utf-8")
                with self.assertRaises(FanoutJournalError) as caught:
                    read_fanout_run_journal(path)
                self.assertEqual(caught.exception.reason_code, reason_code, str(path))

    def test_a_journal_from_another_fanout_is_refused(self) -> None:
        journal = build_fanout_run_journal(_summary(_succeeded("core")))
        with TemporaryDirectory() as tmp:
            path = write_fanout_run_journal(Path(tmp) / "run_journal.json", journal)
            with self.assertRaises(FanoutJournalError) as caught:
                read_fanout_run_journal(path, expected_fanout_id="fanout-2")
            self.assertEqual(caught.exception.reason_code, JOURNAL_FANOUT_MISMATCH)


class JournalCrashConsistencyTests(unittest.TestCase):
    def test_a_write_that_dies_before_the_rename_leaves_the_prior_journal_intact(self) -> None:
        first = build_fanout_run_journal(_summary(_succeeded("core"), _failed("docs")))
        second = build_fanout_run_journal(_summary(_succeeded("core"), _succeeded("docs")))
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_journal.json"
            write_fanout_run_journal(path, first)
            before = path.read_bytes()
            with mock.patch.object(Path, "replace", side_effect=OSError("crash mid-write")):
                with self.assertRaises(OSError):
                    write_fanout_run_journal(path, second)
            # The point of temp-then-rename: not a truncated document, not a
            # merged one -- exactly the bytes that were there before.
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(read_fanout_run_journal(path), first)
            # And no half-written sibling left behind for a later reader to find.
            self.assertEqual(sorted(child.name for child in path.parent.iterdir()), ["run_journal.json"])


class ResumeMatrixTests(unittest.TestCase):
    def _plan(self, *units: dict[str, object]) -> dict:
        return plan_fanout_resume(
            build_fanout_run_journal(_summary(*units)),
            order=_ORDER,
            depends_on=_DEPENDS_ON,
        )

    def test_a_succeeded_unit_is_never_re_run_and_still_clears_its_dependent(self) -> None:
        plan = self._plan(_succeeded("core"), _succeeded("docs"), _failed("tests"))
        actions = _actions(plan)
        self.assertEqual(actions["core"], RESUME_HOLD_SUCCEEDED)
        self.assertEqual(actions["docs"], RESUME_HOLD_SUCCEEDED)
        # `tests` depends on `core`, which succeeded: the dependency is clear
        # without `core` running again.
        self.assertEqual(actions["tests"], RESUME_RERUN_FAILED)
        self.assertEqual(plan["selected_units"], ["tests"])
        self.assertEqual(sorted(plan["held_units"]), ["core", "docs"])

    def test_a_replay_safe_failure_is_re_run_and_un_skips_its_dependent(self) -> None:
        plan = self._plan(
            _failed("core"),
            _succeeded("docs"),
            _blocked("tests", blocked_on=["core"]),
        )
        actions = _actions(plan)
        self.assertEqual(actions["core"], RESUME_RERUN_FAILED)
        self.assertEqual(actions["docs"], RESUME_HOLD_SUCCEEDED)
        self.assertEqual(actions["tests"], RESUME_UNSKIP_DEPENDENT)
        self.assertEqual(plan["selected_units"], ["core", "tests"])
        self.assertIn("no longer skipped", _reason(plan, "tests"))

    def test_a_replay_unsafe_failure_is_held_and_its_dependent_stays_skipped(self) -> None:
        plan = self._plan(
            _failed("core", recovery="recovery_available"),
            _succeeded("docs"),
            _blocked("tests", blocked_on=["core"]),
        )
        actions = _actions(plan)
        self.assertEqual(actions["core"], RESUME_HOLD_REPLAY_UNSAFE)
        self.assertEqual(actions["tests"], RESUME_HOLD_BLOCKED_DEPENDENCY)
        self.assertEqual(plan["selected_units"], [])
        self.assertIn("destroys the work the failure left behind", _reason(plan, "core"))
        self.assertIn("core", _reason(plan, "tests"))

    def test_an_unmeasured_worktree_is_held_the_same_way(self) -> None:
        plan = self._plan(_failed("core", recovery=None), _succeeded("docs"), _succeeded("tests"))
        self.assertEqual(_actions(plan)["core"], RESUME_HOLD_REPLAY_UNSAFE)

    def test_a_declined_unit_is_held_and_never_selected_for_rerun(self) -> None:
        # #H requirement (a): retry/resume must not select a negative-
        # conclusive unit. Held even though it is replay-safe (no side
        # effect): resuming it would not answer the question any differently.
        plan = self._plan(
            _declined("core", reason="refused_by_policy"),
            _succeeded("docs"),
            _blocked("tests", blocked_on=["core"]),
        )
        actions = _actions(plan)
        self.assertEqual(actions["core"], RESUME_HOLD_DECLINED)
        self.assertNotIn("core", plan["selected_units"])
        self.assertIn("core", plan["held_units"])
        self.assertIn("refused_by_policy", _reason(plan, "core"))
        # Its dependent stays blocked, exactly like a replay-unsafe blocker:
        # a decline never clears the way for downstream work either.
        self.assertEqual(actions["tests"], RESUME_HOLD_BLOCKED_DEPENDENCY)

    def test_a_declined_unit_is_held_even_when_replay_would_be_unsafe_too(self) -> None:
        # A decline is unconditional: it is held for its own answer, not for
        # what it may have touched on the way to reaching it.
        plan = self._plan(_declined("core", recovery="recovery_available"))
        self.assertEqual(_actions(plan)["core"], RESUME_HOLD_DECLINED)

    def test_units_the_interrupt_never_started_are_re_run(self) -> None:
        plan = self._plan(_succeeded("core"), _interrupted("docs"), _interrupted("tests"))
        actions = _actions(plan)
        self.assertEqual(actions["docs"], RESUME_RERUN_NOT_ATTEMPTED)
        self.assertEqual(actions["tests"], RESUME_RERUN_NOT_ATTEMPTED)

    def test_a_unit_absent_from_the_journal_is_re_run(self) -> None:
        plan = self._plan(_succeeded("core"))
        actions = _actions(plan)
        self.assertEqual(actions["docs"], RESUME_RERUN_NOT_ATTEMPTED)
        self.assertIn("never recorded", _reason(plan, "docs"))

    def test_the_plan_names_its_schema_and_what_it_resumed_from(self) -> None:
        journal = build_fanout_run_journal(_summary(_failed("core"), interrupted=True))
        plan = plan_fanout_resume(journal, order=_ORDER, depends_on=_DEPENDS_ON)
        self.assertEqual(plan["schema_version"], FANOUT_RESUME_PLAN_SCHEMA_VERSION)
        self.assertEqual(plan["resumed_from"]["journal_schema_version"], FANOUT_RUN_JOURNAL_SCHEMA_VERSION)
        self.assertTrue(plan["resumed_from"]["interrupted"])


class ResumeVerdictCarryForwardTests(unittest.TestCase):
    def test_a_held_replay_unsafe_unit_stays_held_across_a_second_resume(self) -> None:
        # The regression this exists for: a held unit is recorded in the
        # resumed run's summary as a plain skip. Re-deriving its state from
        # that skip would read "never attempted", and the NEXT resume would
        # re-dispatch exactly the unit the first one refused to.
        first = build_fanout_run_journal(
            _summary(_failed("core", recovery="recovery_available"), _succeeded("docs"))
        )
        plan = plan_fanout_resume(first, order=_ORDER, depends_on=_DEPENDS_ON)
        held = next(entry for entry in plan["decisions"] if entry["unit_id"] == "core")
        resumed_entry = {
            "unit_id": "core",
            "run_ref": "run-core",
            "owner": "codex",
            "status": "not_selected",
            "process_succeeded": False,
            "resume": {
                "action": held["action"],
                "prior_state": held["prior_state"],
                "reason": held["reason"],
                "carry_forward": held["carry_forward"],
            },
        }
        second = build_fanout_run_journal(_summary(resumed_entry, _succeeded("docs")))
        row = _rows(second)["core"]
        self.assertEqual(row["terminal_state"], TERMINAL_FAILED)
        self.assertFalse(row["replay_safe"])
        again = plan_fanout_resume(second, order=_ORDER, depends_on=_DEPENDS_ON)
        self.assertEqual(_actions(again)["core"], RESUME_HOLD_REPLAY_UNSAFE)


def _git(repo: Path, *argv: str) -> None:
    subprocess.run(["git", *argv], cwd=str(repo), check=True, capture_output=True, text=True)


def _make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, sha


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _runner(*, fail_units: set[str] | None = None, write_units: set[str] | None = None):
    """Fake agent CLI; `write_units` leave real files for the recovery probe."""
    spawned: list[str] = []

    def owns(prompt: str, unit_id: str) -> bool:
        return f"agent/{unit_id} in the current worktree" in prompt

    def runner(argv, **kwargs):
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        prompt = " ".join(argv)
        cwd = Path(str(kwargs.get("cwd", ".")))
        for unit_id in _ORDER:
            if owns(prompt, unit_id):
                spawned.append(unit_id)
        for unit_id in write_units or set():
            if owns(prompt, unit_id):
                (cwd / f"{unit_id}_partial.py").write_text("value = 1\n", encoding="utf-8")
        for unit_id in fail_units or set():
            if owns(prompt, unit_id):
                return _FakeCompleted(1, f"unit {unit_id} failed")
        return _FakeCompleted(0, "done")

    runner.spawned = spawned
    return runner


def _ready(paths, profile, **kwargs):
    return {"status": "ready", "profile": profile}


def _clear_unit_worktree(repo: Path, unit_id: str) -> None:
    """The remedy the dispatcher's own refusals name, applied by hand.

    OMH never removes a worktree or a branch for the operator, so a resume of a
    unit whose earlier attempt left both behind only proceeds once they are
    cleared. Doing it explicitly here is the honest fixture.
    """
    _git(repo, "worktree", "remove", "--force", str(repo.parent / f"{repo.name}-fanout-{unit_id}"))
    _git(repo, "branch", "-D", f"agent/{unit_id}")


def _worker_results(paths: OmhPaths, run_ref: str) -> int:
    shown = show_run(paths, run_ref)
    return sum(
        1
        for event in shown.get("journal_events", []) or []
        if str(event.get("event", "")) == "worker_result"
    )


class ResumeDispatchIntegrationTests(unittest.TestCase):
    def _setup(self, tmp: str):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
        return paths, repo, sha, contract

    def _dispatch(self, paths, repo, sha, contract, runner, resume_journal=None, only_units=None):
        return dispatch_fanout(
            paths,
            contract,
            goal_text=_GOAL,
            repo_root=repo,
            base_sha=sha,
            runner=runner,
            readiness=_ready,
            only_units=only_units,
            resume_journal=resume_journal,
        )

    def _journal(self, paths, contract) -> dict:
        return read_fanout_run_journal(fanout_run_journal_path(paths, contract["fanout_id"]))

    def _run_ref(self, contract, unit_id: str) -> str:
        return next(
            str(unit["run_ref"]) for unit in contract["units"] if unit["unit_id"] == unit_id
        )

    def test_a_dispatch_writes_a_run_journal_next_to_its_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            summary = self._dispatch(paths, repo, sha, contract, _runner(fail_units={"core"}))
            path = fanout_run_journal_path(paths, contract["fanout_id"])
            self.assertEqual(summary["run_journal_path"], str(path))
            rows = _rows(read_fanout_run_journal(path, expected_fanout_id=contract["fanout_id"]))
            self.assertEqual(rows["core"]["terminal_state"], TERMINAL_FAILED)
            self.assertEqual(rows["docs"]["terminal_state"], TERMINAL_SUCCEEDED)
            self.assertEqual(rows["tests"]["terminal_state"], TERMINAL_SKIPPED_BY_DEPENDENCY)

    def test_a_resume_runs_only_what_the_cut_short_run_never_reached(self) -> None:
        # The headline case: a run that stopped before every unit was tried.
        # Nothing was started for `core` or `tests`, so they have no worktree
        # and no side effect, and the resume simply picks them up.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            self._dispatch(paths, repo, sha, contract, _runner(), only_units=["docs"])
            journal = self._journal(paths, contract)
            docs_before = _worker_results(paths, self._run_ref(contract, "docs"))

            resumed = _runner()
            summary = self._dispatch(
                paths, repo, sha, contract, resumed, resume_journal=journal
            )

            self.assertEqual(sorted(resumed.spawned), ["core", "tests"])
            units = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(units["core"]["resume"]["action"], RESUME_RERUN_NOT_ATTEMPTED)
            self.assertEqual(units["tests"]["resume"]["action"], RESUME_RERUN_NOT_ATTEMPTED)
            self.assertEqual(units["docs"]["resume"]["action"], RESUME_HOLD_SUCCEEDED)
            self.assertEqual(units["docs"]["status"], "already_completed")
            self.assertEqual(summary["resume"]["counts"][RESUME_HOLD_SUCCEEDED], 1)
            # A held unit is never dispatched, so no second `worker_result` is
            # appended for it and the live telemetry reporter -- which only
            # exists inside a dispatch -- cannot report it a second time.
            self.assertEqual(_worker_results(paths, self._run_ref(contract, "docs")), docs_before)

    def test_a_replay_safe_failure_is_selected_and_still_meets_the_worktree_refusal(self) -> None:
        # The plan decides eligibility; it does not reach into the repository.
        # A unit whose earlier attempt left its worktree in place is selected
        # and then meets the dispatcher's own long-standing refusal -- OMH
        # never auto-deletes a worktree, and a resume is not the place to start.
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            self._dispatch(paths, repo, sha, contract, _runner(fail_units={"core"}))
            journal = self._journal(paths, contract)
            self.assertTrue(_rows(journal)["core"]["replay_safe"])

            summary = self._dispatch(paths, repo, sha, contract, _runner(), resume_journal=journal)
            units = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(units["core"]["resume"]["action"], RESUME_RERUN_FAILED)
            self.assertEqual(units["core"]["status"], "worktree_failed")
            self.assertIn("remove it", units["core"]["reason"])

    def test_once_the_leftover_worktree_is_cleared_the_resume_re_runs_and_un_skips(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            self._dispatch(paths, repo, sha, contract, _runner(fail_units={"core"}))
            journal = self._journal(paths, contract)
            self.assertEqual(_rows(journal)["tests"]["terminal_state"], TERMINAL_SKIPPED_BY_DEPENDENCY)
            _clear_unit_worktree(repo, "core")

            resumed = _runner()
            summary = self._dispatch(paths, repo, sha, contract, resumed, resume_journal=journal)

            self.assertEqual(sorted(resumed.spawned), ["core", "tests"])
            units = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(units["core"]["resume"]["action"], RESUME_RERUN_FAILED)
            self.assertEqual(units["core"]["status"], "completed")
            # The blocker cleared, so the dependent the first run skipped runs.
            self.assertEqual(units["tests"]["resume"]["action"], RESUME_UNSKIP_DEPENDENT)
            self.assertEqual(units["tests"]["status"], "completed")
            self.assertEqual(units["docs"]["resume"]["action"], RESUME_HOLD_SUCCEEDED)

    def test_a_resume_refuses_to_replay_a_failure_that_left_work_behind(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            self._dispatch(
                paths,
                repo,
                sha,
                contract,
                _runner(fail_units={"core"}, write_units={"core"}),
            )
            journal = self._journal(paths, contract)
            self.assertFalse(_rows(journal)["core"]["replay_safe"])

            resumed = _runner()
            summary = self._dispatch(paths, repo, sha, contract, resumed, resume_journal=journal)

            self.assertEqual(resumed.spawned, [])
            units = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(units["core"]["resume"]["action"], RESUME_HOLD_REPLAY_UNSAFE)
            self.assertIn("recovery record", units["core"]["resume"]["reason"])
            self.assertEqual(units["tests"]["resume"]["action"], RESUME_HOLD_BLOCKED_DEPENDENCY)
            self.assertEqual(summary["resume"]["selected_units"], [])
            # And the refusal survives into the journal this resume writes.
            again = self._journal(paths, contract)
            self.assertFalse(_rows(again)["core"]["replay_safe"])
            self.assertEqual(_rows(again)["core"]["terminal_state"], TERMINAL_FAILED)

    def test_a_dispatch_without_a_journal_is_unchanged(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            runner = _runner()
            summary = self._dispatch(paths, repo, sha, contract, runner)
            self.assertEqual(sorted(runner.spawned), ["core", "docs", "tests"])
            self.assertNotIn("resume", summary)
            self.assertTrue(all("resume" not in entry for entry in summary["units"]))


class ResumeCliTests(unittest.TestCase):
    def test_an_unreadable_journal_is_refused_with_its_reason_code(self) -> None:
        from _cli_harness import run_cli

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, _sha = _make_repo(root)
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
            goal_file = root / "goal.txt"
            goal_file.write_text(_GOAL, encoding="utf-8")
            journal = root / "run_journal.json"
            journal.write_text("{not json", encoding="utf-8")
            code, _out, err = run_cli(
                [
                    "--omh-home",
                    str(paths.omh_home),
                    "--hermes-home",
                    str(paths.hermes_home),
                    "coding",
                    "fanout",
                    "dispatch",
                    str(contract["fanout_id"]),
                    "--goal-file",
                    str(goal_file),
                    "--repo-root",
                    str(repo),
                    "--resume-journal",
                    str(journal),
                    "--dry-run",
                ]
            )
            self.assertNotEqual(code, 0)
            self.assertIn(JOURNAL_CORRUPT, err)


if __name__ == "__main__":
    unittest.main()
