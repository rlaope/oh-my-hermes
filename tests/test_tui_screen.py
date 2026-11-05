"""The OMH TUI's live region (`omh.tui.screen`) driven into a VT screen model.

The region repaints with relative motion only, so these tests start it at the
bottom of a screen that already holds shell history, the way a real launch
does, and read back what a terminal would show: the region's rows, the
scrollback above, and where the hardware cursor ended up. The model raises on
any write past the right margin, so every frame here also proves the
clipping. The model's own behaviour is pinned at the end of the file.
"""

from __future__ import annotations

import random
import re
import unittest
from unittest.mock import patch

from _vt_screen import VTOverflow, VTScreen

from omh.tui import screen as screen_module
from omh.tui.screen import LiveRegion, paint_line
from omh.tui.style import SGR_RESET, Line, Span, Style, fill

_CSI = re.compile(r"\x1b\[([0-?]*)[ -/]*([@-~])")
RED_BOLD = Style(fg="#ff0000", bold=True)
RED_BOLD_SGR = (1, 38, 2, 255, 0, 0)
FAMILY = "\U0001F468‍\U0001F469‍\U0001F467‍\U0001F466"


def plain(*texts: str) -> list[Line]:
    return [(Span(text),) for text in texts]


def printable(written: str) -> str:
    """The text a write paints, with every control sequence and CR/LF removed."""
    return _CSI.sub("", written).replace("\r", "").replace("\n", "")


class Harness:
    def __init__(self, rows: int = 10, cols: int = 20, history: int = 0, at_top: bool = False) -> None:
        self.screen = VTScreen(rows, cols)
        self.cols = cols
        self.writes: list[str] = []
        for index in range(history):
            self.screen.feed(f"history {index}\r\n")
        self.region = LiveRegion(self._write, at_top=at_top)

    def _write(self, text: str) -> None:
        self.writes.append(text)
        self.screen.feed(text)

    def render(
        self, lines: list[Line], cursor: tuple[int, int] | None = (0, 0), width: int | None = None,
        screen_rows: int | None = None,
    ) -> None:
        self.region.render(lines, cursor, self.cols if width is None else width, screen_rows=screen_rows)

    def flush(self, lines: list[Line], width: int | None = None) -> None:
        self.region.flush_above(lines, self.cols if width is None else width)


class SynchronizedOutputTests(unittest.TestCase):
    """Every frame that paints rows is one synchronized update (DECSET 2026), so a terminal shows it whole."""

    def test_every_painting_frame_is_wrapped_and_a_cursor_only_move_is_not(self) -> None:
        from omh.tui.screen import SYNC_BEGIN, SYNC_END

        harness = Harness(history=3)
        harness.render(plain("one", "two"), cursor=(1, 0))
        harness.render(plain("one", "TWO"), cursor=(1, 0))
        harness.flush(plain("flushed"))
        harness.render(plain("one", "TWO"), cursor=(0, 2))  # nothing changed but the caret
        painting, parking = harness.writes[:3], harness.writes[3]
        for frame in painting:
            with self.subTest(frame=frame):
                self.assertTrue(frame.startswith(SYNC_BEGIN) and frame.endswith(SYNC_END), repr(frame))
                self.assertEqual((frame.count(SYNC_BEGIN), frame.count(SYNC_END)), (1, 1))
        self.assertNotIn(SYNC_BEGIN, parking)
        self.assertEqual(SYNC_BEGIN, "\x1b[?2026h")
        self.assertEqual(SYNC_END, "\x1b[?2026l")

    def test_a_flush_and_the_frame_under_it_are_one_write(self) -> None:
        from omh.tui.screen import SYNC_BEGIN, SYNC_END

        harness = Harness(history=9)
        harness.render(plain("f1", "f2", "one", "two"), cursor=(3, 0))
        written = len(harness.writes)
        harness.region.render(plain("one", "TWO"), (1, 0), harness.cols, flush=plain("f1", "f2", "f3"))
        (frame,) = harness.writes[written:]
        self.assertTrue(frame.startswith(SYNC_BEGIN) and frame.endswith(SYNC_END), repr(frame))
        self.assertEqual((frame.count(SYNC_BEGIN), frame.count(SYNC_END)), (1, 1))
        history = [f"history {index}" for index in range(9)]
        self.assertEqual(harness.screen.history(), history + ["f1", "f2", "f3", "one", "TWO"])
        self.assertEqual(harness.screen.cursor, (9, 0))
        self.assertEqual(harness.region.height, 2)

    def test_a_lead_goes_out_once_inside_the_first_frames_update(self) -> None:
        # A full redraw's erase: written alone, the terminal would show the blank screen until the frame came.
        from omh.tui.screen import CLEAR_SCREEN_AND_SCROLLBACK, SYNC_BEGIN, SYNC_END

        harness = Harness(history=3)
        harness.region = LiveRegion(harness._write, at_top=True, lead=CLEAR_SCREEN_AND_SCROLLBACK)
        self.assertEqual(harness.writes, [])  # nothing until the frame
        harness.render(plain("one", "two"), cursor=(1, 0))
        harness.render(plain("one", "TWO"), cursor=(1, 0))
        first, second = harness.writes
        self.assertTrue(first.startswith(SYNC_BEGIN + CLEAR_SCREEN_AND_SCROLLBACK) and first.endswith(SYNC_END))
        self.assertNotIn(CLEAR_SCREEN_AND_SCROLLBACK, second)
        self.assertEqual(harness.screen.lines()[:2], ["one", "TWO"])
        self.assertEqual(harness.screen.scrollback, [])

    def test_a_region_cleared_before_its_first_frame_still_writes_its_lead(self) -> None:
        # An exit right after a full redraw, before its frame: the erase the redraw asked for still goes out, once.
        from omh.tui.screen import CLEAR_SCREEN_AND_SCROLLBACK

        harness = Harness(history=3)
        harness.region = LiveRegion(harness._write, at_top=True, lead=CLEAR_SCREEN_AND_SCROLLBACK)
        harness.region.clear()
        harness.region.clear()
        self.assertEqual(harness.writes, [CLEAR_SCREEN_AND_SCROLLBACK])
        self.assertEqual(harness.screen.scrollback, [])

    def test_a_pager_frame_is_wrapped_too(self) -> None:
        from omh.tui.pager import Pager
        from omh.tui.screen import SYNC_BEGIN, SYNC_END
        from omh.tui.theme import DEFAULT_THEME

        pager = Pager("t", plain("a", "b"))
        frame = pager.frame(20, 5, DEFAULT_THEME)
        self.assertTrue(frame.startswith(SYNC_BEGIN) and frame.endswith(SYNC_END))
        self.assertEqual(pager.frame(20, 5, DEFAULT_THEME), "")  # nothing changed: nothing written


