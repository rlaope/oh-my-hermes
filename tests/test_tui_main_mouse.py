"""The main screen takes the mouse (the owner's decision of 2026-11-05): a drag copies without the rail, the wheel opens
the transcript view, and `OMH_TUI_MOUSE=0` keeps the terminal's own wheel and selection.

The rail stays as it is drawn (`tests/test_tui_clean_copy.py`); what changes
is who selects. Wherever the row a report lands on is certain, the OMH TUI asks
for clicks, a held button's motion and the wheel in SGR form. A drag over the
rows the live region printed, the transcript's above it and its own, is
shown reversed and copied without gutter cells, as the pager copies; a double
click copies a word and a triple click a row. The wheel up opens Ctrl+O's
view one notch up from its end. A row the region did not print selects
nothing: moving the held button from it opens the transcript view instead. A
selection that would no longer hold what the screen showed (the live rows
moved under it) is dropped and copies nothing. A resize drops the selection
without painting at rows the terminal reflowed. The highlight is painted back
exactly as the rows were flushed, the scene look's ground included, and never
scrolls into the scrollback. Most cases here run with the main screen taking
the mouse, the default the other harnesses turn off (`make_app`).

Where a report lands is read from the VT screen the scripted terminal
painted, as `tests/test_tui_agent_mouse.py` reads it: columns and rows from 1.
"""

from __future__ import annotations

import base64
import time
import unittest

from _tui_gateway_replay import Scenario, spans
from _vt_screen import VTScreen
from test_tui_agent_mouse import SECOND_ROW, click, step_through
from test_tui_agent_view import agent_app
from test_tui_aura import frame_for as aura_frame, rows_of as aura_rows
from test_tui_app import NO_TERMIOS, AppTestCase, PromptSlotTests, Step, startup_answers
from test_tui_clean_copy import osc52, row_of
from test_tui_modes import QueuedLine, drawn, make_app, type_text
from omh.tui import terminal as terminal_module
from omh.tui.app import (
    COPIED_NOTE,
    COPY_NOTE_SECONDS,
    CURSOR_POSITION_REQUEST,
    READ_TIMEOUT_SECONDS,
    REPORTING_SLOT_ARM_SECONDS,
    App,
    Notification,
)
from omh.tui.gateway import ServerRequest
from omh.tui.keys import BUTTON_LEFT, CHAR, DOWN, WHEEL_DOWN, WHEEL_UP, Key, Mouse
from omh.tui.pager import HistoryPager, reversed_cells
from omh.tui.screen import FLUSHED_KEPT, LiveRegion, _flushed_row, cursor_at
from omh.tui.style import Span, Style
from omh.tui.transcript import AssistantBlock

MOUSE = {"OMH_TUI_MOUSE": "1", "TERM": "xterm-kitty"}  # kitty: a copy goes out as OSC 52, which the VT screen keeps
NATIVE = {"OMH_TUI_MOUSE": "0", "TERM": "xterm-kitty"}
REPLY = "first line of the reply\nsecond line"
CTRL_L = Key(CHAR, "l", ctrl=True)
REVERSE = 7


def main_app(environ: dict[str, str] | None = None, rows: int = 14, cols: int = 60, **options: object) -> App:
    """A prompt and its reply on the main screen, redrawn from the top row so the region's place is certain."""
    app, _client = make_app(rows=rows, cols=cols, environ={**MOUSE, **(environ or {})}, **options)
    app.platform = "linux"
    app.pbcopy = lambda text: False  # type: ignore[method-assign]  # never the real clipboard
    app.transcript.add_user("explain it")
    app.transcript.blocks.append(AssistantBlock(REPLY, model="m"))
    app._on_input(CTRL_L)
    drawn(app)
    return app


def press(app: App, x: int, y: int) -> None:
    app._on_input(Mouse(BUTTON_LEFT, x, y))


def move(app: App, x: int, y: int) -> None:
    app._on_input(Mouse(BUTTON_LEFT, x, y, motion=True))


def release(app: App, x: int, y: int) -> None:
    app._on_input(Mouse(BUTTON_LEFT, x, y, pressed=False))


def drag(app: App, start: tuple[int, int], end: tuple[int, int]) -> None:
    press(app, *start)
    move(app, *end)
    release(app, *end)


def column(app: App, text: str) -> int:
    """The 1-based column `text` starts on, on the first screen row showing it (no wide glyph before it)."""
    return next(line.index(text) for line in app.terminal.screen.lines() if text in line) + 1  # type: ignore[attr-defined]


def reversed_columns(app: App, y: int) -> list[int]:
    """The 1-based columns of screen row `y` (from 1) drawn reversed."""
    screen: VTScreen = app.terminal.screen  # type: ignore[attr-defined]
    return [col + 1 for col in range(screen.cols) if REVERSE in screen.attrs_at(y - 1, col)]


def reversed_count(screen: VTScreen) -> int:
    return sum(REVERSE in screen.attrs_at(row, col) for row in range(screen.rows) for col in range(screen.cols))


def scroll_watch(screen: VTScreen) -> list[tuple[int, ...]]:
    """Every cell's attributes as its row leaves the screen's top, from now on."""
    scrolled: list[tuple[int, ...]] = []
    feed_line = screen._line_feed

    def line_feed() -> None:
        if screen.cursor[0] == screen.rows - 1:
            scrolled.extend(screen.attrs_at(0, col) for col in range(screen.cols))
        feed_line()

    screen._line_feed = line_feed  # type: ignore[method-assign]
    return scrolled


def picture(app: App) -> tuple[list[str], list[list[tuple[int, ...]]]]:
    """Every cell of the main screen: its text and its attributes."""
    screen: VTScreen = app.terminal.screen  # type: ignore[attr-defined]
    return screen.lines(), [[screen.attrs_at(row, col) for col in range(screen.cols)] for row in range(screen.rows)]


