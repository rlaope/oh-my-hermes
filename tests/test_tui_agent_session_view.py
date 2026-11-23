"""One subagent's session on the main screen (`subagent_session`, `AgentViewMixin._open_agent`): Enter on an agent
shows its session like Claude Code's teammate view, the composer messages it, Esc and `main` go back, and where the
view cannot open the agent's log opens in the pager as before.

The read follows the spike's decisions: on Hermes' stdio entry a lazy resume of the child's session gives a watch sid
whose mirrored events draw in the view; on the shared gateway (`App.shared_gateway`) `session.transcript` with the
subagent's id is polled forward. Answers below are trimmed from the spike's recorded frames.
"""

from __future__ import annotations

import unittest

from test_tui_agent_mouse import row_of, settled
from test_tui_agent_view import agent_app, agent_event, relay
from test_tui_respawn import crash, crashing
from test_tui_modes import SID, answer, call_id, drawn, type_text
from test_tui_subagents import FIRST, FRAMES, SECOND
from omh.tui import subagent_session as view_state
from omh.tui.agent_view import AGENT_LIST_HINTS
from omh.tui.app import Attachment
from omh.tui.frame import labelled_rule
from omh.tui.gateway import Event, Response
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, Key, Mouse, BUTTON_LEFT, Paste
from omh.tui.pager import ALT_SCREEN_ON
from omh.tui.style import Span
from omh.tui.subagent_session import (
    AWAY_MARK, FROM_MAIN, POLL_SECONDS, REFUSED_WHILE_VIEWING, UNSUPPORTED_LINE, VIEWED_MARK, SubagentView, mark_rows,
)
from omh.tui.subagents import MAIN_ID
from omh.tui.theme import DEFAULT_THEME
from omh.tui.transcript import AssistantBlock, NoticeBlock, SteerBlock, ToolGroup, Transcript, UserBlock
from omh.tui.width import cell_width

WATCH = "942c2fef"  # the watch sid a lazy resume answered in the spike
CHILD = "child-session-0"  # FIRST's child session in the recorded frames
GOAL = "find usages of old_api in src/ and list every call site"
NAME = "find usages of"  # FIRST's `Agent.name`
BRIEF = {"role": "user", "text": GOAL, "row_id": 4}
TOOL = {"role": "tool", "name": "terminal", "context": "sleep 30 + 1 command", "tool_call_id": "t1",
        "args": {"command": "sleep 30 && echo done"}}
REPLY = {"role": "assistant", "text": "Finished. The command printed done.", "row_id": 9}
STEER_ROW = {"role": "user", "text": "also say hi", "row_id": 8, "display_kind": "steer"}


def lazy_answer(messages: list[dict] | None = None, running: bool = True) -> dict:
    return {"session_id": WATCH, "resumed": CHILD, "messages": messages or [], "running": running,
            "info": {"lazy": True}}


def rows_answer(rows: list[dict] | None = None, running: bool = True, reset: bool = True, cursor: str = "c1") -> dict:
    return {"session_id": SID, "rows": [{**row, "row_kind": "message"} for row in rows or []], "next_cursor": cursor,
            "reset": reset, "subagent_id": FIRST, "available": True, "running": running, "child_session_id": CHILD}


def entered(shared: bool = False, **options: object):
    """An app with the recorded agents running whose agent list took Enter on the first agent: the open is out."""
    clock = options.pop("clock", None)
    now = [0.0]
    app, client = agent_app(frames=FRAMES[:6], clock=clock or (lambda: now[0]), session_view=True, **options)
    app.shared_gateway = shared
    app._on_input(Key(DOWN))
    app._on_input(Key(ENTER))
    return app, client, now


def viewing(shared: bool = False, result: dict | None = None, **options: object):
    """An app with the first agent's session on screen, opened on the stdio wire (or the shared gateway's)."""
    app, client, now = entered(shared, **options)
    answer(app, client, result if result is not None else (rows_answer([BRIEF]) if shared else lazy_answer([BRIEF])))
    return app, client, now


