"""Vim mode in the composer: Hermes' `display.vim_mode`, read from the active profile's config (#2434).

Off (the setting false, absent or not a true), every key does what it did
before. On, the main composer starts in INSERT and Esc goes to NORMAL, where
a character is a command and never text (`omh.tui.composer`, Vim mode). The
app gives Esc to the composer while it is in INSERT, so that press never
arms the clear or the rewind and never interrupts a turn; from NORMAL, Esc
does what it does without vim mode. Questions, pickers, the agent list and
the composers that stand in for the draft (a question's answer, a masked
secret, a tell row) keep their own keys.

Every NORMAL command the docs list has a test here, with a count where it
takes one, over plain text, several lines, a paste chip, an image token and
clusters of more than one code point.
"""

from __future__ import annotations

import string
import unittest

from _tui_lines import line_text, without_badge
from test_tui_agent_view import agent_app
from test_tui_cc_look import working_rows
from test_tui_modes import SID, make_app, type_text
from test_tui_subagents import FIRST
from test_tui_rewind import Clock
from omh.tui.app import DOUBLE_ESCAPE_SECONDS, App, PathItem, vim_mode
from omh.tui.composer import CANCEL, NONE, SUBMIT, VIM_INSERT, VIM_NORMAL, Composer
from omh.tui.gateway import ServerRequest
from omh.tui.keys import BACKSPACE, CHAR, DELETE, DOWN, ENTER, ESCAPE, LEFT, TAB, UP, Key, KeyDecoder, Paste
from omh.tui.modes import chip_column, editing_label, info_line, mode_label
from omh.tui.frame import MODE_ACCEPT, MODE_NORMAL
from omh.tui.style import Span
from omh.tui.theme import DEFAULT_THEME
from omh.tui.width import line_width

FAMILY = "\U0001F468‍\U0001F469‍\U0001F467‍\U0001F466"
Q_ACUTE = "q́"
ESC = Key(ESCAPE)
CHIP_TEXT = "one\ntwo\nthree\nfour\nfive"
CHIP = "[Pasted text #1 +5 lines]"
CLARIFY = {"questions": [{"qid": "q0", "question": "Why?"}]}  # answered with text


def keys(composer: Composer, typed: str) -> None:
    for char in typed:
        composer.handle(Key(CHAR, char))


def normal(text: str, caret: int | None = None) -> Composer:
    """A vim composer holding `text`, in NORMAL, the caret at `caret` (else where Esc put it)."""
    composer = Composer(vim=True)
    composer.replace(0, 0, text)
    composer.handle(ESC)
    if caret is not None:
        composer.caret = caret
    return composer


def state(composer: Composer) -> tuple[str, int, str]:
    return composer.text, composer.caret, composer.vim_label


class OffTests(unittest.TestCase):
    def test_without_vim_mode_esc_cancels_and_a_letter_after_it_is_text(self) -> None:
        # The issue's probe: type hello, Esc, h.
        composer = Composer()
        keys(composer, "hello")
        self.assertEqual(composer.handle(ESC).kind, CANCEL)
        keys(composer, "h")
        self.assertEqual((composer.text, composer.caret, composer.vim_label), ("helloh", 6, ""))

    def test_a_legacy_alt_chord_still_types_its_key_and_alt_enter_adds_a_line(self) -> None:
        composer = Composer()
        composer.handle(Key(CHAR, "h", alt=True))
        composer.handle(Key(ENTER, alt=True))
        self.assertEqual(composer.text, "h\n")

    def test_turning_it_off_leaves_insert_and_drops_a_half_typed_command(self) -> None:
        composer = normal("abc")
        keys(composer, "d")
        composer.set_vim(False)
        self.assertEqual((composer.vim, composer.normal, composer.pending), (False, False, False))
        keys(composer, "x")
        self.assertEqual(composer.text, "abxc")


class InsertAndEscTests(unittest.TestCase):
    def test_it_starts_in_insert_where_keys_type_as_without_it(self) -> None:
        composer = Composer(vim=True)
        self.assertEqual(composer.vim_label, VIM_INSERT)
        keys(composer, "hjkl")
        composer.handle(Key(BACKSPACE))
        self.assertEqual(state(composer), ("hjk", 3, VIM_INSERT))

    def test_esc_goes_to_normal_reports_nothing_and_steps_back_onto_the_last_character(self) -> None:
        composer = Composer(vim=True)
        keys(composer, "hello")
        self.assertEqual(composer.handle(ESC).kind, NONE)
        self.assertEqual(state(composer), ("hello", 4, VIM_NORMAL))

    def test_esc_at_the_start_of_a_line_keeps_the_caret(self) -> None:
        composer = Composer(vim=True)
        keys(composer, "ab")
        composer.handle(Key(ENTER, shift=True))
        composer.handle(ESC)
        self.assertEqual(state(composer), ("ab\n", 3, VIM_NORMAL))

    def test_esc_in_normal_cancels_as_without_vim_mode(self) -> None:
        composer = normal("abc")
        self.assertEqual(composer.handle(ESC).kind, CANCEL)
        self.assertEqual(state(composer), ("abc", 2, VIM_NORMAL))

    def test_esc_in_normal_drops_a_half_typed_command_and_nothing_else(self) -> None:
        composer = normal("abc def", 0)
        keys(composer, "2d")
        self.assertTrue(composer.pending)
        self.assertEqual(composer.handle(ESC).kind, NONE)
        self.assertFalse(composer.pending)
        keys(composer, "w")
        self.assertEqual(state(composer), ("abc def", 4, VIM_NORMAL))  # a motion, not d2w

    def test_masked_input_is_never_modal(self) -> None:
        composer = Composer(masked=True, vim=True)
        self.assertEqual(composer.vim_label, "")
        keys(composer, "pw")
        self.assertEqual(composer.handle(ESC).kind, CANCEL)
        keys(composer, "x")
        self.assertEqual(composer.text, "pwx")