class ReportsTests(unittest.TestCase):
    def test_reports_with_a_held_buttons_motion_are_on_once_the_regions_place_is_certain(self) -> None:
        app, _client = make_app(rows=14, cols=60, environ=MOUSE)
        drawn(app)  # a launch whose cursor row nobody reported: no row is certain
        self.assertFalse(app.terminal.mouse_reporting)  # type: ignore[attr-defined]
        app._on_input(CTRL_L)
        drawn(app)
        self.assertTrue(app.terminal.mouse_reporting)  # type: ignore[attr-defined]
        self.assertTrue(app.terminal.mouse_drag)  # type: ignore[attr-defined]
        written = "".join(app.terminal.writes)  # type: ignore[attr-defined]
        self.assertEqual((written.count(terminal_module.MOUSE_REPORTING_ON), written.count(terminal_module.MOUSE_DRAG_ON)),
                         (1, 1))
        self.assertNotIn("?1003h", written)  # never motion with no button held

    def test_opt_out_asks_for_nothing_and_a_late_report_does_nothing(self) -> None:
        app = main_app(NATIVE)
        before = picture(app)
        row = row_of(app, "first line")
        drag(app, (3, row), (20, row + 1))
        press(app, 5, row)
        release(app, 5, row)
        press(app, 5, row)
        release(app, 5, row)
        app._on_input(Mouse(WHEEL_UP, 5, row))
        drawn(app)
        written = "".join(app.terminal.writes)  # type: ignore[attr-defined]
        for mode in ("?1000h", "?1002h", "?1003h", "?1006h"):
            self.assertNotIn(mode, written)
        self.assertEqual((app.pager, osc52(app), app.copy_note, picture(app)), (None, [], None, before))


class DragTests(unittest.TestCase):
    def test_a_drag_over_the_transcript_copies_it_without_the_rail(self) -> None:
        app = main_app()
        first, second = row_of(app, "first line"), row_of(app, "second line")
        drag(app, (1, first), (60, second))  # from the rail's own cell to the row's far end
        self.assertEqual(osc52(app), [REPLY])
        self.assertNotIn("┃", osc52(app)[0])
        self.assertIn(COPIED_NOTE.format(count=len(REPLY)), "\n".join(drawn(app)))  # the notice row says so

    def test_the_copy_notice_goes_after_its_time(self) -> None:
        now = [100.0]
        app = main_app(clock=lambda: now[0])
        row = row_of(app, "first line")
        drag(app, (3, row), (12, row))
        self.assertIn("copied", "\n".join(drawn(app)))
        now[0] += COPY_NOTE_SECONDS
        app._expire_notification()
        self.assertNotIn("copied", "\n".join(drawn(app)))

    def test_a_drag_from_the_transcript_into_the_live_region_copies_both(self) -> None:
        app = main_app()
        type_text(app, "draft text")
        drawn(app)
        prompt, composer = row_of(app, "explain it"), row_of(app, "draft text")
        drag(app, (1, prompt), (60, composer))
        (copied,) = osc52(app)
        self.assertTrue(copied.startswith("❯ explain it"), copied)
        self.assertTrue(copied.endswith("draft text"), copied)
        self.assertIn(REPLY, copied)
        self.assertNotIn("┃", copied)

    def test_the_selection_is_shown_reversed_on_text_cells_not_on_the_rail_and_painted_back_exactly(self) -> None:
        now = [100.0]
        app = main_app(clock=lambda: now[0])
        before = picture(app)
        first, second = row_of(app, "first line"), row_of(app, "second line")
        text = column(app, "first line")
        press(app, 1, first)
        move(app, text + 5, second)
        drawn(app)
        # The rail and the reply's margin keep their look; the text is reversed from its first cell.
        self.assertEqual(reversed_columns(app, first), list(range(text, text + len("first line of the reply"))))
        self.assertEqual(reversed_columns(app, second), list(range(text, text + 6)))
        release(app, text + 5, second)
        drawn(app)
        self.assertTrue(reversed_columns(app, first))  # kept after the copy, as a terminal keeps it
        app._on_input(Key(CHAR, "x"))  # a key lets it go
        app.composer.replace(0, len(app.composer.text), "")
        now[0] += COPY_NOTE_SECONDS  # and the copy's notice goes
        app._expire_notification()
        drawn(app)
        self.assertEqual(picture(app), before)

    def test_a_double_click_copies_a_word_and_a_triple_click_the_row(self) -> None:
        app = main_app()
        row, at = row_of(app, "first line"), column(app, "reply") + 1
        for _count in range(3):
            press(app, at, row)
            release(app, at, row)
        self.assertEqual(osc52(app), ["reply", "first line of the reply"])

    def test_a_drag_carried_under_the_region_stops_above_the_info_line(self) -> None:
        app = main_app()
        type_text(app, "draft")
        screen = drawn(app)
        drag(app, (1, row_of(app, "second line")), (60, len(screen)))
        (copied,) = osc52(app)
        self.assertEqual(copied, "second line\n\ndraft")  # the rules, the mark and the info line are no text

    def test_the_selection_stays_on_its_text_while_output_scrolls_the_screen(self) -> None:
        app = main_app(rows=10)
        row, text = row_of(app, "first line"), column(app, "first line")
        press(app, text, row)
        move(app, text + 9, row)
        for index in range(6):  # output while the button is held: the row moves up and off the screen
            app.transcript.add_notice(f"notice {index}")
            drawn(app)
        self.assertNotIn("first line of the reply", "\n".join(drawn(app)))
        release(app, text + 9, row)
        self.assertEqual(osc52(app), ["first line"])
        screen: VTScreen = app.terminal.screen  # type: ignore[attr-defined]
        self.assertIn("┃   first line of the reply", screen.scrollback)  # the row went into the scrollback as flushed


