"""Bare `omh` on the TUI's own Hermes runtime: which home the launch opens on, and what the TUI is told.

`_own_runtime_home` decides from the saved choice and the argv: an explicit home or profile, or a `--resume` of a
session that lives in the shared gateway's store, stays on the shared gateway. `_run_terminal` hands Hermes'
launcher the TUI home as `HERMES_HOME` and names the bots' home beside it; the TUI's `/gateway restart` then offers
its own runtime's restart alone.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from omh.commands import bare_launch
from omh.commands.bare_launch import bare_launch_args
from omh.paths import resolve_paths
from omh.skin_pack import RUNTIME_OWN, RUNTIME_SHARED, write_runtime_choice
from omh.tui import app as app_module
from omh.tui import launch
from omh.tui.own_runtime import MARKER_FILE, tui_home_path


def _root(tmp: Path) -> Path:
    root = tmp / "hermes"
    (root / "skills" / "apple").mkdir(parents=True)
    (root / "config.yaml").write_text("model: {}\n", encoding="utf-8")
    return root


def _state_db(home: Path, *session_ids: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(home / "state.db")
    connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, message_count INTEGER)")
    connection.executemany("INSERT INTO sessions VALUES (?, ?, ?)", [(sid, "t", 2) for sid in session_ids])
    connection.commit()
    connection.close()


class EnvironmentTests(unittest.TestCase):
    def test_the_bots_home_rides_the_environment_only_on_the_own_runtime(self) -> None:
        base = dict(python="/py", site="/site", omh_home=Path("/o"), fallback_sentinel=Path("/t/f"), session_file=Path("/t/s"))
        env = launch.omh_tui_environment({launch.RUNTIME_ENV: "own", launch.BOTS_HOME_ENV: "/stale"}, **base)
        self.assertNotIn(launch.RUNTIME_ENV, env)
        self.assertNotIn(launch.BOTS_HOME_ENV, env)
        env = launch.omh_tui_environment({}, bots_home=Path("/bots"), **base)
        self.assertEqual((env[launch.RUNTIME_ENV], env[launch.BOTS_HOME_ENV]), (launch.RUNTIME_OWN_VALUE, str(Path("/bots"))))
        for name in (launch.RUNTIME_ENV, launch.BOTS_HOME_ENV):
            self.assertTrue(name.startswith("OMH_TUI_"), name)  # the gateway child never sees them


class DecisionTests(unittest.TestCase):
    def test_nothing_saved_or_shared_stays_on_the_shared_gateway(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root(Path(tmp))
            paths = resolve_paths(str(Path(tmp) / "omh"), str(root))
            self.assertIsNone(bare_launch._own_runtime_home(bare_launch_args([]), paths))
            write_runtime_choice(paths.omh_home, RUNTIME_SHARED)
            self.assertIsNone(bare_launch._own_runtime_home(bare_launch_args([]), paths))
            self.assertFalse(tui_home_path(paths.omh_home).exists())

    def test_own_builds_the_home_and_names_it(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root(Path(tmp))
            paths = resolve_paths(str(Path(tmp) / "omh"), str(root))
            write_runtime_choice(paths.omh_home, RUNTIME_OWN)
            home = bare_launch._own_runtime_home(bare_launch_args([]), paths)
            self.assertEqual(home, tui_home_path(paths.omh_home))
            self.assertTrue((home / "config.yaml").is_file())
            self.assertTrue((home / "skills" / "apple").is_symlink())
            self.assertTrue((home / MARKER_FILE).is_file())

    def test_an_explicit_home_or_profile_stays_on_the_shared_gateway(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root(Path(tmp))
            paths = resolve_paths(str(Path(tmp) / "omh"), str(root))
            write_runtime_choice(paths.omh_home, RUNTIME_OWN)
            for argv in (["--hermes-home", str(root)], ["-p", "kami"], ["--profile", "kami", "--resume", "s-1"]):
                with self.subTest(argv=argv):
                    self.assertIsNone(bare_launch._own_runtime_home(bare_launch_args(argv), paths))
            self.assertFalse(tui_home_path(paths.omh_home).exists())

    def test_a_resume_of_a_session_in_the_shared_store_opens_there_and_says_so(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root(Path(tmp))
            paths = resolve_paths(str(Path(tmp) / "omh"), str(root))
            write_runtime_choice(paths.omh_home, RUNTIME_OWN)
            _state_db(Path(paths.hermes_home), "shared-1")
            home = tui_home_path(paths.omh_home)
            _state_db(home, "own-1")
            import io
            from contextlib import redirect_stderr
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertIsNone(bare_launch._own_runtime_home(bare_launch_args(["--resume", "shared-1"]), paths))
            self.assertIn("shared-1 lives on the shared Hermes gateway", stderr.getvalue())
            self.assertEqual(bare_launch._own_runtime_home(bare_launch_args(["--resume", "own-1"]), paths), home)
            # A session neither store knows is Hermes' to refuse: the launch goes where the choice says.
            self.assertEqual(bare_launch._own_runtime_home(bare_launch_args(["--resume", "nowhere"]), paths), home)
            # A bare `--resume` (the picker) opens on the own runtime.
            self.assertEqual(bare_launch._own_runtime_home(bare_launch_args(["--resume"]), paths), home)

    def test_a_home_that_cannot_be_built_says_why_and_stays_on_the_shared_gateway(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root(Path(tmp))
            paths = resolve_paths(str(Path(tmp) / "omh"), str(root))
            write_runtime_choice(paths.omh_home, RUNTIME_OWN)
            import io
            from contextlib import redirect_stderr
            stderr = io.StringIO()
            with redirect_stderr(stderr), patch("omh.tui.own_runtime.build_tui_home", side_effect=OSError("disk full")):
                self.assertIsNone(bare_launch._own_runtime_home(bare_launch_args([]), paths))
            self.assertIn("could not prepare the TUI's own runtime home (disk full)", stderr.getvalue())


class LaunchTests(unittest.TestCase):
    def test_the_launcher_gets_the_tui_home_and_the_tui_is_told_the_bots_home(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = root / "child-env.json"
            hermes = root / "hermes-bin"
            hermes.write_text(
                f"#!{sys.executable}\nimport json, os\n"
                f"with open({str(record)!r}, 'w') as out: json.dump([os.environ.get('HERMES_HOME'), "
                "os.environ.get('OMH_TUI_RUNTIME'), os.environ.get('OMH_TUI_BOTS_HOME')], out)\n",
                encoding="utf-8",
            )
            hermes.chmod(0o755)
            paths = resolve_paths(str(root / "omh"), str(root / "selected"))
            tui_home = root / "tui-home"
            with patch.dict(os.environ, {"HERMES_HOME": str(root / "other"), "OMH_TUI_RUNTIME": "own"}), \
                    patch.object(bare_launch, "_omh_tui_blocker", return_value=""):
                self.assertEqual(bare_launch._run_terminal(str(hermes), bare_launch_args([]), paths, hermes_home=tui_home), 0)
                self.assertEqual(json.loads(record.read_text()), [str(tui_home), "own", str(paths.hermes_home)])
                self.assertEqual(bare_launch._run_terminal(str(hermes), bare_launch_args([]), paths), 0)
                self.assertEqual(json.loads(record.read_text()), [str(paths.hermes_home), None, None])


class RestartChoiceTests(unittest.TestCase):
    def test_the_own_runtime_offers_its_restart_alone(self) -> None:
        choices = app_module.gateway_restart_choices("", own=True)
        self.assertEqual(choices, (app_module.GATEWAY_OWN_RUNTIME_CHOICE, app_module.GATEWAY_CANCEL_CHOICE))
        self.assertEqual(app_module.gateway_restart_choices("kami", own=True), choices)
        self.assertEqual(app_module.gateway_restart_choices("", own=True, offered=True),
                         (app_module.GATEWAY_CANCEL_CHOICE, app_module.GATEWAY_OWN_RUNTIME_CHOICE))

    def test_the_shared_gateway_keeps_its_choices(self) -> None:
        self.assertEqual(app_module.gateway_restart_choices(""),
                         (app_module.GATEWAY_RESTART_CHOICE, app_module.GATEWAY_CANCEL_CHOICE))
        self.assertEqual(app_module.gateway_restart_choices("kami"), (
            app_module.GATEWAY_PROFILE_CHOICE.format(profile="kami"), app_module.GATEWAY_WHOLE_CHOICE,
            app_module.GATEWAY_CANCEL_CHOICE))
        self.assertEqual(app_module.gateway_restart_choices("kami", offered=True), (
            app_module.GATEWAY_CANCEL_CHOICE, app_module.GATEWAY_PROFILE_CHOICE.format(profile="kami"),
            app_module.GATEWAY_WHOLE_CHOICE))


if __name__ == "__main__":
    unittest.main()
