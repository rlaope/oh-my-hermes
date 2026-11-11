"""Hermes inline edit diffs as transcript rows (`omh.tui.diff_view`).

The sample payloads are built the way Hermes 6c61c3e27d builds
`tool.complete.payload.inline_diff` (`agent/display.py`): `_emit_inline_diff`
writes its "  ┊ review diff" header, `_render_inline_unified_diff` folds the
`---`/`+++` pair into one `a/x → b/x` line and wraps every other line in the
24-bit SGR colour `_diff_ansi` resolves (the dark-terminal fallbacks below),
and `_summarize_rendered_diff_sections` appends its omitted-lines summary.
Every expectation is a literal row, never a call back into the module.
"""

from __future__ import annotations

import random
import unicodedata
import unittest

from _tui_lines import line_text, lines_text
from omh.tui.diff_view import (
    DIFF_ADDED,
    DIFF_CONTEXT,
    DIFF_FILE,
    DIFF_HUNK,
    DIFF_NOTE,
    DIFF_REMOVED,
    DiffLine,
    diff_rows,
    parse_inline_diff,
)
from omh.tui.style import WRAP_SPACE, Span, wrap_mark
from omh.tui.theme import DEFAULT_THEME as THEME
from omh.tui.width import is_control, line_width

RESET = "\x1b[0m"
FILE = "\x1b[38;2;180;160;255m"
HUNK = "\x1b[38;2;120;120;140m"
MINUS = "\x1b[38;2;255;255;255;48;2;120;20;20m"
PLUS = "\x1b[38;2;255;255;255;48;2;20;90;20m"
DIM = "\x1b[38;2;150;150;150m"
REVIEW_HEADER = "  ┊ review diff"
EARTH = "\U0001F30F"

SAMPLE = "\n".join(
    [
        REVIEW_HEADER,
        f"{FILE}a/src/app.py → b/src/app.py{RESET}",
        f"{HUNK}@@ -1,3 +1,3 @@{RESET}",
        f"{DIM} import os{RESET}",
        f"{MINUS}-print('hello'){RESET}",
        f"{PLUS}+print('안녕 {EARTH}'){RESET}",
        "\\ No newline at end of file",
        f"{HUNK}… omitted 12 diff line(s) across 1 additional file(s)/section(s){RESET}",
    ]
)


def long_diff(changed: int) -> str:
    """A one-file payload with a hunk header and `changed` added lines (2 + changed diff lines)."""
    lines = [REVIEW_HEADER, f"{FILE}a/big.py → b/big.py{RESET}", f"{HUNK}@@ -0,0 +1,{changed} @@{RESET}"]
    lines.extend(f"{PLUS}+line {number}{RESET}" for number in range(1, changed + 1))
    return "\n".join(lines)


class ParseTests(unittest.TestCase):
    def test_colour_and_the_review_header_go_and_each_line_is_classified(self) -> None:
        self.assertEqual(
            parse_inline_diff(SAMPLE),
            (
                DiffLine(DIFF_FILE, "src/app.py"),
                DiffLine(DIFF_HUNK, "@@ -1,3 +1,3 @@"),
                DiffLine(DIFF_CONTEXT, " import os"),
                DiffLine(DIFF_REMOVED, "-print('hello')"),
                DiffLine(DIFF_ADDED, f"+print('안녕 {EARTH}')"),
                DiffLine(DIFF_NOTE, "\\ No newline at end of file"),
                DiffLine(DIFF_NOTE, "… omitted 12 diff line(s) across 1 additional file(s)/section(s)"),
            ),
        )

    def test_an_empty_payload_or_a_bare_header_is_no_diff(self) -> None:
        for payload in ("", "\n\n", REVIEW_HEADER, f"\n{REVIEW_HEADER}\n\n", f"{DIM}{RESET}"):
            with self.subTest(payload=payload):
                self.assertEqual(parse_inline_diff(payload), ())

    def test_a_payload_without_the_header_keeps_its_first_line(self) -> None:
        self.assertEqual(
            parse_inline_diff(f"{FILE}/dev/null → b/new.py{RESET}\r\n{PLUS}+x = 1{RESET}\r\n"),
            (DiffLine(DIFF_FILE, "new.py"), DiffLine(DIFF_ADDED, "+x = 1")),
        )

    def test_tabs_expand_and_decomposed_hangul_is_kept_for_the_renderer_to_compose(self) -> None:
        decomposed = unicodedata.normalize("NFD", "한글")
        lines = parse_inline_diff(f"{PLUS}+\t{decomposed}{RESET}")
        self.assertEqual(lines, (DiffLine(DIFF_ADDED, "+   " + decomposed),))
        self.assertEqual(lines_text(diff_rows(lines, 13, THEME)), ["     +   한글"])


