"""Bare `omh`'s fast path (`omh.cli.main`, `omh.commands.bare_launch`).

A bare launch must read exactly as the full parser reads it, and must reach
`hermes` without importing the command tree. The first is checked argv by
argv against `build_parser`; the second in a fresh interpreter, since this
test process has imported `omh.commands.main` long before.
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from omh.commands.bare_launch import bare_launch_args
from omh.commands.main import build_parser

TOP_LEVEL_DESTS = ("omh_home", "hermes_home", "scope", "pretty", "tui_resume", "tui_continue", "tui_profile",
                   "tui_onboard", "tui_new")

BARE = (
    [],
    ["--omh-home", "/x/omh"],
    ["--hermes-home=/x/hermes", "--scope", "project"],
    ["--pretty"],
    ["-r", "sess-1"],
    ["--resume", "sess-1", "-p", "work"],
    ["--resume"],  # no id: the TUI opens on its session picker
    ["-r", "-p", "work"],
    ["-c"],
    ["--continue", "doctor"],  # continue's optional value swallows the token, as the full parser reads it
    ["-c", "-p", "work"],
    ["--profile=work", "--continue=notes"],
    ["--omh", "/x"],  # an abbreviation of --omh-home, which the full parser accepts too
    ["--onboard", "model-setup"],
    ["--omh-home", "/x/omh", "--hermes-home", "/x/hermes", "--onboard", "model-setup"],  # as `omh setup` runs it
    ["--new"],
    ["--new", "-p", "work"],
)
NOT_BARE = (
    ["doctor"],
    ["--omh-home", "/x", "doctor"],
    ["-h"],
    ["--help"],
    ["--version"],
    ["-V"],
    ["--json"],
    ["--scope", "nowhere"],
    ["--omh-home"],
    ["--p", "x"],  # ambiguous between --pretty and --profile
    ["--", "doctor"],
    ["--onboard", "provider-setup"],  # not an onboarding OMH ships
    ["--onboard"],
    ["--new", "doctor"],
)


def full_parse(argv: list[str]) -> argparse.Namespace | None:
    """What `omh.commands.main`'s parser makes of `argv`; None when it refuses it."""
    try:
        return build_parser().parse_args(argv)
    except SystemExit:
        return None


class BareArgvTests(unittest.TestCase):
    def test_every_bare_argv_reads_as_the_full_parser_reads_it(self) -> None:
        for argv in BARE:
            with self.subTest(argv=argv):
                light, full = bare_launch_args(argv), full_parse(argv)
                if full is None:  # refused by the full parser: the fast path must not have taken it either
                    self.assertIsNone(light)
                    continue
                self.assertIsNotNone(light)
                self.assertIsNone(full.command)
                self.assertEqual({dest: getattr(light, dest) for dest in TOP_LEVEL_DESTS},
                                 {dest: getattr(full, dest) for dest in TOP_LEVEL_DESTS})

    def test_a_bare_resume_forwards_no_id_and_asks_the_tui_for_its_picker(self) -> None:
        from omh.commands.bare_launch import _hermes_passthrough_argv

        for argv, forwarded in ((["--resume"], ["--tui"]), (["-r"], ["--tui"]),
                                (["--resume", "sess-1"], ["--tui", "--resume", "sess-1"]),
                                (["-c", "notes"], ["--tui", "--continue", "notes"])):
            with self.subTest(argv=argv):
                args = bare_launch_args(argv)
                self.assertEqual(_hermes_passthrough_argv(args, tui=True), forwarded)
        self.assertEqual(bare_launch_args(["--resume"]).tui_resume, "")
        self.assertIsNone(bare_launch_args([]).tui_resume)

    def test_anything_else_goes_to_the_full_parser(self) -> None:
        for argv in NOT_BARE:
            with self.subTest(argv=argv):
                self.assertIsNone(bare_launch_args(argv))

    def test_a_parser_error_on_any_path_defers_to_the_full_parser_silently(self) -> None:
        # Python 3.11 reports an ambiguous abbreviation through `error()` itself, which `exit_on_error=False`
        # does not cover; this sends every argv down that path, whatever the interpreter.
        def through_error(parser: argparse.ArgumentParser, args: object = None, namespace: object = None) -> None:
            parser.error("ambiguous option: --p could match --pretty, --profile")

        stderr = io.StringIO()
        with patch.object(argparse.ArgumentParser, "parse_known_args", through_error), redirect_stderr(stderr):
            self.assertIsNone(bare_launch_args(["--p", "x"]))
        self.assertEqual(stderr.getvalue(), "")


