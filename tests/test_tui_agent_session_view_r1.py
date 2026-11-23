"""The subagent session view's fix round (R1): each test replays a scenario the first review reproduced and pins the
fixed outcome, one class per contract decision (D1-D14, NB1-NB3).

Setups follow the review's repro scripts; the helpers are `test_tui_agent_session_view`'s.
"""

from __future__ import annotations

import unittest

from test_tui_agent_session_view import (
    BRIEF, FIRST, GOAL, REPLY, SECOND, STEER_ROW, TOOL, WATCH, entered, lazy_answer, rows_answer, texts, viewing,
)
from test_tui_agent_view import agent_event
from test_tui_modes import SID, answer, call_id, drawn, queue, type_text
from omh.tui import app as app_module
from omh.tui import subagent_session as view_state
from omh.tui.gateway import Event, Response, ServerRequest
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, UP, Key


def submit(app, text: str) -> None:
    type_text(app, text)
    app._on_input(Key(ENTER))


class OwnershipTests(unittest.TestCase):
    """D1: every piece of input state has one owner, main or the open view."""

    def test_a_draft_typed_while_the_open_is_out_stays_mains_and_the_view_starts_empty(self) -> None:
        app, client, _ = entered()
        app._on_input(Key(ESCAPE))  # the list closes; the open is still out and the composer is main's
        type_text(app, "main-only draft")
        answer(app, client, lazy_answer([BRIEF]))
        assert app.viewing is not None and app.viewing.main_draft is not None
        self.assertEqual((app.composer.text, app.viewing.main_draft.text), ("", "main-only draft"))
        app._on_input(Key(ENTER))
        self.assertEqual(client.named("subagent.steer"), [], "main's draft never goes to the child")

    def test_leaving_puts_mains_draft_back_and_keeps_the_childs_for_its_next_open(self) -> None:
        app, client, _ = entered()
        app._on_input(Key(ESCAPE))
        type_text(app, "main-only draft")
        answer(app, client, lazy_answer([BRIEF]))
        type_text(app, "child-only draft")
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.viewing)
        self.assertEqual((app.composer.text, app.child_drafts[FIRST].text), ("main-only draft", "child-only draft"))
        app._open_agent(FIRST)
        answer(app, client, lazy_answer([BRIEF]))
        self.assertEqual(app.composer.text, "child-only draft")
        self.assertNotIn(FIRST, app.child_drafts)

    def test_a_kept_child_draft_goes_with_its_agent_when_the_roster_drops_it(self) -> None:
        app, _client, _ = viewing()
        type_text(app, "child-only draft")
        app._on_input(Key(ESCAPE))
        self.assertIn(FIRST, app.child_drafts)
        app._clear_roster()
        self.assertEqual(app.child_drafts, {})

    def test_up_in_the_view_leaves_mains_queue_alone(self) -> None:
        app, client, _ = viewing()
        queue(app, "queued for main")
        app._on_input(Key(UP))
        app._on_input(Key(ENTER))
        self.assertEqual((len(app.queued), client.named("subagent.steer")), (1, []))

    def test_ctrl_enter_in_the_view_never_sends_mains_queued_head(self) -> None:
        app, client, _ = viewing()
        queue(app, "queued for main")
        app._on_input(Key(ENTER, ctrl=True))
        app._on_input(Key(CHAR, "j", ctrl=True))
        self.assertEqual(client.named("session.redirect") + client.named("session.steer"), [])
        self.assertEqual(len(app.queued), 1)

    def test_mains_auto_continue_reads_mains_draft_not_the_views(self) -> None:
        app, client, now = viewing()
        app.turn_pending = True
        app._on_event(Event("message.start", SID, {}))
        type_text(app, "child-only draft")
        now[0] = 20
        app._on_event(Event("message.complete", SID, {"text": "main reply", "status": "interrupted"}))
        now[0] += app_module.AUTO_CONTINUE_SECONDS + 1
        app._auto_continue_when_due()
        self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": "continue"}])
        self.assertEqual(app.composer.text, "child-only draft")


