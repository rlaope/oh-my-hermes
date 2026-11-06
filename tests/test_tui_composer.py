"""The composer's editing state machine and its rendering (`omh.tui.composer`).

Every key the design lists has a test, and each editing key is also run over
text a terminal user actually types: Hangul (composed, and decomposed as a
macOS paste delivers it), emoji with a ZWJ, a skin tone or a flag, and a
combining mark. Expectations are literals; the caret position after a wrap is
counted by hand in cells.
"""

from __future__ import annotations

import random
import unicodedata
import unittest
from unittest.mock import patch

from _tui_lines import line_text, lines_text
from omh.tui.composer import (
    CANCEL,
    COMPLETE,
    EXIT,
    HISTORY_CAP,
    IMAGE_LABEL,
    INTERRUPT,
    NONE,
    SUBMIT,
    Composer,
    ComposerAction,
)
from omh.tui.keys import (
    BACKSPACE,
    CHAR,
    DELETE,
    DOWN,
    END,
    ENTER,
    ESCAPE,
    HOME,
    INSERT,
    LEFT,
    PAGE_UP,
    RIGHT,
    TAB,
    UNKNOWN,
    UP,
    Key,
    KeyDecoder,
    Paste,
    is_leader_key,
)
from omh.tui.style import Style
from omh.tui import composer as composer_module
from omh.tui.width import cell_width, cluster_width, clusters, line_width

HANGUL = "한글"
HANGUL_NFD = unicodedata.normalize("NFD", HANGUL)
FAMILY = "\U0001F468‍\U0001F469‍\U0001F467‍\U0001F466"
THUMBS_UP_TONED = "\U0001F44D\U0001F3FD"
FLAG_KR = "\U0001F1F0\U0001F1F7"
Q_ACUTE = "q́"


def ctrl(char: str) -> Key:
    return Key(CHAR, char, ctrl=True)


def typed(composer: Composer, text: str) -> None:
    for ch in text:
        composer.handle(Key(CHAR, ch))


def press(composer: Composer, *keys: Key) -> ComposerAction:
    action = ComposerAction(NONE)
    for key in keys:
        action = composer.handle(key)
    return action


def at(text: str, caret: int) -> Composer:
    return Composer(text=text, caret=caret)


class ComposerLeaderTests(unittest.TestCase):
    def normal_composer(self) -> Composer:
        composer = Composer(vim=True)
        typed(composer, "abcd")
        composer.handle(Key(ESCAPE))
        composer.handle(Key(CHAR, "0"))
        return composer

    def test_normal_mode_space_arms_leader(self) -> None:
        for text in ("", "abcd", "한글 👩‍💻"):
            with self.subTest(text=text):
                composer = Composer(text=text, caret=0, vim=True)
                composer.handle(Key(ESCAPE))
                before = (composer.text, composer.caret)
                self.assertFalse(composer.leader)
                self.assertFalse(composer.pending)
                self.assertEqual(composer.handle(Key(CHAR, " ")), ComposerAction(NONE))
                self.assertTrue(composer.leader)
                self.assertTrue(composer.pending)
                self.assertTrue(composer.normal)
                self.assertEqual((composer.text, composer.caret), before)

    def test_leader_property_is_read_only(self) -> None:
        composer = self.normal_composer()
        with self.assertRaises(AttributeError):
            setattr(composer, "leader", True)

    def test_all_key_followers_cancel_without_dispatch(self) -> None:
        followers = [Key(CHAR, char) for char in " zhidrcgxup123"]
        followers += [Key(name) for name in (ESCAPE, ENTER, TAB, BACKSPACE, DELETE, LEFT, RIGHT, UP, DOWN, HOME, END, UNKNOWN)]
        followers += [ctrl(char) for char in "_-rycd"]
        followers += [Key(CHAR, " ", **{modifier: True}) for modifier in ("ctrl", "alt", "shift", "reported_shift")]
        for event in followers:
            with self.subTest(event=event):
                composer = self.normal_composer()
                composer.handle(Key(CHAR, " "))
                before = (composer.text, composer.caret, list(composer._undo), list(composer._redo))
                self.assertEqual(composer.handle(event), ComposerAction(NONE))
                self.assertFalse(composer.leader)
                self.assertFalse(composer.pending)
                self.assertTrue(composer.normal)
                self.assertEqual((composer.text, composer.caret, composer._undo, composer._redo), before)

    def test_leader_follower_does_not_redo_a_real_history_step(self) -> None:
        composer = self.normal_composer()
        composer.handle(ctrl("_"))
        self.assertEqual(composer.text, "")
        self.assertTrue(composer._redo)
        typed(composer, " ")
        before = (composer.text, composer.caret, list(composer._undo), list(composer._redo))
        self.assertEqual(composer.handle(ctrl("r")), ComposerAction(NONE))
        self.assertEqual((composer.text, composer.caret, composer._undo, composer._redo), before)
        self.assertFalse(composer.leader)
        self.assertFalse(composer.pending)
        composer.handle(ctrl("r"))
        self.assertEqual(composer.text, "abcd")

    def test_consumed_follower_does_not_swallow_the_next_command(self) -> None:
        composer = self.normal_composer()
        typed(composer, " x")
        self.assertEqual(composer.text, "abcd")
        typed(composer, "x")
        self.assertEqual(composer.text, "bcd")

    def test_insert_and_non_vim_mode_space_types_character(self) -> None:
        for vim, masked in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(vim=vim, masked=masked):
                composer = Composer(vim=vim, masked=masked)
                composer.handle(Key(CHAR, " "))
                self.assertEqual(composer.text, " ")
                self.assertFalse(composer.leader)
                self.assertFalse(composer.pending)

    def test_is_leader_key_modifier_rejection(self) -> None:
        modifiers = ("ctrl", "alt", "shift", "reported_shift")
        for bits in range(1 << len(modifiers)):
            flags = {name: bool(bits & (1 << index)) for index, name in enumerate(modifiers)}
            with self.subTest(flags=flags):
                event = Key(CHAR, " ", **flags)
                self.assertEqual(is_leader_key(event), not any(flags.values()))
                composer = self.normal_composer()
                composer.handle(event)
                self.assertEqual(composer.leader, not any(flags.values()))
        for event in (Key(CHAR, "x"), Key(ENTER, " "), Key(CHAR, "\t"), Paste(" ")):
            with self.subTest(event=event):
                self.assertFalse(is_leader_key(event))
        self.assertTrue(is_leader_key(Key(CHAR, " ", protocol=True)))

    def test_reported_plain_space_arms_leader(self) -> None:
        for raw in (b" ", b"\x1b[32u", b"\x1b[32;1u", b"\x1b[27;1;32~"):
            with self.subTest(raw=raw):
                events = KeyDecoder().feed(raw)
                self.assertEqual(len(events), 1)
                composer = self.normal_composer()
                composer.handle(events[0])
                self.assertTrue(composer.leader)

    def test_operator_and_prefix_precedence_over_leader(self) -> None:
        for command, expected in (("r", " bcd"), ("d", "abcd"), ("c", "abcd"), ("y", "abcd"), ("g", "abcd")):
            with self.subTest(command=command):
                composer = self.normal_composer()
                typed(composer, command)
                self.assertTrue(composer.pending)
                composer.handle(Key(CHAR, " "))
                self.assertEqual(composer.text, expected)
                self.assertFalse(composer.leader)
                self.assertFalse(composer.pending)
                self.assertTrue(composer.normal)

    def test_count_is_cleared_when_leader_arms(self) -> None:
        composer = self.normal_composer()
        typed(composer, "3 ")
        self.assertTrue(composer.leader)
        typed(composer, "zx")
        self.assertEqual(composer.text, "bcd")
        self.assertFalse(composer.pending)

    def test_drop_pending_and_mode_transitions_reset_leader(self) -> None:
        for transition in ("_drop_pending", "_enter_insert", "_enter_normal", "vim_off", "vim_on"):
            with self.subTest(transition=transition):
                composer = self.normal_composer()
                typed(composer, " ")
                if transition.startswith("vim_"):
                    composer.set_vim(transition == "vim_on")
                else:
                    getattr(composer, transition)()
                self.assertFalse(composer.leader)
                self.assertFalse(composer.pending)
                if transition in ("_enter_insert", "vim_off", "vim_on"):
                    self.assertFalse(composer.normal)
                    typed(composer, " ")
                    self.assertEqual(composer.text, " abcd")
                    self.assertFalse(composer.leader)

    def test_paste_resets_leader_and_preserves_paste_insertion(self) -> None:
        composer = self.normal_composer()
        typed(composer, " ")
        self.assertEqual(composer.handle(Paste("hello ")), ComposerAction(NONE))
        self.assertEqual(composer.text, "hello abcd")
        self.assertTrue(composer.normal)
        self.assertFalse(composer.leader)
        self.assertFalse(composer.pending)


class InsertTests(unittest.TestCase):
    def test_printable_keys_insert_at_the_caret(self) -> None:
        composer = Composer()
        typed(composer, "helo")
        press(composer, Key(LEFT))
        typed(composer, "l")
        self.assertEqual((composer.text, composer.caret), ("hello", 4))

    def test_hangul_and_emoji_insert_as_typed(self) -> None:
        composer = Composer()
        typed(composer, HANGUL)
        composer.handle(Key(CHAR, FAMILY))
        self.assertEqual(composer.text, HANGUL + FAMILY)
        self.assertEqual(composer.caret, len(HANGUL + FAMILY))

    def test_alt_with_a_printable_character_types_the_character(self) -> None:
        # `ESC x` is also what Esc then x send when both arrive in one read: the x is not lost with the Esc.
        for char, text in (("x", "axbc"), ("/", "a/bc"), ("한", "a한bc"), (" ", "a bc")):
            with self.subTest(char=char):
                composer = at("abc", 1)
                self.assertEqual(composer.handle(Key(CHAR, char, alt=True)), ComposerAction(NONE))
                self.assertEqual((composer.text, composer.caret), (text, 1 + len(char)))

    def test_option_arrows_from_terminal_app_move_by_a_word(self) -> None:
        # Terminal.app sends Option+Left and Option+Right as `ESC b` and `ESC f`, readline's word moves.
        for data, arrow in ((b"\x1bb", LEFT), (b"\x1bf", RIGHT)):
            with self.subTest(data=data):
                composer, by_arrow = at("one two three", 5), at("one two three", 5)
                by_arrow.handle(Key(arrow, alt=True))
                for key in KeyDecoder().feed(data):
                    composer.handle(key)
                self.assertNotEqual(by_arrow.caret, 5)
                self.assertEqual((composer.text, composer.caret), ("one two three", by_arrow.caret))

    def test_esc_then_a_command_in_one_read_types_the_command(self) -> None:
        composer = Composer()
        for key in KeyDecoder().feed(b"\x1b/quit"):
            composer.handle(key)
        self.assertEqual(composer.text, "/quit")

    def test_reported_alt_b_and_f_move_by_a_word_as_the_legacy_bytes_do(self) -> None:
        for data, arrow in ((b"\x1b[98;3u", LEFT), (b"\x1b[102;3u", RIGHT)):
            with self.subTest(data=data):
                composer, by_arrow = at("one two three", 5), at("one two three", 5)
                by_arrow.handle(Key(arrow, alt=True))
                (key,) = KeyDecoder().feed(data)
                self.assertTrue(key.protocol)
                composer.handle(key)
                self.assertEqual((composer.text, composer.caret), ("one two three", by_arrow.caret))

    def test_reported_alt_chords_and_unbound_ctrl_keys_change_nothing(self) -> None:
        # A kitty or modifyOtherKeys report says Alt was held: no Esc can hide in it, so it types nothing.
        composer = at("abc", 1)
        for key in (Key(CHAR, "x", alt=True, protocol=True), ctrl("q"), Key(INSERT), Key(PAGE_UP), Key(UNKNOWN)):
            with self.subTest(key=key):
                self.assertEqual(composer.handle(key), ComposerAction(NONE))
                self.assertEqual((composer.text, composer.caret), ("abc", 1))

    def test_a_decomposed_paste_is_stored_composed(self) -> None:
        composer = Composer()
        composer.handle(Paste(HANGUL_NFD))
        self.assertEqual(composer.text, HANGUL)
        self.assertEqual(composer.caret, 2)

    def test_construction_normalizes_and_a_caret_inside_a_syllable_lands_after_it(self) -> None:
        composer = Composer(text=HANGUL_NFD, caret=4)  # after the first jamo of the second syllable
        self.assertEqual((composer.text, composer.caret), (HANGUL, 2))


class NewlineAndSubmitTests(unittest.TestCase):
    def test_enter_submits_the_text_and_clears(self) -> None:
        composer = Composer()
        typed(composer, "hi")
        self.assertEqual(composer.handle(Key(ENTER)), ComposerAction(SUBMIT, "hi"))
        self.assertEqual((composer.text, composer.caret, composer.history), ("", 0, ["hi"]))

    def test_enter_on_empty_input_submits_nothing_into_history(self) -> None:
        composer = Composer()
        self.assertEqual(composer.handle(Key(ENTER)), ComposerAction(SUBMIT, ""))
        typed(composer, "   ")
        press(composer, Key(ENTER))
        self.assertEqual(composer.history, [])

    def test_a_repeated_submit_is_stored_once(self) -> None:
        composer = Composer()
        for text in ("one", "one", "two", "one"):
            typed(composer, text)
            press(composer, Key(ENTER))
        self.assertEqual(composer.history, ["one", "two", "one"])

    def test_history_keeps_its_newest_entries_up_to_the_cap(self) -> None:
        composer = Composer(history=[f"old {number}" for number in range(HISTORY_CAP)])
        typed(composer, "newest")
        press(composer, Key(ENTER))
        self.assertEqual(len(composer.history), HISTORY_CAP)
        self.assertEqual((composer.history[0], composer.history[-1]), ("old 1", "newest"))

    def test_alt_enter_and_ctrl_j_insert_a_newline(self) -> None:
        composer = Composer()
        typed(composer, "a")
        press(composer, Key(ENTER, alt=True))
        typed(composer, "b")
        press(composer, ctrl("j"))
        typed(composer, "c")
        self.assertEqual(composer.text, "a\nb\nc")
        self.assertEqual(composer.handle(Key(ENTER)), ComposerAction(SUBMIT, "a\nb\nc"))

    def test_shift_enter_adds_a_line_as_alt_enter_does(self) -> None:
        for modifier in ("alt", "shift"):
            with self.subTest(modifier=modifier):
                composer = Composer()
                typed(composer, "a\\")
                self.assertEqual(composer.handle(Key(ENTER, **{modifier: True})), ComposerAction(NONE))
                typed(composer, "b")
                # The backslash stays: only a plain Enter trades it for the newline.
                self.assertEqual(composer.text, "a\\\nb")
                self.assertEqual(composer.history, [])

    def test_ctrl_enter_submits_as_enter_does(self) -> None:
        for key in (Key(ENTER), Key(ENTER, ctrl=True)):
            with self.subTest(key=key):
                composer = Composer()
                typed(composer, "send me")
                self.assertEqual(composer.handle(key), ComposerAction(SUBMIT, "send me"))
                self.assertEqual(composer.history, ["send me"])

    def test_enter_right_after_a_backslash_turns_it_into_a_newline(self) -> None:
        composer = Composer()
        typed(composer, "one\\")
        self.assertEqual(composer.handle(Key(ENTER)), ComposerAction(NONE))
        typed(composer, "two")
        self.assertEqual((composer.text, composer.caret), ("one\ntwo", 7))
        self.assertEqual(composer.handle(Key(ENTER)), ComposerAction(SUBMIT, "one\ntwo"))

    def test_a_backslash_away_from_the_caret_or_in_masked_input_does_not_hold_enter(self) -> None:
        composer = Composer(text="a\\ b", caret=4)
        self.assertEqual(composer.handle(Key(ENTER)), ComposerAction(SUBMIT, "a\\ b"))
        masked = Composer(masked=True)
        typed(masked, "pw\\")
        self.assertEqual(masked.handle(Key(ENTER)), ComposerAction(SUBMIT, "pw\\"))

    def test_replace_swaps_a_range_and_parks_the_caret_after_it(self) -> None:
        composer = Composer(text="see @sr now", caret=7)
        composer.replace(4, 7, "@file:src/" + HANGUL_NFD + ".md")
        self.assertEqual(composer.text, f"see @file:src/{HANGUL}.md now")
        self.assertEqual(composer.caret, len(f"see @file:src/{HANGUL}.md"))


