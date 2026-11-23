"""The clipboard text a Ctrl+V pastes when Hermes found no image (#3131): read only where the screen is this machine's,
by one fixed reader per platform, never more than CLIPBOARD_TEXT_BYTES. Only the CI-only Windows test below touches a
real clipboard."""

from __future__ import annotations

import ctypes
import os
import sys
import time
import unittest

from omh.tui.clipboard import (
    CF_UNICODETEXT,
    CLIPBOARD_TEXT_BYTES,
    PASTE_READ_SECONDS,
    READ_FAILED,
    READ_OK,
    READ_TIMED_OUT,
    clipboard_text,
    read_bounded,
    text_readers,
    windows_clipboard_text,
)


class Reads:
    """A stand-in for `read_bounded`: the argvs it was asked to run, and each one's answer in turn."""

    def __init__(self, *answers: tuple[str, bytes]) -> None:
        self.answers = list(answers)
        self.argvs: list[list[str]] = []
        self.calls: list[tuple[dict[str, str], float, int]] = []

    def __call__(self, argv: list[str], env: dict[str, str], timeout: float, limit: int) -> tuple[str, bytes]:
        self.argvs.append(argv)
        self.calls.append((dict(env), timeout, limit))
        return self.answers.pop(0)


def never(*args: object, **kwargs: object) -> object:
    raise AssertionError("nothing may run")


