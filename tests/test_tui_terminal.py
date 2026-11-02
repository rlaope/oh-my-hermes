"""The OMH TUI's tty layer (`omh.tui.terminal`).

`terminal_supported` decides between the OMH TUI and the fallback, so its
matrix is pinned with fake streams. `Terminal` is the one piece that touches a
real tty, so it runs against a pty: raw mode must make Ctrl+C a byte rather
than a signal, and the saved attributes must come back on every exit path,
including an exception and a window that closed under it.

Every read of the pty master is bounded, and nobody reads the master while a
`Terminal` changes modes: entering and leaving use TCSANOW, which does not
wait for output to drain, so the fixture cannot hang on its own buffer.
"""

from __future__ import annotations

import os
import select
import signal
import threading
import time
import unittest
from unittest.mock import patch

from omh.tui import terminal as terminal_module
from omh.tui.keys import BUTTON_LEFT, KeyDecoder, Mouse
from omh.tui.screen import CURSOR_SHAPE_BEAM, CURSOR_SHAPE_BLOCK, CURSOR_SHAPE_DEFAULT
from omh.tui.terminal import (
    BRACKETED_PASTE_OFF,
    BRACKETED_PASTE_ON,
    KITTY_KEYBOARD_POP,
    KITTY_KEYBOARD_PUSH,
    KITTY_KEYBOARD_QUERY,
    XTVERSION_QUERY,
    MODIFY_OTHER_KEYS_OFF,
    MODIFY_OTHER_KEYS_ON,
    MOUSE_DRAG_OFF,
    MOUSE_DRAG_ON,
    MOUSE_REPORTING_OFF,
    MOUSE_REPORTING_ON,
    BACKGROUND_QUERY,
    BACKGROUND_QUERY_SECONDS,
    CURSOR_POSITION_QUERY,
    DEVICE_ATTRIBUTES_QUERY,
    RESTORE_SEQUENCE,
    Terminal,
    background_from_colorfgbg,
    colorfgbg_names_dark,
    keyboard_protocol_request,
    split_background_replies,
    split_cursor_reply,
    terminal_blocker,
    terminal_supported,
)

try:  # POSIX only; Windows has no pty and no termios.
    import pty
    import termios
except ImportError:  # pragma: no cover - exercised by the skip below
    pty = None
    termios = None

_IFLAG = 0
_OFLAG = 1
_LFLAG = 3
_READ_WATCHDOG_SECONDS = 2.0


class _Stream:
    def __init__(self, tty: bool = True, error: Exception | None = None) -> None:
        self._tty = tty
        self._error = error

    def isatty(self) -> bool:
        if self._error is not None:
            raise self._error
        return self._tty


def _comparable_mode(attributes: list) -> list:
    """Terminal attributes without PENDIN, which the kernel flips across a mode change on its own."""
    settled = list(attributes)
    settled[_LFLAG] = settled[_LFLAG] & ~getattr(termios, "PENDIN", 0)
    return settled


class TerminalSupportedTests(unittest.TestCase):
    @unittest.skipIf(terminal_module.termios is None, "no termios on this platform")
    def test_two_terminals_and_a_plain_environment_are_supported(self) -> None:
        self.assertTrue(terminal_supported(_Stream(), _Stream(), {"TERM": "xterm-256color"}))
        self.assertTrue(terminal_supported(_Stream(), _Stream(), {}))

    @unittest.skipIf(terminal_module.termios is None, "no termios on this platform")
    def test_an_empty_opt_out_does_not_opt_out(self) -> None:
        self.assertTrue(terminal_supported(_Stream(), _Stream(), {"OMH_NO_TUI": ""}))
        # Only "1" turns it off, as for the theme and setup pickers.
        self.assertTrue(terminal_supported(_Stream(), _Stream(), {"OMH_NO_TUI": "0"}))

    def test_each_reason_to_fall_back(self) -> None:
        cases = {
            "stdin not a tty": (_Stream(tty=False), _Stream(), {}),
            "stdout not a tty": (_Stream(), _Stream(tty=False), {}),
            "stdin closed": (_Stream(error=ValueError("I/O operation on closed file")), _Stream(), {}),
            "stdout detached": (_Stream(), _Stream(error=OSError("bad descriptor")), {}),
            "stdin missing": (None, _Stream(), {}),
            "TERM=dumb": (_Stream(), _Stream(), {"TERM": "dumb"}),
            "OMH_NO_TUI=1": (_Stream(), _Stream(), {"OMH_NO_TUI": "1"}),
        }
        for reason, (stdin, stdout, environ) in cases.items():
            with self.subTest(reason=reason):
                self.assertFalse(terminal_supported(stdin, stdout, environ))

    def test_no_termios_means_no_tui(self) -> None:
        with patch.object(terminal_module, "termios", None):
            self.assertFalse(terminal_supported(_Stream(), _Stream(), {}))

    def test_each_reason_is_named_in_one_line(self) -> None:
        # What bare `omh` prints on stderr before opening Hermes' own terminal.
        with patch.object(terminal_module, "termios", object()):
            for (stdin, stdout, environ), expected in (
                ((_Stream(), _Stream(), {"TERM": "dumb"}), "TERM=dumb cannot draw the OMH TUI"),
                ((_Stream(), _Stream(), {"OMH_NO_TUI": "1"}), "OMH_NO_TUI=1 turns the OMH TUI off"),
                ((_Stream(tty=False), _Stream(), {}), "stdin or stdout is not a terminal"),
                ((_Stream(), _Stream(error=OSError("bad descriptor")), {}), "stdin or stdout is not a terminal"),
                ((None, _Stream(), {}), "stdin or stdout is not a terminal"),
                ((_Stream(), _Stream(), {}), ""),
            ):
                with self.subTest(expected=expected):
                    self.assertEqual(terminal_blocker(stdin, stdout, environ), expected)
        with patch.object(terminal_module, "termios", None):
            self.assertEqual(
                terminal_blocker(_Stream(), _Stream(), {"TERM": "dumb"}),
                "the OMH TUI needs termios, which this platform does not have",
            )


