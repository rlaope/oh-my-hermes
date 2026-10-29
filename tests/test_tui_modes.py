"""Steering, input modes, effort, the queue rows, the key guide and the approval bell.

Two harnesses. Most cases drive an `App` whose gateway client only records:
the test sends keys through `App._on_input`, reads the calls the app made, and
hands back the answer it wants through `App._on_response`, so a refusal, a
wrong scope or a late answer is one line. Every recorded call is checked
against the gateway contract the way `GatewayClient` checks it before a byte
is written. The end-to-end cases run `main` against the replay gateway from
`test_tui_app`, with `session.steer` and `config.set` answered from the
scenario's answer table in Hermes 6c61c3e27d's shapes.
"""

from __future__ import annotations

import ast
import base64
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
from unittest.mock import patch

from _tui_gateway_replay import Scenario, spans
from _tui_lines import composer_text, INFO_INSET, line_text, lines_text, rule_edges, RULE_ROW, without_badge
from test_tui_app import (
    INTERRUPTED,
    LIVE_ID,
    NO_TERMIOS,
    UNREAD_DEFAULT,
    AppTestCase,
    FakePoller,
    ScriptedTerminal,
    Step,
    startup_answers,
    info_row_of,
)
from omh.tui import app as app_module
from omh.tui import gateway_contract as contract
from omh.tui import modes as modes_module
from omh.tui.app import (
    ATTACH_LEFT_NOTICE, OSC52_COPY, SLOT_ARM_SECONDS, STEER_FALLBACK_KEY, App, QueuedLine, queue_lines,
)
from omh.tui.frame import MODE_ACCEPT, MODE_ACCEPT_PLAN, MODE_NORMAL, MODE_PLAN
from omh.tui.gateway import Event, GatewayUnavailable, Response, ServerRequest
from omh.tui.keys import CHAR, DOWN, ENTER, TAB, UP, Key, KeyDecoder, Paste
from omh.tui.layout import MIN_COLS, MIN_ROWS, slot_cap
from omh.tui.modes import EFFORT_CYCLE
from omh.tui.pager import Pager
from omh.tui.session_picker import SessionPicker, SessionRow
from omh.tui.slash import parse_slash, plan_invocation
from omh.tui.theme import DEFAULT_THEME
from omh.tui.transcript import (
    NOTICE_ERROR,
    NOTICE_WARN,
    STEER_QUEUED,
    AssistantBlock,
    CommandBlock,
    NoticeBlock,
    SteerBlock,
    UserBlock,
    block_rows,
)
from omh.tui.width import line_width

SID = "live-1"
CTRL_ENTER = Key(ENTER, ctrl=True)
CTRL_ENTER_BYTES = b"\x1b[13;5u"  # kitty CSI u; modifyOtherKeys sends ESC[27;5;13~
SHIFT_TAB = Key(TAB, shift=True)
SHIFT_TAB_BYTES = b"\x1b[Z"
# Hermes 6c61c3e27d's answers to the per-session switch (`_set_yolo`, methods_config_set.py).
YOLO_IS_ON = {"key": "yolo", "value": "1", "scope": "session"}
YOLO_IS_OFF = {"key": "yolo", "value": "0", "scope": "session"}
YOLO_ON_CALL = ("config.set", {"key": "yolo", "session_id": SID, "value": "on"})
YOLO_OFF_CALL = ("config.set", {"key": "yolo", "session_id": SID, "value": "off"})
CTRL_T = Key(CHAR, "t", ctrl=True)
PLAN_PROMPT = "[/plan — plan mode]\n\nFor this turn, you are in PLAN MODE.\n\nTask to plan:\nfix the flaky test\n"