class NormalNeverTypesTests(unittest.TestCase):
    def test_no_character_that_is_no_command_changes_the_text_or_moves_the_caret(self) -> None:
        commands = set("hl0^$wbejkgGiaIAoOxXdDcCsSryupP")
        others = [char for char in string.printable if char not in commands and not char.isspace()]
        others += [" ", "한", "é", FAMILY]
        for char in others:
            with self.subTest(char=char):
                composer = normal("one two", 2)
                self.assertEqual(composer.handle(Key(CHAR, char)).kind, NONE)
                self.assertEqual(state(composer), ("one two", 2, VIM_NORMAL))

    def test_digits_are_a_count_and_never_text(self) -> None:
        composer = normal("abc", 0)
        keys(composer, "123456789")
        self.assertEqual(state(composer), ("abc", 0, VIM_NORMAL))
        self.assertTrue(composer.pending)

    def test_a_key_that_arrives_while_a_command_is_half_typed_drops_it_and_does_nothing_else(self) -> None:
        for key in (Key(ENTER), Key(LEFT), Key(CHAR, "c", ctrl=True), Key(UP)):
            with self.subTest(key=key):
                composer = normal("abc", 1)
                keys(composer, "d")
                self.assertEqual(composer.handle(key).kind, NONE)  # Enter sends nothing
                self.assertEqual((*state(composer), composer.pending), ("abc", 1, VIM_NORMAL, False))

    def test_a_paste_inserts_at_the_caret_and_stays_in_normal(self) -> None:
        composer = normal("ad", 1)
        composer.handle(Paste("bc"))
        self.assertEqual(state(composer), ("abcd", 3, VIM_NORMAL))


class MotionTests(unittest.TestCase):
    def test_h_and_l_stay_on_the_line_and_take_a_count(self) -> None:
        composer = normal("one\ntwo", 5)
        keys(composer, "h")
        self.assertEqual(composer.caret, 4)
        keys(composer, "h")
        self.assertEqual(composer.caret, 4)  # the line's first character
        keys(composer, "9l")
        self.assertEqual(composer.caret, 6)  # its last, never after it
        keys(composer, "2h")
        self.assertEqual(composer.caret, 4)

    def test_backspace_is_h_and_delete_is_x(self) -> None:
        composer = normal("abc", 2)
        composer.handle(Key(BACKSPACE))
        self.assertEqual(state(composer), ("abc", 1, VIM_NORMAL))
        composer.handle(Key(DELETE))
        self.assertEqual(state(composer), ("ac", 1, VIM_NORMAL))

    def test_zero_caret_and_dollar(self) -> None:
        composer = normal("x\n   indented line", 10)
        keys(composer, "0")
        self.assertEqual(composer.caret, 2)
        keys(composer, "^")
        self.assertEqual(composer.caret, 5)
        keys(composer, "$")
        self.assertEqual(composer.caret, 17)  # on the last character

    def test_w_b_e_move_by_words_between_blanks_with_a_count(self) -> None:
        text = "one two-2 three\nfour"
        composer = normal(text, 0)
        keys(composer, "w")
        self.assertEqual(composer.caret, 4)
        keys(composer, "2w")
        self.assertEqual(composer.caret, 16)  # across the line's end
        keys(composer, "b")
        self.assertEqual(composer.caret, 10)
        keys(composer, "3b")
        self.assertEqual(composer.caret, 0)
        keys(composer, "e")
        self.assertEqual(composer.caret, 2)
        keys(composer, "e")
        self.assertEqual(composer.caret, 8)
        keys(composer, "9w")
        self.assertEqual(composer.caret, len(text) - 1)  # the end of the text, on its last character

    def test_j_and_k_move_between_lines_and_walk_history_at_the_edges(self) -> None:
        composer = Composer(vim=True, history=["older"])
        keys(composer, "ab")
        composer.handle(Key(ENTER, shift=True))
        keys(composer, "cd")
        composer.handle(ESC)
        self.assertEqual(composer.caret, 4)
        keys(composer, "k")
        self.assertEqual(composer.caret, 1)
        keys(composer, "j")
        self.assertEqual(composer.caret, 4)
        keys(composer, "j")  # the last line: history forward, and there is none to go forward to
        self.assertEqual(composer.text, "ab\ncd")
        keys(composer, "3k")  # up a row, then into the history: one entry, whatever the count
        self.assertEqual(state(composer), ("older", 4, VIM_NORMAL))
        keys(composer, "j")
        self.assertEqual(composer.text, "ab\ncd")  # the draft comes back

    def test_gg_and_G_go_to_the_first_and_the_last_line_or_line_n(self) -> None:
        composer = normal("  one\ntwo\n three", 3)
        keys(composer, "G")
        self.assertEqual(composer.caret, 11)  # the last line's first character that is no blank
        keys(composer, "gg")
        self.assertEqual(composer.caret, 2)
        keys(composer, "2G")
        self.assertEqual(composer.caret, 6)
        keys(composer, "3gg")
        self.assertEqual(composer.caret, 11)
        keys(composer, "9G")
        self.assertEqual(composer.caret, 11)  # past the last line, the last

    def test_a_huge_count_is_capped_and_stops_at_the_edge(self) -> None:
        composer = normal("abc def", 0)
        keys(composer, "99999999999999999999l")
        self.assertEqual((composer.caret, composer.pending), (6, False))
        keys(composer, "99999999999999999999X")
        self.assertEqual(state(composer), ("f", 0, VIM_NORMAL))

    def test_a_count_thousands_of_digits_long_is_capped_as_it_is_typed(self) -> None:
        composer = normal("abc", 2)
        keys(composer, "9" * 5000 + "h")  # int() of a string this long refuses on Python 3.11+
        self.assertEqual((composer.caret, composer.pending), (0, False))

    def test_the_drawn_caret_is_on_the_character_in_normal(self) -> None:
        composer = Composer(vim=True)
        keys(composer, "abc")
        self.assertEqual(composer.render(40, 3)[1], (0, 2 + 3))  # after c in INSERT (the prompt is two cells)
        composer.handle(ESC)
        self.assertEqual(composer.render(40, 3)[1], (0, 2 + 2))  # on c in NORMAL

    def test_a_g_then_another_key_does_nothing(self) -> None:
        composer = normal("abc def", 4)
        keys(composer, "gx")
        self.assertEqual(state(composer), ("abc def", 4, VIM_NORMAL))