BOTH_REPORTS = KITTY_KEYBOARD_PUSH + MODIFY_OTHER_KEYS_ON


class KeyboardProtocolRequestTests(unittest.TestCase):
    """Which terminals are asked for Ctrl+Enter and friends; the list is Hermes' own TUI's."""

    def test_the_allowlisted_terminals_are_asked_for_both_reports(self) -> None:
        for program in ("iTerm.app", "kitty", "WezTerm", "tmux", "vscode", "windows-terminal"):
            with self.subTest(program=program):
                self.assertEqual(keyboard_protocol_request({"TERM_PROGRAM": program}), BOTH_REPORTS)

    def test_ghostty_is_asked_for_modify_other_keys_only(self) -> None:
        # Its kitty mode drops Alt from Backspace (Hermes' own TUI skips it there too).
        self.assertEqual(keyboard_protocol_request({"TERM_PROGRAM": "ghostty"}), MODIFY_OTHER_KEYS_ON)
        self.assertEqual(keyboard_protocol_request({"TERM": "xterm-ghostty"}), MODIFY_OTHER_KEYS_ON)

    def test_other_terminals_are_not_asked(self) -> None:
        for environ in (
            {},
            {"TERM_PROGRAM": "Apple_Terminal"},
            {"TERM_PROGRAM": "Hyper"},
            {"TERM_PROGRAM": "iterm.app"},  # the name is matched exactly
            {"TERM": "xterm-256color"},
            {"STY": "1234.pts-0.host"},  # GNU screen
            # Cursor sets TERM_PROGRAM=vscode; Hermes reads it as its own terminal, not allowlisted.
            {"TERM_PROGRAM": "vscode", "CURSOR_TRACE_ID": "abc"},
        ):
            with self.subTest(environ=environ):
                self.assertEqual(keyboard_protocol_request(environ), "")

    def test_the_terminal_is_named_as_hermes_names_it(self) -> None:
        # kitty sets no TERM_PROGRAM; tmux and Windows Terminal are also known by their own variables.
        for environ in (
            {"TERM": "xterm-kitty"},
            {"KITTY_WINDOW_ID": "1"},
            {"TMUX": "/tmp/tmux-501/default,1,0"},
            {"WT_SESSION": "id"},
        ):
            with self.subTest(environ=environ):
                self.assertEqual(keyboard_protocol_request(environ), BOTH_REPORTS)
        # TERM_PROGRAM wins over TMUX, as in Hermes.
        self.assertEqual(keyboard_protocol_request({"TERM_PROGRAM": "Apple_Terminal", "TMUX": "x"}), "")

    def test_legacy_keeps_plain_bytes_everywhere(self) -> None:
        for program in ("iTerm.app", "kitty", "ghostty", "tmux"):
            with self.subTest(program=program):
                environ = {"TERM_PROGRAM": program, "OMH_TUI_KEYBOARD": "legacy"}
                self.assertEqual(keyboard_protocol_request(environ), "")
        for value in ("", "kitty", "LEGACY "):
            with self.subTest(value=value):
                environ = {"TERM_PROGRAM": "iTerm.app", "OMH_TUI_KEYBOARD": value}
                self.assertEqual(keyboard_protocol_request(environ), BOTH_REPORTS)

    def test_the_restore_sequence_always_switches_both_reports_off(self) -> None:
        # Written on every exit, a crash and a signal included, whether or not they were asked for.
        self.assertIn(MODIFY_OTHER_KEYS_OFF, RESTORE_SEQUENCE)
        self.assertIn(KITTY_KEYBOARD_POP, RESTORE_SEQUENCE)
        self.assertEqual(KITTY_KEYBOARD_POP, "\x1b[<u")
        self.assertEqual(MODIFY_OTHER_KEYS_OFF, "\x1b[>4m")
        self.assertEqual(BOTH_REPORTS, "\x1b[>1u\x1b[>4;2m")


