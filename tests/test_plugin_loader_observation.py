"""The isolated loader probe must reproduce the binding the real home declares.

`omh setup` writes `plugins.entries.omh.settings.omh_home` into every home it
registers. The plugin refuses to load in a native host whose profile names no
store (#2037), so a probe whose synthetic config omits that binding can only
ever report a load failure -- on a machine where the plugin loads fine.
"""

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from omh.install.plugin_loader_observation import observe_real_loader_registration
from omh.install.release_smoke_core import CommandResult
from omh.plugin_bundle.omh.metadata import PROVIDED_HOOKS, PROVIDED_TOOLS

OBSERVATION_PREFIX = "OMH_PLUGIN_LOADER_OBSERVATION="


class ObserveRealLoaderRegistrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory(prefix="omh-loader-test-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.plugin_dir = root / "plugins" / "omh"
        self.plugin_dir.mkdir(parents=True)
        (self.plugin_dir / "plugin.yaml").write_text("name: omh\n", encoding="utf-8")
        self.code_root = root / "hermes-agent"
        (self.code_root / "hermes_cli").mkdir(parents=True)
        self.python = root / "python.exe"
        self.python.write_bytes(b"stub")
        self.config_seen = ""
        self.env_seen: dict[str, str] = {}

    def _runner(self, *, tools=None, hooks=None, returncode=0, stderr=""):
        def run(command, timeout_seconds, env):
            self.env_seen = dict(env)
            self.config_seen = (Path(env["HERMES_HOME"]) / "config.yaml").read_text(encoding="utf-8")
            payload = {
                "enabled": True,
                "error": None,
                "hermes_version": "0.22.2",
                "tools": sorted(PROVIDED_TOOLS if tools is None else tools),
                "hooks": sorted(PROVIDED_HOOKS if hooks is None else hooks),
            }
            stdout = OBSERVATION_PREFIX + json.dumps(payload)
            return CommandResult(list(command), returncode, stdout, stderr)

        return run

    def observe(self, *, omh_home=None, **runner_kwargs):
        return observe_real_loader_registration(
            self.plugin_dir,
            python_executable=self.python,
            hermes_code_root=self.code_root,
            omh_home=omh_home,
            runner=self._runner(**runner_kwargs),
        )

    def test_pm_launcher_wins_over_a_leftover_legacy_python(self):
        launcher = Path(self.tmp.name) / "hermes"
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        commands = []
        loader = self._runner()

        def run(command, timeout_seconds, env):
            commands.append(command)
            if "--print-runtime-command" in command:
                self.assertNotIn("API_KEY", env)
                self.assertNotEqual(env["HOME"], os.environ.get("HOME"))
                return CommandResult(command, 0, json.dumps([str(self.python), "-I", "-c", "bootstrap"]), "")
            return loader(command, timeout_seconds, env)

        with mock.patch.dict(os.environ, {"HERMES_PYTHON": "", "API_KEY": "not-forwarded"}), \
                mock.patch("omh.install.plugin_loader_observation.shutil.which", return_value=str(launcher)):
            result = observe_real_loader_registration(self.plugin_dir, hermes_code_root=self.code_root,
                                                     runner=run)
        self.assertTrue(result["ok"], result)
        self.assertIn("--print-runtime-command", commands[0])
        self.assertIn("committed_venv", commands[-1][-1])
        self.assertIn("site_packages", commands[-1][-1])
        self.assertIn("owning_home_root", commands[-1][-1])
        self.assertIn("reset_hermes_home_override", commands[-1][-1])
        self.assertNotIn("import hermes_bootstrap", commands[-1][-1])

    def test_genuinely_absent_hermes_is_reported_as_not_installed(self):
        home = Path(self.tmp.name) / "empty-home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HERMES_PYTHON": ""}), \
                mock.patch("omh.install.plugin_loader_observation.shutil.which", return_value=None), \
                mock.patch("omh.install.plugin_loader_observation.Path.home", return_value=home):
            result = observe_real_loader_registration(
                self.plugin_dir, runner=lambda command, timeout, env: self.fail(f"ran {command}"))
        self.assertFalse(result["observed"])
        self.assertEqual(result["reason"], "hermes_not_installed")

    def test_broken_present_launcher_is_not_reported_as_missing(self):
        launcher = Path(self.tmp.name) / "hermes"
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"HERMES_PYTHON": ""}), \
                mock.patch("omh.install.plugin_loader_observation.shutil.which", return_value=str(launcher)):
            result = observe_real_loader_registration(self.plugin_dir, hermes_code_root=self.code_root,
                runner=lambda command, timeout, env: CommandResult(command, 2, "", "broken"))
        self.assertEqual(result["reason"], "hermes_runtime_command_failed")

    def test_invalid_or_timed_out_pm_printer_never_falls_back_to_another_runtime(self):
        import subprocess
        launcher = Path(self.tmp.name) / "hermes"
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        for stdout in ("noise", "{}", "[]", '["relative-python"]', '[7]', '["/missing/python"]'):
            with self.subTest(stdout=stdout), mock.patch.dict(os.environ, {"HERMES_PYTHON": ""}), \
                    mock.patch("omh.install.plugin_loader_observation.shutil.which", return_value=str(launcher)):
                result = observe_real_loader_registration(self.plugin_dir, hermes_code_root=self.code_root,
                    runner=lambda command, timeout, env: CommandResult(command, 0, stdout, ""))
                self.assertEqual(result["reason"], "hermes_runtime_command_failed")
        with mock.patch.dict(os.environ, {"HERMES_PYTHON": ""}), \
                mock.patch("omh.install.plugin_loader_observation.shutil.which", return_value=str(launcher)):
            def timeout(command, seconds, env):
                self.assertLessEqual(seconds, 15)
                raise subprocess.TimeoutExpired(command, seconds)
            result = observe_real_loader_registration(self.plugin_dir, runner=timeout)
        self.assertEqual(result["reason"], "hermes_runtime_command_failed")

    def test_override_preserves_internal_spaces_and_does_not_query_the_launcher(self):
        python = Path(self.tmp.name) / "python  with spaces"
        python.write_bytes(b"stub")
        with mock.patch.dict(os.environ, {"HERMES_PYTHON": str(python)}), \
                mock.patch("omh.install.plugin_loader_observation.shutil.which") as which:
            result = observe_real_loader_registration(self.plugin_dir, runner=self._runner())
        self.assertTrue(result["ok"], result)
        which.assert_not_called()
        with mock.patch.dict(os.environ, {"HERMES_PYTHON": str(python.with_name("missing"))}):
            result = observe_real_loader_registration(self.plugin_dir, runner=self._runner())
        self.assertEqual(result["reason"], "hermes_python_override_missing")

    def test_direct_python_and_legacy_layout_remain_supported(self):
        launcher = Path(self.tmp.name) / "hermes"
        launcher.write_text("#!" + str(self.python) + "\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"HERMES_PYTHON": ""}), \
                mock.patch("omh.install.plugin_loader_observation.shutil.which", return_value=str(launcher)):
            result = observe_real_loader_registration(self.plugin_dir, runner=self._runner())
        self.assertTrue(result["ok"], result)
        legacy = Path(self.tmp.name) / ".hermes/hermes-agent/venv/bin/python"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"stub")
        with mock.patch.dict(os.environ, {"HERMES_PYTHON": ""}), \
                mock.patch("omh.install.plugin_loader_observation.shutil.which", return_value=None), \
                mock.patch("omh.install.plugin_loader_observation.Path.home", return_value=Path(self.tmp.name)):
            result = observe_real_loader_registration(self.plugin_dir, runner=self._runner())
        self.assertTrue(result["ok"], result)

    def test_binding_is_written_into_the_isolated_config(self):
        result = self.observe(omh_home=Path("/stores/profile-a"))

        self.assertIn("  entries:", self.config_seen)
        self.assertIn('        omh_home: \"/stores/profile-a\"', self.config_seen)
        self.assertEqual(self.env_seen.get("TMPDIR"), self.env_seen["HERMES_HOME"])
        self.assertTrue(result["observed"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["reason"], "registration_matches_manifest")

    def test_a_windows_path_is_written_with_forward_slashes(self):
        result = self.observe(omh_home=r"C:\Users\Admin\.omh")

        self.assertIn('        omh_home: "C:/Users/Admin/.omh"', self.config_seen)
        self.assertTrue(result["ok"])

    def test_without_a_binding_the_config_keeps_its_old_shape(self):
        result = self.observe()

        self.assertNotIn("entries:", self.config_seen)
        self.assertTrue(result["observed"])
        self.assertTrue(result["ok"])

    def test_a_missing_tool_is_a_mismatch_not_a_load_failure(self):
        result = self.observe(tools=PROVIDED_TOOLS[:-1])

        self.assertTrue(result["observed"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "registration_mismatch")

    def test_windows_baseline_reaches_the_probe(self):
        baseline = {
            "SystemRoot": r"C:\Windows",
            "windir": r"C:\Windows",
            "TEMP": r"C:\Temp",
            "LOCALAPPDATA": r"C:\Users\tester\AppData\Local",
        }
        with mock.patch.dict(os.environ, baseline, clear=False):
            self.observe()

        for key, value in baseline.items():
            self.assertEqual(self.env_seen.get(key), value)

    def test_absent_baseline_variables_are_not_invented(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.observe()

        self.assertNotIn("SystemRoot", self.env_seen)
        self.assertNotIn("windir", self.env_seen)
        self.assertNotIn("LOCALAPPDATA", self.env_seen)

    def test_a_failed_probe_reports_a_bounded_detail(self):
        result = self.observe(returncode=1, stderr="x" * 4000)

        self.assertFalse(result["observed"])
        self.assertEqual(result["reason"], "loader_probe_failed")
        self.assertLessEqual(len(result["detail"]), 400)


if __name__ == "__main__":
    unittest.main()
