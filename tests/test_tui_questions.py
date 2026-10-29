"""The questions Hermes asks, through the app: reading one whole before answering it.

Ctrl+O while a question is open pages it whole (a long command every row of
it) and answers nothing; q or Esc goes back to the question as it was, and a
question that closes while paged takes its pager with it. A terminal too small
for anything but the composer and the info line still shows a question
answered with text its label. These cases drive an `App` whose gateway client
only records, and read the VT screen it painted.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from _tui_lines import info_row_index, INFO_INSET, composer_text, line_text, without_badge
from test_tui_choice_ui import armed, drawn, press
from test_tui_app import FakePoller, ScriptedTerminal
from test_tui_modes import RecordingClient, make_app, type_text
from omh.tui import app as app_module
from omh.tui import prompts
from omh.tui.gateway import Event, Response, ServerRequest
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, UP, Key
from omh.tui.layout import MIN_COLS, allocate
from omh.tui.app import BELL, App
from omh.tui.pager import ALT_SCREEN_OFF, HistoryPager
from omh.tui.style import Span
from omh.tui.transcript import (
    NOTICE_ERROR, NOTICE_OK, TURN_WAITED, NoticeBlock, ToolGroup, TurnSummaryBlock, block_rows, rail_cell,
)

LONG_COMMAND = "\n".join(f"echo line {n}" for n in range(1, 21))
LONG_APPROVAL = ServerRequest(
    "srq-1", "approval",
    {"command": LONG_COMMAND, "description": "script execution", "choices": ["once", "session", "deny"]},
)
CTRL_O = Key(CHAR, "o", ctrl=True)
TEXT_QUESTIONS = (
    (ServerRequest("srq-3", "sudo", {"command": "apt install x"}), "Hermes needs your sudo password"),
    (ServerRequest("srq-4", "secret", {"env_var": "API_KEY"}), "Hermes needs API_KEY"),
    (ServerRequest("srq-5", "clarify", {"questions": [{"qid": "q", "question": "Which number?"}]}), "Which number?"),
)


def paged(app) -> list[str]:
    return ["".join(span.text for span in line) for line in app.pager.lines]


class QuestionViewTests(unittest.TestCase):
    def test_ctrl_o_pages_the_open_approval_whole_and_answers_nothing(self) -> None:
        app, client = make_app(busy=True, rows=12, cols=60)
        app._on_server_request(LONG_APPROVAL)
        armed(app)
        press(app, Key(DOWN))
        self.assertIn("▌   echo line 1", drawn(app))  # the slot shows the command's head and the marker
        self.assertTrue([row for row in drawn(app) if "ctrl+o shows all" in row])
        press(app, CTRL_O)
        self.assertIsNotNone(app.pager)
        self.assertIs(app.pager, app.question_view)
        text = paged(app)
        self.assertEqual([row for row in text if "echo line" in row], [f"▌   echo line {n}" for n in range(1, 21)])
        self.assertIn("▌ ❯ ✓ allow once", text)
        self.assertEqual(client.answers, [])
        press(app, Key(CHAR, "q"))
        self.assertIsNone(app.pager)
        self.assertIs(app.slot.request_id, "srq-1")  # type: ignore[union-attr]
        self.assertEqual(app.slot.selected, 1)  # type: ignore[union-attr]
        self.assertIn("▌ ❯ ✓ allow once", drawn(app))
        self.assertEqual(client.answers, [])

    def test_esc_in_the_pager_leaves_it_and_denies_nothing(self) -> None:
        app, client = make_app(busy=True, rows=12, cols=60)
        app._on_server_request(LONG_APPROVAL)
        armed(app)
        press(app, CTRL_O, Key(ESCAPE))
        self.assertIsNone(app.pager)
        self.assertIsNotNone(app.slot)
        self.assertEqual(client.answers, [])
        press(app, Key(ESCAPE))  # with the pager gone, Esc is the question's again
        self.assertEqual(client.answers, [("srq-1", {"result": {"choice": "deny"}})])

    def test_a_question_withdrawn_while_paged_takes_its_pager_with_it(self) -> None:
        app, client = make_app(busy=True, rows=12, cols=60)
        app._on_server_request(LONG_APPROVAL)
        press(app, CTRL_O)
        app._on_withdrawn({"id": "srq-1", "reason": "timeout"})
        self.assertIsNone(app.slot)
        self.assertIsNone(app.pager)
        self.assertIsNone(app.question_view)
        self.assertIn(ALT_SCREEN_OFF, "".join(app.terminal.writes))  # type: ignore[attr-defined]
        self.assertEqual(client.answers, [])

    def test_without_a_question_ctrl_o_is_still_the_transcript(self) -> None:
        app, _client = make_app()
        app.transcript.add_notice("something to view")
        press(app, CTRL_O)
        self.assertIsInstance(app.pager, HistoryPager)
        self.assertIsNone(app.question_view)


class WaitingQuestionTests(unittest.TestCase):
    def test_the_open_question_counts_the_questions_waiting_behind_it(self) -> None:
        app, client = make_app(busy=True, rows=24, cols=100)
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x", "description": "recursive delete"}))
        self.assertFalse([row for row in drawn(app) if "waiting" in row and row.startswith("▌")])
        for request, _label in TEXT_QUESTIONS[:2]:
            app._on_server_request(request)
        self.assertIn("▌ ⚠ Hermes asks to run recursive delete · 2 more questions waiting", drawn(app))
        armed(app)
        press(app, Key(ESCAPE))
        self.assertIn("▌ 🔑 Hermes needs your sudo password · 1 more question waiting", drawn(app))
        press(app, CTRL_O)
        self.assertIn("▌ 🔑 Hermes needs your sudo password · 1 more question waiting", paged(app))
        press(app, Key(CHAR, "q"))
        armed(app)
        press(app, Key(ESCAPE))
        self.assertIn("▌ 🔑 Hermes needs API_KEY", drawn(app))  # the last one: nothing behind it
        self.assertEqual([request_id for request_id, _ in client.answers], ["srq-1", "srq-3"])

    def test_a_request_the_tui_cannot_show_is_declined_at_once_even_behind_a_question(self) -> None:
        app, client = make_app(busy=True)
        app._on_server_request(LONG_APPROVAL)
        app._on_server_request(ServerRequest("srq-9", "terminal.read", {}))
        self.assertEqual([request_id for request_id, _ in client.answers], ["srq-9"])
        self.assertEqual(client.answers[0][1]["error"]["code"], -32601)
        self.assertFalse(app.waiting_requests)
        self.assertIs(app.slot.request_id, "srq-1")  # type: ignore[union-attr]
        self.assertFalse([row for row in drawn(app) if "waiting" in row and row.startswith("▌")])


class MultiSelectAppTests(unittest.TestCase):
    def test_space_on_a_multi_select_question_ticks_and_never_reaches_the_draft(self) -> None:
        app, client = make_app(busy=True)
        type_text(app, "my draft")
        app._on_server_request(ServerRequest("srq-6", "clarify", {"questions": [
            {"qid": "q0", "question": "Which toppings?", "choices": ["cheese", "ham"], "multi_select": True},
        ]}))
        armed(app)
        press(app, Key(CHAR, " "), Key(DOWN), Key(CHAR, " "))
        self.assertIn("▌ ❯ [x] 2. ham", drawn(app))
        press(app, Key(ENTER))
        self.assertEqual(client.answers, [("srq-6", {"result": {"answers": {"q0": '["cheese","ham"]'}}})])
        self.assertEqual(app.composer.text, "my draft")


COLOUR = ServerRequest("srq-7", "clarify", {"questions": [
    {"qid": "q0", "question": "Which colour?", "choices": ["red (Recommended)", "blue"], "multi_select": False},
]})


def outcome_rows(app) -> list[tuple[str, str]]:
    """The answers the transcript recorded: each row's text and level."""
    return [(block.text, block.level) for block in app.transcript.blocks if isinstance(block, NoticeBlock)]


