"""Composer undo and redo (Ctrl+_ and Ctrl+Y), and Ctrl+X for the session picker (parity P9).

Ctrl+_ is the byte 0x1F, which Ctrl+-, Ctrl+/ and Ctrl+7 send on most
terminals, and Claude Code's undo key; a terminal that reports keys in the
kitty protocol reports Ctrl+- as itself, so that counts too. Ctrl+Y is
Ink's redo key; the composer has no yank for it to collide with.
"""

from __future__ import annotations

import unittest

from test_tui_modes import make_app, type_text
from omh.tui.app import SESSION_LIST_LIMIT
from omh.tui.composer import Composer
from omh.tui.keys import BACKSPACE, CHAR, ENTER, ESCAPE, LEFT, UP, Key, KeyDecoder, Paste

UNDO = Key(CHAR, "_", ctrl=True)
REDO = Key(CHAR, "y", ctrl=True)


def typed(composer: Composer, text: str) -> None:
    for char in text:
        composer.handle(Key(CHAR, char))


class UndoTests(unittest.TestCase):
    def test_a_run_of_typed_characters_is_one_edit(self) -> None:
        composer = Composer()
        typed(composer, "hello")
        composer.handle(UNDO)
        self.assertEqual((composer.text, composer.caret), ("", 0))
        composer.handle(REDO)
        self.assertEqual((composer.text, composer.caret), ("hello", 5))

    def test_each_other_edit_is_its_own_step_and_the_caret_comes_back(self) -> None:
        composer = Composer()
        typed(composer, "one two")
        composer.handle(Key(BACKSPACE))
        composer.handle(Key(CHAR, "w", ctrl=True))  # the word before the caret
        self.assertEqual(composer.text, "one ")
        composer.handle(UNDO)
        self.assertEqual(composer.text, "one tw")
        composer.handle(UNDO)
        self.assertEqual((composer.text, composer.caret), ("one two", 7))
        composer.handle(UNDO)
        self.assertEqual(composer.text, "")
        composer.handle(UNDO)  # nothing older: nothing changes
        self.assertEqual(composer.text, "")

    def test_typing_after_a_caret_move_starts_a_new_step(self) -> None:
        composer = Composer()
        typed(composer, "ab")
        composer.handle(Key(LEFT))
        typed(composer, "X")
        self.assertEqual(composer.text, "aXb")
        composer.handle(UNDO)
        self.assertEqual((composer.text, composer.caret), ("ab", 1))

    def test_a_new_edit_drops_what_redo_had(self) -> None:
        composer = Composer()
        typed(composer, "abc")
        composer.handle(UNDO)
        typed(composer, "z")
        composer.handle(REDO)
        self.assertEqual(composer.text, "z")

    def test_a_cleared_draft_comes_back_with_its_paste_chip(self) -> None:
        composer = Composer()
        composer.handle(Paste("one\ntwo\nthree\nfour\nfive"))
        typed(composer, " and")
        chips = dict(composer.pastes)
        composer.handle(Key(CHAR, "c", ctrl=True))  # Ctrl+C clears the draft
        self.assertEqual(composer.text, "")
        composer.handle(UNDO)
        self.assertEqual(dict(composer.pastes), chips)
        self.assertEqual(composer.expanded(), "one\ntwo\nthree\nfour\nfive and")

    def test_a_sent_line_cannot_be_undone_back(self) -> None:
        composer = Composer()
        typed(composer, "sent")
        composer.handle(Key(ENTER))
        composer.handle(UNDO)
        self.assertEqual(composer.text, "")

    def test_an_edit_the_app_makes_is_a_step_too(self) -> None:
        composer = Composer()
        typed(composer, "draft")
        composer.replace(0, len(composer.text), "")
        composer.handle(UNDO)
        self.assertEqual(composer.text, "draft")

    def test_masked_input_keeps_no_steps(self) -> None:
        composer = Composer(masked=True)
        typed(composer, "hunter2")
        composer.handle(UNDO)
        self.assertEqual(composer.text, "hunter2")

    def test_the_keys_terminals_send_for_undo(self) -> None:
        for data in (b"\x1f", b"\x1b[45;5u", b"\x1b[47;5u"):  # Ctrl+_ (and Ctrl+- / Ctrl+/), kitty Ctrl+-, kitty Ctrl+/
            with self.subTest(data=data):
                composer = Composer()
                typed(composer, "x")
                for event in KeyDecoder().feed(data):
                    composer.handle(event)
                self.assertEqual(composer.text, "")


class AppUndoTests(unittest.TestCase):
    def test_esc_esc_cleared_text_comes_back_with_undo(self) -> None:
        app, _client = make_app()
        type_text(app, "a long draft")
        app._on_input(Key(ESCAPE))
        app._on_input(Key(ESCAPE))
        self.assertEqual(app.composer.text, "")
        app._on_input(UNDO)
        self.assertEqual(app.composer.text, "a long draft")

    def test_history_browsing_then_undo_returns_to_the_draft(self) -> None:
        app, _client = make_app()
        app.composer.history = ["older"]
        type_text(app, "mine")
        app._on_input(Key(UP))
        self.assertEqual(app.composer.text, "older")
        app._on_input(UNDO)
        self.assertEqual(app.composer.text, "mine")


class CtrlXTests(unittest.TestCase):
    def test_ctrl_x_asks_for_the_stored_sessions_as_sessions_does(self) -> None:
        by_key, key_client = make_app()
        by_key._on_input(Key(CHAR, "x", ctrl=True))
        by_command, command_client = make_app()
        type_text(by_command, "/sessions")
        by_command._on_input(Key(ENTER))
        self.assertEqual(key_client.calls, command_client.calls)
        self.assertEqual(key_client.calls[0][0], "session.list")
        self.assertEqual(by_key.composer.text, "")

    def test_ctrl_x_opens_the_all_profile_table(self) -> None:
        app, client = make_app()
        app._on_input(Key(CHAR, "x", ctrl=True))
        self.assertIsNotNone(app.picker)
        self.assertIsNotNone(app.picker.profiles)
        self.assertEqual(client.calls[0], ("session.list", {"limit": SESSION_LIST_LIMIT}))

    def test_resume_opens_the_all_profile_table(self) -> None:
        app, client = make_app()
        type_text(app, "/resume")
        app._on_input(Key(ENTER))
        self.assertIsNotNone(app.picker)
        self.assertIsNotNone(app.picker.profiles)
        self.assertEqual(client.calls[0], ("session.list", {"limit": SESSION_LIST_LIMIT}))
        self.assertEqual(app.composer.text, "")

    def test_ctrl_x_keeps_the_draft_underneath(self) -> None:
        app, client = make_app()
        type_text(app, "half written")
        app._on_input(Key(CHAR, "x", ctrl=True))
        self.assertEqual(app.composer.text, "half written")
        self.assertEqual(client.calls[0][0], "session.list")


if __name__ == "__main__":
    unittest.main()