@unittest.skipIf(os.name == "nt", "fixture executable uses a POSIX shebang")
class LaunchHomeTests(unittest.TestCase):
    def test_resolved_home_reaches_both_terminal_paths(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import json
        from omh.commands import bare_launch
        from omh.paths import resolve_paths

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = root / "child-home.json"
            hermes = root / "hermes"
            hermes.write_text(
                f"#!{sys.executable}\nimport json, os\n"
                f"with open({str(record)!r}, 'w') as out: json.dump(os.environ.get('HERMES_HOME'), out)\n",
                encoding="utf-8",
            )
            hermes.chmod(0o755)
            args = bare_launch_args(["--hermes-home", str(root / "selected")])
            paths = resolve_paths(str(root / "omh"), str(root / "selected"))
            for blocker in ("", "fixture fallback"):
                with self.subTest(blocker=blocker), patch.dict(os.environ, {"HERMES_HOME": str(root / "other")}), \
                        patch.object(bare_launch, "_omh_tui_blocker", return_value=blocker), \
                        patch.object(bare_launch, "_node_available", return_value=False):
                    self.assertEqual(bare_launch._run_terminal(str(hermes), args, paths), 0)
                    self.assertEqual(json.loads(record.read_text()), str(paths.hermes_home))


    def test_the_tui_session_runs_inside_a_generation_hold(self) -> None:
        # `omh update`'s GC keeps a generation only while something holds it;
        # the hold has to be taken before the child starts and kept until it exits.
        from contextlib import contextmanager
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from omh.commands import bare_launch
        from omh.install import generation_hold
        from omh.paths import resolve_paths

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            flag, record = root / "held", root / "seen"

            @contextmanager
            def fake_hold(prefix=None):
                flag.touch()
                try:
                    yield "fixture"
                finally:
                    flag.unlink()

            hermes = root / "hermes"
            hermes.write_text(
                f"#!{sys.executable}\nimport os\n"
                f"open({str(record)!r}, 'w').write(str(os.path.exists({str(flag)!r})))\n",
                encoding="utf-8",
            )
            hermes.chmod(0o755)
            args = bare_launch_args(["--hermes-home", str(root / "selected")])
            paths = resolve_paths(str(root / "omh"), str(root / "selected"))
            with patch.object(generation_hold, "hold_running_generation", fake_hold), \
                    patch.object(bare_launch, "_omh_tui_blocker", return_value=""):
                self.assertEqual(bare_launch._run_terminal(str(hermes), args, paths), 0)
            self.assertEqual(record.read_text(), "True")
            self.assertFalse(flag.exists())


    def test_only_a_bare_resume_asks_the_omh_tui_for_its_picker(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import json
        from omh.commands import bare_launch
        from omh.paths import resolve_paths

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = root / "child-env.json"
            hermes = root / "hermes"
            hermes.write_text(
                f"#!{sys.executable}\nimport json, os, sys\n"
                f"with open({str(record)!r}, 'w') as out: "
                "json.dump([os.environ.get('OMH_TUI_PICK_SESSION'), sys.argv[1:]], out)\n",
                encoding="utf-8",
            )
            hermes.chmod(0o755)
            paths = resolve_paths(str(root / "omh"), str(root / "selected"))
            for argv, expected in ((["--resume"], ["1", ["--tui"]]), (["-r", "s-1"], [None, ["--tui", "--resume", "s-1"]]),
                                   ([], [None, ["--tui"]])):
                with self.subTest(argv=argv), patch.dict(os.environ, {"OMH_TUI_PICK_SESSION": "1"}), \
                        patch.object(bare_launch, "_omh_tui_blocker", return_value=""):
                    bare_launch._run_terminal(str(hermes), bare_launch_args(argv), paths)
                    self.assertEqual(json.loads(record.read_text()), expected)


class OnboardTests(unittest.TestCase):
    def test_onboard_beside_resume_or_continue_is_refused_before_anything_launches(self) -> None:
        from omh.commands import bare_launch

        for argv in (["--onboard", "model-setup", "--resume"], ["--onboard", "model-setup", "-r", "s-1"],
                     ["--onboard", "model-setup", "-c"], ["--continue", "notes", "--onboard", "model-setup"]):
            with self.subTest(argv=argv):
                args = bare_launch_args(argv)
                self.assertIsNotNone(args)
                stderr = io.StringIO()
                with patch.object(bare_launch, "_launch_hermes_tui") as launched, redirect_stderr(stderr):
                    self.assertEqual(bare_launch.run_bare_launch(args), 2)
                launched.assert_not_called()
                self.assertIn("--onboard opens a new session", stderr.getvalue())

    def test_an_unknown_onboarding_is_refused_by_the_full_parser(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertIsNone(full_parse(["--onboard", "provider-setup"]))
        self.assertIn("invalid choice", stderr.getvalue())

    def test_onboard_with_a_subcommand_is_refused(self) -> None:
        from omh.commands.main import main

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(main(["--onboard", "model-setup", "doctor"]), 2)
        self.assertIn("--onboard opens the OH-MY-HERMES terminal and cannot be combined", stderr.getvalue())

    def test_onboard_is_not_forwarded_to_hermes(self) -> None:
        from omh.commands.bare_launch import _hermes_passthrough_argv

        self.assertEqual(_hermes_passthrough_argv(bare_launch_args(["--onboard", "model-setup"]), tui=True), ["--tui"])

    def test_the_language_is_omh_lang_when_the_prompt_has_it(self) -> None:
        from omh.commands.bare_launch import _onboard_language

        for value, expected in (("ko", "ko"), ("ja", "ja"), ("zh", "zh"), ("en", "en"), ("fr", "en"), ("", "en")):
            with self.subTest(value=value), patch.dict(os.environ, {"OMH_LANG": value}):
                self.assertEqual(_onboard_language(), expected)

    @unittest.skipIf(os.name == "nt", "fixture executable uses a POSIX shebang")
    def test_only_onboard_reaches_the_tui_and_the_fallback_never_carries_it(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import json
        from omh.commands import bare_launch
        from omh.paths import resolve_paths

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = root / "child-env.json"
            hermes = root / "hermes"
            hermes.write_text(
                f"#!{sys.executable}\nimport json, os, sys\n"
                f"with open({str(record)!r}, 'w') as out: "
                "json.dump([os.environ.get('OMH_TUI_ONBOARD'), os.environ.get('OMH_TUI_ONBOARD_LANG'), sys.argv[1:]], "
                "out)\n",
                encoding="utf-8",
            )
            hermes.chmod(0o755)
            paths = resolve_paths(str(root / "omh"), str(root / "selected"))
            inherited = {"OMH_TUI_ONBOARD": "model-setup", "OMH_TUI_ONBOARD_LANG": "ja", "OMH_LANG": "ko"}
            for argv, blocker, expected in (
                (["--onboard", "model-setup"], "", ["model-setup", "ko", ["--tui"]]),
                ([], "", [None, None, ["--tui"]]),
                (["--onboard", "model-setup"], "fixture fallback", [None, None, []]),
            ):
                with self.subTest(argv=argv, blocker=blocker), patch.dict(os.environ, inherited), \
                        patch.object(bare_launch, "_omh_tui_blocker", return_value=blocker), \
                        patch.object(bare_launch, "_node_available", return_value=False), \
                        redirect_stderr(io.StringIO()):
                    bare_launch._run_terminal(str(hermes), bare_launch_args(argv), paths)
                    self.assertEqual(json.loads(record.read_text()), expected)


@unittest.skipIf(os.name == "nt", "fixture executable uses a POSIX shebang")
class AutoResumeLaunchTests(unittest.TestCase):
    """Path A: a bare `omh` reopens the session its terminal (else its folder) dropped, at once."""

    def setUp(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from omh.tui import live_sessions

        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.omh, self.hermes = self.root / "omh", self.root / "hermes"
        self.record = self.root / "argv.json"
        self.fake = self.root / "bin-hermes"
        self.code = self.root / "code"
        self.code.write_text("0", encoding="utf-8")
        self.fake.write_text(
            f"#!{sys.executable}\nimport json, sys\n"
            f"runs = json.load(open({str(self.record)!r})) if __import__('os').path.exists({str(self.record)!r}) else []\n"
            f"runs.append(sys.argv[1:])\njson.dump(runs, open({str(self.record)!r}, 'w'))\n"
            f"sys.exit(int(open({str(self.code)!r}).read()))\n",
            encoding="utf-8",
        )
        self.fake.chmod(0o755)
        environ = patch.dict(os.environ, {"OMH_HOME": str(self.omh), "HERMES_HOME": str(self.hermes)})
        environ.start()
        self.addCleanup(environ.stop)
        for name in ("OMH_AUTO_RESUME", "TERM_PROGRAM", *live_sessions.TERMINAL_KEY_ENV):
            os.environ.pop(name, None)
        self.write_db([("s-1", "fixing the build", 4), ("s-2", "", 2), ("s-empty", "", 0)])

    def write_db(self, rows) -> None:
        import sqlite3

        self.hermes.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.hermes / "state.db")
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, title TEXT, message_count INT)")
            connection.executemany("INSERT INTO sessions VALUES (?, ?, ?)", rows)
            connection.commit()
        finally:
            connection.close()

    def write_store(self, entries) -> None:
        import json
        from datetime import datetime, timezone

        from omh.tui import live_sessions

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        directory = self.omh / "tui"
        directory.mkdir(parents=True, exist_ok=True)
        sessions = [{"hermes_home": str(self.hermes), "cwd": "", "terminal_key": "", "state": "dropped",
                     "pid": 999_999, "boot": "", "updated_at": now, **entry} for entry in entries]
        (directory / live_sessions.LIVE_SESSIONS_FILE).write_text(
            json.dumps({"schema_version": live_sessions.LIVE_SESSIONS_SCHEMA, "sessions": sessions}), encoding="utf-8")
        (directory / live_sessions.PENDING_MARKER).touch()

    def states(self) -> dict[str, str]:
        import json

        from omh.tui import live_sessions

        data = json.loads((self.omh / "tui" / live_sessions.LIVE_SESSIONS_FILE).read_text(encoding="utf-8"))
        return {entry["session_id"]: entry["state"] for entry in data["sessions"]}

    def launch(self, argv: list[str], environ: dict[str, str] | None = None, *, tty: bool = True,
               cwd: str | None = None) -> tuple[int | None, list[list[str]], str]:
        import json
        from pathlib import Path

        from omh.commands import bare_launch

        class _Tty(io.StringIO):
            def isatty(self) -> bool:
                return tty

        self.record.unlink(missing_ok=True)
        stderr = io.StringIO()
        previous = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = _Tty(), _Tty()
        try:
            with patch.dict(os.environ, environ or {}), redirect_stderr(stderr), \
                    patch("shutil.which", return_value=str(self.fake)), \
                    patch.object(bare_launch, "_run_startup_update_check"), \
                    patch.object(bare_launch, "_omh_tui_blocker", return_value=""), \
                    patch.object(bare_launch, "_own_runtime_home", return_value=None), \
                    patch.object(os, "getcwd", return_value=cwd or str(self.root / "elsewhere")):
                args = bare_launch_args(argv)
                assert args is not None
                code = bare_launch._launch_hermes_tui(args)
        finally:
            sys.stdin, sys.stdout = previous
        runs = json.loads(Path(self.record).read_text(encoding="utf-8")) if self.record.exists() else []
        return code, runs, stderr.getvalue()

    def test_a_dropped_session_in_this_terminal_reopens_at_once(self) -> None:
        self.write_store([{"session_id": "s-1", "terminal_key": "TMUX_PANE=%4", "cwd": "/w"}])
        code, runs, stderr = self.launch([], {"TMUX_PANE": "%4"})
        self.assertEqual(code, 0)
        self.assertEqual(runs, [["--tui", "--resume", "s-1"]])
        self.assertIn("omh: reopening the session this terminal left (s-1, fixing the build); "
                      "run `omh --new` for a new one.", stderr)
        self.assertEqual(self.states(), {"s-1": "resumed"})

    def test_an_omher_terminal_with_no_arguments_reopens_by_its_link(self) -> None:
        # omher starts `omh` with OMHER_TERMINAL_LINK and TERM_PROGRAM=omher and nothing else.
        here = str(self.root / "project")
        self.write_store([
            {"session_id": "s-2", "terminal_key": "OMHER_TERMINAL_LINK=abcdefghij"},
            {"session_id": "s-1", "cwd": here},  # same folder, newer, but omher never falls back to the folder
        ])
        environ = {"OMHER_TERMINAL_LINK": "abcdefghij", "TERM_PROGRAM": "omher"}
        code, runs, stderr = self.launch([], environ, cwd=here)
        self.assertEqual(runs, [["--tui", "--resume", "s-2"]])
        self.assertIn("(s-2)", stderr)
        self.assertEqual(self.states(), {"s-2": "resumed", "s-1": "dropped"})
        # Another omher terminal, in that folder, with a link of its own: nothing to reopen.
        code, runs, stderr = self.launch([], {"OMHER_TERMINAL_LINK": "bbbbbbbbbb", "TERM_PROGRAM": "omher"}, cwd=here)
        self.assertEqual(runs, [["--tui"]])
        self.assertEqual(stderr, "")

    def test_outside_omher_the_folder_is_the_fallback(self) -> None:
        here = str(self.root / "project")
        self.write_store([{"session_id": "s-2", "cwd": here}])
        code, runs, stderr = self.launch([], cwd=here)
        self.assertEqual(runs, [["--tui", "--resume", "s-2"]])
        self.assertIn(f"(s-2, {here})", stderr)

    def test_each_off_switch_opens_a_new_session(self) -> None:
        from omh.maintenance.auto_resume_state import write_auto_resume_mode

        cases = (
            ("--new", ["--new"], {}, True, None),
            ("env off", [], {"OMH_AUTO_RESUME": "0"}, True, None),
            ("policy off", [], {}, True, "off"),
            ("explicit resume", ["--resume", "s-2"], {}, True, None),
            ("continue", ["--continue"], {}, True, None),
            ("onboard", ["--onboard", "model-setup"], {}, True, None),
            ("no terminal", [], {}, False, None),
        )
        for label, argv, environ, tty, mode in cases:
            with self.subTest(label):
                self.write_store([{"session_id": "s-1", "terminal_key": "TMUX_PANE=%4"}])
                write_auto_resume_mode(self.omh, mode or "on")
                code, runs, stderr = self.launch(argv, {"TMUX_PANE": "%4", **environ}, tty=tty)
                self.assertNotIn("reopening", stderr)
                self.assertFalse(any("s-1" in run for run in runs), runs)
                self.assertEqual(self.states(), {"s-1": "dropped"})
                if not tty:
                    self.assertIsNone(code)

    def test_a_session_nothing_was_said_in_is_skipped(self) -> None:
        self.write_store([
            {"session_id": "s-2", "terminal_key": "TMUX_PANE=%4"},
            {"session_id": "s-empty", "terminal_key": "TMUX_PANE=%4"},
            {"session_id": "s-unknown", "terminal_key": "TMUX_PANE=%4"},  # no row at all: nothing said either
        ])
        code, runs, stderr = self.launch([], {"TMUX_PANE": "%4"})
        self.assertEqual(runs, [["--tui", "--resume", "s-2"]])
        self.assertEqual(self.states(), {"s-2": "resumed", "s-empty": "resumed", "s-unknown": "resumed"})

    def test_a_resume_hermes_refuses_is_not_tried_again(self) -> None:
        self.write_store([{"session_id": "s-1", "terminal_key": "TMUX_PANE=%4"}])
        self.code.write_text("1", encoding="utf-8")
        code, runs, _stderr = self.launch([], {"TMUX_PANE": "%4"})
        self.assertEqual((code, runs), (1, [["--tui", "--resume", "s-1"]]))
        self.code.write_text("0", encoding="utf-8")
        code, runs, stderr = self.launch([], {"TMUX_PANE": "%4"})
        self.assertEqual(runs, [["--tui"]])
        self.assertNotIn("reopening", stderr)

    def test_new_beside_a_session_flag_is_refused_before_anything_launches(self) -> None:
        from omh.commands import bare_launch

        for argv in (["--new", "--resume"], ["--new", "-r", "s-1"], ["--new", "-c"], ["--new", "--onboard", "model-setup"]):
            with self.subTest(argv=argv):
                args = bare_launch_args(argv)
                self.assertIsNotNone(args)
                stderr = io.StringIO()
                with patch.object(bare_launch, "_launch_hermes_tui") as launched, redirect_stderr(stderr):
                    self.assertEqual(bare_launch.run_bare_launch(args), 2)
                launched.assert_not_called()
                self.assertIn("--new opens a new session", stderr.getvalue())

    def test_new_is_not_forwarded_to_hermes_and_is_refused_with_a_subcommand(self) -> None:
        from omh.commands.bare_launch import _hermes_passthrough_argv
        from omh.commands.main import main

        self.assertEqual(_hermes_passthrough_argv(bare_launch_args(["--new"]), tui=True), ["--tui"])
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(main(["--new", "doctor"]), 2)
        self.assertIn("--new opens the OH-MY-HERMES terminal and cannot be combined", stderr.getvalue())


class BareImportTests(unittest.TestCase):
    def test_a_bare_launch_does_not_import_the_command_tree(self) -> None:
        # stdin is not a terminal, so the launch has nothing to open and prints the welcome text.
        probe = (
            "import sys; from omh.cli import main; code = main(['--omh-home', sys.argv[1]]); "
            "print('command tree imported:', 'omh.commands.main' in sys.modules); sys.exit(code)"
        )
        done = subprocess.run(
            [sys.executable, "-P", "-c", probe, os.devnull],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("OMH - oh-my-hermes", done.stdout)
        self.assertIn("command tree imported: False", done.stdout)

    def test_welcome_is_a_short_first_use_guide(self) -> None:
        from contextlib import redirect_stdout
        from omh.commands.bare_launch import _print_welcome

        output = io.StringIO()
        with redirect_stdout(output):
            _print_welcome()
        text = output.getvalue()
        self.assertLessEqual(len(text.splitlines()), 16)
        for command in ("omh setup", "omh --help", "Hermes"):
            self.assertIn(command, text)
        for command in ("omh runtime", "omh cases", "omh coding", "omh release"):
            self.assertNotIn(command, text)

    def test_a_subcommand_still_goes_through_the_command_tree(self) -> None:
        probe = "import sys; from omh.cli import main; sys.exit(main(['--version']))"
        done = subprocess.run([sys.executable, "-P", "-c", probe], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(done.stdout.strip())

    def test_the_names_omh_cli_used_to_star_import_are_still_there(self) -> None:
        import omh.cli

        self.assertIs(omh.cli.build_parser, build_parser)


if __name__ == "__main__":
    unittest.main()
