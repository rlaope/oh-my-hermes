"""The OMH TUI on a Windows console (`omh.tui.terminal_windows`, and `Terminal` and the gateway wake on Windows).

The console layer runs on POSIX against a fake kernel32 that records every
mode and code-page call, so the order modes are set and put back, the reader
thread's record reading and surrogate joining, the wake, the resize poll and a vanished console
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

    Input is a queue of console input records, `((type, down, VK, char[, repeat]), note)`; typed text is one
    character key-down per UTF-16 unit, as virtual terminal input delivers it. ReadConsoleInputW behaves as a real
    console's: it returns at once while records are queued and waits for one on an empty queue (`inside` is set
    then) until a cancel ends the wait. ReadConsoleW is here only to prove it is never called (`read_calls`).
    """

    def __init__(self, *, refuse: int = 0, refuse_on: int | None = None) -> None:
        self.modes = {IN: SAVED_IN, OUT: SAVED_OUT}
        self.input_cp = self.output_cp = SAVED_CP
        self.calls: list[tuple] = []
        self.refuse = refuse  # SetConsoleMode fails for a mode with any of these bits
        self.refuse_on = refuse_on  # ... on this handle only (None: either)
        self.queue: list[tuple[tuple[int, ...], object]] = []
        self.read_calls = 0  # ReadConsoleW: must stay 0
        self.record_reads: list[int] = []  # the length of each ReadConsoleInputW
        self.read_limit: int | None = None  # at most this many records per ReadConsoleInputW
        self.stale = 0  # records GetNumberOfConsoleInputEvents still counts after a flush took them
        self.inside = threading.Event()  # a ReadConsoleInputW waits on an empty queue
        self.aborted = threading.Event()  # ... and a cancel ended that wait
        self.thread_calls: list[tuple] = []  # OpenThread / CancelSynchronousIo / CloseHandle
        self.written_back: list[tuple] = []  # records WriteConsoleInputW put back
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
                if self.queue or self.stale:
                    return tw.WAIT_OBJECT_0
            time.sleep(0.002)
        return tw.WAIT_TIMEOUT

    def ReadConsoleW(self, handle, buffer, size, count, reserved) -> int:  # noqa: N802
        self.read_calls += 1
        raise AssertionError("ReadConsoleW is never called: it blocks on records that are no text")

    def CancelIoEx(self, handle, overlapped) -> int:  # noqa: N802
        self.calls.append(("cancel", handle))
        if not self.inside.is_set():
            return 0  # ERROR_NOT_FOUND: no I/O to cancel
        self.aborted.set()
        return 1

    def PeekNamedPipe(self, handle, buffer, size, read, available, left) -> int:  # noqa: N802
        available.value = self.pipe_bytes.get(handle, 0)
        return 1

    def GetNumberOfConsoleInputEvents(self, handle, count) -> int:  # noqa: N802
        with self.lock:
            if self.gone:
                return 0
            count.value = len(self.queue) + self.stale
        return 1

    def ReadConsoleInputW(self, handle, records, length, seen) -> int:  # noqa: N802
        self.record_reads.append(length)
        deadline = time.monotonic() + 5.0
        while True:
            with self.lock:
                if self.gone:
                    return 0
                if self.queue:
                    entries = self.queue[:min(length, self.read_limit or length)]
                    del self.queue[:len(entries)]
                    break
                self.stale = 0  # the counted records were flushed: wait for the next one
            self.inside.set()
            if self.aborted.wait(0.002) or time.monotonic() > deadline:
                self.aborted.clear()
                self.inside.clear()
                return 0  # ERROR_OPERATION_ABORTED
        self.inside.clear()
        for index, (fields, _note) in enumerate(entries):
            event_type, down, vk, char, *repeat = fields
            records[index].EventType = event_type
            key = records[index].Event.KeyEvent
            key.bKeyDown, key.wVirtualKeyCode, key.UnicodeChar = down, vk, char
            key.wRepeatCount = repeat[0] if repeat else 1
        seen.value = len(entries)
        return 1

    def WriteConsoleInputW(self, handle, records, length, written) -> int:  # noqa: N802
        """Put records back at the end of the queue, as the console appends them."""
        entries = []
        for index in range(length):
            key = records[index].Event.KeyEvent
            entries.append(((records[index].EventType, key.bKeyDown, key.wVirtualKeyCode, key.UnicodeChar,
                             key.wRepeatCount), "written back"))
        with self.lock:
            self.queue.extend(entries)
            self.written_back.extend(entries)
        return 1

    def OpenThread(self, access, inherit, thread_id) -> int:  # noqa: N802
        self.thread_calls.append(("open", access, thread_id))
        return 77

    def CancelSynchronousIo(self, thread) -> int:  # noqa: N802
        self.thread_calls.append(("cancel_sync", thread))
        self.aborted.set()
        return 1

    def CloseHandle(self, handle) -> int:  # noqa: N802
        self.thread_calls.append(("close", handle))
        return 1

    def feed(self, *reads: list[int]) -> None:
        """Typed text: one character key-down record per UTF-16 unit."""
        with self.lock:
            self.queue.extend(((tw.KEY_EVENT, 1, 0, unit), None) for units in reads for unit in units)

    def push(self, event_type: int, down: int = 0, vk: int = 0, char: int = 0, repeat: int = 1) -> None:
        with self.lock:
            self.queue.append(((event_type, down, vk, char, repeat), None))

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
        kernel32.read_limit = 6  # "a", Ctrl+C, ESC [ A and the high half; the low half comes with the next read
        kernel32.feed([*_units("a\x03\x1b[A"), high], [low, *_units("é")])
        data = b""
        deadline = time.monotonic() + 2.0
        while len(data) < len("a\x03\x1b[A\U0001F600é".encode()) and time.monotonic() < deadline:
            data += console.read(0.2)
        self.assertEqual(data, "a\x03\x1b[A\U0001F600é".encode("utf-8"))
        self.assertEqual(kernel32.record_reads[:2], [8, 2])  # only the records that were queued, each time
        self.assertEqual(kernel32.read_calls, 0)

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


