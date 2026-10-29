"""Which commands leave a `› /name` echo in the transcript (walk G6).

A command that only opens a local picker or pager, or only repaints, prints
nothing to attribute: an echo row would stand in scrollback as if it were a
prompt. A command that prints something keeps its echo, so its output says
whose it is. Every case drives an `App` over the recording client.
"""

from __future__ import annotations

import unittest

from test_tui_modes import answer, make_app, notices
from test_tui_muscle_memory import commands, send
from omh.tui.app import REWIND_BUSY_NOTICE
from omh.tui.slash import COMMANDS, LOCAL
from omh.tui.transcript import AssistantBlock

# The bare commands with nothing to attribute, and the ones that print and keep their echo.
QUIET = ("keys", "history", "rewind", "sessions", "logs", "dag", "bots", "redraw", "model", "theme")
ECHOED = ("help", "todos", "queue", "copy", "details", "export", "effort", "omh-model", "reload-skills", "image",
          "paste", "new", "quit", "steer", "topup", "glow")


class EchoTests(unittest.TestCase):
    def test_every_local_command_is_decided(self) -> None:
        local = {command.name for command in COMMANDS if command.route == LOCAL}
        self.assertEqual(local, set(QUIET) | set(ECHOED))
        quiet = {command.name for command in COMMANDS if command.route == LOCAL and not command.echo_bare}
        self.assertEqual(quiet, set(QUIET))

    def test_a_bare_picker_or_pager_command_leaves_no_echo(self) -> None:
        for name in ("keys", "history", "rewind", "sessions", "logs", "redraw", "theme"):
            with self.subTest(name=name):
                app, client = make_app()
                client.stderr_tail = lambda: []  # type: ignore[attr-defined]  # /logs reads it
                app.transcript.add_assistant("an earlier reply")  # /history has something to page
                send(app, f"/{name}")
                self.assertEqual(commands(app), [])

    def test_a_command_with_an_argument_or_output_keeps_its_echo(self) -> None:
        app, client = make_app()
        send(app, "/sessions stored-2")  # a switch: what it says needs its echo
        self.assertEqual(commands(app), ["/sessions stored-2"])
        app, _client = make_app()
        send(app, "/help")
        self.assertEqual(commands(app), ["/help"])
        app, client = make_app()
        send(app, "/usage")  # Hermes' own command: its output lands under the echo
        answer(app, client, {"output": "tokens: 12"})
        self.assertEqual(commands(app), ["/usage"])

    def test_what_a_quiet_command_says_during_a_turn_waits_under_what_runs(self) -> None:
        # With no echo to hold it, a notice from /rewind, /logs or /sessions must not close the streaming reply;
        # it is written once the turn's next boundary comes.
        said = {
            "rewind": REWIND_BUSY_NOTICE,
            "logs": "The gateway has written nothing to stderr.",
            "sessions": "Hermes has no stored sessions to switch to.",
        }
        for name, notice in said.items():
            with self.subTest(name=name):
                app, client = make_app(busy=True)
                client.stderr_tail = lambda: []  # type: ignore[attr-defined]
                app.transcript.blocks.append(AssistantBlock("streaming", done=False))
                send(app, f"/{name}")
                if name == "sessions":
                    answer(app, client, {"sessions": []})
                self.assertFalse(app.transcript.blocks[0].done)  # the live reply is still open
                self.assertNotIn(notice, notices(app))
                app.transcript.blocks[0].done = True
                app.transcript.add_notice("the turn ended")
                self.assertIn(notice, notices(app))


if __name__ == "__main__":
    unittest.main()
