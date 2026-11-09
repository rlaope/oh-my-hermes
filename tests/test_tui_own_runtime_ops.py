"""The TUI's own runtime profile on the maintenance surfaces: `omh update` rebuilds it, `omh doctor` reports it, the
menu bar names it, `omh uninstall` removes it, and the surfaces that list the person's Hermes profiles leave it out
(`commands/setup._refresh_tui_home` and `_uninstall_tui_runtime`, `maintenance/doctor._tui_own_runtime_check`,
`surfaces/menubar_status.tui_runtime_setting`, all over `tui/own_runtime.tui_home_status`; `tui/bot_board.board_homes`,
`install/skill_registration.hermes_profile_dirs`, `install/curator_ledger.curator_ledger_paths`)."""

from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from omh.commands import setup
from omh.install.curator_ledger import curator_ledger_paths
from omh.install.skill_registration import hermes_profile_dirs
from omh.maintenance.doctor import _tui_own_runtime_check
from omh.paths import OmhPaths
from omh.skin_pack import RUNTIME_OWN, RUNTIME_SHARED, TUI_PROFILE, write_runtime_choice
from omh.surfaces.menubar_status import tui_runtime_setting
from omh.tui.bot_board import board_homes
from omh.tui.own_runtime import MARKER_FILE, build_tui_home, tui_home_path, tui_home_status


def _homes(tmp: Path) -> OmhPaths:
    root = tmp / "hermes"
    (root / "skills" / "apple").mkdir(parents=True)
    (root / "skills" / "apple" / "SKILL.md").write_text("# apple\n", encoding="utf-8")
    (root / "config.yaml").write_text("model: {}\n", encoding="utf-8")
    (root / ".env").write_text("OPENAI_API_KEY=k\nDISCORD_BOT_TOKEN=t\n", encoding="utf-8")
    (root / "profiles" / "kami").mkdir(parents=True)
    (root / "profiles" / "kami" / "config.yaml").write_text("model: {}\n", encoding="utf-8")
    omh_home = tmp / "omh"
    omh_home.mkdir()
    return OmhPaths(omh_home=omh_home, hermes_home=root)


def _args(paths: OmhPaths, dry_run: bool = False) -> SimpleNamespace:
    return SimpleNamespace(omh_home=str(paths.omh_home), hermes_home=str(paths.hermes_home), dry_run=dry_run)