class VimWordObjectTests(unittest.TestCase):
    """WO-1..WO-7: complete command outcomes and falsification cases from the accepted plan."""

    def normal(self, text: str, caret: int = 0) -> Composer:
        composer = Composer(text=text, caret=caret, vim=True)
        composer.normal = True
        return composer

    def cleared(self, composer: Composer) -> None:
        self.assertFalse(composer.pending)
        self.assertEqual((composer._operator, composer._prefix, composer._count, composer._op_count), ("", "", "", ""))

    def deletion(self, text: str, caret: int, command: str, result: str, at: int, captured: str) -> None:
        composer = self.normal(text, caret)
        typed(composer, command)
        self.assertEqual((composer.text, composer.caret, composer.normal), (result, at, True))
        self.cleared(composer)
        self.assertIsNotNone(composer._register)
        self.assertEqual((composer._register.text, composer._register.linewise,
                          composer._register.pastes, composer._register.images), (captured, False, {}, {}))
        self.assertEqual(len(composer._undo), 1)

    def test_inner_range(self) -> None:
        for caret in (6, 8, 9):
            with self.subTest(caret=caret):
                self.deletion("alpha beta gamma", caret, "diw", "alpha  gamma", 6, "beta")
        for caret in (0, 2, 3):
            with self.subTest(single=caret):
                self.deletion("word", caret, "diw", "", 0, "word")

    def test_whitespace_range(self) -> None:
        for caret in (3, 4, 5):
            with self.subTest(caret=caret):
                self.deletion("one  \ttwo", caret, "diw", "onetwo", 3, "  \t")
        for token in ("foo.bar-baz", "...!?", "one\u00a0two"):
            with self.subTest(token=token):
                self.deletion(token + " end", 2, "diw", " end", 0, token)
        for text, caret, result, at, captured in (
            (" \tone", 1, "one", 0, " \t"),
            ("one \t ", 4, "one", 2, " \t "),
            (" \t ", 1, "", 0, " \t "),
        ):
            with self.subTest(text=text):
                self.deletion(text, caret, "diw", result, at, captured)
        self.assertEqual(composer_module._word_end(list("one\u00a0two"), 0), 3)
        self.assertEqual(composer_module.WORD_BREAKS, {" ", "\t"})

    def test_around_range(self) -> None:
        for caret in (5, 6, 7):
            with self.subTest(caret=caret):
                self.deletion("one  two\t  three", caret, "daw", "one  three", 5, "two\t  ")
                self.deletion("one  two", caret, "daw", "one", 2, "  two")
        self.deletion("word", 2, "daw", "", 0, "word")
        self.deletion(" \tword", 3, "daw", "", 0, " \tword")
        self.deletion("...!? end", 2, "daw", "end", 0, "...!? ")

    def test_around_blank_range(self) -> None:
        for caret in (3, 4):
            with self.subTest(caret=caret):
                self.deletion("one  two  three", caret, "daw", "one  three", 3, "  two")
        for text, caret, result, at, captured in (
            ("one \t ", 4, "one", 2, " \t "),
            (" \t ", 1, "", 0, " \t "),
            (" \tone  end", 1, "  end", 0, " \tone"),
            ("one  two  ", 3, "one  ", 3, "  two"),
        ):
            with self.subTest(text=text):
                self.deletion(text, caret, "daw", result, at, captured)

    def test_count_range(self) -> None:
        for command, result, captured in (
            ("1diw", " b c d e", "a"), ("2diw", "b c d e", "a "),
            ("d2iw", "b c d e", "a "), ("2d2iw", "c d e", "a b "),
            ("2daw", "c d e", "a b "), ("d2aw", "c d e", "a b "),
            ("2d2aw", "e", "a b c d "),
        ):
            with self.subTest(command=command):
                self.deletion("a b c d e", 0, command, result, 0, captured)
        self.deletion("a b  ", 1, "d99999aw", "a  ", 1, " b")
        self.deletion("a b c", 2, "d99aw", "a", 0, " b c")
        self.deletion("a  b  ", 3, "d99aw", "a  ", 2, "b  ")
        for descriptor in "ia":
            with self.subTest(descriptor=descriptor):
                self.deletion("a b c\nnext  line", 0, "99999d99999" + descriptor + "w",
                              "\nnext  line", 0, "a b c")
        composer = self.normal("a b c")
        typed(composer, "99999d99999i")
        self.assertEqual((composer._count, composer._op_count), ("9999", "9999"))
        self.assertEqual(composer._take_count(), 9999)
        composer = self.normal("a b c")
        typed(composer, "d20")
        self.assertEqual((composer.text, composer.caret, composer.pending, composer._operator, composer._op_count),
                         ("a b c", 0, True, "d", "20"))
        composer = self.normal("a b c", 2)
        typed(composer, "d0")
        self.assertEqual((composer.text, composer.caret, composer._register.text), ("b c", 0, "a "))
        self.cleared(composer)

    def test_pending_state(self) -> None:
        composer = self.normal("a b c d e")
        composer._yank(8, 9, False)
        register = composer._register
        typed(composer, "2d3i")
        self.assertEqual((composer.text, composer.caret, composer.normal, composer._register),
                         ("a b c d e", 0, True, register))
        self.assertTrue(composer.pending)
        self.assertEqual((composer._operator, composer._count, composer._op_count, composer._prefix), ("d", "2", "3", "i"))
        typed(composer, "w")
        self.assertEqual((composer.text, composer.caret, composer.normal, composer._register.text), ("d e", 0, True, "a b c "))
        self.cleared(composer)

    def test_cancel_state(self) -> None:
        events = (Key(ESCAPE), Key(CHAR, "x"), Key(CHAR, "2"), Key(CHAR, "g"),
                  Key(CHAR, "r"), Key(CHAR, " "), Key(LEFT), Key(BACKSPACE), Key(DELETE))
        for operator in "dcy":
            for descriptor in "ia":
                for event in events:
                    with self.subTest(operator=operator, descriptor=descriptor, event=event):
                        composer = self.normal("one two three", 4)
                        composer._yank(0, 3, False)
                        before = (composer._state(), composer.normal, composer._register)
                        typed(composer, "2" + operator + "3" + descriptor)
                        composer.handle(event)
                        self.assertEqual((composer._state(), composer.normal, composer._register), before)
                        self.cleared(composer)
                        self.assertFalse(composer._undo)
                        typed(composer, "w")
                        self.assertEqual((composer.text, composer.caret, composer.normal), ("one two three", 8, True))
                        self.cleared(composer)
                for reset in ("off", "on", "paste", "undo", "redo", "vim_redo"):
                    with self.subTest(operator=operator, descriptor=descriptor, reset=reset):
                        composer, control = self.normal("one two", 4), self.normal("one two", 4)
                        for c in (composer, control):
                            typed(c, "x")
                            if reset in ("redo", "vim_redo"):
                                c.handle(ctrl("_"))
                        typed(composer, "2" + operator + "3" + descriptor)
                        for c in (composer, control):
                            if reset in ("off", "on"):
                                c.set_vim(reset == "on")
                            else:
                                c.handle({"paste": Paste("!"), "undo": ctrl("_"),
                                          "redo": ctrl("y"), "vim_redo": ctrl("r")}[reset])
                        self.cleared(composer)
                        self.assertEqual((composer._state(), composer.normal, composer.vim, composer._register,
                                          composer._undo, composer._redo),
                                         (control._state(), control.normal, control.vim, control._register,
                                          control._undo, control._redo))
                        for c in (composer, control):
                            c.set_vim(True)
                            c.normal = True
                            typed(c, "w")
                        self.assertEqual(composer._state(), control._state())
                        self.cleared(composer)

    def test_operator_effects(self) -> None:
        for operator in "dcy":
            for descriptor, captured, result in (("i", "beta", "alpha  gamma"), ("a", "beta ", "alpha gamma")):
                with self.subTest(operator=operator, descriptor=descriptor):
                    composer = self.normal("alpha beta gamma", 8)
                    typed(composer, operator + descriptor + "w")
                    self.assertEqual((composer.text, composer.caret, composer.normal),
                                     ("alpha beta gamma" if operator == "y" else result, 6, operator != "c"))
                    self.cleared(composer)
                    self.assertEqual((composer._register.text, composer._register.linewise,
                                      composer._register.pastes, composer._register.images), (captured, False, {}, {}))
                    self.assertEqual(len(composer._undo), 0 if operator == "y" else 1)

    def test_undo_register(self) -> None:
        for descriptor in "ia":
            for operator in "dcy":
                with self.subTest(operator=operator, descriptor=descriptor):
                    composer = self.normal("alpha beta gamma", 8)
                    before = composer._state()
                    typed(composer, operator + descriptor + "w")
                    register = composer._register
                    if operator == "c":
                        typed(composer, "NEW")
                        composer.handle(Key(ESCAPE))
                        self.assertEqual(composer.text, "alpha NEW gamma" if descriptor == "i" else "alpha NEWgamma")
                    after = composer._state()
                    self.assertEqual(len(composer._undo), 0 if operator == "y" else 1)
                    typed(composer, "u")
                    self.assertEqual(composer._state(), after if operator == "y" else before)
                    composer.handle(ctrl("r"))
                    self.assertEqual(composer._state(), after)
                    self.assertEqual(composer._register, register)
                    text, caret = composer.text, composer.caret
                    typed(composer, "P")
                    self.assertEqual(composer.text, text[:caret] + register.text + text[caret:])
                    self.cleared(composer)

    def test_empty_line_atomic(self) -> None:
        for text, caret in (("", 0), ("\nnext", 0), ("prev\n\nnext", 5), ("prev\n", 5)):
            for operator in "dcy":
                for descriptor in "ia":
                    with self.subTest(text=text, operator=operator, descriptor=descriptor):
                        composer = self.normal(text, caret)
                        composer._yank(0, len(text), False)
                        register = composer._register
                        typed(composer, operator + descriptor + "w")
                        self.assertEqual((composer.text, composer.caret, composer.normal, composer._register),
                                         (text, caret, operator != "c", register))
                        self.assertFalse(composer._undo)
                        self.cleared(composer)
                        if operator == "c":
                            typed(composer, "z")
                            self.assertEqual(composer.text, text[:caret] + "z" + text[caret:])
                            self.assertEqual(len(composer._undo), 1)
        for descriptor in "ia":
            self.deletion("prev\na b\nnext", 5, "d9999" + descriptor + "w", "prev\n\nnext", 5, "a b")
            self.deletion("prev\n \t\nnext", 6, "d9999" + descriptor + "w", "prev\n\nnext", 5, " \t")
        for unit in ("한", FAMILY, THUMBS_UP_TONED, FLAG_KR, Q_ACUTE):
            for descriptor in "ia":
                with self.subTest(unit=unit, descriptor=descriptor):
                    captured = unit if descriptor == "i" else unit + " "
                    self.deletion("a " + unit + " z", 2, "d" + descriptor + "w",
                                  "a  z" if descriptor == "i" else "a z", 2, captured)
        composer = Composer(vim=True)
        composer.handle(Paste(HANGUL_NFD))
        composer.normal, composer.caret = True, 0
        typed(composer, "diw")
        self.assertEqual((composer.text, composer._register.text), ("", HANGUL))
        for kind in ("chip", "image", "image_adjacent"):
            for operator in "dcy":
                for descriptor in "ia":
                    with self.subTest(kind=kind, operator=operator, descriptor=descriptor):
                        composer = Composer(vim=True)
                        if kind == "chip":
                            composer.handle(Paste("line with spaces\n" * 10))
                        else:
                            composer.insert_image("[Image #1]", "shot.png")
                            if kind == "image_adjacent":
                                composer.replace(1, len(composer.text), "tail")
                        composer.normal, composer.caret = True, 0
                        composer._undo.clear()  # fixture construction is not part of the object operation
                        before = composer._state()
                        units, bounds, _ = composer._atoms()
                        captured = composer.text.rstrip(" ") if kind == "image" and descriptor == "i" else composer.text
                        span = composer._text_object_span(descriptor, 1)
                        self.assertEqual((bounds[span[0]], bounds[span[1]]), (0, len(captured)))
                        if kind == "chip":
                            self.assertEqual(units, [composer.text])  # label spaces are inside one nonblank atom
                        elif kind == "image":
                            self.assertEqual(span, (0, 1 if descriptor == "i" else 2))
                        expected = (captured, dict(composer.pastes), dict(composer.images), False)
                        typed(composer, operator + descriptor + "w")
                        register = composer._register
                        self.assertEqual((register.text, register.pastes, register.images, register.linewise), expected)
                        self.cleared(composer)
                        if operator == "y":
                            self.assertEqual(composer._state(), before)
                            self.assertFalse(composer._undo)
                        else:
                            self.assertEqual((composer.pastes, composer.images), ({}, {}))
                            self.assertEqual(len(composer._undo), 1)
                            if operator == "c":
                                composer.handle(Key(ESCAPE))
                            after = composer._state()
                            typed(composer, "u")
                            self.assertEqual(composer._state(), before)
                            composer.handle(ctrl("r"))
                            self.assertEqual(composer._state(), after)
                        composer.normal = True
                        typed(composer, "P")
                        self.assertTrue(all(value in composer.pastes.values() for value in register.pastes.values()))
                        self.assertTrue(all(value in composer.images.values() for value in register.images.values()))
                        self.assertIn("line with spaces" if kind == "chip" else "[Image #1]", composer.expanded())
                        self.assertFalse(composer._register.linewise)

    def test_isolation_regressions(self) -> None:
        for options in ({"vim": True}, {"vim": False}, {"vim": True, "masked": True}):
            composer = Composer(**options)
            typed(composer, "diwdaw")
            self.assertEqual((composer.text, composer.caret, composer.normal), ("diwdaw", 6, False))
            self.cleared(composer)
        for command, caret in (("i", 1), ("a", 2)):
            composer = self.normal("abc", 1)
            typed(composer, command)
            self.assertEqual((composer.text, composer.caret, composer.normal), ("abc", caret, False))
            self.cleared(composer)
        for command, result, normal, captured, linewise in (
            ("dw", "two", True, "one ", False), ("cw", " two", False, "one", False),
            ("yw", "one two", True, "one ", False), ("dd", "", True, "one two", True),
            ("cc", "", False, "one two", True), ("yy", "one two", True, "one two", True),
        ):
            with self.subTest(command=command):
                composer = self.normal("one two")
                typed(composer, command)
                self.assertEqual((composer.text, composer.caret, composer.normal), (result, 0, normal))
                self.assertEqual((composer._register.text, composer._register.linewise), (captured, linewise))
                self.cleared(composer)
        for prefix in "gr":
            composer = self.normal("one two", 4)
            typed(composer, prefix)
            self.assertTrue(composer.pending)
            composer.handle(Key(ESCAPE))
            self.cleared(composer)
            self.assertEqual((composer.text, composer.caret, composer.normal), ("one two", 4, True))
        composer = self.normal("one two", 4)
        typed(composer, "gg")
        self.assertEqual(composer.caret, 0)
        typed(composer, "rZ")
        self.assertEqual((composer.text, composer.caret), ("Zne two", 0))
        composer = self.normal("one two", 4)
        composer.handle(Key(CHAR, "b", alt=True))
        self.assertEqual(composer.caret, 0)
        composer.handle(Key(CHAR, "f", alt=True))
        self.assertEqual(composer.caret, 3)
        for command in ("d ", "di ", "da "):
            composer = self.normal("one two")
            typed(composer, command)
            self.cleared(composer)
            self.assertFalse(composer.leader)
            self.assertEqual((composer.text, composer.caret, composer.normal), ("one two", 0, True))
        for follower in "diaw":
            composer = self.normal("one two")
            typed(composer, " " + follower)
            self.cleared(composer)
            self.assertEqual((composer.text, composer.caret, composer.normal), ("one two", 0, True))
        from test_tui_modes import make_app
        for text, busy in (("draft", False), ("", True), ("", False)):
            for operator in "dcy":
                for descriptor in "ia":
                    with self.subTest(app_text=text, busy=busy, operator=operator, descriptor=descriptor):
                        app, client = make_app(busy=busy)
                        app.composer.set_vim(True)
                        app.composer.replace(0, len(app.composer.text), text)
                        app.composer.normal = True
                        app.composer._clamp_normal()
                        before = app.composer._state()
                        for char in operator + descriptor:
                            app._on_input(Key(CHAR, char))
                        self.assertTrue(app.composer.pending)
                        app._on_input(Key(ESCAPE))
                        self.cleared(app.composer)
                        self.assertEqual(app.composer._state(), before)
                        self.assertIsNone(app.escape_armed)
                        self.assertEqual(client.calls, [])
                        app._on_input(Key(CHAR, "w"))
                        self.cleared(app.composer)
                        self.assertTrue(app.composer.normal)