def opened(request: ServerRequest):
    app, client = make_app(busy=True)
    app._on_server_request(request)
    armed(app)
    return app, client


class QuestionOutcomeTests(unittest.TestCase):
    def test_a_picked_choice_is_recorded_with_its_label(self) -> None:
        app, _client = opened(COLOUR)
        press(app, Key(ENTER))
        # The answer still goes as the choice reads (as Ink sends it); the record says what Hermes reads from it,
        # its display tag stripped (clarify_tool.strip_recommended).
        self.assertEqual(outcome_rows(app), [("red · Which colour?", NOTICE_OK)])
        self.assertIn("✓ red · Which colour?", drawn(app))

    def test_a_typed_answer_is_recorded_as_typed(self) -> None:
        app, _client = opened(TEXT_QUESTIONS[2][0])
        type_text(app, "seven")
        press(app, Key(ENTER))
        self.assertEqual(outcome_rows(app), [("seven · Which number?", NOTICE_OK)])

    def test_ticked_choices_are_recorded_joined(self) -> None:
        app, _client = opened(ServerRequest("srq-6", "clarify", {"questions": [
            {"qid": "q0", "question": "Which toppings?", "choices": ["cheese", "ham"], "multi_select": True},
        ]}))
        press(app, Key(CHAR, "2"), Key(CHAR, "1"), Key(ENTER))
        self.assertEqual(outcome_rows(app), [("ham, cheese · Which toppings?", NOTICE_OK)])

    def test_a_ticked_choice_is_recorded_without_hermes_display_tag(self) -> None:
        app, client = opened(ServerRequest("srq-6", "clarify", {"questions": [
            {"qid": "q0", "question": "Which toppings?", "choices": ["cheese (recommended)", "ham"], "multi_select": True},
        ]}))
        press(app, Key(CHAR, "2"), Key(CHAR, "1"), Key(ENTER))
        self.assertEqual(client.answers, [("srq-6", {"result": {"answers": {"q0": '["ham","cheese (recommended)"]'}}})])
        self.assertEqual(outcome_rows(app), [("ham, cheese · Which toppings?", NOTICE_OK)])

    def test_a_cancelled_question_is_a_red_cross_with_a_word(self) -> None:
        for key in (Key(ESCAPE), Key(CHAR, "c", ctrl=True)):
            with self.subTest(key=key):
                app, client = opened(COLOUR)
                press(app, key)
                self.assertEqual(client.answers, [("srq-7", {"result": {}})])
                self.assertEqual(outcome_rows(app), [("cancelled · Which colour?", NOTICE_ERROR)])
                self.assertIn("✗ cancelled · Which colour?", drawn(app))

    def test_a_question_that_went_unanswered_leaves_its_tool_row_a_red_mark_too(self) -> None:
        # Hermes' clarify result says how the wait ended (`outcome`); only `submitted` was an answer.
        def mark(app) -> tuple[Span, Span]:
            """The call row's rail and its mark: the first and third spans of `  ✗ clarify(…)` (the rail's painted cell)."""
            (group,) = [block for block in app.transcript.blocks if isinstance(block, ToolGroup)]
            row = block_rows(group, 80, app.theme)[0]
            return row[0], row[2]

        def complete(app, outcome: str) -> list[str]:
            app._on_event(Event("tool.start", SID, {"tool_id": "c1", "name": "clarify", "context": "Which colour?"}))
            responses = [{"question": "Which colour?", "choices_offered": ["red", "blue"], "status": "unanswered",
                          "user_response": None}]
            app._on_event(Event("tool.complete", SID, {"tool_id": "c1", "name": "clarify", "duration_s": 3.0,
                                                       "result": {"responses": responses, "outcome": outcome}}))
            return drawn(app)

        for outcome, words in (("cancelled", "cancelled"), ("timed_out", "timed out"), ("undelivered", "not delivered")):
            with self.subTest(outcome=outcome):
                app, _client = opened(COLOUR)
                press(app, Key(ESCAPE))
                screen = complete(app, outcome)
                (row,) = [line for line in screen if "clarify" in line and "Which colour?" in line and "·" not in line]
                self.assertTrue(row.startswith("  ✗ clarify("), row)
                self.assertEqual(mark(app), (rail_cell(app.theme.error), Span("✗", app.theme.error)))
                self.assertIn(f"⎿  {words}", "\n".join(screen))
        app, _client = opened(COLOUR)
        press(app, Key(ENTER))
        (row,) = [line for line in complete(app, "submitted") if "clarify" in line and "·" not in line]
        self.assertTrue(row.startswith("  ● clarify("), row)
        self.assertEqual(mark(app), (rail_cell(app.theme.accent), Span("●", app.theme.ok)))  # the look's rail

    def test_hermes_notice_says_why_under_the_cross_when_it_gives_one(self) -> None:
        app, _client = make_app(busy=True)
        app._on_event(Event("tool.start", SID, {"tool_id": "c1", "name": "clarify", "context": "Which colour?"}))
        result = {"responses": [], "outcome": "timed_out", "notice": "No answer within 300 s."}
        app._on_event(Event("tool.complete", SID, {"tool_id": "c1", "name": "clarify", "result": result}))
        self.assertIn("⎿  No answer within 300 s.", "\n".join(drawn(app)))

    def test_each_question_of_a_batch_gets_its_row_and_an_empty_answer_is_skipped(self) -> None:
        app, _client = opened(ServerRequest("srq-8", "clarify", {"questions": [
            {"qid": "a", "question": "Why?"}, {"qid": "b", "question": "Which?", "choices": ["x", "y"]},
        ]}))
        press(app, Key(ENTER))  # nothing typed for the first
        armed(app)
        press(app, Key(DOWN), Key(ENTER))
        self.assertEqual(outcome_rows(app), [("skipped · Why?", NOTICE_ERROR), ("y · Which?", NOTICE_OK)])

    def test_a_value_prompt_says_answered_or_declined_and_never_the_value(self) -> None:
        for request, subject in ((TEXT_QUESTIONS[0][0], "sudo password"), (TEXT_QUESTIONS[1][0], "API_KEY")):
            with self.subTest(method=request.method):
                app, client = opened(request)
                type_text(app, "hunter2")
                press(app, Key(ENTER))
                self.assertEqual(client.answers, [(request.id, {"result": {"value": "hunter2"}})])
                self.assertEqual(outcome_rows(app), [(f"answered · {subject}", NOTICE_OK)])
                self.assertNotIn("hunter2", repr(app.transcript.blocks))
                self.assertFalse([row for row in drawn(app) if "hunter2" in row])
                app, _client = opened(request)
                press(app, Key(ESCAPE))
                self.assertEqual(outcome_rows(app), [(f"declined · {subject}", NOTICE_ERROR)])

    def test_a_withdrawn_question_says_why_with_a_red_cross(self) -> None:
        cases = (
            (COLOUR, "timeout", "timed out · Which colour?"),
            (COLOUR, "interrupted", "interrupted · Which colour?"),
            (TEXT_QUESTIONS[0][0], "", "withdrawn (no reason given) · sudo password"),
            (ServerRequest("srq-1", "approval", {"command": "rm -rf ./x\nmore"}), "session_closed",
             "withdrawn (session_closed) · rm -rf ./x"),
        )
        for request, reason, row in cases:
            with self.subTest(reason=reason, method=request.method):
                app, client = opened(request)
                app._on_withdrawn({"id": request.id, "reason": reason})
                self.assertIsNone(app.slot)
                self.assertEqual(client.answers, [])
                self.assertEqual(outcome_rows(app), [(row, NOTICE_ERROR)])

    def test_hermes_always_choice_is_sent_and_recorded_as_sent_not_as_saved(self) -> None:
        app, client = opened(ServerRequest("srq-1", "approval", {
            "command": "rm -rf ./x", "description": "recursive delete", "choices": ["once", "session", "always", "deny"],
        }))
        self.assertIn("▌   ★ always allow recursive delete (Hermes saves it)", drawn(app))
        press(app, Key(DOWN), Key(DOWN), Key(DOWN), Key(ENTER))
        self.assertEqual(client.answers, [("srq-1", {"result": {"choice": "always"}})])
        # The TUI sent the choice; that Hermes saved it is not something it saw.
        self.assertEqual(outcome_rows(app), [("always allow sent (Hermes saves it) · rm -rf ./x", NOTICE_OK)])

    def test_a_request_without_always_never_shows_or_sends_it(self) -> None:
        app, client = opened(ServerRequest("srq-1", "approval", {
            "command": "rm -rf ./x", "description": "recursive delete", "choices": ["once", "deny"], "smart_denied": True,
        }))
        self.assertFalse([row for row in drawn(app) if "always" in row])
        press(app, *[Key(DOWN)] * 6, Key(ENTER))
        self.assertNotIn("always", repr(client.answers))

    def test_an_approvals_answer_is_still_recorded_once(self) -> None:
        app, _client = opened(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        press(app, Key(ESCAPE))
        self.assertEqual(outcome_rows(app), [("denied · rm -rf ./x", NOTICE_ERROR)])


SID = "live-1"  # make_app's session


class WaitingTimeTests(unittest.TestCase):
    def clocked(self, cols: int = 80):
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0], cols=cols)
        app.busy_since = 90.0
        return app, client, now

    def tool(self, app, kind: str, **payload) -> None:
        app._on_event(Event(f"tool.{kind}", SID, {"tool_id": "t1", "name": "terminal", **payload}))

    def test_the_working_row_says_it_waits_on_you_with_one_clock(self) -> None:
        app, _client, now = self.clocked()
        self.assertTrue([row for row in drawn(app) if "Working… (10s" in row])
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        now[0] = 111.0
        screen = drawn(app)
        self.assertIn("? waiting on you (11s)", screen)  # the wait's clock, not the turn's 21s
        self.assertFalse([row for row in screen if "working" in row or "21s" in row], screen)
        armed(app)
        press(app, Key(ESCAPE))
        now[0] = 112.0
        # The deny also stops the turn: the row is the turn's own clock again, while Hermes stops it.
        self.assertTrue([row for row in drawn(app) if "interrupting… (22s" in row])

    def test_the_info_lines_activity_chip_keeps_no_second_clock_and_goes_with_the_turn(self) -> None:
        # The OMH HUD's in-flight chip counts the open call's own seconds; it lags the turn by a poll or more.
        from test_tui_panels import hud_payload

        from omh.tui.panels import HudSnapshot

        def status() -> str:
            screen = drawn(app)
            return screen[info_row_index(screen)]  # the info line, the region's last row

        app, _client, now = self.clocked(cols=100)  # room for the badge, a question's keys and the chip
        app.stored_id = "stored"
        payload = hud_payload()
        payload["activity"].update(live=True, post_tool_call_observed=True, open_call_count=1, oldest_open_elapsed_seconds=9)
        app.hud = HudSnapshot("stored", payload, now[0])
        self.assertIn("1 tool · 9s", status())  # while the turn runs, the call's seconds
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        now[0] = 114.0
        screen = drawn(app)
        self.assertIn("? waiting on you (14s)", screen)
        self.assertIn("1 tool", status())  # one clock: the wait's, on the working row
        self.assertNotIn("9s", status())
        armed(app)
        press(app, Key(DOWN), Key(ENTER))
        self.assertIn("1 tool · 9s", status())
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertNotIn("tool", status())  # the snapshot still says live; the turn is over
        self.assertTrue(status().startswith(INFO_INSET + "[⚚ OMH Native]   "), status())  # the badge alone on the left

    def test_back_to_back_questions_are_one_wait(self) -> None:
        app, _client, now = self.clocked()
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        app._on_server_request(TEXT_QUESTIONS[0][0])
        now[0] = 104.0
        armed(app)
        press(app, Key(ESCAPE))  # the sudo prompt opens as the approval closes
        now[0] = 107.0
        self.assertIn("? waiting on you (7s)", drawn(app))
        armed(app)
        press(app, Key(ESCAPE))
        self.assertEqual(app.turn_waited, 7.0)
        self.assertIsNone(app.waiting_since)

    def test_a_tools_duration_leaves_out_the_wait_on_you(self) -> None:
        for duration in ({"duration_s": 22.0}, {}):  # Hermes' own figure, or the TUI's from the start
            with self.subTest(duration=duration):
                app, _client, now = self.clocked()
                self.tool(app, "start", context="rm -rf ./x")
                now[0] = 101.0
                app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
                now[0] = 121.0
                armed(app)
                press(app, Key(DOWN), Key(ENTER))
                now[0] = 122.0
                self.tool(app, "complete", result="ok", **duration)
                (row,) = [tool for block in app.transcript.blocks if isinstance(block, ToolGroup) for tool in block.tools]
                self.assertAlmostEqual(row.duration_s, 2.0)

    def test_a_tool_running_beside_the_one_that_asked_keeps_its_own_duration(self) -> None:
        # Hermes runs some calls as one parallel batch (a read_file beside a write_file that asks), and a request
        # does not say which call asked. Only a wait a tool ran through from start to end can be the one it was
        # blocked on; one that began or ended while the tool ran is left in its duration.
        def event(kind: str, tool_id: str, **payload) -> None:
            app._on_event(Event(f"tool.{kind}", SID, {"tool_id": tool_id, "name": "read_file", **payload}))

        for hermes in (True, False):  # Hermes' own figure, or the TUI's from the start
            with self.subTest(duration_s=hermes):
                app, _client, now = self.clocked()
                event("start", "asker", context="AGENTS.md")
                event("start", "beside", context="a.py")
                now[0] = 101.0
                app._on_server_request(ServerRequest("srq-1", "approval", {"command": "write AGENTS.md"}))
                now[0] = 105.0
                event("complete", "beside", result="ok", **({"duration_s": 5.0} if hermes else {}))
                event("start", "later", context="b.py")
                now[0] = 110.0
                event("complete", "later", result="ok", **({"duration_s": 5.0} if hermes else {}))
                event("start", "across", context="c.py")
                now[0] = 121.0
                armed(app)
                press(app, Key(DOWN), Key(ENTER))
                now[0] = 122.0
                event("complete", "asker", result="ok", **({"duration_s": 22.0} if hermes else {}))
                now[0] = 125.0
                event("complete", "across", result="ok", **({"duration_s": 15.0} if hermes else {}))
                rows = {tool.tool_id: tool.duration_s for block in app.transcript.blocks if isinstance(block, ToolGroup)
                        for tool in block.tools}
                self.assertAlmostEqual(rows["asker"], 2.0)  # the wait it was blocked on is left out
                self.assertAlmostEqual(rows["beside"], 5.0)  # finished while the question waited
                self.assertAlmostEqual(rows["later"], 5.0)  # started while it waited
                self.assertAlmostEqual(rows["across"], 15.0)  # started while it waited, finished after it ended

    def test_a_tool_that_ran_before_the_wait_keeps_its_whole_duration(self) -> None:
        app, _client, now = self.clocked()
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        now[0] = 130.0
        armed(app)
        press(app, Key(ESCAPE))
        self.tool(app, "start", context="ls")
        now[0] = 133.0
        self.tool(app, "complete", result="ok", duration_s=3.0)
        (row,) = [tool for block in app.transcript.blocks if isinstance(block, ToolGroup) for tool in block.tools]
        self.assertAlmostEqual(row.duration_s, 3.0)

    def test_the_done_line_keeps_the_wall_clock_and_says_the_wait_beside_it(self) -> None:
        app, _client, now = self.clocked()
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        now[0] = 127.0
        armed(app)
        press(app, Key(ESCAPE))
        now[0] = 120.0 + 10.0
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        (summary,) = [block for block in app.transcript.blocks if isinstance(block, TurnSummaryBlock)]
        self.assertEqual((summary.seconds, summary.waited), (40.0, 27.0))
        self.assertTrue([row for row in drawn(app) if row.startswith("  ✻ 40s (27s waiting on you)")])

    def test_the_next_turn_starts_with_no_wait_whoever_started_it(self) -> None:
        for start in ("prompt", "message.start"):
            with self.subTest(start=start):
                app, _client, now = self.clocked()
                app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
                now[0] = 120.0
                armed(app)
                press(app, Key(ESCAPE))
                app._on_event(Event("message.complete", SID, {"text": "done"}))
                if start == "prompt":
                    type_text(app, "next")
                    press(app, Key(ENTER))
                else:  # a turn the TUI did not start
                    app._on_event(Event("message.start", SID, {}))
                now[0] = 125.0
                app._on_event(Event("message.complete", SID, {"text": "done"}))
                summaries = [block for block in app.transcript.blocks if isinstance(block, TurnSummaryBlock)]
                self.assertEqual([summary.waited for summary in summaries], [20.0, 0.0])

    def test_a_turn_without_a_question_says_no_wait(self) -> None:
        app, _client, now = self.clocked()
        now[0] = 130.0
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertTrue([row for row in drawn(app) if row.startswith("  ✻ 40s") and "waiting" not in row])


