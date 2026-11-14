"""Desktop notifications (OSC 9 / OSC 777) wait for a window that is not focused; the bell does not.

A terminal that reported focus (`ESC[I` or `ESC[O`, mode 1004) and has it now needs no notification for a turn end, a
question or a finished background process: the bell is all that rings. One that reported focus gone gets the bell and
the notification. One that never reported (`KeyDecoder.focus_seen` false) is unknown and keeps the full signal.
`OMH_TUI_BELL=0` keeps every state quiet.
"""

from __future__ import annotations

import unittest

from omh.tui.app import BELL, TURN_ALERT_SECONDS
from omh.tui.bot_board import ON_POSIX
from omh.tui.gateway import ServerRequest
from omh.tui.panels import HudSnapshot
from omh.tui.keys import KeyDecoder
from test_tui_background_row import NOW, STORED, process
from test_tui_modes import make_app
from test_tui_turn_signals import Clock, turn

FOCUS_IN = b"\x1b[I"
FOCUS_OUT = b"\x1b[O"
ITERM = {"TERM_PROGRAM": "iTerm.app"}
FOOT = {"TERM": "foot"}
OSC = ("\x1b]9;", "\x1b]777;")
STATES = (("focused", FOCUS_IN), ("unfocused", FOCUS_OUT), ("unknown", b""))


def has_osc(text: str) -> bool:
    return any(mark in text for mark in OSC)


def settled(app, report: bytes) -> None:
    app.decoder.feed(report)


def alert_text(app) -> str:
    return "".join(app.terminal.writes)  # type: ignore[attr-defined]


class DecoderFocusSeenTests(unittest.TestCase):
    def test_focus_seen_after_the_first_report_of_either_kind(self) -> None:
        for report in (FOCUS_IN, FOCUS_OUT):
            with self.subTest(report=report):
                decoder = KeyDecoder()
                self.assertFalse(decoder.focus_seen)
                decoder.feed(report)
                self.assertTrue(decoder.focus_seen)

    def test_input_without_a_report_does_not_mean_focus_seen(self) -> None:
        decoder = KeyDecoder()
        decoder.feed(b"abc")
        self.assertFalse(decoder.focus_seen)
        decoder.feed(FOCUS_OUT)
        decoder.feed(b"x")  # a key clears unfocused_at; the terminal still reports focus
        self.assertTrue(decoder.focus_seen)
        self.assertIsNone(decoder.unfocused_at)


class TurnEndTests(unittest.TestCase):
    def ends(self, environ: dict, report: bytes, seconds: float = TURN_ALERT_SECONDS) -> str:
        clock = Clock()
        app, _client = make_app(clock=clock, environ=environ)
        settled(app, report)
        before = len(app.terminal.writes)  # type: ignore[attr-defined]
        turn(app, clock, seconds)
        return "".join(app.terminal.writes[before:])  # type: ignore[attr-defined]

    def test_focused_rings_the_bell_only(self) -> None:
        for environ in (ITERM, FOOT):
            with self.subTest(environ=environ):
                out = self.ends(environ, FOCUS_IN)
                self.assertEqual(out.count(BELL), 1)
                self.assertFalse(has_osc(out))

    def test_unfocused_adds_the_notification(self) -> None:
        self.assertIn("\x1b]9;", self.ends(ITERM, FOCUS_OUT))
        self.assertIn("\x1b]777;notify;", self.ends(FOOT, FOCUS_OUT))

    def test_never_reported_keeps_todays_signal(self) -> None:
        self.assertIn("\x1b]9;", self.ends(ITERM, b""))
        self.assertIn("\x1b]777;notify;", self.ends(FOOT, b""))

    def test_a_terminal_with_no_notification_rings_the_bell_in_every_state(self) -> None:
        for name, report in STATES:
            with self.subTest(state=name):
                self.assertIn(BELL, self.ends({"TERM_PROGRAM": "Apple_Terminal"}, report))

    def test_a_short_turn_is_quiet_in_every_state(self) -> None:
        for name, report in STATES:
            with self.subTest(state=name):
                self.assertEqual(self.ends(ITERM, report, TURN_ALERT_SECONDS - 0.5), "")

    def test_bell_off_is_silent_in_every_state(self) -> None:
        for name, report in STATES:
            with self.subTest(state=name):
                out = self.ends({**ITERM, "OMH_TUI_BELL": "0"}, report, 60)
                self.assertNotIn(BELL, out)
                self.assertFalse(has_osc(out))

    def test_focus_back_after_focus_gone_drops_the_notification_again(self) -> None:
        clock = Clock()
        app, _client = make_app(clock=clock, environ=ITERM)
        settled(app, FOCUS_OUT)
        settled(app, FOCUS_IN)
        before = len(app.terminal.writes)  # type: ignore[attr-defined]
        turn(app, clock, 30)
        self.assertFalse(has_osc("".join(app.terminal.writes[before:])))  # type: ignore[attr-defined]