def texts(transcript: Transcript) -> list[str]:
    out = []
    for block in transcript.blocks:
        if isinstance(block, NoticeBlock):
            out.append(f"notice:{block.text}")
        elif isinstance(block, UserBlock):
            out.append(f"user:{block.text}")
        elif isinstance(block, AssistantBlock):
            out.append(f"reply:{block.text}")
        elif isinstance(block, ToolGroup):
            out.append("tools")
        elif isinstance(block, SteerBlock):
            out.append(f"steer:{block.text}")
    return out


class OpeningTests(unittest.TestCase):
    def test_enter_on_stdio_sends_a_lazy_resume_of_the_child_and_never_a_plain_one(self) -> None:
        app, client, _now = entered()
        self.assertEqual(client.calls[-1], ("session.resume", {"session_id": CHILD, "lazy": True, "cols": 80}))
        self.assertFalse([params for method, params in client.calls if method == "session.resume" and not params.get("lazy")])
        self.assertIsNone(app.pager)

    def test_enter_on_the_shared_gateway_reads_the_subagents_transcript_on_the_parent(self) -> None:
        _app, client, _now = entered(shared=True)
        self.assertEqual(client.calls[-1], ("session.transcript", {
            "session_id": SID, "subagent_id": FIRST, "order": "oldest", "limit": view_state.READ_LIMIT}))
        self.assertFalse(client.named("session.resume"))

    def test_the_answer_draws_the_history_under_from_main_on_the_main_screen(self) -> None:
        app, _client, _now = viewing(result=lazy_answer([BRIEF, TOOL, STEER_ROW, REPLY], running=False))
        assert app.viewing is not None
        self.assertEqual((app.viewing.subagent_id, app.viewing.watch_sid, app.list_selected), (FIRST, WATCH, None))
        self.assertEqual(texts(app.viewing.transcript),
                         [f"notice:{FROM_MAIN}", f"user:{GOAL}", "tools", "user:also say hi", f"reply:{REPLY['text']}"])
        screen = drawn(app)
        joined = "\n".join(screen)
        self.assertIn(FROM_MAIN, joined)
        self.assertIn(REPLY["text"], joined)
        self.assertLess(joined.index(FROM_MAIN), joined.index(GOAL[:30]))

    def test_a_child_with_no_rows_yet_shows_its_goal_as_the_brief_once(self) -> None:
        app, client, now = viewing(shared=True, result=rows_answer([]))
        assert app.viewing is not None
        self.assertEqual(texts(app.viewing.transcript), [f"notice:{FROM_MAIN}", f"user:{GOAL}"])
        now[0] = POLL_SECONDS
        app._poll_view_when_due()
        app._on_response(Response(call_id(client, "session.transcript"), rows_answer([BRIEF, TOOL], reset=False), None))
        self.assertEqual(texts(app.viewing.transcript), [f"notice:{FROM_MAIN}", f"user:{GOAL}", "tools"])

    def test_the_composer_names_the_agent_on_its_top_rule_and_placeholder(self) -> None:
        app, _client, _now = viewing()
        screen = drawn(app)
        rule = next(line for line in screen if line.startswith("────") and line.rstrip().endswith(f"{NAME} ─"))
        self.assertEqual(cell_width(rule.rstrip()), 80)
        self.assertTrue(any(f"Message @{NAME}…" in line for line in screen))

    def test_the_main_screen_without_a_view_keeps_its_plain_rule_and_placeholder(self) -> None:
        app, _client, _now = entered()
        screen = drawn(app)
        self.assertFalse(any(NAME in line and line.startswith("────") for line in screen))


