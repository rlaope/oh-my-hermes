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
from test_tui_modes import make_app
from omh.tui.gateway import Event
from omh.tui.markdown import MarkdownState, opens_table, render_lines
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


    # (e) Review follow-ups: exit, control characters, partial dividers, plain fallback.

    def test_exit_take_releases_held_table_rows(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("message.delta", text="| X | Y |\n| --- | --- |\n| 1 | a |\n| 2 | b |"))
        self.assertEqual(lines_text(self.transcript.take_stable_lines(WIDTH, THEME)), [])
        final = lines_text(self.transcript.take_stable_lines(WIDTH, THEME, final=True))
        joined = "\n".join(final)
        self.assertIn("X", joined)
        self.assertIn("1  ", joined)
        self.assertNotIn("| --- |", joined)

    def test_quitting_mid_reply_flushes_the_held_table_rows(self) -> None:
        app, _client = make_app(busy=True)
        flushed: list[str] = []
        app.region.flush_above = lambda lines, cols: flushed.extend(lines_text(lines))  # type: ignore[method-assign]
        app.transcript.apply(ev("message.start"))
        app.transcript.apply(ev("message.delta", text="| X | Y |\n| --- | --- |\n| 1 | a |\n| 2 | b |"))
        app._shutdown()
        self.assertTrue(any("X" in row for row in flushed), flushed)
        self.assertTrue(any("1" in row and "a" in row for row in flushed), flushed)

    def test_control_characters_do_not_shift_columns(self) -> None:
        rows = self.render("| \x1b[1ma\x1b[0m | b |\n|---|---|\n| \x1b[31mred\x1b[0m | x |\n| t\tz | y |")
        self.assertTrue(rows[2].startswith("red"))
        self.assertEqual(rows[2].index("x"), rows[0].index("b"))
        self.assertEqual(rows[3].index("y"), rows[0].index("b"))

    def test_divider_with_escape_sequences_still_opens_the_table(self) -> None:
        self.assertTrue(opens_table("| a | b |", "|\x1b[2m---\x1b[0m|---|"))

    def test_divider_needs_as_many_cells_as_the_header(self) -> None:
        for divider in ("| ---", "| --- | -", "|---|---|---|"):
            self.assertEqual(self.render(f"| a | b |\n{divider}")[0], "| a | b |", divider)
        self.assertNotEqual(self.render("| a | b |\n| --- | ---")[0], "| a | b |")

    def test_partial_divider_never_flips_back_to_a_table_then_raw(self) -> None:
        shown = []
        for tail in ("| -", "| --- | -", "| --- | ---", "| --- | --- |"):
            self.transcript = Transcript(clock=lambda: 100.0)
            self.step(ev("message.start"))
            self.step(ev("message.delta", text=f"| X | Y |\n{tail}"))
            shown.append(any("─" in row for row in self.live()))
        self.assertEqual(shown, sorted(shown))

    def test_indented_overwide_table_stays_plain_text(self) -> None:
        cell = "a" * 17
        source = f"  | {cell} | {cell} |\n  |---|---|\n  | 1 | 2 |"
        rows = self.render(source, width=37)  # the columns fit (36) but not behind the indent
        self.assertFalse(any("─" in row for row in rows))

    def test_overwide_table_rows_equal_the_plain_text_render(self) -> None:
        wide = "a" * 30
        lines = [f"| {wide} | **b** |", "|---|---|", "| 1 | 2 |"]
        plain = []
        for line in lines:
            rows, _state = render_lines([line], MarkdownState(), 30, THEME)
            plain.extend(rows)
        rows, _state = render_lines(lines, MarkdownState(), 30, THEME)
        self.assertEqual(rows, plain)


    # (f) A table taller than the live region is released as it grows.

    def test_tall_table_is_released_to_scrollback_while_streaming(self) -> None:
        rows_high = 24
        self.step(ev("message.start"))
        self.step(ev("message.delta", text="| N | Value |\n| --- | --- |\n"))
        taken_mid_stream = 0
        for n in range(1, 201):
            cell = "w" * 40 if n == 150 else f"v{n}"
            self.transcript.apply(ev("message.delta", text=f"| {n} | {cell} |\n"))
            self.taken.extend(lines_text(self.transcript.take_stable_lines(WIDTH, THEME, live_rows=rows_high)))
            live = lines_text(self.transcript.live_lines(WIDTH, THEME, max_rows=rows_high))
            self.assertLessEqual(len(live), rows_high // 2 + 4, f"the held run was not bounded at row {n}")
            if n == 100:
                taken_mid_stream = len(self.taken)
        self.assertGreater(taken_mid_stream, 90)
        self.transcript.apply(ev("message.delta", text="| 201 | par"))
        partial = lines_text(self.transcript.live_lines(WIDTH, THEME, max_rows=rows_high))
        self.assertFalse(any("| " in row for row in partial), "the streaming row drew raw")
        self.transcript.apply(ev("message.complete", text="", status="complete"))
        self.taken.extend(lines_text(self.transcript.take_stable_lines(WIDTH, THEME, live_rows=rows_high)))
        everything = self.taken + lines_text(self.transcript.live_lines(WIDTH, THEME, max_rows=rows_high))
        header = [i for i, row in enumerate(everything) if "Value" in row]
        self.assertEqual(len(header), 1, "the header is in scrollback once")
        self.assertEqual(header[0], min(i for i, row in enumerate(everything) if "N " in row or "Value" in row))
        for n in range(1, 201):
            if n != 150:
                self.assertEqual(sum(1 for row in everything if f"v{n} " in row + " "), 1, n)
        self.assertEqual(sum(1 for row in everything if "w" * 40 in row), 1)
        self.assertFalse(any("| " in row for row in self.taken), "a row reached scrollback raw")


if __name__ == "__main__":
    unittest.main()
