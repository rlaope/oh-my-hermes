"""The subagent session view's fix round (R1): each test replays a scenario the first review reproduced and pins the
fixed outcome, one class per contract decision (D1-D14, NB1-NB3).

Setups follow the review's repro scripts; the helpers are `test_tui_agent_session_view`'s.
"""

from __future__ import annotations

import unittest

from test_tui_agent_session_view import BRIEF, FIRST, SECOND, entered, lazy_answer, viewing
from test_tui_modes import SID, answer, call_id, queue, type_text
from omh.tui import app as app_module
from omh.tui.gateway import Event, Response
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


if __name__ == "__main__":
    unittest.main()
