"""The real terminal: raw mode, bracketed paste, key reports, size, resize signal, and byte IO.

This is the only module of the OMH TUI that touches a tty. Everything above it
works on bytes in (`read`) and text out (`write`), so it runs in tests against
a pipe, a pty, or a list.

Raw mode here is full raw, not the cbreak mode `omh theme` uses: ISIG is off so
Ctrl+C arrives as a key the composer can bind (the gateway ignores SIGINT
anyway), IXON is off so Ctrl+S/Ctrl+Q reach it too, ICRNL is off so Enter
reads as CR and Ctrl+J as LF, and OPOST is off so "\\n" is a bare line feed:
the screen writes "\\r\\n" itself and owns every cursor move. Attributes are
put back on exit whether the block ended normally or by an exception.

On the terminals Hermes' own TUI trusts with them, entering also asks for the
kitty keyboard protocol and xterm modifyOtherKeys, so Ctrl+Enter and
Shift+Enter can arrive as keys of their own; `OMH_TUI_KEYBOARD=legacy` keeps
the plain bytes everywhere. `keyboard_protocol` says only that it asked: a
terminal on the list can ignore the request (tmux with `extended-keys off`),
and then Ctrl+Enter arrives as Enter. Every other terminal, unless it is
Ghostty or `OMH_TUI_KEYBOARD=legacy` is set, gets the kitty flags pushed only
when it answers the kitty keyboard query in the startup query
(`query_background`): an answer says it speaks the protocol (Otty, with its
`kitty-keyboard` setting on, is one). A terminal the environment does not
name (over SSH, where TERM_PROGRAM rarely arrives) gets them only when its
XTVERSION answer names one of `PUSH_BY_XTVERSION`, since an unnamed answer
may come from Ghostty. Whether the reports really come is
`KeyDecoder.protocol_reported`, which turns on at the terminal's answer to the
kitty keyboard query when that answer says the flag is on, or else at the
first key that arrives as a report.

Mouse reporting is off unless `set_mouse(True)` turns it on, and then only
clicks and the wheel are reported, in SGR form. `set_mouse(True, drag=True)`
adds the motion of a held button (the pager's drag to select); motion with no
button held is never asked for. Every exit turns both off again
(`mouse_reporting` and `mouse_drag` say whether they are on).

`query_background` asks the terminal for its background colour once, before
the first frame, so the theme can be measured against the background the
person really has (`theme.build_theme`), and in the same write for the row
its cursor is on, which the launch reads to know whether any row above the
cursor needs pushing into scrollback before the first frame
(`App.clear_launch_screen`): OSC 11, then the cursor position request (CSI 6n), then the kitty keyboard query (CSI ? u),
whose answer stays in the input for the decoder to read, with a device-attributes request behind them that
every terminal answers, in order, so that answer ends the wait whether or not
the others were answered, and `BACKGROUND_QUERY_SECONDS` bounds it when
nothing comes. Keys typed while it waits are handed back to the caller. A terminal that does not answer OSC 11
can still say light or dark through `COLORFGBG`: a light background as its
colour (`background_from_colorfgbg`), a dark one only as dark
(`colorfgbg_names_dark`), for which the caller stands in a dark colour.

`read` waits on the input and, when the caller names one, a wake descriptor
(the gateway client's), and a resize signal ends its wait too, so the loop can
sleep until there is input, news from the gateway, or a new size.

`suspend` is Ctrl+Z for a raw terminal, where ISIG is off and the key is a
byte: it puts the terminal back as the shell had it, stops the whole job
with SIGTSTP (the shell's job, the gateway in it included, as a Ctrl+Z the
terminal turned into a signal would), and enters raw mode again once the
shell continues it. Where there is no SIGTSTP (no job control) it does
nothing. A process group with no shell to continue it (orphaned, as a
program started straight in a tmux pane) is not stopped by the kernel, so
the terminal is entered again at once.

Windows has no termios; `terminal_supported` reports that, and the caller
takes the fallback path instead of entering a `Terminal`.
"""

from __future__ import annotations

from collections.abc import Mapping
import errno
import os
import re
import select
import signal
import sys
import time
from types import FrameType, TracebackType
from typing import Protocol

