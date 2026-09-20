"""Contracts for `omh model-chains` — the supported editor over the
mixture chain override document.

show prints the effective per-category state with origins; set writes one
category through the same validation the plugin reader enforces and --clear
returns it to the shipped default; interview walks every category with
numbered options on a terminal and refuses (with the scriptable path) on a
pipe. Every path converges on `<omh-home>/routing/model-chains.json`.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli

from omh.commands.model_chains import _ultrafast_variant
from omh.plugin_bundle.omh.hermes_delegation import HERMES_MIXTURE_CATEGORY_CHAINS


def _base(root: Path) -> list[str]:
    return ["--omh-home", str(root / ".omh")]


def _chains_path(root: Path) -> Path:
    return root / ".omh" / "routing" / "model-chains.json"


class ModelChainsShowTests(unittest.TestCase):
    def test_show_lists_every_category_with_default_origin(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, stdout, stderr = run_cli(_base(root) + ["model-chains", "show"], output_json=False)
            self.assertEqual((status, stderr), (0, ""))
            for category in HERMES_MIXTURE_CATEGORY_CHAINS:
                self.assertIn(f"  {category}: ", stdout)
            self.assertIn("[absent]", stdout)
            self.assertNotIn("(override)", stdout)

    def test_show_json_reports_state_schema_and_origins(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, stdout, stderr = run_cli(
                _base(root) + ["model-chains", "show", "--json"], output_json=False
            )
            self.assertEqual((status, stderr), (0, ""))
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "model_chain_state/v1")
            self.assertEqual(
                {row["category"] for row in payload["categories"]},
                set(HERMES_MIXTURE_CATEGORY_CHAINS),
            )
            self.assertTrue(all(row["origin"] == "default" for row in payload["categories"]))


class ModelChainsSetTests(unittest.TestCase):
    def test_set_writes_one_category_and_show_marks_the_override(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, stdout, stderr = run_cli(
                _base(root)
                + ["model-chains", "set", "quick", "kimi-k3-ultrafast:low, glm-5.2-ultrafast:low"],
                output_json=False,
            )
            self.assertEqual((status, stderr), (0, ""))
            self.assertIn("quick: kimi-k3-ultrafast:low, glm-5.2-ultrafast:low (override)", stdout)
            document = json.loads(_chains_path(root).read_text(encoding="utf-8"))
            self.assertEqual(document["schema_version"], "mixture_chain_overrides/v1")
            self.assertEqual(
                document["categories"]["quick"][0],
                {"model": "kimi-k3-ultrafast", "reasoning_effort": "low"},
            )

            status, stdout, _ = run_cli(_base(root) + ["model-chains", "show"], output_json=False)
            self.assertEqual(status, 0)
            self.assertIn("quick: kimi-k3-ultrafast:low, glm-5.2-ultrafast:low (override)", stdout)
            # Untouched categories keep the shipped default.
            self.assertNotIn("architect: claude-fable-5-1:xhigh, gpt-6-astra:xhigh, kimi-k3:xhigh (override)", stdout)

    def test_clear_returns_the_category_to_the_shipped_default(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(_base(root) + ["model-chains", "set", "deep", "gpt-5.6-terra:xhigh"], output_json=False)
            status, stdout, stderr = run_cli(
                _base(root) + ["model-chains", "set", "deep", "--clear"], output_json=False
            )
            self.assertEqual((status, stderr), (0, ""))
            self.assertIn("deep: gpt-5.6-terra:high, deepseek-flash:high (default)", stdout)
            document = json.loads(_chains_path(root).read_text(encoding="utf-8"))
            self.assertNotIn("deep", document["categories"])

    def test_set_refuses_unknown_categories_and_non_token_models(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, _, stderr = run_cli(
                _base(root) + ["model-chains", "set", "warp-drive", "kimi-k3"], output_json=False
            )
            self.assertEqual(status, 2)
            self.assertIn("unknown category", stderr)
            status, _, stderr = run_cli(
                _base(root) + ["model-chains", "set", "quick", "bad model!"], output_json=False
            )
            self.assertEqual(status, 2)
            self.assertIn("not a plain model identifier", stderr)
            self.assertFalse(_chains_path(root).exists())

    def test_set_preserves_other_override_categories(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(_base(root) + ["model-chains", "set", "quick", "kimi-k3-ultrafast:low"], output_json=False)
            run_cli(_base(root) + ["model-chains", "set", "deep", "gpt-5.6-terra:xhigh"], output_json=False)
            document = json.loads(_chains_path(root).read_text(encoding="utf-8"))
            self.assertEqual(set(document["categories"]), {"quick", "deep"})


class ModelChainsInterviewTests(unittest.TestCase):
    def test_interview_refuses_without_a_terminal_and_names_the_scriptable_path(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, _, stderr = run_cli(_base(root) + ["model-chains", "interview"], output_json=False)
            self.assertEqual(status, 2)
            self.assertIn("model-chains set", stderr)

    def test_interview_applies_numbered_choices_and_custom_entry(self) -> None:
        # Category order is the shipped dict order. Without an override the
        # options are 1) keep, [2) Ultrafast when the chain has a swappable
        # member], last) custom. Keep everything except `quick` (Ultrafast)
        # and `writing` (custom entry).
        answers = []
        for name, chain in HERMES_MIXTURE_CATEGORY_CHAINS.items():
            has_ultrafast = any(model in ("glm-5.2", "kimi-k3") for model, _ in chain)
            if name == "quick":
                answers.append("2" if has_ultrafast else "1")
            elif name == "writing":
                answers.extend(["3" if has_ultrafast else "2", "qwen3-coder:high, kimi-k3:high"])
            else:
                answers.append("")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            responses = iter(answers)
            with (
                patch("omh.commands.model_chains._stdin_is_tty", return_value=True),
                patch("builtins.input", side_effect=lambda *_: next(responses)),
            ):
                status, stdout, stderr = run_cli(
                    _base(root) + ["model-chains", "interview"], output_json=False
                )
            self.assertEqual((status, stderr), (0, ""), stdout)
            document = json.loads(_chains_path(root).read_text(encoding="utf-8"))
            self.assertEqual(set(document["categories"]), {"quick", "writing"})
            quick_models = [entry["model"] for entry in document["categories"]["quick"]]
            self.assertIn("kimi-k3-ultrafast", quick_models)
            self.assertNotIn("kimi-k3", quick_models)
            self.assertEqual(
                document["categories"]["writing"],
                [
                    {"model": "qwen3-coder", "reasoning_effort": "high"},
                    {"model": "kimi-k3", "reasoning_effort": "high"},
                ],
            )

    def test_ultrafast_option_never_invents_an_unknown_variant(self) -> None:
        # The offer follows the -ultrafast suffix only when that token is a known
        # model (shipped chains or price table). Since 2026-09-11 no shipped chain
        # names an Ultrafast tier, so the offer rests on the retained price rows
        # (`glm-5.2-ultrafast`, `kimi-k3-ultrafast`). deepseek-v3.2-ultrafast exists
        # in neither source, so no swap is offered; an already-suffixed member never
        # re-swaps.
        self.assertEqual(
            _ultrafast_variant((("glm-5.2", "low"), ("kimi-k3", "high"))),
            (("glm-5.2-ultrafast", "low"), ("kimi-k3-ultrafast", "high")),
        )
        self.assertIsNone(_ultrafast_variant((("deepseek-v3.2", "high"),)))
        self.assertIsNone(_ultrafast_variant((("glm-5.2-ultrafast", "low"),)))


_NO_EXTERNAL_CLI_DETECTED = {
    "claude-code": {"binary_present": False, "login_marker": "absent"},
    "codex": {"binary_present": False, "login_marker": "absent"},
}

_SEEDED_EMPTY_DOCUMENT = {"schema_version": "mixture_chain_overrides/v1", "categories": {}}


class ModelChainsSetupWizardTests(unittest.TestCase):
    """The interactive `omh setup` offer for the native lane's chain walk.

    Mirrors the Maestro lane's inline category offer: default No, asked at
    most once, and never reached by a suppressed run. A "no" must leave the
    document exactly as step 3's empty seed wrote it.
    """

    def _wizard_base(self, root: Path) -> list[str]:
        return ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

    def test_wizard_offers_the_chain_walk_and_a_no_leaves_the_seed_untouched(self) -> None:
        from omh.commands import setup as setup_module

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(
                    setup_module, "_detect_external_cli_profiles", return_value=_NO_EXTERNAL_CLI_DETECTED
                ),
                patch.object(setup_module, "_env_key_names", return_value=set()),
                patch.object(setup_module, "_stdin_is_tty", return_value=True),
                # TUI identity yes, then the chain-walk offer declined. The
                # maestro and provider-entitlement questions have nothing to
                # ask: no CLI is on PATH and a fresh config names no provider.
                patch.object(setup_module, "_ask_yes_no", side_effect=[True, False]) as yes_no,
            ):
                status, stdout, stderr = run_cli(
                    self._wizard_base(root) + ["setup", "--interactive"], output_json=False
                )

            self.assertEqual((status, stderr), (0, ""), stdout)
            self.assertEqual(yes_no.call_count, 2)
            self.assertIn("chains", yes_no.call_args_list[1].args[0].lower())
            self.assertEqual(
                json.loads(_chains_path(root).read_text(encoding="utf-8")),
                _SEEDED_EMPTY_DOCUMENT,
            )

    def test_wizard_yes_reaches_the_interview_with_the_resolved_paths(self) -> None:
        from omh.commands import model_chains as model_chains_module
        from omh.commands import setup as setup_module

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls: list[object] = []
            with (
                patch.object(
                    setup_module, "_detect_external_cli_profiles", return_value=_NO_EXTERNAL_CLI_DETECTED
                ),
                patch.object(setup_module, "_env_key_names", return_value=set()),
                patch.object(setup_module, "_stdin_is_tty", return_value=True),
                patch.object(setup_module, "_ask_yes_no", side_effect=[True, True]),
                patch.object(
                    model_chains_module,
                    "model_chains_interview",
                    side_effect=lambda received: calls.append(received.omh_home.resolve()) or 0,
                ),
            ):
                status, stdout, stderr = run_cli(
                    self._wizard_base(root) + ["setup", "--interactive"], output_json=False
                )

            self.assertEqual((status, stderr), (0, ""), stdout)
            self.assertEqual(calls, [(root / ".omh").resolve()])

    def test_a_wizard_override_survives_the_step_3_seed(self) -> None:
        # The wizard prompts before step 3 runs `_seed_model_chains_result`,
        # so the real risk is the seed overwriting an answer given seconds
        # earlier. It early-returns `already_present`, and the interview
        # creates `routing/` itself, so the override has to come out intact.
        from omh.commands import model_chains as model_chains_module
        from omh.commands import setup as setup_module

        answers = []
        for name, chain in HERMES_MIXTURE_CATEGORY_CHAINS.items():
            has_ultrafast = any(model in ("glm-5.2", "kimi-k3") for model, _ in chain)
            if name == "writing":
                answers.extend(["3" if has_ultrafast else "2", "qwen3-coder:high"])
            else:
                answers.append("")
        # The update-check question follows the interview and reads the same
        # typed prompt; Enter takes its pre-selected shipped default.
        answers.append("")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            responses = iter(answers)
            with (
                patch.object(
                    setup_module, "_detect_external_cli_profiles", return_value=_NO_EXTERNAL_CLI_DETECTED
                ),
                patch.object(setup_module, "_env_key_names", return_value=set()),
                patch.object(setup_module, "_stdin_is_tty", return_value=True),
                patch.object(setup_module, "_ask_yes_no", side_effect=[True, True]),
                patch.object(model_chains_module, "_stdin_is_tty", return_value=True),
                patch("builtins.input", side_effect=lambda *_: next(responses)),
            ):
                status, stdout, stderr = run_cli(
                    self._wizard_base(root) + ["setup", "--interactive"], output_json=False
                )

            self.assertEqual((status, stderr), (0, ""), stdout)
            document = json.loads(_chains_path(root).read_text(encoding="utf-8"))
            self.assertEqual(
                document["categories"],
                {"writing": [{"model": "qwen3-coder", "reasoning_effort": "high"}]},
            )

    def test_wizard_question_needs_a_terminal(self) -> None:
        # `--interactive` forces the wizard on a pipe, but the interview
        # refuses without a terminal, so the offer is skipped rather than
        # asked and then refused into stderr.
        import argparse
        from types import SimpleNamespace

        from omh.commands import setup as setup_module

        with TemporaryDirectory() as tmp:
            paths = SimpleNamespace(omh_home=Path(tmp) / ".omh")
            args = argparse.Namespace()
            with (
                patch.object(setup_module, "_stdin_is_tty", return_value=False),
                patch.object(setup_module, "_ask_yes_no") as yes_no,
            ):
                setup_module._ask_model_chains_interview(args, paths, "en")
            yes_no.assert_not_called()
            self.assertIsNone(args._model_chains_interview_choice)

    def test_this_gate_and_the_keyboard_menu_guard_do_not_interact(self) -> None:
        """The wizard's two terminal guards are deliberately different.

        `_keyboard_menu_available` needs both streams on a terminal (plus
        termios and a real TERM) and is what the provider multi-select and
        `_ask_yes_no` consult to pick a renderer. This offer needs only stdin,
        because stdin is all the interview reads. So a run whose stdin is a
        terminal but whose stdout is piped is still asked -- through the typed
        y/N fallback -- and a yes still reaches the interview. The reverse
        combination cannot make it appear: stdin decides, not the renderer.
        """
        import argparse
        from contextlib import redirect_stdout
        from io import StringIO
        from types import SimpleNamespace

        from omh.commands import model_chains as model_chains_module
        from omh.commands import setup as setup_module

        for stdin_tty, keyboard, expected in (
            (True, False, True),   # typed fallback: asked, and the yes lands
            (True, True, True),    # keyboard menu: same answer, same landing
            (False, True, False),  # no stdin terminal wins over any renderer
            (False, False, False),
        ):
            with self.subTest(stdin_tty=stdin_tty, keyboard_menu=keyboard):
                with TemporaryDirectory() as tmp:
                    paths = SimpleNamespace(omh_home=Path(tmp) / ".omh")
                    args = argparse.Namespace()
                    with (
                        patch.object(setup_module, "_stdin_is_tty", return_value=stdin_tty),
                        patch.object(setup_module, "_keyboard_menu_available", return_value=keyboard),
                        patch.object(setup_module, "_ask_single_choice", return_value="yes"),
                        patch.object(setup_module, "_ask", return_value="y"),
                        patch.object(model_chains_module, "model_chains_interview") as interview,
                        redirect_stdout(StringIO()),
                    ):
                        setup_module._ask_model_chains_interview(args, paths, "en")
                    self.assertEqual(interview.called, expected)
                    self.assertEqual(args._model_chains_interview_choice, expected or None)

    def test_wizard_question_is_asked_at_most_once(self) -> None:
        import argparse
        from types import SimpleNamespace

        from omh.commands import setup as setup_module

        with TemporaryDirectory() as tmp:
            paths = SimpleNamespace(omh_home=Path(tmp) / ".omh")
            args = argparse.Namespace()
            with (
                patch.object(setup_module, "_stdin_is_tty", return_value=True),
                patch.object(setup_module, "_ask_yes_no", return_value=False) as yes_no,
            ):
                setup_module._ask_model_chains_interview(args, paths, "en")
                setup_module._ask_model_chains_interview(args, paths, "en")
            self.assertEqual(yes_no.call_count, 1)
            self.assertFalse(args._model_chains_interview_choice)

    def test_every_suppressor_asks_nothing_and_never_reaches_the_interview(self) -> None:
        import argparse

        from omh.commands import model_chains as model_chains_module
        from omh.commands import setup as setup_module

        # Every entry `_setup_should_interact` names: the two hard
        # suppressors, the two explicit opt-outs, and the whole
        # flag-was-passed list. `--with-menubar` is left out because it starts
        # a macOS helper; its sibling `--no-menubar` proves the same branch.
        for flags in (
            ["--json"],
            ["--dry-run"],
            ["--yes"],
            ["--no-interactive"],
            ["--profile", "safety-first"],
            ["--default-executor", "hermes"],
            ["--profile-pack", "engineering-delivery"],
            ["--with-mcp"],
            ["--memory-mode", "off"],
            ["--no-menubar"],
            ["--skip-apply"],
            ["--scope", "user"],
        ):
            with self.subTest(flags=" ".join(flags)), TemporaryDirectory() as tmp:
                root = Path(tmp)
                with (
                    patch.object(setup_module, "_stdin_is_tty", return_value=True),
                    patch.object(setup_module, "_ask_yes_no") as yes_no,
                    patch.object(model_chains_module, "model_chains_interview") as interview,
                ):
                    status, _, stderr = run_cli(
                        self._wizard_base(root) + ["setup", *flags], output_json=False
                    )
                self.assertEqual(status, 0, stderr)
                yes_no.assert_not_called()
                interview.assert_not_called()

        # `--model-setup` is the last entry in the same list. A full run of it
        # reaches step 6, which needs a Hermes config this fixture never
        # writes, so it is asserted at the gate the question depends on.
        self.assertFalse(
            setup_module._setup_should_interact(
                argparse.Namespace(
                    profile=None,
                    profile_pack=None,
                    with_mcp=False,
                    skip_apply=False,
                    model_setup=True,
                )
            )
        )

    def test_the_offer_copy_exists_in_every_locale(self) -> None:
        from omh.commands.language import MESSAGES

        for code, table in MESSAGES.items():
            for key in ("model_chains_interview_prompt", "model_chains_interview_note"):
                with self.subTest(locale=code, key=key):
                    self.assertIn(key, table)
            # The note has to name the later command, so a skipped offer is
            # not a lost one.
            self.assertIn("omh model-chains interview", table["model_chains_interview_note"])


class ModelChainsSetupTerminalTests(unittest.TestCase):
    """`omh setup --interactive` driven through a real pty.

    The offer is gated on `_stdin_is_tty()`, so no in-process `run_cli` test
    can reach it without patching that gate away. These two run the real
    command on a real terminal and are the only end-to-end coverage the
    question has: delete the wizard call and they go red.
    """

    def _run_setup_under_pty(self, root: Path, answers: list[str], *, timeout: float = 240.0) -> str:
        import errno
        import os
        import select
        import signal
        import sys
        import time

        if not hasattr(os, "fork"):  # pragma: no cover - POSIX-only surface
            self.skipTest("driving a terminal needs a POSIX fork")
        import pty

        home = root / "home"
        empty_path = root / "empty-path"
        home.mkdir()
        empty_path.mkdir()
        # A bare environment so the wizard's other questions stay out of the
        # way deterministically: no `*_API_KEY` name for `_env_key_names` to
        # hint a provider from, no `claude`/`codex` on PATH for the maestro
        # question, and a fresh HOME so no auth marker is present.
        env = {key: value for key, value in os.environ.items() if not key.endswith("_API_KEY")}
        env.update(
            HOME=str(home),
            PATH=str(empty_path),
            # Force the typed y/N fallback; the keyboard menu redraws in place
            # and would make the transcript unreadable.
            OMH_NO_TUI="1",
            TERM="dumb",
            NO_COLOR="1",
            PYTHONUNBUFFERED="1",
        )
        argv = [
            sys.executable,
            # `-P`: the repo root ships a top-level `omh/` shim, so a spawn
            # without it would import the checkout instead of the install.
            "-P",
            "-m",
            "omh.cli",
            "--omh-home",
            str(root / ".omh"),
            "--hermes-home",
            str(root / ".hermes"),
            "setup",
            "--interactive",
        ]

        pid, fd = pty.fork()
        if pid == 0:  # pragma: no cover - child never returns to the runner
            try:
                os.execve(argv[0], argv, env)
            finally:
                os._exit(127)

        chunks: list[bytes] = []
        status = None
        try:
            os.write(fd, ("\n".join(answers) + "\n").encode())
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                ready, _, _ = select.select([fd], [], [], 1.0)
                if ready:
                    try:
                        chunk = os.read(fd, 65536)
                    except OSError as exc:
                        if exc.errno != errno.EIO:
                            raise
                        chunk = b""
                    if chunk:
                        chunks.append(chunk)
                        continue
                finished, waited = os.waitpid(pid, os.WNOHANG)
                if finished:
                    status = waited
                    break
        finally:
            os.close(fd)
            if status is None:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)

        transcript = b"".join(chunks).decode(errors="replace")
        self.assertIsNotNone(status, f"omh setup never finished under the pty:\n{transcript}")
        self.assertEqual(os.waitstatus_to_exitcode(status), 0, transcript)
        return transcript

    def test_declining_on_a_terminal_leaves_the_empty_seed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            # TUI identity no, the chain offer declined, then Enter through
            # the update-check question. Without that third answer the child
            # blocks on a prompt the pty never closes and the run times out.
            transcript = self._run_setup_under_pty(root, ["n", "n", ""])

            self.assertIn("Walk the per-category model chains now (interview)?", transcript)
            # Default No: a bare Enter has to keep the shipped chains.
            self.assertIn("[y/N]", transcript.split("model chains now (interview)?", 1)[1][:16])
            self.assertNotIn("Model chain interview", transcript)
            self.assertEqual(
                json.loads(_chains_path(root).read_text(encoding="utf-8")),
                _SEEDED_EMPTY_DOCUMENT,
            )

    def test_accepting_on_a_terminal_writes_an_override_that_survives_the_seed(self) -> None:
        # The wizard prompts before step 3 runs `_seed_model_chains_result`,
        # so the answer has to outlive it. Option numbering follows the
        # interview's own rules: 1) keep, 2) Ultrafast when the chain has a
        # swappable member, last) custom entry.
        answers = ["n", "y"]
        for name, chain in HERMES_MIXTURE_CATEGORY_CHAINS.items():
            has_ultrafast = any(model in ("glm-5.2", "kimi-k3") for model, _ in chain)
            if name == "writing":
                answers.extend(["3" if has_ultrafast else "2", "qwen3-coder:high"])
            else:
                answers.append("")
        # Enter through the update-check question, which follows the interview.
        answers.append("")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript = self._run_setup_under_pty(root, answers)

            self.assertIn("Model chain interview", transcript)
            self.assertEqual(
                json.loads(_chains_path(root).read_text(encoding="utf-8"))["categories"],
                {"writing": [{"model": "qwen3-coder", "reasoning_effort": "high"}]},
            )


if __name__ == "__main__":
    unittest.main()
