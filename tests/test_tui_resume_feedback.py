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
from omh.tui.keys import BACKSPACE, CHAR, DOWN, ENTER, ESCAPE, Key
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
                app, client = make_app()
                resume(app)  # asked between turns: typed during one, it would wait for its end
                app.turn_pending = True  # a turn started while the list was out
                app.transcript.blocks.append(AssistantBlock("streaming", done=False))
                reply(app, client, result, error)
                self.assertFalse(app.transcript.blocks[0].done)  # the live reply is still open
                self.assertTrue(any(said[:40] in line for line in drawn(app)))

    def test_text_typed_while_the_list_is_out_stays_in_the_composer(self) -> None:
        for busy in (False, True):
            with self.subTest(busy=busy):
                now = [100.0]
                app, client = make_app(clock=lambda: now[0])
                resume(app)  # asked between turns: typed during one, it would wait for its end
                if busy:  # a turn started while the list was out
                    app.turn_pending = True
                    app.transcript.blocks.append(AssistantBlock("streaming", done=False))
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
                app, client = make_app(clock=lambda: now[0])
                resume(app)  # asked between turns, or at the end of the turn it waited for
                if busy:  # a turn started while the list was out
                    app.turn_pending = True
                    app.transcript.blocks.append(AssistantBlock("streaming", done=False))

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
                self.assertTrue(any("↑↓ to pick · keep typing to stay in your prompt" in line for line in screen))
                typed("미나 그런 스타일")
                self.assertEqual((app.picker.query, app.composer.text), ("", "바꾸고 리드미나 그런 스타일"))
                self.assertEqual(len(app.picker.visible()), 2)
                now[0] += 0.6  # a natural pause mid-prompt: the rest of it is still the composer's
                typed(" 해줘")
                self.assertEqual((app.picker.query, app.composer.text), ("", "바꾸고 리드미나 그런 스타일 해줘"))
                app._on_input(Key(DOWN))  # a key of the picker's own hands it the keys
                self.assertFalse(app.picker.waiting)
                app._on_input(Key(CHAR, "e"))
                self.assertEqual((app.picker.query, app.composer.text), ("e", "바꾸고 리드미나 그런 스타일 해줘"))
                app._on_input(Key(ESCAPE))
                self.assertIsNone(app.picker)
                self.assertEqual(app.composer.text, "바꾸고 리드미나 그런 스타일 해줘")

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
    """Open the picker, pick `s-other` (titled `other`), and return the `session.resume` call's id.

    The picker is asked for between turns, as a typed `/resume` waits for a running turn's end; a turn `app` runs
    started while it was open."""
    app.stored_id = "s-current"
    busy, app.turn_pending = app.turn_pending, False
    resume(app)
    app.turn_pending = busy
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


