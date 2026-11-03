"""What would end the OMH TUI's view or garble its screen, kept to a bounded log while the TUI owns the terminal.

The live region finds its rows by relative cursor moves (`screen`), so a line
written to the terminal by anything else moves every frame after it. While
`FaultLog.contained` is entered, what would otherwise land there goes into the
log instead: an uncaught exception in a background thread
(`threading.excepthook`), a Python warning (`warnings.showwarning`) and
anything written to `sys.stdout` or `sys.stderr`. On exit the hooks and the
streams it found are put back, so a crash that ends the TUI prints its
traceback on the shell's terminal once the terminal is restored, as before.

It swaps Python's objects, never file descriptors 1 and 2. The TUI paints with
`os.write` on its own descriptor (`Terminal`), which a swapped `sys.stdout`
does not touch, and the gateway child writes its stderr to a pipe of its own
(`GatewayClient`), so neither depends on what Python's streams are. The swapped
stream (`_LogStream`) is text only: it has no `fileno()` and no `.buffer`, so
code that asks either of `sys.stdout` or `sys.stderr` while the TUI runs gets
`io.UnsupportedOperation` or `AttributeError`.

The stream output is the last `STDERR_TAIL_LINES` lines, the cap of the
gateway's own stderr tail. `fault` keeps the traceback of a part of the frame
that could not be drawn (`App._drawn`) apart from it, once per part and raise
site however many frames raise it, at most `FAULT_CAP` of them, so no amount of
stream output pushes out the traceback a warn row points at. `/logs` shows the
tracebacks, then the stream output, after the gateway's tail. The first
background-thread exception is also told to the loop once (`take_thread_fault`)
for a warning in the transcript, since a dying thread is otherwise silent.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import io
import sys
import threading
import traceback
import warnings
from typing import Any, TextIO

from .gateway import STDERR_LINE_CHARS, STDERR_TAIL_LINES

# The frame parts' tracebacks kept at once; a new one past it lets the oldest go (it is kept again if it raises again).
FAULT_CAP = 20


class FaultLog:
    """The OMH TUI's own stderr while it owns the terminal: the last `STDERR_TAIL_LINES` lines, in memory only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()  # threads write here: the excepthook runs in the thread that raised
        self._lines: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self._partial = ""  # a stream write's text after its last newline, until the newline comes
        # (part, exception class, innermost file, line) -> its traceback's lines, oldest first; never the stream's
        self._faults: dict[tuple[str, str, str, int], list[str]] = {}
        self._thread_kept = False  # a background thread's exception was kept
        self._thread_told = False  # and `take_thread_fault` said so
        self.wake: Callable[[], None] | None = None  # wakes the loop from the thread that raised

    def lines(self) -> list[str]:
        """The frame parts' tracebacks, then the stream output, oldest first."""
        with self._lock:
            return [line for shown in self._faults.values() for line in shown] + list(self._lines)

    def take_thread_fault(self) -> bool:
        """True once, the first time it is asked after a background thread's exception was kept."""
        with self._lock:
            if not self._thread_kept or self._thread_told:
                return False
            self._thread_told = True
            return True

    def write(self, text: str) -> None:
        """Keep `text` as lines; what follows its last newline waits for the next write's."""
        with self._lock:
            *done, self._partial = (self._partial + text).split("\n")
            self._lines.extend(line.rstrip("\r")[:STDERR_LINE_CHARS] for line in done)

    def fault(self, part: str, error: BaseException) -> None:
        """Keep `error`'s traceback under `part`, the frame's part it came from, unless one of its class raised on
        the same line is kept already: a message that changes every frame (a count, a time), or a recursion that
        reaches that line at another depth, is still one fault. Only a new one is formatted."""
        innermost = error.__traceback__
        while innermost is not None and innermost.tb_next is not None:
            innermost = innermost.tb_next
        site = ("", 0) if innermost is None else (innermost.tb_frame.f_code.co_filename, innermost.tb_lineno)
        where = (part, type(error).__qualname__, *site)
        with self._lock:
            if where in self._faults:
                return
        shown = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        kept = [f"omh tui: {part} could not be drawn", *(line[:STDERR_LINE_CHARS] for line in shown.splitlines())]
        with self._lock:
            self._faults[where] = kept
            while len(self._faults) > FAULT_CAP:
                del self._faults[next(iter(self._faults))]

    @contextmanager
    def contained(self) -> Iterator[None]:
        """While entered: thread exceptions, warnings and `sys.stdout`/`sys.stderr` writes go to this log."""
        saved = (threading.excepthook, warnings.showwarning, sys.stdout, sys.stderr)
        stream = _LogStream(self)
        threading.excepthook = self._thread_raised
        warnings.showwarning = self._warned
        sys.stdout = sys.stderr = stream
        try:
            yield
        finally:
            threading.excepthook, warnings.showwarning, sys.stdout, sys.stderr = saved
            with self._lock:
                if self._partial:  # the last write's unfinished line
                    self._lines.append(self._partial[:STDERR_LINE_CHARS])
                    self._partial = ""

    def _thread_raised(self, args: threading.ExceptHookArgs) -> None:
        """`threading.excepthook`: the traceback Python would print, into the log (a SystemExit stays silent)."""
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread is not None else threading.get_ident()
        shown = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        self.write(f"Exception in thread {name}:\n{shown}")
        with self._lock:
            first, self._thread_kept = not self._thread_kept, True
        if first and self.wake is not None:
            self.wake()  # the loop says it in the transcript (`take_thread_fault`) without waiting out its read

    def _warned(
        self, message: Warning | str, category: type[Warning], filename: str, lineno: int,
        file: TextIO | None = None, line: str | None = None,
    ) -> None:
        """`warnings.showwarning`: the warning, as Python formats it, into the log."""
        self.write(warnings.formatwarning(message, category, filename, lineno, line))


class _LogStream(io.TextIOBase):
    """`sys.stdout` and `sys.stderr` while contained: text written is the log's, never the terminal's."""

    def __init__(self, log: FaultLog) -> None:
        super().__init__()
        self._log = log

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return "utf-8"

    def writable(self) -> bool:
        return True

    def write(self, text: Any) -> int:
        self._log.write(str(text))
        return len(text)
