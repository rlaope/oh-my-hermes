"""`inline_graphics` picks kitty pixels or half-blocks from the environment, in the order Hermes' own TUI does."""

from __future__ import annotations

import unittest

from omh.tui.terminal import INLINE_KITTY, INLINE_UNICODE, inline_graphics


class InlineGraphicsTests(unittest.TestCase):
    def test_empty_environment_is_unicode(self) -> None:
        self.assertEqual(inline_graphics({}), INLINE_UNICODE)

    def test_plain_xterm_is_unicode(self) -> None:
        self.assertEqual(inline_graphics({"TERM": "xterm-256color"}), INLINE_UNICODE)

    def test_vscode_is_unicode(self) -> None:
        self.assertEqual(inline_graphics({"TERM_PROGRAM": "vscode"}), INLINE_UNICODE)

    def test_vscode_with_inherited_kitty_window_is_unicode(self) -> None:
        self.assertEqual(inline_graphics({"TERM_PROGRAM": "vscode", "KITTY_WINDOW_ID": "1"}), INLINE_UNICODE)

    def test_dashboard_host_is_unicode(self) -> None:
        self.assertEqual(inline_graphics({"HERMES_PTY_HOST": "dashboard", "TERM": "xterm-kitty"}), INLINE_UNICODE)

    def test_tmux_is_unicode(self) -> None:
        self.assertEqual(inline_graphics({"TMUX": "/tmp/tmux-1/default,1,0"}), INLINE_UNICODE)

    def test_screen_is_unicode(self) -> None:
        self.assertEqual(inline_graphics({"STY": "1.pts-0", "TERM": "xterm-kitty"}), INLINE_UNICODE)

    def test_empty_tmux_does_not_count(self) -> None:
        self.assertEqual(inline_graphics({"TMUX": "", "KITTY_WINDOW_ID": "1"}), INLINE_KITTY)

    def test_kitty_inside_tmux_is_unicode(self) -> None:
        self.assertEqual(inline_graphics({"KITTY_WINDOW_ID": "1", "TMUX": "x"}), INLINE_UNICODE)

    def test_wezterm_program_is_unicode(self) -> None:
        self.assertEqual(inline_graphics({"TERM_PROGRAM": "WezTerm", "KITTY_WINDOW_ID": "1"}), INLINE_UNICODE)

    def test_wezterm_pane_is_unicode(self) -> None:
        self.assertEqual(inline_graphics({"WEZTERM_PANE": "3", "TERM": "xterm-kitty"}), INLINE_UNICODE)

    def test_kitty_window_id_is_kitty(self) -> None:
        self.assertEqual(inline_graphics({"KITTY_WINDOW_ID": "1"}), INLINE_KITTY)

    def test_ghostty_resources_dir_is_kitty(self) -> None:
        self.assertEqual(inline_graphics({"GHOSTTY_RESOURCES_DIR": "/Applications/Ghostty.app"}), INLINE_KITTY)

    def test_kitty_term_is_kitty(self) -> None:
        self.assertEqual(inline_graphics({"TERM": "xterm-kitty"}), INLINE_KITTY)

    def test_ghostty_term_is_kitty(self) -> None:
        self.assertEqual(inline_graphics({"TERM": "xterm-ghostty"}), INLINE_KITTY)

    def test_ghostty_program_is_kitty(self) -> None:
        self.assertEqual(inline_graphics({"TERM_PROGRAM": "Ghostty"}), INLINE_KITTY)

    def test_comparison_is_case_insensitive(self) -> None:
        self.assertEqual(inline_graphics({"TERM": "XTERM-KITTY"}), INLINE_KITTY)


if __name__ == "__main__":
    unittest.main()