class InsertCommandTests(unittest.TestCase):
    def test_i_a_I_A(self) -> None:
        for command, caret, expected in (
            ("i", 1, "aXbc"), ("a", 1, "abXc"), ("I", 3, "  Xabc"), ("A", 1, "abcX"),
        ):
            with self.subTest(command=command):
                text = "  abc" if command == "I" else "abc"
                composer = normal(text, caret)
                keys(composer, command)
                self.assertEqual(composer.vim_label, VIM_INSERT)
                keys(composer, "X")
                self.assertEqual(composer.text, expected)

    def test_o_and_O_open_a_line_below_and_above(self) -> None:
        composer = normal("one\ntwo", 1)
        keys(composer, "oX")
        self.assertEqual(state(composer), ("one\nX\ntwo", 5, VIM_INSERT))
        composer = normal("one\ntwo", 5)
        keys(composer, "OX")
        self.assertEqual(state(composer), ("one\nX\ntwo", 5, VIM_INSERT))

    def test_every_change_on_an_empty_composer_goes_to_insert(self) -> None:
        for command in ("cw", "ce", "cb", "c$", "C", "s", "cc", "S"):
            with self.subTest(command=command):
                composer = normal("")
                keys(composer, command)
                self.assertEqual(state(composer), ("", 0, VIM_INSERT))

    def test_a_on_an_empty_composer_inserts_at_the_start(self) -> None:
        composer = normal("")
        keys(composer, "aX")
        self.assertEqual(composer.text, "X")


class EditTests(unittest.TestCase):
    def test_x_and_X_with_a_count_stay_on_the_line(self) -> None:
        composer = normal("abcdef\nz", 1)
        keys(composer, "x")
        self.assertEqual(state(composer), ("acdef\nz", 1, VIM_NORMAL))
        keys(composer, "9x")
        self.assertEqual(state(composer), ("a\nz", 0, VIM_NORMAL))
        composer = normal("abcdef", 4)
        keys(composer, "2X")
        self.assertEqual(state(composer), ("abef", 2, VIM_NORMAL))
        keys(composer, "X")
        self.assertEqual(state(composer), ("aef", 1, VIM_NORMAL))

    def test_dd_with_a_count_and_on_the_last_line(self) -> None:
        composer = normal("one\ntwo\n  three\nfour", 4)
        keys(composer, "dd")
        self.assertEqual(state(composer), ("one\n  three\nfour", 6, VIM_NORMAL))  # on its first character not blank
        keys(composer, "9dd")
        self.assertEqual(state(composer), ("one", 0, VIM_NORMAL))  # the newline before it goes with the last line
        keys(composer, "dd")
        self.assertEqual(state(composer), ("", 0, VIM_NORMAL))

    def test_D_and_C(self) -> None:
        composer = normal("one two\nx", 4)
        keys(composer, "D")
        self.assertEqual(state(composer), ("one \nx", 3, VIM_NORMAL))
        composer = normal("one two\nx", 4)
        keys(composer, "CY")
        self.assertEqual(state(composer), ("one Y\nx", 5, VIM_INSERT))

    def test_cc_S_s(self) -> None:
        for command in ("cc", "S"):
            with self.subTest(command=command):
                composer = normal("one\ntwo\nthree", 5)
                keys(composer, command + "X")
                self.assertEqual(state(composer), ("one\nX\nthree", 5, VIM_INSERT))
        composer = normal("one\ntwo\nthree", 0)
        keys(composer, "2ccX")
        self.assertEqual(composer.text, "X\nthree")
        composer = normal("abcd", 1)
        keys(composer, "2sX")
        self.assertEqual(state(composer), ("aXd", 2, VIM_INSERT))

    def test_r_replaces_characters_on_the_line(self) -> None:
        composer = normal("abcd", 1)
        keys(composer, "rX")
        self.assertEqual(state(composer), ("aXcd", 1, VIM_NORMAL))
        keys(composer, "2rY")
        self.assertEqual(state(composer), ("aYYd", 2, VIM_NORMAL))
        keys(composer, "9rZ")  # more than the line holds: nothing
        self.assertEqual(state(composer), ("aYYd", 2, VIM_NORMAL))
        composer.handle(Key(CHAR, "r"))
        self.assertEqual(composer.handle(Key(ENTER)).kind, NONE)  # r then Enter: nothing replaced, nothing sent
        self.assertEqual(state(composer), ("aYYd", 2, VIM_NORMAL))

    def test_an_operator_with_each_motion(self) -> None:
        for command, caret, expected, after in (
            ("dw", 4, "one three", 4), ("d2w", 0, "three", 0), ("2dw", 0, "three", 0),
            ("dw", 8, "one two \nnext", 7),  # stops at the end of the line
            ("db", 8, "one three\nnext", 4), ("de", 4, "one  three\nnext", 4),
            ("d$", 4, "one \nnext", 3), ("d0", 4, "two three\nnext", 0), ("d^", 6, "  two three\nnext", 2),
            ("dl", 0, "ne two three\nnext", 0), ("dh", 2, "oe two three\nnext", 1),
        ):
            with self.subTest(command=command, caret=caret):
                text = "  one two three\nnext" if command == "d^" else "one two three\nnext"
                if command in ("dw", "d2w", "2dw") and caret != 8:
                    text = "one two three"
                composer = normal(text, caret)
                keys(composer, command)
                self.assertEqual(state(composer), (expected, after, VIM_NORMAL))

    def test_cw_on_a_word_changes_to_its_end_and_on_blanks_to_the_next_word(self) -> None:
        for command, caret, expected in (
            ("cw", 4, "one X three"), ("cw", 5, "one tX three"), ("c2w", 0, "X three"),
            ("cw", 3, "oneXtwo three"), ("c$", 4, "one X"), ("ce", 0, "X two three"),
        ):
            with self.subTest(command=command, caret=caret):
                composer = normal("one two three", caret)
                keys(composer, command + "X")
                self.assertEqual((composer.text, composer.vim_label), (expected, VIM_INSERT))

    def test_an_operator_with_no_motion_it_knows_does_nothing(self) -> None:
        for command in ("dj", "dz", "dc", "yG", "dgg"):
            with self.subTest(command=command):
                composer = normal("one\ntwo", 1)
                keys(composer, command)
                self.assertEqual((*state(composer), composer.pending), ("one\ntwo", 1, VIM_NORMAL, False))


