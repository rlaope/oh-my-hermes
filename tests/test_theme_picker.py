"""The arrow-key picker behind bare `omh theme`.

A colour theme is the one setting a name cannot describe, so the picker paints
each palette under the cursor. These tests drive it entirely through its
injected seams -- a key-token reader and a frame sink -- because the thing it
does on a real terminal (raw mode, cursor-up repaints) is exactly what a test
harness cannot provide. What they pin: navigation lands on the theme the keys
point at, cancelling writes nothing at all, the preview paints with each
theme's OWN declared hex values, and NO_COLOR emits no escape bytes.
"""

from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _cli_harness import run_cli
from omh.commands.main import main
from _platform_support import requires_posix_select

from omh.commands.theme_picker import (
    ESC,
    KEY_DEFAULT,
    KEY_DOWN,
    KEY_ENTER,
    KEY_LEFT,
    KEY_MINUS,
    KEY_NONE,
    KEY_PLUS,
    KEY_QUIT,
    KEY_RIGHT,
    KEY_UP,
    picker_available,
    preview_lines,
    read_terminal_key,
    render_frame,
    run_picker,
)
from omh.skin_pack import SKIN_THEMES, read_theme_choice, skin_colors


def _drive(keys: list[str], *, active_skin: str = "omh", use_color: bool = False):
    """Run the picker over a scripted key sequence, returning (choice, frames)."""
    remaining = list(keys)
    frames: list[str] = []

    def read_key() -> str:
        return remaining.pop(0) if remaining else KEY_QUIT

    chosen = run_picker(
        SKIN_THEMES,
        active_skin,
        read_key=read_key,
        write=frames.append,
        use_color=use_color,
    )
    return chosen, frames


class PickerNavigationTests(unittest.TestCase):
    def test_down_down_up_enter_lands_on_the_second_theme(self) -> None:
        chosen, _ = _drive([KEY_DOWN, KEY_DOWN, KEY_UP, KEY_ENTER])
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.short_name, "amber")

    def test_enter_on_the_opening_frame_takes_the_first_theme(self) -> None:
        chosen, _ = _drive([KEY_ENTER])
        self.assertEqual(chosen.short_name, "sky")

    def test_the_cursor_wraps_at_both_ends(self) -> None:
        self.assertEqual(_drive([KEY_UP, KEY_ENTER])[0].short_name, SKIN_THEMES[-1].short_name)
        self.assertEqual(_drive([KEY_DOWN] * len(SKIN_THEMES) + [KEY_ENTER])[0].short_name, "sky")

    def test_quit_and_an_exhausted_reader_both_cancel(self) -> None:
        self.assertIsNone(_drive([KEY_DOWN, KEY_QUIT])[0])
        self.assertIsNone(_drive([])[0])

    def test_unknown_keys_are_ignored_without_moving_the_cursor(self) -> None:
        chosen, _ = _drive([KEY_NONE, KEY_NONE, KEY_ENTER])
        self.assertEqual(chosen.short_name, "sky")

    def test_the_opening_frame_lists_every_theme_and_marks_the_active_one(self) -> None:
        _, frames = _drive([KEY_ENTER], active_skin="omh-crimson")
        opening = frames[0]
        for theme in SKIN_THEMES:
            self.assertIn(theme.short_name, opening)
        self.assertIn("[*] crimson", opening)
        self.assertIn("> [ ] sky", opening)

    def test_moving_repaints_in_place_instead_of_appending_a_new_block(self) -> None:
        _, frames = _drive([KEY_DOWN, KEY_ENTER])
        self.assertEqual(len(frames), 2)
        # The repaint rewinds by exactly the row count it drew, then clears
        # each line; without the rewind the picker scrolls the terminal.
        self.assertTrue(frames[1].startswith(f"{ESC}["))
        self.assertIn("A", frames[1][:8])
        self.assertIn(f"{ESC}[2K", frames[1])


