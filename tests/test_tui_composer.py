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
