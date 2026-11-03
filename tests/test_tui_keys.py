"""The OMH TUI's incremental key decoder (`omh.tui.keys`).

Input arrives in whatever chunks the terminal and the kernel choose, so every
multi-byte form is also fed split at each possible point: the decoder must
produce the same keys as from one chunk and never half a key.
"""

from __future__ import annotations

import random
import unittest

from omh.tui.keys import (
    BUTTON_LEFT,
    BUTTON_MIDDLE,
    BUTTON_RIGHT,
    MOUSE_REPORT_SECONDS,
    NO_BUTTON,
    PASTE_LATE_SECONDS,
    PASTE_SETTLE_SECONDS,
    WHEEL_DOWN,
    WHEEL_LEFT,
    WHEEL_RIGHT,
    WHEEL_UP,
    Key,
    KeyDecoder,
    Mouse,
    Paste,
)


def decode(data: bytes) -> list:
    decoder = KeyDecoder()
    return decoder.feed(data) + decoder.flush()


def decode_split_everywhere(test: unittest.TestCase, data: bytes) -> list:
    """Decode `data` whole, then split at every offset; all must agree."""
    whole = decode(data)
    for cut in range(1, len(data)):
        decoder = KeyDecoder()
        events = decoder.feed(data[:cut]) + decoder.feed(data[cut:]) + decoder.flush()
        test.assertEqual(events, whole, f"split at byte {cut} of {data!r}")
    return whole


def char(text: str, **modifiers: bool) -> Key:
    return Key("char", text, **modifiers)


class PlainKeyTests(unittest.TestCase):
    def test_printable_ascii(self) -> None:
        self.assertEqual(decode(b"aZ ~"), [char("a"), char("Z"), char(" "), char("~")])

    def test_enter_tab_backspace(self) -> None:
        self.assertEqual(decode(b"\r"), [Key("enter")])
        self.assertEqual(decode(b"\t"), [Key("tab")])
        self.assertEqual(decode(b"\x7f"), [Key("backspace")])
        self.assertEqual(decode(b"\x08"), [Key("backspace")])

    def test_line_feed_is_ctrl_j_not_enter(self) -> None:
        self.assertEqual(decode(b"\n"), [char("j", ctrl=True)])

    def test_ctrl_letters(self) -> None:
        self.assertEqual(decode(b"\x01"), [char("a", ctrl=True)])
        self.assertEqual(decode(b"\x03"), [char("c", ctrl=True)])  # raw mode: Ctrl+C is a key
        self.assertEqual(decode(b"\x04"), [char("d", ctrl=True)])
        self.assertEqual(decode(b"\x1a"), [char("z", ctrl=True)])

    def test_ctrl_punctuation(self) -> None:
        self.assertEqual(decode(b"\x00"), [char("@", ctrl=True)])  # also Ctrl+Space
        self.assertEqual(decode(b"\x1c\x1d\x1f"), [char("\\", ctrl=True), char("]", ctrl=True), char("_", ctrl=True)])


class Utf8Tests(unittest.TestCase):
    def test_multibyte_characters(self) -> None:
        self.assertEqual(decode("é한😀".encode()), [char("é"), char("한"), char("😀")])

    def test_a_character_split_across_chunks_waits_for_its_tail(self) -> None:
        data = "한".encode()
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(data[:1]), [])
        self.assertEqual(decoder.feed(data[1:2]), [])
        self.assertEqual(decoder.feed(data[2:]), [char("한")])

    def test_every_split_of_mixed_text_agrees(self) -> None:
        events = decode_split_everywhere(self, "a한😀b".encode())
        self.assertEqual(events, [char("a"), char("한"), char("😀"), char("b")])

    def test_invalid_bytes_become_unknown_and_decoding_continues(self) -> None:
        self.assertEqual(decode(b"\xffa"), [Key("unknown"), char("a")])
        self.assertEqual(decode(b"\x80a"), [Key("unknown"), char("a")])
        # A lead byte whose sequence is broken: the breaking byte is decoded on its own.
        self.assertEqual(decode(b"\xe1\x84a"), [Key("unknown"), char("a")])
        # Well framed but overlong.
        self.assertEqual(decode(b"\xe0\x80\x80a"), [Key("unknown"), char("a")])

    def test_an_unfinished_character_is_settled_by_flush(self) -> None:
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed("한".encode()[:2]), [])
        self.assertEqual(decoder.flush(), [Key("unknown")])
        self.assertEqual(decoder.feed(b"a"), [char("a")])


class EscapeSequenceTests(unittest.TestCase):
    def test_csi_and_ss3_arrows(self) -> None:
        for prefix in (b"\x1b[", b"\x1bO"):
            with self.subTest(prefix=prefix):
                self.assertEqual(
                    decode(prefix + b"A" + prefix + b"B" + prefix + b"C" + prefix + b"D"),
                    [Key("up"), Key("down"), Key("right"), Key("left")],
                )

    def test_home_and_end_in_every_form(self) -> None:
        self.assertEqual(decode(b"\x1b[H\x1b[F\x1bOH\x1bOF"), [Key("home"), Key("end"), Key("home"), Key("end")])
        self.assertEqual(decode(b"\x1b[1~\x1b[4~\x1b[7~\x1b[8~"), [Key("home"), Key("end"), Key("home"), Key("end")])

    def test_editing_and_paging_keys(self) -> None:
        self.assertEqual(
            decode(b"\x1b[2~\x1b[3~\x1b[5~\x1b[6~"),
            [Key("insert"), Key("delete"), Key("pageup"), Key("pagedown")],
        )

    def test_modifier_forms(self) -> None:
        self.assertEqual(decode(b"\x1b[1;5C"), [Key("right", ctrl=True)])
        self.assertEqual(decode(b"\x1b[1;2A"), [Key("up", shift=True)])
        self.assertEqual(decode(b"\x1b[1;3D"), [Key("left", alt=True)])
        self.assertEqual(decode(b"\x1b[1;8B"), [Key("down", shift=True, alt=True, ctrl=True)])
        self.assertEqual(decode(b"\x1b[3;5~"), [Key("delete", ctrl=True)])
        self.assertEqual(decode(b"\x1b[1;5H"), [Key("home", ctrl=True)])

    def test_shift_tab(self) -> None:
        self.assertEqual(decode(b"\x1b[Z"), [Key("tab", shift=True)])

    def test_alt_chords(self) -> None:
        self.assertEqual(decode(b"\x1bb"), [char("b", alt=True)])
        self.assertEqual(decode(b"\x1bB"), [char("B", alt=True)])
        self.assertEqual(decode(b"\x1b\r"), [Key("enter", alt=True)])
        self.assertEqual(decode(b"\x1b\x7f"), [Key("backspace", alt=True)])
        self.assertEqual(decode("\x1b한".encode()), [char("한", alt=True)])

    def test_every_split_of_an_escape_sequence_agrees(self) -> None:
        # Not an Alt chord: split right after its ESC it is Esc and the key (`EscapeWaitTests`).
        for data in (b"\x1b[1;5C", b"\x1b[3~", b"\x1bOA", b"\x1b[Z", b"x\x1b[Ay"):
            with self.subTest(data=data):
                decode_split_everywhere(self, data)

    def test_unknown_sequences_never_raise(self) -> None:
        self.assertEqual(decode(b"\x1b[99~"), [Key("unknown")])
        self.assertEqual(decode(b"\x1b[1;5X"), [Key("unknown")])
        self.assertEqual(decode(b"\x1b[5A"), [Key("unknown")])
        self.assertEqual(decode(b"\x1b[1;2;3A"), [Key("unknown")])
        self.assertEqual(decode(b"\x1bOP"), [Key("unknown")])  # F1: not bound
        self.assertEqual(decode(b"\x1b[201~"), [Key("unknown")])  # a paste end with no start

    def test_an_osc_string_the_terminal_sends_is_one_unknown_key(self) -> None:
        # A background answer (OSC 11) that arrives after the startup query stopped waiting types nothing.
        for reply in (b"\x1b]11;rgb:ffff/ffff/ffff\x07", b"\x1b]11;rgb:1e1e/1e1e/1e1e\x1b\\"):
            with self.subTest(reply=reply):
                self.assertEqual(decode(reply + b"ab"), [Key("unknown"), char("a"), char("b")])
                # Split right after its ESC or its `ESC ]` too: the bytes held wait for the digit that opens it.
                self.assertEqual(decode_split_everywhere(self, reply), [Key("unknown")])

    def test_an_answer_split_after_its_bracket_with_its_rest_before_the_silence_types_nothing(self) -> None:
        reply = b"\x1b]11;rgb:1e1e/1e1e/1e1e\x07"
        for cut in (1, 2):  # after the ESC, after the `]`
            with self.subTest(cut=cut):
                now = [0.0]
                decoder = KeyDecoder(lambda: now[0])
                events = decoder.feed(reply[:cut])
                now[0] += 0.005  # the rest 5 ms later, inside the loop's silence window
                events += decoder.feed(reply[cut:])
                now[0] += 1.0
                self.assertEqual(events + decoder.flush(), [Key("unknown")])

    def test_alt_bracket_in_the_legacy_encoding_types_a_bracket_and_never_swallows_the_next_keys(self) -> None:
        # Alt+] with metaSendsEscape is `ESC ]`; no digit follows it, so it is no OSC string.
        now = [0.0]
        decoder = KeyDecoder(lambda: now[0])
        events = decoder.feed(b"\x1b]")
        now[0] += 0.02  # the next keys before the loop's silence flush
        events += decoder.feed(b"h")
        now[0] += 0.02
        events += decoder.feed(b"i") + decoder.flush()
        self.assertEqual(events, [char("]", alt=True), char("h"), char("i")])
        self.assertEqual(decode(b"\x1b]h"), [char("]", alt=True), char("h")])
        self.assertEqual(decode(b"\x1b]"), [char("]", alt=True)])  # at the silence

    def test_alt_bracket_at_the_end_of_a_read_waits_for_the_next_byte(self) -> None:
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1b]"), [])  # an answer's OSC number may be the next byte
        self.assertEqual(decoder.feed(b"x"), [char("]", alt=True), char("x")])
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1b]") + decoder.feed(b"11;rgb:0/0/0\x07"), [Key("unknown")])

    def test_an_osc_string_that_never_ends_is_dropped_whole(self) -> None:
        self.assertEqual(decode(b"\x1b]11;rgb:ff"), [Key("unknown")])
        events = decode(b"\x1b]" + b"1" * 600 + b"\x07x")
        self.assertEqual(events[0], Key("unknown"))
        self.assertEqual(events[-1], char("x"))
        self.assertLess(len(events), 600)  # cut off at its bound, not one key per byte

    def test_a_broken_sequence_hands_its_breaking_byte_on(self) -> None:
        self.assertEqual(decode(b"\x1b[1\x03"), [Key("unknown"), char("c", ctrl=True)])

    def test_a_runaway_sequence_is_cut_off(self) -> None:
        events = decode(b"\x1b[" + b"1" * 100 + b"A")
        self.assertEqual(events[0], Key("unknown"))
        self.assertEqual(events[-1], char("A"))


