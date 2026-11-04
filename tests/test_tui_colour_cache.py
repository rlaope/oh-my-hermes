"""The colour caches under the wallpaper (`hex_to_rgb`, `theme._mix`, `style._colour_parameter`) only skip repeated
work: a busy frame with each wallpaper scene is byte for byte what the same frame is
with the caches taken out, and a wake-up from the gateway during a frame's interval still waits that interval out."""

from __future__ import annotations

import unittest
from unittest import mock

from omh import skin_pack
from omh.tui import app as app_module, style, theme
from omh.tui.app import MIN_FRAME_SECONDS
from omh.tui.gateway import Event
from omh.tui.wallpaper import SCENES
from test_tui_modes import make_app

ENVIRON = {"COLORTERM": "truecolor", "TERM": "xterm-256color", "OMH_TUI_WALLPAPER": "1"}
CACHED = (
    (skin_pack, "hex_to_rgb"),
    (theme, "hex_to_rgb"),  # the modules that import it by name hold their own reference
    (style, "hex_to_rgb"),
    (app_module, "hex_to_rgb"),
    (theme, "_mix"),
    (style, "_colour_parameter"),
)


class Clock:
    def __init__(self, at: float) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at


def frames(look: str, background: str) -> str:
    clock = Clock(1000.0)
    app, _client = make_app(rows=30, cols=100, clock=clock, environ=ENVIRON)
    app.adopt_background(background)
    app.launch_look = look
    app.region = app._new_region(at_top=True)
    app.transcript.add_user("run the tests")
    app.turn_pending = True
    app.busy_since = clock()
    for index in range(40):
        clock.at += 0.05
        app.dirty = True
        app.last_render = -1e9
        app._render_when_due()
        if index == 20:
            app.transcript.apply(Event(type="message.start", session_id=app.sid, payload={}))
            app.transcript.apply(Event(type="message.complete", session_id=app.sid, payload={"text": "step"}))
    return "".join(app.terminal.writes)


class ColourCacheTests(unittest.TestCase):
    def test_frames_are_the_same_bytes_with_the_caches_taken_out(self) -> None:
        for look in sorted(SCENES):
            for background in ("#1E1E1E", "#FAFAFA"):
                for module, name in CACHED:
                    getattr(module, name).cache_clear()
                cached = frames(look, background)
                originals = [getattr(module, name) for module, name in CACHED]
                patches = [mock.patch.object(module, name, function.__wrapped__)
                           for (module, name), function in zip(CACHED, originals, strict=True)]
                for patch in patches:
                    patch.start()
                try:
                    uncached = frames(look, background)
                finally:
                    for patch in patches:
                        patch.stop()
                self.assertGreater(len(cached), 5000, (look, background))
                self.assertEqual(cached, uncached, (look, background))


class FrameIntervalWakeTests(unittest.TestCase):
    def test_an_idle_interval_is_one_read_for_the_whole_timeout(self) -> None:
        clock = Clock(1000.0)
        app, _client = make_app(clock=clock, environ=ENVIRON)
        app.last_render = clock.at  # a frame was just drawn
        app.wake = 7
        reads = []

        def read(timeout, wake=None):
            reads.append((timeout, wake))
            clock.at += timeout
            return b""

        with mock.patch.object(app.terminal, "read", read), mock.patch.object(app, "_read_timeout", lambda: 0.5):
            app._step()
        self.assertEqual(reads, [(0.5, app.wake)])

    def test_a_wake_up_inside_the_interval_waits_it_out_but_input_does_not(self) -> None:
        clock = Clock(1000.0)
        app, _client = make_app(clock=clock, environ=ENVIRON)
        app.last_render = clock.at
        app.wake = 7
        reads = []

        def read(timeout, wake=None):
            reads.append((round(timeout, 6), wake))
            clock.at += 0.004 if wake is not None else timeout
            return b""

        with mock.patch.object(app.terminal, "read", read), mock.patch.object(app, "_read_timeout", lambda: 0.5):
            app._step()
        self.assertEqual(reads, [(0.5, app.wake), (round(MIN_FRAME_SECONDS - 0.004, 6), None)])


if __name__ == "__main__":
    unittest.main()
