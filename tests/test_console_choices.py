"""A console session is asked to put a choice through Hermes' `clarify` picker, once, and again after a timeout.

Messaging platforms, later turns and turns Hermes opened for itself must
render exactly what they rendered before, so the negative cases assert
absence and the byte-identity case compares the whole context with the line
switched off.
"""
from __future__ import annotations

from contextlib import nullcontext
import json
import unittest
from tempfile import TemporaryDirectory
from unittest import mock

from omh.plugin_bundle.omh.console_choices import (
    CONSOLE_CHOICES_LINE,
    TIMED_OUT_LINE,
    clarify_timed_out_since_person_spoke,
    console_choices_line,
)
from omh.plugin_bundle.omh.hooks import llm_hooks
from omh.plugin_bundle.omh.memory_session_lens import OPERATOR_CONSOLE_PLATFORMS
from omh.plugin_bundle.omh.plan_follow_on import reset_plan_follow_on_state
from omh.plugin_bundle.omh.skill_shortlist import reset_candidate_line_state

HEAD = "[OMH Console Choices]"
MESSAGING = ("discord", "slack", "telegram", "whatsapp", "signal", "cron", "")


def clarify_call(call_id: str) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": call_id, "call_id": call_id, "type": "function",
                        "function": {"name": "clarify", "arguments": "{}"}}],
    }


def clarify_result(call_id: str, outcome: str) -> dict[str, object]:
    # Hermes 2026-10's shape (`clarify_tool._result`), as recorded in the owner's state.db.
    body = {"responses": [{"question": "어떻게 할까요?", "choices_offered": ["머지", "재실행"],
                           "status": "unanswered" if outcome != "submitted" else "answered",
                           "user_response": None if outcome != "submitted" else "머지"}],
            "outcome": outcome}
    if outcome == "timed_out":
        body["notice"] = "[user did not respond within 60m]"
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(body, ensure_ascii=False)}


# The owner's 2026-11-04 path: a background process opened the turn, the clarify timed out after
# 60 minutes, the model listed the options in prose, and the person came back with "뭐해".
TIMED_OUT_HISTORY = [
    {"role": "user", "content": "PR 머지 준비해줘"},
    {"role": "assistant", "content": "CI를 지켜보겠습니다."},
    {"role": "user", "content": "[Background process proc_1 completed]", "display_kind": "process_complete"},
    clarify_call("call_1"),
    clarify_result("call_1", "timed_out"),
    {"role": "assistant", "content": "선택지는 두 가지입니다.\n- **\"머지해\"**: …\n- **\"재실행\"**: …"},
    {"role": "user", "content": "뭐해"},
]