class QuestionAttentionTests(unittest.TestCase):
    QUESTIONS = (
        (ServerRequest("srq-1", "approval", {"command": "rm -rf ./x", "description": "recursive delete"}),
         "Hermes asks to run recursive delete"),
        (COLOUR, "Hermes asks: Which colour?"),
        (TEXT_QUESTIONS[0][0], "Hermes needs your sudo password"),
        (TEXT_QUESTIONS[1][0], "Hermes needs API_KEY"),
    )

    def written(self, environ: dict, request: ServerRequest) -> str:
        app, _client = make_app(busy=True, environ=environ)
        app._on_server_request(request)
        return "".join(app.terminal.writes)  # type: ignore[attr-defined]

    def test_every_question_fires_the_turn_ends_channel_with_the_bell_it_always_had(self) -> None:
        for request, said in self.QUESTIONS:
            with self.subTest(method=request.method):
                iterm = self.written({"TERM_PROGRAM": "iTerm.app"}, request)
                self.assertEqual(iterm.count(BELL), 1)
                self.assertIn(f"\x1b]9;{said}\x1b\\", iterm)
                foot = self.written({"TERM": "foot"}, request)
                self.assertIn(f"\x1b]777;notify;OMH;{said}\x1b\\", foot)
                elsewhere = self.written({"TERM_PROGRAM": "Apple_Terminal"}, request)
                self.assertEqual(elsewhere.count(BELL), 1)
                self.assertNotIn("\x1b]9;", elsewhere)
                self.assertNotIn("\x1b]777;", elsewhere)
                quiet = self.written({"TERM_PROGRAM": "iTerm.app", "OMH_TUI_BELL": "0"}, request)
                self.assertNotIn(BELL, quiet)
                self.assertNotIn("\x1b]9;", quiet)

    def test_a_request_alerts_once_as_it_opens_however_many_questions_it_carries(self) -> None:
        three = ServerRequest("srq-2", "clarify", {"questions": [{"qid": q, "question": f"{q}?"} for q in ("a", "b", "c")]})
        app, client = make_app(busy=True, environ={"TERM_PROGRAM": "Apple_Terminal"})
        app._on_server_request(three)
        app._on_server_request(TEXT_QUESTIONS[0][0])  # a sudo prompt waits behind it
        for answer in ("one", "two"):
            armed(app)
            type_text(app, answer)
            press(app, Key(ENTER))
        self.assertEqual(app.slot.question_index, 2)  # type: ignore[union-attr]  # on its third question
        self.assertEqual("".join(app.terminal.writes).count(BELL), 1)  # type: ignore[attr-defined]
        armed(app)
        type_text(app, "three")
        press(app, Key(ENTER))  # the last answer sends it; the sudo prompt opens, a request of its own
        self.assertEqual([request for request, _frame in client.answers], ["srq-2"])
        self.assertEqual("".join(app.terminal.writes).count(BELL), 2)  # type: ignore[attr-defined]

    def test_the_notification_never_says_a_value_and_stays_short(self) -> None:
        long = ServerRequest("srq-2", "clarify", {"questions": [{"qid": "q", "question": "Why " * 60}]})
        written = self.written({"TERM_PROGRAM": "iTerm.app"}, long)
        said = written[written.index("\x1b]9;") + 4 : written.index("\x1b\\", written.index("\x1b]9;"))]
        self.assertLessEqual(len(said), app_module.QUESTION_ALERT_CHARS)
        self.assertTrue(said.startswith("Hermes asks: Why Why"))