class VimCharSearchTests(unittest.TestCase):
    """CS-1..CS-7: complete command outcomes and falsification cases from the accepted char-search plan."""

    def normal(self, text: str, caret: int = 0) -> Composer:
        composer = Composer(text=text, caret=caret, vim=True)
        composer.normal = True
        return composer

    def cleared(self, composer: Composer) -> None:
        self.assertFalse(composer.pending)
        self.assertEqual(
            (composer._operator, composer._prefix, composer._count, composer._op_count),
            ("", "", "", ""),
        )

    def snapshot(self, composer: Composer) -> tuple:
        reg = composer._register
        reg_tuple = (reg.text, reg.linewise, dict(reg.pastes), dict(reg.images)) if reg is not None else None
        return (
            composer.text,
            composer.caret,
            composer.normal,
            dict(composer.pastes),
            dict(composer.images),
            reg_tuple,
            list(composer._undo),
            list(composer._redo),
            getattr(composer, "_last_search", None),
        )

    def test_directions(self) -> None:
        # Four fresh xabcQabcx at caret 4: fx, Fx, tx, Tx land at 8, 0, 7, 1.
        # Text/register/undo unchanged, NORMAL, pending false.
        cases = (
            ("fx", 8, ("f", "x")),
            ("Fx", 0, ("F", "x")),
            ("tx", 7, ("t", "x")),
            ("Tx", 1, ("T", "x")),
        )
        for cmd, expected_caret, expected_last in cases:
            with self.subTest(cmd=cmd):
                composer = self.normal("xabcQabcx", 4)
                composer._yank(0, 1, linewise=False)
                expected_reg = composer._register
                undo_before = list(composer._undo)

                typed(composer, cmd)

                self.assertEqual((composer.text, composer.caret, composer.normal), ("xabcQabcx", expected_caret, True))
                self.assertEqual(composer._register, expected_reg)
                self.assertEqual(composer._undo, undo_before)
                self.assertEqual(getattr(composer, "_last_search", None), expected_last)
                self.cleared(composer)

    def test_atomic_targets(self) -> None:
        # ab cd at 2: f + space misses and stays 2
        composer = self.normal("ab cd", 2)
        composer.handle(Key(CHAR, "f"))
        self.assertTrue(composer.pending)
        composer.handle(Key(CHAR, " "))
        self.assertEqual((composer.text, composer.caret, composer.normal), ("ab cd", 2, True))
        self.cleared(composer)

        # fresh ab cd at 0: hits space at 2
        composer = self.normal("ab cd", 0)
        composer.handle(Key(CHAR, "f"))
        composer.handle(Key(CHAR, " "))
        self.assertEqual((composer.text, composer.caret, composer.normal), ("ab cd", 2, True))
        self.cleared(composer)

        # x1y1 at 0, f1 hits 1
        composer = self.normal("x1y1", 0)
        typed(composer, "f1")
        self.assertEqual((composer.text, composer.caret), ("x1y1", 1))
        self.cleared(composer)

        # a,b at 0, f, hits 1
        composer = self.normal("a,b", 0)
        typed(composer, "f,")
        self.assertEqual((composer.text, composer.caret), ("a,b", 1))
        self.cleared(composer)

        # Fresh aéz at 0 with one CHAR payload e\u0301 hits the whole atom at offset 1
        composed_text = "aéz"
        composer = self.normal(composed_text, 0)
        composer.handle(Key(CHAR, "f"))
        composer.handle(Key(CHAR, "e\u0301"))
        self.assertEqual((composer.text, composer.caret), (composed_text, 1))
        self.cleared(composer)

        # Fresh ae\u0301z at 0 with target é hits decomposed atom starting at offset 1, never its interior
        decomposed_text = "ae\u0301z"
        composer = self.normal(decomposed_text, 0)
        # Normal construction composes NFC; also exercise a decomposed stored atom.
        composer.text = decomposed_text
        composer.handle(Key(CHAR, "f"))
        composer.handle(Key(CHAR, "é"))
        self.assertEqual((composer.text, composer.caret), (decomposed_text, 1))
        self.cleared(composer)

        # Multi-codepoint printable graphemes accepted
        for unit in (HANGUL[0], FAMILY, THUMBS_UP_TONED, FLAG_KR, Q_ACUTE):
            with self.subTest(grapheme=unit):
                composer = self.normal("a" + unit + "z", 0)
                composer.handle(Key(CHAR, "f"))
                composer.handle(Key(CHAR, unit))
                self.assertEqual((composer.text, composer.caret), ("a" + unit + "z", 1))
                self.cleared(composer)

        # Invalid multi-grapheme/control/tab/NEWLINE/reserved tokens rejected
        invalid_payloads = [
            "", "\n", "\t", "\x00", "\x1b", "multi", "[Image #1]", IMAGE_LABEL, chr(0x100000),
        ]
        for payload in invalid_payloads:
            with self.subTest(invalid=payload):
                composer = self.normal("abc\ndef", 0)
                before = self.snapshot(composer)
                composer.handle(Key(CHAR, "f"))
                self.assertTrue(composer.pending)
                composer.handle(Key(CHAR, payload))
                after = self.snapshot(composer)
                self.assertEqual(after, before)
                self.cleared(composer)

        # Install real chip/image metadata with label-only x and no ordinary x:
        # fx/dfx miss without splitting or metadata loss
        # 1) Image token
        composer = Composer(vim=True)
        composer.insert_image("[Image #x]", "shot.png")
        composer.normal = True
        composer.caret = 0
        img_before = self.snapshot(composer)
        typed(composer, "fx")
        self.assertEqual(self.snapshot(composer), img_before)
        self.cleared(composer)

        typed(composer, "dfx")
        self.assertEqual(self.snapshot(composer), img_before)
        self.cleared(composer)

        # 2) Chip token
        composer = Composer(vim=True)
        composer.restore("[chip x]", [("[chip x]", "line with spaces\n" * 10)])
        composer.normal = True
        composer.caret = 0
        chip_before = self.snapshot(composer)
        typed(composer, "fx")
        self.assertEqual(self.snapshot(composer), chip_before)
        self.cleared(composer)

        typed(composer, "dfx")
        self.assertEqual(self.snapshot(composer), chip_before)
        self.cleared(composer)

        # Ordinary targets beyond whole tokens permit whole-token traversal
        composer = Composer(vim=True)
        composer.insert_image("[Image #1]", "shot.png")
        composer.replace(len(composer.text), len(composer.text), "tail_z")
        composer.normal = True
        composer.caret = 0
        target_idx = composer.text.index("z")
        images_copy = dict(composer.images)
        typed(composer, "fz")
        self.assertEqual((composer.caret, composer.normal), (target_idx, True))
        self.assertEqual(composer.images, images_copy)
        self.cleared(composer)

    def test_pending_literals(self) -> None:
        # a2b2c at 0: 2f holds pending at 0; final 2 lands 3
        composer = self.normal("a2b2c", 0)
        typed(composer, "2f")
        self.assertTrue(composer.pending)
        self.assertEqual(composer.caret, 0)
        self.assertEqual(composer._prefix, "f")
        self.assertEqual(composer._count, "2")
        composer.handle(Key(CHAR, "2"))
        self.assertEqual((composer.text, composer.caret, composer.normal), ("a2b2c", 3, True))
        self.cleared(composer)

        # For each target in d/i/a/g/r/f/;/comma/space, use fresh q+target+q at 0:
        # pending f consumes literal target at 1, never a fresh operator/count/INSERT/leader.
        targets = ("d", "i", "a", "g", "r", "f", ";", ",", " ")
        for target in targets:
            with self.subTest(target=target):
                text = "q" + target + "q"
                composer = self.normal(text, 0)
                composer.handle(Key(CHAR, "f"))
                self.assertTrue(composer.pending)
                self.assertEqual(composer._prefix, "f")
                composer.handle(Key(CHAR, target))
                self.assertEqual((composer.text, composer.caret, composer.normal), (text, 1, True))
                self.assertFalse(composer.leader)
                self.cleared(composer)
                self.assertEqual(getattr(composer, "_last_search", None), ("f", target))

    def test_shifted_targets(self) -> None:
        # A kitty or modifyOtherKeys terminal reports Shift beside the shifted character ("X", not "x"): the
        # target is that character, so fX, f( and t: search as they do on a legacy terminal.
        for kind, target, caret in (("f", "X", 4), ("f", "(", 1), ("t", ":", 2), ("F", "X", 4)):
            with self.subTest(kind=kind, target=target):
                composer = self.normal("a(b:XQ:X", 5 if kind == "F" else 0)
                composer.handle(Key(CHAR, kind, reported_shift=kind.isupper()))
                composer.handle(Key(CHAR, target, reported_shift=True))
                self.assertEqual((composer.caret, composer.normal), (caret, True))
                self.assertEqual(composer._last_search, (kind, target))
                self.cleared(composer)

    def test_cancel(self) -> None:
        # Cover all f/F/t/T with standalone and d/c/y pending counts, including 2d3f.
        # Escape, BACKSPACE, DELETE, Enter, arrows, modified CHAR and invalid CHAR cancel
        # and consume without a search effect.
        cancel_events = (
            Key(ESCAPE),
            Key(BACKSPACE),
            Key(DELETE),
            Key(ENTER),
            Key(LEFT),
            Key(RIGHT),
            Key(UP),
            Key(DOWN),
            Key(CHAR, "a", ctrl=True),
            Key(CHAR, "a", alt=True),
            Key(CHAR, "\x00"),
            Key(CHAR, "multi"),
        )
        for kind in ("f", "F", "t", "T"):
            for event in cancel_events:
                with self.subTest(kind=kind, event=event, mode="standalone"):
                    composer = self.normal("abcbdbebfbgb", 4)
                    before = self.snapshot(composer)
                    typed(composer, kind)
                    self.assertTrue(composer.pending)
                    composer.handle(event)
                    self.assertEqual(self.snapshot(composer), before)
                    self.cleared(composer)

            for op in "dcy":
                for event in cancel_events:
                    with self.subTest(kind=kind, op=op, event=event, mode="counted"):
                        composer = self.normal("abcbdbebfbgb", 4)
                        typed(composer, "Fb")
                        before = self.snapshot(composer)
                        typed(composer, "2" + op + "3" + kind)
                        self.assertTrue(composer.pending)
                        composer.handle(event)
                        self.assertEqual(self.snapshot(composer), before)
                        self.cleared(composer)

        for event in cancel_events:
            with self.subTest(mode="2d3f_cancel", event=event):
                composer = self.normal("abcbdbebfbgb", 4)
                before = self.snapshot(composer)
                typed(composer, "2d3f")
                self.assertTrue(composer.pending)
                composer.handle(event)
                self.assertEqual(self.snapshot(composer), before)
                self.cleared(composer)

        # On fresh abcbdbebfbgb at 0, cancel 2d3f, then:
        # 1) fb must land 1 with no deletion
        composer = self.normal("abcbdbebfbgb", 0)
        typed(composer, "2d3f")
        self.assertTrue(composer.pending)
        composer.handle(Key(ESCAPE))
        self.cleared(composer)
        typed(composer, "fb")
        self.assertEqual((composer.text, composer.caret, composer.normal), ("abcbdbebfbgb", 1, True))
        self.cleared(composer)

        # 2) x must delete rather than leak an operator
        composer = self.normal("abcbdbebfbgb", 0)
        typed(composer, "2d3f")
        composer.handle(Key(ESCAPE))
        self.cleared(composer)
        typed(composer, "x")
        self.assertEqual((composer.text, composer.caret, composer.normal), ("bcbdbebfbgb", 0, True))
        self.cleared(composer)

        # 3) i must enter INSERT
        composer = self.normal("abcbdbebfbgb", 0)
        typed(composer, "2d3f")
        composer.handle(Key(ESCAPE))
        self.cleared(composer)
        typed(composer, "i")
        self.assertEqual((composer.text, composer.caret, composer.normal), ("abcbdbebfbgb", 0, False))
        self.cleared(composer)

        # Pending Paste inserts via the existing path after clearing pending
        composer = self.normal("one two", 4)
        control = self.normal("one two", 4)
        typed(composer, "2d3f")
        self.assertTrue(composer.pending)
        composer.handle(Paste("!"))
        control.handle(Paste("!"))
        self.cleared(composer)
        self.assertEqual(self.snapshot(composer), self.snapshot(control))

        # Shared Ctrl undo/redo uses a preseeded real undo/redo stack and has only its normal effect
        for action in ("undo", "redo", "vim_redo"):
            with self.subTest(action=action):
                composer = self.normal("initial text", 0)
                control = self.normal("initial text", 0)
                for c in (composer, control):
                    typed(c, "x")
                    if action in ("redo", "vim_redo"):
                        c.handle(ctrl("_"))
                typed(composer, "2d3f")
                self.assertTrue(composer.pending)
                ev = {"undo": ctrl("_"), "redo": ctrl("y"), "vim_redo": ctrl("r")}[action]
                composer.handle(ev)
                control.handle(ev)
                self.cleared(composer)
                self.assertEqual(self.snapshot(composer), self.snapshot(control))

    def test_counts(self) -> None:
        # Fresh abcbdbebfbgb at 0, b indices 1, 3, 5, 7, 9, 11
        # 2fb lands 3
        composer = self.normal("abcbdbebfbgb", 0)
        typed(composer, "2fb")
        self.assertEqual((composer.text, composer.caret, composer.normal), ("abcbdbebfbgb", 3, True))
        self.cleared(composer)

        # d2fb deletes [0, 4) = abcb, leaving dbebfbgb
        composer = self.normal("abcbdbebfbgb", 0)
        typed(composer, "d2fb")
        self.assertEqual((composer.text, composer.caret, composer.normal), ("dbebfbgb", 0, True))
        self.cleared(composer)

        # 2dfb deletes [0, 4) = abcb, leaving dbebfbgb
        composer = self.normal("abcbdbebfbgb", 0)
        typed(composer, "2dfb")
        self.assertEqual((composer.text, composer.caret, composer.normal), ("dbebfbgb", 0, True))
        self.cleared(composer)

        # 2d3fb deletes [0, 12) to empty with one undo step
        composer = self.normal("abcbdbebfbgb", 0)
        typed(composer, "2d3fb")
        self.assertEqual((composer.text, composer.caret, composer.normal), ("", 0, True))
        self.assertEqual(len(composer._undo), 1)
        self.cleared(composer)

        # Cap-discriminating line a + b repeated 9999 times at 0 (total length 10000):
        # 99999fb lands 9999 (uncapped 99999 would miss)
        long_text = "a" + "b" * 9999
        composer = self.normal(long_text, 0)
        typed(composer, "99999fb")
        self.assertEqual(composer.caret, 9999)
        self.cleared(composer)

        # fresh 9999d9999fb deletes all 10000 atoms (uncapped product would miss)
        composer = self.normal(long_text, 0)
        typed(composer, "9999d9999fb")
        self.assertEqual((composer.text, composer.caret), ("", 0))
        self.cleared(composer)

        # One fewer b makes the capped request miss atomically
        short_text = "a" + "b" * 9998
        composer = self.normal(short_text, 0)
        typed(composer, "99999fb")
        self.assertEqual((composer.text, composer.caret), (short_text, 0))
        self.cleared(composer)

        # Backward and till counts
        # On abcbdbebfbgb at 11:
        # 2Fb lands at 7
        composer = self.normal("abcbdbebfbgb", 11)
        typed(composer, "2Fb")
        self.assertEqual(composer.caret, 7)
        self.cleared(composer)

        # 2Tb lands at 8
        composer = self.normal("abcbdbebfbgb", 11)
        typed(composer, "2Tb")
        self.assertEqual(composer.caret, 8)
        self.cleared(composer)

        # 2tb from 0 lands at 2
        composer = self.normal("abcbdbebfbgb", 0)
        typed(composer, "2tb")
        self.assertEqual(composer.caret, 2)
        self.cleared(composer)

        # Literal 0 target
        composer = self.normal("a0b0c", 0)
        typed(composer, "f0")
        self.assertEqual(composer.caret, 1)
        self.cleared(composer)

        composer = self.normal("a0b0c", 0)
        typed(composer, "2f0")
        self.assertEqual(composer.caret, 3)
        self.cleared(composer)

        # Insufficient matches do nothing
        composer = self.normal("abcbdbebfbgb", 0)
        before = self.snapshot(composer)
        typed(composer, "7fb")
        self.assertEqual(self.snapshot(composer), before)
        self.cleared(composer)

        typed(composer, "d7fb")
        self.assertEqual(self.snapshot(composer), before)
        self.cleared(composer)

    def test_miss(self) -> None:
        # Fresh abc\nb at 0: fz, 2fb, dfz, cfz, yfz are atomic misses; c stays NORMAL.
        # later-line b cannot satisfy 2fb.
        miss_cmds = ("fz", "2fb", "dfz", "cfz", "yfz")
        for cmd in miss_cmds:
            with self.subTest(cmd=cmd):
                composer = self.normal("abc\nb", 0)
                before = self.snapshot(composer)
                typed(composer, cmd)
                self.assertEqual(self.snapshot(composer), before)
                self.assertTrue(composer.normal)
                self.cleared(composer)

        # Empty buffer/line also miss
        for text in ("", "\n", "line1\n\nline3"):
            caret = 6 if text == "line1\n\nline3" else 0
            for cmd in ("fa", "dfa", "cfa", "yfa"):
                with self.subTest(text=text, cmd=cmd):
                    composer = self.normal(text, caret)
                    before = self.snapshot(composer)
                    typed(composer, cmd)
                    self.assertEqual(self.snapshot(composer), before)
                    self.assertTrue(composer.normal)
                    self.cleared(composer)

        # Hard line boundary & wrap width
        # abc\ndef at 0: fe cannot cross line
        composer = self.normal("abc\ndef", 0)
        typed(composer, "fe")
        self.assertEqual(composer.caret, 0)
        self.cleared(composer)

        # abc\ndef at 5: Fa cannot cross back
        composer = self.normal("abc\ndef", 5)
        typed(composer, "Fa")
        self.assertEqual(composer.caret, 5)
        self.cleared(composer)

        # fa cannot wrap across newline
        composer = self.normal("abc\ndefa", 0)
        typed(composer, "fa")
        self.assertEqual(composer.caret, 0)
        self.cleared(composer)

        # Same logical line rendered at different widths: wrap width must not alter result
        for width in (4, 10, 80):
            with self.subTest(width=width):
                composer = self.normal("abcdef ghijkl", 0)
                composer.render(width, max_rows=5)
                typed(composer, "fk")
                self.assertEqual(composer.caret, 11)
                self.cleared(composer)

        # Search target exactly at buffer edge must succeed without crossing
        composer = self.normal("abc", 0)
        typed(composer, "fc")
        self.assertEqual(composer.caret, 2)
        self.cleared(composer)

        composer = self.normal("abc", 2)
        typed(composer, "Fa")
        self.assertEqual(composer.caret, 0)
        self.cleared(composer)

        # For memory retention, fresh xabcxabcx at 0: fx reaches 4;
        # failed fz/cfz or cancelled pending search preserves f/x; following ; reaches 8.
        composer = self.normal("xabcxabcx", 0)
        typed(composer, "fx")
        self.assertEqual(composer.caret, 4)
        self.assertEqual(getattr(composer, "_last_search", None), ("f", "x"))

        # failed fz
        typed(composer, "fz")
        self.assertEqual(composer.caret, 4)
        self.assertEqual(getattr(composer, "_last_search", None), ("f", "x"))
        self.cleared(composer)

        typed(composer, ";")
        self.assertEqual(composer.caret, 8)
        self.cleared(composer)

        # repeat with cfz
        composer = self.normal("xabcxabcx", 0)
        typed(composer, "fx")
        self.assertEqual(composer.caret, 4)
        typed(composer, "cfz")
        self.assertEqual(composer.caret, 4)
        self.assertTrue(composer.normal)
        self.assertEqual(getattr(composer, "_last_search", None), ("f", "x"))
        self.cleared(composer)
        typed(composer, ";")
        self.assertEqual(composer.caret, 8)
        self.cleared(composer)

    def test_operator_spans(self) -> None:
        # All twelve d/c/y x fx/tx/Fx/Tx subtests use fresh xabcQabcx, caret 4
        table = {
            "fx": {"selected": "Qabcx", "d_text": "xabc", "d_caret": 3, "c_caret": 4, "y_caret": 4},
            "tx": {"selected": "Qabc", "d_text": "xabcx", "d_caret": 4, "c_caret": 4, "y_caret": 4},
            "Fx": {"selected": "xabc", "d_text": "Qabcx", "d_caret": 0, "c_caret": 0, "y_caret": 0},
            "Tx": {"selected": "abc", "d_text": "xQabcx", "d_caret": 1, "c_caret": 1, "y_caret": 1},
        }
        for motion, exp in table.items():
            for op in ("d", "c", "y"):
                with self.subTest(op=op, motion=motion):
                    composer = self.normal("xabcQabcx", 4)
                    typed(composer, op + motion)
                    if op == "d":
                        self.assertEqual((composer.text, composer.caret, composer.normal), (exp["d_text"], exp["d_caret"], True))
                    elif op == "c":
                        self.assertEqual((composer.text, composer.caret, composer.normal), (exp["d_text"], exp["c_caret"], False))
                    elif op == "y":
                        self.assertEqual((composer.text, composer.caret, composer.normal), ("xabcQabcx", exp["y_caret"], True))
                    self.assertIsNotNone(composer._register)
                    self.assertEqual((composer._register.text, composer._register.linewise), (exp["selected"], False))
                    self.cleared(composer)

    def test_adjacent(self) -> None:
        # xQ at 1 has backward x match m=0 and T span [1, 1)
        for op in ("d", "y"):
            with self.subTest(op=op):
                composer = self.normal("xQ", 1)
                composer._yank(0, 2, linewise=False)
                typed(composer, "x")
                composer.handle(ctrl("_"))
                expected_reg = composer._register
                undo_before = list(composer._undo)
                redo_before = list(composer._redo)

                typed(composer, op + "Tx")

                self.assertEqual((composer.text, composer.caret, composer.normal), ("xQ", 1, True))
                self.assertEqual(composer._register, expected_reg)
                self.assertEqual(list(composer._undo), undo_before)
                self.assertEqual(list(composer._redo), redo_before)
                self.assertEqual(getattr(composer, "_last_search", None), ("T", "x"))
                self.cleared(composer)

        # cTx enters INSERT at 1 with unchanged undo/redo until typing
        composer = self.normal("xQ", 1)
        typed(composer, "x")
        composer.handle(ctrl("_"))
        undo_before = list(composer._undo)
        redo_before = list(composer._redo)

        typed(composer, "cTx")
        self.assertEqual((composer.text, composer.caret, composer.normal), ("xQ", 1, False))
        self.assertEqual(list(composer._undo), undo_before)
        self.assertEqual(list(composer._redo), redo_before)
        self.assertEqual(getattr(composer, "_last_search", None), ("T", "x"))
        self.cleared(composer)

        typed(composer, "Z")
        composer.handle(Key(ESCAPE))
        typed(composer, "u")
        self.assertEqual(composer.text, "xQ")

        # Directly assert successful remembered tuple, or fresh xQxQ at 3, Tx stays 3 and subsequent ; reaches 1
        composer = self.normal("xQxQ", 3)
        typed(composer, "Tx")
        self.assertEqual(composer.caret, 3)
        self.assertEqual(getattr(composer, "_last_search", None), ("T", "x"))
        self.cleared(composer)
        typed(composer, ";")
        self.assertEqual(composer.caret, 1)
        self.cleared(composer)

        # Qx at 0: dtx spans [0, 1), leaves x at 0
        composer = self.normal("Qx", 0)
        typed(composer, "dtx")
        self.assertEqual((composer.text, composer.caret, composer.normal), ("x", 0, True))
        self.cleared(composer)

        # Separate cfz stays NORMAL
        composer = self.normal("xQ", 1)
        typed(composer, "cfz")
        self.assertEqual((composer.text, composer.caret, composer.normal), ("xQ", 1, True))
        self.cleared(composer)

    def test_effects(self) -> None:
        for operator in ("", "d", "c", "y"):
            with self.subTest(operator=operator):
                composer = Composer(vim=True)
                typed(composer, "head ")
                composer.insert_image("[Image #1]", "shot.png")
                composer.handle(Paste("chip content\n" * 10))
                typed(composer, " tail_z")
                composer.normal = True
                composer.caret = 0
                composer._undo.clear()
                composer._redo.clear()
                before = composer._state()
                typed(composer, operator + "fz")
                self.cleared(composer)
                self.assertEqual(composer._last_search, ("f", "z"))
                self.assertEqual(len(composer._undo), int(operator in ("d", "c")))
                if not operator:
                    self.assertEqual((composer.text, composer.pastes, composer.images),
                                     (before[0], before[2], before[3]))
                    continue
                register = composer._register
                self.assertEqual(register.text, before[0])
                self.assertEqual((register.pastes, register.images, register.linewise),
                                 (before[2], before[3], False))
                if operator == "y":
                    self.assertEqual(composer._state(), before)
                    typed(composer, "x")  # clear the original h, then put the full captured metadata
                    for put in ("P", "p"):
                        typed(composer, put)
                        self.assertTrue(all(value in composer.images.values() for value in register.images.values()))
                        self.assertTrue(all(value in composer.pastes.values() for value in register.pastes.values()))
                        self.assertIn("chip content", composer.expanded())
                    continue
                self.assertEqual((composer.text, composer.pastes, composer.images), ("", {}, {}))
                if operator == "c":
                    typed(composer, "REPLACED")
                    composer.handle(Key(ESCAPE))
                    self.assertEqual(len(composer._undo), 1)
                after = composer._state()
                typed(composer, "u")
                self.assertEqual(composer._state(), before)
                composer.handle(ctrl("r"))
                self.assertEqual(composer._state(), after)
                self.assertEqual(composer._last_search, ("f", "z"))
                typed(composer, "P")
                self.assertEqual(composer._register, register)
                self.assertEqual(composer.pastes, register.pastes)
                self.assertEqual(list(composer.images.values()), list(register.images.values()))

    def test_repeat(self) -> None:
        # xabcxabcxabcx at 0 has x indices 0, 4, 8, 12.
        # fx -> 4; ; -> 8; comma -> 4; ; -> 8.
        composer = self.normal("xabcxabcxabcx", 0)
        typed(composer, "fx")
        self.assertEqual(composer.caret, 4)
        typed(composer, ";")
        self.assertEqual(composer.caret, 8)
        typed(composer, ",")
        self.assertEqual(composer.caret, 4)
        typed(composer, ";")
        self.assertEqual(composer.caret, 8)
        self.cleared(composer)

        # Fresh fx state at 4 then d; selects [4,9)=xabcx, leaves xabcabcx, caret 4
        composer = self.normal("xabcxabcxabcx", 0)
        typed(composer, "fx")
        self.assertEqual(composer.caret, 4)
        typed(composer, "d;")
        self.assertEqual((composer.text, composer.caret, composer.normal), ("xabcabcx", 4, True))
        self.assertEqual(composer._register.text, "xabcx")
        self.cleared(composer)

        # Fresh fx; state at 8 then d-comma selects [4,8)=xabc, leaves xabcxabcx, caret 4;
        # following ; reaches 8 with original f/x memory.
        composer = self.normal("xabcxabcxabcx", 0)
        typed(composer, "fx;")
        self.assertEqual(composer.caret, 8)
        typed(composer, "d,")
        self.assertEqual((composer.text, composer.caret, composer.normal), ("xabcxabcx", 4, True))
        self.assertEqual(composer._register.text, "xabc")
        self.assertEqual(getattr(composer, "_last_search", None), ("f", "x"))
        self.cleared(composer)
        typed(composer, ";")
        self.assertEqual(composer.caret, 8)
        self.cleared(composer)

        # Mirror F direction
        composer = self.normal("xabcxabcxabcx", 12)
        typed(composer, "Fx")
        self.assertEqual(composer.caret, 8)
        typed(composer, ";")
        self.assertEqual(composer.caret, 4)
        typed(composer, ",")
        self.assertEqual(composer.caret, 8)
        typed(composer, ";")
        self.assertEqual(composer.caret, 4)
        self.cleared(composer)

        # Mirror t and T direction pairs
        composer = self.normal("xabcxabcxabcx", 0)
        typed(composer, "tx")
        self.assertEqual(composer.caret, 3)
        typed(composer, ";")
        self.assertEqual(composer.caret, 7)
        typed(composer, ",")
        self.assertEqual(composer.caret, 5)
        self.cleared(composer)

        composer = self.normal("xabcxabcxabcx", 12)
        typed(composer, "Tx")
        self.assertEqual(composer.caret, 9)
        typed(composer, ";")
        self.assertEqual(composer.caret, 5)
        typed(composer, ",")
        self.assertEqual(composer.caret, 7)
        self.cleared(composer)

        # d/c/y repeats consume normal product/cap
        composer = self.normal("abcbdbebfbgb", 0)
        typed(composer, "fb")
        self.assertEqual(composer.caret, 1)
        typed(composer, "2d2;")
        self.assertEqual((composer.text, composer.caret), ("agb", 1))
        self.cleared(composer)

        for operator in "cy":
            with self.subTest(counted_repeat=operator):
                composer = self.normal("abcbdbebfbgb", 0)
                typed(composer, "fb2" + operator + "2;")
                self.assertEqual(composer._register.text, "bcbdbebfb")
                self.assertEqual((composer.text, composer.caret, composer.normal),
                                 ("agb" if operator == "c" else "abcbdbebfbgb", 1, operator == "y"))
                self.cleared(composer)
        for command in ("99999;", "9999d9999;", "9999c9999;", "9999y9999;"):
            with self.subTest(capped_repeat=command):
                composer = self.normal("a" + "b" * 10000, 0)
                typed(composer, "fb" + command)
                self.assertEqual(composer._last_search, ("f", "b"))
                if command == "99999;":
                    self.assertEqual(composer.caret, 10000)
                else:
                    self.assertEqual(len(composer._register.text), 10000)
                    self.assertEqual(composer.text, "a" + "b" * 10000 if "y" in command else "a")
                self.cleared(composer)

        # Move organically before a repeat and search the current text/line, not cached offsets
        composer = self.normal("xabcxabcxabcx", 0)
        typed(composer, "fx")
        self.assertEqual(composer.caret, 4)
        typed(composer, "ll")
        self.assertEqual(composer.caret, 6)
        typed(composer, ";")
        self.assertEqual(composer.caret, 8)
        self.cleared(composer)

    def test_memory(self) -> None:
        # Establish successful search
        composer = self.normal("xabcxabcx", 0)
        typed(composer, "fx")
        self.assertEqual(composer.caret, 4)
        self.assertEqual(getattr(composer, "_last_search", None), ("f", "x"))

        # Failure/cancel retain last success
        typed(composer, "fz")
        self.assertEqual(getattr(composer, "_last_search", None), ("f", "x"))
        self.cleared(composer)

        typed(composer, "2df")
        composer.handle(Key(ESCAPE))
        self.assertEqual(getattr(composer, "_last_search", None), ("f", "x"))
        self.cleared(composer)

        # INSERT/Escape, unrelated motion/edit, history load and undo/redo preserve memory
        typed(composer, "i")
        composer.handle(Key(ESCAPE))
        self.assertEqual(getattr(composer, "_last_search", None), ("f", "x"))

        typed(composer, "h")
        self.assertEqual(getattr(composer, "_last_search", None), ("f", "x"))

        typed(composer, "rZ")
        self.assertEqual(getattr(composer, "_last_search", None), ("f", "x"))

        typed(composer, "u")
        self.assertEqual(getattr(composer, "_last_search", None), ("f", "x"))

        composer.handle(ctrl("r"))
        self.assertEqual(getattr(composer, "_last_search", None), ("f", "x"))

        # Real history browsing changes text but not search memory; repeats use that text.
        composer = self.normal("xabcxabcx", 0)
        typed(composer, "fx")
        composer.history = ["x---x---x"]
        composer.handle(Key(UP))
        self.assertEqual(composer.text, "x---x---x")
        self.assertEqual(composer._last_search, ("f", "x"))
        typed(composer, "0;")
        self.assertEqual(composer.caret, 4)

        # Count not retained
        composer = self.normal("abcbdbebfbgb", 0)
        typed(composer, "2fb")
        self.assertEqual(composer.caret, 3)
        self.assertEqual(getattr(composer, "_last_search", None), ("f", "b"))
        typed(composer, ";")
        self.assertEqual(composer.caret, 5)
        self.cleared(composer)

        # Independent/cleared instances no-op and drop pending counts/operators
        fresh = self.normal("abcbdbebfbgb", 0)
        self.assertIsNone(getattr(fresh, "_last_search", None))
        for cmd in (";", ",", "2;", "d;", "c,", "2d3;"):
            with self.subTest(fresh_cmd=cmd):
                c = self.normal("abcbdbebfbgb", 0)
                before = self.snapshot(c)
                typed(c, cmd)
                self.assertEqual(self.snapshot(c), before)
                self.cleared(c)

        # submit/set_vim/clear erase memory
        composer = self.normal("xabcx", 0)
        typed(composer, "fx")
        self.assertIsNotNone(getattr(composer, "_last_search", None))
        composer.set_vim(False)
        self.assertIsNone(getattr(composer, "_last_search", None))

        composer.set_vim(True)
        composer.normal = True
        composer.caret = 0
        typed(composer, "fx")
        self.assertIsNotNone(getattr(composer, "_last_search", None))
        composer.set_vim(True)
        self.assertIsNone(getattr(composer, "_last_search", None))

        composer.set_vim(True)
        composer.normal = True
        composer.caret = 0
        typed(composer, "fx")
        self.assertIsNotNone(getattr(composer, "_last_search", None))
        composer._clear()
        self.assertIsNone(getattr(composer, "_last_search", None))

        composer = self.normal("xabcx", 0)
        typed(composer, "fx")
        self.assertIsNotNone(getattr(composer, "_last_search", None))
        composer.handle(Key(ENTER))
        self.assertIsNone(getattr(composer, "_last_search", None))

        # Memory is per-instance and excluded from undo snapshots
        c1 = self.normal("xabcx", 0)
        c2 = self.normal("xabcx", 0)
        typed(c1, "fx")
        self.assertEqual(getattr(c1, "_last_search", None), ("f", "x"))
        self.assertIsNone(getattr(c2, "_last_search", None))

        c1._undo.clear()
        typed(c1, "x")
        typed(c1, "u")
        self.assertEqual(getattr(c1, "_last_search", None), ("f", "x"))

    def test_till_repeat(self) -> None:
        # Forward aXbXcX at 0:
        # explicit tX stays 0; ; reaches 2, next ; reaches 4, comma reaches 2.
        composer = self.normal("aXbXcX", 0)
        typed(composer, "tX")
        self.assertEqual(composer.caret, 0)
        self.assertEqual(getattr(composer, "_last_search", None), ("t", "X"))
        typed(composer, ";")
        self.assertEqual(composer.caret, 2)
        typed(composer, ";")
        self.assertEqual(composer.caret, 4)
        typed(composer, ",")
        self.assertEqual(composer.caret, 2)
        self.cleared(composer)

        # Fresh explicit-tX state: 2; reaches 4
        composer = self.normal("aXbXcX", 0)
        typed(composer, "tX")
        self.assertEqual(composer.caret, 0)
        typed(composer, "2;")
        self.assertEqual(composer.caret, 4)
        self.cleared(composer)

        # d2; uses final match m=5, selects [0, 5) = aXbXc, leaves X at 0, one span/undo step
        composer = self.normal("aXbXcX", 0)
        typed(composer, "tX")
        self.assertEqual(composer.caret, 0)
        typed(composer, "d2;")
        self.assertEqual((composer.text, composer.caret, composer.normal), ("X", 0, True))
        self.assertEqual(len(composer._undo), 1)
        self.cleared(composer)

        # Backward mirror XcXbXa at 5:
        # explicit TX lands 5; ; reaches 3, next ; reaches 1, comma reaches 3.
        composer = self.normal("XcXbXa", 5)
        typed(composer, "TX")
        self.assertEqual(composer.caret, 5)
        self.assertEqual(getattr(composer, "_last_search", None), ("T", "X"))
        typed(composer, ";")
        self.assertEqual(composer.caret, 3)
        typed(composer, ";")
        self.assertEqual(composer.caret, 1)
        typed(composer, ",")
        self.assertEqual(composer.caret, 3)
        self.cleared(composer)

        # Fresh explicit-TX state: 2; reaches 1
        composer = self.normal("XcXbXa", 5)
        typed(composer, "TX")
        self.assertEqual(composer.caret, 5)
        typed(composer, "2;")
        self.assertEqual(composer.caret, 1)
        self.cleared(composer)

        # A further ; from the exhausted progression misses without moving
        composer = self.normal("aXbXcX", 0)
        typed(composer, "tX;;")
        self.assertEqual(composer.caret, 4)
        typed(composer, ";")
        self.assertEqual(composer.caret, 4)
        self.cleared(composer)

        composer = self.normal("XcXbXa", 5)
        typed(composer, "TX;;")
        self.assertEqual(composer.caret, 1)
        typed(composer, ";")
        self.assertEqual(composer.caret, 1)
        self.cleared(composer)

    def test_repeat_miss(self) -> None:
        # Fresh aXbXcX at 0 with successful tX memory:
        # 3; and c3; each fail atomically at original caret 0, with no partial edit/INSERT/register/undo change and pending false;
        # next ; reaches 2, proving memory retention.
        composer = self.normal("aXbXcX", 0)
        typed(composer, "tX")
        self.assertEqual(composer.caret, 0)
        before = self.snapshot(composer)

        typed(composer, "3;")
        self.assertEqual(self.snapshot(composer), before)
        self.assertTrue(composer.normal)
        self.cleared(composer)

        typed(composer, ";")
        self.assertEqual(composer.caret, 2)
        self.cleared(composer)

        # c3; fails atomically
        composer = self.normal("aXbXcX", 0)
        typed(composer, "tX")
        self.assertEqual(composer.caret, 0)
        before = self.snapshot(composer)

        typed(composer, "c3;")
        self.assertEqual(self.snapshot(composer), before)
        self.assertTrue(composer.normal)
        self.cleared(composer)

        typed(composer, ";")
        self.assertEqual(composer.caret, 2)
        self.cleared(composer)

        # Fresh aX\nbX at 0 after tX: ; cannot cross NEWLINE and stays 0
        composer = self.normal("aX\nbX", 0)
        typed(composer, "tX")
        self.assertEqual(composer.caret, 0)
        typed(composer, ";")
        self.assertEqual(composer.caret, 0)
        self.cleared(composer)

        # Mirror counted failure on XcXbXa at 5 after TX: 3; stays 5
        composer = self.normal("XcXbXa", 5)
        typed(composer, "TX")
        self.assertEqual(composer.caret, 5)
        before = self.snapshot(composer)

        typed(composer, "3;")
        self.assertEqual(self.snapshot(composer), before)
        self.assertTrue(composer.normal)
        self.cleared(composer)

        typed(composer, "c3;")
        self.assertEqual(self.snapshot(composer), before)
        self.assertTrue(composer.normal)
        self.cleared(composer)

    def test_isolation(self) -> None:
        # Discriminating inherited gate probes:
        # Fresh ax at 0, single f must insert fax at caret 1 with no pending for:
        # (vim=True, masked=False, normal=False)
        c1 = Composer(text="ax", caret=0, vim=True, masked=False)
        c1.normal = False
        c1.handle(Key(CHAR, "f"))
        self.assertEqual((c1.text, c1.caret, c1.normal), ("fax", 1, False))
        self.cleared(c1)

        # (vim=False, masked=False, normal=True)
        c2 = Composer(text="ax", caret=0, vim=False, masked=False)
        c2.normal = True
        c2.handle(Key(CHAR, "f"))
        self.assertEqual((c2.text, c2.caret), ("fax", 1))
        self.cleared(c2)

        # (vim=True, masked=True, normal=True)
        c3 = Composer(text="ax", caret=0, vim=True, masked=True)
        c3.normal = True
        c3.handle(Key(CHAR, "f"))
        self.assertEqual((c3.text, c3.caret), ("fax", 1))
        self.cleared(c3)

        # Also type each literal f/F/t/T/;/comma in ordinary INSERT/non-Vim/masked input
        chars = ("f", "F", "t", "T", ";", ",")
        for ch in chars:
            with self.subTest(ch=ch, mode="insert"):
                c = Composer(text="x", caret=0, vim=True)
                c.normal = False
                c.handle(Key(CHAR, ch))
                self.assertEqual((c.text, c.caret, c.normal), (ch + "x", 1, False))
                self.cleared(c)

            with self.subTest(ch=ch, mode="non-vim"):
                c = Composer(text="x", caret=0, vim=False)
                c.handle(Key(CHAR, ch))
                self.assertEqual((c.text, c.caret), (ch + "x", 1))
                self.cleared(c)

            with self.subTest(ch=ch, mode="masked"):
                c = Composer(text="x", caret=0, vim=True, masked=True)
                c.normal = True
                c.handle(Key(CHAR, ch))
                self.assertEqual((c.text, c.caret), (ch + "x", 1))
                self.cleared(c)

        # Pending f+space searches rather than arms leader
        composer = self.normal("a b c", 0)
        composer.handle(Key(CHAR, "f"))
        self.assertTrue(composer.pending)
        composer.handle(Key(CHAR, " "))
        self.assertFalse(composer.leader)
        self.assertFalse(composer.pending)
        self.assertEqual(composer.caret, 1)
        self.cleared(composer)

        # Search does not steal word-object, replace or g-prefix followers
        for cmd, expected_caret in (("i", 1), ("a", 2)):
            composer = self.normal("abc", 1)
            typed(composer, cmd)
            self.assertEqual((composer.text, composer.caret, composer.normal), ("abc", expected_caret, False))
            self.cleared(composer)

        composer = self.normal("one two", 4)
        typed(composer, "rZ")
        self.assertEqual((composer.text, composer.caret), ("one Zwo", 4))
        self.cleared(composer)

        composer = self.normal("one two", 4)
        typed(composer, "gg")
        self.assertEqual(composer.caret, 0)
        self.cleared(composer)

        # Word objects iw/aw
        composer = self.normal("alpha beta gamma", 8)
        typed(composer, "diw")
        self.assertEqual(composer.text, "alpha  gamma")
        self.cleared(composer)

        composer = self.normal("alpha beta gamma", 8)
        typed(composer, "daw")
        self.assertEqual(composer.text, "alpha gamma")
        self.cleared(composer)

        # Leader followers
        composer = self.normal("one two", 0)
        typed(composer, " ")
        self.assertTrue(composer.leader)
        composer.handle(Key(ESCAPE))
        self.assertFalse(composer.leader)
        self.cleared(composer)

        # Legacy/modern Alt motions
        composer = self.normal("one two", 4)
        composer.handle(Key(CHAR, "b", alt=True))
        self.assertEqual(composer.caret, 0)
        composer.handle(Key(CHAR, "f", alt=True))
        self.assertEqual(composer.caret, 3)

        # Undo / redo
        composer = self.normal("abc", 0)
        typed(composer, "x")
        self.assertEqual(composer.text, "bc")
        typed(composer, "u")
        self.assertEqual(composer.text, "abc")
        composer.handle(ctrl("r"))
        self.assertEqual(composer.text, "bc")


