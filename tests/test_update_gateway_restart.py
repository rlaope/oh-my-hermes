"""`omh update` offers to restart a running Hermes gateway still on the old OMH plugin code, and `omh` relaunches the
TUI that asked for it onto the generation the update installed.

The gateway's files say which gateways are stale (a recorded start before the
plugin bundle's install) and running now; the process the person started asks
on a terminal, No by default, naming what the restart interrupts, and on yes
runs Hermes' own `hermes -p <profile> gateway restart --yes --detach`. Nothing
is asked in a re-entry, a dry run, with --json, --no-interactive or --yes, or
after an update that did not activate; --restart-gateway and
--no-restart-gateway decide without asking. A requested restart that fails
exits 4. Every case runs over temporary homes and a recording runner: no
Hermes, no gateway, no process.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_hermes_gateway_health import INSTALLED_AT, NOW, STARTED, state_record, write_home
from omh.commands import bare_launch, update_gateway
from omh.commands.bare_launch import bare_launch_args
from omh.commands.main import build_parser
from omh.commands.update_gateway import (
    ASK,
    DECLINED_LINE,
    FAILED_LINE,
    FINISHED_LINE,
    GATEWAY_RESTART_EXIT_CODE,
    INTERRUPTED_EXIT_CODE,
    NOTHING_STALE_LINE,
    NO_DESCRIPTION,
    PROFILE_QUESTION,
    QUESTION,
    RESTART,
    SKIP,
    STALE_LINE,
    STARTED_LINE,
    UNSTARTED_LINE,
    YES_DESCRIPTION,
    restart_after_update,
    restart_mode,
)
from omh.install import generation_hold, self_update
from omh.maintenance.hermes_gateway import stale_running_gateways
from omh.tui import launch
from omh.tui.gateway_restart import AFTER_TURN_ENV, RestartImpact
from test_tui_gateway_restart import HOST

HERMES = "/usr/local/bin/hermes"


def profile_marker(home: Path) -> Path:
    """A bot profile is a home with an identity file (`hermes_profile_dirs`)."""
    if home.parent.name == "profiles":
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.yaml").write_text("{}\n", encoding="utf-8")
    return home


def stale(home: Path) -> Path:
    """A gateway running in `home` that started before the plugin bundle installed there."""
    return write_home(profile_marker(home), state=state_record(home), starts=[STARTED], installed_at=INSTALLED_AT)


def current(home: Path) -> Path:
    """A gateway running in `home` that started after the bundle's install: it runs the new code."""
    return write_home(profile_marker(home), state=state_record(home), starts=[STARTED + 120],
                      installed_at=INSTALLED_AT)


class Recorder:
    """What `restart_after_update` asked, ran and said."""

    def __init__(self, answers: list[bool] | None = None, codes: list[int | BaseException] | None = None) -> None:
        self.answers = list(answers or [])
        self.codes = list(codes or [])
        self.asked: list[str] = []
        self.ran: list[tuple[list[str], dict[str, str]]] = []
        self.said: list[str] = []

    def ask(self, question: str) -> bool:
        self.asked.append(question)
        return self.answers.pop(0)

    def run(self, argv: list[str], env: dict[str, str]) -> int:
        self.ran.append((argv, env))
        code = self.codes.pop(0) if self.codes else 0
        if isinstance(code, BaseException):
            raise code
        return code

    def say(self, line: str) -> None:
        self.said.append(line)

    def __call__(self, code: int, home: Path, mode: str = ASK, *, hermes: str | None = HERMES,
                 environ: dict[str, str] | None = None) -> int:
        self.impact_homes: list[tuple[str, str]] = []
        self.impact_environs: list[dict[str, str]] = []

        def impact(environ: dict[str, str], profile: str) -> RestartImpact:
            self.impact_homes.append((environ["HERMES_HOME"], profile))
            self.impact_environs.append(environ)
            return RestartImpact(Path(environ["HERMES_HOME"]), HOST)

        with patch.object(update_gateway, "stale_running_gateways",
                          lambda root: stale_running_gateways(root, now=NOW)), \
                patch.object(update_gateway, "read_impact", impact):
            return restart_after_update(code, home, mode=mode, ask=self.ask, run=self.run, hermes=hermes,
                                        environ=environ if environ is not None else {"PATH": "/bin"}, say=self.say)


class StaleGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "hermes"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_running_gateway_that_started_before_the_bundle_install_is_stale(self) -> None:
        stale(self.root)
        self.assertEqual(stale_running_gateways(self.root, now=NOW), [("default", self.root)])

    def test_a_gateway_on_the_new_code_or_one_that_is_not_running_is_not(self) -> None:
        current(self.root)
        self.assertEqual(stale_running_gateways(self.root, now=NOW), [])
        stopped = Path(self.tmp.name) / "stopped"
        write_home(stopped, state=state_record(stopped, gateway_state="stopped"), starts=[STARTED],
                   installed_at=INSTALLED_AT)
        self.assertEqual(stale_running_gateways(stopped, now=NOW), [])
        gone = Path(self.tmp.name) / "gone"
        write_home(gone, pid=None, state=state_record(gone), starts=[STARTED], installed_at=INSTALLED_AT)
        self.assertEqual(stale_running_gateways(gone, now=NOW), [])

    def test_a_profile_running_its_own_gateway_is_named_after_the_root(self) -> None:
        stale(self.root)
        stale(self.root / "profiles" / "kami")
        current(self.root / "profiles" / "work")
        self.assertEqual(stale_running_gateways(self.root, now=NOW),
                         [("default", self.root), ("kami", self.root / "profiles" / "kami")])


class ModeTests(unittest.TestCase):
    def args(self, *argv: str) -> argparse.Namespace:
        return build_parser().parse_args(["update", *argv])

    def test_a_terminal_is_asked_unless_the_run_says_to_ask_nothing(self) -> None:
        self.assertEqual(restart_mode(self.args(), terminal=True, environ={}), ASK)
        for flag in ("--json", "--no-interactive", "--yes", "--dry-run"):
            with self.subTest(flag=flag):
                self.assertEqual(restart_mode(self.args(flag), terminal=True, environ={}), SKIP)
        self.assertEqual(restart_mode(self.args(), terminal=False, environ={}), SKIP)

    def test_the_flags_decide_without_asking_on_or_off_a_terminal(self) -> None:
        for terminal in (True, False):
            self.assertEqual(restart_mode(self.args("--restart-gateway"), terminal=terminal, environ={}), RESTART)
            self.assertEqual(restart_mode(self.args("--restart-gateway", "--json"), terminal=terminal, environ={}),
                             RESTART)
            self.assertEqual(restart_mode(self.args("--no-restart-gateway"), terminal=terminal, environ={}), SKIP)
        with redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            self.args("--restart-gateway", "--no-restart-gateway")

    def test_a_re_entered_update_never_asks_or_restarts(self) -> None:
        reentered = {update_gateway.REENTRY_ENV: "1"}
        self.assertEqual(restart_mode(self.args("--restart-gateway"), terminal=True, environ=reentered), SKIP)
        self.assertEqual(restart_mode(self.args("--command-package-updated"), terminal=True, environ={}), SKIP)

    def test_neither_flag_leaves_the_choice_unset(self) -> None:
        self.assertIsNone(self.args().restart_gateway)
        self.assertIs(self.args("--restart-gateway").restart_gateway, True)
        self.assertIs(self.args("--no-restart-gateway").restart_gateway, False)

    def test_no_re_entry_carries_an_abbreviation_of_those_flags_either(self) -> None:
        with patch.object(sys, "argv", ["omh", "update", "--restart", "--no-restart", "--no-interactive", "--json"]):
            self.assertEqual(self_update._reentry_argv(),
                             ["update", "--no-interactive", "--json", "--command-package-updated"])
            from omh.commands import setup

            self.assertEqual(setup._reentry_argv_with_command_package_updated(),
                             ["update", "--no-interactive", "--json", "--command-package-updated"])

    def test_no_re_entry_carries_the_flags_an_older_generation_does_not_know(self) -> None:
        argv = ["omh", "update", "--restart-gateway", "--no-restart-gateway", "--recover-known-good", "--channel", "main"]
        with patch.object(sys, "argv", argv):
            self.assertEqual(self_update._reentry_argv(), ["update", "--channel", "preview", "--command-package-updated"])
            from omh.commands import setup

            self.assertEqual(setup._reentry_argv_with_command_package_updated(),
                             ["update", "--recover-known-good", "--channel", "main", "--command-package-updated"])


class RestartAfterUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "hermes"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_it_names_what_the_restart_interrupts_then_asks_and_no_restarts_nothing(self) -> None:
        stale(self.root)
        record = Recorder(answers=[False])
        self.assertEqual(record(0, self.root), 0)
        self.assertEqual(record.asked, [QUESTION])
        self.assertEqual(record.ran, [])
        self.assertEqual(record.said[0], STALE_LINE.format(which=""))
        self.assertEqual(record.said[1], "  profiles: default, kami · bots: kami:discord, telegram · 2 running")
        self.assertEqual(record.impact_homes, [(str(self.root), "")])  # the root's own record
        self.assertEqual(record.said[-1], DECLINED_LINE.format(command="hermes gateway restart"))

    def test_yes_runs_hermes_own_restart_for_the_default_profile_on_the_root(self) -> None:
        stale(self.root)
        record = Recorder(answers=[True])
        environ = {"PATH": "/bin", "_HERMES_GATEWAY": "1", "HERMES_GATEWAY_MODE": "x", "HERMES_HOME": "/elsewhere"}
        self.assertEqual(record(0, self.root, environ=environ), 0)
        ((argv, env),) = record.ran
        self.assertEqual(argv, [HERMES, "-p", "default", "gateway", "restart", "--yes", "--detach"])
        self.assertEqual(env, {"PATH": "/bin", "HERMES_HOME": str(self.root)})  # no gateway markers
        self.assertEqual(record.said[-2:], [STARTED_LINE.format(command="hermes gateway restart"), FINISHED_LINE])

    def test_the_impact_reads_the_environment_the_restart_gets(self) -> None:
        stale(self.root)
        record = Recorder(answers=[False])
        record(0, self.root, environ={AFTER_TURN_ENV: "60", "HERMES_HOME": "/elsewhere"})
        self.assertEqual(record.impact_environs[0][AFTER_TURN_ENV], "60")
        self.assertEqual(record.impact_environs[0]["HERMES_HOME"], str(self.root))

    def test_a_profiles_own_gateway_is_asked_and_restarted_by_name(self) -> None:
        stale(self.root / "profiles" / "kami")
        record = Recorder(answers=[True])
        record(0, self.root)
        self.assertEqual(record.asked, [PROFILE_QUESTION.format(profile="kami")])
        self.assertEqual(record.ran[0][0][:3], [HERMES, "-p", "kami"])
        self.assertIn(STALE_LINE.format(which=" for profile kami"), record.said)
        self.assertEqual(record.impact_homes, [(str(self.root / "profiles" / "kami"), "kami")])

    def test_restart_mode_asks_nothing_and_restarts(self) -> None:
        stale(self.root)
        record = Recorder()
        self.assertEqual(record(0, self.root, RESTART), 0)
        self.assertEqual(record.asked, [])
        self.assertEqual(len(record.ran), 1)

    def test_a_failed_or_unstartable_restart_is_not_called_success(self) -> None:
        cases = (("exit 1", [1], HERMES, FAILED_LINE.format(code=1, command="hermes gateway restart")),
                 ("oserror", [OSError("denied")], HERMES, UNSTARTED_LINE.format(why="denied",
                                                                                   command="hermes gateway restart")),
                 ("no hermes", [], None, UNSTARTED_LINE.format(why=update_gateway.NO_HERMES,
                                                               command="hermes gateway restart")))
        for case, codes, hermes, line in cases:
            with self.subTest(case=case):
                stale(self.root)
                record = Recorder(codes=codes)
                self.assertEqual(record(0, self.root, RESTART, hermes=hermes), GATEWAY_RESTART_EXIT_CODE)
                self.assertEqual(record.said[-1], line)
                record = Recorder(codes=list(codes))
                self.assertEqual(record(self_update.PROFILE_REPAIR_EXIT_CODE, self.root, RESTART, hermes=hermes),
                                 self_update.PROFILE_REPAIR_EXIT_CODE)  # already nonzero: kept

    def test_ctrl_c_ends_the_wait_and_says_the_restart_goes_on(self) -> None:
        stale(self.root)
        stale(self.root / "profiles" / "kami")
        record = Recorder(codes=[KeyboardInterrupt()])
        self.assertEqual(record(0, self.root, RESTART), INTERRUPTED_EXIT_CODE)
        self.assertEqual(len(record.ran), 1)  # the next gateway is not restarted
        self.assertEqual(record.said[-1], update_gateway.INTERRUPTED_LINE)

    def test_nothing_stale_asks_nothing_and_only_an_asked_for_restart_says_so(self) -> None:
        current(self.root)
        record = Recorder()
        self.assertEqual(record(0, self.root), 0)
        self.assertEqual((record.asked, record.ran, record.said), ([], [], []))
        self.assertEqual(record(0, self.root, RESTART), 0)
        self.assertEqual(record.said, [NOTHING_STALE_LINE])

    def test_an_update_that_did_not_activate_or_a_skip_reads_and_asks_nothing(self) -> None:
        stale(self.root)
        for code, mode in ((1, ASK), (1, RESTART), (0, SKIP)):
            with self.subTest(code=code, mode=mode), \
                    patch.object(update_gateway, "stale_running_gateways", side_effect=AssertionError("read")):
                record = Recorder()
                self.assertEqual(restart_after_update(code, self.root, mode=mode, ask=record.ask, run=record.run,
                                                      hermes=HERMES, environ={}, say=record.say), code)


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


