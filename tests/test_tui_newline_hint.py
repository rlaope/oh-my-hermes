"""Where Shift+Enter sends, the info line names the keys that add a line while the draft spans lines (walk G7).

A terminal that has sent no CSI u or modifyOtherKeys report gives Shift+Enter
as Enter, which sends the draft. `\\` then Enter, Alt+Enter and Ctrl+J still
add a line there; the `?` list says so, and the info line says it where a
person composing more than one line looks: under the draft, while it spans
lines (typed, or a paste), idle and in normal mode.
"""

from __future__ import annotations

import re
import unittest

from _tui_lines import without_badge
from test_tui_modes import make_app, type_text
from omh.tui.app import NEWLINE_KEYS
from omh.tui.keys import CHAR, ENTER, Key, Paste


def mode_row(app) -> str:
    """The info line's left side: its right one stands 3 cells or more away."""
    return re.split(r" {3,}", without_badge("".join(span.text for span in app._info_line(100))).strip())[0]


def two_lines(app) -> None:
    type_text(app, "first")
    app._on_input(Key(CHAR, "j", ctrl=True))
    type_text(app, "second")


class NewlineHintTests(unittest.TestCase):
    def test_a_draft_of_two_lines_names_the_newline_keys(self) -> None:
        app, _client = make_app()
        two_lines(app)
        self.assertEqual(mode_row(app), NEWLINE_KEYS[0])

    def test_a_multi_line_paste_names_them_too(self) -> None:
        for pasted in ("one\ntwo", "\n".join(f"line {n}" for n in range(9))):  # typed in place, or held in a chip
            with self.subTest(lines=pasted.count("\n") + 1):
                app, _client = make_app()
                app._on_input(Paste(pasted))
                self.assertEqual(mode_row(app), NEWLINE_KEYS[0])

    def test_one_line_names_no_newline_keys(self) -> None:
        app, _client = make_app()
        type_text(app, "one line")
        row = "".join(span.text for span in app._info_line(100))
        self.assertNotIn(NEWLINE_KEYS[-1], row)
        self.assertNotIn("shortcuts", row)  # `?` types itself into a draft

    def test_a_terminal_that_reported_keys_names_no_newline_keys(self) -> None:
        app, _client = make_app()
        app.decoder.protocol_reported = True  # Shift+Enter is a key of its own there
        two_lines(app)
        self.assertNotIn(NEWLINE_KEYS[-1], "".join(span.text for span in app._info_line(100)))

    def test_a_turn_running_or_another_mode_keeps_its_own_hint(self) -> None:
        app, _client = make_app(busy=True)
        type_text(app, "first")
        app._on_input(Key(ENTER, alt=True))  # Ctrl+J steers while a turn runs
        type_text(app, "second")
        self.assertNotIn(NEWLINE_KEYS[0], mode_row(app))
        app, _client = make_app()
        app.plan_mode = True
        two_lines(app)
        self.assertNotIn(NEWLINE_KEYS[0], mode_row(app))

    def test_a_narrow_row_keeps_the_point(self) -> None:
        app, _client = make_app()
        two_lines(app)
        row = re.split(r" {3,}", "".join(span.text for span in app._info_line(20)).strip())[0]
        self.assertEqual(row, NEWLINE_KEYS[-1])

    def test_vim_insert_suppresses_newline_keys_hint(self) -> None:
        app, _client = make_app()
        app.composer.set_vim(True)
        two_lines(app)
        self.assertEqual(mode_row(app), "INSERT")
        self.assertNotIn(NEWLINE_KEYS[-1], "".join(span.text for span in app._info_line(100)))

    def test_vim_normal_retains_newline_keys_hint(self) -> None:
        app, _client = make_app()
        app.composer.set_vim(True)
        two_lines(app)
        app._on_input(Key("escape"))
        self.assertEqual(mode_row(app), f"NORMAL · {NEWLINE_KEYS[0]}")


if __name__ == "__main__":
    unittest.main()
