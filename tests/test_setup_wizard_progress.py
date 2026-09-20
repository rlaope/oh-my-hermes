"""`[k/n]` framing for the interactive setup wizard's question phase.

The apply phase has narrated itself since it shipped (`[1/5] Installing OMH
workflows...`); the question phase that runs before it printed a header and
then fired unrelated questions back to back. These tests cover the framing and,
more importantly, the number it carries: `n` is a claim about how many
questions this machine is about to ask, so every case here compares the printed
headings against the prompts that actually appeared rather than against a
constant written next to them.

Several groups skip themselves -- a config that is already TUI plus an OMH
skin, no external coding CLI on PATH, nothing to offer as a provider, no
terminal, no `--with-mcp`. A total that counted those would be a lie on most
machines.
"""

from __future__ import annotations

import argparse
import io
import json
import re
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
from omh.maintenance.update_check import (  # noqa: E402
    DEFAULT_UPDATE_CHECK_MODE,
    UPDATE_CHECK_MODES,
    read_update_check_policy,
    update_check_policy_recorded,
    write_update_check_policy,
)

_HEADING = re.compile(r"^\[(\d+)/(\d+)\] (.+)\.\.\.$")

_ALL_DETECTED = {
    profile: {"binary_present": True, "login_marker": "present"} for profile in EXTERNAL_CLI_PROFILES
}
_NONE_DETECTED = {
    profile: {"binary_present": False, "login_marker": "absent"} for profile in EXTERNAL_CLI_PROFILES
}

# A config the TUI identity question has nothing left to ask about.
_BRANDED_CONFIG = "display:\n  interface: tui\n  skin: omh\n"
# A config that still uses the plain CLI interface, so the question is live.
_PLAIN_CONFIG = "display:\n  interface: cli\n"

_STEP_LABEL_KEYS = (
    "wizard_step_tui_identity",
    "wizard_step_maestro_delegation",
    "wizard_step_provider_entitlements",
    "wizard_step_model_chains",
    "wizard_step_mcp_host",
    "wizard_step_update_check",
)


class _WizardHarness:
    """Drive `_run_setup_wizard` against a temporary home with fake prompts."""

    def _paths(self, root: Path):
        args = argparse.Namespace(omh_home=str(root / ".omh"), hermes_home=str(root / ".hermes"), scope=None)
        return setup_module._paths(args)

    def _config(self, paths, text: str) -> None:
        paths.hermes_config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.hermes_config_path.write_text(text, encoding="utf-8")

    def _run_wizard(
        self,
        paths,
        *,
        detected: dict[str, dict[str, object]],
        stdin_tty: bool,
        with_mcp: bool,
        provider_candidates: list[tuple[str, str, str]] | None = None,
        update_check_answer: str = "off",
    ) -> tuple[argparse.Namespace, list[tuple[int, int, str]], list[str], str]:
        """Drive the wizard with every prompt recorded instead of displayed.

        Returns the namespace, the parsed `[k/n] label` headings, the prompt
        titles the question groups actually raised, and the raw output. Each
        group's opening prompt is answered so that the group stops there, so a
        recorded prompt is one group having spoken.
        """
        args = argparse.Namespace(
            profile=[],
            profile_pack=[],
            default_executor=None,
            with_mcp=with_mcp,
            mcp_host="generic",
        )
        prompts: list[str] = []

        def yes_no(prompt, **_kwargs):
            prompts.append(prompt)
            return False

        def multi_choice(title, *_args, **_kwargs):
            prompts.append(title)
            return [setup_module._PROVIDER_SKIP_CHOICE]

        def single_choice(title, *_args, **_kwargs):
            prompts.append(title)
            # One fake cannot answer two different questions with one value:
            # the MCP host question takes a host name and the update-check
            # question takes a mode, and the latter is validated on write.
            if title == tr("en", "update_check_title"):
                return update_check_answer
            return "generic"

        stream = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch.object(setup_module, "_detect_external_cli_profiles", return_value=detected))
            stack.enter_context(patch.object(setup_module, "_stdin_is_tty", return_value=stdin_tty))
            stack.enter_context(patch.object(setup_module, "_ask_yes_no", side_effect=yes_no))
            stack.enter_context(patch.object(setup_module, "_ask_multi_choice", side_effect=multi_choice))
            stack.enter_context(patch.object(setup_module, "_ask_single_choice", side_effect=single_choice))
            if provider_candidates is not None:
                stack.enter_context(
                    patch.object(setup_module, "_provider_candidates", return_value=provider_candidates)
                )
            stack.enter_context(redirect_stdout(stream))
            setup_module._run_setup_wizard(args, paths, "en")
        output = stream.getvalue()
        headings = [
            (int(match.group(1)), int(match.group(2)), match.group(3))
            for match in (_HEADING.match(line) for line in output.splitlines())
            if match
        ]
        return args, headings, prompts, output


