"""The subagent session view's parent fix round (R3), after the final review: three narrow variants of classes R1/R2
fixed. Each test replays a scenario from the final review's repros (`scratch/subview/review3/end_during_open.py`,
`tell_after_leave.py`, `prune_live_intake.py`) and pins the fixed outcome.

The helpers are `test_tui_agent_session_view`'s and `test_tui_agent_session_view_r2`'s.
"""

from __future__ import annotations

import unittest
from unittest import mock

from test_tui_agent_session_view import BRIEF, FIRST, WATCH, entered, lazy_answer, rows_answer, texts, viewing
from test_tui_agent_session_view_r2 import press, sends, submit
from test_tui_agent_view import agent_event
from test_tui_modes import SID, answer, call_id
from omh.tui import app as app_module
from omh.tui.gateway import Event, Response, ServerRequest
from omh.tui.keys import DOWN, ENTER, ESCAPE, Paste


class EndDuringOpenTests(unittest.TestCase):
    """R1-D6 / R2-E4-E5: a child whose end the roster already holds stays ended, whatever the open's read says."""

    def test_an_end_seen_while_the_open_read_is_out_is_kept_and_the_reads_stay_bounded(self) -> None:
        app, client, now = entered(shared=True)
        first = call_id(client, "session.transcript")
        now[0] = 0.1
        agent_event(app, "complete", FIRST, status="completed", summary="done")
        now[0] = 0.2
        # The host sampled `running` before it delivered the end: the open's answer still says running.
        app._on_response(Response(first, rows_answer([BRIEF], running=True), None))
        assert app.viewing is not None
        self.assertFalse(app.viewing.running, "the roster's end wins over the open read's stale `running`")
        for i in range(80):
            now[0] = 1.2 + 11 * i
            app._poll_view_when_due()
        reads = len(client.named("session.transcript"))
        self.assertLessEqual(reads, 51, "the open's read plus at most 50 after the end")
        self.assertTrue(any("Could not read the rest" in line for line in texts(app.viewing.transcript)))

    def test_a_child_still_running_at_the_open_keeps_running(self) -> None:
        app, client, _ = entered(shared=True)
        answer(app, client, rows_answer([BRIEF], running=True))
        assert app.viewing is not None
        self.assertTrue(app.viewing.running)


def _child_tell(app, client, now) -> None:
    submit(app, "continue child")
    answer(app, client, {"status": "streaming"})
    app._on_event(Event("message.start", WATCH, {}))
    app._on_server_request(ServerRequest("child-approval", "approval",
                                         {"session_id": WATCH, "command": "printf ok",
                                          "choices": ["once", "session", "deny"]}))
    now[0] += 1
    press(app, DOWN, DOWN, DOWN, ENTER)
    assert app.tell_draft is not None


class TellLeavesWithItsViewTests(unittest.TestCase):
    """R2-F3 / D4: a child approval's tell field belongs to that child's view and goes with it."""

    def test_esc_out_of_the_view_ends_the_childs_tell_and_keeps_its_text_for_the_child(self) -> None:
        app, client, now = viewing(result=lazy_answer([BRIEF], running=False))
        _child_tell(app, client, now)
        app._on_input(Paste("child-only alternative"))
        press(app, ESCAPE)
        self.assertIsNone(app.viewing)
        self.assertIsNone(app.tell_draft, "the child's tell field leaves with its view")
        self.assertEqual(app.tell_owner, "")
        self.assertEqual(app.composer.text, "", "main's composer is main's draft, not the child's tell text")
        press(app, ENTER)
        self.assertFalse(any("child-only alternative" in body.get("text", "") for _m, body in sends(client)))
        self.assertFalse(any("child-only alternative" in line.text for line in app.queued))
        self.assertIn("child-only alternative", app.child_drafts[FIRST].text, "kept for the child's next open")

    def test_main_tell_is_untouched_by_a_view_it_never_belonged_to(self) -> None:
        app, client, now = viewing(result=lazy_answer([BRIEF], running=False))
        press(app, ESCAPE)
        app.tell_owner = ""
        app._open_tell()
        self.assertIsNotNone(app.tell_draft)
        app._on_input(Paste("for main"))
        app._leave_view()  # no view on screen: nothing of main's tell moves
        self.assertIsNotNone(app.tell_draft)
        self.assertEqual(app.composer.text, "for main")


class RetiredChildIntakeTests(unittest.TestCase):
    """D12 / R2-E1-E3: a child's held submit never goes in halves when its agent leaves the roster."""

    def test_a_viewed_child_retired_while_its_image_is_pending_sends_no_text_alone(self) -> None:
        app, client, _ = viewing(result=lazy_answer([BRIEF], running=False), busy=False)
        app.roster.agents[FIRST].dag_node = "d:review-fixture:child"
        agent_event(app, "complete", FIRST, status="completed", summary="done")
        path = "/tmp/child-only.png"
        app._on_input(Paste(path))
        intake_id = call_id(client, "input.detect_drop")
        submit(app, "please describe this image")
        app._retire_finished_run({"nodes": [{"id": "d:review-fixture:child"}]})
        self.assertEqual(client.named("prompt.submit"), [], "no text half before the image answer")
        with mock.patch.object(app_module, "read_image", return_value=b"fixture"):
            app._on_response(Response(intake_id, {"matched": True, "is_image": True, "path": path}, None))
        self.assertEqual(client.named("prompt.submit"), [], "an image prompt is refused whole for a child")
        self.assertNotIn("please describe this image", repr(client.named("subagent.steer")))
        self.assertIn("please describe this image", app.composer.text, "the text stays where it was typed")

    def test_main_queue_does_not_wait_on_a_retired_childs_intake(self) -> None:
        app, client, _ = viewing()
        press(app, ESCAPE)
        submit(app, "main bare prompt")
        assert list(app.queued) and not client.named("prompt.submit")
        app._open_agent(FIRST)
        answer(app, client, lazy_answer([BRIEF]))
        app.roster.agents[FIRST].dag_node = "d:review-fixture:child"
        app._on_input(Paste("/tmp/child-only.png"))
        press(app, ESCAPE)
        app._on_event(Event("message.complete", SID, {"text": "main finished", "status": "completed"}))
        app._retire_finished_run({"nodes": [{"id": "d:review-fixture:child"}]})
        self.assertEqual([body.get("text") for body in client.named("prompt.submit")], ["main bare prompt"],
                         "main's queued prompt goes once the child's intake is gone with its agent")


if __name__ == "__main__":
    unittest.main()
