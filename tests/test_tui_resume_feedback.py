"""Bare `/resume` always says something, and a bare `omh --resume` starts on the session picker.

Reported by the owner on 2026-11-02: `/resume` drew nothing at all. Bare `/resume` has no echo, so until Hermes
answered `session.list` the screen did not change; during a turn the answer waits behind Hermes' 8-worker pool for
long calls and `flush_token_counts` (up to 5 s), while the listing itself took 0.02-0.21 s on a 428 MB copy of the
owner's store. Then, with the list slow during a turn, the prompt typed meanwhile ended up as the picker's filter
(`Sessions (0/50)`, `no session matches the filter`).
"""

from __future__ import annotations

import unittest

from _tui_lines import line_text
from test_tui_modes import SID, FakePoller, RecordingClient, ScriptedTerminal, drawn, make_app, notices, type_text
from omh.tui import app as app_module
from omh.tui.app import (
    QueuedLine,
    SESSION_LIST_LIMIT,
    SESSIONS_EMPTY_NOTICE,
    SESSIONS_LOADING_LINE,
    App,
)
from omh.tui.gateway import Response
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, Key
from omh.tui.launch import PICK_SESSION_ENV
from omh.tui.session_picker import SessionPicker, SessionRow
from omh.tui.theme import DEFAULT_THEME
from omh.tui.transcript import NOTICE_WARN, AssistantBlock

LISTED = {"sessions": [
    {"id": "stored-2", "title": "an earlier session", "preview": "", "started_at": 1_791_900_000.0, "message_count": 4},
    {"id": "stored-3", "title": "", "preview": "the first prompt", "started_at": 1_791_800_000.0, "message_count": 2},
]}


def list_call(client: RecordingClient) -> int:
    """The request id of the newest `session.list` call."""
    return max(index for index, (method, _params) in enumerate(client.calls, 1) if method == "session.list")


def reply(app: App, client: RecordingClient, result: dict | None = None, error: dict | None = None) -> None:
    app._on_response(Response(list_call(client), result, error))


def resume(app: App) -> None:
    type_text(app, "/resume")
    app._on_input(Key(ENTER))