class YankPutTests(unittest.TestCase):
    def test_yy_then_p_and_P_put_whole_lines_below_and_above(self) -> None:
        composer = normal("one\ntwo", 1)
        keys(composer, "yyjp")
        self.assertEqual(state(composer), ("one\ntwo\none", 8, VIM_NORMAL))
        keys(composer, "ggP")
        self.assertEqual(state(composer), ("one\none\ntwo\none", 0, VIM_NORMAL))

    def test_yw_and_a_count_on_p(self) -> None:
        composer = normal("ab cd", 0)
        keys(composer, "yw")
        self.assertEqual(state(composer), ("ab cd", 0, VIM_NORMAL))  # a yank changes nothing
        keys(composer, "$2p")
        self.assertEqual(state(composer), ("ab cdab ab ", 10, VIM_NORMAL))  # on the last character put

    def test_a_deletion_is_what_p_puts(self) -> None:
        composer = normal("abc", 0)
        keys(composer, "xp")
        self.assertEqual(state(composer), ("bac", 1, VIM_NORMAL))
        composer = normal("one\ntwo", 0)
        keys(composer, "ddp")
        self.assertEqual(state(composer), ("two\none", 4, VIM_NORMAL))
        composer = normal("abc def", 4)
        keys(composer, "dwP")  # dw leaves the caret on the blank, and P puts before it
        self.assertEqual(state(composer), ("abcdef ", 5, VIM_NORMAL))

    def test_p_with_nothing_taken_does_nothing(self) -> None:
        composer = normal("abc", 1)
        keys(composer, "pP")
        self.assertEqual(state(composer), ("abc", 1, VIM_NORMAL))

    def test_the_register_outlives_a_submit(self) -> None:
        composer = normal("keep me", 0)
        keys(composer, "yy")
        self.assertEqual(composer.handle(Key(ENTER)).kind, SUBMIT)
        composer.handle(ESC)
        keys(composer, "P")
        self.assertEqual(composer.text, "keep me\n")


class RegisterChipTests(unittest.TestCase):
    def test_a_yanked_chip_put_after_the_draft_emptied_keeps_its_text_beside_a_new_chip(self) -> None:
        first, second = "A1\nA2\nA3\nA4\nA5", "B1\nB2\nB3\nB4\nB5"
        for empties in (Key(CHAR, "c", ctrl=True), Key(ENTER)):
            with self.subTest(empties=empties):
                composer = Composer(vim=True)
                composer.handle(Paste(first))
                composer.handle(ESC)
                keys(composer, "yy")
                composer.handle(empties)  # the labels count from 1 again
                composer.handle(Paste(second))  # the same shape: the same label as the yanked chip
                composer.handle(ESC)
                keys(composer, "p")
                self.assertEqual(sorted(composer.pastes.values()), [first, second])
                self.assertEqual(composer.handle(Key(ENTER)).text, f"{second}\n{first}")

    def test_a_chip_put_twice_into_its_own_draft_keeps_one_label(self) -> None:
        composer = Composer(vim=True)
        composer.handle(Paste(CHIP_TEXT))
        composer.handle(ESC)
        keys(composer, "yyp")
        self.assertEqual((composer.text, composer.pastes), (f"{CHIP}\n{CHIP}", {CHIP: CHIP_TEXT}))


class UndoTests(unittest.TestCase):
    def test_u_and_ctrl_r_undo_and_redo_with_a_count(self) -> None:
        composer = normal("one two three", 0)
        keys(composer, "dwdw")
        self.assertEqual(composer.text, "three")
        keys(composer, "2u")
        self.assertEqual(state(composer), ("one two three", 0, VIM_NORMAL))
        composer.handle(Key(CHAR, "r", ctrl=True))
        self.assertEqual(state(composer), ("two three", 0, VIM_NORMAL))
        composer.handle(Key(CHAR, "_", ctrl=True))  # the composer's own undo key works in NORMAL too
        self.assertEqual(composer.text, "one two three")

    def test_each_x_is_its_own_undo_step(self) -> None:
        composer = normal("abc", 0)
        keys(composer, "xx")
        keys(composer, "u")
        self.assertEqual(composer.text, "bc")

    def test_a_change_and_what_is_typed_after_it_are_one_step(self) -> None:
        composer = normal("one two", 4)
        keys(composer, "cwsix")
        composer.handle(ESC)
        self.assertEqual(composer.text, "one six")
        keys(composer, "u")
        self.assertEqual(state(composer), ("one two", 4, VIM_NORMAL))
        composer = normal("one", 0)
        keys(composer, "otwo")
        composer.handle(ESC)
        keys(composer, "u")
        self.assertEqual(composer.text, "one")

    def test_an_undo_lands_the_caret_on_a_character(self) -> None:
        composer = Composer(vim=True)
        keys(composer, "abc")
        composer.handle(ESC)
        keys(composer, "x")
        keys(composer, "u")
        self.assertEqual(state(composer), ("abc", 2, VIM_NORMAL))
        keys(composer, "u")  # back to empty: the typed run was one step
        self.assertEqual(state(composer), ("", 0, VIM_NORMAL))