class CommandWiringTests(unittest.TestCase):
    def test_off_a_terminal_cmd_update_reaches_no_gateway_file(self) -> None:
        from omh.commands import setup

        args = build_parser().parse_args(["update"])
        with patch.object(update_gateway, "stale_running_gateways", side_effect=AssertionError("read")), \
                patch.object(setup, "_stdin_is_tty", return_value=False):
            self.assertEqual(setup._offer_gateway_restart(args, 0), 0)

    def test_a_terminal_asks_through_the_yes_no_picker_defaulting_to_no(self) -> None:
        from omh.commands import setup

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "hermes"
            stale(root)
            args = build_parser().parse_args(["--hermes-home", str(root), "--omh-home", str(Path(tmp) / "omh"),
                                              "update"])
            asked: list[tuple[str, bool]] = []

            def ask(prompt: str, *, default: bool, use_color: bool, note: str = "", language: str = "en",
                    yes_description: str = "", no_description: str = "") -> bool:
                asked.append((prompt, default))
                self.assertEqual((yes_description, no_description), (YES_DESCRIPTION, NO_DESCRIPTION))
                return False

            with patch.object(update_gateway, "stale_running_gateways",
                              lambda home: stale_running_gateways(home, now=NOW)), \
                    patch.object(setup, "_stdin_is_tty", return_value=True), \
                    patch.object(setup, "_ask_yes_no", ask), patch.object(setup.subprocess, "Popen") as popen, \
                    redirect_stdout(Terminal()):
                self.assertEqual(setup._offer_gateway_restart(args, 0), 0)
            self.assertEqual(asked, [(QUESTION, False)])
            popen.assert_not_called()

    def test_the_question_imports_nothing_new_after_the_update(self) -> None:
        # A package manager has replaced these files by then, and an installer update has re-pointed them.
        script = (
            "import sys, tempfile\n"
            "from pathlib import Path\n"
            "from omh.commands.update_gateway import impact_lines, read_impact, stale_running_gateways\n"
            "class Blocked:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.startswith('omh.'):\n"
            "            raise ImportError('imported after the update: ' + name)\n"
            "sys.meta_path.insert(0, Blocked())\n"
            "home = Path(tempfile.mkdtemp())\n"
            "stale_running_gateways(home)\n"
            "impact_lines(read_impact({'HERMES_HOME': str(home)}, ''), False)\n"
        )
        run = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_ctrl_c_at_the_question_is_a_no_and_keeps_the_updates_code(self) -> None:
        from omh.commands import setup

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "hermes"
            stale(root)
            args = build_parser().parse_args(["--hermes-home", str(root), "--omh-home", str(Path(tmp) / "omh"),
                                              "update"])
            with patch.object(update_gateway, "stale_running_gateways",
                              lambda home: stale_running_gateways(home, now=NOW)), \
                    patch.object(setup, "_stdin_is_tty", return_value=True), \
                    patch.object(setup, "_ask_yes_no", side_effect=KeyboardInterrupt), \
                    patch.object(setup.subprocess, "Popen") as popen, redirect_stdout(Terminal()) as stdout:
                self.assertEqual(setup._offer_gateway_restart(args, 0), 0)
            popen.assert_not_called()
            self.assertIn(DECLINED_LINE.format(command="hermes gateway restart"), stdout.getvalue())

    def test_omh_output_json_on_a_terminal_asks_nothing(self) -> None:
        from omh.commands import setup

        args = build_parser().parse_args(["update"])
        with patch.dict(os.environ, {"OMH_OUTPUT": "json"}), \
                patch.object(update_gateway, "stale_running_gateways", side_effect=AssertionError("read")), \
                patch.object(setup, "_stdin_is_tty", return_value=True), redirect_stdout(Terminal()):
            self.assertEqual(setup._offer_gateway_restart(args, 0), 0)

    def test_a_restart_runs_in_a_session_of_its_own_with_no_stdin(self) -> None:
        from omh.commands import setup

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "hermes"
            stale(root)
            args = build_parser().parse_args(["--hermes-home", str(root), "--omh-home", str(Path(tmp) / "omh"),
                                              "update", "--restart-gateway", "--json"])
            stderr = io.StringIO()
            with patch.object(update_gateway, "stale_running_gateways",
                              lambda home: stale_running_gateways(home, now=NOW)), \
                    patch.object(setup.shutil, "which", return_value=HERMES), \
                    patch.object(setup.subprocess, "Popen") as popen, patch("sys.stderr", stderr), \
                    redirect_stdout(io.StringIO()) as stdout:
                popen.return_value.wait.return_value = 0
                self.assertEqual(setup._offer_gateway_restart(args, 0), 0)
            (call,) = popen.call_args_list
            self.assertEqual(call.args[0], [HERMES, "-p", "default", "gateway", "restart", "--yes", "--detach"])
            self.assertTrue(call.kwargs["start_new_session"])
            self.assertEqual(call.kwargs["stdin"], setup.subprocess.DEVNULL)
            self.assertIs(call.kwargs["stdout"], stderr)  # --json: stdout holds the payload alone
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn(FINISHED_LINE, stderr.getvalue())