class FirstFrameTests(unittest.TestCase):
    def test_first_frame_paints_from_the_cursor_row(self) -> None:
        harness = Harness()
        harness.render(plain("one", "two", "three"), cursor=(2, 1))
        self.assertEqual(harness.screen.lines()[:4], ["one", "two", "three", ""])
        self.assertEqual(harness.screen.cursor, (2, 1))
        self.assertTrue(harness.screen.cursor_visible)
        self.assertTrue(harness.screen.autowrap)

    def test_first_frame_at_the_bottom_scrolls_history_up(self) -> None:
        harness = Harness(rows=10, history=9)  # the shell left the cursor on the last row
        harness.render(plain("one", "two", "three"), cursor=(2, 0))
        self.assertEqual(harness.screen.scrollback, ["history 0", "history 1"])
        self.assertEqual(harness.screen.lines()[-4:], ["history 8", "one", "two", "three"])
        self.assertEqual(harness.screen.cursor, (9, 0))

    def test_an_empty_first_frame_writes_nothing(self) -> None:
        harness = Harness()
        harness.render([])
        self.assertEqual(harness.writes, [])


class RepaintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Harness(rows=10, history=9)
        self.harness.render(plain("alpha", "beta", "gamma"), cursor=(2, 0))

    def test_an_unchanged_frame_writes_nothing(self) -> None:
        before = len(self.harness.writes)
        self.harness.render(plain("alpha", "beta", "gamma"), cursor=(2, 0))
        self.assertEqual(len(self.harness.writes), before)

    def test_only_the_changed_row_is_repainted(self) -> None:
        self.harness.render(plain("alpha", "BETA", "gamma"), cursor=(2, 0))
        self.assertEqual(printable(self.harness.writes[-1]), "BETA")
        self.assertEqual(self.harness.screen.lines()[-3:], ["alpha", "BETA", "gamma"])

    def test_a_shorter_row_leaves_no_tail_behind(self) -> None:
        self.harness.render(plain("alpha", "b", "gamma"), cursor=(2, 0))
        self.assertEqual(self.harness.screen.lines()[-3:], ["alpha", "b", "gamma"])

    def test_cursor_is_parked_where_asked(self) -> None:
        self.harness.render(plain("alpha", "BETA", "gamma"), cursor=(1, 4))
        self.assertEqual(self.harness.screen.cursor, (8, 4))

    def test_moving_only_the_cursor_paints_no_text(self) -> None:
        self.harness.render(plain("alpha", "beta", "gamma"), cursor=(0, 3))
        self.assertEqual(printable(self.harness.writes[-1]), "")
        self.assertEqual(self.harness.screen.cursor, (7, 3))

    def test_cursor_is_clamped_into_the_region(self) -> None:
        self.harness.render(plain("alpha", "beta", "gamma"), cursor=(10, 99))
        self.assertEqual(self.harness.screen.cursor, (9, 19))

    def test_a_width_change_repaints_every_row(self) -> None:
        self.harness.render(plain("alpha", "beta", "gamma"), cursor=(2, 0), width=12)
        self.assertEqual(printable(self.harness.writes[-1]), "alphabetagamma")

    def test_only_relative_motion_is_used(self) -> None:
        self.harness.render(plain("alpha", "beta", "gamma", "delta"), cursor=(1, 2))
        self.harness.flush(plain("done"))
        self.harness.render(plain("x"))
        self.harness.region.clear()
        finals = {final for text in self.harness.writes for _, final in _CSI.findall(text)}
        self.assertLessEqual(finals, {"A", "B", "C", "K", "J", "m", "h", "l"})


class HiddenCaretTests(unittest.TestCase):
    """A frame with no caret (`cursor=None`: the composer is hidden) leaves the hardware cursor hidden."""

    def setUp(self) -> None:
        self.harness = Harness(rows=10, history=9)
        self.harness.render(plain("alpha", "beta", "gamma"), cursor=(2, 1))

    def test_a_frame_with_no_caret_leaves_the_cursor_hidden(self) -> None:
        from omh.tui.screen import SHOW_CURSOR

        self.harness.render(plain("alpha", "BETA", "gamma"), cursor=None)
        self.assertFalse(self.harness.screen.cursor_visible)
        self.assertNotIn(SHOW_CURSOR, self.harness.writes[-1])
        self.assertTrue(self.harness.region.caret_hidden)
        self.assertEqual(self.harness.screen.lines()[-3:], ["alpha", "BETA", "gamma"])

    def test_hiding_or_showing_the_caret_alone_is_written_and_an_unchanged_frame_is_not(self) -> None:
        self.harness.render(plain("alpha", "beta", "gamma"), cursor=None)  # only the caret changed
        self.assertFalse(self.harness.screen.cursor_visible)
        before = len(self.harness.writes)
        self.harness.render(plain("alpha", "beta", "gamma"), cursor=None)
        self.assertEqual(len(self.harness.writes), before)
        self.harness.render(plain("alpha", "beta", "gamma"), cursor=(2, 1))
        self.assertTrue(self.harness.screen.cursor_visible)
        self.assertEqual(self.harness.screen.cursor, (9, 1))
        self.assertFalse(self.harness.region.caret_hidden)

    def test_hiding_or_showing_the_caret_where_it_is_parked_is_still_written(self) -> None:
        # A hidden caret parks at the start of the last row: from a caret already there, only its visibility changes.
        self.harness.render(plain("alpha", "beta", "gamma"), cursor=(2, 0))
        self.harness.render(plain("alpha", "beta", "gamma"), cursor=None)
        self.assertFalse(self.harness.screen.cursor_visible)
        self.harness.render(plain("alpha", "beta", "gamma"), cursor=(2, 0))
        self.assertTrue(self.harness.screen.cursor_visible)

    def test_a_flush_keeps_the_caret_hidden_and_the_next_caret_shows_it(self) -> None:
        self.harness.render(plain("alpha", "beta"), cursor=None)
        self.harness.flush(plain("done one", "done two"))
        self.assertFalse(self.harness.screen.cursor_visible)
        self.assertEqual(self.harness.screen.lines()[-4:], ["done one", "done two", "alpha", "beta"])
        self.harness.render(plain("alpha", "beta"), cursor=(1, 2))
        self.assertTrue(self.harness.screen.cursor_visible)
        self.assertEqual(self.harness.screen.cursor, (9, 2))


class PaintReuseTests(unittest.TestCase):
    """A row whose line and width are what the last frame painted keeps its bytes: nothing paints it again."""

    def test_unchanged_lines_are_not_painted_again(self) -> None:
        harness = Harness(rows=10, history=9)
        harness.render(plain("alpha", "beta", "gamma"), cursor=(2, 0))
        painted: list[Line] = []

        def counting(line: Line, width: int, ground: str | None = None) -> str:
            painted.append(line)
            return paint_line(line, width, ground)

        with patch("omh.tui.screen.paint_line", counting):
            harness.render(plain("alpha", "BETA", "gamma"), cursor=(2, 0))
            self.assertEqual(painted, plain("BETA"))
            harness.render(plain("alpha", "BETA", "gamma", "delta"), cursor=(3, 0))  # a row added at the end
            self.assertEqual(painted, plain("BETA", "delta"))
            harness.render(plain("alpha", "BETA", "gamma", "delta"), cursor=(3, 0), width=12)
            self.assertEqual(painted[2:], plain("alpha", "BETA", "gamma", "delta"))
        self.assertEqual(harness.screen.lines()[-4:], ["alpha", "BETA", "gamma", "delta"])

    def test_after_a_flush_the_rows_its_lines_did_not_cover_are_kept_not_painted_again(self) -> None:
        harness = Harness(rows=10, history=9)
        harness.render(plain("tail 1", "tail 2", "alpha", "beta"), cursor=(3, 0))
        screen_module._flushed_row.cache_clear()  # a row another test flushed at this width is kept already
        painted: list[Line] = []

        def counting(line: Line, width: int, ground: str | None = None) -> str:
            painted.append(line)
            return paint_line(line, width, ground)

        with patch("omh.tui.screen.paint_line", counting):
            harness.region.render(plain("alpha", "beta", "gamma"), (2, 0), harness.cols, flush=plain("tail 1", "tail 2"))
        self.assertEqual(painted, plain("tail 1", "tail 2", "gamma"))  # the flushed lines and the new row
        self.assertEqual(harness.screen.lines()[-5:], ["tail 1", "tail 2", "alpha", "beta", "gamma"])

    def test_after_a_flush_longer_than_the_region_every_row_is_painted_again(self) -> None:
        harness = Harness(rows=10, history=9)
        harness.render(plain("alpha", "beta"), cursor=(1, 0))
        harness.flush(plain("done one", "done two", "done three"))
        harness.render(plain("alpha", "beta"), cursor=(1, 0))
        self.assertEqual(harness.screen.lines()[-5:], ["done one", "done two", "done three", "alpha", "beta"])


