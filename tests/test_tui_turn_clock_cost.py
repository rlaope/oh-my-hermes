"""Hermes' `display.timestamps` and `display.show_cost` in the OMH TUI (#3187).

With `display.timestamps: true` a turn's done line also says the local clock
minutes it ran between, `✻ 1m 20s · 10:42→10:44 · 3 tools`; `/timestamps
on|off` sets that for the run without writing Hermes' config. With
`display.show_cost: true` the info line also says the session's cost, but only
the figure Hermes' usage carries in `cost_usd`: OMH prices nothing, so a usage
block without one shows no cost at all, never `$0.00`.
"""

from __future__ import annotations

import math
import time
import unittest

from _tui_lines import line_text
from test_tui_command_output import send
from test_tui_modes import SID, make_app, notices
from omh.tui.app import (
    TIMESTAMPS_NOTICE, TIMESTAMPS_STATUS_NOTICE, TIMESTAMPS_USAGE_NOTICE, App, cost_label, display_on,
)
from omh.tui.gateway import Event
from omh.tui.theme import DEFAULT_THEME as THEME
from omh.tui.transcript import NOTICE_WARN, TurnSummaryBlock, block_rows, turn_clock

# 2026-11-25 10:42:05 UTC; read with `time.gmtime`, so the minutes do not depend on the machine's zone.
AT_10_42 = 1795603325.0


def utc(at: float) -> str:
    return time.strftime("%H:%M", time.gmtime(at))


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def settings(**display: object) -> dict:
    return {"config": {"display": display}}


class TurnClockTests(unittest.TestCase):
    def test_start_and_end_minutes_joined_by_an_arrow(self) -> None:
        self.assertEqual(utc(AT_10_42), "10:42")
        self.assertEqual(turn_clock(AT_10_42, AT_10_42 + 120, time.gmtime), "10:42→10:44")

    def test_a_turn_inside_one_minute_says_that_minute_once(self) -> None:
        self.assertEqual(turn_clock(AT_10_42, AT_10_42 + 40, time.gmtime), "10:42")

    def test_a_turn_across_midnight_reads_on_the_clock_without_a_day(self) -> None:
        before_midnight = AT_10_42 + (13 * 3600 + 17 * 60)  # 23:59:05
        self.assertEqual(utc(before_midnight), "23:59")
        self.assertEqual(turn_clock(before_midnight, before_midnight + 120, time.gmtime), "23:59→00:01")

    def test_the_default_reads_the_local_clock(self) -> None:
        local = time.mktime((2026, 11, 25, 9, 5, 30, 0, 0, -1))
        self.assertEqual(turn_clock(local, local + 600), "09:05→09:15")


class DoneLineClockTests(unittest.TestCase):
    def test_the_clock_goes_after_the_time_and_before_the_tools(self) -> None:
        (row,) = block_rows(TurnSummaryBlock(80.0, 3, 1200, clock="10:42→10:44"), 80, THEME)
        self.assertEqual(line_text(row), "  ✻ 1m 20s · 10:42→10:44 · 3 tools · ↓1.2k")

    def test_off_the_line_is_unchanged(self) -> None:
        (row,) = block_rows(TurnSummaryBlock(80.0, 3, 1200), 80, THEME)
        self.assertEqual(line_text(row), "  ✻ 1m 20s · 3 tools · ↓1.2k")

    def test_a_narrow_line_drops_tokens_then_tools_then_the_clock_then_the_wait(self) -> None:
        block = TurnSummaryBlock(9.0, 1, 1200, waited=2.0, clock="10:42")
        full = "  ✻ 9s (2s waiting on you) · 10:42 · 1 tool · ↓1.2k"
        for width, said in ((len(full), full), (len(full) - 1, "  ✻ 9s (2s waiting on you) · 10:42 · 1 tool"),
                            (40, "  ✻ 9s (2s waiting on you) · 10:42"), (30, "  ✻ 9s (2s waiting on you)"),
                            (20, "  ✻ 9s")):
            with self.subTest(width=width):
                (row,) = block_rows(block, width, THEME)
                self.assertEqual(line_text(row), said)


def run_turn(app: App, clock: Clock, wall: Clock, seconds: float) -> TurnSummaryBlock:
    app._send_prompt("go")
    app._on_event(Event("message.start", SID, {}))
    clock.now += seconds
    wall.now += seconds
    app._on_event(Event("message.complete", SID, {"text": "done", "status": "complete"}))
    return [block for block in app.transcript.blocks if isinstance(block, TurnSummaryBlock)][-1]


