"""Hermes' `image.render` answer becomes preview rows only when every part of it is in the shape Hermes writes.

The kitty `transmit` is the one escape sequence the TUI passes through on
Hermes' word, so each way it could carry something else (another escape around
or between its chunks, a second control, a delete, a different image or size,
an oversized chunk or whole) gives no preview at all.
"""

from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

from omh.tui import inline_image
from omh.tui.inline_image import (
    LOWER_HALF,
    MODE_KITTY,
    MODE_UNICODE,
    PLACEHOLDER,
    PREVIEW_MAX_COLS,
    PREVIEW_MAX_ROWS,
    UPPER_HALF,
    Preview,
    preview_from,
)
from omh.tui.style import Style
from omh.tui.width import line_width

# kitty's row/column diacritics in order (its `rowcolumn-diacritics`), as Hermes' `_ROWCOL_DIACRITICS` starts.
DIACRITICS = tuple(map(chr, (0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F,
                             0x0346, 0x034A, 0x034B, 0x034C, 0x0350, 0x0351, 0x0352, 0x0357)))
IMAGE_ID = 0x9A2B3C  # Hermes' image ids lie in [0x8000, 0xFFFFFF] (agent/terminal_image.py `_IMAGE_ID_BASE`)
COLOR = "#%06x" % (IMAGE_ID & 0xFFFFFF)
OSC_52 = "\x1b]52;c;aGVsbG8=\x07"


def chunk(payload: str, more: bool, control: str = "") -> str:
    """One kitty APC chunk as Hermes' `_kitty_apc` writes it."""
    return f"\x1b_G{control + ',' if control else ''}m={1 if more else 0};{payload}\x1b\\"


def control(image_id: int = IMAGE_ID, cols: int = 3, rows: int = 2) -> str:
    return f"a=T,U=1,i={image_id},c={cols},r={rows},f=100,q=2"


def chunks(image_id: int = IMAGE_ID, cols: int = 3, rows: int = 2) -> list[str]:
    """A transmit in three chunks, so a first (with the control), a middle and a last are all exercised; as Hermes'
    `_kitty_apc` cuts them, every payload but the last is 4096 characters."""
    data = base64.standard_b64encode(bytes(range(256)) * 24).decode("ascii")  # 8192 characters
    parts = [data[:4096], data[4096:], data[:12]]
    return [
        chunk(part, more=index < len(parts) - 1, control=control(image_id, cols, rows) if index == 0 else "")
        for index, part in enumerate(parts)
    ]


def placeholder_rows(cols: int = 3, rows: int = 2) -> list[str]:
    return [PLACEHOLDER + DIACRITICS[row] + PLACEHOLDER * (cols - 1) for row in range(rows)]


def kitty_result(**changes: object) -> dict:
    result = {
        "mode": "kitty", "cols": 3, "rows": 2, "color": COLOR, "transmit": "".join(chunks()),
        "placeholder": placeholder_rows(),
    }
    result.update(changes)
    return result


OPAQUE_RED, OPAQUE_BLUE, CLEAR = [255, 0, 0, 255], [0, 0, 255, 200], [9, 9, 9, 31]


def unicode_cells() -> list[list[list[int]]]:
    """A 2-row by 3-column grid: both halves, top only, bottom only; then clear, both, a threshold alpha of 32."""
    return [
        [OPAQUE_RED + OPAQUE_BLUE, OPAQUE_RED + CLEAR, CLEAR + OPAQUE_BLUE],
        [CLEAR + CLEAR, [16, 32, 48, 32] + [171, 205, 239, 255], [1, 2, 3, 0] + [10, 11, 12, 32]],
    ]


def unicode_result(**changes: object) -> dict:
    result = {"mode": "unicode", "cols": 3, "rows": 2, "cells": unicode_cells()}
    result.update(changes)
    return result