class WheelTests(unittest.TestCase):
    def test_the_wheel_up_opens_ctrl_os_view_one_notch_up_from_its_end_and_types_nothing(self) -> None:
        app = main_app(rows=8)
        for index in range(12):
            app.transcript.add_notice(f"notice {index}")
        drawn(app)
        type_text(app, "draft")
        app._on_input(Mouse(WHEEL_DOWN, 5, 3))
        self.assertIsNone(app.pager)  # down: the main screen is at its end already
        app._on_input(Mouse(WHEEL_UP, 5, 3))
        self.assertIsInstance(app.pager, HistoryPager)
        drawn(app)
        opened = (app.pager.item, app.pager.offset)  # type: ignore[union-attr]
        app._on_input(Key(CHAR, "q"))
        app._on_input(Key(CHAR, "o", ctrl=True))  # Ctrl+O, then one notch of the wheel in it
        drawn(app)
        ended = (app.pager.item, app.pager.offset)  # type: ignore[union-attr]
        app._on_input(Mouse(WHEEL_UP, 5, 3))
        drawn(app)
        self.assertEqual(opened, (app.pager.item, app.pager.offset))  # type: ignore[union-attr]
        self.assertNotEqual(opened, ended)
        self.assertEqual(app.composer.text, "draft")  # nothing typed

    def test_the_wheel_does_nothing_while_a_drag_is_under_way(self) -> None:
        app = main_app()
        row, text = row_of(app, "first line"), column(app, "first line")
        press(app, text, row)
        move(app, text + 4, row)
        app._on_input(Mouse(WHEEL_UP, text + 4, row))
        self.assertIsNone(app.pager)
        release(app, text + 4, row)
        self.assertEqual(osc52(app), ["first"])

    def test_with_nothing_in_the_transcript_the_wheel_opens_nothing(self) -> None:
        app, _client = make_app(rows=14, cols=60, environ=MOUSE)
        app._on_input(CTRL_L)
        drawn(app)
        app._on_input(Mouse(WHEEL_UP, 5, 3))
        self.assertIsNone(app.pager)
        self.assertEqual(app.transcript.blocks, [])  # and no notice for each notch


class AgentListTests(unittest.TestCase):
    def test_a_click_on_a_list_row_still_opens_that_agents_log_and_selects_nothing(self) -> None:
        app, _client = agent_app(environ=MOUSE)
        app._on_input(CTRL_L)
        drawn(app)
        app._on_input(Key(DOWN))
        drawn(app)
        row = row_of(app, SECOND_ROW)
        click(app, 5, row)
        release(app, 5, row)
        self.assertIsNotNone(app.pager)
        self.assertTrue(app.log_agent)
        self.assertEqual(osc52(app), [])


class UncertainRowTests(unittest.TestCase):
    def test_a_press_on_a_row_the_region_did_not_print_copies_nothing_and_a_drag_from_it_opens_the_transcript_view(self) -> None:
        app, _client = make_app(rows=14, cols=60, environ=MOUSE)
        app.terminal.write("shell output\r\nmore shell output\r\n")  # type: ignore[attr-defined]
        app.adopt_cursor_row(3)  # the region starts under the shell's rows, which it never printed
        app.transcript.add_user("explain it")
        drawn(app)
        self.assertTrue(app.terminal.mouse_reporting)  # type: ignore[attr-defined]
        press(app, 3, 1)
        release(app, 3, 1)
        press(app, 3, 1)
        release(app, 3, 1)  # not a double click on a row with no number either
        self.assertEqual((osc52(app), app.pager), ([], None))
        press(app, 3, 1)
        move(app, 9, 2)
        self.assertIsInstance(app.pager, HistoryPager)
        release(app, 9, 2)
        self.assertEqual(osc52(app), [])

    def test_a_resize_drops_the_selection_writes_nothing_at_the_reflowed_rows_and_turns_reports_off(self) -> None:
        app = main_app()
        row = row_of(app, "first line")
        press(app, 3, row)
        move(app, 12, row)
        drawn(app)
        self.assertTrue(reversed_columns(app, row))
        writes = app.terminal.writes  # type: ignore[attr-defined]
        start = len(writes)
        app.terminal.screen.resize(14, 50)  # type: ignore[attr-defined]
        app._on_resize()
        self.assertFalse(app.terminal.mouse_reporting)  # type: ignore[attr-defined]
        release(app, 12, row)  # the release after the resize: nothing to copy
        self.assertEqual(osc52(app), [])
        # Reports off and nothing else: no row painted back at the rows the terminal reflowed.
        self.assertEqual(writes[start:], [terminal_module.MOUSE_DRAG_OFF, terminal_module.MOUSE_REPORTING_OFF])
        self.assertEqual(app.selection.rows, None)


class LookTests(unittest.TestCase):
    def test_without_colour_the_copy_drops_the_light_rail_and_the_selection_still_shows(self) -> None:
        app = main_app({"NO_COLOR": "1"})
        prompt = row_of(app, "explain it")
        self.assertTrue(app.terminal.screen.line(prompt - 1).startswith("│"))  # type: ignore[attr-defined]
        press(app, 1, prompt)
        move(app, 60, prompt)
        drawn(app)
        self.assertTrue(reversed_columns(app, prompt))
        release(app, 60, prompt)
        self.assertEqual(osc52(app), ["❯ explain it"])


GROUND = "#102030"
WIDTH = 30


def region_on(screen: VTScreen, ground: str | None) -> LiveRegion:
    return LiveRegion(screen.feed, at_top=True, ground=ground, highlight=reversed_cells)


def rows_of(*texts: str) -> list[tuple[Span, ...]]:
    return [(Span("┃", Style(fg="#ff0000", gutter=True)), Span(f" {text}")) for text in texts]