TELL_APPROVAL = ServerRequest("srq-1", "approval", {
    "command": "rm -rf ./x", "description": "recursive delete", "choices": ["once", "session", "deny"],
})


def mode_row(app) -> str:
    return without_badge(line_text(app._info_line(100)))


class TellRowTests(unittest.TestCase):
    def told(self, busy: bool = True, clock=None):
        """An approval answered from its tell row, over a draft; the app, its client and the draft's text."""
        app, client = make_app(busy=busy, **({"clock": clock} if clock else {}))
        type_text(app, "my draft")
        app._on_server_request(TELL_APPROVAL)
        armed(app)
        press(app, *[Key(DOWN)] * 3, Key(ENTER))
        return app, client

    def test_the_tell_row_denies_at_once_and_opens_a_labelled_composer(self) -> None:
        app, client = self.told()
        self.assertEqual(client.answers, [("srq-1", {"result": {"choice": "deny"}})])  # the turn is not held
        self.assertEqual(outcome_rows(app), [("denied · rm -rf ./x", NOTICE_ERROR)])
        self.assertIsNone(app.slot)
        self.assertEqual(app.composer.text, "")  # a field of its own; the draft is set aside
        self.assertEqual(app.tell_draft.text, "my draft")  # type: ignore[union-attr]
        self.assertIn(app_module.TELL_SAY[0], mode_row(app))
        self.assertNotIn("esc to interrupt", mode_row(app))  # Esc leaves the field, it interrupts nothing
        self.assertIn(f"❯ {app_module.TELL_PLACEHOLDER}", [composer_text(row) for row in drawn(app)])
        self.assertEqual(client.named("session.steer"), [])  # nothing is sent until the person sends it

    def test_what_is_sent_goes_into_the_running_turn_as_a_steer_and_the_draft_comes_back(self) -> None:
        for key in (Key(ENTER), Key(ENTER, ctrl=True)):
            with self.subTest(key=key):
                app, client = self.told()
                type_text(app, "use ./tmp instead")
                press(app, key)
                self.assertEqual(client.named("session.steer"), [{"session_id": SID, "text": "use ./tmp instead"}])
                self.assertEqual(client.named("prompt.submit"), [])
                self.assertIsNone(app.tell_draft)
                self.assertEqual(app.composer.text, "my draft")
                self.assertNotIn(app_module.TELL_SAY[0], mode_row(app))

    def test_a_steer_hermes_refuses_waits_in_the_queue_like_any_steer(self) -> None:
        app, client = self.told()
        type_text(app, "use ./tmp instead")
        press(app, Key(ENTER))
        app._on_response(Response(len(client.calls), {"status": "rejected", "text": "use ./tmp instead"}, None))
        self.assertEqual([line.text for line in app.queued], ["use ./tmp instead"])
        self.assertEqual(client.named("prompt.submit"), [])

    def test_a_steer_hermes_never_answers_comes_back_after_the_usual_wait(self) -> None:
        now = [100.0]
        app, client = self.told(clock=lambda: now[0])
        type_text(app, "use ./tmp instead")
        press(app, Key(ENTER))
        now[0] += app_module.CALL_ANSWER_SECONDS
        app._expire_calls()
        self.assertEqual(app.composer.text, "my draft\nuse ./tmp instead")  # given back, never sent again
        self.assertEqual(len(client.named("session.steer")), 1)

    def test_once_the_turn_has_ended_it_goes_as_an_ordinary_prompt(self) -> None:
        app, client = self.told()
        app.turn_pending = False
        type_text(app, "use ./tmp instead")
        press(app, Key(ENTER))
        self.assertEqual(client.named("session.steer"), [])
        self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": "use ./tmp instead"}])

    def test_after_the_denied_turn_ended_it_never_steers_the_queued_prompt_that_runs_now(self) -> None:
        for mode in sorted(app_module.BUSY_MODES):
            with self.subTest(busy_mode=mode):
                app, client = make_app(busy=True)
                app.busy_mode = mode
                app.queued.append(app_module.QueuedLine("queued P"))
                app._on_server_request(TELL_APPROVAL)
                armed(app)
                press(app, *[Key(DOWN)] * 3, Key(ENTER))
                app._on_event(Event("message.complete", SID, {"text": "ok"}))  # the denied turn ends on its own
                self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": "queued P", "queued": True}])
                type_text(app, "use ./tmp instead")
                press(app, Key(ENTER))
                self.assertEqual(client.named("session.steer"), [])
                self.assertEqual([line.text for line in app.queued], ["use ./tmp instead"])  # behind P's turn
                app._on_event(Event("message.complete", SID, {"text": "done"}))
                self.assertEqual(client.named("prompt.submit")[-1],
                                 {"session_id": SID, "text": "use ./tmp instead", "queued": True})

    def test_a_queue_taken_back_after_a_stopping_deny_goes_into_the_draft_behind_the_field(self) -> None:
        app, client = make_app(busy=True)
        app.queued.append(app_module.QueuedLine("queued P"))
        app._on_server_request(TELL_APPROVAL)
        armed(app)
        press(app, *[Key(DOWN)] * 3, Key(ENTER))  # the field opens over an empty draft
        type_text(app, "use ./tmp")
        app._on_server_request(ServerRequest("srq-2", "approval", dict(TELL_APPROVAL.params)))
        armed(app)
        press(app, Key(ESCAPE))  # this deny stops the turn
        self.assertEqual(client.named("session.interrupt"), [{"session_id": SID}])
        app._on_event(Event("message.complete", SID, {"text": ""}))
        self.assertEqual(app.composer.text, "use ./tmp")  # the field is left as it was
        self.assertEqual(app.tell_draft.text, "queued P")  # type: ignore[union-attr]
        self.assertEqual(client.named("prompt.submit"), [])
        said = [block.text for block in app.transcript.blocks if isinstance(block, NoticeBlock)]
        self.assertIn(app_module.QUEUE_BACK_HIDDEN_NOTICE.format(why=app_module.INTERRUPTED_WHY), said)
        self.assertNotIn(app_module.QUEUE_BACK_NOTICE.format(why=app_module.INTERRUPTED_WHY), said)

    def test_esc_sends_nothing_more_and_keeps_what_was_typed_in_this_sessions_history(self) -> None:
        app, client = self.told()
        type_text(app, "half a thought")
        calls = list(client.calls)
        press(app, Key(ESCAPE))
        self.assertEqual(client.calls, calls)
        self.assertEqual(client.answers, [("srq-1", {"result": {"choice": "deny"}})])  # the one deny, nothing after
        self.assertIsNone(app.tell_draft)
        self.assertEqual(app.composer.text, "my draft")
        self.assertEqual(app.composer.history[-1], "half a thought")

    def test_an_empty_send_keeps_the_field_waiting(self) -> None:
        app, client = self.told()
        press(app, Key(ENTER))
        self.assertIsNotNone(app.tell_draft)
        self.assertEqual(client.named("session.steer"), [])

    def test_a_question_that_arrives_meanwhile_takes_the_keys_and_gives_the_field_back(self) -> None:
        app, client = self.told()
        type_text(app, "use ./tmp")
        app._on_server_request(ServerRequest("srq-2", "approval", {"command": "ls"}))
        self.assertTrue(app._composer_hidden())
        armed(app)
        press(app, Key(ESCAPE))  # denies the second approval; the field stays as it was
        self.assertEqual(app.composer.text, "use ./tmp")
        self.assertIn(app_module.TELL_SAY[0], mode_row(app))
        press(app, Key(ENTER))
        self.assertEqual(client.named("session.steer"), [{"session_id": SID, "text": "use ./tmp"}])

    def test_a_second_tell_row_keeps_the_open_field_and_the_draft_behind_it(self) -> None:
        # The tell row lets the turn go on, so the next approval can come while its field is open.
        app, client = self.told()
        type_text(app, "first tell")
        app._on_server_request(ServerRequest("srq-2", "approval", dict(TELL_APPROVAL.params)))
        armed(app)
        press(app, *[Key(DOWN)] * 3, Key(ENTER))
        self.assertEqual(client.answers[-1], ("srq-2", {"result": {"choice": "deny"}}))
        self.assertEqual(app.composer.text, "first tell")  # the field stays open, what was typed in it kept
        self.assertEqual(app.tell_draft.text, "my draft")  # type: ignore[union-attr]
        self.assertIn(app_module.TELL_SAY[0], mode_row(app))
        type_text(app, ", then this")
        press(app, Key(ENTER))
        self.assertEqual(client.named("session.steer"), [{"session_id": SID, "text": "first tell, then this"}])
        self.assertIsNone(app.tell_draft)
        self.assertEqual(app.composer.text, "my draft")

    def test_a_text_question_waiting_behind_the_approval_gets_its_own_field_and_gives_the_tell_field_back(self) -> None:
        app, client = make_app(busy=True)
        type_text(app, "my draft")
        app._on_server_request(TELL_APPROVAL)
        app._on_server_request(TEXT_QUESTIONS[0][0])  # a sudo prompt waits behind it
        armed(app)
        press(app, *[Key(DOWN)] * 3, Key(ENTER))
        self.assertEqual(app.slot.method, "sudo")  # type: ignore[union-attr]
        self.assertTrue(app.composer.masked)  # the sudo prompt's own field, not the tell field
        armed(app)
        type_text(app, "hunter2")
        press(app, Key(ENTER))
        self.assertEqual(client.answers[-1], ("srq-3", {"result": {"value": "hunter2"}}))
        self.assertFalse(app.composer.masked)
        self.assertEqual(app.composer.text, "")
        self.assertEqual(app.tell_draft.text, "my draft")  # type: ignore[union-attr]
        self.assertIn(app_module.TELL_SAY[0], mode_row(app))

    def test_the_working_row_offers_no_interrupt_while_the_field_is_open(self) -> None:
        app, _client = make_app(busy=True)  # no draft: an empty composer during a turn offers Esc for the interrupt
        app._on_server_request(TELL_APPROVAL)
        armed(app)
        press(app, *[Key(DOWN)] * 3, Key(ENTER))
        self.assertFalse([row for row in drawn(app) if "esc to interrupt" in row])
        press(app, Key(ESCAPE))
        self.assertTrue([row for row in drawn(app) if "esc to interrupt" in row])

    def test_a_steer_given_back_meanwhile_lands_in_the_draft_not_in_the_field(self) -> None:
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        type_text(app, "an earlier steer")
        press(app, Key(ENTER, ctrl=True))  # Hermes will never answer it
        type_text(app, "my draft")
        app._on_server_request(TELL_APPROVAL)
        armed(app)
        press(app, *[Key(DOWN)] * 3, Key(ENTER))
        type_text(app, "use ./tmp")
        now[0] += app_module.CALL_ANSWER_SECONDS
        app._expire_calls()
        self.assertEqual(app.composer.text, "use ./tmp")
        self.assertEqual(app.tell_draft.text, "my draft\nan earlier steer")  # type: ignore[union-attr]

    def test_leaving_the_session_leaves_the_field_with_nothing_sent(self) -> None:
        app, client = self.told()
        type_text(app, "use ./tmp")
        app._enter_session({"session_id": "other", "info": {}})
        self.assertIsNone(app.tell_draft)
        self.assertEqual(app.composer.text, "my draft")
        self.assertEqual(client.named("session.steer"), [])


