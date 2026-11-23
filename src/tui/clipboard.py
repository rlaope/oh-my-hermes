"""Where a copy from the OMH TUI's pager goes (OSC 52, or `pbcopy` on the Mac the screen is on), and the clipboard
text Ctrl+V pastes when the clipboard holds no image.

OSC 52 is never answered, so nothing confirms it reached the clipboard. It
counts as copied only for a terminal that honours it as it ships (kitty,
Ghostty, WezTerm, Alacritty) and outside tmux, which passes it on only with
`set-clipboard on`. Terminal.app ignores it and iTerm2 takes it only once its
preference allows it, so on a Mac whose screen is the one the TUI runs on (no
SSH between them) the copy goes through `pbcopy` instead, whose exit status
does confirm it. Anywhere else it goes out as OSC 52 and is reported as sent.
Inside tmux the pane's own environment says nothing about a client that
attached later over SSH, so there `pbcopy` is used only once `tmux
show-environment SSH_CONNECTION` (tmux's `update-environment` keeps it for the
last client that attached) says the variable is not set; an answer that does
not come, or does not say so, counts as remote. Both are fixed argvs, run only
for a copy the person made with the mouse in the pager, `pbcopy` with the text
on stdin.

A herdr pane (herdr, a terminal workspace manager) is the exception to both.
herdr strips TMUX, STY and ZELLIJ from its panes and keeps no SSH variables
per client (a pane inherits the long-lived server's), so the pane's
environment says nothing about where the screen is. herdr itself puts the
pane's OSC 52 on the clipboard of the machine its client runs on (as OSC 52
again when that client runs under SSH), so there the copy always goes out as
OSC 52 and counts as copied: it reached herdr, and over SSH the terminal the
person looks at must still honour OSC 52. A copy past the most herdr takes
(HERDR_CLIPBOARD_BYTES) is written too but reported as not copied, since
herdr drops it. A pane is herdr's by `TERM_PROGRAM=herdr`, or `HERDR_ENV=1`
with no `TERM_PROGRAM` at all (another terminal opened from the pane inherits
`HERDR_ENV` and sets its own). A tmux, screen or zellij started inside the pane
sets its variable again, and the rules above apply to it as before.

Ctrl+V asks Hermes for the clipboard's image (`clipboard.paste`). A terminal
that does not paste on Ctrl+V itself sends it on as ^V, so when Hermes finds
no image the TUI pastes the clipboard's text instead (`clipboard_text`), as
the terminal's own paste would have. It reads the clipboard of the machine the
TUI runs on, the one Hermes looked in for the image, and so only while that
machine's screen is the person's: no SSH variable is set and, inside tmux, the
last client did not attach over SSH (the same question as the copy's). On
Windows it reads `CF_UNICODETEXT` through the Win32 clipboard API (no
process); on a Mac one fixed `pbpaste`; on Linux one fixed `wl-paste
--no-newline --type text` under Wayland, else `xclip -selection clipboard
-out`, else `xsel --clipboard --output` under X11, each with a one-second
timeout (one that runs past it ends the search) and never more than
CLIPBOARD_TEXT_BYTES and one byte read from it; on Windows the clipboard
block's size is checked before its text is read. Text past
CLIPBOARD_TEXT_BYTES as UTF-8 counts as none. Nothing it reads goes anywhere
but the composer, as a paste; a submit the person already sent is never
changed by it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import ctypes
import subprocess
import threading
import time

from .terminal import terminal_name

COPY_OSC52 = "osc52"
COPY_PBCOPY = "pbcopy"
COPY_UNCONFIRMED = "osc52-unconfirmed"
COPY_TOO_LARGE = "osc52-too-large"  # a herdr pane's copy past HERDR_CLIPBOARD_BYTES: herdr drops it
# herdr hands a pane's OSC 52 on only up to this many bytes of decoded text (ghostty-vt's MAX_CLIPBOARD_BYTES).
HERDR_CLIPBOARD_BYTES = 192 * 1024
HERDR_TOO_LARGE = f"herdr drops a copy over {HERDR_CLIPBOARD_BYTES // 1024} KiB"  # why a COPY_TOO_LARGE is not copied
HERDR_STRIPPED = ("TMUX", "STY", "ZELLIJ")  # herdr unsets them in its panes: set, a multiplexer runs inside the pane
OSC52_TERMINALS = frozenset({"kitty", "ghostty", "WezTerm", "alacritty"})  # by `terminal_name`
SSH_VARIABLES = ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")  # set: the screen is on another machine than pbcopy's
PBCOPY_SECONDS = 2.0
TMUX_QUERY_SECONDS = 1.0
TMUX_SSH_VARIABLE = "SSH_CONNECTION"  # the one of SSH_VARIABLES in tmux's default `update-environment`
PASTE_READ_SECONDS = 1.0  # how long one clipboard reader may take
CLIPBOARD_TEXT_BYTES = 4 * 1024 * 1024  # the most clipboard text a Ctrl+V takes; more reads as no text
CF_UNICODETEXT = 13  # the Win32 clipboard format of UTF-16 text
OPEN_CLIPBOARD_TRIES = 5  # another program may hold the Windows clipboard for a moment
OPEN_CLIPBOARD_PAUSE = 0.02


def tmux_client_over_ssh(environ: Mapping[str, str]) -> bool:
    """Whether the tmux session this pane is in has `SSH_CONNECTION` set (its last client attached over SSH); True too
    when tmux does not answer within TMUX_QUERY_SECONDS or answers anything but the variable's absence."""
    try:
        done = subprocess.run(
            ["tmux", "show-environment", TMUX_SSH_VARIABLE], env=dict(environ), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=TMUX_QUERY_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    # Measured on tmux 3.7b: `-NAME` for a variable a client removed, `unknown variable: NAME` (status 1) for one the
    # session never had, `NAME=value` when set; a server it cannot reach fails with another message.
    said = done.stdout.strip()
    never_had = done.returncode != 0 and done.stderr.strip() == f"unknown variable: {TMUX_SSH_VARIABLE}"
    return not (said == f"-{TMUX_SSH_VARIABLE}" or never_had)


def herdr_takes_osc52(environ: Mapping[str, str]) -> bool:
    """Whether an OSC 52 written here goes straight to herdr: a herdr pane (`TERM_PROGRAM=herdr`, or herdr's
    `HERDR_ENV=1` with no `TERM_PROGRAM` another terminal set) with no tmux, screen or zellij started inside it."""
    program = environ.get("TERM_PROGRAM", "")
    in_herdr = program == "herdr" or (environ.get("HERDR_ENV") == "1" and not program)
    return in_herdr and not any(environ.get(name) for name in HERDR_STRIPPED)


def herdr_drops(environ: Mapping[str, str], size: int) -> bool:
    """Whether herdr drops an OSC 52 written here that carries `size` bytes of text."""
    return herdr_takes_osc52(environ) and size > HERDR_CLIPBOARD_BYTES


def copy_route(
    environ: Mapping[str, str], platform: str, tmux_over_ssh: Callable[[Mapping[str, str]], bool] = tmux_client_over_ssh,
    size: int = 0,
) -> str:
    """How a copy of `size` bytes from the pager reaches the clipboard: COPY_OSC52 where herdr takes it
    (`herdr_takes_osc52`; COPY_TOO_LARGE past what herdr takes) or for a terminal outside tmux that honours OSC 52 as
    it ships, COPY_PBCOPY on a Mac the screen is on (no SSH between them, tmux's last client included), else
    COPY_UNCONFIRMED."""
    if herdr_takes_osc52(environ):
        return COPY_TOO_LARGE if herdr_drops(environ, size) else COPY_OSC52
    if terminal_name(environ) in OSC52_TERMINALS and not environ.get("TMUX"):
        return COPY_OSC52
    if platform != "darwin" or any(environ.get(name) for name in SSH_VARIABLES):
        return COPY_UNCONFIRMED
    if environ.get("TMUX") and tmux_over_ssh(environ):
        return COPY_UNCONFIRMED
    return COPY_PBCOPY


def pbcopy(text: str, environ: Mapping[str, str]) -> bool:
    """`text` on the Mac's clipboard through `pbcopy`, read as UTF-8 whatever the locale says; False when it did not
    run or failed."""
    try:
        done = subprocess.run(
            ["pbcopy"], input=text.encode("utf-8", "replace"), env={**environ, "LC_ALL": "en_US.UTF-8"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=PBCOPY_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def text_readers(environ: Mapping[str, str], platform: str) -> tuple[tuple[str, ...], ...]:
    """The fixed argvs that print the clipboard's text here, in the order they are tried (none on Windows, which is
    read in process, or where no display is named)."""
    if platform == "darwin":
        return (("pbpaste",),)
    if not platform.startswith("linux"):
        return ()
    readers: list[tuple[str, ...]] = []
    if environ.get("WAYLAND_DISPLAY"):
        readers.append(("wl-paste", "--no-newline", "--type", "text"))
    if environ.get("DISPLAY"):
        readers += [("xclip", "-selection", "clipboard", "-out"), ("xsel", "--clipboard", "--output")]
    return tuple(readers)


def windows_clipboard_text(limit: int = CLIPBOARD_TEXT_BYTES) -> str | None:
    """The Windows clipboard's text (`CF_UNICODETEXT`), or None when it holds none, could not be opened, or holds more
    than `limit` bytes of it (the size is read before the text is)."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None
    handle, bool_ = ctypes.c_void_p, ctypes.c_int
    user32.OpenClipboard.argtypes, user32.OpenClipboard.restype = (handle,), bool_
    user32.CloseClipboard.argtypes, user32.CloseClipboard.restype = (), bool_
    user32.GetClipboardData.argtypes, user32.GetClipboardData.restype = (ctypes.c_uint,), handle
    kernel32.GlobalSize.argtypes, kernel32.GlobalSize.restype = (handle,), ctypes.c_size_t
    kernel32.GlobalLock.argtypes, kernel32.GlobalLock.restype = (handle,), handle
    kernel32.GlobalUnlock.argtypes, kernel32.GlobalUnlock.restype = (handle,), bool_
    for attempt in range(OPEN_CLIPBOARD_TRIES):
        if user32.OpenClipboard(None):
            break
        if attempt + 1 < OPEN_CLIPBOARD_TRIES:
            time.sleep(OPEN_CLIPBOARD_PAUSE)
    else:
        return None
    try:
        data = user32.GetClipboardData(CF_UNICODETEXT)
        if not data:
            return None
        size = kernel32.GlobalSize(data)  # UTF-16, so at most twice the bytes the text takes as UTF-8 here
        if not size or size > 2 * limit + 2:
            return None
        locked = kernel32.GlobalLock(data)
        if not locked:
            return None
        try:
            # never past the block: a text without its terminating NUL ends at the block's end
            return ctypes.wstring_at(locked, size // 2).split("\0", 1)[0]
        finally:
            kernel32.GlobalUnlock(data)
    finally:
        user32.CloseClipboard()


READ_OK, READ_FAILED, READ_TIMED_OUT = "ok", "failed", "timed-out"


def read_bounded(argv: list[str], env: Mapping[str, str], timeout: float, limit: int) -> tuple[str, bytes]:
    """Run `argv` and keep at most `limit` + 1 bytes of what it prints: (READ_OK, bytes) for a zero exit,
    (READ_FAILED, b"") when it could not start or failed, (READ_TIMED_OUT, b"") when it ran past `timeout` (killed)."""
    try:
        process = subprocess.Popen(
            argv, env=dict(env), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
    except (OSError, ValueError):
        return READ_FAILED, b""
    timed_out = threading.Event()

    def kill() -> None:
        timed_out.set()
        try:
            process.kill()
        except OSError:
            pass  # it ended meanwhile

    timer = threading.Timer(timeout, kill)
    timer.start()
    try:
        data = process.stdout.read(limit + 1) if process.stdout is not None else b""
        if len(data) > limit:
            try:
                process.kill()  # more than is taken: what is left is never read
            except OSError:
                pass
        if process.stdout is not None:
            process.stdout.close()
        code = process.wait()
    finally:
        timer.cancel()
    if timed_out.is_set():
        return READ_TIMED_OUT, b""
    if len(data) > limit:
        return READ_OK, data
    return (READ_OK, data) if code == 0 else (READ_FAILED, b"")


def clipboard_text(
    environ: Mapping[str, str], platform: str, tmux_over_ssh: Callable[[Mapping[str, str]], bool] = tmux_client_over_ssh,
    read: Callable[[list[str], Mapping[str, str], float, int], tuple[str, bytes]] = read_bounded,
    windows_text: Callable[[], str | None] = windows_clipboard_text,
) -> str | None:
    """The clipboard's text where the TUI runs, for a Ctrl+V that found no image; None when there is none, it is more
    than CLIPBOARD_TEXT_BYTES as UTF-8, it could not be read, or the screen is on another machine (an SSH variable, or
    tmux's last client over SSH). A reader that runs past PASTE_READ_SECONDS ends the search: the next would wait too."""
    if any(environ.get(name) for name in SSH_VARIABLES) or (environ.get("TMUX") and tmux_over_ssh(environ)):
        return None
    if platform == "win32":
        text = windows_text()
        return text if text and len(text.encode("utf-8", "replace")) <= CLIPBOARD_TEXT_BYTES else None
    for argv in text_readers(environ, platform):
        status, data = read(list(argv), {**environ, "LC_ALL": "en_US.UTF-8"}, PASTE_READ_SECONDS, CLIPBOARD_TEXT_BYTES)
        if status == READ_TIMED_OUT:
            return None
        if status != READ_OK:
            continue
        if not data or len(data) > CLIPBOARD_TEXT_BYTES:
            return None
        return data.decode("utf-8", "replace")
    return None