from .screen import AUTOWRAP_ON, SHOW_CURSOR
from .style import CSI, SGR_RESET

try:  # pragma: no cover - exercised by platform, not by a branch test
    import termios
except ImportError:  # pragma: no cover - Windows ships no termios
    termios = None  # type: ignore[assignment]

BRACKETED_PASTE_ON = f"{CSI}?2004h"
BRACKETED_PASTE_OFF = f"{CSI}?2004l"
# Richer key reports, so Ctrl+Enter and Shift+Enter differ from Enter: the kitty
# keyboard protocol (push flag 1, "disambiguate") and xterm modifyOtherKeys level 2.
KITTY_KEYBOARD_PUSH = f"{CSI}>1u"
KITTY_KEYBOARD_POP = f"{CSI}<u"
# Asks which kitty keyboard flags are on; a terminal that speaks the protocol answers `CSI ? <flags> u`, before its
# answer to a device-attributes request sent after it, and one that does not answers nothing.
KITTY_KEYBOARD_QUERY = f"{CSI}?u"
MODIFY_OTHER_KEYS_ON = f"{CSI}>4;2m"
MODIFY_OTHER_KEYS_OFF = f"{CSI}>4m"
# Mouse reports: button presses and releases, the wheel included (xterm mode
# 1000), sent in SGR form (1006) so any column and row can be reported. Never
# 1003, which reports motion with no button held too.
MOUSE_REPORTING_ON = f"{CSI}?1000h{CSI}?1006h"
# The motion of a held button as well (1002), only on top of the above and only for a drag to select.
MOUSE_DRAG_ON = f"{CSI}?1002h"
MOUSE_DRAG_OFF = f"{CSI}?1002l"
MOUSE_REPORTING_OFF = f"{CSI}?1006l{MOUSE_DRAG_OFF}{CSI}?1000l"
# Written on exit even after a crash mid-frame: the screen hides the cursor and
# turns autowrap off while it paints, and a shell must not inherit either. The
# key and mouse reports are switched off whether or not they were asked for, as
# Hermes' own TUI does on every exit (hermes-ink `ink.tsx`, its signal-exit path
# too), so no exit path depends on remembering whether they were asked for.
RESTORE_SEQUENCE = (
    f"{SGR_RESET}{AUTOWRAP_ON}{SHOW_CURSOR}{MODIFY_OTHER_KEYS_OFF}{KITTY_KEYBOARD_POP}"
    f"{MOUSE_REPORTING_OFF}{BRACKETED_PASTE_OFF}"
)

# Terminals asked for the richer key reports, by the name Hermes' own TUI gives
# them (hermes-ink `ink/terminal.ts` EXTENDED_KEYS_TERMINALS, an allowlist
# because some terminals honour the request and then send codes a parser does
# not expect). Ghostty's kitty mode drops Alt from Backspace, so it gets
# modifyOtherKeys only.
KEYBOARD_PROTOCOL_TERMINALS = frozenset({"iTerm.app", "kitty", "WezTerm", "ghostty", "tmux", "windows-terminal", "vscode"})
MODIFY_OTHER_KEYS_ONLY_TERMINALS = frozenset({"ghostty"})
# OMH_TUI_KEYBOARD=legacy keeps the plain key bytes on any terminal.
KEYBOARD_OPT_OUT = "legacy"

READ_CHUNK_BYTES = 4096
FALLBACK_SIZE = (80, 24)

# The startup background query: OSC 11 asks for the background colour, the cursor position request (CPR) for the
# cursor's row, and the device-attributes request (DA1) behind them is answered by every terminal, after the other
# answers if there are any, so its answer ends the wait.
BACKGROUND_QUERY = "\x1b]11;?\x07"
# The living wallpaper's background (`App._sync_ground`): OSC 11 sets the terminal's default background, and on the
# way out the colour the startup query read is set back. Not OSC 111 (reset to the profile's default) after it: a
# background set at runtime before the TUI started (base16-shell and the like) is the one the person had, and 111
# would drop it for the profile's.
OSC_TERMINATOR = "\x1b\\"


