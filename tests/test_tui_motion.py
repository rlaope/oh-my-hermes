"""Motion in the OMH TUI: the marks that tell said from done, the running tool's pulse, the working row's sweep.

A reply opens with a bold `●` in the text colour, and each tool call with its state's mark in its state's
colour, its name in its tool family's hue. A running tool's `○` alternates the running blue and dim every
`PULSE_SECONDS` from its own start, only in the live region: scrollback
gets the settled mark. The working row's verb carries a highlight that
sweeps across it. `OMH_TUI_REDUCED_MOTION=1` (or `NO_COLOR`) stops all of
it, and the screen then repaints once a second while a turn runs.
"""

from __future__ import annotations

from dataclasses import replace
import unittest
from unittest import mock

from _tui_lines import line_text
from test_tui_modes import SID, make_app
from test_tui_panels import hud_payload
from omh.tui.app import (
    REDUCED_TICK_SECONDS,
    SWEEP_CLUSTERS,
    TICK_SECONDS,
    WORKING_GLYPHS,
    App,
    reduced_motion,
    working_spans,
)
from omh.tui.gateway import Event
from omh.tui.panels import HudSnapshot, hud_chips, panel_lines
from omh.tui.style import Span
from omh.tui.theme import DEFAULT_THEME as THEME
from omh.tui.theme import kind_style, theme_named
from omh.tui.transcript import (
    PULSE_SECONDS,
    TOOL_DENIED,
    TOOL_ERROR,
    TOOL_GENERATING,
    TOOL_INTERRUPTED,
    TOOL_OK,
    TOOL_RUNNING,
    AssistantBlock,
    ToolGroup,
    ToolRow,
    Transcript,
    block_rows,
)
from omh.tui.width import truncate_left


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def ev(kind: str, **payload: object) -> Event:
    return Event(kind, SID, payload)


def mark(line: tuple) -> object:
    """The span of a tool row's mark: after its rail (a painted cell and a space)."""
    return line[2]


class SaidAndDoneTests(unittest.TestCase):
    def test_a_reply_opens_in_the_text_colour_and_each_call_is_named_in_its_familys_hue(self) -> None:
        header, reply = block_rows(AssistantBlock("hello", done=True), 40, THEME)[:2]
        self.assertEqual((header[2].text, header[2].style), ("⚚ Hermes", replace(THEME.brand, bold=True)))
        self.assertEqual(reply[-1], Span("hello", THEME.text))
        group = ToolGroup([ToolRow("a", "read_file", status=TOOL_OK), ToolRow("b", "terminal", status=TOOL_OK)], done=True)
        rows = [row for row in block_rows(group, 40, THEME) if row]  # a blank row between two calls
        self.assertEqual([(row[4].text, row[4].style) for row in rows],
                         [("read_file", kind_style("read_file", THEME)), ("terminal", kind_style("terminal", THEME))])
        self.assertNotEqual(kind_style("read_file", THEME), kind_style("terminal", THEME))

    def test_every_tool_state_is_told_apart_by_its_marks_glyph_or_colour(self) -> None:
        marks, lines = {}, {}
        for status in (TOOL_RUNNING, TOOL_OK, TOOL_ERROR, TOOL_DENIED, TOOL_INTERRUPTED, TOOL_GENERATING):
            rows = block_rows(ToolGroup([ToolRow("a", "terminal", status=status)], done=True), 40, THEME)
            marks[status], lines[status] = mark(rows[0]), line_text(rows[-1])
        # A shape of its own for each state, in its state's colour, so the colour is never the only signal.
        self.assertEqual({status: marks[status].text for status in (TOOL_RUNNING, TOOL_OK, TOOL_ERROR)},
                         {TOOL_RUNNING: "○", TOOL_OK: "●", TOOL_ERROR: "✗"})
        self.assertEqual({status: marks[status].style for status in (TOOL_RUNNING, TOOL_OK, TOOL_ERROR)},
                         {TOOL_RUNNING: THEME.running, TOOL_OK: THEME.ok, TOOL_ERROR: THEME.error})
        # A denial shows the failure's red mark, and says so on its line.
        self.assertEqual(marks[TOOL_DENIED], marks[TOOL_ERROR])
        self.assertTrue(lines[TOOL_DENIED].endswith("⎿  denied"), lines[TOOL_DENIED])
        del marks[TOOL_DENIED]
        self.assertEqual(len(set(marks.values())), len(marks), marks)