class ClipboardTextTests(unittest.TestCase):
    def test_a_mac_reads_pbpaste_as_utf8_with_a_timeout_and_a_cap(self) -> None:
        reads = Reads((READ_OK, "한글 text\n".encode()))
        self.assertEqual(clipboard_text({"HOME": "/h"}, "darwin", read=reads), "한글 text\n")
        self.assertEqual(reads.argvs, [["pbpaste"]])
        self.assertEqual(reads.calls, [({"HOME": "/h", "LC_ALL": "en_US.UTF-8"}, PASTE_READ_SECONDS, CLIPBOARD_TEXT_BYTES)])

    def test_windows_reads_the_win32_clipboard_in_process(self) -> None:
        self.assertEqual(clipboard_text({}, "win32", read=never, windows_text=lambda: "from windows"), "from windows")
        self.assertIsNone(clipboard_text({}, "win32", read=never, windows_text=lambda: None))
        self.assertIsNone(clipboard_text({}, "win32", read=never, windows_text=lambda: ""))

    def test_linux_tries_wayland_then_x11_readers_in_order(self) -> None:
        both = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}
        self.assertEqual(text_readers(both, "linux"), (
            ("wl-paste", "--no-newline", "--type", "text"),
            ("xclip", "-selection", "clipboard", "-out"),
            ("xsel", "--clipboard", "--output"),
        ))
        self.assertEqual(text_readers({"DISPLAY": ":0"}, "linux")[0][0], "xclip")
        self.assertEqual(text_readers({}, "linux"), ())  # no display named: nothing to read
        self.assertEqual(text_readers({}, "win32"), ())
        # wl-paste is missing and xclip finds no text (an image only): xsel answers
        reads = Reads((READ_FAILED, b""), (READ_FAILED, b""), (READ_OK, b"from xsel"))
        self.assertEqual(clipboard_text(both, "linux", read=reads), "from xsel")
        self.assertEqual([argv[0] for argv in reads.argvs], ["wl-paste", "xclip", "xsel"])

    def test_a_reader_that_times_out_ends_the_search(self) -> None:
        reads = Reads((READ_TIMED_OUT, b""))
        self.assertIsNone(clipboard_text({"WAYLAND_DISPLAY": "w", "DISPLAY": ":0"}, "linux", read=reads))
        self.assertEqual([argv[0] for argv in reads.argvs], ["wl-paste"])  # xclip and xsel are not waited on too

    def test_empty_or_too_much_text_is_no_text(self) -> None:
        self.assertIsNone(clipboard_text({}, "darwin", read=Reads((READ_OK, b""))))
        self.assertIsNone(clipboard_text({}, "darwin", read=Reads((READ_OK, b"x" * (CLIPBOARD_TEXT_BYTES + 1)))))
        self.assertIsNone(clipboard_text({}, "win32", windows_text=lambda: "x" * (CLIPBOARD_TEXT_BYTES + 1)))
        # counted in bytes, as the other platforms count it: 3 bytes a character here
        wide = "가" * (CLIPBOARD_TEXT_BYTES // 3 + 1)
        self.assertIsNone(clipboard_text({}, "win32", windows_text=lambda: wide))

    def test_a_screen_on_another_machine_reads_nothing(self) -> None:
        for name in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"):
            self.assertIsNone(clipboard_text({name: "1"}, "darwin", read=never, windows_text=never))
            self.assertIsNone(clipboard_text({name: "1"}, "win32", read=never, windows_text=never))
        tmux = {"TMUX": "/tmp/tmux-1/default,1,0"}
        self.assertIsNone(clipboard_text(tmux, "darwin", tmux_over_ssh=lambda env: True, read=never))
        self.assertEqual(clipboard_text(tmux, "darwin", tmux_over_ssh=lambda env: False, read=Reads((READ_OK, b"ok"))), "ok")


def python(code: str) -> list[str]:
    return [sys.executable, "-I", "-c", code]


class ReadBoundedTests(unittest.TestCase):
    """`read_bounded` against a real child: what it keeps, and how long it waits."""

    def test_it_keeps_what_a_reader_printed(self) -> None:
        self.assertEqual(read_bounded(python("print('hi', end='')"), os.environ, 10.0, 100), (READ_OK, b"hi"))

    def test_a_failed_reader_or_one_that_cannot_start_is_failed(self) -> None:
        self.assertEqual(read_bounded(python("import sys; sys.exit(1)"), os.environ, 10.0, 100), (READ_FAILED, b""))
        self.assertEqual(read_bounded(["/nonexistent/omh-reader"], os.environ, 10.0, 100), (READ_FAILED, b""))

    def test_it_reads_no_more_than_the_cap_and_one_byte(self) -> None:
        # it would print forever: the read stops past the cap and the child is ended, well inside the timeout
        endless = python("import sys\nwhile True: sys.stdout.write('x' * 65536)")
        started = time.monotonic()
        status, data = read_bounded(endless, os.environ, 10.0, 1000)
        self.assertEqual((status, len(data)), (READ_OK, 1001))
        self.assertLess(time.monotonic() - started, 5.0)

    def test_one_that_hangs_is_ended_at_its_timeout(self) -> None:
        started = time.monotonic()
        self.assertEqual(read_bounded(python("import time; time.sleep(30)"), os.environ, 0.5, 100), (READ_TIMED_OUT, b""))
        self.assertLess(time.monotonic() - started, 10.0)


def put_windows_clipboard(text: str) -> None:
    """`text` as CF_UNICODETEXT on the Windows clipboard, the way a program's copy puts it there."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    handle = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes, kernel32.GlobalAlloc.restype = (ctypes.c_uint, ctypes.c_size_t), handle
    kernel32.GlobalLock.argtypes, kernel32.GlobalLock.restype = (handle,), handle
    kernel32.GlobalUnlock.argtypes = (handle,)
    user32.OpenClipboard.argtypes = (handle,)
    user32.SetClipboardData.argtypes, user32.SetClipboardData.restype = (ctypes.c_uint, handle), handle
    data = (text + "\0").encode("utf-16-le")
    memory = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
    ctypes.memmove(kernel32.GlobalLock(memory), data, len(data))
    kernel32.GlobalUnlock(memory)
    if not user32.OpenClipboard(None):
        raise OSError(ctypes.get_last_error(), "OpenClipboard")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, memory):
            raise OSError(ctypes.get_last_error(), "SetClipboardData")
    finally:
        user32.CloseClipboard()


# It replaces the clipboard, so only on a CI runner, never on a person's own Windows machine.
@unittest.skipUnless(sys.platform == "win32" and os.environ.get("CI"), "the real Windows clipboard, on a CI runner only")
class WindowsClipboardTests(unittest.TestCase):
    def test_the_win32_clipboard_text_is_read_whole(self) -> None:
        text = "pasted on Windows 한글 ✓\r\nsecond line"
        put_windows_clipboard(text)
        self.assertEqual(windows_clipboard_text(), text)
        self.assertEqual(clipboard_text({}, "win32"), text)


if __name__ == "__main__":
    unittest.main()
