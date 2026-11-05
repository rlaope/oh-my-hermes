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
resize drops the selection without painting at rows the terminal reflowed. The
highlight is painted back exactly as the rows were flushed, the scene look's
ground included, and never scrolls into the scrollback.

Where a report lands is read from the VT screen the scripted terminal
painted, as `tests/test_tui_agent_mouse.py` reads it: columns and rows from 1.
"""

from __future__ import annotations

import base64
import unittest

from _tui_gateway_replay import Scenario, spans
from _vt_screen import VTScreen
from test_tui_agent_mouse import SECOND_ROW, click
from test_tui_agent_view import agent_app
from test_tui_app import NO_TERMIOS, AppTestCase, Step, startup_answers
from test_tui_clean_copy import osc52, row_of
from test_tui_modes import drawn, make_app, type_text
from omh.tui import terminal as terminal_module
from omh.tui.app import COPIED_NOTE, COPY_NOTE_SECONDS, App
from omh.tui.keys import BUTTON_LEFT, CHAR, DOWN, WHEEL_DOWN, WHEEL_UP, Key, Mouse
from omh.tui.pager import HistoryPager, reversed_cells
from omh.tui.screen import LiveRegion, _flushed_row
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

    def test_a_drag_carried_under_the_region_ends_on_its_last_row(self) -> None:
        app = main_app()
        screen = drawn(app)
        last = max(index for index, line in enumerate(screen) if line) + 1
        drag(app, (1, row_of(app, "second line")), (60, len(screen)))
        (copied,) = osc52(app)
        self.assertTrue(copied.startswith("second line"), copied)
        self.assertTrue(copied.endswith(screen[last - 1].strip()), copied)

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

    def test_rows_inserted_inside_the_region_carry_the_selection_down_with_them(self) -> None:
        region = region_on(VTScreen(12, WIDTH), None)
        region.render([(Span("a"),), (Span("b"),)], (0, 0), WIDTH, screen_rows=12)
        region.render([(Span("a"),), (Span("new"),), (Span("b"),)], (0, 0), WIDTH, screen_rows=12, marks={1: (0, 0)})
        self.assertEqual(region.inserted_rows, (1, 1))
        self.assertEqual(region._shown[2], reversed_cells((Span("b"),), 0, 0))


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


if __name__ == "__main__":
    unittest.main()
