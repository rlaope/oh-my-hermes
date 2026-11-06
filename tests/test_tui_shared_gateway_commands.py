"""The OMH TUI's side of the commands Hermes' shared gateway runs through a verb of its own.

The gateway child (`attach/gateway_attach.py`, tested in `test_tui_gateway_attach`) answers `/compress`, `/branch`,
`/bg`, `/btw` and the rest in `slash.exec`'s shape; here the TUI says a compression is under way, opens the session a
`/branch` made, and shows a side agent's answer when it arrives. Driven through the recording client of
`test_tui_modes`, answering each call by hand.
"""

from __future__ import annotations

import unittest

from _tui_lines import lines_text
from test_tui_command_output import last, send
from test_tui_modes import SID, answer, make_app, notices, type_text
from omh.tui.app import (
    BRANCHED_NOTICE,
    CALL_EXPIRED_NOTICE,
    COMPRESS_ANSWER_SECONDS,
    COMPRESS_STARTED_NOTICE,
    COMPRESS_UNANSWERED_NOTICE,
    COMPRESSING_VERB,
    COMPRESSION_BUSY_NOTICE,
    COMPRESSION_HELD_NOTICE,
    HELD_ANSWER_SECONDS,
    REFUSAL_SENTENCES,
    SIDE_ANSWERS_LEFT_NOTICE,
    STEER_UNANSWERED_OUTCOME,
)
from omh.tui import gateway_contract as contract
from omh.tui.gateway import Event, Response
from omh.tui.keys import ENTER, Key
from omh.tui.transcript import NOTICE_ERROR, NOTICE_INFO, NOTICE_WARN, CommandBlock

BUSY = {"code": 4001, "message": "session_busy", "data": {"reason": "session_busy"}}


