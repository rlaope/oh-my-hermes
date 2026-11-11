"""LV-1–LV-6: line VISUAL acceptance; no gv or block selection."""
from pathlib import Path
import unittest

from test_tui_vim_mode import (
    CHIP, CHIP_TEXT, ESC, FAMILY, Composer, keys, normal, state,
    VIM_INSERT, VIM_NORMAL,
)
from test_tui_vim_character_visual import (
    VIEWPORTS, selected_text, snapshot, vim_app,
)
from test_tui_modes import SID, type_text
from omh.tui.keys import CHAR, ENTER, ESCAPE, Key, Paste
from omh.tui.screen import CURSOR_SHAPE_BLOCK


class TestLV(unittest.TestCase):
    def assert_clear(self, c):
        self.assertFalse(c.visual)
        self.assertFalse(c.visual_line)
        self.assertEqual((c.visual_anchor, c.visual_head, c.visual_span), (None, None, None))
        self.assertFalse(c.pending)

    def assert_line(self, c, anchor, head, span):
        self.assertTrue(c.visual)
        self.assertTrue(c.visual_line)
        self.assertEqual(c.vim_label, "VISUAL LINE")
        self.assertEqual((c.visual_anchor, c.visual_head, c.visual_span), (anchor, head, span))

    def test_entry(self):
        for count in ("", "9", "999999"):
            c = normal("abc\ndef\nghi", 5)
            before = snapshot(c)
            keys(c, count + "V")
            self.assert_line(c, 5, 5, (4, 8))
            keys(c, "k")
            self.assert_line(c, 5, 1, (0, 8))
            keys(c, "v")
            self.assertFalse(c.visual_line)
            self.assertEqual((c.visual_anchor, c.visual_head, c.visual_span), (5, 1, (1, 6)))
            keys(c, "V")
            self.assert_line(c, 5, 1, (0, 8))
            keys(c, "V")
            self.assert_clear(c)
            self.assertEqual(c.caret, 1)
            self.assertEqual(snapshot(c)[:1] + snapshot(c)[2:], before[:1] + before[2:])
        for c in (Composer(), Composer(vim=True), Composer(vim=True, masked=True)):
            keys(c, "V")
            self.assertEqual(c.text, "V")
            self.assertFalse(c.visual)

    def test_boundaries(self):
        for text, caret, span, register in (
            ("", 0, (0, 0), ""), ("a\n", 2, (2, 2), ""),
            ("a\n\nb", 2, (2, 3), ""), ("a\nb", 2, (2, 3), "b"),
            ("only", 2, (0, 4), "only"), ("a\nb\nc", 0, (0, 2), "a"),
        ):
            with self.subTest(text=text, caret=caret):
                c = normal(text, caret)
                keys(c, "V")
                self.assert_line(c, caret, caret, span)
                keys(c, "y")
                self.assert_clear(c)
                self.assertEqual(c.text, text)
                self.assertEqual(c._register.text, register)
                self.assertTrue(c._register.linewise)
        c = Composer(vim=True)
        c.handle(Paste(CHIP_TEXT))
        c.handle(ESC)
        keys(c, "0Vy")
        self.assertEqual(c._register.text, CHIP)
        self.assertEqual(c._register.pastes, {CHIP: CHIP_TEXT})

    def test_motion_viewport(self):
        text = "0123456789abcdefghijKLMNOPQRST\nuvwxyz"
        for width, height, head, span, highlight, caret in (
            (20, 8, 20, (0, 31), "0123456789abcdefghijKLMNOPQRST␊", (1, 4)),
            (100, 30, 33, (0, 37), "0123456789abcdefghijKLMNOPQRST␊uvwxyz ", (1, 4)),
        ):
            with self.subTest(width=width):
                c = normal(text, 2)
                c.history = ["MUST NOT LOAD"]
                c.render(width, height, prompt="> ")
                keys(c, "Vj")
                self.assert_line(c, 2, head, span)
                lines, actual_caret = c.render(width, height, prompt="> ")
                self.assertEqual(selected_text(lines), highlight)
                self.assertEqual(actual_caret, caret)
                endpoints = c.visual_anchor, c.visual_head, c.visual_span
                c.render(100 if width == 20 else 20, height)
                self.assertEqual((c.visual_anchor, c.visual_head, c.visual_span), endpoints)
                keys(c, "999999k")
                self.assertIsNone(c.history_index)
                self.assertEqual(c.text, text)

    def test_operators(self):
        for command, expected, register, caret in (
            ("Vd", "a\n  c", "  b", 4),
            ("V9d", "a\n  c", "  b", 4),
            ("Vkd", "  c", "a\n  b", 2),
            ("VGd", "a", "  b\n  c", 0),
            ("Vggd", "  c", "a\n  b", 2),
        ):
            c = normal("a\n  b\n  c", 4)
            depth = len(c._undo)
            keys(c, command)
            self.assertEqual(state(c), (expected, caret, VIM_NORMAL))
            self.assertEqual((c._register.text, c._register.linewise), (register, True))
            self.assert_clear(c)
            self.assertEqual(len(c._undo), depth + 1)
            keys(c, "u")
            self.assertEqual(c.text, "a\n  b\n  c")
        for text, caret, expected in (("a\nb", 2, "a"), ("only", 0, ""), ("a\n", 2, "a")):
            c = normal(text, caret)
            keys(c, "Vd")
            self.assertEqual(c.text, expected)
        c = normal("a\nb\nc", 2)
        depth = len(c._undo)
        keys(c, "V9c")
        self.assertEqual(state(c), ("a\n\nc", 2, VIM_INSERT))
        keys(c, "XY")
        c.handle(ESC)
        self.assertEqual(c.text, "a\nXY\nc")
        self.assertEqual(len(c._undo), depth + 1)
        keys(c, "u")
        self.assertEqual(c.text, "a\nb\nc")
        c.handle(Key(CHAR, "r", ctrl=True))
        self.assertEqual(c.text, "a\nXY\nc")
        c = normal("abc\n  def", 0)
        keys(c, "x")
        repeat, undo = c._repeat_change, list(c._undo)
        keys(c, "GVy")
        self.assertEqual(state(c), ("bc\n  def", 5, VIM_NORMAL))
        self.assertIs(c._repeat_change, repeat)
        self.assertEqual(c._undo, undo)

    def test_render(self):
        for width, height in VIEWPORTS:
            for text, at, highlight in (("a\n\nb", 2, "␊"), ("a\n", 0, "a␊"), ("a\nb", 2, "b "), ("", 0, " "), ("a\n", 2, " ")):
                c = normal(text, at)
                keys(c, "V")
                lines, _ = c.render(width, height, prompt="> ")
                self.assertEqual(selected_text(lines), highlight)
                self.assertEqual(c.text, text)
        app, client, _ = vim_app()
        type_text(app, "abc")
        app._on_input(ESC)
        type_text(app, "V")
        app._render()
        self.assertEqual(app.terminal.cursor_shape, CURSOR_SHAPE_BLOCK)
        self.assertIn("VISUAL LINE", "".join(app.terminal.writes))
        self.assertEqual(client.calls, [])

    def test_repeat(self):
        for width, height in VIEWPORTS:
            c = normal("a\nb\nc\nd\ne\nf\ng\nh\ni", 2)
            c.render(width, height)
            keys(c, "Vkd")
            self.assertEqual(c.text, "c\nd\ne\nf\ng\nh\ni")
            saved = c._repeat_change
            keys(c, "2gg2.")
            self.assertEqual(c.text, "c\nh\ni")
            self.assertEqual(c._repeat_change, saved)
            keys(c, ".")
            self.assertEqual(c.text, "c")
            keys(c, "u")
            self.assertEqual(c.text, "c\nh\ni")
        c = normal("a\nb\nc\nd", 2)
        keys(c, "VcXY")
        c.handle(ESC)
        keys(c, "G.")
        self.assertEqual(c.text, "a\nXY\nc\nXY")
        keys(c, "u")
        self.assertEqual(c.text, "a\nXY\nc\nd")

    def test_atoms(self):
        c = Composer(vim=True)
        c.handle(Paste(CHIP_TEXT))
        image = object()
        c.insert_image("[Image #1]", image)
        keys(c, "é" + FAMILY)
        c.handle(ESC)
        original = c.text, dict(c.pastes), dict(c.images)
        keys(c, "0Vd")
        self.assertEqual((c.text, c.pastes, c.images), ("", {}, {}))
        self.assertTrue(c._register.linewise)
        keys(c, "u")
        self.assertEqual((c.text, c.pastes, c.images), original)
        keys(c, "0Vypp")
        self.assertEqual(c.expanded().count(CHIP_TEXT), 3)
        self.assertEqual(len(c.images), 3)
        self.assertTrue(all(payload[1] is image for payload in c.images.values()))

    def test_lifetime(self):
        for reset in (
            lambda c: c._clear(), lambda c: c.replace(0, len(c.text), "new"),
            lambda c: c.restore("new", []), lambda c: c.set_vim(False),
            lambda c: c.set_vim(True), lambda c: c.handle(Paste("Q")),
            lambda c: c.insert_image("[Image #1]", object()), lambda c: c._history_back(),
        ):
            c = normal("abc\ndef", 0)
            c.history = ["old"]
            keys(c, "VvVg")
            reset(c)
            self.assert_clear(c)
        c = normal("abc", 0)
        keys(c, "xV")
        keys(c, "u")
        self.assert_clear(c)
        self.assertEqual(c.text, "abc")
        keys(c, "Vg")
        c.handle(Key(CHAR, "r", ctrl=True))
        self.assert_clear(c)
        self.assertEqual(c.text, "bc")

    def test_routing(self):
        for busy in (False, True):
            for prefix in ("", "g", "f"):
                app, client, clock = vim_app(busy=busy)
                type_text(app, "abc")
                app._on_input(ESC)
                type_text(app, "0V" + prefix)
                app.escape_armed = ("exit", clock.now)
                app._on_input(Key(ENTER))
                self.assert_clear(app.composer)
                self.assertIsNone(app.escape_armed)
                if busy:
                    self.assertEqual([line.text for line in app.queued], ["abc"])
                    self.assertEqual(client.calls, [])
                else:
                    self.assertEqual(client.named("prompt.submit")[-1]["text"], "abc")
            app, client, _ = vim_app(busy=busy)
            type_text(app, "abc")
            app._on_input(ESC)
            type_text(app, "0Vg")
            escape = Key(ESCAPE, alt=True, protocol=True)
            app._on_input(escape)
            self.assertTrue(app.composer.visual_line)
            self.assertFalse(app.composer.pending)
            app._on_input(escape)
            self.assert_clear(app.composer)
            self.assertEqual(client.calls, [])

    def test_routing_clipboard(self):
        for prefix in ("", "g", "f", "F", "t", "T"):
            app, client, _ = vim_app(environ={"NO_COLOR": "1"})
            type_text(app, "abc")
            app._on_input(ESC)
            type_text(app, "0Vl" + prefix)
            app._on_input(Key(CHAR, "v", ctrl=True))
            self.assert_clear(app.composer)
            self.assertEqual(client.calls, [("clipboard.paste", {"session_id": SID})])
            self.assertEqual(app.composer.text, "abc")

    def test_repeat_rejection_is_atomic(self):
        from contextlib import ExitStack
        from functools import partial
        from unittest import mock
        from omh.tui.vim_repeat import Limits, preflight
        c = normal("a\nb\nc", 2)
        keys(c, "Vc" + "Z" * 257)
        c.handle(ESC)
        c.caret = 0
        before = snapshot(c)
        keys(c, "9999")
        with ExitStack() as stack:
            stack.enter_context(mock.patch("omh.tui.vim_repeat.preflight",
                wraps=partial(preflight, limits=Limits(materialized_bytes=256))))
            for method in ("_state", "_new_token", "_set"):
                stack.enter_context(mock.patch.object(Composer, method,
                    side_effect=AssertionError("allocation before admission: " + method)))
            keys(c, ".")
        self.assertEqual(snapshot(c), before)
        self.assertFalse(c.pending)
        self.assertTrue(c.take_bell())
        self.assertFalse(c.take_bell())

    def test_docs(self):
        from omh.tui.shortcuts import SHORTCUTS
        doc = (Path(__file__).resolve().parents[1] / "docs/INSTALLATION.md").read_text()
        for text in ("VISUAL LINE", "hard-line count", "v/V", "linewise"):
            self.assertIn(text, dict(SHORTCUTS)["Esc (vim mode)"])
            self.assertIn(text, doc)

    def test_pty(self):
        from _vim_line_pty import assert_line_visual_pty
        assert_line_visual_pty(self)


if __name__ == "__main__":
    unittest.main()
