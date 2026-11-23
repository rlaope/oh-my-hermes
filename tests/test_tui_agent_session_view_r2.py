"""The subagent session view's last fix round (R2). Each test replays a scenario from the second review's repros
(`ownership_edges.py`, `read_edges.py`) and pins the fixed outcome. There is one class per contract item (E1-E5,
F1-F4), plus regression pins for what 879969ccd already got right.

The helpers are `test_tui_agent_session_view`'s.
"""

from __future__ import annotations

import unittest
from unittest import mock

from test_tui_agent_session_view import (
    BRIEF, FIRST, REPLY, SECOND, WATCH, entered, lazy_answer, rows_answer, texts, viewing,
)
from test_tui_agent_view import agent_event
from test_tui_modes import SID, answer, call_id, drawn, type_text
from omh.tui import app as app_module
from omh.tui import subagent_session as view_state
from omh.tui.gateway import Event, Response, ServerRequest
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, Key, Paste


def press(app, *keys: str) -> None:
    for key in keys:
        app._on_input(Key(key))


def submit(app, text: str) -> None:
    type_text(app, text)
    app._on_input(Key(ENTER))


def sends(client) -> list[tuple[str, dict]]:
    names = ("subagent.steer", "session.redirect", "session.steer", "prompt.submit", "shell.exec")
    return [(method, body) for method, body in client.calls if method in names]


def pick_second(app) -> None:
    press(app, DOWN, DOWN)
    assert app.list_selected == SECOND
    app._on_input(Key(CHAR, "s"))
    assert app.agent_steer == SECOND


class IntakeOwnerTests(unittest.TestCase):
    """E1 (review2 B1): every intake has an owner; holds, give-backs and main recovery read only that owner's."""

    def test_a_main_paste_never_rides_a_child_send(self) -> None:
        app, client, _ = entered()
        press(app, ESCAPE)
        app._on_input(Paste("/tmp/main-only-notes.txt"))
        paste = call_id(client, "input.detect_drop")
        app._on_response(Response(call_id(client, "session.resume"), lazy_answer([BRIEF]), None))
        submit(app, "child says hello ")
        self.assertEqual(client.named("subagent.steer"),
                         [{"session_id": SID, "subagent_id": FIRST, "text": "child says hello "}])
        app._on_response(Response(paste, {"matched": False}, None))
        self.assertNotIn("main-only-notes", repr(client.named("subagent.steer")))
        assert app.viewing is not None and app.viewing.main_draft is not None
        self.assertIn("/tmp/main-only-notes.txt", app.viewing.main_draft.text)  # main's paste lands in main's draft

    def test_a_child_paste_never_rides_a_main_send(self) -> None:
        app, client, _ = viewing()
        app._on_input(Paste("/tmp/child-only-notes.txt"))
        paste = call_id(client, "input.detect_drop")
        press(app, ESCAPE)
        submit(app, "main says hello ")
        app._on_response(Response(paste, {"matched": False}, None))
        self.assertNotIn("child-only-notes", repr(sends(client)))
        self.assertFalse(any("child-only-notes" in line.text for line in app.queued))
        self.assertIn("/tmp/child-only-notes.txt", app.child_drafts[FIRST].text)  # back with its own agent

    def test_a_child_enter_held_for_its_paste_leaves_mains_auto_continue_armed(self) -> None:
        app, client, now = viewing()
        app.turn_pending = True
        app._on_event(Event("message.start", SID, {}))
        now[0] = 20
        app._on_event(Event("message.complete", SID, {"text": "main interrupted", "status": "interrupted"}))
        self.assertIsNotNone(app.auto_continue)
        app._on_input(Paste("/tmp/child-pending.txt"))
        paste = call_id(client, "input.detect_drop")
        submit(app, "child pending ")
        self.assertEqual(len(app.held_submits), 1)
        self.assertIsNotNone(app.auto_continue, "a child's held submit is not main's")
        now[0] += app_module.AUTO_CONTINUE_SECONDS + 1
        app._auto_continue_when_due()
        self.assertNotIn(app_module.AUTO_CONTINUE_HELD_NOTICE.split("{")[0], " ".join(texts(app.transcript)))
        app._on_response(Response(paste, {"matched": False}, None))  # Hermes stages per session: a prompt waits it out
        self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": "continue"}])
        self.assertEqual(client.named("subagent.steer")[-1]["text"], "child pending /tmp/child-pending.txt")

    def test_a_views_intake_goes_with_its_agent_when_the_roster_drops_it(self) -> None:
        app, client, _ = viewing()
        app._on_input(Paste("/tmp/child-image.png"))
        paste = call_id(client, "input.detect_drop")
        press(app, ESCAPE)
        del app.roster.agents[FIRST]
        app._forget_agents(frozenset({FIRST}))
        self.assertEqual([intake.owner for intake in app.intakes], [])
        with mock.patch.object(app_module, "read_image", return_value=b"fixture"):
            app._on_response(Response(paste, {"matched": True, "is_image": True, "path": "/tmp/child-image.png"}, None))
        self.assertEqual(client.named("image.detach"), [{"session_id": SID, "path": "/tmp/child-image.png"}])
        self.assertEqual(app.composer.images, {}, "never into main's draft")