class PickerPreviewTests(unittest.TestCase):
    def test_the_preview_paints_with_the_highlighted_themes_own_palette(self) -> None:
        for index, theme in enumerate(SKIN_THEMES):
            with self.subTest(theme=theme.short_name):
                frame = "\n".join(render_frame(SKIN_THEMES, index, "omh", use_color=True, width=120))
                colors = skin_colors(theme.skin_name)
                for token in ("ui_accent", "ui_label", "ui_ok", "ui_error"):
                    red, green, blue = (
                        int(colors[token].lstrip("#")[0:2], 16),
                        int(colors[token].lstrip("#")[2:4], 16),
                        int(colors[token].lstrip("#")[4:6], 16),
                    )
                    self.assertIn(f"{ESC}[38;2;{red};{green};{blue}m", frame)

    def test_one_themes_preview_does_not_leak_another_themes_accent(self) -> None:
        crimson = skin_colors("omh-crimson")["ui_accent"].lstrip("#")
        sky_frame = "\n".join(render_frame(SKIN_THEMES, 0, "omh", use_color=True, width=120))
        red, green, blue = (int(crimson[0:2], 16), int(crimson[2:4], 16), int(crimson[4:6], 16))
        self.assertNotIn(f"{ESC}[38;2;{red};{green};{blue}m", sky_frame)

    def test_no_color_output_carries_no_escape_bytes(self) -> None:
        for index, theme in enumerate(SKIN_THEMES):
            with self.subTest(theme=theme.short_name):
                frame = "\n".join(render_frame(SKIN_THEMES, index, "omh", use_color=False, width=120))
                self.assertNotIn(ESC, frame)
                # The palette is still reported, just as text a plain terminal
                # can read rather than as colour it cannot show.
                self.assertIn(skin_colors(theme.skin_name)["ui_accent"], frame)

    def test_the_plain_preview_names_the_theme_and_the_semantic_row(self) -> None:
        lines = preview_lines(SKIN_THEMES[2], use_color=False)
        self.assertIn("crimson", lines[0])
        self.assertIn("ok", lines[2])
        self.assertIn("error", lines[2])


class TerminalKeyReaderTests(unittest.TestCase):
    """The default reader, driven over a pipe instead of a tty.

    `read_terminal_key` only needs a file descriptor, so a pipe exercises the
    exact decoding path a terminal takes without any raw-mode setup.
    """

    def _reader(self, payload: bytes):
        read_fd, write_fd = os.pipe()
        os.write(write_fd, payload)
        os.close(write_fd)
        self.addCleanup(os.close, read_fd)

        class _Stream:
            def fileno(self) -> int:
                return read_fd

        return _Stream()

    @requires_posix_select
    def test_an_arrow_sequence_is_read_whole(self) -> None:
        # The regression this exists for: reading through `sys.stdin` pulls
        # `[B` into Python's buffer, `select` on the descriptor then reports
        # nothing pending, and every arrow key cancelled the picker instead of
        # moving the cursor.
        stream = self._reader(b"\x1b[B\x1b[A")
        self.assertEqual(read_terminal_key(stream), KEY_DOWN)
        self.assertEqual(read_terminal_key(stream), KEY_UP)

    def test_plain_keys_and_end_of_input_map_to_tokens(self) -> None:
        stream = self._reader(b"jk\rq\x03")
        self.assertEqual(
            [read_terminal_key(stream) for _ in range(6)],
            [KEY_DOWN, KEY_UP, KEY_ENTER, KEY_QUIT, KEY_QUIT, KEY_QUIT],
        )

    @requires_posix_select
    def test_a_lone_escape_cancels(self) -> None:
        self.assertEqual(read_terminal_key(self._reader(b"\x1b")), KEY_QUIT)

    @requires_posix_select
    def test_an_unrecognised_escape_sequence_is_ignored_not_obeyed(self) -> None:
        # Shift-Tab: no OMH picker binds it. (`[C` used to be the example
        # here and is the right arrow now, a token the chain picker uses.)
        self.assertEqual(read_terminal_key(self._reader(b"\x1b[Z")), KEY_NONE)

    @requires_posix_select
    def test_horizontal_arrows_and_their_vi_keys_share_tokens(self) -> None:
        # The theme picker ignores these; the chain picker steps a row with
        # them. One reader serves both, so the tokens are pinned here.
        stream = self._reader(b"\x1b[D\x1b[Chl-+=d")
        self.assertEqual(
            [read_terminal_key(stream) for _ in range(9)],
            [KEY_LEFT, KEY_RIGHT, KEY_LEFT, KEY_RIGHT, KEY_MINUS, KEY_PLUS, KEY_PLUS, KEY_DEFAULT, KEY_QUIT],
        )


