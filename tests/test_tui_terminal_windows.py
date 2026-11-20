"""The OMH TUI on a Windows console (`omh.tui.terminal_windows`, and `Terminal` and the gateway wake on Windows).

The console layer runs on POSIX against a fake kernel32 that records every
mode and code-page call, so the order modes are set and put back, the reader
thread's surrogate joining, the wake, the resize poll and a vanished console
are proven here; the tests that need real Windows objects run only on Windows
(the CI `test-windows` job).
"""

from __future__ import annotations

import os
import threading
import time
import unittest
from unittest.mock import patch

from omh.tui import terminal as terminal_module
from omh.tui import terminal_windows as tw
from omh.tui.terminal import RESTORE_SEQUENCE, Terminal, terminal_blocker

IN, OUT = 10, 11  # the fake handles of the console's input and output
WAIT_FAILED = 0xFFFFFFFF
SAVED_IN = tw.ENABLE_PROCESSED_INPUT | tw.ENABLE_LINE_INPUT | tw.ENABLE_ECHO_INPUT | tw.ENABLE_QUICK_EDIT_MODE
SAVED_IN |= tw.ENABLE_EXTENDED_FLAGS
SAVED_OUT = 0x0003  # processed output and wrap at end of line, as conhost starts
SAVED_CP = 437


class FakeKernel32:
    """The kernel32 calls `terminal_windows` makes, recorded; input is a list of UTF-16 unit reads."""

    def __init__(self, *, refuse: int = 0, refuse_on: int | None = None) -> None:
        self.modes = {IN: SAVED_IN, OUT: SAVED_OUT}
        self.input_cp = self.output_cp = SAVED_CP
        self.calls: list[tuple] = []
        self.refuse = refuse  # SetConsoleMode fails for a mode with any of these bits
        self.refuse_on = refuse_on  # ... on this handle only (None: either)
        self.reads: list[list[int]] = []
        self.gone = False
        self.pipe_bytes: dict[int, int] = {}
        self.lock = threading.Lock()

    def GetConsoleMode(self, handle, mode) -> int:  # noqa: N802 - kernel32's own name
        if handle not in self.modes:
            return 0
        mode.value = self.modes[handle]
        return 1

    def SetConsoleMode(self, handle, mode) -> int:  # noqa: N802
        if mode & self.refuse and self.refuse_on in (None, handle):
            return 0
        self.calls.append(("mode", handle, mode))
        self.modes[handle] = mode
        return 1

    def GetConsoleCP(self) -> int:  # noqa: N802
        return self.input_cp

    def GetConsoleOutputCP(self) -> int:  # noqa: N802
        return self.output_cp

    def SetConsoleCP(self, cp) -> int:  # noqa: N802
        self.calls.append(("cp", cp))
        self.input_cp = cp
        return 1

    def SetConsoleOutputCP(self, cp) -> int:  # noqa: N802
        self.calls.append(("output_cp", cp))
        self.output_cp = cp
        return 1

    def WaitForSingleObject(self, handle, ms) -> int:  # noqa: N802
        deadline = time.monotonic() + ms / 1000
        while time.monotonic() < deadline:
            with self.lock:
                if self.gone:
                    return WAIT_FAILED
                if self.reads:
                    return tw.WAIT_OBJECT_0
            time.sleep(0.002)
        return tw.WAIT_TIMEOUT

    def ReadConsoleW(self, handle, buffer, size, count, reserved) -> int:  # noqa: N802
        with self.lock:
            if self.gone or not self.reads:
                return 0
            units = self.reads.pop(0)
        for index, unit in enumerate(units):
            buffer[index] = unit
        count.value = len(units)
        return 1

    def CancelIoEx(self, handle, overlapped) -> int:  # noqa: N802
        self.calls.append(("cancel", handle))
        return 1

    def PeekNamedPipe(self, handle, buffer, size, read, available, left) -> int:  # noqa: N802
        available.value = self.pipe_bytes.get(handle, 0)
        return 1

    def feed(self, *reads: list[int]) -> None:
        with self.lock:
            self.reads.extend(reads)

    def mode_calls(self) -> list[tuple]:
        return [call for call in self.calls if call[0] != "cancel"]


def _units(text: str) -> list[int]:
    data = text.encode("utf-16-le")
    return [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]


def _identity(fd: int) -> int:
    return fd


class _Stream:
    def __init__(self, fd: int, tty: bool = True) -> None:
        self._fd, self._tty = fd, tty

    def isatty(self) -> bool:
        return self._tty

    def fileno(self) -> int:
        return self._fd


