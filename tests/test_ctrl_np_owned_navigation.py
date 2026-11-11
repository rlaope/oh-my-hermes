"""Ctrl-N/P at the prompt, list, pager and standalone picker boundaries."""
from __future__ import annotations

import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.commands import setup, theme_picker
from omh.tui.bot_board import BoardSnapshot, BoardView, BotBoard, SessionRow
from omh.tui.dag_pager import DagPager
from omh.tui.keys import CHAR, Key
from omh.tui.pager import Pager
from omh.tui.style import Span
from test_tui_prompts import APPROVAL, CLARIFY, slot
from test_tui_agent_view import agent_app
from test_tui_dag_tree import tree_app


def ctrl(char: str, **modifiers: bool) -> Key:
    return Key(CHAR, char, ctrl=True, **modifiers)


class PromptNavigationTests(unittest.TestCase):
    def test_controls_move_and_clamp_without_answering(self):
        for method, params in (("approval", APPROVAL), ("clarify", CLARIFY)):
            with self.subTest(method=method):
                prompt = slot(method, params)
                self.assertIsNone(prompt.handle_key(ctrl("n")))
                self.assertEqual(prompt.selected, 1)
                self.assertIsNone(prompt.handle_key(ctrl("p")))
                self.assertEqual(prompt.selected, 0)
                prompt.handle_key(ctrl("p"))
                self.assertEqual(prompt.selected, 0)
                last = len(prompt.approval_choices()) - 1 if method == "approval" else 2
                for _ in range(10):
                    self.assertIsNone(prompt.handle_key(ctrl("n")))
                self.assertEqual(prompt.selected, last)

    def test_modified_controls_neither_move_nor_answer(self):
        for method, params in (("approval", APPROVAL), ("clarify", CLARIFY)):
            for char in "np":
                for modifiers in ({"alt": True}, {"shift": True}, {"alt": True, "shift": True}):
                    with self.subTest(method=method, char=char, modifiers=modifiers):
                        prompt = slot(method, params)
                        prompt.selected = 1
                        self.assertIsNone(prompt.handle_key(ctrl(char, **modifiers)))
                        self.assertEqual(prompt.selected, 1)
                        self.assertFalse(prompt.typing)

    def test_clarify_controls_return_to_list_and_preserve_draft(self):
        for char, expected in (("n", 2), ("p", 1)):
            prompt = slot("clarify", CLARIFY)
            prompt.handle_key(Key(CHAR, "z"))
            prompt.draft = "keep this"
            self.assertTrue(prompt.typing)
            for modifiers in ({"alt": True}, {"shift": True}):
                prompt.handle_key(ctrl(char, **modifiers))
                self.assertTrue(prompt.typing)
            prompt.handle_key(ctrl(char))
            self.assertFalse(prompt.typing)
            self.assertEqual(prompt.selected, expected)
            self.assertEqual(prompt.draft, "keep this")


class PagerNavigationTests(unittest.TestCase):
    def test_controls_scroll_one_line_and_reject_extra_modifiers(self):
        for pager_type in (Pager, DagPager):
            with self.subTest(pager=pager_type):
                pager = pager_type("test", [(Span(str(i)),) for i in range(30)], top=5)
                for char in "np":
                    for modifiers in ({"alt": True}, {"shift": True}, {"alt": True, "shift": True}):
                        self.assertTrue(pager.handle_key(ctrl(char, **modifiers), 8))
                        self.assertEqual(pager.top, 5)
                self.assertTrue(pager.handle_key(ctrl("n"), 8))
                self.assertEqual(pager.top, 6)
                self.assertTrue(pager.handle_key(ctrl("p"), 8))
                self.assertEqual(pager.top, 5)
                pager.top = 0
                pager.handle_key(ctrl("p"), 8)
                self.assertEqual(pager.top, 0)
                pager.top = pager._last_top(8)
                pager.handle_key(ctrl("n"), 8)
                self.assertEqual(pager.top, pager._last_top(8))

    def test_dag_plain_np_still_select_boxes_not_lines(self):
        pager = DagPager("dag", [(Span(str(i)),) for i in range(30)], top=5, node="a")
        pager._boxes = (("a", 0, 2), ("b", 3, 5))
        pager.handle_key(ctrl("n"), 8)
        self.assertEqual((pager.node, pager.top), ("a", 6))
        pager.handle_key(Key(CHAR, "n"), 8)
        self.assertEqual((pager.node, pager.top), ("b", 6))
        pager.handle_key(Key(CHAR, "p"), 8)
        self.assertEqual((pager.node, pager.top), ("a", 6))


class BoardNavigationTests(unittest.TestCase):
    def test_profile_and_session_lists_move_clamp_and_reject_modifiers(self):
        for view in (BoardView(), BoardView(profile="default")):
            with self.subTest(view=view):
                board = BotBoard("bots", view=view)
                board.take(BoardSnapshot(view, tuple(SimpleNamespace(name=str(i)) for i in range(3)),
                                         tuple(SessionRow(str(i), str(i), "cli", 0, 0) for i in range(3))))
                index = "session_index" if view.profile else "profile_index"
                board.handle_key(ctrl("n"), 8)
                self.assertEqual(getattr(board, index), 1)
                for char in "np":
                    for modifiers in ({"alt": True}, {"shift": True}, {"alt": True, "shift": True}):
                        board.handle_key(ctrl(char, **modifiers), 8)
                        self.assertEqual(getattr(board, index), 1)
                board.handle_key(ctrl("p"), 8)
                self.assertEqual(getattr(board, index), 0)
                board.handle_key(ctrl("p"), 8)
                self.assertEqual(getattr(board, index), 0)
                for _ in range(5):
                    board.handle_key(ctrl("n"), 8)
                self.assertEqual(getattr(board, index), 2)


