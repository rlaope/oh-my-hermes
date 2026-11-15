"""An assistant reply hangs on no rail (owner, 2026-11-15).

A prompt (`┃ ❯`) and a tool call (`┃ ● …`) keep their rails; a reply reads
apart from them without one: its `⚚ Hermes · <model>` header starts at the
left edge, bold in the skin's accent with the model muted, its text sits at the
reply's two-cell indent, a blank row inside it is an empty line, and its text
gets the two cells the rail took. A drag still copies the text without that
indent.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest import mock

from _tui_lines import line_text
from test_tui_clean_copy import BAR_GLYPHS, KITTY, REPLY as PAGER_REPLY, osc52, row_of
from test_tui_clean_copy import reply_app as pager_app
from test_tui_main_mouse import drag
from test_tui_wrap_copy import copied, reply_app
from omh.tui import transcript as transcript_module
from omh.tui.gateway import Event
from omh.tui.style import Span
from omh.tui.theme import DEFAULT_THEME, without_colour
from omh.tui.transcript import (
    ASSISTANT_INDENT,
    GUTTER,
    TOOL_OK,
    AssistantBlock,
    CommandBlock,
    ToolGroup,
    ToolRow,
    Transcript,
    UserBlock,
    _reply_width,
    block_rows,
    rail_cell,
)
from omh.tui.width import line_width

REPLY = "**hello** there\n\n```sh\nls\n```\n\nlast words"
THEMES = (("colour", DEFAULT_THEME), ("NO_COLOR", without_colour(DEFAULT_THEME)))


def bars(rows: list) -> list[str]:
    """Every span of `rows` that draws a bar a rail could be."""
    return [span.text for row in rows for span in row if set(span.text) & BAR_GLYPHS]


class ReplyLookTests(unittest.TestCase):
    def test_a_reply_draws_no_rail_and_its_header_starts_at_the_left_edge(self) -> None:
        for name, theme in THEMES:
            with self.subTest(theme=name):
                rows = block_rows(AssistantBlock(REPLY, done=True, model="deepseek/deepseek-v4.1-flash"), 60, theme)
                self.assertEqual(bars(rows), [], [line_text(row) for row in rows])
                self.assertEqual(line_text(rows[0]), "⚚ Hermes · deepseek-v4.1-flash")
                self.assertEqual(rows[0][0], Span("⚚ Hermes", replace(theme.brand, bold=True)))
                self.assertEqual(rows[0][1].style, theme.muted)
                for row in rows[1:]:
                    if row:
                        self.assertEqual(row[0], Span(ASSISTANT_INDENT, GUTTER), line_text(row))
                self.assertEqual([line_text(row) for row in rows[1:]],
                                 ["  hello there", "", "  sh", "  ls", "", "  last words"])

    def test_a_blank_row_inside_a_reply_is_an_empty_line_as_drawn_and_as_streamed(self) -> None:
        rows = block_rows(AssistantBlock("one\n\ntwo", done=True), 40, DEFAULT_THEME)
        self.assertEqual(rows[2], ())
        transcript = Transcript(clock=lambda: 100.0)
        transcript.apply(Event("message.start", "s", {}))
        transcript.apply(Event("message.delta", "s", {"text": "one\n\ntwo"}))
        transcript.apply(Event("message.complete", "s", {"text": "one\n\ntwo", "status": "complete"}))
        taken = transcript.take_stable_lines(40, DEFAULT_THEME)
        self.assertEqual([line_text(row) for row in taken], ["⚚ Hermes", "  one", "", "  two"])
        self.assertEqual(taken[2], ())

    def test_without_the_header_the_mark_opens_the_first_row_at_the_left_edge(self) -> None:
        with mock.patch.object(transcript_module, "ASSISTANT_HEADER", False):
            rows = block_rows(AssistantBlock("ok\nmore", done=True), 40, DEFAULT_THEME)
        self.assertEqual([line_text(row) for row in rows], ["⚚ ok", "  more"])
        self.assertEqual(bars(rows), [])

    def test_prompts_commands_and_tool_calls_keep_their_rails(self) -> None:
        call = ToolGroup([ToolRow("a", "terminal", "ls", TOOL_OK)], done=True)
        for name, theme in THEMES:
            with self.subTest(theme=name):
                prompt_bar = "│" if name == "NO_COLOR" else "┃"
                for block, bar, mark in ((UserBlock("hi"), prompt_bar, "❯"),
                                         (CommandBlock("/model", done=True), prompt_bar, "❯"),
                                         (call, "┃", "●")):
                    first = block_rows(block, 40, theme)[0]
                    self.assertEqual(line_text(first)[:4], f"{bar} {mark} ", type(block).__name__)
                    self.assertTrue(first[0].style.gutter)
                tool_row = block_rows(call, 40, theme)[0]
                self.assertEqual(tool_row[0], rail_cell(theme.accent))

    def test_a_replys_text_takes_the_width_but_its_two_cell_margin(self) -> None:
        self.assertEqual(_reply_width(60), 58)
        self.assertEqual(_reply_width(1), 1)
        rows = block_rows(AssistantBlock("a" * 28, done=True), 30, DEFAULT_THEME)
        self.assertEqual([line_text(row) for row in rows[1:]], ["  " + "a" * 28])  # one row, the whole width
        self.assertEqual(line_width(rows[1]), 30)
        rows = block_rows(AssistantBlock("a" * 28 + " b", done=True), 30, DEFAULT_THEME)
        self.assertEqual([line_text(row) for row in rows[1:]], ["  " + "a" * 28, "  b"])


class ReplyCopyTests(unittest.TestCase):
    def test_a_selection_over_a_replys_rows_leaves_the_margin_out(self) -> None:
        rows = block_rows(AssistantBlock("first line\n\nsecond line", done=True), 40, DEFAULT_THEME)
        self.assertEqual(copied(rows[1:]), "first line\n\nsecond line")

    def test_a_drag_on_the_main_screen_from_the_left_edge_copies_the_text_without_the_margin(self) -> None:
        app = reply_app("first line of the reply\nsecond line")
        screen = app.terminal.screen  # type: ignore[attr-defined]
        first, second = row_of(app, "first line"), row_of(app, "second line")
        self.assertEqual(screen.line(first - 1)[:4], "  fi")  # no rail on the screen either
        self.assertTrue(screen.line(first - 2).startswith("⚚ Hermes"), screen.line(first - 2))
        drag(app, (1, first), (app.size[0], second))
        self.assertEqual(osc52(app)[-1], "first line of the reply\nsecond line")

    def test_a_drag_in_the_pager_copies_the_text_without_the_margin(self) -> None:
        app, _copied = pager_app(KITTY)
        first, second = row_of(app, "first line"), row_of(app, "second line")
        self.assertEqual(app.terminal.screen.line(first - 1)[:4], "  fi")  # type: ignore[attr-defined]
        drag(app, (1, first), (60, second))
        self.assertEqual(osc52(app), [PAGER_REPLY])


if __name__ == "__main__":
    unittest.main()
