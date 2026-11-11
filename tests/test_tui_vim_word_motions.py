"""Slice 02 acceptance suite for Vim word motions (`w`, `W`, `b`, `B`, `e`, `E`, `ge`, `gE`).

Maps directly to OpenSpec change `add-tui-vim-word-motions` requirements:
- WM-1 (`test_classes`): keyword, punctuation, WORD, and opaque singleton classification across all 8 spellings.
- WM-2 (`test_limits`): BOF, EOF, empty buffer, newline, and count 9999 saturation on atom boundaries.
- WM-3 (`test_prefix`): invalid `g` follower and Escape clear counts/operator without global dispatch.
- WM-4 (`test_objects`): `iw`/`aw` parity and `cw`/`cW`/`dw`/`dW` operator class behavior.
- WM-5 (`test_metadata`): NFC Hangul, combining marks, ZWJ, chips/images never split; metadata maps survive undo/put.
- WM-6 (`test_routing`): real App busy/armed/modified Escape, leaders/pickers, Ctrl+V paste, and Enter routing.
- WM-7 (`test_pty`): real terminal PTY motion destinations across wrapping widths (20 and 100 columns).
"""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any
import unicodedata
import unittest

from _vim_word_pty import assert_word_motions_pty
from test_tui_modes import SID, answer, make_app, type_text
from test_tui_rewind import Clock
from omh.tui.app import DOUBLE_ESCAPE_SECONDS, STEER_FALLBACK_KEY
from omh.tui.composer import (
    VIM_INSERT,
    VIM_NORMAL,
    Composer,
    _Register,
)
from omh.tui.gateway import ServerRequest
from omh.tui.keys import CHAR, ENTER, ESCAPE, Key, Paste
from omh.tui.session_picker import SessionPicker, SessionRow

ESC = Key(ESCAPE)
FAMILY = "\U0001F468\u200d\U0001F469\u200d\U0001F467\u200d\U0001F466"
Q_ACUTE = "q\u0301"
MARK_ONLY = "\u0301"
HANGUL_NFD = "\u1112\u1161\u11ab"
HANGUL_NFC = "\ud55c"
CHIP_A_TEXT = "line1\nline2\nline3\nline4"
CHIP_A = "[Pasted text #1 +4 lines]"
CHIP_B_TEXT = "other1\nother2\nother3\nother4"
CHIP_B = "[Pasted text #2 +4 lines]"
CLARIFY = {"questions": [{"qid": "q0", "question": "Why?"}]}


def send_keys(composer: Composer, typed: str) -> None:
    for ch in typed:
        composer.handle(Key(CHAR, ch))


def make_normal(text: str = "", caret: int | None = None) -> Composer:
    composer = Composer(vim=True)
    if text:
        composer.replace(0, 0, text)
    composer.handle(ESC)
    if caret is not None:
        composer.caret = caret
    return composer


def state(composer: Composer) -> tuple[str, int, str]:
    return composer.text, composer.caret, composer.vim_label


def vim_app(**options: Any):
    clock = Clock()
    app, client = make_app(clock=clock, **options)
    app._take_settings({"config": {"display": {"vim_mode": True}}})
    return app, client, clock