class FlushedRowKeptTests(unittest.TestCase):
    """A row flushed again (a full redraw prints the rows flushed last) is not painted again: its kept bytes are the
    bytes painting it writes, by width."""

    BAND = Style(fg="#c0c0c0", bg="#202040")
    ROWS: list[Line] = [
        (Span("┃ ", Style(fg="#ff8800", gutter=True)), Span("한국어 문장 ✅ and "), Span("bold", Style(bold=True))),
        (Span("❯ a prompt on its band", BAND), fill(BAND)),
        (),
        (Span("x" * 30),),  # wider than the screen: clipped
    ]

    def flushed(self, cols: int) -> tuple[str, list[int | None], int]:
        """The bytes written and wallpaper starts of `ROWS` flushed by a new region, and how many rows were painted."""
        harness = Harness(rows=10, cols=cols)
        harness.region = LiveRegion(harness._write)
        harness.region.render(plain("live"), (0, 0), cols)
        painted: list[Line] = []

        def counting(line: Line, width: int, ground: str | None = None) -> str:
            painted.append(line)
            return paint_line(line, width, ground)

        harness.writes.clear()
        with patch("omh.tui.screen.paint_line", counting):
            harness.region.render(plain("live"), (0, 0), cols, flush=self.ROWS)
        flushed = [row for row in painted if row in self.ROWS]
        return "".join(harness.writes), list(harness.region._above_blank), len(flushed)

    def test_a_row_flushed_again_writes_what_painting_it_writes(self) -> None:
        for cols in (20, 14):
            with self.subTest(cols=cols):
                screen_module._flushed_row.cache_clear()
                first, first_blank, painted = self.flushed(cols)
                self.assertEqual(painted, len(self.ROWS))
                again, again_blank, painted = self.flushed(cols)
                self.assertEqual(painted, 0)  # every row's bytes were kept
                self.assertEqual((again, again_blank), (first, first_blank))
                for row in self.ROWS:
                    self.assertIn(paint_line(row, cols), first)
                self.assertEqual(first_blank, [screen_module._blank_from(row, cols) for row in self.ROWS])

    def test_another_width_paints_the_row_again(self) -> None:
        screen_module._flushed_row.cache_clear()
        at_20, _blank, _painted = self.flushed(20)
        at_14, _blank, painted = self.flushed(14)
        self.assertEqual(painted, len(self.ROWS))
        self.assertNotEqual(at_14, at_20)


GROUND = "#211538"
OTHER_GROUND = "#072E2C"


def background_at(screen: VTScreen, row: int, col: int) -> str | None:
    """The explicit background (SGR 48;2) a cell was written or erased with, None for the terminal's default."""
    params, colour, at = screen.attrs_at(row, col), None, 0
    while at < len(params):
        if params[at] in (38, 48) and params[at + 1:at + 2] == (2,):
            colour = "#%02X%02X%02X" % params[at + 2:at + 5] if params[at] == 48 else colour
            at += 5
            continue
        colour = None if params[at] in (0, 49) else colour
        at += 1
    return colour


def blank_backgrounds(screen: VTScreen, rows: range) -> set[str | None]:
    """The backgrounds of every blank cell on `rows`."""
    return {background_at(screen, row, col) for row in rows for col in range(screen.cols)
            if not screen.line(row)[col:col + 1].strip()}


def background_of(params: tuple[int, ...]) -> str | None:
    """`background_at` for a cell's SGR parameters."""
    colour, at = None, 0
    while at < len(params):
        if params[at] in (38, 48) and params[at + 1:at + 2] == (2,):
            colour = "#%02X%02X%02X" % params[at + 2:at + 5] if params[at] == 48 else colour
            at += 5
            continue
        colour = None if params[at] in (0, 49) else colour
        at += 1
    return colour


def autowrap_at_erases(written: str) -> set[bool]:
    """Whether autowrap was on at each erase-below and erase-line in `written`, read in order."""
    states, on = set(), True
    for match in re.finditer(r"\x1b\[\?7([hl])|\x1b\[2?[JK]", written):
        if match.group(1):
            on = match.group(1) == "h"
        else:
            states.add(on)
    return states


class ScrolledAttrs(VTScreen):
    """The VT screen keeping the attributes of every row it scrolls into the scrollback."""

    def __init__(self, rows: int, cols: int) -> None:
        super().__init__(rows, cols)
        self.scrolled_attrs: list[list[tuple[int, ...]]] = []

    def _line_feed(self) -> None:
        if self._row >= self.rows - 1:
            self.scrolled_attrs.append(list(self._attrs[0]))
        super()._line_feed()


