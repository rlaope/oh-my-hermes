"""The clipboard text a Ctrl+V pastes when Hermes found no image (#3131): read only where the screen is this machine's,
by one fixed reader per platform, never more than CLIPBOARD_TEXT_BYTES. No test here touches the real clipboard."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import unittest

from omh.tui.clipboard import CF_UNICODETEXT, CLIPBOARD_TEXT_BYTES, PASTE_READ_SECONDS, clipboard_text, text_readers, windows_clipboard_text


class Runs:
    """A stand-in for subprocess.run: the argvs it was asked to run, and each one's answer in turn."""

    def __init__(self, *answers: subprocess.CompletedProcess[bytes] | BaseException) -> None:
        self.answers = list(answers)
        self.argvs: list[list[str]] = []
        self.options: list[dict[str, object]] = []

    def __call__(self, argv: list[str], **options: object) -> subprocess.CompletedProcess[bytes]:
        self.argvs.append(argv)
        self.options.append(options)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def printed(stdout: bytes, code: int = 0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess([], code, stdout, b"")


def never(*args: object, **kwargs: object) -> object:
    raise AssertionError("nothing may run")


class ClipboardTextTests(unittest.TestCase):
    def test_a_mac_reads_pbpaste_as_utf8_with_a_timeout(self) -> None:
        runs = Runs(printed("한글 text\n".encode()))
        self.assertEqual(clipboard_text({"HOME": "/h"}, "darwin", run=runs), "한글 text\n")
        self.assertEqual(runs.argvs, [["pbpaste"]])
        self.assertEqual(runs.options[0]["timeout"], PASTE_READ_SECONDS)
        self.assertEqual(runs.options[0]["env"], {"HOME": "/h", "LC_ALL": "en_US.UTF-8"})
        self.assertIs(runs.options[0]["stdin"], subprocess.DEVNULL)

    def test_windows_reads_the_win32_clipboard_in_process(self) -> None:
        self.assertEqual(clipboard_text({}, "win32", run=never, windows_text=lambda: "from windows"), "from windows")
        self.assertIsNone(clipboard_text({}, "win32", run=never, windows_text=lambda: None))
        self.assertIsNone(clipboard_text({}, "win32", run=never, windows_text=lambda: ""))

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
        runs = Runs(FileNotFoundError("wl-paste"), printed(b"", 1), printed(b"from xsel"))
        self.assertEqual(clipboard_text(both, "linux", run=runs), "from xsel")
        self.assertEqual([argv[0] for argv in runs.argvs], ["wl-paste", "xclip", "xsel"])
        runs = Runs(subprocess.TimeoutExpired("xclip", PASTE_READ_SECONDS), printed(b"", 1))
        self.assertIsNone(clipboard_text({"DISPLAY": ":0"}, "linux", run=runs))

    def test_empty_or_too_much_text_is_no_text(self) -> None:
        self.assertIsNone(clipboard_text({}, "darwin", run=Runs(printed(b""))))
        self.assertIsNone(clipboard_text({}, "darwin", run=Runs(printed(b"x" * (CLIPBOARD_TEXT_BYTES + 1)))))
        self.assertIsNone(clipboard_text({}, "win32", windows_text=lambda: "x" * (CLIPBOARD_TEXT_BYTES + 1)))

    def test_a_screen_on_another_machine_reads_nothing(self) -> None:
        for name in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"):
            self.assertIsNone(clipboard_text({name: "1"}, "darwin", run=never, windows_text=never))
            self.assertIsNone(clipboard_text({name: "1"}, "win32", run=never, windows_text=never))
        tmux = {"TMUX": "/tmp/tmux-1/default,1,0"}
        self.assertIsNone(clipboard_text(tmux, "darwin", tmux_over_ssh=lambda env: True, run=never))
        self.assertEqual(clipboard_text(tmux, "darwin", tmux_over_ssh=lambda env: False, run=Runs(printed(b"ok"))), "ok")


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
