from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from omh.release import CommandResult, _subprocess_runner, hermes_release_smoke_plan, run_hermes_release_smoke


class ReleaseSmokeTests(unittest.TestCase):
    def test_hermes_smoke_plan_is_non_mutating_until_live(self) -> None:
        omh_home = str(Path("/tmp/omh-smoke").resolve())
        hermes_home = str(Path("/tmp/hermes-smoke").resolve())
        payload = hermes_release_smoke_plan(omh_home="/tmp/omh-smoke", hermes_home="/tmp/hermes-smoke")

        self.assertEqual(payload["schema_version"], "hermes_release_smoke/v1")
        self.assertEqual(payload["mode"], "plan")
        self.assertFalse(payload["observed"])
        self.assertIn("--live", payload["live_command"])
        commands = [step["command"] for step in payload["steps"]]
        self.assertEqual(commands[0], ["hermes", "skills", "tap", "add", "rlaope/oh-my-hermes-agent"])
        self.assertEqual(
            commands[1],
            ["hermes", "skills", "install", "rlaope/oh-my-hermes-agent/skills/oh-my-hermes", "--yes"],
        )
        self.assertIn(["hermes", "skills", "list", "--enabled-only"], commands)
        self.assertIn(["hermes", "skills", "check", "oh-my-hermes"], commands)
        self.assertIn(["hermes", "skills", "inspect", "rlaope/oh-my-hermes-agent/skills/oh-my-hermes"], commands)
        self.assertIn("does not touch", payload["proof_boundary"])
        self.assertEqual(payload["target_binding"]["hermes_home"], hermes_home)
        self.assertIn("--hermes-home", payload["live_command"])

    def test_setup_install_path_uses_omh_setup_before_hermes_checks(self) -> None:
        omh_home = str(Path("/tmp/omh-smoke").resolve())
        hermes_home = str(Path("/tmp/hermes-smoke").resolve())
        payload = hermes_release_smoke_plan(
            install_path="setup",
            omh_command="omh-dev",
            omh_home="/tmp/omh-smoke",
            hermes_home="/tmp/hermes-smoke",
        )

        commands = [step["command"] for step in payload["steps"]]
        self.assertEqual(commands[0], ["omh-dev", "--omh-home", omh_home, "--hermes-home", hermes_home, "setup"])
        self.assertIn(["hermes", "skills", "check", "oh-my-hermes"], commands)
        self.assertIn(["omh-dev", "--omh-home", omh_home, "--hermes-home", hermes_home, "doctor"], commands)
        self.assertNotIn(["hermes", "skills", "inspect", "oh-my-hermes"], commands)

    def test_live_smoke_records_successful_command_results(self) -> None:
        seen: list[list[str]] = []
        seen_env: list[dict[str, str]] = []

        def runner(command, _timeout, env):
            seen.append(list(command))
            seen_env.append(dict(env or {}))
            return CommandResult(command, 0, "ok", "")

        with patch("omh.release.shutil.which", return_value="/usr/local/bin/hermes"):
            payload = run_hermes_release_smoke(runner=runner, timeout_seconds=5, hermes_home="/tmp/hermes-smoke")

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["observed"])
        self.assertEqual(payload["hermes_cli"]["path"], "/usr/local/bin/hermes")
        self.assertEqual(seen[0], ["hermes", "skills", "tap", "add", "rlaope/oh-my-hermes-agent"])
        self.assertEqual(seen[-1], ["hermes", "skills", "inspect", "rlaope/oh-my-hermes-agent/skills/oh-my-hermes"])
        self.assertTrue(all(env["HERMES_HOME"] == str(Path("/tmp/hermes-smoke").resolve()) for env in seen_env))
        self.assertTrue(all(result["environment"]["HERMES_HOME"] == str(Path("/tmp/hermes-smoke").resolve()) for result in payload["results"]))
        self.assertTrue(all(result["ok"] for result in payload["results"]))
        self.assertIn("does not prove a later chat session", payload["proof_boundary"])

    def test_live_smoke_stops_on_required_failure(self) -> None:
        def runner(command, _timeout, _env):
            if list(command)[:3] == ["hermes", "skills", "install"]:
                return CommandResult(command, 1, "", "scan failed")
            return CommandResult(command, 0, "ok", "")

        with patch("omh.release.shutil.which", return_value="/usr/local/bin/hermes"):
            payload = run_hermes_release_smoke(runner=runner)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed_step"], "skill_install")
        self.assertEqual(len(payload["results"]), 2)
        self.assertIn("Hermes skill scan", payload["recommended_next_action"])

    def test_live_smoke_reports_missing_hermes_cli_without_running_steps(self) -> None:
        def runner(command, _timeout, _env):  # pragma: no cover - should not be called
            raise AssertionError(f"unexpected command: {command}")

        with patch("omh.release.shutil.which", return_value=None):
            payload = run_hermes_release_smoke(runner=runner)

        self.assertFalse(payload["ok"])
        self.assertFalse(payload["observed"])
        self.assertEqual(payload["failed_step"], "hermes_cli")
        self.assertEqual(payload["results"], [])

    def test_subprocess_runner_reports_missing_executable_as_command_failure(self) -> None:
        result = _subprocess_runner(["/definitely/not/a/real/omh-command"], 1)

        self.assertEqual(result.returncode, 127)
        self.assertIn("No such file", result.stderr)

    def test_subprocess_runner_normalizes_timeout_bytes_output(self) -> None:
        result = _subprocess_runner(
            [
                sys.executable,
                "-c",
                "import sys,time; sys.stdout.write('hello'); sys.stdout.flush(); sys.stderr.write('warn'); sys.stderr.flush(); time.sleep(5)",
            ],
            1,
        )

        self.assertEqual(result.returncode, 124)
        self.assertIn("hello", result.stdout)
        self.assertTrue(result.stderr)


if __name__ == "__main__":
    unittest.main()