class DeleteTests(unittest.TestCase):
    def test_backspace_removes_one_cluster(self) -> None:
        for unit in ("x", "한", FAMILY, THUMBS_UP_TONED, FLAG_KR, Q_ACUTE):
            with self.subTest(unit=unit):
                composer = at("a" + unit, len("a" + unit))
                press(composer, Key(BACKSPACE))
                self.assertEqual((composer.text, composer.caret), ("a", 1))

    def test_backspace_after_a_decomposed_paste_removes_a_whole_syllable(self) -> None:
        composer = Composer()
        composer.handle(Paste(HANGUL_NFD))
        press(composer, Key(BACKSPACE))
        self.assertEqual(composer.text, "한")

    def test_delete_removes_the_cluster_after_the_caret(self) -> None:
        for unit in ("x", "한", FAMILY, THUMBS_UP_TONED, FLAG_KR, Q_ACUTE):
            with self.subTest(unit=unit):
                composer = at(unit + "b", 0)
                press(composer, Key(DELETE))
                self.assertEqual((composer.text, composer.caret), ("b", 0))

    def test_deleting_past_the_ends_changes_nothing(self) -> None:
        composer = at("ab", 0)
        press(composer, Key(BACKSPACE))
        self.assertEqual((composer.text, composer.caret), ("ab", 0))
        composer.caret = 2
        press(composer, Key(DELETE))
        self.assertEqual((composer.text, composer.caret), ("ab", 2))

    def test_ctrl_w_deletes_the_word_before_the_caret(self) -> None:
        composer = at("say 안녕 하세요  ", len("say 안녕 하세요  "))
        press(composer, ctrl("w"))
        self.assertEqual(composer.text, "say 안녕 ")
        press(composer, ctrl("w"), ctrl("w"))
        self.assertEqual((composer.text, composer.caret), ("", 0))

    def test_alt_or_ctrl_backspace_deletes_the_word_before_the_caret_as_ctrl_w_does(self) -> None:
        # Legacy Alt+Backspace (`ESC DEL`), and the kitty reports of Alt+Backspace and Ctrl+Backspace.
        for data in (b"\x1b\x7f", b"\x1b[127;3u", b"\x1b[127;5u"):
            with self.subTest(data=data):
                composer = at("say 안녕 하세요  ", len("say 안녕 하세요  "))
                for key in KeyDecoder().feed(data):
                    composer.handle(key)
                self.assertEqual((composer.text, composer.caret), ("say 안녕 ", len("say 안녕 ")))
        composer = Composer()
        composer.handle(Paste("\n".join(f"line {number}" for number in range(10))))
        press(composer, Key(BACKSPACE, alt=True))
        self.assertEqual((composer.text, composer.pastes), ("", {}))  # a chip goes whole

    def test_ctrl_u_and_ctrl_k_kill_to_the_line_edges(self) -> None:
        composer = at("one\ntwo three\nfour", len("one\ntwo "))
        press(composer, ctrl("k"))
        self.assertEqual(composer.text, "one\ntwo \nfour")
        press(composer, ctrl("u"))
        self.assertEqual((composer.text, composer.caret), ("one\n\nfour", 4))

    def test_ctrl_u_and_ctrl_k_at_a_line_edge_remove_the_newline(self) -> None:
        composer = at("one\ntwo", 4)
        press(composer, ctrl("u"))
        self.assertEqual((composer.text, composer.caret), ("onetwo", 3))
        press(composer, ctrl("e"), ctrl("k"))
        self.assertEqual(composer.text, "onetwo")
        composer = at("one\ntwo", 3)
        press(composer, ctrl("k"))
        self.assertEqual((composer.text, composer.caret), ("onetwo", 3))


