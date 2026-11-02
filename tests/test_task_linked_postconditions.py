"""Task-linked postconditions: "done" includes the tests the unit's changes reach.

The contract half (freeze, criteria), the pure resolver, and the dispatcher
half (observed diff -> selected tests -> exit status on the ladder) are pinned
here, with negative cases so the contract does not over-block: a change no
test imports, and a unit that declares no runner at all.
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

from omh.codegraph import build_codegraph  # noqa: E402
from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import write_fanout_contract  # noqa: E402
from omh.coding.fanout_contracts import FanoutContractError  # noqa: E402
from omh.coding.fanout_dispatch import _unit_verification_is_observed, dispatch_fanout  # noqa: E402
from omh.coding.postconditions import (  # noqa: E402
    MAX_TASK_LINKED_TEST_RUNNER_CHARS,
    TASK_LINKED_POSTCONDITION_SCHEMA_VERSION,
    normalized_task_linked_test_runner,
    resolve_task_linked_postcondition,
)
from omh.coding.unit_prompt_protocol import completion_criteria_for_unit  # noqa: E402
from omh.runtime.artifacts import append_journal_observation  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402

_GOAL = "change the sample module"
_RUNNER = f"{verification_python()} -m unittest"
_PASSING_COMMAND = f"{verification_python()} -c pass"

_MODULE = "def value():\n    return 1\n"
_BROKEN_MODULE = "def value():\n    return 2\n"
_DIRECT_TEST = (
    "import unittest\n"
    "from pkg.mod import value\n\n\n"
    "class ValueTests(unittest.TestCase):\n"
    "    def test_value(self):\n"
    "        self.assertEqual(value(), 1)\n"
)
# Reaches pkg/mod.py only through pkg/helper.py: distance 2, outside the rule.
_INDIRECT_TEST = (
    "import unittest\n"
    "from pkg import helper\n\n\n"
    "class IndirectTests(unittest.TestCase):\n"
    "    def test_fails_whenever_run(self):\n"
    "        self.fail('an indirect importer must not be selected')\n"
)


def _write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def _seed_tree(root: Path) -> None:
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/mod.py", _MODULE)
    _write(root, "pkg/helper.py", "from pkg.mod import value\n")
    _write(root, "pkg/lonely.py", "x = 1\n")
    _write(root, "tests/test_mod.py", _DIRECT_TEST)
    _write(root, "tests/test_indirect.py", _INDIRECT_TEST)
    _write(root, "README.md", "sample\n")


def _git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", *argv], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


class ResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory()))
        _seed_tree(self.root)
        self.graph = build_codegraph(self.root)

    def test_a_changed_module_selects_its_direct_importers_only(self) -> None:
        record = resolve_task_linked_postcondition(self.graph, ["pkg/mod.py"], "python -m unittest")

        self.assertEqual(record["schema_version"], TASK_LINKED_POSTCONDITION_SCHEMA_VERSION)
        self.assertEqual(record["status"], "tests_selected")
        # test_indirect reaches pkg/mod.py only through pkg/helper.py.
        self.assertEqual(record["selected_test_paths"], ["tests/test_mod.py"])
        self.assertEqual(record["command"], "python -m unittest tests/test_mod.py")

    def test_a_changed_test_module_is_selected_itself(self) -> None:
        record = resolve_task_linked_postcondition(self.graph, ["tests/test_indirect.py"], "python -m unittest")

        self.assertEqual(record["selected_test_paths"], ["tests/test_indirect.py"])

    def test_a_change_no_test_imports_adds_no_command(self) -> None:
        record = resolve_task_linked_postcondition(
            self.graph, ["pkg/lonely.py", "README.md"], "python -m unittest"
        )

        self.assertEqual(record["status"], "no_reachable_tests")
        self.assertEqual(record["selected_test_paths"], [])
        self.assertEqual(record["command"], "")

    def test_an_empty_change_set_adds_no_command(self) -> None:
        record = resolve_task_linked_postcondition(self.graph, [], "python -m unittest")

        self.assertEqual(record["status"], "no_reachable_tests")
        self.assertEqual(record["command"], "")

    def test_excluded_tests_are_recorded_and_left_out_of_the_command(self) -> None:
        record = resolve_task_linked_postcondition(
            self.graph,
            ["pkg/mod.py", "tests/test_indirect.py"],
            "python -m unittest",
            exclude_test_paths=["tests/test_mod.py"],
        )

        self.assertEqual(record["selected_test_paths"], ["tests/test_indirect.py"])
        self.assertEqual(record["excluded_test_paths"], ["tests/test_mod.py"])
        self.assertNotIn("tests/test_mod.py", record["command"])


class RunnerDeclarationTests(unittest.TestCase):
    def test_absent_runner_normalizes_to_empty(self) -> None:
        self.assertEqual(normalized_task_linked_test_runner(None, 0), "")

    def test_runner_whitespace_is_collapsed(self) -> None:
        self.assertEqual(
            normalized_task_linked_test_runner("PYTHONPATH=tests  python -m   unittest", 0),
            "PYTHONPATH=tests python -m unittest",
        )

    def test_unusable_runners_are_refused_at_freeze(self) -> None:
        for bad in ("", "   ", 3, "PYTHONPATH=tests", "python 'unterminated", "x" * (MAX_TASK_LINKED_TEST_RUNNER_CHARS + 1)):
            with self.subTest(bad=bad), self.assertRaises(FanoutContractError):
                normalized_task_linked_test_runner(bad, 0)


class ContractTests(unittest.TestCase):
    def _unit(self, **extra: object) -> dict[str, object]:
        return {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["pkg/"], **extra}

    def test_a_declared_runner_rides_the_frozen_unit_and_becomes_a_criterion(self) -> None:
        contract = build_fanout_contract(_GOAL, [self._unit(task_linked_test_runner="python -m unittest")])
        unit = contract["units"][0]

        self.assertEqual(unit["task_linked_test_runner"], "python -m unittest")
        self.assertNotIn("unit tests covering the unit's file_scope pass", unit["integration_checks"])
        criteria = completion_criteria_for_unit(unit)
        self.assertTrue(any("`python -m unittest <test files>` passes" in item for item in criteria))

    def test_an_undeclared_runner_leaves_the_contract_unit_unchanged(self) -> None:
        contract = build_fanout_contract(_GOAL, [self._unit()])
        unit = contract["units"][0]

        self.assertNotIn("task_linked_test_runner", unit)
        self.assertEqual(
            unit["integration_checks"],
            ["unit tests covering the unit's file_scope pass", "no edits outside boundary.file_scope"],
        )


def _ready(paths: OmhPaths, profile: str, **kwargs: object) -> dict[str, object]:
    return {"status": "ready", "profile": profile}


def _prompted_sidecar(argv: list[str]) -> Path:
    match = re.search(r"JSON sidecar to exactly (.+)\.", " ".join(argv))
    if match is None:
        raise AssertionError("missing invocation sidecar path")
    return Path(match[1])


class DispatcherTests(unittest.TestCase):
    """A fake executor edits and commits; git and the checks really run."""

    def _dispatch(
        self, *, edits: dict[str, str], break_diff: bool = False, stale_pass: bool = False, **unit_extra: object
    ):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo = root / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _seed_tree(repo)
        base = _commit_all(repo, "init")
        unit = {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["pkg/"], **unit_extra}
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, [unit]))
        frozen = contract["units"][0]
        checks_run: list[list[str]] = []
        if stale_pass:
            # What an earlier attempt of the same run would have left behind.
            for event in ("executor_dispatch_observed", "executor_result_observed", "unit_verification_observed"):
                append_journal_observation(paths, {
                    "target_type": "run", "target_id": frozen["run_ref"], "run_id": frozen["run_ref"],
                    "event": event, "status": "observed",
                    "summary": "an earlier attempt", "worker_ref": "core",
                })

        def runner(argv, **kwargs):
            if argv[0] == "git":
                if break_diff and "diff" in argv and "--name-only" in argv:
                    return subprocess.CompletedProcess(argv, 128, "", "")
                return subprocess.run(argv, **kwargs)
            cwd = Path(str(kwargs.get("cwd")))
            if argv[0] == "codex":
                for rel, text in edits.items():
                    _write(cwd, rel, text)
                head = _commit_all(cwd, "unit work") if edits else base
                payload = {
                    "schema_version": "fanout_unit_result/v1",
                    "unit_id": "core",
                    "run_id": frozen["run_ref"],
                    "fanout_id": contract["fanout_id"],
                    "base_sha": base,
                    "head_sha": head,
                    "process_status": "process_succeeded",
                    "changed_paths": sorted(edits),
                    "checks": [],
                    "findings": [],
                }
                sidecar = _prompted_sidecar(argv)
                sidecar.parent.mkdir(parents=True, exist_ok=True)
                sidecar.write_text(json.dumps(payload), encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, "done", "")
            checks_run.append(list(argv))
            return subprocess.run(
                argv, cwd=kwargs.get("cwd"), env=kwargs.get("env"), text=True,
                capture_output=True, timeout=kwargs.get("timeout"),
            )

        summary = dispatch_fanout(
            paths,
            contract,
            goal_text=_GOAL,
            repo_root=repo,
            base_sha=base,
            only_units=["core"],
            runner=runner,
            readiness=_ready,
            run_verification=True,
        )
        return paths, summary["units"][0], checks_run

    def test_a_failing_task_linked_test_blocks_completion_even_when_declared_checks_pass(self) -> None:
        paths, core, _checks = self._dispatch(
            edits={"pkg/mod.py": _BROKEN_MODULE},
            verification_commands=[_PASSING_COMMAND],
            task_linked_test_runner=_RUNNER,
        )

        linked = core["task_linked_postcondition"]
        self.assertEqual(linked["status"], "tests_selected")
        self.assertEqual(linked["changed_paths"], ["pkg/mod.py"])
        self.assertEqual(linked["selected_test_paths"], ["tests/test_mod.py"])
        self.assertEqual(
            [(row["command"], row["status"]) for row in core["verification_checks"]],
            [(_PASSING_COMMAND, "passed"), (linked["command"], "failed")],
        )
        self.assertEqual(core["verification_checks"][1]["observed_by"], "dispatcher")
        self.assertEqual(core["verification_status"], "failed")
        self.assertEqual(core["unit_state"], "failed")
        self.assertEqual(core["unit_state_reason"], "verification_failed")
        self.assertFalse(core["unit_verification_observed"])
        self.assertFalse(core["integration_ready"])
        self.assertFalse(_unit_verification_is_observed(paths, core["run_ref"]))

    def test_a_passing_task_linked_test_lets_the_unit_verify(self) -> None:
        _paths, core, checks = self._dispatch(
            edits={"pkg/mod.py": _MODULE + "\n\ndef other():\n    return 0\n"},
            task_linked_test_runner=_RUNNER,
        )

        self.assertEqual(core["task_linked_postcondition"]["status"], "tests_selected")
        self.assertEqual(core["verification_status"], "passed")
        self.assertEqual(core["unit_state"], "verified")
        self.assertTrue(core["integration_ready"])
        # Only the direct importer ran; the indirect test would have failed.
        self.assertEqual([argv[-1] for argv in checks], ["tests/test_mod.py"])

    def test_a_change_no_test_imports_is_decided_by_the_declared_checks(self) -> None:
        _paths, core, _checks = self._dispatch(
            edits={"pkg/lonely.py": "x = 2\n", "README.md": "changed\n"},
            verification_commands=[_PASSING_COMMAND],
            task_linked_test_runner=_RUNNER,
        )

        self.assertEqual(core["task_linked_postcondition"]["status"], "no_reachable_tests")
        self.assertEqual([row["command"] for row in core["verification_checks"]], [_PASSING_COMMAND])
        self.assertEqual(core["unit_state"], "verified")

    def test_an_unreadable_diff_fails_closed_without_running_anything(self) -> None:
        paths, core, checks = self._dispatch(
            edits={"pkg/mod.py": _MODULE + "\n"},
            break_diff=True,
            verification_commands=[_PASSING_COMMAND],
            task_linked_test_runner=_RUNNER,
        )

        self.assertEqual(core["task_linked_postcondition"]["status"], "not_resolved")
        self.assertEqual(checks, [])
        self.assertEqual(core["verification_status"], "failed")
        self.assertEqual(core["unit_state"], "failed")
        self.assertFalse(_unit_verification_is_observed(paths, core["run_ref"]))

    def test_an_earlier_attempts_pass_does_not_outlive_a_failure_in_this_one(self) -> None:
        paths, core, _checks = self._dispatch(
            edits={"pkg/mod.py": _BROKEN_MODULE},
            stale_pass=True,
            task_linked_test_runner=_RUNNER,
        )

        self.assertTrue(_unit_verification_is_observed(paths, core["run_ref"]))
        self.assertEqual(core["verification_status"], "failed")
        self.assertFalse(core["unit_verification_observed"])
        self.assertEqual(core["unit_state"], "failed")
        self.assertEqual(core["unit_state_reason"], "verification_failed")

    def test_a_unit_without_a_runner_carries_no_task_linked_record(self) -> None:
        _paths, core, _checks = self._dispatch(
            edits={"pkg/mod.py": _BROKEN_MODULE},
            verification_commands=[_PASSING_COMMAND],
        )

        self.assertNotIn("task_linked_postcondition", core)
        self.assertEqual(core["unit_state"], "verified")


if __name__ == "__main__":
    unittest.main()