class PulseTests(unittest.TestCase):
    def started(self) -> tuple[Transcript, Clock]:
        clock = Clock()
        transcript = Transcript(clock)
        transcript.apply(ev("message.start"))
        transcript.apply(ev("tool.start", tool_id="t1", name="terminal", context="sleep 9"))
        return transcript, clock

    def test_a_running_mark_alternates_accent_and_dim_from_its_own_start(self) -> None:
        transcript, clock = self.started()
        styles = []
        for offset in (0.1, PULSE_SECONDS + 0.1, 2 * PULSE_SECONDS + 0.1):
            (row,) = transcript.live_lines(80, THEME, now=clock.now + offset)
            styles.append(mark(row).style)
        self.assertEqual(styles, [THEME.running, THEME.dim, THEME.running])

    def test_calls_side_by_side_pulse_each_on_its_own(self) -> None:
        transcript, clock = self.started()
        clock.now += PULSE_SECONDS / 2
        transcript.apply(ev("tool.start", tool_id="t2", name="read_file", context="a.py"))
        first, second = [row for row in transcript.live_lines(80, THEME, now=100.0 + PULSE_SECONDS + 0.1) if row]
        self.assertEqual((mark(first).style, mark(second).style), (THEME.dim, THEME.running))

    def test_the_tail_renders_again_only_when_a_mark_turns(self) -> None:
        transcript, clock = self.started()
        transcript.live_lines(80, THEME, now=clock.now + 0.1)
        held = transcript._live_held
        transcript.live_lines(80, THEME, now=clock.now + 0.2)  # the same half of the pulse
        self.assertIs(transcript._live_held, held)
        transcript.live_lines(80, THEME, now=clock.now + PULSE_SECONDS + 0.1)
        self.assertIsNot(transcript._live_held, held)

    def test_the_apps_live_region_passes_the_clock(self) -> None:
        clock = Clock()
        app, _client = make_app(busy=True, clock=clock)
        app._on_event(ev("message.start"))
        app._on_event(ev("tool.start", tool_id="t1", name="terminal", context="ls"))
        clock.now += PULSE_SECONDS + 0.1
        *_rest, tool, _gap, _working, _tip = app._tail(80)
        self.assertEqual(mark(tool).style, THEME.dim)

    def test_without_a_clock_the_mark_holds_the_accent(self) -> None:
        transcript, clock = self.started()
        (row,) = transcript.live_lines(80, THEME)
        self.assertEqual(mark(row).style, THEME.running)

    def test_calls_that_pulsed_reach_scrollback_with_their_settled_marks(self) -> None:
        clock = Clock()
        app, _client = make_app(clock=clock, rows=12)
        app._send_prompt("go")
        app._on_event(ev("message.start"))
        app._on_event(ev("tool.start", tool_id="t1", name="terminal", context="ls"))
        app._on_event(ev("tool.start", tool_id="t2", name="read_file", context="a.py"))
        for step in range(6):  # through both halves of the pulse
            clock.now += PULSE_SECONDS / 2
            app._render()
        app._on_event(ev("tool.complete", tool_id="t1", name="terminal", result={"output": "a.py"}))
        app._on_event(ev("tool.complete", tool_id="t2", name="read_file", result={"error": "missing"}))
        app._on_event(ev("message.complete", text="done", status="complete"))
        flushed: list = []
        take = app.transcript.take_stable_lines

        def recorded(*args: object) -> list:
            lines = take(*args)
            flushed.extend(lines)
            return lines

        with mock.patch.object(app.transcript, "take_stable_lines", recorded):
            app._render()
        history = app.terminal.screen.history() + app.terminal.screen.lines()  # type: ignore[attr-defined]
        self.assertTrue(any(line.startswith("  ● terminal") for line in history), history)
        self.assertTrue(any(line.startswith("  ✗ read_file") for line in history), history)
        calls = [row for row in flushed if len(row) > 4 and row[0].style.gutter and row[4].text in ("terminal", "read_file")]
        self.assertEqual([mark(row).style for row in calls], [THEME.ok, THEME.error])  # settled, never a frame of a pulse

    def test_a_take_in_the_middle_of_a_pulse_writes_no_frame_of_it(self) -> None:
        # A boundary while the call's mark is in its dim half: the group leaves the live region right then.
        clock = Clock()
        app, _client = make_app(clock=clock, rows=12)
        app._send_prompt("go")
        app._on_event(ev("message.start"))
        app._on_event(ev("tool.start", tool_id="t1", name="terminal", context="sleep 9"))
        clock.now += PULSE_SECONDS * 1.5  # the dim half
        app._render()
        (live,) = [row for row in app.transcript.live_lines(80, THEME, now=clock.now) if "terminal" in line_text(row)]
        self.assertEqual(mark(live).style, THEME.dim)  # mid-pulse on screen
        app._on_event(ev("message.delta", text="Still going."))  # the group is taken now
        app._render()
        history = app.terminal.screen.history()  # type: ignore[attr-defined]  # scrollback and the screen
        rows = [line for line in history if "terminal" in line and "sleep 9" in line]
        self.assertEqual([row.split()[0] for row in rows], ["▪"], history)  # the settled mark, not a frame of ○