class OriginTests(unittest.TestCase):
    """D2: a late answer gives its text back to where it was typed, never to main's draft."""

    def test_a_steer_refused_after_a_session_switch_never_lands_in_the_new_mains_draft(self) -> None:
        app, client, _ = viewing()
        submit(app, "for first child only")
        late = call_id(client, "subagent.steer")
        app._on_input(Key(ESCAPE))
        app._switch_session("different-stored-session")
        answer(app, client, {"session_id": "other-live", "messages": [], "info": {}})
        type_text(app, "new main draft")
        app._on_response(Response(late, {"status": "rejected"}, None))
        self.assertEqual(app.composer.text, "new main draft")

    def test_a_steer_refused_while_its_view_is_on_screen_comes_back_to_that_views_composer(self) -> None:
        app, client, _ = entered()
        app._on_input(Key(ESCAPE))
        type_text(app, "main draft")
        answer(app, client, lazy_answer([BRIEF]))
        submit(app, "for the child")
        answer(app, client, {"status": "rejected"})
        assert app.viewing is not None and app.viewing.main_draft is not None
        self.assertEqual((app.composer.text, app.viewing.main_draft.text), ("for the child", "main draft"))

    def test_a_steer_refused_after_its_view_was_left_goes_to_the_agents_kept_draft(self) -> None:
        app, client, _ = viewing()
        submit(app, "for the child")
        late = call_id(client, "subagent.steer")
        app._on_input(Key(ESCAPE))
        type_text(app, "main draft")
        app._on_response(Response(late, {"status": "rejected"}, None))
        self.assertEqual((app.composer.text, app.child_drafts[FIRST].text), ("main draft", "for the child"))

    def test_mains_unanswered_steer_while_a_view_is_shown_goes_to_mains_set_aside_draft(self) -> None:
        app, client, now = entered()
        app._on_input(Key(ESCAPE))
        app._on_event(Event("message.start", SID, {}))
        submit(app, "steer main")  # main's turn runs: Enter steers it
        self.assertEqual(client.calls[-1], ("session.redirect", {"session_id": SID, "text": "steer main"}))
        app._on_response(Response(call_id(client, "session.resume"), lazy_answer([BRIEF]), None))
        now[0] = app_module.CALL_ANSWER_SECONDS + 1
        app._expire_calls()
        assert app.viewing is not None and app.viewing.main_draft is not None
        self.assertEqual((app.composer.text, app.viewing.main_draft.text), ("", "steer main"))


class ExplicitTargetTests(unittest.TestCase):
    """D3: `s` on a list row steers that agent even while another agent's view is shown."""

    def test_s_on_another_row_steers_that_agent_not_the_one_on_screen(self) -> None:
        app, client, _ = viewing()
        app._on_input(Key(DOWN))
        app._on_input(Key(DOWN))
        self.assertEqual(app.list_selected, SECOND)
        app._on_input(Key(CHAR, "s"))
        submit(app, "for second")
        self.assertEqual([call["subagent_id"] for call in client.named("subagent.steer")], [SECOND])


def approval(origin: str) -> ServerRequest:
    return ServerRequest("approval", "approval", {"session_id": origin, "command": "printf ok",
                                                  "description": "approval marker", "choices": ["once", "session", "deny"]})


class StopOwnerTests(unittest.TestCase):
    """D4: a stop stays with its owner; main's questions are answered on main's screen; main's stop keys do nothing
    in a view."""

    def test_a_continued_childs_approval_denied_interrupts_that_child_not_main(self) -> None:
        app, client, now = viewing(result=lazy_answer([BRIEF], running=False))
        app._on_event(Event("message.start", WATCH, {}))  # a turn continued on the watch sid
        app._on_server_request(approval(WATCH))
        self.assertIsNotNone(app.viewing, "the child's own question stays in its view")
        now[0] += 1
        app._on_input(Key(CHAR, "c", ctrl=True))
        self.assertEqual(client.answers[-1][1]["result"]["choice"], "deny")
        self.assertEqual(client.named("session.interrupt"), [{"session_id": WATCH}])

    def test_a_main_approval_leaves_the_view_first_with_the_drafts_restored(self) -> None:
        app, client, now = entered()
        app._on_input(Key(ESCAPE))
        type_text(app, "main draft")
        answer(app, client, lazy_answer([BRIEF]))
        type_text(app, "child draft")
        app._on_server_request(approval(SID))
        self.assertIsNone(app.viewing)
        self.assertEqual(app.child_drafts[FIRST].text, "child draft")
        now[0] += 1
        app._on_input(Key(CHAR, "c", ctrl=True))  # denied on main's screen: main's turn stops
        self.assertEqual(client.named("session.interrupt"), [{"session_id": SID}])
        self.assertEqual(app.composer.text, "main draft")

    def test_vim_space_c_does_nothing_in_a_view(self) -> None:
        app, client, _ = viewing()
        app.composer.set_vim(True)
        app._on_input(Key(ESCAPE))  # INSERT's first Esc leaves INSERT (NB1)
        self.assertIsNotNone(app.viewing)
        app._on_input(Key(CHAR, " "))
        app._on_input(Key(CHAR, "c"))
        self.assertEqual(client.named("session.interrupt"), [])
        self.assertIsNotNone(app.viewing)