VK_SHIFT, VK_UP, VK_MENU, VK_VOLUME_UP, VK_PROCESSKEY = 0x10, 0x26, 0x12, 0xAF, 0xE5


class BlockingRead(FakeKernel32):
    """CancelIoEx releases nothing; only CancelSynchronousIo on the reader's thread ends a waiting read."""

    def CancelIoEx(self, handle, overlapped) -> int:  # noqa: N802
        self.calls.append(("cancel", handle))
        return 0


class ConsoleRecordTests(unittest.TestCase):
    """The reader reads only records that are queued and takes text only from the key records that read returned."""

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

    def test_an_arrow_arrives_as_its_three_character_records(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        console.enter()
        for unit in _units("\x1b[A"):  # VT input: ESC, "[" and "A" as key-downs (VK_UP with each)
            kernel32.push(tw.KEY_EVENT, down=1, vk=VK_UP, char=unit)
        self.assertEqual(self.read_until(console, b"\x1b[A"), b"\x1b[A")
        self.assertEqual(kernel32.read_calls, 0)

    def test_a_held_key_repeats_its_character(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        console.enter()
        kernel32.push(tw.KEY_EVENT, down=1, vk=0x41, char=ord("a"), repeat=3)
        self.assertEqual(self.read_until(console, b"aaa"), b"aaa")

    def test_only_an_alt_key_up_hands_over_its_character(self) -> None:
        kernel32 = FakeKernel32()  # Alt+numpad: the composed character comes with the Alt key-up
        console = self.console(kernel32)
        console.enter()
        kernel32.push(tw.KEY_EVENT, down=1, vk=0x41, char=ord("a"))
        kernel32.push(tw.KEY_EVENT, down=0, vk=0x41, char=ord("a"))  # an ordinary key-up carries it again
        kernel32.push(tw.KEY_EVENT, down=0, vk=VK_MENU, char=ord("é"))
        # An IME's character comes on its key-down; a key-up of the IME key carrying it again is no second copy.
        kernel32.push(tw.KEY_EVENT, down=1, vk=VK_PROCESSKEY, char=ord("漢"))
        kernel32.push(tw.KEY_EVENT, down=0, vk=VK_PROCESSKEY, char=ord("漢"))
        self.assertEqual(self.read_until(console, "aé漢".encode()), "aé漢".encode())
        self.assertEqual(console.read(0.1), b"")  # neither "a" nor "漢" is doubled

    def test_records_that_are_no_text_are_read_and_dropped_and_the_reader_stays_responsive(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        console.enter()
        for event_type in (tw.FOCUS_EVENT, tw.MENU_EVENT, tw.WINDOW_BUFFER_SIZE_EVENT, tw.MOUSE_EVENT):
            kernel32.push(event_type)
        kernel32.push(tw.KEY_EVENT, down=1, vk=VK_SHIFT)  # a modifier alone
        kernel32.push(tw.KEY_EVENT, down=1, vk=VK_VOLUME_UP)  # a key without a character
        kernel32.push(tw.KEY_EVENT, down=0, vk=VK_SHIFT)
        self.wait_drained(kernel32)
        self.assertEqual(console.read(0.1), b"")
        kernel32.feed(_units("a"))
        self.assertEqual(self.read_until(console, b"a"), b"a")
        self.assertEqual(kernel32.read_calls, 0)
        self.assertFalse(kernel32.inside.is_set())

    def test_a_surrogate_pair_split_over_two_record_reads_arrives_whole(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        console.enter()
        high, low = _units("\U0001F600")
        kernel32.feed([high])
        self.assertEqual(console.read(0.15), b"")  # the high half waits for its low half
        kernel32.feed([low])
        self.assertEqual(self.read_until(console, "\U0001F600".encode()), "\U0001F600".encode())
        self.assertGreaterEqual(len(kernel32.record_reads), 2)

    def test_records_flushed_after_the_signal_are_not_read_on_an_empty_queue(self) -> None:
        kernel32 = FakeKernel32()
        signalled = kernel32.WaitForSingleObject

        def flush_after_signal(handle, ms):
            state = signalled(handle, ms)
            with kernel32.lock:
                kernel32.queue.clear()  # another reader or FlushConsoleInputBuffer takes the records
            return state

        kernel32.WaitForSingleObject = flush_after_signal
        kernel32.push(tw.FOCUS_EVENT)
        console = self.console(kernel32)
        console.enter()
        time.sleep(0.15)
        self.assertFalse(kernel32.inside.is_set())
        self.assertEqual(kernel32.record_reads, [])  # a count of 0 never reaches ReadConsoleInputW

    def test_a_read_only_takes_the_records_that_were_counted(self) -> None:
        kernel32 = FakeKernel32()
        kernel32.feed(_units("x" * (tw.READ_RECORDS + 3)))
        console = self.console(kernel32)
        console.enter()
        self.assertEqual(self.read_until(console, b"x" * (tw.READ_RECORDS + 3)), b"x" * (tw.READ_RECORDS + 3))
        self.assertEqual(kernel32.record_reads[:2], [tw.READ_RECORDS, 3])

    def test_restore_with_no_input_stops_the_reader_at_once_without_a_cancel(self) -> None:
        kernel32 = BlockingRead()
        console = self.console(kernel32)
        console.enter()
        kernel32.push(tw.FOCUS_EVENT)
        self.wait_drained(kernel32)
        reader = console._reader
        started = time.monotonic()
        console.restore()
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertFalse(reader.is_alive())
        self.assertEqual(kernel32.thread_calls, [])  # no thread I/O to cancel
        kernel32.feed(_units("X"))  # the shell's next key stays in the console
        time.sleep(0.06)
        self.assertEqual(len(kernel32.queue), 1)
        self.assertEqual(list(console._chunks), [])

    def test_a_flush_between_count_and_read_is_cancelled_on_the_reader_thread(self) -> None:
        kernel32 = BlockingRead()  # the one window left: the counted record is flushed before the read
        console = self.console(kernel32)
        console.enter()
        with kernel32.lock:
            kernel32.stale = 1
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

    def test_a_reader_no_cancel_releases_gives_what_it_reads_back_to_the_console(self) -> None:
        kernel32 = BlockingRead()  # a flush left the read waiting, and neither cancel takes
        kernel32.CancelSynchronousIo = lambda thread: 0
        console = self.console(kernel32)
        console.enter()
        with kernel32.lock:
            kernel32.stale = 1
        self.assertTrue(kernel32.inside.wait(2.0))
        reader = console._reader
        started = time.monotonic()
        console.restore()
        self.assertLess(time.monotonic() - started, 1.3)  # bounded: two joins
        self.assertEqual(kernel32.modes, {IN: SAVED_IN, OUT: SAVED_OUT})
        kernel32.feed(_units("X"))  # the shell's next key, after restore returned
        reader.join(2.0)
        self.assertFalse(reader.is_alive())
        self.assertEqual(list(console._chunks), [])  # nothing reached the TUI
        self.assertEqual([fields[3] for fields, _note in kernel32.queue], [ord("X")])  # the console has it again

    def test_a_paste_a_stuck_reader_takes_the_start_of_goes_back_whole_and_in_order(self) -> None:
        kernel32 = BlockingRead()  # the waiting read takes only the first record of the paste that ends it
        kernel32.CancelSynchronousIo = lambda thread: 0
        console = self.console(kernel32)
        console.enter()
        with kernel32.lock:
            kernel32.stale = 1
        self.assertTrue(kernel32.inside.wait(2.0))
        reader = console._reader
        console.restore()
        kernel32.feed(*([unit] for unit in _units("echo OK\r")))  # pasted into the shell at once
        reader.join(2.0)
        self.assertFalse(reader.is_alive())
        self.assertEqual(list(console._chunks), [])
        shell = "".join(chr(fields[3]) for fields, _note in kernel32.queue)
        self.assertEqual(shell, "echo OK\r")  # not "cho OK\re": what was behind the taken record goes back after it

    def test_startup_query_replies_arrive_through_the_records(self) -> None:
        kernel32 = FakeKernel32()
        console = self.console(kernel32)
        console.enter()
        term = Terminal(IN, OUT, environ={"WT_SESSION": "1"})
        term._console = console

        def answer(query: str) -> None:
            kernel32.feed(_units("\x1b[12;5R\x1b[?1u\x1b[?1;2c"))

        with patch.object(term, "write", side_effect=answer), \
                patch.object(terminal_module.select, "select", side_effect=AssertionError("no select on Windows")):
            typed, row = term.query_cursor_row(0.5)
        self.assertEqual(row, 12)
        self.assertEqual(kernel32.read_calls, 0)


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