class WindowsConsoleTests(unittest.TestCase):
    def console(self, kernel32: FakeKernel32, size=lambda: (100, 30)) -> tw.WindowsConsole:
        console = tw.WindowsConsole(IN, OUT, kernel32=kernel32, handle_of=_identity, size_of=size)
        self.addCleanup(console.restore)
        return console

    def test_enter_sets_vt_modes_and_utf8_and_restore_puts_each_back_in_reverse(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        console.enter()
        raw = tw.ENABLE_QUICK_EDIT_MODE | tw.ENABLE_EXTENDED_FLAGS | tw.ENABLE_VIRTUAL_TERMINAL_INPUT
        vt_out = SAVED_OUT | tw.ENABLE_VIRTUAL_TERMINAL_PROCESSING | tw.DISABLE_NEWLINE_AUTO_RETURN
        self.assertEqual(kernel32.mode_calls(), [
            ("mode", IN, raw), ("mode", OUT, vt_out), ("cp", tw.CP_UTF8), ("output_cp", tw.CP_UTF8),
        ])
        # Echo, line and processed input are off: Ctrl+C arrives as 0x03, Enter as CR.
        for flag in (tw.ENABLE_ECHO_INPUT, tw.ENABLE_LINE_INPUT, tw.ENABLE_PROCESSED_INPUT):
            self.assertFalse(kernel32.modes[IN] & flag)
        kernel32.calls.clear()
        console.restore()
        self.assertEqual(kernel32.mode_calls(), [
            ("output_cp", SAVED_CP), ("cp", SAVED_CP), ("mode", OUT, SAVED_OUT), ("mode", IN, SAVED_IN),
        ])
        self.assertIn(("cancel", IN), kernel32.calls)  # the reader is stopped first
        kernel32.calls.clear()
        console.restore()  # a second restore does nothing
        self.assertEqual(kernel32.calls, [])

    def test_a_failed_enter_restores_what_it_set_and_raises(self) -> None:
        kernel32 = FakeKernel32(refuse=tw.ENABLE_VIRTUAL_TERMINAL_PROCESSING, refuse_on=OUT)
        console = self.console(kernel32)
        with self.assertRaisesRegex(OSError, "virtual terminal output"):
            console.enter()
        self.assertEqual(kernel32.modes, {IN: SAVED_IN, OUT: SAVED_OUT})
        self.assertEqual((kernel32.input_cp, kernel32.output_cp), (SAVED_CP, SAVED_CP))

    def test_mouse_reports_turn_quick_edit_off_and_back(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        console.enter()
        console.set_mouse(True)
        self.assertFalse(kernel32.modes[IN] & tw.ENABLE_QUICK_EDIT_MODE)
        self.assertTrue(kernel32.modes[IN] & tw.ENABLE_EXTENDED_FLAGS)  # QuickEdit is written only with this bit
        console.set_mouse(False)
        self.assertTrue(kernel32.modes[IN] & tw.ENABLE_QUICK_EDIT_MODE)

    def test_a_surrogate_pair_split_across_two_reads_arrives_whole_as_utf8(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        console.enter()
        high, low = _units("\U0001F600")
        kernel32.feed([*_units("a\x03\x1b[A"), high], [low, *_units("é")])
        data = b""
        deadline = time.monotonic() + 2.0
        while len(data) < len("a\x03\x1b[A\U0001F600é".encode()) and time.monotonic() < deadline:
            data += console.read(0.2)
        self.assertEqual(data, "a\x03\x1b[A\U0001F600é".encode("utf-8"))

    def test_the_wake_pipe_ends_a_read_early_without_taking_its_byte(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        console.enter()
        kernel32.pipe_bytes[7] = 1
        started = time.monotonic()
        self.assertEqual(console.read(5.0, wake=7), b"")
        self.assertLess(time.monotonic() - started, 1.0)
        kernel32.pipe_bytes[7] = 0
        started = time.monotonic()
        self.assertEqual(console.read(0.15, wake=7), b"")  # an empty pipe: the read waits its timeout out
        self.assertGreaterEqual(time.monotonic() - started, 0.14)

    def test_a_size_change_ends_the_wait_and_is_reported_once(self) -> None:
        size = [(100, 30)]
        kernel32 = FakeKernel32()
        console = self.console(kernel32, size=lambda: size[0])
        console.enter()
        self.assertFalse(console.resized())
        size[0] = (120, 40)
        started = time.monotonic()
        self.assertEqual(console.read(5.0), b"")
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertTrue(console.resized())
        self.assertFalse(console.resized())
        time.sleep(tw.RESIZE_POLL_SECONDS * 1.5)
        self.assertFalse(console.resized())  # the same size measured again is no change

    def test_a_console_that_is_gone_is_eof_after_what_was_read(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        console.enter()
        kernel32.feed(_units("q"))
        self.assertEqual(console.read(2.0), b"q")
        with kernel32.lock:
            kernel32.gone = True
        with self.assertRaises(EOFError):
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                console.read(0.1)


class ConsoleBlockerTests(unittest.TestCase):
    def test_a_console_that_takes_vt_input_and_output_hosts_the_tui_and_keeps_its_modes(self) -> None:
        kernel32 = FakeKernel32()
        self.assertEqual(tw.console_blocker(_Stream(IN), _Stream(OUT), kernel32=kernel32, handle_of=_identity), "")
        self.assertEqual(kernel32.modes, {IN: SAVED_IN, OUT: SAVED_OUT})

    def test_a_console_that_refuses_vt_names_why_in_one_line(self) -> None:
        for flag, handle, expected in (
            (tw.ENABLE_VIRTUAL_TERMINAL_INPUT, IN, tw.NO_VT_INPUT),
            (tw.ENABLE_VIRTUAL_TERMINAL_PROCESSING, OUT, tw.NO_VT_OUTPUT),
        ):
            with self.subTest(expected=expected):
                kernel32 = FakeKernel32(refuse=flag, refuse_on=handle)
                reason = tw.console_blocker(_Stream(IN), _Stream(OUT), kernel32=kernel32, handle_of=_identity)
                self.assertEqual(reason, expected)
                self.assertIn("use Windows Terminal", reason)
                self.assertEqual(kernel32.modes, {IN: SAVED_IN, OUT: SAVED_OUT})

    def test_a_handle_that_is_no_console_is_named(self) -> None:
        reason = tw.console_blocker(_Stream(99), _Stream(OUT), kernel32=FakeKernel32(), handle_of=_identity)
        self.assertEqual(reason, tw.NOT_A_CONSOLE)

    def test_terminal_blocker_on_windows_asks_the_console_after_the_shared_rules(self) -> None:
        kernel32 = FakeKernel32(refuse=tw.ENABLE_VIRTUAL_TERMINAL_INPUT)
        with patch.object(terminal_module, "termios", None), patch.object(terminal_module.os, "name", "nt"), \
                patch.object(tw, "load_kernel32", return_value=kernel32), patch.object(tw, "os_handle", _identity):
            self.assertEqual(terminal_blocker(_Stream(IN), _Stream(OUT), {}), tw.NO_VT_INPUT)
            self.assertEqual(terminal_blocker(_Stream(IN), _Stream(OUT), {"TERM": "dumb"}),
                             "TERM=dumb cannot draw the OMH TUI")
            self.assertEqual(terminal_blocker(_Stream(IN), _Stream(OUT), {"OMH_NO_TUI": "1"}),
                             "OMH_NO_TUI=1 turns the OMH TUI off")
            self.assertEqual(terminal_blocker(_Stream(IN, tty=False), _Stream(OUT), {}),
                             "stdin or stdout is not a terminal")
            kernel32.refuse = 0
            self.assertEqual(terminal_blocker(_Stream(IN), _Stream(OUT), {}), "")


@unittest.skipUnless(os.name == "nt", "real Windows console handles")
class WindowsRealStreamTests(unittest.TestCase):
    def test_terminal_blocker_with_files_for_streams_says_not_a_terminal(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "stream.bin")
            with open(path, "wb") as handle:
                handle.write(b"")
            with open(path, "rb") as stdin, open(path, "ab") as stdout:
                self.assertEqual(terminal_blocker(stdin, stdout, {}), "stdin or stdout is not a terminal")
                self.assertEqual(tw.console_blocker(stdin, stdout), tw.NOT_A_CONSOLE)


class TerminalOnWindowsTests(unittest.TestCase):
    """`Terminal` with no termios on Windows enters the console instead, and writes the same sequences."""

    def test_terminal_enters_the_console_reads_through_it_and_restores_it(self) -> None:
        kernel32 = FakeKernel32()
        read_end, write_end = os.pipe()
        self.addCleanup(os.close, read_end)
        self.addCleanup(os.close, write_end)
        with patch.object(terminal_module, "termios", None), patch.object(terminal_module.os, "name", "nt"), \
                patch.object(tw, "load_kernel32", return_value=kernel32), \
                patch.object(tw, "os_handle", lambda fd: {0: IN, write_end: OUT}.get(fd, fd)):
            with Terminal(0, write_end, environ={}) as term:
                self.assertTrue(kernel32.modes[IN] & tw.ENABLE_VIRTUAL_TERMINAL_INPUT)
                kernel32.feed(_units("\x03"))
                deadline = time.monotonic() + 2.0
                data = b""
                while not data and time.monotonic() < deadline:
                    data = term.read(0.2)
                self.assertEqual(data, b"\x03")
                term.set_mouse(True)
                self.assertFalse(kernel32.modes[IN] & tw.ENABLE_QUICK_EDIT_MODE)
            self.assertEqual(kernel32.modes, {IN: SAVED_IN, OUT: SAVED_OUT})
        self.assertTrue(os.read(read_end, 65536).decode().endswith(RESTORE_SEQUENCE))

    def test_a_terminal_whose_console_refuses_vt_restores_and_raises(self) -> None:
        kernel32 = FakeKernel32(refuse=tw.ENABLE_VIRTUAL_TERMINAL_INPUT)
        with patch.object(terminal_module, "termios", None), patch.object(terminal_module.os, "name", "nt"), \
                patch.object(tw, "load_kernel32", return_value=kernel32), patch.object(tw, "os_handle", _identity):
            with self.assertRaises(OSError):
                Terminal(IN, OUT, environ={}).__enter__()
        self.assertEqual(kernel32.modes, {IN: SAVED_IN, OUT: SAVED_OUT})


if __name__ == "__main__":
    unittest.main()