class LineTests(unittest.TestCase):
    def test_a_console_first_turn_gets_the_line_and_names_the_presence_rule(self) -> None:
        for platform in sorted(OPERATOR_CONSOLE_PLATFORMS) + ["TUI", " cli "]:
            with self.subTest(platform=platform):
                self.assertEqual(
                    console_choices_line(platform, [], is_first_turn=True, person_turn=True), CONSOLE_CHOICES_LINE
                )
        self.assertIn("clarify is in your tool list or tool_search finds it", CONSOLE_CHOICES_LINE)
        # Only where the reply stops for a pick or an approval it needs: a courtesy offer is left as it is.
        self.assertIn("approve an action you will not take without their answer", CONSOLE_CHOICES_LINE)
        self.assertIn("A closing offer of optional further work stays prose.", CONSOLE_CHOICES_LINE)

    def test_a_messaging_platform_gets_nothing(self) -> None:
        for platform in MESSAGING:
            with self.subTest(platform=platform):
                self.assertEqual(console_choices_line(platform, [], is_first_turn=True, person_turn=True), "")
                self.assertEqual(console_choices_line(platform, TIMED_OUT_HISTORY, is_first_turn=False,
                                                      person_turn=True), "")

    def test_an_unattended_console_run_gets_nothing(self) -> None:
        # There clarify comes back undelivered with "use your own judgment": an approval would be self-decided.
        for env in ({"HERMES_SINGLE_QUERY_SESSION": "1"}, {"HERMES_KANBAN_TASK": "t_1"}):
            with self.subTest(env=env), mock.patch.dict("os.environ", env):
                self.assertEqual(console_choices_line("cli", [], is_first_turn=True, person_turn=True), "")
                self.assertEqual(console_choices_line("tui", TIMED_OUT_HISTORY, is_first_turn=False,
                                                      person_turn=True), "")
        with mock.patch.dict("os.environ", {"HERMES_SINGLE_QUERY_SESSION": "0"}):
            self.assertEqual(console_choices_line("cli", [], is_first_turn=True, person_turn=True),
                             CONSOLE_CHOICES_LINE)

    def test_the_line_goes_out_again_once_compaction_dropped_it(self) -> None:
        fence = "\n\n<omh-context>\n" + CONSOLE_CHOICES_LINE + "\n</omh-context>"
        kept = [{"role": "user", "content": "hi", "api_content": "hi" + fence},
                {"role": "assistant", "content": "hello"}, {"role": "user", "content": "next"}]
        self.assertEqual(console_choices_line("tui", kept, is_first_turn=False, person_turn=True), "")
        dropped = [{"role": "user", "content": "[CONTEXT COMPACTION] summary", "api_content": "x\n\n<omh-context>\n"
                    "[OMH Route Hint] something else\n</omh-context>"}, {"role": "user", "content": "next"}]
        self.assertEqual(console_choices_line("tui", dropped, is_first_turn=False, person_turn=True),
                         CONSOLE_CHOICES_LINE)
        # A person quoting the line does not count as the host carrying it.
        quoted = [{"role": "user", "content": CONSOLE_CHOICES_LINE, "api_content": CONSOLE_CHOICES_LINE + "\n\nx"},
                  {"role": "user", "content": "next"}]
        self.assertEqual(console_choices_line("tui", quoted, is_first_turn=False, person_turn=True),
                         CONSOLE_CHOICES_LINE)
        # An assistant row's api_content (a promoted final row) is no sign the host replays injections.
        assistant_only = [{"role": "user", "content": "hi"},
                          {"role": "assistant", "content": "hello", "api_content": "hello"},
                          {"role": "user", "content": "next"}]
        self.assertEqual(console_choices_line("tui", assistant_only, is_first_turn=False, person_turn=True), "")
        # A host that replays nothing never repeats it.
        bare = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
                {"role": "user", "content": "next"}]
        self.assertEqual(console_choices_line("tui", bare, is_first_turn=False, person_turn=True), "")

    def test_a_later_turn_gets_nothing(self) -> None:
        history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
                   {"role": "user", "content": "merge it?"}]
        self.assertEqual(console_choices_line("tui", history, is_first_turn=False, person_turn=True), "")

    def test_the_persons_return_after_a_timed_out_clarify_gets_the_re_ask(self) -> None:
        self.assertEqual(console_choices_line("tui", TIMED_OUT_HISTORY, is_first_turn=False, person_turn=True),
                         TIMED_OUT_LINE)

    def test_an_older_hosts_timed_out_flag_counts(self) -> None:
        older = {"role": "tool", "tool_call_id": "call_1",
                 "content": json.dumps({"responses": [{"question": "q", "user_response": ""}], "timed_out": True})}
        history = [*TIMED_OUT_HISTORY[:4], older, *TIMED_OUT_HISTORY[5:]]
        self.assertTrue(clarify_timed_out_since_person_spoke(history))

    def test_a_turn_hermes_opened_does_not_re_ask_and_does_not_spend_it(self) -> None:
        notice = {"role": "user", "content": "[Background process proc_2 completed]", "display_kind": "process_complete"}
        history = [*TIMED_OUT_HISTORY[:-1], notice]
        self.assertEqual(console_choices_line("tui", history, is_first_turn=False, person_turn=False), "")
        # The person's message after that notice still sees the timeout.
        history = [*history, {"role": "assistant", "content": "ok"}, {"role": "user", "content": "뭐해"}]
        self.assertEqual(console_choices_line("tui", history, is_first_turn=False, person_turn=True), TIMED_OUT_LINE)

    def test_a_session_command_frame_is_not_the_person_coming_back(self) -> None:
        # Hermes writes `/loop` wake-ups and `/goal` continuations with no display_kind; the person's message
        # after them still sees the timeout from before them.
        for frame in ("[/loop wakeup #3]\nRecurring task: check CI", "[Continuing toward your standing goal]\nGoal: ship"):
            with self.subTest(frame=frame):
                history = [*TIMED_OUT_HISTORY[:-1], {"role": "user", "content": frame},
                           {"role": "assistant", "content": "still waiting"}, {"role": "user", "content": "뭐해"}]
                self.assertTrue(clarify_timed_out_since_person_spoke(history))

    def test_once_per_timeout(self) -> None:
        # The person already answered after the timeout: their next message is past it.
        history = [*TIMED_OUT_HISTORY, {"role": "assistant", "content": "머지할까요?"}, {"role": "user", "content": "응"}]
        self.assertEqual(console_choices_line("tui", history, is_first_turn=False, person_turn=True), "")

    def test_a_later_answered_clarify_supersedes_the_timeout(self) -> None:
        history = [*TIMED_OUT_HISTORY[:-1], clarify_call("call_2"), clarify_result("call_2", "submitted"),
                   {"role": "assistant", "content": "머지했습니다."}, TIMED_OUT_HISTORY[-1]]
        self.assertFalse(clarify_timed_out_since_person_spoke(history))
        for outcome in ("submitted", "cancelled", "undelivered"):
            with self.subTest(outcome=outcome):
                history = [*TIMED_OUT_HISTORY[:4], clarify_result("call_1", outcome), *TIMED_OUT_HISTORY[5:]]
                self.assertFalse(clarify_timed_out_since_person_spoke(history))

    def test_another_tools_timeout_is_not_a_clarify(self) -> None:
        terminal = {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_t", "type": "function", "function": {"name": "terminal", "arguments": "{}"}}]}
        result = {"role": "tool", "tool_call_id": "call_t", "content": json.dumps({"timed_out": True})}
        history = [{"role": "user", "content": "run it"}, terminal, result, {"role": "user", "content": "뭐해"}]
        self.assertFalse(clarify_timed_out_since_person_spoke(history))

    def test_malformed_history_reads_as_no_timeout(self) -> None:
        for history in (None, "rows", [], [{"role": "user", "content": "x"}], [1, None, {"role": "tool"}],
                        [clarify_call("c"), {"role": "tool", "tool_call_id": "c", "content": "not json"},
                         {"role": "user", "content": "x"}]):
            with self.subTest(history=history):
                self.assertFalse(clarify_timed_out_since_person_spoke(history))


class PreLlmCallTests(unittest.TestCase):
    session = "console-choices-session"

    def context(self, message: str, *, platform: str, first: bool, history: list[dict[str, object]] | None = None,
                **patches: object) -> str:
        # A fresh home and fresh in-process claims, so no run spends another's route hint or candidate line.
        llm_hooks._reset_awareness_section_state()
        reset_candidate_line_state()
        reset_plan_follow_on_state()
        with TemporaryDirectory() as tmp, mock.patch.multiple(llm_hooks, **patches) if patches else nullcontext():
            payload = llm_hooks.pre_llm_call(
                omh_home=tmp, hermes_home=tmp, session_id=self.session, user_message=message,
                is_first_turn=first, platform=platform,
                conversation_history=history if history is not None else [{"role": "user", "content": message}],
            ) or {}
        return str(payload.get("context", ""))

    def test_a_console_first_turn_carries_the_line_once(self) -> None:
        for platform in sorted(OPERATOR_CONSOLE_PLATFORMS):
            with self.subTest(platform=platform):
                context = self.context("rename the export button", platform=platform, first=True)
                self.assertEqual(context.count(HEAD), 1)
                self.assertIn(CONSOLE_CHOICES_LINE, context)
                self.assertNotIn(HEAD, self.context("rename the export button", platform=platform, first=False))

    def test_the_re_ask_rides_the_persons_return(self) -> None:
        context = self.context("뭐해", platform="tui", first=False, history=TIMED_OUT_HISTORY)
        self.assertIn(TIMED_OUT_LINE, context)
        self.assertNotIn(CONSOLE_CHOICES_LINE, context)

    def test_an_unattended_cli_run_gets_nothing_through_the_hook(self) -> None:
        for env in ({"HERMES_SINGLE_QUERY_SESSION": "1"}, {"HERMES_KANBAN_TASK": "t_1"}):
            with self.subTest(env=env), mock.patch.dict("os.environ", env):
                self.assertNotIn(HEAD, self.context("rename the export button", platform="cli", first=True))
                self.assertNotIn(HEAD, self.context("뭐해", platform="tui", first=False, history=TIMED_OUT_HISTORY))

    def test_a_delegated_child_gets_nothing(self) -> None:
        with mock.patch.object(llm_hooks, "session_is_delegated", return_value=True):
            self.assertNotIn(HEAD, self.context("rename the export button", platform="cli", first=True))
            self.assertNotIn(HEAD, self.context("뭐해", platform="tui", first=False, history=TIMED_OUT_HISTORY))

    def test_without_the_line_every_turn_is_byte_identical(self) -> None:
        # A messaging platform, a later console turn and the re-ask's negatives render what they rendered
        # before the line existed: the whole context with the reader switched off.
        cases = [(platform, True, None) for platform in MESSAGING] + [
            ("discord", False, TIMED_OUT_HISTORY),
            ("tui", False, None),
            ("tui", False, [*TIMED_OUT_HISTORY, {"role": "assistant", "content": "?"}, {"role": "user", "content": "응"}]),
        ]
        for platform, first, history in cases:
            with self.subTest(platform=platform, first=first, history=bool(history)):
                message = str((history or [{"content": "review this PR for bugs before merge"}])[-1]["content"])
                with_line = self.context(message, platform=platform, first=first, history=history)
                without_line = self.context(message, platform=platform, first=first, history=history,
                                            console_choices_line=lambda *args, **kwargs: "")
                self.assertEqual(with_line, without_line)
                self.assertNotIn(HEAD, with_line)

    def test_the_line_is_the_only_difference_on_a_console_first_turn(self) -> None:
        message = "review this PR for bugs before merge"
        with_line = self.context(message, platform="tui", first=True)
        without_line = self.context(message, platform="tui", first=True,
                                    console_choices_line=lambda *args, **kwargs: "")
        self.assertEqual(len(with_line) - len(without_line), len(CONSOLE_CHOICES_LINE) + len("\n\n"))


if __name__ == "__main__":
    unittest.main()
