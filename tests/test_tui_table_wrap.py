"""A Markdown table drawn as a box, its cells wrapped inside their columns when it is wider than the row.

The owner's report of 2026-11-05: a reply whose three-column table had long
sentences in its last column showed the raw source (`| 고칠 것 | 담당 | 내용 |`,
`|---|---|---|`, rows wrapped as plain text), because #2551 kept a table wider
than the row as the plain text it was. Now every table is a box (the owner's
"클로드코드처럼 해": `┌─┬─┐` borders, a `├─┼─┤` line under the header and
under each body row), its columns narrow when it is wider than the row and
each cell wraps inside its own; a table too narrow for any column layout
draws each body row as a record (`header: value`). Streaming, the release of
a tall table on frozen columns, and `/history` keep every word exactly once.
"""

from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _tui_lines import lines_text
from omh.tui.gateway import Event
from omh.tui.app import _copied_part
from omh.tui.markdown import MarkdownState, TableColumns, fit_columns, render_lines, render_markdown
from omh.tui.style import Line
from omh.tui.theme import DEFAULT_THEME as THEME, without_colour
from omh.tui.transcript import Transcript, _stable_lines
from omh.tui.width import cell_width, cluster_width, clusters, line_width

SID = "c0ffee11"

OWNER_ROWS = [
    ("출처 섹션 누락", "`reply_lint`",
     "답변 끝에 `## Sources` 섹션이 없으면 lint가 경고만 하고 넘어갑니다. A Hermes reply that cites web results must"
     " end with a `## Sources` heading listing every URL it used, so the check should block the turn instead of"
     " passing it with a warning."),
    ("표 렌더링", "`src/tui/markdown.py`",
     "터미널보다 넓은 표가 raw markdown(`\\| a \\| b \\|`)으로 보입니다. Wrap each cell inside its column the way"
     " Claude Code does, keep the header bold, and never fall back to pipes unless the terminal is too narrow for"
     " any layout at all."),
    ("라우팅 오탐", "`routing/chat.py`",
     "\"표로 정리해줘\" 같은 일상 요청이 `long-document-reading`으로 잘못 라우팅됩니다. Add a negative case to"
     " `ROUTING_PRECISION_CASES` and hold the generic token in `_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS` before shipping"
     " the phrase trigger."),
    ("메모리 회상", "memory provider",
     "회상 라인이 messenger에서 두 번 찍힙니다. The recall status line should print once per turn on every surface;"
     " dedupe on the lifecycle status Hermes already emits rather than adding a second marker."),
]
OWNER_HEADER = ("고칠 것", "담당", "내용")
OWNER_TABLE = "\n".join(
    ["| " + " | ".join(OWNER_HEADER) + " |", "|---|---|---|"] + ["| " + " | ".join(row) + " |" for row in OWNER_ROWS]
)


def shown(cell: str) -> str:
    """A cell as it shows: code spans without their backticks, an escaped pipe as a pipe."""
    return cell.replace("\\|", "|").replace("`", "")


def ev(event_type: str, /, **payload: object) -> Event:
    return Event(type=event_type, session_id=SID, payload=dict(payload))


def cells_slice(row: str, start: int, end: int | None = None) -> str:
    """The text of `row` between cell columns `start` and `end` (display cells, wide characters counted as two)."""
    out, at = [], 0
    for cluster in clusters(row):
        if at >= start and (end is None or at + cluster_width(cluster) <= end):
            out.append(cluster)
        at += cluster_width(cluster)
    return "".join(out)


BOX = frozenset("┌┬┐├┼┤└┴┘│─")


def words(rows: list[str]) -> list[str]:
    """The words of `rows`, without the box's borders."""
    return [word for row in rows for word in row.split() if not set(word) <= BOX]