class FallbackTests(unittest.TestCase):
    def test_a_refused_read_opens_the_agents_log_in_the_pager(self) -> None:
        for shared, error in ((False, {"code": 4000, "message": "unknown field lazy"}),
                              (False, {"code": -32601, "message": "no such method"}),
                              (True, {"code": 4001, "message": "invalid_params"})):
            with self.subTest(shared=shared, code=error["code"]):
                app, client, _now = entered(shared)
                answer(app, client, error=error)
                self.assertIsNone(app.viewing)
                self.assertEqual(app.log_agent, FIRST)
                self.assertIn(ALT_SCREEN_ON, app.terminal.writes)
                self.assertIsNone(app.exit_code)  # a drift code on this open costs no session

    def test_an_unavailable_transcript_opens_the_log(self) -> None:
        app, client, _now = entered(shared=True)
        answer(app, client, {**rows_answer([]), "available": False})
        self.assertEqual((app.viewing, app.log_agent), (None, FIRST))

    def test_an_answer_without_a_child_session_opens_the_log(self) -> None:
        app, client, _now = entered(shared=True)
        answer(app, client, {**rows_answer([]), "child_session_id": None})
        self.assertEqual((app.viewing, app.log_agent), (None, FIRST))

    def test_an_agent_with_no_child_session_opens_the_log_and_sends_nothing(self) -> None:
        app, client, _now = entered()
        sent = len(client.calls)
        app._leave_view()
        app.roster.agents[SECOND].child_session_id = ""
        app._open_agent(SECOND)
        self.assertEqual((app.log_agent, len(client.calls)), (SECOND, sent))

    def test_a_lazy_resume_answer_without_a_watch_sid_opens_the_log(self) -> None:
        app, client, _now = entered()
        answer(app, client, {"messages": []})
        self.assertEqual((app.viewing, app.log_agent), (None, FIRST))


class OpenFromTests(unittest.TestCase):
    def test_a_click_on_an_agents_row_opens_its_session(self) -> None:
        app, client = agent_app(frames=FRAMES[:6], session_view=True)
        app._on_input(Key(DOWN))
        settled(app)
        app._on_input(Mouse(BUTTON_LEFT, 5, row_of(app, GOAL[:30])))
        self.assertEqual(client.calls[-1][0], "session.resume")
        answer(app, client, lazy_answer([BRIEF]))
        self.assertEqual(app.viewing.subagent_id if app.viewing else None, FIRST)

    def test_enter_on_a_dag_tree_node_opens_its_childs_session(self) -> None:
        app, client = agent_app(frames=FRAMES[:6], session_view=True)
        app._open_agent(FIRST)  # the tree's Enter calls the same opener with its node's child (`_tree_key`)
        answer(app, client, lazy_answer([BRIEF]))
        self.assertEqual(app.viewing.subagent_id if app.viewing else None, FIRST)