class RecordingClient:
    """What `App` needs from a gateway client, kept in memory; nothing is spawned."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.answers: list[tuple[str, dict]] = []
        self.inbox: list[object] = []  # what the next `poll` hands the loop
        self.forgotten: list[int] = []  # request ids the app stopped waiting for

    def poll(self) -> list[object]:
        items, self.inbox = self.inbox, []
        return items

    def wake_fd(self) -> None:
        return None  # nothing to select on: a test drives the loop's reads itself

    def wake(self) -> None:
        pass  # no descriptor to make readable

    def request(self, method: str, params: dict) -> int:
        problem = contract.call_problem(method, params)
        if problem:
            raise ValueError(problem)
        self.calls.append((method, params))
        return len(self.calls)

    def respond(self, request_id: str, frame: dict) -> None:
        self.answers.append((request_id, frame))

    def forget(self, request_id: int) -> None:
        self.forgotten.append(request_id)

    def named(self, method: str) -> list[dict]:
        return [params for name, params in self.calls if name == method]


def make_app(*, busy: bool = False, rows: int = 24, cols: int = 80, **options: object) -> tuple[App, RecordingClient]:
    client = RecordingClient()
    # The working glow's margin moves every row and the living wallpaper paints the blank cells; their own tests
    # turn them on.
    environ = {"OMH_TUI_GLOW": "0", "OMH_TUI_WALLPAPER": "0", **options.pop("environ", {})}  # type: ignore[dict-item]
    app = App(ScriptedTerminal(rows, cols), client, environ, poller=FakePoller(), **options)  # type: ignore[arg-type]
    app.sid = SID
    app.turn_pending = busy
    app.launch_layout = False  # a session past its launch; the launch's full-screen frame is OpeningTests' (real loop)
    return app, client


def type_text(app: App, text: str) -> None:
    for char in text:
        app._on_input(Key(CHAR, char))


def answer(app: App, client: RecordingClient, result: dict | None = None, error: dict | None = None) -> None:
    """Answer the newest call."""
    app._on_response(Response(len(client.calls), result, error))


def show_mode(app: App, mode: str) -> None:
    """Put `app` in `mode` as the composer shows it: accept (approvals off), plan (the TUI's flag), or both."""
    app.approvals_off = mode in (MODE_ACCEPT, MODE_ACCEPT_PLAN)
    app.plan_mode = mode in (MODE_PLAN, MODE_ACCEPT_PLAN)


def notices(app: App, level: str | None = None) -> list[str]:
    """What the transcript said, in order: each notice, and each part of a command's output under its echo."""
    said: list[str] = []
    for block in app.transcript.blocks:
        if isinstance(block, NoticeBlock):
            parts = [(block.text, block.level)]
        elif isinstance(block, CommandBlock):
            parts = block.parts
        else:
            continue
        said += [text for text, kind in parts if level is None or kind == level]
    return said


def steers_of(blocks: list) -> list[str]:
    return [line_text(row) for block in blocks if isinstance(block, SteerBlock) for row in block_rows(block, 100, DEFAULT_THEME)]


def steers(app: App) -> list[str]:
    """The steer rows the transcript has written (one Hermes has not answered yet is still held under the tail)."""
    return steers_of(app.transcript.blocks)


class SteerTests(unittest.TestCase):
    def test_ctrl_enter_during_a_turn_steers_with_the_typed_text(self) -> None:
        app, client = make_app(busy=True)
        type_text(app, "use the other file")
        app._on_input(CTRL_ENTER)
        self.assertEqual(client.calls, [("session.steer", {"session_id": SID, "text": "use the other file"})])
        self.assertEqual(app.composer.text, "")
        self.assertEqual(steers(app), [])  # nothing is claimed before Hermes answers
        self.assertIn("↪ steer · use the other file", lines_text(app.transcript.live_lines(80, DEFAULT_THEME)))
        answer(app, client, {"status": "queued", "text": "use the other file"})
        self.assertEqual(steers(app), ["↪ steer queued by Hermes · use the other file"])
        self.assertEqual(client.named("prompt.submit"), [])
        self.assertFalse(app.queued)

    def test_the_steered_notice_names_only_the_first_line(self) -> None:
        app, client = make_app(busy=True)
        type_text(app, "first line")
        app._on_input(Key(ENTER, shift=True))
        type_text(app, "second line")
        app._on_input(CTRL_ENTER)
        self.assertEqual(client.named("session.steer"), [{"session_id": SID, "text": "first line\nsecond line"}])
        answer(app, client, {"status": "queued", "text": "first line\nsecond line"})
        self.assertEqual(steers(app), ["↪ steer queued by Hermes · first line"])

    def test_ctrl_enter_while_idle_is_enter(self) -> None:
        sent = []
        for key in (Key(ENTER), CTRL_ENTER):
            app, client = make_app()
            type_text(app, "a prompt")
            app._on_input(key)
            sent.append(client.calls)
        self.assertEqual(sent[0], [("prompt.submit", {"session_id": SID, "text": "a prompt"})])
        self.assertEqual(sent[1], sent[0])

    def test_a_rejected_steer_goes_as_a_normal_prompt(self) -> None:
        # The turn ended before the text arrived: idle by the time the answer is read, so it is sent now.
        app, client = make_app(busy=True)
        type_text(app, "too late")
        app._on_input(CTRL_ENTER)
        app.turn_pending = False
        answer(app, client, {"status": "rejected", "text": "too late"})
        self.assertEqual(client.calls[1:], [("prompt.submit", {"session_id": SID, "text": "too late"})])
        self.assertEqual(notices(app), [])

    def test_a_rejected_steer_while_the_tui_still_waits_on_a_turn_joins_the_queue(self) -> None:
        app, client = make_app(busy=True)
        type_text(app, "too early")
        app._on_input(CTRL_ENTER)
        answer(app, client, {"status": "rejected", "text": "too early"})
        self.assertEqual([text for text, *_ in app.queued], ["too early"])
        self.assertEqual(client.named("prompt.submit"), [])

    def test_a_steer_hermes_cannot_take_is_not_lost(self) -> None:
        # 4010: the agent is still starting, or takes no steer.
        app, client = make_app(busy=True)
        type_text(app, "keep this")
        app._on_input(CTRL_ENTER)
        answer(app, client, error={"code": 4010, "message": "agent does not support steer"})
        self.assertEqual([text for text, *_ in app.queued], ["keep this"])
        (warning,) = steers(app)
        self.assertEqual(warning, "⧗ queued — Hermes refused the steer (agent does not support steer) · keep this")

    def test_a_steer_hermes_does_not_take_never_interrupts_the_turn_whatever_the_busy_mode(self) -> None:
        # Under `interrupt` (Hermes' default) or `steer`, a prompt.submit mid-turn redirects the turn.
        refusals = {"rejected": {"result": {"status": "rejected", "text": "and the docs"}},
                    "4010": {"error": {"code": 4010, "message": "agent does not support steer"}}}
        for mode in ("interrupt", "steer", "queue"):
            for name, frame in refusals.items():
                with self.subTest(mode=mode, refusal=name):
                    app, client = make_app(busy=True)
                    app.busy_mode = mode
                    type_text(app, "and the docs")
                    app._on_input(CTRL_ENTER)
                    app._on_response(Response(1, frame.get("result"), frame.get("error")))
                    self.assertEqual(client.named("prompt.submit"), [])
                    self.assertEqual([text for text, *_ in app.queued], ["and the docs"])
                    app._on_event(Event("message.complete", SID, {"text": "done"}))  # the turn ends: it goes now
                    self.assertEqual(
                        client.named("prompt.submit"), [{"session_id": SID, "text": "and the docs", "queued": True}]
                    )

    def test_a_steer_refused_once_the_session_is_idle_goes_as_a_prompt_at_once(self) -> None:
        for mode in ("interrupt", "queue"):
            with self.subTest(mode=mode):
                app, client = make_app(busy=True)
                app.busy_mode = mode
                type_text(app, "too late")
                app._on_input(CTRL_ENTER)
                app.turn_pending = False
                answer(app, client, error={"code": 4010, "message": "agent does not support steer"})
                self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": "too late"}])
                self.assertIn("sent as a prompt — Hermes refused the steer (agent", steers(app)[0])

    def test_in_plan_mode_the_refused_steer_waits_as_the_plan_prompt(self) -> None:
        app, client = make_app(busy=True)
        app.busy_mode = "interrupt"
        show_mode(app, MODE_PLAN)
        type_text(app, "fix the flaky test")
        app._on_input(CTRL_ENTER)
        answer(app, client, {"status": "rejected", "text": "fix the flaky test"})
        self.assertEqual(client.calls[-1], ("slash.exec", {"command": "plan fix the flaky test", "session_id": SID}))
        answer(app, client, {"type": "send", "message": PLAN_PROMPT})
        self.assertEqual(client.named("prompt.submit"), [])
        self.assertEqual([text for text, *_ in app.queued], [PLAN_PROMPT])

    def test_the_notice_for_a_taken_steer_is_true_of_both_things_hermes_means_by_queued(self) -> None:
        # Hermes 6c61c3e27d answers {"status": "queued", "text": ...} when the turn takes the steer
        # (_apply_correction) and when it queues the text as the next prompt during compression.
        app, client = make_app(busy=True)
        type_text(app, "check the tests too")
        app._on_input(CTRL_ENTER)
        answer(app, client, {"status": "queued", "text": "check the tests too"})
        (row,) = steers(app)
        self.assertEqual(row, "↪ steer queued by Hermes · check the tests too")
        self.assertNotIn("applied", row)

    def test_ctrl_enter_with_nothing_typed_sends_nothing(self) -> None:
        app, client = make_app(busy=True)
        app._on_input(CTRL_ENTER)
        type_text(app, "   ")
        app._on_input(CTRL_ENTER)
        self.assertEqual(client.calls, [])

    def test_ctrl_enter_on_a_slash_command_runs_the_command(self) -> None:
        app, client = make_app(busy=True)
        type_text(app, "/queue")
        app._on_input(CTRL_ENTER)
        self.assertEqual(client.calls, [])
        self.assertEqual(notices(app), ["Nothing is queued."])

    def test_ctrl_enter_answers_an_open_question_instead_of_steering(self) -> None:
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        app._on_server_request(ServerRequest("srq-1", "vault.code", {}))
        now[0] += SLOT_ARM_SECONDS
        type_text(app, "123456")
        app._on_input(CTRL_ENTER)
        self.assertEqual(client.answers, [("srq-1", {"result": {"value": "123456"}})])
        self.assertEqual(client.calls, [])

    def test_the_steer_command_steers_a_running_turn_and_sends_a_prompt_when_idle(self) -> None:
        app, client = make_app(busy=True)
        type_text(app, "/steer check the tests too")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("session.steer", {"session_id": SID, "text": "check the tests too"})])
        answer(app, client, {"status": "queued", "text": "check the tests too"})
        self.assertEqual(steers(app), ["↪ steer queued by Hermes · check the tests too"])

        app, client = make_app()
        type_text(app, "/steer check the tests too")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("prompt.submit", {"session_id": SID, "text": "check the tests too"})])

    def test_the_steer_command_without_text_says_how_and_sends_nothing(self) -> None:
        for busy in (True, False):
            with self.subTest(busy=busy):
                app, client = make_app(busy=busy)
                type_text(app, "/steer")
                app._on_input(Key(ENTER))
                self.assertEqual(client.calls, [])
                self.assertEqual(notices(app, NOTICE_WARN), ["Usage: /steer <text to add to the running turn>"])

    def test_a_queued_prompt_is_sent_as_a_prompt_never_as_a_steer(self) -> None:
        app, client = make_app(busy=True)
        type_text(app, "wait for the turn")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [])
        app.turn_pending = False
        app._drain_queue()
        self.assertEqual(
            client.calls, [("prompt.submit", {"session_id": SID, "text": "wait for the turn", "queued": True})]
        )

    def test_a_steer_answered_after_its_session_was_left_comes_back_to_the_composer(self) -> None:
        answers = {
            "rejected": ({"status": "rejected", "text": "keep this"}, None),
            "refused": (None, {"code": 4010, "message": "agent does not support steer"}),
            "taken": ({"status": "queued", "text": "keep this"}, None),
        }
        for name, (result, error) in answers.items():
            for leave in ("new", "switch"):
                with self.subTest(answer=name, leave=leave):
                    app, client = make_app(busy=True)
                    type_text(app, "keep this")
                    app._on_input(CTRL_ENTER)
                    steer = len(client.calls)
                    if leave == "new":
                        app._on_new_session({"session_id": "live-2", "stored_session_id": "stored-2"})
                    else:
                        app._on_session_resumed("stored-2", {"session_id": "live-2", "stored_session_id": "stored-2"})
                    app._on_response(Response(steer, result, error))
                    # The new session's catalog is asked for too; nothing goes to either session for the steer.
                    self.assertEqual(
                        [method for method, _params in client.calls[steer:]], ["session.close", "commands.catalog"]
                    )
                    self.assertEqual(app.composer.text, "keep this")
                    self.assertFalse(app.queued)
                    self.assertIn(app_module.STEER_LEFT_NOTICE, notices(app, NOTICE_WARN))
                    self.assertFalse(any("queued by Hermes" in text for text in notices(app)))

    def test_a_steer_unanswered_after_its_session_was_left_comes_back_and_nothing_is_sent(self) -> None:
        for leave in ("new", "switch"):
            with self.subTest(leave=leave):
                now = [100.0]
                app, client = make_app(busy=True, clock=lambda: now[0])
                type_text(app, "keep this")
                app._on_input(CTRL_ENTER)
                steer = len(client.calls)
                if leave == "new":
                    app._on_new_session({"session_id": "live-2", "stored_session_id": "stored-2"})
                else:
                    app._on_session_resumed("stored-2", {"session_id": "live-2", "stored_session_id": "stored-2"})
                now[0] += 3600
                app._expire_calls()
                self.assertEqual(
                    [method for method, _params in client.calls[steer:]], ["session.close", "commands.catalog"]
                )
                self.assertEqual(app.composer.text, "keep this")
                self.assertFalse(app.queued)
                said = app_module.STEER_LEFT_UNANSWERED_NOTICE.format(seconds=app_module.CALL_ANSWER_SECONDS)
                self.assertIn(said, notices(app, NOTICE_WARN))  # said in the session now live

    def test_a_steer_that_comes_back_never_lands_in_an_answer_or_over_a_draft(self) -> None:
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        type_text(app, "keep this")
        app._on_input(CTRL_ENTER)
        steer = len(client.calls)
        app._on_new_session({"session_id": "live-2", "stored_session_id": "stored-2"})
        type_text(app, "a draft")
        app._on_server_request(ServerRequest("srq-1", "sudo", {"command": "apt install x"}))
        app._on_response(Response(steer, {"status": "rejected", "text": "keep this"}, None))
        self.assertEqual(app.composer.text, "")  # the composer holds the answer to the question now
        now[0] += SLOT_ARM_SECONDS
        app._on_input(Key(ENTER))
        self.assertEqual(client.answers, [("srq-1", {"result": {"value": ""}})])
        self.assertEqual(app.composer.text, "a draft\nkeep this")

        app, client = make_app(busy=True)  # no question open: the text goes after the draft being typed
        type_text(app, "keep this")
        app._on_input(CTRL_ENTER)
        steer = len(client.calls)
        app._on_new_session({"session_id": "live-2", "stored_session_id": "stored-2"})
        type_text(app, "a draft")
        app._on_response(Response(steer, None, {"code": 4010, "message": "agent does not support steer"}))
        self.assertEqual(app.composer.text, "a draft\nkeep this")

    def test_the_send_now_key_is_ctrl_enter_only_once_the_terminal_has_sent_a_report(self) -> None:
        app, _client = make_app(busy=True)
        app.terminal.keyboard_protocol = True  # type: ignore[attr-defined]  # asked, as on an allowlisted terminal
        self.assertIsNone(send_now_row(app))  # nothing queued: no row, and the info line names no steer key
        self.assertNotIn("steer", info_row_of(drawn(app)))
        for event in app.decoder.feed(b"x\r"):  # a terminal that ignored the request: Ctrl+Enter comes as Enter
            app._on_input(event)
        self.assertEqual(send_now_row(app), "  ctrl+j to send now · ↑ to edit")
        for event in app.decoder.feed(b"\x1b[108;5u"):  # Ctrl+L, as kitty reports it (Esc would interrupt the turn)
            app._on_input(event)
        self.assertEqual(send_now_row(app), "  ctrl+enter to send now · ↑ to edit")

    def test_a_kitty_flags_answer_names_ctrl_enter_before_any_key_and_types_nothing(self) -> None:
        for answer, key in ((b"\x1b[?1u", "ctrl+enter"), (b"\x1b[?0u", "ctrl+j")):
            with self.subTest(answer=answer):
                app, _client = make_app(busy=True)
                type_text(app, "ab")
                app._take_input(answer)  # the start-up query's answer, or one that came after its wait
                type_text(app, "c")
                self.assertEqual(app.composer.text, "abc")
                app._on_input(Key(ENTER))  # queued behind the turn
                self.assertEqual(send_now_row(app), f"  {key} to send now · ↑ to edit")

    def test_the_send_now_key_steers_with_the_oldest_queued_prompt_and_takes_it_off_the_queue(self) -> None:
        for data in (CTRL_ENTER_BYTES, b"\n", b"\x1b[27;5;13~"):  # Ctrl+Enter reported, Ctrl+J, modifyOtherKeys
            with self.subTest(data=data):
                app, client = make_app(busy=True)
                queue(app, "first queued", "second queued")
                app._take_input(data)
                self.assertEqual(client.calls, [("session.steer", {"session_id": SID, "text": "first queued"})])
                self.assertEqual([line.text for line in app.queued], ["second queued"])
                self.assertIn("↪ steer · first queued", lines_text(app.transcript.live_lines(80, DEFAULT_THEME)))
                answer(app, client, {"status": "queued", "text": "first queued"})
                self.assertEqual(steers(app), ["↪ steer queued by Hermes · first queued"])

    def test_a_refused_send_now_goes_back_to_the_head_of_the_queue_as_it_was(self) -> None:
        for refusal in ({"error": {"code": 4010, "message": "agent does not support steer"}},
                        {"result": {"status": "rejected", "text": "first queued"}}):
            with self.subTest(refusal=refusal):
                app, client = make_app(busy=True)
                first = QueuedLine("first queued", "first ⟨chip⟩", chips=(("⟨chip⟩", "queued"),))
                app.queued.extend([first, QueuedLine("second queued")])
                app._on_input(CTRL_ENTER)
                app.plan_mode = True  # a mode switched on since: the line is not wrapped again
                answer(app, client, refusal.get("result"), refusal.get("error"))
                self.assertIs(app.queued[0], first)
                self.assertEqual([line.text for line in app.queued], ["first queued", "second queued"])
                self.assertIn("back at the head of the queue", steers(app)[0])

    def test_the_send_now_key_leaves_a_shell_line_or_a_command_s_prompt_queued_and_shows_no_row(self) -> None:
        for head in (QueuedLine("ls", "!ls", shell=True), QueuedLine("skill prompt", typed="/myskill go")):
            with self.subTest(head=head):
                app, client = make_app(busy=True)
                app.queued.extend([head, QueuedLine("later")])
                self.assertIsNone(send_now_row(app))
                app._on_input(CTRL_ENTER)
                self.assertEqual((client.calls, len(app.queued)), ([], 2))

    def test_a_plan_mode_prompt_keeps_its_place_and_shows_no_row(self) -> None:
        # A plan request must not land in a turn that can edit: it waits, as a `!` line and a skill's prompt do.
        app, client = make_app(busy=True)
        app.queued.extend([QueuedLine(PLAN_PROMPT, typed="fix the flaky test"), QueuedLine("later")])
        self.assertIsNone(send_now_row(app))
        for event in (CTRL_ENTER, STEER_FALLBACK_KEY):
            app._on_input(event)
        self.assertEqual((client.calls, len(app.queued)), ([], 2))

    def test_the_send_now_key_needs_an_empty_composer_and_no_rewind_or_tell_row(self) -> None:
        app, client = make_app(busy=True)
        queue(app, "queued meanwhile")
        type_text(app, "x")
        app._on_input(STEER_FALLBACK_KEY)  # text typed: Ctrl+J adds a line, and nothing leaves the queue
        self.assertEqual((app.composer.text, client.calls, len(app.queued)), ("x\n", [], 1))
        for picked in ("rewind", "tell_draft"):
            with self.subTest(picked=picked):
                app, client = make_app(busy=True)
                queue(app, "queued meanwhile")
                # A picked rewind, or an open tell row, takes what is sent.
                if picked == "rewind":
                    app.rewind = mock.sentinel.picked
                else:
                    app.tell_draft = mock.sentinel.picked
                app._on_input(STEER_FALLBACK_KEY)
                self.assertEqual((client.calls, len(app.queued)), ([], 1))

    def sent_now_then_stopped(self, *events: str, before_stop=None) -> tuple[App, list[str]]:
        """Queue two prompts, send the first now and have Hermes take it, then `events`, then stop the turn: the
        composer's text afterwards and the warnings said."""
        app, client = make_app(busy=True)
        queue(app, "first queued", "second queued")
        app._on_input(CTRL_ENTER)
        answer(app, client, {"status": "queued", "text": "first queued"})
        for kind in events:
            app._on_event(Event(kind, SID, {"tool_id": "t1", "name": "terminal", "text": "x"}))
        if before_stop is not None:
            before_stop(app)
        app.interrupting = True
        app._on_event(Event("message.complete", app.sid, {"text": "stopped"}))  # the turn of the session live now
        return app, notices(app, NOTICE_WARN)

    def test_a_sent_now_steer_the_turn_had_not_read_comes_back_when_the_turn_is_stopped(self) -> None:
        said = app_module.SENT_NOW_DROPPED_NOTICE.format(count=1, s="")
        # No tool finished after Hermes took it, a model delta included: that request was under way before the steer.
        for events in ((), ("message.delta",), ("tool.start", "reasoning.delta")):
            with self.subTest(events=events):
                app, warned = self.sent_now_then_stopped(*events)
                self.assertEqual(app.composer.text, "first queued\nsecond queued")  # queued again, ahead of the rest
                self.assertIn(said, warned)

    def test_a_sent_now_steer_counts_as_read_at_the_first_tool_that_finishes(self) -> None:
        # Hermes joins it to the batch's results when the batch is finalized, an interrupted batch included.
        app, warned = self.sent_now_then_stopped("tool.complete")
        self.assertEqual(app.composer.text, "second queued")
        self.assertNotIn(app_module.SENT_NOW_DROPPED_NOTICE.format(count=1, s=""), warned)

    def test_a_steer_handed_on_or_left_behind_is_never_queued_again(self) -> None:
        def ended_on_its_own(app: App) -> None:  # Hermes passes a held steer on as the next turn, which starts now
            app._on_event(Event("message.complete", SID, {"text": "done"}))
            app.turn_pending = True

        def switched(app: App) -> None:
            app._on_new_session({"session_id": "live-2", "stored_session_id": "stored-2"})
            app.turn_pending = True

        for name, step in (("ended", ended_on_its_own), ("switched", switched)):
            with self.subTest(name):
                app, warned = self.sent_now_then_stopped(before_stop=step)
                self.assertNotIn("first queued", app.composer.text)
                self.assertNotIn(app_module.SENT_NOW_DROPPED_NOTICE.format(count=1, s=""), warned)

    def test_a_send_now_refused_after_its_turn_ended_and_the_next_began_goes_back_to_the_composer(self) -> None:
        app, client = make_app(busy=True)
        queue(app, "first queued", "second queued")
        app._on_input(CTRL_ENTER)
        steer = len(client.calls)
        app._on_event(Event("message.complete", SID, {"text": "done"}))  # the turn ends; "second queued" starts
        app._on_response(Response(steer, {"status": "rejected", "text": "first queued"}, None))
        self.assertTrue(app._busy())
        self.assertEqual(app.composer.text, "first queued")  # not queued behind a prompt sent after it
        self.assertEqual(list(app.queued), [])
        self.assertIn(app_module.SENT_NOW_LATE_NOTICE, notices(app, NOTICE_WARN))
        self.assertIn("back in the composer", steers(app)[0])

    def test_a_late_refusal_while_the_next_prompt_waits_on_the_default_check_drops_nothing(self) -> None:
        # review-2372 HIGH: with a default route read, the drained prompt waits in `starting` for `config.get mtime`,
        # `_busy()` is False then, and a refusal answered in that window must not take its place.
        app, client = make_app(busy=True)
        app.default_route = ("some/model", "provider")
        queue(app, "A first", "B second")
        app._on_input(CTRL_ENTER)
        steer = len(client.calls)
        app._on_event(Event("message.complete", SID, {"text": "done"}))  # the turn ends; B waits on the check
        self.assertEqual(client.calls[-1], ("config.get", {"key": "mtime"}))
        self.assertIsNotNone(app.starting)
        app._on_response(Response(steer, {"status": "rejected", "text": "A first"}, None))
        self.assertEqual(app.composer.text, "A first")  # back to the person, never ahead of B
        self.assertEqual(list(app.queued), [])
        self.assertIn(app_module.SENT_NOW_LATE_NOTICE, notices(app, NOTICE_WARN))
        app._on_response(Response(len(client.calls), {"mtime": app.config_mtime}, None))
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": "B second", "queued": True}))

    def test_a_prompt_held_for_the_default_check_is_never_replaced(self) -> None:
        app, client = make_app()
        app.default_route = ("some/model", "provider")
        sent: list[str] = []
        app._start_turn("B second", lambda: sent.append("B"))
        held = app.starting
        later = QueuedLine("C third")
        app._start_turn("C third", lambda: sent.append("C"), later)
        app._start_turn("D typed", lambda: sent.append("D"))
        self.assertIs(app.starting, held)
        self.assertIs(app.queued[0], later)  # a queue's line goes back to its head
        self.assertEqual(app.composer.text, "D typed")  # one with no line goes back to the draft
        queue(app, "E fifth")
        app._drain_queue()  # the queue waits behind the held prompt
        self.assertIs(app.starting, held)
        self.assertEqual([line.text for line in app.queued], ["C third", "E fifth"])
        self.assertEqual(sent, [])

    def test_no_send_now_row_between_turns_or_while_the_queue_is_held(self) -> None:
        app, _client = make_app()
        queue(app, "later")
        self.assertIsNone(send_now_row(app))
        app.turn_pending, app.queue_held = True, True
        self.assertIsNotNone(send_now_row(app))  # held or not, a running turn takes it now
        app.turn_pending = False
        self.assertIsNone(send_now_row(app))
        self.assertIn("held · ↑ edit", "\n".join(drawn(app)))

    def test_ctrl_j_with_text_adds_a_line_during_a_turn_and_ctrl_enter_steers_it(self) -> None:
        for data in (b"\n", b"\x1b[106;5u", b"\x1b[27;5;106~"):  # a line feed, or Ctrl+J as either report sends it
            with self.subTest(data=data):
                app, client = make_app(busy=True)
                queue(app, "queued meanwhile")
                type_text(app, "use the other file")
                app._take_input(data)
                self.assertEqual((app.composer.text, client.calls), ("use the other file\n", []))  # a line, as idle
        app, client = make_app(busy=True)
        queue(app, "queued meanwhile")
        type_text(app, "use the other file")
        app._take_input(CTRL_ENTER_BYTES)  # Ctrl+Enter with text steers the text; the queue stays as it was
        self.assertEqual(client.calls, [("session.steer", {"session_id": SID, "text": "use the other file"})])
        self.assertEqual([line.text for line in app.queued], ["queued meanwhile"])
        app, client = make_app()
        type_text(app, "first")
        app._take_input(b"\n")
        self.assertEqual((app.composer.text, client.calls), ("first\n", []))

    def test_ctrl_j_steers_nothing_while_a_question_or_a_picked_agent_steer_takes_what_is_sent(self) -> None:
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        app._on_server_request(ServerRequest("srq-1", "vault.code", {}))
        now[0] += SLOT_ARM_SECONDS
        type_text(app, "12")
        app._on_input(STEER_FALLBACK_KEY)
        self.assertEqual((client.answers, client.calls), ([], []))

        app, client = make_app(busy=True)
        app.agent_steer = "sub-1"  # `s` in the agent list picked a subagent: Enter sends the line to it
        type_text(app, "first")
        app._on_input(STEER_FALLBACK_KEY)
        self.assertEqual((app.composer.text, client.calls), ("first\n", []))  # a line, as between turns

    def test_only_ctrl_enter_and_the_steer_command_can_steer(self) -> None:
        # Steer text is what the person typed and sent, so `session.steer` has one sender with two callers.
        tree = ast.parse(Path(app_module.__file__).read_text(encoding="utf-8"))
        callers: set[str] = set()
        senders: set[str] = set()
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef):
                continue
            for node in ast.walk(function):
                if isinstance(node, ast.Constant) and node.value == "session.steer":
                    senders.add(function.name)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_steer":
                    callers.add(function.name)
        self.assertEqual(senders, {"_steer"})
        self.assertEqual(callers, {"_steer_or_submit", "_steer_command", "_send_queued_now"})


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class DocumentedSteerTests(unittest.TestCase):
    """What INSTALLATION and the OMH TUI boundary page say a steer does, held to the code."""

    ROOT = Path(__file__).resolve().parents[1]

    def prose(self, name: str) -> str:
        return " ".join((self.ROOT / name).read_text(encoding="utf-8").split())

    def test_the_label_and_the_fallback_are_the_ones_the_code_uses(self) -> None:
        installation = self.prose("docs/INSTALLATION.md")
        label = steers_of([SteerBlock("x", STEER_QUEUED)])[0].removesuffix(" · x")
        self.assertIn(f"`{label}`", installation)
        self.assertIn("joins the OMH TUI's own queue (`⧗`) and goes when the turn ends, whatever "
                      "`display.busy_input_mode` says, so it never interrupts the turn", installation)
        self.assertNotIn("`↪ steered:`", installation)
        unanswered = app_module.STEER_UNANSWERED_OUTCOME.format(seconds=app_module.CALL_ANSWER_SECONDS)
        self.assertIn(f"`⧗ {unanswered} · <text>`", installation)  # given back, never sent again
        self.assertIn("A steer Hermes does not take waits in the TUI's own queue for the running turn to end, whatever "
                      "the busy mode, so it never interrupts that turn.", self.prose("docs/OMH-TUI-BOUNDARY.md"))
        seconds = f"{app_module.CALL_ANSWER_SECONDS:g}"
        self.assertIn(f"A steer Hermes does not answer within its answer budget ({seconds} s, longer when held behind a "
                      "/compress) goes back to the composer and is never re-sent.",
                      self.prose("docs/OMH-TUI-BOUNDARY.md"))


