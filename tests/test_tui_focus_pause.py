"""The ambience holds still while the terminal window does not have focus (owner decision D1, 2026-11-03).

`Terminal` asks for focus reports (mode 1004); `KeyDecoder` reads `ESC[O` and `ESC[I` as no key and keeps when focus
went (`unfocused_at`). While it is gone, the living wallpaper's idle tick is not scheduled and the working glow's
light holds where it was, so nothing wakes the loop or is written for them; the spinner and the rest of a running
turn's frame go on. With focus back, the first frame is the one a never-paused session draws at that time.
"""

from __future__ import annotations

import unittest
from unittest import mock

from omh.tui import app as app_module
from omh.tui.composer import VIM_NORMAL, Composer
from omh.tui.keys import ESCAPE, Key, KeyDecoder, Paste
from omh.tui.gateway import Event
from omh.tui.wallpaper import SCENES, Cell
from test_tui_keys import decode, decode_split_everywhere
from test_tui_modes import type_text
import test_tui_wallpaper as wallpaper_tests
import test_tui_working_glow as glow_tests

FOCUS_IN = b"\x1b[I"
FOCUS_OUT = b"\x1b[O"


def moving(look, cols, rows, seconds, light):
    """One glyph walking along a blank row of the screen, a step every quarter second."""
    return (Cell(rows - 6, int(seconds * 4) % cols, wallpaper_tests.MARK, "#445566"),)


def screen_state(app) -> tuple:
    """Every row's text and every cell's attributes: what the person sees."""
    screen = app.terminal.screen
    return tuple(screen.lines()), tuple(tuple(screen.attrs_at(row, col) for col in range(screen.cols))
                                        for row in range(screen.rows))


def written(app) -> int:
    return sum(len(text.encode()) for text in app.terminal.writes)


class FocusReportDecodeTests(unittest.TestCase):
    def test_a_focus_report_is_no_key_and_says_when_focus_went(self) -> None:
        for data in (FOCUS_IN, FOCUS_OUT, FOCUS_OUT + FOCUS_IN):
            with self.subTest(data=data):
                self.assertEqual(decode_split_everywhere(self, data), [])
        clock = wallpaper_tests.Clock(5.0)
        decoder = KeyDecoder(clock)
        self.assertIsNone(decoder.unfocused_at, "focused until the terminal says otherwise")
        self.assertEqual(decoder.feed(FOCUS_OUT), [])
        self.assertEqual(decoder.unfocused_at, 5.0)
        clock.at = 9.0
        self.assertEqual(decoder.feed(FOCUS_IN), [])
        self.assertIsNone(decoder.unfocused_at)

    def test_keys_around_a_report_stay_keys_and_any_key_means_focus(self) -> None:
        self.assertEqual(decode(b"a" + FOCUS_OUT + b"b"), [Key("char", "a"), Key("char", "b")])
        decoder = KeyDecoder()
        decoder.feed(FOCUS_OUT)
        self.assertIsNotNone(decoder.unfocused_at)
        self.assertEqual(decoder.feed(b"x"), [Key("char", "x")])
        self.assertIsNone(decoder.unfocused_at, "a focus-in the terminal never sent does not outlast the next key")

    def test_a_held_escape_is_escape_and_a_report_split_after_its_escape_is_still_no_key(self) -> None:
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1b"), [])
        self.assertEqual([key.name for key in decoder.feed(FOCUS_OUT)], [ESCAPE])  # Esc, then focus went
        self.assertIsNotNone(decoder.unfocused_at)
        decoder = KeyDecoder()
        self.assertEqual(decoder.feed(b"\x1b") + decoder.feed(b"[O") + decoder.flush(), [])
        self.assertIsNotNone(decoder.unfocused_at)

    def test_an_unmarked_paste_stays_one_paste_around_a_report(self) -> None:
        # In the paste's own read, and as a read of its own inside the burst window: never Enter, never split.
        for reads in ((b"one\rtwo\rthree\r" + FOCUS_OUT,), (b"one\rtwo\r", FOCUS_OUT, b"three\r")):
            with self.subTest(reads=reads):
                clock = wallpaper_tests.Clock(5.0)
                decoder = KeyDecoder(clock)
                events = []
                for data in reads:
                    events += decoder.feed(data)
                    if data == reads[-1] or FOCUS_OUT in data:
                        self.assertEqual(decoder.unfocused_at is not None, FOCUS_OUT in data, data)
                    clock.at += 0.005
                clock.at += 1.0
                self.assertEqual(events + decoder.flush(), [Paste("one\ntwo\nthree\n")])

    def test_a_report_inside_a_bracketed_paste_is_not_pasted(self) -> None:
        start, end = b"\x1b[200~hello ", b"world\x1b[201~"
        for reads in ((start, FOCUS_OUT, end), (start + FOCUS_OUT + end,)):
            with self.subTest(reads=reads):
                decoder = KeyDecoder()
                events = []
                for data in reads:
                    events += decoder.feed(data)
                    if FOCUS_OUT in data:  # a later read of the paste's rest is input again
                        self.assertIsNotNone(decoder.unfocused_at)
                self.assertEqual(events, [Paste("hello world")])


