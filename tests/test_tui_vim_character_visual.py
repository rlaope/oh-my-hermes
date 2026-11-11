"""Slice04 / CV-1..CV-8: literal character-VISUAL acceptance oracles.

Expected atom endpoints, spans, text and visible highlights are authored here,
not obtained from production motion/range resolvers. No V/gv contract is tested.
The PTY rollback journey reuses the real operator PTY runner, not a fake TTY.
"""
from __future__ import annotations

from contextlib import ExitStack
from functools import partial
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_tui_vim_mode import (
    CHIP, CHIP_TEXT, CLARIFY, ESC, FAMILY, keys, normal, state, vim_app as _vim_app,
)
from test_tui_modes import SID, RecordingClient, answer, type_text
from typing import cast
from omh.tui.composer import Composer, SUBMIT, VIM_INSERT, VIM_NORMAL
from omh.tui.gateway import ServerRequest
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, Key, Paste
from omh.tui.screen import CURSOR_SHAPE_BLOCK
from omh.tui.session_picker import SessionPicker, SessionRow
from omh.tui.style import Style
from omh.tui.width import line_width


VIEWPORTS = ((20, 8), (100, 30))


def vim_app(**options):
    app, client, clock = _vim_app(**options)
    return app, cast(RecordingClient, client), clock


def selection(c):
    return c.visual, c.visual_anchor, c.visual_head, c.visual_span


def selected_text(lines, *, background=None):
    """Observe emitted spans, independently of selection's logical range."""
    return "".join(span.text for line in lines for span in line
                   if (span.style.reverse if background is None else span.style.bg == background))


def snapshot(c):
    return (c.text, c.caret, dict(c.pastes), dict(c.images), list(c._undo),
            list(c._redo), c._register, c._repeat_change, c._token_count)