class DocumentedApprovalsToggleTests(unittest.TestCase):
    """CONTEXT.md's OMH TUI entry names the one switch the TUI sets in Hermes, and how far it reaches."""

    def test_the_glossary_entry_names_the_per_session_toggle(self) -> None:
        text = " ".join((Path(__file__).resolve().parents[1] / "CONTEXT.md").read_text(encoding="utf-8").split())
        entry = text[text.index("**OMH TUI**:") : text.index("**Hermes gateway protocol**:")]
        self.assertIn(
            "Shift+Tab may turn on Hermes' per-session yolo, so Hermes stops asking for approvals in that one session "
            "(a `config.set` naming the session, never `approvals.mode`), and the TUI sends that session an explicit "
            "off before it leaves it.",
            entry,
        )

    def test_the_boundary_and_the_changelog_say_when_accept_shows_and_when_the_off_goes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        agents = " ".join((root / "docs/OMH-TUI-BOUNDARY.md").read_text(encoding="utf-8").split())
        changelog = " ".join((root / "CHANGELOG.md").read_text(encoding="utf-8").split())
        self.assertIn("Leaving a session it turned yolo on for, or whose yolo call is still unanswered", agents)
        self.assertIn(
            "is shown on the composer once Hermes confirms it, or when Hermes confirms neither it nor the switch back "
            "off, and the TUI sends that session an explicit off before it leaves it,",
            changelog,
        )
        self.assertNotIn("switched off again before the TUI leaves", changelog)  # it sends the off; it does not wait
        self.assertIn("(a steer Hermes does not take waits in the queue for the turn to end)", changelog)


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class SteerReplayTests(AppTestCase):
    def steer_run(self, status: str, *segments: str) -> object:
        answers = (*startup_answers(UNREAD_DEFAULT), ("session.steer", {"result": {"status": status, "text": "second prompt"}}))
        return self.prepare(Scenario("session", spans("session", "startup", "create", *segments), answers=answers))

    def test_ctrl_enter_as_a_key_report_steers_and_the_notice_lands(self) -> None:
        run = self.steer_run("queued", "plain_turn")
        terminal = run.terminal
        terminal.script(
            # One read: Ctrl+Enter lands while the first prompt's turn is pending.
            Step(b"first prompt\rsecond prompt" + CTRL_ENTER_BYTES, when=terminal.idle, label="idle"),
            Step(b"\x04", when=lambda: "↪ steer queued by Hermes · second prompt" in terminal.history() and terminal.idle(), label="steered"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        (steer,) = run.calls("session.steer")
        self.assertEqual(steer["params"], {"session_id": LIVE_ID, "text": "second prompt"})
        self.assertEqual(len(run.calls("prompt.submit")), 1)

    def test_ctrl_j_from_a_terminal_that_sends_it_as_a_line_feed_steers(self) -> None:
        run = self.steer_run("queued", "plain_turn")
        terminal = run.terminal
        terminal.script(
            # One read: a second prompt queued while the first prompt's turn is pending, then Ctrl+J, a bare line
            # feed in raw mode, on the empty composer: it sends the queued prompt now.
            Step(b"first prompt\rsecond prompt\r\n", when=terminal.idle, label="idle"),
            Step(b"\x04", when=lambda: "↪ steer queued by Hermes · second prompt" in terminal.history() and terminal.idle(), label="steered"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        (steer,) = run.calls("session.steer")
        self.assertEqual(steer["params"], {"session_id": LIVE_ID, "text": "second prompt"})
        self.assertEqual(len(run.calls("prompt.submit")), 1)

    def test_a_rejected_steer_is_submitted_once_the_turn_is_over(self) -> None:
        run = self.steer_run("rejected", "plain_turn", "smart_approved_turn")
        terminal = run.terminal
        terminal.script(
            Step(b"first prompt\rsecond prompt" + CTRL_ENTER_BYTES, when=terminal.idle, label="idle"),
            Step(b"\x04", when=lambda: "cleanly)." in terminal.history() and terminal.idle(), label="turn 2"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        first, second = run.calls("prompt.submit")
        self.assertEqual(first["params"], {"session_id": LIVE_ID, "text": "first prompt"})
        self.assertEqual(second["params"], {"session_id": LIVE_ID, "text": "second prompt"})
        self.assertNotIn("queued by Hermes", terminal.history())


def session_info(app: App, **payload: object) -> None:
    app._on_event(Event("session.info", app.sid, dict(payload)))


def in_accept(**options: object) -> tuple[App, RecordingClient]:
    """An app Hermes confirmed accept for, with the calls so far forgotten."""
    app, client = make_app(**options)
    app._on_input(SHIFT_TAB)
    answer(app, client, YOLO_IS_ON)
    client.calls.clear()
    return app, client


class ModeCycleTests(unittest.TestCase):
    def test_shift_tab_cycles_normal_accept_plan_normal(self) -> None:
        app, client = make_app()
        app._on_input(SHIFT_TAB)
        self.assertEqual(client.calls, [YOLO_ON_CALL])
        self.assertEqual(app.mode, MODE_NORMAL)  # accept is shown once Hermes confirms it, not before
        answer(app, client, YOLO_IS_ON)
        self.assertEqual(app.mode, MODE_ACCEPT)

        app._on_input(SHIFT_TAB)
        self.assertEqual(client.calls, [YOLO_ON_CALL, YOLO_OFF_CALL])
        self.assertEqual(app.mode, MODE_ACCEPT)  # plan waits for the off to be confirmed
        answer(app, client, YOLO_IS_OFF)
        self.assertEqual(app.mode, MODE_PLAN)

        app._on_input(SHIFT_TAB)
        self.assertEqual(app.mode, MODE_NORMAL)
        self.assertEqual(client.calls, [YOLO_ON_CALL, YOLO_OFF_CALL])  # plan is the TUI's flag: no call
        self.assertEqual(notices(app), [])

    def test_the_screen_states_the_approval_mode_once_in_the_info_lines_words_whatever_the_hud_read(self) -> None:
        # The audit's case (D4): the mode row said approvals off while the status line, reading Hermes' saved state
        # through the HUD, still said `yolo mode: off`. The info line carries both now, and only the mode's words.
        from test_tui_panels import hud_payload

        from omh.tui.panels import HudSnapshot

        app, client = make_app()
        app.stored_id = "stored"
        for enabled in (False, True):
            with self.subTest(hud_says_yolo=enabled):
                payload = hud_payload()
                payload["yolo"] = {"status": "observed", "enabled": enabled}
                app.hud = HudSnapshot("stored", payload, 100.0)
                if app.mode != MODE_ACCEPT:
                    app._on_input(SHIFT_TAB)
                    answer(app, client, YOLO_IS_ON)
                screen = drawn(app)
                self.assertFalse([row for row in screen if "yolo" in row], screen)
                self.assertEqual([without_badge(row) for row in screen if "accept all on" in row], [info_row_of(screen)])

    def test_a_yolo_answer_that_is_not_this_session_only_is_a_failure(self) -> None:
        refusals = {
            "scope global": {"key": "yolo", "value": "1", "scope": "global"},
            "no scope": {"key": "yolo", "value": "1"},
            "value off": {"key": "yolo", "value": "0", "scope": "session"},
            "value missing": {"key": "yolo", "scope": "session"},
            "value true": {"key": "yolo", "value": True, "scope": "session"},
        }
        for name, result in refusals.items():
            with self.subTest(name):
                app, client = make_app()
                app._on_input(SHIFT_TAB)
                answer(app, client, result)
                self.assertEqual(app.mode, MODE_NORMAL)
                self.assertEqual(client.calls, [YOLO_ON_CALL, YOLO_OFF_CALL])  # the explicit off
                (notice,) = notices(app, NOTICE_ERROR)
                self.assertIn("Accept all stays off", notice)
                answer(app, client, YOLO_IS_OFF)
                self.assertEqual(len(notices(app)), 1)
                self.assertEqual(len(client.calls), 2)

    def test_a_failed_on_returns_to_normal_even_after_a_session_info_said_on(self) -> None:
        # Whatever Hermes reported meanwhile, a call that did not confirm "this session only" shows nothing on.
        app, client = make_app()
        app._on_input(SHIFT_TAB)
        session_info(app, yolo=True)
        answer(app, client, {"key": "yolo", "value": "1", "scope": "global"})
        self.assertEqual(app.mode, MODE_NORMAL)
        self.assertEqual(client.calls, [YOLO_ON_CALL, YOLO_OFF_CALL])

    def test_the_answer_cannot_show_the_switch_stayed_on_one_session_so_the_call_must(self) -> None:
        # Hermes 6c61c3e27d's sessionless branch sets HERMES_YOLO_MODE for the gateway process and answers
        # exactly what the session branch answers, so the answer check passes it; the guards are on the call.
        sessionless_answer = {"key": "yolo", "value": "1", "scope": "session"}
        self.assertEqual(modes_module.yolo_answer_problem(sessionless_answer, True), "")
        self.assertIn("session id", contract.call_problem("config.set", {"key": "yolo", "value": "on"}))
        app, client = make_app()
        app._on_input(SHIFT_TAB)
        self.assertEqual(client.calls, [("config.set", {"key": "yolo", "session_id": SID, "value": "on"})])

    def test_an_error_answer_to_accept_is_a_failure_too(self) -> None:
        # 5001 can follow a switch that was already flipped, so the explicit off still goes out.
        app, client = make_app()
        app._on_input(SHIFT_TAB)
        answer(app, client, error={"code": 5001, "message": "boom"})
        self.assertEqual(app.mode, MODE_NORMAL)
        self.assertEqual(client.calls, [YOLO_ON_CALL, YOLO_OFF_CALL])
        (notice,) = notices(app, NOTICE_ERROR)
        self.assertIn("5001: boom", notice)

    def test_a_switch_back_hermes_does_not_confirm_is_said_and_not_retried(self) -> None:
        app, client = make_app()
        app._on_input(SHIFT_TAB)
        answer(app, client, {"key": "yolo", "value": "1", "scope": "global"})
        answer(app, client, {"key": "yolo", "value": "1", "scope": "session"})
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(len(notices(app, NOTICE_ERROR)), 2)
        self.assertIn("did not confirm the switch back", notices(app)[-1])

    def test_a_switch_back_that_fails_shows_accept_again_the_safe_way(self) -> None:
        failures = {
            "an error": {"error": {"code": 5001, "message": "boom"}},
            "an unconfirmed answer": {"result": {"key": "yolo", "value": "1", "scope": "session"}},
        }
        for name, frame in failures.items():
            with self.subTest(name):
                app, client = make_app()
                app._on_input(SHIFT_TAB)
                answer(app, client, {"key": "yolo", "value": "1", "scope": "global"})
                self.assertEqual(app.mode, MODE_NORMAL)
                app._on_response(Response(2, frame.get("result"), frame.get("error")))
                self.assertEqual(app.mode, MODE_ACCEPT)
                notice = notices(app, NOTICE_ERROR)[-1]
                self.assertIn("did not confirm the switch back", notice)
                self.assertNotIn("config.set failed", " ".join(notices(app)))  # handled, not the generic error
                sent = len(client.calls)
                app._on_input(SHIFT_TAB)  # and the key asks for the off again
                self.assertEqual(client.calls[sent:], [YOLO_OFF_CALL])

    def test_a_switch_back_answered_after_the_session_was_left_changes_nothing_shown(self) -> None:
        app, client = make_app()
        app._on_input(SHIFT_TAB)
        answer(app, client, {"key": "yolo", "value": "1", "scope": "global"})
        app._adopt_session({"session_id": "live-2", "info": {}})
        said = notices(app)
        app._on_response(Response(2, None, {"code": 5001, "message": "boom"}))
        self.assertEqual(app.mode, MODE_NORMAL)
        self.assertEqual(notices(app), said)  # and says nothing: "accept all is shown again" is not true here

    def test_shift_tab_waits_for_the_switch_back_as_for_any_yolo_call(self) -> None:
        app, client = make_app()
        app._on_input(SHIFT_TAB)
        answer(app, client, {"key": "yolo", "value": "1", "scope": "global"})
        app._on_input(SHIFT_TAB)
        self.assertEqual(client.calls, [YOLO_ON_CALL, YOLO_OFF_CALL])
        answer(app, client, YOLO_IS_OFF)
        app._on_input(SHIFT_TAB)
        self.assertEqual(client.calls, [YOLO_ON_CALL, YOLO_OFF_CALL, YOLO_ON_CALL])

    def test_without_a_session_nothing_is_sent(self) -> None:
        app, client = make_app()
        app.sid = ""
        app._on_input(SHIFT_TAB)
        self.assertEqual(client.calls, [])
        self.assertEqual(app.mode, MODE_NORMAL)
        self.assertEqual(len(notices(app, NOTICE_WARN)), 1)
        self.assertFalse(app.mode_request_open)

    def test_an_off_hermes_does_not_confirm_leaves_accept_shown(self) -> None:
        for name, result, error in (
            ("still on", YOLO_IS_ON, None),
            ("scope global", {"key": "yolo", "value": "0", "scope": "global"}, None),
            ("error", None, {"code": 4001, "message": "session not found"}),
        ):
            with self.subTest(name):
                app, client = in_accept()
                app._on_input(SHIFT_TAB)
                answer(app, client, result, error)
                self.assertEqual(app.mode, MODE_ACCEPT)
                self.assertEqual(client.calls, [YOLO_OFF_CALL])  # no loop of further calls
                (notice,) = notices(app, NOTICE_ERROR)
                self.assertIn("may still be on", notice)

    def test_an_off_while_hermes_still_reports_approvals_off_keeps_accept_beside_plan(self) -> None:
        # approvals.mode off, or --yolo: the session switch is off and Hermes still asks nothing.
        app, client = in_accept()
        app._on_input(SHIFT_TAB)
        session_info(app, yolo=True)
        answer(app, client, YOLO_IS_OFF)
        self.assertEqual(app.mode, MODE_ACCEPT_PLAN)  # the press reached plan, and approvals off stays shown
        (notice,) = notices(app, NOTICE_WARN)
        self.assertIn("Hermes itself has approvals off", notice)
        # From here the approvals are Hermes' own: the key moves plan alone, sends nothing, says nothing more.
        for expected in (MODE_ACCEPT, MODE_ACCEPT_PLAN, MODE_ACCEPT):
            app._on_input(SHIFT_TAB)
            self.assertEqual(app.mode, expected)
        self.assertEqual(client.calls, [YOLO_OFF_CALL])
        self.assertEqual(len(notices(app)), 1)

    def test_the_session_info_that_precedes_a_confirmed_off_does_not_cost_plan(self) -> None:
        app, client = in_accept()
        app._on_input(SHIFT_TAB)
        session_info(app, yolo=False)  # Hermes emits it before it answers the call
        self.assertEqual(app.mode, MODE_NORMAL)
        answer(app, client, YOLO_IS_OFF)
        self.assertEqual(app.mode, MODE_PLAN)
        self.assertEqual(notices(app), [])

    def test_a_second_shift_tab_waits_for_the_first_answer(self) -> None:
        app, client = make_app()
        app._on_input(SHIFT_TAB)
        app._on_input(SHIFT_TAB)
        self.assertEqual(client.calls, [YOLO_ON_CALL])
        answer(app, client, YOLO_IS_ON)
        app._on_input(SHIFT_TAB)
        self.assertEqual(client.calls, [YOLO_ON_CALL, YOLO_OFF_CALL])

    def test_shift_tab_does_nothing_while_something_else_has_the_keys(self) -> None:
        def approval(app: App) -> None:
            app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))

        def question(app: App) -> None:
            app._on_server_request(ServerRequest("srq-1", "sudo", {"command": "apt install x"}))

        def menu(app: App) -> None:
            type_text(app, "/he")

        def picker(app: App) -> None:
            app.picker = SessionPicker([SessionRow("stored-1", "a title", "", 0.0, 1)], current="")

        def pager(app: App) -> None:
            app.pager = Pager("history", [])

        for opened in (approval, question, menu, picker, pager):
            with self.subTest(opened.__name__):
                now = [100.0]
                app, client = make_app(clock=lambda: now[0])
                opened(app)
                now[0] += SLOT_ARM_SECONDS
                app._on_input(SHIFT_TAB)
                self.assertEqual(client.calls, [])
                self.assertEqual(client.answers, [])
                self.assertEqual(app.mode, MODE_NORMAL)

    def test_only_shift_tab_itself_cycles_a_ctrl_or_alt_chord_on_it_does_nothing(self) -> None:
        # Kitty CSI u and xterm modifyOtherKeys forms of Ctrl+Shift+Tab, Alt+Shift+Tab and Ctrl+Alt+Shift+Tab.
        for chord in (b"\x1b[9;6u", b"\x1b[27;6;9~", b"\x1b[9;4u", b"\x1b[27;4;9~", b"\x1b[9;8u"):
            with self.subTest(chord=chord):
                app, client = make_app()
                (key,) = KeyDecoder().feed(chord)
                self.assertEqual((key.name, key.shift, key.ctrl or key.alt), (TAB, True, True))
                app._on_input(key)
                self.assertEqual(client.calls, [])
                self.assertEqual(app.mode, MODE_NORMAL)
        for plain in (SHIFT_TAB_BYTES, b"\x1b[9;2u", b"\x1b[27;2;9~"):
            with self.subTest(plain=plain):
                app, client = make_app()
                (key,) = KeyDecoder().feed(plain)
                app._on_input(key)
                self.assertEqual(client.calls, [YOLO_ON_CALL])

    def test_every_call_the_mode_and_effort_scenarios_send_passes_the_contract_check(self) -> None:
        # The recording client checks each call as GatewayClient does and raises; this one only records,
        # so a call the check would refuse reaches the assertion below instead of stopping the scenario.
        class Unchecked(RecordingClient):
            def request(self, method: str, params: dict) -> int:
                self.calls.append((method, dict(params)))
                return len(self.calls)

        def cycle(app: App, client: RecordingClient, now: list[float]) -> None:
            app._on_input(SHIFT_TAB)
            session_info(app, yolo=True)
            answer(app, client, YOLO_IS_ON)
            now[0] += 0.5
            session_info(app, yolo=False)  # held: within the settle window of the confirmed on
            app._on_input(SHIFT_TAB)
            session_info(app, yolo=False)
            answer(app, client, YOLO_IS_OFF)
            app._on_input(SHIFT_TAB)

        def refused_on(app: App, client: RecordingClient, now: list[float]) -> None:
            app._on_input(SHIFT_TAB)
            answer(app, client, {"key": "yolo", "value": "1", "scope": "global"})
            answer(app, client, {"key": "yolo", "value": "1", "scope": "session"})  # the switch back fails too
            app._on_input(SHIFT_TAB)
            answer(app, client, error={"code": 5001, "message": "boom"})

        def stuck_off(app: App, client: RecordingClient, now: list[float]) -> None:
            app._on_input(SHIFT_TAB)
            answer(app, client, YOLO_IS_ON)
            app._on_input(SHIFT_TAB)
            answer(app, client, error={"code": 4001, "message": "session not found"})
            app._on_input(SHIFT_TAB)
            session_info(app, yolo=True)
            answer(app, client, YOLO_IS_OFF)
            for _ in range(3):
                app._on_input(SHIFT_TAB)  # Hermes' own approvals from here: plan alone

        def hermes_own(app: App, client: RecordingClient, now: list[float]) -> None:
            session_info(app, yolo=True)
            for _ in range(3):
                app._on_input(SHIFT_TAB)
            session_info(app, yolo=False)
            app._on_input(SHIFT_TAB)
            app._on_input(SHIFT_TAB)

        def left_mid_call(app: App, client: RecordingClient, now: list[float]) -> None:
            app._on_input(SHIFT_TAB)
            app._on_input(CTRL_T)
            app._adopt_session({"session_id": "live-2", "info": {"yolo": False}})
            app._on_response(Response(1, YOLO_IS_ON, None))
            app._on_response(Response(2, effort_set("low"), None))
            app._on_input(SHIFT_TAB)
            app._on_input(CTRL_T)

        def effort(app: App, client: RecordingClient, now: list[float]) -> None:
            for _ in range(3):
                app._on_input(CTRL_T)
                answer(app, client, effort_set(client.calls[-1][1]["value"]))
            for level in ("ultra", "none", "minimal", "show", "high --global"):
                type_text(app, f"/effort {level}")
                app._on_input(Key(ENTER))

        sent: list[tuple[str, dict]] = []
        for scenario in (cycle, refused_on, stuck_off, hermes_own, left_mid_call, effort):
            with self.subTest(scenario=scenario.__name__):
                now = [100.0]
                client = Unchecked()
                app = App(ScriptedTerminal(24, 80), client, {}, poller=FakePoller(), clock=lambda: now[0])  # type: ignore[arg-type]
                app.sid = SID
                scenario(app, client, now)
                for method, params in client.calls:
                    self.assertEqual(contract.call_problem(method, params), "", (method, params))
                sent += client.calls
        configs = [params for method, params in sent if method == "config.set"]
        self.assertEqual(
            {(params["key"], params["value"]) for params in configs},
            {("yolo", "on"), ("yolo", "off"), ("reasoning", "low"), ("reasoning", "medium"), ("reasoning", "high"),
             ("reasoning", "ultra"), ("reasoning", "none"), ("reasoning", "minimal")},
        )
        self.assertEqual({params["session_id"] for params in configs}, {SID, "live-2"})


class ExitHintTests(unittest.TestCase):
    def test_a_first_ctrl_c_says_so_on_the_info_line_for_two_seconds_and_writes_nothing(self) -> None:
        from omh.tui.app import EXIT_CONFIRM_SECONDS, EXIT_HINT

        now = [100.0]
        app, _client = make_app(clock=lambda: now[0])
        resting = drawn(app)
        app._on_input(Key(CHAR, "c", ctrl=True))
        screen = drawn(app)
        self.assertIn(EXIT_HINT, info_row_of(screen))  # the info line, as the Esc-armed message is
        self.assertEqual(notices(app), [])  # nothing left in the transcript or the scrollback
        self.assertIsNone(app.exit_code)
        now[0] += EXIT_CONFIRM_SECONDS - 0.5
        self.assertAlmostEqual(app._read_timeout(), 0.5)  # the loop wakes when the window ends, not a second later
        now[0] += 0.6
        app.dirty = False
        app._expire_exit()
        self.assertEqual((app.dirty, app.exit_armed_at), (True, None))  # so that wake repaints the row without it
        self.assertEqual(drawn(app), resting)
        app._on_input(Key(CHAR, "c", ctrl=True))  # the window passed: this press arms again
        self.assertIsNone(app.exit_code)
        now[0] += EXIT_CONFIRM_SECONDS / 2
        app._on_input(Key(CHAR, "c", ctrl=True))
        self.assertEqual(app.exit_code, 0)


class HermesOwnApprovalsTests(unittest.TestCase):
    """Approvals Hermes turned off on its own: accept stays shown, and Shift+Tab moves plan alone."""

    def test_shift_tab_turns_plan_on_and_off_and_sends_nothing(self) -> None:
        app, client = make_app()
        session_info(app, yolo=True)  # approvals.mode off, --yolo, or a /yolo typed to Hermes
        self.assertEqual(app.mode, MODE_ACCEPT)
        for expected in (MODE_ACCEPT_PLAN, MODE_ACCEPT, MODE_ACCEPT_PLAN):
            app._on_input(SHIFT_TAB)
            self.assertEqual(app.mode, expected)
        self.assertEqual(client.calls, [])
        (notice,) = notices(app)
        self.assertEqual(notice, modes_module.HERMES_APPROVALS_NOTICE)
        type_text(app, "fix the flaky test")
        app._on_input(Key(ENTER))  # plan is on, so the prompt goes as /plan
        self.assertEqual(client.calls, [("slash.exec", {"command": "plan fix the flaky test", "session_id": SID})])

    def test_the_notice_is_said_once_per_session(self) -> None:
        app, _client = make_app()
        session_info(app, yolo=True)
        for _ in range(4):
            app._on_input(SHIFT_TAB)
        app._adopt_session({"session_id": "live-2", "info": {"yolo": True}})
        app._on_input(SHIFT_TAB)
        app._on_input(SHIFT_TAB)
        self.assertEqual(notices(app), [modes_module.HERMES_APPROVALS_NOTICE] * 2)

    def test_approvals_turned_back_on_and_off_again_without_the_tui_are_hermes_own(self) -> None:
        # The TUI's on, then a /yolo typed to Hermes turns approvals on, and another turns them off again.
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        app._on_input(SHIFT_TAB)
        answer(app, client, YOLO_IS_ON)
        now[0] += 10
        session_info(app, yolo=False)
        session_info(app, yolo=True)
        app._on_input(SHIFT_TAB)
        self.assertEqual((app.mode, client.calls), (MODE_ACCEPT_PLAN, [YOLO_ON_CALL]))

    def test_once_hermes_turns_them_back_on_the_cycle_is_the_tuis_again(self) -> None:
        app, client = make_app()
        session_info(app, yolo=True)
        app._on_input(SHIFT_TAB)
        session_info(app, yolo=False)  # approvals.mode set back, or /yolo again
        self.assertEqual(app.mode, MODE_PLAN)
        app._on_input(SHIFT_TAB)
        self.assertEqual((app.mode, client.calls), (MODE_NORMAL, []))
        app._on_input(SHIFT_TAB)
        self.assertEqual(client.calls, [YOLO_ON_CALL])

    def test_approvals_the_tui_turned_off_are_still_the_tuis_to_turn_back_on(self) -> None:
        # Hermes emits session.info with yolo true before it answers the call that turned it on.
        app, client = make_app()
        app._on_input(SHIFT_TAB)
        session_info(app, yolo=True)
        answer(app, client, YOLO_IS_ON)
        session_info(app, yolo=True)
        app._on_input(SHIFT_TAB)
        self.assertEqual(client.calls, [YOLO_ON_CALL, YOLO_OFF_CALL])
        self.assertEqual(notices(app), [])

    def test_both_labels_show_on_the_info_line_at_every_height_and_the_box_stays_as_it_is(self) -> None:
        app, _client = make_app()
        session_info(app, yolo=True)
        app._on_input(SHIFT_TAB)
        screen = drawn(app)
        # Hermes has approvals off on its own: Shift+Tab only turns plan back off, and the line says so.
        self.assertTrue(info_row_of(screen).startswith(INFO_INSET + "⏵⏵ accept all on · ⏸ plan mode on (⇧⇥ plan off)"),
                        screen)
        top, bottom = rule_edges(80)  # the composer's two rules are the same row, above and under it
        self.assertEqual(screen.count(top), 2)  # no mode recolours or redraws the composer's rules
        short, _client = make_app(rows=9)
        session_info(short, yolo=True)
        short._on_input(SHIFT_TAB)
        self.assertTrue(info_row_of(drawn(short)).startswith(INFO_INSET + "⏵⏵ accept all on · ⏸ plan mode on"))


class StaleSessionInfoTests(unittest.TestCase):
    """A session.info Hermes built before a confirmed on, written after its answer, cannot show normal by itself."""

    def confirmed_on(self) -> tuple[App, RecordingClient, list[float]]:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        app._on_input(SHIFT_TAB)
        session_info(app, yolo=True)  # the one Hermes emits inside the call, before it answers
        answer(app, client, YOLO_IS_ON)
        return app, client, now

    def test_one_saying_on_within_two_seconds_waits_for_the_next_and_asks_nothing(self) -> None:
        self.assertEqual(modes_module.YOLO_SETTLE_SECONDS, 2.0)
        app, client, now = self.confirmed_on()
        now[0] += 1.9
        session_info(app, yolo=False)
        self.assertEqual(app.mode, MODE_ACCEPT)
        self.assertEqual(client.calls, [YOLO_ON_CALL])  # Hermes has no per-session read to ask
        session_info(app, yolo=False)  # the next one decides
        self.assertEqual(app.mode, MODE_NORMAL)
        app._on_input(SHIFT_TAB)  # and nothing is left on: the next press turns approvals off again
        self.assertEqual(client.calls[-1], YOLO_ON_CALL)

    def test_a_snapshot_agreeing_with_the_switch_does_not_use_the_hold_up(self) -> None:
        app, _client, now = self.confirmed_on()
        now[0] += 0.5
        session_info(app, yolo=True)
        session_info(app, yolo=False)
        self.assertEqual(app.mode, MODE_ACCEPT)

    def test_from_two_seconds_on_a_session_info_decides_at_once(self) -> None:
        app, _client, now = self.confirmed_on()
        now[0] += 2.0
        session_info(app, yolo=False)
        self.assertEqual(app.mode, MODE_NORMAL)

    def test_after_a_confirmed_off_approvals_off_is_shown_at_once(self) -> None:
        app, client, now = self.confirmed_on()
        now[0] += 3
        app._on_input(SHIFT_TAB)
        answer(app, client, YOLO_IS_OFF)
        self.assertEqual(app.mode, MODE_PLAN)
        now[0] += 0.5
        session_info(app, yolo=True)  # in doubt the composer shows accept
        self.assertEqual(app.mode, MODE_ACCEPT_PLAN)

    def test_the_off_a_press_sends_is_not_held_against_the_on_before_it(self) -> None:
        app, client, now = self.confirmed_on()
        now[0] += 0.5
        app._on_input(SHIFT_TAB)
        session_info(app, yolo=False)  # the off's own session.info, before its answer
        self.assertEqual(app.mode, MODE_NORMAL)
        answer(app, client, YOLO_IS_OFF)
        self.assertEqual(app.mode, MODE_PLAN)


class ModeFollowsHermesTests(unittest.TestCase):
    def test_session_info_decides_whether_accept_is_shown(self) -> None:
        app, _client = make_app()
        session_info(app, yolo=True)
        self.assertEqual(app.mode, MODE_ACCEPT)
        session_info(app, yolo=False)
        self.assertEqual(app.mode, MODE_NORMAL)
        show_mode(app, MODE_PLAN)
        session_info(app, yolo=False)
        self.assertEqual(app.mode, MODE_PLAN)
        session_info(app, yolo=True)  # approvals off is shown, and the TUI's own plan flag stays on beside it
        self.assertEqual(app.mode, MODE_ACCEPT_PLAN)
        session_info(app, yolo=False)
        self.assertEqual(app.mode, MODE_PLAN)

    def test_a_session_info_without_a_yolo_word_changes_nothing(self) -> None:
        for payload in ({}, {"yolo": None}, {"yolo": "1"}, {"yolo": 1}):
            for mode in (MODE_NORMAL, MODE_ACCEPT, MODE_PLAN):
                with self.subTest(payload=payload, mode=mode):
                    app, _client = make_app()
                    show_mode(app, mode)
                    session_info(app, **payload)
                    self.assertEqual(app.mode, mode)

    def test_another_sessions_info_is_not_this_sessions_mode(self) -> None:
        app, _client = make_app()
        app._on_event(Event("session.info", "someone-else", {"yolo": True}))
        self.assertEqual(app.mode, MODE_NORMAL)

    def test_a_new_session_starts_from_what_its_own_info_says(self) -> None:
        for info, expected in (({}, MODE_NORMAL), ({"yolo": False}, MODE_NORMAL), ({"yolo": True}, MODE_ACCEPT)):
            with self.subTest(info=info):
                app, _client = in_accept()
                app._adopt_session({"session_id": "live-2", "info": info})
                self.assertEqual(app.mode, expected)

    def test_plan_stays_on_across_a_new_session(self) -> None:
        app, _client = make_app()
        show_mode(app, MODE_PLAN)
        app._adopt_session({"session_id": "live-2", "info": {}})
        self.assertEqual(app.mode, MODE_PLAN)

    def test_an_answer_for_a_session_already_left_changes_nothing(self) -> None:
        app, client = make_app()
        app._on_input(SHIFT_TAB)
        app._adopt_session({"session_id": "live-2", "info": {}})
        answer(app, client, YOLO_IS_ON)
        self.assertEqual(app.mode, MODE_NORMAL)
        self.assertEqual(notices(app), [])
        app._on_input(SHIFT_TAB)  # and the new session's key is not stuck behind the old call
        self.assertEqual(client.calls[-1], ("config.set", {"key": "yolo", "session_id": "live-2", "value": "on"}))


class LeavingTurnsYoloOffTests(unittest.TestCase):
    """Hermes keeps a messaging-gateway session's yolo through session.close, so the TUI turns off what it set."""

    NEW = {"session_id": "live-2", "info": {}}

    def methods(self, client: RecordingClient, start: int = 0) -> list[str]:
        return [method for method, _params in client.calls[start:]]

    def answer_call(self, app: App, client: RecordingClient, call: tuple[str, dict], **frame: object) -> None:
        app._on_response(Response(client.calls.index(call) + 1, frame.get("result"), frame.get("error")))

    def test_a_new_session_sends_off_for_the_old_one_before_closing_it(self) -> None:
        app, client = in_accept()
        app._new_session("")
        answer(app, client, self.NEW)
        self.assertEqual(
            client.calls[1:],
            [YOLO_OFF_CALL, ("session.close", {"session_id": SID}), ("commands.catalog", {"session_id": "live-2"})],
        )
        self.answer_call(app, client, YOLO_OFF_CALL, result=YOLO_IS_OFF)
        self.assertEqual(notices(app, NOTICE_ERROR), [])
        self.assertEqual((app.sid, app.mode), ("live-2", MODE_NORMAL))

    def test_a_switch_does_too_and_an_off_hermes_does_not_confirm_is_a_notice_in_the_new_transcript(self) -> None:
        for frame in ({"error": {"code": 5001, "message": "boom"}}, {"result": YOLO_IS_ON}, {"result": {"value": "0"}}):
            with self.subTest(frame=frame):
                app, client = in_accept()
                app._switch_session("stored-2")
                answer(app, client, {**self.NEW, "stored_session_id": "stored-2", "messages": []})
                self.assertEqual(self.methods(client, 1), ["config.set", "session.close", "commands.catalog"])
                self.assertEqual(client.calls[1], YOLO_OFF_CALL)
                self.answer_call(app, client, YOLO_OFF_CALL, **frame)
                (notice,) = notices(app, NOTICE_ERROR)
                self.assertIn("the session you left", notice)
                self.assertEqual(app.sid, "live-2")  # the switch was never held up

    def test_a_yolo_call_still_out_gets_an_off_after_it(self) -> None:
        for on in (True, False):
            with self.subTest(on=on):
                app, client = in_accept() if not on else make_app()
                app._on_input(SHIFT_TAB)  # on from normal, off from accept; no answer yet
                app._enter_session(self.NEW)
                self.assertEqual(client.calls[-2:], [YOLO_OFF_CALL, ("session.close", {"session_id": SID})])

    def test_a_switch_back_still_out_counts_as_possibly_on_and_its_answer_lands_nowhere(self) -> None:
        unconfirmed = {"key": "yolo", "value": "1", "scope": "session"}
        for frame in ({"error": {"code": 5001, "message": "boom"}}, {"result": unconfirmed}, {"result": YOLO_IS_OFF}):
            with self.subTest(frame=frame):
                app, client = make_app()
                app._on_input(SHIFT_TAB)
                answer(app, client, {"key": "yolo", "value": "1", "scope": "global"})  # refused: the switch-back goes out
                app._enter_session(self.NEW)
                self.assertEqual(client.calls[2:], [YOLO_OFF_CALL, ("session.close", {"session_id": SID})])
                app._on_response(Response(2, frame.get("result"), frame.get("error")))  # the switch-back's answer
                self.assertEqual(notices(app), [])
                self.assertEqual((app.sid, app.mode), ("live-2", MODE_NORMAL))

    def test_nothing_is_sent_for_yolo_the_tui_did_not_set(self) -> None:
        for hermes_own in (False, True):
            with self.subTest(hermes_own=hermes_own):
                app, client = make_app()
                if hermes_own:
                    session_info(app, yolo=True)  # approvals off for Hermes' own reasons
                app._enter_session(self.NEW)
                self.assertEqual(self.methods(client), ["session.close"])

    def test_quit_sends_off_before_the_close_and_the_exit_does_not_send_it_again(self) -> None:
        app, client = in_accept()
        app._quit("")
        app._shutdown()
        self.assertEqual(client.calls, [YOLO_OFF_CALL, ("session.close", {"session_id": SID})])

    def test_any_other_exit_sends_off_for_the_open_session_and_waits_for_no_answer(self) -> None:
        app, client = in_accept()
        app.exit_code = 0  # Ctrl+D, Ctrl+C twice, SIGTERM: the loop ends without /quit
        app._shutdown()
        self.assertEqual(client.calls, [YOLO_OFF_CALL])

    def test_an_exit_with_the_gateway_gone_still_ends(self) -> None:
        app, client = in_accept()
        app.exit_code = 1

        def gone(method: str, params: dict) -> int:
            raise GatewayUnavailable("the gateway stopped reading its input")

        client.request = gone  # type: ignore[method-assign]
        app._shutdown()
        self.assertEqual(app.exit_code, 1)


class LeftSessionStateTests(unittest.TestCase):
    """What the session being left still has on its way, or kept, after `/new` or a switch."""

    NEW = {"session_id": "live-2", "stored_session_id": "stored-2", "info": {"model": "m2", "cwd": "/p"}}
    SHOT = {"attached": True, "path": "/h/images/shot.png", "name": "shot.png", "width": 4, "height": 3}

    def left_with_call(self, start: object) -> tuple[App, RecordingClient, int]:
        """`start(app)` sends a call in the first session; `/new` opens another before the call's answer."""
        app, client = make_app()
        start(app)
        pending = len(client.calls)
        app._new_session("")
        answer(app, client, self.NEW)
        self.assertEqual(app.sid, "live-2")
        return app, client, pending

    def test_a_new_session_after_a_resumed_launch_no_longer_says_resumed(self) -> None:
        app, client = make_app()
        app.stored_id = "stored-old"
        app.banner_record = {"cwd": "~/p", "resumed": "stored-old"}
        app._new_session("")
        answer(app, client, self.NEW)
        self.assertEqual(app.banner_record, {"cwd": "/p", "resumed": ""})
        app._redraw("")
        self.assertEqual(app.banner_facts, {"cwd": "/p", "resumed": ""})

    def test_an_image_attached_in_the_session_left_is_no_chip_here_and_says_so(self) -> None:
        for start, result in (
            (lambda app: app._image("shot.png what is this?"), {**self.SHOT, "remainder": "what is this?"}),
            (lambda app: app._paste(""), self.SHOT),
            (lambda app: app._on_input(Paste("/h/shot.png")), {**self.SHOT, "matched": True, "is_image": True}),
        ):
            with self.subTest(result=result):
                app, client, pending = self.left_with_call(start)
                app._on_response(Response(pending, result, None))
                self.assertEqual(app.composer.images, {})
                self.assertIn(("image.detach", {"session_id": SID, "path": "/h/images/shot.png"}), client.calls)
                self.assertEqual(notices(app, NOTICE_WARN)[-1], ATTACH_LEFT_NOTICE.format(name="shot.png"))
                # The question typed after the path is the person's own words: it comes back to the composer.
                self.assertEqual(app.composer.text, result.get("remainder", ""))

    def test_a_dropped_path_that_is_no_image_still_types_its_text_after_a_switch(self) -> None:
        app, client, pending = self.left_with_call(lambda app: app._on_input(Paste("/h/notes.txt")))
        app._on_response(Response(pending, {"matched": True, "is_image": False, "text": "[file: notes.txt]"}, None))
        self.assertEqual((app.composer.text, app.composer.images), ("[file: notes.txt]", {}))

    def test_in_the_same_session_the_image_is_a_token(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            path = Path(home, "shot.png")
            path.write_bytes(b"\x89PNG\r\n\x1a\n")
            app, client = make_app()
            app._image("shot.png")
            answer(app, client, {**self.SHOT, "path": str(path)})
        ((label, image),) = app.composer.images.values()
        self.assertEqual((label, image.name, image.data), ("[Image #1]", "shot.png", b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(client.calls[-1], ("image.detach", {"session_id": SID, "path": str(path)}))
        self.assertEqual(notices(app), [])


class CopyTests(unittest.TestCase):
    def test_a_reply_with_a_lone_surrogate_is_copied_as_the_screen_draws_it(self) -> None:
        # JSON can carry an escaped lone surrogate; the terminal write draws it as "?", and so does the copy.
        reply = "caf\udce9 au lait"
        app, _client = make_app()
        app.transcript.blocks.append(AssistantBlock(reply, done=True))
        type_text(app, "/copy")
        app._on_input(Key(ENTER))
        frames = [text for text in app.terminal.writes if text.startswith("\x1b]52;")]  # type: ignore[attr-defined]
        drawn = reply.encode("utf-8", "replace")  # what Terminal.write sends for the reply
        self.assertEqual(drawn, b"caf? au lait")
        self.assertEqual(frames, [OSC52_COPY.format(base64.b64encode(drawn).decode("ascii"))])
        self.assertIsNone(app.exit_code)


class LiveTailTickTests(unittest.TestCase):
    def test_a_spinner_tick_with_nothing_new_renders_no_transcript_row_again(self) -> None:
        now = [100.0]
        app, _client = make_app(busy=True, clock=lambda: now[0])
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("message.delta", SID, {"text": "a paragraph that is still streaming " * 12}))
        first = drawn(app)
        now[0] += 0.15  # the next spinner frame
        fail = AssertionError("the live tail was rendered again")
        with patch("omh.tui.transcript.render_lines", side_effect=fail), patch("omh.tui.transcript.block_rows", side_effect=fail):
            ticked = drawn(app)
        self.assertNotEqual(ticked, first)  # the spinner moved
        self.assertEqual([row for row in ticked if "streaming" in row], [row for row in first if "streaming" in row])


class StartupWaitsOnlyForTheSessionTests(unittest.TestCase):
    """The first frame needs the session alone: the busy mode and the catalog are answered in the loop."""

    def test_only_the_session_call_is_awaited(self) -> None:
        class Blocking(RecordingClient):
            def __init__(self) -> None:
                super().__init__()
                self.awaited: list[str] = []

            def call(self, method: str, params: dict, timeout: float = 30.0) -> dict:
                self.awaited.append(method)
                return {"session_id": SID, "stored_session_id": "stored-1", "info": {"model": "m"}}

        client = Blocking()
        app = App(ScriptedTerminal(), client, {}, poller=FakePoller())  # type: ignore[arg-type]
        app.startup()
        self.assertEqual(client.awaited, ["session.create"])
        self.assertEqual(
            [method for method, _params in client.calls],
            ["config.get", "commands.catalog", "session.list", "config.get", "model.options"],  # the default's two last
        )
        self.assertEqual(app.busy_mode, "queue")  # Hermes' own default, until config.get answers
        type_text(app, "/")
        self.assertTrue(app._menu_rows())  # no catalog yet: the TUI's own commands still complete
        app._on_response(Response(1, {"config": {"display": {"busy_input_mode": "interrupt"}}}, None))
        self.assertEqual(app.busy_mode, "interrupt")


class RedrawTailTests(unittest.TestCase):
    def test_a_full_redraw_prints_only_the_last_rows_under_a_row_counting_the_rest(self) -> None:
        app, _client = make_app(rows=24, cols=80)
        for number in range(40):
            app.transcript.add_notice(f"notice {number}")
        drawn(app)
        with patch("omh.tui.app.REDRAW_TAIL_ROWS", 10):
            app._full_redraw()
        drawn(app)
        shown = "\n".join(app.terminal.screen.history())  # type: ignore[attr-defined]
        self.assertIn("⋯ 35 earlier messages · /history shows all", shown)
        self.assertNotIn("notice 34\n", shown)
        self.assertIn("notice 39", shown)

    def test_installation_names_the_tail_the_code_keeps(self) -> None:
        from pathlib import Path

        from omh.tui.app import REDRAW_TAIL_ROWS

        prose = " ".join((Path(__file__).resolve().parents[1] / "docs/INSTALLATION.md").read_text(encoding="utf-8").split())
        self.assertIn(f"prints the session's last {REDRAW_TAIL_ROWS:,} rows again", prose)

    def test_installation_names_the_block_cap_the_code_keeps(self) -> None:
        from pathlib import Path

        from omh.tui.transcript import BLOCK_CAP

        prose = " ".join((Path(__file__).resolve().parents[1] / "docs/INSTALLATION.md").read_text(encoding="utf-8").split())
        self.assertIn(f"holds a session's last {BLOCK_CAP:,} messages", prose)

    def test_history_opens_with_a_row_counting_the_messages_the_cap_dropped(self) -> None:
        app, _client = make_app(rows=24, cols=80)
        with patch("omh.tui.transcript.BLOCK_CAP", 10):
            for number in range(25):
                app.transcript.add_notice(f"notice {number}")
                drawn(app)  # printed, so the cap may drop it
        app._history("")
        shown = [line.rstrip() for line in drawn(app)]
        self.assertEqual(shown[:3], ["⋯ 15 earlier messages no longer held", "", "· notice 15"])
        self.assertEqual(shown[20:23], ["· notice 24", "", ""])  # the row, a blank, then the 10 notices held, spaced
        self.assertIn("history · 1-10/10 messages", shown[-1])

    def test_a_drop_while_history_is_open_leaves_its_count_as_it_opened(self) -> None:
        app, _client = make_app(rows=24, cols=80)
        with patch("omh.tui.transcript.BLOCK_CAP", 10):
            for number in range(25):
                app.transcript.add_notice(f"notice {number}")
                drawn(app)
            app._history("")
            for number in range(25, 30):  # five more printed under the pager: the cap drops five more
                app.transcript.add_notice(f"notice {number}")
                app.transcript.take_stable_lines(80, DEFAULT_THEME)
            self.assertEqual(app.transcript.dropped, 20)
            shown = [line.rstrip() for line in drawn(app)]
        self.assertEqual(shown[:3], ["⋯ 15 earlier messages no longer held", "", "· notice 15"])

    def test_history_renders_its_first_block_once_for_the_check_and_the_first_page(self) -> None:
        app, _client = make_app(rows=24, cols=80)
        for number in range(3):
            app.transcript.add_notice(f"notice {number}")
        first = app.transcript.blocks[0]
        real = app_module.block_rows
        rendered: list[object] = []

        def counting(block: object, *args: object, **kwargs: object) -> list:
            rendered.append(block)
            return real(block, *args, **kwargs)

        with patch("omh.tui.app.block_rows", counting):
            app._history("")
            drawn(app)
        self.assertEqual(sum(block is first for block in rendered), 1)

    def test_history_with_no_row_to_show_says_so_instead_of_opening(self) -> None:
        app, _client = make_app(rows=24, cols=80)
        app.transcript.blocks.append(AssistantBlock("\n", done=True))  # a reply that was only a line break
        app._history("")
        self.assertIsNone(app.pager)
        self.assertEqual(app.transcript.blocks[-1].text, "Nothing in this session's transcript yet.")

    def test_a_resumed_sessions_history_is_kept_to_the_tail_too(self) -> None:
        app, _client = make_app(rows=24, cols=80)
        messages = [{"role": "user", "text": f"question {number}"} for number in range(40)]
        with patch("omh.tui.app.REDRAW_TAIL_ROWS", 6):
            app._draw_history(messages)
        taken = [line for line in app.transcript.take_stable_lines(80, DEFAULT_THEME) if line]
        self.assertEqual(taken[0][0].text, "⋯ 37 earlier messages · /history shows all")
        self.assertEqual([line_text(line) for line in taken[1:]], ["  ❯ question 37", "  ❯ question 38", "  ❯ question 39"])  # each prompt on its rail


class CallExpiryTests(unittest.TestCase):
    """A call the gateway never answers is forgotten after a while, in the app and in the client, without running its handlers."""

    def test_an_unanswered_call_is_forgotten_with_a_notice_and_a_late_answer_changes_nothing(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        seen: list[object] = []
        app._request("session.list", {"limit": 5}, seen.append, lambda error: seen.append(error) or True)
        now[0] += app_module.CALL_ANSWER_SECONDS - 0.5
        app._expire_calls()
        self.assertEqual((len(app.pending), client.forgotten), (1, []))
        now[0] += 0.5
        app._expire_calls()
        self.assertEqual((app.pending, client.forgotten), ({}, [1]))
        self.assertEqual(notices(app, NOTICE_WARN), ["Hermes has not answered session.list in 120 s; the OMH TUI stopped waiting for it."])
        answer(app, client, {"sessions": []})
        self.assertEqual(seen, [])  # neither handler ran: no answer is not a refusal

    def test_calls_nobody_waits_on_are_forgotten_without_a_word_a_tail_after_its_own_window(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        app._request("complete.path", {"word": "./s", "session_id": SID}, lambda result: None, lambda error: True)
        app._request("config.get", {"key": "full"}, lambda result: None, lambda error: True)
        app._request("subagent.tail", {"session_id": SID, "subagent_id": "a1"}, lambda result: None)
        now[0] += app_module.TAIL_ANSWER_SECONDS
        app._expire_calls()
        self.assertEqual(sorted(call.method for call in app.pending.values()), ["complete.path", "config.get"])
        now[0] += app_module.CALL_ANSWER_SECONDS
        app._expire_calls()
        self.assertEqual((app.pending, sorted(client.forgotten)), ({}, [1, 2, 3]))
        self.assertEqual(notices(app), [])

    def test_the_loop_expires_calls_on_every_step(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        app._request("session.list", {"limit": 5}, lambda result: None)
        now[0] += app_module.CALL_ANSWER_SECONDS
        app.terminal.deadline = time.monotonic() + 10.0  # type: ignore[attr-defined]  # an empty read, not an EOF
        app._step()
        self.assertEqual((app.pending, client.forgotten), ({}, [1]))


class LazyHistoryTests(unittest.TestCase):
    def test_history_renders_only_the_blocks_its_pages_reach_with_their_details(self) -> None:
        from omh.tui import transcript as transcript_module

        app, _client = make_app(rows=24, cols=80)
        for number in range(500):
            app.transcript.add_notice(f"notice {number}")
        drawn(app)
        rendered: list[object] = []

        def counting(block: object, *args: object, **kwargs: object) -> object:
            rendered.append(kwargs.get("expanded"))
            return transcript_module.block_rows(block, *args, **kwargs)  # type: ignore[arg-type]

        with patch("omh.tui.app.block_rows", side_effect=counting):
            app._history("")
            shown = [line.rstrip() for line in drawn(app)]
        self.assertEqual(shown[0], "· notice 0")
        self.assertIn("history · 1-12/500 messages", shown[-1])
        self.assertLess(len(rendered), 30)  # the first page and the last, not 500 blocks
        self.assertEqual(set(rendered), {True})  # thinking text, result summaries and whole diffs


class ResumingTheLiveSessionTests(unittest.TestCase):
    """Hermes 6c61c3e27d resolves a title to the session already live and answers with its id (`_resume_reuse_live`)."""

    APPROVAL = ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"})

    def resume(self, app: App, client: RecordingClient, session_id: str) -> list[str]:
        """`/sessions <title>` answered with `session_id`; the methods it sent after the resume."""
        app.stored_id = "stored-1"
        app._switch_session("my title")
        sent = len(client.calls)
        answer(app, client, {"session_id": session_id, "stored_session_id": "stored-1", "messages": [], "info": {}})
        return [method for method, _params in client.calls[sent:]]

    def test_it_is_no_switch_and_shift_tab_still_turns_off_the_yolo_the_tui_set(self) -> None:
        app, client = in_accept()
        self.assertEqual(self.resume(app, client, SID), [])
        self.assertEqual(notices(app)[-1], "Already in session stored-1.")
        self.assertEqual((app.sid, app.mode, app.yolo_by_tui), (SID, MODE_ACCEPT, True))
        app._on_input(SHIFT_TAB)
        self.assertEqual(client.calls[-1], YOLO_OFF_CALL)

    def test_quit_then_sends_the_off_before_the_close(self) -> None:
        app, client = in_accept()
        self.resume(app, client, SID)
        sent = len(client.calls)
        app._quit("")
        self.assertEqual(client.calls[sent:], [YOLO_OFF_CALL, ("session.close", {"session_id": SID})])

    def test_a_yolo_call_still_out_still_holds_shift_tab(self) -> None:
        app, client = make_app()
        app._on_input(SHIFT_TAB)  # on, unanswered
        self.resume(app, client, SID)
        self.assertTrue(app.mode_request_open)
        sent = len(client.calls)
        app._on_input(SHIFT_TAB)
        self.assertEqual(client.calls[sent:], [])

    def test_an_open_approval_in_that_session_is_not_declined(self) -> None:
        app, client = make_app()
        app._on_server_request(self.APPROVAL)
        self.resume(app, client, SID)
        self.assertEqual(client.answers, [])
        self.assertIsNotNone(app.slot)
        self.assertEqual(app.slot.request_id, "srq-1")  # type: ignore[union-attr]

    def test_a_real_switch_still_turns_off_declines_and_closes(self) -> None:
        app, client = in_accept()
        app._on_server_request(self.APPROVAL)
        self.assertEqual(self.resume(app, client, "live-2"), ["config.set", "session.close", "commands.catalog"])
        self.assertEqual(client.calls[-3:-1], [YOLO_OFF_CALL, ("session.close", {"session_id": SID})])
        self.assertEqual(client.answers, [("srq-1", {"result": {"choice": "deny"}})])
        self.assertEqual((app.sid, app.mode, app.slot), ("live-2", MODE_NORMAL, None))
        self.assertNotIn("Already in session stored-1.", notices(app))


class PlanModeTests(unittest.TestCase):
    def plan_app(self, busy: bool = False) -> tuple[App, RecordingClient]:
        app, client = make_app(busy=busy)
        show_mode(app, MODE_PLAN)
        return app, client

    def test_a_prompt_goes_as_slash_plan_through_the_slash_command_path(self) -> None:
        app, client = self.plan_app()
        type_text(app, "fix the flaky test")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("slash.exec", {"command": "plan fix the flaky test", "session_id": SID})])
        answer(app, client, error={"code": contract.NOT_MINE, "message": "pending-input command"})
        self.assertEqual(
            client.calls[1], ("command.dispatch", {"name": "plan", "arg": "fix the flaky test", "session_id": SID})
        )
        answer(app, client, {"type": "send", "message": PLAN_PROMPT})
        self.assertEqual(client.calls[2], ("prompt.submit", {"session_id": SID, "text": PLAN_PROMPT}))
        shown = [block.text for block in app.transcript.blocks if isinstance(block, UserBlock)]
        self.assertEqual(shown, ["/plan fix the flaky test"])

    def test_a_typed_slash_plan_in_normal_mode_keeps_showing_what_hermes_built(self) -> None:
        app, client = make_app()
        type_text(app, "/plan fix the flaky test")
        app._on_input(Key(ENTER))
        answer(app, client, error={"code": contract.NOT_MINE, "message": "pending-input command"})
        answer(app, client, {"type": "send", "message": PLAN_PROMPT})
        shown = [block.text for block in app.transcript.blocks if isinstance(block, UserBlock)]
        self.assertEqual(shown, [PLAN_PROMPT])

    def test_normal_and_accept_send_the_prompt_as_typed(self) -> None:
        for mode in (MODE_NORMAL, MODE_ACCEPT):
            with self.subTest(mode=mode):
                app, client = make_app()
                show_mode(app, mode)
                type_text(app, "fix the flaky test")
                app._on_input(Key(ENTER))
                self.assertEqual(client.calls, [("prompt.submit", {"session_id": SID, "text": "fix the flaky test"})])

    def test_a_slash_command_typed_in_plan_mode_is_not_wrapped(self) -> None:
        app, client = self.plan_app()
        type_text(app, "/queue")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [])
        self.assertEqual(notices(app), ["Nothing is queued."])

    def test_an_answer_to_a_question_is_never_wrapped(self) -> None:
        requests = (
            ("clarify", {"questions": [{"qid": "q0", "question": "Which?", "choices": []}]},
             {"result": {"answers": {"q0": "the blue one"}}}),
            ("sudo", {"command": "apt install x"}, {"result": {"value": "the blue one"}}),
            ("secret", {"env_var": "TOKEN_X"}, {"result": {"value": "the blue one"}}),
            ("vault.code", {}, {"result": {"value": "the blue one"}}),
        )
        for method, params, expected in requests:
            with self.subTest(method=method):
                now = [100.0]
                app, client = make_app(clock=lambda: now[0])
                show_mode(app, MODE_PLAN)
                app._on_server_request(ServerRequest("srq-1", method, params))
                now[0] += SLOT_ARM_SECONDS
                type_text(app, "the blue one")
                app._on_input(Key(ENTER))
                self.assertEqual(client.answers, [("srq-1", expected)])
                self.assertEqual(client.calls, [])

    def test_a_steer_in_plan_mode_is_sent_as_typed_and_its_fallback_is_a_plan_prompt(self) -> None:
        app, client = self.plan_app(busy=True)
        type_text(app, "also the docs")
        app._on_input(CTRL_ENTER)
        self.assertEqual(client.calls, [("session.steer", {"session_id": SID, "text": "also the docs"})])
        app.turn_pending = False
        answer(app, client, {"status": "rejected", "text": "also the docs"})
        self.assertEqual(client.calls[1], ("slash.exec", {"command": "plan also the docs", "session_id": SID}))

    def test_slash_plan_is_a_command_hermes_runs_not_one_the_tui_turns_away(self) -> None:
        for invocation in (parse_slash("/plan fix it"), plan_invocation("fix it")):
            with self.subTest(invocation=invocation):
                self.assertIsNotNone(invocation)
                self.assertIsNone(invocation.command)  # unrouted: it goes to slash.exec
                self.assertEqual(invocation.text, "plan fix it")
        self.assertEqual(plan_invocation("  two\nlines \n").shown, "/plan two\nlines")


def effort_call(level: str, sid: str = SID) -> tuple[str, dict]:
    return ("config.set", {"key": "reasoning", "session_id": sid, "value": level})


def effort_set(level: str) -> dict:
    """Hermes 6c61c3e27d's answer to a session effort (`_set_reasoning`): the word it took."""
    return {"key": "reasoning", "value": level}


class EffortTests(unittest.TestCase):
    def test_ctrl_t_steps_the_effort_and_shows_it_once_hermes_confirms(self) -> None:
        app, client = make_app()
        seen = []
        for _ in range(len(EFFORT_CYCLE) + 1):
            app._on_input(CTRL_T)
            asked = client.calls[-1][1]["value"]
            self.assertNotEqual(app.effort, asked)  # shown only once Hermes answers
            answer(app, client, effort_set(asked))
            self.assertEqual(app.effort, asked)
            seen.append(asked)
        self.assertEqual(seen, ["low", "medium", "high", "xhigh", "max", "low"])
        self.assertEqual(client.calls, [effort_call(level) for level in seen])
        self.assertEqual(notices(app), [])

    def test_a_level_outside_the_cycle_steps_to_low(self) -> None:
        for level in ("", "none", "minimal", "ultra", "something-new"):
            with self.subTest(level=level):
                app, client = make_app()
                app.effort = level
                app._on_input(CTRL_T)
                self.assertEqual(client.calls, [effort_call("low")])

    def test_presses_before_the_answer_step_on_from_what_was_asked(self) -> None:
        app, client = make_app()
        app.effort = "low"
        app._on_input(CTRL_T)
        app._on_input(CTRL_T)
        self.assertEqual(client.calls, [effort_call("medium"), effort_call("high")])
        app._on_response(Response(1, effort_set("medium"), None))
        self.assertEqual(app.effort, "medium")
        app._on_response(Response(2, effort_set("high"), None))
        self.assertEqual(app.effort, "high")
        app._on_input(CTRL_T)
        self.assertEqual(client.calls[-1], effort_call("xhigh"))

    def test_a_refused_effort_says_so_and_leaves_the_display(self) -> None:
        refusals = (
            ("an error", None, {"code": 4002, "message": "unknown reasoning value: low"}),
            ("another level", effort_set("medium"), None),
            ("no value", {"key": "reasoning"}, None),
        )
        for name, result, error in refusals:
            with self.subTest(name):
                app, client = make_app()
                app.effort = "high"
                app._on_input(CTRL_T)
                answer(app, client, result, error)
                self.assertEqual(app.effort, "high")
                (notice,) = notices(app, NOTICE_WARN)
                self.assertIn("did not set the reasoning effort to xhigh", notice)
                app._on_input(CTRL_T)  # and the next press asks for the same step again
                self.assertEqual(client.calls[-1], effort_call("xhigh"))

    def test_ctrl_t_does_nothing_while_a_question_is_open_or_without_a_session(self) -> None:
        for method, params in (("approval", {"command": "rm -rf ./x"}), ("sudo", {"command": "apt install x"})):
            with self.subTest(method=method):
                now = [100.0]
                app, client = make_app(clock=lambda: now[0])
                app._on_server_request(ServerRequest("srq-1", method, params))
                now[0] += SLOT_ARM_SECONDS
                app._on_input(CTRL_T)
                self.assertEqual((client.calls, client.answers), ([], []))
                self.assertEqual(app.composer.text, "")
        app, client = make_app()
        app.sid = ""
        app._on_input(CTRL_T)
        self.assertEqual(client.calls, [])
        self.assertEqual(len(notices(app, NOTICE_WARN)), 1)

    def test_session_info_is_where_the_shown_effort_comes_from(self) -> None:
        app, _client = make_app()
        session_info(app, reasoning_effort="high")
        self.assertEqual(app.effort, "high")
        session_info(app, reasoning_effort="none", yolo=False)
        self.assertEqual(app.effort, "none")
        for payload in ({}, {"reasoning_effort": None}, {"reasoning_effort": 3}):
            session_info(app, **payload)
            self.assertEqual(app.effort, "none")
        session_info(app, reasoning_effort="")  # Hermes' word for the provider's default
        self.assertEqual(app.effort, modes_module.EFFORT_DEFAULT)

    def started_with(self, config: dict) -> tuple[App, RecordingClient]:
        """A launched app whose `session.create` answered Hermes' lazy info (no effort), then `config.get` `config`."""

        class Lazy(RecordingClient):
            def call(self, method: str, params: dict, timeout: float = 30.0) -> dict:
                return {"session_id": SID, "stored_session_id": "stored-1", "info": {"model": "m", "lazy": True}}

        client = Lazy()
        app = App(ScriptedTerminal(), client, {}, poller=FakePoller())  # type: ignore[arg-type]
        app.startup()
        self.assertEqual(app.effort, "")
        app._on_response(Response(1, {"config": config}, None))  # the config.get the launch already asks
        return app, client

    def test_before_the_first_prompt_the_configured_effort_is_shown_and_ctrl_t_steps_from_it(self) -> None:
        # The re-review: no session.info names the effort before Hermes has built the session's agent.
        def hint(app: App) -> str:
            return line_text(app._info_line(100))

        app, client = self.started_with({"agent": {"reasoning_effort": "high"}})
        self.assertIn("effort high", hint(app))
        app._on_input(CTRL_T)
        self.assertEqual(client.calls[-1], effort_call("xhigh"))
        for config, shown in (({}, "default"), ({"agent": {"reasoning_effort": ""}}, "default"),
                              ({"agent": {"reasoning_effort": False}}, "none"), ({"agent": {"reasoning_effort": "HIGH "}}, "high"),
                              ({"agent": {"reasoning_effort": {"enabled": False}}}, "none"),
                              ({"agent": {"reasoning_effort": {"effort": "max"}}}, "max"),
                              ({"agent": {"reasoning_effort": "hgih"}}, "default")):  # Hermes falls back as for unset
            with self.subTest(config=config):
                app, _client = self.started_with(config)
                self.assertIn(f"effort {shown}", hint(app))

    def test_a_per_model_override_or_the_sessions_own_word_wins_over_the_global_setting(self) -> None:
        app, _client = self.started_with({"agent": {"reasoning_effort": "high", "reasoning_overrides": {"m": "low"}}})
        self.assertEqual(app.effort, "")  # which entry matches the model is Hermes' to decide: no level is claimed
        app, _client = self.started_with({"agent": {"reasoning_effort": "high"}})
        session_info(app, reasoning_effort="medium")
        self.assertEqual(app.effort, "medium")
        late, _client = make_app()
        session_info(late, reasoning_effort="low")
        late._take_settings({"config": {"agent": {"reasoning_effort": "high"}}})  # an answer after the session spoke
        self.assertEqual(late.effort, "low")

    def test_a_new_session_or_a_cold_switch_shows_the_configured_effort_again_and_ctrl_t_steps_from_it(self) -> None:
        # The round-4 verification: /new and a switch adopt the new session's lazy info, which names no effort, and
        # no config.get goes out for them; the level the config set is still the one the new session starts with.
        def hint(app: App) -> str:
            return line_text(app._info_line(100))

        lazy = {"session_id": "live-2", "stored_session_id": "stored-2", "info": {"model": "m", "lazy": True}}
        for leave in ("new", "switch"):
            with self.subTest(leave=leave):
                app, client = self.started_with({"agent": {"reasoning_effort": "high"}})
                app._on_input(CTRL_T)
                answer(app, client, effort_set("xhigh"))  # this session's own level, not the config's
                self.assertIn("effort xhigh", hint(app))
                sent = len(client.calls)
                if leave == "new":
                    app._on_new_session(lazy)
                else:
                    app._on_session_resumed("stored-2", {**lazy, "messages": []})
                self.assertIn("effort high", hint(app))
                self.assertNotIn("config.get", [method for method, _params in client.calls[sent:]])
                app._on_input(CTRL_T)
                self.assertEqual(client.calls[-1], effort_call("xhigh", sid="live-2"))

    def test_after_a_session_change_its_own_word_still_wins_and_overrides_still_claim_nothing(self) -> None:
        app, _client = self.started_with({"agent": {"reasoning_effort": "high"}})
        for said, shown in (("low", "low"), ("", modes_module.EFFORT_DEFAULT)):
            with self.subTest(said=said):
                app._on_session_resumed(
                    "stored-2", {"session_id": f"live-{said}", "stored_session_id": f"stored-{said}",
                                 "info": {"reasoning_effort": said}, "messages": []})
                self.assertEqual(app.effort, shown)
        app, _client = self.started_with({"agent": {"reasoning_effort": "high", "reasoning_overrides": {"m": "low"}}})
        app._on_new_session({"session_id": "live-2", "stored_session_id": "stored-2", "info": {"lazy": True}})
        self.assertEqual(app.effort, "")
        # A respawn adopts the resumed session, then asks config.get again: a level the config changed to replaces
        # the one carried over, which was the config's too.
        app, _client = self.started_with({"agent": {"reasoning_effort": "high"}})
        app._adopt_session({"session_id": "live-2", "stored_session_id": "stored-1", "info": {"lazy": True}})
        self.assertEqual(app.effort, "high")
        app._take_settings({"config": {"agent": {"reasoning_effort": "low"}}})
        self.assertEqual(app.effort, "low")

    def test_a_level_the_session_said_stays_over_a_later_config_read_even_when_it_matched_the_old_config(self) -> None:
        # The round-5 verification: told apart by value, a session's `high` equal to the config's `high` read as the
        # config's, and the next config read (a respawn's) replaced it.
        for respawned in (False, True):
            for said in ("session.info", "ctrl+t"):
                with self.subTest(respawned=respawned, said=said):
                    app, client = self.started_with({"agent": {"reasoning_effort": "high"}})
                    if respawned:  # the resumed session, adopted before the fresh config.get is answered
                        app._adopt_session({"session_id": SID, "stored_session_id": "stored-1", "info": {"lazy": True}})
                    if said == "session.info":
                        session_info(app, reasoning_effort="high")
                    else:  # a level the person set for this session and Hermes confirmed
                        app._set_effort("high")
                        answer(app, client, effort_set("high"))
                    app._take_settings({"config": {"agent": {"reasoning_effort": "low"}}})
                    self.assertEqual(app.effort, "high")
        # The other way round: a session adopted after the old one said its level starts from the config's, which the
        # fresh config read then replaces.
        app, _client = self.started_with({"agent": {"reasoning_effort": "high"}})
        session_info(app, reasoning_effort="max")
        app._adopt_session({"session_id": SID, "stored_session_id": "stored-1", "info": {"lazy": True}})
        self.assertEqual(app.effort, "high")
        app._take_settings({"config": {"agent": {"reasoning_effort": "low"}}})
        self.assertEqual(app.effort, "low")

    def test_the_hint_names_the_sessions_effort_from_the_start_and_ctrl_t_steps_from_it(self) -> None:
        # Hermes 6c61c3e27d sends the session's effort in the session.info that follows the agent's build, before
        # any turn: a configured level, or "" where none is configured and the route's own default applies.
        def hint(app: App) -> str:
            return line_text(app._info_line(100))

        app, client = make_app()
        self.assertTrue(hint(app).endswith("ctrl+t effort"))  # no word from Hermes yet (the lazy info carries none)
        self.assertNotIn("effort ", hint(app).replace("ctrl+t effort", ""))
        session_info(app, reasoning_effort="high")
        self.assertIn("effort high", hint(app))
        app._on_input(CTRL_T)
        self.assertEqual(client.calls[-1], effort_call("xhigh"))  # one step up from the level shown
        app, client = make_app()
        session_info(app, reasoning_effort="")
        self.assertIn("effort default", hint(app))  # never a level Hermes did not name
        app._on_input(CTRL_T)
        self.assertEqual(client.calls[-1], effort_call("low"))  # the default is no step of the cycle

    def test_a_new_session_shows_its_own_effort(self) -> None:
        app, client = make_app()
        app.effort = "high"
        app._on_input(CTRL_T)
        app._adopt_session({"session_id": "live-2", "info": {}})
        self.assertEqual(app.effort, "")
        answer(app, client, effort_set("xhigh"))  # the session left answers late
        self.assertEqual(app.effort, "")
        app._adopt_session({"session_id": "live-3", "info": {"reasoning_effort": "max"}})
        self.assertEqual(app.effort, "max")
        app._on_input(CTRL_T)
        self.assertEqual(client.calls[-1], effort_call("low", "live-3"))

    def test_the_effort_command_takes_any_hermes_level(self) -> None:
        for level in contract.REASONING_LEVELS:
            with self.subTest(level=level):
                app, client = make_app()
                type_text(app, f"/effort {level.upper()}")
                app._on_input(Key(ENTER))
                self.assertEqual(client.calls, [effort_call(level)])
                answer(app, client, effort_set(level))
                self.assertEqual(app.effort, level)

    def test_the_effort_command_sends_nothing_that_is_not_a_level(self) -> None:
        # show, hide, on, off, full and clamp are display settings under the same Hermes key.
        for word in ("show", "hide", "on", "off", "full", "clamp", "hgih", "high --global"):
            with self.subTest(word=word):
                app, client = make_app()
                type_text(app, f"/effort {word}")
                app._on_input(Key(ENTER))
                self.assertEqual(client.calls, [])
                (notice,) = notices(app, NOTICE_WARN)
                self.assertIn("none, minimal, low, medium, high, xhigh, max, ultra", notice)

    def test_the_effort_command_alone_names_the_level_shown(self) -> None:
        app, client = make_app()
        app.effort = "high"
        type_text(app, "/effort")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [])
        (notice,) = notices(app)
        self.assertIn("Reasoning effort high.", notice)
        app, _client = make_app()
        session_info(app, reasoning_effort="")
        type_text(app, "/effort")
        app._on_input(Key(ENTER))
        (notice,) = notices(app)
        self.assertIn("Hermes sets no reasoning effort for this session, so the provider's default applies.", notice)


def send_now_row(app: App) -> str | None:
    """The row under the queued prompts that names the send-now key, as drawn; None when there is none."""
    return next((line.rstrip() for line in drawn(app) if "to send now" in line), None)


def drawn(app: App) -> list[str]:
    """The screen after one repaint."""
    app._render()
    return app.terminal.screen.lines()  # type: ignore[attr-defined]


def composer_index(screen: list[str]) -> int:
    """The composer's first row: the one under the top rule (terminals of 6 rows and 20 columns or more)."""
    return next(index for index, line in enumerate(screen) if line.startswith(RULE_ROW)) + 1


def queue(app: App, *prompts: str) -> None:
    for prompt in prompts:
        app.queued.append(QueuedLine(prompt))


class QueueLinesTests(unittest.TestCase):
    def rows(self, prompts: list[str], width: int = 40, max_rows: int = 8) -> list[str]:
        return [line_text(line) for line in queue_lines(prompts, width, max_rows, DEFAULT_THEME)]

    def test_nothing_queued_draws_nothing(self) -> None:
        self.assertEqual(self.rows([]), [])
        self.assertEqual(self.rows(["a prompt"], max_rows=0), [])

    def test_each_prompt_is_one_row_and_the_last_ends_with_the_edit_key(self) -> None:
        self.assertEqual(self.rows(["fix the failing test"]), ["⧗ fix the failing test" + " " * 12 + "↑ edit"])
        rows = self.rows(["fix the failing test", "then update the changelog"])
        self.assertEqual(rows, ["⧗ fix the failing test", "⧗ then update the changelog" + " " * 7 + "↑ edit"])

    def test_the_glyph_is_muted_the_prompt_is_text_and_the_key_is_a_hint(self) -> None:
        (line,) = queue_lines(["fix it"], 40, 8, DEFAULT_THEME)
        self.assertEqual(
            [(span.text.strip(), span.style) for span in line if span.text.strip()],
            [("⧗", DEFAULT_THEME.muted), ("fix it", DEFAULT_THEME.text), ("↑ edit", DEFAULT_THEME.hint)],
        )

    def test_more_than_three_are_counted_on_a_last_row(self) -> None:
        rows = self.rows(["one", "two", "three", "four", "five"])
        self.assertEqual(rows[:3], ["⧗ one", "⧗ two", "⧗ three"])
        self.assertEqual(rows[3], "+2 more" + " " * 27 + "↑ edit")
        self.assertEqual(len(self.rows(["one", "two", "three"])), 3)  # exactly three need no count

    def test_only_the_first_line_of_a_prompt_is_named(self) -> None:
        self.assertEqual(self.rows(["\nfirst line\nsecond line"], width=30), ["⧗ first line" + " " * 12 + "↑ edit"])

    def test_a_short_slot_names_fewer_and_counts_the_rest(self) -> None:
        prompts = ["one", "two", "three", "four"]
        self.assertEqual([row.split("  ")[0] for row in self.rows(prompts, max_rows=3)], ["⧗ one", "⧗ two", "+2 more"])
        self.assertEqual([row.split("  ")[0] for row in self.rows(prompts[:3], max_rows=2)], ["⧗ one", "+2 more"])
        self.assertEqual([row.split("  ")[0] for row in self.rows(prompts[:2], max_rows=2)], ["⧗ one", "⧗ two"])
        self.assertEqual([row.split("  ")[0] for row in self.rows(prompts, max_rows=1)], ["+4 more"])

    def test_no_row_is_wider_than_the_terminal_and_the_key_survives_a_long_prompt(self) -> None:
        prompts = ["a prompt that goes on for a good while longer than any terminal here is wide. " * 2] * 5
        for width in range(20, 121):
            lines = queue_lines(prompts, width, 8, DEFAULT_THEME)
            with self.subTest(width=width):
                self.assertTrue(all(line_width(line) <= width for line in lines))
                self.assertEqual(line_width(lines[-1]), width)
                self.assertTrue(line_text(lines[-1]).endswith("↑ edit"))
                self.assertTrue(line_text(lines[0]).endswith("…"))

    def test_text_hermes_built_cannot_carry_an_escape_onto_the_row(self) -> None:
        (row,) = self.rows(["\x1b[31mred\x1b[0m \x07alert\ttab"], width=40)
        self.assertTrue(row.startswith("⧗ red alert"))
        self.assertNotIn("\x1b", row)


class QueueTests(unittest.TestCase):
    def test_queued_prompts_push_the_composer_down_by_their_rows_and_leave_no_blank_row(self) -> None:
        for rows, cols in ((7, 40), (9, 40), (10, 80), (12, 80), (24, 80), (40, 120)):
            for menu in (False, True):
                with self.subTest(rows=rows, cols=cols, menu=menu):
                    app, _client = make_app(busy=True, rows=rows, cols=cols)
                    working = composer_index(drawn(app)) - 1  # where the top edge is, the working row right above it
                    for count in (1, 2, 3, 6):
                        app.queued.clear()
                        queue(app, *(f"prompt {number}" for number in range(count)))
                        if menu:
                            app.composer.replace(0, len(app.composer.text), "/")
                        screen = drawn(app)
                        top = composer_index(screen)
                        between = screen[working : top - 1]  # the slot: the menu, the queued prompts under it
                        self.assertTrue(all(between), screen)
                        if not menu and rows >= 10:
                            # three named and "+N more", then the send-now row, within the slot's cap of a third of the rows
                            self.assertEqual(len(between), min(count, 4, rows // 3 - 1) + 1, screen)

    def test_the_rows_sit_right_above_the_composers_top_edge(self) -> None:
        app, _client = make_app(busy=True)
        queue(app, "fix the failing test", "then update the changelog")
        screen = drawn(app)
        top = composer_index(screen)
        self.assertEqual(screen[top - 1], rule_edges(80)[0])
        self.assertEqual(screen[top - 4].rstrip(), "⧗ fix the failing test")
        self.assertEqual(screen[top - 3].rstrip(), "⧗ then update the changelog")
        self.assertEqual(screen[top - 2].rstrip(), "  ctrl+j to send now · ↑ to edit")  # under them, muted
        self.assertTrue(screen[top - 5].startswith("  ⎿  Tip: "), screen)
        self.assertIn("esc to interrupt", screen[top - 6])  # the turn's activity row and its tip stay above them

    def test_a_completion_menu_keeps_the_rows_left_and_stays_above_the_queue(self) -> None:
        app, _client = make_app(busy=True, rows=24)
        queue(app, "one", "two", "three", "four")
        type_text(app, "/")
        lines = [line_text(line) for line in app._slot_lines(80, 24)]
        self.assertEqual(len(lines), slot_cap(24, 80))
        self.assertTrue(all(line.lstrip("❯ ").startswith("/") for line in lines[:3]), lines)
        self.assertEqual(lines[3:], ["⧗ one", "⧗ two", "⧗ three", "+1 more", "  ctrl+j to send now · ↑ to edit"])

    def test_a_question_or_the_session_picker_hides_the_rows(self) -> None:
        app, _client = make_app(busy=True)
        queue(app, "fix the failing test")
        self.assertIn("⧗ fix the failing test", "\n".join(drawn(app)))
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        self.assertNotIn("⧗", "\n".join(drawn(app)))
        app._answer(app.slot.decline())  # type: ignore[union-attr]
        app.picker = SessionPicker([SessionRow("stored-1", "a title", "", 0.0, 1)], current="")
        self.assertNotIn("⧗", "\n".join(drawn(app)))

    def test_up_on_an_empty_composer_takes_every_queued_prompt_back(self) -> None:
        app, client = make_app(busy=True)
        queue(app, "fix the failing test", "then update\nthe changelog", "and push")
        app._on_input(Key(UP))
        self.assertEqual(app.composer.text, "fix the failing test\nthen update\nthe changelog\nand push")
        self.assertFalse(app.queued)
        self.assertEqual(client.calls, [])
        self.assertNotIn("⧗", "\n".join(drawn(app)))

    def test_up_with_nothing_queued_still_walks_the_input_history(self) -> None:
        app, _client = make_app()
        type_text(app, "an earlier prompt")
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, "")
        app._on_input(Key(UP))
        self.assertEqual(app.composer.text, "an earlier prompt")

    def test_up_with_text_in_the_composer_leaves_the_queue_alone(self) -> None:
        app, _client = make_app(busy=True)
        queue(app, "queued")
        type_text(app, "a draft")
        app._on_input(Key(UP))
        self.assertEqual([text for text, *_ in app.queued], ["queued"])
        self.assertNotIn("queued", app.composer.text)

    def test_down_and_other_keys_do_not_take_the_queue_back(self) -> None:
        app, _client = make_app(busy=True)
        queue(app, "queued")
        for key in (Key(DOWN), Key(TAB), Key(CHAR, "k", ctrl=True)):
            app._on_input(key)
        self.assertEqual((len(app.queued), app.composer.text), (1, ""))

    def test_up_does_nothing_to_the_queue_while_something_else_has_the_keys(self) -> None:
        def approval(app: App) -> None:
            app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))

        def question(app: App) -> None:
            choices = {"questions": [{"qid": "q0", "question": "Which?", "choices": ["red", "blue"]}]}
            app._on_server_request(ServerRequest("srq-1", "clarify", choices))

        def picker(app: App) -> None:
            app.picker = SessionPicker([SessionRow("stored-1", "a title", "", 0.0, 1)], current="")

        def pager(app: App) -> None:
            app.pager = Pager("history", [])

        for opened in (approval, question, picker, pager):
            with self.subTest(opened.__name__):
                now = [100.0]
                app, client = make_app(busy=True, clock=lambda: now[0])
                queue(app, "queued")
                opened(app)
                now[0] += SLOT_ARM_SECONDS
                app._on_input(Key(UP))
                self.assertEqual([text for text, *_ in app.queued], ["queued"])
                self.assertEqual(app.composer.text, "")
                self.assertEqual((client.calls, client.answers), ([], []))

    def test_up_then_enter_on_an_approval_with_prompts_queued_still_denies(self) -> None:
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        queue(app, "queued")
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        now[0] += SLOT_ARM_SECONDS
        app._on_input(Key(UP))
        app._on_input(Key(ENTER))
        self.assertEqual(client.answers, [("srq-1", {"result": {"choice": "deny"}})])
        self.assertEqual(len(app.queued), 1)

    def test_up_then_enter_puts_the_prompts_back_in_the_queue_as_one(self) -> None:
        app, client = make_app(busy=True)
        queue(app, "first", "second")
        app._on_input(Key(UP))
        app._on_input(Key(ENTER))
        self.assertEqual([text for text, *_ in app.queued], ["first\nsecond"])
        self.assertEqual(client.calls, [])

    def test_recalled_prompts_go_as_one_text_and_only_a_first_line_command_runs(self) -> None:
        # What the recall docstring says Enter does with them: one submission, as for anything typed.
        app, client = make_app(busy=True)
        app.queued.extend([QueuedLine("plain prompt"), QueuedLine("a long skill prompt", "learn: the build", "/learn the build")])
        app._on_input(Key(UP))
        app.turn_pending = False
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("prompt.submit", {"session_id": SID, "text": "plain prompt\n/learn the build"})])

        app, client = make_app(busy=True)
        app.queued.extend([QueuedLine("a long skill prompt", "learn: the build", "/learn the build"), QueuedLine("plain prompt")])
        app._on_input(Key(UP))
        app.turn_pending = False
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("slash.exec", {"command": "learn the build\nplain prompt", "session_id": SID})])

    def test_a_prompt_a_command_built_comes_back_as_what_was_typed(self) -> None:
        # Plan mode wrote /plan around the prompt, so the prompt comes back; a typed command comes back as typed.
        app, client = make_app(busy=True)
        show_mode(app, MODE_PLAN)
        type_text(app, "fix the flaky test")
        app._on_input(Key(ENTER))
        answer(app, client, error={"code": contract.NOT_MINE, "message": "pending-input command"})
        answer(app, client, {"type": "send", "message": PLAN_PROMPT})
        show_mode(app, MODE_NORMAL)
        type_text(app, "/learn the build")
        app._on_input(Key(ENTER))
        answer(app, client, error={"code": contract.NOT_MINE, "message": "pending-input command"})
        answer(app, client, {"type": "skill", "message": "a long skill prompt", "display": "learn: the build"})
        self.assertEqual(
            list(app.queued),
            [
                QueuedLine(PLAN_PROMPT, "/plan fix the flaky test", "fix the flaky test"),
                QueuedLine("a long skill prompt", "learn: the build", "/learn the build"),
            ],
        )
        rows = [line_text(line) for line in app._slot_lines(80, 24)]
        self.assertEqual(rows[0], "⧗ /plan fix the flaky test")
        self.assertTrue(rows[1].startswith("⧗ learn: the build"))
        app._on_input(Key(UP))
        self.assertEqual(app.composer.text, "fix the flaky test\n/learn the build")