class AppTimestampsTests(unittest.TestCase):
    def make(self) -> tuple[App, object, Clock, Clock]:
        clock, wall = Clock(100.0), Clock(AT_10_42)
        app, client = make_app(clock=clock, wall_clock=wall)
        return app, client, clock, wall

    def test_display_timestamps_true_puts_the_turns_clock_on_its_done_line(self) -> None:
        app, _client, clock, wall = self.make()
        app._take_settings(settings(timestamps=True))
        block = run_turn(app, clock, wall, 80.0)
        self.assertEqual(block.clock, turn_clock(AT_10_42, AT_10_42 + 80.0))

    def test_off_by_default_and_for_anything_but_yaml_true(self) -> None:
        for display in ({}, {"timestamps": False}, {"timestamps": "true"}, {"timestamps": 1}):
            with self.subTest(display=display):
                app, _client, clock, wall = self.make()
                app._take_settings(settings(**display))
                self.assertEqual(run_turn(app, clock, wall, 5.0).clock, "")

    def test_slash_timestamps_sets_the_run_over_the_config_and_sends_nothing(self) -> None:
        app, client, clock, wall = self.make()
        app._take_settings(settings(timestamps=True))
        sent = len(client.calls)
        send(app, "/timestamps off")
        self.assertEqual(client.calls[sent:], [])
        self.assertIn(TIMESTAMPS_NOTICE.format(state="off"), notices(app))
        app._take_settings(settings(timestamps=True))  # a reconnect reads the config again: the run's choice holds
        self.assertEqual(run_turn(app, clock, wall, 5.0).clock, "")
        send(app, "/ts")  # alone, switches them
        self.assertIn(TIMESTAMPS_NOTICE.format(state="on"), notices(app))
        self.assertEqual(run_turn(app, clock, wall, 5.0).clock, turn_clock(wall.now - 5.0, wall.now))

    def test_slash_timestamps_status_says_which_and_changes_nothing(self) -> None:
        app, client, clock, wall = self.make()
        app._take_settings(settings(timestamps=True))
        sent = len(client.calls)
        send(app, "/timestamps status")
        self.assertIn(TIMESTAMPS_STATUS_NOTICE.format(state="on"), notices(app))
        self.assertEqual(client.calls[sent:], [])
        self.assertIsNone(app.timestamps_said)  # the config's setting still holds
        send(app, "/ts off")
        send(app, "/ts status")
        self.assertIn(TIMESTAMPS_STATUS_NOTICE.format(state="off"), notices(app))

    def test_slash_timestamps_during_a_turn_applies_to_that_turns_done_line(self) -> None:
        app, _client, clock, wall = self.make()
        app._send_prompt("go")
        app._on_event(Event("message.start", SID, {}))
        send(app, "/timestamps on")  # runs at once (`RUNS_DURING_TURN`)
        clock.now += 80.0
        wall.now += 80.0
        app._on_event(Event("message.complete", SID, {"text": "done", "status": "complete"}))
        (block,) = [block for block in app.transcript.blocks if isinstance(block, TurnSummaryBlock)]
        self.assertEqual(block.clock, turn_clock(AT_10_42, AT_10_42 + 80.0))

    def test_slash_timestamps_with_another_word_says_how_to_use_it(self) -> None:
        app, _client, clock, wall = self.make()
        send(app, "/timestamps maybe")
        self.assertIn(TIMESTAMPS_USAGE_NOTICE, notices(app, NOTICE_WARN))
        self.assertEqual(run_turn(app, clock, wall, 5.0).clock, "")


