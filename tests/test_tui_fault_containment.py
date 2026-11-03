"""A fault in one part of the OMH TUI's frame, or a stray write, stays off the live region (`App._drawn`, `faults`).

The launched TUI (`contain_faults`) draws a part of the frame that raises as one
warn row naming it and keeps the traceback once in its `FaultLog`, which /logs
shows; an App built any other way, as these tests build them by default,
raises. While the launched TUI runs, a background thread's traceback, a Python
warning and a write to `sys.stderr` or `sys.stdout` go to the same log, never to
the terminal, and the hooks and streams are put back when the run ends,
however it ends.
"""

from __future__ import annotations

import sys
import threading
import unittest
import warnings
from unittest import mock

from test_tui_app import FakePoller
from test_tui_loop import LoopTerminal
from test_tui_modes import SID, RecordingClient, drawn, make_app
from test_tui_panels import hud_payload
from omh.tui.app import THREAD_FAULT_NOTICE, App
from omh.tui.faults import FAULT_CAP, FaultLog
from omh.tui.panels import HudSnapshot
from omh.tui.style import Span

PANEL_ROW = "the menu or HUD panel could not be drawn (RuntimeError); /logs has the traceback"


def broken_panel(*_args: object, **_kwargs: object) -> list:
    raise RuntimeError("the panel's bug")


class RecordingTerminal(LoopTerminal):
    """A loop terminal whose reads run `during` once, at the read it is set for, and keep the screen each read saw."""

    def __init__(self, now: list[float], reads: list[tuple[float, bytes]]) -> None:
        super().__init__(now, reads)
        self.seen: list[list[str]] = []
        self.during: dict[int, object] = {}

    def read(self, timeout: float, wake: int | None = None) -> bytes:
        self.seen.append(self.screen.lines())
        action = self.during.pop(len(self.seen), None)
        if action is not None:
            action()  # type: ignore[operator]
        return super().read(timeout, wake)


def launched(*reads: tuple[float, bytes]) -> tuple[App, RecordingTerminal]:
    """An App as `_run` builds it (`contain_faults`), on a terminal that reads `reads`."""
    now = [100.0]
    terminal = RecordingTerminal(now, list(reads))
    environ = {"OMH_TUI_GLOW": "0", "OMH_TUI_WALLPAPER": "0", "OMH_TUI_UPDATE_CHECK": "0"}
    app = App(terminal, RecordingClient(), environ, poller=FakePoller(), clock=lambda: now[0],  # type: ignore[arg-type]
              contain_faults=True)
    app.sid = SID
    app.launch_layout = False
    app.client.stderr_tail = lambda: []  # type: ignore[attr-defined]  # /logs reads it
    return app, terminal


def with_plan(app: App) -> App:
    app.hud = HudSnapshot(app.stored_id, hud_payload([{"text": "Ship it", "state": "active"}]), 0.0)
    return app


class RenderContainmentTests(unittest.TestCase):
    def test_a_panel_that_raises_is_one_warn_row_and_the_session_goes_on_drawing(self) -> None:
        app, terminal = launched((0.0, b"hi"), (0.0, b"\x7f\x7f"), (0.0, b"\x04"))
        with_plan(app)
        with mock.patch("omh.tui.app.panel_lines", broken_panel):
            self.assertEqual(app.run(), 0)  # Ctrl+D on the emptied composer: the session ended as the person asked
        first, typed = terminal.seen[0], terminal.seen[1]
        self.assertIn(PANEL_ROW, [row.strip() for row in first])
        self.assertTrue(any(row.startswith("❯ hi") for row in typed), typed)  # the next frame, with the keys typed
        self.assertIn(PANEL_ROW, [row.strip() for row in typed])
        logged = app.faults.lines()
        self.assertEqual(logged.count("omh tui: the menu or HUD panel could not be drawn"), 1, "kept once")
        self.assertIn("RuntimeError: the panel's bug", logged)

    def test_the_warn_row_is_in_the_warning_colour(self) -> None:
        app, _client = make_app(contain_faults=True)
        row = app._drawn("the agent view", lambda: broken_panel(), 80)
        self.assertEqual(row, [(Span("the agent view could not be drawn (RuntimeError); /logs has the traceback",
                                     app.theme.warn),)])

    def test_logs_shows_the_kept_traceback_after_the_gateways_lines(self) -> None:
        app, _client = make_app(contain_faults=True)
        app.client.stderr_tail = lambda: ["gateway line"]  # type: ignore[attr-defined]
        with_plan(app)
        with mock.patch("omh.tui.app.panel_lines", broken_panel):
            drawn(app)
        app._logs("")
        self.assertEqual(app.pager.title, "gateway and OMH TUI stderr (memory only)")  # type: ignore[union-attr]
        shown = ["".join(span.text for span in line) for line in app.pager.lines]  # type: ignore[union-attr]
        self.assertEqual(shown[:2], ["gateway line", "omh tui: the menu or HUD panel could not be drawn"])

    def test_without_containment_the_error_raises(self) -> None:
        app, _client = make_app()  # as every test builds an App: no bug is hidden behind a warn row
        with_plan(app)
        with mock.patch("omh.tui.app.panel_lines", broken_panel), self.assertRaises(RuntimeError):
            drawn(app)

    def test_a_normal_frame_is_the_same_bytes_with_containment_on(self) -> None:
        frames = []
        for contain in (False, True):
            # One clock for both: the plan's shimmer moves with the time (`panel_lines`).
            app, _client = make_app(contain_faults=contain, clock=lambda: 50.0, wall_clock=lambda: 1_000.0)
            with_plan(app)
            app.composer.text = "hello"
            app._render()
            frames.append("".join(app.terminal.writes))  # type: ignore[attr-defined]
        self.assertEqual(frames[0], frames[1])


