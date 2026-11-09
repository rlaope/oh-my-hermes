"""Vim bracket text objects in the TUI composer: `i` and `a` with `()`, `[]`, `{}` under
`c`, `d`, and `y`.
"""

from __future__ import annotations

import unittest

from test_tui_modes import make_app, type_text
from omh.tui.composer import Composer, VIM_INSERT, _Register
from omh.tui.keys import CHAR, ENTER, ESCAPE, TAB, Key, KeyDecoder, Paste

ESC = Key(ESCAPE)


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


class VimBracketObjectsTests(unittest.TestCase):
    def test_bracket_operator_alias_matrix(self) -> None:
        """AB01: all 6 literal targets x i/a x c/d/y; closing aliases identical, no target insertion."""
        pairs = [("(", ")"), ("[", "]"), ("{", "}")]
        for open_ch, close_ch in pairs:
            for target in (open_ch, close_ch):
                # y inner
                c = make_vim_composer(f"x {open_ch}abc{close_ch} z", caret=4)
                send_keys(c, f"yi{target}")
                self.assertEqual(c.text, f"x {open_ch}abc{close_ch} z")
                self.assertEqual(c.caret, 3)
                self.assertEqual(c._register.text, "abc")
                self.assertFalse(c._register.linewise)
                self.assertTrue(c.normal)
                self.assertFalse(c.pending)

                # d inner
                c = make_vim_composer(f"x {open_ch}abc{close_ch} z", caret=4)
                send_keys(c, f"di{target}")
                self.assertEqual(c.text, f"x {open_ch}{close_ch} z")
                self.assertEqual(c.caret, 3)
                self.assertEqual(c._register.text, "abc")
                self.assertTrue(c.normal)
                self.assertFalse(c.pending)

                # c inner
                c = make_vim_composer(f"x {open_ch}abc{close_ch} z", caret=4)
                send_keys(c, f"ci{target}")
                self.assertEqual(c.text, f"x {open_ch}{close_ch} z")
                self.assertEqual(c.caret, 3)
                self.assertEqual(c._register.text, "abc")
                self.assertFalse(c.normal)
                self.assertEqual(c.vim_label, VIM_INSERT)
                self.assertFalse(c.pending)

                # y around
                c = make_vim_composer(f"x {open_ch}abc{close_ch} z", caret=4)
                send_keys(c, f"ya{target}")
                self.assertEqual(c.text, f"x {open_ch}abc{close_ch} z")
                self.assertEqual(c.caret, 2)
                self.assertEqual(c._register.text, f"{open_ch}abc{close_ch}")
                self.assertTrue(c.normal)

                # d around
                c = make_vim_composer(f"x {open_ch}abc{close_ch} z", caret=4)
                send_keys(c, f"da{target}")
                self.assertEqual(c.text, "x  z")
                self.assertEqual(c.caret, 2)
                self.assertEqual(c._register.text, f"{open_ch}abc{close_ch}")
                self.assertTrue(c.normal)

                # c around
                c = make_vim_composer(f"x {open_ch}abc{close_ch} z", caret=4)
                send_keys(c, f"ca{target}")
                self.assertEqual(c.text, "x  z")
                self.assertEqual(c.caret, 2)
                self.assertEqual(c._register.text, f"{open_ch}abc{close_ch}")
                self.assertFalse(c.normal)
                self.assertEqual(c.vim_label, VIM_INSERT)

    def test_bracket_scope_preserves_word_modes(self) -> None:
        """AB02: iw/aw, quote objects, off/masked/INSERT unchanged; unsupported targets cancel without edits."""
        # iw
        c = make_vim_composer("hello world", caret=1)
        send_keys(c, "diw")
        self.assertEqual(c.text, " world")

        # quote
        c = make_vim_composer('x "abc" z', caret=4)
        send_keys(c, 'di"')
        self.assertEqual(c.text, 'x "" z')

        # unsupported targets: b, B, <, >, x cancel pending without edits
        for bad in ("b", "B", "<", ">", "x"):
            c = make_vim_composer("x (abc) z", caret=4)
            send_keys(c, f"di{bad}")
            self.assertEqual(c.text, "x (abc) z")
            self.assertFalse(c.pending)
            self.assertTrue(c.normal)

        # digits after i/a cancel pending command without edit
        for digit in ("1", "2", "9"):
            c = make_vim_composer("x (abc) z", caret=4)
            send_keys(c, f"di{digit}")
            self.assertEqual(c.text, "x (abc) z")
            self.assertFalse(c.pending)
            self.assertTrue(c.normal)

        # masked composer unchanged
        c_masked = Composer(vim=True, masked=True)
        c_masked.replace(0, 0, "secret (bracket)")
        c_masked.caret = 8
        send_keys(c_masked, "di(")
        self.assertEqual(c_masked.text, "secret (di(bracket)")

        # vim off
        c_off = Composer(vim=False)
        c_off.replace(0, 0, "x (abc) z")
        c_off.caret = 4
        send_keys(c_off, "di(")
        self.assertEqual(c_off.text, "x (adi(bc) z")

        # INSERT mode
        c_ins = Composer(vim=True)
        c_ins.replace(0, 0, "x (abc) z")
        c_ins.caret = 4
        send_keys(c_ins, "di(")
        self.assertEqual(c_ins.text, "x (adi(bc) z")

    def test_bracket_cursor_targeting(self) -> None:
        """AB03: before/on-open/inside/on-close/gap/after-last and across logical lines select exact candidate."""
        # before first opener (caret 0): selects aa
        c = make_vim_composer("xx (aa) (bb) zz", caret=0)
        send_keys(c, "di(")
        self.assertEqual(c.text, "xx () (bb) zz")

        # on open delimiter (caret 3): selects aa
        c = make_vim_composer("xx (aa) (bb) zz", caret=3)
        send_keys(c, "di(")
        self.assertEqual(c.text, "xx () (bb) zz")

        # inside (caret 4): selects aa
        c = make_vim_composer("xx (aa) (bb) zz", caret=4)
        send_keys(c, "di(")
        self.assertEqual(c.text, "xx () (bb) zz")

        # on close delimiter (caret 6): selects aa
        c = make_vim_composer("xx (aa) (bb) zz", caret=6)
        send_keys(c, "di(")
        self.assertEqual(c.text, "xx () (bb) zz")

        # gap before second (caret 7): selects bb
        c = make_vim_composer("xx (aa) (bb) zz", caret=7)
        send_keys(c, "di(")
        self.assertEqual(c.text, "xx (aa) () zz")

        # after last closer (caret 13): no next opener, no-op
        c = make_vim_composer("xx (aa) (bb) zz", caret=13)
        send_keys(c, "di(")
        self.assertEqual(c.text, "xx (aa) (bb) zz")

        # across logical lines: "xx\n(aa)" from row1 (caret 0) selects aa
        c = make_vim_composer("xx\n(aa)", caret=0)
        send_keys(c, "di(")
        self.assertEqual(c.text, "xx\n()")

    def test_bracket_nested_counts(self) -> None:
        """AB04: nearest pair then enclosing level; 2d3i( equals d6i(; cap9999, insufficient depth no-op."""
        # "((((((x))))))" (6 levels)
        c = make_vim_composer("((((((x))))))")
        c.caret = c.text.index("x")
        send_keys(c, "2d3i(")
        self.assertEqual(c.text, "()")
        self.assertEqual(c._register.text, "(((((x)))))")

        # identical to d6i(
        c2 = make_vim_composer("((((((x))))))")
        c2.caret = c2.text.index("x")
        send_keys(c2, "d6i(")
        self.assertEqual(c2.text, "()")
        self.assertEqual(c2._register.text, "(((((x)))))")

        # around count selects enclosing ancestor
        c_around = make_vim_composer("((((((x))))))")
        c_around.caret = c_around.text.index("x")
        send_keys(c_around, "d2a(")
        self.assertEqual(c_around.text, "(((())))")
        self.assertEqual(c_around._register.text, "((x))")

        # count 7 exceeds depth (6 levels) -> no-op
        c3 = make_vim_composer("((((((x))))))")
        c3.caret = c3.text.index("x")
        send_keys(c3, "d7i(")
        self.assertEqual(c3.text, "((((((x))))))")

        # Runnable product regression: 9999 and 10000 depth with cap 9999 without recursion
        for depth in (9999, 10000):
            c_deep = make_vim_composer("(" * depth + "x" + ")" * depth, caret=depth)
            send_keys(c_deep, "999999di(")
            expected = "()" if depth == 9999 else "(())"
            self.assertEqual(c_deep.text, expected)
            self.assertEqual(c_deep._register.text, "(" * 9998 + "x" + ")" * 9998)

    def test_bracket_lexical_family_policy(self) -> None:
        """AB05: same-family balance; other families/quotes/backslashes ordinary content."""
        # "([)]": parenthesis around is "([)" and square around is "[)]"
        c = make_vim_composer("([)]", caret=1)
        send_keys(c, "da(")
        self.assertEqual(c.text, "]")
        self.assertEqual(c._register.text, "([)")

        c = make_vim_composer("([)]", caret=1)
        send_keys(c, "da[")
        self.assertEqual(c.text, "(")
        self.assertEqual(c._register.text, "[)]")

        # "(a[b]c)": parenthesis inner is "a[b]c"
        c = make_vim_composer("(a[b]c)", caret=3)
        send_keys(c, "di(")
        self.assertEqual(c.text, "()")
        self.assertEqual(c._register.text, "a[b]c")

        # "(a\\)b)": closes at the first ')' -> inner is "a\\"
        c = make_vim_composer(r"(a\)b)", caret=1)
        send_keys(c, "di(")
        self.assertEqual(c.text, "()b)")
        self.assertEqual(c._register.text, "a\\")

    def test_bracket_multiline_newlines(self) -> None:
        """AB06: literal inner/around newlines, indentation and cursor clamp; characterwise."""
        text = "call(\n  one,\n  two\n)"
        c = make_vim_composer(text, caret=text.index("one"))
        send_keys(c, "yi(")
        self.assertEqual(c.text, text)
        self.assertEqual(c._register.text, "\n  one,\n  two\n")
        self.assertFalse(c._register.linewise)
        self.assertEqual(c.caret, 4)

        # d inner leaves call()
        c = make_vim_composer(text, caret=text.index("one"))
        send_keys(c, "di(")
        self.assertEqual(c.text, "call()")
        self.assertEqual(c.caret, 5)

        # c inner leaves call() and enters INSERT at 5
        c = make_vim_composer(text, caret=text.index("one"))
        send_keys(c, "ci(")
        self.assertEqual(c.text, "call()")
        self.assertEqual(c.caret, 5)
        self.assertFalse(c.normal)
        self.assertEqual(c.vim_label, VIM_INSERT)
        send_keys(c, "X")
        self.assertEqual(c.text, "call(X)")

        # a around
        c = make_vim_composer(text, caret=text.index("one"))
        send_keys(c, "da(")
        self.assertEqual(c.text, "call")
        self.assertEqual(c.caret, 3)

    def test_bracket_register_cursor_undo(self) -> None:
        """AB07: c/d/y register/type/caret/mode, p/P metadata and grouped undo/redo."""
        c = make_vim_composer("pre (middle) post", caret=6)
        send_keys(c, "di(")
        self.assertEqual(c.text, "pre () post")
        send_keys(c, "u")
        self.assertEqual(c.text, "pre (middle) post")
        c.handle(Key(CHAR, "r", ctrl=True))  # Ctrl+R redo
        self.assertEqual(c.text, "pre () post")

        # c grouped undo with typed insertion
        c = make_vim_composer("pre (middle) post", caret=6)
        send_keys(c, "ci(")
        send_keys(c, "new")
        self.assertEqual(c.text, "pre (new) post")
        c.handle(ESC)
        send_keys(c, "u")
        self.assertEqual(c.text, "pre (middle) post")

    def test_bracket_empty_policy(self) -> None:
        """AB08: empty d no change, y moves to interior without replacing register, c enters INSERT at interior."""
        # d inner on empty: leaves text, caret, and register intact
        c = make_vim_composer("x()y", caret=0)
        c._register = _Register("preserved", {}, {}, False)
        send_keys(c, "di(")
        self.assertEqual(c.text, "x()y")
        self.assertEqual(c.caret, 0)
        self.assertEqual(c._register.text, "preserved")

        # y inner on empty: leaves register intact, moves caret to interior
        c = make_vim_composer("x()y", caret=0)
        c._register = _Register("preserved", {}, {}, False)
        send_keys(c, "yi(")
        self.assertEqual(c.text, "x()y")
        self.assertEqual(c.caret, 2)
        self.assertEqual(c._register.text, "preserved")

        # c inner on empty: enters INSERT at interior (caret 2) without deleting
        c = make_vim_composer("x()y", caret=0)
        c._register = _Register("preserved", {}, {}, False)
        send_keys(c, "ci(")
        self.assertEqual(c.text, "x()y")
        self.assertEqual(c.caret, 2)
        self.assertFalse(c.normal)
        self.assertEqual(c.vim_label, VIM_INSERT)
        self.assertEqual(c._register.text, "preserved")
        send_keys(c, "X")
        self.assertEqual(c.text, "x(X)y")

        # a around on empty deletes delimiters
        c = make_vim_composer("x()y", caret=0)
        send_keys(c, "da(")
        self.assertEqual(c.text, "xy")
        self.assertEqual(c.caret, 1)

    def test_bracket_missing_unbalanced_noop(self) -> None:
        """AB09: missing/unbalanced/insufficient depth preserves text/caret/mode/register/undo, clears pending."""
        # "(bad (ok)"
        # caret 2 (inside unclosed outer): returns None, no forward child substitution
        c = make_vim_composer("(bad (ok)", caret=2)
        c._register = _Register("keep", {}, {}, False)
        send_keys(c, "di(")
        self.assertEqual(c.text, "(bad (ok)")
        self.assertEqual(c.caret, 2)
        self.assertEqual(c._register.text, "keep")
        self.assertFalse(c.pending)

        # "xx (bad (ok)" caret 0: first forward opener is unmatched outer -> returns None, NOT (ok)!
        c_fwd = make_vim_composer("xx (bad (ok)", caret=0)
        c_fwd._register = _Register("keep", {}, {}, False)
        send_keys(c_fwd, "di(")
        self.assertEqual(c_fwd.text, "xx (bad (ok)")
        self.assertEqual(c_fwd.caret, 0)
        self.assertEqual(c_fwd._register.text, "keep")
        self.assertFalse(c_fwd.pending)

        # caret 6 count 1: selects inner (ok)
        c = make_vim_composer("(bad (ok)", caret=6)
        send_keys(c, "di(")
        self.assertEqual(c.text, "(bad ()")
        self.assertEqual(c._register.text, "ok")

        # caret 6 count 2: outer ancestor unbalanced -> no-op
        c = make_vim_composer("(bad (ok)", caret=6)
        c._register = _Register("keep", {}, {}, False)
        send_keys(c, "d2i(")
        self.assertEqual(c.text, "(bad (ok)")
        self.assertEqual(c.caret, 6)
        self.assertEqual(c._register.text, "keep")
        self.assertFalse(c.pending)

    def test_bracket_atomic_content(self) -> None:
        """AB10: Unicode graphemes and atom integrity intact through select/edit/register/undo."""
        # e + combining acute accent (\u0301) NFC-normalized at text boundary into \u00e9, intact with ZWJ sequence
        import unicodedata
        expected_graphemes = unicodedata.normalize("NFC", "e\u0301 \U0001F468\u200D\U0001F469\u200D\U0001F467")
        text = f"({expected_graphemes})"
        c = make_vim_composer(text, caret=2)
        send_keys(c, "di(")
        self.assertEqual(c.text, "()")
        self.assertEqual(c._register.text, expected_graphemes)
        send_keys(c, "u")
        self.assertEqual(c.text, text)

        # Attachment journey: Paste + insert_image with brackets in payload
        for desc in ("i", "a"):
            for op in ("c", "d", "y"):
                for put in ("p", "P"):
                    with self.subTest(desc=desc, op=op, put=put):
                        comp = make_vim_composer("pre (item) post", caret=5)
                        multiline_paste = "multiline (paste [with] {brackets})\nline2\nline3\nline4\nline5\nline6"
                        comp.handle(Paste(multiline_paste))
                        img_payload = object()
                        self.assertTrue(comp.insert_image("[Image (img) #1]", img_payload))
                        self.assertTrue(comp.pastes)
                        self.assertTrue(comp.images)

                        orig_state = comp._state()
                        undo_len = len(comp._undo)
                        send_keys(comp, f"{op}{desc}(")
                        reg = comp._register
                        self.assertIn("item", reg.text)
                        self.assertEqual(reg.pastes, orig_state[2])
                        self.assertEqual(reg.images, orig_state[3])
                        self.assertIn(comp.caret, comp._atoms()[1])

                        if op == "y":
                            self.assertEqual(comp.text, orig_state[0])
                            self.assertEqual(len(comp._undo), undo_len)
                        else:
                            self.assertEqual(comp.pastes, {})
                            self.assertEqual(comp.images, {})
                            if op == "c":
                                send_keys(comp, "Z")
                                comp.handle(ESC)
                            final_state = comp._state()
                            send_keys(comp, "u")
                            self.assertEqual(comp.text, orig_state[0])
                            self.assertEqual(comp.pastes, orig_state[2])
                            self.assertEqual(comp.images, orig_state[3])
                            comp.handle(Key(CHAR, "r", ctrl=True))
                            self.assertEqual(comp._state(), final_state)

                        # Destination put
                        dest = make_vim_composer("dest () end", caret=6)
                        dest._register = reg
                        before_put = dest._state()
                        send_keys(dest, put)
                        self.assertTrue(dest.pastes)
                        self.assertTrue(dest.images)
                        self.assertTrue(any(v[1] is img_payload for v in dest.images.values()))
                        self.assertIn(dest.caret, dest._atoms()[1])
                        after_put = dest._state()
                        send_keys(dest, "u")
                        self.assertEqual(dest._state(), before_put)
                        dest.handle(Key(CHAR, "r", ctrl=True))
                        self.assertEqual(dest._state(), after_put)

        # Seeded attachment no-match state preservation
        comp_nomatch = make_vim_composer("(item)", caret=1)
        comp_nomatch.handle(Paste("long paste payload\nline2\nline3\nline4\nline5\nline6"))
        self.assertTrue(comp_nomatch.insert_image("[Image #1]", object()))
        comp_nomatch.replace(0, 1, "!")  # remove open bracket
        before_state = comp_nomatch._state()
        send_keys(comp_nomatch, "di(")
        self.assertEqual(comp_nomatch._state(), before_state)

    def test_app_bracket_target_cancel(self) -> None:
        """AB11: cancellation of pending bracket commands via Esc / Enter / unmapped keys and App integration."""
        c = make_vim_composer("x (abc) z", caret=4)
        send_keys(c, "di")
        self.assertTrue(c.pending)
        c.handle(ESC)
        self.assertFalse(c.pending)
        self.assertTrue(c.normal)
        self.assertEqual(c.text, "x (abc) z")

        # Enter while pending cancels
        send_keys(c, "di")
        self.assertTrue(c.pending)
        c.handle(Key(ENTER))
        self.assertFalse(c.pending)
        self.assertTrue(c.normal)
        self.assertEqual(c.text, "x (abc) z")

        # Real App fixture tests:
        app, client = make_app()
        app.composer.set_vim(True)
        type_text(app, "x (abc) z")
        app._on_input(ESC)
        app.composer.caret = 4

        # KeyDecoder feeding byte sequences: normal shifted edits vs Alt cancellation
        dec = KeyDecoder()
        # Normal shifted bracket completes target:
        type_text(app, "di")
        self.assertTrue(app.composer.pending)
        for ev in dec.feed(b"("):
            app._on_input(ev)
        self.assertEqual(app.composer.text, "x () z")
        self.assertFalse(app.composer.pending)

        # Shifted bracket via kitty modifyOtherKeys completes target:
        type_text(app, "u")  # restore "x (abc) z"
        type_text(app, "di")
        self.assertTrue(app.composer.pending)
        for ev in dec.feed(b"\x1b[40;2u"):
            app._on_input(ev)
        self.assertEqual(app.composer.text, "x () z")

        # Shifted bracket via xterm modifyOtherKeys completes target:
        type_text(app, "u")
        type_text(app, "di")
        self.assertTrue(app.composer.pending)
        for ev in dec.feed(b"\x1b[27;2;40~"):
            app._on_input(ev)
        self.assertEqual(app.composer.text, "x () z")

        # Alt bracket via kitty modifyOtherKeys cancels pending without edits:
        type_text(app, "u")
        type_text(app, "di")
        self.assertTrue(app.composer.pending)
        for ev in dec.feed(b"\x1b[40;3u"):
            app._on_input(ev)
        self.assertFalse(app.composer.pending)
        self.assertEqual(app.composer.text, "x (abc) z")
        # Eventual target cannot perform stale edit
        app._on_input(Key(CHAR, ")"))
        self.assertEqual(app.composer.text, "x (abc) z")

        # Alt bracket via xterm modifyOtherKeys cancels pending without edits:
        type_text(app, "di")
        self.assertTrue(app.composer.pending)
        for ev in dec.feed(b"\x1b[27;3;40~"):
            app._on_input(ev)
        self.assertFalse(app.composer.pending)
        self.assertEqual(app.composer.text, "x (abc) z")
        app._on_input(Key(CHAR, ")"))
        self.assertEqual(app.composer.text, "x (abc) z")

        # Ctrl+C un-armed cancels pending without exit
        type_text(app, "di")
        self.assertTrue(app.composer.pending)
        app._on_input(Key(CHAR, "c", ctrl=True))
        self.assertFalse(app.composer.pending)
        self.assertIsNone(app.exit_code)

        # Armed second Ctrl+C exits over pending command
        type_text(app, "di")
        self.assertTrue(app.composer.pending)
        app.exit_armed_at = app.clock()
        app.exit_armed_by_interrupt = True
        app._on_input(Key(CHAR, "c", ctrl=True))
        self.assertEqual(app.exit_code, 0)

        # Ctrl+T steps effort
        app2, _ = make_app()
        app2.composer.set_vim(True)
        type_text(app2, "x (abc) z")
        app2._on_input(ESC)
        type_text(app2, "di")
        before_effort = app2.effort_asked or app2.effort
        app2._on_input(Key(CHAR, "t", ctrl=True))
        after_effort = app2.effort_asked or app2.effort
        self.assertNotEqual(before_effort, after_effort)

        # Shift+Tab cycles mode: assert actual before/after state change or mode request
        before_state = (app2.plan_mode, app2.approvals_off, app2.mode_request_open)
        app2._on_input(Key(TAB, shift=True))
        after_state = (app2.plan_mode, app2.approvals_off, app2.mode_request_open)
        self.assertNotEqual(before_state, after_state)

    def test_app_bracket_submit_isolation(self) -> None:
        """AB12: Enter while pending cancels only; fresh Enter submits."""
        c = make_vim_composer("x (abc) z", caret=4)
        send_keys(c, "di")
        action = c.handle(Key(ENTER))
        self.assertFalse(c.pending)
        self.assertEqual(action.kind, "none")
        self.assertEqual(c.text, "x (abc) z")

        # Fresh Enter after cancellation submits
        action = c.handle(Key(ENTER))
        self.assertEqual(action.kind, "submit")

        # App level submit test
        app, client = make_app()
        app.composer.set_vim(True)
        type_text(app, "x (abc) z")
        app._on_input(ESC)
        app.composer.caret = 4
        type_text(app, "di")
        # Enter cancels
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [])
        # Fresh Enter submits
        app._on_input(Key(ENTER))
        self.assertEqual(len(client.calls), 1)


if __name__ == "__main__":
    unittest.main()
