"""The Windows console under the OMH TUI: what termios raw mode is on POSIX, for Windows Terminal and conhost.

`terminal.Terminal` enters a `WindowsConsole` where there is no termios.
Entering saves the input and output console modes and code pages, then sets
the input to virtual terminal input with echo, line and processed input off,
so keys arrive as the same VT bytes a POSIX terminal sends (Ctrl+C as 0x03,
Enter as CR), and the output to virtual terminal processing without the
automatic return after a line feed, with the UTF-8 code page. Every exit puts
all four back, a failed enter too, as `Terminal._restore` does with termios.

Input is read as console input records on a reader thread. With virtual
terminal input every character the console delivers, each one of an arrow's
or F-key's VT sequence, a paste and the replies to the startup queries, is a
KEY_EVENT record carrying that UTF-16 unit, so the reader waits for the input
handle (at most `INPUT_WAIT_MS`), asks how many records are queued, and reads
only that many with ReadConsoleInputW, which returns at once because they
exist; it never calls a read on an empty queue. Text is taken only from the
records that read returned: a key-down's character (repeated as often as the
key repeated) and the character an Alt key-up (Alt+numpad) hands over (an
IME's key-down carries its character, as prompt_toolkit reads it); focus,
menu, mouse and size records, key-ups and keys without a character are
dropped. Nothing is decided on a snapshot of the queue, so a record that
changes under the reader is never lost; the one window left is a flush
exactly between counting and reading, which leaves that read waiting for the
next record. A surrogate pair split across two reads is joined and the text
queued as UTF-8 bytes, the bytes `keys.KeyDecoder` reads on POSIX. As the
reader only ever waits in WaitForSingleObject, `restore` stops it with its
flag; cancelling its I/O (CancelIoEx, then CancelSynchronousIo on its thread)
stays as a belt. A reader that outlives even that (both cancels refused while
a flush left it waiting) is abandoned: the one batch it reads after `restore` goes
back to the end of the console's input with WriteConsoleInputW, never into the
TUI's queue, and the reader ends; the shell still gets that key. `read(timeout, wake)` waits on that queue
and ends early when the gateway's wake pipe holds a byte (PeekNamedPipe, which
never consumes it) or the console's size changed: Windows has no SIGWINCH, so
the size is polled at most every `RESIZE_POLL_SECONDS` inside the wait. A
console that is gone (its input cannot be waited on, counted or read) is
EOFError, as a hung-up pty is.

`console_blocker` asks the console whether it takes VT input and output before
the TUI is tried, so an old conhost that cannot falls back to Hermes' own
terminal with one line. Mouse reports turn QuickEdit off while they are on,
so a click reaches the TUI instead of starting a console selection.

Nothing here calls Windows at import time: the module imports on POSIX, where
the tests hand it a fake kernel32.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
import ctypes
import os
import struct
import threading
import time
from typing import Any, Protocol

# Console input modes.
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004
ENABLE_QUICK_EDIT_MODE = 0x0040
ENABLE_EXTENDED_FLAGS = 0x0080  # QuickEdit is read and written only with this bit
ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
# Console output modes.
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
DISABLE_NEWLINE_AUTO_RETURN = 0x0008
CP_UTF8 = 65001

WAIT_OBJECT_0 = 0x0000
THREAD_TERMINATE = 0x0001  # the access CancelSynchronousIo needs on a thread handle
WAIT_TIMEOUT = 0x0102
ERROR_OPERATION_ABORTED = 995

INPUT_WAIT_MS = 50  # how long the reader waits for input before it looks at its stop flag
READ_SLICE_SECONDS = 0.02  # how often a `read` looks at the wake pipe while no input comes
RESIZE_POLL_SECONDS = 0.1
STOP_JOIN_SECONDS = 0.5
READ_RECORDS = 128  # input records read per ReadConsoleInputW

# Input record event types.
KEY_EVENT = 0x0001
MOUSE_EVENT = 0x0002
WINDOW_BUFFER_SIZE_EVENT = 0x0004
MENU_EVENT = 0x0008
FOCUS_EVENT = 0x0010
VK_MENU = 0x12  # Alt: Alt+numpad hands its composed character over on this key's key-up, its only copy

NOT_A_TERMINAL = "stdin or stdout is not a terminal"
NOT_A_CONSOLE = "stdin or stdout is not a Windows console"
NO_VT_INPUT = "this Windows console cannot enable virtual terminal input; use Windows Terminal"
NO_VT_OUTPUT = "this Windows console cannot enable virtual terminal output; use Windows Terminal"


class KEY_EVENT_RECORD(ctypes.Structure):
    """Win32 KEY_EVENT_RECORD; WCHAR is spelled c_uint16, as c_wchar is 4 bytes on POSIX."""

    _fields_ = [
        ("bKeyDown", ctypes.c_int32),
        ("wRepeatCount", ctypes.c_uint16),
        ("wVirtualKeyCode", ctypes.c_uint16),
        ("wVirtualScanCode", ctypes.c_uint16),
        ("UnicodeChar", ctypes.c_uint16),
        ("dwControlKeyState", ctypes.c_uint32),
    ]


class _INPUT_EVENT(ctypes.Union):
    _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("raw", ctypes.c_uint8 * 16)]  # MOUSE_EVENT_RECORD is the largest, 16


class INPUT_RECORD(ctypes.Structure):
    """Win32 INPUT_RECORD: EventType, 2 bytes of padding, then the 16-byte event."""

    _fields_ = [("EventType", ctypes.c_uint16), ("Event", _INPUT_EVENT)]


def record_units(records: Any) -> list[int]:
    """The UTF-16 units typed in these input records: each key-down's character, repeated as the key repeated, and
    the character an Alt key-up (Alt+numpad) carries; every other record (focus, menu, mouse, size, any other key-up, a key
    without a character such as a lone Shift) is no text."""
    units: list[int] = []
    for record in records:
        if record.EventType != KEY_EVENT:
            continue
        key = record.Event.KeyEvent
        if not key.UnicodeChar:
            continue
        if key.bKeyDown:
            units.extend([key.UnicodeChar] * max(key.wRepeatCount, 1))
        elif key.wVirtualKeyCode == VK_MENU:
            units.append(key.UnicodeChar)
    return units


class _Stream(Protocol):
    def fileno(self) -> int: ...


def raw_input_mode(saved: int, mouse: bool = False) -> int:
    """The input mode while the TUI owns the console: VT input only, QuickEdit kept as it was unless `mouse`."""
    quick_edit = 0 if mouse else saved & ENABLE_QUICK_EDIT_MODE
    return quick_edit | ENABLE_EXTENDED_FLAGS | ENABLE_VIRTUAL_TERMINAL_INPUT


def vt_output_mode(saved: int) -> int:
    """The output mode while the TUI owns the console: `saved` plus VT processing, no return after a line feed."""
    return saved | ENABLE_VIRTUAL_TERMINAL_PROCESSING | DISABLE_NEWLINE_AUTO_RETURN


def utf16_to_utf8(units: list[int]) -> bytes:
    """UTF-16 code units as UTF-8 bytes; a lone surrogate becomes U+FFFD."""
    return struct.pack(f"<{len(units)}H", *units).decode("utf-16-le", "replace").encode("utf-8")


def _console_size(fd: int) -> tuple[int, int]:
    size = os.get_terminal_size(fd)
    return (size.columns, size.lines)


_KERNEL32: Any = None


def load_kernel32() -> Any:
    """kernel32 with the signatures this module calls; Windows only."""
    global _KERNEL32
    if _KERNEL32 is None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        handle, dword, bool_ = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int
        dword_p = ctypes.POINTER(ctypes.c_uint32)
        signatures = {
            "GetConsoleMode": ((handle, dword_p), bool_),
            "SetConsoleMode": ((handle, dword), bool_),
            "GetConsoleCP": ((), dword),
            "GetConsoleOutputCP": ((), dword),
            "SetConsoleCP": ((dword,), bool_),
            "SetConsoleOutputCP": ((dword,), bool_),
            "WaitForSingleObject": ((handle, dword), dword),
            "CancelIoEx": ((handle, ctypes.c_void_p), bool_),
            "GetNumberOfConsoleInputEvents": ((handle, dword_p), bool_),
            "ReadConsoleInputW": ((handle, ctypes.POINTER(INPUT_RECORD), dword, dword_p), bool_),
            "WriteConsoleInputW": ((handle, ctypes.POINTER(INPUT_RECORD), dword, dword_p), bool_),
            "OpenThread": ((dword, bool_, dword), handle),
            "CancelSynchronousIo": ((handle,), bool_),
            "CloseHandle": ((handle,), bool_),
            "PeekNamedPipe": ((handle, ctypes.c_void_p, dword, ctypes.c_void_p, dword_p, ctypes.c_void_p), bool_),
        }
        for name, (argtypes, restype) in signatures.items():
            function = getattr(kernel32, name)
            function.argtypes, function.restype = argtypes, restype
        _KERNEL32 = kernel32
    return _KERNEL32


def os_handle(fd: int) -> int:
    """The Windows handle behind a C runtime descriptor; Windows only."""
    import msvcrt

    return msvcrt.get_osfhandle(fd)  # type: ignore[attr-defined]


def console_blocker(
    stdin: _Stream, stdout: _Stream, *, kernel32: Any = None, handle_of: Callable[[int], int] | None = None
) -> str:
    """Why this console cannot host the OMH TUI, in one line, or "" when it takes VT input and output.

    Each mode is set and put back at once: only the answer is kept.
    """
    kernel32 = kernel32 if kernel32 is not None else load_kernel32()
    handle_of = handle_of or os_handle
    try:
        handles = (handle_of(stdin.fileno()), handle_of(stdout.fileno()))
    except (AttributeError, OSError, ValueError):  # no descriptor, or one the C runtime does not know
        return NOT_A_TERMINAL
    for handle, flag, reason in ((handles[0], ENABLE_VIRTUAL_TERMINAL_INPUT, NO_VT_INPUT),
                                 (handles[1], ENABLE_VIRTUAL_TERMINAL_PROCESSING, NO_VT_OUTPUT)):
        mode = ctypes.c_uint32(0)
        if not kernel32.GetConsoleMode(handle, mode):
            return NOT_A_CONSOLE
        if not kernel32.SetConsoleMode(handle, mode.value | flag):
            return reason
        kernel32.SetConsoleMode(handle, mode.value)
    return ""


class WindowsConsole:
    """The console's modes, its input as UTF-8 bytes, and its size changes, for one `Terminal` entry."""

    def __init__(
        self,
        input_fd: int,
        output_fd: int,
        *,
        kernel32: Any = None,
        handle_of: Callable[[int], int] | None = None,
        size_of: Callable[[], tuple[int, int]] | None = None,
    ) -> None:
        self._kernel32 = kernel32 if kernel32 is not None else load_kernel32()
        self._handle_of = handle_of or os_handle
        self._input = self._handle_of(input_fd)
        self._output = self._handle_of(output_fd)
        self._size_of = size_of or (lambda: _console_size(output_fd))
        self._saved: tuple[int, int, int, int] | None = None  # input mode, output mode, input CP, output CP
        self._ready = threading.Condition()
        self._chunks: deque[bytes] = deque()
        self._eof = False
        self._stop = False
        self._abandoned = False  # set by `restore` for a reader it could not stop: what it reads is put back
        self._reader: threading.Thread | None = None
        self._size: tuple[int, int] | None = None
        self._size_checked = 0.0
        self._resized = False

    def enter(self) -> None:
        """Save the modes and code pages and set the TUI's; a failure puts back whatever was set and raises OSError."""
        kernel32 = self._kernel32
        input_mode, output_mode = ctypes.c_uint32(0), ctypes.c_uint32(0)
        if not kernel32.GetConsoleMode(self._input, input_mode) or not kernel32.GetConsoleMode(self._output, output_mode):
            raise OSError("the console modes cannot be read")
        self._saved = (input_mode.value, output_mode.value, kernel32.GetConsoleCP(), kernel32.GetConsoleOutputCP())
        entered = False
        try:
            if not kernel32.SetConsoleMode(self._input, raw_input_mode(input_mode.value)):
                raise OSError(NO_VT_INPUT)
            if not kernel32.SetConsoleMode(self._output, vt_output_mode(output_mode.value)):
                raise OSError(NO_VT_OUTPUT)
            kernel32.SetConsoleCP(CP_UTF8)
            kernel32.SetConsoleOutputCP(CP_UTF8)
            self._size = self._measure()
            self._size_checked = time.monotonic()
            self._stop = self._abandoned = False
            reader = threading.Thread(target=self._pump, name="omh-tui-console-input", daemon=True)
            reader.start()
            self._reader = reader  # only a started thread: `restore` joins it
            entered = True
        finally:
            if not entered:
                self.restore()

    def restore(self) -> None:
        """Stop the reader and put back the code pages and modes entering saved, in reverse order. Never raises
        for a console that is gone: there is nothing left to restore then."""
        saved, self._saved = self._saved, None
        try:
            self._stop_reader()
        finally:  # no reader failure may leave the console raw
            if saved is not None:
                input_mode, output_mode, input_cp, output_cp = saved
                kernel32 = self._kernel32
                kernel32.SetConsoleOutputCP(output_cp)
                kernel32.SetConsoleCP(input_cp)
                kernel32.SetConsoleMode(self._output, output_mode)
                kernel32.SetConsoleMode(self._input, input_mode)

    def set_mouse(self, enabled: bool) -> None:
        """QuickEdit off while mouse reports are on, so a click is a report; back as it was when they go off."""
        if self._saved is not None:
            self._kernel32.SetConsoleMode(self._input, raw_input_mode(self._saved[0], mouse=enabled))

    def read(self, timeout: float, wake: int | None = None) -> bytes:
        """Queued input, or b"" after `timeout`, once `wake` holds a byte, or once the size changed.

        Raises EOFError once the console is gone and everything read before
        that has been handed out.
        """
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            with self._ready:
                if self._chunks:
                    data = b"".join(self._chunks)
                    self._chunks.clear()
                    return data
                if self._eof:
                    raise EOFError("the console is gone")
            if wake is not None and self._wake_ready(wake):
                return b""
            if self._poll_size():
                return b""
            left = deadline - time.monotonic()
            if left <= 0:
                return b""
            with self._ready:
                if not self._chunks and not self._eof:
                    self._ready.wait(min(left, READ_SLICE_SECONDS))

    def resized(self) -> bool:
        """True once per size change since the last call."""
        self._poll_size()
        resized, self._resized = self._resized, False
        return resized

    def _measure(self) -> tuple[int, int] | None:
        try:
            return self._size_of()
        except OSError:
            return None

    def _poll_size(self) -> bool:
        """Measure the console at most every `RESIZE_POLL_SECONDS`; True when this measure found a new size."""
        now = time.monotonic()
        if now - self._size_checked < RESIZE_POLL_SECONDS:
            return False
        self._size_checked = now
        size = self._measure()
        if size is None or size == self._size:
            return False
        self._size = size
        self._resized = True
        return True

    def _wake_ready(self, wake: int) -> bool:
        """Whether the wake pipe holds a byte, without taking it; a pipe whose writer closed counts as woken."""
        available = ctypes.c_uint32(0)
        try:
            handle = self._handle_of(wake)
        except OSError:
            return True
        if not self._kernel32.PeekNamedPipe(handle, None, 0, None, available, None):
            return True
        return available.value > 0

    def _pump(self) -> None:
        """The reader thread: console input as UTF-8 chunks on the queue, then the end once the console is gone."""
        kernel32 = self._kernel32
        records = (INPUT_RECORD * READ_RECORDS)()
        high: int | None = None  # a high surrogate whose low half has not been read yet
        while not self._stop:
            state = kernel32.WaitForSingleObject(self._input, INPUT_WAIT_MS)
            if self._stop:
                return
            if state == WAIT_TIMEOUT:
                continue
            pending, count = ctypes.c_uint32(0), ctypes.c_uint32(0)
            if state != WAIT_OBJECT_0 or not kernel32.GetNumberOfConsoleInputEvents(self._input, pending):
                self._end()
                return
            if pending.value == 0:
                continue  # the signal's records are gone already: a read now would wait for the next one
            if not kernel32.ReadConsoleInputW(self._input, records, min(pending.value, READ_RECORDS), count):
                if self._stop:  # CancelIoEx from `restore`
                    return
                self._end()
                return
            if self._abandoned:  # `restore` returned while this read waited: the records are the shell's
                kernel32.WriteConsoleInputW(self._input, records, count.value, ctypes.c_uint32(0))
                return
            # Queued even if `restore` began meanwhile (it has not returned): these keys were typed for the TUI.
            units = record_units(records[: count.value])
            if high is not None:
                units.insert(0, high)
                high = None
            if units and 0xD800 <= units[-1] <= 0xDBFF:
                high = units.pop()
            if units:
                with self._ready:
                    self._chunks.append(utf16_to_utf8(units))
                    self._ready.notify_all()

    def _end(self) -> None:
        with self._ready:
            self._eof = True
            self._ready.notify_all()

    def _stop_reader(self) -> None:
        reader, self._reader = self._reader, None
        if reader is None:
            return
        self._stop = True
        self._kernel32.CancelIoEx(self._input, None)  # a belt: the reader waits only in WaitForSingleObject
        reader.join(STOP_JOIN_SECONDS)
        if reader.is_alive():  # CancelIoEx did not release it: cancel the I/O the thread itself waits in
            self._cancel_thread_io(reader)
            reader.join(STOP_JOIN_SECONDS)
        if reader.is_alive():  # neither cancel took: the console is the shell's now, so is anything it reads
            self._abandoned = True

    def _cancel_thread_io(self, reader: threading.Thread) -> None:
        kernel32 = self._kernel32
        thread = kernel32.OpenThread(THREAD_TERMINATE, False, reader.native_id)
        if not thread:
            return
        try:
            kernel32.CancelSynchronousIo(thread)
        finally:
            kernel32.CloseHandle(thread)