def raise_at(depth: int) -> None:
    if depth:
        raise_at(depth - 1)
    else:
        raise RuntimeError(f"a bug at depth {depth}")


def caught(depth: int = 0) -> RuntimeError:
    """The error `raise_at(depth)` raises, its message naming the depth: one raise site, a message that varies."""
    try:
        raise_at(depth)
    except RuntimeError as error:
        return error
    raise AssertionError("nothing raised")


class FaultLogTests(unittest.TestCase):
    def test_stray_output_never_pushes_out_a_kept_traceback(self) -> None:
        log = FaultLog()
        log.fault("the agent view", caught())
        log.write("a stray line\n" * 210)
        for _ in range(100):
            log.fault("the agent view", caught())
        lines = log.lines()
        self.assertEqual(lines.count("omh tui: the agent view could not be drawn"), 1)
        self.assertEqual(lines[0], "omh tui: the agent view could not be drawn")  # before the stream's lines
        self.assertIn("RuntimeError: a bug at depth 0", lines)

    def test_one_raise_site_is_one_fault_whatever_its_depth_or_message(self) -> None:
        log = FaultLog()
        for depth in range(40):
            log.fault("the info line", caught(depth))
        self.assertEqual(log.lines().count("omh tui: the info line could not be drawn"), 1)

    def test_past_the_cap_the_oldest_traceback_goes_and_the_newest_stays(self) -> None:
        log = FaultLog()
        for index in range(FAULT_CAP + 5):
            log.fault(f"part {index}", caught())
        heads = [line for line in log.lines() if line.startswith("omh tui: ")]
        self.assertEqual(len(heads), FAULT_CAP)
        self.assertEqual(heads[-1], f"omh tui: part {FAULT_CAP + 4} could not be drawn")
        log.fault("part 0", caught())  # raised again: kept again
        self.assertEqual(log.lines().count("omh tui: part 0 could not be drawn"), 1)


class StrayOutputTests(unittest.TestCase):
    def test_a_thread_traceback_a_warning_and_stray_writes_go_to_the_log_not_the_terminal(self) -> None:
        app, terminal = launched((0.0, b"\x04"))

        def stray() -> None:
            def raises() -> None:
                raise ValueError("a background thread's bug")

            thread = threading.Thread(target=raises, name="omh-test-poller")
            thread.start()
            thread.join()
            warnings.warn("a library's warning", UserWarning, stacklevel=1)
            print("a stray print")
            sys.stderr.write("a stray stderr line\n")

        terminal.during[1] = stray
        saved = (threading.excepthook, warnings.showwarning, sys.stdout, sys.stderr)
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            self.assertEqual(app.run(), 0)
        self.assertEqual((threading.excepthook, warnings.showwarning, sys.stdout, sys.stderr), saved)
        written = "".join(terminal.writes)
        logged = "\n".join(app.faults.lines())
        for said in ("a background thread's bug", "a library's warning", "a stray print", "a stray stderr line"):
            self.assertNotIn(said, written)
            self.assertIn(said, logged)
        self.assertIn("Exception in thread omh-test-poller:", logged)

    def test_the_first_thread_traceback_is_said_once_in_the_transcript(self) -> None:
        # Each exception's wake-up ends a read at once and the loop sleeps out the frame interval with nothing typed
        # (`App._step`), as a terminal does; Ctrl+D comes in a later read, after both.
        interval = (0.016, b"")
        app, terminal = launched((0.0, b""), interval, (0.0, b""), interval, (1.0, b"\x04"))

        def raise_in_a_thread() -> None:
            thread = threading.Thread(target=lambda: 1 / 0)
            thread.start()
            thread.join()

        terminal.during[1] = terminal.during[3] = raise_in_a_thread
        self.assertEqual(app.run(), 0)
        said = [block.text for block in app.transcript.blocks if getattr(block, "text", None) == THREAD_FAULT_NOTICE]
        self.assertEqual(said, [THREAD_FAULT_NOTICE])
        self.assertEqual("\n".join(app.faults.lines()).count("ZeroDivisionError"), 2)  # both kept in the log

    def test_a_crash_puts_the_hooks_back_and_still_raises_for_python_to_print(self) -> None:
        app, _terminal = launched()
        saved = (threading.excepthook, warnings.showwarning, sys.stdout, sys.stderr)
        with mock.patch.object(app, "_step", side_effect=RuntimeError("the loop's bug")):
            with self.assertRaises(RuntimeError):
                app.run()
        self.assertEqual((threading.excepthook, warnings.showwarning, sys.stdout, sys.stderr), saved)

    def test_without_containment_nothing_is_swapped(self) -> None:
        app, _client = make_app()
        seen = []
        with mock.patch.object(app, "_step", side_effect=lambda: seen.append(sys.stderr) or app.__setattr__("exit_code", 0)):
            app.run()
        self.assertEqual(seen, [sys.stderr])


if __name__ == "__main__":
    unittest.main()