class WireClient(RecordingClient):
    """A recording client that also keeps answers and calls in the order they would reach the gateway."""

    def __init__(self) -> None:
        super().__init__()
        self.wire: list[tuple[str, ...]] = []

    def request(self, method: str, params: dict) -> int:
        number = super().request(method, params)
        self.wire.append(("call", method))
        return number

    def respond(self, request_id: str, frame: dict) -> None:
        super().respond(request_id, frame)
        self.wire.append(("answer", request_id, json.dumps(frame, sort_keys=True)))


DENY = ("answer", "srq-1", json.dumps({"result": {"choice": "deny"}}))
STOP = ("call", "session.interrupt")


class DenyStopsTests(unittest.TestCase):
    """Owner decision 11: every deny the person gives an approval sends the deny, then stops the running turn."""

    def wired(self, request: ServerRequest = TELL_APPROVAL, busy: bool = True) -> tuple[App, WireClient]:
        client = WireClient()
        app = App(ScriptedTerminal(24, 80), client, {}, poller=FakePoller())  # type: ignore[arg-type]
        app.sid = SID
        app.turn_pending = busy
        app._on_server_request(request)
        armed(app)
        return app, client

    def test_every_deny_key_sends_the_deny_then_the_interrupt(self) -> None:
        keys = {
            "esc": [Key(ESCAPE)], "ctrl+c": [Key(CHAR, "c", ctrl=True)], "d": [Key(CHAR, "d")], "n": [Key(CHAR, "n")],
            "D": [Key(CHAR, "D")], "enter on deny": [Key(ENTER)], "up then enter typed ahead": [Key(UP), Key(ENTER)],
            "down, up, enter": [Key(DOWN), Key(UP), Key(ENTER)],
        }
        for name, presses in keys.items():
            with self.subTest(keys=name):
                app, client = self.wired()
                press(app, *presses)
                self.assertEqual(client.wire, [DENY, STOP])
                self.assertEqual(client.named("session.interrupt"), [{"session_id": SID}])
                self.assertIsNone(app.slot)

    def test_with_no_turn_running_the_deny_goes_alone(self) -> None:
        for presses in ([Key(ESCAPE)], [Key(CHAR, "d")], [Key(ENTER)]):
            with self.subTest(presses=presses):
                app, client = self.wired(busy=False)
                press(app, *presses)
                self.assertEqual(client.wire, [DENY])

    def test_the_tell_row_denies_and_steers_but_never_stops_the_turn(self) -> None:
        app, client = self.wired()
        press(app, *[Key(DOWN)] * 3, Key(ENTER))
        self.assertEqual(client.wire, [DENY])
        type_text(app, "use ./tmp")
        press(app, Key(ENTER))
        self.assertEqual(client.wire, [DENY, ("call", "session.steer")])

    def test_allowing_stops_nothing(self) -> None:
        app, client = self.wired()
        press(app, Key(DOWN), Key(ENTER))
        self.assertEqual(client.wire, [("answer", "srq-1", json.dumps({"result": {"choice": "once"}}))])

    def test_the_tuis_own_declines_stop_nothing(self) -> None:
        app, client = self.wired()
        app._decline_all_requests()  # a session being left: the TUI's decline, not the person's deny
        self.assertEqual(client.wire, [DENY])
        app, client = self.wired(request=COLOUR)
        press(app, Key(ESCAPE))  # a clarify cancel is no approval deny
        self.assertEqual(client.wire, [("answer", "srq-7", json.dumps({"result": {}}))])