class UnicodePreviewTests(unittest.TestCase):
    def test_each_cell_is_painted_as_hermes_own_tui_paints_it(self) -> None:
        preview = preview_from(unicode_result())
        self.assertIsInstance(preview, Preview)
        self.assertEqual((preview.mode, preview.cols, preview.rows), (MODE_UNICODE, 3, 2))
        self.assertEqual((preview.transmit, preview.image_id), ("", 0))
        drawn = [[(span.text, span.style) for span in line] for line in preview.lines]
        self.assertEqual(drawn, [
            [
                (UPPER_HALF, Style(fg="#ff0000", bg="#0000ff", gutter=True)),
                (UPPER_HALF, Style(fg="#ff0000", gutter=True)),
                (LOWER_HALF, Style(fg="#0000ff", gutter=True)),
            ],
            [
                (" ", Style(gutter=True)),
                (UPPER_HALF, Style(fg="#102030", bg="#abcdef", gutter=True)),
                (LOWER_HALF, Style(fg="#0a0b0c", gutter=True)),
            ],
        ])

    def test_every_row_is_exactly_cols_cells_wide(self) -> None:
        preview = preview_from(unicode_result())
        self.assertEqual([line_width(line) for line in preview.lines], [3, 3])

    def test_the_largest_grid_hermes_sends_is_drawn(self) -> None:
        cells = [[OPAQUE_RED + OPAQUE_BLUE] * PREVIEW_MAX_COLS for _ in range(PREVIEW_MAX_ROWS)]
        preview = preview_from(unicode_result(cols=PREVIEW_MAX_COLS, rows=PREVIEW_MAX_ROWS, cells=cells))
        self.assertEqual(len(preview.lines), PREVIEW_MAX_ROWS)
        self.assertEqual({line_width(line) for line in preview.lines}, {PREVIEW_MAX_COLS})

    def test_a_ragged_grid_draws_nothing(self) -> None:
        cells = unicode_cells()
        for name, broken in (
            ("short row", [cells[0], cells[1][:2]]),
            ("long row", [cells[0], [*cells[1], cells[1][0]]]),
            ("missing row", [cells[0]]),
            ("extra row", [*cells, cells[0]]),
            ("short cell", [cells[0], [cells[1][0][:7], *cells[1][1:]]]),
            ("long cell", [cells[0], [[*cells[1][0], 0], *cells[1][1:]]]),
            ("tuple row", [cells[0], tuple(cells[1])]),
            ("not a list", "cells"),
            ("absent", None),
        ):
            with self.subTest(name):
                self.assertIsNone(preview_from(unicode_result(cells=broken)))

    def test_cells_that_look_the_same_share_one_span(self) -> None:
        cells = [[OPAQUE_RED + OPAQUE_BLUE] * PREVIEW_MAX_COLS for _ in range(PREVIEW_MAX_ROWS)]
        preview = preview_from(unicode_result(cols=PREVIEW_MAX_COLS, rows=PREVIEW_MAX_ROWS, cells=cells))
        self.assertEqual(len({id(span.style) for line in preview.lines for span in line}), 1)

    def test_a_value_out_of_a_byte_draws_nothing(self) -> None:
        for value in (256, -1, True, False, 1.0, "1", None):
            with self.subTest(value=value):
                cells = unicode_cells()
                cells[1][2][5] = value
                self.assertIsNone(preview_from(unicode_result(cells=cells)))