class RegionMarkTests(unittest.TestCase):
    def test_a_highlight_above_the_region_is_painted_back_exactly_as_flushed_on_the_looks_ground(self) -> None:
        for ground in (None, GROUND):
            with self.subTest(ground=ground):
                screen, plain = VTScreen(8, WIDTH), VTScreen(8, WIDTH)
                frame = [(Span("composer"),)]
                for target in (screen, plain):
                    region = region_on(target, ground)
                    region.render(frame, (0, 0), WIDTH, flush=rows_of("alpha", "beta"), screen_rows=8)
                    if target is screen:
                        marked = region
                self.assertEqual([marked.doc_row(row, 8) for row in range(4)], [0, 1, 2, None])
                marked.render(frame, (0, 0), WIDTH, screen_rows=8, marks={0: (0, 3), 1: (2, 99)})
                self.assertNotIn(REVERSE, screen.attrs_at(0, 0))  # the rail
                self.assertIn(REVERSE, screen.attrs_at(0, 2))
                self.assertIn(REVERSE, screen.attrs_at(1, 5))
                marked.render(frame, (0, 0), WIDTH, screen_rows=8, marks={})
                self.assertEqual(screen.lines(), plain.lines())
                self.assertEqual([[screen.attrs_at(r, c) for c in range(WIDTH)] for r in range(8)],
                                 [[plain.attrs_at(r, c) for c in range(WIDTH)] for r in range(8)])

    def test_the_bytes_that_paint_a_row_back_are_the_ones_it_was_flushed_with(self) -> None:
        writes: list[str] = []
        region = LiveRegion(writes.append, at_top=True, ground=GROUND, highlight=reversed_cells)
        (line,) = rows_of("alpha")
        region.render([(Span("c"),)], (0, 0), WIDTH, flush=[line], screen_rows=8)
        region.render([(Span("c"),)], (0, 0), WIDTH, screen_rows=8, marks={0: (0, 99)})
        region.render([(Span("c"),)], (0, 0), WIDTH, screen_rows=8, marks={})
        self.assertIn(_flushed_row(line, WIDTH, GROUND)[0], writes[-1])

    def test_a_highlight_never_scrolls_into_the_scrollback(self) -> None:
        screen = VTScreen(5, WIDTH)
        region = region_on(screen, GROUND)
        frame = [(Span("composer"),)]
        region.render(frame, (0, 0), WIDTH, flush=rows_of("alpha", "beta", "gamma"), screen_rows=5)
        region.render(frame, (0, 0), WIDTH, screen_rows=5, marks={0: (0, 99), 1: (0, 99)})
        self.assertIn(REVERSE, screen.attrs_at(0, 2))
        scrolled: list[tuple[int, ...]] = []
        feed_line = screen._line_feed

        def line_feed() -> None:  # what each row carries as it leaves the screen's top
            if screen.cursor[0] == screen.rows - 1:
                scrolled.extend(screen.attrs_at(0, col) for col in range(WIDTH))
            feed_line()

        screen._line_feed = line_feed  # type: ignore[method-assign]
        region.render(frame, (0, 0), WIDTH, flush=rows_of("one", "two", "three"), screen_rows=5,
                      marks={0: (0, 99), 1: (0, 99)})
        self.assertTrue(scrolled)
        self.assertFalse([attrs for attrs in scrolled if REVERSE in attrs])
        self.assertEqual(screen.scrollback[:2], ["┃ alpha", "┃ beta"])

    def test_a_row_flushed_at_another_width_is_not_mapped(self) -> None:
        region = region_on(VTScreen(8, WIDTH), None)
        region.render([(Span("c"),)], (0, 0), WIDTH, flush=rows_of("alpha"), screen_rows=8)
        self.assertEqual(region.doc_row(0, 8), 0)
        region.render([(Span("c"),)], (0, 0), WIDTH - 5, screen_rows=8)
        self.assertIsNone(region.doc_row(0, 8))
        self.assertIsNone(region.doc_line(0))

    def test_a_clear_paints_a_highlight_above_the_region_back_first(self) -> None:
        screen = VTScreen(8, WIDTH)
        region = region_on(screen, GROUND)
        frame = [(Span("composer"),)]
        region.render(frame, (0, 0), WIDTH, flush=rows_of("alpha", "beta"), screen_rows=8)
        region.render(frame, (0, 0), WIDTH, screen_rows=8, marks={0: (0, 99)})
        self.assertIn(REVERSE, screen.attrs_at(0, 2))
        region.clear(8)  # Ctrl+Z and the exit hand the screen back with this
        self.assertEqual(reversed_count(screen), 0)
        self.assertEqual(screen.lines()[:2], ["┃ alpha", "┃ beta"])

    def test_a_flush_above_at_exit_carries_no_highlight_into_the_scrollback(self) -> None:
        screen = VTScreen(5, WIDTH)
        region = region_on(screen, None)
        frame = [(Span("composer"),)]
        region.render(frame, (0, 0), WIDTH, flush=rows_of("alpha", "beta", "gamma"), screen_rows=5)
        region.render(frame, (0, 0), WIDTH, screen_rows=5, marks={0: (0, 99), 1: (0, 99)})
        scrolled = scroll_watch(screen)
        region.flush_above(rows_of("one", "two", "three"), WIDTH, 5)
        self.assertTrue(scrolled)
        self.assertFalse([attrs for attrs in scrolled if REVERSE in attrs])