class RelaunchTests(unittest.TestCase):
    """bare `omh`: a TUI that exits `RELAUNCH_EXIT` with its marker is opened again on the installed generation."""

    def fake_hermes(self, root: Path, *, code: int, marker: bool, holds: str = "") -> Path:
        hermes = root / "hermes"
        create = (f"open(os.environ[{launch.RELAUNCH_FILE_ENV!r}], 'w').write({holds!r})\n" if marker else "")
        hermes.write_text(
            f"#!{sys.executable}\nimport json, os, sys\n"
            f"open({str(root / 'env.json')!r}, 'w').write(json.dumps(os.environ.get({launch.RELAUNCH_FILE_ENV!r})))\n"
            f"{create}"
            f"open(os.environ[{launch.SESSION_FILE_ENV!r}], 'w').write(json.dumps("
            f"{{'session_id': 's-1', 'hermes_home': {str(root)!r}}}))\n"
            f"sys.exit({code})\n",
            encoding="utf-8",
        )
        hermes.chmod(0o755)
        return hermes

    def run_terminal(self, root: Path, *, code: int, marker: bool, installer: Path | None,
                     holds: str = "") -> tuple[int, list[tuple[Path, str]]]:
        from omh.paths import resolve_paths

        hermes = self.fake_hermes(root, code=code, marker=marker, holds=holds)
        relaunch: list[tuple[Path, str]] = []
        closed: list = []
        with patch.object(bare_launch, "_omh_tui_blocker", return_value=""), \
                patch.object(bare_launch, "_installer_generation", return_value=installer):
            returncode = bare_launch._run_terminal(str(hermes), bare_launch_args([]),
                                                   resolve_paths(str(root / "omh"), str(root / "h")), closed, relaunch)
        self.assertEqual(closed, [("s-1", str(root), ())])
        return returncode, relaunch

    @unittest.skipIf(os.name == "nt", "fixture executable uses a POSIX shebang")
    def test_the_exit_and_the_marker_together_ask_for_the_relaunch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, relaunch = self.run_terminal(root, code=launch.RELAUNCH_EXIT, marker=True, installer=root / "omh-root")
            self.assertEqual((code, relaunch), (launch.RELAUNCH_EXIT, [(root / "omh-root", launch.UPDATED_PLAIN)]))
            self.assertTrue(json.loads((root / "env.json").read_text()).endswith("relaunch"))

    @unittest.skipIf(os.name == "nt", "fixture executable uses a POSIX shebang")
    def test_what_the_marker_holds_goes_on_to_the_relaunch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _code, relaunch = self.run_terminal(root, code=launch.RELAUNCH_EXIT, marker=True, installer=root,
                                                holds=launch.UPDATED_PLAN)
            self.assertEqual(relaunch, [(root, launch.UPDATED_PLAN)])

    @unittest.skipIf(os.name == "nt", "fixture executable uses a POSIX shebang")
    def test_a_78_without_the_marker_is_an_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(self.run_terminal(root, code=launch.RELAUNCH_EXIT, marker=False, installer=root),
                             (launch.RELAUNCH_EXIT, []))

    @unittest.skipIf(os.name == "nt", "fixture executable uses a POSIX shebang")
    def test_off_an_installer_generation_no_marker_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(self.run_terminal(root, code=0, marker=False, installer=None), (0, []))
            self.assertIsNone(json.loads((root / "env.json").read_text()))

    def test_the_relaunch_resumes_the_session_on_the_current_generation_with_this_launchs_options(self) -> None:
        args = bare_launch_args(["--omh-home", "/o", "--hermes-home", "/h", "-p", "kami", "--continue"])
        with patch.object(bare_launch, "_nothing_said", return_value=False):
            argv = bare_launch._relaunch_argv(args, ("s-1", "/h", ()))
        self.assertEqual(argv, ["--omh-home", "/o", "--hermes-home", "/h", "--profile", "kami", "--resume", "s-1"])
        command = self_update.current_omh_cli(Path("/root"), *argv)
        python = self_update._python(Path("/root/current"), self_update.SelfUpdatePlatform.host())
        self.assertEqual(command[:4], [python, "-P", "-m", "omh.cli"])

    def test_a_session_nothing_was_said_in_or_none_recorded_opens_a_new_one(self) -> None:
        args = bare_launch_args([])
        with patch.object(bare_launch, "_nothing_said", return_value=True):
            self.assertEqual(bare_launch._relaunch_argv(args, ("s-1", "/h", ())), [])
        self.assertEqual(bare_launch._relaunch_argv(args, ("", "", ())), [])

    def test_the_relaunched_omh_is_told_it_follows_an_update_and_prints_the_card_itself(self) -> None:
        args = bare_launch_args([])
        with patch.object(bare_launch, "_run_startup_update_check"), \
                patch.object(bare_launch, "stdin_is_tty", return_value=True), \
                patch.object(sys.stdout, "isatty", return_value=True), \
                patch("shutil.which", return_value="/bin/hermes"), \
                patch.object(bare_launch, "_run_terminal",
                             side_effect=lambda hermes, a, paths, closed, relaunch: (
                                 closed.append(("s-1", "/h", ())), relaunch.append((Path("/root/generations/old"), launch.UPDATED_PLAN)),
                                 launch.RELAUNCH_EXIT)[-1]), \
                patch.object(bare_launch, "_nothing_said", return_value=False), \
                patch.object(bare_launch, "_print_exit_card") as card, \
                patch.object(generation_hold, "hold_running_generation", lambda prefix: nullcontext()), \
                patch.object(bare_launch.subprocess, "Popen") as popen:
            popen.return_value.wait.return_value = 0
            self.assertEqual(bare_launch._launch_hermes_tui(args), 0)
        card.assert_not_called()
        (call,) = popen.call_args_list
        self.assertEqual(call.args[0][-2:], ["--resume", "s-1"])
        self.assertEqual(call.kwargs["env"][launch.UPDATED_ENV], launch.UPDATED_PLAN)

    def test_an_installed_generation_that_cannot_start_says_how_to_resume(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(bare_launch.subprocess, "Popen", side_effect=OSError("missing")), \
                patch.object(bare_launch, "_nothing_said", return_value=False), patch("sys.stderr", stderr):
            generation = Path(tmp) / "generations" / "old"
            (generation / "venv").mkdir(parents=True)
            self.assertEqual(bare_launch._relaunch_installed(bare_launch_args([]), generation, ("s-1", "/h", ())), 1)
        self.assertIn("run `omh --resume s-1`", stderr.getvalue())

    def test_a_new_omh_that_ended_in_failure_leaves_the_way_back(self) -> None:
        for code, said in ((1, True), (0, False), (130, False)):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                stderr = io.StringIO()
                generation = Path(tmp) / "generations" / "old"
                (generation / "venv").mkdir(parents=True)
                with patch.object(bare_launch.subprocess, "Popen") as popen, \
                        patch.object(bare_launch, "_nothing_said", return_value=False), patch("sys.stderr", stderr):
                    popen.return_value.wait.return_value = code
                    self.assertEqual(
                        bare_launch._relaunch_installed(bare_launch_args([]), generation, ("s-1", "/h", ())), code)
                self.assertEqual("run `omh --resume s-1`" in stderr.getvalue(), said)

    def test_the_relaunch_argv_is_a_bare_launch_the_new_omh_reads_back(self) -> None:
        args = bare_launch_args(["--omh-home", "/o", "--hermes-home", "/h", "--scope", "user", "-p", "kami"])
        with patch.object(bare_launch, "_nothing_said", return_value=False):
            again = bare_launch_args(bare_launch._relaunch_argv(args, ("s-1", "/h", ())))
        self.assertEqual((again.omh_home, again.hermes_home, again.scope, again.tui_profile, again.tui_resume),
                         ("/o", "/h", "user", "kami", "s-1"))

    def test_the_waiting_omh_holds_its_own_generation_not_the_one_current_names(self) -> None:
        from omh.install.generation_hold import held_generations

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            old = root / "generations" / "old"
            (old / "venv").mkdir(parents=True)
            during: list[set[str]] = []

            def wait() -> int:
                during.append(held_generations(root))
                return 0

            with patch.object(bare_launch, "_nothing_said", return_value=False), \
                    patch.object(bare_launch.subprocess, "Popen") as popen:
                popen.return_value.wait.side_effect = wait
                self.assertEqual(bare_launch._relaunch_installed(bare_launch_args([]), old, ("s-1", "/h", ())), 0)
            self.assertEqual(during, [{"old"}])
            self.assertEqual(held_generations(root), set())
            python = self_update._python(root / "current", self_update.SelfUpdatePlatform.host())
            self.assertEqual(popen.call_args.args[0][0], python)


if __name__ == "__main__":
    unittest.main()
