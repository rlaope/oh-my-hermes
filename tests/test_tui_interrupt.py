"""Interrupting a turn: the `interrupting…` row until Hermes stops, and the queue that does not go on by itself.

Claude Code puts queued input back into the prompt when a turn is
interrupted; the OMH TUI does the same with what Up would take back, so a
person who stops a turn is never surprised by the next queued prompt
starting. A queued `!` line is never joined to a prompt (`_recall_queue`),
so what Up would not take with the rest stays queued, held, until the person
sends a prompt or takes it back with Up. Every case drives an `App` over the
recording client from `test_tui_modes`.
"""

from __future__ import annotations

import unittest

from _tui_lines import lines_text
from test_tui_app import info_row_of
from test_tui_choice_ui import armed, press
from test_tui_modes import SID, answer, drawn, make_app, notices, type_text
from test_tui_questions import COLOUR, TELL_APPROVAL
from omh.tui.app import EXIT_CONFIRM_SECONDS, EXIT_HINT, INTERRUPTING, QUEUE_HELD_HINT, QueuedLine, Rewind, queue_lines
from omh.tui.gateway import Event
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, UP, Key
from omh.tui.theme import DEFAULT_THEME
from omh.tui.transcript import NOTICE_ERROR

CTRL_C = Key(CHAR, "c", ctrl=True)
INTERRUPTED = Event("message.complete", SID, {"text": "", "status": "interrupted"})


def running(*queued: QueuedLine):
    app, client = make_app(busy=True)
    app.queued.extend(queued)
    return app, client


def submitted(client) -> list[str]:
    return [params["text"] for params in client.named("prompt.submit")]


class InterruptingRowTests(unittest.TestCase):
    def test_after_esc_the_working_row_says_interrupting_and_offers_no_esc(self) -> None:
        app, client = running()
        self.assertIn("esc to interrupt", "\n".join(drawn(app)))
        app._on_input(Key(ESCAPE))
        self.assertEqual(client.named("session.interrupt"), [{"session_id": SID}])
        screen = "\n".join(drawn(app))
        self.assertIn(INTERRUPTING, screen)
        self.assertNotIn("esc to interrupt", screen)
        self.assertNotIn("esc interrupt", screen)  # the info line does not offer it either

    def test_ctrl_c_shows_it_too(self) -> None:
        app, _client = running()
        app._on_input(CTRL_C)
        self.assertIn(INTERRUPTING, "\n".join(drawn(app)))

    def test_it_goes_when_the_turn_ends(self) -> None:
        app, _client = running()
        app._on_input(Key(ESCAPE))
        app._on_event(INTERRUPTED)
        self.assertNotIn(INTERRUPTING, "\n".join(drawn(app)))
        self.assertFalse(app.interrupting)

    def test_a_refused_interrupt_brings_the_spinner_back_and_says_so(self) -> None:
        app, client = running()
        app._on_input(Key(ESCAPE))
        answer(app, client, error={"code": 4009, "message": "no turn to interrupt"})
        self.assertFalse(app.interrupting)
        self.assertIn("esc to interrupt", "\n".join(drawn(app)))
        self.assertEqual(notices(app, NOTICE_ERROR), ["Hermes did not interrupt the turn: no turn to interrupt."])

    def test_a_second_esc_asks_again(self) -> None:
        app, client = running()
        app._on_input(Key(ESCAPE))
        app._on_input(Key(ESCAPE))
        self.assertEqual(len(client.named("session.interrupt")), 2)