class FocusInputTests(unittest.TestCase):
    def test_a_focus_report_never_reaches_the_composer_in_any_mode(self) -> None:
        def plain(app):
            type_text(app, "draft")

        def vim_insert(app):
            app.composer = Composer(vim=True)
            type_text(app, "draft")

        def vim_normal(app):
            vim_insert(app)
            app._on_input(Key(ESCAPE))
            self.assertEqual(app.composer.vim_label, VIM_NORMAL)

        def mouse_on(app):
            plain(app)
            app.terminal.mouse_reporting = True

        for name, setup in (("plain", plain), ("vim insert", vim_insert), ("vim normal", vim_normal),
                            ("mouse reporting", mouse_on)):
            with self.subTest(mode=name):
                app, clock = wallpaper_tests.AppWallpaperTests.app(self)
                setup(app)
                before = (app.composer.text, app.composer.caret)
                with mock.patch.object(app, "_on_input") as on_input:
                    for data in (FOCUS_OUT, FOCUS_IN, FOCUS_OUT + FOCUS_IN, b"\x1b", b"[O", b"\x1b[", b"I"):
                        app._take_input(data)
                    clock.at += 1.0
                    app._take_input(b"")  # a silence: anything held settles
                on_input.assert_not_called()
                self.assertEqual((app.composer.text, app.composer.caret), before)


class IdleWallpaperTests(unittest.TestCase):
    def app(self):
        self.enterContext(mock.patch.object(app_module, "scene", moving))
        app, clock = wallpaper_tests.AppWallpaperTests.app(self, rows=42, cols=150)
        app.launch_look = "moonlit"
        app.dirty = True
        app._render_when_due()
        return app, clock

    def test_out_of_focus_no_tick_wakes_the_loop_or_writes_and_focus_back_draws_the_never_paused_frame(self) -> None:
        paused, clock = self.app()
        steady, steady_clock = self.app()
        self.assertAlmostEqual(paused._read_timeout(), app_module.WALLPAPER_TICK_SECONDS)
        paused._take_input(FOCUS_OUT)
        steady._take_input(b"")  # the same step, with no report
        self.assertFalse(paused._wallpaper_moves())
        self.assertEqual(paused._read_timeout(), app_module.IDLE_READ_SECONDS, "no wake-up for the wallpaper")
        before, frames = written(paused), 0
        with mock.patch.object(paused.region, "paint_ambient", wraps=paused.region.paint_ambient) as paint:
            for _ in range(40):  # ten seconds idle
                for app, at in ((paused, clock), (steady, steady_clock)):
                    at.at += app_module.WALLPAPER_TICK_SECONDS
                    app._take_input(b"")
                    app._render_when_due()
            frames = paint.call_count
        self.assertEqual((frames, written(paused) - before), (0, 0), "0 ambient frames and 0 bytes while unfocused")
        self.assertNotEqual(screen_state(paused), screen_state(steady), "the steady session's glyph moved on")
        paused._take_input(FOCUS_IN)
        self.assertEqual(paused._read_timeout(), 0.0, "focus back: the tick is due at once")
        paused._render_when_due()
        self.assertEqual(screen_state(paused), screen_state(steady))
        self.assertEqual(paused.terminal.screen.line(36).count(wallpaper_tests.MARK), 1)

    def test_in_focus_the_ticks_are_as_before(self) -> None:
        app, clock = self.app()
        app._take_input(FOCUS_OUT + FOCUS_IN)
        with mock.patch.object(app.region, "paint_ambient", wraps=app.region.paint_ambient) as paint:
            for _ in range(20):
                clock.at += app_module.WALLPAPER_TICK_SECONDS
                self.assertAlmostEqual(app._read_timeout(), 0.0)
                app._render_when_due()
            self.assertEqual(paint.call_count, 20)