class InfoLineModeTests(unittest.TestCase):
    """The info line under the composer says the mode at every height and width; the rules never change with it."""

    def info(self, mode: str, rows: int, cols: int = 80) -> str:
        app, _client = make_app(rows=rows, cols=cols)
        show_mode(app, mode)
        app.yolo_by_tui = app.approvals_off  # accept as the TUI turns it on, so Shift+Tab walks every mode
        return info_row_of(drawn(app))

    def test_every_height_with_an_info_line_says_the_mode_on_it(self) -> None:
        # From 3 rows: a 2-row terminal has room for the composer alone and draws no info line at all. Under the rules
        # the line starts where the composer's text does; a tiny terminal draws no rules, and there it starts on the edge.
        for rows in (3, 5, 6, 7, 9, 10, 24):
            with self.subTest(rows=rows):
                inset = INFO_INSET if rows >= MIN_ROWS else ""
                self.assertTrue(self.info(MODE_ACCEPT, rows).startswith(inset + "⏵⏵ accept all on (⇧⇥ to cycle)"))
                self.assertTrue(self.info(MODE_PLAN, rows).startswith(inset + "⏸ plan mode on (⇧⇥ to cycle)"))
                self.assertFalse(self.info(MODE_NORMAL, rows).strip().startswith(("⏵", "⏸")))  # normal says no mode

    def test_a_narrow_terminal_keeps_the_label_whole(self) -> None:
        for cols in (19, 20, 30):
            with self.subTest(cols=cols):
                inset = INFO_INSET if cols >= MIN_COLS else ""
                self.assertTrue(self.info(MODE_ACCEPT, 24, cols).startswith(inset + "⏵⏵ accept all on"))
                self.assertTrue(self.info(MODE_PLAN, 24, cols).startswith(inset + "⏸ plan mode on"))

    def test_the_label_takes_the_modes_colour_and_reads_on_every_palette_and_background(self) -> None:
        from dataclasses import replace

        from omh.skin_pack import default_theme, theme_for_name, theme_names
        from omh.tui.theme import TEXT_CONTRAST, contrast_ratio, surface_for, theme_named

        for name in theme_names():
            for background in (None, "#FFFFFF", "#F6F1E6", "#1E1E1E", "#000000"):
                theme = theme_named(name, background)
                surface = surface_for(theme_for_name(name) or default_theme(), background)
                for mode, colour, label in ((MODE_ACCEPT, theme.mode_accept, "⏵⏵ accept all on"),
                                            (MODE_PLAN, theme.mode_plan, "⏸ plan mode on")):
                    with self.subTest(theme=name, background=background, mode=mode):
                        app, _client = make_app(rows=9, theme=theme)
                        show_mode(app, mode)
                        chip = next(span for span in app._info_line(80) if span.text == label)
                        self.assertEqual(chip.style, replace(colour, bold=True))
                        self.assertIsNone(chip.style.bg)  # no band: the line sits on the terminal's background
                        self.assertGreaterEqual(contrast_ratio(chip.style.fg, surface), TEXT_CONTRAST)