class QueueAfterInterruptTests(unittest.TestCase):
    def test_queued_prompts_come_back_to_the_composer_joined_in_order_and_nothing_is_sent(self) -> None:
        app, client = running(QueuedLine("first"), QueuedLine("second"))
        app._on_input(Key(ESCAPE))
        app._on_event(INTERRUPTED)
        self.assertEqual(submitted(client), [])
        self.assertEqual(app.composer.text, "first\nsecond")
        self.assertEqual(list(app.queued), [])
        self.assertIn("Interrupted: what you queued is back in the composer, not sent.", notices(app))

    def test_a_turn_that_ends_on_its_own_still_sends_the_next_queued_prompt(self) -> None:
        app, client = running(QueuedLine("first"), QueuedLine("second"))
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual(submitted(client), ["first"])

    def test_a_turn_refused_after_the_interrupt_returns_the_queue_too(self) -> None:
        # Hermes cancels a turn whose agent was not ready yet with a bare error event, not message.complete.
        app, client = running(QueuedLine("first"))
        app._on_input(CTRL_C)
        app._on_event(Event("error", SID, {"message": "Turn cancelled before the agent was ready"}))
        self.assertEqual(submitted(client), [])
        self.assertEqual(app.composer.text, "first")

    def test_a_queued_shell_line_stays_held_and_the_next_prompt_lets_the_queue_go_on(self) -> None:
        app, client = running(QueuedLine("first"), QueuedLine("!ls", shell=True), QueuedLine("third"))
        app._on_input(Key(ESCAPE))
        app._on_event(INTERRUPTED)
        self.assertEqual(app.composer.text, "first")  # Up's rule: a `!` line is never joined to a prompt
        self.assertEqual([line.text for line in app.queued], ["!ls", "third"])
        self.assertTrue(app.queue_held)
        self.assertIn(QUEUE_HELD_HINT, "\n".join(drawn(app)))
        app._drain_queue()
        self.assertEqual((submitted(client), client.named("shell.exec")), ([], []))  # held: nothing goes by itself
        app._on_input(Key(ENTER))  # the person sends "first": the queue goes on behind it
        self.assertFalse(app.queue_held)
        self.assertEqual(submitted(client), ["first"])
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual(client.named("shell.exec"), [{"command": "ls"}])

    def test_up_takes_held_lines_back(self) -> None:
        app, _client = running(QueuedLine("!ls", shell=True), QueuedLine("two"))
        app._on_input(Key(ESCAPE))
        app._on_event(INTERRUPTED)
        self.assertEqual(app.composer.text, "!ls")  # the shell line first: it comes back on its own
        app._set_composer("")
        app._on_input(Key(UP))
        self.assertEqual(app.composer.text, "two")
        self.assertFalse(app.queue_held)

    def test_a_draft_typed_while_interrupting_is_kept_and_the_queue_is_held(self) -> None:
        app, client = running(QueuedLine("first"))
        app._on_input(Key(ESCAPE))
        type_text(app, "my draft")
        app._on_event(INTERRUPTED)
        self.assertEqual(app.composer.text, "my draft")
        self.assertEqual([line.text for line in app.queued], ["first"])
        self.assertTrue(app.queue_held)
        self.assertEqual(submitted(client), [])

    def test_a_new_session_drops_the_hold(self) -> None:
        app, _client = running(QueuedLine("!ls", shell=True))
        app._on_input(Key(ESCAPE))
        app._on_event(INTERRUPTED)
        app._on_new_session({"session_id": "live-2", "stored_session_id": "stored-2"})
        self.assertFalse(app.queue_held)
        self.assertFalse(app.interrupting)

    def test_the_held_rows_say_why_they_wait(self) -> None:
        rows = lines_text(queue_lines(["!ls"], 60, 3, DEFAULT_THEME, hint=QUEUE_HELD_HINT))
        self.assertTrue(rows[0].endswith(QUEUE_HELD_HINT), rows)


if __name__ == "__main__":
    unittest.main()