class BackgroundReplyTests(unittest.TestCase):
    """The answers to the startup background query, read out of whatever else the input held."""

    def test_the_background_answer_is_read_in_every_digit_count_and_either_terminator(self) -> None:
        da1 = b"\x1b[?62;22c"
        cases = {
            b"\x1b]11;rgb:ffff/ffff/ffff\x07": "#FFFFFF",
            b"\x1b]11;rgb:1e1e/1e1e/1e1e\x1b\\": "#1E1E1E",
            b"\x1b]11;rgb:fd/f6/e3\x07": "#FDF6E3",
            b"\x1b]11;rgb:f/0/8\x07": "#FF0088",
            b"\x1b]11;rgb:800/800/800\x07": "#808080",
        }
        for reply, colour in cases.items():
            with self.subTest(reply=reply):
                self.assertEqual(split_background_replies(reply + da1), (colour, b"", True))

    def test_keys_typed_around_the_answers_are_kept_in_order(self) -> None:
        data = b"ab\x1b]11;rgb:0000/0000/0000\x07c\x1b[?1;2cd"
        self.assertEqual(split_background_replies(data), ("#000000", b"abcd", True))

    def test_a_terminal_that_answers_only_the_attributes_request_reports_no_background(self) -> None:
        self.assertEqual(split_background_replies(b"\x1b[?64;1;2c"), (None, b"", True))
        self.assertEqual(split_background_replies(b"x"), (None, b"x", False))

    def test_colorfgbg_names_a_light_background_only_for_its_light_colours(self) -> None:
        self.assertEqual(background_from_colorfgbg({"COLORFGBG": "0;15"}), "#FFFFFF")
        self.assertEqual(background_from_colorfgbg({"COLORFGBG": "0;default;7"}), "#E5E5E5")
        for value in ("15;0", "7;8", "15;default", "", "garbage", "0;99"):
            with self.subTest(value=value):
                self.assertIsNone(background_from_colorfgbg({"COLORFGBG": value}))
        self.assertIsNone(background_from_colorfgbg({}))

    def test_colorfgbg_names_a_dark_background_for_its_dark_colours(self) -> None:
        for value in ("15;0", "7;0", "15;default;0", "7;8", "0;4"):
            with self.subTest(value=value):
                self.assertTrue(colorfgbg_names_dark({"COLORFGBG": value}))
        for value in ("0;15", "0;default;7", "15;default", "15", "", "garbage", "0;99", "15;9"):
            with self.subTest(value=value):
                self.assertFalse(colorfgbg_names_dark({"COLORFGBG": value}))
        self.assertFalse(colorfgbg_names_dark({}))


class CursorReplyTests(unittest.TestCase):
    """The cursor position report the startup query asks for: its row counts only in the answers DA1 closes."""

    DA1 = b"\x1b[?62;22c"

    def test_the_report_before_the_attributes_answer_gives_the_row_and_leaves_the_keys(self) -> None:
        data = b"a\x1b]11;rgb:0000/0000/0000\x07b\x1b[34;1R" + self.DA1 + b"c"
        row, rest = split_cursor_reply(data)
        self.assertEqual(row, 34)
        self.assertEqual(split_background_replies(rest), ("#000000", b"abc", True))

    def test_with_no_report_garbage_or_no_attributes_answer_there_is_no_row_and_nothing_is_taken(self) -> None:
        for data in (self.DA1, b"\x1b[34;R" + self.DA1, b"\x1b[;1R" + self.DA1, b"\x1b[34;1R", b"x\x1b[x"):
            with self.subTest(data=data):
                self.assertEqual(split_cursor_reply(data), (None, data))

    def test_a_key_of_the_same_shape_typed_before_the_report_stays_a_key(self) -> None:
        # Shift+F3 in xterm's encoding is `CSI 1;2R`; the terminal's own report is the last one before DA1.
        row, rest = split_cursor_reply(b"\x1b[1;2R\x1b[20;1R" + self.DA1)
        self.assertEqual((row, rest), (20, b"\x1b[1;2R" + self.DA1))

    def test_a_key_of_the_same_shape_typed_after_the_attributes_answer_stays_a_key(self) -> None:
        # The terminal answered in order, so nothing after DA1 is its report: Shift+F3 typed then is a key.
        for data, expected in (
            (self.DA1 + b"\x1b[5;1R", (None, self.DA1 + b"\x1b[5;1R")),
            (b"\x1b[20;1R" + self.DA1 + b"\x1b[5;1R", (20, self.DA1 + b"\x1b[5;1R")),
        ):
            with self.subTest(data=data):
                self.assertEqual(split_cursor_reply(data), expected)

    def test_the_query_asks_for_the_position_between_the_background_and_the_attributes(self) -> None:
        self.assertEqual(CURSOR_POSITION_QUERY, "\x1b[6n")