class MoveTests(unittest.TestCase):
    def test_left_and_right_step_one_cluster(self) -> None:
        text = "a" + FAMILY + "한" + FLAG_KR
        composer = at(text, 0)
        stops = []
        for _ in range(5):
            press(composer, Key(RIGHT))
            stops.append(composer.caret)
        self.assertEqual(stops, [1, 1 + len(FAMILY), 2 + len(FAMILY), len(text), len(text)])
        for _ in range(5):
            press(composer, Key(LEFT))
        self.assertEqual(composer.caret, 0)

    def test_ctrl_and_alt_arrows_step_one_word(self) -> None:
        text = "hello  한글 world"
        for modifier in ("ctrl", "alt"):
            with self.subTest(modifier=modifier):
                composer = at(text, 0)
                stops = []
                for _ in range(4):
                    press(composer, Key(RIGHT, **{modifier: True}))
                    stops.append(composer.caret)
                self.assertEqual(stops, [5, 9, 15, 15])
                stops = []
                for _ in range(4):
                    press(composer, Key(LEFT, **{modifier: True}))
                    stops.append(composer.caret)
                self.assertEqual(stops, [10, 7, 0, 0])

    def test_home_end_ctrl_a_ctrl_e_use_the_logical_line(self) -> None:
        composer = at("one\ntwo three\nfour", len("one\ntwo t"))
        press(composer, Key(HOME))
        self.assertEqual(composer.caret, 4)
        press(composer, Key(END))
        self.assertEqual(composer.caret, 13)
        press(composer, ctrl("a"))
        self.assertEqual(composer.caret, 4)
        press(composer, ctrl("e"))
        self.assertEqual(composer.caret, 13)

    def test_up_and_down_move_between_lines_keeping_the_cell_column(self) -> None:
        composer = at("abcdef\n한글\nxy", 5)  # after "abcde", column 5
        press(composer, Key(DOWN))
        self.assertEqual(composer.caret, 9)  # column 4: after "한글"
        press(composer, Key(DOWN))
        self.assertEqual(composer.caret, 12)  # line "xy" ends at column 2
        press(composer, Key(UP))
        self.assertEqual(composer.caret, 8)  # column 2: after "한"
        press(composer, Key(UP))
        self.assertEqual(composer.caret, 2)

    def test_up_and_down_follow_wrapped_rows_after_a_render(self) -> None:
        composer = at("abcdefghij", 10)
        composer.render(6, 5)  # "❯ " + 4 cells per row: abcd / efgh / ij
        press(composer, Key(UP))
        self.assertEqual(composer.caret, 6)
        press(composer, Key(UP))
        self.assertEqual(composer.caret, 2)
        press(composer, Key(DOWN), Key(DOWN))
        self.assertEqual(composer.caret, 10)

    def test_a_wide_glyph_straddling_the_column_lands_before_it(self) -> None:
        composer = at("abc\n한글", 3)
        press(composer, Key(DOWN))
        self.assertEqual(composer.caret, 5)  # column 3 falls inside "글": stop after "한"


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.composer = Composer(history=["first", "second\nline"])

    def test_up_at_the_top_recalls_older_entries_and_stops_at_the_oldest(self) -> None:
        typed(self.composer, "draft")
        press(self.composer, Key(UP))
        self.assertEqual((self.composer.text, self.composer.history_index), ("second\nline", 1))
        press(self.composer, Key(UP))  # caret was at the end: first up moves within the entry
        self.assertEqual(self.composer.text, "second\nline")
        press(self.composer, Key(UP))
        self.assertEqual((self.composer.text, self.composer.history_index), ("first", 0))
        press(self.composer, Key(UP))
        self.assertEqual((self.composer.text, self.composer.history_index), ("first", 0))

    def test_down_at_the_bottom_returns_to_the_draft(self) -> None:
        typed(self.composer, "draft")
        press(self.composer, Key(UP), Key(UP), Key(UP))
        press(self.composer, Key(DOWN))
        self.assertEqual(self.composer.text, "second\nline")
        press(self.composer, Key(DOWN))
        self.assertEqual((self.composer.text, self.composer.history_index), ("draft", None))
        self.assertEqual(self.composer.caret, 5)
        press(self.composer, Key(DOWN))
        self.assertEqual(self.composer.text, "draft")

    def test_submitting_a_recalled_entry_appends_and_resets(self) -> None:
        press(self.composer, Key(UP), Key(UP), Key(UP))
        self.assertEqual(self.composer.handle(Key(ENTER)), ComposerAction(SUBMIT, "first"))
        self.assertEqual(self.composer.history, ["first", "second\nline", "first"])
        self.assertIsNone(self.composer.history_index)

    def test_history_keeps_an_entry_as_the_file_does_trimmed_and_once(self) -> None:
        # Hermes' history file keeps the trimmed text (`history.append_entry`); this session's history matches it.
        recorded: list[str] = []
        composer = Composer(on_record=recorded.append)
        composer.record("  fix the test\n")
        composer.record("fix the test")
        self.assertEqual((composer.history, recorded), (["fix the test"], ["fix the test"]))

    def test_empty_history_leaves_the_text_alone(self) -> None:
        composer = at("abc", 1)
        press(composer, Key(UP), Key(DOWN))
        self.assertEqual((composer.text, composer.history_index), ("abc", None))


