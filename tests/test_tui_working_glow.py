"""The working glow (owner request 2026-10-28): a light with a fading trail goes round the terminal's whole screen
while a turn runs (`omh.tui.edge_glow`), painted over the screen's edge by the live region (`screen.LiveRegion`)
and taken off before anything scrolls, so nothing of it reaches the scrollback."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from _vt_screen import VTScreen
from omh.tui.edge_glow import (
    BOTTOM,
    EDGE_MARGIN,
    LEFT,
    LOOP_SECONDS,
    NOSE,
    RIGHT,
    TICK_SECONDS,
    TOP,
    _cells,
    brightness,
    edge,
    edge_fits,
)
from omh.tui.gateway import Event
from omh.tui.keys import CHAR, ENTER, Key
from omh.tui.screen import LiveRegion
from omh.tui.style import Span
from omh.skin_pack import (
    THEME_STORE_SCHEMA,
    default_theme,
    read_glow_choice,
    read_launch_choice,
    theme_store_path,
    write_glow_choice,
    write_launch_choice,
)
from omh.tui.theme import theme_named, with_catch_colours
from test_tui_modes import make_app, notices

GLYPHS = set("▀▄▌▐▛▜▟▙")
GLOW_ON = {"COLORTERM": "truecolor", "TERM": "xterm-256color", "OMH_TUI_GLOW": "1"}
BACKGROUND = "#222733"


class Clock:
    def __init__(self, at: float) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at


def glowing_theme(background: str | None = BACKGROUND):
    return with_catch_colours(theme_named("default", background), default_theme(), background, "spectrum")


def lit(line) -> list[int]:
    """The cells of a row a glow paints, by column."""
    cells: list[int] = []
    col = 0
    for span in line:
        for _ in span.text:
            if span.style.fg is not None or span.style.bg is not None:
                cells.append(col)
            col += 1
    return cells


class EdgeShapeTests(unittest.TestCase):
    def test_the_way_round_runs_through_the_middle_of_what_each_cell_lights(self) -> None:
        cells, around = _cells(20, 8)
        self.assertEqual(around, 2 * ((20 - 1) + (2 * 8 - 1)))
        where = {(row, col): at for row, col, _glyph, at in cells}
        self.assertEqual(len(where), 2 * 20 + 2 * (8 - 2))  # every edge cell once
        # Along the top a cell is a cell width on; down a side a row is two; turning a corner is 2.5 both ways, the
        # top row's upper half to the middle of the side's first cell: the same distance it looks, so no jump.
        self.assertEqual(where[0, 5] - where[0, 4], 1)
        self.assertEqual(where[3, 19] - where[2, 19], 2)
        self.assertEqual(where[1, 19] - where[0, 19], 2.5)
        self.assertEqual(where[7, 19] - where[6, 19], 2.5)
        self.assertEqual(where[7, 0] - where[6, 0], -2.5)
        self.assertEqual(around - where[1, 0], 2.5)

    def test_the_head_glides_round_corners_without_a_jump(self) -> None:
        theme = glowing_theme()
        cols, rows = 30, 10
        cells, around = _cells(cols, rows)
        where = {(row, col): at for row, col, _glyph, at in cells}
        previous = None
        steps = 400
        for step in range(steps):
            moment = edge(cols, rows, theme, step * LOOP_SECONDS / steps)
            brightest = max(where, key=lambda at: self._level(moment, at, cols))
            if previous is not None:
                moved = (where[brightest] - where[previous]) % around
                self.assertLessEqual(moved, 2.5, f"the head jumped {moved} cells at step {step}")
            previous = brightest

    @staticmethod
    def _level(moment, at, cols) -> float:
        row, col = at
        span: Span
        if row == 0 or row == len(moment.left) + 1:
            line = moment.top if row == 0 else moment.bottom
            at_col = 0
            for span in line:
                if at_col <= col < at_col + len(span.text):
                    break
                at_col += len(span.text)
        else:
            (span,) = (moment.left if col == 0 else moment.right)[row - 1]
        colour = span.style.bg if span.style.bg is not None and span.text == " " else span.style.fg
        if colour is None:
            return 0.0
        return sum(int(colour[index:index + 2], 16) for index in (1, 3, 5))

    def test_only_the_light_and_its_trail_are_drawn_no_box(self) -> None:
        theme = glowing_theme()
        moment = edge(110, 30, theme, 0.0)
        drawn = len(lit(moment.top)) + len(lit(moment.bottom)) + sum(
            bool(lit(line)) for line in (*moment.left, *moment.right))
        self.assertGreater(drawn, 0)
        self.assertLess(drawn, 0.4 * (2 * 110 + 2 * 28))  # the trail is under a third of the way round, the rest blank

    def test_the_head_is_round_a_circle_rising_ahead_of_it(self) -> None:
        self.assertEqual(brightness(0.0, 100), 1.0)
        ahead = [brightness(-distance, 100) for distance in (0.5, 1.5, 2.5, NOSE)]
        self.assertEqual(ahead, sorted(ahead, reverse=True))
        self.assertGreater(ahead[0], 0.95)  # a circle is flat at its top: round, not a point
        self.assertEqual(ahead[-1], 0.0)
        self.assertGreater(brightness(10, 100), brightness(40, 100))  # the trail fades behind it
        self.assertEqual(brightness(100, 100), 0.0)

    def test_the_sides_are_whole_cells_where_the_background_is_known_else_half_blocks(self) -> None:
        known = edge(40, 12, glowing_theme(), 1.6)  # the head on the right side
        unknown = edge(40, 12, glowing_theme(None), 1.6)
        sides = [span for line in (*known.right, *known.left) for span in line if span.style.bg is not None]
        self.assertTrue(sides)
        self.assertTrue(all(span.text == " " and span.style.fg is None for span in sides))
        drawn = [span for line in (*unknown.right, *unknown.left) for span in line if span.style.fg is not None]
        self.assertTrue(drawn)
        self.assertTrue(all(span.text in (LEFT, RIGHT) and span.style.bg is None for span in drawn))
        top = [span for span in (*unknown.top, *unknown.bottom) if span.style.fg is not None]
        self.assertTrue(all(set(span.text) <= {TOP, BOTTOM, *"▛▜▟▙"} and span.style.bg is None for span in top))

    def test_a_small_screen_has_no_glow(self) -> None:
        self.assertTrue(edge_fits(20, 8))
        self.assertFalse(edge_fits(19, 30))
        self.assertFalse(edge_fits(80, 7))


class RegionMarginTests(unittest.TestCase):
    def test_a_footer_is_the_regions_own_and_every_count_leaves_it_out(self) -> None:
        screen = VTScreen(10, 30)
        region = LiveRegion(screen.feed, at_top=True, margin=EDGE_MARGIN, footer=True)
        region.render([(Span("one"),), (Span("two"),)], (1, 3), 28, screen_rows=9)
        self.assertEqual(region.height, 2)
        self.assertEqual(region.top_row(9), 0)
        self.assertEqual(region.last_row(9), 1)
        self.assertEqual(screen.lines()[:3], [" one", " two", ""])
        self.assertEqual(screen.cursor, (1, 1 + 3))  # the caret, a margin in

    def test_flushed_rows_keep_the_margin(self) -> None:
        screen = VTScreen(10, 30)
        region = LiveRegion(screen.feed, at_top=True, margin=EDGE_MARGIN, footer=True)
        region.render([(Span("live"),)], None, 28, flush=[(Span("a"),), (Span("b"),)], screen_rows=9)
        self.assertEqual(screen.lines()[:3], [" a", " b", " live"])


class AppGlowTests(unittest.TestCase):
    def app(self, environ=GLOW_ON, rows=20, cols=60):
        clock = Clock(1000.0)
        app, _client = make_app(rows=rows, cols=cols, clock=clock, environ=environ)
        app.background = BACKGROUND
        app.theme = app._themed()
        app.region = app._new_region(at_top=True)
        return app, clock

    def busy(self, app, clock, flushes: int = 12) -> None:
        def event(kind, **payload):
            app.transcript.apply(Event(type=kind, session_id=app.sid, payload=dict(payload)))

        app.transcript.add_user("run the tests")
        app.turn_pending = True
        for index in range(flushes):  # finished replies, flushed above the region, enough to scroll the screen
            event("message.start")
            event("tool.start", tool_id=f"t{index}", name="read_file", context=f"src/file_{index}.py")
            event("tool.complete", tool_id=f"t{index}", name="read_file", result={"ok": True}, duration_s=0.1)
            event("message.complete", text=f"step {index} read")
            clock.at += 0.3
            app._render()

    def test_the_screen_keeps_its_edge_for_the_glow(self) -> None:
        app, _clock = self.app()
        self.assertTrue(app._edged())
        self.assertEqual(app.screen, (60, 20))
        self.assertEqual(app.size, (60 - 2 * EDGE_MARGIN, 20 - 1))
        self.assertEqual(app._margin(), EDGE_MARGIN)

    def test_no_glow_with_it_off_with_reduced_motion_or_without_truecolor(self) -> None:
        for environ in ({**GLOW_ON, "OMH_TUI_GLOW": "0"}, {**GLOW_ON, "OMH_TUI_REDUCED_MOTION": "1"},
                        {"TERM": "xterm-256color", "OMH_TUI_GLOW": "1"}):
            with self.subTest(environ=environ):
                app, clock = self.app(environ)
                self.assertFalse(app._edged())
                self.assertEqual(app.size, app.screen)
                self.busy(app, clock)
                self.assertIsNone(app._edge())
                screen = app.terminal.screen
                self.assertFalse(any(set(line) & GLYPHS for line in screen.history()))

    def test_a_turn_draws_the_light_on_the_edge_and_nothing_of_it_reaches_the_scrollback(self) -> None:
        app, clock = self.app()
        self.busy(app, clock)
        screen = app.terminal.screen
        self.assertGreater(len(screen.scrollback), 0, "the turn's output scrolled")
        self.assertFalse(any(set(line) & GLYPHS for line in screen.scrollback))
        on_top = on_bottom = on_sides = False
        for _ in range(int(LOOP_SECONDS / TICK_SECONDS)):  # once round
            clock.at += TICK_SECONDS
            app._render()
            self.assertFalse(any(set(line) & GLYPHS for line in screen.scrollback))
            lines = screen.lines()
            on_top = on_top or bool(set(lines[0]) & GLYPHS)
            on_bottom = on_bottom or bool(set(lines[-1]) & GLYPHS)
            on_sides = on_sides or any(screen.attrs_at(row, col) for row in range(1, 19) for col in (0, 59))
        self.assertTrue(on_top and on_bottom and on_sides, (on_top, on_bottom, on_sides))
        self.assertEqual(app._tick_seconds(), TICK_SECONDS)

    def test_the_glow_goes_when_the_turn_ends_and_the_rows_are_whole_again(self) -> None:
        app, clock = self.app()
        self.busy(app, clock)
        app.transcript.apply(Event(type="message.complete", session_id=app.sid, payload={"text": "done"}))
        app.turn_pending = False
        clock.at += 1
        app._render()
        screen = app.terminal.screen
        self.assertFalse(any(set(line) & GLYPHS for line in screen.history()))
        for row in range(20):
            self.assertEqual(screen.attrs_at(row, 0), (), f"row {row}'s first column is blank")
        self.assertIn("done", "\n".join(screen.lines()))
        self.assertNotEqual(app._tick_seconds(), TICK_SECONDS)

    def once_round(self, app, clock) -> tuple[bool, bool, bool]:
        """Whether the light reached the top row, the last row and the sides over one loop; nothing of it scrolls."""
        screen = app.terminal.screen
        on_top = on_bottom = on_sides = False
        for _ in range(int(LOOP_SECONDS / TICK_SECONDS)):
            clock.at += TICK_SECONDS
            app._render()
            self.assertFalse(any(set(line) & GLYPHS for line in screen.scrollback))
            lines = screen.lines()
            on_top = on_top or bool(set(lines[0]) & GLYPHS)
            on_bottom = on_bottom or bool(set(lines[-1]) & GLYPHS)
            on_sides = on_sides or any(screen.attrs_at(row, col) for row in range(1, 19) for col in (0, 59))
        return on_top, on_bottom, on_sides

    def test_a_short_session_glows_too_over_the_blank_rows_under_it(self) -> None:
        app, clock = self.app()
        self.busy(app, clock, flushes=1)
        last = app.region.last_row(app.size[1])
        self.assertIsNotNone(last)
        self.assertLess(last, app.size[1] - 1, "the session is shorter than the screen")
        self.assertEqual(self.once_round(app, clock), (True, True, True))
        app.transcript.apply(Event(type="message.complete", session_id=app.sid, payload={"text": "done"}))
        app.turn_pending = False
        clock.at += 1
        app._render()
        screen = app.terminal.screen
        for row in range(20):
            self.assertEqual((screen.attrs_at(row, 0), screen.attrs_at(row, 59)), ((), ()), f"row {row}'s edge is blank")
        self.assertEqual(screen.lines()[-1], "")

    def test_the_top_rows_text_shows_wherever_the_light_is_not(self) -> None:
        app, clock = self.app()
        self.busy(app, clock, flushes=1)
        screen = app.terminal.screen
        top = app.region.top_row(app.size[1])
        reference = app.region._under(top)  # the flushed row on the screen's top row
        shown = set()
        for _ in range(int(LOOP_SECONDS / TICK_SECONDS)):
            clock.at += TICK_SECONDS
            app._render()
            row = screen.lines()[0]
            lit = {col for col in range(60) if set(row[col:col + 1]) & GLYPHS}
            shown.add(len(lit) > 0)
            plain = VTScreen(20, 60)
            plain.feed(" " * EDGE_MARGIN + reference)
            expected = plain.lines()[0]
            self.assertTrue(expected.strip(), "the top row has text")
            for col in range(1, 59):
                if col not in lit:
                    self.assertEqual(row[col:col + 1] or " ", expected[col:col + 1] or " ", f"column {col}: {row!r}")
        self.assertEqual(shown, {True, False}, "the light was on the top row for part of the loop and off it for part")

    def test_a_bands_background_stops_short_of_the_right_margin_as_of_the_left(self) -> None:
        app, _clock = self.app()
        for prompt in ("first question", "second question"):  # prompts flushed above the region, each on a band
            app.transcript.add_user(prompt)
            app.transcript.apply(Event(type="message.start", session_id=app.sid, payload={}))
            app.transcript.apply(Event(type="message.complete", session_id=app.sid, payload={"text": "an answer"}))
            app._render()
        screen = app.terminal.screen

        def background(row, col) -> bool:
            return 48 in screen.attrs_at(row, col)  # SGR 48: a background colour

        banded = [row for row in range(20) if background(row, 2)]
        self.assertEqual(len(banded), 2, screen.lines())
        for row in banded:
            self.assertEqual([col for col in range(60) if background(row, col)], list(range(1, 59)), f"row {row}")

    def test_glow_off_and_on_keeps_the_choice_and_lays_the_session_out_again(self) -> None:
        home = Path(tempfile.mkdtemp(prefix="omh-glow-test-")) / ".omh"
        app, clock = self.app({**GLOW_ON, "OMH_HOME": str(home)})
        for char in "/glow off":
            app._on_input(Key(CHAR, char))
        app._on_input(Key(ENTER))
        self.assertFalse(app._edged())
        self.assertEqual(app.size, app.screen)
        self.assertIs(read_glow_choice(home), False)
        self.assertIn(f"Working glow off, kept in {theme_store_path(home)}.", notices(app))
        self.busy(app, clock)
        self.assertIsNone(app._edge())
        self.assertFalse(any(set(line) & GLYPHS for line in app.terminal.screen.history() + app.terminal.screen.lines()))
        reopened, _clock = self.app({**GLOW_ON, "OMH_HOME": str(home)})
        self.assertFalse(reopened._edged(), "the saved choice holds in the next session")
        app._glow("")  # alone, it switches
        self.assertTrue(app._edged())
        self.assertEqual(app.size, (60 - 2 * EDGE_MARGIN, 20 - 1))
        self.assertIs(read_glow_choice(home), True)

    def test_glow_on_says_what_still_holds_it_off(self) -> None:
        app, _clock = self.app({**GLOW_ON, "OMH_TUI_GLOW": "0"})
        app._glow("on")
        self.assertFalse(app._edged())
        self.assertTrue(any("OMH_TUI_GLOW=0" in notice for notice in notices(app)))
        app._glow("maybe")
        self.assertTrue(any("/glow on" in notice for notice in notices(app)))

    def test_mouse_columns_count_from_the_margin(self) -> None:
        app, _clock = self.app()
        self.assertEqual(app._margin(), 1)
        app_off, _ = self.app({**GLOW_ON, "OMH_TUI_GLOW": "0"})
        self.assertEqual(app_off._margin(), 0)

    def test_the_glow_follows_the_launch_look(self) -> None:
        spectrum = glowing_theme()
        gold = with_catch_colours(theme_named("default", BACKGROUND), default_theme(), BACKGROUND, "gold")
        self.assertNotEqual(spectrum.glow_ring, gold.glow_ring)


class GlowStoreTests(unittest.TestCase):
    def test_the_glow_is_kept_beside_the_launch_look_and_neither_write_drops_the_other(self) -> None:
        home = Path(tempfile.mkdtemp()) / ".omh"
        self.assertIsNone(read_glow_choice(home))
        write_launch_choice(home, "gold")
        write_glow_choice(home, False)
        self.assertEqual(read_launch_choice(home), "gold")
        write_launch_choice(home, "violet")
        self.assertIs(read_glow_choice(home), False)
        record = json.loads(theme_store_path(home).read_text(encoding="utf-8"))
        self.assertEqual(record, {"schema_version": THEME_STORE_SCHEMA, "launch": "violet", "glow": "off"})


if __name__ == "__main__":
    unittest.main()