class DocumentedQuestionViewTests(unittest.TestCase):
    def test_installation_shows_the_markers_the_slot_draws(self) -> None:
        installation = " ".join((Path(__file__).resolve().parents[1] / "docs" / "INSTALLATION.md").read_text(
            encoding="utf-8").split())
        self.assertIn(f"`{prompts.MORE_ANY_ROWS[0].strip()}`", installation)
        self.assertIn(f"`{prompts.MORE_ROWS[0].strip().format(count=14, s='s')}`", installation)
        self.assertIn("Ctrl+O opens the whole question in the pager: it answers nothing", installation)
        self.assertIn(f"(`{prompts.WAITING.strip().format(count=1, s='')}`)", installation)
        for word in (prompts.OUTCOME_CANCELLED, prompts.OUTCOME_SKIPPED, *prompts.WITHDRAWN_WORDS.values()):
            self.assertIn(f"`✗ {word}", installation)
        self.assertIn("`✓ answered · sudo password`", installation)
        always = prompts.open_request("srq-1", "approval", {"description": "recursive delete", "choices": ["always"]})
        self.assertIn(f"(`{always.approval_label('always')}`)", installation)  # type: ignore[union-attr]
        self.assertNotIn("Approving a command permanently stays a choice for `hermes --tui`", installation)
        self.assertIn(f"labelled `{app_module.TELL_SAY[0]}` on the info line", installation)
        self.assertIn(f"which is what the info line's `{prompts.APPROVAL_KEYS[-1]}` says", installation)
        self.assertIn("When the approval came from a subagent, that stops the session's whole running turn", installation)
        tell = prompts.open_request("srq-1", "approval", {})
        self.assertIn(f"last {tell.approval_label(prompts.APPROVAL_TELL)}, one per row", installation)  # type: ignore[union-attr]
        self.assertIn(f"`{app_module.WAITING_GLYPH}{app_module.STATE_WAITING} (11s)`", installation)
        self.assertIn("`✻ 30s" + TURN_WAITED.format(elapsed="27s") + " · 1 tool`", installation)
        self.assertIn("`✗ declined · sudo password`", installation)
        self.assertIn("`✗ " + prompts.WITHDRAWN.format(reason="<Hermes' reason>") + "`", installation)


