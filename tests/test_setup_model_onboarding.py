"""The setup wizard's last question: open the model-setup conversation in the OMH TUI.

Asked only where that conversation can open (both terminal ends, not Windows,
`hermes` on PATH, nothing blocking the OMH TUI). Where it is asked, the
model-chains question stays silent. A Yes on a setup that succeeded runs the
person's `hermes model` first when Hermes has no main model, then opens
`omh --onboard model-setup`. Nothing is spawned here: every process seam is
replaced with a recorder.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.coding.executors import EXTERNAL_CLI_PROFILES  # noqa: E402
from omh.commands import setup as setup_module  # noqa: E402
from omh.commands.language import LANGUAGE_CODES, MESSAGES, tr  # noqa: E402
from omh.maintenance.update_check import write_update_check_policy  # noqa: E402

_NONE_DETECTED = {
    profile: {"binary_present": False, "login_marker": "absent"} for profile in EXTERNAL_CLI_PROFILES
}
_HERMES = "/fake/bin/hermes"


def _paths(root: Path):
    args = argparse.Namespace(omh_home=str(root / ".omh"), hermes_home=str(root / ".hermes"), scope=None)
    return setup_module._paths(args)


def _machine(stack: ExitStack, *, stdin=True, stdout=True, platform="darwin", hermes=_HERMES, blocker="") -> None:
    stack.enter_context(patch.object(setup_module, "_stdin_is_tty", return_value=stdin))
    stack.enter_context(patch.object(setup_module, "_stdout_is_tty", return_value=stdout))
    stack.enter_context(patch.object(setup_module.sys, "platform", platform))
    stack.enter_context(patch.object(setup_module.shutil, "which", return_value=hermes))
    stack.enter_context(patch("omh.tui.launch.omh_tui_blocker", return_value=blocker))


class _FakeRun:
    """`subprocess.run` stand-in: answers `hermes config get model` from a script of values."""

    def __init__(self, models: list[object]) -> None:
        self.models = list(models)
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[1:] == ["config", "get", "model", "--json"]:
            value = self.models.pop(0)
            if value is None:
                return subprocess.CompletedProcess(argv, 1, "", "Config key not set: model")
            return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")
        return subprocess.CompletedProcess(argv, 0, None, None)


class AskedMatrixTests(unittest.TestCase):
    def test_asked_only_where_the_conversation_can_open(self) -> None:
        cases = (
            ({}, True),
            ({"stdin": False}, False),
            ({"stdout": False}, False),
            ({"platform": "win32"}, False),
            ({"hermes": None}, False),
            ({"blocker": "TERM=dumb cannot draw the OMH TUI"}, False),
        )
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            for machine, expected in cases:
                with self.subTest(**{k: str(v) for k, v in machine.items()}), ExitStack() as stack:
                    _machine(stack, **machine)
                    self.assertIs(setup_module._will_ask_model_onboarding(argparse.Namespace(), paths), expected)

    def test_group_is_last_and_defaults_to_yes(self) -> None:
        groups = setup_module._wizard_question_groups()
        self.assertEqual(groups[-1].key, "model_onboarding")
        self.assertEqual(groups[-1].label_key, "wizard_step_model_onboarding")
        with TemporaryDirectory() as tmp, ExitStack() as stack:
            paths = _paths(Path(tmp))
            _machine(stack)
            ask = stack.enter_context(patch.object(setup_module, "_ask_yes_no", return_value=True))
            args = argparse.Namespace()
            setup_module._ask_model_onboarding_choice(args, paths, "en")
            setup_module._ask_model_onboarding_choice(args, paths, "en")
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(ask.call_args.args[0], tr("en", "model_onboarding_prompt"))
        self.assertTrue(ask.call_args.kwargs["default"])
        self.assertEqual(ask.call_args.kwargs["note"], tr("en", "model_onboarding_note"))
        self.assertTrue(args._model_onboarding_choice)

    def test_not_asked_records_none(self) -> None:
        with TemporaryDirectory() as tmp, ExitStack() as stack:
            paths = _paths(Path(tmp))
            _machine(stack, platform="win32")
            ask = stack.enter_context(patch.object(setup_module, "_ask_yes_no"))
            args = argparse.Namespace()
            setup_module._ask_model_onboarding_choice(args, paths, "en")
        ask.assert_not_called()
        self.assertIsNone(args._model_onboarding_choice)

    def test_model_chains_suppressed_only_when_onboarding_is_asked(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            for machine, chains in (({}, False), ({"platform": "win32"}, True), ({"blocker": "no Node"}, True),
                                    ({"hermes": None}, True), ({"stdin": False}, False)):
                with self.subTest(**{k: str(v) for k, v in machine.items()}), ExitStack() as stack:
                    _machine(stack, **machine)
                    args = argparse.Namespace()
                    self.assertIs(setup_module._will_ask_model_chains_interview(args, paths), chains)

    def test_wizard_plan_ends_with_onboarding_and_drops_chains(self) -> None:
        with TemporaryDirectory() as tmp, ExitStack() as stack:
            paths = _paths(Path(tmp))
            _machine(stack)
            stack.enter_context(patch.object(setup_module, "_detect_external_cli_profiles", return_value=_NONE_DETECTED))
            stack.enter_context(patch.object(setup_module, "_provider_candidates", return_value=[]))
            prompts: list[str] = []
            stack.enter_context(patch.object(
                setup_module, "_ask_yes_no", side_effect=lambda prompt, **_k: prompts.append(prompt) or True))
            stack.enter_context(patch.object(
                setup_module, "_ask_single_choice", side_effect=lambda title, *_a, **_k: prompts.append(title) or "off"))
            args = argparse.Namespace(profile=[], profile_pack=[], default_executor=None, with_mcp=False,
                                      mcp_host="generic")
            out = io.StringIO()
            with redirect_stdout(out):
                setup_module._run_setup_wizard(args, paths, "en")
        self.assertEqual(prompts, [tr("en", "update_check_title"), tr("en", "model_onboarding_prompt")])
        self.assertIn("[2/2] " + tr("en", "wizard_step_model_onboarding"), out.getvalue())
        self.assertIsNone(args._model_chains_interview_choice)
        self.assertTrue(args._model_onboarding_choice)

    def test_suppressing_flags_never_ask_or_launch(self) -> None:
        for flags in (["--yes"], ["--json"], ["--dry-run"], ["--no-interactive"]):
            with self.subTest(flags=flags), TemporaryDirectory() as tmp, ExitStack() as stack:
                root = Path(tmp)
                _machine(stack)
                ask = stack.enter_context(patch.object(setup_module, "_ask_yes_no"))
                launch = stack.enter_context(patch.object(setup_module, "_launch_model_onboarding"))
                status, _out, stderr = run_cli(
                    ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"), "setup", *flags],
                    output_json=False,
                )
                self.assertEqual(status, 0, stderr)
                ask.assert_not_called()
                launch.assert_not_called()

    def test_strings_exist_in_every_language(self) -> None:
        keys = ("wizard_step_model_onboarding", "model_onboarding_prompt", "model_onboarding_note",
                "model_onboarding_running_hermes_model", "model_onboarding_no_model", "model_onboarding_later")
        for code in LANGUAGE_CODES:
            for key in keys:
                with self.subTest(language=code, key=key):
                    self.assertTrue(MESSAGES[code][key].strip())
            self.assertIn("`omh`", MESSAGES[code]["model_onboarding_note"])
            self.assertIn("`hermes model`", MESSAGES[code]["model_onboarding_running_hermes_model"])


class LaunchTests(unittest.TestCase):
    def _launch(self, paths, models: list[object], language: str = "en"):
        run = _FakeRun(models)
        execs: list[tuple[list[str], dict[str, str]]] = []
        out = io.StringIO()
        with patch.object(setup_module.shutil, "which", return_value=_HERMES), redirect_stdout(out):
            result = setup_module._launch_model_onboarding(
                paths, language, run=run, exec_=lambda argv, env: execs.append((argv, env)) or 0
            )
        return result, run.calls, execs, out.getvalue()

    def test_yes_with_a_main_model_opens_onboarding_with_the_exact_argv(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            result, calls, execs, _out = self._launch(paths, [{"provider": "p", "default": "m"}], "ko")
        self.assertEqual(result, 0)
        self.assertEqual(calls, [[_HERMES, "config", "get", "model", "--json"]])
        self.assertEqual(len(execs), 1)
        argv, env = execs[0]
        self.assertEqual(argv, [sys.executable, "-P", "-m", "omh.cli", "--omh-home", str(paths.omh_home),
                                "--hermes-home", str(paths.hermes_home), "--onboard", "model-setup"])
        self.assertEqual(env["OMH_LANG"], "ko")

    def test_no_main_model_runs_hermes_model_then_opens_when_one_appears(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            result, calls, execs, out = self._launch(paths, [None, {"default": "m"}])
        self.assertEqual(result, 0)
        self.assertEqual(calls[1], [_HERMES, "model"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(execs), 1)
        self.assertIn(tr("en", "model_onboarding_running_hermes_model"), out)

    def test_no_main_model_after_hermes_model_opens_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            result, calls, execs, out = self._launch(paths, [{"default": ""}, {"provider": "p"}])
        self.assertIsNone(result)
        self.assertEqual(calls[1], [_HERMES, "model"])
        self.assertEqual(execs, [])
        self.assertIn(tr("en", "model_onboarding_no_model"), out)


class FinishTests(unittest.TestCase):
    def _finish(self, choice, exit_code: int):
        args = argparse.Namespace(_model_onboarding_choice=choice)
        out = io.StringIO()
        with TemporaryDirectory() as tmp, patch.object(
            setup_module, "_launch_model_onboarding", return_value=0
        ) as launch, redirect_stdout(out):
            result = setup_module._finish_model_onboarding(args, _paths(Path(tmp)), "en", exit_code)
        return result, launch, out.getvalue()

    def test_yes_on_success_launches(self) -> None:
        result, launch, _out = self._finish(True, 0)
        self.assertEqual(result, 0)
        launch.assert_called_once()

    def test_no_prints_the_hint_and_launches_nothing(self) -> None:
        result, launch, out = self._finish(False, 0)
        self.assertIsNone(result)
        launch.assert_not_called()
        self.assertIn(tr("en", "model_onboarding_later"), out)

    def test_failed_setup_never_launches(self) -> None:
        for code in (1, 3):
            result, launch, _out = self._finish(True, code)
            self.assertIsNone(result)
            launch.assert_not_called()

    def test_not_asked_does_nothing(self) -> None:
        result, launch, out = self._finish(None, 0)
        self.assertIsNone(result)
        launch.assert_not_called()
        self.assertEqual(out, "")

    def test_interactive_setup_yes_reaches_the_launch_after_the_summary(self) -> None:
        with TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            paths = _paths(root)
            write_update_check_policy(paths, mode="off")
            _machine(stack)
            stack.enter_context(patch.object(setup_module, "_detect_external_cli_profiles", return_value=_NONE_DETECTED))
            stack.enter_context(patch.object(setup_module, "_provider_candidates", return_value=[]))
            stack.enter_context(patch.object(setup_module, "_wizard_has_terminal", return_value=True))
            stack.enter_context(patch.object(setup_module, "_ask_yes_no", return_value=True))
            launch = stack.enter_context(patch.object(setup_module, "_launch_model_onboarding", return_value=0))
            status, out, stderr = run_cli(
                ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"), "setup",
                 "--interactive", "--scope", "user", "--no-menubar"],
                output_json=False,
            )
        self.assertEqual(status, 0, stderr)
        launch.assert_called_once()
        self.assertEqual(launch.call_args.args[1], "en")
        self.assertIn(tr("en", "setup_complete"), out)


if __name__ == "__main__":
    unittest.main()