class ResumeFeedbackTests(unittest.TestCase):
    def test_resume_shows_the_loading_row_at_once_and_asks_once(self) -> None:
        app, client = make_app()
        resume(app)
        self.assertEqual(client.calls, [("session.list", {"limit": SESSION_LIST_LIMIT})])
        self.assertTrue(any(SESSIONS_LOADING_LINE in line for line in drawn(app)))
        self.assertIsNone(app.picker)
        resume(app)  # asked again while the first is out: no second call, the row stays
        self.assertEqual([method for method, _params in client.calls], ["session.list"])
        reply(app, client, LISTED)
        self.assertFalse(any(SESSIONS_LOADING_LINE in line for line in drawn(app)))

    def test_rows_open_the_picker(self) -> None:
        app, client = make_app()
        resume(app)
        reply(app, client, LISTED)
        self.assertIsNotNone(app.picker)
        self.assertEqual([row.id for row in app.picker.rows], ["stored-2", "stored-3"])
        self.assertTrue(any("Sessions (2)" in line for line in drawn(app)))

    def test_none_listed_says_so(self) -> None:
        app, client = make_app()
        resume(app)
        reply(app, client, {"sessions": []})
        self.assertIsNone(app.picker)
        self.assertEqual(notices(app), [SESSIONS_EMPTY_NOTICE])

    def test_a_refusal_is_a_warning_in_hermes_words(self) -> None:
        app, client = make_app()
        resume(app)
        reply(app, client, error={"code": 5006, "message": "database is locked"})
        self.assertEqual(notices(app, NOTICE_WARN), ["Hermes did not list the stored sessions: database is locked."])
        self.assertFalse(any(SESSIONS_LOADING_LINE in line for line in drawn(app)))

    def test_no_answer_within_the_wait_says_so_and_a_late_answer_opens_nothing(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        resume(app)
        now[0] += app_module.CALL_ANSWER_SECONDS
        app._expire_calls()
        self.assertEqual(notices(app, NOTICE_WARN), ["Hermes did not answer the session list in 120 s; /resume asks again."])
        self.assertFalse(any(SESSIONS_LOADING_LINE in line for line in drawn(app)))
        reply(app, client, LISTED)
        self.assertIsNone(app.picker)

    def test_what_is_said_during_a_turn_is_drawn_under_what_runs(self) -> None:
        for result, error, said in (
            ({"sessions": []}, None, SESSIONS_EMPTY_NOTICE),
            (None, {"code": 5006, "message": "boom"}, "Hermes did not list the stored sessions: boom."),
        ):
            with self.subTest(said=said):
                app, client = make_app(busy=True)
                app.transcript.blocks.append(AssistantBlock("streaming", done=False))
                resume(app)
                reply(app, client, result, error)
                self.assertFalse(app.transcript.blocks[0].done)  # the live reply is still open
                self.assertTrue(any(said[:40] in line for line in drawn(app)))

    def test_text_typed_while_the_list_is_out_stays_in_the_composer(self) -> None:
        for busy in (False, True):
            with self.subTest(busy=busy):
                now = [100.0]
                app, client = make_app(busy=busy, clock=lambda: now[0])
                if busy:
                    app.transcript.blocks.append(AssistantBlock("streaming", done=False))
                resume(app)
                type_text(app, "a prompt typed meanwhile")
                self.assertEqual(app.composer.text, "a prompt typed meanwhile")
                now[0] += 5.0  # the person stopped typing long before the list came
                reply(app, client, LISTED)
                self.assertEqual(app.picker.query, "")
                self.assertEqual(len(app.picker.visible()), 2)
                self.assertEqual(app.composer.text, "a prompt typed meanwhile")
                app._on_input(Key(ESCAPE))
                self.assertIsNone(app.picker)
                self.assertEqual(app.composer.text, "a prompt typed meanwhile")

    def test_a_list_that_arrives_mid_typing_waits_for_the_typing_to_stop(self) -> None:
        # The owner's screenshot (2026-11-02): during a turn, `/resume`, then a prompt typed while the list loaded; the
        # picker opened mid-word and the rest of the prompt became its filter (`Sessions (0/50)`).
        for busy in (False, True):
            with self.subTest(busy=busy):
                now = [100.0]
                app, client = make_app(busy=busy, clock=lambda: now[0])
                if busy:
                    app.transcript.blocks.append(AssistantBlock("streaming", done=False))
                resume(app)

                def typed(text: str) -> None:
                    for char in text:
                        now[0] += 0.12  # an unbroken run: each key well inside the quiet gap
                        app._on_input(Key(CHAR, char))

                typed("바꾸고 리드")
                now[0] += 0.05
                reply(app, client, LISTED)  # the list lands mid-run
                self.assertTrue(app.picker.waiting)
                screen = drawn(app)
                self.assertTrue(any("Sessions (2)" in line for line in screen))  # its rows show meanwhile
                self.assertTrue(any("takes keys once typing stops" in line for line in screen))
                typed("미나 그런 스타일")
                self.assertEqual((app.picker.query, app.composer.text), ("", "바꾸고 리드미나 그런 스타일"))
                self.assertEqual(len(app.picker.visible()), 2)
                now[0] += app_module.SLOT_ARM_SECONDS  # typing stopped: the next key is the picker's
                app._on_input(Key(CHAR, "e"))
                self.assertFalse(app.picker.waiting)
                self.assertEqual((app.picker.query, app.composer.text), ("e", "바꾸고 리드미나 그런 스타일"))
                app._on_input(Key(ESCAPE))
                self.assertIsNone(app.picker)
                self.assertEqual(app.composer.text, "바꾸고 리드미나 그런 스타일")

    def test_a_list_that_answers_right_after_the_enter_that_asked_takes_keys_at_once(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        resume(app)
        now[0] += 0.05  # a fast gateway: the Enter that asked is no typing meanwhile
        reply(app, client, LISTED)
        self.assertFalse(app.picker.waiting)
        app._on_input(Key(DOWN))
        self.assertEqual(app.picker.index, 1)

    def test_a_list_that_arrives_after_a_pause_takes_keys_at_once(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        resume(app)
        now[0] += app_module.SLOT_ARM_SECONDS
        reply(app, client, LISTED)
        self.assertFalse(app.picker.waiting)
        app._on_input(Key(DOWN))
        self.assertEqual(app.picker.index, 1)

    def test_resume_by_id_or_title_sends_no_listing_first(self) -> None:
        app, client = make_app()
        type_text(app, "/resume stored-2")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[0][0], "session.resume")
        self.assertFalse(any(SESSIONS_LOADING_LINE in line for line in drawn(app)))


RESUMED = {"session_id": "live-2", "stored_session_id": "s-other", "messages": [], "info": {"model": "m"}}


def pick_other(app: App, client: RecordingClient) -> int:
    """Open the picker, pick `s-other` (titled `other`), and return the `session.resume` call's id."""
    app.stored_id = "s-current"
    resume(app)
    reply(app, client, {"sessions": [{"id": "s-current", "title": "here"}, {"id": "s-other", "title": "other"}]})
    for _step in range(len(app.picker.rows)):
        if app.picker.visible()[app.picker.index].id == "s-other":
            break
        app._on_input(Key(DOWN))
    app._on_input(Key(ENTER))
    assert client.calls[-1][0] == "session.resume", client.calls[-1]
    return len(client.calls)


def submitted(client: RecordingClient) -> list[tuple[str, str]]:
    return [(params["session_id"], params["text"]) for method, params in client.calls if method == "prompt.submit"]


class SwitchWaitTests(unittest.TestCase):
    def test_a_picked_switch_says_where_it_goes_and_a_prompt_sent_meanwhile_goes_there(self) -> None:
        app, client = make_app()
        rid = pick_other(app, client)
        self.assertTrue(any("switching to other…" in line for line in drawn(app)))
        type_text(app, "do it in the other session")
        app._on_input(Key(ENTER))
        self.assertEqual(submitted(client), [])  # never into live-1, which the switch closes
        self.assertTrue(any("switching to other… · 1 prompt waits for it" in line for line in drawn(app)))
        app._on_response(Response(rid, RESUMED, None))
        self.assertEqual(submitted(client), [("live-2", "do it in the other session")])
        self.assertFalse(any("switching to" in line for line in drawn(app)))

    def test_a_prompt_sent_while_new_waits_goes_to_the_new_session(self) -> None:
        app, client = make_app()
        type_text(app, "/new")
        app._on_input(Key(ENTER))
        cid = len(client.calls)
        self.assertTrue(any("starting a new session…" in line for line in drawn(app)))
        type_text(app, "first prompt for the new session")
        app._on_input(Key(ENTER))
        self.assertEqual(submitted(client), [])
        app._on_response(Response(cid, {"session_id": "live-2", "stored_session_id": "s-new", "info": {}}, None))
        self.assertEqual(submitted(client), [("live-2", "first prompt for the new session")])

    def test_prompts_queued_behind_the_old_turn_come_back_to_the_composer(self) -> None:
        app, client = make_app(busy=True)
        app.queued.extend([QueuedLine("queued one"), QueuedLine("queued two")])
        rid = pick_other(app, client)
        app._on_response(Response(rid, RESUMED, None))
        self.assertEqual(list(app.queued), [])
        self.assertEqual(app.composer.text, "queued one\nqueued two")
        self.assertIn("2 prompts queued in the session you left went back to the composer; none was sent.",
                      notices(app, NOTICE_WARN))
        self.assertEqual(submitted(client), [])

    def test_a_prompt_held_for_a_switch_that_failed_comes_back(self) -> None:
        app, client = make_app()
        rid = pick_other(app, client)
        type_text(app, "held prompt")
        app._on_input(Key(ENTER))
        app._on_response(Response(rid, None, {"code": 4007, "message": "no such session"}))
        self.assertEqual(app.composer.text, "held prompt")
        self.assertIn("The switch did not happen, so 1 prompt held for it went back to the composer.",
                      notices(app, NOTICE_WARN))
        self.assertEqual(submitted(client), [])

    def test_only_the_newest_switch_lands_and_an_older_answer_is_closed_again(self) -> None:
        app, client = make_app()
        app.stored_id = "s-a"
        type_text(app, "/sessions s-b")
        app._on_input(Key(ENTER))
        rid_b = len(client.calls)
        type_text(app, "/sessions s-c")
        app._on_input(Key(ENTER))
        rid_c = len(client.calls)
        app._on_response(Response(rid_c, {"session_id": "live-c", "stored_session_id": "s-c", "messages": [],
                                          "info": {}}, None))
        app._on_response(Response(rid_b, {"session_id": "live-b", "stored_session_id": "s-b", "messages": [],
                                          "info": {}}, None))
        self.assertEqual((app.stored_id, app.sid), ("s-c", "live-c"))
        self.assertEqual(client.named("session.close"), [{"session_id": "live-1"}, {"session_id": "live-b"}])
        self.assertIn("Closed session s-b, which opened after a newer switch.", notices(app, NOTICE_WARN))

    def test_asking_twice_sends_one_list_and_an_open_picker_keeps_its_place(self) -> None:
        sessions = {"sessions": [{"id": f"s-{index}", "title": f"session {index}"} for index in range(5)]}
        app, client = make_app()
        app.stored_id = "s-0"
        ctrl_x = Key(CHAR, "x", ctrl=True)
        app._on_input(ctrl_x)
        app._on_input(ctrl_x)
        self.assertEqual([method for method, _params in client.calls], ["session.list"])
        reply(app, client, sessions)
        type_text(app, "session 3")
        app._open_session_picker(sessions)  # a late answer over the open picker
        self.assertEqual((app.picker.query, [row.id for row in app.picker.visible()]), ("session 3", ["s-3"]))


class EmptyPickerTests(unittest.TestCase):
    def test_an_empty_list_says_no_stored_sessions_and_a_filter_says_it_hides_them(self) -> None:
        empty = SessionPicker([], current="")
        self.assertIn("no stored sessions", line_text(empty.lines(60, DEFAULT_THEME, 1, 0.0)[0]))
        filtered = SessionPicker([SessionRow("stored-1", "a title", "", 0.0, 1)], current="", query="zzz")
        self.assertIn("no session matches the filter", line_text(filtered.lines(60, DEFAULT_THEME, 1, 0.0)[0]))


class PickAtStartTests(unittest.TestCase):
    def started(self, environ: dict) -> tuple[App, RecordingClient]:
        class Creating(RecordingClient):
            def call(self, method: str, params: dict, timeout: float = 30.0) -> dict:
                self.calls.append((method, params))
                return {"session_id": SID, "stored_session_id": "stored-1", "info": {"model": "m"}}

        client = Creating()
        app = App(ScriptedTerminal(40, 100), client, {"OMH_TUI_GLOW": "0", "OMH_TUI_WALLPAPER": "0", **environ},
                  poller=FakePoller())  # type: ignore[arg-type]
        app.startup()
        return app, client

    def test_a_bare_omh_resume_opens_the_picker_as_the_tui_starts(self) -> None:
        app, client = self.started({PICK_SESSION_ENV: "1"})
        self.assertEqual(client.calls[0][0], "session.create")
        self.assertIn(("session.list", {"limit": SESSION_LIST_LIMIT}), client.calls)
        self.assertTrue(app._sessions_loading())
        reply(app, client, LISTED)
        self.assertIsNotNone(app.picker)
        app._on_input(Key(ENTER))  # Enter picks the highlighted (first) row
        self.assertEqual(client.calls[-1][0], "session.resume")

    def test_a_plain_launch_opens_no_picker(self) -> None:
        app, client = self.started({})
        self.assertFalse(app._sessions_loading())
        self.assertIsNone(app.picker)


if __name__ == "__main__":
    unittest.main()
