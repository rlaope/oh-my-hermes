"""OL-1..OL-9: independently specified operator/line acceptance oracles.

Literal spans and outcomes below come from the audited OpenSpec contract, not
from the production motion resolver.  Private state is observed only to check
register shape, transaction atomicity and semantic repeat lifetime.
"""
from __future__ import annotations

from pathlib import Path
import unittest

from _test_temp_root import make_test_tempdir
from _vim_operator_pty import assert_operator_pty
from test_tui_modes import SID, answer, type_text
from test_tui_vim_word_motions import make_normal, send_keys, state, vim_app
from omh.tui.app import DOUBLE_ESCAPE_SECONDS, STEER_FALLBACK_KEY
from omh.tui.composer import Composer, VIM_INSERT, VIM_NORMAL, _Register
from omh.tui.gateway import ServerRequest
from omh.tui.keys import CHAR, ENTER, ESCAPE, Key, Paste
from omh.tui.session_picker import SessionPicker, SessionRow

ESC = Key(ESCAPE)
CHIP_TEXT = "one\ntwo\nthree\nfour\nfive"
FAMILY = "👨\u200d👩\u200d👧\u200d👦"


def visible(c):
    return c.text, c.caret, dict(c.pastes), dict(c.images)


def immutable_state(c):
    return (visible(c), c._register, list(c._undo), list(c._redo),
            c._repeat_change, c._token_count)