class SweepTests(unittest.TestCase):
    def test_the_highlight_moves_one_cluster_a_tick_and_the_text_stays(self) -> None:
        text = "Reading the router"
        frames = [working_spans(text, frame, THEME) for frame in range(SWEEP_CLUSTERS, SWEEP_CLUSTERS + 3)]
        for spans in frames:
            self.assertEqual("".join(span.text for span in spans), text)
        bright = [next(span for span in spans if span.style.bold) for spans in frames]
        self.assertEqual([len(span.text) for span in bright], [SWEEP_CLUSTERS] * 3)
        starts = [text.index(span.text) for span in bright]
        self.assertEqual(starts, [0, 1, 2])
        self.assertEqual(working_spans(text, 0, THEME), [Span(text, THEME.muted)])  # the frame reduced motion holds

    def test_the_working_row_sweeps_and_keeps_its_words(self) -> None:
        clock = Clock()
        app, _client = make_app(busy=True, clock=clock)
        app.transcript.status = "Reading the router"
        rows = []
        for _ in range(2):
            clock.now += TICK_SECONDS
            rows.append(app._tail(80)[-2])  # the working row, its tip under it
        self.assertEqual(line_text(rows[0])[2:], line_text(rows[1])[2:])  # past the spinner, the same words
        self.assertNotEqual(rows[0][2:], rows[1][2:])  # in a different light
        self.assertEqual(rows[0][0].style, THEME.accent)  # the spinner in the launch look's accent


class ReducedMotionTests(unittest.TestCase):
    def test_the_setting_and_no_color_reduce_motion_and_zero_does_not(self) -> None:
        self.assertTrue(reduced_motion({"OMH_TUI_REDUCED_MOTION": "1"}))
        self.assertTrue(reduced_motion({"NO_COLOR": "1"}))
        self.assertFalse(reduced_motion({"OMH_TUI_REDUCED_MOTION": "0"}))
        self.assertFalse(reduced_motion({"NO_COLOR": ""}))
        self.assertFalse(reduced_motion({}))

    def reduced(self) -> tuple[App, Clock]:
        clock = Clock()
        app, _client = make_app(busy=True, clock=clock, environ={"OMH_TUI_REDUCED_MOTION": "1"})
        app.transcript.activity = "(⌐■_■) reading the router..."  # Hermes' spinner: the verb slot's
        app._on_event(ev("message.start"))
        app._on_event(ev("tool.start", tool_id="t1", name="terminal", context="ls"))
        return app, clock

    def test_nothing_pulses_sweeps_or_turns(self) -> None:
        app, clock = self.reduced()
        seen = set()
        for _ in range(12):
            clock.now += PULSE_SECONDS / 2
            *_rest, tool, _gap, working, _tip = app._tail(80)
            seen.add((mark(tool).style, tuple(working)))
        self.assertEqual(len(seen), 1)  # the same rows at every moment (this turn has no start time to count from)
        ((style, working),) = seen
        self.assertEqual(style, THEME.running)
        self.assertTrue(line_text(working).startswith(f"{WORKING_GLYPHS[0]} Reading the router… (0s"))
        self.assertFalse([span for span in working if span.style.bold])

    def test_the_screen_repaints_once_a_second_instead_of_ten_times(self) -> None:
        app, _clock = self.reduced()
        self.assertEqual(app._tick_seconds(), REDUCED_TICK_SECONDS)
        moving, _client = make_app(busy=True)
        self.assertEqual(moving._tick_seconds(), TICK_SECONDS)

    def test_the_panel_holds_still(self) -> None:
        items = [{"text": "Split the router into two modules", "state": "active"}, {"text": "Run", "state": "pending"}]
        payload = hud_payload(items)
        still = {tuple(map(tuple, panel_lines(payload, 80, 6, THEME, now, motion=False))) for now in (0.0, 0.3, 0.6, 0.9)}
        self.assertEqual(len(still), 1)  # styles too: no wave through the active item
        (rows,) = still
        self.assertTrue(line_text(rows[0]).rstrip().endswith("0/2"), rows)  # no pulse dots after the count
        moving = {tuple(map(tuple, panel_lines(payload, 80, 6, THEME, now))) for now in (0.0, 0.3, 0.6, 0.9)}
        self.assertGreater(len(moving), 1)
        wall = [0.0]
        app, _client = make_app(environ={"OMH_TUI_REDUCED_MOTION": "1"}, wall_clock=lambda: wall[0])
        app.hud = HudSnapshot(app.stored_id, payload, 0.0)
        seen = set()
        for now in (0.0, 0.3, 0.6, 0.9):
            wall[0] = now
            seen.add(tuple(map(tuple, app._menu_or_panel_lines(80, 6))))
        self.assertEqual(len(seen), 1)  # the app tells the panel