def box_rows(texts: list[str]) -> list[list[str]]:
    """The rows of a box-drawn table (header first) as cell texts, each cell's lines joined by a space.

    Checks the box as it goes: it opens with `┌` and closes with `└`, every
    content line has its `│` borders where the border line above it has its
    junctions, and no blank line falls inside it."""
    assert texts and texts[0].lstrip()[:1] == "┌" and texts[-1].lstrip()[:1] == "└", texts
    rows: list[list[str]] = []
    edges: list[int] = []
    for text in texts:
        body = text.lstrip()
        if body[:1] in ("┌", "├", "└"):
            rows.append([])
            edges = [cell_width(text[:index]) for index, ch in enumerate(text) if ch in "┌┬┐├┼┤└┴┘"]
            continue
        assert body[:1] == "│", f"not a box line: {text!r}"
        bars = [cell_width(text[:index]) for index, ch in enumerate(text) if ch == "│"]
        assert set(bars) <= set(edges), (text, bars, edges)
        pieces = [piece.strip() for piece in body.split("│")[1:-1]]
        if not rows[-1]:
            rows[-1] = [""] * len(pieces)
        rows[-1] = [f"{have} {piece}".strip() for have, piece in zip(rows[-1], pieces)]
    return [row for row in rows if row]


class WideTableLayoutTests(unittest.TestCase):
    def render(self, source: str, width: int, theme=THEME) -> list[Line]:
        return render_lines(source.split("\n"), MarkdownState(), width, theme)[0]

    def assert_owner_table(self, width: int, exact: bool = True) -> None:
        """The owner's table at `width` as a box: every cell inside its column, nothing past the row. `exact`: every
        word whole (a long word may otherwise break across rows, so only the characters are compared)."""
        rows = self.render(OWNER_TABLE, width)
        texts = lines_text(rows)
        for row, text in zip(rows, texts):
            self.assertLessEqual(line_width(row), width, text)
            self.assertFalse(text.startswith("|"), f"a raw source row: {text!r}")
            self.assertIsNone(re.search(r"\|\s*:?-{3,}", text), f"a raw divider: {text!r}")
        self.assertNotIn("", texts, "a blank line inside the box")
        cells = box_rows(texts)
        self.assertEqual(len(cells), 1 + len(OWNER_ROWS), texts)
        self.assertEqual(cells[0], list(OWNER_HEADER))
        self.assertEqual(sum(1 for text in texts if text.startswith("├")), len(OWNER_ROWS), "a line under each row")
        self.assertTrue(any(len(rows) > 2 for rows in [texts]), texts)
        # The header is bold in the brand colour, on every span that shows text; the borders are gutters.
        self.assertTrue(all(span.style.bold for span in rows[1] if span.text.strip() and not set(span.text) <= BOX))
        for got, source in zip(cells[1:], OWNER_ROWS):
            for ci, cell in enumerate(source):
                if exact:
                    self.assertEqual(" ".join(got[ci].split()), " ".join(shown(cell).split()), (width, ci))
                else:
                    self.assertEqual("".join(got[ci].split()), "".join(shown(cell).split()), (width, ci))

    def test_the_owners_table_wraps_inside_its_columns_at_150(self) -> None:
        self.assert_owner_table(146)  # a reply's text at 150 columns, beside the rail and margin

    def test_the_owners_table_wraps_inside_its_columns_at_100(self) -> None:
        self.assert_owner_table(96)

    def test_the_owners_table_wraps_inside_its_columns_at_80(self) -> None:
        self.assert_owner_table(76)

    def test_short_columns_keep_their_whole_width(self) -> None:
        texts = lines_text(self.render(OWNER_TABLE, 96))
        self.assertTrue(any("│ 출처 섹션 누락 │" in text for text in texts))
        self.assertTrue(any("│ src/tui/markdown.py │" in text for text in texts))

    def test_a_fitting_table_is_a_box(self) -> None:
        self.assertEqual(
            lines_text(self.render("| X | Y |\n| --- | --- |\n| 1 | a |\n| 2 | b |", 40)),
            ["┌─────┬─────┐", "│ X   │ Y   │", "├─────┼─────┤", "│ 1   │ a   │", "├─────┼─────┤", "│ 2   │ b   │",
             "└─────┴─────┘"],
        )

    def test_a_header_with_no_body_is_a_closed_box(self) -> None:
        self.assertEqual(lines_text(self.render("| a | b |\n|---|---|", 40)), ["┌─────┬─────┐", "│ a   │ b   │",
                                                                              "└─────┴─────┘"])

    def test_a_ragged_row_gets_columns_of_its_own(self) -> None:
        texts = lines_text(self.render("| a | b |\n|---|---|\n| 1 | 2 | 3 |", 40))
        self.assertEqual(box_rows(texts), [["a", "b", ""], ["1", "2", "3"]])

    def test_the_borders_are_gutters_so_a_drag_copies_the_cells(self) -> None:
        rows = self.render(OWNER_TABLE, 96)
        for row in rows:
            for span in row:
                if span.text.strip() and set(span.text) <= BOX:
                    self.assertTrue(span.style.gutter, span)
                elif span.text.strip():
                    self.assertFalse(span.style.gutter, span)
        copied = ["".join(span.text for span in _copied_part(row)).rstrip() for row in rows]
        self.assertTrue(all(not set(text) & BOX for text in copied), copied)
        self.assertEqual(copied[0], "")  # the top border copies as nothing
        self.assertEqual(copied[1].split(), ["고칠", "것", "담당", "내용"])
        self.assertIn("출처 섹션 누락", copied[3])

    def test_no_color_keeps_the_box(self) -> None:
        plain = without_colour(THEME)
        self.assertEqual(lines_text(self.render(OWNER_TABLE, 96, plain)), lines_text(self.render(OWNER_TABLE, 96)))
        rows = self.render(OWNER_TABLE, 96, plain)
        self.assertEqual(lines_text(rows)[0][0], "┌")
        self.assertTrue(all(span.style.bold for span in rows[1] if span.text.strip() and not set(span.text) <= BOX))

    def test_code_spans_keep_their_style_across_wrapped_rows(self) -> None:
        source = "| key | note |\n|---|---|\n| k1 | lead `alpha beta gamma delta epsilon zeta eta theta` tail |"
        rows = self.render(source, 34)
        code = [span for row in rows for span in row if span.style == THEME.code]
        self.assertEqual(" ".join(span.text for span in code).split(), "alpha beta gamma delta epsilon zeta eta theta".split())
        self.assertGreater(len({id(row) for row in rows for span in row if span.style == THEME.code}), 1,
                           "the code span did not wrap")
        self.assertFalse(any("`" in text for text in lines_text(rows)))

    def test_bold_inside_a_cell_stays_bold_across_a_wrap(self) -> None:
        rows = self.render("| a | b |\n|---|---|\n| x | **one two three four five six seven** |", 28)
        bold = [span.text for row in rows[3:] for span in row if span.style.bold and span.text.strip()]
        self.assertEqual(" ".join(bold).split(), "one two three four five six seven".split())
        self.assertGreater(len(rows), 5)

    def test_wide_characters_wrap_by_cell_width(self) -> None:
        cell = "日本語のテキストは空白がなくても列の幅で折り返されます"
        rows = self.render(f"| 名前 | 説明 |\n|---|---|\n| 東京 | {cell} |", 28)
        for row in rows:
            self.assertLessEqual(line_width(row), 28)
        self.assertEqual(box_rows(lines_text(rows))[1], ["東京", " ".join(box_rows(lines_text(rows))[1][1].split())])
        self.assertEqual("".join(box_rows(lines_text(rows))[1][1].split()), cell)
        self.assertGreater(len(rows), 6)

    def test_escaped_pipes_stay_inside_a_wrapped_cell(self) -> None:
        rows = lines_text(self.render("| a | b |\n|---|---|\n| x | left \\| right and a long tail of words here |", 24))
        self.assertGreater(len(rows), 6, "the cell did not wrap")
        self.assertEqual(box_rows(rows)[1], ["x", "left | right and a long tail of words here"])

    def test_a_long_url_like_token_breaks_inside_its_column_and_loses_nothing(self) -> None:
        url = "https://example.com/" + "/".join(f"segment{n}" for n in range(12)) + "/index.html"
        rows = self.render(f"| name | link |\n|---|---|\n| docs | {url} |", 44)
        for row in rows:
            self.assertLessEqual(line_width(row), 44)
        self.assertEqual("".join(box_rows(lines_text(rows))[1][1].split()), url)
        self.assertGreater(len(rows), 6)

    def test_an_indented_wide_table_wraps_behind_its_indent(self) -> None:
        cell = "a" * 17
        rows = self.render(f"  | {cell} | {cell} words |\n  |---|---|\n  | 1 | 2 |", 43)
        texts = lines_text(rows)  # the box fits at 42 cells, but not behind the indent
        for row, text in zip(rows, texts):
            self.assertLessEqual(line_width(row), 43)
            self.assertTrue(text.startswith("  "), text)
        self.assertEqual("".join(texts).count("a"), 34)
        self.assertEqual(words(texts).count("words"), 1)
        box_rows(texts)

    def test_too_narrow_for_columns_draws_records(self) -> None:
        rows = self.render(OWNER_TABLE, 24)
        texts = lines_text(rows)
        for row, text in zip(rows, texts):
            self.assertLessEqual(line_width(row), 24)
            self.assertIsNone(re.search(r"\|\s*:?-{3,}", text), text)
            self.assertFalse(text.startswith("| 고칠"), text)
            self.assertFalse(set(text) & BOX - {"│"}, text)
        for label in OWNER_HEADER:
            self.assertEqual(sum(1 for text in texts if text.startswith(label + ":")), len(OWNER_ROWS), label)
        joined = "".join("".join(texts).split())
        for row in OWNER_ROWS:
            for cell in row:
                self.assertIn("".join(shown(cell).split()), joined)

    def test_a_header_with_no_body_too_narrow_for_columns_keeps_its_labels(self) -> None:
        texts = lines_text(self.render("| first label | second label |\n|---|---|", 12))
        self.assertIn("firstlabel", "".join("".join(texts).split()))
        self.assertIn("secondlabel", "".join("".join(texts).split()))

    def test_every_width_from_40_to_200_keeps_every_cell_inside_the_row(self) -> None:
        for cols in range(40, 201):
            width = cols - 4  # a reply's text beside the rail and margin
            texts = lines_text(self.render(OWNER_TABLE, width))
            if texts[0].startswith(OWNER_HEADER[0] + ":"):  # too narrow for columns: records
                joined = "".join("".join(texts).split())
                for row in OWNER_ROWS:
                    for cell in row:
                        self.assertIn("".join(shown(cell).split()), joined, cols)
            else:
                with self.subTest(cols=cols):
                    self.assert_owner_table(width, exact=False)

    def test_fit_columns_keeps_short_columns_and_never_leaves_the_long_one_narrowest(self) -> None:
        self.assertEqual(fit_columns([14, 19, 250], [6, 19, 12], 142), (14, 19, 109))
        self.assertEqual(fit_columns([3, 4], [3, 4], 20), (3, 4))
        natural = [14, 19, 250]
        for room in range(30, 150):
            widths = fit_columns(natural, [6, 19, 12], room)
            if widths is None:
                continue
            self.assertLessEqual(sum(widths), room)
            kept = [width for width, own in zip(widths, natural) if width == own]
            self.assertGreaterEqual(widths[2], max(kept, default=0), room)
        # Past the word minimums, every column narrows to `TABLE_WRAP_MIN` before the table becomes records.
        self.assertEqual(fit_columns([40, 40, 40], [20, 20, 20], 30), (10, 10, 10))
        self.assertIsNone(fit_columns([40, 40, 40], [20, 20, 20], 23))

    def test_a_table_of_paths_stays_columns_where_each_column_holds_eight_cells(self) -> None:
        paths = [f"src/omh/module{n}/package/file{n}.py" for n in range(5)]
        source = "| " + " | ".join(f"h{n}" for n in range(5)) + " |\n|---|---|---|---|---|\n| " + " | ".join(paths) + " |"
        for cols in (60, 70, 87):
            texts = lines_text(self.render(source, cols - 4))
            self.assertFalse(any(text.startswith("h0:") for text in texts), (cols, texts))
            cells = box_rows(texts)
            self.assertEqual(cells[0], [f"h{n}" for n in range(5)])
            self.assertEqual(["".join(cell.split()) for cell in cells[1]], paths, cols)

    def test_header_code_spans_and_links_stay_bold(self) -> None:
        rows = self.render("| `key` | [docs](https://example.com) |\n|---|---|\n| a | b |", 60)
        shown_spans = [span for span in rows[1] if span.text.strip() and not set(span.text) <= BOX]
        self.assertEqual(" ".join(span.text for span in shown_spans).split(), ["key", "docs", "(https://example.com)"])
        self.assertTrue(all(span.style.bold for span in shown_spans), shown_spans)

    def test_a_rule_under_every_row_and_no_blank_inside_the_box(self) -> None:
        long = " ".join(f"word{n}" for n in range(40))
        texts = lines_text(self.render(f"| k | v |\n|---|---|\n| a | 1 |\n| b | 2 |\n| c | {long} |\n| d | 4 |", 60))
        self.assertNotIn("", texts)
        self.assertEqual([text[0] for text in texts if text[0] != "│"], ["┌", "├", "├", "├", "├", "└"])
        self.assertEqual([row[0] for row in box_rows(texts)], ["k", "a", "b", "c", "d"])


