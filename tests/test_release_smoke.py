from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from omh.release import (
    CommandResult,
    _subprocess_runner,
    hermes_release_smoke_plan,
    release_readiness_checklist,
    run_hermes_release_smoke,
)


class ReleaseSmokeTests(unittest.TestCase):
    def test_release_readiness_checklist_is_plan_only_and_names_required_gates(self) -> None:
        payload = release_readiness_checklist(version="v1.0.0", omh_command="/tmp/omh")

        self.assertEqual(payload["schema_version"], "release_readiness_checklist/v1")
        self.assertEqual(payload["mode"], "plan")
        self.assertFalse(payload["observed"])
        self.assertEqual(payload["version"], "1.0.0")
        self.assertEqual(payload["tag"], "v1.0.0")
        self.assertIn("does not run commands", payload["proof_boundary"])
        items = {item["id"]: item for item in payload["items"]}
        self.assertIn("unit_tests", items)
        self.assertIn("installed_command_smoke", items)
        self.assertIn("installed_command_path", items)
        self.assertIn("live_tap_smoke", items)
        self.assertIn("tag_and_publish", items)
        self.assertEqual(items["installed_command_path"]["command"], "command -v /tmp/omh")
        self.assertEqual(items["installed_command_help"]["command"], "/tmp/omh --help")
        self.assertIn("--include-command-smoke", items["installed_command_smoke"]["command"])
        self.assertIn("dist/oh_my_hermes-1.0.0-py3-none-any.whl", items["wheel_install"]["command"])
        self.assertIn("wheel_setup_dry_run", items)
        self.assertIn("setup --dry-run --channel stable --version 1.0.0", items["wheel_setup_dry_run"]["command"])
        self.assertTrue(items["live_tap_smoke"]["mutates_profile"])
        self.assertTrue(items["live_tap_smoke"]["requires_release_authority"])
        self.assertFalse(items["tag_and_publish"]["required"])
        self.assertIn('git tag -a v1.0.0 -m "Release v1.0.0"', items["tag_and_publish"]["command"])
        self.assertTrue(items["tag_and_publish"]["requires_release_authority"])
        self.assertGreaterEqual(payload["required_item_count"], 16)

    def test_release_readiness_checklist_rejects_unsafe_versions_and_quotes_command_paths(self) -> None:
        with self.assertRaises(ValueError):
            release_readiness_checklist(version="1.0.0; echo injected")

        payload = release_readiness_checklist(version="1.0.0", omh_command="/tmp/omh command")

        items = {item["id"]: item for item in payload["items"]}
        self.assertEqual(items["installed_command_help"]["command"], "'/tmp/omh command' --help")
        self.assertEqual(items["installed_command_path"]["command"], "command -v '/tmp/omh command'")
        self.assertIn("--omh-command '/tmp/omh command'", items["installed_command_smoke"]["command"])
        self.assertIn("'/tmp/omh command' release hermes-smoke --live", items["live_tap_smoke"]["command"])

    def test_release_readiness_checklist_rejects_empty_version(self) -> None:
        with self.assertRaises(ValueError):
            release_readiness_checklist(version=" ")

    def test_hermes_smoke_plan_is_non_mutating_until_live(self) -> None:
        omh_home = str(Path("/tmp/omh-smoke").resolve())
        hermes_home = str(Path("/tmp/hermes-smoke").resolve())
        payload = hermes_release_smoke_plan(omh_home="/tmp/omh-smoke", hermes_home="/tmp/hermes-smoke")

        self.assertEqual(payload["schema_version"], "hermes_release_smoke/v1")
        self.assertEqual(payload["mode"], "plan")
        self.assertFalse(payload["observed"])
        self.assertIn("--live", payload["live_command"])
        commands = [step["command"] for step in payload["steps"]]
        self.assertEqual(commands[0], ["hermes", "skills", "tap", "add", "rlaope/oh-my-hermes"])
        self.assertEqual(
            commands[1],
            ["hermes", "skills", "install", "rlaope/oh-my-hermes/skills/oh-my-hermes", "--yes"],
        )
        self.assertIn(["hermes", "skills", "list", "--enabled-only"], commands)
        self.assertIn(["hermes", "skills", "check", "oh-my-hermes"], commands)
        self.assertIn(["hermes", "skills", "inspect", "rlaope/oh-my-hermes/skills/oh-my-hermes"], commands)
        self.assertIn("does not touch", payload["proof_boundary"])
        self.assertEqual(payload["target_binding"]["hermes_home"], hermes_home)
        self.assertIn("--hermes-home", payload["live_command"])
        self.assertEqual(payload["installed_command_smoke"]["schema_version"], "installed_omh_command_smoke/v1")
        self.assertEqual(payload["installed_command_smoke"]["path_check"]["schema_version"], "installed_omh_path_check/v1")
        self.assertFalse(payload["installed_command_smoke"]["path_check"]["observed"])
        installed_commands = [step["command"] for step in payload["installed_command_smoke"]["steps"]]
        self.assertEqual(installed_commands[0], ["omh", "--help"])
        self.assertIn(
            ["omh", "--omh-home", omh_home, "--hermes-home", hermes_home, "release", "hermes-smoke", "--install-path", "setup", "--omh-command", "omh"],
            installed_commands,
        )
        self.assertEqual(payload["first_use_status_smoke"]["schema_version"], "first_use_status_smoke/v1")
        self.assertFalse(payload["first_use_status_smoke"]["observed"])
        first_use_commands = [step["command"] for step in payload["first_use_status_smoke"]["steps"]]
        self.assertIn("chat", first_use_commands[0])
        self.assertIn("session", first_use_commands[0])
        self.assertIn("accept-plan", first_use_commands[1])
        self.assertIn("select-executor", first_use_commands[2])
        self.assertIn("prepare-handoff", first_use_commands[3])
        self.assertIn("status", first_use_commands[4])
        self.assertEqual(
            payload["first_use_status_smoke"]["expected_status_boundary"]["before_handoff"]["executor_actions_visible"],
            False,
        )

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
        installed_commands = [step["command"] for step in payload["installed_command_smoke"]["steps"]]
        self.assertEqual(installed_commands[0], ["omh-dev", "--help"])
        self.assertIn(
            [
                "omh-dev",
                "--omh-home",
                omh_home,
                "--hermes-home",
                hermes_home,
                "release",
                "hermes-smoke",
                "--install-path",
                "setup",
                "--omh-command",
                "omh-dev",
            ],
            installed_commands,
        )

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
        self.assertEqual(seen[0], ["hermes", "skills", "tap", "add", "rlaope/oh-my-hermes"])
        self.assertEqual(seen[-1], ["hermes", "skills", "inspect", "rlaope/oh-my-hermes/skills/oh-my-hermes"])
        self.assertTrue(all(env["HERMES_HOME"] == str(Path("/tmp/hermes-smoke").resolve()) for env in seen_env))
        self.assertTrue(all(result["environment"]["HERMES_HOME"] == str(Path("/tmp/hermes-smoke").resolve()) for result in payload["results"]))
        self.assertTrue(all(result["ok"] for result in payload["results"]))
        self.assertIn("does not prove a later chat session", payload["proof_boundary"])
        self.assertFalse(payload["installed_command_smoke"]["observed"])

    def test_live_smoke_can_include_installed_command_smoke(self) -> None:
        seen: list[list[str]] = []

        def runner(command, _timeout, _env):
            seen.append(list(command))
            return CommandResult(command, 0, "ok", "")

        with patch("omh.release.shutil.which", return_value="/usr/local/bin/hermes"):
            payload = run_hermes_release_smoke(
                runner=runner,
                timeout_seconds=5,
                hermes_home="/tmp/hermes-smoke",
                omh_home="/tmp/omh-smoke",
                omh_command="omh-dev",
                include_command_smoke=True,
            )

        omh_home = str(Path("/tmp/omh-smoke").resolve())
        hermes_home = str(Path("/tmp/hermes-smoke").resolve())
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["installed_command_smoke"]["observed"])
        self.assertTrue(payload["installed_command_smoke"]["path_check"]["ok"])
        self.assertEqual(payload["installed_command_smoke"]["path_check"]["mode"], "live")
        self.assertIn(["omh-dev", "--help"], seen)
        self.assertIn(
            [
                "omh-dev",
                "--omh-home",
                omh_home,
                "--hermes-home",
                hermes_home,
                "release",
                "hermes-smoke",
                "--install-path",
                "setup",
                "--omh-command",
                "omh-dev",
            ],
            seen,
        )

    def test_installed_command_smoke_failure_marks_release_smoke_failed(self) -> None:
        def runner(command, _timeout, _env):
            if list(command) == ["omh-dev", "--help"]:
                return CommandResult(command, 127, "", "missing omh")
            return CommandResult(command, 0, "ok", "")

        with patch("omh.release.shutil.which", return_value="/usr/local/bin/hermes"):
            payload = run_hermes_release_smoke(runner=runner, omh_command="omh-dev", include_command_smoke=True)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed_step"], "installed_command_smoke")
        self.assertEqual(payload["installed_command_smoke"]["failed_step"], "installed_omh_help")
        self.assertIn("console script", payload["recommended_next_action"])

    def test_installed_command_smoke_fails_before_help_when_omh_is_not_on_path(self) -> None:
        def runner(command, _timeout, _env):  # pragma: no cover - path check should stop first
            raise AssertionError(f"unexpected command: {command}")

        with patch("omh.release.shutil.which", side_effect=lambda command: "/usr/local/bin/hermes" if command == "hermes" else None):
            payload = run_hermes_release_smoke(runner=runner, omh_command="omh-dev", include_command_smoke=True)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed_step"], "installed_command_smoke")
        self.assertEqual(payload["installed_command_smoke"]["failed_step"], "installed_omh_path")
        self.assertFalse(payload["installed_command_smoke"]["observed"])
        self.assertTrue(payload["installed_command_smoke"]["path_check"]["observed"])
        self.assertFalse(payload["installed_command_smoke"]["path_check"]["ok"])
        self.assertEqual(payload["installed_command_smoke"]["results"], [])
        self.assertIn("command -v omh-dev", payload["installed_command_smoke"]["recommended_next_action"])

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

    def test_missing_hermes_cli_can_still_observe_installed_command_smoke(self) -> None:
        seen: list[list[str]] = []

        def runner(command, _timeout, _env):
            seen.append(list(command))
            return CommandResult(command, 0, "ok", "")

        def which(command: str) -> str | None:
            if command == "omh-dev":
                return "/usr/local/bin/omh-dev"
            return None

        with patch("omh.release.shutil.which", side_effect=which):
            payload = run_hermes_release_smoke(runner=runner, omh_command="omh-dev", include_command_smoke=True)

        self.assertFalse(payload["ok"])
        self.assertFalse(payload["observed"])
        self.assertEqual(payload["failed_step"], "hermes_cli")
        self.assertTrue(payload["installed_command_smoke"]["observed"])
        self.assertIn(["omh-dev", "--help"], seen)
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