def bells(app_or_terminal: object) -> int:
    terminal = getattr(app_or_terminal, "terminal", app_or_terminal)
    return "".join(terminal.writes).count("\a")  # type: ignore[attr-defined]


class BellTests(unittest.TestCase):
    APPROVAL = ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"})

    def test_an_approval_opening_rings_once(self) -> None:
        app, _client = make_app(busy=True)
        self.assertEqual(bells(app), 0)
        app._on_server_request(self.APPROVAL)
        self.assertEqual(bells(app), 1)
        for _ in range(3):  # repaints of the open slot ring nothing more
            drawn(app)
        self.assertEqual(bells(app), 1)

    def test_omh_tui_bell_0_keeps_it_quiet_and_nothing_else_does(self) -> None:
        for value, expected in (("0", 0), ("1", 1), ("", 1), ("off", 1), ("00", 1)):
            with self.subTest(value=value):
                app, _client = make_app(busy=True, environ={"OMH_TUI_BELL": value})
                app._on_server_request(self.APPROVAL)
                self.assertEqual(bells(app), expected)
                self.assertIsNotNone(app.slot)  # quiet or not, the approval is shown

    def test_every_question_rings_once_and_a_request_the_tui_cannot_show_does_not(self) -> None:
        requests = (
            ("clarify", {"questions": [{"qid": "q0", "question": "Which?", "choices": ["red", "blue"]}]}, 1),
            ("sudo", {"command": "apt install x"}, 1),
            ("secret", {"env_var": "TOKEN_X"}, 1),
            ("vault.code", {}, 1),
            ("vault.unlock_prompt", {}, 0),
            ("terminal.read", {}, 0),
        )
        for method, params, expected in requests:
            with self.subTest(method=method):
                app, _client = make_app(busy=True)
                app._on_server_request(ServerRequest("srq-1", method, params))
                self.assertEqual(bells(app), expected)

    def test_an_approval_waiting_behind_another_rings_when_its_own_slot_opens(self) -> None:
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        app._on_server_request(self.APPROVAL)
        app._on_server_request(ServerRequest("srq-2", "approval", {"command": "rm -rf ./y"}))
        self.assertEqual(bells(app), 1)
        now[0] += SLOT_ARM_SECONDS
        app._on_input(Key(CHAR, "d"))
        self.assertEqual([request_id for request_id, _frame in client.answers], ["srq-1"])
        self.assertEqual(bells(app), 2)

    def test_a_withdrawn_approval_rings_nothing_more(self) -> None:
        app, _client = make_app(busy=True)
        app._on_server_request(self.APPROVAL)
        app._on_event(Event("request.cancel", app.sid, {"id": "srq-1", "reason": "timeout"}))
        self.assertIsNone(app.slot)
        self.assertEqual(bells(app), 1)


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class BellReplayTests(AppTestCase):
    def test_the_recorded_approval_rings_once_and_omh_tui_bell_0_not_at_all(self) -> None:
        for env, expected in (({}, 1), ({"OMH_TUI_BELL": "0"}, 0)):
            with self.subTest(env=env):
                run = self.prepare(
                    Scenario("approval", spans("approval", "startup", "create", "approval_turn"),
                             answers=(*startup_answers(), INTERRUPTED)),
                    env=env,
                )
                terminal = run.terminal
                terminal.script(
                    Step(b"Run rm -rf ./omh-m0-probe-dir\r", when=terminal.idle, label="idle"),
                    Step(when=terminal.shows("Hermes asks to run"), label="the approval slot"),
                    Step(
                        b"d",
                        when=lambda terminal=terminal: time.monotonic() - terminal.fired["the approval slot"]
                        > SLOT_ARM_SECONDS + 0.05,
                        label="armed",
                    ),
                    Step(b"\x04", when=lambda terminal=terminal: "proceed." in terminal.history() and terminal.idle(),
                         label="end"),
                )
                self.run_main(run)
                self.assert_clean_run(run)
                self.assertEqual(bells(terminal), expected)


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class ModeReplayTests(AppTestCase):
    def test_queued_prompts_show_above_the_box_and_up_takes_them_back_unsent(self) -> None:
        run = self.prepare(
            Scenario("session", spans("session", "startup", "create", "interrupted_turn"), answers=startup_answers())
        )
        terminal = run.terminal

        def running() -> bool:
            return terminal.running()

        terminal.script(
            Step(b"Write the numbers from 1 to 300, one per line, nothing else.\r", when=terminal.idle, label="idle"),
            # The replay holds this turn open until it sees session.interrupt.
            Step(b"second prompt\rthird prompt\r", when=running, label="running"),
            Step(b"\x1b[A", when=terminal.shows("⧗ third prompt"), capture="queued", label="queued"),
            Step(b"\x03", when=terminal.shows("❯ second prompt"), capture="recalled", label="recalled"),
            Step(b"\x03", when=lambda: not terminal.shows("third prompt")(), label="cleared"),
            Step(b"\x04", when=lambda: "Interrupted." in terminal.history() and terminal.idle(), label="end"),
        )
        self.run_main(run)
        self.assert_clean_run(run)  # a prompt.submit for either queued prompt would be a replay mismatch
        self.assertEqual(len(run.calls("prompt.submit")), 1)
        queued, recalled = (terminal.captures[name] for name in ("queued", "recalled"))
        top = composer_index(queued)
        self.assertEqual(queued[top - 4].rstrip(), "⧗ second prompt")
        self.assertEqual(queued[top - 3].rstrip(), "⧗ third prompt")
        self.assertEqual(queued[top - 2].rstrip(), "  ctrl+j to send now · ↑ to edit")  # the keys, under the rows
        self.assertNotIn("queued", info_row_of(queued))
        self.assertNotIn("⧗", "\n".join(recalled))
        self.assertEqual(composer_text(recalled[composer_index(recalled) + 1]).strip(), "third prompt")
        self.assertNotIn("queued", info_row_of(recalled))

    def test_ctrl_t_shows_the_effort_hermes_confirmed_on_the_info_line(self) -> None:
        answers = (*startup_answers(), ("config.set", {"result": effort_set("low")}))
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        terminal = run.terminal
        terminal.script(
            Step(b"\x14", when=terminal.idle, capture="before", label="idle"),
            Step(b"\x04", when=terminal.shows("effort low"), label="the effort"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        (call,) = run.calls("config.set")
        self.assertEqual(call["params"], {"key": "reasoning", "session_id": LIVE_ID, "value": "low"})
        # The level is absent until Hermes names one.
        self.assertNotIn("effort low", "\n".join(terminal.captures["before"]))

    def test_shift_tab_walks_the_modes_and_the_frame_shows_each(self) -> None:
        answers = (*startup_answers(), ("config.set", {"result": YOLO_IS_ON}), ("config.set", {"result": YOLO_IS_OFF}))
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=answers))
        terminal = run.terminal
        terminal.script(
            Step(SHIFT_TAB_BYTES, when=terminal.idle, capture="normal", label="idle"),
            Step(SHIFT_TAB_BYTES, when=terminal.shows("⏵⏵ accept all on"), capture="accept", label="accept"),
            Step(SHIFT_TAB_BYTES, when=terminal.shows("⏸ plan mode on"), capture="plan", label="plan"),
            Step(b"\x04", when=lambda: not terminal.shows("plan mode on")() and terminal.idle(), label="normal again"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual(
            [frame["params"] for frame in run.calls("config.set")],
            [
                {"key": "yolo", "session_id": LIVE_ID, "value": "on"},
                {"key": "yolo", "session_id": LIVE_ID, "value": "off"},
            ],
        )
        top, _bottom = rule_edges(80)  # the composer's two rules are the same row, above and under it
        for name in ("normal", "accept", "plan"):  # the rules are the same in every mode
            screen = terminal.captures[name]
            self.assertEqual(screen.count(top), 2, screen)

    def test_a_plan_mode_prompt_reaches_hermes_as_the_prompt_slash_plan_builds(self) -> None:
        answers = (
            *startup_answers(),
            ("config.set", {"result": YOLO_IS_ON}),
            ("config.set", {"result": YOLO_IS_OFF}),
            ("slash.exec", {"error": {"code": 4018, "message": "pending-input command"}}),
            ("command.dispatch", {"result": {"type": "send", "message": PLAN_PROMPT}}),
        )
        run = self.prepare(Scenario("session", spans("session", "startup", "create", "plain_turn"), answers=answers))
        terminal = run.terminal
        terminal.script(
            Step(SHIFT_TAB_BYTES, when=terminal.idle, label="idle"),
            Step(SHIFT_TAB_BYTES, when=terminal.shows("⏵⏵ accept all on"), label="accept"),
            Step(b"fix the flaky test\r", when=terminal.shows("⏸ plan mode on"), label="plan"),
            Step(b"\x04", when=lambda: "later." in terminal.history() and terminal.idle(), label="the reply"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        (dispatch,) = run.calls("command.dispatch")
        self.assertEqual(dispatch["params"], {"name": "plan", "arg": "fix the flaky test", "session_id": LIVE_ID})
        (submitted,) = run.calls("prompt.submit")
        self.assertEqual(submitted["params"], {"session_id": LIVE_ID, "text": PLAN_PROMPT})
        self.assertIn("❯ /plan fix the flaky test", terminal.history())
        self.assertNotIn("PLAN MODE", terminal.history())


if __name__ == "__main__":
    unittest.main()