class KittyPreviewTests(unittest.TestCase):
    def test_a_valid_answer_keeps_its_transmit_byte_for_byte(self) -> None:
        result = kitty_result()
        preview = preview_from(result)
        self.assertIsInstance(preview, Preview)
        self.assertEqual((preview.mode, preview.cols, preview.rows), (MODE_KITTY, 3, 2))
        self.assertEqual(preview.transmit, result["transmit"])
        self.assertEqual(preview.image_id, IMAGE_ID)
        self.assertEqual(
            preview.lines,
            tuple((inline_image.Span(row, Style(fg=COLOR, gutter=True)),) for row in placeholder_rows()),
        )

    def test_every_placeholder_row_is_exactly_cols_cells_wide(self) -> None:
        for cols, rows in ((3, 2), (1, 1), (PREVIEW_MAX_COLS, 4)):
            with self.subTest(cols=cols, rows=rows):
                preview = preview_from(kitty_result(
                    cols=cols, rows=rows, transmit="".join(chunks(cols=cols, rows=rows)),
                    placeholder=placeholder_rows(cols, rows),
                ))
                self.assertEqual([line_width(line) for line in preview.lines], [cols] * rows)

    def test_a_single_chunk_transmit_is_one_last_chunk_with_the_control(self) -> None:
        transmit = chunk("AAAA", more=False, control=control())
        self.assertEqual(preview_from(kitty_result(transmit=transmit)).transmit, transmit)

    def test_an_upper_case_colour_is_kept_lower_case(self) -> None:
        preview = preview_from(kitty_result(color=COLOR.upper()))
        self.assertEqual({line[0].style.fg for line in preview.lines}, {COLOR})

    def test_only_the_low_24_bits_of_the_id_meet_the_colour(self) -> None:
        image_id = IMAGE_ID + 0x01000000  # still eight digits
        preview = preview_from(kitty_result(transmit="".join(chunks(image_id=image_id))))
        self.assertEqual(preview.image_id, image_id)

    def test_a_payload_of_4096_characters_is_still_one_chunk(self) -> None:
        transmit = chunk("A" * 4096, more=True, control=control()) + chunk("A" * 4096, more=False)
        self.assertIsNotNone(preview_from(kitty_result(transmit=transmit)))

    def test_a_colour_that_is_not_hex_draws_nothing(self) -> None:
        for color in ("red", "#12345", "#1234567", "1a2b3c4", "#gggggg", COLOR + "\n", None, 0x2B3C4D):
            with self.subTest(color=color):
                self.assertIsNone(preview_from(kitty_result(color=color)))

    def test_a_placeholder_out_of_shape_draws_nothing(self) -> None:
        rows = placeholder_rows()
        for name, broken in (
            ("row too short", [rows[0], rows[1][:-1]]),
            ("row too long", [rows[0], rows[1] + PLACEHOLDER]),
            ("missing row", rows[:1]),
            ("extra row", [*rows, PLACEHOLDER + DIACRITICS[2] + PLACEHOLDER * 2]),
            ("diacritic not Mn", [rows[0], PLACEHOLDER + "x" + PLACEHOLDER * 2]),
            ("diacritic Me", [rows[0], PLACEHOLDER + "\u20dd" + PLACEHOLDER * 2]),
            ("diacritic is an escape", [rows[0], PLACEHOLDER + "\x1b" + PLACEHOLDER * 2]),
            ("repeated diacritic", [rows[0], rows[0]]),
            ("rows swapped", [rows[1], rows[0]]),
            ("an Mn mark kitty does not number rows with", [rows[0], PLACEHOLDER + "\u0300" + PLACEHOLDER * 2]),
            ("a later row's diacritic", [rows[0], PLACEHOLDER + DIACRITICS[2] + PLACEHOLDER * 2]),
            ("other cell character", [rows[0], PLACEHOLDER + DIACRITICS[1] + PLACEHOLDER + "x"]),
            ("does not start with a placeholder", [rows[0], "x" + rows[1][1:]]),
            ("not a string", [rows[0], 7]),
            ("not a list", "".join(rows)),
        ):
            with self.subTest(name):
                self.assertIsNone(preview_from(kitty_result(placeholder=broken)))