class GroundTests(unittest.TestCase):
    """A region given a look's ground (`screen.on_ground`) erases on it, so a terminal that clears a cell with its own
    colour whatever OSC 11 set (Otty) shows the ground there too: every erase, and a new ground painted over the whole
    screen without touching the scrollback."""

    BAND = Style(fg="#c0c0c0", bg="#202040")

    def test_every_erase_paints_the_ground(self) -> None:
        harness = Harness(rows=10, history=4)
        harness.region = LiveRegion(harness._write, ground=GROUND)
        harness.render(plain("one", "two", "three"), cursor=(2, 0))
        harness.region.render(plain("a", "b", "c"), (2, 0), harness.cols, flush=plain("done", ""))
        harness.render(plain("one"), cursor=(0, 0))  # shrinks: the freed rows erased
        self.assertEqual(blank_backgrounds(harness.screen, range(4, 10)), {GROUND})
        self.assertEqual(blank_backgrounds(harness.screen, range(4)), {None}, "the shell's rows are not ours")

    def test_a_new_ground_is_painted_over_the_whole_screen_and_nothing_reaches_the_scrollback(self) -> None:
        harness = Harness(rows=8, at_top=True)
        harness.region = LiveRegion(harness._write, at_top=True, ground=GROUND)
        for index in range(4):
            harness.region.render(plain("tail", "live"), (1, 0), harness.cols, flush=plain(f"done-{index}", ""),
                                  screen_rows=8)
        harness.region.render(plain("live"), (0, 0), harness.cols, screen_rows=8)
        history, shown = list(harness.screen.scrollback), harness.screen.lines()
        self.assertEqual(blank_backgrounds(harness.screen, range(8)), {GROUND})
        harness.region.set_ground(OTHER_GROUND)
        harness.region.render(plain("live"), (0, 0), harness.cols, screen_rows=8)
        self.assertEqual(blank_backgrounds(harness.screen, range(8)), {OTHER_GROUND})
        self.assertEqual((harness.screen.scrollback, harness.screen.lines()), (history, shown))

    def test_a_new_ground_reaches_the_flushed_rows_and_the_wallpaper_comes_back_on_them(self) -> None:
        from omh.tui.wallpaper import Cell

        harness = Harness(rows=8, at_top=True)
        harness.region = LiveRegion(harness._write, at_top=True, ground=GROUND)
        glyph = (Cell(1, 15, "@", "#445566"),)
        harness.region.render(plain("live"), (0, 0), 20, flush=plain("done-0", "done-1"), screen_rows=8,
                              ambient=glyph, ambient_above=True)
        self.assertEqual(harness.screen.line(1)[15], "@")
        harness.region.set_ground(OTHER_GROUND)
        harness.region.render(plain("live"), (0, 0), 20, screen_rows=8, ambient=glyph, ambient_above=True)
        self.assertEqual(blank_backgrounds(harness.screen, range(1)), {OTHER_GROUND}, "the top row, painted again")
        self.assertEqual(harness.screen.line(1)[15], "@", "the wallpaper's cell on a row painted again")

    def test_a_frame_that_shrinks_on_a_new_ground_leaves_no_cell_of_the_old_one(self) -> None:
        # Esc from a /theme preview: the picker's rows go in the same frame the look's ground comes back.
        harness = Harness(rows=10, at_top=True)
        harness.region = LiveRegion(harness._write, at_top=True, ground=GROUND)
        harness.region.render(plain("one", "two"), (0, 0), 20, screen_rows=10)
        harness.region.set_ground(OTHER_GROUND)
        harness.region.render(plain("one", "two", "pick 1", "pick 2"), (0, 0), 20, screen_rows=10)
        harness.region.set_ground(GROUND)
        harness.region.render(plain("one", "two"), (0, 0), 20, screen_rows=10)
        self.assertEqual(blank_backgrounds(harness.screen, range(10)), {GROUND})

    def test_clear_after_a_new_ground_paints_the_rows_on_the_screen_on_it(self) -> None:
        harness = Harness(rows=8, at_top=True)
        harness.region = LiveRegion(harness._write, at_top=True, ground=GROUND)
        harness.region.render(plain("live"), (0, 0), 20, flush=plain("done-0", "done-1"), screen_rows=8)
        harness.region.set_ground(None)
        harness.region.flush_above(plain("last"), 20)  # as at exit: a frame with no height keeps the new ground owed
        harness.region.clear(8)
        self.assertEqual(blank_backgrounds(harness.screen, range(8)), {None})
        self.assertEqual(harness.screen.lines()[:3], ["done-0", "done-1", "last"])

    def test_clear_erases_on_the_terminals_own_background(self) -> None:
        harness = Harness(rows=10, history=4)
        harness.region = LiveRegion(harness._write, ground=GROUND)
        harness.render(plain("one", "two"), cursor=(1, 0))
        harness.region.clear()
        self.assertTrue(harness.writes[-1].endswith(screen_module.ERASE_BELOW))
        self.assertNotIn("48;2", harness.writes[-1], "the shell's rows come back on its own background")
        self.assertNotIn(screen_module.SYNC_BEGIN, harness.writes[-1], "nothing painted again: the bytes as before")

    def test_a_blanked_wallpaper_cell_is_the_cell_an_erase_leaves(self) -> None:
        from omh.tui.wallpaper import Cell

        glyph = "#445566"
        with self.subTest("taken off (no wallpaper)"):
            harness = Harness(rows=8, at_top=True)
            harness.region = LiveRegion(harness._write, at_top=True, ground=GROUND)
            harness.region.render(plain("live"), (0, 0), 20, screen_rows=8, ambient=(Cell(5, 3, "@", glyph),))
            self.assertEqual(harness.screen.line(5)[3], "@")
            harness.region.render(plain("live"), (0, 0), 20, screen_rows=8, ambient=None)
            self.assertEqual((harness.screen.line(5)[3:4].strip(), background_at(harness.screen, 5, 3)), ("", GROUND))
        with self.subTest("lifted before a scroll carries it into the scrollback"):
            harness = Harness(rows=6, at_top=True)
            harness.screen = ScrolledAttrs(6, 20)
            harness.region = LiveRegion(harness._write, at_top=True, ground=GROUND)
            above = (Cell(0, 10, "@", glyph),)
            harness.region.render(plain("a", "b"), (1, 0), 20, flush=plain("f0", "f1", "f2"), screen_rows=6,
                                  ambient=above, ambient_above=True)
            self.assertEqual(harness.screen.line(0)[10], "@")
            harness.region.render(plain("a", "b"), (1, 0), 20, flush=plain("g0", "g1", "g2"), screen_rows=6,
                                  ambient=above, ambient_above=True)
            scrolled = harness.screen.scrollback.index("f0")
            self.assertEqual(background_of(harness.screen.scrolled_attrs[scrolled][10]), GROUND)

    def test_a_clear_that_paints_the_screen_again_is_one_synchronized_update_with_autowrap_off(self) -> None:
        harness = Harness(rows=8, at_top=True)
        harness.region = LiveRegion(harness._write, at_top=True, ground=GROUND)
        harness.region.render(plain("live"), (0, 0), 20, flush=plain("done-0", "done-1"), screen_rows=8)
        harness.region.set_ground(None)
        harness.region.clear(8)
        written = harness.writes[-1]
        self.assertTrue(written.startswith(screen_module.SYNC_BEGIN) and written.endswith(screen_module.SYNC_END))
        self.assertEqual(autowrap_at_erases(written), {False}, "every erase and row painted with autowrap off")
        self.assertTrue(written.endswith(screen_module.AUTOWRAP_ON + screen_module.SYNC_END))

    def test_a_new_ground_where_the_regions_place_is_not_certain_erases_from_its_first_row(self) -> None:
        harness = Harness(rows=10, history=4)  # started wherever the shell left the cursor: its row unknown
        harness.region = LiveRegion(harness._write, ground=GROUND)
        harness.render(plain("one", "two"), cursor=(1, 0), screen_rows=10)
        self.assertIsNone(harness.region.top_row(10))
        harness.region.set_ground(OTHER_GROUND)
        harness.render(plain("one", "two"), cursor=(1, 0), screen_rows=10)
        self.assertEqual(blank_backgrounds(harness.screen, range(4, 10)), {OTHER_GROUND})
        self.assertEqual(blank_backgrounds(harness.screen, range(4)), {None}, "the shell's rows are not ours")


