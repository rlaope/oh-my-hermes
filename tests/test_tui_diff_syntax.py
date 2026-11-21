"""An edit diff's code lines carry syntax colour, as fenced code does (the owner, 2026-11-21: every line of a diff
read in one turquoise, while a Claude Code diff colours keywords, strings and comments).

The file header names the language (`language_of`: `e2e/spec.ts` is TypeScript, `src/app.py` Python); each `+`, `-`
and context line is highlighted by `highlight.highlight_line` after its mark, over its band. A colour that would not
read on a band is lifted there to `TEXT_CONTRAST` (`_on_band`). Each side of the diff carries its own open string or
comment across lines, and a hunk or a file header resets both. A file with no syntax table keeps the one-colour rows.
"""

from __future__ import annotations

import unittest

from omh.tui.diff_view import DIFF_ADDED, DIFF_CONTEXT, DIFF_REMOVED, DiffLine, diff_rows, language_of, parse_inline_diff
from omh.tui.style import Span
from omh.tui.theme import DEFAULT_THEME as THEME, TEXT_CONTRAST, contrast_ratio, theme_named
from omh.tui.width import line_width


def payload(path: str, *lines: str) -> str:
    return "\n".join([f"a/{path} → b/{path}", "@@ -1,9 +1,9 @@", *lines])


def spans_of(text: str, rows) -> list[Span]:
    """The spans of the row whose text holds `text`, gutter dropped."""
    row = next(row for row in rows if text in "".join(span.text for span in row))
    return list(row[1:])


def style_of(word: str, spans: list[Span]):
    return next(span.style for span in spans if word in span.text)


class LanguageTests(unittest.TestCase):
    def test_the_file_name_names_the_language(self) -> None:
        cases = {"e2e/spec.ts": "ts", "src/app.py": "py", "a/Makefile": "makefile", "README": "", "x.TSX": "tsx",
                 "dir.v2/notes": ""}
        for path, lang in cases.items():
            with self.subTest(path=path):
                self.assertEqual(language_of(path), lang)


