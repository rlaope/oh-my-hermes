"""The OMH TUI on a Windows console (`omh.tui.terminal_windows`, and `Terminal` and the gateway wake on Windows).

The console layer runs on POSIX against a fake kernel32 that records every
mode and code-page call, so the order modes are set and put back, the reader
thread's surrogate joining, the wake, the resize poll and a vanished console
are proven here; the tests that need real Windows objects run only on Windows
(the CI `test-windows` job).
"""

from __future__ import annotations

import ctypes
import os
import signal
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
    """The kernel32 calls `terminal_windows` makes, recorded.

    Input is a queue of console records, each with the UTF-16 units ReadConsoleW
    turns it into (None: a record ReadConsoleW skips, as a real console does).
    """

    def __init__(self, *, refuse: int = 0, refuse_on: int | None = None) -> None:
        self.modes = {IN: SAVED_IN, OUT: SAVED_OUT}
        self.input_cp = self.output_cp = SAVED_CP
        self.calls: list[tuple] = []
        self.refuse = refuse  # SetConsoleMode fails for a mode with any of these bits
        self.refuse_on = refuse_on  # ... on this handle only (None: either)
        self.queue: list[tuple[tuple[int, int, int, int], list[int] | None]] = []  # (type, down, VK, char), units
        self.read_calls = 0
        self.thread_calls: list[tuple] = []  # OpenThread / CancelSynchronousIo / CloseHandle
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
                if self.queue:
                    return tw.WAIT_OBJECT_0
            time.sleep(0.002)
        return tw.WAIT_TIMEOUT

    def ReadConsoleW(self, handle, buffer, size, count, reserved) -> int:  # noqa: N802
        with self.lock:
            self.read_calls += 1
            while self.queue and self.queue[0][1] is None:
                self.queue.pop(0)  # records that are no text are skipped
            if self.gone or not self.queue:
                return 0  # a real console would block here
            units = self.queue.pop(0)[1]
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

    def GetNumberOfConsoleInputEvents(self, handle, count) -> int:  # noqa: N802
        with self.lock:
            if self.gone:
                return 0
            count.value = len(self.queue)
        return 1

    def _copy_records(self, records, length, seen, *, take: bool) -> int:
        with self.lock:
            if self.gone:
                return 0
            entries = self.queue[:length]
            if take:
                del self.queue[:length]
        for index, ((event_type, down, vk, char), _units) in enumerate(entries):
            records[index].EventType = event_type
            key = records[index].Event.KeyEvent
            key.bKeyDown, key.wVirtualKeyCode, key.UnicodeChar = down, vk, char
        seen.value = len(entries)
        return 1

    def PeekConsoleInputW(self, handle, records, length, seen) -> int:  # noqa: N802
        return self._copy_records(records, length, seen, take=False)

    def ReadConsoleInputW(self, handle, records, length, seen) -> int:  # noqa: N802
        return self._copy_records(records, length, seen, take=True)

    def OpenThread(self, access, inherit, thread_id) -> int:  # noqa: N802
        self.thread_calls.append(("open", access, thread_id))
        return 77

    def CancelSynchronousIo(self, thread) -> int:  # noqa: N802
        self.thread_calls.append(("cancel_sync", thread))
        return 1

    def CloseHandle(self, handle) -> int:  # noqa: N802
        self.thread_calls.append(("close", handle))
        return 1

    def feed(self, *reads: list[int]) -> None:
        """Typed text: one character key-down per read, which ReadConsoleW returns as those units."""
        with self.lock:
            self.queue.extend(((tw.KEY_EVENT, 1, 0, units[0] if units else 0), units) for units in reads)

    def push(self, event_type: int, down: int = 0, vk: int = 0, char: int = 0, units: list[int] | None = None) -> None:
        with self.lock:
            self.queue.append(((event_type, down, vk, char), units))

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

    def test_a_reader_thread_that_cannot_start_restores_everything_and_raises_its_error(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        with patch.object(threading.Thread, "start", side_effect=RuntimeError("can't start new thread")), \
                self.assertRaisesRegex(RuntimeError, "can't start new thread"):
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


VK_SHIFT, VK_UP, VK_MENU, VK_VOLUME_UP = 0x10, 0x26, 0x12, 0xAF


class BlockingRead(FakeKernel32):
    """A ReadConsoleW that blocks until cancelled; CancelIoEx does not release it, CancelSynchronousIo does."""

    def __init__(self) -> None:
        super().__init__()
        self.inside = threading.Event()
        self.aborted = threading.Event()

    def ReadConsoleW(self, handle, buffer, size, count, reserved) -> int:  # noqa: N802
        self.read_calls += 1
        self.inside.set()
        self.aborted.wait(5)
        return 0  # ERROR_OPERATION_ABORTED

    def CancelIoEx(self, handle, overlapped) -> int:  # noqa: N802
        self.calls.append(("cancel", handle))
        return 0

    def CancelSynchronousIo(self, thread) -> int:  # noqa: N802
        super().CancelSynchronousIo(thread)
        self.aborted.set()
        return 1


class ConsoleRecordTests(unittest.TestCase):
    """ReadConsoleW is called only when it returns at once: records that never become text are drained."""

    def console(self, kernel32: FakeKernel32) -> tw.WindowsConsole:
        console = tw.WindowsConsole(IN, OUT, kernel32=kernel32, handle_of=_identity, size_of=lambda: (100, 30))
        self.addCleanup(console.restore)
        return console

    def wait_drained(self, kernel32: FakeKernel32) -> None:
        deadline = time.monotonic() + 2.0
        while kernel32.queue and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(kernel32.queue, [])

    def read_until(self, console: tw.WindowsConsole, expected: bytes) -> bytes:
        data = b""
        deadline = time.monotonic() + 2.0
        while len(data) < len(expected) and time.monotonic() < deadline:
            data += console.read(0.2)
        return data

    def test_input_record_has_the_win32_layout(self) -> None:
        self.assertEqual(ctypes.sizeof(tw.INPUT_RECORD), 20)
        self.assertEqual(tw.INPUT_RECORD.Event.offset, 4)
        self.assertEqual([getattr(tw.KEY_EVENT_RECORD, name).offset for name in (
            "bKeyDown", "wRepeatCount", "wVirtualKeyCode", "wVirtualScanCode", "UnicodeChar", "dwControlKeyState")],
            [0, 4, 6, 8, 10, 12])

    def test_focus_menu_and_size_records_are_drained_without_reading(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        console.enter()
        for event_type in (tw.FOCUS_EVENT, tw.MENU_EVENT, tw.WINDOW_BUFFER_SIZE_EVENT, tw.MOUSE_EVENT):
            kernel32.push(event_type)
        self.wait_drained(kernel32)
        self.assertEqual(kernel32.read_calls, 0)
        kernel32.feed(_units("a"))
        self.assertEqual(self.read_until(console, b"a"), b"a")

    def test_a_modifier_pressed_alone_and_a_key_up_are_drained_without_reading(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        console.enter()
        kernel32.push(tw.KEY_EVENT, down=1, vk=VK_SHIFT)
        kernel32.push(tw.KEY_EVENT, down=0, vk=0x41)  # the key-up of an "a" already read
        self.wait_drained(kernel32)
        self.assertEqual(kernel32.read_calls, 0)

    def test_a_character_key_reaches_read_console_past_a_modifier(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        console.enter()
        kernel32.push(tw.KEY_EVENT, down=1, vk=VK_SHIFT)
        kernel32.push(tw.KEY_EVENT, down=1, vk=0x41, char=ord("A"), units=_units("A"))
        self.assertEqual(self.read_until(console, b"A"), b"A")
        self.assertGreaterEqual(kernel32.read_calls, 1)

    def test_an_arrow_key_without_a_character_reaches_read_console_as_its_sequence(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        console.enter()
        kernel32.push(tw.KEY_EVENT, down=1, vk=VK_UP, units=_units("\x1b[A"))
        self.assertEqual(self.read_until(console, b"\x1b[A"), b"\x1b[A")

    def test_a_character_on_a_key_up_reaches_read_console(self) -> None:
        kernel32 = FakeKernel32()  # Alt+numpad: the composed character comes with the Alt key-up
        console = self.console(kernel32)
        console.enter()
        kernel32.push(tw.KEY_EVENT, down=0, vk=VK_MENU, char=ord("é"), units=_units("é"))
        self.assertEqual(self.read_until(console, "é".encode()), "é".encode())

    def test_a_signal_with_no_text_and_a_failing_cancel_leaves_no_reader_after_restore(self) -> None:
        kernel32 = BlockingRead()
        console = self.console(kernel32)
        console.enter()
        kernel32.push(tw.FOCUS_EVENT)
        self.wait_drained(kernel32)
        reader = console._reader
        console.restore()
        self.assertFalse(reader.is_alive())
        self.assertEqual(kernel32.read_calls, 0)
        self.assertEqual(list(console._chunks), [])
        self.assertEqual(kernel32.thread_calls, [])  # the reader stopped at once: no thread I/O to cancel

    def test_a_read_cancel_io_ex_cannot_release_is_cancelled_on_the_reader_thread(self) -> None:
        kernel32 = BlockingRead()  # a key-down VT input does not translate: ReadConsoleW skips it and blocks
        console = self.console(kernel32)
        console.enter()
        kernel32.push(tw.KEY_EVENT, down=1, vk=VK_VOLUME_UP)
        self.assertTrue(kernel32.inside.wait(2.0))
        reader = console._reader
        started = time.monotonic()
        console.restore()
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertFalse(reader.is_alive())
        self.assertEqual(kernel32.thread_calls, [
            ("open", tw.THREAD_TERMINATE, reader.native_id), ("cancel_sync", 77), ("close", 77)])
        self.assertEqual(list(console._chunks), [])
        self.assertEqual(kernel32.modes, {IN: SAVED_IN, OUT: SAVED_OUT})


class ExitSignalTests(unittest.TestCase):
    """Ctrl+Break and a closed console window reach Python as SIGBREAK: both exit-signal sets unwind on it."""

    def test_both_exit_signal_sets_name_sigbreak(self) -> None:
        from omh.tui import app, launch

        for module in (app, launch):
            with self.subTest(module=module.__name__):
                self.assertIn("SIGBREAK", module.EXIT_SIGNALS)

    @unittest.skipIf(hasattr(signal, "SIGBREAK"), "POSIX has no SIGBREAK")
    def test_posix_installs_skip_the_signal_it_lacks(self) -> None:
        from omh.tui import app, launch

        expected = {getattr(signal, name) for name in ("SIGTERM", "SIGHUP")}
        with patch.object(signal, "signal", return_value=signal.SIG_DFL) as install:
            app._install_exit_signals()
            self.assertEqual({call.args[0] for call in install.call_args_list}, expected)
            install.reset_mock()
            with launch.exit_on_signals():
                self.assertEqual({call.args[0] for call in install.call_args_list}, expected)


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