class HeightChangeTests(unittest.TestCase):
    def test_growth_scrolls_earlier_content_into_scrollback(self) -> None:
        harness = Harness(rows=10, history=9)
        harness.render(plain("one", "two", "three"), cursor=(2, 0))
        harness.render(plain("one", "two", "three", "four", "five"), cursor=(4, 0))
        self.assertEqual(harness.screen.scrollback, ["history 0", "history 1", "history 2", "history 3"])
        self.assertEqual(harness.screen.lines()[-6:], ["history 8", "one", "two", "three", "four", "five"])
        self.assertEqual(harness.screen.cursor, (9, 0))

    def test_shrink_blanks_the_freed_rows(self) -> None:
        harness = Harness(rows=10, history=4)
        harness.render(plain("one", "two", "three", "four", "five"), cursor=(4, 0))
        harness.render(plain("one", "two"), cursor=(1, 2))
        self.assertEqual(harness.screen.lines()[3:], ["history 3", "one", "two", "", "", "", ""])
        self.assertEqual(harness.screen.cursor, (5, 2))

    def test_an_empty_frame_blanks_the_region(self) -> None:
        harness = Harness(rows=10, history=4)
        harness.render(plain("one", "two"), cursor=(1, 0))
        harness.render([])
        self.assertEqual(harness.screen.lines()[3:7], ["history 3", "", "", ""])
        self.assertEqual(harness.screen.cursor, (4, 0))

    def test_growing_again_after_a_shrink_reuses_the_freed_rows(self) -> None:
        harness = Harness(rows=10, history=4)
        harness.render(plain("one", "two", "three"), cursor=(2, 0))
        harness.render(plain("one"))
        harness.render(plain("one", "two", "three"), cursor=(2, 0))
        self.assertEqual(harness.screen.scrollback, [])
        self.assertEqual(harness.screen.lines()[3:8], ["history 3", "one", "two", "three", ""])


class FlushAboveTests(unittest.TestCase):
    def test_flushed_lines_land_directly_above_the_region(self) -> None:
        harness = Harness(rows=10)
        harness.render(plain("a", "b", "c"), cursor=(2, 1))
        harness.flush(plain("f1", "f2"))
        self.assertEqual(harness.screen.lines()[:6], ["f1", "f2", "a", "b", "c", ""])
        self.assertEqual(harness.screen.cursor, (4, 1))

    def test_flushed_lines_reach_scrollback_and_the_region_stays_intact(self) -> None:
        harness = Harness(rows=10, history=9)
        harness.render(plain("a", "b", "c"), cursor=(1, 0))
        flushed = [f"line {index}" for index in range(15)]
        harness.flush(plain(*flushed))
        history = [f"history {index}" for index in range(9)]
        self.assertEqual(harness.screen.history(), history + flushed + ["a", "b", "c"])
        self.assertEqual(harness.screen.lines()[-3:], ["a", "b", "c"])
        self.assertEqual(harness.screen.scrollback[-1], "line 7")
        self.assertEqual(harness.screen.cursor, (8, 0))

    def test_flush_after_a_shrink_leaves_no_stale_rows(self) -> None:
        harness = Harness(rows=10, history=2)
        harness.render(plain("1", "2", "3", "4", "5"), cursor=(4, 0))
        harness.render(plain("1", "2"), cursor=(1, 0))
        harness.flush(plain("done"))
        self.assertEqual(harness.screen.lines()[:7], ["history 0", "history 1", "done", "1", "2", "", ""])

    def test_flush_before_any_frame_just_prints(self) -> None:
        harness = Harness(rows=10)
        harness.flush(plain("hello"))
        self.assertEqual(harness.screen.lines()[:2], ["hello", ""])
        self.assertEqual(harness.screen.cursor, (1, 0))
        self.assertTrue(harness.screen.cursor_visible)

    def test_flushed_lines_are_clipped_too(self) -> None:
        harness = Harness(rows=6, cols=8)
        harness.render(plain("x"))
        harness.flush(plain("a much longer line than eight", "한글한글한글"))
        self.assertEqual(harness.screen.lines()[:3], ["a much l", "한글한글", "x"])


class FlushOverRegionTests(unittest.TestCase):
    """Flushed lines are written over the region's top rows; the region's rows under them stay where they are."""

    def setUp(self) -> None:
        self.harness = Harness(rows=10, history=9)  # the region's bottom is the screen's last row
        self.frame = plain("t1", "t2", "t3", "a", "b")
        self.harness.render(self.frame, cursor=(4, 1))
        self.history = [f"history {index}" for index in range(9)]

    def test_lines_leaving_the_top_of_the_region_repaint_nothing_under_them(self) -> None:
        # What a streaming tail does: its first lines settle into the transcript, the rows under them stay.
        self.harness.region.render(self.frame[2:], (2, 1), self.harness.cols, flush=plain("t1", "t2"))
        self.assertEqual(printable(self.harness.writes[-1]), "t1t2")
        self.assertEqual(self.harness.screen.lines()[-5:], ["t1", "t2", "t3", "a", "b"])
        self.assertEqual(self.harness.screen.history(), self.history + ["t1", "t2", "t3", "a", "b"])
        self.assertEqual(self.harness.screen.cursor, (9, 1))
        self.assertEqual(self.harness.region.height, 3)

    def test_the_next_frame_sees_the_shorter_region(self) -> None:
        self.harness.region.render(self.frame[2:], (2, 1), self.harness.cols, flush=plain("t1", "t2"))
        before = len(self.harness.writes)
        self.harness.render(self.frame[2:], cursor=(2, 1))
        self.assertEqual(len(self.harness.writes), before)  # the same rows: nothing to write

    def test_flush_above_draws_the_whole_region_again_under_the_lines(self) -> None:
        self.harness.flush(plain("f1", "f2"))
        self.assertEqual(self.harness.screen.history(), self.history + ["f1", "f2", "t1", "t2", "t3", "a", "b"])
        self.assertEqual(self.harness.screen.cursor, (9, 1))
        self.assertEqual(self.harness.region.height, 5)

    def test_a_flush_longer_than_the_region_pushes_it_down(self) -> None:
        flushed = ["f1", "f2", "f3", "f4", "f5", "f6", "f7"]
        self.harness.region.render(plain("a", "b"), (1, 1), self.harness.cols, flush=plain(*flushed))
        self.assertEqual(self.harness.screen.history(), self.history + flushed + ["a", "b"])
        self.assertEqual(self.harness.screen.lines()[-2:], ["a", "b"])
        self.assertEqual(self.harness.screen.cursor, (9, 1))

    def test_a_shorter_frame_under_the_lines_erases_what_it_no_longer_holds(self) -> None:
        harness = Harness(rows=10, history=2)
        harness.render(plain("t1", "a", "b", "c"), cursor=(3, 0))
        harness.region.render(plain("x"), (0, 0), harness.cols, flush=plain("t1"))
        self.assertEqual(harness.screen.lines()[:6], ["history 0", "history 1", "t1", "x", "", ""])

    def test_a_first_frame_erases_what_was_under_its_rows(self) -> None:
        harness = Harness(rows=10, history=2)
        harness.screen.feed("\r\n\r\nleft over\x1b[2A\r")  # text two rows under the cursor
        harness.render(plain("one"))
        self.assertEqual(harness.screen.lines()[:5], ["history 0", "history 1", "one", "", ""])


END = "END"