class ChildTextMergeTests(unittest.TestCase):
    """E2 (review2 B2): what is kept for a child is only ever added to; reopening moves it all into the composer."""

    def test_a_late_refusal_and_a_later_draft_both_survive_another_leave_and_reopen(self) -> None:
        app, client, _ = viewing()
        submit(app, "first rejected message")
        steer = call_id(client, "subagent.steer")
        press(app, ESCAPE)
        app._open_agent(FIRST)
        answer(app, client, lazy_answer([BRIEF]))
        app._on_response(Response(steer, {"status": "rejected"}, None))
        self.assertEqual(app.composer.text, "first rejected message")  # the view of A shown now takes it at once
        self.assertNotIn(FIRST, app.child_drafts)
        type_text(app, "second draft")
        press(app, ESCAPE)
        app._open_agent(FIRST)
        answer(app, client, lazy_answer([BRIEF]))
        self.assertIn("first rejected message", app.composer.text)
        self.assertIn("second draft", app.composer.text)
        self.assertNotIn(FIRST, app.child_drafts)

    def test_a_refusal_for_a_view_left_is_appended_to_the_draft_already_kept(self) -> None:
        app, client, _ = viewing()
        submit(app, "rejected later")
        steer = call_id(client, "subagent.steer")
        type_text(app, "kept draft")
        press(app, ESCAPE)
        app._on_response(Response(steer, {"status": "rejected"}, None))
        self.assertEqual(app.child_drafts[FIRST].text, "kept draft\nrejected later")