class StatusTests(unittest.TestCase):
    def test_an_unbuilt_profile_reads_as_absent_on_the_default_runtime(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            status = tui_home_status(Path(paths.hermes_home), None)
            self.assertEqual((status.runtime, status.exists, status.built, status.gateway_live), ("own", False, False, False))
            self.assertEqual(status.home, Path(paths.hermes_home) / "profiles" / TUI_PROFILE)
            self.assertEqual(tui_home_status(Path(paths.hermes_home), RUNTIME_SHARED).runtime, "shared")

    def test_a_built_profile_reports_its_marker_links_and_env(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            build_tui_home(paths.omh_home, paths.hermes_home, served=())
            status = tui_home_status(Path(paths.hermes_home), RUNTIME_OWN)
            self.assertEqual((status.runtime, status.built_from, status.skill_count, status.broken_links,
                              status.messaging_names, status.platforms), ("own", str(paths.hermes_home), 1, (), (), ()))
            # The skill goes without a rebuild: its link is broken until the next build drops it.
            os.remove(paths.hermes_home / "skills" / "apple" / "SKILL.md")
            os.rmdir(paths.hermes_home / "skills" / "apple")
            self.assertEqual(tui_home_status(Path(paths.hermes_home), RUNTIME_OWN).broken_links, ("apple",))
            # A live record of the profile's gateway with an adapter: what the check warns about.
            (tui_home_path(paths.hermes_home) / "gateway_state.json").write_text(json.dumps({
                "pid": os.getpid(), "gateway_state": "running", "hermes_home": str(tui_home_path(paths.hermes_home)),
                "platforms": {"discord": {"state": "connected", "writer_pid": os.getpid()}},
            }), encoding="utf-8")
            with patch("omh.tui.bot_board.read_gateway") as read_gateway:
                read_gateway.return_value = SimpleNamespace(
                    live=True, pid=4242, platforms=(SimpleNamespace(name="discord", current=True, state="connected"),))
                status = tui_home_status(Path(paths.hermes_home), RUNTIME_OWN)
            self.assertEqual((status.gateway_live, status.gateway_pid, status.platforms), (True, 4242, ("discord",)))


class DoctorCheckTests(unittest.TestCase):
    def test_shared_says_so_and_names_the_alternative(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            write_runtime_choice(paths.omh_home, RUNTIME_SHARED)
            check = _tui_own_runtime_check(paths)
            self.assertEqual((check.name, check.ok, check.severity), ("omh_tui_runtime", True, "ok"))
            self.assertIn("shared Hermes gateway", check.message)
            self.assertEqual(check.detail["runtime"], RUNTIME_SHARED)

    def test_the_default_before_the_first_launch_warns_that_the_profile_is_not_built(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            check = _tui_own_runtime_check(paths)
            self.assertEqual((check.ok, check.severity), (True, "warning"))
            self.assertIn("not built yet", check.message)
            self.assertIn("omh update", check.next_action)
            self.assertEqual(check.detail["tui_home"], str(Path(paths.hermes_home) / "profiles" / TUI_PROFILE))

    def test_a_built_profile_from_this_root_is_ok_and_counts_its_skills(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            build_tui_home(paths.omh_home, paths.hermes_home, served=())
            check = _tui_own_runtime_check(paths)
            self.assertEqual((check.ok, check.severity), (True, "ok"), check.message)
            self.assertIn("1 skills", check.message)
            self.assertIn("no messaging credential", check.message)
            self.assertIn("gateway not running", check.message)

    def test_findings_warn_with_what_clears_them(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            build_tui_home(paths.omh_home, paths.hermes_home, served=())
            home = tui_home_path(paths.hermes_home)
            marker = json.loads((home / MARKER_FILE).read_text(encoding="utf-8"))
            marker["root"] = str(Path(tmp) / "elsewhere")
            (home / MARKER_FILE).write_text(json.dumps(marker), encoding="utf-8")
            (home / ".env").write_text("OPENAI_API_KEY=k\nSLACK_BOT_TOKEN=leak\n", encoding="utf-8")
            check = _tui_own_runtime_check(paths)
            self.assertEqual((check.ok, check.severity), (False, "blocking"))  # a credential on the TUI runtime fails the row
            self.assertIn("built from", check.message)
            self.assertIn("SLACK_BOT_TOKEN", check.message)
            self.assertIn("omh update", check.next_action)
            self.assertEqual(check.detail["messaging_names"], ["SLACK_BOT_TOKEN"])


class UpdateRefreshTests(unittest.TestCase):
    def test_nothing_to_do_when_shared_is_saved(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            write_runtime_choice(paths.omh_home, RUNTIME_SHARED)
            with patch.object(setup, "_paths", return_value=paths):
                self.assertIsNone(setup._refresh_tui_home(_args(paths)))
            self.assertFalse(tui_home_path(paths.hermes_home).exists())

    def test_the_default_builds_the_profile_and_a_second_update_finds_it_current(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            with patch.object(setup, "_paths", return_value=paths):
                first = setup._refresh_tui_home(_args(paths))
                second = setup._refresh_tui_home(_args(paths))
                dry = setup._refresh_tui_home(_args(paths, dry_run=True))
            self.assertEqual((first["status"], first["skills"], first["scrubbed"]), ("refreshed", 1, ["DISCORD_BOT_TOKEN"]))
            self.assertEqual(first["tui_home"], str(tui_home_path(paths.hermes_home)))
            self.assertEqual((second["status"], second["refreshed"]), ("current", []))
            self.assertEqual(dry["status"], "dry_run")
            self.assertTrue((tui_home_path(paths.hermes_home) / "config.yaml").is_file())

    def test_a_profile_left_behind_by_switching_to_shared_is_not_refreshed(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            build_tui_home(paths.omh_home, paths.hermes_home, served=())
            write_runtime_choice(paths.omh_home, RUNTIME_SHARED)
            before = (tui_home_path(paths.hermes_home) / "config.yaml").stat().st_mtime_ns
            (paths.hermes_home / "config.yaml").write_text("model: {other: 1}\n", encoding="utf-8")
            with patch.object(setup, "_paths", return_value=paths):
                self.assertIsNone(setup._refresh_tui_home(_args(paths)))
            self.assertEqual((tui_home_path(paths.hermes_home) / "config.yaml").stat().st_mtime_ns, before)

    def test_a_failure_is_noted_and_does_not_raise(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            stderr = io.StringIO()
            with patch.object(setup, "_paths", return_value=paths), \
                    patch("omh.tui.own_runtime.build_tui_home", side_effect=OSError("read-only")), redirect_stderr(stderr):
                result = setup._refresh_tui_home(_args(paths))
            self.assertEqual((result["status"], result["reason"]), ("failed", "read-only"))
            self.assertIn("was not refreshed: read-only", stderr.getvalue())

    def test_windows_leaves_the_profile_alone(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            with patch.object(setup, "_paths", return_value=paths), patch.object(setup.os, "name", "nt"):
                self.assertIsNone(setup._refresh_tui_home(_args(paths)))
            self.assertFalse(tui_home_path(paths.hermes_home).exists())


class UninstallTests(unittest.TestCase):
    def test_a_full_uninstall_removes_the_profile_and_other_scopes_leave_it(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            home = tui_home_path(paths.hermes_home)
            self.assertEqual(setup._uninstall_tui_runtime(paths, remove_all=True, dry_run=False)["status"], "absent")
            build_tui_home(paths.omh_home, paths.hermes_home, served=())
            self.assertEqual(setup._uninstall_tui_runtime(paths, remove_all=False, dry_run=False)["status"], "not_requested")
            self.assertEqual(setup._uninstall_tui_runtime(paths, remove_all=True, dry_run=True)["status"], "would_remove")
            self.assertTrue(home.is_dir())
            with patch("omh.tui.bot_board.read_gateway", return_value=SimpleNamespace(live=True, served=())):
                self.assertEqual(setup._uninstall_tui_runtime(paths, remove_all=True, dry_run=False)["status"], "kept")
            result = setup._uninstall_tui_runtime(paths, remove_all=True, dry_run=False)
            self.assertEqual((result["status"], result["path"]), ("removed", str(home)))
            self.assertFalse(home.exists())
            self.assertTrue((paths.hermes_home / "profiles" / "kami").is_dir())  # a bot's profile is not touched here

    def test_a_removal_failure_is_noted_and_does_not_raise(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            build_tui_home(paths.omh_home, paths.hermes_home, served=())
            stderr = io.StringIO()
            with patch("omh.tui.own_runtime.remove_tui_home", side_effect=OSError("busy")), redirect_stderr(stderr):
                result = setup._uninstall_tui_runtime(paths, remove_all=True, dry_run=False)
            self.assertEqual((result["status"], result["reason"]), ("failed", "busy"))
            self.assertIn("was not removed: busy", stderr.getvalue())


class ProfileListingTests(unittest.TestCase):
    def test_the_tui_profile_is_no_bot_on_any_listing(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            build_tui_home(paths.omh_home, paths.hermes_home, served=("kami",))
            self.assertTrue(tui_home_path(paths.hermes_home).is_dir())
            self.assertEqual([name for name, _ in hermes_profile_dirs(Path(paths.hermes_home))], ["kami"])
            ledgers = curator_ledger_paths(Path(paths.hermes_home))
            self.assertNotIn(tui_home_path(paths.hermes_home) / "skills" / ".curator_ledger.jsonl", ledgers)
            self.assertIn(paths.hermes_home / "profiles" / "kami" / "skills" / ".curator_ledger.jsonl", ledgers)
            # The bot board, read from a session on the TUI profile itself: the root and kami, never the TUI profile.
            current, homes = board_homes({"HERMES_HOME": str(tui_home_path(paths.hermes_home)), "HOME": tmp})
            self.assertEqual(current, tui_home_path(paths.hermes_home))
            self.assertEqual([name for name, _ in homes], ["default", "kami"])


class MenubarSettingTests(unittest.TestCase):
    def test_the_setting_names_the_runtime_and_the_gateway_state(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _homes(Path(tmp))
            self.assertEqual(tui_runtime_setting(paths)["label"], "TUI runtime: own (home not built yet)")
            write_runtime_choice(paths.omh_home, RUNTIME_SHARED)
            self.assertEqual(tui_runtime_setting(paths)["label"], "TUI runtime: shared gateway")
            write_runtime_choice(paths.omh_home, RUNTIME_OWN)
            build_tui_home(paths.omh_home, paths.hermes_home, served=())
            setting = tui_runtime_setting(paths)
            self.assertEqual((setting["value"], setting["label"], setting["raw"]), ("own", "TUI runtime: own (gateway idle)", "tui_runtime:own:0"))
            with patch("omh.tui.bot_board.read_gateway") as read_gateway:
                read_gateway.return_value = SimpleNamespace(live=True, pid=77, platforms=())
                self.assertEqual(tui_runtime_setting(paths)["label"], "TUI runtime: own (gateway pid 77)")


if __name__ == "__main__":
    unittest.main()
