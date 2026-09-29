"""The fanout repair loop: a unit keeps going until an explicit stop criterion.

A unit that declares `max_repair_attempts` is re-dispatched in the SAME
worktree when the dispatcher itself observes a declared check exit nonzero, and
the loop stops only when every check is observed passing or the budget is
spent (recorded `blocked`, reason `repair_budget_exhausted`, last failing check
named). Pinned here with a fake executor and real git worktrees and real check
processes, plus the negative cases that keep the trigger narrow: no budget, a
reproduction unit's expected failure, a check that timed out, and an
executor's own claim that its checks passed.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import threading
from tempfile import TemporaryDirectory
from typing import Any
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.commands.coding import (  # noqa: E402
    _brief_repair,
    _fanout_brief_unit_line,
    _fanout_dispatch_exit_code,
    _fanout_show_repair,
)
from omh.coding import fanout_dispatch  # noqa: E402
from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import fanout_dispatch_summary_path, fanout_run_journal_path, write_fanout_contract  # noqa: E402
from omh.coding.fanout_journal import read_fanout_run_journal  # noqa: E402
from omh.coding.fanout_contracts import FanoutContractError  # noqa: E402
from omh.coding.fanout_dispatch import dispatch_fanout  # noqa: E402
from omh.coding.fanout_repair import (  # noqa: E402
    FANOUT_UNIT_REPAIR_SCHEMA_VERSION,
    MAX_REPAIR_ATTEMPTS,
    REPAIR_ATTEMPT_OBSERVED_EVENT,
    REPAIR_ATTEMPT_STARTED_EVENT,
    REPAIR_BUDGET_EXHAUSTED,
    REPAIR_IN_FLIGHT_STATUS,
    REPAIR_WORKTREE_MISSING,
    journal_repair_checks,
    observed_check_failure,
    project_unit_repair,
    repair_trigger_checks,
)
from omh.system.paths import OmhPaths  # noqa: E402
from omh.runtime.artifacts import append_journal_observation  # noqa: E402
from omh.workflows.observation_journal import read_observation_events  # noqa: E402

_GOAL = "make the value check pass"
_CHECK_SCRIPT = "check_value.py"
_CHECK = f"{shlex.quote(sys.executable)} {_CHECK_SCRIPT}"
_PASSING = f"{shlex.quote(sys.executable)} -c pass"
# Exits 1 unless the unit has written the fixed value; prints a marker so a
# test can prove no output text reaches the repair brief.
_CHECK_SOURCE = (
    "import pathlib, sys\n"
    "text = pathlib.Path('pkg/value.txt').read_text(encoding='utf-8').strip()\n"
    "print('RAW-CHECK-OUTPUT-' + text)\n"
    "sys.exit(0 if text == 'fixed' else 1)\n"
)


def _write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def _git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", *argv], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _ready(paths: OmhPaths, profile: str, **kwargs: object) -> dict[str, object]:
    return {"status": "ready", "profile": profile}


def _sidecar(argv: list[str]) -> Path:
    match = re.search(r"JSON sidecar to exactly (.+)\.", " ".join(argv))
    if match is None:
        raise AssertionError("missing invocation sidecar path")
    return Path(match[1])


class _Harness:
    """A fake executor writes the next planned value and commits; git and checks really run."""

    def __init__(
        self,
        test: unittest.TestCase,
        *,
        plan: list[str],
        units: list[dict[str, Any]] | None = None,
        max_repair_attempts: int | None = 2,
        self_report_pass: bool = False,
        timeout_checks: bool = False,
        on_spawn: Any = None,
    ) -> None:
        tmp = TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        self.repo = root / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        _write(self.repo, "pkg/value.txt", "broken\n")
        _write(self.repo, _CHECK_SCRIPT, _CHECK_SOURCE)
        self.base = _commit_all(self.repo, "init")
        if units is None:
            unit: dict[str, Any] = {
                "unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["pkg/"],
                "verification_commands": [_CHECK],
            }
            if max_repair_attempts is not None:
                unit["max_repair_attempts"] = max_repair_attempts
            units = [unit]
        self.contract = write_fanout_contract(self.paths, build_fanout_contract(_GOAL, units))
        self.run_refs = {str(unit["unit_id"]): str(unit["run_ref"]) for unit in self.contract["units"]}
        self.plan = list(plan)
        self.self_report_pass = self_report_pass
        self.timeout_checks = timeout_checks
        self.on_spawn = on_spawn
        self.prompts: list[str] = []
        self.spawn_worktrees: list[str] = []

    def runner(self, argv, **kwargs):
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        cwd = Path(str(kwargs.get("cwd")))
        if argv[0] == "codex":
            unit_id = cwd.name.rsplit("-fanout-", 1)[1]
            self.prompts.append(argv[-1])
            self.spawn_worktrees.append(str(cwd))
            if self.on_spawn is not None:
                self.on_spawn(len(self.prompts))
            if unit_id == "core":
                _write(cwd, "pkg/value.txt", self.plan.pop(0) + "\n")
            head = _commit_all(cwd, f"{unit_id} attempt {len(self.prompts)}")
            checks = []
            if self.self_report_pass:
                checks = [{
                    "command": _CHECK, "status": "passed", "evidence_ref": "executor:local-run",
                    "reported_by": "executor", "observed_by": None, "observation_source": None,
                }]
            payload = {
                "schema_version": "fanout_unit_result/v1",
                "unit_id": unit_id,
                "run_id": self.run_refs[unit_id],
                "fanout_id": self.contract["fanout_id"],
                "base_sha": self.base,
                "head_sha": head,
                "process_status": "process_succeeded",
                "changed_paths": ["pkg/value.txt"],
                "checks": checks,
                "findings": [],
            }
            sidecar = _sidecar(argv)
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "done", "")
        if self.timeout_checks and argv[-1] == _CHECK_SCRIPT:
            raise subprocess.TimeoutExpired(argv, 1)
        return subprocess.run(
            argv, cwd=kwargs.get("cwd"), env=kwargs.get("env"), text=True,
            capture_output=True, timeout=kwargs.get("timeout"),
        )

    def dispatch(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("readiness", _ready)
        return dispatch_fanout(
            self.paths,
            self.contract,
            goal_text=_GOAL,
            repo_root=self.repo,
            base_sha=self.base,
            runner=self.runner,
            run_verification=True,
            **kwargs,
        )

    def resume_journal(self) -> dict[str, Any]:
        return read_fanout_run_journal(fanout_run_journal_path(self.paths, self.contract["fanout_id"]))

    def left_pending(self, test: unittest.TestCase) -> dict[str, Any]:
        """Dispatch once with the interrupt raised mid-spawn: checks fail, no repair runs."""
        def interrupt(spawn: int) -> None:
            if spawn == 1:
                fanout_dispatch._INTERRUPT_FLAG.set()

        self.on_spawn = interrupt
        first = _unit(self.dispatch())
        fanout_dispatch._INTERRUPT_FLAG.clear()
        self.on_spawn = None
        test.assertEqual(first["repair"]["state"], "pending")
        return first

    def events(self, name: str, unit_id: str = "core") -> list[dict[str, Any]]:
        return [
            event
            for event in read_observation_events(self.paths, run_id=self.run_refs[unit_id], limit=None)
            if event.get("event") == name
        ]


def _unit(summary: dict[str, Any], unit_id: str = "core") -> dict[str, Any]:
    return next(entry for entry in summary["units"] if entry["unit_id"] == unit_id)


class RepairReachesVerifiedTests(unittest.TestCase):
    def test_fail_then_repair_then_pass_is_integration_ready_after_one_attempt(self) -> None:
        harness = _Harness(self, plan=["broken", "fixed"])

        summary = harness.dispatch()
        core = _unit(summary)

        self.assertEqual(len(harness.prompts), 2)
        self.assertEqual(core["unit_state"], "verified")
        self.assertTrue(core["integration_ready"])
        self.assertEqual(summary["integration_ready_units"], ["core"])
        repair = core["repair"]
        self.assertEqual(repair["schema_version"], FANOUT_UNIT_REPAIR_SCHEMA_VERSION)
        self.assertEqual(repair["attempts_used"], 1)
        self.assertEqual(repair["status"], "passed")
        self.assertEqual(repair["stop_reason"], "checks_passed")
        self.assertEqual([attempt["attempt"] for attempt in repair["attempts"]], [1])
        self.assertEqual(repair["attempts"][0]["check"]["command"], _CHECK)
        self.assertEqual(repair["attempts"][0]["check"]["exit_code"], 1)
        self.assertTrue(repair["attempts"][0]["started_at"])
        self.assertTrue(repair["attempts"][0]["check"]["observed_at"])
        self.assertEqual(_fanout_dispatch_exit_code(summary), 0)
        self.assertEqual(
            [event["status"] for event in harness.events(REPAIR_ATTEMPT_OBSERVED_EVENT)], ["failed", "observed"]
        )

    def test_the_repair_continues_the_same_worktree_and_keeps_prior_commits(self) -> None:
        harness = _Harness(self, plan=["broken", "fixed"])

        harness.dispatch()

        self.assertEqual(harness.spawn_worktrees[0], harness.spawn_worktrees[1])
        worktree = Path(harness.spawn_worktrees[0])
        subjects = _git(worktree, "log", "--format=%s", f"{harness.base}..HEAD").splitlines()
        self.assertEqual(subjects, ["core attempt 2", "core attempt 1"])

    def test_the_repair_brief_is_metadata_only_and_the_original_prompt_is_unchanged(self) -> None:
        harness = _Harness(self, plan=["broken", "fixed"])

        harness.dispatch()

        first, second = harness.prompts
        self.assertNotIn("[Repair attempt]", first)
        head, _, brief_text = second.partition("\n[Repair attempt]\n")
        # Same goal, scope, and criteria; only the sidecar path differs per attempt.
        self.assertEqual(re.sub(r"\S+\.json", "<sidecar>", head), re.sub(r"\S+\.json", "<sidecar>", first))
        brief = json.loads(brief_text)
        self.assertEqual(brief["repair_attempt"], 1)
        self.assertEqual(brief["max_repair_attempts"], 2)
        self.assertEqual(brief["observed_by"], "dispatcher")
        self.assertEqual(
            brief["failing_checks"], [{"command": _CHECK, "exit_code": 1, "failure_kind": "nonzero"}]
        )
        self.assertNotIn("RAW-CHECK-OUTPUT", second)
        self.assertNotIn("codex", brief_text)

    def test_a_failing_task_linked_test_is_a_repair_trigger(self) -> None:
        runner = f"{shlex.quote(sys.executable)} -m unittest"
        test_source = (
            "import pathlib, unittest\n\n\n"
            "class ValueTests(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        import pkg.value_mod as mod\n"
            "        self.assertEqual(mod.VALUE, 'fixed')\n"
        )
        units = [{
            "unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["pkg/"],
            "task_linked_test_runner": runner, "max_repair_attempts": 2,
        }]
        harness = _Harness(self, plan=[], units=units)
        _write(harness.repo, "pkg/__init__.py", "")
        _write(harness.repo, "pkg/value_mod.py", "VALUE = 'broken'\n")
        _write(harness.repo, "tests/test_value_mod.py", test_source.replace("import pkg.value_mod as mod\n", "from pkg import value_mod as mod\n"))
        harness.base = _commit_all(harness.repo, "seed")
        values = ["'still-broken'", "'fixed'"]
        original = harness.runner

        def runner_writing_module(argv, **kwargs):
            if argv[0] == "codex":
                _write(Path(str(kwargs.get("cwd"))), "pkg/value_mod.py", f"VALUE = {values.pop(0)}\n")
                harness.plan.append("unused")
            return original(argv, **kwargs)

        harness.runner = runner_writing_module  # type: ignore[method-assign]
        core = _unit(harness.dispatch())

        self.assertEqual(len(harness.prompts), 2)
        self.assertEqual(core["task_linked_postcondition"]["status"], "tests_selected")
        self.assertEqual(core["unit_state"], "verified")
        self.assertEqual(core["repair"]["attempts_used"], 1)


class RepairStopsBlockedTests(unittest.TestCase):
    def test_persistent_failure_stops_at_exactly_the_budget_as_blocked(self) -> None:
        harness = _Harness(self, plan=["broken", "broken", "broken", "broken"], max_repair_attempts=2)

        summary = harness.dispatch()
        core = _unit(summary)

        # The original dispatch plus exactly two repairs.
        self.assertEqual(len(harness.prompts), 3)
        self.assertEqual(harness.plan, ["broken"])
        repair = core["repair"]
        self.assertEqual(repair["attempts_used"], 2)
        self.assertEqual(repair["status"], "blocked")
        self.assertEqual(repair["stop_reason"], REPAIR_BUDGET_EXHAUSTED)
        self.assertEqual(repair["blocked_reason"], REPAIR_BUDGET_EXHAUSTED)
        self.assertEqual(repair["last_failing_check"]["command"], _CHECK)
        self.assertEqual(repair["last_failing_check"]["exit_code"], 1)
        self.assertTrue(repair["last_failing_check"]["observed_at"])
        self.assertEqual([attempt["attempt"] for attempt in repair["attempts"]], [1, 2])
        self.assertEqual(core["unit_state"], "failed")
        self.assertEqual(core["unit_state_reason"], REPAIR_BUDGET_EXHAUSTED)
        self.assertFalse(core["integration_ready"])
        self.assertEqual(
            [event["repair_attempt"] for event in harness.events(REPAIR_ATTEMPT_STARTED_EVENT)], [1, 2]
        )
        self.assertEqual(
            [event["status"] for event in harness.events(REPAIR_ATTEMPT_OBSERVED_EVENT)],
            ["failed", "failed", "blocked"],
        )

    def test_a_batch_with_a_blocked_repair_does_not_exit_zero(self) -> None:
        harness = _Harness(self, plan=["broken", "broken"], max_repair_attempts=1)

        summary = harness.dispatch()

        self.assertNotIn("failure_kind", _unit(summary))
        self.assertEqual(_fanout_dispatch_exit_code(summary), 1)
        line = _fanout_brief_unit_line({"unit_id": "core", "repair": _unit(summary)["repair"]})
        self.assertIn(f"repair 1/1 blocked ({REPAIR_BUDGET_EXHAUSTED})", line)
        self.assertIn(f"`{_CHECK}` exit 1", line)

    def test_show_and_brief_carry_the_attempt_count_and_the_stop_reason(self) -> None:
        harness = _Harness(self, plan=["broken", "broken"], max_repair_attempts=1)
        core = _unit(harness.dispatch())

        shown = _fanout_show_repair(harness.paths, harness.contract["units"][0])["repair"]
        briefed = _brief_repair(core)["repair"]

        for record in (shown, briefed):
            self.assertEqual(record["attempts_used"], 1)
            self.assertEqual(record["max_repair_attempts"], 1)
            self.assertEqual(record["status"], "blocked")
            self.assertEqual(record["stop_reason"], REPAIR_BUDGET_EXHAUSTED)
            self.assertEqual(record["last_failing_check"]["command"], _CHECK)
        self.assertEqual(shown["last_failing_check"], core["repair"]["last_failing_check"])
        # A unit that declared no budget adds nothing to either surface.
        self.assertEqual(_fanout_show_repair(harness.paths, {"unit_id": "x", "run_ref": "r"}), {})
        self.assertEqual(_brief_repair({"unit_id": "x"}), {})

    def test_a_later_dispatch_of_an_exhausted_unit_spawns_nothing_and_still_exits_nonzero(self) -> None:
        harness = _Harness(self, plan=["broken", "broken"], max_repair_attempts=1)
        harness.dispatch()

        summary = harness.dispatch()

        self.assertEqual(len(harness.prompts), 2)
        self.assertEqual(_unit(summary)["status"], "already_completed")
        self.assertEqual(_unit(summary)["repair"]["status"], "blocked")
        self.assertEqual(_fanout_dispatch_exit_code(summary), 1)


class RepairResumeTests(unittest.TestCase):
    def tearDown(self) -> None:
        fanout_dispatch._INTERRUPT_FLAG.clear()

    def test_a_later_dispatch_continues_the_count_and_never_resets_it(self) -> None:
        def interrupt_during_first_repair(spawn: int) -> None:
            if spawn == 2:
                fanout_dispatch._INTERRUPT_FLAG.set()

        harness = _Harness(
            self, plan=["broken", "broken", "fixed"], max_repair_attempts=3, on_spawn=interrupt_during_first_repair
        )
        first = _unit(harness.dispatch())
        self.assertEqual(first["repair"]["state"], "pending")
        self.assertEqual(first["repair"]["attempts_used"], 1)

        second = _unit(harness.dispatch())

        self.assertEqual(len(harness.prompts), 3)
        self.assertEqual(json.loads(harness.prompts[2].partition("\n[Repair attempt]\n")[2])["repair_attempt"], 2)
        self.assertEqual(second["unit_state"], "verified")
        self.assertEqual(second["repair"]["attempts_used"], 2)
        self.assertEqual(second["repair"]["stop_reason"], "checks_passed")
        self.assertNotIn("resume", second)
        self.assertEqual(
            [event["repair_attempt"] for event in harness.events(REPAIR_ATTEMPT_STARTED_EVENT)], [1, 2]
        )

    def test_a_repair_spawn_killed_by_the_interrupt_stays_counted_and_pending(self) -> None:
        harness = _Harness(self, plan=["broken", "fixed"], max_repair_attempts=3)
        original = harness.runner

        def runner(argv, **kwargs):
            if argv[0] == "codex" and len(harness.prompts) == 1:
                # The first repair spawn, terminated by the group signal.
                harness.prompts.append(argv[-1])
                fanout_dispatch._INTERRUPT_FLAG.set()
                return subprocess.CompletedProcess(argv, -15, "", "")
            return original(argv, **kwargs)

        harness.runner = runner  # type: ignore[method-assign]
        first = _unit(harness.dispatch())
        fanout_dispatch._INTERRUPT_FLAG.clear()
        harness.runner = original  # type: ignore[method-assign]

        self.assertEqual(first["repair"]["state"], "pending")
        self.assertEqual(first["repair"]["attempts_used"], 1)
        # No verdict for the killed attempt: its started event keeps it counted.
        self.assertEqual([event["repair_attempt"] for event in harness.events(REPAIR_ATTEMPT_OBSERVED_EVENT)], [0])

        second = _unit(harness.dispatch(resume_journal=harness.resume_journal()))

        self.assertEqual(len(harness.prompts), 3)
        self.assertEqual(json.loads(harness.prompts[2].partition("\n[Repair attempt]\n")[2])["repair_attempt"], 2)
        self.assertEqual(second["unit_state"], "verified")
        self.assertEqual(second["repair"]["attempts_used"], 2)
        # The resume plan held this exit-0 unit; the repair loop, not the plan,
        # decided this run, so no stale resume note is attached.
        self.assertNotIn("resume", second)
        self.assertEqual([event["repair_attempt"] for event in harness.events(REPAIR_ATTEMPT_STARTED_EVENT)], [1, 2])

    def test_a_repair_refused_before_its_spawn_leaves_the_loop_pending(self) -> None:
        harness = _Harness(self, plan=["broken", "fixed"], max_repair_attempts=2)
        calls: list[int] = []

        def ready_once(paths, profile, **kwargs):
            calls.append(1)
            return {"status": "ready" if len(calls) == 1 else "missing", "profile": profile}

        first = _unit(harness.dispatch(readiness=ready_once))

        self.assertEqual(len(harness.prompts), 1)
        self.assertEqual(first["status"], "executor_not_ready")
        self.assertEqual(first["repair"]["state"], "pending")
        self.assertEqual(first["repair"]["attempts_used"], 0)

        second = _unit(harness.dispatch())

        self.assertEqual(second["unit_state"], "verified")
        self.assertEqual(second["repair"]["attempts_used"], 1)

    def test_duplicate_attempt_numbers_are_each_counted(self) -> None:
        checks = [{"command": "c", "exit_code": 1, "failure_kind": "nonzero"}]
        events = [
            {"run_id": "r", "event": REPAIR_ATTEMPT_OBSERVED_EVENT, "status": "failed", "repair_attempt": 0,
             "observed_at": "t0", "repair_checks": checks},
            {"run_id": "r", "event": REPAIR_ATTEMPT_STARTED_EVENT, "repair_attempt": 1, "observed_at": "t1",
             "repair_checks": checks},
            {"run_id": "r", "event": REPAIR_ATTEMPT_STARTED_EVENT, "repair_attempt": 1, "observed_at": "t2",
             "repair_checks": checks},
        ]

        projection = project_unit_repair(events, run_id="r", max_repair_attempts=2)

        self.assertEqual(projection["attempts_used"], 2)
        self.assertEqual(projection["state"], "blocked")
        self.assertEqual(projection["attempts"][0]["check"], {"command": "c", "exit_code": 1, "observed_at": "t0"})


class RepairConcurrencyTests(unittest.TestCase):
    def tearDown(self) -> None:
        fanout_dispatch._INTERRUPT_FLAG.clear()

    def test_a_second_dispatch_skips_a_unit_whose_repair_is_in_flight(self) -> None:
        # A budget of 2, so the in-flight attempt leaves the loop pending to a
        # second reader and only the lock stands between it and a second spawn.
        harness = _Harness(self, plan=["broken", "fixed"], max_repair_attempts=2)
        harness.left_pending(self)
        in_spawn, release = threading.Event(), threading.Event()

        def hold_the_repair(spawn: int) -> None:
            in_spawn.set()
            release.wait(timeout=30)

        harness.on_spawn = hold_the_repair
        outcome: dict[str, Any] = {}
        first = threading.Thread(target=lambda: outcome.update(first=_unit(harness.dispatch())))
        first.start()
        self.assertTrue(in_spawn.wait(timeout=60))
        try:
            summary_path = fanout_dispatch_summary_path(harness.paths, harness.contract["fanout_id"])
            before = _unit(json.loads(summary_path.read_text(encoding="utf-8")))
            second_summary = harness.dispatch()
            after = _unit(json.loads(summary_path.read_text(encoding="utf-8")))
            self.assertEqual(after, before)
            self.assertIn("exit_code", after)
        finally:
            release.set()
            first.join(timeout=120)

        second = _unit(second_summary)
        self.assertEqual(second["status"], REPAIR_IN_FLIGHT_STATUS)
        self.assertEqual(_fanout_dispatch_exit_code(second_summary), 0)
        self.assertEqual(sum("[Repair attempt]" in prompt for prompt in harness.prompts), 1)
        self.assertEqual([event["repair_attempt"] for event in harness.events(REPAIR_ATTEMPT_STARTED_EVENT)], [1])
        self.assertEqual(outcome["first"]["unit_state"], "verified")


    def test_a_loop_settled_before_the_lock_is_taken_is_not_repaired_again(self) -> None:
        # The selection read said pending; by the time this dispatch holds the
        # lock another one has verified the unit. Nothing may spawn.
        harness = _Harness(self, plan=["broken", "fixed"], max_repair_attempts=2)
        harness.dispatch()
        unit = harness.contract["units"][0]
        stale = {"attempts_used": 0, "failing_checks": [{"command": _CHECK, "exit_code": 1, "failure_kind": "nonzero"}]}

        entry = fanout_dispatch._dispatch_unit_until_repaired(
            harness.paths, unit, resume=stale, dry_run=False, run_verification=True
        )

        self.assertEqual(entry["status"], "already_completed")
        self.assertEqual(entry["repair"]["status"], "passed")
        self.assertEqual(len(harness.prompts), 2)


class RepairWorktreeMissingTests(unittest.TestCase):
    def tearDown(self) -> None:
        fanout_dispatch._INTERRUPT_FLAG.clear()

    def test_a_vanished_worktree_blocks_the_loop_and_exits_nonzero_without_spawning(self) -> None:
        harness = _Harness(self, plan=["broken"], max_repair_attempts=2)
        harness.left_pending(self)
        subprocess.run(
            ["git", "worktree", "remove", "--force", harness.spawn_worktrees[0]],
            cwd=str(harness.repo), check=True, capture_output=True,
        )

        for _ in range(2):
            summary = harness.dispatch()
            core = _unit(summary)
            self.assertEqual(len(harness.prompts), 1)
            self.assertEqual(core["repair"]["status"], "blocked")
            self.assertEqual(core["repair"]["blocked_reason"], REPAIR_WORKTREE_MISSING)
            self.assertEqual(core["repair"]["last_failing_check"]["command"], _CHECK)
            self.assertEqual(core["unit_state_reason"], REPAIR_WORKTREE_MISSING)
            self.assertEqual(_fanout_dispatch_exit_code(summary), 1)
        self.assertEqual(harness.events(REPAIR_ATTEMPT_STARTED_EVENT), [])


class RepairExitScopeTests(unittest.TestCase):
    def test_an_unselected_units_blocked_history_does_not_set_the_exit_code(self) -> None:
        units = [
            {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["pkg/"],
             "verification_commands": [_CHECK], "max_repair_attempts": 1},
            {"unit_id": "docs", "title": "Docs", "owner": "codex", "file_scope": ["docs/"],
             "verification_commands": [_PASSING]},
        ]
        harness = _Harness(self, plan=["broken", "broken"], units=units)
        self.assertEqual(_fanout_dispatch_exit_code(harness.dispatch()), 1)

        summary = harness.dispatch(only_units=["docs"])

        core = _unit(summary)
        # Skipped as completed (exit 0), and outside this dispatch's selection.
        self.assertEqual(core["status"], "already_completed")
        # Still reported, so show/brief see it; not this batch's failure.
        self.assertEqual(core["repair"]["status"], "blocked")
        self.assertNotIn("unit_state_reason", core)
        self.assertEqual(_fanout_dispatch_exit_code(summary), 0)


class RepairPairingTests(unittest.TestCase):
    def test_duplicate_commands_consume_distinct_captures_in_order(self) -> None:
        result = {
            "status": "completed", "process_succeeded": True, "result_schema_valid": True,
            "verification_status": "failed",
            "verification_observed_failures": [
                observed_check_failure(_CHECK, "nonzero", 1, "process"),
                observed_check_failure(_CHECK, "nonzero", 7, "process"),
            ],
            "verification_checks": [
                {"command": _CHECK, "status": "failed", "observed_by": "dispatcher"},
                {"command": _CHECK, "status": "failed", "observed_by": "dispatcher"},
            ],
        }
        self.assertEqual(repair_trigger_checks(result), [
            {"command": _CHECK, "exit_code": 1, "failure_kind": "nonzero"},
            {"command": _CHECK, "exit_code": 7, "failure_kind": "nonzero"},
        ])
        result["verification_observed_failures"].pop()
        self.assertEqual(repair_trigger_checks(result), [])

    def test_a_task_linked_command_longer_than_the_journal_bound_still_triggers(self) -> None:
        command = "python -m unittest " + " ".join(f"tests/test_module_number_{i:03d}.py" for i in range(20))
        self.assertGreater(len(command), 512)
        result = {
            "status": "completed", "process_succeeded": True, "result_schema_valid": True,
            "verification_status": "failed",
            "verification_observed_failures": [observed_check_failure(command, "nonzero", 1, "process")],
            "verification_checks": [{"command": command, "status": "failed", "observed_by": "dispatcher"}],
        }

        failing = repair_trigger_checks(result)

        self.assertEqual(failing, [{"command": command, "exit_code": 1, "failure_kind": "nonzero"}])
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            append_journal_observation(paths, {
                "target_type": "run", "target_id": "r", "run_id": "r", "event": REPAIR_ATTEMPT_OBSERVED_EVENT,
                "status": "failed", "summary": "s", "repair_attempt": 0, "repair_checks": journal_repair_checks(failing),
            })
            projection = project_unit_repair(read_observation_events(paths, run_id="r"), run_id="r", max_repair_attempts=1)
        self.assertEqual(projection["state"], "pending")
        self.assertEqual(projection["failing_checks"][0]["command"], command[:512])

    def test_a_dependency_skipped_planned_check_does_not_block_the_repair(self) -> None:
        units = [{
            "unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["pkg/"],
            "verification_checks": [
                {"id": "value", "command": _CHECK},
                {"id": "after", "command": _PASSING, "depends_on": ["value"]},
            ],
            "max_repair_attempts": 2,
        }]
        harness = _Harness(self, plan=["broken", "fixed"], units=units)

        core = _unit(harness.dispatch())

        self.assertEqual(len(harness.prompts), 2)
        self.assertEqual(core["unit_state"], "verified")
        self.assertEqual(core["repair"]["attempts_used"], 1)

    def test_a_repair_dispatch_never_reads_a_parent_clarification(self) -> None:
        harness = _Harness(self, plan=["broken", "fixed"], max_repair_attempts=2)
        calls: list[object] = []
        original = fanout_dispatch.read_clarification

        def counting(path):
            calls.append(path)
            return original(path)

        with mock.patch.object(fanout_dispatch, "read_clarification", counting):
            core = _unit(harness.dispatch())

        self.assertEqual(core["unit_state"], "verified")
        self.assertEqual(len(harness.prompts), 2)
        self.assertEqual(len(calls), 1)


class RepairJournalFieldTests(unittest.TestCase):
    def _append(self, **fields: object) -> dict[str, Any]:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        paths = OmhPaths(omh_home=Path(tmp.name) / ".omh", hermes_home=Path(tmp.name) / ".hermes")
        event = {"target_type": "run", "target_id": "r", "run_id": "r", "event": REPAIR_ATTEMPT_OBSERVED_EVENT,
                 "status": "failed", "summary": "s", "repair_attempt": 1,
                 "repair_checks": [{"command": "c", "exit_code": 1, "failure_kind": "nonzero"}], **fields}
        return append_journal_observation(paths, event)

    def test_valid_repair_fields_round_trip(self) -> None:
        record = self._append(status="blocked", repair_stop_reason=REPAIR_WORKTREE_MISSING)

        self.assertEqual(record["repair_attempt"], 1)
        self.assertEqual(record["repair_checks"][0]["command"], "c")
        self.assertEqual(record["repair_stop_reason"], REPAIR_WORKTREE_MISSING)

    def test_malformed_repair_fields_are_refused(self) -> None:
        for label, fields in (
            ("attempt above the ceiling", {"repair_attempt": 99}),
            ("attempt missing", {"repair_attempt": None}),
            ("unknown failure kind", {"repair_checks": [{"command": "c", "exit_code": 1, "failure_kind": "oops"}]}),
            ("command over the bound", {"repair_checks": [{"command": "c" * 513, "exit_code": 1, "failure_kind": "nonzero"}]}),
            ("unknown stop reason", {"repair_stop_reason": "tired"}),
        ):
            with self.subTest(label), self.assertRaises(ValueError):
                self._append(**fields)


class RepairTriggerNegativeTests(unittest.TestCase):
    def test_a_contract_without_the_field_freezes_byte_identically_to_before_the_field(self) -> None:
        # Frozen by origin/main 02442af92, before this field existed, with the
        # same units; `safety_profile_revision` tracks the live safety profile
        # and is left out on both sides.
        fixture = Path(__file__).with_name("fixtures") / "fanout_contract_without_repair_budget.json"
        units = [
            {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["pkg/"],
             "verification_commands": ["python -c pass"]},
            {"unit_id": "b", "title": "B", "owner": "claude-code", "file_scope": ["b/"], "depends_on": ["core"],
             "verification_checks": [{"id": "x", "command": "python -c pass", "tier": "unit"}],
             "task_linked_test_runner": "python -m unittest"},
        ]
        for label, frozen_units in (
            ("undeclared", units),
            ("declared zero", [{**unit, "max_repair_attempts": 0} for unit in units]),
        ):
            with self.subTest(label):
                contract = build_fanout_contract("goal text", frozen_units)
                contract.pop("safety_profile_revision", None)
                self.assertEqual(
                    json.dumps(contract, sort_keys=True, indent=1) + "\n", fixture.read_text(encoding="utf-8")
                )

    def test_a_unit_without_a_budget_is_never_repaired(self) -> None:

        harness = _Harness(self, plan=["broken", "fixed"], max_repair_attempts=None)
        summary = harness.dispatch()
        core = _unit(summary)

        self.assertEqual(len(harness.prompts), 1)
        self.assertEqual(core["unit_state_reason"], "verification_failed")
        self.assertNotIn("repair", core)
        self.assertNotIn("verification_observed_failures", core)
        self.assertEqual(harness.events(REPAIR_ATTEMPT_STARTED_EVENT), [])
        self.assertEqual(harness.events(REPAIR_ATTEMPT_OBSERVED_EVENT), [])
        # Observed failing verification is failed work whether or not a budget
        # was declared: the batch must not exit 0 (#1929 closed this gap).
        self.assertNotIn("failure_kind", core)
        self.assertEqual(_fanout_dispatch_exit_code(summary), 1)

    def test_a_passing_batch_without_a_budget_exits_zero(self) -> None:
        harness = _Harness(self, plan=["fixed"], max_repair_attempts=None)

        summary = harness.dispatch()

        self.assertEqual(_unit(summary)["unit_state"], "verified")
        self.assertEqual(_fanout_dispatch_exit_code(summary), 0)

    def test_a_verification_that_was_never_observed_is_not_mapped_as_failed(self) -> None:
        # Every unit of a dispatch run without --run-verification reads this
        # way; nothing ran and failed, so it stays outside the failure signal.
        summary = {"units": [{"unit_id": "a", "unit_state_reason": "verification_not_observed"}]}

        self.assertEqual(_fanout_dispatch_exit_code(summary), 0)

    def test_a_reproduction_units_expected_failure_is_not_repaired(self) -> None:
        repro_command = f"{shlex.quote(sys.executable)} -c \"raise SystemExit(1)\""
        units = [
            {"unit_id": "repro", "title": "Reproduce", "owner": "codex", "file_scope": ["tests/"],
             "kind": "reproduction", "reproduction_command": repro_command,
             "verification_commands": [_PASSING], "max_repair_attempts": 2},
            {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["pkg/"],
             "depends_on": ["repro"], "verification_commands": [_PASSING]},
        ]
        harness = _Harness(self, plan=["fixed"], units=units)

        repro = _unit(harness.dispatch(), "repro")

        self.assertEqual(repro["reproduction"]["status"], "failure_reproduced")
        self.assertEqual(repro["unit_state"], "verified")
        self.assertEqual(repro["repair"]["attempts_used"], 0)
        self.assertEqual(repro["repair"]["stop_reason"], "checks_passed")
        self.assertEqual(harness.events(REPAIR_ATTEMPT_STARTED_EVENT, "repro"), [])
        # One spawn for each unit, none of them a repair.
        self.assertEqual(len(harness.prompts), 2)
        self.assertFalse(any("[Repair attempt]" in prompt for prompt in harness.prompts))

    def test_an_executor_self_reported_pass_does_not_stop_the_loop(self) -> None:
        harness = _Harness(self, plan=["broken", "broken", "broken"], max_repair_attempts=2, self_report_pass=True)

        core = _unit(harness.dispatch())

        self.assertEqual(len(harness.prompts), 3)
        self.assertEqual(core["repair"]["status"], "blocked")

    def test_a_check_that_timed_out_is_not_an_observed_failure_and_is_not_repaired(self) -> None:
        harness = _Harness(self, plan=["broken", "fixed"], max_repair_attempts=2, timeout_checks=True)

        core = _unit(harness.dispatch())

        self.assertEqual(len(harness.prompts), 1)
        self.assertEqual(core["verification_observed_failures"][0]["failure_kind"], "deadline")
        self.assertEqual(core["repair"]["stop_reason"], "not_repairable")
        self.assertEqual(core["unit_state_reason"], "verification_failed")

    def test_a_dry_run_and_an_unverified_run_never_repair(self) -> None:
        harness = _Harness(self, plan=["broken", "fixed"])

        dry = dispatch_fanout(
            harness.paths, harness.contract, goal_text=_GOAL, repo_root=harness.repo, base_sha=harness.base,
            runner=harness.runner, readiness=_ready, run_verification=True, dry_run=True,
        )
        unverified = dispatch_fanout(
            harness.paths, harness.contract, goal_text=_GOAL, repo_root=harness.repo, base_sha=harness.base,
            runner=harness.runner, readiness=_ready,
        )

        self.assertNotIn("repair", _unit(dry))
        self.assertNotIn("repair", _unit(unverified))
        self.assertEqual(len(harness.prompts), 1)

    def test_the_trigger_reads_dispatcher_rows_only(self) -> None:
        failing = {"command": "c", "exit_code": 1, "failure_kind": "nonzero", "exit_code_source": "process"}
        base = {
            "status": "completed", "process_succeeded": True, "result_schema_valid": True,
            "verification_status": "failed", "verification_observed_failures": [failing],
            "verification_checks": [{"command": "c", "status": "failed", "observed_by": "dispatcher"}],
        }
        self.assertEqual(repair_trigger_checks(base), [{"command": "c", "exit_code": 1, "failure_kind": "nonzero"}])
        for label, override in (
            ("process failed", {"status": "failed"}),
            ("result invalid", {"result_schema_valid": False}),
            ("verification passed", {"verification_status": "passed"}),
            ("row not dispatcher-observed", {"verification_checks": [{"command": "c", "status": "failed", "observed_by": None}]}),
            ("failure not captured", {"verification_observed_failures": []}),
            ("exit not observed from a process", {"verification_observed_failures": [{**failing, "exit_code_source": "not_observed"}]}),
            ("a timed-out check", {"verification_observed_failures": [{**failing, "failure_kind": "deadline"}]}),
        ):
            with self.subTest(label):
                self.assertEqual(repair_trigger_checks({**base, **override}), [])


class RepairContractTests(unittest.TestCase):
    def _unit(self, **extra: object) -> dict[str, object]:
        return {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["pkg/"], **extra}

    def test_a_declared_budget_rides_the_frozen_unit(self) -> None:
        contract = build_fanout_contract(_GOAL, [self._unit(verification_commands=[_PASSING], max_repair_attempts=2)])

        self.assertEqual(contract["units"][0]["max_repair_attempts"], 2)

    def test_unusable_budgets_are_refused_at_freeze(self) -> None:
        for bad in (-1, MAX_REPAIR_ATTEMPTS + 1, True, "2", 1.5):
            with self.subTest(bad=bad), self.assertRaises(FanoutContractError):
                build_fanout_contract(_GOAL, [self._unit(verification_commands=[_PASSING], max_repair_attempts=bad)])

    def test_a_budget_without_a_runnable_check_is_refused(self) -> None:
        with self.assertRaises(FanoutContractError):
            build_fanout_contract(_GOAL, [self._unit(max_repair_attempts=1)])


if __name__ == "__main__":
    unittest.main()