class TestCV(unittest.TestCase):
    def assert_clear(self, c):
        self.assertEqual(selection(c), (False, None, None, None))
        self.assertFalse(c.pending)

    def assert_selection(self, c, anchor, head, span):
        self.assertEqual(selection(c), (True, anchor, head, span))
        self.assertEqual(c.vim_label, "VISUAL")
        self.assertIn(c.caret, c._atoms()[1])

    def test_entry(self):
        """CV-1: one atom, toggle/cancel, count consumption, EOF sentinel."""
        from omh.tui.composer import VIM_VISUAL
        self.assertEqual(VIM_VISUAL, "VISUAL")
        for count in ("", "9", "999999"):
            with self.subTest(count=count):
                c = normal("abc", 1)
                before = snapshot(c)
                keys(c, count + "v")
                self.assert_selection(c, 1, 1, (1, 2))
                keys(c, "v")
                self.assert_clear(c)
                self.assertEqual(state(c), ("abc", 1, VIM_NORMAL))
                self.assertEqual(snapshot(c), before)
                keys(c, "vl")
                self.assert_selection(c, 1, 2, (1, 3))
                c.handle(ESC)
                self.assert_clear(c)
                self.assertEqual(state(c), ("abc", 2, VIM_NORMAL))
        for text, caret, atom in (("", 0, 0), ("a\n", 2, 2)):
            for operator in ("d", "y", "c"):
                with self.subTest(text=text, operator=operator):
                    c = normal(text, caret)
                    undo = list(c._undo)
                    keys(c, "v")
                    self.assert_selection(c, atom, atom, (caret, caret))
                    keys(c, operator)
                    self.assert_clear(c)
                    self.assertEqual(c.text, text)
                    self.assertEqual(c._undo, undo)
                    if operator == "c":
                        self.assertEqual(c.vim_label, VIM_INSERT)
                        keys(c, "Z")
                        c.handle(ESC)
                        keys(c, "u")
                        self.assertEqual(c.text, text)
        for c in (Composer(), Composer(vim=True), Composer(vim=True, masked=True)):
            keys(c, "v")
            self.assertEqual(c.text, "v")
            self.assertFalse(c.visual)

    def test_motion(self):
        """CV-2: literal motion endpoints, independent at both viewports."""
        cases = (
            ("abc def", 1, "h", 0, (0, 2)),
            ("abc def", 1, "2l", 3, (1, 4)),
            ("  abc def", 4, "0", 0, (0, 5)),
            ("  abc def", 4, "^", 2, (2, 5)),
            ("abc def", 1, "$", 6, (1, 7)),
            ("one two! three", 0, "w", 4, (0, 5)),
            ("one two! three", 0, "2w", 7, (0, 8)),
            ("one two! three", 0, "2W", 9, (0, 10)),
            ("one two! three", 9, "b", 7, (7, 10)),
            ("one two! three", 9, "B", 4, (4, 10)),
            ("one two! three", 4, "e", 6, (4, 7)),
            ("one two! three", 4, "E", 7, (4, 8)),
            ("one two! three", 9, "ge", 7, (7, 10)),
            ("one two! three", 9, "gE", 7, (7, 10)),
            ("abc\ndef\nghi", 5, "gg", 0, (0, 6)),
            ("abc\ndef\nghi", 1, "G", 8, (1, 9)),
            ("abacad", 0, "fc", 3, (0, 4)),
            ("abacad", 5, "Fa", 4, (4, 6)),
            ("abacad", 0, "tc", 2, (0, 3)),
            ("abacad", 5, "Ta", 5, (5, 6)),
            ("abacad", 0, "fa;", 4, (0, 5)),
            ("abacad", 0, "fa;,", 2, (0, 3)),
            ("abc", 0, "999999l", 2, (0, 3)),
        )
        for width, height in VIEWPORTS:
            for text, start, motion, head, span in cases:
                with self.subTest(size=(width, height), motion=motion, start=start):
                    c = normal(text, start)
                    c.render(width, height)
                    keys(c, "v" + motion)
                    self.assert_selection(c, start, head, span)
                    self.assertEqual(c.caret, head)  # ASCII-only literal fixture
                    self.assertEqual(c.text, text)
            for command in ("fz", "g?", "z", "x", "p", "i", "a", "r", "o"):
                c = normal("abc", 1)
                keys(c, "v" + command)
                self.assert_selection(c, 1, 1, (1, 2))
                self.assertFalse(c.pending)
                self.assertEqual(c.text, "abc")

    def test_motion_viewport(self):
        """CV-2: rendered j/k have viewport-specific, not copied, oracles."""
        text = "0123456789abcdefghijKLMNOPQRST\nuvwxyz"
        # Prompt '> ' leaves 18/98 cells. First j lands on row two at
        # narrow width and on the second hard line at wide width.
        for width, height, head, span, highlighted in (
            (20, 8, 20, (2, 21), "23456789abcdefghijK"),
            (100, 30, 33, (2, 34), "23456789abcdefghijKLMNOPQRST␊uvw"),
        ):
            with self.subTest(size=(width, height)):
                c = normal(text, 2)
                c.history = ["MUST NOT LOAD HISTORY"]
                c.render(width, height, prompt="> ")
                keys(c, "vj")
                self.assert_selection(c, 2, head, span)
                lines, caret = c.render(width, height, prompt="> ")
                self.assertEqual(selected_text(lines), highlighted)
                self.assertEqual(caret, (1, 4))
                keys(c, "k")
                self.assert_selection(c, 2, 2, (2, 3))
                keys(c, "9999k")
                self.assert_selection(c, 2, 2, (2, 3))
                self.assertIsNone(c.history_index)
                self.assertEqual(c.text, text)
                keys(c, "9999j")
                self.assert_selection(c, 2, 33, (2, 34))
                self.assertIsNone(c.history_index)
                self.assertEqual(c.text, text)
        c = normal(text, 2)
        c.render(20, 8, prompt="> ")
        keys(c, "vj")
        c.render(100, 30, prompt="> ")
        self.assert_selection(c, 2, 20, (2, 21))
        c.render(20, 8, prompt="> ")
        self.assert_selection(c, 2, 20, (2, 21))

    def test_operators(self):
        """CV-3: inclusive d/c/y, normalized low endpoint, one undo."""
        for motion in ("v2l", "2lv2h"):
            for operator in ("d", "c", "y"):
                for count in ("", "9"):
                    with self.subTest(motion=motion, operator=operator, count=count):
                        c = normal("abcdef", 0)
                        undo = len(c._undo)
                        keys(c, motion + count + operator)
                        self.assert_clear(c)
                        self.assertEqual(c._register.text, "abc")
                        self.assertFalse(c._register.linewise)
                        if operator == "y":
                            self.assertEqual(state(c), ("abcdef", 0, VIM_NORMAL))
                            self.assertEqual(len(c._undo), undo)
                        elif operator == "d":
                            self.assertEqual(state(c), ("def", 0, VIM_NORMAL))
                            self.assertEqual(len(c._undo), undo + 1)
                            keys(c, "u")
                            self.assertEqual(c.text, "abcdef")
                        else:
                            self.assertEqual(state(c), ("def", 0, VIM_INSERT))
                            keys(c, "XY")
                            c.handle(ESC)
                            self.assertEqual(c.text, "XYdef")
                            self.assertEqual(len(c._undo), undo + 1)
                            keys(c, "u")
                            self.assertEqual(c.text, "abcdef")
                            c.handle(Key(CHAR, "r", ctrl=True))
                            self.assertEqual(c.text, "XYdef")
        c = normal("abcdef", 0)
        keys(c, "x")
        repeat, undo = c._repeat_change, list(c._undo)
        keys(c, "vly")
        self.assertIs(c._repeat_change, repeat)
        self.assertEqual(c._undo, undo)
        keys(c, ".")
        self.assertEqual(c.text, "cdef")

    def test_render(self):
        """CV-4: exact highlight, whitespace/newline/sentinel, head caret."""
        for width, height in VIEWPORTS:
            with self.subTest(size=(width, height)):
                c = normal("a b\nc", 0)
                keys(c, "v3l")  # l is hard-line local: selects a, space, b
                lines, caret = c.render(width, height, prompt="> ")
                self.assertEqual(selected_text(lines), "a b")
                self.assertEqual(caret, (0, 4))
                self.assertTrue(all(line_width(line) <= width for line in lines))
                c = normal("a\nb", 0)
                keys(c, "vj")  # crosses the newline as well as both letters
                lines, caret = c.render(width, height, prompt="> ")
                self.assertEqual(selected_text(lines), "a␊b")
                self.assertEqual(caret, (1, 2))
                self.assertEqual(c.text, "a\nb")
                keys(c, "y")
                self.assertEqual(c._register.text, "a\nb")
                c = normal("", 0)
                keys(c, "v")
                lines, caret = c.render(width, height, prompt="> ")
                self.assertEqual(selected_text(lines), " ")
                self.assertEqual(caret, (0, 2))
                self.assertEqual(c.text, "")
                c = normal("a b", 2)
                keys(c, "v2h")
                lines, caret = c.render(width, height, prompt="> ")
                self.assertEqual(selected_text(lines), "a b")
                self.assertEqual(caret, (0, 2))
                self.assert_selection(c, 2, 0, (0, 3))
        c = normal("a\tb", 0)
        keys(c, "v2l")
        lines, _ = c.render(100, 30)
        self.assertIn("a", selected_text(lines))
        self.assertIn("b", selected_text(lines))
        self.assertTrue(selected_text(lines)[1:-1].isspace())
        app, _client, _clock = vim_app()
        type_text(app, "abc")
        app._on_input(ESC)
        type_text(app, "v")
        app._render()
        self.assertEqual(app.terminal.cursor_shape, CURSOR_SHAPE_BLOCK)
        self.assertIn("VISUAL", "".join(app.terminal.writes))

    def test_render_style_precedence(self):
        """CV-4/CV-6: opaque labels and overlapping effects stay selected."""
        c = Composer(vim=True)
        c.handle(Paste(CHIP_TEXT))
        image = object()
        c.insert_image("[Image #1]", image)
        c.handle(ESC)
        keys(c, "0vG$")
        style = Style(fg="#eeeeee", bg="#123456")
        for width, height in VIEWPORTS:
            with self.subTest(size=(width, height)):
                lines, _ = c.render(width, height, prompt="> ",
                    chip_style=Style(bg="#654321"), marks=((0, len(c.text)),),
                    mark_style=Style(bg="#456789"), glow=((0, len(c.text)),),
                    glow_style=lambda _at, _length: Style(bg="#789abc"),
                    selection_style=style)
                self.assertTrue(selected_text(lines, background="#123456"))
                for line in lines:
                    for span in line[1:]:
                        if span.text:
                            self.assertEqual(span.style.bg, "#123456")
                self.assertTrue(all(line_width(line) <= width for line in lines))
                if width == 100:
                    self.assertIn(CHIP, selected_text(lines, background="#123456"))
                    self.assertIn("[Image #1]", selected_text(lines, background="#123456"))

    def test_repeat(self):
        """CV-5: normalized forward geometry, count replacement, EOF clamp."""
        for command in ("v2ld", "2lv2hd"):
            with self.subTest(command=command):
                c = normal("abcdefghijkl", 0)
                keys(c, command)
                self.assertEqual(c.text, "defghijkl")
                keys(c, "l2.")
                self.assertEqual(c.text, "dkl")
                keys(c, "u")
                self.assertEqual(c.text, "defghijkl")
                keys(c, "G$.")
                self.assertEqual(c.text, "defghijk")
        c = normal("abcdefghijkl", 0)
        keys(c, "2lv2hcXY")
        c.handle(ESC)
        self.assertEqual(c.text, "XYdefghijkl")
        c.caret = 4
        keys(c, ".")
        self.assertEqual(c.text, "XYdeXYijkl")
        keys(c, "u")
        self.assertEqual(c.text, "XYdefghijkl")
        c = normal("a\nbcdef", 0)
        keys(c, "vjd.")
        self.assertEqual(c.text, "f")  # N=3 includes the newline, twice
        c = normal("abc", 0)
        keys(c, "v$d")
        before = snapshot(c)
        keys(c, ".")
        self.assertEqual(snapshot(c), before)  # empty replay is not an edit

    def test_repeat_rejection_is_atomic(self):
        """CV-5: visual c recipes use admission before snapshot/allocation."""
        c = normal("abcdef", 0)
        keys(c, "vlc" + "Z" * 257)
        c.handle(ESC)
        c.caret = 0
        before = snapshot(c)
        keys(c, "9999")
        from omh.tui.vim_repeat import Limits, preflight
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
        # Legal geometry survives rejection and remains undoable.
        keys(c, ".")
        self.assertEqual(c.text, "Z" * 512 + "cdef")
        keys(c, "u")
        self.assertEqual(snapshot(c)[:4], before[:4])

    def test_atoms(self):
        """CV-6: literal grapheme spans, complete opaque metadata, fresh puts."""
        for width, height in VIEWPORTS:
            with self.subTest(size=(width, height)):
                c = normal("e\u0301" + FAMILY + "界z", 0)
                c.render(width, height)
                keys(c, "vl")
                self.assert_selection(c, 0, 1, (0, 8))  # NFC é + seven-codepoint ZWJ atom
                keys(c, "d")
                self.assertEqual(c.text, "界z")
                self.assertEqual(c._register.text, "é" + FAMILY)
                keys(c, "u")
                self.assertEqual(c.text, "é" + FAMILY + "界z")
        c = Composer(vim=True)
        c.handle(Paste(CHIP_TEXT))
        image = object()
        c.insert_image("[Image #1]", image)
        c.handle(ESC)
        keys(c, "0")
        original = (c.text, dict(c.pastes), dict(c.images))
        keys(c, "v$d")
        self.assertEqual((c.text, c.pastes, c.images), ("", {}, {}))
        self.assertEqual(c._register.pastes, {CHIP: CHIP_TEXT})
        self.assertEqual(len(c._register.images), 1)
        keys(c, "u")
        self.assertEqual((c.text, c.pastes, c.images), original)
        keys(c, "0v$ypp")
        self.assertEqual(c.expanded().count(CHIP_TEXT), 3)
        self.assertEqual(len(c.images), 3)
        self.assertEqual(len(set(c.images)), 3)
        self.assertTrue(all(payload[1] is image for payload in c.images.values()))
        self.assertTrue(all(token in c.text for token in c.images))

    def test_routing(self):
        """CV-7: real App dispatch, Escape tiers, leader/picker/slot owners."""
        for busy in (False, True):
            for escape in (ESC, Key(ESCAPE, alt=True, protocol=True)):
                with self.subTest(busy=busy, escape=escape):
                    app, client, _clock = vim_app(busy=busy)
                    type_text(app, "abc")
                    app._on_input(ESC)
                    type_text(app, "0vlg")
                    app._on_input(escape)
                    self.assert_selection(app.composer, 0, 1, (0, 2))
                    self.assertFalse(app.composer.pending)
                    self.assertIsNone(app.escape_armed)
                    app._on_input(escape)
                    self.assert_clear(app.composer)
                    self.assertEqual(app.composer.caret, 1)
                    self.assertIsNone(app.escape_armed)
                    self.assertEqual(client.calls, [])
        app, client, _clock = vim_app()
        type_text(app, "abc")
        app._on_input(ESC)
        type_text(app, "0v s")
        self.assertFalse(app.composer.leader)
        self.assertEqual(client.calls, [])
        self.assert_selection(app.composer, 0, 0, (0, 1))
        type_text(app, "g")
        app.picker = SessionPicker([SessionRow(SID, "title", "", 0.0, 1)], current=app.stored_id)
        app.picker.waiting = False
        app._on_input(Key(CHAR, "e"))
        self.assertFalse(app.composer.pending)
        self.assertEqual(app.picker.query, "e")
        self.assertEqual(app.composer.text, "abc")
        app, client, _clock = vim_app()
        type_text(app, "abc")
        app._on_input(ESC)
        type_text(app, "0v")
        app.picker = SessionPicker([SessionRow(SID, "title", "", 0.0, 1)],
                                  current=app.stored_id, waiting=True)
        app._on_input(Key(DOWN))
        self.assertFalse(app.picker.waiting)
        self.assertEqual(app.composer.text, "abc")
        app, _client, clock = vim_app()
        type_text(app, "draft")
        app._on_input(ESC)
        type_text(app, "v")
        app._on_server_request(ServerRequest("cv-question", "clarify", CLARIFY))
        clock.now += 1
        type_text(app, "v")
        self.assertEqual(app.composer.text, "v")
        self.assertFalse(app.composer.visual)

    def test_routing_clipboard_and_enter(self):
        """CV-7: Ctrl+V once at head; Enter/steer send the untouched draft."""
        app, client, _clock = vim_app(environ={"NO_COLOR": "1"})
        type_text(app, "abc")
        app._on_input(ESC)
        type_text(app, "0vl")
        app._on_input(Key(CHAR, "v", ctrl=True))
        self.assert_clear(app.composer)
        self.assertEqual(client.calls, [("clipboard.paste", {"session_id": SID})])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clipboard.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\n")
            answer(app, client, {"attached": True, "path": str(path), "name": "clipboard.png"})
        self.assertEqual(len(app.composer.images), 1)
        self.assertEqual(app.composer.expanded(), "a [Image #1] bc")
        self.assertEqual(len(client.named("clipboard.paste")), 1)
        for busy, enter in ((False, Key(ENTER)), (True, Key(ENTER)),
                            (True, Key(ENTER, ctrl=True))):
            with self.subTest(busy=busy, enter=enter):
                app, client, _clock = vim_app(busy=busy)
                type_text(app, "send unmodified")
                app._on_input(ESC)
                type_text(app, "0v2l")
                app._on_input(enter)
                self.assert_clear(app.composer)
                self.assertEqual(app.composer.text, "")
                if busy and not enter.ctrl:
                    self.assertEqual([line.text for line in app.queued], ["send unmodified"])
                    self.assertEqual(client.calls, [])
                else:
                    method = "session.redirect" if busy else "prompt.submit"
                    self.assertEqual(client.named(method)[-1]["text"], "send unmodified")

    def test_routing_visual_shortcuts_and_confirmation(self):
        """CV-7: visual keys never invoke global actions or retain an armed exit."""
        for busy in (False, True):
            for command in ("0v", "0vg", "0vf"):
                app, client, _clock = vim_app(busy=busy)
                type_text(app, "abc")
                app._on_input(ESC)
                type_text(app, command)
                before = snapshot(app.composer), selection(app.composer)
                app._on_input(Key(CHAR, "t", ctrl=True))
                self.assertEqual(client.calls, [])
                self.assertEqual((snapshot(app.composer), selection(app.composer)), before)
                self.assertFalse(app.composer.pending)
            for armed in ("exit", "rewind"):
                for command in ("l", " ", "y", "v", "g", "f"):
                    with self.subTest(busy=busy, armed=armed, command=command):
                        app, client, clock = vim_app(busy=busy)
                        type_text(app, "abc")
                        app._on_input(ESC)
                        type_text(app, "0v")
                        app.escape_armed = (armed, clock.now)
                        app._on_input(Key(CHAR, command))
                        self.assertIsNone(app.escape_armed)
                        self.assertEqual(app.composer.text, "abc")
                        self.assertEqual(client.calls, [])
        for prefix in ("", "g", "f"):
            app, client, _clock = vim_app()
            type_text(app, "abc")
            app._on_input(ESC)
            type_text(app, "0v" + prefix)
            with mock.patch.object(app, "_display_key") as display:
                app._on_input(Key(CHAR, "o", ctrl=True))
                display.assert_not_called()
            self.assertTrue(app.composer.visual)
            self.assertEqual(client.calls, [])
        app, client, _clock = vim_app()
        app._on_input(ESC)
        type_text(app, "v?")
        self.assertIsNone(app.pager)
        self.assertTrue(app.composer.visual)
        self.assertEqual(client.calls, [])

    def test_routing_pending_visual_clipboard_and_enter(self):
        """CV-7: pending find cannot swallow image paste or existing send policy."""
        for prefix in ("", "g", "f", "F", "t", "T"):
            for busy in (False, True):
                with self.subTest(prefix=prefix, busy=busy):
                    app, client, clock = vim_app(busy=busy, environ={"NO_COLOR": "1"})
                    type_text(app, "abc")
                    app._on_input(ESC)
                    type_text(app, "0vl" + prefix)
                    app.escape_armed = ("exit", clock.now)
                    app._on_input(Key(CHAR, "v", ctrl=True))
                    self.assert_clear(app.composer)
                    self.assertIsNone(app.escape_armed)
                    self.assertEqual(client.calls, [("clipboard.paste", {"session_id": SID})])
                    with tempfile.TemporaryDirectory() as directory:
                        path = Path(directory) / "clipboard.png"
                        path.write_bytes(b"\x89PNG\r\n\x1a\n")
                        answer(app, client, {"attached": True, "path": str(path), "name": "clipboard.png"})
                    self.assertEqual(app.composer.expanded(), "a [Image #1] bc")
                    self.assertEqual(len(client.named("clipboard.paste")), 1)
            for busy, enter in ((False, Key(ENTER)), (True, Key(ENTER)),
                                (True, Key(ENTER, ctrl=True))):
                app, client, _clock = vim_app(busy=busy)
                type_text(app, "abc")
                app._on_input(ESC)
                type_text(app, "0vl" + prefix)
                app._on_input(enter)
                self.assert_clear(app.composer)
                self.assertEqual(app.composer.text, "")
                if busy and not enter.ctrl:
                    self.assertEqual([line.text for line in app.queued], ["abc"])
                    self.assertEqual(client.calls, [])
                else:
                    method = "session.redirect" if busy else "prompt.submit"
                    self.assertEqual(client.named(method)[-1]["text"], "abc")

    def test_lifetime(self):
        """CV-8: state/pending invalidation and exactly one undo/redo."""
        resets = (
            ("clear", lambda c: c._clear()),
            ("replace", lambda c: c.replace(0, len(c.text), "new")),
            ("restore", lambda c: c.restore("new", [])),
            ("vim-off", lambda c: c.set_vim(False)),
            ("vim-on", lambda c: c.set_vim(True)),
            ("paste", lambda c: c.handle(Paste("Q"))),
            ("image", lambda c: c.insert_image("[Image #1]", object())),
            ("history", lambda c: c._history_back()),
        )
        for name, reset in resets:
            with self.subTest(reset=name):
                c = normal("abc", 0)
                c.history = ["old"]
                keys(c, "vlg")
                reset(c)
                self.assert_clear(c)
        c = normal("abc", 0)
        keys(c, "xvlg")
        c.handle(ESC)  # discard g first; undo is then a standalone visual command
        keys(c, "u")
        self.assert_clear(c)
        self.assertEqual(c.text, "abc")
        keys(c, "vg")
        c.handle(Key(CHAR, "r", ctrl=True))
        self.assert_clear(c)
        self.assertEqual(c.text, "bc")
        c = normal("abc", 0)
        keys(c, "vl")
        action = c.handle(Key(ENTER))
        self.assertEqual((action.kind, action.text), (SUBMIT, "abc"))
        self.assert_clear(c)
        c = normal("abcdef", 0)
        keys(c, "xvlcZ")
        c.handle(Paste("Q"))
        c.handle(ESC)
        keys(c, "u0.")
        self.assertEqual(c.text, "cdef")  # external paste disqualifies visual c, retains x

    def test_visual_grammar_regressions(self):
        """CV-2: unsupported controls cannot edit; find-target u is not undo."""
        for control in ("u", "w", "k", "d", "a", "e"):
            c = normal("abcdef", 5)
            keys(c, "v")
            before = snapshot(c), selection(c)
            c.handle(Key(CHAR, control, ctrl=True))
            self.assertEqual((snapshot(c), selection(c)), before)
            c.render(20, 8)
        for motion, caret, head in (("f", 0, 1), ("t", 0, 0),
                                    ("F", 4, 3), ("T", 4, 4)):
            c = normal("abucud", 0)
            keys(c, "x")
            c.caret = caret
            depth = len(c._undo)
            keys(c, "v" + motion + "u")
            self.assertEqual(c.text, "bucud")
            self.assert_selection(c, caret, head, (min(caret, head), max(caret, head) + 1))
            self.assertEqual(len(c._undo), depth)

    def test_docs(self):
        """CV-4/CV-7: help and installation expose the supported visual slice."""
        from omh.tui.shortcuts import SHORTCUTS
        description = dict(SHORTCUTS)["Esc (vim mode)"]
        doc = (Path(__file__).resolve().parents[1] / "docs/INSTALLATION.md").read_text(encoding="utf-8")
        for wording in ("character VISUAL", "d/c/y", "Visual j/k", "VISUAL"):
            self.assertIn(wording, description)
            self.assertIn(wording, doc)

    @unittest.skipIf(__import__("os").name == "nt", "POSIX PTY only; the OMH TUI does not run on Windows")
    def test_pty(self):
        """CV-3/CV-8: real decoder/render/submit + undo, both terminal sizes."""
        from _vim_character_pty import assert_character_visual_pty
        assert_character_visual_pty(self)


if __name__ == "__main__":
    unittest.main()
