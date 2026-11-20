"""`omh auto-resume`: the policy, the read-only status, the shell hook commands and `shell-start`.

The record of sessions is written here straight into `<omh_home>/tui/live-sessions.json` in its
`omh_tui_live_sessions/v1` shape (`omh.tui.live_sessions`), and Hermes' state database as the one table
the claim reads, so every case runs against real files and nothing is spawned.
"""

from __future__ import annotations

from contextlib import contextmanager, redirect_stderr
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.commands import auto_resume as command  # noqa: E402
from omh.maintenance.auto_resume_state import (  # noqa: E402
    auto_resume_enabled,
    dropped_sessions,
    read_auto_resume_mode,
    write_auto_resume_mode,
)
from omh.tui import live_sessions  # noqa: E402


def stamp(minutes_ago: float = 1.0) -> str:
    moment = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_store(omh_home: Path, entries: list[dict]) -> None:
    """The live-sessions record holding `entries` (oldest first), and the pending marker when one is dropped."""
    directory = Path(omh_home) / "tui"
    directory.mkdir(parents=True, exist_ok=True)
    full = []
    for entry in entries:
        full.append({"cwd": "", "terminal_key": "", "state": "dropped", "pid": 999_999, "boot": "",
                     "updated_at": stamp(), **entry})
    (directory / live_sessions.LIVE_SESSIONS_FILE).write_text(
        json.dumps({"schema_version": live_sessions.LIVE_SESSIONS_SCHEMA, "sessions": full}), encoding="utf-8")
    if any(entry["state"] == "dropped" for entry in full):
        (directory / live_sessions.PENDING_MARKER).touch()


def read_store(omh_home: Path) -> dict[str, str]:
    """session id -> state."""
    data = json.loads((Path(omh_home) / "tui" / live_sessions.LIVE_SESSIONS_FILE).read_text(encoding="utf-8"))
    return {entry["session_id"]: entry["state"] for entry in data["sessions"]}


def write_state_db(hermes_home: Path, rows: list[tuple[str, str, int]]) -> None:
    """Hermes' state database with one `sessions` row per (id, title, message_count)."""
    Path(hermes_home).mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(Path(hermes_home) / "state.db")
    try:
        connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, message_count INTEGER)")
        connection.executemany("INSERT INTO sessions VALUES (?, ?, ?)", rows)
        connection.commit()
    finally:
        connection.close()


class _TtyStream(io.StringIO):
    tty = True

    def isatty(self) -> bool:
        return self.tty


@contextmanager
def terminal_stdio(tty: bool = True):
    """stdin and stdout that answer `isatty()` with `tty`; yields the captured stdout."""
    stdout, stdin = _TtyStream(), _TtyStream()
    stdout.tty = stdin.tty = tty
    previous_in, previous_out = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = stdin, stdout
    try:
        yield stdout
    finally:
        sys.stdin, sys.stdout = previous_in, previous_out