class RowTests(unittest.TestCase):
    def test_hermes_padding_after_a_changed_line_wraps_no_band_row(self) -> None:
        # Hermes 6c61c3e27d pads each changed line to 143 cells with spaces (a live patch's inline_diff, read back from
        # its state.db display_metadata); on a narrower terminal each band wrapped into an empty second band row.
        removed, added = '-print("hello")'.ljust(143), '+print("hi")'.ljust(143)
        padded = "\n".join([REVIEW_HEADER, f"{FILE}a/app.py → b/app.py{RESET}", f"{DIM}@@ -1,3 +1,3 @@{RESET}",
                            f"{DIM} import os{RESET}", f"{DIM} {RESET}", f"{MINUS}{removed}{RESET}", f"{PLUS}{added}{RESET}"])
        lines = parse_inline_diff(padded)
        self.assertEqual([line.text for line in lines[2:]], [" import os", " ", '-print("hello")', '+print("hi")'])
        self.assertEqual([line_text(row).rstrip() for row in diff_rows(lines, 100, THEME)],
                         ["     app.py", "   1  import os", "   2", '   3 -print("hello")', '   3 +print("hi")'])

    def test_rows_hang_under_the_tool_and_take_their_roles(self) -> None:
        rows = diff_rows(parse_inline_diff(SAMPLE), 40, THEME)
        indent = Span("     ")
        self.assertEqual(
            rows,
            [
                (indent, Span("src/app.py", THEME.label)),
                # the hunk header is no row: its starts number the lines in the dim gutter
                (Span("   1 ", THEME.muted), Span(" import os", THEME.code)),
                (Span("   2 ", THEME.muted), Span("-print('hello')" + " " * 20, THEME.diff_remove)),
                (Span("   2 ", THEME.muted), Span(f"+print('안녕 {EARTH}')" + " " * 18, THEME.diff_add)),  # 17 cells
                (indent, Span("\\ No newline at end of file", THEME.muted)),
                (indent, Span("… omitted 12 diff line(s) across 1", THEME.muted)),
                (wrap_mark(WRAP_SPACE), indent, Span("additional file(s)/section(s)", THEME.muted)),  # joined on copy
            ],
        )

    def test_bands_fill_the_width_with_wide_glyphs_and_wrapped_rows(self) -> None:
        line = DiffLine(DIFF_ADDED, "+" + "한글" * 6 + EARTH * 3 + "x")
        for width in (9, 13, 20, 41, 80):
            with self.subTest(width=width):
                rows = diff_rows((line, DiffLine(DIFF_REMOVED, "-")), width, THEME)
                self.assertTrue(all(line_width(row) == width for row in rows), lines_text(rows))
                self.assertEqual("".join(row[-1].text for row in rows[:-1]).replace(" ", ""), line.text)
                self.assertEqual({row[-1].style for row in rows[:-1]}, {THEME.diff_add})
                self.assertEqual(rows[-1][-1].style, THEME.diff_remove)

    def test_a_terminal_too_narrow_for_the_indent_drops_it(self) -> None:
        lines = (DiffLine(DIFF_HUNK, "@@ -1 +1 @@"), DiffLine(DIFF_ADDED, "+abc"), DiffLine(DIFF_CONTEXT, " x"))
        self.assertEqual(lines_text(diff_rows(lines, 8, THEME)), ["+abc    ", " x"])
        self.assertEqual(lines_text(diff_rows(lines, 10, THEME)), ["+abc      ", " x"])
        self.assertEqual(lines_text(diff_rows(lines, 11, THEME)), ["   1 +abc  ", "   2  x"])

    def test_the_gutter_numbers_each_side_and_marks_where_a_later_hunk_jumps(self) -> None:
        lines = (
            DiffLine(DIFF_FILE, "app.py"),
            DiffLine(DIFF_HUNK, "@@ -10,3 +10,3 @@ def main():"),
            DiffLine(DIFF_CONTEXT, " keep"),
            DiffLine(DIFF_REMOVED, "-old"),
            DiffLine(DIFF_ADDED, "+new"),
            DiffLine(DIFF_ADDED, "+more"),
            DiffLine(DIFF_CONTEXT, " tail"),
            DiffLine(DIFF_HUNK, "@@ -120 +121 @@"),
            DiffLine(DIFF_REMOVED, "-x = 1"),
            DiffLine(DIFF_ADDED, "+x = 2"),
        )
        rows = diff_rows(lines, 20, THEME)
        self.assertEqual(
            [line_text(row).rstrip() for row in rows],
            ["     app.py", "  10  keep", "  11 -old", "  11 +new", "  12 +more", "  13  tail", "   ⋮", " 120 -x = 1",
             " 121 +x = 2"],
        )
        self.assertEqual(rows[6], (Span("   ⋮", THEME.dim),))
        # every numbered row's text starts where the indent ends; a band runs from there to the edge
        for row in rows[1:6] + rows[7:]:
            self.assertEqual((line_width(row[:1]), row[0].style), (5, THEME.muted))
        for row in (rows[2], rows[3], rows[4], rows[7], rows[8]):
            self.assertEqual(line_width(row), 20)
            self.assertIn(row[1].style, (THEME.diff_add, THEME.diff_remove))

    def test_a_number_longer_than_the_indent_widens_the_gutter_for_the_whole_diff(self) -> None:
        lines = (DiffLine(DIFF_HUNK, "@@ -9999,2 +9999,2 @@"), DiffLine(DIFF_CONTEXT, " a"), DiffLine(DIFF_ADDED, "+b"))
        self.assertEqual(lines_text(diff_rows(lines, 20, THEME)), [" 9999  a", "10000 +b" + " " * 12])

    def test_a_header_without_both_starts_numbers_nothing(self) -> None:
        lines = (DiffLine(DIFF_HUNK, "@@ garbage @@"), DiffLine(DIFF_ADDED, "+b"))
        self.assertEqual(lines_text(diff_rows(lines, 20, THEME)), ["     +b" + " " * 13])

    def test_the_preview_shows_24_lines_and_counts_the_rest(self) -> None:
        lines = parse_inline_diff(long_diff(28))
        self.assertEqual(len(lines), 30)
        rows = diff_rows(lines, 60, THEME)
        # the file row, the 22 added lines the preview reaches (its hunk header is the gutter), the count
        self.assertEqual(len(rows), 1 + 22 + 1)
        self.assertEqual(lines_text(rows)[22].rstrip(), "  22 +line 22")
        self.assertEqual(rows[-1], (Span("     "), Span("… +6 lines · ctrl+o shows all", THEME.muted)))
        full = diff_rows(lines, 60, THEME, full=True)
        self.assertEqual(len(full), 1 + 28)
        self.assertEqual(lines_text(full)[-1].rstrip(), "  28 +line 28")
        self.assertEqual(lines_text(diff_rows(parse_inline_diff(long_diff(23)), 60, THEME))[-1], "     … +1 line · ctrl+o shows all")
        self.assertEqual(len(diff_rows(parse_inline_diff(long_diff(22)), 60, THEME)), 1 + 22)

    def test_random_payloads_never_raise_or_paint_a_control_character(self) -> None:
        generator = random.Random(2085)
        alphabet = ["\x1b", "[", "]", "38;2;1;2;3", "m", "\x07", "\\", "+", "-", "@@", " ", "→", "┊", "\n", "\t",
                    "\r", "한", EARTH, "\x9b", "\x9d", "a", "0", ";", "\x00"]
        for _ in range(300):
            payload = "".join(generator.choice(alphabet) for _ in range(generator.randrange(0, 60)))
            for width in (1, 5, 9, 40):
                with self.subTest(payload=payload, width=width):
                    rows = diff_rows(parse_inline_diff(payload), width, THEME, full=generator.random() < 0.5)
                    for row in rows:
                        for span in row:
                            self.assertFalse(any(is_control(ch) for ch in span.text), span.text)
                    if width >= 9:
                        self.assertTrue(all(line_width(row) <= width for row in rows))


class FileHeaderTests(unittest.TestCase):
    def test_an_edit_names_its_file_once(self) -> None:
        from omh.tui.diff_view import compact_file_header

        self.assertEqual(compact_file_header("a//tmp/p/hello.py → b//tmp/p/hello.py"), "/tmp/p/hello.py")
        self.assertEqual(compact_file_header("a/src/x.py → b/src/x.py"), "src/x.py")
        self.assertEqual(compact_file_header("a/old.py → b/new.py"), "old.py → new.py")

    def test_a_long_header_is_one_row_ending_in_the_file_name(self) -> None:
        from omh.tui.diff_view import diff_rows, parse_inline_diff
        from omh.tui.theme import DEFAULT_THEME

        long = "/private/tmp/claude-501/" + "x" * 80 + "/scratchpad/m9/project/hello.py"
        lines = parse_inline_diff(f"a/{long} → b/{long}\n@@ -1 +1 @@\n-a\n+b")
        rows = diff_rows(lines, 60, DEFAULT_THEME, full=True)
        header = line_text(rows[0])
        self.assertTrue(header.rstrip().endswith("project/hello.py"), header)
        self.assertIn("…", header)
        self.assertNotIn("→", header)


if __name__ == "__main__":
    unittest.main()