class MovedRowsTests(unittest.TestCase):
    """The review's repro (2026-11-05): a notice flushed while a drag on the draft is held put the notice at the draft's
    row numbers, and the release copied the notice's tail, the rule and the draft."""

    def drag_on_the_draft_then(self, rows: int, change) -> tuple[App, list[str]]:  # type: ignore[no-untyped-def]
        app = main_app(rows=rows)
        for index in range(12 if rows < 14 else 0):  # the pinned variant: the region on the screen's last rows
            app.transcript.add_notice(f"earlier {index}")
        drawn(app)
        type_text(app, "DRAFTTEXT here")
        drawn(app)
        row, at = row_of(app, "DRAFTTEXT"), column(app, "DRAFTTEXT")
        press(app, at, row)
        move(app, at + 8, row)
        drawn(app)
        self.assertTrue(reversed_columns(app, row))
        change(app)
        screen = drawn(app)
        release(app, at + 8, row)
        return app, screen

    def test_a_notice_flushed_under_a_held_drag_drops_it_and_copies_nothing(self) -> None:
        for rows in (14, 8):
            with self.subTest(pinned=rows < 14):
                app, screen = self.drag_on_the_draft_then(rows, lambda app: app.transcript.add_notice("NOTICE LINE ONE"))
                self.assertIn("NOTICE LINE ONE", "\n".join(screen))
                self.assertEqual(osc52(app), [])
                self.assertIsNone(app.selection.rows)
                self.assertEqual(reversed_count(app.terminal.screen), 0)  # type: ignore[attr-defined]

    def test_a_row_inserted_inside_the_region_under_a_held_drag_drops_it(self) -> None:
        app, _screen = self.drag_on_the_draft_then(14, lambda app: app.queued.append(QueuedLine("queued prompt")))
        self.assertEqual(osc52(app), [])

    def test_a_drag_over_the_transcript_survives_output_and_a_released_one_goes_at_the_next_flush(self) -> None:
        app = main_app()
        row, text = row_of(app, "first line"), column(app, "first line")
        press(app, text, row)
        move(app, text + 9, row)
        app.transcript.add_notice("output meanwhile")
        drawn(app)
        self.assertTrue(reversed_columns(app, row_of(app, "first line")))
        release(app, text + 9, row)
        self.assertEqual(osc52(app), ["first line"])
        drawn(app)
        self.assertIsNotNone(app.selection.rows)  # shown after the copy
        app.transcript.add_notice("more output")
        drawn(app)
        self.assertIsNone(app.selection.rows)
        self.assertEqual(reversed_count(app.terminal.screen), 0)  # type: ignore[attr-defined]


class TurnTests(unittest.TestCase):
    def test_a_drag_that_overshoots_onto_the_working_rows_during_a_turn_copies_the_reply(self) -> None:
        now = [100.0]
        app = main_app(rows=12, clock=lambda: now[0])
        app.turn_pending = True
        screen = drawn(app)
        self.assertIn("Working", "\n".join(screen))
        first = row_of(app, "first line")
        press(app, column(app, "first line"), first)
        move(app, 60, len(screen))  # the screen's last row: under the working row, the composer and the info line
        for _tick in range(4):  # the working row changes every tick
            now[0] += 1.0
            drawn(app)
            self.assertTrue(reversed_columns(app, row_of(app, "first line")))
        release(app, 60, len(screen))
        self.assertEqual(osc52(app), [REPLY])
        self.assertNotIn("dropped", "\n".join(drawn(app)))

    def test_a_press_on_the_working_row_selects_nothing(self) -> None:
        app = main_app()
        app.turn_pending = True
        drawn(app)
        row = row_of(app, "Working")
        drag(app, (1, row), (40, row))
        self.assertEqual((osc52(app), app.selection.rows), ([], None))

    def test_a_drag_dropped_for_rows_that_changed_says_so(self) -> None:
        app = main_app()
        type_text(app, "DRAFTTEXT here")
        drawn(app)
        row = row_of(app, "DRAFTTEXT")
        press(app, column(app, "DRAFTTEXT"), row)
        move(app, column(app, "DRAFTTEXT") + 5, row)
        app.transcript.add_notice("NOTICE LINE ONE")
        drawn(app)
        self.assertIn("selection dropped: text moved", "\n".join(drawn(app)))

    def test_a_drag_over_rows_that_left_what_the_region_keeps_is_dropped_and_says_so(self) -> None:
        app = main_app()
        row, text = row_of(app, "first line"), column(app, "first line")
        press(app, text, row)
        move(app, text + 9, row)
        for index in range(FLUSHED_KEPT + 20):  # one frame flushes more rows than the region keeps
            app.transcript.add_notice(f"n{index}")
        drawn(app)
        release(app, text + 9, row)
        self.assertEqual(osc52(app), [])
        self.assertIn("selection dropped: text moved", "\n".join(drawn(app)))


    def test_a_copy_whose_notice_moves_the_draft_keeps_saying_it_copied(self) -> None:
        # The review's probe: the region on the bottom rows, a drag over the draft; the copy notice's row moves the
        # composer, so the released selection no longer holds its rows and goes, quietly.
        app = main_app(rows=8)
        for index in range(12):
            app.transcript.add_notice(f"earlier {index}")
        drawn(app)
        type_text(app, "DRAFTTEXT here")
        drawn(app)
        row, at = row_of(app, "DRAFTTEXT"), column(app, "DRAFTTEXT")
        drag(app, (at, row), (at + len("DRAFTTEXT here") - 1, row))
        self.assertEqual(osc52(app), ["DRAFTTEXT here"])
        for _frame in range(3):
            screen = "\n".join(drawn(app))
            self.assertIn(COPIED_NOTE.format(count=14), screen)
            self.assertNotIn("dropped", screen)


class ButtonTests(unittest.TestCase):
    def test_a_press_whose_release_never_comes_stops_holding_esc_once_reports_go_off(self) -> None:
        for leave in ("resize", "suspend"):
            with self.subTest(leave=leave):
                app = main_app()
                row = row_of(app, "first line")
                press(app, 5, row)
                self.assertTrue(app.button_held)
                if leave == "resize":
                    app._on_resize()
                else:
                    app._suspend()
                self.assertFalse(app.button_held)


