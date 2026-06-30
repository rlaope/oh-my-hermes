from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
import omh.menubar_app as menubar_app_module
from omh.menubar_app import MENUBAR_APP_SCHEMA_VERSION, setup_menubar_app
from omh.paths import resolve_paths


class MenubarAppTests(unittest.TestCase):
    def test_setup_menubar_app_skips_unsupported_platform(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")

            payload = setup_menubar_app(paths, platform_name="Linux", dry_run=True)

            self.assertEqual(payload["schema_version"], MENUBAR_APP_SCHEMA_VERSION)
            self.assertEqual(payload["status"], "skipped")
            self.assertFalse(payload["supported"])
            self.assertFalse((root / ".omh" / "menubar").exists())

    def test_setup_menubar_app_darwin_dry_run_reports_install_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")

            with patch("omh.menubar_app.shutil.which", return_value="/usr/bin/swiftc"):
                payload = setup_menubar_app(
                    paths,
                    platform_name="Darwin",
                    dry_run=True,
                    command_path="/usr/local/bin/omh",
                )

            self.assertEqual(payload["schema_version"], MENUBAR_APP_SCHEMA_VERSION)
            self.assertEqual(payload["status"], "dry_run")
            self.assertTrue(payload["supported"])
            self.assertFalse(payload["installed"])
            self.assertEqual(payload["swiftc"], "/usr/bin/swiftc")
            self.assertEqual(payload["omh_command"], "/usr/local/bin/omh")
            self.assertFalse((root / ".omh" / "menubar").exists())

    def test_menubar_install_cli_dry_run_uses_contract_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch("omh.menubar_app.platform.system", return_value="Darwin"),
                patch("omh.menubar_app.shutil.which", return_value="/usr/bin/swiftc"),
                patch("omh.menubar_app._resolved_omh_command", return_value="/usr/local/bin/omh"),
            ):
                status, stdout, stderr = run_cli(
                    [
                        "--omh-home",
                        str(root / ".omh"),
                        "--hermes-home",
                        str(root / ".hermes"),
                        "menubar",
                        "install",
                        "--dry-run",
                    ]
                )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], MENUBAR_APP_SCHEMA_VERSION)
            self.assertEqual(payload["status"], "dry_run")
            self.assertEqual(payload["omh_command"], "/usr/local/bin/omh")
            self.assertFalse((root / ".omh" / "menubar").exists())

    def test_native_helper_requests_json_status_payload(self) -> None:
        self.assertIn(
            '["menubar", "status", "--observe-local-processes", "--json"]',
            menubar_app_module._SWIFT_SOURCE,
        )

    def test_menubar_start_defaults_to_human_readable_output(self) -> None:
        payload = {
            "schema_version": MENUBAR_APP_SCHEMA_VERSION,
            "operation": "start",
            "platform": "Darwin",
            "label": "com.rlaope.omh.menubar",
            "launch_agent": "/tmp/com.rlaope.omh.menubar.plist",
            "started": True,
            "status": "running",
            "message": "OMH menu bar helper started.",
        }
        with patch("omh.commands.menubar.start_menubar_app", return_value=payload):
            status, stdout, stderr = run_cli(["menubar", "start"], output_json=False)

        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        self.assertIn("OMH menu bar start", stdout)
        self.assertIn("Status: running", stdout)
        self.assertIn("Result: helper started", stdout)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(stdout)

        with patch("omh.commands.menubar.start_menubar_app", return_value=payload):
            status, stdout, stderr = run_cli(["menubar", "start", "--json"], output_json=False)

        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout)["schema_version"], MENUBAR_APP_SCHEMA_VERSION)

    def test_menubar_stop_failure_is_readable_without_json(self) -> None:
        payload = {
            "schema_version": MENUBAR_APP_SCHEMA_VERSION,
            "operation": "stop",
            "platform": "Darwin",
            "label": "com.rlaope.omh.menubar",
            "launch_agent": "/tmp/com.rlaope.omh.menubar.plist",
            "stopped": False,
            "status": "failed",
            "message": "Boot-out failed: 5: Input/output error\nTry re-running the command as root for richer errors.",
        }
        with patch("omh.commands.menubar.stop_menubar_app", return_value=payload):
            status, stdout, stderr = run_cli(["menubar", "stop"], output_json=False)

        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        self.assertIn("OMH menu bar stop", stdout)
        self.assertIn("Status: failed", stdout)
        self.assertIn("Boot-out failed: 5: Input/output error", stdout)
        self.assertIn("Run `omh menubar status`", stdout)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(stdout)

    def test_custom_path_uninstall_does_not_touch_user_launch_agent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup"])[0], 0)

            with patch(
                "omh.commands.setup.uninstall_menubar_app",
                side_effect=AssertionError("custom path uninstall must not touch the user LaunchAgent"),
            ):
                status, stdout, stderr = run_cli(
                    ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "uninstall"]
                )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["menubar_app"]["status"], "not_requested")


if __name__ == "__main__":
    unittest.main()