class SubmitTests(unittest.TestCase):
    def test_enter_in_normal_submits_as_in_insert_and_the_next_prompt_starts_in_insert(self) -> None:
        composer = normal("send me")
        action = composer.handle(Key(ENTER))
        self.assertEqual((action.kind, action.text), (SUBMIT, "send me"))
        self.assertEqual(state(composer), ("", 0, VIM_INSERT))

    def test_enter_after_a_backslash_in_normal_sends(self) -> None:
        for text in ("use \\n", "end\\"):
            with self.subTest(text=text):
                composer = Composer(vim=True)
                keys(composer, text)
                composer.handle(ESC)
                action = composer.handle(Key(ENTER))
                self.assertEqual((action.kind, action.text), (SUBMIT, text))

    def test_a_backslash_then_enter_in_insert_still_adds_a_line(self) -> None:
        composer = Composer(vim=True)
        keys(composer, "end\\")
        self.assertEqual(composer.handle(Key(ENTER)).kind, NONE)
        self.assertEqual(composer.text, "end\n")

    def test_alt_enter_adds_a_line_in_either_mode(self) -> None:
        composer = Composer(vim=True)
        keys(composer, "a")
        composer.handle(Key(ENTER, alt=True))
        composer.handle(ESC)
        composer.handle(Key(ENTER, alt=True))
        self.assertEqual(composer.text, "a\n\n")


class ChipAndTokenTests(unittest.TestCase):
    def chipped(self) -> Composer:
        composer = Composer(vim=True)
        keys(composer, "a ")
        composer.handle(Paste(CHIP_TEXT))
        keys(composer, " b")
        composer.handle(ESC)
        self.assertEqual(composer.text, f"a {CHIP} b")
        return composer

    def test_a_chip_is_one_character_to_motions(self) -> None:
        composer = self.chipped()
        keys(composer, "0w")
        self.assertEqual(composer.caret, 2)
        keys(composer, "l")
        self.assertEqual(composer.caret, 2 + len(CHIP))
        keys(composer, "h")
        self.assertEqual(composer.caret, 2)
        keys(composer, "e")
        self.assertEqual(composer.caret, 2 + len(CHIP) + 1)  # past the chip's own blanks
        keys(composer, "b")
        self.assertEqual(composer.caret, 2)

    def test_x_takes_a_chip_whole_and_p_puts_it_back_with_its_text(self) -> None:
        composer = self.chipped()
        composer.caret = 2
        keys(composer, "x")
        self.assertEqual((composer.text, composer.pastes), ("a  b", {}))
        keys(composer, "P")
        self.assertEqual((composer.text, composer.pastes), (f"a {CHIP} b", {CHIP: CHIP_TEXT}))
        self.assertEqual(composer.handle(Key(ENTER)).text, f"a {CHIP_TEXT} b")

    def test_the_caret_never_lands_inside_a_chip_at_the_end_of_a_line(self) -> None:
        composer = Composer(vim=True)
        composer.handle(Paste(CHIP_TEXT))
        composer.handle(ESC)
        self.assertEqual(composer.caret, 0)  # on the chip: it is the line's one character
        keys(composer, "$")
        self.assertEqual(composer.caret, 0)

    def test_dw_over_a_chip_and_undo_put_it_back(self) -> None:
        composer = self.chipped()
        composer.caret = 2
        keys(composer, "dw")
        self.assertEqual((composer.text, composer.pastes), ("a b", {}))
        keys(composer, "u")
        self.assertEqual((composer.text, composer.pastes), (f"a {CHIP} b", {CHIP: CHIP_TEXT}))

    def test_an_image_token_is_one_character_and_p_gives_the_same_image_a_token_of_its_own(self) -> None:
        composer = Composer(vim=True)
        keys(composer, "see")
        image = object()
        composer.insert_image("[Image #1]", image)
        composer.handle(ESC)
        (token,) = composer.images
        self.assertEqual(composer.text, f"see {token} ")
        composer.caret = 4
        keys(composer, "x")
        self.assertEqual((composer.text, composer.images), ("see  ", {}))
        keys(composer, "2P")
        tokens = [ch for ch in composer.text if ch in composer.images]
        self.assertEqual(len(tokens), 2)
        self.assertEqual({composer.images[ch][1] for ch in tokens}, {image})
        action = composer.handle(Key(ENTER))
        self.assertEqual(action.text, "see [Image #1][Image #1] ")
        self.assertEqual([item for _label, item in action.images], [image, image])


class ClusterTests(unittest.TestCase):
    def test_a_cluster_of_several_code_points_is_one_character(self) -> None:
        for cluster in (FAMILY, Q_ACUTE, "한"):
            with self.subTest(cluster=cluster):
                text = f"a{cluster}b"
                composer = normal(text, 0)
                keys(composer, "l")
                self.assertEqual(composer.caret, 1)
                keys(composer, "l")
                self.assertEqual(composer.caret, 1 + len(cluster))
                keys(composer, "hx")
                self.assertEqual(state(composer), ("ab", 1, VIM_NORMAL))
                keys(composer, "P")
                self.assertEqual(composer.text, text)

    def test_esc_steps_back_over_a_whole_cluster(self) -> None:
        composer = Composer(vim=True)
        keys(composer, "a")
        composer.handle(Paste(FAMILY))
        composer.handle(ESC)
        self.assertEqual(composer.caret, 1)

    def test_r_with_a_cluster_replaces_a_cluster(self) -> None:
        composer = normal(f"a{FAMILY}b", 1)
        composer.handle(Key(CHAR, "r"))
        composer.handle(Key(CHAR, "x"))
        self.assertEqual(composer.text, "axb")


