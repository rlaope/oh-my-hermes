"""The docs say what the inline image preview sends, writes and draws, and the code does it."""

from __future__ import annotations

from pathlib import Path
import unittest

from omh.tui import app, gateway_contract as contract, inline_image
from omh.tui.terminal import INLINE_KITTY, INLINE_UNICODE, inline_graphics

ROOT = Path(__file__).resolve().parents[1]


def prose(name: str) -> str:
    return " ".join((ROOT / name).read_text(encoding="utf-8").split())


class BoundaryDocTests(unittest.TestCase):
    def test_the_render_call_is_named_with_what_it_sends(self) -> None:
        boundary = prose("docs/OMH-TUI-BOUNDARY.md")
        self.assertIn(
            "When the person attaches an image, it also sends `image.render` once for that image, "
            "naming only the path Hermes staged and answered, to draw a preview under the prompt that sends it",
            boundary,
        )
        self.assertIn("It reads nothing else for the preview and sends nothing on its own.", boundary)
        self.assertIn("image.render", contract.OPTIONAL_METHODS)
        self.assertIn("image.render", app.QUIET_EXPIRY_METHODS)

    def test_the_request_bounds_and_forms_match_the_code(self) -> None:
        boundary = prose("docs/OMH-TUI-BOUNDARY.md")
        self.assertIn(
            "it asks for at most 64 columns by 16 rows, for kitty graphics only on a kitty-family terminal "
            "at truecolor and otherwise for half-blocks, and not at all under `NO_COLOR`",
            boundary,
        )
        self.assertEqual((inline_image.PREVIEW_MAX_COLS, inline_image.PREVIEW_MAX_ROWS), (64, 16))
        self.assertEqual(inline_graphics({"KITTY_WINDOW_ID": "1"}), INLINE_KITTY)
        self.assertEqual(inline_graphics({"KITTY_WINDOW_ID": "1", "TMUX": "x"}), INLINE_UNICODE)
        self.assertEqual(inline_graphics({}), INLINE_UNICODE)

    def test_the_preview_follows_hermes_setting_and_fails_quietly(self) -> None:
        boundary = prose("docs/OMH-TUI-BOUNDARY.md")
        self.assertIn(
            "The preview follows Hermes' `display.inline_images` (off draws none), and a Hermes that does "
            "not know the call, or an answer that does not check out, draws no preview and says nothing.",
            boundary,
        )
        self.assertIsNone(inline_image.preview_from({"mode": "off"}))
        self.assertIsNone(inline_image.preview_from({"mode": "kitty", "cols": 2, "rows": 1}))

    def test_the_one_escape_it_writes_is_the_checked_transmit(self) -> None:
        boundary = prose("docs/OMH-TUI-BOUNDARY.md")
        self.assertIn(
            "Every escape sequence in text is still removed before it reaches the terminal "
            "(`screen.paint_line`). The one sequence the TUI writes from Hermes is the kitty graphics "
            "transmit of an image the person attached, and only after it matches the kitty APC chunk form "
            "for the image Hermes named (`src/tui/inline_image.py`)",
            boundary,
        )
        self.assertIn(
            "it is written once per image, to the terminal only and never to disk or a log, and only the "
            "placeholder rows are kept for the transcript. A half-block preview is ordinary coloured cells.",
            boundary,
        )
        self.assertEqual(app.PREVIEW_KEEP, 32)

    def test_graphics_is_asked_only_with_a_kitty_ask(self) -> None:
        boundary = prose("docs/OMH-TUI-BOUNDARY.md")
        self.assertIn(
            "It sends `graphics` true only with a kitty ask, so Hermes answers half-blocks to a half-block ask even "
            "when its config pins kitty, and a kitty answer to a half-block ask is dropped.",
            boundary,
        )

    def test_the_echo_waits_at_most_two_seconds(self) -> None:
        boundary = prose("docs/OMH-TUI-BOUNDARY.md")
        self.assertIn(
            "The echo of a prompt sent with an image stays in the live region until its previews answer, at most "
            "2 seconds, and is then printed with what it has.",
            boundary,
        )
        self.assertEqual(app.PREVIEW_WAIT_SECONDS, 2.0)

    def test_no_transmit_on_the_alternate_screen_and_the_cap(self) -> None:
        boundary = prose("docs/OMH-TUI-BOUNDARY.md")
        self.assertIn(
            "A transmit over 4 MiB is refused unread. No transmit is written while the pager or a picker holds the "
            "alternate screen, whose image store is not the main screen's: it is written once the main screen is "
            "back, and the pager shows a kitty preview as its caption only.",
            boundary,
        )
        self.assertEqual(inline_image.TRANSMIT_MAX_CHARS, 4 * 1024 * 1024)


class InstallationDocTests(unittest.TestCase):
    def test_the_user_sees_a_preview_and_can_turn_it_off(self) -> None:
        installation = prose("docs/INSTALLATION.md")
        self.assertIn(
            "with a small preview under each: real pixels on kitty, Ghostty and Otty at truecolor, coloured half-blocks "
            "elsewhere (tmux, Terminal.app, iTerm2, WezTerm, VS Code), even where Hermes' config names kitty, none "
            "under `NO_COLOR`; `display.inline_images: off` in Hermes' config turns it off.",
            installation,
        )
        self.assertIn(
            "The prompt waits up to 2 seconds for its previews before it is printed, and prints with only the image "
            "names when they do not come in time. `/history` shows a kitty preview as its name only.",
            installation,
        )
        self.assertEqual(inline_graphics({"GHOSTTY_RESOURCES_DIR": "/g"}), INLINE_KITTY)
        self.assertEqual(inline_graphics({"TERM_PROGRAM": "otty", "TERM": "xterm-256color"}), INLINE_KITTY)
        for environ in ({"TERM_PROGRAM": "WezTerm"}, {"TERM_PROGRAM": "vscode"}, {"TERM_PROGRAM": "Apple_Terminal"},
                        {"TERM_PROGRAM": "iTerm.app"}):
            self.assertEqual(inline_graphics(environ), INLINE_UNICODE, environ)


if __name__ == "__main__":
    unittest.main()