class TestOL(unittest.TestCase):
    def assert_edit(self, text, caret, command, after, final, register,
                    linewise=False, *, insert=None):
        c = make_normal(text, caret)
        original = visible(c)
        depth = len(c._undo)
        send_keys(c, command)
        if insert is not None:
            self.assertEqual(c.vim_label, VIM_INSERT)
            send_keys(c, insert)
            c.handle(ESC)
        self.assertEqual(state(c), (after, final, VIM_NORMAL))
        self.assertEqual((c._register.text, c._register.linewise), (register, linewise))
        self.assertFalse(c.pending)
        self.assertEqual(len(c._undo), depth + 1)
        send_keys(c, "u")
        self.assertEqual(visible(c), original, "one undo must restore caret and metadata too")
        self.assertEqual(len(c._undo), depth)
        self.assertEqual((c._register.text, c._register.linewise), (register, linewise))
        c.handle(Key(CHAR, "r", ctrl=True))
        self.assertEqual(state(c), (after, final, VIM_NORMAL))
        return c

    def test_matrix(self):
        """OL-1: d/c/y × eight words, five line-local motions, doubled forms."""
        text = "alpha,beta gamma.delta epsilon"
        # motion, origin, d/y lower+upper, c lower+upper: cW/cw's
        # current-run-end exception deliberately has a different oracle.
        words = (("w", 0, 0, 5, 0, 5), ("W", 0, 0, 11, 0, 10),
                 ("b", 20, 17, 20, 17, 20), ("B", 20, 11, 20, 11, 20),
                 ("e", 11, 11, 16, 11, 16), ("E", 11, 11, 22, 11, 22),
                 ("ge", 17, 16, 18, 16, 18), ("gE", 17, 9, 18, 9, 18))
        local_text = "  alpha beta\ntail"
        local = (("h", 4, 3, 4), ("l", 4, 4, 5), ("0", 4, 0, 4),
                 ("^", 4, 2, 4), ("$", 4, 4, 12))
        rows = [(text, *row) for row in words]
        rows += [(local_text, motion, origin, lo, hi, lo, hi)
                 for motion, origin, lo, hi in local]
        for text, motion, origin, lo, hi, clo, chi in rows:
            for operator in "dcy":
                with self.subTest(operator=operator, motion=motion):
                    start, end = (clo, chi) if operator == "c" else (lo, hi)
                    payload = text[start:end]
                    if operator == "y":
                        c = make_normal(text, origin)
                        depth, repeat = len(c._undo), c._repeat_change
                        send_keys(c, operator + motion)
                        self.assertEqual(state(c), (text, start, VIM_NORMAL))
                        self.assertEqual((c._register.text, c._register.linewise), (payload, False))
                        self.assertEqual((len(c._undo), c._repeat_change), (depth, repeat))
                    else:
                        after = text[:start] + ("X" if operator == "c" else "") + text[end:]
                        # Only $ leaves the caret on a now-shorter hard line.
                        final = 3 if operator == "d" and motion == "$" else start
                        self.assert_edit(text, origin, operator + motion, after,
                                         final, payload, insert="X" if operator == "c" else None)
        for operator in "dcy":
            with self.subTest(doubled=operator * 2):
                if operator == "y":
                    c = make_normal("a\n  bb\nc", 4)
                    before = immutable_state(c)
                    send_keys(c, "yy")
                    self.assertEqual(state(c), ("a\n  bb\nc", 4, VIM_NORMAL))
                    self.assertEqual((c._register.text, c._register.linewise), ("  bb", True))
                    self.assertEqual((c._undo, c._repeat_change), (before[2], before[4]))
                else:
                    self.assert_edit("a\n  bb\nc", 4, operator * 2,
                                     "a\nX\nc" if operator == "c" else "a\nc", 2,
                                     "  bb", True, insert="X" if operator == "c" else None)

    def test_lines(self):
        """OL-2: hard-line inclusion, separators, caret, absolute destinations, no history."""
        text = "aa\n  bb\ncc\ndd"
        # motion, selected payload, delete text/caret, change text/caret
        rows = (("j", "  bb\ncc", "aa\ndd", 3, "aa\nX\ndd", 3),
                ("k", "aa\n  bb", "cc\ndd", 0, "X\ncc\ndd", 0),
                ("gg", "aa\n  bb", "cc\ndd", 0, "X\ncc\ndd", 0),
                ("G", "  bb\ncc\ndd", "aa", 0, "aa\nX", 3),
                ("2j", "  bb\ncc\ndd", "aa", 0, "aa\nX", 3),
                ("9k", "aa\n  bb", "cc\ndd", 0, "X\ncc\ndd", 0),
                ("3gg", "  bb\ncc", "aa\ndd", 3, "aa\nX\ndd", 3),
                ("3G", "  bb\ncc", "aa\ndd", 3, "aa\nX\ndd", 3),
                ("1G", "aa\n  bb", "cc\ndd", 0, "X\ncc\ndd", 0),
                ("99G", "  bb\ncc\ndd", "aa", 0, "aa\nX", 3))
        for motion, payload, deleted, dc, changed, cc in rows:
            for operator in "dcy":
                with self.subTest(operator=operator, motion=motion):
                    if operator == "y":
                        c = make_normal(text, 6)
                        before = immutable_state(c)
                        send_keys(c, "y" + motion)
                        self.assertEqual(state(c), (text, 6, VIM_NORMAL))
                        self.assertEqual((c._register.text, c._register.linewise), (payload, True))
                        self.assertEqual((c._undo, c._repeat_change), (before[2], before[4]))
                    else:
                        self.assert_edit(text, 6, operator + motion,
                                         changed if operator == "c" else deleted,
                                         cc if operator == "c" else dc, payload, True,
                                         insert="X" if operator == "c" else None)
        self.assert_edit("a\nb\n  c", 0, "dj", "  c", 2, "a\nb", True)
        self.assert_edit("a\nb", 0, "dG", "", 0, "a\nb", True)
        # Empty line is real linewise content, not an invalid/empty char span.
        for text, origin, after, final in (("a\n\nb", 2, "a\nb", 2),
                                           ("a\n", 2, "a", 0),
                                           ("\n", 0, "", 0)):
            with self.subTest(empty_line=text):
                self.assert_edit(text, origin, "dd", after, final, "", True)
                c = make_normal(text, origin)
                send_keys(c, "yy")
                self.assertEqual((c._register.text, c._register.linewise), ("", True))
                self.assertEqual((c.text, c.caret), (text, origin))
        for op in "dcy":
            for motion, origin in (("k", 0), ("j", 2)):
                with self.subTest(history=op + motion):
                    c = make_normal("a\nb", origin)
                    c.history = ["older"]
                    send_keys(c, op + motion)
                    self.assertNotIn("older", c.text)
                    self.assertEqual(c.history, ["older"])
                    self.assertEqual((c._register.text, c._register.linewise),
                                     ("a" if motion == "k" else "b", True))

    def test_exceptions(self):
        """OL-3: every normative boundary row, with final NORMAL caret and one undo."""
        rows = (("one two", 0, "cw", "X two", 0, "one", False, "X"),
                ("one two", 2, "cw", "onX two", 2, "e", False, "X"),
                ("  one", 0, "cw", "Xone", 0, "  ", False, "X"),
                ("one\ntwo", 0, "dw", "\ntwo", 0, "one", False, None),
                ("one\ntwo", 0, "d2w", "", 0, "one\ntwo", False, None),
                ("one\ntwo\nthree", 0, "d2w", "three", 0, "one\ntwo", True, None),
                ("x one\ntwo\nthree", 2, "d2w", "x \nthree", 1, "one\ntwo", False, None),
                ("one two", 6, "dge", "on", 1, "e two", False, None),
                ("a\nb\nc", 2, "dj", "a", 0, "b\nc", True, None),
                ("a\nb\nc", 2, "dk", "c", 0, "a\nb", True, None),
                ("a\nb\nc", 2, "dgg", "c", 0, "a\nb", True, None),
                ("a\nb\nc", 2, "dG", "a", 0, "b\nc", True, None),
                ("a\nb", 2, "cc", "a\nX", 2, "b", True, "X"),
                # Exclusive promotion only at column-zero targets; backwards
                # and inclusive words must never be promoted by min/max.
                ("  one\ntwo\nthree", 2, "d2w", "three", 0, "  one\ntwo", True, None),
                ("one\n  two\nthree", 0, "d2w", "three", 0, "one\n  two", True, None),
                ("one\n\ntwo\nthree", 0, "d2w", "three", 0, "one\n\ntwo", True, None),
                ("one\ntwo", 4, "db", "two", 0, "one\n", False, None),
                ("one\ntwo", 4, "dB", "two", 0, "one\n", False, None),
                ("one\ntwo", 2, "de", "on", 1, "e\ntwo", False, None),
                ("one\ntwo", 2, "dE", "on", 1, "e\ntwo", False, None),
                ("one\ntwo", 4, "dge", "onwo", 2, "e\nt", False, None),
                ("one\ntwo", 4, "dgE", "onwo", 2, "e\nt", False, None),
                ("one  \n  two", 0, "dw", "\n  two", 0, "one  ", False, None),
                ("one\ntwo\nthree", 0, "c2w", "X\nthree", 0, "one\ntwo", False, "X"),
                ("foo.bar baz", 0, "c2w", "Xbar baz", 0, "foo.", False, "X"))
        for text, origin, command, after, caret, payload, shape, insert in rows:
            with self.subTest(text=text, origin=origin, command=command):
                self.assert_edit(text, origin, command, after, caret, payload, shape, insert=insert)
        for motion in ("$", "3$", "9999$"):
            self.assert_edit("one\ntwo", 0, "d" + motion, "\ntwo", 0, "one")

    def test_counts(self):
        """OL-4: counts multiply once; cap is observable before buffer exhaustion."""
        words = "a b c d e f g h i j"
        self.assert_edit(words, 0, "2d3w", "g h i j", 0, "a b c d e f ")
        self.assert_edit(words, 0, "d6w", "g h i j", 0, "a b c d e f ")
        self.assert_edit(words, 0, "2c3w", "X g h i j", 0, "a b c d e f", insert="X")
        c = make_normal(words, 0)
        send_keys(c, "2y3w")
        self.assertEqual((c.text, c._register.text, c._register.linewise),
                         (words, "a b c d e f ", False))
        lines = "a\nb\nc\nd\ne\nf\ng\nh"
        for motion in ("G", "gg"):
            self.assert_edit(lines, 2, "2d3" + motion, "a\ng\nh", 2, "b\nc\nd\ne\nf", True)
        self.assert_edit(lines, 2, "2d3j", "a", 0, "b\nc\nd\ne\nf\ng\nh", True)
        self.assert_edit(lines, 2, "2d3d", "a\nh", 2, "b\nc\nd\ne\nf\ng", True)
        # >9999 independent semantic steps distinguishes capping from a short
        # buffer merely saturating at EOF. No production resolver as oracle.
        many = "a " * 10005 + "END"
        for command in ("999999d999999w", "9999d2w"):
            with self.subTest(cap=command):
                c = make_normal(many, 0)
                send_keys(c, command)
                self.assertEqual(c.text, "a " * 6 + "END")
                self.assertEqual(c._register.text, "a " * 9999)
                self.assertFalse(c._register.linewise)
                self.assertEqual(c.caret, 0)
                send_keys(c, "u")
                self.assertEqual(c.text, many)
        many_lines = "a\n" * 10004 + "END"
        c = make_normal(many_lines, 0)
        send_keys(c, "999999d999999G")
        self.assertEqual(c.text, "a\n" * 5 + "END")
        self.assertEqual((c._register.text, c._register.linewise), ("\n".join(["a"] * 9999), True))

    def test_failure(self):
        """OL-5: invalid/cancelled/no-op retains every mutation-visible resource."""
        for command in ("d?", "c?", "y?", "2d3gx", "cgx", "ygx", "dh", "yh", "d0", "y0"):
            with self.subTest(command=command):
                c = make_normal("zabc", 0)
                send_keys(c, "x")
                before = immutable_state(c)
                send_keys(c, command)
                self.assertEqual(immutable_state(c), before)
                self.assertFalse(c.pending)
                send_keys(c, ".")
                self.assertEqual(c.text, "bc", "failed operation must retain preceding x")
        for prefix in ("d", "2d3", "cg", "2y3g"):
            for event in (ESC, Key(ENTER), Key(ESCAPE, alt=True, protocol=True)):
                with self.subTest(prefix=prefix, event=event):
                    c = make_normal("zabc", 0)
                    send_keys(c, "x")
                    before = immutable_state(c)
                    send_keys(c, prefix)
                    self.assertTrue(c.pending)
                    c.handle(event)
                    self.assertEqual(immutable_state(c), before)
                    self.assertFalse(c.pending)
        for command in ("ch", "c0", "c^"):
            with self.subTest(empty_change=command):
                c = make_normal("zabc", 0)
                send_keys(c, "x")
                before = immutable_state(c)
                send_keys(c, command)
                self.assertEqual(c.vim_label, VIM_INSERT)
                c.handle(ESC)
                self.assertEqual(immutable_state(c), before)
                send_keys(c, ".")
                self.assertEqual(c.text, "bc")
        for command in ("dw", "yw", "db", "yb"):
            c = make_normal("", 0)
            c._register = _Register("SEED", {}, {}, False)
            before = immutable_state(c)
            send_keys(c, command)
            self.assertEqual(immutable_state(c), before)
        c = make_normal("", 0)
        send_keys(c, "cwX")
        c.handle(ESC)
        self.assertEqual(state(c), ("X", 0, VIM_NORMAL))
        send_keys(c, "u")
        self.assertEqual(state(c), ("", 0, VIM_NORMAL))
        for command in ("cc", "cj", "ck", "cgg", "cG"):
            with self.subTest(empty_line_change=command):
                c = make_normal("z", 0)
                send_keys(c, "x")
                before = immutable_state(c)
                send_keys(c, command)
                self.assertFalse(c.normal)
                c.handle(ESC)
                self.assertEqual(immutable_state(c), before)
        # Invalid replay is atomic and keeps an older successful descriptor.
        c = make_normal("a\nb", 0)
        send_keys(c, "dj")
        before = immutable_state(c)
        send_keys(c, ".")
        self.assertEqual(immutable_state(c), before)

    def test_repeat(self):
        """OL-6: replay semantic words/lines; overrides are execution-local."""
        c = make_normal("one two enormous tail end", 0)
        send_keys(c, "dw")
        saved = c._repeat_change
        c.caret = 4
        before, depth = visible(c), len(c._undo)
        send_keys(c, ".")
        self.assertEqual(state(c), ("two tail end", 4, VIM_NORMAL))
        self.assertEqual(c._register.text, "enormous ")
        self.assertEqual(c._repeat_change, saved)
        self.assertEqual(len(c._undo), depth + 1)
        send_keys(c, "u")
        self.assertEqual(visible(c), before)
        c = make_normal("a b c d e f g h i j k l", 0)
        send_keys(c, "2d3w")
        saved = c._repeat_change
        send_keys(c, "2.")
        self.assertEqual(c.text, "i j k l")
        self.assertEqual(c._repeat_change, saved)
        send_keys(c, ".")
        self.assertEqual(c.text, "")
        # dj selects two logical lines; not two stored lengths or wrapped rows.
        c = make_normal("a\nb\nlong different line\nq\nlast", 0)
        send_keys(c, "dj")
        saved = c._repeat_change
        send_keys(c, ".")
        self.assertEqual(state(c), ("last", 0, VIM_NORMAL))
        self.assertEqual((c._register.text, c._register.linewise), ("long different line\nq", True))
        self.assertEqual(c._repeat_change, saved)
        send_keys(c, "u")
        self.assertEqual(c.text, "long different line\nq\nlast")
        for command in ("2d3G", "2d3gg"):
            with self.subTest(absolute_repeat=command):
                c = make_normal("a\nb\nc\nd\ne\nf\ng\nh\ni\nj", 2)
                send_keys(c, command)
                self.assertEqual(c.text, "a\ng\nh\ni\nj")
                saved = c._repeat_change
                c.caret = 6  # i, absolute target 2 => g/h/i inclusive
                send_keys(c, "2.")
                self.assertEqual(c.text, "a\nj")
                self.assertEqual(c._repeat_change, saved)
                send_keys(c, ".")  # saved destination six, clamped => removes j
                self.assertEqual(c.text, "a")
        for command, initial, after in (("cw", "one two enormous", "X two enormous"),
                                         ("cj", "one\ntwo\nthree\nfour", "X\nthree\nfour")):
            with self.subTest(change=command):
                c = make_normal(initial, 0)
                send_keys(c, command + "X")
                c.handle(ESC)
                self.assertEqual(c.text, after)
                saved = c._repeat_change
                c.caret = 2
                before, depth = visible(c), len(c._undo)
                send_keys(c, ".")
                self.assertEqual(c.text, "X X enormous" if command == "cw" else "X\nX")
                self.assertEqual(len(c._undo), depth + 1)
                self.assertEqual(c._repeat_change, saved)
                send_keys(c, "u")
                self.assertEqual(visible(c), before)
                send_keys(c, "u")
                self.assertEqual(state(c), (initial, 0, VIM_NORMAL))
        c = make_normal("a\nb\nc\nd\ne", 0)
        send_keys(c, "dj")
        saved = c._repeat_change
        send_keys(c, "yG")
        self.assertEqual(c._repeat_change, saved)
        send_keys(c, ".")
        self.assertEqual(c.text, "e")

    def test_metadata(self):
        """OL-7: whole multiline chips/images, fresh puts, objects/find regressions."""
        c = make_normal("a\n", 2)
        send_keys(c, "yGP")
        self.assertEqual((c.text, c._register.text, c._register.linewise), ("a\n\n", "", True))
        saved, before, depth = c._repeat_change, visible(c), len(c._undo)
        send_keys(c, ".")
        self.assertEqual(c.text, "a\n\n\n")
        self.assertEqual((c._repeat_change, len(c._undo)), (saved, depth + 1))
        send_keys(c, "u")
        self.assertEqual(visible(c), before)
        for command in ("dj", "cj", "yj", "d3W"):
            with self.subTest(command=command):
                c = Composer(vim=True)
                c.handle(Paste(CHIP_TEXT))
                label = next(iter(c.pastes))
                c.replace(c.caret, c.caret, "\n")
                image = object()
                c.insert_image("[Image #1]", image)
                token = next(iter(c.images))
                c.replace(c.caret, c.caret, "\ntail")
                c.handle(ESC)
                c.caret = 0
                original, depth = visible(c), len(c._undo)
                send_keys(c, command)
                self.assertEqual(c._register.pastes, {label: CHIP_TEXT})
                self.assertEqual(c._register.images, {token: ("[Image #1]", image)})
                self.assertEqual(c._register.linewise, command != "d3W")
                self.assertIn(label, c._register.text)
                self.assertIn(token, c._register.text)
                if command.startswith("y"):
                    self.assertEqual(visible(c), original)
                    self.assertEqual(len(c._undo), depth)
                else:
                    if command.startswith("c"):
                        send_keys(c, "X")
                        c.handle(ESC)
                    self.assertNotIn(label, c.text)
                    self.assertNotIn(token, c.text)
                    self.assertEqual((c.pastes, c.images), ({}, {}))
                    self.assertEqual(len(c._undo), depth + 1)
                    send_keys(c, "u")
                    self.assertEqual(visible(c), original)
                    c.handle(Key(CHAR, "r", ctrl=True))
                send_keys(c, "P")
                self.assertTrue(all(t in c.text for t in c.images))
                self.assertIn(CHIP_TEXT, c.pastes.values())
                first_tokens = set(c.images)
                send_keys(c, "p")
                self.assertGreater(len(c.images), len(first_tokens))
                self.assertTrue(set(c.images) - first_tokens)
                self.assertTrue(all(payload[1] is image for payload in c.images.values()))
                self.assertTrue(all(t in c.text for t in c.images))
                before = visible(c)
                send_keys(c, ".")  # captured put, not the now-current register
                self.assertGreater(len(c.images), len(before[3]))
                send_keys(c, "u")
                self.assertEqual(visible(c), before)
        # Multi-codepoint graphemes are never cut at codepoint rather than atom bounds.
        for text, after, payload in (("q́ next", "next", "q́ "),
                                      (FAMILY + " next", "next", FAMILY + " "),
                                      ("한 next", "next", "한 ")):
            self.assert_edit(text, 0, "dw", after, 0, payload)
        for text, origin, command, after, caret, payload in (
                ('a "bc" d', 3, 'di"', 'a "" d', 3, "bc"),
                ("a (bc) d", 3, "di(", "a () d", 3, "bc"),
                ("a [bc] d", 3, "da]", "a  d", 2, "[bc]"),
                ("abcd", 0, "dfc", "d", 0, "abc"),
                ("abcd", 0, "dtc", "cd", 0, "ab"),
                ("abcd", 3, "dFa", "d", 0, "abc")):
            with self.subTest(regression=command):
                self.assert_edit(text, origin, command, after, caret, payload)

    def test_routing(self):
        """OL-8: actual App routes pending grammar ahead of global policies."""
        for busy in (False, True):
            for prefix in ("d", "2d3g", "c", "yg"):
                for escape in (ESC, Key(ESCAPE, alt=True, protocol=True)):
                    with self.subTest(busy=busy, prefix=prefix, escape=escape):
                        app, client, clock = vim_app(busy=busy)
                        type_text(app, "alpha beta")
                        app._on_input(ESC)
                        app.escape_armed = ("clear", clock.now)
                        type_text(app, prefix)
                        self.assertTrue(app.composer.pending)
                        app._on_input(escape)
                        self.assertEqual((app.composer.text, app.composer.pending), ("alpha beta", False))
                        self.assertIsNone(app.escape_armed)
                        self.assertEqual(client.calls, [])
        app, client, clock = vim_app(busy=True)
        type_text(app, "draft")
        app._on_input(ESC)
        type_text(app, "d")
        app._on_input(ESC)
        app._on_input(ESC)
        self.assertEqual(app.escape_armed, ("clear", clock.now))
        clock.now += DOUBLE_ESCAPE_SECONDS / 4
        app._on_input(ESC)
        self.assertEqual(app.composer.text, "")
        app._on_input(ESC)
        self.assertEqual(app.escape_armed, ("interrupt", clock.now))
        clock.now += DOUBLE_ESCAPE_SECONDS / 4
        app._on_input(ESC)
        self.assertEqual([name for name, _ in client.calls], ["session.interrupt"])
        # Space while operator-pending is consumed, not a global leader.
        app, client, _ = vim_app()
        type_text(app, "alpha beta")
        app._on_input(ESC)
        type_text(app, "d s")
        self.assertEqual(client.calls, [])
        self.assertFalse(app.composer.pending)
        app._on_input(ESC)
        type_text(app, " s")
        self.assertEqual([name for name, _ in client.calls], ["session.list"])
        for waiting in (False, True):
            app, client, _ = vim_app()
            type_text(app, "a\nb\nc")
            app._on_input(ESC)
            type_text(app, "ggd")
            app.picker = SessionPicker([SessionRow(SID, "title", "", 0.0, 1)],
                                       current=app.stored_id, waiting=waiting)
            app._on_input(Key(CHAR, "j"))
            self.assertFalse(app.composer.pending)
            self.assertEqual(app.composer.text, "c" if waiting else "a\nb\nc")
            self.assertEqual((app.picker.waiting, app.picker.query, client.calls),
                             (waiting, "" if waiting else "j", []))
        app, client, clock = vim_app()
        type_text(app, "draft")
        app._on_input(ESC)
        type_text(app, "d")
        app._on_server_request(ServerRequest("srq-1", "clarify", {"questions": [{"qid": "q0", "question": "Why?"}]}))
        clock.now += 1.0
        type_text(app, "dj")
        self.assertEqual(app.composer.text, "dj")
        app, client, _ = vim_app(environ={"NO_COLOR": "1"})
        type_text(app, "ab")
        app._on_input(ESC)
        type_text(app, "d")
        app._on_input(Key(CHAR, "v", ctrl=True))
        self.assertEqual(client.calls, [("clipboard.paste", {"session_id": SID})])
        with make_test_tempdir("omh-operator-image-") as home:
            path = Path(home) / "clipboard.png"
            data = b"\x89PNG\r\n\x1a\n"
            path.write_bytes(data)
            answer(app, client, {"attached": True, "path": str(path), "name": "clipboard.png"})
            self.assertEqual(client.named("image.detach"), [{"session_id": SID, "path": str(path)}])
        self.assertEqual(app.composer.expanded(), "a [Image #1] b")
        self.assertFalse(app.composer.pending)
        self.assertEqual(next(iter(app.composer.images.values()))[1].data, data)
        for busy in (False, True):
            for send_now in (Key(ENTER, ctrl=True), STEER_FALLBACK_KEY):
                app, client, _ = vim_app(busy=busy)
                type_text(app, "send now")
                app._on_input(ESC)
                type_text(app, "2d3g")
                app._on_input(Key(ENTER))
                self.assertEqual(state(app.composer), ("send now", 7, VIM_NORMAL))
                self.assertEqual((client.calls, list(app.queued)), ([], []))
                self.assertFalse(app.composer.pending)
                app._on_input(Key(ENTER))
                if not busy:
                    self.assertEqual(client.named("prompt.submit")[-1]["text"], "send now")
                else:
                    self.assertEqual([line.text for line in app.queued], ["send now"])
                    self.assertEqual(client.calls, [])
                    app._on_input(ESC)
                    app._on_input(send_now)
                    self.assertEqual(client.calls, [("session.redirect", {"session_id": SID, "text": "send now"})])
                    answer(app, client, error={"code": 4010, "message": "agent does not support active-turn redirect"})
                    self.assertEqual(client.calls[-1], ("session.steer", {"session_id": SID, "text": "send now"}))
        # Public replacement/history and submit retire half-written grammar.
        c = make_normal("abc", 0)
        send_keys(c, "2d3g")
        c.restore("new", [])
        self.assertFalse(c.pending)
        if not c.normal:
            c.handle(ESC)
        send_keys(c, "w")
        self.assertEqual(c.text, "newabc")  # restore inserts at the caret; it does not replace.

    @unittest.skipIf(__import__("os").name == "nt", "POSIX PTY only; the OMH TUI does not run on Windows")
    def test_pty(self):
        """OL-9: real OS PTY, production TUI, 20×8 and 100×30."""
        assert_operator_pty(self)


if __name__ == "__main__":
    unittest.main()
