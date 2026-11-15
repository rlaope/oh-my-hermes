"""An approval opens with allow once highlighted (owner decision, 2026-11-15).

Enter alone allows that one command and stops nothing; Up then Enter denies
and stops the turn; a request that does not offer allow once opens on deny.
What keeps a stray Enter from allowing is the slot's arming delay
(`App._slot_arming`), not a deny default: keys typed as the slot opens answer
nothing.
"""

from __future__ import annotations

import unittest

from test_tui_modes import RecordingClient, make_app
from omh.tui import prompts
from omh.tui.app import SLOT_ARM_SECONDS, App
from omh.tui.gateway import ServerRequest
from omh.tui.keys import CHAR, ENTER, UP, Key

COMMAND = {"command": "rm -rf ./build", "description": "recursive delete"}
ONCE = {"result": {"choice": "once"}}
DENY = {"result": {"choice": "deny"}}


def opened(params: dict) -> prompts.PromptSlot:
    slot = prompts.open_request("srq-1", "approval", params)
    assert isinstance(slot, prompts.PromptSlot)
    return slot


def highlighted(slot: prompts.PromptSlot) -> str:
    return slot.approval_choices()[slot.selected]


class SlotDefaultTests(unittest.TestCase):
    def test_the_default_is_allow_once(self) -> None:
        self.assertEqual(prompts.APPROVAL_DEFAULT, "once")

    def test_an_approval_opens_with_allow_once_highlighted_under_deny(self) -> None:
        slot = opened({**COMMAND, "choices": ["once", "session", "always", "deny"]})
        self.assertEqual(slot.approval_choices()[0], "deny")
        self.assertEqual(highlighted(slot), "once")
        self.assertEqual(slot.selected, 1)

    def test_enter_alone_allows_once_and_stops_nothing(self) -> None:
        answer = opened(COMMAND).handle_key(Key(ENTER))
        self.assertEqual((answer.frame, answer.stops, answer.tell), (ONCE, False, False))

    def test_up_then_enter_denies_and_stops(self) -> None:
        slot = opened(COMMAND)
        self.assertIsNone(slot.handle_key(Key(UP)))
        self.assertEqual(highlighted(slot), "deny")
        answer = slot.handle_key(Key(ENTER))
        self.assertEqual((answer.frame, answer.stops, answer.tell), (DENY, True, False))

    def test_a_request_that_does_not_offer_allow_once_opens_on_deny(self) -> None:
        for offered in (["session", "deny"], ["deny"], ["always", "deny"]):
            with self.subTest(offered=offered):
                slot = opened({**COMMAND, "choices": offered})
                self.assertNotIn("once", slot.approval_choices())
                self.assertEqual((slot.selected, highlighted(slot)), (0, "deny"))
                answer = slot.handle_key(Key(ENTER))
                self.assertEqual((answer.frame, answer.stops), (DENY, True))

    def test_a_request_with_no_choices_listed_opens_on_allow_once(self) -> None:
        for params in (COMMAND, {**COMMAND, "choices": []}):
            with self.subTest(params=params):
                slot = opened(params)
                self.assertEqual(slot.approval_choices(), (*prompts.APPROVAL_CHOICES, prompts.APPROVAL_TELL))
                self.assertEqual(highlighted(slot), "once")
                self.assertEqual(slot.handle_key(Key(ENTER)).frame, ONCE)


class ArmingWindowTests(unittest.TestCase):
    """Through the whole app: what is typed as the approval opens answers nothing; after the window Enter allows once."""

    def asked(self) -> tuple[App, RecordingClient, list[float]]:
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        app.sid = "sid-1"
        app._on_server_request(ServerRequest("srq-1", "approval", dict(COMMAND)))
        self.assertIsNotNone(app.slot)
        self.assertEqual(highlighted(app.slot), "once")  # type: ignore[arg-type]
        return app, client, now

    def test_keys_typed_in_the_arming_window_answer_nothing_and_move_nothing(self) -> None:
        for keys in ([Key(ENTER)], [Key(UP), Key(ENTER)], [Key(CHAR, "d")], [Key(ENTER), Key(ENTER), Key(ENTER)]):
            with self.subTest(keys=keys):
                app, client, now = self.asked()
                for key in keys:
                    now[0] += SLOT_ARM_SECONDS / 4
                    app._on_input(key)
                self.assertEqual(client.answers, [])
                self.assertIsNotNone(app.slot)
                self.assertEqual(highlighted(app.slot), "once")  # type: ignore[arg-type]
                self.assertEqual(client.calls, [])  # nothing interrupted

    def test_after_the_window_enter_allows_once_and_stops_nothing(self) -> None:
        app, client, now = self.asked()
        now[0] += SLOT_ARM_SECONDS / 2
        app._on_input(Key(ENTER))  # early: ignored, and the window starts again from it
        now[0] += SLOT_ARM_SECONDS + 0.05
        app._on_input(Key(ENTER))
        self.assertEqual(client.answers, [("srq-1", ONCE)])
        self.assertIsNone(app.slot)
        self.assertEqual(client.calls, [])  # an allow does not stop the turn

    def test_after_the_window_up_then_enter_denies_and_stops_the_turn(self) -> None:
        app, client, now = self.asked()
        now[0] += SLOT_ARM_SECONDS + 0.05
        app._on_input(Key(UP))
        app._on_input(Key(ENTER))
        self.assertEqual(client.answers, [("srq-1", DENY)])
        self.assertEqual([method for method, _params in client.calls], ["session.interrupt"])


if __name__ == "__main__":
    unittest.main()