class DocumentedBoundaryTests(unittest.TestCase):
    """The OMH TUI boundary page and CONTEXT.md's entry name the always and tell rows the code draws."""

    ROOT = Path(__file__).resolve().parents[1]

    def prose(self, name: str) -> str:
        return " ".join((self.ROOT / name).read_text(encoding="utf-8").split())

    def test_the_boundary_names_both_rows_and_the_third_steer_path(self) -> None:
        agents = self.prose("docs/OMH-TUI-BOUNDARY.md")
        tell = prompts.open_request("srq-1", "approval", {}).approval_label(prompts.APPROVAL_TELL)  # type: ignore[union-attr]
        self.assertIn(f'An approval\'s last row, "{tell}", sends the explicit deny at once, interrupts nothing,', agents)
        self.assertIn("an approval decline is an explicit deny and then interrupts the running turn (`session.interrupt`, "
                      "only while a turn runs; every deny the person gives an approval does, `d`, `n` and Enter on deny "
                      "too, except the tell row's below)", agents)
        self.assertIn("Hermes' `always` choice is offered only when the request lists it and is sent, like any allow, "
                      "only on the person's arrows and then Enter", agents)
        self.assertIn("A steer (Ctrl+Enter, `/steer`, or what the person sends from the composer the tell row opened) "
                      "sends into the running turn only text the person typed and sent that way", agents)
        self.assertIn("the TUI never steers on its own, and a queued prompt becomes a steer only when the person presses "
                      "the send-now key", agents)

    def test_the_glossary_says_what_the_two_rows_send(self) -> None:
        context = self.prose("CONTEXT.md")
        entry = context[context.index("**OMH TUI**:") : context.index("**Hermes gateway protocol**:")]
        self.assertIn("Every deny the person gives an approval also interrupts the running turn, except its last row's, "
                      "which denies and sends what the person then types into the running turn as a steer; its `always` "
                      "row, there only when Hermes offers it, sends Hermes' own permanent allow, which Hermes saves.", entry)

    def test_direction_says_a_deny_also_stops_the_turn(self) -> None:
        self.assertIn("answers no request on their behalf; a deny the person gives an approval also interrupts the "
                      "running turn, as Claude Code's Esc does, except the deny from the row that tells Hermes what to "
                      "do instead)", self.prose("docs/DIRECTION.md"))

    def test_the_boundary_names_what_ctrl_z_does_to_the_gateway(self) -> None:
        agents = self.prose("docs/OMH-TUI-BOUNDARY.md")
        # The child is in the TUI's process group; a shared gateway it attached to is not, and goes on.
        self.assertIn("Ctrl+Z stops the process group, the gateway child with it, as Hermes' own CLI's Ctrl+Z does, "
                      "and fg continues both; a shared gateway, which is not in that group, goes on.", agents)
        context = self.prose("CONTEXT.md")
        self.assertIn("Ctrl+Z stops its process group, the gateway child with it, as Hermes' own CLI's Ctrl+Z does.",
                      context)