class OpenIntentTests(unittest.TestCase):
    """D5: each open is one intent; only the latest open's answer may show a view."""

    def test_a_second_enter_on_the_agent_whose_open_is_out_sends_nothing(self) -> None:
        app, client, _ = entered()
        app._on_input(Key(ENTER))
        self.assertEqual(len(client.named("session.resume")), 1)
        answer(app, client, lazy_answer([BRIEF]))
        self.assertEqual((app.viewing.watch_sid, client.named("session.close")), (WATCH, []))

    def test_a_stale_open_answer_reusing_the_shown_watch_never_closes_it(self) -> None:
        app, client, _ = entered()
        old = call_id(client, "session.resume")
        app._on_input(Key(ESCAPE))  # the list closes
        app._on_input(Key(ESCAPE))  # the open is cancelled
        app._open_agent(FIRST)
        app._on_response(Response(call_id(client, "session.resume"), lazy_answer([BRIEF]), None))
        app._on_response(Response(old, lazy_answer([BRIEF]), None))  # Hermes reuses the live watch sid
        self.assertEqual((app.viewing.watch_sid, client.named("session.close")), (WATCH, []))

    def test_a_stale_open_answer_on_the_shared_gateway_never_replaces_the_latest(self) -> None:
        app, client, _ = entered(shared=True)
        old = call_id(client, "session.transcript")
        app._on_input(Key(ESCAPE))
        app._on_input(Key(ESCAPE))
        app._open_agent(FIRST)
        new = call_id(client, "session.transcript")
        app._on_response(Response(old, rows_answer([BRIEF, {"role": "assistant", "text": "old snapshot"}], cursor="old"),
                                  None))
        self.assertIsNone(app.viewing, "the cancelled open shows nothing")
        app._on_response(Response(new, rows_answer([BRIEF, {"role": "assistant", "text": "new snapshot"}], cursor="new"),
                                  None))
        self.assertEqual((app.viewing.cursor, texts(app.viewing.transcript)[-1]), ("new", "reply:new snapshot"))

    def test_the_main_row_cancels_an_open_still_out(self) -> None:
        app, client, _ = entered()
        app._on_input(Key(UP))
        app._on_input(Key(ENTER))  # main's row, before the open answered
        answer(app, client, lazy_answer([BRIEF]))
        self.assertIsNone(app.viewing)
        self.assertEqual(client.named("session.close"), [{"session_id": WATCH}], "the watch no view owns is closed")

    def test_a_session_switch_cancels_an_open_still_out(self) -> None:
        app, client, _ = entered()
        opened = call_id(client, "session.resume")
        app._on_input(Key(ESCAPE))
        app._switch_session("different-stored-session")
        app._on_response(Response(opened, lazy_answer([BRIEF]), None))
        self.assertIsNone(app.viewing)