class SyntaxColourTests(unittest.TestCase):
    def rows(self, path: str, *lines: str, theme=THEME, width: int = 100):
        return diff_rows(parse_inline_diff(payload(path, *lines)), width, theme)

    def test_context_added_and_removed_lines_colour_keywords_strings_and_comments(self) -> None:
        rows = self.rows("e2e/spec.ts", ' const page = "x";', '+  const other = "y"; // why', "-  let old = 1;")
        context = spans_of("page", rows)
        self.assertEqual(style_of("const", context).fg, THEME.syntax_keyword.fg)
        self.assertEqual(style_of('"x"', context).fg, THEME.syntax_string.fg)
        added = spans_of("other", rows)
        self.assertEqual({span.style.bg for span in added}, {THEME.diff_add.bg})  # the band stays whole
        self.assertNotEqual(style_of("const", added).fg, style_of("other", added).fg)
        self.assertTrue(style_of("// why", added).italic)
        removed = spans_of("old", rows)
        self.assertEqual({span.style.bg for span in removed}, {THEME.diff_remove.bg})
        self.assertTrue(style_of("let", removed).bold)

    def test_plain_code_on_a_band_keeps_the_bands_own_ink(self) -> None:
        added = spans_of("other", self.rows("x.ts", "+  other = y;"))
        self.assertEqual(style_of("other", added).fg, THEME.diff_add.fg)

    def test_every_coloured_span_on_a_band_reads_there(self) -> None:
        for name in ("omh", "amber", "crimson", "kanagawa", "mono"):
            for background in (None, "#FFFFFF"):
                theme = theme_named(name, background) if background else theme_named(name)
                rows = self.rows("x.py", '+def f(x=1):  # note "q"', '-    return "s"  # gone', theme=theme)
                for row in rows:
                    for span in row[1:]:
                        if span.style.bg and span.style.fg and span.text.strip():
                            with self.subTest(theme=name, background=background, text=span.text):
                                self.assertGreaterEqual(contrast_ratio(span.style.fg, span.style.bg), TEXT_CONTRAST - 0.01)

    def test_a_band_still_reaches_the_right_edge_when_a_coloured_line_wraps(self) -> None:
        line = '+  const other = "' + "x" * 120 + '"; // end'
        for width in (40, 81, 100):
            with self.subTest(width=width):
                rows = self.rows("x.ts", line, width=width)
                banded = [row for row in rows if any(span.style.bg == THEME.diff_add.bg for span in row)]
                self.assertGreater(len(banded), 1)
                self.assertTrue(all(line_width(row) == width for row in banded), [line_width(row) for row in banded])
                self.assertEqual("".join(span.text for row in banded for span in row[1:]).rstrip(), line)

    def test_a_file_with_no_syntax_table_keeps_one_colour_per_line(self) -> None:
        rows = self.rows("notes.txt", ' const page = "x";', '+const other = "y";')
        self.assertEqual(spans_of("page", rows), [Span(' const page = "x";', THEME.code)])
        self.assertEqual(len(spans_of("other", rows)), 1)

    def test_each_side_carries_its_own_open_comment(self) -> None:
        # The old file opens a block comment on its removed line; the new file never does.
        rows = self.rows("x.ts", "-/* start", "+let a = 1;", " let b = 2;")
        self.assertTrue(style_of("let", spans_of("a = 1", rows)).bold)  # added: a keyword, no comment open
        self.assertTrue(style_of("let", spans_of("b = 2", rows)).bold)  # context follows the new file

    def test_a_context_line_moves_both_sides(self) -> None:
        rows = self.rows("x.ts", " /* start", "-let a = 1; */", "+let b = 2; */")
        for text in ("a = 1", "b = 2"):
            with self.subTest(text=text):
                self.assertTrue(style_of("let", spans_of(text, rows)).italic)  # both sides inside the comment

    def test_a_new_hunk_closes_what_the_last_one_left_open(self) -> None:
        text = "\n".join(["a/x.ts → b/x.ts", "@@ -1,1 +1,1 @@", " /* open", "@@ -9,1 +9,1 @@", " let c = 3;"])
        rows = diff_rows(parse_inline_diff(text), 100, THEME)
        self.assertTrue(style_of("let", spans_of("c = 3", rows)).bold)

    def test_the_mark_keeps_the_lines_own_style(self) -> None:
        for kind, mark, band in ((DIFF_ADDED, "+", THEME.diff_add), (DIFF_REMOVED, "-", THEME.diff_remove)):
            with self.subTest(kind=kind):
                lines = (DiffLine("file", "x.py"), DiffLine("hunk", "@@ -1,1 +1,1 @@"), DiffLine(kind, f"{mark}x = 1"))
                spans = spans_of("x = 1", diff_rows(lines, 60, THEME))
                self.assertEqual(spans[0], Span(mark, band))

    def test_a_context_line_alone_is_not_banded(self) -> None:
        lines = (DiffLine("file", "x.py"), DiffLine("hunk", "@@ -1,1 +1,1 @@"), DiffLine(DIFF_CONTEXT, " x = 'a'"))
        spans = spans_of("x = ", diff_rows(lines, 60, THEME))
        self.assertTrue(all(span.style.bg is None for span in spans), spans)


class PaletteTests(unittest.TestCase):
    def test_the_default_looks_rail_and_spinner_are_violet(self) -> None:
        # The owner, 2026-11-21: the spectrum look's accent moved from orange (#F8A87E) to a soft violet.
        from omh.skin_pack import default_theme
        from omh.tui.theme import DEFAULT_LAUNCH, launch_palette, with_launch_look

        self.assertEqual(DEFAULT_LAUNCH, "spectrum")
        for surface, label in (("#0a0e14", "#B79CFF"), ("#FFFFFF", "#6B3FD0")):
            with self.subTest(surface=surface):
                self.assertEqual(launch_palette("spectrum", surface).label, label)
                look = with_launch_look(THEME, default_theme(), surface, "spectrum")
                red, green, blue = (int(look.accent.fg[index : index + 2], 16) for index in (1, 3, 5))
                self.assertTrue(blue > green and red > green, look.accent.fg)  # violet: blue and red over green

    def test_the_default_code_colours_are_four_different_hues(self) -> None:
        colours = {THEME.syntax_keyword.fg, THEME.syntax_string.fg, THEME.syntax_number.fg, THEME.syntax_comment.fg}
        self.assertEqual(len(colours), 4)
        # None of them is the turquoise every code token used to share.
        self.assertNotIn("#00CED1", colours)

    def test_the_default_comment_reads_on_both_bands(self) -> None:
        for band in (THEME.diff_add.bg, THEME.diff_remove.bg):
            with self.subTest(band=band):
                self.assertGreaterEqual(contrast_ratio(THEME.syntax_comment.fg, band), TEXT_CONTRAST)


if __name__ == "__main__":
    unittest.main()