class LiveEventTests(unittest.TestCase):
    def test_watch_events_draw_in_the_view_and_not_in_main(self) -> None:
        app, _client, _now = viewing()
        main_before = list(app.transcript.blocks)
        app._on_event(Event("message.start", WATCH, {}))
        app._on_event(Event("message.delta", WATCH, {"text": "Hi from the child"}))
        app._on_event(Event("message.complete", WATCH, {"text": "Hi from the child"}))
        assert app.viewing is not None
        self.assertIn("reply:Hi from the child", texts(app.viewing.transcript))
        self.assertEqual(app.transcript.blocks, main_before)
        self.assertNotIn("Hi from the child", "".join(texts(app.transcript)))

    def test_a_main_delta_while_viewing_shows_after_leaving(self) -> None:
        app, _client, _now = viewing()
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("message.delta", SID, {"text": "main keeps going"}))
        self.assertNotIn("main keeps going", "\n".join(drawn(app)))
        app._on_input(Key(ESCAPE))
        self.assertIn("main keeps going", "\n".join(drawn(app)))

    def test_watch_events_after_leaving_are_dropped(self) -> None:
        app, _client, _now = viewing()
        app._on_input(Key(ESCAPE))
        main_before = list(app.transcript.blocks)
        app._on_event(Event("message.delta", WATCH, {"text": "late"}))
        self.assertEqual(app.transcript.blocks, main_before)

    def test_parent_frames_drive_the_views_working_row(self) -> None:
        app, _client, _now = viewing(result=lazy_answer([BRIEF], running=True))
        self.assertTrue(any("Working…" in line for line in drawn(app)))
        agent_event(app, "complete", FIRST, status="completed", summary="done")
        assert app.viewing is not None
        self.assertFalse(app.viewing.running)
        self.assertFalse(any("Working…" in line for line in drawn(app)))

    def test_the_shared_gateway_polls_forward_at_most_every_second_while_running(self) -> None:
        app, client, now = viewing(shared=True, result=rows_answer([BRIEF], cursor="c1"))
        before = len(client.named("session.transcript"))
        app._poll_view_when_due()
        self.assertEqual(len(client.named("session.transcript")), before)  # not yet a second
        now[0] = POLL_SECONDS
        app._poll_view_when_due()
        self.assertEqual(client.named("session.transcript")[-1]["cursor"], "c1")
        app._on_response(Response(call_id(client, "session.transcript"),
                                  rows_answer([TOOL, REPLY], running=False, reset=False, cursor="c2"), None))
        assert app.viewing is not None
        self.assertEqual(texts(app.viewing.transcript)[-2:], ["tools", f"reply:{REPLY['text']}"])
        app._poll_view_when_due()  # it ended with rows on that page: the next page goes at once (R1 D7)
        self.assertEqual(client.named("session.transcript")[-1]["cursor"], "c2")
        app._on_response(Response(call_id(client, "session.transcript"),
                                  rows_answer([], running=False, reset=False, cursor="c2"), None))
        now[0] = 10 * POLL_SECONDS
        count = len(client.named("session.transcript"))
        app._poll_view_when_due()
        self.assertEqual(len(client.named("session.transcript")), count)  # an empty page: caught up, no more reads

    def test_a_poll_answer_for_a_view_since_left_draws_nothing(self) -> None:
        app, client, now = viewing(shared=True)
        now[0] = POLL_SECONDS
        app._poll_view_when_due()
        late = call_id(client, "session.transcript")
        app._on_input(Key(ESCAPE))
        main_before = list(app.transcript.blocks)
        app._on_response(Response(late, rows_answer([REPLY], reset=False), None))
        self.assertEqual(app.transcript.blocks, main_before)


class ComposerTests(unittest.TestCase):
    def test_enter_while_it_runs_steers_that_subagent(self) -> None:
        app, client, _now = viewing()
        type_text(app, "also say hi")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[-1], ("subagent.steer", {"session_id": SID, "subagent_id": FIRST,
                                                              "text": "also say hi"}))
        answer(app, client, {"status": "queued"})
        assert app.viewing is not None
        self.assertIn("steer:also say hi", texts(app.viewing.transcript))
        self.assertFalse(client.named("prompt.submit"))

    def test_after_the_end_on_stdio_a_message_continues_it_on_the_watch_sid(self) -> None:
        app, client, _now = viewing(result=lazy_answer([BRIEF, REPLY], running=False))
        type_text(app, "and now say bye")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": WATCH, "text": "and now say bye"}))
        self.assertFalse(client.named("subagent.steer"))
        assert app.viewing is not None
        self.assertIn("user:and now say bye", texts(app.viewing.transcript))

    def test_a_continue_refused_as_still_running_gives_the_text_back(self) -> None:
        app, client, _now = viewing(result=lazy_answer([BRIEF], running=False))
        type_text(app, "go on")
        app._on_input(Key(ENTER))
        answer(app, client, error={"code": 4009, "message": "session busy"})
        self.assertEqual(app.composer.text, "go on")
        self.assertIsNone(app.exit_code)

    def test_after_the_end_on_the_shared_gateway_says_it_cannot_and_keeps_the_text(self) -> None:
        app, client, _now = viewing(shared=True, result=rows_answer([BRIEF, REPLY], running=False))
        type_text(app, "and now say bye")
        sent = len(client.calls)
        app._on_input(Key(ENTER))
        self.assertEqual(len(client.calls), sent)
        self.assertEqual(app.composer.text, "and now say bye")
        assert app.viewing is not None
        self.assertEqual(texts(app.viewing.transcript)[-1], f"notice:{UNSUPPORTED_LINE.format(name=NAME)}")

    def test_slash_commands_shell_lines_and_images_are_refused_with_the_text_kept(self) -> None:
        for typed in ("/help", "!ls"):
            with self.subTest(typed=typed):
                app, client, _now = viewing()
                sent = len(client.calls)
                type_text(app, typed)
                app._on_input(Key(ENTER))
                self.assertEqual(len(client.calls), sent)
                self.assertEqual(app.composer.text, typed)
                assert app.viewing is not None
                self.assertEqual(texts(app.viewing.transcript)[-1],
                                 f"notice:{REFUSED_WHILE_VIEWING.format(name=NAME)}")
        app, client, _now = viewing()
        sent = len(client.calls)
        image = Attachment("/tmp/a.png", "a.png", "1x1", label="[Image #1]")
        app._send_to_view("look at this [Image #1]", "", [image])
        self.assertEqual(len(client.calls), sent)
        self.assertIn("look at this", app.composer.text)

    def test_a_paste_is_typed_text_for_the_subagent(self) -> None:
        app, client, _now = viewing()
        app._on_input(Paste("hello agent"))
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[-1][0], "subagent.steer")