class CompressTests(unittest.TestCase):
    def test_compact_runs_hermes_compress_and_says_it_is_under_way_until_the_report(self) -> None:
        app, client = make_app()
        send(app, "/compact here 2")
        self.assertEqual(client.calls, [("slash.exec", {"command": "compress here 2", "session_id": SID})])
        block = last(app)
        self.assertIsInstance(block, CommandBlock)
        self.assertEqual((block.command, block.parts, block.done),
                         ("/compact here 2", [(COMPRESS_STARTED_NOTICE, NOTICE_INFO)], False))
        report = "✓ Compressed: 24 → 12 messages\n  Approx request size: ~816 → ~1,040 tokens"
        answer(app, client, {"type": "exec", "output": report})
        self.assertEqual((block.parts[-1], block.done), ((report, NOTICE_INFO), True))

    def test_a_compress_out_shows_a_working_row_whose_clock_counts_until_it_settles(self) -> None:
        # Owner report 2026-10-30: `/compact` showed the started notice and nothing moved for the ~88 s Hermes took.
        for settle in ("answered", "unanswered"):
            with self.subTest(settle=settle):
                now = [100.0]
                app, client = make_app(clock=lambda: now[0])
                send(app, "/compact")
                now[0] += 42.0
                self.assertTrue(lines_text(app._tail(80))[-1].endswith(f"{COMPRESSING_VERB}… (42s)"))
                now[0] += 46.0
                self.assertTrue(lines_text(app._tail(80))[-1].endswith(f"{COMPRESSING_VERB}… (1m 28s)"))
                self.assertFalse(app._busy())  # no glow, and a prompt still goes out as it did
                self.assertEqual(app._working_rows(), 1)
                self.assertLessEqual(app._read_timeout(), 1.0)  # the loop wakes to move the clock
                if settle == "answered":
                    answer(app, client, {"type": "exec", "output": "✓ Compressed: 24 → 12 messages"})
                else:
                    now[0] += COMPRESS_ANSWER_SECONDS
                    app._expire_calls()
                self.assertFalse([line for line in lines_text(app._tail(80)) if f"{COMPRESSING_VERB}…" in line])
                self.assertEqual(app._working_rows(), 0)

    def test_a_compress_sent_during_a_turn_leaves_the_turn_its_own_working_row(self) -> None:
        app, _client = make_app(busy=True)
        send(app, "/compress")
        self.assertFalse([line for line in lines_text(app._tail(80)) if f"{COMPRESSING_VERB}…" in line])

    def test_a_preview_or_a_running_turn_says_nothing_is_under_way(self) -> None:
        for line, busy in (("/compress --preview", False), ("/compact --dry-run", False), ("/compress", True)):
            with self.subTest(line=line, busy=busy):
                app, client = make_app(busy=busy)
                send(app, line)
                self.assertEqual(client.calls[-1][0], "slash.exec")
                self.assertNotIn(COMPRESS_STARTED_NOTICE, notices(app))

    def test_a_compress_is_waited_for_as_long_as_hermes_waits_and_never_sent_twice(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        send(app, "/compact")
        [call] = app.pending.values()
        self.assertEqual(call.expires_at, 100.0 + COMPRESS_ANSWER_SECONDS)  # Hermes' COMPRESS_RPC_TIMEOUT, 660 s
        now[0] += 200.0  # past the 120 s every other call gets
        app._expire_calls()
        self.assertEqual(len(app.pending), 1)
        now[0] += COMPRESS_ANSWER_SECONDS
        app._expire_calls()
        self.assertEqual(app.pending, {})
        self.assertEqual(client.forgotten, [1])
        self.assertIn(COMPRESS_UNANSWERED_NOTICE.format(seconds=COMPRESS_ANSWER_SECONDS), notices(app, NOTICE_WARN))
        self.assertEqual(len(client.calls), 1)  # nothing sent again
        self.assertTrue(last(app).done)

    def test_another_command_keeps_the_usual_budget(self) -> None:
        now = [100.0]
        app, _client = make_app(clock=lambda: now[0])
        send(app, "/undo")
        [call] = app.pending.values()
        self.assertEqual(call.expires_at, 100.0 + 120.0)

    def test_a_command_sent_while_the_compress_is_out_is_waited_for_until_hermes_runs_it(self) -> None:
        # Measured on Hermes bf0203a794's shared gateway: an /undo sent during a /compress is held until the
        # compression commits, then runs. Given only 120 s, its draft was dropped while Hermes still undid the turn.
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        app.shared_gateway = True
        send(app, "/compress")
        now[0] += 40.0
        send(app, "/undo")
        self.assertEqual(client.calls[-1], ("slash.exec", {"command": "undo", "session_id": SID}))
        undo = app.pending[2]
        self.assertEqual(undo.expires_at, 100.0 + COMPRESS_ANSWER_SECONDS + 120.0)  # the compress's end, then 120 s
        # Under /undo's echo, which waits below the open /compress echo.
        self.assertEqual(undo.command.parts, [(COMPRESSION_HELD_NOTICE.format(name="undo"), NOTICE_INFO)])
        now[0] += 300.0  # past the 120 s a command alone gets
        app._expire_calls()
        self.assertEqual(sorted(app.pending), [1, 2])
        app._on_response(Response(1, {"type": "exec", "output": "✓ Compressed: 12 → 10 messages"}, None))
        app._on_response(Response(2, {"type": "prefill", "message": "hello number 6", "notice": "↶ Undid 1 turn."},
                                  None))
        self.assertEqual(app.composer.text, "hello number 6")
        self.assertEqual(notices(app, NOTICE_WARN), [])

    def test_a_held_command_unanswered_past_its_budget_says_how_long_it_was_waited_for(self) -> None:
        now = [100.0]
        app, _client = make_app(clock=lambda: now[0])
        send(app, "/compress")
        send(app, "/retry")
        self.assertEqual(app.pending[2].command.parts, [])  # the stdio entry refuses it as busy, holding nothing
        now[0] += COMPRESS_ANSWER_SECONDS + 120.0
        app._expire_calls()
        self.assertIn(CALL_EXPIRED_NOTICE.format(method="slash.exec", seconds=COMPRESS_ANSWER_SECONDS + 120.0),
                      notices(app, NOTICE_WARN))

    def test_a_command_waits_as_usual_once_the_compress_settled_or_for_a_preview(self) -> None:
        for settle in ("answered", "preview"):
            with self.subTest(settle=settle):
                now = [100.0]
                app, client = make_app(clock=lambda: now[0])
                app.shared_gateway = True
                send(app, "/compress --preview" if settle == "preview" else "/compress")
                if settle == "answered":
                    answer(app, client, {"type": "exec", "output": "✓ Compressed: 12 → 10 messages"})
                send(app, "/undo")
                undo = app.pending[2]
                self.assertEqual((undo.expires_at, undo.command.parts), (100.0 + 120.0, []))

    def test_every_call_sent_while_the_compress_is_out_waits_behind_it(self) -> None:
        # #2352 review: Hermes' shared gateway serves a connection's calls one at a time (bf0203a794
        # `tui_gateway/ws.py`) and awaits /compress inline; a /usage and a plain prompt were held live too.
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        app.shared_gateway = True
        send(app, "/compress")
        now[0] += 10.0
        send(app, "plain prompt please")
        self.assertEqual(client.calls[-1][0], "prompt.submit")
        self.assertEqual(app.pending[2].expires_at, 100.0 + COMPRESS_ANSWER_SECONDS + 120.0)
        send(app, "/myskill do it")  # a skill: slash.exec refuses it with 4018 and command.dispatch runs it
        app._on_response(Response(3, None, {"code": contract.NOT_MINE, "message": "skill command"}))
        self.assertEqual(client.calls[-1][0], "command.dispatch")
        self.assertEqual(app.pending[4].expires_at, 100.0 + COMPRESS_ANSWER_SECONDS + 120.0)

    def test_a_second_compress_waits_behind_the_first_but_never_past_the_cap(self) -> None:
        now = [100.0]
        app, _client = make_app(clock=lambda: now[0])
        app.shared_gateway = True
        send(app, "/compress")
        now[0] += 300.0
        send(app, "/compress")
        second = app.pending[2]
        self.assertEqual(second.expires_at, 400.0 + HELD_ANSWER_SECONDS)  # 360 s left + 660 s, cut to 780 s
        self.assertEqual(second.command.parts, [(COMPRESS_STARTED_NOTICE, NOTICE_INFO)])  # no held notice of its own
        now[0] += 1.0
        send(app, "/usage")
        self.assertEqual(app.pending[3].expires_at, 401.0 + HELD_ANSWER_SECONDS)  # behind the later of the two

    def test_a_second_compress_that_goes_unanswered_names_the_seconds_it_was_waited_for(self) -> None:
        now = [100.0]
        app, _client = make_app(clock=lambda: now[0])
        app.shared_gateway = True
        send(app, "/compress")
        now[0] += 300.0
        send(app, "/compress")
        app._on_response(Response(1, {"type": "exec", "output": "✓ Compressed"}, None))  # the first one lands
        now[0] += HELD_ANSWER_SECONDS
        app._expire_calls()
        said = notices(app, NOTICE_WARN)
        self.assertIn(COMPRESS_UNANSWERED_NOTICE.format(seconds=HELD_ANSWER_SECONDS), said)  # 780 s, not 660 s
        self.assertNotIn(COMPRESS_UNANSWERED_NOTICE.format(seconds=COMPRESS_ANSWER_SECONDS), said)

    def test_a_steer_held_behind_a_compress_names_the_seconds_it_was_waited_for(self) -> None:
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        app.shared_gateway = True
        send(app, "/compress")
        now[0] += 60.0
        type_text(app, "use the other file")
        app._on_input(Key(ENTER, ctrl=True))
        self.assertEqual(client.calls[-1][0], "session.redirect")
        [steer] = [call for call in app.pending.values() if call.steer is not None]
        waited = COMPRESS_ANSWER_SECONDS - 60.0 + 120.0  # the compression's time left, then its own 120 s
        self.assertEqual(steer.seconds, waited)
        now[0] += waited
        app._expire_calls()
        outcome = STEER_UNANSWERED_OUTCOME.format(seconds=waited)
        self.assertEqual(steer.steer.outcome, outcome)
        self.assertNotIn("120 s", outcome)

    def test_a_command_refused_while_hermes_compresses_says_so(self) -> None:
        for line, name in (("/undo", "undo"), ("/retry", "retry"), ("/compress", "compress")):
            with self.subTest(line=line):
                app, client = make_app()
                send(app, line)
                answer(app, client, error={"code": 4001, "message": "session_busy",
                                           "data": {"reason": "session_busy", "field": "compression"}})
                self.assertEqual(notices(app, NOTICE_WARN), [COMPRESSION_BUSY_NOTICE.format(name=name)])
                self.assertEqual(notices(app, NOTICE_ERROR), [])

    def test_a_compress_during_a_turn_is_refused_in_words(self) -> None:
        app, client = make_app(busy=True)
        send(app, "/compress")
        answer(app, client, error=BUSY)
        self.assertIn(REFUSAL_SENTENCES["session_busy"], notices(app, NOTICE_ERROR))


class BranchTests(unittest.TestCase):
    def test_the_session_a_branch_made_is_opened_and_says_where_it_came_from(self) -> None:
        app, client = make_app()
        app.stored_id = "stored-1"
        send(app, "/branch side quest")
        answer(app, client, {"type": "exec", "output": "⑂ Branched into session local-child.",
                             "branched_session_id": "local-child"})
        self.assertEqual(client.calls[-1], ("session.resume", {"session_id": "local-child", "cols": 80}))
        answer(app, client, {"session_id": "live-2", "stored_session_id": "local-child", "info": {}, "messages": []})
        self.assertEqual(app.stored_id, "local-child")
        self.assertIn(BRANCHED_NOTICE.format(parent="stored-1"), notices(app))

    def test_output_with_no_new_session_opens_nothing(self) -> None:
        app, client = make_app()
        send(app, "/branch")
        answer(app, client, {"type": "exec", "output": "Hermes branched the session but named no new session."})
        self.assertEqual([method for method, _params in client.calls], ["slash.exec"])


class SideAnswerTests(unittest.TestCase):
    def test_a_bg_or_btw_answer_is_shown_when_it_arrives_and_one_from_a_session_left_names_it(self) -> None:
        app, _client = make_app()
        done = {"task_id": "bg_7b76c3", "text": "## Done\nTests pass.\x1b[2J"}
        app._on_event(Event("background.complete", SID, done))
        app._on_event(Event("btw.complete", SID, {"task_id": "btw_1", "question": "what did I say first?",
                                                  "text": "hello number 0"}))
        app._on_event(Event("btw.complete", "other-session", {"task_id": "btw_2", "text": "not this one"}))
        self.assertEqual(notices(app)[-3:], ["[bg bg_7b76c3] ## Done\nTests pass.",
                                             '[btw "what did I say first?"] hello number 0',
                                             "From session other-session: [btw] not this one"])

    def test_leaving_a_session_before_its_side_answer_says_it_will_not_show(self) -> None:
        # Measured on Hermes bf0203a794: once the view is closed (a switch, /new), the gateway sends a /bg answer
        # nowhere this connection sees.
        app, client = make_app()
        send(app, "/bg run the tests")
        answer(app, client, {"type": "exec", "output": "Running in the background as bg_1; its answer appears here.",
                             "task_id": "bg_1"})
        send(app, "/btw why?")
        answer(app, client, {"type": "exec", "output": "Asking on the side as btw_2.", "task_id": "btw_2"})
        app._on_event(Event("btw.complete", SID, {"task_id": "btw_2", "text": "because"}))
        send(app, "/new")
        answer(app, client, {"session_id": "live-2", "stored_session_id": "s-2", "info": {}})
        self.assertIn(SIDE_ANSWERS_LEFT_NOTICE.format(tasks="bg_1", session=SID), notices(app, NOTICE_WARN))
        self.assertEqual(app.side_tasks, {})


class RoutedToHermesTests(unittest.TestCase):
    def test_topup_and_the_classic_commands_go_to_hermes_as_typed(self) -> None:
        for line, command in (("/topup", "topup"), ("/handoff telegram", "handoff telegram")):
            with self.subTest(line=line):
                app, client = make_app()
                app.shared_gateway = True
                send(app, line)
                self.assertEqual(client.calls, [("slash.exec", {"command": command, "session_id": SID})])

    def test_topup_on_the_stdio_entry_names_hermes_own_terminal(self) -> None:
        # An older Hermes runs it in its CLI worker, whose top-up menus are interactive.
        app, client = make_app()
        send(app, "/topup")
        self.assertEqual(client.calls, [])
        self.assertIn("/topup runs in Hermes' own terminal: `hermes --tui`.", notices(app))

    def test_a_session_answer_naming_this_connections_view_is_a_shared_gateway(self) -> None:
        app, client = make_app()
        send(app, "/new")
        answer(app, client, {"session_id": "live-2", "stored_session_id": "s-2", "info": {}, "subscription_id": "sub"})
        self.assertTrue(app.shared_gateway)
        send(app, "/new")
        answer(app, client, {"session_id": "live-3", "stored_session_id": "s-3", "info": {}})
        self.assertFalse(app.shared_gateway)

    def test_a_classic_commands_refusal_carries_hermes_own_pointer(self) -> None:
        app, client = make_app()
        send(app, "/handoff")
        hint = "Hand off from the classic CLI: `hermes --cli --resume <session>`, then /handoff <platform>."
        answer(app, client, error={"code": 4001, "message": "unsupported_command",
                                   "data": {"reason": "unsupported_command", "detail": hint}})
        self.assertEqual(notices(app, NOTICE_ERROR), [f"{REFUSAL_SENTENCES['unsupported_command']} {hint}"])

    def test_timestamps_sends_nothing(self) -> None:
        app, client = make_app()
        send(app, "/timestamps on")
        self.assertEqual(client.calls, [])
        self.assertIn("/timestamps is an Ink display setting; the OMH TUI has no equivalent.", notices(app))


if __name__ == "__main__":
    unittest.main()