class LoneEscapeTests(unittest.TestCase):
    def test_a_lone_escape_waits_for_flush(self) -> None:
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1b"), [])
        self.assertEqual(decoder.flush(), [Key("escape")])
        self.assertEqual(decoder.flush(), [])

    def test_an_escape_that_turns_out_to_start_a_sequence(self) -> None:
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1b"), [])
        self.assertEqual(decoder.feed(b"[A"), [Key("up")])

    def test_double_escape_is_two_escapes(self) -> None:
        self.assertEqual(decode(b"\x1b\x1b"), [Key("escape"), Key("escape")])

    def test_escape_bracket_or_o_at_a_silence_is_an_alt_chord(self) -> None:
        self.assertEqual(decode(b"\x1b["), [char("[", alt=True)])
        self.assertEqual(decode(b"\x1bO"), [char("O", alt=True)])

    def test_an_unfinished_csi_at_a_silence_is_unknown(self) -> None:
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1b[1;"), [])
        self.assertEqual(decoder.flush(), [Key("unknown")])


class BracketedPasteTests(unittest.TestCase):
    def test_a_paste_is_one_event(self) -> None:
        self.assertEqual(decode(b"\x1b[200~hello world\x1b[201~"), [Paste("hello world")])

    def test_keys_around_a_paste_keep_their_order(self) -> None:
        self.assertEqual(
            decode(b"a\x1b[200~mid\x1b[201~\r"),
            [char("a"), Paste("mid"), Key("enter")],
        )

    def test_carriage_returns_inside_a_paste_become_newlines(self) -> None:
        self.assertEqual(decode(b"\x1b[200~one\r\ntwo\rthree\nfour\x1b[201~"), [Paste("one\ntwo\nthree\nfour")])

    def test_escape_sequences_inside_a_paste_are_text(self) -> None:
        self.assertEqual(decode(b"\x1b[200~x\x1b[Ay\x03\x1b[201~"), [Paste("x\x1b[Ay\x03")])

    def test_a_paste_spanning_chunks(self) -> None:
        data = "\x1b[200~줄 하나\r\n줄 둘\x1b[201~k".encode()
        events = decode_split_everywhere(self, data)
        self.assertEqual(events, [Paste("줄 하나\n줄 둘"), char("k")])

    def test_a_flush_before_the_paste_has_been_silent_long_does_not_end_it(self) -> None:
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1b[200~par"), [])
        self.assertEqual(decoder.flush(), [])
        self.assertEqual(decoder.feed(b"tial\x1b[201~"), [Paste("partial")])
        paused = PausedInput(reporting=False)
        paused.feed(b"\x1b[200~one ")
        paused.pause(PASTE_SETTLE_SECONDS - READ_SECONDS)
        paused.feed(b"two\x1b[201~")
        self.assertEqual(paused.events, [Paste("one two")])

    def test_a_paste_whose_end_marker_never_comes_settles_after_a_silence_and_keys_come_back(self) -> None:
        paused = PausedInput(reporting=False)
        paused.feed(b"\x1b[200~partial paste")
        paused.pause(PASTE_SETTLE_SECONDS - READ_SECONDS)
        self.assertEqual(paused.events, [])
        paused.pause(READ_SECONDS)
        self.assertEqual(paused.events, [Paste("partial paste")])
        paused.feed(b"k\x03")  # a key, then Ctrl+C: neither is swallowed as paste text any more
        self.assertEqual(paused.events[1:], [char("k"), char("c", ctrl=True)])

    def test_the_rest_of_a_stalled_paste_never_submits_and_its_late_end_marker_is_swallowed(self) -> None:
        paused = PausedInput(reporting=False)
        paused.feed(b"\x1b[200~first line\r")
        paused.pause(PASTE_SETTLE_SECONDS + READ_SECONDS)  # the watchdog gives the end marker up
        paused.feed(b"second\r\nthird")  # the rest of the paste, late
        paused.feed(b"\x03\x1b[201~")  # Ctrl+C is still a key; the end marker closes the window and is no key
        paused.feed(b"\r")  # after the end marker, Enter is Enter again
        self.assertEqual(
            paused.events,
            [Paste("first line\n"), *map(char, "second"), Paste("\n"), *map(char, "third"), char("c", ctrl=True),
             Key("enter")],
        )

    def test_a_rest_that_keeps_arriving_keeps_the_late_window_open(self) -> None:
        paused = PausedInput(reporting=False)
        paused.feed(b"\x1b[200~a")
        paused.pause(PASTE_SETTLE_SECONDS + READ_SECONDS)
        # A paste's rest arrives in chunks of several keys; past PASTE_LATE_SECONDS since the settle, never that
        # long without a chunk.
        for chunk in (b"bb", b"cc", b"dd\r"):
            paused.pause(PASTE_LATE_SECONDS * 0.6)
            paused.feed(chunk)
        self.assertEqual(paused.events, [Paste("a"), *map(char, "bbccdd"), Paste("\n")])

    def test_keys_typed_one_a_read_do_not_hold_the_late_window_open(self) -> None:
        paused = PausedInput(reporting=False)
        paused.feed(b"\x1b[200~pasted text")
        paused.pause(PASTE_SETTLE_SECONDS + READ_SECONDS)  # settled at 0.5 s: the window runs to 1.5 s
        for gap, data in ((0.3, b"o"), (0.15, b"k"), (0.15, b"\r"), (0.6, b"\r")):  # typed, one key a read
            paused.pause(gap)
            paused.feed(data)
        # The Enter at 1.15 s is still a line in the paste; the one at 1.75 s sends, though keys kept coming.
        self.assertEqual(paused.events, [Paste("pasted text"), char("o"), char("k"), Paste("\n"), Key("enter")])

    def test_a_carriage_return_after_the_late_window_is_enter(self) -> None:
        paused = PausedInput(reporting=False)
        paused.feed(b"\x1b[200~partial")
        paused.pause(PASTE_SETTLE_SECONDS + READ_SECONDS)
        paused.feed(b"x\r")  # inside the window: a newline
        paused.pause(PASTE_LATE_SECONDS + READ_SECONDS)
        paused.feed(b"\r")  # a second without a byte, and no end marker came: Enter
        paused.feed(b"\x1b[201~")  # a stray end marker outside the window is the unknown key it always was
        self.assertEqual(paused.events, [Paste("partial"), char("x"), Paste("\n"), Key("enter"), Key("unknown")])

    def test_an_open_paste_with_nothing_in_it_settles_as_nothing(self) -> None:
        paused = PausedInput(reporting=False)
        paused.feed(b"\x1b[200~")
        paused.pause(PASTE_SETTLE_SECONDS + READ_SECONDS)
        paused.feed(b"a")
        self.assertEqual(paused.events, [char("a")])

    def test_an_empty_paste(self) -> None:
        self.assertEqual(decode(b"\x1b[200~\x1b[201~"), [Paste("")])


def csi_u(code: int, modifiers: int | None = None) -> bytes:
    return f"\x1b[{code}u".encode() if modifiers is None else f"\x1b[{code};{modifiers}u".encode()


def modify_other_keys(code: int, modifiers: int) -> bytes:
    return f"\x1b[27;{modifiers};{code}~".encode()


SHIFT, ALT, CTRL = 2, 3, 5  # the modifier parameter: 1 + (shift 1 | alt 2 | ctrl 4)


class KeyboardProtocolTests(unittest.TestCase):
    """kitty CSI u and xterm modifyOtherKeys, which `Terminal` asks for on some terminals."""

    def assert_same_key(self, report: bytes, legacy: bytes) -> None:
        expected = decode(legacy)
        self.assertEqual(len(expected), 1, legacy)
        self.assertEqual(decode(report), expected, f"{report!r} must decode as {legacy!r} does")

    def test_every_ctrl_letter_decodes_as_its_control_byte(self) -> None:
        # Ctrl+C stays an interrupt, Ctrl+J a newline, and Ctrl+H, Ctrl+I, Ctrl+M stay
        # Backspace, Tab and Enter, exactly as without the protocol.
        for letter in "abcdefghijklmnopqrstuvwxyz":
            control = bytes([ord(letter) - 0x60])
            for report in (csi_u(ord(letter), CTRL), modify_other_keys(ord(letter), CTRL)):
                with self.subTest(report=report):
                    self.assert_same_key(report, control)
        self.assert_same_key(csi_u(ord("c"), CTRL), b"\x03")
        self.assert_same_key(modify_other_keys(ord("C"), CTRL + 1), b"\x03")  # xterm may send the shifted code

    def test_the_keys_legacy_bytes_already_have_decode_to_the_same_key(self) -> None:
        cases = {
            "Esc": (csi_u(27), b"\x1b"),
            "Enter": (csi_u(13), b"\r"),
            "Tab": (csi_u(9), b"\t"),
            "Shift+Tab": (csi_u(9, SHIFT), b"\x1b[Z"),
            "Shift+Tab (modifyOtherKeys)": (modify_other_keys(9, SHIFT), b"\x1b[Z"),
            "Backspace": (csi_u(127), b"\x7f"),
            "Alt+Backspace": (csi_u(127, ALT), b"\x1b\x7f"),
            "Alt+Enter": (csi_u(13, ALT), b"\x1b\r"),
            "Alt+b": (csi_u(ord("b"), ALT), b"\x1bb"),
            "Alt+b (modifyOtherKeys)": (modify_other_keys(ord("b"), ALT), b"\x1bb"),
            "Alt+Shift+b": (csi_u(ord("b"), ALT + 1), b"\x1bB"),
            "Ctrl+Alt+c": (csi_u(ord("c"), CTRL + 2), b"\x1b\x03"),
            "Ctrl+[ is Esc": (csi_u(ord("["), CTRL), b"\x1b"),
            "Ctrl+[ is Esc (modifyOtherKeys)": (modify_other_keys(ord("["), CTRL), b"\x1b"),
            "Ctrl+space": (csi_u(32, CTRL), b"\x00"),
            "Ctrl+@": (csi_u(ord("@"), CTRL), b"\x00"),
            "Ctrl+\\": (csi_u(ord("\\"), CTRL), b"\x1c"),
            "Ctrl+]": (csi_u(ord("]"), CTRL), b"\x1d"),
            "Ctrl+^": (csi_u(ord("^"), CTRL), b"\x1e"),
            "Ctrl+_": (csi_u(ord("_"), CTRL), b"\x1f"),
            "a": (csi_u(ord("a")), b"a"),
            "Shift+a": (csi_u(ord("a"), SHIFT), b"A"),
            "Shift+a (shifted key reported)": (b"\x1b[97:65;2u", b"A"),
            "Shift+1 (shifted key reported)": (b"\x1b[49:33;2u", b"!"),
            "Shift+a (modifyOtherKeys)": (modify_other_keys(ord("A"), SHIFT), b"A"),
            "Shift+space": (csi_u(32, SHIFT), b" "),
            "Shift+non-ASCII letter": (csi_u(ord("ф"), SHIFT), "Ф".encode()),
            "Ctrl+c with caps lock": (csi_u(ord("c"), 1 + 4 + 64), b"\x03"),
            "Ctrl+c with num lock": (csi_u(ord("c"), 1 + 4 + 128), b"\x03"),
            "Ctrl+c, press event": (b"\x1b[99;5:1u", b"\x03"),
            "Ctrl+c, repeat event": (b"\x1b[99;5:2u", b"\x03"),
            "Ctrl+c, base layout key": (b"\x1b[99::99;5u", b"\x03"),
            "keypad Enter": (csi_u(57414), b"\r"),
            "keypad 1": (csi_u(57400), b"1"),
            "keypad +": (csi_u(57413), b"+"),
        }
        for name, (report, legacy) in cases.items():
            with self.subTest(name):
                self.assert_same_key(report, legacy)

    def test_ctrl_with_a_digit_or_punctuation_decodes_as_the_control_byte_xterm_sends(self) -> None:
        # Ctrl+8 and Ctrl+? are DEL, so Backspace; Ctrl+3 is Esc, so it interrupts as Esc does.
        cases = {"2": b"\x00", "3": b"\x1b", "4": b"\x1c", "5": b"\x1d", "6": b"\x1e", "7": b"\x1f", "/": b"\x1f",
                 "8": b"\x7f", "?": b"\x7f"}
        for typed, legacy in cases.items():
            for report in (csi_u(ord(typed), CTRL), modify_other_keys(ord(typed), CTRL)):
                with self.subTest(report=report):
                    self.assert_same_key(report, legacy)
        self.assertEqual(decode(csi_u(ord("8"), CTRL)), [Key("backspace")])
        self.assertEqual(decode(csi_u(ord("3"), CTRL)), [Key("escape")])
        self.assert_same_key(csi_u(ord("8"), CTRL + 2), b"\x1b\x7f")  # with Alt, as ESC and the byte
        self.assert_same_key(csi_u(ord("2"), CTRL + 2), b"\x1b\x00")

    def test_a_ctrl_chord_xterm_sends_no_control_byte_for_stays_a_ctrl_chord(self) -> None:
        for typed in "190,.;'=-":
            with self.subTest(typed=typed):
                self.assertEqual(decode(csi_u(ord(typed), CTRL)), [char(typed, ctrl=True)])
        for code, typed in ((57399 + 2, "2"), (57399 + 8, "8"), (57410, "/")):  # keypad keys keep their Ctrl
            with self.subTest(keypad=typed):
                self.assertEqual(decode(csi_u(code, CTRL)), [char(typed, ctrl=True)])

    def test_ctrl_enter_and_shift_enter_are_keys_of_their_own(self) -> None:
        for report in (b"\x1b[13;5u", b"\x1b[27;5;13~"):
            with self.subTest(report=report):
                self.assertEqual(decode(report), [Key("enter", ctrl=True)])
        for report in (b"\x1b[13;2u", b"\x1b[27;2;13~"):
            with self.subTest(report=report):
                self.assertEqual(decode(report), [Key("enter", shift=True)])
        self.assertNotEqual(Key("enter", ctrl=True), Key("enter"))
        self.assertNotEqual(Key("enter", shift=True), Key("enter"))

    def test_every_split_of_a_report_agrees(self) -> None:
        for data in (b"\x1b[13;5u", b"\x1b[27;5;13~", b"\x1b[99;5u", b"\x1b[97:65;2u", b"\x1b[99;5:2u", b"x\x1b[27uy"):
            with self.subTest(data=data):
                decode_split_everywhere(self, data)

    def test_a_report_split_across_two_reads_waits_for_its_final_byte(self) -> None:
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1b[13;"), [])
        self.assertEqual(decoder.feed(b"5u"), [Key("enter", ctrl=True)])
        self.assertEqual(decoder.feed(b"\x1b[27;5;"), [])
        self.assertEqual(decoder.feed(b"99~"), [char("c", ctrl=True)])

    def test_malformed_and_unknown_reports_are_one_unknown_key_and_no_text(self) -> None:
        for data in (
            b"\x1b[99;9u",  # super: no place in Key, so not Ctrl or plain c
            b"\x1b[99;33u",  # meta
            b"\x1b[99;5:3u",  # a release is not a key
            b"\x1b[99;5:4u",  # no such event type
            b"\x1b[99;5:1:2u",
            b"\x1b[99;0u",
            b"\x1b[99;u",
            b"\x1b[;5u",
            b"\x1b[u",
            b"\x1b[99;5;99u",  # associated text: never asked for
            b"\x1b[99:65:99:1u",
            b"\x1b[99:=;2u",  # a sub-field that is not a number
            b"\x1b[1114112u",  # past the last code point
            b"\x1b[55296u",  # a surrogate
            b"\x1b[0u",
            b"\x1b[57441u",  # a modifier key on its own (kitty private use code point)
            b"\x1b[?u",  # a keyboard-flags answer with no flags
            b"\x1b[?1;2u",
            b"\x1b[>1u",
            b"\x1b[27;9;99~",
            b"\x1b[27;5;99:67~",
            b"\x1b[27;5;0~",
            b"\x1b[27;0;99~",
            b"\x1b[27;;99~",
        ):
            with self.subTest(data=data):
                self.assertEqual(decode(data), [Key("unknown")])
        self.assertEqual(decode(b"\x1b[99;9ua"), [Key("unknown"), char("a")])

    def test_any_parameters_with_a_u_final_are_exactly_one_key(self) -> None:
        # Whatever digits, colons and semicolons arrive, the report is one key: no byte of it is left over as text.
        generator = random.Random(2095)
        for _ in range(2000):
            parameters = "".join(generator.choice("0123456789:;") for _ in range(generator.randrange(0, 20)))
            data = f"\x1b[{parameters}u".encode()
            with self.subTest(data=data):
                self.assertEqual(len(decode(data)), 1)


class ProtocolReportedTests(unittest.TestCase):
    """Which form a key came in, and whether the terminal has sent one of the richer reports at all."""

    LEGACY = b"a\r\x03\t\x7f\x1b[A\x1b[1;5C\x1b[Z\x1b[3~\x1bOP\x1bb\x1b[200~pasted\x1b[201~\x1b[<0;3;4M"

    def test_legacy_bytes_never_say_the_reports_arrive(self) -> None:
        decoder = KeyDecoder()
        events = decoder.feed(self.LEGACY) + decoder.feed(b"\x1b") + decoder.flush()
        self.assertGreater(len(events), 10)
        self.assertFalse(any(getattr(event, "protocol", False) for event in events))
        self.assertFalse(decoder.protocol_reported)

    def test_the_first_csi_u_or_modify_other_keys_key_says_they_do(self) -> None:
        for report in (csi_u(ord("c"), CTRL), csi_u(27), csi_u(13, CTRL), modify_other_keys(ord("c"), CTRL),
                       modify_other_keys(13, CTRL), csi_u(9, SHIFT), b"\x1b[97:65;2u"):
            with self.subTest(report=report):
                decoder = KeyDecoder()
                decoder.feed(self.LEGACY)
                self.assertFalse(decoder.protocol_reported)
                (key,) = decoder.feed(report)
                self.assertTrue(key.protocol)
                self.assertTrue(decoder.protocol_reported)
                decoder.feed(self.LEGACY)
                self.assertTrue(decoder.protocol_reported)  # it stays on

    def test_the_form_is_not_part_of_the_key(self) -> None:
        reported, (legacy,) = decode(csi_u(ord("c"), CTRL))[0], decode(b"\x03")
        self.assertEqual(reported, legacy)
        self.assertEqual(hash(reported), hash(legacy))
        self.assertEqual(repr(reported), repr(legacy))
        self.assertTrue(reported.protocol)
        self.assertFalse(legacy.protocol)
        self.assertFalse(reported.reported_shift)
        self.assertFalse(legacy.reported_shift)

    def test_reported_shift_normalization_and_invariants(self) -> None:
        # CSI-u and modifyOtherKeys report Ctrl+Shift+N
        # modifier = 1 + 1 (shift) + 4 (ctrl) = 6
        csi_ctrl_shift_n = csi_u(ord("n"), 6)
        mok_ctrl_shift_n = modify_other_keys(ord("n"), 6)

        legacy_ctrl_n = decode(b"\x0e")[0]  # ord('n') - 0x60 = 14 = 0x0e
        for report in (csi_ctrl_shift_n, mok_ctrl_shift_n):
            with self.subTest(report=report):
                (key,) = decode(report)
                # Identity and legacy equality preserved
                self.assertEqual(key, legacy_ctrl_n)
                self.assertEqual(hash(key), hash(legacy_ctrl_n))
                self.assertEqual(repr(key), repr(legacy_ctrl_n))
                self.assertEqual(key.char, "n")
                self.assertTrue(key.ctrl)
                self.assertFalse(key.shift)
                self.assertTrue(key.protocol)
                self.assertTrue(key.reported_shift)

        # Unshifted Ctrl+n does NOT have reported_shift
        for report in (csi_u(ord("n"), CTRL), modify_other_keys(ord("n"), CTRL)):
            with self.subTest(report=report):
                (key,) = decode(report)
                self.assertEqual(key, legacy_ctrl_n)
                self.assertFalse(key.reported_shift)

        # Ctrl+j protocol reporting preserves newline / steer key identity and invariants
        csi_ctrl_j = csi_u(ord("j"), CTRL)
        csi_ctrl_shift_j = csi_u(ord("j"), 6)
        (key_j,) = decode(csi_ctrl_j)
        (key_shift_j,) = decode(csi_ctrl_shift_j)
        legacy_lf = decode(b"\n")[0]
        self.assertEqual(key_j, legacy_lf)
        self.assertEqual(key_shift_j, legacy_lf)
        self.assertFalse(key_j.reported_shift)
        self.assertTrue(key_shift_j.reported_shift)

        # Chunked / split feeds of protocol reports preserve reported_shift
        decode_split_everywhere(self, csi_ctrl_shift_n)
        decode_split_everywhere(self, mok_ctrl_shift_n)

        # Uppercase letter alone (e.g. Caps Lock) does NOT infer reported_shift
        # modifier 1 = bare/no modifiers
        (caps_n,) = decode(b"\x1b[78;1u")  # code 78 is 'N'
        self.assertEqual(caps_n.char, "N")
        self.assertFalse(caps_n.reported_shift)
        self.assertFalse(caps_n.shift)

    def test_a_kitty_flags_answer_is_no_key_and_says_so_only_with_disambiguate_on(self) -> None:
        # The answer to `CSI ? u`, which `Terminal.query_background` sends where it pushed the kitty flags.
        for answer, on in ((b"\x1b[?1u", True), (b"\x1b[?31u", True), (b"\x1b[?0u", False), (b"\x1b[?2u", False)):
            with self.subTest(answer=answer):
                decoder = KeyDecoder()
                self.assertEqual(decoder.feed(b"a" + answer + b"b"), [char("a"), char("b")])  # it types nothing
                self.assertIs(decoder.protocol_reported, on)
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1b[?") + decoder.feed(b"1u"), [])  # split across reads, as over SSH
        self.assertTrue(decoder.protocol_reported)
        decoder.feed(b"\x1b[?0u")  # a later answer with the flag off takes nothing back
        self.assertTrue(decoder.protocol_reported)

    def test_a_late_xtversion_answer_is_no_key_and_alt_p_stays_alt_p(self) -> None:
        # One unknown key, as an OSC answer is: it types nothing, whole or split across reads.
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"a\x1bP>|kitty(0.35.2)\x1b\\b"), [char("a"), Key("unknown"), char("b")])
        split = decoder.feed(b"\x1bP") + decoder.feed(b">|WezTerm\x07") + decoder.feed(b"c")
        self.assertEqual(split, [Key("unknown"), char("c")])
        self.assertEqual(decode(b"\x1bPx"), [Key("char", "P", alt=True), char("x")])
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1bP") + decoder.flush(), [Key("char", "P", alt=True)])
        # An answer split right after its ESC: the next read goes on with it, so none of its bytes are typed.
        decoder = KeyDecoder()
        events = decoder.feed(b"\x1b") + decoder.feed(b"P>|kitty(0.35.2)\x1b\\") + decoder.flush()
        self.assertEqual(events, [Key("unknown")])

    def test_a_report_that_decodes_to_no_key_says_nothing(self) -> None:
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1b[99;9u\x1b[99;5:3u\x1b[27;9;99~"), [Key("unknown")] * 3)
        self.assertFalse(decoder.protocol_reported)


def sgr_mouse(code: int, x: int, y: int, pressed: bool = True) -> bytes:
    return f"\x1b[<{code};{x};{y}{'M' if pressed else 'm'}".encode()


class MouseReportTests(unittest.TestCase):
    """SGR mouse reports (`ESC[<b;x;yM` / `m`), which `Terminal.set_mouse(True)` turns on."""

    def test_a_left_click_is_a_press_then_a_release_at_1_based_cells(self) -> None:
        self.assertEqual(
            decode(sgr_mouse(0, 10, 5) + sgr_mouse(0, 10, 5, pressed=False)),
            [Mouse(BUTTON_LEFT, 10, 5, pressed=True), Mouse(BUTTON_LEFT, 10, 5, pressed=False)],
        )
        # The top-left cell is (1, 1), as the terminal reports it.
        self.assertEqual(decode(sgr_mouse(0, 1, 1)), [Mouse(BUTTON_LEFT, 1, 1)])

    def test_each_button(self) -> None:
        for code, button in ((0, BUTTON_LEFT), (1, BUTTON_MIDDLE), (2, BUTTON_RIGHT)):
            with self.subTest(button=button):
                self.assertEqual(decode(sgr_mouse(code, 3, 4)), [Mouse(button, 3, 4)])
                self.assertEqual(decode(sgr_mouse(code, 3, 4, pressed=False)), [Mouse(button, 3, 4, pressed=False)])
        # A release that does not say which button (low bits 3).
        self.assertEqual(decode(sgr_mouse(3, 3, 4, pressed=False)), [Mouse(NO_BUTTON, 3, 4, pressed=False)])

    def test_modifiers(self) -> None:
        cases = {
            4: Mouse(BUTTON_LEFT, 7, 8, shift=True),
            8: Mouse(BUTTON_LEFT, 7, 8, alt=True),
            16: Mouse(BUTTON_LEFT, 7, 8, ctrl=True),
            4 + 8 + 16: Mouse(BUTTON_LEFT, 7, 8, shift=True, alt=True, ctrl=True),
            2 + 16: Mouse(BUTTON_RIGHT, 7, 8, ctrl=True),
            1 + 4: Mouse(BUTTON_MIDDLE, 7, 8, shift=True),
        }
        for code, expected in cases.items():
            with self.subTest(code=code):
                self.assertEqual(decode(sgr_mouse(code, 7, 8)), [expected])

    def test_the_wheel(self) -> None:
        cases = {
            64: Mouse(WHEEL_UP, 5, 6),
            65: Mouse(WHEEL_DOWN, 5, 6),
            66: Mouse(WHEEL_LEFT, 5, 6),
            67: Mouse(WHEEL_RIGHT, 5, 6),
            64 + 16: Mouse(WHEEL_UP, 5, 6, ctrl=True),
            65 + 4: Mouse(WHEEL_DOWN, 5, 6, shift=True),
        }
        for code, expected in cases.items():
            with self.subTest(code=code):
                self.assertEqual(decode(sgr_mouse(code, 5, 6)), [expected])

    def test_motion(self) -> None:
        cases = {
            32: Mouse(BUTTON_LEFT, 9, 2, motion=True),  # a drag
            34: Mouse(BUTTON_RIGHT, 9, 2, motion=True),
            35: Mouse(NO_BUTTON, 9, 2, motion=True),  # the pointer moving with no button held
            35 + 16: Mouse(NO_BUTTON, 9, 2, motion=True, ctrl=True),
        }
        for code, expected in cases.items():
            with self.subTest(code=code):
                self.assertEqual(decode(sgr_mouse(code, 9, 2)), [expected])

    def test_large_coordinates(self) -> None:
        # SGR exists for this: the legacy form cannot say a column past 223.
        self.assertEqual(decode(sgr_mouse(0, 224, 100)), [Mouse(BUTTON_LEFT, 224, 100)])
        self.assertEqual(decode(sgr_mouse(0, 1000, 500)), [Mouse(BUTTON_LEFT, 1000, 500)])
        self.assertEqual(decode(sgr_mouse(2, 65535, 65535, pressed=False)), [Mouse(BUTTON_RIGHT, 65535, 65535, pressed=False)])

    def test_keys_around_a_report_keep_their_order(self) -> None:
        self.assertEqual(
            decode(b"a" + sgr_mouse(0, 2, 3) + b"\r" + sgr_mouse(64, 2, 3) + b"\x1b[A"),
            [char("a"), Mouse(BUTTON_LEFT, 2, 3), Key("enter"), Mouse(WHEEL_UP, 2, 3), Key("up")],
        )

    def test_every_split_of_a_report_agrees(self) -> None:
        cases = {
            sgr_mouse(0, 10, 5): [Mouse(BUTTON_LEFT, 10, 5)],
            sgr_mouse(0, 10, 5, pressed=False): [Mouse(BUTTON_LEFT, 10, 5, pressed=False)],
            sgr_mouse(28, 1234, 567): [Mouse(BUTTON_LEFT, 1234, 567, shift=True, alt=True, ctrl=True)],
            sgr_mouse(65, 80, 24): [Mouse(WHEEL_DOWN, 80, 24)],
            sgr_mouse(35, 3, 3): [Mouse(NO_BUTTON, 3, 3, motion=True)],
            b"x" + sgr_mouse(2, 40, 12) + b"y": [char("x"), Mouse(BUTTON_RIGHT, 40, 12), char("y")],
            sgr_mouse(0, 1, 1) + sgr_mouse(0, 1, 1, pressed=False): [
                Mouse(BUTTON_LEFT, 1, 1),
                Mouse(BUTTON_LEFT, 1, 1, pressed=False),
            ],
        }
        for data, expected in cases.items():
            with self.subTest(data=data):
                self.assertEqual(decode_split_everywhere(self, data), expected)

    def test_a_report_split_across_two_reads_waits_for_its_final_byte(self) -> None:
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1b[<0;10"), [])
        self.assertEqual(decoder.feed(b";5"), [])
        self.assertEqual(decoder.feed(b"M"), [Mouse(BUTTON_LEFT, 10, 5)])

    def test_malformed_reports_are_one_unknown_key_and_no_text(self) -> None:
        for data in (
            b"\x1b[<0;1M",  # a field missing
            b"\x1b[<0M",
            b"\x1b[<M",
            b"\x1b[<m",
            b"\x1b[<;1;1M",  # an empty field
            b"\x1b[<0;;1M",
            b"\x1b[<0;1;M",
            b"\x1b[<0;1;1;1M",  # a field too many
            b"\x1b[<0;1:2;3M",  # a sub-field
            b"\x1b[<0;-1;3M",  # a sign
            b"\x1b[<0;1;1 M",  # an intermediate byte
            b"\x1b[<<0;1;1M",
            b"\x1b[<0;=;1m",
            b"\x1b[<0;0;1M",  # cells start at 1
            b"\x1b[<0;1;0M",
            b"\x1b[<128;1;1M",  # buttons 8 to 11 have no name
            b"\x1b[<131;1;1m",
            b"\x1b[<99999999999;1;1M",  # a huge button code
            b"\x1b[<4294967296;1;1M",  # 2**32: its low bits are a left button, the rest is not
            b"\x1b[<0;1;1~",  # not a mouse final byte
            b"\x1b[<0;1;1u",
            b"\x1b[0;1;1M",  # no SGR marker
        ):
            with self.subTest(data=data):
                self.assertEqual(decode(data), [Key("unknown")])
        self.assertEqual(decode(b"\x1b[<0;1Ma"), [Key("unknown"), char("a")])

    def test_huge_coordinates_are_one_event_and_no_text(self) -> None:
        events = decode(b"\x1b[<0;99999999999999999999;7Mz")
        self.assertEqual(events, [Mouse(BUTTON_LEFT, 99999999999999999999, 7), char("z")])

    def test_a_report_inside_a_paste_is_text(self) -> None:
        self.assertEqual(decode(b"\x1b[200~x\x1b[<0;1;1My\x1b[201~"), [Paste("x\x1b[<0;1;1My")])

    def test_any_parameters_after_the_sgr_marker_are_exactly_one_event(self) -> None:
        # Whatever digits and semicolons arrive, the report is one event: no byte of it is left over as text.
        generator = random.Random(1006)
        for _ in range(2000):
            parameters = "".join(generator.choice("0123456789;") for _ in range(generator.randrange(0, 24)))
            data = f"\x1b[<{parameters}{generator.choice('Mm')}".encode()
            with self.subTest(data=data):
                self.assertEqual(len(decode(data)), 1)


READ_SECONDS = 0.05  # the loop's read timeout: it runs `flush` after every read that brought nothing


class PausedInput:
    """Bytes fed to a decoder on a test clock, with the loop's `flush` after each empty read of a pause."""

    def __init__(self, reporting: bool, off_at: float | None = None) -> None:
        self.now = 0.0
        self.reporting = reporting
        self.off_at = off_at  # when reporting last went off, as the loop passes it
        self.decoder = KeyDecoder(lambda: self.now)
        self.events: list = []

    def feed(self, data: bytes) -> None:
        self.events += self.decoder.feed(data)

    def pause(self, seconds: float) -> None:
        """`seconds` without a byte: a flush at the end of every whole read in it, then the rest of the time."""
        end = self.now + seconds
        while self.now + READ_SECONDS <= end + 1e-9:
            self.now += READ_SECONDS
            self.events += self.decoder.flush(self.reporting, self.off_at)
        self.now = end


class SplitReportTests(unittest.TestCase):
    """A report a pause splits across two reads, as SSH jitter does: none of it is ever typed."""

    REPORT = sgr_mouse(65, 12, 40)  # a wheel turn, the report the review split
    DECODED = Mouse(WHEEL_DOWN, 12, 40)

    def split(self, cut: int, pause: float, reporting: bool = True) -> list:
        paused = PausedInput(reporting)
        paused.feed(self.REPORT[:cut])
        paused.pause(pause)
        paused.feed(self.REPORT[cut:])
        paused.pause(2.0)
        return paused.events

    def test_a_60_ms_pause_at_any_split_still_gives_the_report(self) -> None:
        for cut in range(1, len(self.REPORT)):
            with self.subTest(cut=self.REPORT[:cut]):
                self.assertEqual(self.split(cut, 0.06), [self.DECODED])

    def test_a_400_ms_pause_gives_the_report_from_the_marker_on_and_types_nothing_before_it(self) -> None:
        # Before `<` nothing says it is a report: ESC waits 300 ms and is then Esc, `ESC[` one unknown key,
        # and the rest that follows is dropped. From `<` on it waits 500 ms, so the report arrives whole.
        for cut in range(1, len(self.REPORT)):
            with self.subTest(cut=self.REPORT[:cut]):
                expected = {1: [Key("escape")], 2: [Key("unknown")]}.get(cut, [self.DECODED])
                self.assertEqual(self.split(cut, 0.4), expected)

    def test_past_500_ms_a_started_report_is_one_unknown_key_and_its_tail_is_dropped(self) -> None:
        for cut in range(3, len(self.REPORT)):
            for pause in (0.6, 0.95):
                with self.subTest(cut=self.REPORT[:cut], pause=pause):
                    self.assertEqual(self.split(cut, pause), [Key("unknown")])

    def test_a_started_report_waits_with_reporting_off_too(self) -> None:
        # Reports already on their way when reporting goes off still arrive.
        for cut in range(3, len(self.REPORT)):
            with self.subTest(cut=self.REPORT[:cut]):
                self.assertEqual(self.split(cut, 0.4, reporting=False), [self.DECODED])
                self.assertEqual(self.split(cut, 0.6, reporting=False), [Key("unknown")])

    def test_no_split_and_no_pause_inside_the_window_types_anything(self) -> None:
        # The window ends 500 ms after the start settles: at 0.8 s for ESC and `ESC[` (settled at 300 ms),
        # at 1.0 s for a report past its `<` (settled at 500 ms).
        for cut in range(1, len(self.REPORT)):
            window = 0.8 if cut < 3 else 1.0
            for pause in (0.01, 0.05, 0.06, 0.2, 0.29, 0.31, 0.4, 0.49, 0.51, 0.6, 0.79, 0.95, 0.99):
                if pause >= window:
                    continue
                with self.subTest(cut=self.REPORT[:cut], pause=pause):
                    events = self.split(cut, pause)
                    self.assertEqual(len(events), 1, events)
                    self.assertNotEqual(events[0].name if isinstance(events[0], Key) else "", "char", events)

    def test_a_key_that_cannot_finish_the_report_is_a_key(self) -> None:
        paused = PausedInput(reporting=True)
        paused.feed(b"\x1b[<65;12")
        paused.pause(0.6)
        paused.feed(b"x\x1b[A")
        self.assertEqual(paused.events, [Key("unknown"), char("x"), Key("up")])
        paused = PausedInput(reporting=True)
        paused.feed(b"\x1b")
        paused.pause(0.35)
        paused.feed(b"[a")  # after Esc, `[` and a letter: not a report's rest
        self.assertEqual(paused.events, [Key("escape"), char("["), char("a")])

    def test_once_the_window_has_closed_keys_type_again(self) -> None:
        paused = PausedInput(reporting=True)
        paused.feed(b"\x1b[<65;12")
        paused.pause(1.1)  # dropped at 0.5 s, the window closed at 1.0 s
        paused.feed(b";4")
        self.assertEqual(paused.events, [Key("unknown"), char(";"), char("4")])

    def test_a_rest_cut_off_by_the_window_is_dropped_once_it_reached_the_marker(self) -> None:
        paused = PausedInput(reporting=True)
        paused.feed(b"\x1b")
        paused.pause(0.35)  # Esc
        paused.feed(b"[<65")
        paused.pause(1.0)
        self.assertEqual(paused.events, [Key("escape")])
        paused = PausedInput(reporting=True)
        paused.feed(b"\x1b")
        paused.pause(0.35)
        paused.feed(b"[")  # no `<` yet: it may be the bracket key, so it is one
        paused.pause(1.0)
        self.assertEqual(paused.events, [Key("escape"), char("[")])


class EscapeTimeTests(unittest.TestCase):
    """A lone ESC: at the first silence with mouse reporting off, after 300 ms with it on."""

    def escape(self, reporting: bool, pause: float) -> list:
        paused = PausedInput(reporting)
        paused.feed(b"\x1b")
        paused.pause(pause)
        return paused.events

    def test_with_reporting_off_it_is_esc_at_50_ms(self) -> None:
        self.assertEqual(self.escape(False, 0.05), [Key("escape")])
        self.assertEqual(self.escape(False, 0.35), [Key("escape")])

    def test_with_reporting_on_it_is_nothing_yet_at_50_ms_and_esc_at_350_ms(self) -> None:
        self.assertEqual(self.escape(True, 0.05), [])
        self.assertEqual(self.escape(True, 0.25), [])
        self.assertEqual(self.escape(True, 0.35), [Key("escape")])

    def test_an_escape_bracket_with_reporting_on_waits_too_and_is_then_no_key(self) -> None:
        paused = PausedInput(reporting=True)
        paused.feed(b"\x1b[")
        paused.pause(0.25)
        self.assertEqual(paused.events, [])
        paused.pause(0.1)
        self.assertEqual(paused.events, [Key("unknown")])

    def test_a_second_escape_inside_the_window_is_its_own_esc(self) -> None:
        paused = PausedInput(reporting=True)
        paused.feed(b"\x1b")
        paused.pause(0.35)
        paused.feed(b"\x1b")
        paused.pause(0.35)
        self.assertEqual(paused.events, [Key("escape"), Key("escape")])


class ReportsAfterTheOffTests(unittest.TestCase):
    """Reports sent before the terminal acted on an off arrive after it: for half a second they are held as if it were on."""

    RELEASE = sgr_mouse(0, 5, 5, pressed=False)  # the release of the click that opened a log
    DECODED = Mouse(BUTTON_LEFT, 5, 5, pressed=False)

    def split(self, cut: int, pause: float, started: float) -> list:
        """The release, split at `cut` by `pause`, starting `started` seconds after reporting went off at 0."""
        paused = PausedInput(reporting=False, off_at=0.0)
        paused.now = started
        paused.feed(self.RELEASE[:cut])
        paused.pause(pause)
        paused.feed(self.RELEASE[cut:])
        paused.pause(2.0)
        return paused.events

    def test_within_the_grace_every_split_types_nothing(self) -> None:
        for started in (0.0, 0.2, 0.45):
            for cut in range(1, len(self.RELEASE)):
                for pause in (0.06, 0.2, 0.4):
                    with self.subTest(started=started, cut=self.RELEASE[:cut], pause=pause):
                        events = self.split(cut, pause, started)
                        self.assertEqual(len(events), 1, events)
                        self.assertNotEqual(events[0].name if isinstance(events[0], Key) else "", "char", events)
                        if pause < 0.3 or cut >= 3:
                            self.assertEqual(events, [self.DECODED])

    def test_the_grace_counts_from_when_the_report_started_not_when_it_is_settled(self) -> None:
        # Its ESC arrived 0.45 s after the off; the silence that would settle it ends past 0.5 s.
        self.assertEqual(self.split(1, 0.2, 0.45), [self.DECODED])

    def test_a_byte_that_joins_a_held_escape_does_not_move_when_the_report_started(self) -> None:
        # Its ESC came 0.45 s after the off and its `[` at 0.6 s: the report started inside the grace, so
        # `ESC[` still waits and the rest finishes it, though the `[` alone came after the grace.
        paused = PausedInput(reporting=False, off_at=0.0)
        paused.now = 0.45
        paused.feed(self.RELEASE[:1])
        paused.pause(0.15)
        paused.feed(self.RELEASE[1:2])
        paused.pause(0.1)
        paused.feed(self.RELEASE[2:])
        paused.pause(2.0)
        self.assertEqual(paused.events, [self.DECODED])

    def test_an_escape_that_arrived_while_reporting_was_on_waits_though_it_is_off_now(self) -> None:
        paused = PausedInput(reporting=False, off_at=0.01)
        paused.feed(b"\x1b")  # at 0: reporting was still on
        paused.pause(0.2)
        paused.feed(self.RELEASE[1:])
        self.assertEqual(paused.events, [self.DECODED])

    def test_a_tail_left_by_a_later_read_is_timed_from_that_read(self) -> None:
        # An ESC from while reporting was on, then 0.6 s of reads with no silence: the ESC left at the end
        # came 0.55 s after the off, so it is Esc at the first silence, not held as the first one would be.
        paused = PausedInput(reporting=False, off_at=0.05)
        paused.feed(b"\x1b")
        paused.now = 0.6
        paused.feed(b"x\x1b")
        paused.pause(0.05)
        self.assertEqual(paused.events, [Key("escape"), char("x"), Key("escape")])

    def test_a_report_that_starts_after_the_grace_and_splits_before_its_marker_is_keys(self) -> None:
        events = self.split(1, 0.06, MOUSE_REPORT_SECONDS)
        self.assertEqual(events, [Key("escape"), *(char(c) for c in self.RELEASE[1:].decode())])

    def test_a_lone_escape_long_after_the_off_is_esc_at_the_first_silence(self) -> None:
        paused = PausedInput(reporting=False, off_at=0.0)
        paused.now = 0.6
        paused.feed(b"\x1b")
        paused.pause(0.05)
        self.assertEqual(paused.events, [Key("escape")])


class EscapeWaitTests(unittest.TestCase):
    """The 300 ms an ESC waits for a report's `[`: a key typed after it ends the wait, and stays its own key."""

    def test_a_key_read_after_a_waiting_escape_ends_the_wait_and_is_its_own_key(self) -> None:
        for reporting, off_at in ((True, None), (False, 0.0)):
            with self.subTest(reporting=reporting):
                paused = PausedInput(reporting, off_at)
                paused.feed(b"\x1b")
                paused.pause(0.2)
                self.assertEqual(paused.events, [])
                paused.feed(b"n")
                self.assertEqual(paused.events, [Key("escape"), char("n")])
                paused.feed(b"\x1b")
                paused.pause(0.1)
                paused.feed(b"\x1b[A")  # another ESC first: Esc, then the arrow
                self.assertEqual(paused.events[2:], [Key("escape"), Key("up")])

    def test_escape_and_a_key_in_one_read_stay_an_alt_chord(self) -> None:
        paused = PausedInput(reporting=True)
        paused.feed(b"\x1bn")
        paused.pause(0.4)
        self.assertEqual(paused.events, [char("n", alt=True)])

    def test_a_later_read_that_starts_with_the_bracket_goes_on_with_the_sequence(self) -> None:
        paused = PausedInput(reporting=True)
        paused.feed(b"\x1b")
        paused.pause(0.2)
        paused.feed(b"[<0;5;5M")
        paused.pause(1.0)
        self.assertEqual(paused.events, [Mouse(BUTTON_LEFT, 5, 5)])
        paused = PausedInput(reporting=True)
        paused.feed(b"\x1b")
        paused.pause(0.2)
        paused.feed(b"[A")
        self.assertEqual(paused.events, [Key("up")])

    def test_an_ss3_key_split_after_its_escape_goes_on_with_the_sequence(self) -> None:
        # F1 to F4 (no key the TUI names), then the arrows, Home and End in application cursor mode: every final.
        cases = {b"OP": Key("unknown"), b"OQ": Key("unknown"), b"OR": Key("unknown"), b"OS": Key("unknown"),
                 b"OA": Key("up"), b"OB": Key("down"), b"OC": Key("right"), b"OD": Key("left"),
                 b"OH": Key("home"), b"OF": Key("end")}
        for reporting, off_at in ((True, None), (False, 0.0)):
            for rest, key in cases.items():
                with self.subTest(reporting=reporting, rest=rest):
                    paused = PausedInput(reporting, off_at)
                    paused.feed(b"\x1b")
                    paused.pause(0.2)
                    paused.feed(rest)
                    paused.pause(1.0)
                    self.assertEqual(paused.events, [key])

    def test_a_capital_o_typed_after_a_waiting_escape_is_esc_then_the_o(self) -> None:
        # A read that is a lone `O`, or `O` and a byte no SS3 key ends with, is typed: Esc, then its characters.
        # So is a lone `]`, or `]` and anything but the digit an answer's OSC string goes on with.
        for rest in (b"O", b"Ok", b"n", b"]", b"]x"):
            with self.subTest(rest=rest):
                paused = PausedInput(reporting=True)
                paused.feed(b"\x1b")
                paused.pause(0.2)
                paused.feed(rest)
                self.assertEqual(paused.events, [Key("escape"), *(char(c) for c in rest.decode())])

    def test_without_a_silence_an_escape_split_from_its_key_is_esc_and_the_key(self) -> None:
        # Esc, then a key read before the loop's next silence: both act, whether or not a flush ran between.
        cases = {b"n": [Key("escape"), char("n")], b"/x": [Key("escape"), char("/"), char("x")],
                 b"\r": [Key("escape"), Key("enter")],  # an Alt+Enter the kernel split this way is Esc and Enter
                 b"[A": [Key("up")], b"OA": [Key("up")]}  # a read that goes on with a sequence still does
        for rest, keys in cases.items():
            with self.subTest(rest=rest):
                decoder = KeyDecoder()
                self.assertEqual(decoder.feed(b"\x1b") + decoder.feed(rest), keys)


class ArrivalTests(unittest.TestCase):
    """Each key carries when its first byte arrived, however long the decoder held it before deciding."""

    def arrivals(self, events: list) -> list:
        return [(event, round(event.arrived_at, 9)) for event in events]

    def test_an_escape_held_for_a_report_carries_its_arrival_not_its_settling(self) -> None:
        paused = PausedInput(reporting=True)
        paused.now = 0.1
        paused.feed(b"\x1b")
        paused.pause(0.35)
        self.assertEqual(self.arrivals(paused.events), [(Key("escape"), 0.1)])

    def test_a_key_split_after_its_escape_carries_the_escapes_arrival_and_the_next_key_its_own(self) -> None:
        paused = PausedInput(reporting=True)
        paused.feed(b"\x1b")
        paused.pause(0.2)
        paused.feed(b"[Cx")
        self.assertEqual(self.arrivals(paused.events), [(Key("right"), 0.0), (char("x"), 0.2)])

    def test_an_escape_a_later_key_ends_carries_its_own_arrival(self) -> None:
        paused = PausedInput(reporting=False, off_at=0.0)
        paused.now = 0.1
        paused.feed(b"\x1b")
        paused.pause(0.2)
        paused.feed(b"n")
        self.assertEqual(self.arrivals(paused.events), [(Key("escape"), 0.1), (char("n"), 0.3)])

    def test_a_key_after_the_rest_of_a_settled_report_carries_its_own_read(self) -> None:
        paused = PausedInput(reporting=True)
        paused.feed(b"\x1b")
        paused.pause(0.35)  # Esc
        paused.now = 0.4
        paused.feed(b"[<0")  # the report's rest, held
        paused.now = 0.5
        paused.feed(b";5;5mx")  # its end, dropped, and a key
        self.assertEqual(self.arrivals(paused.events), [(Key("escape"), 0.0), (char("x"), 0.5)])

    def test_an_escape_left_after_the_rest_of_a_settled_report_carries_its_own_read(self) -> None:
        # The rest's `[` came at 0.36 and was dropped with the rest at 0.84: the ESC after it came at 0.84.
        now = [0.0]
        decoder = KeyDecoder(lambda: now[0])
        events = decoder.feed(b"\x1b")
        now[0] = 0.35
        events += decoder.flush(True)  # Esc, its report's rest dropped while it arrives
        now[0] = 0.36
        events += decoder.feed(b"[")
        now[0] = 0.84
        events += decoder.feed(b"<0;5;5m\x1b")
        now[0] = 1.2
        events += decoder.flush(True)
        self.assertEqual(self.arrivals(events), [(Key("escape"), 0.0), (Key("escape"), 0.84)])

    def test_a_key_decided_at_once_carries_the_read_it_came_in(self) -> None:
        now = [7.0]
        decoder = KeyDecoder(lambda: now[0])
        self.assertEqual(self.arrivals(decoder.feed(b"a\r")), [(char("a"), 7.0), (Key("enter"), 7.0)])
        decoder.feed(b"\x1b")
        now[0] = 7.05
        self.assertEqual(self.arrivals(decoder.flush()), [(Key("escape"), 7.0)])


class LegacyMouseReportTests(unittest.TestCase):
    """`ESC[M` and three bytes: what a terminal that ignores the SGR request sends instead."""

    def test_a_legacy_report_is_one_unknown_key(self) -> None:
        # A left press at (1, 1) and its release: each byte is 32 plus the value.
        self.assertEqual(decode(b"\x1b[M !!\x1b[M#!!"), [Key("unknown"), Key("unknown")])
        self.assertEqual(decode(b"\x1b[M`!!a"), [Key("unknown"), char("a")])  # wheel up
        self.assertEqual(decode(b"\x1b[M \xff\xff"), [Key("unknown")])  # far cells: bytes past ASCII

    def test_every_split_of_a_legacy_report_agrees(self) -> None:
        cases = {
            b"\x1b[M !!": [Key("unknown")],
            b"a\x1b[M#*+b": [char("a"), Key("unknown"), char("b")],
            # Payload bytes that happen to spell a UTF-8 character are still payload.
            b"\x1b[M \xc3\xa9": [Key("unknown")],
        }
        for data, expected in cases.items():
            with self.subTest(data=data):
                self.assertEqual(decode_split_everywhere(self, data), expected)

    def test_a_control_byte_where_the_payload_belongs_starts_the_next_key(self) -> None:
        self.assertEqual(decode(b"\x1b[M\x1b[A"), [Key("unknown"), Key("up")])
        # Not a report, so the bytes after ESC[M are keys of their own.
        self.assertEqual(decode(b"\x1b[M \x03"), [Key("unknown"), char(" "), char("c", ctrl=True)])
        self.assertEqual(decode(b"\x1b[M\x1b[200~p\x1b[201~"), [Key("unknown"), Paste("p")])

    def test_a_legacy_report_split_across_reads_waits_and_a_silence_settles_it(self) -> None:
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1b[M"), [])
        self.assertEqual(decoder.feed(b" !"), [])
        self.assertEqual(decoder.feed(b"!x"), [Key("unknown"), char("x")])
        self.assertEqual(decoder.feed(b"\x1b[M "), [])
        self.assertEqual(decoder.flush(), [Key("unknown")])
        self.assertEqual(decode(b"\x1b[M"), [Key("unknown")])


class RobustnessTests(unittest.TestCase):
    def test_random_bytes_in_random_chunks_never_raise(self) -> None:
        generator = random.Random(2084)
        alphabet = [bytes([value]) for value in range(256)] + [b"\x1b[", b"\x1b[200~", b"\x1b[201~", b"\x1bO", b"\x1b[<", b"\x1b[M"]
        for _ in range(500):
            decoder = KeyDecoder()
            for _ in range(generator.randrange(1, 8)):
                chunk = b"".join(generator.choice(alphabet) for _ in range(generator.randrange(0, 12)))
                for event in decoder.feed(chunk):
                    self.assertIsInstance(event, (Key, Paste, Mouse))
            for event in decoder.flush():
                self.assertIsInstance(event, (Key, Paste, Mouse))


if __name__ == "__main__":
    unittest.main()