class ActionKeyTests(unittest.TestCase):
    def test_tab_completes_and_shift_tab_does_not(self) -> None:
        composer = at("/he", 3)
        self.assertEqual(composer.handle(Key(TAB)), ComposerAction(COMPLETE))
        self.assertEqual(composer.handle(Key(TAB, shift=True)), ComposerAction(NONE))
        self.assertEqual(composer.text, "/he")

    def test_escape_cancels_and_keeps_the_text(self) -> None:
        composer = at("draft", 5)
        self.assertEqual(composer.handle(Key(ESCAPE)), ComposerAction(CANCEL))
        self.assertEqual(composer.text, "draft")

    def test_ctrl_c_clears_text_then_interrupts(self) -> None:
        composer = at("draft", 5)
        self.assertEqual(composer.handle(ctrl("c")), ComposerAction(CANCEL))
        self.assertEqual((composer.text, composer.caret), ("", 0))
        self.assertEqual(composer.handle(ctrl("c")), ComposerAction(INTERRUPT))

    def test_ctrl_d_exits_on_empty_and_deletes_forward_otherwise(self) -> None:
        composer = at("ab", 0)
        self.assertEqual(composer.handle(ctrl("d")), ComposerAction(NONE))
        self.assertEqual(composer.text, "b")
        press(composer, ctrl("d"))
        self.assertEqual(composer.handle(ctrl("d")), ComposerAction(EXIT))


class PasteTests(unittest.TestCase):
    def test_a_multi_line_paste_keeps_its_lines_and_lands_at_the_caret(self) -> None:
        composer = at("[]", 1)
        composer.handle(Paste("one\r\ntwo\rthree\n"))
        self.assertEqual(composer.text, "[one\ntwo\nthree\n]")
        self.assertEqual(composer.caret, len("[one\ntwo\nthree\n"))

    def test_control_characters_are_dropped_and_tabs_kept(self) -> None:
        composer = Composer()
        composer.handle(Paste("a\x1b[31mb\x07\tc"))
        self.assertEqual(composer.text, "a[31mb\tc")

    def test_a_tab_draws_as_four_cells(self) -> None:
        composer = at("\tx", 2)
        lines, caret = composer.render(40, 3)
        self.assertEqual(lines_text(lines), ["❯     x"])
        self.assertEqual(caret, (0, 7))


class PasteChipTests(unittest.TestCase):
    """A long paste is one atomic chip in the composer and its whole text when sent (kept in memory only)."""

    SIXTY = "\n".join(f"line {number}" for number in range(60))

    def test_a_paste_of_more_than_three_lines_or_800_characters_is_a_chip(self) -> None:
        composer = Composer()
        composer.handle(Paste(self.SIXTY))
        self.assertEqual(composer.text, "[Pasted text #1 +60 lines]")
        long_line = Composer()
        long_line.handle(Paste("x" * 801))
        self.assertEqual(long_line.text, "[Pasted text #1 · 801 chars]")
        for text in ("one\ntwo\nthree", "one\ntwo\nthree\n", "x" * 800):
            with self.subTest(text=text[:20]):
                small = Composer()
                small.handle(Paste(text))
                self.assertEqual(small.text, text)  # short enough to keep as typed

    def test_sending_expands_the_chip_where_it_stands_and_reports_the_compact_text(self) -> None:
        composer = Composer()
        typed(composer, "see ")
        composer.handle(Paste(self.SIXTY))
        typed(composer, " please")
        action = press(composer, Key(ENTER))
        self.assertEqual(action.text, f"see {self.SIXTY} please")
        self.assertEqual(action.shown, "see [Pasted text #1 +60 lines] please")
        self.assertEqual(composer.history[-1], f"see {self.SIXTY} please")  # Up gives back what was sent
        self.assertEqual(composer.pastes, {})

    def test_backspace_and_delete_take_the_chip_whole(self) -> None:
        composer = Composer()
        typed(composer, "a ")
        composer.handle(Paste(self.SIXTY))
        typed(composer, " b")
        press(composer, Key(LEFT), Key(LEFT))
        press(composer, Key(BACKSPACE))
        self.assertEqual((composer.text, composer.pastes), ("a  b", {}))
        composer = Composer()
        composer.handle(Paste(self.SIXTY))
        press(composer, Key(HOME), Key(DELETE))
        self.assertEqual(composer.text, "")

    def test_the_caret_steps_over_a_chip_and_never_lands_inside_it(self) -> None:
        composer = Composer()
        typed(composer, "a")
        composer.handle(Paste(self.SIXTY))
        typed(composer, "b")
        chip = "[Pasted text #1 +60 lines]"
        press(composer, Key(LEFT))
        self.assertEqual(composer.caret, 1 + len(chip))
        press(composer, Key(LEFT))
        self.assertEqual(composer.caret, 1)
        press(composer, Key(RIGHT))
        self.assertEqual(composer.caret, 1 + len(chip))

    def test_word_and_line_kills_take_a_chip_they_reach_whole(self) -> None:
        for kill in (ctrl("w"), ctrl("u")):
            with self.subTest(kill=kill):
                composer = Composer()
                composer.handle(Paste(self.SIXTY))
                press(composer, kill)
                self.assertEqual((composer.text, composer.pastes), ("", {}))

    def test_chips_are_numbered_and_the_numbers_start_again_with_an_empty_composer(self) -> None:
        composer = Composer()
        composer.handle(Paste(self.SIXTY))
        composer.handle(Paste(self.SIXTY + "\nmore"))
        self.assertEqual(composer.text, "[Pasted text #1 +60 lines][Pasted text #2 +61 lines]")
        press(composer, Key(ENTER))
        composer.handle(Paste(self.SIXTY))
        self.assertEqual(composer.text, "[Pasted text #1 +60 lines]")

    def test_a_masked_answer_takes_a_paste_as_typed(self) -> None:
        composer = Composer(masked=True)
        composer.handle(Paste("x" * 900))
        self.assertEqual(composer.text, "x" * 900)

    def test_the_chip_is_drawn_in_the_chip_style(self) -> None:
        composer = Composer()
        typed(composer, "a ")
        composer.handle(Paste(self.SIXTY))
        chip = Style(fg="#00FF00")
        lines, _caret = composer.render(80, 3, chip_style=chip)
        styled = [span for span in lines[0] if span.style == chip]
        self.assertEqual([span.text for span in styled], ["[Pasted text #1 +60 lines]"])