class ReadFenceTests(unittest.TestCase):
    """D6: one attached read in flight per view; only the latest, asked from the view's cursor, applies."""

    def test_a_completion_while_a_read_is_out_sends_no_second_read(self) -> None:
        app, client, now = viewing(shared=True)
        now[0] = 1
        app._poll_view_when_due()
        now[0] = 1.1
        agent_event(app, "complete", FIRST, status="completed", summary="done")
        app._poll_view_when_due()
        self.assertEqual(len(client.named("session.transcript")), 2, "the open's read and the one poll")

    def test_an_older_answer_never_duplicates_rows_rolls_the_cursor_back_or_marks_the_child_running(self) -> None:
        app, client, now = viewing(shared=True)
        now[0] = 1
        app._poll_view_when_due()
        older = call_id(client, "session.transcript")
        now[0] = 1 + view_state.POLL_ANSWER_SECONDS
        app._poll_view_when_due()  # the first went unanswered: forgotten, the next goes
        newer = call_id(client, "session.transcript")
        self.assertNotIn(older, app.pending)
        app._on_response(Response(newer, rows_answer([REPLY], running=False, reset=False, cursor="final"), None))
        app._on_response(Response(older, rows_answer([REPLY], running=True, reset=False, cursor="earlier"), None))
        assert app.viewing is not None
        self.assertEqual((app.viewing.running, app.viewing.cursor), (False, "final"))
        self.assertEqual(texts(app.viewing.transcript).count(f"reply:{REPLY['text']}"), 1)

    def test_a_completion_schedules_one_read_at_the_paced_second(self) -> None:
        app, client, now = viewing(shared=True)
        before = len(client.named("session.transcript"))
        now[0] = 0.2
        agent_event(app, "complete", FIRST, status="completed", summary="done")
        app._poll_view_when_due()
        self.assertEqual(len(client.named("session.transcript")), before, "not before the second is up")
        now[0] = 1
        app._poll_view_when_due()
        self.assertEqual(len(client.named("session.transcript")), before + 1)


class CatchUpTests(unittest.TestCase):
    """D7: caught up means an empty page."""

    def test_a_finished_child_with_a_full_first_page_is_read_until_an_empty_page(self) -> None:
        page = [BRIEF, *[{"role": "assistant", "text": f"chunk {i}"} for i in range(199)]]
        app, client, now = viewing(shared=True, result=rows_answer(page, running=False, cursor="page-2"))
        app._poll_view_when_due()  # at once: a page that brought rows is followed by the next
        self.assertEqual(client.named("session.transcript")[-1].get("cursor"), "page-2")
        answer(app, client, rows_answer([{"role": "assistant", "text": "the final reply"}], running=False, reset=False,
                                        cursor="page-3"))
        app._poll_view_when_due()
        self.assertEqual(client.named("session.transcript")[-1].get("cursor"), "page-3")
        answer(app, client, rows_answer([], running=False, reset=False, cursor="page-3"))
        count = len(client.named("session.transcript"))
        now[0] = 100
        app._poll_view_when_due()
        assert app.viewing is not None
        self.assertEqual(len(client.named("session.transcript")), count, "an empty page: caught up")
        self.assertEqual(texts(app.viewing.transcript)[-1], "reply:the final reply")

    def test_catch_up_stops_after_its_page_cap(self) -> None:
        app, client, now = viewing(shared=True, result=rows_answer([BRIEF], running=False, cursor="p0"))
        for page in range(view_state.CATCH_UP_PAGES + 5):
            app._poll_view_when_due()
            if app.viewing.poll_open:
                answer(app, client, rows_answer([{"role": "assistant", "text": f"p{page}"}], running=False, reset=False,
                                                cursor=f"p{page + 1}"))
        self.assertEqual(len(client.named("session.transcript")), view_state.CATCH_UP_PAGES)


class SameTextTests(unittest.TestCase):
    """D8: the same text however the view was read."""

    def test_the_real_brief_replaces_the_goal_placeholder_in_place(self) -> None:
        app, client, now = viewing(shared=True, result=rows_answer([]), rows=35, cols=100)
        assert app.viewing is not None
        drawn(app)  # the goal is on screen as the brief
        now[0] = 1
        app._poll_view_when_due()
        brief = {**BRIEF, "text": GOAL + "\n\nUse the terminal toolset only."}
        answer(app, client, rows_answer([brief, TOOL], reset=False, cursor="c2"))
        self.assertEqual(texts(app.viewing.transcript), ["notice:› From main", f"user:{brief['text']}", "tools"])
        self.assertIn("Use the terminal toolset only.", "\n".join(drawn(app)))

    def test_a_reset_rebuilds_from_rows_and_keeps_the_stored_steer(self) -> None:
        app, client, now = viewing(shared=True)
        submit(app, STEER_ROW["text"])
        answer(app, client, {"status": "queued"})
        now[0] = 1
        app._poll_view_when_due()
        answer(app, client, rows_answer([BRIEF, STEER_ROW, REPLY], reset=True, running=False))
        assert app.viewing is not None
        self.assertEqual(texts(app.viewing.transcript),
                         ["notice:› From main", f"user:{GOAL}", f"user:{STEER_ROW['text']}", f"reply:{REPLY['text']}"])


if __name__ == "__main__":
    unittest.main()
