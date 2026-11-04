"""Regression tests: a `|` table streamed delta-by-delta through the app loop.

Each step runs in app-loop order (`apply` -> `take_stable_lines` ->
`live_lines`) and checks `taken + live == history` at every frame: no row
is taken twice, none goes missing, and no raw `| --- |` row reaches
scrollback before the table is decidable.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _tui_lines import lines_text
from omh.tui.gateway import Event
from omh.tui.markdown import MarkdownState, render_lines
from omh.tui.theme import DEFAULT_THEME as THEME
from omh.tui.transcript import Transcript

SID = "b6af062a"
WIDTH = 60

TABLE_DELTAS = ["| X | Y |\n", "| --- | --- |\n", "| 1 | a |\n", "| 2 | b |"]
TABLE_TEXT = "| X | Y |\n| --- | --- |\n| 1 | a |\n| 2 | b |"

# Raw source rows that must never reach scrollback once the table is decidable.
RAW_ROWS = ("| X | Y |", "| --- | --- |", "| 1 | a |", "| 2 | b |")


def ev(event_type: str, /, **payload: object) -> Event:
    return Event(type=event_type, session_id=SID, payload=dict(payload))


class TableStreamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transcript = Transcript(clock=lambda: 100.0)
        self.taken: list[str] = []

    def step(self, event: Event) -> list[str]:
        """One frame of the app loop; returns what this frame flushed."""
        self.transcript.apply(event)
        fresh = lines_text(self.transcript.take_stable_lines(WIDTH, THEME))
        self.assertEqual(
            lines_text(self.transcript.take_stable_lines(WIDTH, THEME)), [],
            "a line was offered twice",
        )
        self.taken.extend(fresh)
        live = lines_text(self.transcript.live_lines(WIDTH, THEME))
        self.assertEqual(
            self.taken + live,
            lines_text(self.transcript.history_lines(WIDTH, THEME, details=False)),
        )
        return fresh

    def live(self) -> list[str]:
        return lines_text(self.transcript.live_lines(WIDTH, THEME))

    def assert_no_raw_rows_taken(self) -> None:
        for row in self.taken:
            for raw in RAW_ROWS:
                self.assertNotIn(raw, row)

    # (a) Detection and pretty render during delta streaming.

    def test_table_header_is_held_back_until_the_divider_arrives(self) -> None:
        self.step(ev("message.start"))
        flushed = self.step(ev("message.delta", text="| X | Y |\n"))
        self.assertEqual(flushed, [], "the header escaped into scrollback before it was decidable")
        self.assertEqual(self.live(), ["┃ ⚚ Hermes", "┃   | X | Y |"])
        self.assert_no_raw_rows_taken()

    def test_table_renders_pretty_in_the_live_region_during_streaming(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("message.delta", text="| X | Y |\n"))
        self.step(ev("message.delta", text="| --- | --- |\n"))
        live = self.live()
        # Decided the frame the divider lands: aligned header + separator band.
        self.assertIn("┃   X    Y  ", live)
        self.assertTrue(any("───" in row for row in live), f"no separator band in {live!r}")
        self.assertFalse(any("| ---" in row for row in live), f"raw divider in {live!r}")
        self.step(ev("message.delta", text="| 1 | a |\n"))
        self.assertIn("┃   1    a  ", self.live())
        self.step(ev("message.delta", text="| 2 | b |"))
        self.assertIn("┃   2    b  ", self.live())
        # Nothing table-shaped was flushed early: the whole table is still live
        # (and pretty, matching history at every frame via step's invariant).
        self.assertEqual(self.taken, [])
        self.assert_no_raw_rows_taken()

    # (b) Rendering after message.complete.

    def test_table_renders_after_message_complete(self) -> None:
        self.step(ev("message.start"))
        for delta in TABLE_DELTAS:
            self.step(ev("message.delta", text=delta))
        flushed = self.step(ev("message.complete", text=TABLE_TEXT, status="complete"))
        self.assertTrue(self.transcript.blocks[-1].done)
        self.assertEqual(self.live(), [])
        self.assertIn("┃   X    Y  ", flushed)
        self.assertIn("┃   1    a  ", flushed)
        self.assertIn("┃   2    b  ", flushed)
        self.assertTrue(any("───" in row for row in flushed), f"no separator band in {flushed!r}")
        self.assert_no_raw_rows_taken()

    def test_table_renders_after_message_complete_without_any_delta(self) -> None:
        self.step(ev("message.start"))
        flushed = self.step(ev("message.complete", text=TABLE_TEXT, status="complete"))
        self.assertTrue(self.transcript.blocks[-1].done)
        self.assertIn("┃   X    Y  ", flushed)
        self.assertTrue(any("───" in row for row in flushed), f"no separator band in {flushed!r}")
        self.assert_no_raw_rows_taken()

    # (c) Non-table text is unchanged by the hold-back.

    def test_non_table_text_is_unchanged(self) -> None:
        self.step(ev("message.start"))
        self.assertEqual(self.step(ev("message.delta", text="hello ")), [])
        self.assertEqual(self.live(), ["┃ ⚚ Hermes", "┃   hello "])
        # A settled plain line still flushes immediately, exactly as before.
        self.assertEqual(
            self.step(ev("message.delta", text="world\n")),
            ["┃ ⚚ Hermes", "┃   hello world"],
        )
        self.assertEqual(self.step(ev("message.delta", text="\nsecond line")), [])
        self.assertEqual(self.live(), ["┃", "┃   second line"])
        flushed = self.step(ev("message.complete", text="hello world\n\nsecond line", status="complete"))
        self.assertEqual(flushed, ["┃", "┃   second line"])
        self.assertEqual(
            self.taken,
            ["┃ ⚚ Hermes", "┃   hello world", "┃", "┃   second line"],
        )
        self.assertFalse(any("─" in row for row in self.taken), "plain text gained a separator band")

    # (d) Cell content: wide characters, escaped pipes, a table wider than the row.

    def render(self, source: str, width: int = WIDTH) -> list[str]:
        rows, _state = render_lines(source.split("\n"), MarkdownState(), width, THEME)
        return lines_text(rows)

    def test_wide_characters_align_by_cell_width(self) -> None:
        rows = self.render("| 名前 | b |\n|---|---|\n| 日本語 | x |\n| ab | y |")
        self.assertTrue(rows[2].startswith("日本語  x"))
        self.assertTrue(rows[3].startswith("ab      y"))

    def test_escaped_pipe_stays_inside_its_cell(self) -> None:
        rows = self.render("| a | b |\n|---|---|\n| x \\| y | z |")
        self.assertIn("x | y", rows[2])
        self.assertIn("z", rows[2])

    def test_table_wider_than_the_row_stays_plain_text(self) -> None:
        wide = "a" * 30
        rows = self.render(f"| {wide} | {wide} |\n|---|---|\n| 1 | 2 |", width=40)
        self.assertEqual("".join(rows).replace(" ", "").count("|---|---|"), 1)
        self.assertFalse(any(set(row.strip()) == {"─", " "} for row in rows))

    def test_pipe_lines_inside_a_code_fence_stay_code(self) -> None:
        rows = self.render("```\n| a | b |\n|---|---|\n```")
        self.assertEqual(rows[:2], ["| a | b |", "|---|---|"])


if __name__ == "__main__":
    unittest.main()