class PickerAvailabilityTests(unittest.TestCase):
    def test_a_non_terminal_pair_never_gets_the_picker(self) -> None:
        class _NotATty:
            def isatty(self) -> bool:
                return False

        class _IsATty:
            def isatty(self) -> bool:
                return True

        self.assertFalse(picker_available(stdin=_NotATty(), stdout=_IsATty()))
        self.assertFalse(picker_available(stdin=_IsATty(), stdout=_NotATty()))

    def test_a_platform_without_termios_falls_back(self) -> None:
        # Windows ships no termios; the documented behaviour there is the plain
        # list, not a half-working picker.
        class _IsATty:
            def isatty(self) -> bool:
                return True

        with patch("omh.commands.theme_picker.termios", None):
            self.assertFalse(picker_available(stdin=_IsATty(), stdout=_IsATty()))


class PickerCommandIntegrationTests(unittest.TestCase):
    def _homes(self, tmp: str) -> list[str]:
        root = Path(tmp)
        (root / "hermes").mkdir()
        (root / "omh").mkdir()
        return ["--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes")]

    def _config_text(self, tmp: str) -> str:
        path = Path(tmp) / "hermes" / "config.yaml"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_bare_theme_without_a_terminal_degrades_to_the_plain_list(self) -> None:
        # The harness has no tty, which is the same shape as a pipe or CI.
        with TemporaryDirectory() as tmp:
            status, out, _ = run_cli([*self._homes(tmp), "theme"], output_json=False)
            self.assertEqual(status, 0)
            self.assertIn("OMH TUI themes", out)
            self.assertNotIn("Enter to apply", out)

    def test_closed_stdin_degrades_to_the_plain_list_for_theme_and_model_chains(self) -> None:
        # `<&-` leaves sys.stdin as None. termios/tty are stood in for and TERM
        # is a real terminal's, so the probe is reached on every platform.
        for command, heading in (("theme", "OMH TUI themes"), ("model-chains", "Current model chains")):
            with self.subTest(command=command), TemporaryDirectory() as tmp:
                stdout, stderr = io.StringIO(), io.StringIO()
                with (
                    patch.dict(os.environ, {"TERM": "xterm-256color"}),
                    patch("omh.commands.theme_picker.termios", object()),
                    patch("omh.commands.theme_picker.tty", object()),
                    patch.object(sys, "stdin", None),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    os.environ.pop("OMH_NO_TUI", None)
                    os.environ.pop("OMH_OUTPUT", None)
                    status = main([*self._homes(tmp), command])
                self.assertEqual(status, 0, stderr.getvalue())
                self.assertIn(heading, stdout.getvalue())

    def test_a_picked_theme_is_written_through_the_same_selection_path(self) -> None:
        with TemporaryDirectory() as tmp:
            with (
                patch("omh.commands.theme.picker_available", return_value=True),
                patch(
                    "omh.commands.theme.pick_theme_interactively",
                    return_value=SKIN_THEMES[2],
                ),
            ):
                status, out, _ = run_cli([*self._homes(tmp), "theme"], output_json=False)
            self.assertEqual(status, 0)
            self.assertIn("OMH theme: crimson", out)
            self.assertIn("the next time you run `omh`", out)
            self.assertEqual(read_theme_choice(Path(tmp) / "omh"), SKIN_THEMES[2])
            # The OMH TUI's theme, not Hermes': nothing lands in the Hermes home.
            self.assertEqual(self._config_text(tmp), "")
            self.assertFalse((Path(tmp) / "hermes" / "skins").exists())

    def test_cancelling_the_picker_writes_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            with (
                patch("omh.commands.theme.picker_available", return_value=True),
                patch("omh.commands.theme.pick_theme_interactively", return_value=None),
            ):
                status, out, _ = run_cli([*self._homes(tmp), "theme"], output_json=False)
            self.assertEqual(status, 0)
            self.assertIn("Cancelled", out)
            self.assertIsNone(read_theme_choice(Path(tmp) / "omh"))
            self.assertEqual(self._config_text(tmp), "")
            self.assertFalse((Path(tmp) / "hermes" / "skins").exists())

    def test_theme_list_stays_plain_even_on_a_terminal(self) -> None:
        # `list` is the scriptable surface; a picker there would break anyone
        # piping it.
        with TemporaryDirectory() as tmp:
            with patch("omh.commands.theme.picker_available", return_value=True) as available:
                status, out, _ = run_cli([*self._homes(tmp), "theme", "list"], output_json=False)
            self.assertEqual(status, 0)
            available.assert_not_called()
            self.assertIn("OMH TUI themes", out)

    def test_json_never_opens_the_picker(self) -> None:
        with TemporaryDirectory() as tmp:
            with patch("omh.commands.theme.pick_theme_interactively") as picker:
                status, _, _ = run_cli([*self._homes(tmp), "theme", "--json"], output_json=False)
            self.assertEqual(status, 0)
            picker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
