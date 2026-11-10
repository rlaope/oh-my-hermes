"""Esc Esc and `/rewind`: clear a draft into history, or go back to an earlier prompt and send it again.

With text in the composer, Esc twice clears it and keeps it in the input
history. On an empty composer between turns, Esc twice (or `/rewind`) lists
the session's prompts from `session.history`; the one picked comes back into
the composer, and sending it sends `prompt.submit` with
`truncate_before_row_id` and `confirm_truncate`, so Hermes drops that prompt
and everything after it, and the screen is redrawn from the cut. Answers are
the recorded Hermes 6c61c3e27d frames in `tests/fixtures/tui_gateway/parity.jsonl`.
A command sent over a picked rewind that sends a prompt (a skill) sends it in
the picked prompt's place; one that only prints leaves the rewind picked.
"""

from __future__ import annotations

import math
import unittest
from dataclasses import replace

from _tui_lines import line_text, lines_text, without_badge
from test_tui_command_output import SKILL_LINE, SKILL_REFUSAL, SKILL_TURN
from test_tui_gateway_contract import recorded_rows
from test_tui_modes import PLAN_PROMPT, SID, answer, make_app, notices, type_text
from omh.tui.app import DOUBLE_ESCAPE_SECONDS, HERMES_NEXT_TURN_SECONDS, REWIND_TURN_BACK_NOTICE, App, Attachment, QueuedLine
from omh.tui.gateway import Event, Response
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, Key
from omh.tui.rewind_picker import CLOSE, PICK, RewindPicker, rewind_rows
from omh.tui.slash import SlashInvocation
from omh.tui.theme import DEFAULT_THEME
from omh.tui.transcript import NOTICE_WARN, AssistantBlock, CommandBlock, NoticeBlock, UserBlock


def recorded_result(segment: str) -> dict:
    (frame,) = [row["frame"] for row in recorded_rows("parity", segment) if row["dir"] == "in" and "result" in row["frame"]]
    return frame["result"]


HISTORY = recorded_result("history_two")
TODO_PROMPT = HISTORY["messages"][0]["text"]
SECOND_PROMPT = "Reply with exactly the word: two"
# What Hermes' /retry and /undo answer once they took the last turn back (methods_tools.py `_cmd_retry`, `_cmd_undo`).
RETRIED = {"type": "send", "message": SECOND_PROMPT}
UNDONE = {"type": "prefill", "message": SECOND_PROMPT,
          "notice": "↶ Undid 1 turn (2 message(s)). Edit and resubmit, or send a new message."}


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def esc(app: App) -> None:
    app._on_input(Key(ESCAPE))


def mode_row(app: App, cols: int) -> str:
    return without_badge(line_text(app._info_line(cols)))


class PickerTests(unittest.TestCase):
    def test_the_rows_are_the_sessions_prompts_newest_first_with_their_row_ids(self) -> None:
        rows = rewind_rows(HISTORY)
        self.assertEqual([(row.text, row.row_id, row.ordinal) for row in rows], [(SECOND_PROMPT, 7, 2), (TODO_PROMPT, 1, 1)])
        self.assertEqual(rows[0].index, [message.get("row_id") for message in HISTORY["messages"]].index(7))

    def test_a_user_row_without_an_int_row_id_or_text_is_no_prompt_to_rewind_to(self) -> None:
        messages = [
            {"role": "user", "text": "kept", "row_id": 3},
            {"role": "user", "text": "no id"},
            {"role": "user", "text": "a string id", "row_id": "4"},
            {"role": "user", "text": "a bool id", "row_id": True},
            {"role": "user", "text": "   ", "row_id": 5},
            {"role": "assistant", "text": "a reply", "row_id": 6},
        ]
        self.assertEqual([(row.text, row.row_id) for row in rewind_rows({"messages": messages})], [("kept", 3)])

    def test_enter_picks_the_highlighted_prompt_typing_filters_and_esc_closes(self) -> None:
        picker = RewindPicker(rewind_rows(HISTORY))
        picker.handle_key(Key(DOWN))
        action = picker.handle_key(Key(ENTER))
        self.assertEqual((action.kind, action.row.row_id), (PICK, 1))
        picker = RewindPicker(rewind_rows(HISTORY))
        for char in "todo":
            picker.handle_key(Key(CHAR, char))
        self.assertEqual(picker.handle_key(Key(ENTER)).row.row_id, 1)
        self.assertEqual(RewindPicker(rewind_rows(HISTORY)).handle_key(Key(ESCAPE)).kind, CLOSE)

    def test_the_slot_names_what_picking_does(self) -> None:
        rows = lines_text(RewindPicker(rewind_rows(HISTORY)).lines(100, DEFAULT_THEME, 6, 1792006300.0))
        self.assertEqual(rows[0].rstrip(), " Rewind to a prompt (2)")  # its keys are the info line's
        self.assertTrue(rows[2].startswith("❯ #2 Reply with exactly the word: two"), rows)  # under the header's rule