class MouseReportingSequenceTests(unittest.TestCase):
    def test_clicks_and_the_wheel_in_sgr_form_and_never_motion(self) -> None:
        self.assertEqual(MOUSE_REPORTING_ON, "\x1b[?1000h\x1b[?1006h")
        self.assertEqual(MOUSE_REPORTING_OFF, "\x1b[?1006l\x1b[?1002l\x1b[?1000l")  # a drag's motion goes off too
        for motion_mode in ("?1002", "?1003"):
            with self.subTest(mode=motion_mode):
                self.assertNotIn(motion_mode, MOUSE_REPORTING_ON)

    def test_a_drag_adds_only_a_held_buttons_motion(self) -> None:
        self.assertEqual((MOUSE_DRAG_ON, MOUSE_DRAG_OFF), ("\x1b[?1002h", "\x1b[?1002l"))
        self.assertNotIn("?1003", MOUSE_DRAG_ON + MOUSE_REPORTING_OFF)  # motion with no button held: never

    def test_the_restore_sequence_always_switches_mouse_reports_off(self) -> None:
        # Written on every exit, a crash and a signal included, whether or not they were turned on.
        self.assertIn(MOUSE_REPORTING_OFF, RESTORE_SEQUENCE)
        self.assertNotIn(MOUSE_REPORTING_ON, RESTORE_SEQUENCE)