class TransmitTests(unittest.TestCase):
    """Each way a transmit could be something other than the one command Hermes writes gives no preview."""

    def assert_refused(self, transmit: object) -> None:
        self.assertIsNone(preview_from(kitty_result(transmit=transmit)))

    def test_another_escape_around_or_between_the_chunks_is_refused(self) -> None:
        first, middle, last = chunks()
        for name, transmit in (
            ("prepended", OSC_52 + first + middle + last),
            ("appended", first + middle + last + OSC_52),
            ("between chunks", first + OSC_52 + middle + last),
            ("inside a payload", first + chunk("AAAA" + OSC_52, more=True) + last),
            ("text between chunks", first + "x" + middle + last),
            ("newline at the end", first + middle + last + "\n"),
            ("a chunk after the last", first + middle + last + chunk("AAAA", more=False)),
        ):
            with self.subTest(name):
                self.assert_refused(transmit)

    def test_the_control_on_a_second_chunk_is_refused(self) -> None:
        first, _middle, last = chunks()
        self.assert_refused(first + chunk("AAAA", more=True, control=control()) + last)

    def test_a_first_chunk_without_the_control_is_refused(self) -> None:
        _first, middle, last = chunks()
        self.assert_refused(chunk("A" * 4096, more=True) + middle + last)

    def test_a_last_chunk_that_says_more_follows_is_refused(self) -> None:
        first, middle, _last = chunks()
        self.assert_refused(first + middle + chunk("A" * 4096, more=True))

    def test_a_middle_chunk_that_says_it_is_the_last_is_refused(self) -> None:
        first, _middle, last = chunks()
        self.assert_refused(first + chunk("AAAA", more=False) + last)

    def test_another_kitty_command_is_refused(self) -> None:
        for name, command in (
            ("delete", "a=d,d=A"),
            ("delete with the rest", "a=d,U=1,i=%d,c=3,r=2,f=100,q=2" % IMAGE_ID),
            ("missing q=2", "a=T,U=1,i=%d,c=3,r=2,f=100" % IMAGE_ID),
            ("q=1", "a=T,U=1,i=%d,c=3,r=2,f=100,q=1" % IMAGE_ID),
            ("not virtual", "a=T,i=%d,c=3,r=2,f=100,q=2" % IMAGE_ID),
            ("raw pixels", "a=T,U=1,i=%d,c=3,r=2,f=32,q=2" % IMAGE_ID),
            ("extra key", "a=T,U=1,i=%d,c=3,r=2,f=100,q=2,t=f" % IMAGE_ID),
            ("id too long", "a=T,U=1,i=123456789,c=3,r=2,f=100,q=2"),
            ("non-ASCII digit", "a=T,U=1,i=\u0661,c=3,r=2,f=100,q=2"),
        ):
            with self.subTest(name):
                self.assert_refused(chunk("AAAA", more=False, control=command))

    def test_a_payload_outside_base64_is_refused(self) -> None:
        for payload in ("AA AA", "AA\x1bAA", "AA-_", "AA\u00e9"):
            with self.subTest(payload=payload):
                self.assert_refused(chunk(payload, more=False, control=control()))

    def test_an_id_that_is_not_the_colour_is_refused(self) -> None:
        self.assert_refused("".join(chunks(image_id=IMAGE_ID + 1)))

    def test_a_size_that_is_not_the_answer_is_refused(self) -> None:
        for cols, rows in ((4, 2), (3, 1), (30, 2)):
            with self.subTest(cols=cols, rows=rows):
                self.assert_refused("".join(chunks(cols=cols, rows=rows)))

    def test_a_payload_chunk_over_4096_characters_is_refused(self) -> None:
        self.assert_refused(chunk("A" * 4097, more=True, control=control()) + chunk("AAAA", more=False))
        self.assert_refused(chunk("A" * 4096, more=True, control=control()) + chunk("A" * 4097, more=False))

    def test_a_transmit_over_the_limit_is_refused(self) -> None:
        transmit = "".join(chunks())
        with patch.object(inline_image, "TRANSMIT_MAX_CHARS", len(transmit)):
            self.assertIsNotNone(preview_from(kitty_result(transmit=transmit)))
        with patch.object(inline_image, "TRANSMIT_MAX_CHARS", len(transmit) - 1):
            self.assert_refused(transmit)

    def test_an_empty_payload_chunk_is_refused(self) -> None:
        first, middle, last = chunks()
        self.assert_refused(first + chunk("", more=True) + middle + last)
        self.assert_refused(first + middle + chunk("", more=False))
        self.assert_refused(chunk("", more=False, control=control()))

    def test_a_short_chunk_before_the_last_is_refused(self) -> None:
        first, middle, last = chunks()
        self.assert_refused(first + chunk("A" * 4092, more=True) + last)
        self.assert_refused(chunk("AAAA", more=True, control=control()) + middle + last)

    def test_a_transmit_over_two_mib_is_refused(self) -> None:
        self.assertEqual(inline_image.TRANSMIT_MAX_CHARS, 2 * 1024 * 1024)
        first = chunk("A" * 4096, more=True, control=control())
        middle = chunk("A" * 4096, more=True)
        count = inline_image.TRANSMIT_MAX_CHARS // len(middle) + 1
        self.assert_refused(first + middle * count + chunk("AAAA", more=False))

    def test_hermes_largest_shape_is_accepted(self) -> None:
        """A 64x16 transmit near the size Hermes' largest measured one has (about 922 KB), cut as `_kitty_apc` cuts."""
        data = "A" * (900 * 1024 + 7)
        pieces = [data[start : start + 4096] for start in range(0, len(data), 4096)]
        transmit = "".join(chunk(piece, more=index < len(pieces) - 1,
                                 control=control(cols=PREVIEW_MAX_COLS, rows=PREVIEW_MAX_ROWS) if index == 0 else "")
                           for index, piece in enumerate(pieces))
        result = kitty_result(cols=PREVIEW_MAX_COLS, rows=PREVIEW_MAX_ROWS, transmit=transmit,
                              placeholder=placeholder_rows(PREVIEW_MAX_COLS, PREVIEW_MAX_ROWS))
        self.assertEqual(preview_from(result).transmit, transmit)

    def test_a_transmit_that_is_not_a_string_is_refused(self) -> None:
        for transmit in ("", None, b"".join(part.encode() for part in chunks()), ["".join(chunks())]):
            with self.subTest(transmit=type(transmit).__name__):
                self.assert_refused(transmit)