class DoubleEscapeTests(unittest.TestCase):
    def test_escape_after_leader_cancel_arms_fresh_before_completing(self) -> None:
        for text, busy, kind in (("draft", False, "clear"), ("", True, "interrupt"), ("", False, "rewind")):
            with self.subTest(kind=kind):
                clock = Clock()
                app, client = make_app(busy=busy, clock=clock)
                app.composer.set_vim(True)
                type_text(app, text)
                esc(app)
                before = (app.composer.text, app.composer.caret, app.composer.normal, list(app.composer.history))
                esc(app)
                self.assertEqual(app.escape_armed, (kind, 100.0))
                clock.now = 100.1
                app._on_input(Key(CHAR, " "))
                self.assertEqual(app.escape_armed, (kind, 100.0))
                clock.now = 100.2
                esc(app)
                self.assertIsNone(app.escape_armed)
                self.assertFalse(app.composer.pending)
                self.assertEqual(client.calls, [])
                clock.now = 100.3
                esc(app)  # Esc Space Esc Esc must only arm a fresh confirmation.
                self.assertEqual(app.escape_armed, (kind, 100.3))
                self.assertEqual(
                    (app.composer.text, app.composer.caret, app.composer.normal, app.composer.history), before,
                )
                self.assertEqual(client.calls, [])
                self.assertIsNone(app.rewind_picker)
                clock.now = 100.4
                esc(app)
                self.assertIsNone(app.escape_armed)
                if kind == "clear":
                    self.assertEqual(app.composer.text, "")
                    self.assertEqual(app.composer.history, [text])
                    self.assertEqual(client.calls, [])
                else:
                    method = "session.interrupt" if busy else "session.history"
                    self.assertEqual(client.calls, [(method, {"session_id": SID})])
                    self.assertEqual(app.composer.history, [])
                    if kind == "rewind":
                        answer(app, client, HISTORY)
                        self.assertIsNotNone(app.rewind_picker)
                        self.assertEqual(len(app.rewind_picker.rows), 2)

    def test_vim_double_escape_preserves_the_exact_inclusive_timeout(self) -> None:
        self.assertEqual(DOUBLE_ESCAPE_SECONDS, 0.8)
        for text, busy, kind in (("draft", False, "clear"), ("", True, "interrupt"), ("", False, "rewind")):
            for canceled in (False, True):
                for delta in (DOUBLE_ESCAPE_SECONDS, math.nextafter(DOUBLE_ESCAPE_SECONDS, math.inf)):
                    with self.subTest(kind=kind, canceled=canceled, delta=delta):
                        clock = Clock()
                        clock.now = -0.3
                        app, client = make_app(busy=busy, clock=clock)
                        app.composer.set_vim(True)
                        type_text(app, text)
                        esc(app)
                        if canceled:
                            esc(app)
                            clock.now = -0.2
                            app._on_input(Key(CHAR, " "))
                            clock.now = -0.1
                            esc(app)
                            self.assertIsNone(app.escape_armed)
                        clock.now = 0.0  # Avoid rounding a tiny delta added to a large timestamp.
                        esc(app)
                        self.assertEqual(app.escape_armed, (kind, 0.0))
                        self.assertEqual(client.calls, [])
                        clock.now = delta
                        esc(app)
                        if delta > DOUBLE_ESCAPE_SECONDS:
                            self.assertEqual(app.escape_armed, (kind, delta))
                            self.assertEqual(app.composer.text, text)
                            self.assertEqual(app.composer.history, [])
                            self.assertEqual(client.calls, [])
                            self.assertIsNone(app.rewind_picker)
                            esc(app)  # The re-armed confirmation still works within its fresh window.
                        self.assertIsNone(app.escape_armed)
                        if kind == "clear":
                            self.assertEqual(app.composer.text, "")
                            self.assertEqual(app.composer.history, [text])
                            self.assertEqual(client.calls, [])
                        else:
                            method = "session.interrupt" if busy else "session.history"
                            self.assertEqual(client.calls, [(method, {"session_id": SID})])
                            self.assertEqual(app.composer.history, [])
                            if kind == "rewind":
                                answer(app, client, HISTORY)
                                self.assertIsNotNone(app.rewind_picker)

    def test_esc_twice_with_text_clears_it_into_the_history_and_once_keeps_it(self) -> None:
        clock = Clock()
        app, client = make_app(clock=clock)
        type_text(app, "a draft")
        esc(app)
        self.assertEqual(app.composer.text, "a draft")
        clock.now += DOUBLE_ESCAPE_SECONDS / 2
        esc(app)
        self.assertEqual(app.composer.text, "")
        self.assertEqual(app.composer.history, ["a draft"])
        self.assertEqual(client.calls, [])

    def test_two_escs_further_apart_than_the_window_are_two_first_escs(self) -> None:
        clock = Clock()
        app, _client = make_app(clock=clock)
        type_text(app, "a draft")
        esc(app)
        clock.now += DOUBLE_ESCAPE_SECONDS + 0.1
        esc(app)
        self.assertEqual(app.composer.text, "a draft")

    def test_the_mode_row_says_what_the_second_esc_will_do(self) -> None:
        clock = Clock()
        app, _client = make_app(clock=clock)
        type_text(app, "a draft")
        esc(app)
        self.assertIn("esc again to clear", mode_row(app, 80))
        clock.now += DOUBLE_ESCAPE_SECONDS + 0.1
        self.assertNotIn("esc again", mode_row(app, 80))
        app._set_composer("")
        esc(app)
        self.assertIn("esc again to rewind", mode_row(app, 80))

    def test_the_cut_counts_the_same_messages_the_picker_was_made_from(self) -> None:
        app, client = make_app()
        app._rewind("")
        messages = ["not a message", {"role": "user", "text": "first", "row_id": 1}, {"role": "assistant", "text": "one"},
                    {"role": "user", "text": "second", "row_id": 2}, {"role": "assistant", "text": "two"}]
        answer(app, client, {"messages": messages})
        app._on_input(Key(ENTER))  # the newest prompt, "second"
        self.assertEqual(app.rewind.before, tuple(messages[1:3]))  # type: ignore[union-attr]  # not "second" itself

    def test_esc_twice_on_a_paste_chip_keeps_its_text_in_the_history(self) -> None:
        from omh.tui.keys import Paste

        clock = Clock()
        app, _client = make_app(clock=clock)
        pasted = "line one\nline two\nline three\nline four"
        app._on_input(Paste(pasted))
        esc(app)
        esc(app)
        self.assertEqual(app.composer.text, "")
        self.assertEqual(app.composer.history[-1], pasted)  # recalled and sent, it is the text, not the label

    def test_typing_after_one_esc_takes_back_what_the_second_would_do(self) -> None:
        clock = Clock()
        app, _client = make_app(clock=clock)
        esc(app)
        self.assertIn("esc again to rewind", mode_row(app, 100))
        app._on_input(Key(CHAR, "a"))
        self.assertNotIn("esc again", mode_row(app, 100))  # at once, not 0.8 s later
        self.assertIsNone(app.escape_armed)

    def test_esc_twice_on_an_empty_idle_composer_lists_the_prompts_to_rewind_to(self) -> None:
        clock = Clock()
        app, client = make_app(clock=clock)
        esc(app)
        self.assertEqual(client.calls, [])
        esc(app)
        self.assertEqual(client.calls, [("session.history", {"session_id": SID})])
        answer(app, client, HISTORY)
        self.assertIsNotNone(app.rewind_picker)

    def test_esc_on_an_empty_composer_during_a_turn_still_interrupts_at_once(self) -> None:
        app, client = make_app(busy=True)
        esc(app)
        self.assertEqual(client.calls, [("session.interrupt", {"session_id": SID})])