APPROVAL = ServerRequest("srq-1", "approval", {"command": "rm -rf ./x", "description": "recursive delete"})


class QuestionTests(unittest.TestCase):
    def written(self, environ: dict, report: bytes) -> str:
        app, _client = make_app(busy=True, environ=environ)
        settled(app, report)
        before = len(app.terminal.writes)  # type: ignore[attr-defined]
        app._on_server_request(APPROVAL)
        return "".join(app.terminal.writes[before:])  # type: ignore[attr-defined]

    def test_focused_rings_the_bell_only(self) -> None:
        out = self.written(ITERM, FOCUS_IN)
        self.assertEqual(out.count(BELL), 1)
        self.assertFalse(has_osc(out))

    def test_unfocused_and_unknown_add_the_notification(self) -> None:
        for report in (FOCUS_OUT, b""):
            with self.subTest(report=report):
                out = self.written(ITERM, report)
                self.assertEqual(out.count(BELL), 1)
                self.assertIn("\x1b]9;Hermes asks to run recursive delete", out)

    def test_bell_off_is_silent_in_every_state(self) -> None:
        for name, report in STATES:
            with self.subTest(state=name):
                out = self.written({**ITERM, "OMH_TUI_BELL": "0"}, report)
                self.assertNotIn(BELL, out)
                self.assertFalse(has_osc(out))


@unittest.skipUnless(ON_POSIX, "a finished host process is only noticed on POSIX (`background.askable`)")
class BackgroundEndTests(unittest.TestCase):
    def written(self, environ: dict, report: bytes) -> str:
        clock, wall = Clock(), Clock()
        wall.now = NOW
        app, _client = make_app(cols=120, clock=clock, wall_clock=wall, environ=environ)
        app.stored_id = STORED
        settled(app, report)
        for processes in ((process(),), ()):
            snapshot = HudSnapshot(STORED, {}, 0.0, {}, processes)
            app.poller.take = lambda snapshot=snapshot: snapshot
            clock.now += 1
            app._take_hud()
        return "".join(app.terminal.writes)  # type: ignore[attr-defined]

    def test_focused_rings_the_bell_only(self) -> None:
        out = self.written(ITERM, FOCUS_IN)
        self.assertEqual(out.count(BELL), 1)
        self.assertFalse(has_osc(out))

    def test_unfocused_and_unknown_add_the_notification(self) -> None:
        for report in (FOCUS_OUT, b""):
            with self.subTest(report=report):
                out = self.written(ITERM, report)
                self.assertEqual(out.count(BELL), 1)
                self.assertIn("\x1b]9;", out)

    def test_bell_off_is_silent_in_every_state(self) -> None:
        for name, report in STATES:
            with self.subTest(state=name):
                out = self.written({**ITERM, "OMH_TUI_BELL": "0"}, report)
                self.assertNotIn(BELL, out)
                self.assertFalse(has_osc(out))


if __name__ == "__main__":
    unittest.main()