class InsertedRowsTests(unittest.TestCase):
    """Rows added inside a region that still has room under it: inserted (IL), the rows under them not repainted."""

    UNDER = ["── rule", "› composer", "── rule", "mode", "status"]

    def started(self, history: int, rows: int = 24) -> Harness:
        harness = Harness(rows=rows, cols=40, history=history)
        harness.region = LiveRegion(harness._write, start_row=history)
        harness.render(plain("tail 1", *self.UNDER), cursor=(2, 2), screen_rows=rows)
        harness.writes.clear()
        return harness

    def test_a_tail_row_is_inserted_and_what_is_under_it_is_not_painted_again(self) -> None:
        harness = self.started(history=3)
        harness.render(plain("tail 1", "tail 2", *self.UNDER), cursor=(3, 2), screen_rows=24)
        written = "".join(harness.writes)
        self.assertIn("\x1b[1L", written)
        self.assertEqual(printable(written), "tail 2")  # the new row only: the one above stays, those under move
        for row in self.UNDER:
            self.assertNotIn(row, printable(written))
        self.assertEqual(harness.screen.lines()[3:11], ["tail 1", "tail 2", *self.UNDER, ""])
        self.assertEqual(harness.screen.cursor, (6, 2))
        self.assertEqual(harness.region.last_row(24), 9)

    def test_a_changed_row_under_the_insert_is_still_painted(self) -> None:
        harness = self.started(history=3)
        under = [*self.UNDER[:-1], "status · running"]
        harness.render(plain("tail 1", "tail 2", "tail 3", *under), cursor=(4, 2), screen_rows=24)
        written = "".join(harness.writes)
        self.assertIn("\x1b[2L", written)
        self.assertNotIn("› composer", printable(written))
        self.assertEqual(harness.screen.lines()[3:12], ["tail 1", "tail 2", "tail 3", *under, ""])

    def test_an_insert_among_repeated_rows_compares_each_row_with_the_one_that_moved_there(self) -> None:
        # Real frames repeat rows (blank rows, a rule drawn twice). After the insert a row must be compared
        # with what IL moved onto it, never with what was there before: here a stale rule would stay on row 3.
        rule = "─" * 12
        harness = Harness(rows=24, cols=40, history=3)
        harness.region = LiveRegion(harness._write, start_row=3)
        harness.render(plain("", "", rule, "", rule), cursor=None, screen_rows=24)
        harness.render(plain("", rule, "", "", "", rule), cursor=None, screen_rows=24)
        self.assertIn("\x1b[1L", "".join(harness.writes))
        self.assertEqual(harness.screen.lines()[3:10], ["", rule, "", "", "", rule, ""])

    def test_rows_that_match_wherever_they_go_grow_at_the_end_with_no_insert(self) -> None:
        # Every point keeps as many rows unchanged: the tie goes to the end, the ordinary growth, which writes no IL.
        harness = Harness(rows=24, cols=40, history=3)
        harness.region = LiveRegion(harness._write, start_row=3)
        harness.render(plain("", "", ""), cursor=None, screen_rows=24)
        harness.writes.clear()
        harness.render(plain("", "", "", ""), cursor=None, screen_rows=24)
        self.assertNotIn("L", "".join(final for _params, final in _CSI.findall("".join(harness.writes))))

    def test_without_room_under_it_or_a_certain_place_it_grows_as_before(self) -> None:
        cases = {
            "the last row": (self.started(history=18), 24),  # six rows from row 18 end on the screen's last row
            "no screen size": (self.started(history=3), None),
        }
        unknown = Harness(rows=24, cols=40, history=3)
        unknown.render(plain("tail 1", *self.UNDER), cursor=(2, 2), screen_rows=24)
        unknown.writes.clear()
        cases["place unknown"] = (unknown, 24)
        for name, (harness, rows) in cases.items():
            with self.subTest(case=name):
                harness.render(plain("tail 1", "tail 2", *self.UNDER), cursor=(3, 2), screen_rows=rows)
                written = "".join(harness.writes)
                self.assertNotIn("L", "".join(final for _params, final in _CSI.findall(written)))
                screen = harness.screen.lines()
                start = screen.index("tail 1")
                self.assertEqual(screen[start : start + 7], ["tail 1", "tail 2", *self.UNDER])


def ending(rows: int) -> list[Line]:
    """A frame of `rows` rows whose last row reads END."""
    return plain(*[f"row {n}" for n in range(rows - 1)], END)