def picked(row: int = 0) -> tuple[App, object]:
    """An app with the prompt `row` places from the newest picked to rewind to, back in the composer."""
    app, client = make_app()
    app._rewind("")
    answer(app, client, HISTORY)
    for _ in range(row):
        app._on_input(Key(DOWN))
    app._on_input(Key(ENTER))
    return app, client


class RewindTests(unittest.TestCase):
    def picked(self, row: int = 0) -> tuple[App, object]:
        return picked(row)

    def test_the_picked_prompt_comes_back_into_the_composer_to_edit(self) -> None:
        app, _client = self.picked()
        self.assertIsNone(app.rewind_picker)
        self.assertEqual(app.composer.text, SECOND_PROMPT)
        self.assertEqual(app.rewind.row_id, 7)  # type: ignore[union-attr]
        self.assertIn("rewind", mode_row(app, 100))

    def test_sending_it_truncates_before_that_prompt_and_redraws_from_the_cut(self) -> None:
        app, client = self.picked()
        app._set_composer("Reply with exactly the word: rewound")
        app._on_input(Key(ENTER))
        self.assertEqual(
            client.calls[-1],
            ("prompt.submit", {"session_id": SID, "text": "Reply with exactly the word: rewound",
                               "truncate_before_row_id": 7, "confirm_truncate": True}),
        )
        users = [block.text for block in app.transcript.blocks if isinstance(block, UserBlock)]
        self.assertEqual(users, [TODO_PROMPT, "Reply with exactly the word: rewound"])
        self.assertTrue([block for block in app.transcript.blocks if isinstance(block, AssistantBlock)])
        self.assertIsNone(app.rewind)
        # the full redraw cleared the screen: the next frame starts on its top row
        self.assertEqual((app.region.height, app.region.top_row(app.size[1])), (0, 0))

    def test_rewinding_to_the_first_prompt_leaves_nothing_above_the_new_one(self) -> None:
        app, client = self.picked(row=1)
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[-1][1]["truncate_before_row_id"], 1)
        self.assertEqual([block.text for block in app.transcript.blocks if isinstance(block, UserBlock)], [TODO_PROMPT])

    def test_a_refused_rewind_says_so_and_redraws_the_session_hermes_still_has(self) -> None:
        app, client = self.picked()
        app._set_composer("an edited prompt")
        app._on_input(Key(ENTER))
        answer(app, client, error={"code": 4018, "message": "rewind target not found"})
        self.assertEqual(client.calls[-1], ("session.history", {"session_id": SID}))
        answer(app, client, HISTORY)
        self.assertIn("Hermes did not rewind: rewind target not found.", notices(app, NOTICE_WARN)[-1])
        users = [block.text for block in app.transcript.blocks if isinstance(block, UserBlock)]
        self.assertEqual(users, [TODO_PROMPT, SECOND_PROMPT])
        self.assertFalse(app.turn_pending)

    def sent_and_refused(self) -> tuple[App, object]:
        """A rewind sent over a screen that shows the session, which Hermes refuses."""
        app, client = self.picked()
        for message in HISTORY["messages"]:  # what the screen showed before the rewind
            if message.get("role") == "user":
                app.transcript.add_user(message["text"])
            elif message.get("role") == "assistant":
                app.transcript.add_assistant(message.get("text") or "")
        app._set_composer("an edited prompt")
        app._on_input(Key(ENTER))
        answer(app, client, error={"code": 4018, "message": "rewind target not found"})
        return app, client

    def users(self, app: App) -> list[str]:
        return [block.text for block in app.transcript.blocks if isinstance(block, UserBlock)]

    def test_a_prompt_refused_after_the_cut_says_the_cut_happened_and_gives_the_prompt_back(self) -> None:
        # Attached to a shared gateway the child cuts first (`session.mutate`), then sends the prompt; Hermes
        # refusing the prompt then is no "Hermes kept its history".
        app, client = self.picked()
        app._set_composer("an edited prompt")
        app._on_input(Key(ENTER))
        answer(app, client, error={"code": 4001, "message": "Hermes cut the session, then refused the prompt (busy)",
                                   "data": {"rewound": True}})
        self.assertEqual(app.composer.text, "an edited prompt")
        said = notices(app, NOTICE_WARN)[-1]
        self.assertIn("Hermes cut the session there but did not take the prompt", said)
        self.assertNotIn("did not rewind", said)
        self.assertEqual(client.calls[-1], ("session.history", {"session_id": SID}))
        answer(app, client, HISTORY)
        self.assertIn("Hermes cut the session there", notices(app, NOTICE_WARN)[-1])
        self.assertFalse(app.turn_pending)

    def picked_with_image(self, text: str) -> tuple[App, object, Attachment]:
        """A rewind picked and `text` with an image token sent: Hermes staged its bytes and answered the path."""
        app, client = self.picked()
        app._set_composer(text)
        image = Attachment("/hermes/cache/images/clip_1.png", "shot.png", "", "[Image #1]", b"\x89PNG")
        app.composer.insert_image(image.label, image)
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[-1][0], "image.attach_bytes")
        answer(app, client, {"attached": True, "path": "/hermes/cache/images/upload_1.png"})
        self.assertEqual(client.calls[-1][0], "prompt.submit")
        return app, client, image

    def test_the_images_staged_for_a_refused_rewind_are_detached_as_the_prompt_is_not_given_back(self) -> None:
        # Hermes keeps what was staged for a prompt it refuses: it is detached, by the path Hermes answered.
        app, client, _image = self.picked_with_image("")
        answer(app, client, error={"code": 4018, "message": "rewind target not found"})
        self.assertIn(("image.detach", {"session_id": SID, "path": "/hermes/cache/images/upload_1.png"}), client.calls)
        self.assertEqual(app.composer.images, {})

    def test_a_rewound_prompt_hermes_cut_for_but_refused_comes_back_with_its_tokens(self) -> None:
        app, client, image = self.picked_with_image("again ")
        answer(app, client, error={"code": 4001, "message": "Hermes cut the session, then refused the prompt (busy)",
                                   "data": {"rewound": True}})
        self.assertEqual(app.composer.expanded(), "again [Image #1] ")
        self.assertEqual([held for _label, held in app.composer.images.values()], [image])
        self.assertIn(("image.detach", {"session_id": SID, "path": "/hermes/cache/images/upload_1.png"}), client.calls)

    def test_a_refused_rewind_puts_the_screen_back_before_hermes_sends_its_history(self) -> None:
        app, client = self.sent_and_refused()
        self.assertEqual(client.calls[-1], ("session.history", {"session_id": SID}))
        self.assertEqual(self.users(app), [TODO_PROMPT, SECOND_PROMPT])  # not the cut, not the prompt Hermes refused
        self.assertIn("Hermes did not rewind: rewind target not found.", notices(app, NOTICE_WARN)[-1])
        self.assertNotIn("as Hermes still has it", " ".join(notices(app)))  # nothing re-read yet

    def test_a_refused_rewind_whose_history_read_fails_keeps_the_screen_from_before(self) -> None:
        app, client = self.sent_and_refused()
        answer(app, client, error={"code": 5000, "message": "state.db locked"})
        self.assertEqual(self.users(app), [TODO_PROMPT, SECOND_PROMPT])
        said = " ".join(notices(app))
        self.assertIn("state.db locked", said)
        self.assertNotIn("as Hermes still has it", said)

    def queued_behind_a_refused_rewind(self) -> tuple[App, object]:
        """A rewind sent, a prompt queued behind it while it was out, and Hermes' refusal of the rewind."""
        app, client = self.picked()
        app._set_composer("an edited prompt")
        app._on_input(Key(ENTER))
        submit = len(client.calls)
        type_text(app, "a queued prompt")
        app._on_input(Key(ENTER))
        app._on_response(Response(submit, None, {"code": 4018, "message": "rewind target not found"}))
        return app, client

    def test_a_prompt_queued_behind_a_refused_rewind_goes_after_the_redraw_and_stays_on_the_screen(self) -> None:
        app, client = self.queued_behind_a_refused_rewind()
        self.assertEqual(client.calls[-1], ("session.history", {"session_id": SID}))  # nothing sent before the redraw
        answer(app, client, HISTORY)
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": "a queued prompt", "queued": True}))
        self.assertEqual(self.users(app), [TODO_PROMPT, SECOND_PROMPT, "a queued prompt"])  # its echo on the redrawn screen

    def test_a_turn_started_before_the_history_answer_keeps_the_queued_prompt_for_its_end(self) -> None:
        app, client = self.queued_behind_a_refused_rewind()
        type_text(app, "sent right away")  # no turn runs after the refusal, so this one goes at once
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": "sent right away"}))
        history = next(index for index, (method, _params) in enumerate(client.calls, start=1) if method == "session.history"
                       and index > 1)
        app._on_response(Response(history, HISTORY, None))
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": "sent right away"}))
        self.assertEqual([line.text for line in app.queued], ["a queued prompt"])  # waits for that turn's end
        app._on_event(Event("message.complete", SID, {"text": "done", "status": "complete"}))
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": "a queued prompt", "queued": True}))

    def test_a_prompt_queued_behind_a_refused_rewind_goes_once_the_history_read_fails_or_goes_unanswered(self) -> None:
        for outcome in ("refused", "unanswered"):
            with self.subTest(outcome=outcome):
                clock = Clock()
                app, client = make_app(clock=clock)
                app._rewind("")
                answer(app, client, HISTORY)
                app._on_input(Key(ENTER))
                app._set_composer("an edited prompt")
                app._on_input(Key(ENTER))
                submit = len(client.calls)
                type_text(app, "a queued prompt")
                app._on_input(Key(ENTER))
                app._on_response(Response(submit, None, {"code": 4018, "message": "rewind target not found"}))
                if outcome == "refused":
                    answer(app, client, error={"code": 5000, "message": "state.db locked"})
                    said = "state.db locked"
                else:
                    clock.now += 3600
                    app._expire_calls()
                    said = "no answer in 120 s"
                self.assertIn(f"Hermes did not send the session's history ({said})", " ".join(notices(app)))
                self.assertEqual(client.calls[-1],
                                 ("prompt.submit", {"session_id": SID, "text": "a queued prompt", "queued": True}))
                self.assertEqual(self.users(app)[-1], "a queued prompt")

    def test_a_rewind_refused_after_the_session_was_left_leaves_the_new_session_on_the_screen(self) -> None:
        for leave in ("new", "switch"):
            with self.subTest(leave=leave):
                app, client = self.picked()
                app._set_composer("an edited prompt")
                app._on_input(Key(ENTER))
                submit = len(client.calls)
                if leave == "new":
                    app._on_new_session({"session_id": "live-2", "stored_session_id": "stored-2"})
                else:
                    app._on_session_resumed("stored-2", {"session_id": "live-2", "stored_session_id": "stored-2"})
                screen = app.transcript
                app._on_response(Response(submit, None, {"code": 4018, "message": "rewind target not found"}))
                self.assertIs(app.transcript, screen)  # not the old session's screen from before the send
                self.assertFalse([text for text in notices(app) if "did not rewind" in text])
                self.assertNotIn(("session.history", {"session_id": SID}), client.calls[submit:])

    def test_a_rewind_sent_once_a_turn_started_gives_the_text_back_and_cuts_nothing(self) -> None:
        app, client = self.picked()
        app.turn_pending = True  # a turn started between the pick and the send
        app._set_composer("an edited prompt")
        app._on_input(Key(ENTER))
        self.assertNotIn("prompt.submit", [method for method, _params in client.calls])
        self.assertEqual(app.composer.text, "an edited prompt")
        self.assertIn("between turns", notices(app, NOTICE_WARN)[-1])
        self.assertIsNone(app.rewind)

    def test_a_rewind_sent_while_the_queue_waits_goes_first_and_the_queued_line_follows_its_turn(self) -> None:
        # While the queue waits for the turn Hermes runs next a prompt joins the queue, but a rewind cannot: its cut
        # would drop the turns the lines ahead of it start. It goes at once, and they follow its turn.
        app, client = self.picked()
        app.queued.append(QueuedLine("older queued line"))
        app.hermes_next_due = app.clock() + HERMES_NEXT_TURN_SECONDS
        app._set_composer("an edited prompt")
        app._on_input(Key(ENTER))
        submits = [params for method, params in client.calls if method == "prompt.submit"]
        self.assertEqual([(params["text"], params.get("truncate_before_row_id")) for params in submits],
                         [("an edited prompt", 7)])
        self.assertEqual([line.text for line in app.queued], ["older queued line"])
        app._on_event(Event("message.start", SID, {}))
        self.assertIsNone(app.hermes_next_due)  # the rewind's turn ends the wait: the queue goes at its end
        app._on_event(Event("message.complete", SID, {"text": "rewound answer", "status": "complete"}))
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": "older queued line", "queued": True}))

    def test_esc_cancels_a_rewind_and_empties_the_composer(self) -> None:
        app, client = self.picked()
        esc(app)
        self.assertIsNone(app.rewind)
        self.assertEqual(app.composer.text, "")
        calls = len(client.calls)
        type_text(app, "a plain prompt")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[calls], ("prompt.submit", {"session_id": SID, "text": "a plain prompt"}))

    def test_rewind_typed_in_capitals_lists_the_prompts_too(self) -> None:
        app, client = make_app()
        type_text(app, "/Rewind")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("session.history", {"session_id": SID})])  # not Hermes' slash.exec
        answer(app, client, HISTORY)
        self.assertIsNotNone(app.rewind_picker)

    def test_rewind_waits_in_the_queue_for_the_turn_to_end(self) -> None:
        app, client = make_app(busy=True)
        type_text(app, "/rewind")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [])
        self.assertEqual([line.text for line in app.queued], ["/rewind"])
        app._on_event(Event("message.complete", SID, {"text": "done", "status": "complete"}))
        self.assertEqual(client.calls[-1], ("session.history", {"session_id": SID}))

    def test_a_session_with_no_prompt_yet_has_nothing_to_rewind_to(self) -> None:
        app, client = make_app()
        app._rewind("")
        answer(app, client, {"count": 0, "messages": []})
        self.assertIsNone(app.rewind_picker)
        self.assertIn("No prompt to rewind to", notices(app)[-1])