class SubmittedChipsTests(unittest.TestCase):
    """A submit reports its chips (label and text), and `restore` puts a submitted text back with them as chips."""

    PASTE = "line one\nline two\nline three\nline four\n"

    def submitted(self) -> ComposerAction:
        composer = Composer()
        composer.handle(Paste(self.PASTE))
        for char in " and more":
            composer.handle(Key(CHAR, char))
        return composer.handle(Key(ENTER))

    def test_a_submit_reports_the_chips_in_what_it_showed(self) -> None:
        action = self.submitted()
        self.assertEqual(action.chips, (("[Pasted text #1 +4 lines]", self.PASTE),))
        self.assertEqual(action.shown, "[Pasted text #1 +4 lines] and more")
        plain = Composer()
        for char in "no chips":
            plain.handle(Key(CHAR, char))
        self.assertEqual(plain.handle(Key(ENTER)).chips, ())

    def test_restore_puts_the_chips_back_and_the_rest_as_text(self) -> None:
        action = self.submitted()
        composer = Composer()
        composer.restore(action.shown, action.chips)
        self.assertEqual(composer.text, action.shown)
        self.assertEqual(composer.expanded(), action.text)
        composer.handle(Key(BACKSPACE))  # a character of the words, not the chip
        self.assertEqual(composer.text, "[Pasted text #1 +4 lines] and mor")
        for _ in range(len(" and mor")):
            composer.handle(Key(BACKSPACE))
        composer.handle(Key(BACKSPACE))  # now the chip, whole
        self.assertEqual((composer.text, composer.pastes), ("", {}))

    def test_a_paste_after_a_restore_never_reuses_a_restored_label(self) -> None:
        action = self.submitted()
        composer = Composer()
        composer.restore(action.shown, action.chips)
        composer.handle(Paste("a\nb\nc\nd\n"))  # four lines, as the restored chip: the same label but for its number
        self.assertEqual(composer.text, action.shown + "[Pasted text #2 +4 lines]")
        self.assertEqual(len(composer.pastes), 2)
        self.assertEqual(composer.expanded(), action.text + "a\nb\nc\nd\n")


class PasteChipAppTests(unittest.TestCase):
    def test_the_prompt_goes_whole_and_the_transcript_shows_the_chip(self) -> None:
        from test_tui_modes import SID, make_app
        from omh.tui.transcript import UserBlock

        app, client = make_app()
        sixty = PasteChipTests.SIXTY
        app._on_input(Paste(sixty))
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("prompt.submit", {"session_id": SID, "text": sixty})])
        (user,) = [block for block in app.transcript.blocks if isinstance(block, UserBlock)]
        self.assertEqual(user.text, "[Pasted text #1 +60 lines]")


class ImageTokenTests(unittest.TestCase):
    """An attached image is an atomic `[Image #N]` token in the text, and its image lives exactly as long as it does."""

    SHOT, NOTES = "/h/images/shot.png", "/h/images/notes.png"

    def with_image(self, before: str = "", after: str = "", label: str = "[Image #41]", image: object = SHOT) -> Composer:
        composer = Composer()
        typed(composer, before + after)
        composer.caret = len(before)
        self.assertTrue(composer.insert_image(label, image))
        return composer

    def images(self, composer: Composer) -> list[object]:
        return [image for _label, image in composer.images.values()]

    def test_the_token_goes_in_at_the_caret_with_a_space_before_the_words_typed_after_it(self) -> None:
        composer = self.with_image()
        typed(composer, "이런느낌으로")
        lines, caret = composer.render(40, 4)
        self.assertEqual(lines_text(lines), ["❯ [Image #41] 이런느낌으로"])
        self.assertEqual(caret, (0, 2 + 11 + 1 + 12))  # the label's 11 cells, the space, six Hangul syllables
        middle = self.with_image("look at", " this")
        self.assertEqual(composer_shown(middle), "look at [Image #41] this")  # spaced from the words on both sides
        self.assertEqual(middle.caret, len("look at ") + 1)  # right after the token, before the space that was there
        self.assertEqual(self.images(middle), [self.SHOT])

    def test_typing_or_pasting_the_label_makes_no_token(self) -> None:
        for arrive in (lambda composer: typed(composer, "[Image #3] x"), lambda composer: composer.handle(Paste("[Image #3] x"))):
            composer = Composer()
            arrive(composer)
            self.assertEqual((composer.text, composer.images), ("[Image #3] x", {}))
            action = press(composer, Key(ENTER))
            self.assertEqual((action.text, action.images), ("[Image #3] x", ()))

    def test_a_pasted_token_character_is_dropped_so_no_token_can_be_forged(self) -> None:
        composer = self.with_image()
        (token,) = composer.images
        composer.handle(Paste(f"x{token}y"))
        self.assertEqual(composer_shown(composer), "[Image #41] xy")
        self.assertEqual(composer.text.count(token), 1)

    def test_every_deletion_that_reaches_the_token_takes_it_and_its_image_whole(self) -> None:
        cases = {  # (text before the caret, after it, keys)
            "Backspace right after it": ("look ", " now", [Key(BACKSPACE)]),  # spaces both sides: none added
            "Backspace through the space": ("", "", [Key(BACKSPACE), Key(BACKSPACE)]),
            "Delete right before it": ("look ", "", [Key(LEFT), Key(LEFT), Key(DELETE)]),
            "Ctrl+W": ("look ", "", [ctrl("w"), ctrl("w")]),
            "Alt+Backspace": ("look ", "", [Key(BACKSPACE, alt=True)] * 2),
            "Ctrl+Backspace": ("look ", "", [Key(BACKSPACE, ctrl=True)] * 2),
            "Ctrl+U (what Cmd+Backspace sends)": ("look ", " now", [ctrl("u")]),
            "Ctrl+K": ("look ", " now", [Key(LEFT), ctrl("k")]),
            "Ctrl+C": ("look ", " now", [ctrl("c")]),
        }
        for name, (before, after, keys) in cases.items():
            with self.subTest(name):
                composer = self.with_image(before, after)
                press(composer, *keys)
                self.assertNotIn("[Image", composer_shown(composer))
                self.assertEqual(composer.images, {})

    def test_the_caret_steps_over_the_token_and_never_lands_inside_it(self) -> None:
        composer = self.with_image("a", "b")  # `a [Image #41] b`, the caret after the space after the token
        self.assertEqual(composer.caret, 4)
        press(composer, Key(LEFT), Key(LEFT))  # over the space, then over the token in one step
        self.assertEqual(composer.caret, 2)
        self.assertEqual(composer.render(40, 2)[1], (0, 2 + len("a ")))
        press(composer, Key(RIGHT))
        self.assertEqual(composer.caret, 3)
        self.assertEqual(composer.render(40, 2)[1], (0, 2 + len("a [Image #41]")))

    def test_a_row_never_splits_the_token(self) -> None:
        composer = self.with_image("한글 텍스트", "끝")
        for width in range(14, 30):
            with self.subTest(width=width):
                rows = lines_text(composer.render(width, 10)[0])
                self.assertEqual(sum(row.count("[Image #41]") for row in rows), 1, rows)
                self.assertTrue(all(cell_width(row) <= width for row in rows), rows)

    def test_undo_puts_the_token_and_its_image_back_and_redo_takes_them_again(self) -> None:
        composer = self.with_image("look ", " now")
        press(composer, ctrl("u"))
        self.assertEqual(composer.images, {})
        press(composer, ctrl("_"))
        self.assertEqual((composer_shown(composer), self.images(composer)), ("look [Image #41] now", [self.SHOT]))
        press(composer, ctrl("y"))
        self.assertEqual(composer.images, {})

    def test_a_submit_sends_the_labels_and_reports_the_images_in_order(self) -> None:
        composer = self.with_image(label="[Image #1]", image=self.SHOT)
        typed(composer, "and")
        composer.insert_image("[Image #2]", self.NOTES)
        typed(composer, "like this")
        action = press(composer, Key(ENTER))
        self.assertEqual(action.text, "[Image #1] and [Image #2] like this")
        self.assertEqual(action.shown, "")  # what it showed is what it sent
        self.assertEqual(action.images, (("[Image #1]", self.SHOT), ("[Image #2]", self.NOTES)))
        self.assertEqual(composer.images, {})

    def test_history_keeps_the_labels_so_a_recalled_prompt_is_plain_text(self) -> None:
        composer = self.with_image(label="[Image #1]")
        typed(composer, "x")
        press(composer, Key(ENTER))
        self.assertEqual(composer.history, ["[Image #1] x"])
        press(composer, Key(UP))
        self.assertEqual((composer.text, composer.images), ("[Image #1] x", {}))
        self.assertEqual(press(composer, Key(ENTER)).images, ())

    def test_restore_and_replace_make_the_named_labels_tokens_again(self) -> None:
        composer = Composer()
        composer.restore("[Image #1] and [Image #2]", (), [("[Image #2]", self.NOTES)])
        self.assertEqual(composer_shown(composer), "[Image #1] and [Image #2]")
        self.assertEqual([label for label, _image in composer.images.values()], ["[Image #2]"])
        composer.replace(0, len(composer.text), "again [Image #1]", [("[Image #1]", self.SHOT)])
        self.assertEqual(self.images(composer), [self.SHOT])
        press(composer, Key(BACKSPACE))
        self.assertEqual(composer_shown(composer), "again ")

    def test_masked_input_takes_no_token(self) -> None:
        composer = Composer(masked=True)
        self.assertFalse(composer.insert_image(IMAGE_LABEL.format(number=1), self.SHOT))
        self.assertEqual((composer.text, composer.images), ("", {}))

    def test_a_row_narrower_than_the_label_cuts_it_and_never_overflows(self) -> None:
        composer = self.with_image("a", "b", label="[Image #12]")
        for width in range(4, 14):
            with self.subTest(width=width):
                lines, (_row, col) = composer.render(width, 10)
                rows = lines_text(lines)
                self.assertTrue(all(cell_width(row) <= width for row in rows), rows)
                self.assertLessEqual(col, width)

    def test_a_combining_mark_typed_after_a_token_is_neither_drawn_nor_sent(self) -> None:
        composer = self.with_image()
        press(composer, Key(LEFT))  # right after the token
        typed(composer, "\u0301")
        self.assertEqual(composer_shown(composer), "[Image #41] ")
        self.assertEqual(press(composer, Key(ENTER)).text, "[Image #41] ")

    def test_history_browsing_keeps_the_drafts_tokens_through_an_edit(self) -> None:
        composer = Composer(history=["older"])
        typed(composer, "look ")
        composer.insert_image("[Image #1]", self.SHOT)
        press(composer, Key(UP))
        typed(composer, "!")
        press(composer, Key(DOWN))
        self.assertEqual((composer_shown(composer), self.images(composer)), ("look [Image #1] ", [self.SHOT]))
        action = press(composer, Key(ENTER))
        self.assertEqual((action.text, action.images), ("look [Image #1] ", (("[Image #1]", self.SHOT),)))

    def test_a_token_character_no_image_is_mapped_to_never_leaves(self) -> None:
        composer = self.with_image()
        (token,) = composer.images
        composer.images.clear()  # as a draft that lost its map would hold it
        self.assertEqual(composer.expanded(), " ")
        self.assertNotIn(token, press(composer, Key(ENTER)).text)
        self.assertNotIn(token, "".join(composer.history))

    def test_the_token_is_drawn_in_the_chip_style(self) -> None:
        composer = self.with_image("a")
        chip = Style(fg="#00FF00")
        lines, _caret = composer.render(80, 3, chip_style=chip)
        self.assertEqual([span.text for span in lines[0] if span.style == chip], ["[Image #41]"])


def composer_shown(composer: Composer) -> str:
    """The text as the composer draws it: each image token as its label."""
    return composer.expanded()


class MaskedTests(unittest.TestCase):
    def test_masked_input_draws_one_bullet_per_cluster(self) -> None:
        composer = Composer(masked=True)
        composer.handle(Paste("p" + HANGUL_NFD + FAMILY))
        lines, caret = composer.render(40, 3)
        self.assertEqual(lines_text(lines), ["❯ ••••"])
        self.assertEqual(caret, (0, 6))
        press(composer, Key(LEFT), Key(LEFT))
        self.assertEqual(composer.render(40, 3)[1], (0, 4))

    def test_masked_input_wraps_by_bullets(self) -> None:
        composer = Composer(masked=True)
        typed(composer, "한글한글한글")  # 12 cells of Hangul, 6 bullets
        lines, caret = composer.render(6, 5)
        self.assertEqual(lines_text(lines), ["❯ ••••", "  ••"])
        self.assertEqual(caret, (1, 4))

    def test_masked_input_never_enters_or_browses_history(self) -> None:
        composer = Composer(history=["old"], masked=True)
        typed(composer, "secret")
        press(composer, Key(UP))
        self.assertEqual(composer.text, "secret")
        self.assertEqual(composer.handle(Key(ENTER)), ComposerAction(SUBMIT, "secret"))
        self.assertEqual(composer.history, ["old"])

    def test_repr_shows_masked_text_as_bullets(self) -> None:
        composer = Composer(masked=True)
        typed(composer, "hunter2")
        self.assertNotIn("hunter2", repr(composer))
        self.assertIn("•••••••", repr(composer))
        composer.masked = False
        self.assertIn("hunter2", repr(composer))

    def test_a_submit_with_history_recording_off_stays_out_of_history(self) -> None:
        composer = Composer(history=["old"], records_history=False)
        typed(composer, "blue")
        self.assertEqual(composer.handle(Key(ENTER)), ComposerAction(SUBMIT, "blue"))
        self.assertEqual(composer.history, ["old"])

    def test_masked_input_refuses_newlines(self) -> None:
        composer = Composer(masked=True)
        typed(composer, "a")
        press(composer, Key(ENTER, alt=True), ctrl("j"))
        composer.handle(Paste("b\nc\n"))
        self.assertEqual(composer.text, "abc")