class LastRowTests(unittest.TestCase):
    """`LiveRegion.last_row`: the screen row the region ends on, said only where it is certain.

    Every answer is checked against the row END is on in the VT screen.
    """

    def shown(self, harness: Harness) -> int:
        return harness.screen.lines().index(END)

    def test_before_any_frame_there_is_no_row(self) -> None:
        for at_top in (False, True):
            self.assertIsNone(Harness(at_top=at_top).region.last_row(10))

    def test_a_first_frame_from_the_top_row_ends_on_its_own_last_row(self) -> None:
        harness = Harness(rows=10, at_top=True)
        harness.render(ending(4))
        self.assertEqual((harness.region.last_row(10), self.shown(harness)), (3, 3))

    def test_the_same_frame_from_a_row_nobody_told_it_says_nothing(self) -> None:
        # Nine rows on a ten-row screen end on row 8 from the top row and on row 9 from anywhere else.
        ends = set()
        for history in range(10):
            harness = Harness(rows=10, history=history)
            harness.render(ending(9))
            self.assertIsNone(harness.region.last_row(10), history)
            ends.add(self.shown(harness))
        self.assertEqual(ends, {8, 9})

    def test_a_flush_under_a_frame_that_fills_the_screen_settles_it_from_any_start(self) -> None:
        for history in range(10):
            harness = Harness(rows=10, history=history)
            harness.render(ending(9))
            self.assertIsNone(harness.region.last_row(10), history)
            harness.region.render(ending(9), (0, 0), harness.cols, flush=plain("a"))
            self.assertEqual((harness.region.last_row(10), self.shown(harness)), (9, 9), history)

    def test_growth_pushes_the_row_down_one_per_row_and_stops_at_the_screens_last(self) -> None:
        harness = Harness(rows=10, at_top=True)
        seen = []
        for rows in (2, 2, 5, 6, 9, 10):
            harness.render(ending(rows))
            seen.append(harness.region.last_row(10))
            self.assertEqual(seen[-1], self.shown(harness))
        self.assertEqual(seen, [1, 1, 4, 5, 8, 9])

    def test_a_flush_pushes_the_row_down_one_per_line_and_stops_at_the_screens_last(self) -> None:
        harness = Harness(rows=12, at_top=True)
        harness.render(ending(6))
        harness.flush(plain("a", "b"))
        self.assertEqual((harness.region.last_row(12), self.shown(harness)), (7, 7))
        harness.flush(plain("c", "d", "e"))
        self.assertEqual((harness.region.last_row(12), self.shown(harness)), (10, 10))
        harness.flush(plain(*"fghijklm"))  # far past the screen's end
        self.assertEqual((harness.region.last_row(12), self.shown(harness)), (11, 11))

    def test_a_frame_that_takes_rows_off_the_end_moves_the_row_up_by_as_many(self) -> None:
        harness = Harness(rows=10, at_top=True)
        harness.render(ending(6))
        harness.render(ending(4))
        self.assertEqual((harness.region.last_row(10), self.shown(harness)), (3, 3))
        harness.render(ending(8))
        self.assertEqual((harness.region.last_row(10), self.shown(harness)), (7, 7))

    def test_a_shrink_at_the_screens_end_moves_the_row_up_from_any_start(self) -> None:
        for history in range(10):
            harness = Harness(rows=10, history=history)
            harness.region.render(ending(9), (0, 0), harness.cols, flush=plain(*"abcdefghij"))
            harness.render(ending(3))
            self.assertEqual((harness.region.last_row(10), self.shown(harness)), (3, 3), history)

    def test_a_flush_before_the_first_frame_moves_where_the_frame_starts(self) -> None:
        harness = Harness(rows=10, at_top=True)
        harness.flush(plain("banner"))
        harness.render(ending(4))
        self.assertEqual((harness.region.last_row(10), self.shown(harness)), (4, 4))

    def test_a_flush_longer_than_the_region_keeps_the_row(self) -> None:
        harness = Harness(rows=10, at_top=True)
        harness.render(ending(2))
        harness.flush(plain("a", "b", "c"))
        self.assertEqual((harness.region.last_row(10), self.shown(harness)), (4, 4))
        harness.region.render(ending(3), (0, 0), harness.cols, flush=plain("d", "e", "f", "g"))
        self.assertEqual((harness.region.last_row(10), self.shown(harness)), (9, 9))

    def test_the_top_row_and_the_rows_above_follow_the_same_writes(self) -> None:
        harness = Harness(rows=10, history=4)
        self.assertEqual(harness.region.rows_above(10, flushed=2, height=3), 2)  # as if it had started on row 0
        harness.region.render(ending(3), (0, 0), harness.cols, flush=plain("a", "b"))
        self.assertIsNone(harness.region.top_row(10))  # started on row 4 or anywhere else: not certain
        self.assertEqual(harness.region.rows_above(10), 2)
        self.assertEqual(harness.region.rows_above(10, flushed=20, height=3), 7)  # the screen's end decides
        harness.flush(plain(*[f"line {n}" for n in range(20)]))
        self.assertEqual((harness.region.top_row(10), harness.region.rows_above(10)), (7, 7))
        self.assertEqual(harness.screen.lines()[7], "row 0")

    def test_clear_forgets_the_row_and_the_top_row_start(self) -> None:
        harness = Harness(rows=10, at_top=True)
        harness.render(ending(4))
        harness.region.clear()
        self.assertIsNone(harness.region.last_row(10))
        harness.render(ending(4))
        self.assertIsNone(harness.region.last_row(10))

    def test_whatever_is_drawn_and_flushed_an_answer_is_the_row_on_the_screen(self) -> None:
        rng = random.Random(20261013)
        answered = unknown = 0
        for case in range(300):
            rows = rng.choice((6, 10, 24))
            at_top = rng.random() < 0.5
            harness = Harness(rows=rows, cols=20, history=0 if at_top else rng.randrange(rows), at_top=at_top)
            height = 0
            for step in range(30):
                flushed = plain(*[f"flushed {case}.{step}.{n}" for n in range(rng.randrange(rows + 3))])
                if rng.random() < 0.6:
                    # frames of any height up to the screen's but one, now and then under flushed lines
                    height = rng.randint(1, rows - 1)
                    harness.region.render(ending(height), (0, 0), 20, flush=flushed if rng.random() < 0.4 else ())
                elif height:
                    harness.flush(flushed)
                    height = harness.region.height
                said = harness.region.last_row(rows)
                if said is None or not height:
                    unknown += 1
                    continue
                answered += 1
                self.assertEqual(said, self.shown(harness), (case, step, rows, at_top))
        self.assertGreater(answered, 2000)
        self.assertGreater(unknown, 400)


class ClippingAndStyleTests(unittest.TestCase):
    def test_wide_glyphs_are_dropped_whole_at_the_edge(self) -> None:
        harness = Harness(rows=4, cols=7)  # the model raises on any write past column 7
        harness.render(plain("한글한글한글", "ab한글", FAMILY * 5))
        self.assertEqual(harness.screen.lines()[:3], ["한글한", "ab한글", FAMILY * 3])

    def test_a_full_width_row_keeps_its_last_glyph(self) -> None:
        harness = Harness(rows=4, cols=5)
        harness.render([(Span("abcde"),), (Span("xy", RED_BOLD), Span("한글"))])
        harness.render([(Span("abcde"),), (Span("XY", RED_BOLD), Span("한글"))])
        self.assertEqual(harness.screen.lines()[:2], ["abcde", "XY한"])

    def test_styles_are_painted_and_reset_before_the_row_ends(self) -> None:
        harness = Harness(rows=4)
        harness.render([(Span("err", RED_BOLD), Span(" ok"))])
        self.assertEqual(harness.screen.attrs_at(0, 0), RED_BOLD_SGR)
        self.assertEqual(harness.screen.attrs_at(0, 2), RED_BOLD_SGR)
        self.assertEqual(harness.screen.attrs_at(0, 3), ())
        self.assertEqual(harness.screen.attrs_at(0, 10), ())  # the erased tail: no colour bleed

    def test_painted_rows_end_in_default_attributes(self) -> None:
        row = paint_line((Span("err", RED_BOLD),), 3)
        self.assertEqual(row, f"{RED_BOLD.sgr()}err{SGR_RESET}")
        self.assertEqual(paint_line((Span("ok"),), 5), "ok\x1b[K")

    def test_control_characters_cannot_move_the_cursor(self) -> None:
        harness = Harness(rows=4)
        harness.render([(Span("a\x1b[2Jb\r\nc\x07"),), (Span("next"),)])
        self.assertEqual(harness.screen.lines()[:2], ["abc", "next"])  # the whole sequence goes, not only ESC


class ClearTests(unittest.TestCase):
    def test_clear_erases_the_region_and_the_next_frame_starts_at_its_top(self) -> None:
        harness = Harness(rows=10, history=7)
        harness.render(plain("a", "b", "c"), cursor=(2, 1))
        harness.region.clear()
        self.assertEqual(harness.screen.lines()[-4:], ["history 6", "", "", ""])
        self.assertEqual(harness.screen.cursor, (7, 0))
        harness.render(plain("x", "y"), cursor=(1, 0))
        self.assertEqual(harness.screen.lines()[-4:], ["history 6", "x", "y", ""])

    def test_clear_with_nothing_shown_writes_nothing(self) -> None:
        harness = Harness()
        harness.region.clear()
        self.assertEqual(harness.writes, [])

    def test_clear_returns_the_cursor_to_column_zero_even_with_no_rows(self) -> None:
        harness = Harness()
        harness.render([], cursor=(0, 5))
        harness.region.clear()
        self.assertEqual(harness.screen.cursor, (0, 0))


