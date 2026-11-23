"""The turn's progress report (OSC 9;4) and the quiet turn end inside omher.

On a terminal that understands OSC 9;4 (`TERM_PROGRAM` omher, WezTerm, ghostty
or iTerm.app, or Windows Terminal's `WT_SESSION`, or ConEmu's `ConEmuPID`),
the TUI says it is working (`ESC ] 9 ; 4 ; 3 ST`, indeterminate) once when its
title's state turns `running`, and done (`ESC ] 9 ; 4 ; 0 ST`) once when it
leaves it (idle or waiting on you), never per frame, and done on the way out
if working was the last word. Elsewhere nothing: another terminal may print
it. `OMH_TUI_BELL=0` keeps it: it is state, not a ring. Inside omher a turn's
end rings nothing (the done is the signal, omher marks the row itself); a
question still rings the bell there.
"""

from __future__ import annotations

import unittest

from omh.tui.app import BELL, TURN_ALERT_SECONDS
from omh.tui.gateway import ServerRequest
from test_tui_modes import drawn, make_app
from test_tui_turn_signals import Clock, turn

WORKING = "\x1b]9;4;3\x1b\\"
DONE = "\x1b]9;4;0\x1b\\"
PROGRESS = "\x1b]9;4;"
OMHER = {"TERM_PROGRAM": "omher"}
UNDERSTANDING = ({"TERM_PROGRAM": "omher"}, {"TERM_PROGRAM": "WezTerm"}, {"TERM_PROGRAM": "ghostty"},
                 {"TERM_PROGRAM": "iTerm.app"}, {"WT_SESSION": "7b3c0e1a"}, {"ConEmuPID": "4242"})
UNKNOWN = ({}, {"TERM_PROGRAM": "Apple_Terminal"}, {"TERM_PROGRAM": "vscode"}, {"TERM": "foot"},
           {"TERM": "xterm-256color"},
           # another terminal started inside Windows Terminal or ConEmu keeps their variable: it is not them
           {"TERM_PROGRAM": "vscode", "WT_SESSION": "7b3c0e1a"}, {"TERM_PROGRAM": "screen", "ConEmuPID": "4242"})
APPROVAL = ServerRequest("srq-1", "approval", {"command": "rm -rf ./x", "description": "recursive delete"})


def writes(app) -> str:
    return "".join(app.terminal.writes)


class ProgressTests(unittest.TestCase):
    def test_working_and_done_are_written_once_per_change_with_the_exact_bytes(self) -> None:
        app, _client = make_app(environ=OMHER)
        drawn(app)
        drawn(app)
        self.assertNotIn(PROGRESS, writes(app))  # idle from the start: nothing to take back
        app.turn_pending = True
        for _frame in range(3):
            drawn(app)
        self.assertEqual(writes(app).count(WORKING), 1)
        self.assertEqual(writes(app).count(DONE), 0)
        app.turn_pending = False
        for _frame in range(3):
            drawn(app)
        self.assertEqual(writes(app).count(WORKING), 1)
        self.assertEqual(writes(app).count(DONE), 1)
        self.assertLess(writes(app).index(WORKING), writes(app).index(DONE))
        app.turn_pending = True
        drawn(app)
        self.assertEqual(writes(app).count(WORKING), 2)

    def test_a_question_that_opens_mid_turn_is_done_with_running(self) -> None:
        app, _client = make_app(busy=True, environ=OMHER)
        drawn(app)
        app._on_server_request(APPROVAL)
        drawn(app)
        drawn(app)
        self.assertEqual(writes(app).count(WORKING), 1)
        self.assertEqual(writes(app).count(DONE), 1)

    def test_every_terminal_that_understands_it_gets_it(self) -> None:
        for environ in UNDERSTANDING:
            with self.subTest(environ=environ):
                app, _client = make_app(busy=True, environ=environ)
                drawn(app)
                app.turn_pending = False
                drawn(app)
                self.assertEqual(writes(app).count(WORKING), 1)
                self.assertEqual(writes(app).count(DONE), 1)

    def test_an_unknown_terminal_gets_nothing(self) -> None:
        for environ in UNKNOWN:
            with self.subTest(environ=environ):
                app, _client = make_app(busy=True, environ=environ)
                drawn(app)
                app.turn_pending = False
                drawn(app)
                app.turn_pending = True
                drawn(app)
                app._shutdown()
                self.assertNotIn(PROGRESS, writes(app))

    def test_the_way_out_says_done_after_working(self) -> None:
        app, _client = make_app(busy=True, environ=OMHER)
        drawn(app)
        app._shutdown()
        self.assertEqual(writes(app).count(DONE), 1)
        self.assertLess(writes(app).index(WORKING), writes(app).index(DONE))

    def test_the_way_out_says_done_even_when_the_last_frame_fails(self) -> None:
        app, _client = make_app(busy=True, environ=OMHER)
        drawn(app)

        def broken(*_args: object, **_kwargs: object) -> list[str]:
            raise RuntimeError("the last frame could not be drawn")

        app.transcript.take_stable_lines = broken  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError):
            app._shutdown()
        self.assertEqual(writes(app).count(DONE), 1)

    def test_the_way_out_says_nothing_when_done_was_the_last_word(self) -> None:
        app, _client = make_app(environ=OMHER)
        drawn(app)
        app._shutdown()
        self.assertNotIn(PROGRESS, writes(app))

    def test_the_quiet_setting_keeps_the_progress_report(self) -> None:
        app, _client = make_app(busy=True, environ={**OMHER, "OMH_TUI_BELL": "0"})
        drawn(app)
        app.turn_pending = False
        drawn(app)
        self.assertEqual(writes(app).count(WORKING), 1)
        self.assertEqual(writes(app).count(DONE), 1)


class OmherBellTests(unittest.TestCase):
    def test_a_long_turn_ends_without_a_ring_inside_omher(self) -> None:
        clock = Clock()
        app, _client = make_app(clock=clock, environ=OMHER)
        before = len(writes(app))
        turn(app, clock, max(60.0, TURN_ALERT_SECONDS))
        out = writes(app)[before:]
        self.assertNotIn(BELL, out)
        self.assertNotIn("\x1b]9;H", out)  # no notification either
        self.assertNotIn("\x1b]777;", out)

    def test_a_question_still_rings_inside_omher(self) -> None:
        app, _client = make_app(busy=True, environ=OMHER)
        before = len(writes(app))
        app._on_server_request(APPROVAL)
        self.assertEqual(writes(app)[before:].count(BELL), 1)


if __name__ == "__main__":
    unittest.main()