def background_set(colour: str) -> str:
    """OSC 11: the terminal's default background becomes `colour` (`#rrggbb`)."""
    return f"\x1b]11;{colour}{OSC_TERMINATOR}"


def background_restore(original: str) -> str:
    """The terminal's background put back: `original`, the colour it reported at start."""
    return background_set(original)


CURSOR_POSITION_QUERY = f"{CSI}6n"
DEVICE_ATTRIBUTES_QUERY = f"{CSI}c"
BACKGROUND_QUERY_SECONDS = 0.1
# `ESC ] 11 ; rgb:R/G/B` ended by BEL or ST, each channel one to four hex digits (xterm's `XParseColor` forms).
_BACKGROUND_REPLY = re.compile(rb"\x1b\]11;rgb:([0-9A-Fa-f]{1,4})/([0-9A-Fa-f]{1,4})/([0-9A-Fa-f]{1,4})(?:\x07|\x1b\\)")
_DEVICE_ATTRIBUTES_REPLY = re.compile(rb"\x1b\[\?[0-9;]*c")
# The kitty keyboard query's answer, `ESC [ ? flags u`: the terminal speaks the protocol.
_KITTY_FLAGS_REPLY = re.compile(rb"\x1b\[\?[0-9]*u")
# XTVERSION: asks the terminal its name and version; the answer is `ESC P > | name ST` (ST is `ESC \`, or BEL).
XTVERSION_QUERY = f"{CSI}>0q"
_XTVERSION_REPLY = re.compile(rb"\x1bP>\|([^\x1b\x07]*)(?:\x1b\\|\x07)")
# The terminals an XTVERSION name may get the kitty flags pushed on an answer, by its first word, any case: the
# ones known to read flag 1 as the TUI does. Ghostty is not one (its kitty mode drops Alt from Backspace).
PUSH_BY_XTVERSION = frozenset({"kitty", "wezterm", "foot", "alacritty", "rio", "otty"})
# `ESC [ row ; col R`, both 1-based: the cursor position report.
_CURSOR_POSITION_REPLY = re.compile(rb"\x1b\[([0-9]{1,5});([0-9]{1,5})R")
# `COLORFGBG`'s background field names a colour of the basic sixteen: 7 and 15 are the light ones (xterm's values),
# 0 to 6 and 8 the dark ones.
COLORFGBG_LIGHT = {"7": "#E5E5E5", "15": "#FFFFFF"}
COLORFGBG_DARK = frozenset({"0", "1", "2", "3", "4", "5", "6", "8"})

# Indices into the list termios.tcgetattr returns.
_IFLAG = 0
_OFLAG = 1
_CFLAG = 2
_LFLAG = 3
_CC = 6


class _TtyProbe(Protocol):
    def isatty(self) -> bool: ...


def terminal_supported(stdin: _TtyProbe | None, stdout: _TtyProbe | None, environ: Mapping[str, str]) -> bool:
    """True only when the OMH TUI can own this terminal; False means take the fallback."""
    return not terminal_blocker(stdin, stdout, environ)


def terminal_blocker(stdin: _TtyProbe | None, stdout: _TtyProbe | None, environ: Mapping[str, str]) -> str:
    """Why the OMH TUI cannot own this terminal, in one line, or "" when it can."""
    if termios is None:
        return "the OMH TUI needs termios, which this platform does not have"
    if environ.get("TERM", "") == "dumb":
        return "TERM=dumb cannot draw the OMH TUI"
    if environ.get("OMH_NO_TUI", "") == "1":
        return "OMH_NO_TUI=1 turns the OMH TUI off"
    for stream in (stdin, stdout):
        if stream is None:
            return "stdin or stdout is not a terminal"
        try:
            if not stream.isatty():
                return "stdin or stdout is not a terminal"
        except (OSError, ValueError):
            # A closed or detached stream is not a terminal.
            return "stdin or stdout is not a terminal"
    return ""