class WizardProgressTests(_WizardHarness, unittest.TestCase):
    def test_every_group_running_numbers_one_through_six(self) -> None:
        """All six groups ask, so the headings run `[1/6]` to `[6/6]`."""
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            self._config(paths, _PLAIN_CONFIG)
            args, headings, prompts, _output = self._run_wizard(
                paths, detected=_ALL_DETECTED, stdin_tty=True, with_mcp=True
            )
            self.assertEqual([index for index, _total, _label in headings], [1, 2, 3, 4, 5, 6])
            self.assertEqual({total for _index, total, _label in headings}, {6})
            self.assertEqual(
                [label for _index, _total, label in headings],
                [tr("en", key) for key in _STEP_LABEL_KEYS],
            )
            # The count is the questions, not the groups that might have run:
            # each group stopped at its opening prompt, so one prompt is one
            # group having spoken.
            self.assertEqual(
                prompts,
                [
                    tr("en", "tui_identity_prompt"),
                    tr("en", "maestro_delegation_prompt", clis=", ".join(EXTERNAL_CLI_PROFILES)),
                    tr("en", "provider_select_title"),
                    tr("en", "model_chains_interview_prompt"),
                    tr("en", "mcp_host_title"),
                    tr("en", "update_check_title"),
                ],
            )
            self.assertEqual(len(headings), len(prompts))
            self.assertEqual(args.mcp_host, "generic")

    def test_a_group_that_skips_itself_is_not_counted(self) -> None:
        """A branded config and no `--with-mcp` leave four questions, numbered 1..4."""
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            self._config(paths, _BRANDED_CONFIG)
            args, headings, prompts, output = self._run_wizard(
                paths, detected=_ALL_DETECTED, stdin_tty=True, with_mcp=False
            )
            self.assertEqual([index for index, _total, _label in headings], [1, 2, 3, 4])
            self.assertEqual({total for _index, total, _label in headings}, {4})
            self.assertEqual(
                [label for _index, _total, label in headings],
                [
                    tr("en", "wizard_step_maestro_delegation"),
                    tr("en", "wizard_step_provider_entitlements"),
                    tr("en", "wizard_step_model_chains"),
                    tr("en", "wizard_step_update_check"),
                ],
            )
            self.assertEqual(len(headings), len(prompts))
            # The two skipped groups left neither a heading nor a question.
            self.assertNotIn(tr("en", "wizard_step_tui_identity"), output)
            self.assertNotIn(tr("en", "wizard_step_mcp_host"), output)
            self.assertNotIn(tr("en", "tui_identity_prompt"), prompts)
            self.assertFalse(hasattr(args, "_omh_tui_choice"))

    def test_nothing_to_ask_prints_no_headings(self) -> None:
        """Every group silent prints nothing, and each skip records what it always did."""
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            self._config(paths, _BRANDED_CONFIG)
            # The update-check question is settled by a recorded answer, not
            # by the machine: this home has one, so the group is silent.
            write_update_check_policy(paths, mode="off")
            args, headings, prompts, output = self._run_wizard(
                paths,
                detected=_NONE_DETECTED,
                stdin_tty=False,
                with_mcp=False,
                provider_candidates=[],
            )
            self.assertEqual(headings, [])
            self.assertEqual(prompts, [])
            self.assertNotIn("[1/", output)
            self.assertFalse(hasattr(args, "_omh_tui_choice"))
            self.assertIsNone(args._maestro_delegation_choice)
            self.assertIsNone(args._provider_entitlements)
            self.assertIsNone(args._model_chains_interview_choice)
            self.assertIsNone(args._update_check_mode)
            # Silent means silent: the recorded answer is still the one the
            # home had before the wizard ran.
            self.assertEqual(read_update_check_policy(paths)["mode"], "off")

    def test_planned_groups_match_the_groups_that_speak(self) -> None:
        """The plan is the predicates; the predicates are what the groups return early on."""
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            self._config(paths, _BRANDED_CONFIG)
            args = argparse.Namespace(with_mcp=False, mcp_host="generic", profile=[], profile_pack=[], default_executor=None)
            with patch.object(setup_module, "_detect_external_cli_profiles", return_value=_ALL_DETECTED), patch.object(
                setup_module, "_stdin_is_tty", return_value=True
            ):
                planned = setup_module._planned_wizard_questions(args, paths)
            self.assertEqual(
                [question.key for question in planned],
                ["maestro_delegation", "provider_entitlements", "model_chains", "update_check"],
            )

    def test_question_headings_do_not_pay_the_apply_phase_settle(self) -> None:
        """A heading over a question skips `_brief_tty_pause`, and still renders the same.

        The 40ms settle makes a line readable when more output lands on it
        immediately, which is the apply phase. A question heading is followed
        by a prompt that waits for a person, so it buys nothing -- and
        `_read_tui_key` flushes the input queue on every read (#1778), so
        delay added before a menu's first read is a window in which a
        keypress is silently discarded.
        """
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            self._config(paths, _PLAIN_CONFIG)
            with patch.object(setup_module._HumanProgress, "_brief_tty_pause") as pause:
                _args, headings, _prompts, _output = self._run_wizard(
                    paths, detected=_ALL_DETECTED, stdin_tty=True, with_mcp=True
                )
            self.assertEqual(len(headings), 6)
            pause.assert_not_called()

        # Not vacuous: the same renderer still settles for an apply-phase step,
        # so this fails if the call is removed from `step` rather than from the
        # wizard's use of it.
        with patch.object(setup_module._HumanProgress, "_brief_tty_pause") as pause:
            setup_module._HumanProgress(enabled=True, use_color=False).step(1, 5, "Installing")
        pause.assert_called_once()

        # Identical line either way: dropping the settle must not become a
        # second visual style for the same heading.
        rendered = []
        for keep_pause in (True, False):
            stream = io.StringIO()
            with patch.object(setup_module._HumanProgress, "_brief_tty_pause"), redirect_stdout(stream):
                setup_module._HumanProgress(enabled=True, use_color=False).step(
                    2, 4, "Choosing how Hermes looks", pause=keep_pause
                )
            rendered.append(stream.getvalue())
        self.assertEqual(rendered[0], rendered[1])
        self.assertEqual(rendered[0], "[2/4] Choosing how Hermes looks...\n")

    def test_group_labels_exist_in_every_language(self) -> None:
        for key in _STEP_LABEL_KEYS:
            for code in LANGUAGE_CODES:
                with self.subTest(key=key, language=code):
                    self.assertIn(key, MESSAGES[code])
                    self.assertTrue(MESSAGES[code][key].strip())

    def test_every_group_label_key_is_a_real_message(self) -> None:
        """Re-derive the label keys from the registry instead of restating them."""
        self.assertEqual(
            tuple(question.label_key for question in setup_module._wizard_question_groups()),
            _STEP_LABEL_KEYS,
        )
        for question in setup_module._wizard_question_groups():
            self.assertIn(question.label_key, MESSAGES["en"])


