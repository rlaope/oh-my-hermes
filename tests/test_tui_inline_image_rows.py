"""A sent prompt draws a preview under each image label that has one, and the rows it adds are exactly the preview's."""

from __future__ import annotations

from dataclasses import replace
import unittest

from _tui_lines import lines_text
from omh.tui.inline_image import Preview, preview_from
from omh.tui.style import Style
from omh.tui.theme import DEFAULT_THEME
from omh.tui.transcript import OUTPUT_INDENT, OUTPUT_MARK, RAIL, Transcript, UserBlock, block_rows
from omh.tui.width import line_width

BAND = Style(bg="#202020")
BANDED = replace(DEFAULT_THEME, prompt_band=BAND)
OPAQUE, CLEAR = (10, 20, 30, 255), (0, 0, 0, 0)
BOTTOM = (200, 100, 50, 255)


def unicode_preview() -> Preview:
    """2 rows of 3 cells: both halves, top only, bottom only; then a transparent cell, both, both."""
    cells = [
        [[*OPAQUE, *BOTTOM], [*OPAQUE, *CLEAR], [*CLEAR, *BOTTOM]],
        [[*CLEAR, *CLEAR], [*OPAQUE, *BOTTOM], [*OPAQUE, *BOTTOM]],
    ]
    preview = preview_from({"mode": "unicode", "cols": 3, "rows": 2, "cells": cells})
    assert preview is not None
    return preview


def spans_of(rows, text):
    return [span for row in rows for span in row if span.text == text]


class PreviewRowsTests(unittest.TestCase):
    def test_without_previews_the_rows_are_the_label_rows_only(self) -> None:
        rows = block_rows(UserBlock("look", images=("[Image #1]", "[Image #2]")), 60, DEFAULT_THEME)
        self.assertEqual(lines_text(rows), ["┃ ❯ look", "┃   ⎿  [Image #1]", "┃   ⎿  [Image #2]"])
        again = block_rows(UserBlock("look", images=("[Image #1]", "[Image #2]"), previews=(None, None)), 60, DEFAULT_THEME)
        self.assertEqual(again, rows)
        short = block_rows(UserBlock("look", images=("[Image #1]", "[Image #2]"), previews=(None,)), 60, DEFAULT_THEME)
        self.assertEqual(short, rows)

    def test_rows_are_text_plus_labels_plus_preview_rows_under_their_label(self) -> None:
        preview = unicode_preview()
        block = UserBlock("look", images=("[Image #1]", "[Image #2]"), previews=(preview, None))
        rows = block_rows(block, 60, DEFAULT_THEME)
        self.assertEqual(len(rows), 1 + 2 + preview.rows)
        text = lines_text(rows)
        self.assertEqual(text[:2], ["┃ ❯ look", "┃   ⎿  [Image #1]"])
        self.assertEqual(text[2], "┃      ▀▀▄")
        self.assertEqual(text[3], "┃       ▀▀")
        self.assertEqual(text[-1], "┃   ⎿  [Image #2]")
        self.assertTrue(all(line_width(row) <= 60 for row in rows))

    def test_a_second_image_may_have_the_preview(self) -> None:
        preview = unicode_preview()
        rows = block_rows(UserBlock("", images=("[Image #1]", "[Image #2]"), previews=(None, preview)), 60, DEFAULT_THEME)
        text = lines_text(rows)
        self.assertEqual(text.index("┃   ⎿  [Image #2]"), len(text) - 1 - preview.rows)

    def test_preview_cells_keep_their_colours_and_stay_out_of_the_copy(self) -> None:
        rows = block_rows(UserBlock("x", images=("[Image #1]",), previews=(unicode_preview(),)), 60, DEFAULT_THEME)
        both = spans_of(rows, "▀")[0]
        self.assertEqual((both.style.fg, both.style.bg, both.style.gutter), ("#0a141e", "#c86432", True))
        top = spans_of(rows, "▀")[1]
        self.assertEqual((top.style.fg, top.style.bg, top.style.gutter), ("#0a141e", None, True))
        bottom = spans_of(rows, "▄")[0]
        self.assertEqual((bottom.style.fg, bottom.style.bg, bottom.style.gutter), ("#c86432", None, True))

    def test_the_band_does_not_paint_over_a_half_blocks_lower_colour(self) -> None:
        block = UserBlock("x", images=("[Image #1]",), previews=(unicode_preview(),))
        rows = block_rows(block, 60, BANDED)
        both = spans_of(rows, "▀")[0]
        self.assertEqual((both.style.fg, both.style.bg), ("#0a141e", "#c86432"))
        top_only = spans_of(rows, "▀")[1]
        self.assertEqual(top_only.style.bg, BAND.bg)  # its lower half is the band
        for row in rows:  # every row, the text and the label too, runs on the band to the edge
            self.assertEqual(row[-1].text, "")
            self.assertEqual(row[-1].style.bg, BAND.bg)
        self.assertEqual(lines_text(rows), lines_text(block_rows(block, 60, DEFAULT_THEME)))

    def test_a_kitty_preview_rows_are_drawn_with_the_colour_that_names_the_image(self) -> None:
        d = "\u0305\u030d"
        placeholder = ["\U0010eeee" + d[0] + "\U0010eeee", "\U0010eeee" + d[1] + "\U0010eeee"]
        transmit = "\x1b_Ga=T,U=1,i=32768,c=2,r=2,f=100,q=2,m=0;AAAA\x1b\\"
        result = {"mode": "kitty", "cols": 2, "rows": 2, "color": "#008000", "transmit": transmit, "placeholder": placeholder}
        preview = preview_from(result)
        assert preview is not None
        rows = block_rows(UserBlock("", images=("[Image #1]",), previews=(preview,)), 60, BANDED)
        self.assertEqual(len(rows), 3)
        for row in rows[1:]:
            cell = [span for span in row if "\U0010eeee" in span.text][0]
            self.assertEqual((cell.style.fg, cell.style.gutter), ("#008000", True))
            self.assertEqual(line_width(row), len(RAIL) + len(OUTPUT_INDENT) + len(OUTPUT_MARK) + 2)  # the lead, then two cells

    def test_a_narrow_terminal_cuts_the_rows_without_error(self) -> None:
        block = UserBlock("x", images=("[Image #1]",), previews=(unicode_preview(),))
        for theme in (DEFAULT_THEME, BANDED):
            for width in (20, 8, 1):
                rows = block_rows(block, width, theme)
                self.assertEqual(len(rows), 4)
                self.assertTrue(all(line_width(row) <= width for row in rows), (width, lines_text(rows)))

    def test_the_transcript_passes_previews_to_its_block(self) -> None:
        transcript = Transcript()
        preview = unicode_preview()
        transcript.add_user("hi", images=("[Image #1]",), previews=(preview,))
        block = transcript.blocks[-1]
        self.assertIsInstance(block, UserBlock)
        self.assertEqual(block.previews, (preview,))


if __name__ == "__main__":
    unittest.main()
