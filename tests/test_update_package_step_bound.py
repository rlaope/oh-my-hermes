"""The package-manager step of `omh update` is bounded and says it is still running (#2793).

`_run_package_manager_self_update` used to wait on npm, bun or brew with no
timeout and no output, so a stalled package manager left the step header on
screen forever. Every case here runs the real function over a tiny child of
this interpreter (`python -c ...`), never a package manager: the bound and the
still-running interval are shortened through the module constants, and the
re-entry of step 2 is `python -c pass`.
"""

from __future__ import annotations

from argparse import Namespace
from contextlib import redirect_stdout
import io
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from omh.commands import setup
from omh.core.errors import OmhError

INSTRUCTION = "npm update -g oh-my-hermes"
TIMEOUT_ENV = "OMH_UPDATE_PACKAGE_TIMEOUT"
STILL_RUNNING = "still running"


def plan(child_code: str) -> dict[str, object]:
    return {
        "method": "package_manager",
        "package_manager": "npm",
        "update_instruction": INSTRUCTION,
        "update_command": [sys.executable, "-c", child_code],
        "reentry_command": [sys.executable, "-c", "pass"],
    }


def run_step(child_code: str, *, json_mode: bool = False) -> tuple[int, str]:
    stdout = io.StringIO()
    with patch.object(sys, "argv", ["omh", "update"]), redirect_stdout(stdout):
        code = setup._run_package_manager_self_update(Namespace(json=json_mode), plan(child_code))
    return code, stdout.getvalue()


class PackageStepBoundTests(unittest.TestCase):
    def setUp(self) -> None:
        environ = patch.dict(os.environ)
        environ.start()
        self.addCleanup(environ.stop)
        for name in (TIMEOUT_ENV, "OMH_OUTPUT"):
            os.environ.pop(name, None)

    def test_a_child_that_outlives_the_bound_is_killed_and_the_error_names_the_manual_command(self) -> None:
        spawned: list[subprocess.Popen[str]] = []

        class Recording(subprocess.Popen):
            def __init__(self, *args, **kwargs) -> None:
                super().__init__(*args, **kwargs)
                spawned.append(self)

        with patch.object(setup, "PACKAGE_UPDATE_TIMEOUT_SECONDS", 0.3), \
                patch.object(subprocess, "Popen", Recording), \
                self.assertRaises(OmhError) as raised:
            run_step("import time; time.sleep(60)")

        message = str(raised.exception)
        self.assertTrue(message.startswith("command package update failed: npm did not finish"), message)
        self.assertIn("within 0.3 seconds", message)
        self.assertIn(f"Run `{INSTRUCTION}` yourself, then rerun `omh update`.", message)
        # One child, the stalled step: step 2 never ran, and the child was waited on after the kill.
        self.assertEqual(len(spawned), 1)
        self.assertIsNotNone(spawned[0].returncode)
        self.assertNotEqual(spawned[0].returncode, 0)

    def test_the_bound_passed_to_the_package_manager_is_the_default_or_the_override(self) -> None:
        done = subprocess.CompletedProcess(args=["npm"], returncode=0, stdout="", stderr="")
        for raw, expected in ((None, 900), ("45", 45), ("abc", 900)):
            with self.subTest(raw=raw):
                override = {} if raw is None else {TIMEOUT_ENV: raw}
                with patch.dict(os.environ, override), \
                        patch.object(setup.subprocess, "run", return_value=done) as run:
                    self.assertEqual(run_step("pass", json_mode=True)[0], 0)
                self.assertEqual(run.call_args_list[0].kwargs["timeout"], expected)
                self.assertNotIn("timeout", run.call_args_list[1].kwargs)

    def test_a_child_that_outlives_one_interval_prints_the_still_running_line(self) -> None:
        with patch.object(setup, "PACKAGE_UPDATE_STILL_RUNNING_SECONDS", 0.05):
            code, stdout = run_step("import time; time.sleep(0.6)")

        self.assertEqual(code, 0)
        lines = [line for line in stdout.splitlines() if STILL_RUNNING in line]
        self.assertGreaterEqual(len(lines), 1, stdout)
        self.assertRegex(lines[0], r"^      still running \(\d+s elapsed\)$")
        # Between the step's own lines: after its detail, before its `[ok]`.
        self.assertLess(stdout.index(INSTRUCTION), stdout.index(STILL_RUNNING))
        self.assertLess(stdout.rindex(STILL_RUNNING), stdout.index("[ok] command package updated"))

    def test_json_mode_prints_nothing_while_the_child_runs(self) -> None:
        with patch.object(setup, "PACKAGE_UPDATE_STILL_RUNNING_SECONDS", 0.05):
            code, stdout = run_step("import time; time.sleep(0.6)", json_mode=True)

        self.assertEqual((code, stdout), (0, ""))

    def test_a_fast_child_prints_exactly_what_it_printed_before(self) -> None:
        code, stdout = run_step("pass")

        self.assertEqual(code, 0)
        self.assertEqual(
            stdout,
            "OMH update\n"
            "Refresh the OMH command package and workflow pack.\n"
            "\n"
            "[1/2] Updating omh command package...\n"
            f"      {INSTRUCTION}\n"
            "      [ok] command package updated\n"
            "[2/2] Refreshing OMH workflows with the updated command...\n",
        )

    def test_the_override_takes_a_positive_whole_number_and_anything_else_is_the_default(self) -> None:
        self.assertEqual(setup.PACKAGE_UPDATE_TIMEOUT_ENV, TIMEOUT_ENV)
        self.assertEqual(setup._package_update_timeout_seconds(), 900)
        for raw, expected in (("120", 120), ("", 900), ("abc", 900), ("0", 900), ("-5", 900)):
            with self.subTest(raw=raw), patch.dict(os.environ, {TIMEOUT_ENV: raw}):
                self.assertEqual(setup._package_update_timeout_seconds(), expected)


if __name__ == "__main__":
    unittest.main()
