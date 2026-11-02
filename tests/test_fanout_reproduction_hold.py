"""The reproduction hold: edit units wait behind an observed failing check (#1699).

A split is debugging-shaped only when it declares a `reproduction` unit kind;
the request text is never read. Pinned here: the hold opens only on a
dispatcher-observed nonzero exit of the declared command; a dry-run plan, an
unrequested run, a command that could not start, and a command that exited 0
all keep it closed; a completed reproduction releases a later dispatch only
through its journaled verdict; and a split with no reproduction unit freezes
and dispatches exactly as before.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from _verification_python import verification_python  # noqa: E402

from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_admission import reproduction_hold_released  # noqa: E402
from omh.coding.fanout_artifacts import write_fanout_contract  # noqa: E402
from omh.coding.fanout_contracts import (  # noqa: E402
    FANOUT_REPRODUCTION_SCHEMA_VERSION,
    REPRODUCTION_OBSERVED_EVENT,
    FanoutContractError,
)
from omh.coding.fanout_dispatch import dispatch_fanout  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402
from omh.workflows.observation_journal import read_observation_events  # noqa: E402

_GOAL = "fix the value regression"
_REPRO_SCRIPT = "tests/repro_value.py"
_REPRO_COMMAND = f"{verification_python()} {_REPRO_SCRIPT}"
_FAILING_REPRO = "raise SystemExit(1)\n"
_PASSING_REPRO = "raise SystemExit(0)\n"


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
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _ready(paths: OmhPaths, profile: str, **kwargs: object) -> dict[str, object]:
    return {"status": "ready", "profile": profile}


def _sidecar(argv: list[str]) -> Path:
    match = re.search(r"JSON sidecar to exactly (.+)\.", " ".join(argv))
    if match is None:
        raise AssertionError("missing invocation sidecar path")
    return Path(match[1])


def _units(*, kind: str | None = "reproduction", command: str = _REPRO_COMMAND) -> list[dict[str, object]]:
    repro: dict[str, object] = {
        "unit_id": "repro", "title": "Reproduce", "owner": "codex", "file_scope": ["tests/"],
    }
    if kind is not None:
        repro["kind"] = kind
        repro["reproduction_command"] = command
    fix = {
        "unit_id": "fix", "title": "Fix", "owner": "codex", "file_scope": ["pkg/"], "depends_on": ["repro"],
    }
    return [repro, fix]


class _Harness:
    """A fake executor writes and commits; git and the declared command really run."""

    def __init__(self, test: unittest.TestCase, *, repro_text: str = _FAILING_REPRO,
                 units: list[dict[str, object]] | None = None) -> None:
        tmp = TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        self.repo = root / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        _write(self.repo, "pkg/__init__.py", "")
        _write(self.repo, "pkg/mod.py", "VALUE = 2\n")
        _write(self.repo, "README.md", "sample\n")
        self.base = _commit_all(self.repo, "init")
        self.contract = write_fanout_contract(
            self.paths, build_fanout_contract(_GOAL, units if units is not None else _units())
        )
        self.run_refs = {str(unit["unit_id"]): str(unit["run_ref"]) for unit in self.contract["units"]}
        self.repro_text = repro_text
        # Every executor spawn and every non-git command, in the order they ran.
        self.calls: list[str] = []

    def runner(self, argv, **kwargs):
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        cwd = Path(str(kwargs.get("cwd")))
        if argv[0] == "codex":
            unit_id = cwd.name.rsplit("-fanout-", 1)[1]
            self.calls.append(f"spawn:{unit_id}")
            if unit_id == "repro":
                _write(cwd, _REPRO_SCRIPT, self.repro_text)
            else:
                _write(cwd, "pkg/mod.py", "VALUE = 1\n")
            head = _commit_all(cwd, f"{unit_id} work")
            payload = {
                "schema_version": "fanout_unit_result/v1",
                "unit_id": unit_id,
                "run_id": self.run_refs[unit_id],
                "fanout_id": self.contract["fanout_id"],
                "base_sha": self.base,
                "head_sha": head,
                "process_status": "process_succeeded",
                "changed_paths": [_REPRO_SCRIPT] if unit_id == "repro" else ["pkg/mod.py"],
                "checks": [],
                "findings": [],
            }
            sidecar = _sidecar(argv)
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "done", "")
        self.calls.append(f"command:{cwd.name.rsplit('-fanout-', 1)[1]}")
        return subprocess.run(
            argv, cwd=kwargs.get("cwd"), env=kwargs.get("env"), text=True,
            capture_output=True, timeout=kwargs.get("timeout"),
        )

    def dispatch(self, **kwargs: object) -> dict[str, dict[str, object]]:
        summary = dispatch_fanout(
            self.paths,
            self.contract,
            goal_text=_GOAL,
            repo_root=self.repo,
            base_sha=self.base,
            runner=self.runner,
            readiness=_ready,
            **kwargs,
        )
        return {str(entry["unit_id"]): entry for entry in summary["units"]}

    def reproduction_events(self) -> list[dict[str, object]]:
        return [
            event
            for event in read_observation_events(self.paths, run_id=self.run_refs["repro"], limit=None)
            if event.get("event") == REPRODUCTION_OBSERVED_EVENT
        ]


class HoldReleaseTests(unittest.TestCase):
    def test_an_observed_failing_reproduction_releases_the_edit_unit(self) -> None:
        harness = _Harness(self)

        units = harness.dispatch(run_verification=True)

        receipt = units["repro"]["reproduction"]
        self.assertEqual(receipt["schema_version"], FANOUT_REPRODUCTION_SCHEMA_VERSION)
        self.assertEqual(receipt["status"], "failure_reproduced")
        self.assertEqual(receipt["observed_by"], "dispatcher")
        self.assertEqual(receipt["exit_code"], 1)
        self.assertEqual(receipt["command"], _REPRO_COMMAND)
        # The edit unit spawned only after the dispatcher ran the command.
        self.assertEqual(harness.calls, ["spawn:repro", "command:repro", "spawn:fix"])
        self.assertEqual(units["fix"]["status"], "completed")
        self.assertEqual([event["status"] for event in harness.reproduction_events()], ["observed"])

    def test_a_reproduced_failure_does_not_fail_the_reproduction_unit(self) -> None:
        # The nonzero exit is the unit's success; it never rides the check
        # rows whose failure would move the ladder to failed.
        harness = _Harness(self)

        repro = harness.dispatch(run_verification=True)["repro"]

        self.assertEqual(repro["status"], "completed")
        self.assertNotEqual(repro.get("unit_state_reason"), "verification_failed")
        self.assertNotIn("verification_failures", repro)


class HoldStaysClosedTests(unittest.TestCase):
    def _assert_held(self, units: dict[str, dict[str, object]]) -> None:
        self.assertEqual(units["fix"]["status"], "blocked_by_dependency")
        self.assertEqual(units["fix"]["blocked_on"], ["repro"])
        self.assertEqual(units["fix"]["blocked_reasons"], {"repro": "reproduction_not_observed"})

    def test_a_prepared_not_observed_dry_run_reproduction_does_not_release(self) -> None:
        harness = _Harness(self)

        units = harness.dispatch(dry_run=True, run_verification=True)

        self.assertEqual(units["repro"]["status"], "dry_run_planned")
        self.assertEqual(units["repro"]["reproduction"]["status"], "not_observed")
        self.assertIsNone(units["repro"]["reproduction"]["observed_by"])
        self._assert_held(units)
        self.assertEqual(harness.calls, [])

    def test_a_reproduction_nobody_asked_to_run_does_not_release(self) -> None:
        harness = _Harness(self)

        units = harness.dispatch()

        self.assertEqual(units["repro"]["status"], "completed")
        self.assertEqual(units["repro"]["reproduction"]["status"], "not_observed")
        self.assertEqual(units["repro"]["reproduction"]["reason"], "verification_not_requested")
        self._assert_held(units)
        self.assertEqual(harness.calls, ["spawn:repro"])
        self.assertEqual(harness.reproduction_events(), [])

    def test_an_observed_passing_reproduction_does_not_release(self) -> None:
        # No failure reproduced: the fix would be verified against nothing. The
        # edit unit is held and named, and the next step is the operator's.
        harness = _Harness(self, repro_text=_PASSING_REPRO)

        units = harness.dispatch(run_verification=True)

        receipt = units["repro"]["reproduction"]
        self.assertEqual(receipt["status"], "not_reproduced")
        self.assertEqual(receipt["observed_by"], "dispatcher")
        self.assertEqual(receipt["exit_code"], 0)
        self._assert_held(units)
        self.assertEqual(harness.calls, ["spawn:repro", "command:repro"])
        self.assertEqual([event["status"] for event in harness.reproduction_events()], ["not_observed"])

    def test_a_command_that_could_not_start_is_not_a_reproduction(self) -> None:
        # Nonzero-looking, but no process exit code was observed.
        harness = _Harness(self, units=_units(command="omh-no-such-reproduction-binary --run"))

        units = harness.dispatch(run_verification=True)

        receipt = units["repro"]["reproduction"]
        self.assertEqual(receipt["status"], "not_observed")
        self.assertIsNone(receipt["exit_code"])
        self.assertEqual(receipt["reason"], "command_missing_binary")
        self._assert_held(units)
        self.assertEqual(harness.reproduction_events(), [])


class ResumeTests(unittest.TestCase):
    def test_a_journaled_failure_releases_a_later_dispatch_without_rerunning(self) -> None:
        harness = _Harness(self)
        harness.dispatch(run_verification=True, only_units=["repro"])
        harness.calls.clear()

        units = harness.dispatch(run_verification=True, only_units=["fix"])

        self.assertEqual(units["repro"]["status"], "already_completed")
        self.assertEqual(units["repro"]["reproduction"]["status"], "failure_reproduced")
        self.assertEqual(harness.calls, ["spawn:fix"])
        self.assertEqual(units["fix"]["status"], "completed")

    def test_a_completed_reproduction_without_a_journaled_failure_still_holds(self) -> None:
        harness = _Harness(self)
        harness.dispatch(only_units=["repro"])
        harness.calls.clear()

        units = harness.dispatch(run_verification=True, only_units=["fix"])

        self.assertEqual(units["repro"]["status"], "already_completed")
        self.assertEqual(units["repro"]["reproduction"]["status"], "not_observed")
        self.assertEqual(units["fix"]["blocked_reasons"], {"repro": "reproduction_not_observed"})
        self.assertEqual(harness.calls, [])

    def test_the_latest_journaled_verdict_decides(self) -> None:
        harness = _Harness(self)
        harness.dispatch(run_verification=True, only_units=["repro"])
        from omh.runtime.artifacts import append_journal_observation

        append_journal_observation(harness.paths, {
            "target_type": "run", "target_id": harness.run_refs["repro"], "run_id": harness.run_refs["repro"],
            "event": REPRODUCTION_OBSERVED_EVENT, "status": "not_observed",
            "summary": "a later attempt did not reproduce", "worker_ref": "repro",
        })
        harness.calls.clear()

        units = harness.dispatch(run_verification=True, only_units=["fix"])

        self.assertEqual(units["repro"]["reproduction"]["status"], "not_reproduced")
        self.assertEqual(units["fix"]["blocked_reasons"], {"repro": "reproduction_not_observed"})
        self.assertEqual(harness.calls, [])


class NonDebuggingContractTests(unittest.TestCase):
    """The negative case: no reproduction unit, no hold, no new keys."""

    def test_a_split_without_a_reproduction_unit_admits_as_before(self) -> None:
        harness = _Harness(self, units=_units(kind=None))

        units = harness.dispatch()

        self.assertEqual(harness.calls, ["spawn:repro", "spawn:fix"])
        self.assertEqual(units["fix"]["status"], "completed")
        self.assertNotIn("reproduction", units["repro"])
        self.assertNotIn("reproduction", units["fix"])

    def test_a_split_without_a_reproduction_unit_freezes_byte_identically(self) -> None:
        contract = build_fanout_contract(_GOAL, _units(kind=None))

        for unit in contract["units"]:
            self.assertNotIn("kind", unit)
            self.assertNotIn("reproduction_command", unit)
        self.assertEqual(
            contract["units"][0]["integration_checks"],
            ["unit tests covering the unit's file_scope pass", "no edits outside boundary.file_scope"],
        )


class FreezeTests(unittest.TestCase):
    def test_a_reproduction_unit_freezes_its_kind_command_and_inverse_criterion(self) -> None:
        repro = build_fanout_contract(_GOAL, _units())["units"][0]

        self.assertEqual(repro["kind"], "reproduction")
        self.assertEqual(repro["reproduction_command"], _REPRO_COMMAND)
        self.assertIn("exits nonzero", repro["integration_checks"][0])

    def test_an_edit_unit_with_no_path_to_the_reproduction_is_refused(self) -> None:
        units = _units()
        units[1]["depends_on"] = []

        with self.assertRaisesRegex(FanoutContractError, "must depend on a reproduction unit"):
            build_fanout_contract(_GOAL, units)

    def test_a_transitive_path_to_the_reproduction_is_accepted(self) -> None:
        units = _units()
        units.append({"unit_id": "docs", "owner": "codex", "file_scope": ["docs/"], "depends_on": ["fix"]})

        contract = build_fanout_contract(_GOAL, units)

        self.assertEqual(contract["merge_plan"]["merge_order"], ["repro", "fix", "docs"])

    def test_unusable_declarations_are_refused(self) -> None:
        cases = {
            "unknown kind": _units(kind="debugging"),
            "missing command": _units(command="   "),
            "unparseable command": _units(command="python 'unterminated"),
        }
        stray = _units(kind=None)
        stray[1]["reproduction_command"] = _REPRO_COMMAND
        cases["command without kind"] = stray
        for label, units in cases.items():
            with self.subTest(label), self.assertRaises(FanoutContractError):
                build_fanout_contract(_GOAL, units)


class ReleasePredicateTests(unittest.TestCase):
    _REPRO_UNIT = {"unit_id": "repro", "kind": "reproduction"}

    def _result(self, status: str, observed_by: str | None) -> dict[str, object]:
        return {"status": "completed", "reproduction": {"status": status, "observed_by": observed_by}}

    def test_only_a_dispatcher_observed_reproduced_failure_releases(self) -> None:
        self.assertTrue(reproduction_hold_released(self._REPRO_UNIT, self._result("failure_reproduced", "dispatcher")))
        for status, observed_by in (
            ("failure_reproduced", None),
            ("failure_reproduced", "executor"),
            ("not_reproduced", "dispatcher"),
            ("not_observed", None),
        ):
            with self.subTest(status=status, observed_by=observed_by):
                self.assertFalse(reproduction_hold_released(self._REPRO_UNIT, self._result(status, observed_by)))
        self.assertFalse(reproduction_hold_released(self._REPRO_UNIT, {"status": "completed"}))
        self.assertFalse(reproduction_hold_released(self._REPRO_UNIT, None))

    def test_an_ordinary_unit_never_holds(self) -> None:
        self.assertTrue(reproduction_hold_released({"unit_id": "fix"}, {"status": "completed"}))


if __name__ == "__main__":
    unittest.main()