class TestWM(unittest.TestCase):
    def assert_atom_aligned(self, composer: Composer) -> None:
        _units, bounds, _index = composer._atoms()
        self.assertIn(composer.caret, bounds)

    def test_classes(self) -> None:
        """WM-1: All 8 spellings distinguish keyword, punctuation, WORD, and opaque singleton runs."""
        text = "alpha,beta gamma.delta epsilon"
        cases = (
            ("w", 0, 5),
            ("W", 0, 11),
            ("b", 20, 17),
            ("B", 20, 11),
            ("e", 11, 15),
            ("E", 11, 21),
            ("ge", 17, 16),
            ("gE", 17, 9),
        )
        for motion, start, expected in cases:
            with self.subTest(motion=motion, start=start):
                composer = make_normal(text, start)
                send_keys(composer, motion)
                self.assertEqual(state(composer), (text, expected, VIM_NORMAL))
                self.assert_atom_aligned(composer)

        # Full forward/backward walks across keyword, punctuation, underscore, digits, and NBSP separator.
        mixed = f"foo_1..bar\u00a0{Q_ACUTE}--baz"
        composer = make_normal(mixed, 0)
        w_stops = []
        for _ in range(7):
            send_keys(composer, "w")
            w_stops.append(composer.caret)
            self.assert_atom_aligned(composer)
        # foo_1 (0..5), .. (5..7), bar (7..10), \xa0 (10..11), q\u0301 (11..13), -- (13..15), baz (15..18)
        self.assertEqual(w_stops, [5, 7, 11, 13, 15, 17, 17])

        composer = make_normal(mixed, 17)
        b_stops = []
        for _ in range(7):
            send_keys(composer, "b")
            b_stops.append(composer.caret)
            self.assert_atom_aligned(composer)
        self.assertEqual(b_stops, [15, 13, 11, 7, 5, 0, 0])

        composer = make_normal(mixed, 0)
        e_stops = []
        for _ in range(7):
            send_keys(composer, "e")
            e_stops.append(composer.caret)
            self.assert_atom_aligned(composer)
        self.assertEqual(e_stops, [4, 6, 9, 11, 14, 17, 17])

        composer = make_normal(mixed, 17)
        ge_stops = []
        for _ in range(7):
            send_keys(composer, "ge")
            ge_stops.append(composer.caret)
            self.assert_atom_aligned(composer)
        self.assertEqual(ge_stops, [14, 11, 9, 6, 4, 0, 0])

        # WORD motions merge keyword and punctuation across non-whitespace, breaking on NBSP.
        composer = make_normal(mixed, 0)
        send_keys(composer, "W")
        self.assertEqual(composer.caret, 11)
        send_keys(composer, "E")
        self.assertEqual(composer.caret, 17)
        send_keys(composer, "B")
        self.assertEqual(composer.caret, 11)
        send_keys(composer, "gE")
        self.assertEqual(composer.caret, 9)

        # Mark-only cluster is classified as punctuation, not keyword.
        mark_text = f"ab{MARK_ONLY}cd"
        composer = make_normal(mark_text, 0)
        composer.text = mark_text  # direct unmerged check for standalone mark if present
        units = ["a", MARK_ONLY, "b"]
        self.assertEqual(composer._word_classes(units, False), ["keyword", "punctuation", "keyword"])

        # Opaque singleton runs: adjacent chips and images never merge into words or WORDs.
        composer = Composer(vim=True)
        send_keys(composer, "ab")
        composer.handle(Paste(CHIP_A_TEXT))
        composer.handle(Paste(CHIP_B_TEXT))
        img1 = object()
        img2 = object()
        composer.insert_image("[Image #1]", img1)
        composer.insert_image("[Image #2]", img2)
        tok1, tok2 = list(composer.images)
        # Set text so chips and tokens are strictly adjacent without separating spaces
        composer._set(f"ab{CHIP_A}{CHIP_B}{tok1}{tok2}cd", 0)
        composer.handle(ESC)
        _, bounds, _ = composer._atoms()
        # Units: 'a'(0), 'b'(1), CHIP_A(2), CHIP_B(3), tok1(4), tok2(5), 'c'(6), 'd'(7)
        for motion_w in ("w", "W"):
            composer.caret = bounds[0]
            visited = [composer.caret]
            for _ in range(6):
                send_keys(composer, motion_w)
                visited.append(composer.caret)
            self.assertEqual(visited, [bounds[0], bounds[2], bounds[3], bounds[4], bounds[5], bounds[6], bounds[7]])

        for motion_b in ("b", "B"):
            composer.caret = bounds[7]
            visited = [composer.caret]
            for _ in range(6):
                send_keys(composer, motion_b)
                visited.append(composer.caret)
            self.assertEqual(visited, [bounds[7], bounds[6], bounds[5], bounds[4], bounds[3], bounds[2], bounds[0]])

        for motion_e in ("e", "E"):
            composer.caret = bounds[0]
            visited = [composer.caret]
            for _ in range(6):
                send_keys(composer, motion_e)
                visited.append(composer.caret)
            self.assertEqual(visited, [bounds[0], bounds[1], bounds[2], bounds[3], bounds[4], bounds[5], bounds[7]])

        for motion_ge in ("ge", "gE"):
            composer.caret = bounds[7]
            visited = [composer.caret]
            for _ in range(6):
                send_keys(composer, motion_ge)
                visited.append(composer.caret)
            self.assertEqual(visited, [bounds[7], bounds[5], bounds[4], bounds[3], bounds[2], bounds[1], bounds[0]])

    def test_limits(self) -> None:
        """WM-2: BOF, EOF, empty buffer, newline, and count 9999 terminate atom-aligned."""
        # Empty buffer
        for motion in ("w", "W", "b", "B", "e", "E", "ge", "gE", "9999w", "9999b", "9999e", "9999ge"):
            with self.subTest(case="empty", motion=motion):
                composer = make_normal("", 0)
                send_keys(composer, motion)
                self.assertEqual(state(composer), ("", 0, VIM_NORMAL))
                self.assertFalse(composer.pending)

        # Literal EOF oracle: the trailing empty hard line is a real NORMAL
        # destination, including when G or a repeated/count motion reaches it.
        for text, eof in (("one\n", 4), ("one\n\n", 5), ("\n", 1)):
            for motion in ("e", "E", "9999e", "9999E"):
                for start in (0, eof):
                    with self.subTest(case="trailing-empty", text=text, start=start, motion=motion):
                        composer = make_normal(text, start)
                        # From BOF, a counted motion exhausts the current word first.
                        keys = motion if start == eof or motion.startswith("9999") else "G" + motion
                        send_keys(composer, keys)
                        self.assertEqual(state(composer), (text, eof, VIM_NORMAL))
                        send_keys(composer, motion)
                        self.assertEqual(state(composer), (text, eof, VIM_NORMAL))
                        self.assertFalse(composer.pending)
                        self.assert_atom_aligned(composer)

        # No trailing newline: exhaustion remains on the final selectable atom.
        for motion in ("e", "E", "9999e", "9999E", "Ge", "GE"):
            with self.subTest(case="nonempty-eof", motion=motion):
                composer = make_normal("one", 0)
                send_keys(composer, motion)
                self.assertEqual(state(composer), ("one", 2, VIM_NORMAL))

        # Single character buffer
        for motion in ("w", "W", "b", "B", "e", "E", "ge", "gE"):
            with self.subTest(case="single", motion=motion):
                composer = make_normal("x", 0)
                send_keys(composer, motion)
                self.assertEqual(state(composer), ("x", 0, VIM_NORMAL))

        # Multiline with empty lines and trailing newline
        multi = "one\n\ntwo-2\n"
        composer = make_normal(multi, 0)
        send_keys(composer, "w")
        self.assertEqual(composer.caret, 5)  # crosses \n\n to 'two'
        send_keys(composer, "w")
        self.assertEqual(composer.caret, 8)  # '-'
        send_keys(composer, "w")
        self.assertEqual(composer.caret, 9)  # '2'
        send_keys(composer, "w")
        self.assertEqual(composer.caret, 11)  # trailing empty line after \n
        self.assert_atom_aligned(composer)

        send_keys(composer, "b")
        self.assertEqual(composer.caret, 9)
        send_keys(composer, "ge")
        self.assertEqual(composer.caret, 8)
        send_keys(composer, "2ge")
        self.assertEqual(composer.caret, 2)  # 'e' of 'one'

        # Huge counts cap at VIM_COUNT_CAP (9999) and saturate cleanly at BOF/EOF
        for motion in ("9999w", "999999W", "9999e", "999999E"):
            composer = make_normal("alpha beta.gamma\ndelta", 0)
            send_keys(composer, motion)
            self.assertEqual(composer.caret, len("alpha beta.gamma\ndelta") - 1)
            self.assert_atom_aligned(composer)

        for motion in ("9999b", "999999B", "9999ge", "999999gE"):
            composer = make_normal("alpha beta.gamma\ndelta", 18)
            send_keys(composer, motion)
            self.assertEqual(composer.caret, 0)
            self.assert_atom_aligned(composer)

        # Decimal count containing '0' vs standalone '0' line-start motion
        composer = make_normal("  a b c d e f g h i j k l", 10)
        send_keys(composer, "0")
        self.assertEqual(composer.caret, 0)
        send_keys(composer, "10w")
        self.assertEqual(composer.caret, 20)

    def test_prefix(self) -> None:
        """WM-3: Invalid `g` follower and Escape clear counts/operator without global dispatch."""
        # Standalone and operator-pending invalid followers after `g`
        for prefix in ("g", "3g", "dg", "2d3g", "cg", "yg"):
            for invalid in ("x", "z", "w", "W", "b", "B", "G", "0", "$", "?"):
                with self.subTest(prefix=prefix, invalid=invalid):
                    composer = make_normal("alpha beta", 5)
                    composer._register = _Register("SEED", {}, {}, False)
                    before = (
                        composer._state(),
                        list(composer._undo),
                        list(composer._redo),
                        composer._register,
                    )
                    send_keys(composer, prefix + invalid)
                    self.assertFalse(composer.pending)
                    self.assertEqual(
                        (composer._state(), composer._undo, composer._redo, composer._register),
                        before,
                    )
                    # Subsequent key acts fresh, not continuing any stale prefix or operator
                    send_keys(composer, "w")
                    self.assertEqual(composer.caret, 6)
                    self.assertEqual(composer.text, "alpha beta")

        # Standalone gg and its count retain navigation; slice 03 adds dgg.
        composer = make_normal("first\n  second\nthird", 16)
        send_keys(composer, "gg")
        self.assertEqual(composer.caret, 0)
        send_keys(composer, "2gg")
        self.assertEqual(composer.caret, 8)
        before_dgg = composer._state()
        send_keys(composer, "dgg")
        self.assertEqual((composer.text, composer.caret), ("third", 0))
        self.assertEqual((composer._register.text, composer._register.linewise), ("first\n  second", True))
        send_keys(composer, "u")
        self.assertEqual(composer._state(), before_dgg)
        self.assertFalse(composer.pending)

        # App-level Escape over pending `g`, `3g`, `dg`, `2d3g` cancels without arming clear/interrupt
        for busy in (False, True):
            for seq in ("g", "3g", "dg", "2d3g", "cg", "yg"):
                with self.subTest(busy=busy, seq=seq):
                    app, client, clock = vim_app(busy=busy)
                    type_text(app, "hello world")
                    app._on_input(ESC)
                    app.escape_armed = ("clear", clock.now)
                    type_text(app, seq)
                    self.assertTrue(app.composer.pending)
                    app._on_input(ESC)
                    self.assertFalse(app.composer.pending)
                    self.assertIsNone(app.escape_armed)
                    self.assertEqual(app.composer.text, "hello world")
                    self.assertEqual(client.calls, [])

    def test_objects(self) -> None:
        """WM-4: `iw`/`aw` parity and `cw`/`cW`/`dw`/`dW` and other word operators follow declared classes."""
        # Established `iw` and `aw` semantics retained (WORD_BREAKS = {" ", "\t"}, line-local)
        c = make_normal("foo.bar-baz end", 2)
        send_keys(c, "diw")
        self.assertEqual((c.text, c.caret, c._register.text), (" end", 0, "foo.bar-baz"))

        c = make_normal("one\u00a0two end", 2)
        send_keys(c, "diw")
        self.assertEqual((c.text, c.caret, c._register.text), (" end", 0, "one\u00a0two"))

        c = make_normal("alpha beta\ngamma", 0)
        send_keys(c, "daw")
        self.assertEqual((c.text, c.caret, c._register.text), ("beta\ngamma", 0, "alpha "))

        c = make_normal("alpha   \nbeta", 5)
        send_keys(c, "diw")
        self.assertEqual((c.text, c.caret, c._register.text), ("alpha\nbeta", 4, "   "))

        # Adjacent image + word stays atomic for iw/aw
        c = Composer(vim=True)
        c.insert_image("[Image #1]", object())
        (tok,) = c.images
        c.replace(1, len(c.text), "tail")
        c.handle(ESC)
        c.caret = 0
        send_keys(c, "yiw")
        self.assertEqual(c._register.text, f"{tok}tail")

        # `cw` vs `cW` on non-blank stops at current run end (even on 1-char or last-char of run)
        c = make_normal("foo.bar baz", 0)
        send_keys(c, "cwX")
        self.assertEqual((c.text, c.vim_label, c._register.text), ("X.bar baz", VIM_INSERT, "foo"))

        c = make_normal("foo.bar baz", 2)  # on last char 'o' of 'foo'
        send_keys(c, "cwX")
        self.assertEqual((c.text, c.vim_label, c._register.text), ("foX.bar baz", VIM_INSERT, "o"))

        c = make_normal("foo.bar baz", 0)
        send_keys(c, "cWX")
        self.assertEqual((c.text, c.vim_label, c._register.text), ("X baz", VIM_INSERT, "foo.bar"))

        c = make_normal("foo.bar baz", 0)
        send_keys(c, "c2wX")
        self.assertEqual((c.text, c.vim_label, c._register.text), ("Xbar baz", VIM_INSERT, "foo."))

        # `cw` / `cW` from whitespace uses exclusive `w` / `W`
        c = make_normal("foo   bar.baz", 3)
        send_keys(c, "cwX")
        self.assertEqual((c.text, c.vim_label, c._register.text), ("fooXbar.baz", VIM_INSERT, "   "))

        # `dw` / `dW` deletes trailing whitespace on same line, clamps at line end in Release 02
        c = make_normal("foo.bar baz\nnext", 0)
        send_keys(c, "dw")
        self.assertEqual((c.text, c.caret, c._register.text), (".bar baz\nnext", 0, "foo"))

        c = make_normal("foo.bar baz\nnext", 0)
        send_keys(c, "dW")
        self.assertEqual((c.text, c.caret, c._register.text), ("baz\nnext", 0, "foo.bar "))

        c = make_normal("one two\nnext", 4)
        send_keys(c, "dw")
        self.assertEqual((c.text, c.caret, c._register.text), ("one \nnext", 3, "two"))

        c = make_normal("one two\nnext", 4)
        send_keys(c, "dW")
        self.assertEqual((c.text, c.caret, c._register.text), ("one \nnext", 3, "two"))

        # Operators with `b`, `B`, `e`, `E`, `ge`, `gE` and multiplicative counts (`2d2w`)
        c = make_normal("foo.bar baz", 7)  # on ' ' before 'baz'
        send_keys(c, "db")
        self.assertEqual((c.text, c.caret, c._register.text), ("foo. baz", 4, "bar"))

        c = make_normal("foo.bar baz", 7)
        send_keys(c, "dB")
        self.assertEqual((c.text, c.caret, c._register.text), (" baz", 0, "foo.bar"))

        c = make_normal("foo.bar baz", 0)
        send_keys(c, "de")
        self.assertEqual((c.text, c.caret, c._register.text), (".bar baz", 0, "foo"))

        c = make_normal("foo.bar baz", 0)
        send_keys(c, "dE")
        self.assertEqual((c.text, c.caret, c._register.text), (" baz", 0, "foo.bar"))

        c = make_normal("foo.bar baz", 8)  # on 'b' of 'baz'
        send_keys(c, "dge")
        self.assertEqual((c.text, c.caret, c._register.text), ("foo.baaz", 6, "r b"))

        c = make_normal("foo.bar baz", 8)
        send_keys(c, "dgE")
        self.assertEqual((c.text, c.caret, c._register.text), ("foo.baaz", 6, "r b"))

        c = make_normal("a.b c.d e", 0)
        send_keys(c, "2d2w")
        self.assertEqual((c.text, c.caret, c._register.text), (".d e", 0, "a.b c"))

    def test_metadata(self) -> None:
        """WM-5: NFC Hangul, combining marks, ZWJ, chips/images never split; maps survive undo/put."""
        # Decomposed Hangul normalizes to NFC; combining marks and ZWJ sequences stay single atoms
        c = Composer(vim=True)
        c.handle(Paste(f"{HANGUL_NFD} {Q_ACUTE} {FAMILY}"))
        c.handle(ESC)
        self.assertEqual(unicodedata.normalize("NFC", c.text), c.text)
        self.assertIn(HANGUL_NFC, c.text)

        c.caret = 0
        send_keys(c, "w")
        self.assertEqual(c.caret, len(HANGUL_NFC) + 1)
        send_keys(c, "w")
        self.assertEqual(c.caret, len(HANGUL_NFC) + 1 + len(Q_ACUTE) + 1)
        send_keys(c, "ge")
        self.assertEqual(c.caret, len(HANGUL_NFC) + 1)
        send_keys(c, "ge")
        self.assertEqual(c.caret, 0)
        self.assert_atom_aligned(c)

        # Chips and images survive delete, undo, redo, yank, and put with one undo step per edit
        c = Composer(vim=True)
        send_keys(c, "start ")
        c.handle(Paste(CHIP_A_TEXT))
        send_keys(c, " ")
        img = object()
        c.insert_image("[Image #1]", img)
        send_keys(c, "end")
        c.handle(ESC)
        send_keys(c, "0w")
        self.assertEqual(c.caret, len("start "))
        original = c._state()
        undo_before = len(c._undo)

        # Delete chip + space + image + space via `d2W`
        send_keys(c, "d2W")
        self.assertEqual(c.text, "start end")
        self.assertEqual(c.pastes, {})
        self.assertEqual(c.images, {})
        self.assertEqual(len(c._undo), undo_before + 1)
        self.assert_atom_aligned(c)

        # Single undo restores exact text, caret, pastes, and images
        send_keys(c, "u")
        self.assertEqual(c._state(), original)
        self.assert_atom_aligned(c)

        # Redo re-applies the deletion
        c.handle(Key(CHAR, "r", ctrl=True))
        self.assertEqual(c.text, "start end")
        self.assertEqual(c.pastes, {})
        self.assertEqual(c.images, {})

        # Put restores both the chip and the image attachment
        send_keys(c, "P")
        self.assertEqual(len(c.pastes), 1)
        self.assertEqual(list(c.pastes.values()), [CHIP_A_TEXT])
        self.assertEqual(len(c.images), 1)
        self.assertIs(next(iter(c.images.values()))[1], img)
        self.assert_atom_aligned(c)

        # Second put allocates a distinct image token pointing to the same image object
        send_keys(c, "p")
        self.assertEqual(len(c.images), 2)
        self.assertTrue(all(val[1] is img for val in c.images.values()))

    def test_routing(self) -> None:
        """WM-6: Real App busy/armed/modified Escape, leaders/pickers, Ctrl+V paste, and Enter unchanged."""
        # Busy turn: pending word prefix drops on Esc without arming interrupt; on empty composer Esc Esc interrupts
        app, client, clock = vim_app(busy=True)
        type_text(app, "alpha beta")
        app._on_input(ESC)  # INSERT -> NORMAL
        self.assertEqual((app.composer.vim_label, app.escape_armed, client.calls), (VIM_NORMAL, None, []))
        type_text(app, "2d")
        self.assertTrue(app.composer.pending)
        app._on_input(ESC)  # drops pending '2d', does not arm clear or interrupt
        self.assertEqual((app.composer.pending, app.escape_armed, client.calls), (False, None, []))
        app._on_input(ESC)  # arms clear on non-empty draft
        self.assertEqual(app.escape_armed, ("clear", clock.now))
        clock.now += DOUBLE_ESCAPE_SECONDS / 4
        app._on_input(ESC)  # clears draft
        self.assertEqual(app.composer.text, "")
        app._on_input(ESC)  # arms interrupt on empty composer
        self.assertEqual(app.escape_armed, ("interrupt", clock.now))
        clock.now += DOUBLE_ESCAPE_SECONDS / 4
        app._on_input(ESC)  # interrupts running turn
        self.assertEqual([name for name, _ in client.calls], ["session.interrupt"])

        # Modified Escape over pending leader or pending word command cancels cleanly
        app, client, clock = vim_app()
        type_text(app, "alpha beta")
        app._on_input(ESC)
        type_text(app, "g")
        self.assertTrue(app.composer.pending)
        app._on_input(Key(ESCAPE, alt=True, protocol=True))
        self.assertFalse(app.composer.pending)
        self.assertEqual(app.composer.text, "alpha beta")

        # Space leader still opens sessions / folds plan in NORMAL
        app, client, clock = vim_app()
        app._on_input(ESC)
        type_text(app, " s")
        self.assertEqual([name for name, _ in client.calls], ["session.list"])

        # Front picker preempts composer and clears pending word prefix (`g`, `2d`)
        app, client, clock = vim_app()
        type_text(app, "alpha beta")
        app._on_input(ESC)
        type_text(app, "g")
        self.assertTrue(app.composer.pending)
        app.picker = SessionPicker([SessionRow(SID, "title", "", 0.0, 1)], current=app.stored_id)
        app.picker.waiting = False
        app._on_input(Key(CHAR, "e"))  # goes to picker filter, not composer `ge`
        self.assertFalse(app.composer.pending)
        self.assertEqual(app.composer.text, "alpha beta")

        # A waiting picker leaves word commands with the composer until navigation acquires it.
        app, client, clock = vim_app()
        type_text(app, "alpha beta")
        app._on_input(ESC)
        type_text(app, "0g")
        app.picker = SessionPicker([SessionRow(SID, "title", "", 0.0, 1)], current=app.stored_id, waiting=True)
        app._on_input(Key(CHAR, "e"))
        self.assertEqual(state(app.composer), ("alpha beta", 0, VIM_NORMAL))
        self.assertFalse(app.composer.pending)
        type_text(app, "w")
        self.assertEqual(state(app.composer), ("alpha beta", 6, VIM_NORMAL))
        self.assertEqual((app.picker.waiting, app.picker.query, client.calls), (True, "", []))

        # Server clarify question uses non-modal composer
        app, client, clock = vim_app()
        type_text(app, "draft text")
        app._on_input(ESC)
        app._on_server_request(ServerRequest("srq-1", "clarify", CLARIFY))
        clock.now += 1.0
        type_text(app, "wWbBeE")
        self.assertEqual(app.composer.text, "wWbBeE")

        # Bracketed paste in NORMAL inserts at caret and stays NORMAL
        app, client, clock = vim_app()
        type_text(app, "ab")
        app._on_input(ESC)
        app._on_input(Paste("XY"))
        self.assertEqual((app.composer.text, app.composer.vim_label), ("aXYb", VIM_NORMAL))

        # Ctrl+V retrieves a staged clipboard image, not bracketed text or a Vim command.
        app, client, clock = vim_app(environ={"NO_COLOR": "1"})
        type_text(app, "ab")
        app._on_input(ESC)
        app._on_input(Key(CHAR, "v", ctrl=True))
        self.assertEqual(client.calls, [("clipboard.paste", {"session_id": SID})])
        self.assertEqual(state(app.composer), ("ab", 1, VIM_NORMAL))
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / "clipboard.png"
            data = b"\x89PNG\r\n\x1a\n"
            path.write_bytes(data)
            answer(app, client, {"attached": True, "path": str(path), "name": "clipboard.png"})
            self.assertEqual(client.named("image.detach"), [{"session_id": SID, "path": str(path)}])
        self.assertEqual(app.composer.expanded(), "a [Image #1] b")
        self.assertEqual(app.composer.vim_label, VIM_NORMAL)
        self.assertEqual(len(app.composer.images), 1)
        self.assertEqual(next(iter(app.composer.images.values()))[1].data, data)
        self.assertFalse(app.composer.pending)
        self.assert_atom_aligned(app.composer)

        # Enter in NORMAL submits draft; pending `g` + Enter cancels prefix without submitting
        app, client, clock = vim_app()
        type_text(app, "send now")
        app._on_input(ESC)
        type_text(app, "g")
        app._on_input(Key(ENTER))
        self.assertEqual(client.named("prompt.submit"), [])
        self.assertEqual(app.composer.text, "send now")
        app._on_input(Key(ENTER))
        self.assertEqual(client.named("prompt.submit")[-1]["text"], "send now")
        self.assertEqual(app.composer.vim_label, VIM_INSERT)

        # Busy Enter queues rather than submitting; either send-now key redirects the queued draft.
        for send_now in (Key(ENTER, ctrl=True), STEER_FALLBACK_KEY):
            with self.subTest(send_now=send_now):
                app, client, clock = vim_app(busy=True)
                type_text(app, "queue now")
                app._on_input(ESC)
                type_text(app, "g")
                app._on_input(Key(ENTER))
                self.assertEqual(state(app.composer), ("queue now", 8, VIM_NORMAL))
                self.assertFalse(app.composer.pending)
                self.assertEqual((client.calls, list(app.queued)), ([], []))
                app._on_input(Key(ENTER))
                self.assertEqual([line.text for line in app.queued], ["queue now"])
                self.assertEqual(state(app.composer), ("", 0, VIM_INSERT))
                self.assertEqual(client.calls, [])
                app._on_input(ESC)  # exercise send-now while NORMAL, not just the shared INSERT harness
                app._on_input(send_now)
                self.assertEqual(client.calls, [("session.redirect", {"session_id": SID, "text": "queue now"})])
                self.assertFalse(app.queued)
                answer(app, client, error={"code": 4010, "message": "agent does not support active-turn redirect"})
                self.assertEqual(client.calls[-1], ("session.steer", {"session_id": SID, "text": "queue now"}))
                self.assertEqual(state(app.composer), ("", 0, VIM_NORMAL))

    @unittest.skipIf(__import__("os").name == "nt", "POSIX PTY only; the OMH TUI does not run on Windows")
    def test_pty(self) -> None:
        """WM-7: Real terminal displays each motion destination across wraps (20 and 100 cols)."""
        assert_word_motions_pty(self)


if __name__ == "__main__":
    unittest.main()
