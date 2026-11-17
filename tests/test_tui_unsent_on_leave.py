"""What the person typed and never sent is not lost when the TUI leaves because its gateway is gone.

A gateway that does not come back (the crash respawn's tries spent, a stop the TUI watched for
`GATEWAY_STOP_WATCH_SECONDS`, a reattach given up) ends the TUI. Its composer draft, and the text of keys it
held while it waited (Enter there, the keys after it), went with the screen. They are now printed under the
farewell, as typed, so nothing typed during a restart is lost.
"""

from __future__ import annotations

import unittest

from test_tui_gateway_restart import ExternalRestartTests
from test_tui_modes import type_text
from test_tui_respawn import crash, crashing
from omh.tui.app import RESPAWN_LIMIT, UNSENT_ON_LEAVE
from omh.tui.bot_board import Gateway
from omh.tui.gateway import GatewayExited
from omh.tui.keys import ENTER, Key, Paste


class UnsentOnLeaveTests(unittest.TestCase):
    def exhausted(self, draft: str = ""):
        app, old, _spawner, now = crashing()
        if draft:
            type_text(app, draft)
        app.respawned_at = [now[0]] * RESPAWN_LIMIT  # every try in the window spent: the next crash leaves
        return app, old

    def test_a_draft_is_printed_under_the_farewell_when_the_gateway_does_not_come_back(self) -> None:
        app, old = self.exhausted("fix the login bug")
        crash(app, old)
        self.assertEqual(app.exit_code, 1)
        self.assertIn(UNSENT_ON_LEAVE.format(text="fix the login bug"), app.farewell)
        self.assertTrue(app.farewell.startswith("omh: "), app.farewell)  # the reason and the resume command come first

    def test_keys_held_while_it_waited_follow_the_draft_with_enter_as_a_line_break(self) -> None:
        app, old = self.exhausted("first ")
        app.held_input.extend([Key("char", "x"), Key(ENTER), Key("char", "y"), Paste("pasted")])
        crash(app, old)
        self.assertIn(UNSENT_ON_LEAVE.format(text="first x\nypasted"), app.farewell)

    def test_control_and_alt_keys_held_are_not_text(self) -> None:
        app, old = self.exhausted()
        app.held_input.extend([Key("char", "a"), Key("char", "c", ctrl=True), Key("char", "b", alt=True)])
        crash(app, old)
        self.assertTrue(app.farewell.endswith("\n" + UNSENT_ON_LEAVE.format(text="a")), app.farewell)

    def test_nothing_typed_leaves_the_farewell_as_it_was(self) -> None:
        app, old = self.exhausted()
        crash(app, old)
        self.assertEqual(app.exit_code, 1)
        self.assertNotIn("was not sent", app.farewell)
        self.assertNotIn("\n", app.farewell)

    def test_text_typed_during_a_watched_stop_is_printed_when_the_watch_ends(self) -> None:
        case = ExternalRestartTests()
        stopped = Gateway("stopped", False, 4242, updated=50.0)
        app, old, _spawner, _now, _spawned = case.external(record=lambda at: stopped)
        reads = iter([b"", b"typed in wait", b"\r", b"after enter"])
        app.terminal.read = lambda timeout, wake=None: next(reads, b"") if timeout == 0.0 else b""  # type: ignore[method-assign]
        old.inbox.append(GatewayExited(1))
        app._step()
        self.assertEqual(app.exit_code, 1)
        self.assertIn(UNSENT_ON_LEAVE.format(text="typed in wait\nafter enter"), app.farewell)


if __name__ == "__main__":
    unittest.main()
