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
                   "tui_onboard")

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
