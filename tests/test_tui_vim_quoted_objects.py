"""Vim quoted text objects in the TUI composer: `i` and `a` with a double quote, single quote or backtick under
`c`, `d` and `y`.

The composer half pins the spans (counts, escapes, blanks, the caret on or off a quote, line-local scans,
paste chips and images as one unit), the register, the caret and undo. The App half pins how the keys reach a
pending object: Shift, Alt, Esc, Ctrl+C, Enter, Paste, pickers and questions.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from test_tui_modes import make_app, type_text
from omh.tui.composer import Composer, VIM_INSERT, _Register
from omh.tui.gateway import ServerRequest
from omh.tui.keys import CHAR, ENTER, ESCAPE, TAB, Key, KeyDecoder, Paste
from omh.tui.session_picker import SessionPicker, SessionRow

ESC = Key(ESCAPE)
CLARIFY = {"questions": [{"qid": "q0", "question": "Why?"}]}


def make_vim_composer(text: str = "", caret: int | None = None) -> Composer:
    c = Composer(vim=True)
    if text:
        c.replace(0, 0, text)
        c.handle(ESC)
    if caret is not None:
        c.caret = caret
    return c


def send_keys(composer: Composer, typed: str) -> None:
    for ch in typed:
        composer.handle(Key(CHAR, ch))


class VimQuotedObjectsTests(unittest.TestCase):
    def test_quote_operator_matrix(self) -> None:
        """All six objects x c/d/y exact spans; no inserted target."""
        # For each quote char: ", ', `
        for q in ('"', "'", "`"):
            # inner tests: x "abc" z, caret on 'b'
            # y inner:
            c = make_vim_composer(f"x {q}abc{q} z")
            c.caret = 4  # on 'b'
            send_keys(c, f"yi{q}")
            self.assertEqual(c.text, f"x {q}abc{q} z")
            self.assertEqual(c.caret, 3)  # caret at start of yanked content ('a')
            self.assertEqual(c._register.text, "abc")
            self.assertFalse(c._register.linewise)
            self.assertTrue(c.normal)
            self.assertFalse(c.pending)

            # d inner:
            c = make_vim_composer(f"x {q}abc{q} z")
            c.caret = 4
            send_keys(c, f"di{q}")
            self.assertEqual(c.text, f"x {q}{q} z")
            self.assertEqual(c.caret, 3)  # clamped to closing quote
            self.assertEqual(c._register.text, "abc")
            self.assertFalse(c._register.linewise)
            self.assertTrue(c.normal)
            self.assertFalse(c.pending)

            # c inner:
            c = make_vim_composer(f"x {q}abc{q} z")
            c.caret = 4
            send_keys(c, f"ci{q}")
            self.assertEqual(c.text, f"x {q}{q} z")
            self.assertEqual(c.caret, 3)  # between quotes in INSERT
            self.assertEqual(c._register.text, "abc")
            self.assertFalse(c._register.linewise)
            self.assertFalse(c.normal)
            self.assertEqual(c.vim_label, VIM_INSERT)
            self.assertFalse(c.pending)

            # around tests: x "abc" z, caret on 'b'
            # y around: trailing space is preferred -> "abc" + " "
            c = make_vim_composer(f"x {q}abc{q} z")
            c.caret = 4
            send_keys(c, f"ya{q}")
            self.assertEqual(c.text, f"x {q}abc{q} z")
            self.assertEqual(c.caret, 2)  # start of span
            self.assertEqual(c._register.text, f"{q}abc{q} ")
            self.assertFalse(c._register.linewise)
            self.assertTrue(c.normal)
            self.assertFalse(c.pending)

            # d around:
            c = make_vim_composer(f"x {q}abc{q} z")
            c.caret = 4
            send_keys(c, f"da{q}")
            self.assertEqual(c.text, "x z")
            self.assertEqual(c.caret, 2)  # clamped to 'z'
            self.assertEqual(c._register.text, f"{q}abc{q} ")
            self.assertFalse(c._register.linewise)
            self.assertTrue(c.normal)
            self.assertFalse(c.pending)

            # c around:
            c = make_vim_composer(f"x {q}abc{q} z")
            c.caret = 4
            send_keys(c, f"ca{q}")
            self.assertEqual(c.text, "x z")
            self.assertEqual(c.caret, 2)
            self.assertEqual(c._register.text, f"{q}abc{q} ")
            self.assertFalse(c._register.linewise)
            self.assertFalse(c.normal)
            self.assertEqual(c.vim_label, VIM_INSERT)
            self.assertFalse(c.pending)

    def test_quote_scope_preserves_word_and_modes(self) -> None:
        """`iw`/`aw` and off/masked/INSERT unchanged; invalid no-op."""
        # 1. Existing iw/aw remains unchanged: diw, daw, caw, y2aw
        c = make_vim_composer("hello world", caret=1)
        send_keys(c, "diw")
        self.assertEqual(c.text, " world")
        self.assertEqual(c.caret, 0)
        self.assertEqual(c._register.text, "hello")

        c = make_vim_composer("hello world", caret=1)
        send_keys(c, "daw")
        self.assertEqual(c.text, "world")
        self.assertEqual(c.caret, 0)
        self.assertEqual(c._register.text, "hello ")

        c = make_vim_composer("hello world", caret=1)
        send_keys(c, "caw")
        self.assertEqual(c.text, "world")
        self.assertEqual(c.caret, 0)
        self.assertEqual(c._register.text, "hello ")
        self.assertFalse(c.normal)
        self.assertEqual(c.vim_label, VIM_INSERT)

        c = make_vim_composer("one two three", caret=0)
        send_keys(c, "y2aw")
        self.assertEqual(c.text, "one two three")
        self.assertEqual(c.caret, 0)
        self.assertEqual(c._register.text, "one two ")
        self.assertTrue(c.normal)

        # 2. Bare i and a retain ordinary insert/append meaning
        c = make_vim_composer("hello", caret=2)
        send_keys(c, "iX")
        self.assertEqual(c.text, "heXllo")
        self.assertFalse(c.normal)
        c.handle(ESC)
        self.assertTrue(c.normal)
        send_keys(c, "aY")
        self.assertEqual(c.text, "heXYllo")
        self.assertFalse(c.normal)

        # 3. Masked input is never modal
        c_masked = Composer(vim=True)
        c_masked.masked = True
        c_masked.replace(0, 0, 'secret "quoted" value')
        c_masked.caret = 8
        c_masked.handle(ESC)  # Esc in masked does not switch to normal
        self.assertFalse(c_masked.normal)
        send_keys(c_masked, 'di"')
        self.assertIn('di"', c_masked.text)

        # 4. Unknown object targets cancel without mutation
        c = make_vim_composer("hello world", caret=1)
        send_keys(c, "di?")
        self.assertEqual(c.text, "hello world")
        self.assertEqual(c.caret, 1)
        self.assertFalse(c.pending)
        self.assertTrue(c.normal)

        c = make_vim_composer("hello world", caret=1)
        send_keys(c, "di(")
        self.assertEqual(c.text, "hello world")
        self.assertEqual(c.caret, 1)
        self.assertFalse(c.pending)

        # 5. Off vim mode: keys type literally
        c_off = Composer(vim=False)
        send_keys(c_off, 'di"')
        self.assertEqual(c_off.text, 'di"')

        # 6. In INSERT mode: keys type literally
        c_ins = Composer(vim=True)
        self.assertFalse(c_ins.normal)
        send_keys(c_ins, 'di"')
        self.assertEqual(c_ins.text, 'di"')

    def test_quote_cursor_target_matrix(self) -> None:
        """Before/on/inside/closing/gap/after/adjacency literal outputs."""
        for q in ('"', "'", "`"):
            text = f"xx {q}aa{q}  {q}bb{q} zz"
            # 0: 'x', 3: q, 4: 'a', 6: q, 7: ' ', 8: ' ', 9: q, 10: 'b', 12: q, 13: ' ', 15: 'z'
            # yi on 0/3/4/6 -> "aa"
            for idx in (0, 3, 4, 6):
                c = make_vim_composer(text, caret=idx)
                send_keys(c, f"yi{q}")
                self.assertEqual(c._register.text, "aa", f"Failed for {q} at caret {idx}")

            # yi on 7/8 (gap) -> prior closing quote is next opener, selects "  "
            for idx in (7, 8):
                c = make_vim_composer(text, caret=idx)
                send_keys(c, f"yi{q}")
                self.assertEqual(c._register.text, "  ", f"Failed for {q} at caret {idx}")

            # yi on 9/10/12 -> "bb"
            for idx in (9, 10, 12):
                c = make_vim_composer(text, caret=idx)
                send_keys(c, f"yi{q}")
                self.assertEqual(c._register.text, "bb", f"Failed for {q} at caret {idx}")

            # yi on 13/15 -> after last pair, no match!
            for idx in (13, 15):
                c = make_vim_composer(text, caret=idx)
                c._register = None
                send_keys(c, f"yi{q}")
                self.assertIsNone(c._register, f"Failed for {q} at caret {idx}")
                self.assertFalse(c.pending)

            # Adjacent quotes: "a""b"
            adj_text = f"{q}a{q}{q}b{q}"
            c = make_vim_composer(adj_text, caret=2)
            send_keys(c, f"yi{q}")
            self.assertEqual(c._register.text, "a")

            c = make_vim_composer(adj_text, caret=3)
            send_keys(c, f"yi{q}")
            self.assertEqual(c._register.text, "b")

    def test_quote_escape_parity(self) -> None:
        """1/2/3/4 backslashes, raw opener, escaped caret, mixed quotes."""
        for q in ('"', "'", "`"):
            # 1 backslash: odd -> escaped quote, does not close
            c = make_vim_composer(f"{q}a\\{q}b{q}", caret=1)
            send_keys(c, f"yi{q}")
            self.assertEqual(c._register.text, f"a\\{q}b")

            # 2 backslashes: even -> backslash is escaped, quote closes
            c = make_vim_composer(f"{q}a\\\\{q}b{q}", caret=1)
            send_keys(c, f"yi{q}")
            self.assertEqual(c._register.text, "a\\\\")

            # 3 backslashes: odd -> escaped quote
            c = make_vim_composer(f"{q}a\\\\\\{q}b{q}", caret=1)
            send_keys(c, f"yi{q}")
            self.assertEqual(c._register.text, f"a\\\\\\{q}b")

            # 4 backslashes: even -> quote closes
            c = make_vim_composer(f"{q}a\\\\\\\\{q}b{q}", caret=1)
            send_keys(c, f"yi{q}")
            self.assertEqual(c._register.text, "a\\\\\\\\")

            # Raw opener discovery ignores escape parity: \ "x"
            c = make_vim_composer(f"\\{q}x{q}", caret=0)
            send_keys(c, f"yi{q}")
            self.assertEqual(c._register.text, "x")

            # Escaped quote under caret is located within line-start pair enumeration
            c = make_vim_composer(f"{q}a\\{q}b{q}", caret=3)  # caret on escaped q
            send_keys(c, f"yi{q}")
            self.assertEqual(c._register.text, f"a\\{q}b")

        # Mixed quotes: other quote characters are ordinary content
        c = make_vim_composer("\"a'b`c\"", caret=1)
        send_keys(c, 'yi"')
        self.assertEqual(c._register.text, "a'b`c")

        c = make_vim_composer("'a\"b`c'", caret=1)
        send_keys(c, "yi'")
        self.assertEqual(c._register.text, 'a"b`c')

        c = make_vim_composer("`a\"b'c`", caret=1)
        send_keys(c, "yi`")
        self.assertEqual(c._register.text, 'a"b\'c')

    def test_quote_around_whitespace_line_local(self) -> None:
        """Trailing-first blanks else leading; NBSP/newline excluded."""
        # 1. Trailing blanks present: prefer trailing blanks
        c = make_vim_composer('a "x" \tq', caret=3)
        send_keys(c, 'ya"')
        self.assertEqual(c._register.text, '"x" \t')

        # 2. No trailing blanks, but leading blanks present: take leading blanks
        c = make_vim_composer('a  "x"', caret=4)
        send_keys(c, 'ya"')
        self.assertEqual(c._register.text, '  "x"')

        # 3. NBSP (\u00a0) adjacent: not ASCII space/tab, not absorbed
        c = make_vim_composer('a\u00a0"x"\u00a0b', caret=3)
        send_keys(c, 'ya"')
        self.assertEqual(c._register.text, '"x"')

        # 4. Cross-line quote: opener on line 1, closer on line 2 -> no match on line 1
        c = make_vim_composer('a "x\ny" b', caret=2)
        c._register = None
        send_keys(c, 'ya"')
        self.assertIsNone(c._register)
        self.assertFalse(c.pending)

    def test_quote_count_contract(self) -> None:
        """Count placements/multiply/cap; no next-pair or count-loop."""
        # "aa" "bb", caret 1
        # yi" -> aa
        c = make_vim_composer('"aa" "bb"', caret=1)
        send_keys(c, 'yi"')
        self.assertEqual(c._register.text, "aa")

        # count >= 2 inner selects delimiters: "aa"
        c = make_vim_composer('"aa" "bb"', caret=1)
        send_keys(c, 'y2i"')
        self.assertEqual(c._register.text, '"aa"')

        # operator count: 2yi" -> "aa"
        c = make_vim_composer('"aa" "bb"', caret=1)
        send_keys(c, '2yi"')
        self.assertEqual(c._register.text, '"aa"')

        # multiplied counts: 2y3i" -> "aa"
        c = make_vim_composer('"aa" "bb"', caret=1)
        send_keys(c, '2y3i"')
        self.assertEqual(c._register.text, '"aa"')

        # capped count: y9999i" -> "aa"
        c = make_vim_composer('"aa" "bb"', caret=1)
        send_keys(c, 'y9999i"')
        self.assertEqual(c._register.text, '"aa"')

        # ya" -> "aa"
        c = make_vim_composer('"aa" "bb"', caret=1)
        send_keys(c, 'ya"')
        self.assertEqual(c._register.text, '"aa" ')

        # y9999a" -> "aa"
        c = make_vim_composer('"aa" "bb"', caret=1)
        send_keys(c, 'y9999a"')
        self.assertEqual(c._register.text, '"aa" ')

        # d count placements: d2i", 2di", 2d3i", d9999i", da", 2da", d9999a"
        c = make_vim_composer('x "aa" "bb" z', caret=3)
        send_keys(c, 'd2i"')
        self.assertEqual(c.text, 'x  "bb" z')
        self.assertEqual(c._register.text, '"aa"')

        c = make_vim_composer('x "aa" "bb" z', caret=3)
        send_keys(c, '2di"')
        self.assertEqual(c.text, 'x  "bb" z')
        self.assertEqual(c._register.text, '"aa"')

        c = make_vim_composer('x "aa" "bb" z', caret=3)
        send_keys(c, '2d3i"')
        self.assertEqual(c.text, 'x  "bb" z')
        self.assertEqual(c._register.text, '"aa"')

        c = make_vim_composer('x "aa" "bb" z', caret=3)
        send_keys(c, 'd9999i"')
        self.assertEqual(c.text, 'x  "bb" z')
        self.assertEqual(c._register.text, '"aa"')

        c = make_vim_composer('x "aa" "bb" z', caret=3)
        send_keys(c, 'da"')
        self.assertEqual(c.text, 'x "bb" z')
        self.assertEqual(c._register.text, '"aa" ')

        c = make_vim_composer('x "aa" "bb" z', caret=3)
        send_keys(c, '2da"')
        self.assertEqual(c.text, 'x "bb" z')
        self.assertEqual(c._register.text, '"aa" ')

        c = make_vim_composer('x "aa" "bb" z', caret=3)
        send_keys(c, 'd9999a"')
        self.assertEqual(c.text, 'x "bb" z')
        self.assertEqual(c._register.text, '"aa" ')

        # c count placements: c2i", 2ci", 2c3i", c9999i", ca", 2ca", c9999a"
        c = make_vim_composer('x "aa" "bb" z', caret=3)
        send_keys(c, 'c2i"W')
        c.handle(ESC)
        self.assertEqual(c.text, 'x W "bb" z')
        self.assertEqual(c._register.text, '"aa"')

        c = make_vim_composer('x "aa" "bb" z', caret=3)
        send_keys(c, '2ci"W')
        c.handle(ESC)
        self.assertEqual(c.text, 'x W "bb" z')
        self.assertEqual(c._register.text, '"aa"')

        c = make_vim_composer('x "aa" "bb" z', caret=3)
        send_keys(c, '2c3i"W')
        c.handle(ESC)
        self.assertEqual(c.text, 'x W "bb" z')
        self.assertEqual(c._register.text, '"aa"')

        c = make_vim_composer('x "aa" "bb" z', caret=3)
        send_keys(c, 'c9999i"W')
        c.handle(ESC)
        self.assertEqual(c.text, 'x W "bb" z')
        self.assertEqual(c._register.text, '"aa"')

        c = make_vim_composer('x "aa" "bb" z', caret=3)
        send_keys(c, 'ca"W')
        c.handle(ESC)
        self.assertEqual(c.text, 'x W"bb" z')
        self.assertEqual(c._register.text, '"aa" ')

        c = make_vim_composer('x "aa" "bb" z', caret=3)
        send_keys(c, '2ca"W')
        c.handle(ESC)
        self.assertEqual(c.text, 'x W"bb" z')
        self.assertEqual(c._register.text, '"aa" ')

        c = make_vim_composer('x "aa" "bb" z', caret=3)
        send_keys(c, 'c9999a"W')
        c.handle(ESC)
        self.assertEqual(c.text, 'x W"bb" z')
        self.assertEqual(c._register.text, '"aa" ')

    def test_quote_register_cursor_undo(self) -> None:
        """`c`/`d`/`y`, `p`/`P`, `u`/Ctrl+R exact state/metadata; grouped change."""
        # di"
        c = make_vim_composer('x "abc" z', caret=3)
        send_keys(c, 'di"')
        self.assertEqual(c.text, 'x "" z')
        self.assertEqual(c._register.text, "abc")
        self.assertFalse(c._register.linewise)
        # u undoes di"
        send_keys(c, "u")
        self.assertEqual(c.text, 'x "abc" z')
        # Ctrl+R redoes di"
        c.handle(Key(CHAR, "r", ctrl=True))
        self.assertEqual(c.text, 'x "" z')

        # ci" + typed text + Esc is grouped into one undo
        c = make_vim_composer('x "abc" z', caret=3)
        send_keys(c, 'ci"Z')
        c.handle(ESC)
        self.assertEqual(c.text, 'x "Z" z')
        self.assertTrue(c.normal)
        send_keys(c, "u")
        self.assertEqual(c.text, 'x "abc" z')

        # yi" does not create text mutation undo step
        c = make_vim_composer('x "abc" z', caret=3)
        undo_len_before = len(c._undo)
        send_keys(c, 'yi"')
        self.assertEqual(c._register.text, "abc")
        self.assertEqual(c.caret, 3)
        self.assertEqual(len(c._undo), undo_len_before)  # no undo step created by yank

        # put p / P preserves characterwise register and caret
        # p puts after caret
        c.caret = 3
        send_keys(c, "p")
        self.assertEqual(c.text, 'x "aabcbc" z')

        # P puts before caret
        c = make_vim_composer('x "abc" z', caret=3)
        send_keys(c, 'yi"')
        c.caret = 3
        send_keys(c, "P")
        self.assertEqual(c.text, 'x "abcabc" z')
        self.assertFalse(c._register.linewise)

    def test_quote_empty_policy(self) -> None:
        """Empty register/caret compatibility and count2 endpoints."""
        for q in ('"', "'", "`"):
            text = f"{q}{q}"
            for start_caret in (0, 1):
                # 1. yi: preserves SEED, caret lands at 1, NORMAL mode
                c = make_vim_composer(text, caret=start_caret)
                seed_reg = _Register("SEED", {}, {}, False)
                c._register = seed_reg
                send_keys(c, f"yi{q}")
                self.assertIs(c._register, seed_reg)
                self.assertEqual(c.caret, 1)
                self.assertTrue(c.normal)

                # 2. di: preserves SEED, caret unchanged, NORMAL mode
                c = make_vim_composer(text, caret=start_caret)
                c._register = seed_reg
                send_keys(c, f"di{q}")
                self.assertIs(c._register, seed_reg)
                self.assertEqual(c.caret, start_caret)
                self.assertEqual(c.text, text)
                self.assertTrue(c.normal)

                # 3. ci: enters INSERT between quotes without deleting, preserves SEED until yank, undoes cleanly
                c = make_vim_composer(text, caret=start_caret)
                c._register = seed_reg
                send_keys(c, f"ci{q}Z")
                self.assertIs(c._register, seed_reg)
                c.handle(ESC)
                self.assertEqual(c.text, f"{q}Z{q}")
                self.assertTrue(c.normal)
                send_keys(c, "u")
                self.assertEqual(c.text, text)

                # 4. count-2 y stores the two quotes: y2i" -> '""'
                c = make_vim_composer(text, caret=start_caret)
                send_keys(c, f"y2i{q}")
                self.assertEqual(c._register.text, text)
                self.assertFalse(c._register.linewise)

    def test_quote_no_match_noop(self) -> None:
        """No quote/malformed/after last/cross-line preserve state."""
        seed_reg = _Register("SEED", {}, {}, False)

        # 1. No quote on line
        c = make_vim_composer("hello world", caret=3)
        c._register = seed_reg
        undo_len = len(c._undo)
        send_keys(c, 'di"')
        self.assertEqual(c.text, "hello world")
        self.assertEqual(c.caret, 3)
        self.assertIs(c._register, seed_reg)
        self.assertEqual(len(c._undo), undo_len)
        self.assertTrue(c.normal)
        self.assertFalse(c.pending)

        # 2. Unmatched single quote
        c = make_vim_composer('hello "world', caret=2)
        c._register = seed_reg
        undo_len = len(c._undo)
        send_keys(c, 'ci"')
        self.assertEqual(c.text, 'hello "world')
        self.assertEqual(c.caret, 2)
        self.assertIs(c._register, seed_reg)
        self.assertEqual(len(c._undo), undo_len)
        self.assertTrue(c.normal)  # c does NOT enter insert on no match
        self.assertFalse(c.pending)

        # 3. Caret after final paired quote
        c = make_vim_composer('"hello" world', caret=10)
        c._register = seed_reg
        undo_len = len(c._undo)
        send_keys(c, 'da"')
        self.assertEqual(c.text, '"hello" world')
        self.assertEqual(c.caret, 10)
        self.assertIs(c._register, seed_reg)
        self.assertEqual(len(c._undo), undo_len)
        self.assertTrue(c.normal)
        self.assertFalse(c.pending)

        # 4. Cross-line split pair
        c = make_vim_composer('one "two\nthree" four', caret=4)
        c._register = seed_reg
        undo_len = len(c._undo)
        send_keys(c, 'yi"')
        self.assertEqual(c.text, 'one "two\nthree" four')
        self.assertEqual(c.caret, 4)
        self.assertIs(c._register, seed_reg)
        self.assertEqual(len(c._undo), undo_len)
        self.assertTrue(c.normal)
        self.assertFalse(c.pending)

    def test_quote_atomic_content(self) -> None:
        """Opaque paste/image and grapheme syntax/boundary protection."""
        # 1. Grapheme starting with quote + combining mark is not syntax delimiter
        # e.g. '"' + combining acute \u0301 -> single grapheme atom
        q_comb = '"\u0301'
        c = make_vim_composer(f"x {q_comb}abc{q_comb} z", caret=4)
        c._register = None
        send_keys(c, 'yi"')
        self.assertIsNone(c._register)

        # 2. Combining, ZWJ, skin tone, Hangul inside quote are preserved and carets equal atom bounds
        # ZWJ emoji (👨‍👩‍👧‍👦), skin tone (👋🏽), Hangul (Composer normalizes input with NFC)
        complex_text = 'x "👋🏽 👨‍👩‍👧‍👦 한글" z'
        c = make_vim_composer(complex_text, caret=4)
        send_keys(c, 'yi"')
        self.assertEqual(c._register.text, "👋🏽 👨‍👩‍👧‍👦 한글")
        units, bounds, _ = c._atoms()
        self.assertIn(c.caret, bounds)

        # 3. Opaque paste chip and image tokens between quotes: full c/d/y i/a p/P undo/redo lifecycle
        c = make_vim_composer('x "" z', caret=0)
        c.pastes = {"[Pasted text #1 +1 lines]": "internal \"quotes\" and \\"}
        c.images = {"\ue000": ("[Image #1]", "fake_image_bytes")}
        c.text = 'x "[Pasted text #1 +1 lines] \ue000" z'
        c.caret = 4

        # yank inner
        send_keys(c, 'yi"')
        self.assertEqual(c._register.text, "[Pasted text #1 +1 lines] \ue000")
        self.assertIn("[Pasted text #1 +1 lines]", c._register.pastes)
        self.assertIn("\ue000", c._register.images)

        # delete inner
        send_keys(c, 'di"')
        self.assertEqual(c.text, 'x "" z')
        self.assertNotIn("[Pasted text #1 +1 lines]", c.pastes)
        self.assertNotIn("\ue000", c.images)

        # undo puts them back with attachments intact
        send_keys(c, "u")
        self.assertEqual(c.text, 'x "[Pasted text #1 +1 lines] \ue000" z')
        self.assertIn("[Pasted text #1 +1 lines]", c.pastes)
        self.assertIn("\ue000", c.images)

        # redo deletes them again
        c.handle(Key(CHAR, "r", ctrl=True))
        self.assertEqual(c.text, 'x "" z')

        # put p puts them back into empty quotes
        # fresh composer for ca"
        c2 = make_vim_composer('x "[Pasted text #1 +1 lines] \ue000" z', caret=4)
        c2.pastes = {"[Pasted text #1 +1 lines]": "internal \"quotes\" and \\"}
        c2.images = {"\ue000": ("[Image #1]", "fake_image_bytes")}
        send_keys(c2, 'ca"NEW')
        c2.handle(ESC)
        self.assertEqual(c2.text, "x NEWz")
        send_keys(c2, "u")
        self.assertEqual(c2.text, 'x "[Pasted text #1 +1 lines] \ue000" z')
        self.assertIn("[Pasted text #1 +1 lines]", c2.pastes)
        self.assertIn("\ue000", c2.images)

    def test_app_quote_target_and_cancel(self) -> None:
        """Actual App Shift/Alt/Esc/Ctrl+C/picker/slot/Paste/armed exit."""
        app, client = make_app()
        app.composer.set_vim(True)
        type_text(app, 'x "abc" z')
        app._on_input(ESC)
        app.composer.caret = 4

        # 1. Shifted quote target: 'di' then Shift+'"' (Key(CHAR, '"', shift=True))
        app._on_input(Key(CHAR, "d"))
        app._on_input(Key(CHAR, "i"))
        self.assertTrue(app.composer.pending)
        app._on_input(Key(CHAR, '"', shift=True))
        self.assertFalse(app.composer.pending)
        self.assertEqual(app.composer.text, 'x "" z')

        # 2. Esc during pending cancels pending and clears escape_armed
        app.composer.text = 'x "abc" z'
        app.composer.caret = 4
        app.escape_armed = ("clear", 100.0)
        app._on_input(Key(CHAR, "d"))
        app._on_input(Key(CHAR, "i"))
        self.assertTrue(app.composer.pending)
        app._on_input(ESC)
        self.assertFalse(app.composer.pending)
        self.assertEqual(app.composer.text, 'x "abc" z')
        self.assertIsNone(app.escape_armed)

        # Next Esc arms afresh
        app._on_input(ESC)
        self.assertIsNotNone(app.escape_armed)
        self.assertEqual(app.composer.text, 'x "abc" z')
        app.escape_armed = None

        # 3. Ctrl+C with no exit armed cancels pending and keeps the draft (an armed exit: the lifecycle tests)
        app._on_input(Key(CHAR, "d"))
        app._on_input(Key(CHAR, "i"))
        self.assertTrue(app.composer.pending)
        app._on_input(Key(CHAR, "c", ctrl=True))
        self.assertFalse(app.composer.pending)
        self.assertEqual(app.composer.text, 'x "abc" z')
        self.assertIsNone(app.exit_code)
        self.assertIsNone(app.exit_armed_at)

        # 4. Protocol Alt cancels pending quote target
        app._on_input(Key(CHAR, "d"))
        app._on_input(Key(CHAR, "i"))
        self.assertTrue(app.composer.pending)
        app._on_input(Key(CHAR, '"', alt=True, protocol=True))
        self.assertFalse(app.composer.pending)
        self.assertEqual(app.composer.text, 'x "abc" z')

        # Legacy Alt is Esc and the key: Esc cancels the object, the quote is then a fresh key (a no-op)
        app._on_input(Key(CHAR, "d"))
        app._on_input(Key(CHAR, "i"))
        self.assertTrue(app.composer.pending)
        app._on_input(Key(CHAR, '"', alt=True, protocol=False))
        self.assertFalse(app.composer.pending)
        self.assertEqual(app.composer.text, 'x "abc" z')

        # Legacy Alt-w the same way: Esc cancels the object, then w moves a word and deletes nothing
        app.composer.text = "hello world"
        app.composer.caret = 1
        app._on_input(Key(CHAR, "d"))
        app._on_input(Key(CHAR, "i"))
        self.assertTrue(app.composer.pending)
        app._on_input(Key(CHAR, "w", alt=True, protocol=False))
        self.assertFalse(app.composer.pending)
        self.assertEqual((app.composer.text, app.composer.caret), ("hello world", 6))

        # 5. Paste drops pending and inserts paste
        app.composer.text = 'x "abc" z'
        app.composer.caret = 4
        app._on_input(Key(CHAR, "d"))
        app._on_input(Key(CHAR, "i"))
        self.assertTrue(app.composer.pending)
        app._on_input(Paste("hello"))
        self.assertFalse(app.composer.pending)
        self.assertIn("hello", app.composer.text)

        # 6. Higher-priority picker acquisition drops pending
        app._on_input(Key(CHAR, "d"))
        app._on_input(Key(CHAR, "i"))
        self.assertTrue(app.composer.pending)
        app.picker = SessionPicker([SessionRow("s1", "Session 1", "", 100.0, 1)], current=app.stored_id)
        app.picker.waiting = False
        with patch.object(app, "_picker_key") as picker_key_mock:
            app._on_input(Key(CHAR, "j"))
            picker_key_mock.assert_called_once()
        self.assertFalse(app.composer.pending)
        app.picker = None

        # 7. Slot question priority drops pending or owns keys
        app._on_input(Key(CHAR, "d"))
        app._on_input(Key(CHAR, "i"))
        self.assertTrue(app.composer.pending)
        app._on_server_request(ServerRequest("srq-1", "clarify", CLARIFY))
        self.assertIsNotNone(app.slot)
        # Key to slot
        app._on_input(Key(CHAR, "1"))
        self.assertFalse(app.composer.pending)
        app.slot = None

    def test_app_quote_submit_isolation(self) -> None:
        """Pending Enter cancels; fresh Enter sends/reset; continuation."""
        app, client = make_app()
        app.composer.set_vim(True)
        type_text(app, 'x "abc" z')
        app._on_input(ESC)
        app.composer.caret = 4

        # 1. Pending Enter cancels without submit
        app._on_input(Key(CHAR, "d"))
        app._on_input(Key(CHAR, "i"))
        self.assertTrue(app.composer.pending)
        app._on_input(Key(ENTER))
        self.assertFalse(app.composer.pending)
        self.assertEqual(client.calls, [])
        self.assertEqual(app.composer.text, 'x "abc" z')

        # 2. Fresh Enter in NORMAL sends prompt and resets to INSERT
        app._on_input(Key(ENTER))
        self.assertEqual(client.named("prompt.submit")[-1]["text"], 'x "abc" z')
        self.assertFalse(app.composer.normal)

        # 3. Enter after backslash in NORMAL sends
        app, client2 = make_app()
        app.composer.set_vim(True)
        type_text(app, "test \\")
        app._on_input(ESC)
        app._on_input(Key(ENTER))
        self.assertEqual(client2.named("prompt.submit")[-1]["text"], "test \\")

        # 4. Backslash then Enter in INSERT adds a newline continuation
        app, _client3 = make_app()
        app.composer.set_vim(True)
        type_text(app, "line 1\\")
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, "line 1\n")
        self.assertFalse(app.composer.normal)

        # 5. Alt+Enter, Shift+Enter, Ctrl+J add line outside pending
        app._on_input(Key(ENTER, alt=True))
        self.assertEqual(app.composer.text, "line 1\n\n")

        app._on_input(Key(ENTER, shift=True))
        self.assertEqual(app.composer.text, "line 1\n\n\n")

        app._on_input(Key(CHAR, "j", ctrl=True))
        self.assertEqual(app.composer.text, "line 1\n\n\n\n")


class QuoteLifecycleRegressionTests(unittest.TestCase):
    """Own the attachment and input-state boundaries that first escaped review."""

    def assert_atom_caret(self, composer):
        self.assertIn(composer.caret, composer._atoms()[1])

    def attached(self, quote):
        composer = make_vim_composer(quote + 'e\u0301 👩🏽\u200d💻 한글 ' + quote)
        composer.caret = len(composer.text) - 1
        payload = 'hidden " \' ` \\\n' * 6 + '👩🏽\u200d💻 e\u0301 한글'
        composer.handle(Paste(payload))
        image = object()
        self.assertTrue(composer.insert_image('[Image " \\\n]', image))
        self.assertTrue(composer.pastes)
        self.assertTrue(composer.images)
        composer.caret = 0
        return composer, image

    def test_real_attachment_operator_put_and_history_matrix(self):
        for quote in ('"', "'", '`'):
            for descriptor in 'ia':
                for operator in 'cdy':
                    for put in 'pP':
                        with self.subTest(quote=quote, descriptor=descriptor, operator=operator, put=put):
                            composer, image = self.attached(quote)
                            original = composer._state()
                            undo = len(composer._undo)
                            inner = original[0][1:-1]
                            selected = inner if descriptor == 'i' else original[0]
                            send_keys(composer, operator + descriptor + quote)
                            register = composer._register
                            self.assertEqual(register.text, selected)
                            self.assertEqual(register.pastes, original[2])
                            self.assertEqual(register.images, original[3])
                            self.assertFalse(register.linewise)
                            self.assertEqual(composer.normal, operator != 'c')
                            self.assertFalse(composer.pending)
                            self.assert_atom_caret(composer)
                            if operator == 'y':
                                self.assertEqual(composer.text, original[0])
                                self.assertEqual(len(composer._undo), undo)
                            else:
                                self.assertEqual(composer.text, quote + quote if descriptor == 'i' else '')
                                self.assertEqual(composer.pastes, {})
                                self.assertEqual(composer.images, {})
                                if operator == 'c':
                                    send_keys(composer, 'Z')
                                    composer.handle(ESC)
                                final = composer._state()
                                self.assertEqual(len(composer._undo), undo + 1)
                                send_keys(composer, 'u')
                                self.assertEqual(composer._state(), original)
                                composer.handle(Key(CHAR, 'r', ctrl=True))
                                self.assertEqual(composer._state(), final)
                                self.assert_atom_caret(composer)
                            destination = make_vim_composer('LR', caret=0)
                            destination._register = register
                            before_put = destination._state()
                            history = len(destination._undo)
                            send_keys(destination, put)
                            at = 1 if put == 'p' else 0
                            self.assertEqual(destination.text, 'LR'[:at] + selected + 'LR'[at:])
                            self.assertEqual(destination.pastes, register.pastes)
                            self.assertEqual(destination.images, register.images)
                            self.assertTrue(all(value[1] is image for value in destination.images.values()))
                            self.assertEqual(len(destination._undo), history + 1)
                            self.assert_atom_caret(destination)
                            inserted = destination._state()
                            send_keys(destination, 'u')
                            self.assertEqual(destination._state(), before_put)
                            destination.handle(Key(CHAR, 'r', ctrl=True))
                            self.assertEqual(destination._state(), inserted)
                            self.assert_atom_caret(destination)
                            # A second copy must allocate a distinct token for the same image.
                            send_keys(destination, put)
                            self.assertEqual(len(destination.images), 2)
                            self.assertTrue(all(value[1] is image for value in destination.images.values()))

    def test_no_match_and_empty_preserve_complete_state(self):
        for quote in ('"', "'", '`'):
            for descriptor in 'ia':
                for operator in 'cdy':
                    with self.subTest(quote=quote, descriptor=descriptor, operator=operator):
                        composer, _ = self.attached(quote)
                        composer.replace(0, 1, '!')  # Keep real attachments, remove the opening quote.
                        composer.caret = 0
                        send_keys(composer, 'xu')  # Populate redo as well as undo.
                        composer._register = _Register('SEED', {}, {}, False)
                        before = (composer._state(), list(composer._undo), list(composer._redo), composer._register)
                        send_keys(composer, operator + descriptor + quote)
                        self.assertEqual((composer._state(), composer._undo, composer._redo, composer._register), before)
                        self.assertTrue(composer.normal)
                        self.assertFalse(composer.pending)
                        self.assert_atom_caret(composer)
            for operator in 'dy':
                for caret in (0, 1):
                    composer = make_vim_composer(quote + quote, caret=caret)
                    composer._register = _Register('SEED', {}, {}, False)
                    before = (list(composer._undo), list(composer._redo), composer._register)
                    send_keys(composer, operator + 'i' + quote)
                    self.assertEqual((composer._undo, composer._redo, composer._register), before)
                    self.assertEqual(composer.caret, 1 if operator == 'y' else caret)

    def test_escape_like_grapheme_is_content_not_syntax(self):
        for quote in ('"', "'", '`'):
            for operator in 'cdy':
                composer = make_vim_composer(quote + '\\\u0301' + quote + 'x' + quote, caret=0)
                send_keys(composer, operator + 'i' + quote)
                self.assertEqual(composer._register.text, '\\\u0301')
                self.assert_atom_caret(composer)

    def app_fixture(self, busy=False):
        app, client = make_app()
        app.composer.set_vim(True)
        type_text(app, 'x "abc" z')
        app._on_input(ESC)
        app.composer.caret = 4
        if busy:
            app.turn_pending = True
        return app, client

    def test_busy_armed_cancellation_and_exit(self):
        # Esc over a half-typed command only drops it, and so does Ctrl+C, unless the Ctrl+C is the second press of
        # an armed exit: that one exits as it does over no command.
        ctrl_c = Key(CHAR, 'c', ctrl=True)
        for busy in (False, True):
            for prefix in ('3', 'd', 'di', 'ya', '2d3i', '2f'):
                for armed in (False, True):
                    for event in (ESC, ctrl_c):
                        with self.subTest(busy=busy, prefix=prefix, armed=armed, event=event):
                            app, client = self.app_fixture(busy)
                            if armed:
                                app.exit_armed_at = app.clock()
                                app.exit_armed_by_interrupt = True
                            app.escape_armed = ('clear', app.clock())
                            type_text(app, prefix)
                            self.assertTrue(app.composer.pending)
                            before = (app.composer._state(), app.turn_pending, app.exit_armed_at,
                                      app.exit_armed_by_interrupt)
                            app._on_input(event)
                            self.assertFalse(app.composer.pending)
                            self.assertEqual(client.calls, [])
                            if event is ctrl_c and armed:
                                self.assertEqual(app.exit_code, 0)
                                continue
                            self.assertEqual((app.composer._state(), app.turn_pending, app.exit_armed_at,
                                              app.exit_armed_by_interrupt), before)
                            self.assertIsNone(app.exit_code)
                            if event is ESC:
                                self.assertIsNone(app.escape_armed)

    def test_second_ctrl_c_exits_over_a_pending_command_on_an_empty_composer(self):
        for prefix in ('d', '2d', 'di', 'g', 'r', '3', 'f'):
            with self.subTest(prefix=prefix):
                app, client = make_app()
                app.composer.set_vim(True)
                app._on_input(ESC)
                self.assertTrue(app.composer.normal)
                app._on_input(Key(CHAR, 'c', ctrl=True))  # the first press arms the exit
                self.assertIsNotNone(app.exit_armed_at)
                self.assertIsNone(app.exit_code)
                type_text(app, prefix)
                self.assertTrue(app.composer.pending)
                app._on_input(Key(CHAR, 'c', ctrl=True))
                self.assertEqual(app.exit_code, 0)
                self.assertEqual(client.calls, [])

    def test_esc_over_a_pending_object_or_target_holds_a_waiting_continue(self):
        for prefix in ('di', 'ca', '2f'):
            with self.subTest(prefix=prefix):
                app, client = self.app_fixture()
                app.auto_continue = (app.sid, app.clock() + 60.0)
                type_text(app, prefix)
                self.assertTrue(app.composer.pending)
                app._on_input(ESC)
                self.assertFalse(app.composer.pending)
                self.assertIsNone(app.auto_continue)
                self.assertEqual(app.composer.text, 'x "abc" z')
                self.assertEqual(client.calls, [])

    def test_object_non_global_chords_cancel_without_stale_edit(self):
        # Ctrl+T and Shift+Tab stay global shortcuts over a pending object, as over a pending `d`
        # (`test_other_pending_commands_keep_global_shortcuts`); a chord no global takes cancels it.
        for prefix in ('di', 'ca', 'yi'):
            for event in (Key(CHAR, 't', ctrl=True, alt=True), Key(TAB, shift=True, ctrl=True)):
                with self.subTest(prefix=prefix, event=event):
                    app, client = self.app_fixture()
                    before = app.composer._state()
                    type_text(app, prefix)
                    app._on_input(event)
                    self.assertEqual(app.composer._state(), before)
                    self.assertFalse(app.composer.pending)
                    self.assertEqual(client.calls, [])
                    app._on_input(Key(CHAR, '"'))
                    self.assertEqual(app.composer._state(), before)
                    self.assertEqual(client.calls, [])

    def test_legacy_alt_cancels_a_pending_object_then_acts_as_a_fresh_key(self):
        for char, caret in (('w', 6), ('"', 1), ("'", 1)):
            with self.subTest(char=char):
                composer = make_vim_composer('hello "world"', caret=1)
                send_keys(composer, 'di')
                self.assertTrue(composer.pending)
                composer.handle(Key(CHAR, char, alt=True))
                self.assertFalse(composer.pending)
                self.assertEqual((composer.text, composer.caret), ('hello "world"', caret))

    def test_decoded_quote_and_shared_undo_routes(self):
        for wire in (b'"', b'\x1b[34;2u', b'\x1b[27;2;34~', b'\x1b[34;3u'):
            app, client = self.app_fixture()
            type_text(app, 'di')
            for event in KeyDecoder().feed(wire):
                app._on_input(event)
            self.assertEqual(app.composer.text, 'x "abc" z' if wire == b'\x1b[34;3u' else 'x "" z')
            self.assertFalse(app.composer.pending)
            self.assertEqual(client.calls, [])
        for event, expected in ((Key(CHAR, '_', ctrl=True), ''), (Key(CHAR, 'r', ctrl=True), 'x "" z')):
            app, client = self.app_fixture()
            type_text(app, 'di"udi')
            app._on_input(event)
            self.assertEqual(app.composer.text, expected)
            self.assertFalse(app.composer.pending)
            self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