class BusyGlowTests(unittest.TestCase):
    def app(self):
        app, clock = glow_tests.AppGlowTests.app(self)
        glow_tests.AppGlowTests.busy(self, app, clock, flushes=2)
        return app, clock

    @staticmethod
    def edge_cells(app) -> tuple:
        screen = app.terminal.screen
        rows, cols = screen.rows, screen.cols
        cells = [(row, col) for row in (0, rows - 1) for col in range(cols)]
        cells += [(row, col) for row in range(1, rows - 1) for col in (0, cols - 1)]
        return tuple((screen.line(row).ljust(cols)[col], screen.attrs_at(row, col)) for row, col in cells)

    def test_the_glow_holds_still_while_the_spinner_goes_on_and_comes_back_where_it_would_be(self) -> None:
        paused, clock = self.app()
        steady, steady_clock = self.app()
        self.assertEqual(paused._tick_seconds(), glow_tests.TICK_SECONDS)
        paused._take_input(FOCUS_OUT)
        self.assertEqual(paused._tick_seconds(), app_module.TICK_SECONDS, "the spinner's pace, not the glow's")
        paused._render()
        held = self.edge_cells(paused)
        with mock.patch.object(paused, "_render", wraps=paused._render) as render:
            for _ in range(40):  # two seconds of a running turn
                for app, at in ((paused, clock), (steady, steady_clock)):
                    at.at += glow_tests.TICK_SECONDS
                    app._take_input(b"")
                    app._render_when_due()
                self.assertEqual(self.edge_cells(paused), held, "the light holds where focus left it")
            # A frame each spinner step (0.1 s; a float step can land a hair short and draw on the next one), not
            # each glow step (0.05 s).
            self.assertTrue(13 <= render.call_count <= 20, f"the turn's frames go on: {render.call_count}")
        self.assertNotEqual(self.edge_cells(steady), held, "the steady session's light went on round")
        paused._take_input(FOCUS_IN)
        self.assertEqual(paused._tick_seconds(), glow_tests.TICK_SECONDS)
        for app in (paused, steady):
            app._render()
        self.assertEqual(screen_state(paused), screen_state(steady))


class FocusedBytesTests(unittest.TestCase):
    def test_a_focus_report_pair_writes_the_same_bytes_as_no_report_on_every_scene(self) -> None:
        # Focus that went and came back at once leaves the session byte for byte what it was: idle ticks, then a
        # running turn, with the glow on and off.
        def session(look: str, glow: str, reports: bool) -> list[str]:
            clock = wallpaper_tests.Clock(1000.0)
            app, _client = wallpaper_tests.make_app(rows=42, cols=150, clock=clock,
                                                    environ={**wallpaper_tests.WALLPAPER_ON, "OMH_TUI_GLOW": glow})
            app.adopt_background(wallpaper_tests.ANSWERED)
            app.region = app._new_region(at_top=True)
            app.launch_look = look
            app.dirty = True
            app._render_when_due()
            for step in range(80):
                if step == 40:
                    app.transcript.add_user("run")
                    app.turn_pending = True
                if step > 40 and step % 10 == 0:
                    app.transcript.apply(Event(type="message.delta", session_id=app.sid, payload={"text": "w "}))
                    app.dirty = True
                clock.at += 0.05
                for data in ((FOCUS_OUT, FOCUS_IN) if reports and step in (20, 60) else (b"",)):
                    app._take_input(data)
                app._render_when_due()
            return app.terminal.writes

        for look in SCENES:
            for glow in ("0", "1"):
                with self.subTest(look=look, glow=glow):
                    self.assertEqual(session(look, glow, True), session(look, glow, False))


if __name__ == "__main__":
    unittest.main()