class RewindCommandTests(unittest.TestCase):
    """A slash command sent with a rewind picked: the prompt it sends replaces the picked one; the rest leave it picked."""

    def send(self, app: App, line: str) -> int:
        """Send `line` from the composer in place of the picked prompt's text; the number of calls made before it."""
        app._set_composer("")
        calls = len(app.client.calls)  # type: ignore[attr-defined]
        type_text(app, line)
        app._on_input(Key(ENTER))
        return calls

    def users(self, app: App) -> list[str]:
        return [block.text for block in app.transcript.blocks if isinstance(block, UserBlock)]

    def test_a_skill_command_sends_its_prompt_in_the_picked_ones_place_and_clears_the_rewind(self) -> None:
        app, client = picked()
        start = self.send(app, SKILL_LINE)
        answer(app, client, error=SKILL_REFUSAL)
        answer(app, client, SKILL_TURN)
        self.assertEqual([method for method, _params in client.calls[start:]], ["slash.exec", "command.dispatch", "prompt.submit"])
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": SKILL_TURN["message"],
                                                              "truncate_before_row_id": 7, "confirm_truncate": True}))
        self.assertIsNone(app.rewind)
        self.assertEqual(self.users(app), [TODO_PROMPT, SKILL_LINE])  # redrawn from the cut, the skill's one row
        self.assertFalse([block for block in app.transcript.blocks if isinstance(block, CommandBlock)])
        self.assertNotIn("rewind", line_text(app._info_line(100)))

    def test_a_skill_prompt_refused_after_the_cut_gives_back_the_command_typed_not_the_skill_message(self) -> None:
        # The draft the person began while it was out stays first; the command comes back on its own line after it.
        app, client = picked()
        self.send(app, SKILL_LINE)
        answer(app, client, error=SKILL_REFUSAL)
        answer(app, client, SKILL_TURN)
        type_text(app, "a new draft")
        answer(app, client, error={"code": 4001, "message": "Hermes cut the session, then refused the prompt (busy)",
                                   "data": {"rewound": True}})
        self.assertEqual(app.composer.text, f"a new draft\n{SKILL_LINE}")
        self.assertNotIn(SKILL_TURN["message"], app.composer.text)

    def test_a_built_in_command_that_sends_a_prompt_sends_it_in_the_picked_ones_place(self) -> None:
        # Hermes 0.22.2's slash.exec runs command.dispatch itself for /plan (`_PENDING_INPUT_COMMANDS`) and answers
        # with its `send`; the TUI's 4018 fallback to command.dispatch, which a skill takes, gives the same.
        for refused in (False, True):
            with self.subTest(refused_first=refused):
                app, client = picked()
                start = self.send(app, "/plan fix the flaky test")
                if refused:
                    answer(app, client, error={"code": 4018, "message": "pending-input command"})
                answer(app, client, {"type": "send", "message": PLAN_PROMPT})
                self.assertEqual([method for method, _params in client.calls[start:]],
                                 ["slash.exec", *(["command.dispatch"] if refused else []), "prompt.submit"])
                self.assertEqual(client.calls[-1][1], {"session_id": SID, "text": PLAN_PROMPT,
                                                       "truncate_before_row_id": 7, "confirm_truncate": True})
                self.assertIsNone(app.rewind)
                self.assertEqual(self.users(app), [TODO_PROMPT, PLAN_PROMPT])  # what Hermes stores and a resume shows

    def test_what_the_dispatch_says_goes_under_the_new_row_after_the_cut(self) -> None:
        notice = "⚡ Loading 2 stacked skills: dag-ulw, review"
        app, client = picked()
        self.send(app, "/dag-ulw /review fix it")
        answer(app, client, error=SKILL_REFUSAL)
        answer(app, client, {**SKILL_TURN, "notice": notice, "display": "/dag-ulw /review fix it"})
        self.assertEqual(client.calls[-1][1]["truncate_before_row_id"], 7)
        row, said = [block for block in app.transcript.blocks if isinstance(block, (UserBlock, NoticeBlock))][-2:]
        self.assertEqual((row.text, said.text), ("/dag-ulw /review fix it", notice))

    def test_a_skill_reached_through_an_alias_still_replaces_the_picked_prompt(self) -> None:
        app, client = picked()
        self.send(app, "/ulw check every upstream pr")
        answer(app, client, {"type": "alias", "target": "dag-ulw"})
        self.assertEqual(client.calls[-1], ("slash.exec", {"command": "dag-ulw check every upstream pr", "session_id": SID}))
        answer(app, client, error=SKILL_REFUSAL)
        answer(app, client, SKILL_TURN)
        self.assertEqual(client.calls[-1][1].get("truncate_before_row_id"), 7)
        self.assertIsNone(app.rewind)

    def test_a_command_that_only_prints_runs_and_leaves_the_rewind_picked(self) -> None:
        for line in ("/help", "/usage"):
            with self.subTest(command=line):
                app, client = picked()
                start = self.send(app, line)
                if len(client.calls) > start:
                    answer(app, client, {"output": "Session cost: $0.01"})
                self.assertNotIn("prompt.submit", [method for method, _params in client.calls])
                self.assertIsNotNone(app.rewind)
                self.assertIn("rewind", line_text(app._info_line(100)))
                self.send(app, "an edited prompt")  # the rewind still goes with the next prompt
                self.assertEqual(client.calls[-1][1].get("truncate_before_row_id"), 7)
                self.assertIsNone(app.rewind)

    def test_a_rewind_cancelled_while_the_dispatch_is_out_cuts_nothing(self) -> None:
        app, client = picked()
        self.send(app, SKILL_LINE)
        answer(app, client, error=SKILL_REFUSAL)
        esc(app)  # Esc cancels the picked rewind before Hermes builds the skill's prompt
        answer(app, client, SKILL_TURN)
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": SKILL_TURN["message"]}))

    def test_a_rewind_picked_after_the_command_went_is_not_its(self) -> None:
        app, client = make_app(rows=40)
        type_text(app, SKILL_LINE)
        app._on_input(Key(ENTER))
        answer(app, client, error=SKILL_REFUSAL)
        app._rewind("")
        answer(app, client, HISTORY)
        app._on_input(Key(ENTER))  # picked while the skill's dispatch is out
        app._on_response(Response(2, SKILL_TURN, None))
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": SKILL_TURN["message"]}))
        self.assertIsNotNone(app.rewind)

    def test_a_turn_started_before_hermes_answered_gives_the_command_back_and_cuts_nothing(self) -> None:
        app, client = picked()
        self.send(app, SKILL_LINE)
        answer(app, client, error=SKILL_REFUSAL)
        app.turn_pending = True  # a turn started between the send and Hermes' answer
        answer(app, client, SKILL_TURN)
        self.assertNotIn("prompt.submit", [method for method, _params in client.calls])
        self.assertEqual(app.composer.text, SKILL_LINE)  # what was typed, not the skill body Hermes built
        self.assertIn("between turns", notices(app, NOTICE_WARN)[-1])
        self.assertIsNone(app.rewind)

    def test_steer_text_sent_between_turns_replaces_the_picked_prompt(self) -> None:
        app, client = picked()
        self.send(app, "/steer redo it shorter")
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": "redo it shorter",
                                                              "truncate_before_row_id": 7, "confirm_truncate": True}))
        self.assertIsNone(app.rewind)
        self.assertEqual(self.users(app), [TODO_PROMPT, "redo it shorter"])

    def test_retry_drops_the_rewind_and_resends_plain_since_hermes_took_the_turn_back(self) -> None:
        # Hermes' /retry rewinds the last turn itself (methods_tools.py `_cmd_retry`): a cut at the picked row on top
        # of that names a row that moved, and Hermes refuses it, so the retry would never run. slash.exec runs
        # command.dispatch itself for /retry (`_PENDING_INPUT_COMMANDS`), so it answers with the `send`. It lowercases the
        # name first, so /Retry is Hermes' /retry too.
        for line in ("/retry", "/Retry", "/RETRY"):
            with self.subTest(command=line):
                app, client = picked()
                self.send(app, line)
                self.assertEqual(client.calls[-1], ("slash.exec", {"command": line[1:], "session_id": SID}))
                answer(app, client, RETRIED)
                self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": SECOND_PROMPT}))
                self.assertIsNone(app.rewind)
                self.assertIn(REWIND_TURN_BACK_NOTICE.format(name=line[1:]), notices(app))

    def test_undo_drops_the_rewind_so_the_prompt_it_gives_back_goes_plain(self) -> None:
        # Hermes' /undo soft-deletes the last turn and answers `prefill` with its prompt (methods_tools.py `_cmd_undo`):
        # left picked, the rewind would send that prompt as a cut at a row that is gone, and Hermes would refuse it.
        for line in ("/undo", "/Undo"):
            with self.subTest(command=line):
                app, client = picked()
                self.send(app, line)
                self.assertEqual(client.calls[-1], ("slash.exec", {"command": line[1:], "session_id": SID}))
                answer(app, client, UNDONE)
                self.assertIsNone(app.rewind)
                self.assertEqual(app.composer.text, SECOND_PROMPT)
                self.assertEqual(notices(app)[-2:], [REWIND_TURN_BACK_NOTICE.format(name=line[1:]), UNDONE["notice"]])
                app._on_input(Key(ENTER))
                self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": SECOND_PROMPT}))

    def test_retry_and_undo_also_cancel_a_rewind_picked_while_they_were_out_and_close_the_picker(self) -> None:
        # The picks and the picker were made from the session as it was before Hermes took the last turn back.
        for line, reply in (("/retry", RETRIED), ("/undo", UNDONE)):
            for down, text in ((0, SECOND_PROMPT), (1, TODO_PROMPT), (0, None)):
                with self.subTest(command=line, row=down, picks=text is not None):
                    app, client = picked()
                    self.send(app, line)
                    out = len(client.calls)
                    esc(app)  # the pick the command went with is cancelled; the next is made while it is out
                    app._rewind("")
                    answer(app, client, HISTORY)
                    for _ in range(down):
                        app._on_input(Key(DOWN))
                    if text is not None:
                        app._on_input(Key(ENTER))
                    app._on_response(Response(out, reply, None))
                    self.assertIsNone(app.rewind)
                    self.assertIsNone(app.rewind_picker)
                    self.assertIn(REWIND_TURN_BACK_NOTICE.format(name=line[1:]), notices(app))
                    self.assertNotIn("rewind", line_text(app._info_line(100)))
                    if reply is RETRIED:
                        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": SECOND_PROMPT}))
                        self.assertEqual(app.composer.text, text or "")  # the picked text stays as a draft
                    else:
                        self.assertNotIn("prompt.submit", [method for method, _params in client.calls])
                        self.assertEqual(app.composer.text, SECOND_PROMPT)  # /undo's prefill takes the draft's place

    def test_retry_answered_with_an_empty_prompt_still_cancels_the_rewind(self) -> None:
        # Hermes took the turn back before it answered, whatever the answer carries.
        app, client = picked()
        self.send(app, "/retry")
        answer(app, client, {"type": "send", "message": "  "})
        self.assertNotIn("prompt.submit", [method for method, _params in client.calls])
        self.assertIsNone(app.rewind)
        self.assertIn("/retry: empty message", notices(app, NOTICE_WARN))

    def test_retry_and_undo_with_no_rewind_picked_say_nothing_about_one(self) -> None:
        for line, reply in (("/retry", RETRIED), ("/undo", UNDONE)):
            with self.subTest(command=line):
                app, client = make_app()
                self.send(app, line)
                answer(app, client, reply)
                self.assertNotIn(REWIND_TURN_BACK_NOTICE.format(name=line[1:]), notices(app))

    def test_the_rewind_an_invocation_carries_takes_no_part_in_its_equality_or_hash(self) -> None:
        # It is matched by identity (`is`): a Rewind holds the history's dicts, so hashing it raises.
        app, _client = picked()
        with self.assertRaises(TypeError):
            hash(app.rewind)
        bare = SlashInvocation("retry", "", None)
        carried = replace(bare, rewind=app.rewind)
        self.assertEqual(carried, bare)
        self.assertEqual(hash(carried), hash(bare))

    def test_a_rewind_picked_again_while_the_dispatch_is_out_is_not_the_commands(self) -> None:
        # Esc cancelled the pick the command went with; a pick made after it, even of the same row, is the next prompt's.
        for down, row_id, text in ((1, 1, TODO_PROMPT), (0, 7, SECOND_PROMPT)):
            with self.subTest(row=row_id):
                app, client = picked()
                self.send(app, SKILL_LINE)
                answer(app, client, error=SKILL_REFUSAL)
                dispatch = len(client.calls)
                esc(app)
                app._rewind("")
                answer(app, client, HISTORY)
                for _ in range(down):
                    app._on_input(Key(DOWN))
                app._on_input(Key(ENTER))  # picked while the skill's dispatch is out
                app._on_response(Response(dispatch, SKILL_TURN, None))
                self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": SKILL_TURN["message"]}))
                self.assertEqual(app.rewind.row_id, row_id)  # type: ignore[union-attr]  # still picked, for the next prompt
                self.assertEqual(app.composer.text, text)

    def test_a_draft_typed_while_the_dispatch_was_out_stays_when_the_command_comes_back(self) -> None:
        app, client = picked()
        self.send(app, SKILL_LINE)
        answer(app, client, error=SKILL_REFUSAL)
        type_text(app, "a draft")
        app.turn_pending = True  # a turn started before Hermes answered
        answer(app, client, SKILL_TURN)
        self.assertEqual(app.composer.text, f"a draft\n{SKILL_LINE}")
        self.assertNotIn("prompt.submit", [method for method, _params in client.calls])

    def test_a_command_that_sends_no_prompt_leaves_the_rewind_picked(self) -> None:
        for reply, said in (({"type": "prefill", "message": "a prefilled draft"}, ""),
                            ({"type": "send", "message": "  "}, "/dag-ulw: empty message")):
            with self.subTest(answer=reply["type"]):
                app, client = picked()
                self.send(app, SKILL_LINE)
                answer(app, client, error=SKILL_REFUSAL)
                answer(app, client, reply)
                self.assertNotIn("prompt.submit", [method for method, _params in client.calls])
                self.assertIsNotNone(app.rewind)
                if said:
                    self.assertIn(said, notices(app, NOTICE_WARN))
                else:
                    self.assertEqual(app.composer.text, "a prefilled draft")

    def test_an_alias_sent_without_a_rewind_cuts_nothing_when_one_is_picked_meanwhile(self) -> None:
        app, client = make_app()
        type_text(app, "/ulw check every upstream pr")
        app._on_input(Key(ENTER))
        app._rewind("")
        answer(app, client, HISTORY)
        app._on_input(Key(ENTER))  # picked before Hermes says /ulw is an alias
        app._on_response(Response(1, {"type": "alias", "target": "dag-ulw"}, None))
        answer(app, client, error=SKILL_REFUSAL)
        answer(app, client, SKILL_TURN)
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": SKILL_TURN["message"]}))
        self.assertIsNotNone(app.rewind)

    def test_a_renamed_command_keeps_the_rewind_it_was_sent_with(self) -> None:
        # Today's renamed targets only print; were one to send a prompt, it would go in the picked one's place too.
        app, client = picked()
        self.send(app, "/cost")
        self.assertEqual(client.calls[-1], ("slash.exec", {"command": "usage", "session_id": SID}))
        answer(app, client, {"type": "send", "message": "a prompt usage sent"})
        self.assertEqual(client.calls[-1][1].get("truncate_before_row_id"), 7)
        self.assertIsNone(app.rewind)


class DocumentedRewindTests(unittest.TestCase):
    def test_installation_names_the_window_and_the_calls_the_code_uses(self) -> None:
        from pathlib import Path

        prose = " ".join((Path(__file__).resolve().parents[1] / "docs/INSTALLATION.md").read_text(encoding="utf-8").split())
        self.assertIn(f"Esc twice (within {DOUBLE_ESCAPE_SECONDS:g} s) on an empty composer between turns", prose)
        self.assertIn("`truncate_before_row_id` and `confirm_truncate`", prose)


if __name__ == "__main__":
    unittest.main()