@unittest.skipUnless(pty is not None and termios is not None, "needs a POSIX pty")
class TerminalPtyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._open: set[int] = set()
        self.master, self.slave = self.open_pty()
        termios.tcsetwinsize(self.slave, (30, 100))

    def open_pty(self) -> tuple[int, int]:
        master, slave = pty.openpty()
        self._open.update((master, slave))
        self.addCleanup(self.close, slave)
        self.addCleanup(self.close, master)
        return master, slave

    def close(self, descriptor: int) -> None:
        """Close once; a descriptor number closed earlier may already belong to someone else."""
        if descriptor in self._open:
            self._open.discard(descriptor)
            os.close(descriptor)

    def master_output(self) -> bytes:
        """Everything the terminal side has written so far."""
        chunks = []
        while select.select([self.master], [], [], 0.2)[0]:
            try:
                chunk = os.read(self.master, 4096)
            except OSError:  # EIO once the slave side is gone (Linux)
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    def read_exactly(self, term: Terminal, count: int) -> bytes:
        data = b""
        while len(data) < count:
            chunk = term.read(_READ_WATCHDOG_SECONDS)
            self.assertTrue(chunk, f"read timed out after {data!r}")
            data += chunk
        return data

    def test_raw_mode_while_inside_and_restored_after(self) -> None:
        before = termios.tcgetattr(self.slave)
        with Terminal(self.slave, self.slave):
            during = termios.tcgetattr(self.slave)
            for flag in ("ICANON", "ECHO", "ISIG", "IEXTEN"):
                with self.subTest(flag=flag):
                    self.assertFalse(during[_LFLAG] & getattr(termios, flag))
            for flag in ("ICRNL", "IXON"):
                with self.subTest(flag=flag):
                    self.assertFalse(during[_IFLAG] & getattr(termios, flag))
            self.assertFalse(during[_OFLAG] & termios.OPOST)
        self.assertEqual(_comparable_mode(termios.tcgetattr(self.slave)), _comparable_mode(before))

    def test_bracketed_paste_is_switched_on_and_back_off(self) -> None:
        with Terminal(self.slave, self.slave):
            self.assertEqual(self.master_output(), BRACKETED_PASTE_ON.encode())
        tail = self.master_output()
        self.assertTrue(tail.endswith(BRACKETED_PASTE_OFF.encode()), tail)

    def test_an_allowlisted_terminal_is_asked_for_key_reports_and_released(self) -> None:
        cases = {
            "iTerm.app": BOTH_REPORTS,
            "ghostty": MODIFY_OTHER_KEYS_ON,
        }
        for program, request in cases.items():
            with self.subTest(program=program):
                term = Terminal(self.slave, self.slave, environ={"TERM_PROGRAM": program})
                self.assertFalse(term.keyboard_protocol)
                with term:
                    self.assertEqual(self.master_output(), (BRACKETED_PASTE_ON + request).encode())
                    self.assertTrue(term.keyboard_protocol)
                self.assertFalse(term.keyboard_protocol)
                self.assertTrue(self.master_output().endswith(RESTORE_SEQUENCE.encode()))

    def test_no_request_without_an_allowlisted_terminal_or_with_legacy(self) -> None:
        for environ in (None, {"TERM_PROGRAM": "Apple_Terminal"}, {"TERM_PROGRAM": "kitty", "OMH_TUI_KEYBOARD": "legacy"}):
            with self.subTest(environ=environ):
                term = Terminal(self.slave, self.slave, environ=environ)
                with term:
                    self.assertEqual(self.master_output(), BRACKETED_PASTE_ON.encode())
                    self.assertFalse(term.keyboard_protocol)
                # Released anyway: harmless where nothing was asked.
                self.assertTrue(self.master_output().endswith(RESTORE_SEQUENCE.encode()))

    def test_key_reports_are_released_when_the_block_raises_or_a_signal_exits(self) -> None:
        for error in (RuntimeError("boom"), SystemExit(128 + signal.SIGTERM)):
            with self.subTest(error=type(error).__name__):
                term = Terminal(self.slave, self.slave, environ={"TERM_PROGRAM": "kitty"})
                with self.assertRaises(type(error)):
                    with term:
                        self.master_output()
                        raise error
                self.assertFalse(term.keyboard_protocol)
                tail = self.master_output().decode()
                self.assertIn(MODIFY_OTHER_KEYS_OFF + KITTY_KEYBOARD_POP, tail)

    def test_mouse_reporting_is_off_on_entry_and_set_mouse_writes_only_on_a_change(self) -> None:
        term = Terminal(self.slave, self.slave)
        with term:
            self.assertEqual(self.master_output(), BRACKETED_PASTE_ON.encode())
            self.assertFalse(term.mouse_reporting)
            term.set_mouse(False)
            self.assertEqual(self.master_output(), b"")
            term.set_mouse(True)
            self.assertTrue(term.mouse_reporting)
            self.assertEqual(self.master_output(), MOUSE_REPORTING_ON.encode())
            term.set_mouse(True)
            self.assertEqual(self.master_output(), b"")
            term.set_mouse(False)
            self.assertFalse(term.mouse_reporting)
            self.assertEqual(self.master_output(), MOUSE_REPORTING_OFF.encode())
            term.set_mouse(False)
            self.assertEqual(self.master_output(), b"")
            term.set_mouse(True)
            self.master_output()
        self.assertFalse(term.mouse_reporting)
        self.assertTrue(self.master_output().endswith(RESTORE_SEQUENCE.encode()))

    def test_the_shells_cursor_shape_is_put_back_only_where_this_run_changed_it(self) -> None:
        with Terminal(self.slave, self.slave) as term:
            self.master_output()
            term.set_cursor_shape(CURSOR_SHAPE_BEAM)
            self.assertEqual(self.master_output(), CURSOR_SHAPE_BEAM.encode())
            term.set_cursor_shape(CURSOR_SHAPE_BEAM)
            self.assertEqual(self.master_output(), b"")
            term.set_cursor_shape(CURSOR_SHAPE_BLOCK)
            self.assertEqual(self.master_output(), CURSOR_SHAPE_BLOCK.encode())
        written = self.master_output()
        self.assertTrue(written.endswith(RESTORE_SEQUENCE.encode()), written)
        self.assertTrue(written.startswith(CURSOR_SHAPE_DEFAULT.encode()), written)
        self.assertIsNone(term.cursor_shape)

    def test_a_run_that_never_set_a_cursor_shape_leaves_the_shells_alone(self) -> None:
        self.assertNotIn(CURSOR_SHAPE_DEFAULT, RESTORE_SEQUENCE)
        with Terminal(self.slave, self.slave) as term:
            self.master_output()
            term.set_cursor_shape(None)
            self.assertEqual(self.master_output(), b"")
        self.assertEqual(self.master_output(), RESTORE_SEQUENCE.encode())

    def test_a_cursor_shape_set_outside_the_with_block_is_refused(self) -> None:
        term = Terminal(self.slave, self.slave)
        term.set_cursor_shape(CURSOR_SHAPE_BEAM)
        self.assertEqual(self.master_output(), b"")
        self.assertIsNone(term.cursor_shape)

    def test_a_drag_turns_on_over_the_reports_and_off_without_them(self) -> None:
        term = Terminal(self.slave, self.slave)
        with term:
            self.master_output()
            term.set_mouse(True, drag=True)
            self.assertEqual(self.master_output(), (MOUSE_REPORTING_ON + MOUSE_DRAG_ON).encode())
            self.assertEqual((term.mouse_reporting, term.mouse_drag), (True, True))
            term.set_mouse(True, drag=True)
            self.assertEqual(self.master_output(), b"")
            term.set_mouse(True)  # the agent list again: clicks only
            self.assertEqual(self.master_output(), MOUSE_DRAG_OFF.encode())
            term.set_mouse(True, drag=True)
            self.assertEqual(self.master_output(), MOUSE_DRAG_ON.encode())
            term.set_mouse(False)
            self.assertEqual(self.master_output(), MOUSE_REPORTING_OFF.encode())
            self.assertEqual((term.mouse_reporting, term.mouse_drag), (False, False))
            term.set_mouse(True, drag=True)
            self.master_output()
        self.assertFalse(term.mouse_drag)
        self.assertTrue(self.master_output().endswith(RESTORE_SEQUENCE.encode()))

    def test_mouse_reports_are_turned_off_when_the_block_raises_or_a_signal_exits(self) -> None:
        for error in (RuntimeError("boom"), SystemExit(128 + signal.SIGTERM)):
            with self.subTest(error=type(error).__name__):
                term = Terminal(self.slave, self.slave)
                with self.assertRaises(type(error)):
                    with term:
                        term.set_mouse(True)
                        self.master_output()
                        raise error
                self.assertFalse(term.mouse_reporting)
                self.assertIn(MOUSE_REPORTING_OFF, self.master_output().decode())

    def test_set_mouse_outside_the_block_writes_nothing(self) -> None:
        # Nothing would turn them off again, and every click would type escape codes into the shell.
        term = Terminal(self.slave, self.slave)
        term.set_mouse(True)
        self.assertFalse(term.mouse_reporting)
        with term:
            pass
        self.master_output()
        term.set_mouse(True)
        term.set_mouse(False)
        self.assertFalse(term.mouse_reporting)
        self.assertEqual(self.master_output(), b"")

    def test_a_mouse_report_arrives_as_bytes_the_decoder_reads(self) -> None:
        with Terminal(self.slave, self.slave) as term:
            term.set_mouse(True)
            self.master_output()
            report = b"\x1b[<0;12;7M"
            os.write(self.master, report)
            self.assertEqual(KeyDecoder().feed(self.read_exactly(term, len(report))), [Mouse(BUTTON_LEFT, 12, 7)])

    def test_leaving_after_a_hangup_with_mouse_reports_on_does_not_raise(self) -> None:
        term = Terminal(self.slave, self.slave)
        with term:
            term.set_mouse(True)
            self.close(self.master)
        self.assertFalse(term.mouse_reporting)

    def test_attributes_come_back_when_the_block_raises(self) -> None:
        before = termios.tcgetattr(self.slave)
        previous_handler = signal.getsignal(signal.SIGWINCH)
        with self.assertRaisesRegex(RuntimeError, "boom"):
            with Terminal(self.slave, self.slave):
                raise RuntimeError("boom")
        self.assertEqual(_comparable_mode(termios.tcgetattr(self.slave)), _comparable_mode(before))
        self.assertIs(signal.getsignal(signal.SIGWINCH), previous_handler)
        self.assertTrue(self.master_output().endswith(BRACKETED_PASTE_OFF.encode()))

    def test_ctrl_c_and_enter_arrive_as_bytes(self) -> None:
        with Terminal(self.slave, self.slave) as term:
            os.write(self.master, b"\x03\r\n")
            # ISIG off: no SIGINT, the byte is input. ICRNL off: CR stays CR.
            self.assertEqual(self.read_exactly(term, 3), b"\x03\r\n")

    def test_the_background_query_reads_the_answer_and_hands_keys_typed_meanwhile_back(self) -> None:
        with Terminal(self.slave, self.slave) as term:
            self.master_output()
            os.write(self.master, b"ab\x1b]11;rgb:ffff/ffff/ffff\x07\x1b[7;1R\x1b[?62;22cz")
            colour, typed, row = term.query_background()
            self.assertEqual((colour, typed, row), ("#FFFFFF", b"abz", 7))
            written = BACKGROUND_QUERY + CURSOR_POSITION_QUERY + XTVERSION_QUERY + KITTY_KEYBOARD_QUERY + DEVICE_ATTRIBUTES_QUERY
            self.assertEqual(self.master_output(), written.encode())  # DA1 last: its answer still ends the wait

    def test_every_terminal_is_asked_for_its_kitty_flags_and_the_answer_goes_to_the_decoder(self) -> None:
        startup = (BACKGROUND_QUERY + CURSOR_POSITION_QUERY + KITTY_KEYBOARD_QUERY + DEVICE_ATTRIBUTES_QUERY).encode()
        for program in ("kitty", "WezTerm", "ghostty", "Apple_Terminal", "otty"):
            with self.subTest(program=program):
                with Terminal(self.slave, self.slave, environ={"TERM_PROGRAM": program}) as term:
                    self.master_output()
                    answer = b"\x1b[?1u" if program in ("kitty", "WezTerm") else b"\x1b[?0u"
                    os.write(self.master, b"\x1b[7;1R" + answer + b"\x1b[?62;22c")
                    if program in ("Apple_Terminal", "otty"):  # an answer where nothing was pushed: push, ask again
                        os.write(self.master, b"\x1b[?1u\x1b[?62;22c")
                        self.assertEqual(term.query_background(), (None, answer + b"\x1b[?1u", 7))
                        again = (KITTY_KEYBOARD_PUSH + KITTY_KEYBOARD_QUERY + DEVICE_ATTRIBUTES_QUERY).encode()
                        self.assertEqual(self.master_output(), startup + again)
                        self.assertTrue(term.keyboard_protocol)
                    else:  # pushed on entry, or Ghostty, which never gets the kitty flags
                        self.assertEqual(term.query_background(), (None, answer, 7))  # the decoder reads it
                        self.assertEqual(self.master_output(), startup)  # before DA1: answered inside the wait
                        self.assertEqual(term.keyboard_protocol, program != "Apple_Terminal")

    def test_an_unnamed_terminal_gets_the_push_only_when_xtversion_names_a_known_one(self) -> None:
        # Over SSH TERM_PROGRAM rarely arrives: the terminal is asked its name (XTVERSION) with the kitty query.
        startup = BACKGROUND_QUERY + CURSOR_POSITION_QUERY + XTVERSION_QUERY + KITTY_KEYBOARD_QUERY + DEVICE_ATTRIBUTES_QUERY
        cases = {
            b"\x1bP>|kitty(0.35.2)\x1b\\": True,
            b"\x1bP>|WezTerm 20240203-110809-5046fc22\x07": True,
            b"\x1bP>|ghostty 1.1.3\x1b\\": False,  # its kitty mode drops Alt from Backspace
            b"\x1bP>|iTerm2 3.5.10\x1b\\": False,  # not known to read the flag as the TUI does
            b"": False,  # no name before the attributes: an unnamed answer may be Ghostty's
        }
        for name, pushed in cases.items():
            with self.subTest(name=name):
                with Terminal(self.slave, self.slave, environ={"TERM": "xterm-256color"}) as term:
                    self.master_output()
                    os.write(self.master, name + b"\x1b[?0u\x1b[?62;22c" + (b"\x1b[?1u\x1b[?62;22c" if pushed else b""))
                    _colour, typed, _row = term.query_background()
                    self.assertNotIn(b"\x1bP", typed)  # the name is an answer, never a key
                    again = KITTY_KEYBOARD_PUSH + KITTY_KEYBOARD_QUERY + DEVICE_ATTRIBUTES_QUERY if pushed else ""
                    self.assertEqual(self.master_output(), (startup + again).encode())
                    self.assertEqual(term.keyboard_protocol, pushed)

    def test_a_kitty_answer_after_the_attributes_answer_is_no_reason_to_push(self) -> None:
        with Terminal(self.slave, self.slave, environ={"TERM_PROGRAM": "otty"}) as term:
            self.master_output()
            os.write(self.master, b"\x1b[?62;22c\x1b[?0u")  # a late answer: the decoder reads it, nothing is pushed
            self.assertEqual(term.query_background(), (None, b"\x1b[?0u", None))
            self.assertNotIn(KITTY_KEYBOARD_PUSH.encode(), self.master_output())
            self.assertFalse(term.keyboard_protocol)

    def test_a_push_on_the_answer_is_popped_on_exit_and_pushed_again_after_a_stop(self) -> None:
        term = Terminal(self.slave, self.slave, environ={"TERM_PROGRAM": "otty"})
        with term:
            self.master_output()
            os.write(self.master, b"\x1b[?0u\x1b[?62;22c\x1b[?1u\x1b[?62;22c")  # both answers in one read
            self.assertEqual(term.query_background(), (None, b"\x1b[?0u\x1b[?1u", None))
            self.master_output()
            with patch.object(os, "kill"):  # the stop itself: the job is not really stopped here
                self.assertTrue(term.suspend())
            written = self.master_output().decode()
            self.assertIn(RESTORE_SEQUENCE, written)
            self.assertTrue(written.endswith(BRACKETED_PASTE_ON + KITTY_KEYBOARD_PUSH), written)
        self.assertTrue(self.master_output().endswith(RESTORE_SEQUENCE.encode()))  # KITTY_KEYBOARD_POP among it

    def test_a_terminal_that_answers_no_kitty_query_gets_no_push(self) -> None:
        for environ in ({"TERM_PROGRAM": "Apple_Terminal"}, {"TERM_PROGRAM": "otty", "OMH_TUI_KEYBOARD": "legacy"}):
            with self.subTest(environ=environ):
                with Terminal(self.slave, self.slave, environ=environ) as term:
                    self.master_output()
                    os.write(self.master, b"\x1b[?62;22c")
                    self.assertEqual(term.query_background(timeout=5.0), (None, b"", None))
                    asked = "" if environ.get("OMH_TUI_KEYBOARD") else KITTY_KEYBOARD_QUERY
                    written = (BACKGROUND_QUERY + CURSOR_POSITION_QUERY + asked + DEVICE_ATTRIBUTES_QUERY).encode()
                    self.assertEqual(self.master_output(), written)
                    self.assertFalse(term.keyboard_protocol)

    def test_a_terminal_that_answers_only_the_attributes_still_ends_the_wait_at_once(self) -> None:
        with Terminal(self.slave, self.slave, environ={"TERM_PROGRAM": "kitty"}) as term:
            os.write(self.master, b"\x1b[?62;22c")  # no kitty answer: the protocol is not spoken there
            started = time.monotonic()
            self.assertEqual(term.query_background(timeout=5.0), (None, b"", None))
            self.assertLess(time.monotonic() - started, 1.0)

    def test_the_cursor_query_after_a_stop_asks_only_for_the_position(self) -> None:
        with Terminal(self.slave, self.slave) as term:
            self.master_output()
            os.write(self.master, b"q\x1b[12;1R\x1b[?62;22cw")
            self.assertEqual(term.query_cursor_row(), (b"qw", 12))
            self.assertEqual(self.master_output(), (CURSOR_POSITION_QUERY + DEVICE_ATTRIBUTES_QUERY).encode())
            os.write(self.master, b"\x1b[?62;22c")
            self.assertEqual(term.query_cursor_row(timeout=5.0), (b"", None))  # no report: no row

    def test_the_attributes_answer_ends_the_wait_without_a_background(self) -> None:
        with Terminal(self.slave, self.slave) as term:
            os.write(self.master, b"\x1b[?62;22c")
            started = time.monotonic()
            self.assertEqual(term.query_background(timeout=5.0), (None, b"", None))  # no background, no position
            self.assertLess(time.monotonic() - started, 1.0)

    def test_a_terminal_that_answers_nothing_costs_the_timeout_and_no_more(self) -> None:
        with Terminal(self.slave, self.slave) as term:
            started = time.monotonic()
            self.assertEqual(term.query_background(), (None, b"", None))
            elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, BACKGROUND_QUERY_SECONDS * 0.9)
        self.assertLess(elapsed, BACKGROUND_QUERY_SECONDS + 0.5)

    def test_read_returns_nothing_when_nothing_arrives(self) -> None:
        with Terminal(self.slave, self.slave) as term:
            self.assertEqual(term.read(0.05), b"")

    def test_a_readable_wake_descriptor_ends_the_wait_with_nothing_read(self) -> None:
        wake, waker = os.pipe()
        self._open.update((wake, waker))
        self.addCleanup(self.close, wake)
        self.addCleanup(self.close, waker)
        with Terminal(self.slave, self.slave) as term:
            os.write(waker, b"\0")
            started = time.monotonic()
            self.assertEqual(term.read(_READ_WATCHDOG_SECONDS, wake), b"")
            self.assertLess(time.monotonic() - started, _READ_WATCHDOG_SECONDS / 2)
            os.write(self.master, b"x")  # input waiting too: the input is what a read returns
            self.assertEqual(term.read(_READ_WATCHDOG_SECONDS, wake), b"x")

    @unittest.skipUnless(threading.current_thread() is threading.main_thread(), "signal handlers need the main thread")
    def test_a_resize_signal_ends_a_wait(self) -> None:
        with Terminal(self.slave, self.slave) as term:
            timer = threading.Timer(0.1, os.kill, (os.getpid(), signal.SIGWINCH))
            started = time.monotonic()
            timer.start()
            self.assertEqual(term.read(_READ_WATCHDOG_SECONDS), b"")
            timer.join()
            self.assertLess(time.monotonic() - started, _READ_WATCHDOG_SECONDS / 2)
            self.assertTrue(term.resized())
            self.assertEqual(term.read(0.05), b"")  # the signal's wake-up was used up by the read it ended

    def test_output_is_not_post_processed(self) -> None:
        with Terminal(self.slave, self.slave) as term:
            self.master_output()
            term.write("a\nb 한")
            self.assertEqual(self.master_output(), "a\nb 한".encode())

    def test_size_is_columns_then_rows(self) -> None:
        with Terminal(self.slave, self.slave) as term:
            self.assertEqual(term.size(), (100, 30))
            termios.tcsetwinsize(self.slave, (0, 0))
            self.assertEqual(term.size(), (80, 24))

    @unittest.skipUnless(threading.current_thread() is threading.main_thread(), "signal handlers need the main thread")
    def test_resize_signal_is_read_once(self) -> None:
        with Terminal(self.slave, self.slave) as term:
            self.assertFalse(term.resized())
            signal.raise_signal(signal.SIGWINCH)
            self.assertTrue(term.resized())
            self.assertFalse(term.resized())

    def test_a_closed_window_ends_the_session_without_a_traceback_on_exit(self) -> None:
        with Terminal(self.slave, self.slave) as term:
            self.close(self.master)
            with self.assertRaises(EOFError):
                term.read(_READ_WATCHDOG_SECONDS)

    def test_leaving_after_an_unnoticed_hangup_does_not_raise(self) -> None:
        with Terminal(self.slave, self.slave):
            self.close(self.master)


if __name__ == "__main__":
    unittest.main()