class SteadyRowsTests(unittest.TestCase):
    """A tick that changes only the spinner leaves the info line's right side and the title as they were, uncomputed."""

    def test_the_info_lines_right_side_is_composed_again_only_when_something_it_shows_changes(self) -> None:
        from omh.tui.prompts import open_request

        clock = Clock()
        app, _client = make_app(busy=True, clock=clock)
        with mock.patch("omh.tui.app.hud_chips", wraps=hud_chips) as chips:
            first = app._info_right()
            clock.now += TICK_SECONDS
            self.assertIs(app._info_right(), first)
            self.assertEqual(chips.call_count, 1)
            for change in (
                lambda: setattr(app, "model", "another/model"),
                lambda: setattr(app, "turn_pending", False),  # running -> idle: the tool chip goes
                lambda: setattr(app, "context_percent", 91.0),
                lambda: setattr(app, "effort", "max"),
                lambda: setattr(app, "slot", open_request("srq-1", "approval", {"command": "ls"})),  # its clock goes
                lambda: setattr(app, "theme", theme_named("amber")),
                lambda: setattr(app, "hud", HudSnapshot("s", hud_payload(), 0.0)),
            ):
                before = chips.call_count
                change()
                app._info_right()
                self.assertEqual(chips.call_count, before + 1)
            before = chips.call_count
            app.size = (60, 24)  # another width: the same forms, `info_line` picks among them
            app._info_line(60)
            self.assertEqual(chips.call_count, before)

    def test_the_title_is_cut_only_when_its_words_change(self) -> None:
        app, _client = make_app(busy=True)
        with mock.patch("omh.tui.app.truncate_left", wraps=truncate_left) as cut:
            app._write_title()
            app._write_title()
            self.assertEqual(cut.call_count, 1)
            app.turn_pending = False
            app._write_title()
            self.assertEqual(cut.call_count, 2)


class DocumentedMotionTests(unittest.TestCase):
    def test_installation_names_the_pulse_and_the_reduced_cadence_the_code_uses(self) -> None:
        from pathlib import Path

        prose = " ".join((Path(__file__).resolve().parents[1] / "docs/INSTALLATION.md").read_text(encoding="utf-8").split())
        self.assertIn(f"pulsing between the blue and dim every {PULSE_SECONDS:g} s from its own start", prose)  # the accent
        self.assertIn("`OMH_TUI_REDUCED_MOTION=1`, or `NO_COLOR`, stops the motion", prose)
        self.assertEqual((TICK_SECONDS, REDUCED_TICK_SECONDS), (0.1, 1.0))  # "once a second ... instead of ten times"


if __name__ == "__main__":
    unittest.main()