class DestinationTests(unittest.TestCase):
    """E3 (review2 B3): Enter decides the destination once; every child destination obeys the child's policy."""

    def test_a_shell_line_after_s_is_refused_not_run(self) -> None:
        app, client, _ = viewing(busy=False)
        pick_second(app)
        submit(app, "!printf child-marker")
        self.assertEqual(client.named("shell.exec"), [])
        self.assertEqual(sends(client), [])
        self.assertEqual(app.composer.text, "!printf child-marker")  # where it was typed

    def test_an_image_after_s_refuses_the_whole_prompt_and_stays_in_the_child_composer(self) -> None:
        app, client, _ = viewing()
        pick_second(app)
        app._on_input(Paste("/tmp/child-explicit-image.png"))
        paste = call_id(client, "input.detect_drop")
        submit(app, "do not send words without image")
        with mock.patch.object(app_module, "read_image", return_value=b"fixture"):
            app._on_response(Response(paste, {"matched": True, "is_image": True,
                                              "path": "/tmp/child-explicit-image.png"}, None))
        self.assertEqual(client.named("subagent.steer"), [])
        assert app.viewing is not None and app.viewing.main_draft is not None
        self.assertEqual(len(app.viewing.main_draft.images), 0, "nothing written into hidden main")
        self.assertEqual(len(app.composer.images), 1)
        self.assertIn("do not send words without image", app.composer.text)

    def test_esc_back_to_main_clears_an_s_armed_in_the_view(self) -> None:
        app, client, _ = entered()
        press(app, ESCAPE)
        type_text(app, "draft for main only")
        answer(app, client, lazy_answer([BRIEF]))
        pick_second(app)
        press(app, ESCAPE)
        self.assertIsNone(app.agent_steer)
        press(app, ENTER)
        self.assertEqual(client.named("subagent.steer"), [])
        self.assertEqual([line.text for line in app.queued], ["draft for main only"])  # main's, behind main's turn

    def test_a_held_explicit_steer_keeps_its_destination_past_a_main_turns_roster_clear(self) -> None:
        app, client, _ = viewing()
        pick_second(app)
        app._on_input(Paste("/tmp/delayed-explicit-steer.txt"))
        paste = call_id(client, "input.detect_drop")
        submit(app, "for second only ")
        app._clear_roster()  # what a queued main turn's prompt preparation does
        app._on_response(Response(paste, {"matched": False}, None))
        self.assertFalse(any("for second only" in line.text for line in app.queued), "never into main's queue")
        self.assertFalse(any("for second only" in body["text"] and not body.get("subagent_id")
                             for _method, body in sends(client)))
        self.assertIn("for second only /tmp/delayed-explicit-steer.txt", app.composer.text)  # back where typed

    def test_a_held_view_submit_whose_view_was_left_comes_back_to_its_composer_not_main(self) -> None:
        app, client, _ = viewing()
        app._on_input(Paste("/tmp/held-view.txt"))
        paste = call_id(client, "input.detect_drop")
        submit(app, "for the child ")
        press(app, ESCAPE)
        app._on_response(Response(paste, {"matched": False}, None))
        self.assertEqual(sends(client), [])
        self.assertEqual(app.queued, type(app.queued)())
        self.assertIn("for the child /tmp/held-view.txt", app.child_drafts[FIRST].text)


class CatchUpBoundaryTests(unittest.TestCase):
    """E4 (review2 B4): catch-up is judged after the end, on the wire's own rows."""

    def test_an_empty_read_sent_before_the_end_never_counts_as_caught_up(self) -> None:
        app, client, now = viewing(shared=True)
        now[0] = 1.0
        app._poll_view_when_due()
        read = call_id(client, "session.transcript")
        now[0] = 1.1
        agent_event(app, "complete", FIRST, status="completed", summary="done")
        app._on_response(Response(read, rows_answer([], running=True, reset=False, cursor="c1"), None))
        for t in (2.0, 12.0, 100.0):
            now[0] = t
            app._poll_view_when_due()
            if app.viewing.poll_open:
                final = call_id(client, "session.transcript")
                app._on_response(Response(final, rows_answer([REPLY], running=False, reset=False, cursor="final"),
                                          None))
        assert app.viewing is not None
        self.assertFalse(app.viewing.running)
        self.assertIn("reply:" + REPLY["text"], texts(app.viewing.transcript))
        self.assertGreaterEqual(len(client.named("session.transcript")), 3)

    def test_a_page_of_only_a_handoff_row_is_not_empty_and_its_cursor_is_followed(self) -> None:
        app, client, now = viewing(shared=True, result=rows_answer([BRIEF], running=False, cursor="handoff-next"))
        app._poll_view_when_due()
        result = rows_answer([], running=False, reset=False, cursor="reply-next")
        result["rows"] = [{"row_kind": "compaction", "role": "user", "text": "bounded handoff", "compacted_messages": 10}]
        answer(app, client, result)
        for t in (0, 2.0, 20.0):
            now[0] = t
            app._poll_view_when_due()
        cursors = [read.get("cursor") for read in client.named("session.transcript")]
        self.assertEqual(cursors[:3], [None, "handoff-next", "reply-next"])

    def test_caught_up_reads_the_wire_rows_not_the_drawn_ones(self) -> None:
        self.assertTrue(view_state.caught_up({"rows": []}))
        self.assertFalse(view_state.caught_up({"rows": [{"row_kind": "compaction"}]}))