class MeasureOnceTests(unittest.TestCase):
    """The text is split into clusters and measured once per value; moving the caret and redrawing reuse that."""

    def test_moving_the_caret_and_redrawing_never_measure_the_text_again(self) -> None:
        composer = Composer()
        composer.handle(Paste(f"{HANGUL} line one\nline two runs longer than the width\nthree"))
        composer.render(20, 5)
        keys = (Key(LEFT), Key(UP), Key(RIGHT, ctrl=True), Key(DOWN), Key(HOME), Key(END), Key(UP), Key(UP))
        with patch("omh.tui.composer.clusters", side_effect=AssertionError("the text was measured again")):
            for key in keys:
                composer.handle(key)
                composer.render(20, 5)
        # Word-wrapped at 18 cells, the second line is `line two runs ` / `longer than the ` / `width`; the walk
        # ends on its middle row, 5 cells in, before the `r` of `longer` (counted by hand).
        self.assertEqual(composer.caret, len(f"{HANGUL} line one\nline two runs longe"))

    def test_a_new_text_a_new_mask_or_a_new_width_is_laid_out_again(self) -> None:
        composer = at("abcdef", 6)
        self.assertEqual(lines_text(composer.render(20, 3)[0]), ["❯ abcdef"])
        composer.masked = True
        self.assertEqual(lines_text(composer.render(20, 3)[0]), ["❯ ••••••"])
        typed(composer, "g")
        self.assertEqual(lines_text(composer.render(20, 3)[0]), ["❯ •••••••"])
        self.assertEqual(lines_text(composer.render(6, 3)[0]), ["❯ ••••", "  •••"])


def whole_text_shape(composer: Composer) -> tuple[list[str], list[int], list[str], list[int | None]]:
    """The composer's text measured in one piece, as the composer did before it measured chunk by chunk."""
    labels = {token: label for token, (label, _image) in composer.images.items()}
    units = clusters(composer.text)
    bounds = [0]
    shown: list[str] = []
    widths: list[int | None] = []
    for unit in units:
        bounds.append(bounds[-1] + len(unit))
        if unit == "\n":
            shown.append("")
            widths.append(None)
        elif unit[0] in labels:
            shown.append(labels[unit[0]])
            widths.append(cell_width(labels[unit[0]]))
        elif composer.masked:
            shown.append("•")
            widths.append(1)
        elif unit == "\t":
            shown.append("    ")
            widths.append(4)
        else:
            shown.append(unit)
            widths.append(cluster_width(unit))
    return units, bounds, shown, widths


class ChunkedShapeTests(unittest.TestCase):
    """The text is measured chunk by chunk, so an edit measures only the chunk it touched, and nothing drawn moves."""

    PIECES = ("a", "bc", " ", "  ", "\n", "\t", HANGUL, HANGUL_NFD, "한 글", FAMILY, THUMBS_UP_TONED, FLAG_KR, Q_ACUTE,
              "\u0301", " \u0301", "界 ", "x y z ", "😀", "\u200d",
              " \u1161", " \u11a8", " \ud7cb", " \ufe0f", " \U0001F3FB", " \u0600", " \u200b", " \ufeff")

    def assert_matches_whole_text(self, composer: Composer) -> None:
        shape = composer._measured()
        self.assertEqual((shape.units, shape.bounds, shape.shown, shape.widths), whole_text_shape(composer))

    def test_every_edit_of_a_random_sequence_measures_what_the_whole_text_measures(self) -> None:
        rng = random.Random(20261103)
        for masked in (False, True):
            composer = Composer()
            composer.masked = masked
            for step in range(300):
                action = rng.random()
                if action < 0.5:
                    composer.handle(Paste("".join(rng.choices(self.PIECES, k=rng.randint(1, 4)))))
                elif action < 0.65:
                    composer.handle(Key(BACKSPACE))
                elif action < 0.75:
                    composer.handle(Key(DELETE))
                elif action < 0.85:
                    composer.handle(Key(rng.choice((LEFT, RIGHT, UP, DOWN, HOME, END))))
                elif action < 0.9:
                    composer.handle(Key(ENTER, shift=True))
                elif action < 0.95:
                    composer.insert_image(f"[Image #{step}]", step)
                else:
                    composer.handle(Paste("p" * rng.choice((50, 900)) + "\n" * rng.randint(0, 12)))
                self.assert_matches_whole_text(composer)
                composer.render(rng.choice((12, 30, 80)), 6)

    def test_no_character_the_cut_rule_admits_joins_the_space_before_it(self) -> None:
        edge = composer_module._CHUNK_EDGE
        admitted = [chr(code) for code in range(0x110000)
                    if not 0xD800 <= code <= 0xDFFF and len(edge.split(" " + chr(code))) == 2]
        self.assertGreater(len(admitted), 30000)
        for before in (" ", "a\u200d "):
            for ch in admitted:
                for tail in ("", "\u0301", "\u200d", "\u3099", "\u1161", "a"):
                    self.assertEqual(clusters(before + ch + tail), clusters(before) + clusters(ch + tail),
                                     (before, hex(ord(ch)), tail))

    def test_a_relabelled_token_is_drawn_with_its_new_label_after_the_next_edit(self) -> None:
        composer = Composer()
        self.assertTrue(composer.insert_image("[Image #1]", "a"))
        composer._measured()
        token = next(iter(composer.images))
        composer.images[token] = ("[Image #22]", "a")
        typed(composer, "x")
        self.assertIn("[Image #22]", composer._measured().shown)
        self.assert_matches_whole_text(composer)

    def test_the_kept_chunks_never_outnumber_the_distinct_chunks_of_the_text(self) -> None:
        composer = Composer()
        rng = random.Random(7)
        for _ in range(100):
            composer.handle(Paste("".join(rng.choices(self.PIECES, k=3))))
            if rng.random() < 0.4:
                composer.handle(Key(BACKSPACE))
            shape = composer._measured()
            self.assertLessEqual(len(composer._chunks), len(set(composer_module._CHUNK_EDGE.split(shape.text))))

    def test_an_edit_in_a_long_text_measures_only_the_chunk_it_touched(self) -> None:
        composer = Composer()
        composer.replace(0, 0, "".join(f"word{n} 한글 " for n in range(2000)) + "\n".join(f"line {n}" for n in range(500)))
        composer.render(80, 6)
        calls: list[int] = []
        real = composer_module.clusters

        def counting(text: str) -> list[str]:
            calls.append(len(text))
            return real(text)

        with patch("omh.tui.composer.clusters", counting):
            composer.handle(Key(CHAR, "x"))
            composer.handle(Key(BACKSPACE))
            composer.handle(Key(CHAR, "한"))
            composer.handle(Key(CHAR, " "))
            composer.handle(Key(BACKSPACE))
            composer.render(80, 6)
        self.assertLessEqual(len(calls), 12)
        self.assertLess(max(calls), 40)
        self.assert_matches_whole_text(composer)


class RenderTests(unittest.TestCase):
    def test_empty_input_draws_the_prompt_with_the_caret_after_it(self) -> None:
        lines, caret = Composer().render(40, 3)
        self.assertEqual(lines_text(lines), ["❯ "])
        self.assertEqual(caret, (0, 2))

    def test_the_prompt_is_styled_and_continuation_rows_are_indented(self) -> None:
        style = Style(fg="#ff0000", bold=True)
        lines, _ = at("ab\ncd", 0).render(40, 3, prompt="> ", prompt_style=style)
        self.assertEqual(lines_text(lines), ["> ab", "  cd"])
        self.assertEqual(lines[0][0].style, style)
        self.assertEqual(lines[1][0].style, Style())

    def test_wrapping_is_by_cells_and_never_splits_a_wide_glyph(self) -> None:
        composer = at("ab한글cd", 6)
        lines, caret = composer.render(7, 5)  # 5 cells per row
        self.assertEqual(lines_text(lines), ["❯ ab한", "  글cd"])
        self.assertEqual(caret, (1, 6))

    def test_the_caret_after_a_full_row_starts_a_new_row(self) -> None:
        composer = at("abcd", 4)
        lines, caret = composer.render(6, 5)  # exactly 4 cells per row
        self.assertEqual(lines_text(lines), ["❯ abcd", "  "])
        self.assertEqual(caret, (1, 2))
        composer.caret = 3
        self.assertEqual(composer.render(6, 5)[1], (0, 5))

    def test_the_caret_at_a_soft_wrap_sits_at_the_next_row_start(self) -> None:
        composer = at("abcdef", 4)
        lines, caret = composer.render(6, 5)
        self.assertEqual(lines_text(lines), ["❯ abcd", "  ef"])
        self.assertEqual(caret, (1, 2))

    def test_the_caret_col_counts_wide_glyphs_and_emoji(self) -> None:
        composer = at("한" + FAMILY + "x", len("한" + FAMILY))
        self.assertEqual(composer.render(40, 3)[1], (0, 6))

    def test_the_window_scrolls_to_keep_the_caret_visible(self) -> None:
        composer = at("1\n2\n3\n4\n5\n6", 11)  # six typed lines (a paste that long is a chip)
        lines, caret = composer.render(40, 3)
        self.assertEqual(lines_text(lines), ["  4", "  5", "  6"])
        self.assertEqual(caret, (2, 3))
        press(composer, Key(UP), Key(UP))  # still inside the window: no scroll
        self.assertEqual(lines_text(composer.render(40, 3)[0]), ["  4", "  5", "  6"])
        press(composer, Key(UP))
        lines, caret = composer.render(40, 3)
        self.assertEqual(lines_text(lines), ["  3", "  4", "  5"])
        self.assertEqual(caret, (0, 3))
        press(composer, Key(UP), Key(UP))
        lines, caret = composer.render(40, 3)
        self.assertEqual(lines_text(lines), ["❯ 1", "  2", "  3"])
        self.assertEqual(caret, (0, 3))

    def test_the_window_refills_when_rows_go_away(self) -> None:
        composer = at("1\n2\n3\n4\n5\n6", 11)
        composer.render(40, 3)
        press(composer, Key(BACKSPACE), Key(BACKSPACE))  # drop "\n6"
        lines, caret = composer.render(40, 3)
        self.assertEqual(lines_text(lines), ["  3", "  4", "  5"])
        self.assertEqual(caret, (2, 3))


class WordWrapTests(unittest.TestCase):
    """Rows break between words, as the transcript's echo of the sent prompt does, and every caret stays mapped."""

    def rows(self, text: str, width: int, masked: bool = False) -> list[str]:
        return lines_text(Composer(text=text, masked=masked).render(width, 20)[0])

    def test_a_long_prompt_wraps_at_a_space_and_the_next_row_starts_with_the_word(self) -> None:
        # The capture's prompt at 110 columns; cut by cells it read `a "Map the H` over `ermes-hosted HUD"`.
        prompt = (
            "Do these steps in order. 1) Call todo_list once with this nested plan and never touch it again: "
            'a "Map the Hermes-hosted HUD" completed, with subtask "Inventory the layout complaints" completed'
        )
        self.assertEqual(
            self.rows(prompt, 110),
            [
                '❯ Do these steps in order. 1) Call todo_list once with this nested plan and never touch it again: a "Map the ',
                '  Hermes-hosted HUD" completed, with subtask "Inventory the layout complaints" completed',
            ],
        )
        self.assertEqual(self.rows("the quick brown fox", 12), ["❯ the quick ", "  brown fox"])  # 10 cells a row

    def test_spaces_at_the_break_end_the_row_and_a_tab_breaks_like_one(self) -> None:
        # The spaces stay on the row (a run of them too), so the row after starts with the word, never a space.
        self.assertEqual(self.rows("ab hello   world", 11), ["❯ ab ", "  hello   ", "  world"])  # 9 cells a row
        self.assertEqual(self.rows("ab\tcdef", 10), ["❯ ab    ", "  cdef"])  # the tab is drawn as four spaces

    def test_a_word_longer_than_a_row_still_breaks_at_the_cell(self) -> None:
        self.assertEqual(self.rows("see abcdefghijk end", 10), ["❯ see ", "  abcdefgh", "  ijk end"])  # 8 cells
        self.assertEqual(self.rows("日本語の文を書く", 8), ["❯ 日本語", "  の文を", "  書く"])  # no spaces at all

    def test_a_word_reaching_the_last_cell_puts_the_space_after_it_on_the_next_row(self) -> None:
        # A continuation row starts with a space only after a row of one word (or of only spaces) with no room left
        # for that space: it cannot hang past the edge, where the caret before it would sit.
        composer = at("abcdefgh end", 8)
        lines, caret = composer.render(10, 5)  # 8 cells a row
        self.assertEqual(lines_text(lines), ["❯ abcdefgh", "   end"])
        self.assertEqual(caret, (1, 2))  # the caret before that space opens the row

    def test_masked_input_and_a_no_break_space_wrap_by_the_cell(self) -> None:
        # A word break under the mask would show where the secret's spaces are.
        self.assertEqual(self.rows("ab cd ef", 6, masked=True), ["❯ ••••", "  ••••", "  "])
        nbsp = chr(0xA0)
        self.assertEqual(self.rows(f"ab cd{nbsp}ef", 8), ["❯ ab ", f"  cd{nbsp}ef"])  # `cd ef` moves as one word
        self.assertEqual(self.rows(f"abcd{nbsp}efgh", 8), [f"❯ abcd{nbsp}e", "  fgh"])

    def test_every_caret_position_has_its_own_cell_inside_a_row_no_wider_than_the_screen(self) -> None:
        texts = [
            "Do these steps in order. todo_list 한국어 문장을 日本語の文 🙂 a xxxxxxxxxxxxxxxxxxxxxxx",
            "a  b   c    d\tend of   line\nnext  line  here",
            "한국어 문장을 이렇게 길게 써도 단어 사이에서 줄이 바뀐다",
            "abcde abcd語 tail",  # at 5 cells a row: a row that starts with a space, then a wide glyph
            "x" * 30 + " y",
        ]
        for text in texts:
            for width in (7, 10, 15, 22, 39):  # from 5 cells a row, a tab fits in one
                with self.subTest(text=text[:20], width=width):
                    composer = Composer(text=text)
                    lines, _ = composer.render(width, 40)
                    self.assertEqual("".join(line_text(line)[2:] for line in lines), text.replace("\n", "").replace("\t", "    "))
                    self.assertTrue(all(line_width(line) <= width for line in lines), lines_text(lines))
                    cells = []
                    for caret in range(len(text) + 1):  # every index of these texts is a cluster boundary
                        composer.caret = caret
                        cells.append(composer.render(width, 40)[1])
                    self.assertEqual(cells, sorted(set(cells)), "two positions on one cell, or out of order")
                    self.assertTrue(all(col < width for _row, col in cells), cells)


if __name__ == "__main__":
    unittest.main()
