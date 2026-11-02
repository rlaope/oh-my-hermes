"""Answers that land after the person moved on: a switched session, a started turn, a typed draft, another picker.

Each case drives the recording-client harness of `test_tui_modes`: the call goes
out, the person does something else, and only then does Hermes' answer arrive.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from test_tui_modes import SHIFT_TAB, SID, answer, drawn, make_app, notices, type_text
from omh.tui import app as app_module
from omh.tui import modes as modes_module
from omh.tui.gateway import Response, ServerRequest
from omh.tui.keys import BACKSPACE, CHAR, DOWN, ENTER, ESCAPE, LEFT, TAB, UP, Key, Paste
from omh.tui.slash import parse_slash
from omh.tui.transcript import UserBlock

OPTIONS = {"model": "m-a", "provider": "p",
           "providers": [{"slug": "p", "name": "P", "models": ["m-a", "m-b", "m-c"], "is_current": True}]}
HISTORY = {"messages": [
    {"role": "user", "row_id": 1, "text": "first prompt"}, {"role": "assistant", "text": "ok"},
    {"role": "user", "row_id": 3, "text": "second prompt"}, {"role": "assistant", "text": "ok"}]}
RESUMED_B = {"session_id": "live-b", "stored_session_id": "s-b", "messages": [], "info": {"model": "m-z"}}


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def run(app, text: str) -> int:
    """Type `text` and Enter; the id of the newest call it made."""
    type_text(app, text)
    app._on_input(Key(ENTER))
    return len(app.client.calls)


def switch_to_b(app) -> None:
    rid = run(app, "/sessions s-b")
    app._on_response(Response(rid, dict(RESUMED_B), None))


def said(app) -> list[str]:
    """Every notice and aside, written or still held under the tail."""
    return [b.text for b in [*app.transcript.blocks, *app.transcript._held] if hasattr(b, "text")]


class SlashAnswerAfterSwitchTests(unittest.TestCase):
    def test_a_late_slash_answer_runs_nothing_in_the_session_switched_to(self) -> None:
        for result in ({"type": "skill", "message": "SKILL BODY for A", "display": "/review-a"},
                       {"type": "send", "message": "Retry: the last prompt from A"},
                       {"type": "prefill", "message": "A's undone draft"}):
            with self.subTest(kind=result["type"]):
                app, client = make_app()
                app.stored_id = "s-a"
                rid = run(app, "/review-a now")
                switch_to_b(app)
                type_text(app, "my draft in B")
                sent = len(client.calls)
                app._on_response(Response(rid, result, None))
                self.assertEqual(client.calls[sent:], [])
                self.assertEqual([b for b in app.transcript.blocks if isinstance(b, UserBlock)], [])
                self.assertEqual(app.composer.text, "my draft in B")
                self.assertIn(app_module.SLASH_LEFT_NOTICE.format(name="review-a"),
                              [b.text for b in [*app.transcript.blocks, *app.transcript._held] if hasattr(b, "text")])

    def test_the_dispatch_fallback_asks_nothing_once_the_session_was_left(self) -> None:
        app, client = make_app()
        rid = run(app, "/review-a now")
        switch_to_b(app)
        sent = len(client.calls)
        app._on_response(Response(rid, None, {"code": app_module.contract.NOT_MINE, "message": "not mine"}))
        self.assertEqual(client.named("command.dispatch"), [])
        self.assertEqual(client.calls[sent:], [])

    def test_a_dispatch_answered_after_the_session_was_left_runs_nothing_there(self) -> None:
        app, client = make_app()
        rid = run(app, "/review-a now")
        app._on_response(Response(rid, None, {"code": app_module.contract.NOT_MINE, "message": "not mine"}))
        self.assertEqual(client.named("command.dispatch"), [{"name": "review-a", "arg": "now", "session_id": SID}])
        dispatched = len(client.calls)
        switch_to_b(app)
        type_text(app, "my draft in B")
        sent = len(client.calls)
        app._on_response(Response(dispatched, {"type": "skill", "message": "SKILL BODY for A"}, None))
        self.assertEqual(client.calls[sent:], [])
        self.assertEqual([b for b in app.transcript.blocks if isinstance(b, UserBlock)], [])
        self.assertEqual(app.composer.text, "my draft in B")
        self.assertIn(app_module.SLASH_LEFT_NOTICE.format(name="review-a"), said(app))

    def test_a_left_sessions_exec_output_is_shown_and_its_side_task_stays_that_sessions(self) -> None:
        app, client = make_app()
        rid = run(app, "/bg check the logs")
        switch_to_b(app)
        sent = len(client.calls)
        app._on_response(Response(rid, {"type": "exec", "output": "started task t-1", "task_id": "t-1",
                                         "branched_session_id": "child-of-a"}, None))
        self.assertIn("started task t-1", notices(app))
        self.assertEqual(app.side_tasks, {"t-1": SID})
        self.assertEqual(client.calls[sent:], [])  # no switch to the branch the left session made
        self.assertEqual(app.sid, "live-b")

    def test_a_left_sessions_command_gives_its_images_back(self) -> None:
        image = app_module.Attachment("/tmp/shot.png", "shot.png", "", label="[Image #1]")
        for result in ({"type": "exec", "output": "done"}, {"type": "skill", "message": "SKILL BODY"}):
            with self.subTest(kind=result["type"]):
                app, client = make_app()
                invocation = replace(parse_slash("/review-a now"), images=(image,))
                app._on_slash_result(invocation, result, 0, "live-a")  # it ran in a session left since
                self.assertEqual([kept for _label, kept in app.composer.images.values()], [image])  # its token is back in the composer
                self.assertIn(app_module.IMAGES_KEPT_NOTICE.format(what="/review-a", labels="[Image #1]"), notices(app))
                self.assertEqual(client.calls, [])


class PrefillOverTypeaheadTests(unittest.TestCase):
    def test_a_late_prefill_keeps_the_draft_typed_meanwhile_in_history(self) -> None:
        app, client = make_app()
        rid = run(app, "/undo")
        type_text(app, "something new I typed")
        app._on_response(Response(rid, {"type": "prefill", "message": "the undone prompt"}, None))
        self.assertEqual(app.composer.text, "the undone prompt")
        self.assertEqual(app.composer.history[-1], "something new I typed")
        self.assertIn(app_module.DRAFT_KEPT_NOTICE, notices(app))


class PickerPriorityTests(unittest.TestCase):
    def test_keys_go_to_the_picker_drawn_and_a_late_list_does_not_open_under_another(self) -> None:
        for command, result in (("/model", OPTIONS), ("/rewind", HISTORY)):
            with self.subTest(command=command):
                app, client = make_app()
                rid = run(app, command)
                run(app, "/theme")
                self.assertIsNotNone(app.launch_picker)
                app._on_response(Response(rid, result, None))
                self.assertEqual((app.model_picker, app.rewind_picker), (None, None))
                self.assertIn(app_module.LIST_TAKEN_NOTICE.format(command=command), notices(app))
                sent = len(client.calls)
                app._on_input(Key(DOWN))
                app._on_input(Key(ENTER))
                self.assertEqual(client.calls[sent:], [])  # the theme picker took the keys, not a hidden list
                self.assertIsNone(app.launch_picker)

    def test_with_two_pickers_open_the_drawn_one_has_the_keys(self) -> None:
        app, client = make_app()
        run(app, "/theme")
        app.model_picker = app_module.ModelPicker(app_module.model_rows(OPTIONS), current="m-a")  # opened unchecked
        self.assertTrue(any("Launch look" in line for line in drawn(app)))
        sent = len(client.calls)
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[sent:], [])
        self.assertIsNone(app.launch_picker)
        self.assertIsNotNone(app.model_picker)


class DuplicateModelListTests(unittest.TestCase):
    def test_model_twice_sends_one_list_and_a_late_answer_leaves_the_open_picker(self) -> None:
        app, client = make_app()
        rid = run(app, "/model")
        run(app, "/model")
        self.assertEqual(client.named("model.options"), [{"session_id": app.sid}])
        app._on_response(Response(rid, OPTIONS, None))
        app._on_input(Key(DOWN))
        app._on_input(Key(DOWN))
        index = app.model_picker.index
        app._open_model_picker(app.sid, OPTIONS)  # a second answer, had one been asked for
        self.assertEqual(app.model_picker.index, index)
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[-1][1]["value"].split()[0], "m-c")


class ListPerSessionTests(unittest.TestCase):
    def test_a_list_still_out_for_the_session_left_never_holds_up_the_new_ones(self) -> None:
        for command, method in (("/model", "model.options"), ("/rewind", "session.history")):
            with self.subTest(command=command):
                app, client = make_app()
                rid = run(app, command)
                switch_to_b(app)
                run(app, command)
                self.assertEqual(client.named(method), [{"session_id": SID}, {"session_id": "live-b"}])
                app._on_response(Response(rid, OPTIONS if command == "/model" else HISTORY, None))  # A's, late
                self.assertEqual((app.model_picker, app.rewind_picker), (None, None))
                answer(app, client, OPTIONS if command == "/model" else HISTORY)
                self.assertIsNotNone(app.model_picker if command == "/model" else app.rewind_picker)

    def test_asking_for_one_list_keeps_the_record_of_the_other(self) -> None:
        app, client = make_app()
        run(app, "/rewind")
        run(app, "/model")
        run(app, "/rewind")
        self.assertEqual(len(client.named("session.history")), 1)
        self.assertEqual(len(client.named("model.options")), 1)

    def test_model_refresh_while_a_bare_list_is_out_says_it_is_loading(self) -> None:
        app, client = make_app()
        run(app, "/model")
        run(app, "/model --refresh")
        self.assertEqual(client.named("model.options"), [{"session_id": SID}])
        self.assertIn(app_module.LIST_LOADING_NOTICE.format(command="/model --refresh"), said(app))

    def test_a_second_answer_for_the_open_picker_says_nothing(self) -> None:
        app, client = make_app()
        run(app, "/model")
        answer(app, client, OPTIONS)
        app._open_model_picker(app.sid, OPTIONS)
        self.assertNotIn(app_module.LIST_TAKEN_NOTICE.format(command="/model"), said(app))


class TypeaheadIntoApprovalTests(unittest.TestCase):
    def test_keys_typed_as_an_approval_opens_never_answer_it_and_stay_in_the_draft(self) -> None:
        clock = Clock()
        app, client = make_app(busy=True, clock=clock)
        text = "please summarise the diff and then stop"
        for i, char in enumerate(text):
            if i == 12:
                app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./build"}))
            app._on_input(Key(CHAR, char))
            clock.now += 0.125
        self.assertEqual(client.answers, [])
        self.assertEqual(client.named("session.interrupt"), [])
        self.assertEqual(app.composer.text, text)
        clock.now += app_module.SLOT_ARM_SECONDS
        app._on_input(Key(CHAR, "d"))  # after a quiet gap: the deny letter, as designed
        self.assertEqual(client.answers, [("srq-1", {"result": {"choice": "deny"}})])

    def open_typing(self, typed: str = "teh") -> tuple:
        clock = Clock()
        app, client = make_app(busy=True, clock=clock)
        type_text(app, typed)
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "ls"}))
        return app, client, clock

    def early(self, app, clock, *events) -> None:
        for event in events:
            app._on_input(event)
            clock.now += 0.1

    def test_editing_keys_typed_as_it_opens_edit_the_draft(self) -> None:
        app, client, clock = self.open_typing()
        self.early(app, clock, Key(BACKSPACE), Key(BACKSPACE), Key(CHAR, "h"), Key(CHAR, "e"),
                   Key(LEFT), Key(LEFT), Key(LEFT), Key(CHAR, "w"), Key(CHAR, "e", ctrl=True), Key(CHAR, "!"))
        self.assertEqual(app.composer.text, "wthe!")
        self.assertEqual(client.answers, [])

    def test_keys_that_submit_interrupt_complete_or_walk_history_do_nothing_early(self) -> None:
        app, client, clock = self.open_typing("/he")
        app.composer.history.append("an older prompt")
        sent = len(client.calls)
        self.early(app, clock, Key(ENTER), Key(TAB), Key(UP), Key(DOWN), Key(ESCAPE), Key(CHAR, "c", ctrl=True),
                   Key(CHAR, "d", ctrl=True), Key(CHAR, "j", ctrl=True))
        self.assertEqual(app.composer.text, "/he")
        self.assertEqual((client.answers, client.calls[sent:]), ([], []))
        self.assertIsNotNone(app.slot)  # still open, unanswered

    def test_early_keys_go_to_the_tell_field_that_was_on_screen(self) -> None:
        clock = Clock()
        app, client = make_app(busy=True, clock=clock)
        type_text(app, "my draft")
        app._open_tell()
        type_text(app, "tell it ")
        app._on_server_request(ServerRequest("srq-2", "approval", {"command": "ls"}))
        self.early(app, clock, *(Key(CHAR, ch) for ch in "to stop"))
        self.assertEqual(app.composer.text, "tell it to stop")
        self.assertEqual(app.tell_draft.text, "my draft")

    def test_an_early_drop_shaped_paste_is_a_drop(self) -> None:
        app, client, clock = self.open_typing("")
        self.early(app, clock, Paste("/Users/me/shot.png"))
        self.assertEqual(client.named("input.detect_drop"), [{"session_id": SID, "text": "/Users/me/shot.png"}])
        self.assertEqual(app.composer.text, "")

    def test_an_early_edit_reopens_the_slash_menu_as_a_composer_edit_does(self) -> None:
        app, client, clock = self.open_typing("/he")
        app.menu_closed, app.menu_index = "/he", 2
        self.early(app, clock, Key(CHAR, "l"))
        self.assertEqual((app.menu_closed, app.menu_index), (None, 0))

    def test_keys_typed_while_a_mouse_report_may_still_arrive_are_dropped(self) -> None:
        # A late report's tail can decode as keys (`[`, `<`, digits, `M`): under the reporting delay none is typed.
        clock = Clock()
        app, client = make_app(busy=True, clock=clock)
        type_text(app, "draft")
        app._set_mouse(True)
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "ls"}))
        self.assertEqual(app.slot_arm_seconds, app_module.REPORTING_SLOT_ARM_SECONDS)
        self.early(app, clock, *(Key(CHAR, ch) for ch in "[<0;5;5M"), Key(BACKSPACE))
        self.assertEqual(app.composer.text, "draft")
        self.assertEqual(client.answers, [])


class UnansweredYoloTests(unittest.TestCase):
    def test_an_unanswered_yolo_call_shows_accept_and_shift_tab_sends_an_explicit_off(self) -> None:
        clock = Clock()
        app, client = make_app(clock=clock)
        app._on_input(SHIFT_TAB)
        clock.now += app_module.CALL_ANSWER_SECONDS + 1
        app._expire_calls()
        self.assertFalse(app.mode_request_open)
        self.assertTrue(app.approvals_off)
        self.assertIn(modes_module.YOLO_UNANSWERED_NOTICE.format(seconds=app_module.CALL_ANSWER_SECONDS), notices(app))
        sent = len(client.calls)
        app._on_input(SHIFT_TAB)
        self.assertEqual(client.calls[sent:], [("config.set", {"key": "yolo", "session_id": app.sid, "value": "off"})])

    def test_an_unanswered_switch_back_shows_accept_too(self) -> None:
        clock = Clock()
        app, client = make_app(clock=clock)
        app._on_input(SHIFT_TAB)
        answer(app, client, error={"code": 4002, "message": "refused"})  # the on refused: the switch-back goes
        self.assertEqual(client.calls[-1], ("config.set", {"key": "yolo", "session_id": app.sid, "value": "off"}))
        self.assertTrue(app.mode_request_open)
        clock.now += app_module.CALL_ANSWER_SECONDS + 1
        app._expire_calls()
        self.assertFalse(app.mode_request_open)
        self.assertTrue(app.approvals_off)
        self.assertIn(modes_module.YOLO_UNANSWERED_NOTICE.format(seconds=app_module.CALL_ANSWER_SECONDS), notices(app))


class ListAfterMovingOnTests(unittest.TestCase):
    def test_a_list_answered_after_a_prompt_went_does_not_open_during_the_turn(self) -> None:
        for command, result, notice in (("/rewind", HISTORY, app_module.REWIND_BUSY_NOTICE),
                                        ("/model", OPTIONS, app_module.MODEL_BUSY_NOTICE)):
            with self.subTest(command=command):
                app, client = make_app()
                rid = run(app, command)
                run(app, "run the tests")
                self.assertTrue(app._busy())
                app._on_response(Response(rid, result, None))
                self.assertEqual((app.rewind_picker, app.model_picker), (None, None))
                self.assertIn(notice, [b.text for b in [*app.transcript.blocks, *app.transcript._held]
                                       if hasattr(b, "text")])

    def test_a_rewind_pick_keeps_the_draft_typed_while_the_history_was_on_its_way(self) -> None:
        app, client = make_app()
        run(app, "/rewind")
        type_text(app, "a long draft I was typing")
        answer(app, client, HISTORY)
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, "second prompt")
        self.assertEqual(app.composer.history[-1], "a long draft I was typing")
        self.assertIn(app_module.DRAFT_KEPT_NOTICE, notices(app))


class ModelAnswerAfterSwitchTests(unittest.TestCase):
    def test_a_late_model_switch_answer_says_nothing_in_the_session_switched_to(self) -> None:
        app, client = make_app()
        app.stored_id = "s-a"
        app.model = "m-a"
        rid = run(app, "/model m-b")
        switch_to_b(app)
        app._on_response(Response(rid, {"key": "model", "value": "m-b"}, None))
        self.assertEqual(app.model, "m-z")
        self.assertNotIn(app_module.MODEL_SWITCHED_NOTICE.format(model="m-b"), notices(app))


class WaitingForAListTests(unittest.TestCase):
    def test_model_and_rewind_say_waiting_for_hermes_until_their_list_lands(self) -> None:
        for command, result in (("/model", OPTIONS), ("/rewind", HISTORY)):
            with self.subTest(command=command):
                app, client = make_app()
                rid = run(app, command)
                self.assertTrue(any(app_module.LIST_WAIT_LINE in line for line in drawn(app)))
                app._on_response(Response(rid, result, None))
                self.assertFalse(any(app_module.LIST_WAIT_LINE in line for line in drawn(app)))


if __name__ == "__main__":
    unittest.main()