class ComposerFrameTests(unittest.TestCase):
    def test_a_drag_over_the_composer_copies_the_draft_without_its_rules_mark_or_placeholder(self) -> None:
        app = main_app()
        type_text(app, "the draft")
        screen = drawn(app)
        composer = row_of(app, "the draft")
        drag(app, (1, composer - 1), (60, composer + 1))  # the rule above it to the rule under it
        self.assertEqual(osc52(app), ["the draft"])
        self.assertIn("─" * 10, screen[composer - 2])
        app._on_input(Key(CHAR, "u", ctrl=True))  # an empty composer shows its placeholder
        drawn(app)
        row = row_of(app, "Ask Hermes anything")
        press(app, 1, row)
        move(app, 60, row)
        release(app, 60, row)
        self.assertEqual(osc52(app), ["the draft"])  # nothing more: the placeholder is no text


    def test_the_rules_are_gutters_with_or_without_the_aura(self) -> None:
        for text, phase in (("migrate every service", 0), ("dag ulw migrate every service", 3)):
            with self.subTest(text=text):
                top, _row, bottom = aura_rows(aura_frame(text, cols=60, aura=phase))
                self.assertTrue(all(span.style.gutter for span in (*top, *bottom)))


class CopyKeyTests(unittest.TestCase):
    def test_ctrl_c_right_after_a_drag_only_drops_the_selection(self) -> None:
        app = main_app()
        client = app.client
        app.turn_pending = True
        type_text(app, "keep me")
        drawn(app)
        row = row_of(app, "first line")
        drag(app, (column(app, "first line"), row), (60, row))
        ctrl_c = Key(CHAR, "c", ctrl=True)
        app._on_input(ctrl_c)  # on Windows Terminal or VS Code this is the copy the person meant
        self.assertEqual((client.named("session.interrupt"), app.composer.text, app.exit_armed_at),  # type: ignore[attr-defined]
                         ([], "keep me", None))
        self.assertIsNone(app.selection.rows)
        app._on_input(ctrl_c)  # the next one is Ctrl+C again: the draft goes, then the turn is interrupted
        self.assertEqual(app.composer.text, "")
        app._on_input(ctrl_c)
        self.assertEqual(len(client.named("session.interrupt")), 1)  # type: ignore[attr-defined]


    def test_only_within_the_copy_notices_time_and_never_without_a_copy(self) -> None:
        now = [100.0]
        app = main_app(clock=lambda: now[0])
        ctrl_c = Key(CHAR, "c", ctrl=True)
        row, at = row_of(app, "first line"), column(app, "first line")
        type_text(app, "keep")
        press(app, at, row)
        move(app, 40, row)
        app._on_input(ctrl_c)  # a drag still held copied nothing: Ctrl+C is Ctrl+C, and the draft goes
        self.assertEqual(app.composer.text, "")
        type_text(app, "keep")
        drag(app, (at, row), (40, row))
        self.assertEqual(osc52(app), ["first line of the reply"])
        now[0] += COPY_NOTE_SECONDS
        app._on_input(ctrl_c)  # the copy is 2 s old: Ctrl+C again
        self.assertEqual(app.composer.text, "")


class EscLatencyTests(unittest.TestCase):
    def interrupted(self, reads: list[tuple[float, bytes]], environ: dict[str, str] | None = None) -> bool:
        now = [100.0]
        app = main_app(environ, clock=lambda: now[0])
        app.turn_pending = True
        self.assertTrue(app.terminal.mouse_reporting)  # type: ignore[attr-defined]
        step_through(app, now, reads)
        return bool(app.client.named("session.interrupt"))  # type: ignore[attr-defined]

    def test_a_lone_esc_interrupts_at_the_first_silence_though_reports_are_on(self) -> None:
        self.assertTrue(self.interrupted([(0.0, b"\x1b"), (READ_TIMEOUT_SECONDS, b"")]))

    def test_it_waits_for_a_reports_rest_right_after_a_report_while_a_button_is_held_and_over_ssh(self) -> None:
        silence = [(READ_TIMEOUT_SECONDS, b"")]
        cases = {
            "after a wheel turn": ([(0.0, b"\x1b[<65;5;3M"), (0.1, b"\x1b"), *silence], None),
            "a button held": ([(0.0, b"\x1b[<0;5;30M"), (0.6, b"\x1b"), *silence], None),
            "over ssh": ([(0.0, b"\x1b"), *silence * 3], {"SSH_CONNECTION": "1 2 3 4"}),
        }
        for name, (reads, environ) in cases.items():
            with self.subTest(name):
                self.assertFalse(self.interrupted(reads, environ))
                self.assertTrue(self.interrupted([*reads, *silence * 6], environ))  # 0.3 s on, Esc after all


class SlotAndViewTests(unittest.TestCase):
    def test_while_a_question_is_open_the_wheel_and_an_unmapped_drag_open_the_question_view(self) -> None:
        app = main_app()
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        drawn(app)
        app._on_input(Mouse(WHEEL_UP, 5, 3))
        self.assertEqual(app.pager, app.question_view)
        self.assertIsNotNone(app.pager)

    def test_an_unmapped_drag_with_no_rows_to_show_opens_nothing_and_says_nothing(self) -> None:
        app, _client = make_app(rows=14, cols=60, environ=MOUSE)
        app.terminal.write("shell output\r\n")  # type: ignore[attr-defined]
        app.adopt_cursor_row(2)
        app.transcript.blocks.append(AssistantBlock("\n", model="m"))  # a block with no rows
        drawn(app)
        for _turn in range(3):
            press(app, 3, 1)
            move(app, 9, 1)
            release(app, 9, 1)
            app._on_input(Mouse(WHEEL_UP, 5, 1))
        self.assertIsNone(app.pager)
        self.assertEqual(len(app.transcript.blocks), 1)  # no "Nothing in this session's transcript yet." notice

    def test_the_copy_notice_and_hermes_notice_both_show(self) -> None:
        app = main_app()
        app.notification = Notification("hermes says so", "info", "k")
        row = row_of(app, "first line")
        drag(app, (column(app, "first line"), row), (60, row))
        screen = "\n".join(drawn(app))
        self.assertIn("copied", screen)
        self.assertIn("hermes says so", screen)