class VTScreenModelTests(unittest.TestCase):
    def test_insert_lines_moves_the_rows_down_and_drops_the_last_ones(self) -> None:
        screen = VTScreen(rows=4, cols=5)
        screen.feed("a\r\nb\r\nc\r\nd\x1b[2A\x1b[2C\x1b[2L")
        self.assertEqual(screen.lines(), ["a", "", "", "b"])
        self.assertEqual((screen.cursor, screen.scrollback), ((1, 0), []))

    def test_line_feed_at_the_bottom_scrolls_into_scrollback(self) -> None:
        screen = VTScreen(rows=2, cols=5)
        screen.feed("a\r\nb\r\nc")
        self.assertEqual(screen.scrollback, ["a"])
        self.assertEqual(screen.lines(), ["b", "c"])

    def test_line_feed_keeps_the_column(self) -> None:
        screen = VTScreen(rows=3, cols=5)
        screen.feed("ab\nc")
        self.assertEqual(screen.lines(), ["ab", "  c", ""])

    def test_relative_motion_clamps_at_the_edges(self) -> None:
        screen = VTScreen(rows=3, cols=5)
        screen.feed("\x1b[9B\x1b[9C")
        self.assertEqual(screen.cursor, (2, 4))
        screen.feed("\x1b[9A\x1b[9D")
        self.assertEqual(screen.cursor, (0, 0))
        screen.feed("\x1b[2;3H")
        self.assertEqual(screen.cursor, (1, 2))

    def test_erase_in_line_modes(self) -> None:
        screen = VTScreen(rows=1, cols=5)
        for sequence, expected in (("\x1b[K", "ab"), ("\x1b[1K", "   de"), ("\x1b[2K", "")):
            with self.subTest(sequence=sequence):
                screen.feed("\rabcde\r\x1b[2C" + sequence)
                self.assertEqual(screen.lines(), [expected])

    def test_erase_in_display_modes(self) -> None:
        screen = VTScreen(rows=3, cols=3)
        screen.feed("aaa\r\nbbb\r\nccc\x1b[2A\r\x1b[1C\x1b[J")
        self.assertEqual(screen.lines(), ["a", "", ""])
        screen.feed("\x1b[2J")
        self.assertEqual(screen.lines(), ["", "", ""])

    def test_wide_glyphs_take_two_cells_and_break_cleanly(self) -> None:
        screen = VTScreen(rows=1, cols=6)
        screen.feed("한글a")
        self.assertEqual(screen.cursor, (0, 5))
        screen.feed("\r\x1b[1Cx")  # overwrite the right half of 한
        self.assertEqual(screen.lines(), [" x글a"])

    def test_writing_past_the_margin_raises(self) -> None:
        screen = VTScreen(rows=1, cols=3)
        screen.feed("abc")
        with self.assertRaises(VTOverflow):
            screen.feed("d")
        screen.feed("\rab")
        with self.assertRaises(VTOverflow):
            screen.feed("한")

    def test_erase_at_the_margin_deletes_the_last_glyph_like_xterm(self) -> None:
        screen = VTScreen(rows=1, cols=3)
        screen.feed("abc\x1b[K")
        self.assertEqual(screen.lines(), ["ab"])

    def test_sgr_is_recorded_per_cell_and_reset(self) -> None:
        screen = VTScreen(rows=1, cols=6)
        screen.feed("\x1b[1;38;2;255;0;0mab\x1b[0mc\x1b[4md\x1b[me")
        self.assertEqual([screen.attrs_at(0, col) for col in range(5)], [RED_BOLD_SGR, RED_BOLD_SGR, (), (4,), ()])

    def test_modes_are_recorded_and_unknown_sequences_ignored(self) -> None:
        screen = VTScreen(rows=1, cols=5)
        screen.feed("\x1b[?25l\x1b[?2004h\x1b[?7l\x1b[5n\x1b[>c\x1b7a")
        self.assertFalse(screen.cursor_visible)
        self.assertTrue(screen.bracketed_paste)
        self.assertFalse(screen.autowrap)
        self.assertEqual(screen.lines(), ["a"])
        screen.feed("\x1b[?25h\x1b[?2004l\x1b[?7h")
        self.assertTrue(screen.cursor_visible)
        self.assertFalse(screen.bracketed_paste)
        self.assertTrue(screen.autowrap)

    def test_an_escape_split_across_feeds(self) -> None:
        screen = VTScreen(rows=2, cols=5)
        screen.feed("ab\x1b[")
        screen.feed("1Dc\x1b")
        screen.feed("[Bd")
        self.assertEqual(screen.lines(), ["ac", "  d"])


class BidiGuardTests(unittest.TestCase):
    def test_no_painted_row_carries_a_bidi_control(self) -> None:
        bidi = "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
        painted = paint_line((Span(f"rm{bidi[4]} -rf{bidi[2]} ~"), Span(f"{bidi}x")), 40)
        self.assertEqual(painted, "rm -rf ~x\x1b[K")
        self.assertEqual(paint_line((Span("a\u200fb"),), 5), "a\u200fb\x1b[K")  # a plain mark stays


class EscapeGuardTests(unittest.TestCase):
    def test_a_sequence_inside_span_text_never_reaches_the_terminal(self) -> None:
        from omh.tui.screen import paint_line
        from omh.tui.style import Span

        painted = paint_line((Span("\x1b[31mred\x1b[0m \x1b]8;;http://x\x07link\x1b]8;;\x07 \x1b[2Jdone"),), 40)
        self.assertNotIn("[31m", painted)
        self.assertNotIn("]8;;", painted)
        self.assertNotIn("[2J", painted)
        self.assertIn("red link done", painted)


if __name__ == "__main__":
    unittest.main()


class LowerTests(unittest.TestCase):
    """A region on the screen's last row that gives rows up moves its top down (`LiveRegion._lower`): the rows above it
    are painted again that many rows lower from the lines it flushed there, in the frame's one write."""

    def rows(self, count: int, word: str) -> list[Line]:
        return [(Span(f"{word} {index}"),) for index in range(count)]

    def test_the_rows_above_move_down_and_the_region_keeps_the_last_row(self) -> None:
        harness = Harness(rows=10, cols=20, at_top=True)
        harness.region.render(self.rows(4, "row"), None, 20, flush=self.rows(12, "out"), screen_rows=10)
        self.assertEqual(harness.region.last_row(10), 9)
        self.assertTrue(harness.region.can_lower(10, 2))
        sent = len(harness.writes)
        harness.region.render(self.rows(2, "row"), None, 20, screen_rows=10, lower=2)
        self.assertEqual(len(harness.writes) - sent, 1, "one write")
        self.assertIn("\x1b[?2026h", harness.writes[-1], "a synchronized update")
        self.assertEqual(harness.screen.lines(), [f"out {index}" for index in range(4, 12)] + ["row 0", "row 1"])
        self.assertEqual((harness.region.top_row(10), harness.region.last_row(10)), (8, 9))

    def test_a_region_cannot_paint_again_rows_it_did_not_write(self) -> None:
        # Started under the shell's own output, it flushed nothing above it: those rows are not its to move.
        harness = Harness(rows=10, cols=20, history=6)
        region = LiveRegion(harness._write, start_row=6)
        harness.region = region
        region.render(self.rows(4, "row"), None, 20, screen_rows=10)
        self.assertEqual(region.last_row(10), 9)
        self.assertFalse(region.can_lower(10, 2))
        region.render(self.rows(2, "row"), None, 20, screen_rows=10, lower=2)
        self.assertEqual(harness.screen.lines()[:6], [f"history {index}" for index in range(6)], "nothing moved")
        region.render(self.rows(4, "row"), None, 20, flush=self.rows(8, "out"), screen_rows=10)
        self.assertTrue(region.can_lower(10, 2), "once it flushed every row above it, it can")
        self.assertFalse(region.can_lower(10, 4), "not by all its rows")
        self.assertFalse(region.can_lower(10, 0))