class LeavingTests(unittest.TestCase):
    def test_esc_goes_back_to_main_and_closes_the_watch(self) -> None:
        app, client, _now = viewing()
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.viewing)
        self.assertEqual(client.calls[-1], ("session.close", {"session_id": WATCH}))
        self.assertFalse(client.named("session.interrupt"))  # the main turn runs on: Esc only went back

    def test_esc_on_the_main_screen_still_stops_the_turn(self) -> None:
        app, client, _now = viewing()
        app._on_input(Key(ESCAPE))
        app._on_input(Key(ESCAPE))
        self.assertTrue(client.named("session.interrupt"))

    def test_ctrl_c_in_the_view_never_stops_the_main_turn(self) -> None:
        app, client, _now = viewing()
        app._on_input(Key(CHAR, "c", ctrl=True))
        self.assertFalse(client.named("session.interrupt"))
        self.assertIsNotNone(app.viewing)

    def test_esc_on_the_shared_gateway_closes_nothing(self) -> None:
        app, client, _now = viewing(shared=True)
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.viewing)
        self.assertFalse(client.named("session.close"))

    def test_main_and_enter_in_the_list_goes_back(self) -> None:
        app, client, _now = viewing()
        app._on_input(Key(DOWN))
        app.list_selected = MAIN_ID
        app._on_input(Key(ENTER))
        self.assertEqual((app.viewing, app.list_selected), (None, None))
        self.assertEqual(client.calls[-1], ("session.close", {"session_id": WATCH}))

    def test_a_session_switch_or_new_session_leaves_the_view_first(self) -> None:
        for method in ("session.create", "session.resume"):
            with self.subTest(method=method):
                app, client, _now = viewing()
                if method == "session.create":
                    app._new_session("")
                else:
                    app._switch_session("other-session")
                answer(app, client, {"session_id": "new-sid", "info": {}, "messages": []})
                self.assertIsNone(app.viewing)
                closed = [params["session_id"] for name, params in client.calls if name == "session.close"]
                self.assertIn(WATCH, closed)

    def test_an_open_answered_after_esc_is_dropped_and_its_watch_closed(self) -> None:
        app, client, _now = entered()
        app._on_input(Key(ESCAPE))  # the list gives the keys back
        app._on_input(Key(ESCAPE))  # and the open still out is dropped
        answer(app, client, lazy_answer([BRIEF]))
        self.assertIsNone(app.viewing)
        self.assertEqual(client.calls[-1], ("session.close", {"session_id": WATCH}))

    def test_a_gateway_respawn_leaves_the_view(self) -> None:
        app, old, _spawner, _now = crashing()
        relay(app, FRAMES[:6])  # `crashing` builds its own app: the real opener, as in every app
        app._open_agent(FIRST)
        app._on_response(Response(len(old.calls), lazy_answer([BRIEF]), None))
        self.assertIsNotNone(app.viewing)
        crash(app, old)
        self.assertEqual((app.viewing, app.view_opening), (None, None))