class FramedPickerTests(unittest.TestCase):
    """#2573's clarify picker, framed like Claude Code's question: rules above and under it, a key row under them."""

    QUESTION = {"session_id": "s", "questions": [
        {"qid": "q0", "question": "Which color do you prefer?", "choices": ["red (Recommended)", "blue"],
         "multi_select": False}]}

    def picker(self) -> App:
        app = main_app(rows=24)
        app._on_server_request(ServerRequest("srq-1", "clarify", self.QUESTION))
        drawn(app)
        return app

    def test_a_drag_over_the_framed_picker_copies_the_question_and_choices_only(self) -> None:
        app = self.picker()
        screen = drawn(app)
        top = next(index for index, line in enumerate(screen) if "Which color" in line)  # the rule is the row above
        keys = next(index for index, line in enumerate(screen) if "Enter to select" in line) + 1
        self.assertTrue(screen[top - 1].startswith("─"))
        drag(app, (1, top), (60, keys))  # from the top rule through the key row
        self.assertEqual(osc52(app), ["Which color do you prefer?\n\n1. red (Recommended)\n2. blue\n3. Type something."])
        highlighted = [reversed_columns(app, row + 1) for row in (top - 1, keys - 2, keys - 1)]
        self.assertEqual(highlighted, [[], [], []])  # the rules and the key row are never highlighted

    def test_its_frame_paints_the_bytes_it_did_before_it_was_a_gutter(self) -> None:
        # The bar beside the context and the "more choices" marker share one look: one SGR run each row, as before the
        # bar and the marker became gutters (`style.joins`), so OMH_TUI_MOUSE=0 writes the bytes it always wrote.
        context = {"qid": "q0", "question": "Some context first.\nWhich one?", "choices": ["red", "blue"],
                   "multi_select": False}
        many = {"qid": "q0", "question": "Which one?", "choices": [f"choice {n}" for n in range(30)],
                "multi_select": False}
        for question, painted, copied_not in ((context, r"\x1b\[[0-9;]*m▌ Some context first\.\x1b\[0m", "▌"),
                                              (many, r"\x1b\[[0-9;]*m▌   … \+\d+ more choices", "more choices")):
            for rows, cols in ((24, 60), (30, 80)):
                with self.subTest(question=question["question"][:10], rows=rows, cols=cols):
                    app = main_app(NATIVE, rows=rows, cols=cols)
                    app._on_server_request(ServerRequest("srq-1", "clarify", {"session_id": "s", "questions": [question]}))
                    drawn(app)
                    self.assertRegex("".join(app.terminal.writes), painted)  # type: ignore[attr-defined]
                    mouse = main_app(rows=rows, cols=cols)  # the same picker where the main screen takes the mouse
                    mouse._on_server_request(ServerRequest("srq-1", "clarify", {"session_id": "s", "questions": [question]}))
                    screen = drawn(mouse)
                    last = max(index for index, line in enumerate(screen) if line.startswith("▌")) + 1
                    drag(mouse, (1, row_of(mouse, "Which one")), (cols, last))
                    self.assertNotIn(copied_not, osc52(mouse)[0])

    def test_the_wheel_while_it_is_open_opens_the_question_view_without_its_key_row_or_rules(self) -> None:
        app = self.picker()
        app._on_input(Mouse(WHEEL_UP, 5, 3))
        self.assertIs(app.pager, app.question_view)
        page = "\n".join(drawn(app))
        self.assertIn("Which color do you prefer?", page)
        self.assertNotIn("Enter to select", page)
        self.assertNotIn("─" * 20, page)

    def test_during_a_turn_it_copies_too_and_its_key_rows_clock_never_drops_a_drag(self) -> None:
        # While a framed question waits, `_tail` draws no working row (its key row carries the wait's clock), so the
        # picker is a stable row a drag may hold during the turn as well; the clock moving is a gutter's change.
        now = [100.0]
        app = main_app(rows=24, clock=lambda: now[0])
        app.turn_pending = True
        app._on_server_request(ServerRequest("srq-1", "clarify", self.QUESTION))
        screen = drawn(app)
        self.assertFalse([line for line in screen if "Working" in line])
        keys = next(index for index, line in enumerate(screen) if "Enter to select" in line) + 1
        press(app, 1, row_of(app, "Which color"))
        move(app, 60, keys)
        for _minute in range(3):
            now[0] += 61.0
            drawn(app)
        release(app, 60, keys)
        self.assertEqual(osc52(app), ["Which color do you prefer?\n\n1. red (Recommended)\n2. blue\n3. Type something."])


class DefaultAgentListTests(unittest.TestCase):
    def test_a_list_click_selects_nothing_and_the_wheel_over_the_list_opens_nothing(self) -> None:
        app, _client = agent_app(environ=MOUSE)
        app.transcript.add_user("explain it")  # a transcript the wheel elsewhere would open
        app._on_input(CTRL_L)
        drawn(app)
        app._on_input(Key(DOWN))
        drawn(app)
        row = row_of(app, SECOND_ROW)
        app._on_input(Mouse(WHEEL_UP, 5, row))
        self.assertIsNone(app.pager)
        app._on_input(Mouse(WHEEL_UP, 5, 1))  # above the list it does
        self.assertIsNotNone(app.pager)
        app._on_input(Key(CHAR, "q"))
        drawn(app)
        click(app, 5, row)
        move(app, 30, row)
        release(app, 30, row)
        self.assertIsNotNone(app.pager)
        self.assertIsNone(app.selection.rows)
        app._on_input(Key(CHAR, "q"))
        drawn(app)
        self.assertEqual(reversed_count(app.terminal.screen), 0)  # type: ignore[attr-defined]