class PostEndBudgetTests(unittest.TestCase):
    """E5 (review2 B5): each post-end read sent spends one of the 50, answered or not; then one dim line."""

    def test_unanswered_post_end_reads_stop_at_the_budget_with_one_line(self) -> None:
        app, client, now = viewing(shared=True, result=rows_answer([BRIEF], running=False, cursor="resume-here"))
        for step in range(80):
            now[0] = 1 + 10 * step
            app._poll_view_when_due()
        assert app.viewing is not None
        # The open's own read was one of the 50.
        self.assertEqual(len(client.named("session.transcript")), view_state.CATCH_UP_PAGES)
        line = "notice:" + view_state.READ_GAVE_UP.format(name=app.viewing.name)
        self.assertEqual(texts(app.viewing.transcript).count(line), 1)
        self.assertEqual(sum(call.method == "session.transcript" for call in app.pending.values()), 0)

    def test_the_boundary_doc_says_at_most_50_reads_after_it_ends(self) -> None:
        from pathlib import Path

        doc = (Path(__file__).resolve().parents[1] / "docs" / "OMH-TUI-BOUNDARY.md").read_text(encoding="utf-8")
        section = doc[doc.index("## Agent views"):]
        section = " ".join(section[:section.index("\n## ", 3)].split())
        self.assertIn("at most 50 reads after it ends", section)


class QuestionDuringOpenTests(unittest.TestCase):
    """F1 (review2 N3): a main question that opens while an open is pending cancels that open."""

    def test_a_main_clarify_during_a_pending_open_keeps_main_on_screen(self) -> None:
        app, client, _ = entered(rows=24, cols=100)
        opening = call_id(client, "session.resume")
        request = ServerRequest("main-clarify", "clarify",
                                {"session_id": SID, "questions": [{"qid": "q", "question": "MAIN QUESTION MARKER"}]})
        app._on_server_request(request)
        app._on_response(Response(opening, lazy_answer([BRIEF]), None))
        self.assertIsNone(app.viewing)
        self.assertEqual(client.named("session.close"), [{"session_id": WATCH}])
        self.assertIn("MAIN QUESTION MARKER", "\n".join(drawn(app)))


class LogFallbackTests(unittest.TestCase):
    """F2 (review2 N4): opening the log pager for any agent supersedes every pending open."""

    def test_a_fallback_log_pick_drops_an_older_pending_open(self) -> None:
        app, client, _ = entered()
        opening = call_id(client, "session.resume")
        app.roster.agents[SECOND].child_session_id = ""
        press(app, DOWN, ENTER)
        self.assertEqual(app.log_agent, SECOND)
        app._on_response(Response(opening, lazy_answer([BRIEF]), None))
        self.assertIsNone(app.viewing)
        press(app, ESCAPE)
        self.assertIsNone(app.viewing)
        self.assertNotIn("From main", "\n".join(drawn(app)))