def terminal_name(environ: Mapping[str, str]) -> str:
    """The terminal's name, read the way Hermes' own TUI reads it (hermes-ink `utils/env.ts` detectTerminal)."""
    term = environ.get("TERM", "")
    if environ.get("CURSOR_TRACE_ID"):
        return "cursor"
    if term == "xterm-ghostty":
        return "ghostty"
    if "kitty" in term:
        return "kitty"
    if environ.get("TERM_PROGRAM"):
        return environ["TERM_PROGRAM"]
    if environ.get("TMUX"):
        return "tmux"
    if environ.get("STY"):
        return "screen"
    if environ.get("KITTY_WINDOW_ID"):
        return "kitty"
    if environ.get("WT_SESSION"):
        return "windows-terminal"
    return term


def keyboard_protocol_request(environ: Mapping[str, str]) -> str:
    """What `Terminal` writes on entry to ask for the richer key reports; "" when it does not ask."""
    if environ.get("OMH_TUI_KEYBOARD", "") == KEYBOARD_OPT_OUT:
        return ""
    name = terminal_name(environ)
    if name not in KEYBOARD_PROTOCOL_TERMINALS:
        return ""
    if name in MODIFY_OTHER_KEYS_ONLY_TERMINALS:
        return MODIFY_OTHER_KEYS_ON
    return KITTY_KEYBOARD_PUSH + MODIFY_OTHER_KEYS_ON


def xtversion_pushable(name: bytes) -> bool:
    """Whether an XTVERSION answer's name (`kitty(0.35.2)`, `WezTerm 20240203`) is one of `PUSH_BY_XTVERSION`."""
    first = re.split(rb"[\s(]", name.strip(), maxsplit=1)[0]
    return first.decode("ascii", "replace").lower() in PUSH_BY_XTVERSION


def _channel_byte(digits: bytes) -> int:
    """One channel of an `rgb:` answer scaled to 0..255, whatever its digit count."""
    return round(int(digits, 16) * 255 / (16 ** len(digits) - 1))


def split_background_replies(data: bytes) -> tuple[str | None, bytes, bool]:
    """(`#RRGGBB` from an OSC 11 answer or None, `data` without the answers, whether the DA1 answer has arrived).

    Whatever else `data` holds is keys typed while the query waited, kept in
    the order they came.
    """
    colour = None
    found = _BACKGROUND_REPLY.search(data)
    if found is not None:
        colour = "#" + "".join(f"{_channel_byte(group):02X}" for group in found.groups())
        data = data[: found.start()] + data[found.end() :]
    answered = _DEVICE_ATTRIBUTES_REPLY.search(data)
    if answered is not None:
        data = data[: answered.start()] + data[answered.end() :]
    return colour, data, answered is not None


def split_cursor_reply(data: bytes) -> tuple[int | None, bytes]:
    """(the cursor's 1-based row from the position report, `data` without that report).

    The report counts only when the device-attributes answer arrived after it:
    a terminal answers in the order it was asked, so the report is the last
    `ESC [ row ; col R` before that answer, and a key of the same shape typed
    earlier stays in `data`. With no attributes answer, or no report before
    it, the row is None and `data` is unchanged.
    """
    answered = _DEVICE_ATTRIBUTES_REPLY.search(data)
    if answered is None:
        return None, data
    reports = list(_CURSOR_POSITION_REPLY.finditer(data, 0, answered.start()))
    if not reports:
        return None, data
    report = reports[-1]
    return int(report.group(1)), data[: report.start()] + data[report.end() :]


def _colorfgbg_background(environ: Mapping[str, str]) -> str:
    """`COLORFGBG`'s background field (`fg;bg` or `fg;default;bg`); "" when it is not set in either form."""
    fields = environ.get("COLORFGBG", "").split(";")
    return fields[-1] if len(fields) > 1 else ""


def background_from_colorfgbg(environ: Mapping[str, str]) -> str | None:
    """A light background `COLORFGBG` names (`fg;bg` or `fg;default;bg`), as its colour; None for anything else."""
    return COLORFGBG_LIGHT.get(_colorfgbg_background(environ))


def colorfgbg_names_dark(environ: Mapping[str, str]) -> bool:
    """Whether `COLORFGBG` names a dark background (`fg;bg` or `fg;default;bg`, bg one of 0 to 6 and 8)."""
    return _colorfgbg_background(environ) in COLORFGBG_DARK


