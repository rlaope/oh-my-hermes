"""The subagent session view's last fix round (R2). Each test replays a scenario from the second review's repros
(`ownership_edges.py`, `read_edges.py`) and pins the fixed outcome. There is one class per contract item (E1-E5,
F1-F4), plus regression pins for what 879969ccd already got right.

The helpers are `test_tui_agent_session_view`'s.
"""

from __future__ import annotations

import unittest
from unittest import mock

from test_tui_agent_session_view import BRIEF, FIRST, SECOND, entered, lazy_answer, texts, viewing
from test_tui_modes import SID, answer, call_id, type_text
from omh.tui import app as app_module
from omh.tui.gateway import Event, Response
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