class AgentEntryTests(unittest.TestCase):
    def test_only_unmodified_ctrl_n_enters_from_empty_composer(self):
        for factory, selected in ((agent_app, "list_selected"), (tree_app, "tree_selected")):
            with self.subTest(selected=selected):
                app, _client = factory()
                for key in (ctrl("j"), ctrl("p"), ctrl("n", alt=True), ctrl("n", shift=True), Key(CHAR, "n")):
                    self.assertFalse(app._agent_list_key(key))
                    self.assertIsNone(getattr(app, selected))
                self.assertTrue(app._agent_list_key(ctrl("n")))
                self.assertIsNotNone(getattr(app, selected))

    def test_ctrl_n_does_not_take_nonempty_composer_or_open_menu(self):
        for factory in (agent_app, tree_app):
            app, _client = factory()
            app.composer.replace(0, 0, "draft")
            self.assertFalse(app._agent_list_key(ctrl("n")))
            app.composer.replace(0, len(app.composer.text), "")
            with patch.object(app, "_menu_rows", return_value=1):
                self.assertFalse(app._agent_list_key(ctrl("n")))


class AppOwnershipTests(unittest.TestCase):
    def test_text_answers_keep_readline_controls_but_clarify_can_return_to_choices(self):
        from omh.tui.app import _slot_owns

        for method in ("clarify", "secret", "sudo", "vault.code"):
            prompt = slot(method, CLARIFY if method == "clarify" else {})
            prompt.typing = True
            for char in "jk":
                self.assertFalse(_slot_owns(prompt, ctrl(char), "draft"))
            for char in "np":
                self.assertEqual(_slot_owns(prompt, ctrl(char), "draft"), method == "clarify")
                for modifiers in ({"alt": True}, {"shift": True}, {"reported_shift": True}):
                    self.assertFalse(_slot_owns(prompt, ctrl(char, **modifiers), "draft"))

    def test_waiting_picker_only_arms_on_navigation_controls_not_readline_edits(self):
        from test_tui_shortcuts import make_app
        from omh.tui.session_picker import SessionPicker

        app, _client = make_app()
        app.picker = SessionPicker([], current="")
        for char in "jk":
            app.picker.waiting = True
            self.assertFalse(app._picker_arms(ctrl(char)))
            self.assertTrue(app.picker.waiting)
        for char in "np":
            for modifiers in ({"alt": True}, {"shift": True}, {"reported_shift": True}):
                app.picker.waiting = True
                self.assertFalse(app._picker_arms(ctrl(char, **modifiers)))
                self.assertTrue(app.picker.waiting)
            self.assertTrue(app._picker_arms(ctrl(char)))
            self.assertFalse(app.picker.waiting)

    def test_model_picker_adapter_accepts_only_unmodified_controls(self):
        from omh.tui.app import picker_key

        for char, expected in (("n", theme_picker.KEY_DOWN), ("p", theme_picker.KEY_UP)):
            self.assertEqual(picker_key(ctrl(char)), expected)
            for modifiers in ({"alt": True}, {"shift": True}, {"reported_shift": True}):
                self.assertEqual(picker_key(ctrl(char, **modifiers)), theme_picker.KEY_NONE)
        for char in "jk":
            self.assertEqual(picker_key(ctrl(char)), theme_picker.KEY_NONE)


class PickerNavigationTests(unittest.TestCase):
    def test_shared_theme_chain_vocabulary(self):
        self.assertEqual(theme_picker.plain_key("\x0e"), theme_picker.KEY_DOWN)
        self.assertEqual(theme_picker.plain_key("\x10"), theme_picker.KEY_UP)
        for key in ("n", "p", "\x1b\x0e", "\x1b\x10", "\x1b[110;6u", "\x1b[112;6u"):
            self.assertEqual(theme_picker.plain_key(key), theme_picker.KEY_NONE)

    def test_setup_single_and_multi_controls_and_modified_sequences(self):
        options = [{"choice": str(i), "value": str(i), "label": str(i), "description": ""} for i in range(1, 4)]
        for keys, expected in ((["\x0e"], "2"), (["\x10"], "3"), (["\x0e", "\x10"], "1"),
                               (["\x1b\x0e", "\x1b\x10", "\x1b[110;6u", "\x1b[112;6u"], "1")):
            with self.subTest(keys=keys), patch.object(setup.sys, "stdout", io.StringIO()):
                with patch.object(setup, "_read_tui_key", side_effect=[*keys, "\r"]):
                    self.assertEqual(setup._keyboard_single_choice("pick", [], options, default_choice="1", use_color=False), expected)
                with patch.object(setup, "_read_tui_key", side_effect=[*keys, " ", "\r"]):
                    self.assertEqual(setup._keyboard_multi_choice("pick", [], options, set(), use_color=False), [expected])


if __name__ == "__main__":
    unittest.main()