class ListMarkTests(unittest.TestCase):
    def test_the_viewed_row_is_marked_and_the_others_and_main_are_hollow(self) -> None:
        app, _client, _now = viewing()
        app._on_input(Key(DOWN))  # the list takes the keys again
        drawn(app)
        rows = app._agent_view(100, 30)
        marks = {row_id: next(span.text for span in line if span.text in (VIEWED_MARK, AWAY_MARK))
                 if any(span.text in (VIEWED_MARK, AWAY_MARK) for span in line) else line[0].text[2:3]
                 for line, row_id in zip(rows, app.listed)}
        self.assertEqual(marks, {MAIN_ID: AWAY_MARK, FIRST: VIEWED_MARK, SECOND: AWAY_MARK})

    def test_with_the_list_closed_the_viewed_row_keeps_the_pointer(self) -> None:
        app, _client, _now = viewing()
        texts_ = ["".join(span.text for span in line) for line in app._agent_view(100, 30)]
        self.assertTrue(texts_[1].startswith(f"❯ {VIEWED_MARK} "))
        self.assertTrue(texts_[0].startswith(f"  {AWAY_MARK} "))

    def test_mark_rows_leaves_a_row_it_does_not_know(self) -> None:
        line = (Span("x"),)
        self.assertEqual(mark_rows([line], [FIRST], FIRST, None, DEFAULT_THEME), [line])

    def test_the_list_hint_says_view_stop_and_back(self) -> None:
        self.assertEqual(AGENT_LIST_HINTS[0], "↑↓ select · ⏎ view · x stop · s steer · esc back")
        self.assertTrue(all("esc back" in hint for hint in AGENT_LIST_HINTS))


class RuleLabelTests(unittest.TestCase):
    def test_the_label_ends_the_rule_and_is_cut_like_other_labels(self) -> None:
        name = "a very long subagent name that goes on and on and on past the edge"
        for cols in (60, 100, 200):
            with self.subTest(cols=cols):
                text = "".join(span.text for span in labelled_rule(cols, name, DEFAULT_THEME))
                self.assertEqual(cell_width(text), cols)
                self.assertTrue(text.startswith("─" * 8) and text.endswith(" ─"))
                if cols < 80:
                    self.assertIn("…", text)
                else:
                    self.assertIn(name, text)

    def test_a_narrow_rule_drops_the_label(self) -> None:
        text = "".join(span.text for span in labelled_rule(10, "name", DEFAULT_THEME))
        self.assertEqual(text, "─" * 10)


class StateTests(unittest.TestCase):
    def test_send_kind(self) -> None:
        view = SubagentView(FIRST, NAME, SID, view_state.WIRE_WATCH, Transcript(), watch_sid=WATCH, running=True)
        self.assertEqual(view_state.send_kind(view), view_state.SEND_STEER)
        view.running = False
        self.assertEqual(view_state.send_kind(view), view_state.SEND_CONTINUE)
        view.turn_running = True
        self.assertEqual(view_state.send_kind(view), view_state.SEND_WATCH_STEER)
        view = SubagentView(FIRST, NAME, SID, view_state.WIRE_POLL, Transcript(), running=False)
        self.assertEqual(view_state.send_kind(view), view_state.SEND_UNSUPPORTED)

    def test_wire_for(self) -> None:
        self.assertEqual(view_state.wire_for(True), view_state.WIRE_POLL)
        self.assertEqual(view_state.wire_for(False), view_state.WIRE_WATCH)

    def test_non_message_rows_are_not_drawn(self) -> None:
        self.assertEqual(view_state.message_rows([{"role": "user", "row_kind": "marker"}, BRIEF]), [BRIEF])

    def test_steers_and_the_brief_sent_from_the_view_are_not_drawn_twice(self) -> None:
        view = SubagentView(FIRST, NAME, SID, view_state.WIRE_POLL, Transcript(), brief_pending=True,
                            sent_steers=["also say hi"])
        self.assertEqual(view_state.unseen_rows(view, [BRIEF, STEER_ROW, REPLY]), ([REPLY], GOAL))
        self.assertEqual(view.sent_steers, [])


if __name__ == "__main__":
    unittest.main()