class ResizeTests(unittest.TestCase):
    def test_after_a_resize_the_exit_paints_nothing_back_at_the_reflowed_rows(self) -> None:
        app = main_app()
        row, text = row_of(app, "first line"), column(app, "first line")
        press(app, text, row)
        move(app, text + 9, row)
        drawn(app)
        app.terminal.screen.resize(14, 50)  # type: ignore[attr-defined]
        app._on_resize()
        writes = app.terminal.writes  # type: ignore[attr-defined]
        start = len(writes)
        app._shutdown()
        self.assertNotIn(cursor_at(row - 1, 0), "".join(writes[start:]))  # the highlighted row is not painted back


class ExitTests(unittest.TestCase):
    def test_the_exit_with_a_highlight_above_the_region_leaves_none_on_the_screen(self) -> None:
        app = main_app()
        row, text = row_of(app, "first line"), column(app, "first line")
        press(app, text, row)
        move(app, text + 9, row)
        drawn(app)
        self.assertTrue(reversed_columns(app, row))
        app._shutdown()
        self.assertEqual(reversed_count(app.terminal.screen), 0)  # type: ignore[attr-defined]


def answering_cursor_requests(terminal) -> None:  # type: ignore[no-untyped-def]
    """The scripted terminal answers a cursor position request at its next read, as a terminal does."""
    answers: list[bytes] = []
    write, read = terminal.write, terminal.read

    def answering_write(text: str) -> None:
        write(text)
        if CURSOR_POSITION_REQUEST in text:
            answers.append(b"\x1b[24;1R")

    def answering_read(timeout: float, wake: int | None = None) -> bytes:
        return answers.pop(0) if answers else read(timeout, wake)

    terminal.write, terminal.read = answering_write, answering_read


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class RealLoopTests(AppTestCase):
    def test_in_the_real_loop_sgr_reports_drag_copy_without_the_rail_and_the_wheel_opens_the_view(self) -> None:
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()),
                           env={"OMH_TUI_MOUSE": "1", "TERM": "xterm-kitty"})
        terminal = run.terminal
        drag = Step(capture="dragged", label="a drag over the typed prompt")
        aimed: list[int] = []

        def aim() -> bool:
            """Over the prompt the person sent, from its rail's cell to the row's end (a report counts from 1)."""
            if not (terminal.mouse_reporting and terminal.mouse_drag):
                return False
            rows = terminal.screen.lines()
            found = [index for index, row in enumerate(rows) if "❯ copy me" in row and row.startswith("┃")]
            if not found:
                return False
            y = found[0] + 1
            aimed.append(y)
            drag.data = f"\x1b[<0;1;{y}M\x1b[<32;40;{y}M\x1b[<0;40;{y}m".encode("ascii")
            return True

        drag.when = aim
        terminal.script(
            Step(b"\x0c", when=terminal.idle, label="the first frame"),
            Step(b"copy me\r", when=lambda: terminal.mouse_reporting, label="a prompt"),
            drag,
            Step(b"\x1b[<64;5;3M", when=lambda: bool(terminal.screen.osc), label="the wheel up"),
            Step(b"q", when=lambda: terminal.screen.alternate, capture="view", label="the transcript view"),
            Step(b"\x04", when=lambda: not terminal.screen.alternate, label="the end"),
        )
        self.run_main(run)
        copies = [text for text in terminal.screen.osc if text.startswith("52;c;")]
        self.assertEqual([base64.b64decode(text[5:].rstrip("\x07")).decode() for text in copies], ["❯ copy me"])
        self.assertIn("copy me", "\n".join(terminal.captures["view"]))
        self.assertTrue(aimed)


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class DefaultMousePromptSlotTests(AppTestCase):
    """`PromptSlotTests`' questions in the real loop with the main screen taking the mouse: a question arms after
    `REPORTING_SLOT_ARM_SECONDS`, since reports are on as it opens."""

    approval_run = PromptSlotTests.approval_run
    assert_denied = PromptSlotTests.assert_denied

    def test_an_approval_opens_a_slot_and_d_sends_the_explicit_deny(self) -> None:
        PromptSlotTests.test_an_approval_opens_a_slot_and_d_sends_the_explicit_deny(self)  # type: ignore[arg-type]

    def test_esc_on_an_approval_sends_the_explicit_deny(self) -> None:
        PromptSlotTests.test_esc_on_an_approval_sends_the_explicit_deny(self)  # type: ignore[arg-type]

    def test_up_then_enter_on_an_armed_approval_still_denies(self) -> None:
        PromptSlotTests.test_up_then_enter_on_an_armed_approval_still_denies(self)  # type: ignore[arg-type]

    def test_a_clarify_choice_is_picked_by_its_number(self) -> None:
        PromptSlotTests.test_a_clarify_choice_is_picked_by_its_number(self)  # type: ignore[arg-type]

    def test_a_typed_clarify_answer_never_enters_the_input_history(self) -> None:
        PromptSlotTests.test_a_typed_clarify_answer_never_enters_the_input_history(self)  # type: ignore[arg-type]

    def prepare(self, scenario: Scenario, *, rows: int = 24, cols: int = 80, env: dict | None = None):  # type: ignore[no-untyped-def,override]
        return super().prepare(scenario, rows=rows, cols=cols, env={"OMH_TUI_MOUSE": "1", **(env or {})})

    def armed(self, run, label: str):  # type: ignore[no-untyped-def]
        return lambda: time.monotonic() - run.terminal.fired[label] > REPORTING_SLOT_ARM_SECONDS + 0.05


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class DefaultMouseExitTests(AppTestCase):
    def test_the_exit_drains_late_reports_up_to_the_cursor_answer_and_is_quick(self) -> None:
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()),
                           env={"OMH_TUI_MOUSE": "1"})
        answering_cursor_requests(run.terminal)
        run.terminal.script(Step(b"\x04", when=lambda: run.terminal.idle() and run.terminal.mouse_reporting,
                                 label="exit"))
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertIn(CURSOR_POSITION_REQUEST, "".join(run.terminal.writes))  # reports were on: the drain ran
        self.assertLess(run.terminal.exited_at - run.terminal.fired["exit"], 0.5)


if __name__ == "__main__":
    unittest.main()