class PolicyTests(unittest.TestCase):
    def test_absent_or_malformed_is_on_and_set_round_trips(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(read_auto_resume_mode(home), "on")
            (home / "setup-profile.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(read_auto_resume_mode(home), "on")
            (home / "setup-profile.json").write_text(json.dumps({"auto_resume": {"mode": "maybe"}, "x": 1}))
            self.assertEqual(read_auto_resume_mode(home), "on")
            write_auto_resume_mode(home, "off")
            profile = json.loads((home / "setup-profile.json").read_text(encoding="utf-8"))
            self.assertEqual(profile, {"auto_resume": {"mode": "off"}, "x": 1})
            self.assertEqual(read_auto_resume_mode(home), "off")
            with self.assertRaises(ValueError):
                write_auto_resume_mode(home, "auto")

    def test_the_environment_turns_it_off_for_one_process(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertTrue(auto_resume_enabled(home, {}))
            self.assertTrue(auto_resume_enabled(home, {"OMH_AUTO_RESUME": "1"}))
            self.assertFalse(auto_resume_enabled(home, {"OMH_AUTO_RESUME": "0"}))
            write_auto_resume_mode(home, "off")
            self.assertFalse(auto_resume_enabled(home, {}))

    def test_dropped_sessions_reads_without_changing_anything(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_store(home, [
                {"session_id": "s-closed", "hermes_home": "/h", "state": "closed"},
                {"session_id": "s-old", "hermes_home": "/h", "cwd": "/w", "terminal_key": "TMUX_PANE=%3"},
                {"session_id": "s-gone", "hermes_home": "/h", "state": "live", "pid": 999_999},
            ])
            before = (home / "tui" / live_sessions.LIVE_SESSIONS_FILE).read_bytes()
            with patch.object(live_sessions, "pid_alive", return_value=False):
                rows = dropped_sessions(home)
            self.assertEqual([row["session_id"] for row in rows], ["s-gone", "s-old"])
            self.assertEqual(rows[1]["terminal_key_name"], "TMUX_PANE")
            self.assertNotIn("%3", json.dumps(rows))
            self.assertEqual((home / "tui" / live_sessions.LIVE_SESSIONS_FILE).read_bytes(), before)


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.omh = self.root / "omh"
        self.home = self.root / "home"
        self.home.mkdir()
        environ = {"HOME": str(self.home), "USERPROFILE": str(self.home), "SHELL": "/bin/zsh",
                   "ZDOTDIR": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")}
        patcher = patch.dict(os.environ, environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The terminal running the tests has keys of its own, which outrank the one each case sets.
        for name in ("OMH_AUTO_RESUME", "TERM_PROGRAM", *live_sessions.TERMINAL_KEY_ENV):
            os.environ.pop(name, None)

    def cli(self, *argv: str, output_json: bool = False) -> tuple[int, str, str]:
        return run_cli(["--omh-home", str(self.omh), "auto-resume", *argv], output_json=output_json)

    def test_set_and_status(self) -> None:
        status, out, err = self.cli("set", "--mode", "off")
        self.assertEqual(status, 0, err)
        self.assertIn("Auto-resume: off", out)
        status, out, _err = self.cli("status")
        self.assertIn("Auto-resume: off", out)
        self.assertIn("Shell hook (zsh): not installed", out)
        self.assertIn("Dropped sessions waiting: none", out)
        status, out, _err = self.cli("set", "--mode", "on")
        with patch.dict(os.environ, {"OMH_AUTO_RESUME": "0"}):
            _status, out, _err = self.cli("status")
        self.assertIn("off in this shell: OMH_AUTO_RESUME=0", out)

    def test_set_refuses_an_unknown_mode(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            self.cli("set", "--mode", "auto")
        self.assertEqual(raised.exception.code, 2)

    def test_status_json_names_the_terminal_variable_never_its_value(self) -> None:
        write_store(self.omh, [{"session_id": "s-1", "hermes_home": "/h", "cwd": "/work",
                                "terminal_key": "ITERM_SESSION_ID=w0t0p0:SECRET"}])
        status, out, err = self.cli("status", "--json", output_json=True)
        self.assertEqual(status, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["schema_version"], "omh_auto_resume_status/v1")
        self.assertEqual((payload["mode"], payload["enabled"], payload["pending"]), ("on", True, True))
        self.assertEqual([row["session_id"] for row in payload["dropped"]], ["s-1"])
        self.assertEqual(payload["dropped"][0]["terminal_key_name"], "ITERM_SESSION_ID")
        self.assertNotIn("SECRET", out)
        self.assertEqual({hook["shell"] for hook in payload["shell_hooks"]}, {"zsh", "bash", "powershell"})
        self.assertEqual(read_store(self.omh), {"s-1": "dropped"})  # status claims nothing

    def test_shell_install_dry_run_install_and_remove(self) -> None:
        rc = self.home / ".zshrc"
        rc.write_bytes(b"export A=1\n")
        status, out, err = self.cli("shell", "install", "--dry-run")
        self.assertEqual(status, 0, err)
        self.assertIn("would be added", out)
        self.assertEqual(rc.read_bytes(), b"export A=1\n")
        status, out, err = self.cli("shell", "install")
        self.assertEqual(status, 0, err)
        self.assertIn("auto-resume shell-start", rc.read_text(encoding="utf-8"))
        self.assertIn(str(self.omh), rc.read_text(encoding="utf-8"))
        _status, out, _err = self.cli("status")
        self.assertIn("Shell hook (zsh): installed", out)
        status, out, err = self.cli("shell", "remove")
        self.assertEqual(status, 0, err)
        self.assertEqual(rc.read_bytes(), b"export A=1\n")
        status, out, err = self.cli("shell", "install", "--shell", "bash", "--json", output_json=True)
        self.assertEqual(json.loads(out)["action"], "installed")
        self.assertTrue((self.home / ".bashrc").is_file())

    def test_shell_without_a_known_shell_asks_for_one(self) -> None:
        with patch.dict(os.environ, {"SHELL": "/usr/bin/fish"}), patch.object(command.shell_hook.sys, "platform",
                                                                               "linux"):
            status, _out, err = self.cli("shell", "install")
        self.assertEqual(status, 2)
        self.assertIn("--shell", err)

    def test_shell_start_reopens_this_terminals_session_at_once(self) -> None:
        hermes = self.root / "hermes"
        write_state_db(hermes, [("s-1", "fixing the build", 4)])
        write_store(self.omh, [{"session_id": "s-1", "hermes_home": str(hermes), "terminal_key": "TMUX_PANE=%1"}])
        launched: list[str | None] = []

        def fake_launch(args):
            launched.append(args.tui_resume)
            return 0

        stderr = io.StringIO()
        with terminal_stdio(), redirect_stderr(stderr), patch.dict(os.environ, {"TMUX_PANE": "%1"}), \
                patch("shutil.which", return_value="/bin/hermes"), \
                patch("omh.commands.bare_launch._launch_hermes_tui", side_effect=fake_launch):
            for name in ("HERMES_SESSION_ID", "OMH_TUI_SESSION_FILE", "CI"):
                os.environ.pop(name, None)
            from omh.commands.main import main

            code = main(["--omh-home", str(self.omh), "--hermes-home", str(hermes), "auto-resume", "shell-start"])
        self.assertEqual(code, 0)
        self.assertEqual(launched, ["s-1"])
        self.assertIn("omh: reopening the session this terminal left (s-1, fixing the build)", stderr.getvalue())
        self.assertEqual(read_store(self.omh), {"s-1": "resumed"})

    def test_shell_start_exits_silently_when_it_must_not_run(self) -> None:
        hermes = self.root / "hermes"
        write_state_db(hermes, [("s-1", "t", 4)])
        cases = (
            ("inside a Hermes session", {"HERMES_SESSION_ID": "x"}, True, "/bin/hermes", "on"),
            ("on CI", {"CI": "true"}, True, "/bin/hermes", "on"),
            ("turned off by env", {"OMH_AUTO_RESUME": "0"}, True, "/bin/hermes", "on"),
            ("turned off by policy", {}, True, "/bin/hermes", "off"),
            ("no terminal", {}, False, "/bin/hermes", "on"),
            ("no hermes", {}, True, None, "on"),
        )
        for label, extra, tty, hermes_bin, mode in cases:
            with self.subTest(label):
                write_store(self.omh, [{"session_id": "s-1", "hermes_home": str(hermes),
                                        "terminal_key": "TMUX_PANE=%1"}])
                write_auto_resume_mode(self.omh, mode)
                err = io.StringIO()
                with terminal_stdio(tty), redirect_stderr(err), patch.dict(os.environ, {"TMUX_PANE": "%1", **extra}), \
                        patch("shutil.which", return_value=hermes_bin), \
                        patch("omh.commands.bare_launch._launch_hermes_tui") as launch:
                    for name in ("HERMES_SESSION_ID", "OMH_TUI_SESSION_FILE", "CI", "OMH_AUTO_RESUME"):
                        if name not in extra:
                            os.environ.pop(name, None)
                    from omh.commands.main import main

                    code = main(["--omh-home", str(self.omh), "--hermes-home", str(hermes), "auto-resume",
                                 "shell-start"])
                self.assertEqual(code, 0)
                launch.assert_not_called()
                self.assertEqual(err.getvalue(), "")
                self.assertEqual(read_store(self.omh), {"s-1": "dropped"})


class DoctorRowTests(unittest.TestCase):
    def test_the_row_names_the_mode_and_the_rc_with_the_hook(self) -> None:
        from omh.maintenance.doctor import _auto_resume_check
        from omh.paths import resolve_paths
        from omh.tui.shell_hook import install

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()
            environ = {"HOME": str(home), "USERPROFILE": str(home), "ZDOTDIR": str(home),
                       "XDG_CONFIG_HOME": str(home / ".config")}
            paths = resolve_paths(str(root / "omh"), str(root / "hermes"))
            with patch.dict(os.environ, environ):
                os.environ.pop("OMH_AUTO_RESUME", None)
                check = _auto_resume_check(paths)
                self.assertEqual((check.name, check.ok), ("omh_auto_resume", True))
                self.assertIn("auto-resume is on; no shell hook installed", check.message)
                install("bash", paths.omh_home, os.environ)
                write_auto_resume_mode(paths.omh_home, "off")
                check = _auto_resume_check(paths)
            self.assertIn("auto-resume is off", check.message)
            self.assertIn("bash (", check.message)
            self.assertIn(str(home / ".bashrc"), check.message)
            self.assertEqual(check.detail["mode"], "off")


if __name__ == "__main__":
    unittest.main()