class AltChordTests(unittest.TestCase):
    def test_a_legacy_alt_chord_in_insert_is_esc_then_its_key(self) -> None:
        # What ESC h in one read decodes to on a terminal that sends no key reports.
        (event,) = KeyDecoder().feed(b"\x1bh")
        self.assertEqual(event, Key(CHAR, "h", alt=True))
        composer = Composer(vim=True)
        keys(composer, "abc")
        self.assertEqual(composer.handle(event).kind, NONE)
        self.assertEqual(state(composer), ("abc", 1, VIM_NORMAL))  # Esc onto c, then h onto b

    def test_esc_and_then_a_key_in_two_reads_are_two_keys(self) -> None:
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1b"), [])
        self.assertEqual(decoder.feed(b"x"), [ESC, Key(CHAR, "x")])
        composer = Composer(vim=True)
        keys(composer, "abc")
        for event in (ESC, Key(CHAR, "x")):
            composer.handle(event)
        self.assertEqual(state(composer), ("ab", 1, VIM_NORMAL))

    def test_alt_b_and_alt_f_stay_word_moves_in_insert(self) -> None:
        composer = Composer(vim=True)
        keys(composer, "one two")
        composer.handle(Key(CHAR, "b", alt=True))
        self.assertEqual(state(composer), ("one two", 4, VIM_INSERT))
        composer.handle(Key(CHAR, "f", alt=True))
        self.assertEqual(state(composer), ("one two", 7, VIM_INSERT))

    def test_a_reported_alt_chord_is_a_genuine_alt_and_does_nothing(self) -> None:
        (event,) = KeyDecoder().feed(b"\x1b[104;3u")  # kitty CSI u: Alt+h
        self.assertEqual((event, event.protocol), (Key(CHAR, "h", alt=True), True))
        for start_normal in (False, True):
            with self.subTest(normal=start_normal):
                composer = Composer(vim=True)
                keys(composer, "abc")
                if start_normal:
                    composer.handle(ESC)
                before = state(composer)
                composer.handle(event)
                self.assertEqual(state(composer), before)

    def test_a_legacy_alt_chord_in_normal_is_its_key(self) -> None:
        composer = normal("abc", 2)
        composer.handle(Key(CHAR, "x", alt=True))
        self.assertEqual(state(composer), ("ab", 1, VIM_NORMAL))


class ConfigTests(unittest.TestCase):
    def test_vim_mode_reads_display_vim_mode_and_only_a_true_turns_it_on(self) -> None:
        for value, on in (
            (True, True), ("true", True), (" Yes ", True), ("on", True), ("1", True),
            (False, False), ("false", False), ("no", False), ("garbage", False), (1, True), (2, True), (0, False),
            (None, False), ({}, False), ([], False),
        ):
            with self.subTest(value=value):
                self.assertEqual(vim_mode({"config": {"display": {"vim_mode": value}}}), on)
        for result in ({}, {"config": None}, {"config": {}}, {"config": {"display": None}}, {"config": {"display": {}}}):
            with self.subTest(result=result):
                self.assertFalse(vim_mode(result))

    def test_the_settings_answer_turns_it_on_and_off_for_the_main_composer(self) -> None:
        app, _client = make_app()
        self.assertFalse(app.composer.vim)
        app._take_settings({"config": {"display": {"vim_mode": True}}})
        self.assertEqual(app.composer.vim_label, VIM_INSERT)
        app._on_input(ESC)
        app._take_settings({"config": {"display": {"vim_mode": True}}})  # again (a respawn): NORMAL stays
        self.assertEqual(app.composer.vim_label, VIM_NORMAL)
        app._take_settings({"config": {"display": {}}})
        self.assertEqual(app.composer.vim_label, "")

    def test_it_reaches_the_draft_set_aside_for_a_question_not_the_questions_composer(self) -> None:
        now = [100.0]
        app, _client = make_app(clock=lambda: now[0])
        draft = app.composer
        app._on_server_request(ServerRequest("srq-1", "clarify", CLARIFY))
        self.assertIsNot(app.composer, draft)
        app._take_settings({"config": {"display": {"vim_mode": True}}})
        self.assertEqual((draft.vim, app.composer.vim), (True, False))


def vim_app(**options: object) -> tuple[App, object, Clock]:
    clock = Clock()
    app, client = make_app(clock=clock, **options)
    app._take_settings({"config": {"display": {"vim_mode": True}}})
    return app, client, clock


def info(app: App, cols: int = 80) -> str:
    return without_badge(line_text(app._info_line(cols)))