def raw_attributes(saved: list) -> list:
    """`saved` with raw mode applied (what `tty.cfmakeraw` does on 3.12+, kept for 3.11)."""
    mode = list(saved)
    mode[_IFLAG] &= ~(termios.BRKINT | termios.ICRNL | termios.INPCK | termios.ISTRIP | termios.IXON)
    mode[_OFLAG] &= ~termios.OPOST
    mode[_CFLAG] = (mode[_CFLAG] & ~(termios.CSIZE | termios.PARENB)) | termios.CS8
    mode[_LFLAG] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG)
    special = list(mode[_CC])
    special[termios.VMIN] = 1
    special[termios.VTIME] = 0
    mode[_CC] = special
    return mode


class Terminal:
    def __init__(
        self,
        input_fd: int | None = None,
        output_fd: int | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._input = input_fd if input_fd is not None else sys.stdin.fileno()
        self._output = output_fd if output_fd is not None else sys.stdout.fileno()
        self._saved: list | None = None
        self._previous_winch: object = None
        self._winch_installed = False
        self._winch_pipe: tuple[int, int] | None = None  # the resize signal writes here to end a `read`'s wait
        self._resized = False
        environ = environ or {}
        self._keyboard_request = keyboard_protocol_request(environ)
        legacy = environ.get("OMH_TUI_KEYBOARD", "") == KEYBOARD_OPT_OUT
        # Asked with the startup query on every terminal but a legacy one: the answer says whether the flags took.
        self._keyboard_query = "" if legacy else KITTY_KEYBOARD_QUERY
        # Where entering did not push the kitty flags, a terminal that answers the query gets them then (never
        # Ghostty, whose kitty mode drops Alt from Backspace). One the environment does not name (over SSH,
        # TERM_PROGRAM rarely arrives) is asked its name too (XTVERSION), and gets them only when that names a
        # terminal in `PUSH_BY_XTVERSION`: an unnamed answer may be Ghostty.
        name = terminal_name(environ)
        self._push_on_answer = not legacy and KITTY_KEYBOARD_PUSH not in self._keyboard_request and (
            name not in MODIFY_OTHER_KEYS_ONLY_TERMINALS
        )
        self._name_query = XTVERSION_QUERY if self._push_on_answer and name == environ.get("TERM", "") else ""
        # True while the richer key reports are asked for. Asked, not reported: see the module docstring.
        self.keyboard_protocol = False
        # True while mouse reports are on (`set_mouse`), and while they include a held button's motion.
        self.mouse_reporting = False
        self.mouse_drag = False

    def __enter__(self) -> Terminal:
        if termios is None:
            raise RuntimeError("the OMH TUI needs termios; check terminal_supported() first")
        saved = termios.tcgetattr(self._input)
        # TCSANOW, not TCSAFLUSH: flushing would throw away keys typed before start.
        termios.tcsetattr(self._input, termios.TCSANOW, raw_attributes(saved))
        self._saved = saved
        entered = False
        try:
            self._install_winch()
            self.write(BRACKETED_PASTE_ON + self._keyboard_request)
            self.keyboard_protocol = bool(self._keyboard_request)
            entered = True
        finally:
            if not entered:  # __exit__ never runs for a failed __enter__
                self._restore()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._restore()

    def _restore(self) -> None:
        # A hung-up terminal (window closed) refuses the write with EIO, and it
        # has no screen to reset and no shell to hand attributes back to:
        # leaving it must not turn into a traceback on exit.
        saved, self._saved = self._saved, None
        if saved is None:
            return
        self.keyboard_protocol = False
        self.mouse_reporting = self.mouse_drag = False
        hung_up = False
        try:
            self.write(RESTORE_SEQUENCE)
        except OSError as error:
            if error.errno != errno.EIO:
                raise
            hung_up = True
        finally:
            try:
                if not hung_up:
                    termios.tcsetattr(self._input, termios.TCSANOW, saved)
            finally:
                self._uninstall_winch()

    def suspend(self) -> bool:
        """Ctrl+Z: restore the terminal, stop the job, and enter raw mode again once it continues; False, and nothing
        done, where there is no SIGTSTP or the terminal is not entered."""
        stop = getattr(signal, "SIGTSTP", None)
        if stop is None or self._saved is None:
            return False
        self._restore()
        try:
            os.kill(0, stop)  # the caller's process group; the process stops here until SIGCONT
        finally:
            self.__enter__()
        return True

    def set_mouse(self, enabled: bool, drag: bool = False) -> None:
        """Turn mouse reports on or off, with a held button's motion (`drag`) or without; writes nothing when they
        already are so.

        Only inside the `with` block: turned on outside it, nothing would turn
        them off again, and every click would type escape codes into the shell.
        """
        drag = enabled and drag
        if (enabled, drag) == (self.mouse_reporting, self.mouse_drag) or (enabled and self._saved is None):
            return
        if not enabled:
            self.write(MOUSE_REPORTING_OFF)
        else:
            switch = "" if drag == self.mouse_drag else MOUSE_DRAG_ON if drag else MOUSE_DRAG_OFF
            self.write(("" if self.mouse_reporting else MOUSE_REPORTING_ON) + switch)
        self.mouse_reporting, self.mouse_drag = enabled, drag

    def query_background(self, timeout: float = BACKGROUND_QUERY_SECONDS) -> tuple[str | None, bytes, int | None]:
        """The background colour (`#RRGGBB`, or None), the input that arrived meanwhile, and the cursor's 1-based row.

        Writes the background query, the cursor position request, the kitty
        keyboard query (not with `OMH_TUI_KEYBOARD=legacy`), and the
        attributes request behind them, then reads until the attributes answer
        arrives or `timeout` passes. A terminal entering did not push the kitty
        flags to that answers the kitty query before the attributes gets them
        pushed now, and is asked again, with the attributes behind, so its
        second answer says whether the push took; the wait for it is bounded
        by `timeout` too, and the push is popped on exit and pushed again after
        a stop, as the entry's own. Where the environment names no terminal,
        XTVERSION goes before the kitty query, its answer is taken out of the
        input, and only a name in `PUSH_BY_XTVERSION` gets the push; no
        answer before the attributes, no push. Only inside the `with` block, where input
        is raw. The row is None unless its report came before the attributes
        answer (`split_cursor_reply`). The kitty answer stays in the input
        handed back: the decoder reads it, types nothing, and learns from it
        whether Ctrl+Enter comes as a key of its own. An answer that comes
        after the wait is no key either: the decoder drops an OSC string whole,
        reads a late kitty answer as it reads an early one, and a late position
        report as an unknown key, which types nothing.
        """
        self.write(
            BACKGROUND_QUERY + CURSOR_POSITION_QUERY + self._name_query + self._keyboard_query + DEVICE_ATTRIBUTES_QUERY
        )
        data = self._read_answers(timeout)
        answered = _DEVICE_ATTRIBUTES_REPLY.search(data)
        flags = _KITTY_FLAGS_REPLY.search(data, 0, answered.start()) if answered is not None else None
        named = _XTVERSION_REPLY.search(data, 0, answered.start()) if answered is not None else None
        if named is not None:  # an answer to a query, never a key: it leaves the input here
            data = data[: named.start()] + data[named.end() :]
            answered = _DEVICE_ATTRIBUTES_REPLY.search(data)
        if self._name_query and not (named is not None and xtversion_pushable(named.group(1))):
            self._push_on_answer = False  # unnamed, or named as a terminal not known to read the flags as asked
        if self._push_on_answer and flags is not None and answered is not None:
            self._push_on_answer = False
            self._keyboard_request += KITTY_KEYBOARD_PUSH  # pushed again after a stop, popped on every exit
            self.keyboard_protocol = True
            self.write(KITTY_KEYBOARD_PUSH + KITTY_KEYBOARD_QUERY + DEVICE_ATTRIBUTES_QUERY)
            # Bytes after the first attributes answer belong to the second read; its own attributes answer goes.
            _colour, again, _answered = split_background_replies(self._read_answers(timeout, data[answered.end() :]))
            data = data[: answered.end()] + again
        row, data = split_cursor_reply(data)
        colour, typed, _answered = split_background_replies(data)
        return colour, typed, row

    def query_cursor_row(self, timeout: float = BACKGROUND_QUERY_SECONDS) -> tuple[bytes, int | None]:
        """The input that arrived meanwhile and the cursor's 1-based row, asked as `query_background` asks it.

        For a job continued after a stop, where the shell moved the cursor:
        writes the cursor position request and the attributes request behind
        it, and reads until the attributes answer or `timeout`. Only inside
        the `with` block.
        """
        self.write(CURSOR_POSITION_QUERY + DEVICE_ATTRIBUTES_QUERY)
        row, data = split_cursor_reply(self._read_answers(timeout))
        _colour, typed, _answered = split_background_replies(data)
        return typed, row

    def _read_answers(self, timeout: float, data: bytes = b"") -> bytes:
        """Input after `data` until the attributes answer arrives (the last a query asks for) or `timeout` passes."""
        deadline = time.monotonic() + timeout
        while not split_background_replies(data)[2] and (left := deadline - time.monotonic()) > 0:
            ready, _, _ = select.select([self._input], [], [], left)
            if not ready:
                break
            try:
                chunk = os.read(self._input, READ_CHUNK_BYTES)
            except OSError:
                break  # a hung-up terminal: the loop's first read says so
            if not chunk:
                break
            data += chunk
        return data

    def _on_winch(self, signum: int, frame: FrameType | None) -> None:
        self._resized = True
        if self._winch_pipe is not None:
            try:
                os.write(self._winch_pipe[1], b"\0")
            except BlockingIOError:  # full: a wait ends already
                pass

    def _install_winch(self) -> None:
        winch = getattr(signal, "SIGWINCH", None)
        if winch is None:
            return
        read_end, write_end = os.pipe()
        os.set_blocking(read_end, False)
        os.set_blocking(write_end, False)
        self._winch_pipe = (read_end, write_end)
        try:
            self._previous_winch = signal.signal(winch, self._on_winch)
        except ValueError:
            # Handlers can only be installed from the main thread; the caller
            # still sees a resize through size() on its next frame.
            self._close_winch_pipe()
            return
        self._winch_installed = True

    def _uninstall_winch(self) -> None:
        if not self._winch_installed:
            return
        previous = self._previous_winch if self._previous_winch is not None else signal.SIG_DFL
        signal.signal(signal.SIGWINCH, previous)
        self._winch_installed = False
        self._close_winch_pipe()

    def _close_winch_pipe(self) -> None:
        pipe, self._winch_pipe = self._winch_pipe, None
        for descriptor in pipe or ():
            os.close(descriptor)

    def resized(self) -> bool:
        """True once per SIGWINCH since the last call."""
        resized, self._resized = self._resized, False
        return resized

    def size(self) -> tuple[int, int]:
        """(cols, rows); a terminal that reports nothing usable gets 80x24."""
        try:
            size = os.get_terminal_size(self._output)
        except OSError:
            return FALLBACK_SIZE
        return (size.columns or FALLBACK_SIZE[0], size.lines or FALLBACK_SIZE[1])

    def read(self, timeout: float, wake: int | None = None) -> bytes:
        """Whatever input arrives within `timeout` seconds, b"" if none.

        The wait also ends, with b"", when `wake` becomes readable (the caller
        empties it) or a resize signal arrives. Raises EOFError when the
        terminal hung up, so a closed window ends the session instead of
        spinning on empty reads.
        """
        waits = [self._input, *(() if wake is None else (wake,))]
        if self._winch_pipe is not None:
            waits.append(self._winch_pipe[0])
        ready, _, _ = select.select(waits, [], [], max(timeout, 0.0))
        if self._winch_pipe is not None and self._winch_pipe[0] in ready:
            try:
                while os.read(self._winch_pipe[0], 64):
                    pass
            except BlockingIOError:
                pass
        if self._input not in ready:
            return b""
        try:
            data = os.read(self._input, READ_CHUNK_BYTES)
        except OSError as error:
            if error.errno != errno.EIO:  # Linux reports a hung-up pty as EIO
                raise
            raise EOFError("the terminal hung up") from error
        if not data:  # macOS reports it as end of file
            raise EOFError("the terminal hung up")
        return data

    def write(self, text: str) -> None:
        data = text.encode("utf-8", "replace")
        while data:
            written = os.write(self._output, data)
            data = data[written:]