class ChildTellTests(unittest.TestCase):
    """F3 (review2 N6): a child approval's tell follow-up goes to the session that asked."""

    def test_a_continued_childs_tell_goes_to_its_watch_sid_not_main(self) -> None:
        app, client, now = viewing(result=lazy_answer([BRIEF], running=False))
        submit(app, "continue child")
        answer(app, client, {"status": "streaming"})
        app._on_event(Event("message.start", WATCH, {}))
        app._on_server_request(ServerRequest("child-approval", "approval",
                                             {"session_id": WATCH, "command": "printf ok",
                                              "choices": ["once", "session", "deny"]}))
        now[0] += 1
        press(app, DOWN, DOWN, DOWN, ENTER)
        self.assertIsNotNone(app.tell_draft)
        submit(app, "alternate instructions for child")
        self.assertEqual(sends(client)[-1], ("session.redirect", {"session_id": WATCH,
                                                                  "text": "alternate instructions for child"}))
        self.assertFalse(any(body.get("session_id") == SID and "alternate" in body.get("text", "")
                             for _method, body in sends(client)))


    def test_the_boundary_doc_names_the_childs_tell_send(self) -> None:
        from pathlib import Path

        doc = (Path(__file__).resolve().parents[1] / "docs" / "OMH-TUI-BOUNDARY.md").read_text(encoding="utf-8")
        section = doc[doc.index("## Agent views"):]
        section = " ".join(section[:section.index("\n## ", 3)].split())
        self.assertIn("`session.redirect` on the watch session", section)


class StaleWatchTests(unittest.TestCase):
    """F4 (review2 N8): a stale open's watch sid that the newest open may own is not closed before that answer."""

    def test_a_stale_answer_first_with_the_shared_watch_sid_closes_nothing_the_newest_view_owns(self) -> None:
        app, client, _ = entered()
        old = call_id(client, "session.resume")
        press(app, ESCAPE, ESCAPE)
        app._open_agent(FIRST)
        new = call_id(client, "session.resume")
        app._on_response(Response(old, lazy_answer([BRIEF], running=False), None))
        self.assertEqual(client.named("session.close"), [], "decided at the newest answer, not before")
        app._on_response(Response(new, lazy_answer([BRIEF], running=False), None))
        assert app.viewing is not None
        self.assertEqual(app.viewing.watch_sid, WATCH)
        self.assertEqual(client.named("session.close"), [], "the shown view owns it")

    def test_a_stale_watch_the_newest_open_does_not_own_is_closed_at_its_answer(self) -> None:
        app, client, _ = entered()
        old = call_id(client, "session.resume")
        press(app, ESCAPE, ESCAPE)
        app._open_agent(FIRST)
        new = call_id(client, "session.resume")
        stale = {**lazy_answer([BRIEF], running=False), "session_id": "old-watch"}
        app._on_response(Response(old, stale, None))
        app._on_response(Response(new, lazy_answer([BRIEF], running=False), None))
        self.assertEqual(client.named("session.close"), [{"session_id": "old-watch"}])


class RegressionPinTests(unittest.TestCase):
    """What 879969ccd got right in review2's B1/B2/B3 scenarios still holds."""

    def test_the_childs_wire_text_carries_no_main_path(self) -> None:
        app, client, _ = entered()
        press(app, ESCAPE)
        app._on_input(Paste("/tmp/main-only-notes.txt"))
        app._on_response(Response(call_id(client, "session.resume"), lazy_answer([BRIEF]), None))
        submit(app, "child says hello ")
        self.assertEqual([body["text"] for body in client.named("subagent.steer")], ["child says hello "])

    def test_rejected_text_is_kept_through_a_reopen(self) -> None:
        app, client, _ = viewing()
        submit(app, "first rejected message")
        steer = call_id(client, "subagent.steer")
        press(app, ESCAPE)
        app._on_response(Response(steer, {"status": "rejected"}, None))
        app._open_agent(FIRST)
        answer(app, client, lazy_answer([BRIEF]))
        self.assertIn("first rejected message", app.composer.text)

    def test_a_shell_line_from_s_is_refused(self) -> None:
        app, client, _ = viewing(busy=False)
        pick_second(app)
        submit(app, "!printf child-marker")
        self.assertEqual(client.named("shell.exec"), [])


if __name__ == "__main__":
    unittest.main()