class UpdateCheckQuestionTests(_WizardHarness, unittest.TestCase):
    """The one wizard question about the install rather than about the assistant.

    `omh update-check set --mode off|notify|auto` has shipped for a while,
    default `off`, and the only way to find it was to already know its name.
    This question surfaces it. The boundary it must not cross is the shipped
    default: nothing here changes what a non-interactive install does, which
    is why every answer -- including `off` -- is written, and why `off` is
    what Enter selects.
    """

    def _ask_once(self, paths, answer: str):
        self._config(paths, _BRANDED_CONFIG)
        return self._run_wizard(
            paths,
            detected=_NONE_DETECTED,
            stdin_tty=False,
            with_mcp=False,
            provider_candidates=[],
            update_check_answer=answer,
        )

    def test_each_answer_writes_the_matching_policy(self) -> None:
        for mode in UPDATE_CHECK_MODES:
            with self.subTest(mode=mode), TemporaryDirectory() as tmp:
                paths = self._paths(Path(tmp))
                args, headings, prompts, output = self._ask_once(paths, mode)
                # Every other group is silenced here, so this is the only
                # question and the only heading.
                self.assertEqual(prompts, [tr("en", "update_check_title")])
                self.assertEqual([label for _i, _n, label in headings], [tr("en", "wizard_step_update_check")])
                self.assertEqual(args._update_check_mode, mode)
                self.assertEqual(read_update_check_policy(paths)["mode"], mode)
                self.assertTrue(update_check_policy_recorded(paths))
                self.assertIn(tr("en", "update_check_recorded", mode=mode), output)

    def test_answering_off_settles_the_question_the_same_as_any_other_answer(self) -> None:
        """The record is the answer, not the deviation from the default.

        This is the whole reason the predicate reads
        `update_check_policy_recorded` rather than the resolved policy: both
        say `off` here, and only one of them can tell a second run that the
        question was already put.
        """
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            _args, headings, prompts, _output = self._ask_once(paths, "off")
            self.assertEqual(len(prompts), 1)
            self.assertEqual(len(headings), 1)
            self.assertEqual(read_update_check_policy(paths)["mode"], "off")

            args, headings, prompts, output = self._ask_once(paths, "off")
            self.assertEqual(prompts, [])
            self.assertEqual(headings, [])
            self.assertNotIn(tr("en", "wizard_step_update_check"), output)
            self.assertIsNone(args._update_check_mode)

    def _captured_menu(self, paths) -> dict[str, object]:
        """Run the question once, returning the menu `_ask_single_choice` was handed."""
        captured: dict[str, object] = {}

        def single_choice(title, intro_lines, options, *, default_choice, **_kwargs):
            captured.update(title=title, intro_lines=intro_lines, options=options, default_choice=default_choice)
            return DEFAULT_UPDATE_CHECK_MODE

        args = argparse.Namespace()
        with patch.object(setup_module, "_ask_single_choice", side_effect=single_choice), redirect_stdout(io.StringIO()):
            setup_module._ask_update_check_choice(args, paths, "en")
        return captured

    def test_the_preselected_option_is_the_shipped_default(self) -> None:
        """Enter lands where a `--yes` install lands, and makes no network request."""
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            captured = self._captured_menu(paths)
            options = captured["options"]
            preselected = next(
                option["value"] for option in options if option["choice"] == captured["default_choice"]
            )
            self.assertEqual(preselected, DEFAULT_UPDATE_CHECK_MODE)
            self.assertEqual(preselected, "off")

    def test_the_offered_modes_are_the_mode_vocabulary_in_order(self) -> None:
        """The rows come from `UPDATE_CHECK_MODES`, so a fourth mode cannot be silently unoffered."""
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            options = self._captured_menu(paths)["options"]
            self.assertEqual([option["value"] for option in options], list(UPDATE_CHECK_MODES))
            self.assertEqual([option["choice"] for option in options], ["1", "2", "3"])
            for option in options:
                self.assertTrue(option["label"].strip())
                self.assertTrue(option["description"].strip())

    def test_the_question_states_the_network_and_the_install_consequence(self) -> None:
        """Both facts the brief requires, in every language rather than only English.

        `notify` and `auto` each make a GitHub request at most once per
        interval, and `auto` additionally installs. A question that named
        neither would be asking for consent to something unstated.
        """
        for code in LANGUAGE_CODES:
            with self.subTest(language=code):
                intro = tr(code, "update_check_intro")
                self.assertIn("GitHub", intro)
                self.assertIn("24", intro)
                self.assertIn("omh update-check set", intro)
                # The mode that installs says it installs; the mode that only
                # reports says the install is still yours to run.
                self.assertIn("omh update", tr(code, "update_check_mode_auto_desc"))
                self.assertIn("omh update", tr(code, "update_check_mode_notify_desc"))
                # And the mode Enter selects promises the absence of the
                # request the other two make.
                self.assertTrue(tr(code, "update_check_mode_off_desc").strip())

    def test_every_mode_has_a_label_and_a_description_in_every_language(self) -> None:
        for mode in UPDATE_CHECK_MODES:
            for code in LANGUAGE_CODES:
                for key in (f"update_check_mode_{mode}", f"update_check_mode_{mode}_desc"):
                    with self.subTest(mode=mode, language=code, key=key):
                        self.assertIn(key, MESSAGES[code])
                        self.assertTrue(MESSAGES[code][key].strip())