class AppEscTests(unittest.TestCase):
    def test_with_vim_mode_off_esc_esc_still_clears_and_rewinds(self) -> None:
        clock = Clock()
        app, client = make_app(clock=clock)
        app._take_settings({"config": {"display": {"vim_mode": False}}})
        type_text(app, "a draft")
        app._on_input(ESC)
        app._on_input(ESC)
        self.assertEqual((app.composer.text, app.composer.history), ("", ["a draft"]))
        app._on_input(ESC)
        app._on_input(ESC)
        self.assertEqual(client.calls, [("session.history", {"session_id": SID})])

    def test_esc_in_insert_never_arms_the_clear_and_esc_from_normal_does_what_esc_does(self) -> None:
        app, client, clock = vim_app()
        type_text(app, "a draft")
        app._on_input(ESC)
        self.assertEqual((app.composer.text, app.composer.vim_label, app.escape_armed), ("a draft", VIM_NORMAL, None))
        clock.now += DOUBLE_ESCAPE_SECONDS / 4
        app._on_input(ESC)
        self.assertEqual(app.escape_armed, ("clear", clock.now))
        clock.now += DOUBLE_ESCAPE_SECONDS / 4
        app._on_input(ESC)
        self.assertEqual((app.composer.text, app.composer.history), ("", ["a draft"]))
        self.assertEqual(client.calls, [])

    def test_esc_on_an_empty_idle_composer_goes_to_normal_and_only_then_arms_the_rewind(self) -> None:
        app, client, _clock = vim_app()
        app._on_input(ESC)
        self.assertIsNone(app.escape_armed)
        app._on_input(ESC)
        self.assertNotIn("session.history", [name for name, _params in client.calls])
        app._on_input(ESC)
        self.assertEqual(client.calls, [("session.history", {"session_id": SID})])

    def test_esc_never_interrupts_a_turn_at_once_and_twice_from_normal_it_does(self) -> None:
        app, client, clock = vim_app(busy=True)
        app._on_input(ESC)
        self.assertEqual((client.calls, app.composer.vim_label, app.escape_armed), ([], VIM_NORMAL, None))
        app._on_input(ESC)  # Esc pressed twice to leave INSERT only arms the interrupt
        self.assertEqual(client.calls, [])
        self.assertIn("esc again to interrupt", info(app))
        clock.now += DOUBLE_ESCAPE_SECONDS / 2
        app._on_input(ESC)
        self.assertEqual([name for name, _params in client.calls], ["session.interrupt"])

    def test_an_armed_interrupt_lapses_after_the_window(self) -> None:
        app, client, clock = vim_app(busy=True)
        app._on_input(ESC)
        app._on_input(ESC)
        clock.now += DOUBLE_ESCAPE_SECONDS + 0.1
        app._on_input(ESC)
        self.assertEqual(client.calls, [])

    def test_with_vim_mode_off_one_esc_still_interrupts(self) -> None:
        app, client = make_app(busy=True)
        app._on_input(ESC)
        self.assertEqual([name for name, _params in client.calls], ["session.interrupt"])

    def test_insert_between_two_escs_takes_back_the_armed_clear(self) -> None:
        app, _client, _clock = vim_app()
        type_text(app, "draft")
        app._on_input(ESC)  # NORMAL
        app._on_input(ESC)  # arms the clear
        type_text(app, "i")
        self.assertIsNone(app.escape_armed)
        app._on_input(ESC)  # NORMAL again
        app._on_input(ESC)  # arms again, clears nothing
        self.assertEqual(app.composer.text, "draft")

    def test_esc_drops_a_half_typed_command_before_it_arms_anything(self) -> None:
        app, _client, _clock = vim_app()
        type_text(app, "draft")
        app._on_input(ESC)
        type_text(app, "d")
        app._on_input(ESC)
        self.assertEqual((app.composer.pending, app.escape_armed), (False, None))

    def test_dropping_a_half_typed_command_takes_back_an_armed_clear(self) -> None:
        app, _client, _clock = vim_app()
        type_text(app, "keep")
        app._on_input(ESC)  # NORMAL
        app._on_input(ESC)  # arms the clear
        type_text(app, "d")
        app._on_input(ESC)  # drops the d, and the armed clear with it
        app._on_input(ESC)  # arms again
        self.assertEqual(app.composer.text, "keep")

    def test_normal_letters_never_type_in_the_app(self) -> None:
        app, client, _clock = vim_app()
        type_text(app, "hello")
        app._on_input(ESC)
        type_text(app, "zqZQ!@#")
        self.assertEqual(app.composer.text, "hello")
        type_text(app, "0x")
        self.assertEqual(app.composer.text, "ello")
        app._on_input(Key(ENTER))
        self.assertEqual(client.named("prompt.submit")[-1]["text"], "ello")
        self.assertEqual(app.composer.vim_label, VIM_INSERT)

    def test_bytes_a_legacy_terminal_sends_decode_and_dispatch_as_vim_keys(self) -> None:
        app, client, _clock = vim_app()
        now = [0.0]
        decoder = KeyDecoder(lambda: now[0])
        for chunk in (b"hello world", b"\x1b", b"0dw", b"\x1bA", b"!\r"):  # ESC A in one read: Esc, then A
            now[0] += 0.1  # a read a tenth of a second after the one before, as typing brings them
            for event in decoder.feed(chunk):
                app._on_input(event)
        self.assertEqual(client.named("prompt.submit")[-1]["text"], "world!")
        self.assertEqual((app.composer.text, app.composer.vim_label), ("", VIM_INSERT))

    def test_ctrl_r_redoes_in_normal_and_searches_the_history_in_insert(self) -> None:
        app, _client, _clock = vim_app()
        type_text(app, "one two")
        app._on_input(ESC)
        type_text(app, "0dwu")
        app._on_input(Key(CHAR, "r", ctrl=True))
        self.assertEqual((app.composer.text, app.search), ("two", None))
        type_text(app, "i")
        app._on_input(Key(CHAR, "r", ctrl=True))
        self.assertIsNotNone(app.search)