class TinyTerminalQuestionTests(unittest.TestCase):
    def test_a_question_answered_with_text_keeps_its_label_on_a_tiny_terminal(self) -> None:
        for rows, cols in ((4, 80), (5, 80), (24, MIN_COLS - 1)):
            for request, label in TEXT_QUESTIONS:
                with self.subTest(rows=rows, cols=cols, method=request.method):
                    app, _client = make_app(busy=True, rows=rows, cols=cols)
                    app._on_server_request(request)
                    screen = drawn(app)
                    (row,) = [line for line in screen if line.startswith("▌ ")]
                    shown = row[2:].removeprefix("🔑 ").removeprefix("? ").split(" …")[0].rstrip("…")
                    self.assertTrue(shown and label.startswith(shown), row)
                    self.assertTrue([line for line in screen if line.startswith("❯")], screen)  # the composer under it

    def test_the_label_row_is_the_text_questions_alone(self) -> None:
        # A tiny terminal still gives a panel, a menu or a picked list nothing beyond what it gave before.
        self.assertEqual(allocate(5, 80, sticky=False, tail_rows=0, slot_rows=4, composer_rows=1, min_height=0).slot, 0)
        self.assertEqual(
            allocate(5, 80, sticky=False, tail_rows=0, slot_rows=4, composer_rows=1, min_height=0, text_question=True).slot, 1
        )
        self.assertEqual(
            allocate(3, 80, sticky=False, tail_rows=0, slot_rows=4, composer_rows=1, min_height=0, text_question=True).slot, 0
        )
        roomy = dict(sticky=False, tail_rows=0, slot_rows=9, composer_rows=1, min_height=0)
        self.assertEqual(allocate(24, 80, **roomy, text_question=True), allocate(24, 80, **roomy))


if __name__ == "__main__":
    unittest.main()