class NonInteractiveRunTests(unittest.TestCase):
    """`--yes`, `--json`, and a run without a terminal print none of the framing.

    They also write no update-check policy. That is the boundary of the whole
    change: the shipped default stays `off`, so an install nobody was asked
    about must leave the key absent rather than record an answer on their
    behalf -- an absent key is what keeps the question askable later.
    """

    def _base(self, root: Path) -> list[str]:
        return ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

    def _assert_no_question_headings(self, stdout: str) -> None:
        for key in _STEP_LABEL_KEYS:
            self.assertNotIn(tr("en", key), stdout)

    def _assert_no_update_check_answer(self, root: Path) -> None:
        paths = setup_module._paths(
            argparse.Namespace(omh_home=str(root / ".omh"), hermes_home=str(root / ".hermes"), scope=None)
        )
        self.assertFalse(update_check_policy_recorded(paths))
        profile = json.loads(paths.setup_profile_path.read_text(encoding="utf-8"))
        self.assertNotIn("update_check", profile)
        self.assertEqual(read_update_check_policy(paths)["mode"], DEFAULT_UPDATE_CHECK_MODE)

    def test_yes_run_prints_the_apply_phase_only(self) -> None:
        with TemporaryDirectory() as tmp:
            status, stdout, stderr = run_cli(self._base(Path(tmp)) + ["setup", "--yes"], output_json=False)
            self.assertEqual(status, 0, stderr)
            # The apply phase still narrates itself -- this is about the
            # question phase alone.
            self.assertIn(tr("en", "step_install_skills"), stdout)
            self._assert_no_question_headings(stdout)
            self._assert_no_update_check_answer(Path(tmp))

    def test_json_run_prints_no_headings(self) -> None:
        with TemporaryDirectory() as tmp:
            status, stdout, stderr = run_cli(self._base(Path(tmp)) + ["setup", "--json"], output_json=True)
            self.assertEqual(status, 0, stderr)
            self._assert_no_question_headings(stdout)
            self._assert_no_update_check_answer(Path(tmp))

    def test_plain_run_without_a_terminal_prints_no_headings(self) -> None:
        with TemporaryDirectory() as tmp:
            status, stdout, stderr = run_cli(self._base(Path(tmp)) + ["setup"], output_json=False)
            self.assertEqual(status, 0, stderr)
            self._assert_no_question_headings(stdout)
            self._assert_no_update_check_answer(Path(tmp))


if __name__ == "__main__":
    unittest.main()