class ReviewFollowUpTests(unittest.TestCase):
    def test_esc_reaches_a_waiting_picker_and_enter_sends_the_prompt(self) -> None:
        app, client = make_app()
        resume(app)
        type_text(app, "draft")
        reply(app, client, LISTED)
        self.assertTrue(app.picker.waiting)
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.picker)
        self.assertEqual(app.composer.text, "draft")
        resume_again = make_app()
        app, client = resume_again
        resume(app)
        type_text(app, "send me")
        reply(app, client, LISTED)
        app._on_input(Key(ENTER))  # what was typed is sent, and the picker still waits
        self.assertEqual(submitted(client), [(SID, "send me")])
        self.assertTrue(app.picker.waiting)
        self.assertTrue(any("keep typing to stay in your prompt" in line for line in drawn(app)))
        type_text(app, "the next prompt")  # typed after the Enter: the composer's, as the hint says
        self.assertEqual((app.picker.query, app.composer.text), ("", "the next prompt"))
        app._on_input(Key(DOWN))
        app._on_input(Key(CHAR, "x"))
        self.assertEqual((app.picker.query, app.composer.text), ("x", "the next prompt"))

    def test_a_titled_resume_picker_waits_for_typing_too(self) -> None:
        app, client = make_app()
        type_text(app, "/resume shared title")
        app._on_input(Key(ENTER))
        rid = len(client.calls)
        type_text(app, "typing")
        app._on_response(Response(rid, None, {"code": app_module.RESUME_REFUSED, "message": "not found"}))
        lookup = len(client.calls)
        app._on_response(Response(lookup, {"sessions": []}, None))
        scan = len(client.calls)
        rows = [{"id": "s-1", "title": "Shared title"}, {"id": "s-2", "title": "SHARED title"}]  # none exact
        app._on_response(Response(scan, {"sessions": rows}, None))
        self.assertTrue(app.picker.waiting)
        type_text(app, " more")
        self.assertEqual((app.picker.query, app.composer.text), ("shared title", "typing more"))

    def test_a_second_switch_to_the_same_target_sends_nothing_and_closes_nothing(self) -> None:
        app, client = make_app()
        app.stored_id = "s-a"
        for _ in range(2):
            type_text(app, "/sessions s-b")
            app._on_input(Key(ENTER))
        self.assertEqual(len(client.named("session.resume")), 1)
        rid = len(client.calls)
        app._on_response(Response(rid, {"session_id": "s-b", "stored_session_id": "s-b", "messages": [], "info": {}},
                                  None))
        self.assertEqual((app.sid, client.named("session.close")), ("s-b", [{"session_id": "live-1"}]))

    def test_a_stale_answer_never_closes_the_session_the_newest_switch_goes_to(self) -> None:
        app, client = make_app()
        app.stored_id = "s-a"
        for target in ("s-b", "s-c", "s-b"):  # back to s-b while its first switch is out: that one is newest again
            type_text(app, f"/sessions {target}")
            app._on_input(Key(ENTER))
        rid_b, rid_c = 1, 2
        self.assertEqual(len(client.named("session.resume")), 2)
        app._on_response(Response(rid_c, {"session_id": "s-c", "stored_session_id": "s-c", "messages": [],
                                          "info": {}}, None))
        app._on_response(Response(rid_b, {"session_id": "s-b", "stored_session_id": "s-b", "messages": [],
                                          "info": {}}, None))
        self.assertEqual(app.sid, "s-b")
        self.assertEqual(client.named("session.close"), [{"session_id": "s-c"}, {"session_id": "live-1"}])
        self.assertIn("Closed session s-c, which opened after a newer switch.", notices(app, NOTICE_WARN))

    def test_in_natural_order_the_stale_notice_is_said_on_the_new_screen(self) -> None:
        app, client = make_app()
        app.stored_id = "s-a"
        type_text(app, "/sessions s-b")
        app._on_input(Key(ENTER))
        type_text(app, "/sessions s-c")
        app._on_input(Key(ENTER))
        app._on_response(Response(1, {"session_id": "live-b", "stored_session_id": "s-b", "messages": [],
                                      "info": {}}, None))
        app._on_response(Response(2, {"session_id": "live-c", "stored_session_id": "s-c", "messages": [],
                                      "info": {}}, None))
        self.assertEqual(app.stored_id, "s-c")
        self.assertIn({"session_id": "live-b"}, client.named("session.close"))
        self.assertIn("Closed session s-b, which opened after a newer switch.", notices(app, NOTICE_WARN))

    def test_an_older_switch_still_out_holds_nothing_once_the_newest_landed(self) -> None:
        app, client = make_app()
        app.stored_id = "s-a"
        type_text(app, "/sessions s-b")
        app._on_input(Key(ENTER))
        type_text(app, "/sessions s-c")
        app._on_input(Key(ENTER))
        app._on_response(Response(2, {"session_id": "live-c", "stored_session_id": "s-c", "messages": [],
                                      "info": {}}, None))
        self.assertFalse(any("switching to" in line for line in drawn(app)))
        type_text(app, "for s-c")
        app._on_input(Key(ENTER))
        self.assertEqual(submitted(client), [("live-c", "for s-c")])

    def test_a_stale_refusal_or_title_lookup_does_nothing(self) -> None:
        app, client = make_app()
        app.stored_id = "s-a"
        type_text(app, "/sessions old title")
        app._on_input(Key(ENTER))
        type_text(app, "/sessions s-c")
        app._on_input(Key(ENTER))
        before = list(client.calls)
        app._on_response(Response(1, None, {"code": app_module.RESUME_REFUSED, "message": "not found"}))
        self.assertEqual(client.calls, before)  # no title lookup for a switch a newer one replaced
        self.assertNotIn("Could not switch", " ".join(notices(app)))
        app._on_response(Response(2, None, {"code": 4007, "message": "gone"}))
        self.assertIn("Could not switch to s-c (4007): gone. Still in s-a.", notices(app, NOTICE_WARN))

    def test_a_stale_title_lookup_answer_says_nothing_and_switches_nowhere(self) -> None:
        for listed in ([{"id": "old title"}], [{"id": "s-9", "title": "old title"}]):
            with self.subTest(listed=listed):
                app, client = make_app()
                app.stored_id = "s-a"
                type_text(app, "/sessions old title")
                app._on_input(Key(ENTER))
                app._on_response(Response(1, None, {"code": app_module.RESUME_REFUSED, "message": "not found"}))
                lookup = len(client.calls)
                type_text(app, "/sessions s-c")
                app._on_input(Key(ENTER))
                calls = len(client.calls)
                app._on_response(Response(lookup, {"sessions": listed}, None))
                self.assertEqual(len(client.calls), calls)  # nothing resumed for the replaced switch
                self.assertNotIn("Could not switch to old title", " ".join(notices(app)))

    def test_a_stale_create_refusal_says_nothing(self) -> None:
        app, client = make_app()
        type_text(app, "/new")
        app._on_input(Key(ENTER))
        type_text(app, "/sessions s-c")
        app._on_input(Key(ENTER))
        app._on_response(Response(1, None, {"code": 5000, "message": "no"}))
        self.assertNotIn("Could not start a new session", " ".join(notices(app)))

    def test_a_plan_mode_prompt_sent_during_a_switch_waits_for_the_new_session(self) -> None:
        app, client = make_app()
        app.plan_mode = True
        rid = pick_other(app, client)
        type_text(app, "plan this")
        app._on_input(Key(ENTER))
        self.assertEqual([method for method, _params in client.calls[rid:]], [])
        app._on_response(Response(rid, RESUMED, None))
        sent = [params for method, params in client.calls[rid:] if method in ("slash.exec", "command.dispatch")]
        self.assertTrue(sent and all(params.get("session_id") == "live-2" for params in sent), client.calls[rid:])

    def test_a_switch_answered_after_its_expiry_is_closed_again(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        app.stored_id = "s-a"
        type_text(app, "/sessions s-b")
        app._on_input(Key(ENTER))
        now[0] += app_module.CALL_ANSWER_SECONDS
        app._expire_calls()
        app._on_response(Response(1, {"session_id": "live-b", "stored_session_id": "s-b", "messages": [],
                                      "info": {}}, None))
        self.assertEqual((app.sid, client.named("session.close")), (SID, [{"session_id": "live-b"}]))


def landed(app: App, request_id: int, sid: str, stored: str) -> None:
    app._on_response(Response(request_id, {"session_id": sid, "stored_session_id": stored, "messages": [],
                                           "info": {}}, None))


class VerificationFollowUpTests(unittest.TestCase):
    def test_a_switch_asked_again_never_shares_its_number_with_a_later_one(self) -> None:
        for order in ("newest first", "oldest first"):
            with self.subTest(order=order):
                app, client = make_app()
                app.stored_id = "s-a"
                ids = {}
                for target in ("s-t", "s-u", "s-t", "s-v"):
                    type_text(app, f"/sessions {target}")
                    app._on_input(Key(ENTER))
                    ids.setdefault(target, len(client.calls))
                self.assertEqual(len(client.named("session.resume")), 3)
                type_text(app, "for v")
                app._on_input(Key(ENTER))
                self.assertEqual(submitted(client), [])
                answers = [("s-t", "live-t"), ("s-u", "live-u"), ("s-v", "live-v")]
                for stored, sid in (reversed(answers) if order == "newest first" else answers):
                    landed(app, ids[stored], sid, stored)
                self.assertEqual((app.sid, app.stored_id), ("live-v", "s-v"))
                self.assertEqual(submitted(client), [("live-v", "for v")])
                closed = [params["session_id"] for params in client.named("session.close")]
                self.assertIn("live-t", closed)
                self.assertIn("live-u", closed)
                self.assertNotIn("live-v", closed)

    def test_a_title_resolving_to_the_target_of_a_switch_out_never_has_it_closed(self) -> None:
        app, client = make_app()
        app.stored_id = "s-a"
        type_text(app, "/sessions s-b")
        app._on_input(Key(ENTER))  # slow
        type_text(app, "/resume title of b")
        app._on_input(Key(ENTER))
        app._on_response(Response(2, None, {"code": app_module.RESUME_REFUSED, "message": "not found"}))
        lookup = len(client.calls)
        app._on_response(Response(lookup, {"sessions": [{"id": "s-b", "resolved_id": "s-b", "title": "title of b"}]},
                                  None))
        second = len(client.calls)
        self.assertEqual(client.calls[-1], ("session.resume", {"session_id": "s-b", "cols": 80}))
        landed(app, 1, "s-b", "s-b")  # the first switch's answer, now stale: on the shared gateway the id is the same
        self.assertNotIn({"session_id": "s-b"}, client.named("session.close"))
        landed(app, second, "s-b", "s-b")
        self.assertEqual(app.sid, "s-b")
        self.assertNotIn({"session_id": "s-b"}, client.named("session.close"))

    def test_the_old_queue_does_not_drain_while_a_switch_is_out(self) -> None:
        app, client = make_app(busy=True)
        app.queued.append(QueuedLine("queued in the old session"))
        pick_other(app, client)
        app.transcript.running = False
        app.turn_pending = False
        app._drain_queue()  # the old turn ended while the switch is out
        self.assertEqual(submitted(client), [])
        self.assertEqual([line.text for line in app.queued], ["queued in the old session"])

    def test_already_in_the_session_sends_what_was_held_there(self) -> None:
        app, client = make_app()
        rid = pick_other(app, client)
        type_text(app, "held prompt")
        app._on_input(Key(ENTER))
        landed(app, rid, SID, "s-current")  # Hermes answered with the session the TUI is in
        self.assertEqual(submitted(client), [(SID, "held prompt")])

    def test_a_switch_back_to_this_session_sends_what_was_held(self) -> None:
        app, client = make_app()
        pick_other(app, client)
        type_text(app, "held prompt")
        app._on_input(Key(ENTER))
        type_text(app, "/sessions s-current")
        app._on_input(Key(ENTER))
        self.assertEqual(submitted(client), [(SID, "held prompt")])

    def test_a_list_that_lands_over_a_waiting_session_picker_does_not_open(self) -> None:
        from test_tui_late_answers import OPTIONS

        app, client = make_app()
        resume(app)
        type_text(app, "draft")
        reply(app, client, LISTED)
        self.assertTrue(app.picker.waiting)
        app._open_model_picker(SID, OPTIONS)
        self.assertIsNone(app.model_picker)
        self.assertIsNotNone(app.picker)


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
        app = App(ScriptedTerminal(40, 100), client, {"OMH_TUI_WALLPAPER": "0", **environ},
                  poller=FakePoller())  # type: ignore[arg-type]
        app.startup()
        return app, client

    def test_a_bare_omh_resume_opens_the_picker_as_the_tui_starts(self) -> None:
        app, client = self.started({PICK_SESSION_ENV: "1"})
        self.assertEqual(client.calls[0][0], "session.create")
        self.assertEqual([params for method, params in client.calls if method == "session.list"],
                         [{"limit": SESSION_LIST_LIMIT}])  # the picker's list alone, no last-session lookup
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


class PickerEditTests(unittest.TestCase):
    """Ctrl+R and Ctrl+D in the open session picker: one `session.title` or `session.delete` call each, on the
    person's keys, its answer said on the row."""

    def opened(self, stored: str = "stored-1") -> tuple[App, RecordingClient]:
        app, client = make_app()
        app.stored_id = stored
        resume(app)
        reply(app, client, LISTED)
        assert app.picker is not None
        drawn(app)  # the day groups order the rows
        return app, client

    def last(self, client: RecordingClient) -> int:
        return len(client.calls)

    def rename(self, app: App, title: str) -> None:
        app._on_input(Key(CHAR, "r", ctrl=True))
        assert app.picker is not None
        for _ in app.picker.title:
            app._on_input(Key(BACKSPACE))
        type_text(app, title)
        app._on_input(Key(ENTER))

    def test_rename_sends_session_title_and_the_answer_updates_the_row(self) -> None:
        app, client = self.opened()
        self.rename(app, "Release prep")
        self.assertEqual(client.calls[-1], ("session.title", {"session_id": "stored-2", "title": "Release prep"}))
        self.assertIsNotNone(app.picker)  # it stays open
        self.assertTrue(any("renaming…" in line for line in drawn(app)))
        app._on_response(Response(self.last(client), {"pending": False, "title": "Release prep"}, None))
        assert app.picker is not None
        self.assertEqual(app.picker.rows[0].title, "Release prep")
        screen = drawn(app)
        self.assertTrue(any("Release prep" in line for line in screen))
        self.assertFalse(any("an earlier session" in line for line in screen))
        self.assertEqual(notices(app), [])

    def test_a_refused_rename_says_hermes_words_on_the_row_and_changes_nothing(self) -> None:
        app, client = self.opened()
        self.rename(app, "Release prep")
        app._on_response(Response(self.last(client), None, {"code": 4001, "message": "session not found"}))
        assert app.picker is not None
        self.assertEqual(app.picker.rows[0].title, "an earlier session")
        self.assertTrue(any("Session not found" in line for line in drawn(app)))
        self.assertEqual(notices(app), [])  # said on the row, not in the transcript
        app._on_input(Key(DOWN))
        self.assertFalse(any("Session not found" in line for line in drawn(app)))

    def test_an_empty_title_and_esc_send_nothing(self) -> None:
        app, client = self.opened()
        sent = len(client.calls)
        self.rename(app, "  ")
        app._on_input(Key(ESCAPE))
        self.assertEqual(len(client.calls), sent)
        self.assertIsNotNone(app.picker)  # Esc left the field, not the picker
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.picker)
        self.assertEqual(len(client.calls), sent)

    def test_the_current_session_is_renamed_by_its_live_id_and_its_title_shows(self) -> None:
        app, client = self.opened(stored="stored-2")  # the TUI is in stored-2: it heads the list
        self.rename(app, "Mine")
        self.assertEqual(client.calls[-1], ("session.title", {"session_id": SID, "title": "Mine"}))
        app._on_response(Response(self.last(client), {"pending": False, "title": "Mine"}, None))
        self.assertEqual(app.session_title, "Mine")

    def test_ctrl_d_twice_sends_session_delete_and_the_answer_removes_the_row(self) -> None:
        app, client = self.opened()
        sent = len(client.calls)
        app._on_input(Key(CHAR, "d", ctrl=True))
        self.assertEqual(len(client.calls), sent)  # the first press only asks
        self.assertTrue(any("press ctrl+d again to delete" in line for line in drawn(app)))
        app._on_input(Key(CHAR, "d", ctrl=True))
        self.assertEqual(client.calls[-1], ("session.delete", {"session_id": "stored-2"}))
        app._on_response(Response(self.last(client), {"deleted": "stored-2"}, None))
        assert app.picker is not None
        self.assertEqual([row.id for row in app.picker.rows], ["stored-3"])
        self.assertTrue(any("Sessions (1)" in line for line in drawn(app)))

    def test_ctrl_d_then_down_sends_nothing_and_the_current_session_is_refused_here(self) -> None:
        app, client = self.opened()
        sent = len(client.calls)
        app._on_input(Key(CHAR, "d", ctrl=True))
        app._on_input(Key(DOWN))
        self.assertEqual(len(client.calls), sent)
        self.assertFalse(any("press ctrl+d again" in line for line in drawn(app)))
        app, client = self.opened(stored="stored-2")
        sent = len(client.calls)
        app._on_input(Key(CHAR, "d", ctrl=True))
        app._on_input(Key(CHAR, "d", ctrl=True))
        self.assertEqual(len(client.calls), sent)
        self.assertTrue(any("not deleted from here" in line for line in drawn(app)))

    def test_a_refused_delete_keeps_the_row_and_says_why(self) -> None:
        app, client = self.opened()
        app._on_input(Key(CHAR, "d", ctrl=True))
        app._on_input(Key(CHAR, "d", ctrl=True))
        app._on_response(Response(self.last(client), None, {"code": 4023, "message": "cannot delete an active session"}))
        assert app.picker is not None
        self.assertEqual([row.id for row in app.picker.rows], ["stored-2", "stored-3"])
        self.assertTrue(any("Cannot delete an active session" in line for line in drawn(app)))

    def test_an_answer_naming_another_session_is_not_taken_as_done(self) -> None:
        app, client = self.opened()
        app._on_input(Key(CHAR, "d", ctrl=True))
        app._on_input(Key(CHAR, "d", ctrl=True))
        app._on_response(Response(self.last(client), {"deleted": "stored-9"}, None))
        assert app.picker is not None
        self.assertEqual(len(app.picker.rows), 2)
        self.assertTrue(any("Hermes did not say it was done" in line for line in drawn(app)))

    def test_an_answer_after_the_picker_closed_is_a_notice(self) -> None:
        app, client = self.opened()
        app._on_input(Key(CHAR, "d", ctrl=True))
        app._on_input(Key(CHAR, "d", ctrl=True))
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.picker)
        app._on_response(Response(self.last(client), {"deleted": "stored-2"}, None))
        self.assertEqual(notices(app), ["Deleted session stored-2."])
        app, client = self.opened()
        self.rename(app, "x")
        app._on_input(Key(ESCAPE))
        app._on_response(Response(self.last(client), None, {"code": 4001, "message": "session not found"}))
        self.assertEqual(notices(app), ["Hermes did not rename the session: session not found."])