class CostLabelTests(unittest.TestCase):
    def test_hermes_figure_as_dollars(self) -> None:
        self.assertEqual(cost_label({"cost_usd": 0.42}), "$0.42")
        self.assertEqual(cost_label({"cost_usd": 12}), "$12.00")
        self.assertEqual(cost_label({"cost_usd": 0}), "$0.00")  # a zero Hermes said is its figure
        self.assertEqual(cost_label({"cost_usd": 0.0046}), "$0.0046")
        self.assertEqual(cost_label({"cost_usd": 0.00001}), "$<0.0001")
        self.assertEqual(cost_label({"cost_usd": 0.42, "cost_status": "estimated"}), "~$0.42")
        self.assertEqual(cost_label({"cost_usd": 0.42, "cost_status": "actual"}), "$0.42")

    def test_a_cost_hermes_could_not_price_shows_none(self) -> None:
        # Hermes leaves the total at 0.0 for a model it cannot price, with `cost_status: unknown` (its label: n/a).
        self.assertIsNone(cost_label({"cost_usd": 0.0, "cost_status": "unknown"}))
        self.assertIsNone(cost_label({"cost_usd": 0.42, "cost_status": "unknown"}))

    def test_a_subscription_included_cost_says_included(self) -> None:
        self.assertEqual(cost_label({"cost_usd": 0.0, "cost_status": "included"}), "included")
        self.assertIsNone(cost_label({"cost_status": "included"}))  # still only with Hermes' figure there

    def test_no_number_no_label(self) -> None:
        for usage in ({}, {"cost_usd": None}, {"cost_usd": "0.42"}, {"cost_usd": True}, {"cost_usd": math.nan},
                      {"cost_usd": math.inf}, {"cost_usd": -1.0}, None, "usage"):
            with self.subTest(usage=usage):
                self.assertIsNone(cost_label(usage))

    def test_display_on_reads_yaml_true_only(self) -> None:
        self.assertTrue(display_on(settings(show_cost=True), "show_cost"))
        for answer in (settings(show_cost="yes"), settings(), {"config": {"display": None}}, {}):
            with self.subTest(answer=answer):
                self.assertFalse(display_on(answer, "show_cost"))


def info_text(app: App) -> str:
    return line_text(app._info_right()[0])


def usage_event(**usage: object) -> Event:
    return Event("session.usage", SID, {"usage": {"output": 10, "calls": 1, **usage}})


class InfoLineCostTests(unittest.TestCase):
    def test_show_cost_and_a_figure_from_hermes_put_the_cost_on_the_info_line(self) -> None:
        app, _client = make_app()
        app.model = "openai/gpt-5"
        app._take_settings(settings(show_cost=True))
        app._on_event(usage_event(cost_usd=0.42))
        self.assertTrue(info_text(app).endswith(" $0.42"), info_text(app))

    def test_an_unknown_cost_keeps_the_line_without_one(self) -> None:
        app, _client = make_app()
        app.model = "openai/gpt-5"
        app._take_settings(settings(show_cost=True))
        before = info_text(app)
        app._on_event(usage_event(cost_usd=0.0, cost_status="unknown"))
        self.assertEqual(info_text(app), before)

    def test_no_figure_from_hermes_shows_no_cost_at_all(self) -> None:
        # Hermes' gateway `_get_usage` fills no `cost_usd` today: the line stays as it was, with no `$0.00`.
        app, _client = make_app()
        app.model = "openai/gpt-5"
        app._take_settings(settings(show_cost=True))
        before = info_text(app)
        app._on_event(usage_event())
        self.assertEqual(info_text(app), before)
        self.assertNotIn("$", info_text(app))

    def test_without_show_cost_a_figure_stays_off_the_line(self) -> None:
        app, _client = make_app()
        app.model = "openai/gpt-5"
        app._take_settings(settings())
        app._on_event(usage_event(cost_usd=0.42))
        self.assertNotIn("$", info_text(app))

    def test_a_block_without_a_figure_keeps_the_last_and_a_new_session_starts_without_one(self) -> None:
        app, _client = make_app()
        app.model = "openai/gpt-5"
        app._take_settings(settings(show_cost=True))
        app._on_event(usage_event(cost_usd=0.42))
        app._on_event(usage_event())
        self.assertIn("$0.42", info_text(app))
        app._adopt_session({"session_id": "live-2", "stored_session_id": "stored-2", "info": {"model": "openai/gpt-5"}})
        self.assertNotIn("$", info_text(app))

    def test_a_narrow_line_drops_the_cost_before_the_model(self) -> None:
        app, _client = make_app()
        app.model = "openai/gpt-5"
        app._take_settings(settings(show_cost=True))
        app._on_event(usage_event(cost_usd=0.42))
        forms = [line_text(form) for form in app._info_right()]
        self.assertTrue(forms[0].endswith(" · $0.42"), forms[0])
        self.assertEqual(forms[1], forms[0].removesuffix(" · $0.42"))  # the next form is the whole line without it
        self.assertEqual([form for form in forms[1:] if "$" in form], [])


if __name__ == "__main__":
    unittest.main()