class CtrlCExitTests(unittest.TestCase):
    """The Ctrl+C that interrupts a turn also arms the exit, so a second one leaves while the turn is still stopping."""

    def test_a_second_ctrl_c_while_the_turn_is_still_stopping_exits(self) -> None:
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        app._on_input(CTRL_C)
        self.assertEqual(client.named("session.interrupt"), [{"session_id": SID}])
        screen = drawn(app)
        self.assertIn(INTERRUPTING, "\n".join(screen))  # the working row stays, and the info line names the exit
        self.assertIn(EXIT_HINT, info_row_of(screen))
        now[0] += 0.4
        app._on_input(CTRL_C)
        self.assertEqual(app.exit_code, 0)
        self.assertTrue(app.interrupting)  # Hermes had not stopped the turn yet
        self.assertEqual(len(client.named("session.interrupt")), 1)  # the second press leaves; it does not ask again

    def test_past_the_window_a_ctrl_c_mid_turn_interrupts_again_and_arms_again(self) -> None:
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        app._on_input(CTRL_C)
        now[0] += EXIT_CONFIRM_SECONDS + 0.1
        app._expire_exit()
        self.assertNotIn(EXIT_HINT, info_row_of(drawn(app)))
        app._on_input(CTRL_C)
        self.assertIsNone(app.exit_code)
        self.assertEqual(len(client.named("session.interrupt")), 2)
        self.assertIn(EXIT_HINT, info_row_of(drawn(app)))

    def test_ctrl_c_with_a_draft_clears_it_and_neither_interrupts_nor_arms(self) -> None:
        app, client = make_app(busy=True)
        type_text(app, "half a thought")
        app._on_input(CTRL_C)
        self.assertEqual(app.composer.text, "")
        self.assertIsNone(app.exit_armed_at)
        self.assertEqual(client.named("session.interrupt"), [])

    def test_ctrl_c_on_a_question_declines_it_and_arms_nothing(self) -> None:
        app, client = make_app(busy=True)
        app._on_server_request(COLOUR)
        armed(app)
        app._on_input(CTRL_C)
        self.assertIsNone(app.slot)
        self.assertEqual(len(client.answers), 1)  # the decline
        self.assertIsNone(app.exit_armed_at)
        self.assertIsNone(app.exit_code)

    def test_the_armed_second_press_exits_when_the_queue_came_back_into_the_composer(self) -> None:
        # QA B3: the queue came back between the presses, and the second press cleared it instead of leaving.
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        app.queued.append(QueuedLine("a queued prompt"))
        app._on_input(CTRL_C)
        app._on_event(INTERRUPTED)
        self.assertEqual(app.composer.text, "a queued prompt")
        self.assertIn(EXIT_HINT, info_row_of(drawn(app)))
        now[0] += 0.6
        app._on_input(CTRL_C)
        self.assertEqual(app.exit_code, 0)
        self.assertEqual(app.composer.text, "a queued prompt")  # not cleared; what was queued is in history too
        self.assertEqual(submitted(client), [])

    def test_the_armed_second_press_exits_over_a_draft_when_idle_too(self) -> None:
        now = [100.0]
        app, _client = make_app(clock=lambda: now[0])
        app._on_input(CTRL_C)
        type_text(app, "kept")
        self.assertIn(EXIT_HINT, info_row_of(drawn(app)))  # what the line promises is what the press does
        now[0] += 0.5
        app._on_input(CTRL_C)
        self.assertEqual(app.exit_code, 0)
        self.assertEqual(app.composer.text, "kept")

    def test_past_the_window_ctrl_c_clears_what_came_back_and_does_not_exit(self) -> None:
        now = [100.0]
        app, _client = make_app(busy=True, clock=lambda: now[0])
        app.queued.append(QueuedLine("a queued prompt"))
        app._on_input(CTRL_C)
        app._on_event(INTERRUPTED)
        now[0] += EXIT_CONFIRM_SECONDS + 0.1
        app._on_input(CTRL_C)
        self.assertIsNone(app.exit_code)
        self.assertEqual(app.composer.text, "")

    def test_any_ctrl_c_the_composer_takes_exits_once_armed(self) -> None:
        # The composer takes Ctrl+C with Shift or Alt held as Ctrl+C: the armed press must too, not clear the text.
        for key in (Key(CHAR, "c", ctrl=True, shift=True), Key(CHAR, "c", ctrl=True, alt=True)):
            with self.subTest(key=key):
                now = [100.0]
                app, _client = make_app(clock=lambda: now[0])
                app._on_input(CTRL_C)
                type_text(app, "kept")
                now[0] += 0.5
                app._on_input(key)
                self.assertEqual(app.exit_code, 0)
                self.assertEqual(app.composer.text, "kept")

    def test_an_idle_arm_gives_a_rewind_or_a_tell_its_own_keys_and_no_exit(self) -> None:
        now = [100.0]
        app, _client = make_app(clock=lambda: now[0])
        app._on_input(CTRL_C)  # no turn: arms only
        app.rewind = Rewind(row_id=7, ordinal=2, before=())
        app._set_composer("picked prompt")
        self.assertNotIn(EXIT_HINT, info_row_of(drawn(app)))
        now[0] += 0.5
        app._on_input(CTRL_C)
        self.assertIsNone(app.exit_code)

        app, _client = make_app(clock=lambda: now[0])
        app._on_input(CTRL_C)  # no turn: arms only
        app._on_server_request(TELL_APPROVAL)
        armed(app)
        press(app, *[Key(DOWN)] * 3, Key(ENTER))  # the tell row: a field of its own
        self.assertIsNotNone(app.tell_draft)
        self.assertNotIn(EXIT_HINT, info_row_of(drawn(app)))
        app._on_input(CTRL_C)  # on the empty field
        self.assertIsNone(app.exit_code)
        type_text(app, "go left")
        app._on_input(CTRL_C)
        self.assertIsNone(app.exit_code)

    def test_after_an_interrupt_the_second_press_exits_from_a_rewind_or_a_tell_too(self) -> None:
        # The owner's rule (#2302): the press that interrupts arms the exit, and the next within 2 s leaves.
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        app._on_input(CTRL_C)
        app.rewind = Rewind(row_id=7, ordinal=2, before=())
        app._set_composer("picked prompt")
        self.assertIn(EXIT_HINT, info_row_of(drawn(app)))
        now[0] += 0.5
        app._on_input(CTRL_C)
        self.assertEqual((app.exit_code, len(client.named("session.interrupt"))), (0, 1))

        for typed in ("", "go left"):
            with self.subTest(typed=typed):
                app, client = make_app(busy=True, clock=lambda: now[0])
                app._on_server_request(TELL_APPROVAL)
                armed(app)
                press(app, *[Key(DOWN)] * 3, Key(ENTER))  # the tell row: the turn goes on
                app._on_input(CTRL_C)  # on the empty field: interrupts and arms
                self.assertEqual(len(client.named("session.interrupt")), 1)
                self.assertIsNotNone(app.tell_draft)
                self.assertIn(EXIT_HINT, info_row_of(drawn(app)))
                type_text(app, typed)
                app._on_input(CTRL_C)
                self.assertEqual((app.exit_code, len(client.named("session.interrupt"))), (0, 1))
