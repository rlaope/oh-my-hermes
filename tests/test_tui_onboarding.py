"""`omh --onboard model-setup`: the packaged onboarding prompt, and the TUI sending it once in a new session.

The one prompt the OMH TUI sends that the person did not type: only under
`OMH_TUI_ONBOARD`, only in a session it created (never a resume or the
picker), and only once, whatever reconnects after (`App._send_onboarding`).
"""

from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

from test_tui_launch_card import Launched
from omh.tui import launch
from omh.tui.app import App
from omh.tui.onboarding import ONBOARDING_LANGUAGES, ONBOARDING_NAMES, onboarding_prompt

# The English master, pinned: a change to what the TUI sends on the person's behalf is a reviewed change.
EN_SHA256 = "7578b705a00c5d79c244a799131a4afc3c4953920375e038900641e9720042c8"
ONBOARD = {launch.ONBOARD_ENV: "model-setup", launch.ONBOARD_LANG_ENV: "ko"}


class PromptTests(unittest.TestCase):
    def test_every_name_and_language_names_the_skill_and_one_fallback(self) -> None:
        for name in ONBOARDING_NAMES:
            for language in ONBOARDING_LANGUAGES:
                with self.subTest(name=name, language=language):
                    text = onboarding_prompt(name, language)
                    self.assertTrue(text.strip())
                    self.assertLessEqual(len(text), 1800)
                    self.assertIn("model-setup", text)
                    self.assertIn("fallback", text)
                    for command in ("hermes auth add <provider>", "hermes model", "omh model-chains provider set",
                                    "omh model-chains show"):
                        self.assertIn(command, text)

    def test_the_languages_differ_and_say_their_own_words(self) -> None:
        texts = {language: onboarding_prompt("model-setup", language) for language in ONBOARDING_LANGUAGES}
        self.assertEqual(len(set(texts.values())), len(ONBOARDING_LANGUAGES))
        self.assertIn("설정", texts["ko"])
        self.assertIn("設定", texts["ja"])
        self.assertIn("设置", texts["zh"])

    def test_it_never_asks_for_a_key_in_chat_and_says_not_to(self) -> None:
        english = onboarding_prompt("model-setup", "en")
        self.assertIn("never ask me to paste a key into this chat", english)
        self.assertIn("never values", english)
        self.assertNotIn("paste your", english.lower())
        self.assertIn("붙여 넣으라고 절대 요청하지 마세요", onboarding_prompt("model-setup", "ko"))
        self.assertIn("貼り付けるよう決して求めないでください", onboarding_prompt("model-setup", "ja"))
        self.assertIn("绝不要让我把密钥粘贴", onboarding_prompt("model-setup", "zh"))

    def test_an_unknown_name_is_refused_and_an_unknown_language_is_english(self) -> None:
        with self.assertRaises(ValueError):
            onboarding_prompt("provider-setup")
        self.assertEqual(onboarding_prompt("model-setup", "fr"), onboarding_prompt("model-setup", "en"))
        self.assertEqual(onboarding_prompt("model-setup", ""), onboarding_prompt("model-setup"))

    def test_the_english_master_is_pinned(self) -> None:
        digest = hashlib.sha256(onboarding_prompt("model-setup", "en").encode("utf-8")).hexdigest()
        self.assertEqual(digest, EN_SHA256)


def submits(run: Launched) -> list[str]:
    return [params["text"] for params in run.client.named("prompt.submit")]


class TuiSendTests(unittest.TestCase):
    def test_a_new_session_sends_the_prompt_once_as_its_first_turn(self) -> None:
        with patch.object(App, "_whats_new_on_launch") as whats_new:
            run = Launched(env=ONBOARD)
        self.assertEqual(submits(run), [onboarding_prompt("model-setup", "ko")])
        self.assertEqual(run.client.named("prompt.submit")[0]["session_id"], run.app.sid)
        self.assertEqual(run.client.named("session.list"), [])  # no last-session question
        whats_new.assert_not_called()
        self.assertTrue(run.app.turn_pending)  # busy as after a typed prompt
        self.assertIn(onboarding_prompt("model-setup", "ko").splitlines()[0], "\n".join(run.everything()))

    def test_a_reconnect_starting_the_session_again_never_sends_it_twice(self) -> None:
        run = Launched(env=ONBOARD)
        run.app.startup()  # the launch's retry after a draining gateway: `startup` runs on the same App again
        self.assertEqual(len(submits(run)), 1)

    def test_a_resume_or_the_picker_sends_nothing(self) -> None:
        for extra in ({"HERMES_TUI_RESUME": "stored-1"}, {launch.PICK_SESSION_ENV: "1"}):
            with self.subTest(extra=extra):
                run = Launched(env={**ONBOARD, **extra})
                self.assertEqual(submits(run), [])

    def test_without_onboard_nothing_is_sent_and_the_launch_asks_as_always(self) -> None:
        for env in ({}, {launch.ONBOARD_ENV: "something-else"}):
            with self.subTest(env=env):
                run = Launched(env=env)
                self.assertEqual(submits(run), [])
                self.assertEqual(len(run.client.named("session.list")), 1)

    def test_a_missing_language_is_english(self) -> None:
        run = Launched(env={launch.ONBOARD_ENV: "model-setup"})
        self.assertEqual(submits(run), [onboarding_prompt("model-setup", "en")])


class EnvironmentTests(unittest.TestCase):
    def environment(self, inherited: dict[str, str], **options: object) -> dict[str, str]:
        from pathlib import Path

        return launch.omh_tui_environment(
            inherited, python="/py", site="/site", omh_home=Path("/o"), fallback_sentinel=Path("/t/f"),
            session_file=Path("/t/s"), **options,  # type: ignore[arg-type]
        )

    def test_onboard_sets_both_names_and_an_inherited_pair_is_dropped_without_it(self) -> None:
        stale = {launch.ONBOARD_ENV: "model-setup", launch.ONBOARD_LANG_ENV: "ja"}
        env = self.environment(stale, onboard="model-setup", onboard_language="zh")
        self.assertEqual((env[launch.ONBOARD_ENV], env[launch.ONBOARD_LANG_ENV]), ("model-setup", "zh"))
        env = self.environment(stale)
        self.assertNotIn(launch.ONBOARD_ENV, env)
        self.assertNotIn(launch.ONBOARD_LANG_ENV, env)

    def test_both_names_are_frontend_state_the_gateway_and_the_fallback_never_see(self) -> None:
        from omh.tui.gateway import INTERNAL_ENV_PREFIX

        for name in (launch.ONBOARD_ENV, launch.ONBOARD_LANG_ENV):
            self.assertTrue(name.startswith(INTERNAL_ENV_PREFIX))
            self.assertIn(name, launch.TUI_LAUNCH_ENV_NAMES)


if __name__ == "__main__":
    unittest.main()