class WideTableStreamingTests(unittest.TestCase):
    def stream(self, text: str, cols: int, live_rows: int | None, chunk: int) -> tuple[list[str], list[str]]:
        """Stream `text` in `chunk`-character deltas, checking taken + live == history while no table was released.

        Returns (everything shown at the end, `/history`)."""
        transcript = Transcript(clock=lambda: 100.0)
        transcript.apply(ev("message.start"))
        taken: list[str] = []
        for at in range(0, len(text), chunk):
            transcript.apply(ev("message.delta", text=text[at : at + chunk]))
            taken += lines_text(transcript.take_stable_lines(cols, THEME, live_rows=live_rows))
            self.assertEqual(lines_text(transcript.take_stable_lines(cols, THEME, live_rows=live_rows)), [])
            live = lines_text(transcript.live_lines(cols, THEME))
            for row in taken:  # the live region may show a divider still arriving; scrollback never does
                self.assertIsNone(re.search(r"\|\s*:?-{3,}", row), row)
            for row in taken + live:
                self.assertLessEqual(cell_width(row), cols, row)
            if live_rows is None:
                self.assertEqual(taken + live, lines_text(transcript.history_lines(cols, THEME, details=False)))
        transcript.apply(ev("message.complete", text=text, status="complete"))
        taken += lines_text(transcript.take_stable_lines(cols, THEME, live_rows=live_rows))
        everything = taken + lines_text(transcript.live_lines(cols, THEME))
        return everything, lines_text(transcript.history_lines(cols, THEME, details=False))

    def test_the_owners_table_streamed_delta_by_delta_loses_and_repeats_nothing(self) -> None:
        text = "Four things to fix.\n\n" + OWNER_TABLE + "\n\nDone."
        expected = words([shown(cell) for row in OWNER_ROWS for cell in row] + list(OWNER_HEADER) + ["Four", "things",
                                                                                                    "to", "fix.", "Done."])
        for cols in (150, 100):
            for live_rows in (None, 42, 12):
                for chunk in (3, 7, 40):
                    with self.subTest(cols=cols, live_rows=live_rows, chunk=chunk):
                        everything, history = self.stream(text, cols, live_rows, chunk)
                        for rows in (everything, history):
                            got = [word for word in words([row for row in rows if not row.endswith("⚚ Hermes")])
                                   if word != "┃"]
                            if live_rows == 12 and rows is everything:
                                # released on the first rows' columns: a later path may break after a `/`
                                self.assertEqual(sorted("".join(got)), sorted("".join(expected)))
                            else:
                                self.assertEqual(sorted(got), sorted(expected))
                            box = [row[4:] for row in rows if row[4:5] in ("┌", "├", "└", "│")]
                            self.assertEqual((box[0][0], box[-1][0]), ("┌", "└"), "the box is not closed")
                            self.assertEqual(sum(1 for row in box if row[0] == "┌"), 1)
                            self.assertEqual(sum(1 for row in box if row[0] == "└"), 1)

    def test_a_table_ending_the_reply_is_closed_in_scrollback_after_a_release(self) -> None:
        text = "| a | b |\n|---|---|\n" + "".join(f"| r{n} | s{n} |\n" for n in range(12))
        for ending in ("complete", "final"):
            with self.subTest(ending=ending):
                transcript = Transcript(clock=lambda: 100.0)
                transcript.apply(ev("message.start"))
                transcript.apply(ev("message.delta", text=text))
                taken = lines_text(transcript.take_stable_lines(60, THEME, live_rows=8))
                self.assertTrue(any("r10" in row for row in taken), "the table was not released")
                self.assertFalse(any("└" in row for row in taken), "closed before the table ended")
                live = lines_text(transcript.live_lines(60, THEME))
                self.assertTrue(live and "└" in live[-1], live)  # the live region shows the box closed
                if ending == "complete":
                    transcript.apply(ev("message.complete", text="", status="complete"))
                    taken += lines_text(transcript.take_stable_lines(60, THEME, live_rows=8))
                else:
                    taken += lines_text(transcript.take_stable_lines(60, THEME, final=True, live_rows=8))
                self.assertEqual(taken[-1][4:5], "└", taken[-3:])
                self.assertEqual(sum(1 for row in taken if "└" in row), 1)
                self.assertEqual(lines_text(transcript.live_lines(60, THEME)), [])

    def test_a_released_table_closes_before_the_text_after_it(self) -> None:
        text = "| a | b |\n|---|---|\n" + "".join(f"| r{n} | s{n} |\n" for n in range(12))
        transcript = Transcript(clock=lambda: 100.0)
        transcript.apply(ev("message.start"))
        transcript.apply(ev("message.delta", text=text))
        taken = lines_text(transcript.take_stable_lines(60, THEME, live_rows=8))
        transcript.apply(ev("message.delta", text="after the table\n"))
        taken += lines_text(transcript.take_stable_lines(60, THEME, live_rows=8))
        at = next(i for i, row in enumerate(taken) if "after the table" in row)
        self.assertEqual(taken[at - 1][4:5], "└", taken[at - 3 : at + 1])

    def test_a_tall_wrapped_table_is_released_by_the_rows_it_draws(self) -> None:
        long = " ".join(f"word{n}" for n in range(60))
        text = "| a | b |\n|---|---|\n" + "".join(f"| r{n} | {long} |\n" for n in range(3))
        self.assertEqual(_stable_lines(text, cap=6), [])  # five lines held: under the line cap
        # released, but its last row waits for the next line: it may be the header of a next table
        self.assertEqual(len(_stable_lines(text, cap=6, height=lambda run: 40)), 4)
        self.assertEqual(len(_stable_lines(text + "after", cap=6, height=lambda run: 40)), 5)
        self.assertEqual(_stable_lines("| a | b |\n|---|---|\n", cap=1, height=lambda run: 40), [])
        transcript = Transcript(clock=lambda: 100.0)
        transcript.apply(ev("message.start"))
        transcript.apply(ev("message.delta", text=text))
        taken = lines_text(transcript.take_stable_lines(40, THEME, live_rows=12))
        self.assertTrue(any("r0" in row for row in taken), "the tall rows stayed held")

    def test_a_late_long_row_on_frozen_columns_wraps_instead_of_overflowing(self) -> None:
        head = "| key | value |\n|---|---|\n" + "".join(f"| k{n} | v{n} |\n" for n in range(10))
        late = "| late | " + " ".join(f"tail{n}" for n in range(40)) + " |\n"
        transcript = Transcript(clock=lambda: 100.0)
        transcript.apply(ev("message.start"))
        transcript.apply(ev("message.delta", text=head))
        taken = lines_text(transcript.take_stable_lines(60, THEME, live_rows=8))
        self.assertTrue(taken)
        self.assertIsInstance(transcript._cursor_state.table, TableColumns)
        transcript.apply(ev("message.delta", text=late))
        taken += lines_text(transcript.take_stable_lines(60, THEME, live_rows=8))
        transcript.apply(ev("message.complete", text="", status="complete"))
        taken += lines_text(transcript.take_stable_lines(60, THEME, live_rows=8))
        for row in taken:
            self.assertLessEqual(cell_width(row), 60, row)
        late_rows = [row for row in taken if "tail" in row]
        self.assertGreater(len(late_rows), 1)
        starts = {cell_width(row[: row.index("tail")]) for row in late_rows}
        self.assertEqual(len(starts), 1, late_rows)
        self.assertEqual(sorted(word for word in words(taken) if word.startswith("tail")),
                         sorted(f"tail{n}" for n in range(40)))
        box_rows([row[4:] for row in taken if row[4:5] in ("┌", "├", "└", "│")])

    def test_a_late_long_cell_on_narrow_frozen_columns_takes_the_rows_room(self) -> None:
        head = "| key | value | note |\n|---|---|---|\n" + "".join(f"| k{n} | v{n} | ok |\n" for n in range(30))
        sentence = "this value is a long sentence that explains what happened in plain words and keeps going for a while "
        late = "| late | " + sentence * 2 + "| fine |\n"
        transcript = Transcript(clock=lambda: 100.0)
        transcript.apply(ev("message.start"))
        transcript.apply(ev("message.delta", text=head))
        taken = lines_text(transcript.take_stable_lines(150, THEME, live_rows=42))
        self.assertIsInstance(transcript._cursor_state.table, TableColumns, "the table was not released")
        heights = []
        for at in range(0, len(late), 5):
            transcript.apply(ev("message.delta", text=late[at : at + 5]))
            taken += lines_text(transcript.take_stable_lines(150, THEME, live_rows=42))
            heights.append(len(lines_text(transcript.live_lines(150, THEME))))
        heights.pop()  # the row's line break: the row has left for scrollback, only the box's bottom is live
        self.assertEqual(heights, sorted(heights), "the live height jumped back and forth")
        self.assertLessEqual(max(heights), 5, heights)
        transcript.apply(ev("message.complete", text="", status="complete"))
        taken += lines_text(transcript.take_stable_lines(150, THEME, live_rows=42))
        late_rows = [row for row in taken[next(i for i, row in enumerate(taken) if "late" in row):] if "│" in row]
        self.assertLessEqual(len(late_rows), 3, late_rows)
        self.assertGreaterEqual(max(len(row.split("│")[2].strip()) for row in late_rows), 100, late_rows)
        self.assertEqual(sorted(w for w in words(late_rows) if w != "┃"), sorted(["late", "fine", *(sentence * 2).split()]))
        # The rule above the late row meets the narrow rows' borders and its own.
        rule = taken[next(i for i, row in enumerate(taken) if "late" in row) - 1]
        self.assertTrue({"┴", "┬"} <= set(rule), rule)
        box_rows([row[4:] for row in taken if row[4:5] in ("┌", "├", "└", "│")])

    def test_history_recomputes_the_widths_over_the_whole_table(self) -> None:
        source = "| a | b |\n|---|---|\n" + "".join(f"| r{n} | short |\n" for n in range(8))
        source += "| last | " + " ".join(f"w{n}" for n in range(30)) + " |"
        whole = lines_text(render_markdown(source, 50, THEME))
        cells = box_rows(whole)
        self.assertEqual(cells[-1][0], "last")
        self.assertEqual(cells[-1][1].split(), [f"w{n}" for n in range(30)])


if __name__ == "__main__":
    unittest.main()