class AppOwnersTests(unittest.TestCase):
    def test_an_approval_keeps_its_keys(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        app._take_settings({"config": {"display": {"vim_mode": True}}})
        type_text(app, "draft")
        app._on_input(ESC)
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        now[0] += 1.0
        app._on_input(Key(CHAR, "d"))  # deny, as without vim mode, and no dd on the draft
        self.assertEqual(client.answers[0][0], "srq-1")
        self.assertEqual(app.composer.text, "draft")

    def test_a_question_typed_into_is_not_modal_and_esc_declines_it(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        app._take_settings({"config": {"display": {"vim_mode": True}}})
        app._on_server_request(ServerRequest("srq-1", "clarify", CLARIFY))
        now[0] += 1.0
        type_text(app, "hjkl")
        self.assertEqual(app.composer.text, "hjkl")
        self.assertNotIn(VIM_INSERT, info(app))
        app._on_input(ESC)
        self.assertEqual(client.answers[0][0], "srq-1")
        self.assertTrue(app.composer.vim)  # the draft comes back, modal

    def test_a_masked_secret_is_not_modal(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        app._take_settings({"config": {"display": {"vim_mode": True}}})
        app._on_server_request(ServerRequest("srq-1", "sudo", {}))
        now[0] += 1.0
        type_text(app, "dd")
        app._on_input(Key(ENTER))
        self.assertEqual(client.answers, [("srq-1", {"result": {"value": "dd"}})])

    def test_the_agent_list_keeps_its_keys(self) -> None:
        app, client = agent_app()
        app._take_settings({"config": {"display": {"vim_mode": True}}})
        app._on_input(ESC)  # NORMAL, and no interrupt
        app._on_input(Key(DOWN))
        self.assertEqual(app.list_selected, FIRST)
        type_text(app, "ddp")  # keys of no use to the list do nothing there, and never reach the draft
        self.assertEqual((app.composer.text, app.list_selected), ("", FIRST))
        self.assertNotIn(VIM_NORMAL, info(app))  # the list has the keys: no editing mode is said
        app._on_input(ESC)
        self.assertIsNone(app.list_selected)
        self.assertEqual(app.composer.vim_label, VIM_NORMAL)
        self.assertNotIn("session.interrupt", [name for name, _params in client.calls])

    def test_the_tell_row_composer_is_not_modal_and_the_draft_stays_modal(self) -> None:
        app, _client, _clock = vim_app()
        type_text(app, "my draft")
        app._on_input(ESC)
        draft = app.composer
        app._open_tell()
        self.assertIs(app._draft(), draft)
        self.assertFalse(app.composer.vim)
        self.assertNotIn(VIM_NORMAL, info(app))
        type_text(app, "hjkl")
        self.assertEqual(app.composer.text, "hjkl")
        app._take_settings({"config": {"display": {"vim_mode": True}}})  # an answer meanwhile reaches the draft only
        self.assertFalse(app.composer.vim)
        app._on_input(ESC)  # leaves the tell row, as without vim mode
        self.assertIs(app.composer, draft)
        self.assertEqual((app.composer.text, app.composer.vim_label), ("my draft", VIM_NORMAL))


class AppMenuTests(unittest.TestCase):
    def test_esc_from_insert_closes_the_path_menu_and_tab_then_completes_nothing(self) -> None:
        app, _client, _clock = vim_app()
        type_text(app, "see @src/ma")
        app.path_word = "@src/ma"
        app.path_items = [PathItem("@src/main.py", "src/main.py", "file")]
        app._on_input(ESC)
        self.assertEqual(app._menu_rows(), [])
        app._track_path_token()  # the loop's next pass asks for no matches in NORMAL
        self.assertEqual((app.path_items, app.path_due), ([], None))
        app._on_input(Key(TAB))
        self.assertEqual(app.composer.text, "see @src/ma")

    def test_esc_from_insert_closes_the_slash_menu_and_enter_sends_what_is_typed(self) -> None:
        app, client, _clock = vim_app()
        type_text(app, "/mod")
        self.assertTrue(app._menu_rows())
        app._on_input(ESC)
        self.assertEqual(app._menu_rows(), [])
        type_text(app, "x")  # an edit in NORMAL opens no menu either
        self.assertEqual((app.composer.text, app._menu_rows()), ("/mo", []))
        type_text(app, "a")  # back in INSERT the menu is back
        self.assertTrue(app._menu_rows())
        app._on_input(ESC)
        app._on_input(Key(ENTER))
        self.assertEqual(client.named("slash.exec")[-1]["command"], "mo")

    def test_with_vim_mode_off_esc_still_closes_the_menu_and_keeps_the_mode(self) -> None:
        app, _client = make_app()
        type_text(app, "/mod")
        app._on_input(ESC)
        self.assertEqual((app._menu_rows(), app.composer.normal), ([], False))


class AppMenuBurstTests(unittest.TestCase):
    def test_esc_a_key_and_tab_in_one_read_complete_nothing_in_normal(self) -> None:
        # A legacy terminal sends Esc and the next key in one read as an Alt chord, which never reaches `_escape`:
        # the `@` menu is still set, and Tab must not complete it against NORMAL's caret.
        app, _client, _clock = vim_app()
        type_text(app, "see @src/ma")
        app.path_word = "@src/ma"
        app.path_items = [PathItem("@src/main.py", "src/main.py", "file")]
        for event in KeyDecoder().feed(b"\x1bl\t"):
            app._on_input(event)
        self.assertEqual((app.composer.text, app.composer.vim_label), ("see @src/ma", VIM_NORMAL))
        self.assertEqual(app._menu_rows(), [])


class WorkingRowHintTests(unittest.TestCase):
    def test_the_interrupt_hint_names_the_keys_that_interrupt(self) -> None:
        app, _client = make_app(busy=True)
        self.assertTrue(working_rows(app)[0].endswith("esc to interrupt)"))  # vim off: one Esc, as before
        app, _client, _clock = vim_app(busy=True)
        self.assertNotIn("interrupt", working_rows(app)[0])  # INSERT: Esc goes to NORMAL first
        app._on_input(ESC)
        self.assertTrue(working_rows(app)[0].endswith("esc esc to interrupt)"), working_rows(app))


class InfoLineTests(unittest.TestCase):
    def test_the_line_names_the_editing_mode_only_while_vim_mode_is_on(self) -> None:
        app, _client = make_app()
        self.assertNotIn(VIM_INSERT, info(app))
        app._take_settings({"config": {"display": {"vim_mode": True}}})
        self.assertEqual(info(app).split()[0], VIM_INSERT)
        app._on_input(ESC)
        self.assertEqual(info(app).split()[0], VIM_NORMAL)

    def test_it_comes_before_the_mode_label_and_keeps_its_word_while_the_label_shortens(self) -> None:
        for width in (80, 40, 24, 16):
            with self.subTest(width=width):
                line = line_text(info_line(mode=MODE_ACCEPT, width=width, theme=DEFAULT_THEME, editing=VIM_NORMAL))
                self.assertTrue(line.startswith(VIM_NORMAL + " · ⏵⏵"), line)

    def test_it_is_among_the_last_things_on_a_narrow_line(self) -> None:
        line = line_text(info_line(mode=MODE_NORMAL, width=12, theme=DEFAULT_THEME, editing=VIM_INSERT,
                                   right=((Span("x" * 30),),)))
        self.assertEqual(line.strip(), VIM_INSERT)

    def test_the_agent_count_starts_after_it(self) -> None:
        self.assertEqual(chip_column(MODE_NORMAL, DEFAULT_THEME, VIM_INSERT), len(VIM_INSERT) + 3)
        label = editing_label(VIM_INSERT, MODE_ACCEPT, DEFAULT_THEME)
        self.assertEqual(chip_column(MODE_ACCEPT, DEFAULT_THEME, VIM_INSERT), line_width(label) + 3)
        self.assertEqual(editing_label("", MODE_ACCEPT, DEFAULT_THEME), mode_label(MODE_ACCEPT, DEFAULT_THEME))


if __name__ == "__main__":
    unittest.main()