class AnswerShapeTests(unittest.TestCase):
    def test_off_or_an_unknown_mode_draws_nothing(self) -> None:
        for result in ({"mode": "off"}, {}, unicode_result(mode="sixel"), unicode_result(mode=None)):
            with self.subTest(result=result.get("mode")):
                self.assertIsNone(preview_from(result))

    def test_an_answer_that_is_not_a_mapping_draws_nothing(self) -> None:
        for result in (None, [], "kitty", [("mode", "unicode")]):
            with self.subTest(result=result):
                self.assertIsNone(preview_from(result))

    def test_a_size_out_of_bounds_draws_nothing(self) -> None:
        for name, value in (("zero", 0), ("over the cap", None), ("bool", True), ("float", 3.0), ("text", "3"),
                            ("negative", -3)):
            with self.subTest(name):
                cols = PREVIEW_MAX_COLS + 1 if value is None else value
                self.assertIsNone(preview_from(unicode_result(cols=cols)))
                self.assertIsNone(preview_from(kitty_result(cols=cols)))
        for rows in (0, PREVIEW_MAX_ROWS + 1, True):
            with self.subTest(rows=rows):
                self.assertIsNone(preview_from(unicode_result(rows=rows)))
                self.assertIsNone(preview_from(kitty_result(rows=rows)))

    def test_cols_of_65_draws_nothing_even_with_cells_to_match(self) -> None:
        cells = [[OPAQUE_RED + OPAQUE_BLUE] * 65 for _ in range(2)]
        self.assertIsNone(preview_from(unicode_result(cols=65, cells=cells)))


if __name__ == "__main__":
    unittest.main()
