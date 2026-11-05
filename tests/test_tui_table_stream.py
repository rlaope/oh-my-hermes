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
from omh.tui.transcript import Transcript, _stable_lines

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

    # (d) Cell content: wide characters, escaped pipes, a table wider than the row (more in test_tui_table_wrap).

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

    def test_table_wider_than_the_row_wraps_its_cells_instead_of_staying_plain_text(self) -> None:
        wide = "a" * 30
        rows = self.render(f"| {wide} | {wide} |\n|---|---|\n| 1 | 2 |", width=40)
        self.assertFalse(any("|" in row for row in rows), rows)
        self.assertEqual(sum(1 for row in rows if set(row.strip()) == {"─", " "}), 1, rows)
        self.assertEqual("".join(rows).count("a"), 60)
        self.assertTrue(all(len(row) <= 40 for row in rows), rows)

    def test_pipe_lines_inside_a_code_fence_stay_code(self) -> None:
        rows = self.render("```\n| a | b |\n|---|---|\n```")
        self.assertEqual(rows[:2], ["| a | b |", "|---|---|"])

    # (e) Review follow-ups: exit, control characters, partial dividers.

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
        app.region.flush_above = lambda lines, cols, rows=None: flushed.extend(lines_text(lines))  # type: ignore[method-assign]
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


    # (g) Review round: frozen widths, app wiring, one-column policy, back-to-back tables.

    def test_late_wider_row_widens_only_its_own_row(self) -> None:
        def name(n: int) -> str:
            return f"r{n}" + "q" * (n % 4)

        self.step(ev("message.start"))
        self.transcript.apply(ev("message.delta", text="| a | b |\n| --- | --- |\n"))
        for n in range(1, 20):
            self.transcript.apply(ev("message.delta", text=f"| {name(n)} | s{n} |\n"))
            self.taken.extend(lines_text(self.transcript.take_stable_lines(WIDTH, THEME, live_rows=12)))
        self.transcript.apply(ev("message.delta", text="| late | " + "w" * 20 + " |\n"))
        self.taken.extend(lines_text(self.transcript.take_stable_lines(WIDTH, THEME, live_rows=12)))
        early = next(row for row in self.taken if f"{name(1)} " in row + " ")
        wide = next(row for row in self.taken if "late" in row)
        self.assertLess(len(early.rstrip()), len(wide.rstrip()))
        self.assertEqual(early.index("s1"), next(row for row in self.taken if name(17) in row).index("s17"))
        self.transcript.apply(ev("message.complete", text="", status="complete"))
        self.taken.extend(lines_text(self.transcript.take_stable_lines(WIDTH, THEME, live_rows=12)))
        words = [word for row in self.taken for word in row.split()]
        for cell in ["a", "b", "late", "w" * 20] + [name(n) for n in range(1, 20)] + [f"s{n}" for n in range(1, 20)]:
            self.assertEqual(words.count(cell), 1, cell)

    def test_one_column_header_stays_plain_text(self) -> None:
        self.assertEqual(self.render("| note |\n|---|"), ["| note |", "|---|"])
        self.assertEqual(self.render("| note |"), ["| note |"])

    def test_trailing_blank_lines_are_not_stable_after_the_held_run(self) -> None:
        self.assertEqual(_stable_lines("para\n\n| a | b |\nx"), ["para"])

    def test_a_second_table_with_no_blank_line_loses_no_cell(self) -> None:
        source = "| a | b |\n|---|---|\n| 1 | 2 |\n| c | d | e |\n|---|---|---|\n| x | y | z |"
        rows = self.render(source)
        text = " ".join(rows).split()
        for cell in ("a", "b", "1", "2", "c", "d", "e", "x", "y", "z"):
            self.assertEqual(sum(1 for word in text if word == cell), 1, cell)
        self.assertEqual(sum(1 for row in rows if "─" in row), 2, "each table has its own band")
        streamed = Transcript(clock=lambda: 100.0)
        streamed.apply(ev("message.start"))
        streamed.apply(ev("message.delta", text=source))
        streamed.apply(ev("message.complete", text=source, status="complete"))
        history = lines_text(streamed.history_lines(WIDTH, THEME, details=False))
        for cell in ("a", "b", "1", "2", "c", "d", "e", "x", "y", "z"):
            self.assertEqual(sum(1 for row in history for word in row.split() if word == cell), 1, cell)

    # (h) Second review round: no cell lost behind a release, no raw divider.

    def stream_released(self, source: str, live_rows: int = 8) -> list[str]:
        self.step(ev("message.start"))
        for line in source.split("\n"):
            self.transcript.apply(ev("message.delta", text=line + "\n"))
            self.taken.extend(lines_text(self.transcript.take_stable_lines(WIDTH, THEME, live_rows=live_rows)))
        self.transcript.apply(ev("message.complete", text="", status="complete"))
        self.taken.extend(lines_text(self.transcript.take_stable_lines(WIDTH, THEME, live_rows=live_rows)))
        return self.taken + lines_text(self.transcript.live_lines(WIDTH, THEME, max_rows=live_rows))

    def test_a_three_column_table_after_a_released_two_column_one_loses_no_cell(self) -> None:
        first = ["| ah1 | ah2 |", "|---|---|"] + [f"| a{i}c1 | a{i}c2 |" for i in range(10)]
        second = ["| bh0 | bh1 | bh2 |", "|---|---|---|"] + [f"| b{i}c0 | b{i}c1 | b{i}c2 |" for i in range(2)]
        rows = self.stream_released("\n".join([*first, *second]))
        words = [word for row in rows for word in row.split()]
        cells = ["ah1", "ah2", "bh0", "bh1", "bh2"]
        cells += [f"a{i}c{j}" for i in range(10) for j in (1, 2)] + [f"b{i}c{j}" for i in range(2) for j in range(3)]
        for cell in cells:
            self.assertEqual(words.count(cell), 1, cell)
        self.assertGreater(len(self.taken), 8, "the first table was never released")

    def test_a_three_column_table_after_a_short_two_column_one_loses_no_cell(self) -> None:
        source = "\n".join(
            ["| ah1 | ah2 |", "|---|---|", "| a0c1 | a0c2 |"]
            + ["| bh0 | bh1 | bh2 |", "|---|---|---|"]
            + [f"| b{i}c0 | b{i}c1 | b{i}c2 |" for i in range(10)]
        )
        words = [word for row in self.stream_released(source) for word in row.split()]
        for cell in ["ah1", "ah2", "a0c1", "a0c2", "bh0", "bh1", "bh2"] + [f"b{i}c{j}" for i in range(10) for j in range(3)]:
            self.assertEqual(words.count(cell), 1, cell)

    def test_malformed_dividers_are_never_drawn_raw(self) -> None:
        cases = {
            "wider divider in a two-column body": "| a | b |\n|---|---|\n| 1 | 2 |\n|---|---|---|\n| 3 | 4 |",
            "second divider right after the first": "| a | b |\n|---|---|\n|---|---|\n| 1 | 2 |",
        }
        for label, source in cases.items():
            with self.subTest(label):
                shown = self.render(source)
                streamed = Transcript(clock=lambda: 100.0)
                streamed.apply(ev("message.start"))
                streamed.apply(ev("message.delta", text=source))
                streamed.apply(ev("message.complete", text=source, status="complete"))
                history = lines_text(streamed.history_lines(WIDTH, THEME, details=False))
                for row in shown + history:
                    self.assertNotIn("|---", row)
                for cell in ("1", "2"):
                    self.assertEqual(sum(1 for row in history for word in row.split() if word == cell), 1, cell)

    # (i) Third review round: the same document must keep every cell however it streams.

    def tokens(self, rows: list[str]) -> list[str]:
        return [word for row in rows for word in row.split()]

    def test_a_table_cut_by_a_release_before_the_next_divider_loses_no_cell(self) -> None:
        source = "\n".join([
            "| ah1 | ah2 |", "|---|---|", "| a0c1 | a0c2 |", "| a1c1 | a1c2 |",
            "| bh0 | bh1 | bh2 |", "|---|---|---|", "| b0c0 | b0c1 | b0c2 |", "| b1c0 | b1c1 | b1c2 |",
        ])
        words = self.tokens(self.stream_released(source))
        for cell in ["ah1", "ah2", "a0c1", "a0c2", "a1c1", "a1c2", "bh0", "bh1", "bh2", "b0c2", "b1c2"]:
            self.assertEqual(words.count(cell), 1, cell)

    def test_a_continued_row_with_escapes_and_tabs_stays_on_the_frozen_columns(self) -> None:
        head = ["| hh1 | hh2 |", "|---|---|"] + [f"| r{i}q | s{i}q |" for i in range(8)]
        rows = self.stream_released("\n".join([*head, "| \x1b[31mcc\x1b[0m | x\tz |", "| dd | ee |"]))
        cc = next(row for row in rows if "cc" in row)
        dd = next(row for row in rows if "dd" in row)
        self.assertEqual(cc.index("cc"), dd.index("dd"))
        self.assertEqual(cc.index("x"), dd.index("ee"))

    def test_streaming_never_loses_a_cell_or_draws_a_raw_divider(self) -> None:
        import random
        import re

        rng = random.Random(2551)
        counter = 0

        def token() -> str:
            nonlocal counter
            counter += 1
            return f"k{counter}z"

        def document() -> tuple[str, list[str]]:
            lines: list[str] = []
            cells: list[str] = []
            for _ in range(rng.randint(1, 3)):
                kind = rng.choice(["table", "table", "table", "prose", "fence"])
                if kind == "prose":
                    word = token()
                    cells.append(word)
                    lines.append(f"prose {word} here")
                elif kind == "fence":
                    a, b = token(), token()
                    cells += [a, b]
                    lines += ["```", f"| {a} | {b} |", "```"]
                else:
                    cols = rng.randint(2, 4)
                    header = [token() for _ in range(cols)]
                    cells += header
                    lines.append("| " + " | ".join(header) + " |")
                    lines.append("|" + "---|" * cols)
                    for _ in range(rng.randint(0, 9)):
                        row = [token() for _ in range(rng.choice([cols, cols, cols + 1, max(2, cols - 1)]))]
                        cells += row
                        lines.append("| " + " | ".join(row) + " |")
                if rng.random() < 0.5:
                    lines.append("")
            return "\n".join(lines) + "\n", cells

        for case in range(60):
            text, cells = document()
            history_view = Transcript(clock=lambda: 100.0)
            history_view.apply(ev("message.start"))
            history_view.apply(ev("message.delta", text=text))
            history_view.apply(ev("message.complete", text=text, status="complete"))
            history = lines_text(history_view.history_lines(80, THEME, details=False))
            for live_rows in (None, 6, 8):
                for chunked in (False, True):
                    for ending in ("complete", "final"):
                        transcript = Transcript(clock=lambda: 100.0)
                        transcript.apply(ev("message.start"))
                        pieces = []
                        position = 0
                        while position < len(text):
                            size = rng.randint(1, 25) if chunked else len(text.split("\n")[0]) + 1
                            end = text.index("\n", position) + 1 if not chunked else position + size
                            pieces.append(text[position:end])
                            position = end
                        taken: list[str] = []
                        for piece in pieces:
                            transcript.apply(ev("message.delta", text=piece))
                            taken += lines_text(transcript.take_stable_lines(80, THEME, live_rows=live_rows))
                        if ending == "complete":
                            transcript.apply(ev("message.complete", text=text, status="complete"))
                            taken += lines_text(transcript.take_stable_lines(80, THEME, live_rows=live_rows))
                            taken += lines_text(transcript.live_lines(80, THEME))
                        else:
                            taken += lines_text(transcript.take_stable_lines(80, THEME, final=True, live_rows=live_rows))
                        label = (case, live_rows, chunked, ending)
                        for where, rows in (("taken", taken), ("history", history)):
                            words = self.tokens(rows)
                            for cell in cells:
                                self.assertEqual(words.count(cell), 1, (label, where, cell, text))
                            for row in rows:
                                if "```" not in text or not re.search(r"\|\s*:?-{3,}", row):
                                    self.assertIsNone(re.search(r"\|\s*:?-{3,}", row), (label, where, row, text))

if __name__ == "__main__":
    unittest.main()
