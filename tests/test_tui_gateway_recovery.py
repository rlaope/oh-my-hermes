"""The OMH TUI on a shared Hermes gateway that is slow or busy, as Hermes' own Ink TUI rides it out.

A dropped attach connection is not a dead gateway: the respawn resumes the
session and keeps a turn the resume says still runs. A launch's `--resume`
that Hermes refuses as itself is said and exits 1, rather than falling back to
Hermes' TUI, which opens a new session in its place. The session calls of a
launch and a respawn wait `CALL_ANSWER_SECONDS`, as in-session calls do.
`session.replay_gap` resumes the live session; `skills.changed` asks for the
command catalog again; a turn Hermes interrupted itself says so, and goes on
by itself with the `continue` the notice names, unless the person stopped it,
moved past it or cancels the short wait. Every case drives an `App` over
recording clients; the clock is the test's.
"""

from __future__ import annotations

import io
import unittest

from _tui_lines import line_text
from test_tui_app import FakePoller, ScriptedTerminal
from test_tui_modes import SID, answer, make_app, notices, type_text
from test_tui_respawn import ENVIRON, STORED, RespawnClient, Spawner, crash, crashing
from omh.tui.app import (
    AUTO_CONTINUE_ASKED,
    AUTO_CONTINUE_DRAFTED,
    AUTO_CONTINUE_ESCAPED,
    AUTO_CONTINUE_HELD_NOTICE,
    AUTO_CONTINUE_LEFT,
    AUTO_CONTINUE_LIMIT,
    AUTO_CONTINUE_QUEUED,
    AUTO_CONTINUE_SECONDS,
    AUTO_CONTINUE_SENT,
    AUTO_CONTINUE_UNSENT,
    CALL_ANSWER_SECONDS,
    GATEWAY_SILENCE_SECONDS,
    RECONNECTED_NOTICE,
    RECONNECTED_WHY,
    REPLAY_GAP_REFUSED_NOTICE,
    REPLAY_GAP_WHY,
    RESPAWN_LIMIT,
    RESPAWN_NOTICE,
    RESPAWN_WINDOW_SECONDS,
    RESPAWNED_NOTICE,
    TURN_ENDED_UNSEEN_NOTICE,
    TURN_LEFT_RUNNING_NOTICE,
    TURN_LOST_NOTICE,
    TURN_MOVED_NOTICE,
    HeldSubmit,
    QueuedLine,
    _run,
    _Told,
)
from omh.tui.composer import VIM_NORMAL, Composer
from omh.tui.gateway import Event, GatewayCallError, Response
from omh.tui.keys import ENTER, ESCAPE, Key
from omh.tui.launch import FALLBACK_EXIT
from omh.tui.transcript import HERMES_INTERRUPTED_NOTICE, HERMES_RESUMING_NOTICE, INTERRUPTED_NOTICE

RESUMING = HERMES_RESUMING_NOTICE.format(seconds=f"{AUTO_CONTINUE_SECONDS:g}")
HERMES_STOPPED = {"text": "", "status": "interrupted"}  # Hermes' frame for an interrupted turn names no cause

SHARED_RESUMED = {"session_id": "live-2", "stored_session_id": STORED, "subscription_id": "sub-2",
                  "info": {"model": "m"}, "messages": []}


class TimedClient(RespawnClient):
    """A respawn client that also keeps how long each blocking call was given."""

    def __init__(self, *args: object, **options: object) -> None:
        super().__init__(*args, **options)  # type: ignore[arg-type]
        self.timeouts: list[float] = []

    def call(self, method: str, params: dict, timeout: float = 30.0, cancel: object = None) -> dict:
        self.timeouts.append(timeout)
        return super().call(method, params, timeout, cancel)


def streaming(app: object, ours: bool = False) -> None:
    """The live session's turn is under way, its reply half streamed; `ours`: a turn this TUI's prompt started."""
    if ours:
        app.turn_pending = True  # type: ignore[attr-defined]  # a prompt out, as `_send_submit` leaves it
    app._on_event(Event("message.start", SID, {}))  # type: ignore[attr-defined]
    app._on_event(Event("message.delta", SID, {"text": "half of the reply"}))  # type: ignore[attr-defined]


class DroppedConnectionTests(unittest.TestCase):
    """Finding 1: the attach child's connection to a shared gateway ends (exit 1) while the gateway runs on."""

    def dropped(self, resume: dict | Exception, busy: bool = True) -> tuple[object, Spawner]:
        new = RespawnClient(resume=resume)
        spawner = Spawner(new)
        app, old, _spawner, _now = crashing(spawner=spawner)
        app.sid = SID
        app.shared_gateway = True
        if busy:
            streaming(app)
        crash(app, old, 1)
        return app, spawner

    def test_a_drop_with_the_turn_still_running_says_no_turn_lost_and_keeps_the_turn(self) -> None:
        app, spawner = self.dropped({**SHARED_RESUMED, "session_id": SID, "running": True})
        said = notices(app)
        self.assertNotIn(TURN_LOST_NOTICE, said)
        self.assertFalse([line for line in said if "gateway exited" in line], said)
        self.assertIn(RESPAWN_NOTICE.format(
            reason="The connection to Hermes' gateway dropped; the turn may still be running", session=STORED,
            attempt=1, limit=RESPAWN_LIMIT, window=RESPAWN_WINDOW_SECONDS), said)
        self.assertIn(RECONNECTED_NOTICE.format(session=STORED), said)
        self.assertNotIn(RESPAWNED_NOTICE.format(session=STORED), said)
        self.assertTrue(app._busy())  # type: ignore[attr-defined]
        self.assertTrue(app.transcript.running)  # type: ignore[attr-defined]
        # The turn's events go on arriving over the new connection, and its end closes it as any turn's does.
        app._on_event(Event("message.complete", SID, {"text": "the whole reply", "status": "complete"}))  # type: ignore[attr-defined]
        self.assertFalse(app._busy())  # type: ignore[attr-defined]
        self.assertEqual(spawner.made[0].named("prompt.submit"), [])

    def test_a_drop_whose_resume_says_the_turn_is_over_says_it_ended_unseen(self) -> None:
        app, _spawner = self.dropped({**SHARED_RESUMED, "running": False})
        said = notices(app)
        self.assertIn(TURN_ENDED_UNSEEN_NOTICE, said)
        self.assertNotIn(TURN_LOST_NOTICE, said)
        self.assertFalse(app._busy())  # type: ignore[attr-defined]

    def test_the_queue_is_held_naming_the_dropped_connection(self) -> None:
        new = RespawnClient(resume={**SHARED_RESUMED, "running": True})
        app, old, _spawner, _now = crashing(spawner=Spawner(new))
        app.sid, app.shared_gateway = SID, True
        streaming(app)
        app.queued.append(QueuedLine("next one"))
        crash(app, old, 1)
        self.assertIn(f"{RECONNECTED_WHY}: what you queued is back in the composer, not sent.", notices(app))

    def test_a_drop_the_new_connection_cannot_resume_leaves_the_turn_as_possibly_running(self) -> None:
        refused = GatewayCallError("session.resume", 4004, "not_found")
        app, _spawner = self.dropped(refused)
        said = notices(app)
        self.assertEqual(app.exit_code, 1)  # type: ignore[attr-defined]
        self.assertIn(TURN_LEFT_RUNNING_NOTICE, said)
        self.assertNotIn(TURN_LOST_NOTICE, said)
        self.assertFalse(app.transcript.running)  # type: ignore[attr-defined]  # the live block went to the scrollback

    def test_a_drop_with_no_turn_running_names_only_the_connection(self) -> None:
        app, _spawner = self.dropped({**SHARED_RESUMED, "running": False}, busy=False)
        said = notices(app)
        self.assertIn(RESPAWN_NOTICE.format(
            reason="The connection to Hermes' gateway dropped", session=STORED, attempt=1, limit=RESPAWN_LIMIT,
            window=RESPAWN_WINDOW_SECONDS), said)
        self.assertNotIn(TURN_ENDED_UNSEEN_NOTICE, said)

    def test_another_exit_code_on_a_shared_gateway_still_says_it_exited(self) -> None:
        new = RespawnClient(resume={**SHARED_RESUMED, "running": True})
        app, old, _spawner, _now = crashing(spawner=Spawner(new))
        app.sid, app.shared_gateway = SID, True
        crash(app, old, 69)
        self.assertIn(RESPAWN_NOTICE.format(
            reason="The Hermes gateway exited (code 69)", session=STORED, attempt=1, limit=RESPAWN_LIMIT,
            window=RESPAWN_WINDOW_SECONDS), notices(app))

    def test_a_different_authority_epoch_is_a_gateway_that_started_again(self) -> None:
        new = RespawnClient(resume={**SHARED_RESUMED, "session_id": SID, "authority_epoch": 2, "running": False})
        app, old, _spawner, _now = crashing(spawner=Spawner(new))
        app.sid, app.shared_gateway, app.authority_epoch = SID, True, 1
        streaming(app)
        crash(app, old, 1)
        said = notices(app)
        self.assertIn(TURN_LOST_NOTICE, said)
        self.assertIn(RESPAWNED_NOTICE.format(session=STORED), said)
        self.assertNotIn(RECONNECTED_NOTICE.format(session=STORED), said)
        self.assertNotIn(TURN_ENDED_UNSEEN_NOTICE, said)

    def test_the_same_authority_epoch_is_the_same_gateway(self) -> None:
        new = RespawnClient(resume={**SHARED_RESUMED, "session_id": SID, "authority_epoch": 1, "running": True})
        app, old, _spawner, _now = crashing(spawner=Spawner(new))
        app.sid, app.shared_gateway, app.authority_epoch = SID, True, 1
        streaming(app)
        crash(app, old, 1)
        said = notices(app)
        self.assertIn(RECONNECTED_NOTICE.format(session=STORED), said)
        self.assertNotIn(TURN_LOST_NOTICE, said)
        self.assertTrue(app._busy())

    def test_a_kept_turn_keeps_its_clock_and_the_persons_stop(self) -> None:
        new = RespawnClient(resume={**SHARED_RESUMED, "session_id": SID, "running": True})
        app, old, _spawner, now = crashing(spawner=Spawner(new))
        app.sid, app.shared_gateway = SID, True
        streaming(app)
        started = app.busy_since
        app.interrupting = True  # the person pressed Esc; the connection dropped before the turn ended
        now[0] += 30
        crash(app, old, 1)
        self.assertEqual(app.busy_since, started)
        self.assertTrue(app.interrupting)
        app._on_event(Event("message.complete", SID, {"text": "", "status": "interrupted"}))
        said = notices(app)
        self.assertIn(INTERRUPTED_NOTICE, said)
        self.assertNotIn(HERMES_INTERRUPTED_NOTICE, said)

    def test_only_a_started_admission_is_a_live_turn(self) -> None:
        # Hermes holds a queue behind an `unknown` head (a turn it lost) until that head is settled: a queued row may
        # never start, and reading it as a turn would leave the screen working forever.
        for statuses, live in ((("started",), True), (("queued",), False), (("unknown", "queued"), False),
                               (("unknown",), False)):
            with self.subTest(statuses=statuses):
                resumed = {**SHARED_RESUMED, "session_id": SID, "running": False,
                           "pending": [{"admission_id": f"a{n}", "status": status} for n, status in enumerate(statuses)]}
                app, _spawner = self.dropped(resumed)
                self.assertEqual(app._busy(), live)  # type: ignore[attr-defined]
                self.assertEqual(TURN_ENDED_UNSEEN_NOTICE in notices(app), not live)

    def test_a_session_adopted_behind_a_paused_queue_is_idle(self) -> None:
        app, _client = make_app()
        app._adopt_session({"session_id": SID, "running": False, "info": {},
                            "pending": [{"admission_id": "a1", "status": "unknown"},
                                        {"admission_id": "a2", "status": "queued"}]})
        self.assertFalse(app._busy())

    def test_no_epoch_before_is_no_restart(self) -> None:
        new = RespawnClient(resume={**SHARED_RESUMED, "session_id": SID, "authority_epoch": 5, "running": True})
        app, old, _spawner, _now = crashing(spawner=Spawner(new))
        app.sid, app.shared_gateway, app.authority_epoch = SID, True, None
        streaming(app)
        crash(app, old, 1)
        said = notices(app)
        self.assertIn(RECONNECTED_NOTICE.format(session=STORED), said)
        self.assertNotIn(TURN_LOST_NOTICE, said)

    def test_the_silence_count_starts_again_at_a_reconnect_no_exit_reported(self) -> None:
        # A write the dead child refused starts the respawn with nothing drained from the gateway.
        new = RespawnClient(resume={**SHARED_RESUMED, "session_id": SID, "running": True})
        app, _old, _spawner, now = crashing(spawner=Spawner(new))
        app.sid, app.shared_gateway = SID, True
        streaming(app)
        app.inbound_at = now[0]
        now[0] += GATEWAY_SILENCE_SECONDS + 15
        app._gateway_gone("the gateway stopped reading its input")
        app._respawn_gateway()
        self.assertTrue(app._busy())
        self.assertNotIn("no word from", "\n".join(line_text(line) for line in app._tail(120)))

    def test_the_silence_count_starts_again_at_the_reconnect(self) -> None:
        new = RespawnClient(resume={**SHARED_RESUMED, "session_id": SID, "running": True})
        app, old, _spawner, now = crashing(spawner=Spawner(new))
        app.sid, app.shared_gateway = SID, True
        streaming(app)
        app.inbound_at = now[0]
        now[0] += GATEWAY_SILENCE_SECONDS + 15  # the kept turn's clock goes back to its start
        crash(app, old, 1)
        self.assertNotIn("no word from", "\n".join(line_text(line) for line in app._tail(120)))

    def test_a_crash_of_a_gateway_the_child_ran_itself_still_loses_the_turn(self) -> None:
        app, old, _spawner, _now = crashing(busy=True)  # the stdio entry: no subscription, the child is the gateway
        crash(app, old, 1)
        self.assertIn(TURN_LOST_NOTICE, notices(app))
        self.assertIn(RESPAWNED_NOTICE.format(session=STORED), notices(app))


class RefusedLaunchResumeTests(unittest.TestCase):
    """Finding 2: `omh --resume <id>` that Hermes refuses as itself ends the launch, saying why."""

    def launch(self, refusal: GatewayCallError, resume: str = STORED) -> tuple[int, str]:
        client = RespawnClient(resume=refusal)
        said = io.StringIO()
        environ = {**ENVIRON, "HERMES_TUI_RESUME": resume} if resume else dict(ENVIRON)
        terminal = ScriptedTerminal(24, 80)
        code = _run(client, environ, _Told(said), lambda: terminal, lambda omh, hermes: FakePoller(),  # type: ignore[arg-type]
                    Spawner(), contain_faults=False)
        self.assertEqual(terminal.entered, 0)  # nothing was drawn
        return code, said.getvalue()

    def test_a_refused_resume_says_the_refusal_and_does_not_fall_back(self) -> None:
        code, said = self.launch(GatewayCallError("session.resume", 4004, "not_found"))
        self.assertEqual(code, 1)
        self.assertEqual(said, f"omh: Hermes refused to resume session {STORED} (4004: not_found). "
                               "Nothing was opened in its place.\n")

    def test_a_refusal_omh_has_words_for_says_them(self) -> None:
        code, said = self.launch(GatewayCallError("session.resume", 4003, "permission_denied"))
        self.assertEqual(code, 1)
        self.assertIn("(4003: permission_denied). Hermes does not let this connection open that session: open it "
                      "where it was started (Hermes Desktop or the WebUI). Nothing was opened in its place.", said)
        self.assertNotIn("hermes --tui", said)  # Hermes' TUI answers this refusal by opening a new session

    def test_drift_on_the_resume_still_falls_back(self) -> None:
        code, said = self.launch(GatewayCallError("session.resume", -32601, "method not found"))
        self.assertEqual(code, FALLBACK_EXIT)
        self.assertIn("could not open a Hermes session", said)

    def test_a_refused_create_still_falls_back(self) -> None:
        code, _said = self.launch(GatewayCallError("session.create", 4001, "refused"), resume="")
        self.assertEqual(code, FALLBACK_EXIT)


class SessionCallDeadlineTests(unittest.TestCase):
    """Finding 3: the launch's and the respawn's session calls wait as long as Hermes' own TUI does."""

    def test_the_launch_creates_or_resumes_with_the_in_session_deadline(self) -> None:
        for environ in ({}, {"HERMES_TUI_RESUME": STORED}):
            with self.subTest(environ=environ):
                app, _recording = make_app(environ=environ)
                client = TimedClient(resume={"session_id": SID, "stored_session_id": STORED, "info": {}})
                app.client = client  # type: ignore[assignment]
                app.startup()
                self.assertEqual(client.timeouts, [CALL_ANSWER_SECONDS])

    def test_the_respawn_resumes_with_the_in_session_deadline(self) -> None:
        new = TimedClient()
        app, old, _spawner, _now = crashing(spawner=Spawner(new))
        crash(app, old)
        self.assertEqual(new.timeouts, [CALL_ANSWER_SECONDS])


class ReplayGapTests(unittest.TestCase):
    """Finding 4: the gateway dropped this screen's subscription; the live session is resumed, as Ink does."""

    def gap(self) -> tuple[object, object]:
        app, client = make_app()
        app.stored_id = STORED
        streaming(app)
        app._on_event(Event("session.replay_gap", SID, {"replay_epoch": "e", "latest_seq": 9}))
        return app, client

    def answer(self, app: object, client: object, result: dict | None = None, error: dict | None = None) -> None:
        (resume,) = [index for index, (method, _params) in enumerate(client.calls, 1) if method == "session.resume"]  # type: ignore[attr-defined]
        app._on_response(Response(resume, result, error))  # type: ignore[attr-defined]

    def test_the_gap_resumes_the_live_session(self) -> None:
        _app, client = self.gap()
        self.assertEqual(client.named("session.resume"), [{"session_id": STORED, "cols": 80}])

    def test_a_turn_the_resume_says_still_runs_goes_on(self) -> None:
        app, client = self.gap()
        self.answer(app, client, {"session_id": SID, "running": True})
        self.assertTrue(app._busy())
        self.assertNotIn(TURN_ENDED_UNSEEN_NOTICE, notices(app))

    def test_a_turn_that_ended_in_the_gap_closes_and_the_queue_goes_on(self) -> None:
        app, client = self.gap()
        app.queued.append(QueuedLine("next one"))
        self.answer(app, client, {"session_id": SID, "running": False})
        self.assertIn(TURN_ENDED_UNSEEN_NOTICE, notices(app))
        self.assertEqual(client.named("prompt.submit")[0]["text"], "next one")

    def test_a_refused_resume_says_so(self) -> None:
        app, client = self.gap()
        self.answer(app, client, error={"code": 4004, "message": "not_found"})
        self.assertIn(REPLAY_GAP_REFUSED_NOTICE.format(reason="not_found"), notices(app))

    def test_the_turns_own_end_before_the_answer_is_not_reopened_by_it(self) -> None:
        # Hermes subscribes the new view before it answers: the completion can come first, and the answer's
        # `running` was read before it.
        app, client = self.gap()
        app._on_event(Event("message.complete", SID, {"text": "the whole reply", "status": "complete"}))
        self.assertFalse(app._busy())
        self.answer(app, client, {"session_id": SID, "running": True})
        self.assertFalse(app._busy())
        self.assertFalse(app.turn_pending)
        self.assertNotIn(TURN_ENDED_UNSEEN_NOTICE, notices(app))

    def test_a_turn_that_starts_before_the_answer_is_not_closed_by_it(self) -> None:
        app, client = make_app()
        app.stored_id = STORED
        app._on_event(Event("session.replay_gap", SID, {}))
        app._on_event(Event("message.start", SID, {}))
        self.answer(app, client, {"session_id": SID, "running": False})
        self.assertTrue(app._busy())
        self.assertNotIn(TURN_ENDED_UNSEEN_NOTICE, notices(app))

    def test_a_turn_that_started_in_the_gap_shows_as_running(self) -> None:
        app, client = make_app()
        app.stored_id = STORED
        app._on_event(Event("session.replay_gap", SID, {}))
        self.answer(app, client, {"session_id": SID, "running": True})
        self.assertTrue(app._busy())

    def test_a_submitted_turn_that_ended_in_the_gap_says_so(self) -> None:
        app, client = make_app(busy=True)  # the prompt went out; no `message.start` reached this screen
        app.stored_id = STORED
        app._on_event(Event("session.replay_gap", SID, {}))
        self.answer(app, client, {"session_id": SID, "running": False})
        self.assertIn(TURN_ENDED_UNSEEN_NOTICE, notices(app))
        self.assertFalse(app._busy())

    def test_a_refused_resume_closes_the_turn_and_holds_the_queue(self) -> None:
        app, client = self.gap()
        app.queued.append(QueuedLine("next one"))
        self.answer(app, client, error={"code": 4004, "message": "not_found"})
        said = notices(app)
        self.assertEqual(said.count(REPLAY_GAP_REFUSED_NOTICE.format(reason="not_found")), 1)
        self.assertFalse([line for line in said if line.startswith("Hermes did not")], said)  # said once, its own way
        self.assertIn(TURN_LEFT_RUNNING_NOTICE, said)
        self.assertFalse(app._busy())
        self.assertFalse(app.transcript.running)
        self.assertEqual(app.composer.text, "next one")
        self.assertIn(f"{REPLAY_GAP_WHY}: what you queued is back in the composer, not sent.", said)
        self.assertEqual(client.named("prompt.submit"), [])

    def test_a_refused_resume_ends_a_submitted_turn_no_event_showed(self) -> None:
        app, client = make_app(busy=True)  # the prompt went out; no `message.start` reached this screen
        app.stored_id = STORED
        app._on_event(Event("session.replay_gap", SID, {}))
        self.answer(app, client, error={"code": 4004, "message": "not_found"})
        self.assertIn(TURN_LEFT_RUNNING_NOTICE, notices(app))
        self.assertFalse(app._busy())

    def test_an_unanswered_resume_closes_the_turn_too(self) -> None:
        now = [100.0]
        app, _client = make_app(clock=lambda: now[0])
        app.stored_id = STORED
        streaming(app)
        app._on_event(Event("session.replay_gap", SID, {}))
        now[0] += CALL_ANSWER_SECONDS + 1
        app._expire_calls()
        said = notices(app)
        self.assertIn(REPLAY_GAP_REFUSED_NOTICE.format(reason=f"no answer in {CALL_ANSWER_SECONDS:g} s"), said)
        self.assertIn(TURN_LEFT_RUNNING_NOTICE, said)
        self.assertFalse(app._busy())

    def test_an_answer_after_a_switch_leaves_the_view_it_opened(self) -> None:
        app, client = self.gap()
        app.sid = "live-9"  # a switch the person made was answered first
        self.answer(app, client, {"session_id": SID, "subscription_id": "sub-x", "running": False})
        self.assertEqual(client.named("session.close"), [{"session_id": SID}])
        self.assertEqual(app.sid, "live-9")
        self.assertNotIn(TURN_ENDED_UNSEEN_NOTICE, notices(app))

    def test_an_answer_naming_the_sessions_newer_id_moves_the_screen_to_it(self) -> None:
        app, client = self.gap()
        app.queued.append(QueuedLine("next one"))
        self.answer(app, client, {"session_id": "live-tip", "running": False})
        self.assertEqual(app.sid, "live-tip")
        self.assertIn(TURN_MOVED_NOTICE.format(session="live-tip"), notices(app))
        self.assertEqual(client.named("prompt.submit")[0]["session_id"], "live-tip")

    def test_a_moved_id_never_leaves_the_turn_open_on_a_stale_running(self) -> None:
        # The turn ended under the new id before the answer: that end was dropped, so `running` cannot be trusted.
        app, client = self.gap()
        app._on_event(Event("message.complete", "live-tip", {"text": "done", "status": "complete"}))
        self.answer(app, client, {"session_id": "live-tip", "running": True})
        self.assertFalse(app._busy())
        self.assertIn(TURN_MOVED_NOTICE.format(session="live-tip"), notices(app))

    def test_a_moved_id_ends_a_submitted_turn_no_event_showed(self) -> None:
        app, client = make_app(busy=True)  # the prompt went out; no `message.start` reached this screen
        app.stored_id = STORED
        app._on_event(Event("session.replay_gap", SID, {}))
        self.answer(app, client, {"session_id": "live-tip", "running": True})
        self.assertFalse(app._busy())
        self.assertIn(TURN_MOVED_NOTICE.format(session="live-tip"), notices(app))

    def test_a_moved_id_with_a_turn_running_does_not_send_the_queue_yet(self) -> None:
        app, client = self.gap()
        app.queued.append(QueuedLine("next one"))
        self.answer(app, client, {"session_id": "live-tip", "running": True})
        self.assertEqual(client.named("prompt.submit"), [])
        self.assertEqual([line.text for line in app.queued], ["next one"])

    def test_a_moved_id_with_no_turn_shown_only_moves(self) -> None:
        app, client = make_app()
        app.stored_id = STORED
        app._on_event(Event("session.replay_gap", SID, {}))
        self.answer(app, client, {"session_id": "live-tip", "running": False})
        self.assertEqual(app.sid, "live-tip")
        self.assertNotIn(TURN_MOVED_NOTICE.format(session="live-tip"), notices(app))
        self.assertFalse(app._busy())

    def test_a_tool_whose_end_the_gap_may_have_lost_no_longer_holds_back_the_silence(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        app.stored_id = STORED
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("tool.start", SID, {"tool_id": "t1", "name": "terminal"}))
        app._on_event(Event("session.replay_gap", SID, {}))
        self.answer(app, client, {"session_id": SID, "running": True})
        self.assertTrue(app._busy())
        self.assertFalse(app.transcript.tool_running())
        app.inbound_at = now[0]
        now[0] += GATEWAY_SILENCE_SECONDS + 15
        self.assertIn("no word from", "\n".join(line_text(line) for line in app._tail(120)))
        # A `tool.complete` that does come still settles its row.
        app._on_event(Event("tool.complete", SID, {"tool_id": "t1", "name": "terminal", "result": "ok"}))
        rows = [row for block in app.transcript.blocks for row in getattr(block, "tools", [])]
        self.assertEqual([(row.tool_id, row.status) for row in rows], [("t1", "ok")])  # the same row, not a second

    def test_a_started_admission_in_the_answer_keeps_the_turn(self) -> None:
        app, client = self.gap()
        self.answer(app, client, {"session_id": SID, "running": False,
                                  "pending": [{"admission_id": "a1", "status": "started"}]})
        self.assertTrue(app._busy())
        self.assertNotIn(TURN_ENDED_UNSEEN_NOTICE, notices(app))

    def test_a_stale_answer_naming_the_session_now_shown_closes_nothing(self) -> None:
        app, client = self.gap()
        app.sid = "live-9"  # the person moved to live-9 first; Hermes answered the gap's resume with it
        self.answer(app, client, {"session_id": "live-9", "running": False})
        self.assertEqual(client.named("session.close"), [])

    def test_a_gap_for_another_session_is_dropped(self) -> None:
        app, client = make_app()
        app._on_event(Event("session.replay_gap", "other", {}))
        self.assertEqual(client.named("session.resume"), [])


class SkillsChangedTests(unittest.TestCase):
    """Finding 5: a skill installed elsewhere reaches completion and /help: the catalog is asked for again."""

    def test_skills_changed_asks_for_the_catalog_again(self) -> None:
        app, client = make_app()
        app._on_event(Event("skills.changed", "", {}))  # gateway-wide: Hermes sends it with no session
        self.assertEqual(len(client.named("commands.catalog")), 1)

    def test_a_burst_asks_once_while_the_catalog_is_unanswered(self) -> None:
        app, client = make_app()
        for _ in range(3):
            app._on_event(Event("skills.changed", "", {}))
        self.assertEqual(len(client.named("commands.catalog")), 1)

    def test_with_no_session_yet_nothing_is_asked(self) -> None:
        app, client = make_app()
        app.sid = ""
        app._on_event(Event("skills.changed", "", {}))
        self.assertEqual(client.named("commands.catalog"), [])


class HermesInterruptTests(unittest.TestCase):
    """Finding 7: a turn Hermes interrupted itself does not read as the person's own Esc."""

    def ended_interrupted(self, interrupting: bool) -> list[str]:
        app, _client = make_app()
        streaming(app, ours=True)
        app.interrupting = interrupting
        app._on_event(Event("message.complete", SID, {"text": "", "status": "interrupted"}))
        return notices(app)

    def test_an_interrupt_omh_did_not_send_says_hermes_stopped_it(self) -> None:
        said = self.ended_interrupted(interrupting=False)
        self.assertIn(RESUMING, said)  # and goes on by itself (AutoContinueTests)
        self.assertNotIn(INTERRUPTED_NOTICE, said)
        self.assertEqual(RESUMING, "Hermes interrupted this turn; sending `continue` in 3 s · Esc cancels")
        self.assertEqual(HERMES_INTERRUPTED_NOTICE, "Hermes interrupted this turn; send `continue` to go on.")

    def test_the_persons_own_interrupt_still_says_interrupted(self) -> None:
        said = self.ended_interrupted(interrupting=True)
        self.assertIn(INTERRUPTED_NOTICE, said)
        self.assertNotIn(HERMES_INTERRUPTED_NOTICE, said)

    def ended_after(self, ask: object) -> tuple[list[str], object]:
        app, client = make_app()
        streaming(app)
        ask(app)  # type: ignore[operator]
        app._on_event(Event("message.complete", SID, {"text": "", "status": "interrupted"}))
        return notices(app), client

    def test_a_prompt_sent_in_busy_mode_interrupt_is_the_persons_stop(self) -> None:
        def replace(app: object) -> None:
            app.busy_mode = "interrupt"  # type: ignore[attr-defined]
            app._send_prompt("replace it")  # type: ignore[attr-defined]

        said, client = self.ended_after(replace)
        self.assertEqual([params["text"] for params in client.named("prompt.submit")], ["replace it"])  # type: ignore[attr-defined]
        self.assertIn(INTERRUPTED_NOTICE, said)
        self.assertNotIn(HERMES_INTERRUPTED_NOTICE, said)

    def test_stop_is_the_persons_stop(self) -> None:
        def stop(app: object) -> None:
            type_text(app, "/stop")  # type: ignore[arg-type]
            app._on_input(Key(ENTER))  # type: ignore[attr-defined]

        said, client = self.ended_after(stop)
        self.assertEqual(len(client.named("slash.exec")), 1)  # type: ignore[attr-defined]
        self.assertIn(INTERRUPTED_NOTICE, said)
        self.assertNotIn(HERMES_INTERRUPTED_NOTICE, said)

    def test_a_prompt_in_busy_mode_steer_or_queue_asks_no_stop(self) -> None:
        for mode in ("steer", "queue"):
            with self.subTest(mode=mode):
                app, _client = make_app()
                streaming(app)
                app.busy_mode = mode
                app._send_prompt("more")
                self.assertFalse(app.stop_asked)

    def test_stop_with_no_turn_asks_no_stop(self) -> None:
        app, client = make_app()
        type_text(app, "/stop")
        app._on_input(Key(ENTER))
        self.assertEqual(len(client.named("slash.exec")), 1)
        self.assertFalse(app.stop_asked)

    def test_a_turn_that_ends_any_other_way_spends_the_stop(self) -> None:
        app, _client = make_app()
        streaming(app)
        app.stop_asked = True
        app._on_event(Event("error", SID, {"message": "cancelled"}))  # a bare error ends the turn
        self.assertFalse(app._busy())
        self.assertFalse(app.stop_asked)

    def test_a_session_adopted_starts_with_no_stop_asked(self) -> None:
        app, _client = make_app()
        app.stop_asked = True
        app._adopt_session({"session_id": "live-2", "info": {}})
        self.assertFalse(app.stop_asked)

    def test_the_stop_asked_is_for_one_turn_only(self) -> None:
        app, _client = make_app()
        streaming(app, ours=True)
        app.stop_asked = True
        app._on_event(Event("message.complete", SID, {"text": "", "status": "interrupted"}))
        streaming(app, ours=True)
        app._on_event(Event("message.complete", SID, {"text": "", "status": "interrupted"}))
        self.assertEqual(notices(app), [INTERRUPTED_NOTICE, RESUMING])


def interrupted_by_hermes(**options: object) -> tuple[object, object, list[float]]:
    """A turn under way that Hermes then interrupts itself, on the test's clock."""
    now = [100.0]
    app, client = make_app(clock=lambda: now[0], **options)
    app.stored_id = STORED
    streaming(app, ours=True)
    app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
    return app, client, now


def sent(client: object) -> list[str]:
    return [params["text"] for params in client.named("prompt.submit")]  # type: ignore[attr-defined]


def wait_out(app: object, now: list[float], seconds: float = AUTO_CONTINUE_SECONDS) -> None:
    now[0] += seconds
    app._auto_continue_when_due()  # type: ignore[attr-defined]


class AutoContinueTests(unittest.TestCase):
    """A turn Hermes interrupted itself (a sleep past its turn lease) goes on with the `continue` the notice names."""

    def test_the_turn_goes_on_with_continue_once_the_wait_is_over(self) -> None:
        app, client, now = interrupted_by_hermes()
        self.assertIn(RESUMING, notices(app))
        self.assertNotIn(HERMES_INTERRUPTED_NOTICE, notices(app))
        wait_out(app, now, AUTO_CONTINUE_SECONDS - 0.5)
        self.assertEqual(sent(client), [])  # not before the wait is over
        wait_out(app, now, 0.5)
        self.assertEqual(sent(client), ["continue"])
        self.assertEqual(client.named("prompt.submit")[0], {"session_id": SID, "text": "continue"})
        self.assertEqual(app.auto_continues, 1)
        self.assertIsNone(app.auto_continue)
        wait_out(app, now)
        self.assertEqual(sent(client), ["continue"])  # once

    def test_it_goes_the_way_a_typed_continue_goes(self) -> None:
        app, client, now = interrupted_by_hermes()
        app.plan_mode = True  # a typed `continue` goes as `/plan continue` in plan mode, so this one does too
        wait_out(app, now)
        self.assertEqual(sent(client), [])
        self.assertEqual(len(client.named("slash.exec")) + len(client.named("command.dispatch")), 1)

    def test_the_persons_esc_is_never_resumed(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        streaming(app, ours=True)
        app._on_input(Key(ESCAPE))  # the person's interrupt
        self.assertTrue(app.interrupting)
        app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
        self.assertEqual(notices(app), [INTERRUPTED_NOTICE])
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_the_persons_stop_is_never_resumed(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        streaming(app, ours=True)
        type_text(app, "/stop")
        app._on_input(Key(ENTER))
        app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
        self.assertEqual(notices(app), [INTERRUPTED_NOTICE])
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_a_turn_that_failed_is_never_resumed(self) -> None:
        for payload in ({"text": "", "status": "error", "error": "provider down"},
                        {"text": "", "status": "interrupted", "error": "provider down"}):
            with self.subTest(payload=payload):
                now = [100.0]
                app, client = make_app(clock=lambda: now[0])
                streaming(app, ours=True)
                app._on_event(Event("message.complete", SID, payload))
                self.assertNotIn(RESUMING, notices(app))
                self.assertIsNone(app.auto_continue)
                wait_out(app, now)
                self.assertEqual(sent(client), [])

    def test_a_turn_that_completed_is_never_resumed(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        streaming(app, ours=True)
        app._on_event(Event("message.complete", SID, {"text": "done", "status": "complete"}))
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_at_most_the_limit_between_two_prompts_of_the_persons_own(self) -> None:
        app, client, now = interrupted_by_hermes()
        for _ in range(AUTO_CONTINUE_LIMIT):
            wait_out(app, now)
            streaming(app)
            app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
        self.assertEqual(sent(client), ["continue"] * AUTO_CONTINUE_LIMIT)
        self.assertEqual(notices(app)[-1], HERMES_INTERRUPTED_NOTICE)  # past the limit the person is asked
        wait_out(app, now)
        self.assertEqual(sent(client), ["continue"] * AUTO_CONTINUE_LIMIT)
        type_text(app, "go on")  # the person's own prompt: the next interrupt goes on by itself again
        app._on_input(Key(ENTER))
        streaming(app)
        app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
        self.assertEqual(notices(app)[-1], RESUMING)

    def test_a_queued_line_of_the_persons_resets_the_limit_too(self) -> None:
        app, client, now = interrupted_by_hermes()
        app.auto_continues = AUTO_CONTINUE_LIMIT
        app.auto_continue = None
        app.queued.append(QueuedLine("next thing", "next thing", ""))
        app._drain_queue()
        self.assertEqual(app.auto_continues, 0)

    def test_a_draft_in_the_composer_asks_the_person_instead(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        streaming(app, ours=True)
        type_text(app, "half a thought")
        app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
        self.assertEqual(notices(app), [HERMES_INTERRUPTED_NOTICE])
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_a_draft_typed_during_the_wait_holds_it(self) -> None:
        app, client, now = interrupted_by_hermes()
        type_text(app, "wait")
        wait_out(app, now)
        self.assertEqual(sent(client), [])
        self.assertEqual(notices(app)[-1], AUTO_CONTINUE_HELD_NOTICE.format(why=AUTO_CONTINUE_DRAFTED))
        self.assertEqual(app.composer.text, "wait")

    def test_a_queued_line_goes_instead(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        streaming(app, ours=True)
        app.busy_mode = "queue"
        app._send_prompt("after this")
        app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
        self.assertNotIn(RESUMING, notices(app))
        wait_out(app, now)
        self.assertEqual(sent(client), ["after this"])  # the queue went at the end, as after any turn

    def test_a_question_open_at_the_wait_holds_it(self) -> None:
        app, client, now = interrupted_by_hermes()
        app.slot = object()  # a question or picker took the slot meanwhile
        wait_out(app, now)
        app.slot = None
        self.assertEqual(sent(client), [])
        self.assertEqual(notices(app)[-1], AUTO_CONTINUE_HELD_NOTICE.format(why=AUTO_CONTINUE_ASKED))

    def test_esc_during_the_wait_cancels_it(self) -> None:
        app, client, now = interrupted_by_hermes()
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.auto_continue)
        self.assertEqual(notices(app)[-1], AUTO_CONTINUE_HELD_NOTICE.format(why=AUTO_CONTINUE_ESCAPED))
        self.assertIsNone(app.escape_armed)  # the press was the cancel's: it arms no rewind
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_a_turn_started_meanwhile_drops_it_without_a_word(self) -> None:
        app, client, now = interrupted_by_hermes()
        said = notices(app)
        app._on_event(Event("message.start", SID, {}))  # another client of the session, or Hermes, started one
        calls = list(client.calls)
        wait_out(app, now)
        self.assertEqual(client.calls, calls)  # no prompt, steer or anything else goes into that turn
        self.assertEqual(list(app.queued), [])  # nor waits behind it
        self.assertEqual(notices(app), said)

    def test_the_persons_own_prompt_meanwhile_is_the_only_one_sent(self) -> None:
        app, client, now = interrupted_by_hermes()
        type_text(app, "do this instead")
        app._on_input(Key(ENTER))
        wait_out(app, now)
        self.assertEqual(sent(client), ["do this instead"])

    def test_another_session_open_drops_it(self) -> None:
        app, client, now = interrupted_by_hermes()
        app.stored_id = "other-session"
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_the_loop_sends_it_when_due_and_waits_for_it(self) -> None:
        app, client, now = interrupted_by_hermes()
        due = app.auto_continue[1]
        now[0] = due - 0.25
        self.assertLessEqual(app._read_timeout(), 0.25 + 1e-9)  # the loop wakes for it, not at its idle second
        now[0] = due - AUTO_CONTINUE_SECONDS
        app.client.poll = lambda: []  # type: ignore[attr-defined]
        reads = [(1.0, b""), (1.0, b""), (1.0, b"")]

        def read(timeout: float, wake: int | None = None) -> bytes:
            delay, data = reads.pop(0)
            now[0] += delay
            return data

        app.terminal.read = read  # type: ignore[method-assign]
        while reads:
            app._step()
        self.assertEqual(sent(client), ["continue"])

    def test_an_esc_read_in_the_step_that_makes_it_due_cancels_it(self) -> None:
        app, client, now = interrupted_by_hermes()
        app.client.poll = lambda: []  # type: ignore[attr-defined]
        reads = [(AUTO_CONTINUE_SECONDS, b"\x1b"), (1.0, b""), (1.0, b""), (1.0, b"")]

        def read(timeout: float, wake: int | None = None) -> bytes:
            delay, data = reads.pop(0)
            now[0] += delay
            return data

        app.terminal.read = read  # type: ignore[method-assign]
        while reads:
            app._step()
        self.assertEqual(sent(client), [])
        self.assertIn(AUTO_CONTINUE_HELD_NOTICE.format(why=AUTO_CONTINUE_ESCAPED), notices(app))

    def test_a_reconnect_to_the_same_session_keeps_it(self) -> None:
        # A fake shared gateway: Hermes interrupts the turn (its lease lost over a sleep), the attach connection then
        # drops, and the gateway takes the same session back on a new connection: the `continue` goes there.
        new = RespawnClient(resume={**SHARED_RESUMED, "running": False})
        spawner = Spawner(new)
        app, old, _spawner, now = crashing(spawner=spawner)
        app.sid = SID
        app.shared_gateway = True
        streaming(app, ours=True)
        app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
        self.assertIn(RESUMING, notices(app))
        crash(app, old, 1)
        self.assertIn(RECONNECTED_NOTICE.format(session=STORED), notices(app))
        wait_out(app, now)
        self.assertEqual(sent(new), ["continue"])
        self.assertEqual(new.named("prompt.submit")[0]["session_id"], "live-2")
        self.assertEqual(old.named("prompt.submit"), [])

    def test_esc_after_a_prompt_sent_during_the_wait_interrupts_its_turn(self) -> None:
        app, client, now = interrupted_by_hermes()
        type_text(app, "do this instead")
        app._on_input(Key(ENTER))
        self.assertIsNone(app.auto_continue)  # the person's prompt took its place
        self.assertIn(AUTO_CONTINUE_HELD_NOTICE.format(why=AUTO_CONTINUE_SENT), notices(app))
        app._on_event(Event("message.start", SID, {}))
        now[0] += 1.0
        app._on_input(Key(ESCAPE))
        self.assertTrue(app.interrupting)
        self.assertEqual(len(client.named("session.interrupt")), 1)
        self.assertEqual(sent(client), ["do this instead"])

    def test_esc_after_another_clients_turn_started_interrupts_it(self) -> None:
        app, client, now = interrupted_by_hermes()
        app._on_event(Event("message.start", SID, {}))  # no prompt of this TUI's: another client's turn
        self.assertIsNone(app.auto_continue)
        app._on_input(Key(ESCAPE))
        self.assertTrue(app.interrupting)
        self.assertEqual(len(client.named("session.interrupt")), 1)
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_one_esc_in_vim_insert_cancels_the_wait(self) -> None:
        app, client, now = interrupted_by_hermes()
        app.composer = Composer(vim=True)  # INSERT
        app._on_input(Key(ESCAPE))
        self.assertEqual(app.composer.vim_label, VIM_NORMAL)  # the press still leaves INSERT
        self.assertIsNone(app.auto_continue)
        self.assertEqual(notices(app)[-1], AUTO_CONTINUE_HELD_NOTICE.format(why=AUTO_CONTINUE_ESCAPED))
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_a_local_command_during_the_wait_cancels_it(self) -> None:
        for command in ("/stop", "/help"):
            with self.subTest(command=command):
                app, client, now = interrupted_by_hermes()
                type_text(app, command)
                app._on_input(Key(ENTER))
                self.assertIsNone(app.auto_continue)
                self.assertIn(AUTO_CONTINUE_HELD_NOTICE.format(why=AUTO_CONTINUE_SENT), notices(app))
                wait_out(app, now)
                self.assertEqual(sent(client), [])
                self.assertEqual(app.auto_continues, 0)

    def test_a_submit_held_for_its_paste_cancels_the_wait(self) -> None:
        app, client, now = interrupted_by_hermes()
        held = HeldSubmit("look at this", "", (), (), False, now[0])
        app.held_submits.append(held)  # one already held: the next submit waits behind it (`_hold_submit`)
        type_text(app, "and this")
        app._on_input(Key(ENTER))
        self.assertIsNone(app.auto_continue)
        self.assertIn(AUTO_CONTINUE_HELD_NOTICE.format(why=AUTO_CONTINUE_SENT), notices(app))
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_another_clients_interrupted_turn_is_not_resumed(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        streaming(app)  # a turn this TUI never submitted: another client's on the shared gateway
        app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
        self.assertIsNone(app.auto_continue)
        self.assertNotIn(RESUMING, notices(app))
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_the_turn_is_the_tuis_own_only_until_it_ends(self) -> None:
        app, client, now = interrupted_by_hermes()
        wait_out(app, now)
        self.assertEqual(sent(client), ["continue"])
        streaming(app)  # the `continue`'s own turn: its prompt was out at its start
        app._on_event(Event("message.complete", SID, {"text": "done", "status": "complete"}))
        streaming(app)  # then another client's
        app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
        self.assertIsNone(app.auto_continue)
        wait_out(app, now)
        self.assertEqual(sent(client), ["continue"])

    def test_new_during_the_wait_cancels_it(self) -> None:
        app, client, now = interrupted_by_hermes()
        type_text(app, "/new")
        app._on_input(Key(ENTER))
        self.assertIsNone(app.auto_continue)
        answer(app, client, {"session_id": "live-2", "stored_session_id": "stored-2", "info": {}})
        self.assertEqual(app.stored_id, "stored-2")
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_resume_during_the_wait_cancels_it(self) -> None:
        app, client, now = interrupted_by_hermes()
        type_text(app, "/sessions another-stored-id")
        app._on_input(Key(ENTER))
        self.assertIsNone(app.auto_continue)
        answer(app, client, {"session_id": "live-3", "stored_session_id": "another-stored-id", "info": {},
                                    "messages": []})
        self.assertEqual(app.stored_id, "another-stored-id")
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_another_session_adopted_during_the_wait_drops_it_and_says_so(self) -> None:
        app, client, now = interrupted_by_hermes()
        app._adopt_session({"session_id": "live-2", "stored_session_id": "stored-rotated", "info": {}})
        self.assertIsNone(app.auto_continue)
        self.assertEqual(notices(app)[-1], AUTO_CONTINUE_HELD_NOTICE.format(why=AUTO_CONTINUE_LEFT))
        wait_out(app, now)
        self.assertEqual(sent(client), [])

    def test_a_prompt_waiting_to_start_at_the_due_time_holds_it_and_says_so(self) -> None:
        for state in ("starting", "held_submits"):
            with self.subTest(state=state):
                app, client, now = interrupted_by_hermes()
                if state == "starting":
                    app.starting = ("mine", lambda: None, SID)
                else:
                    app.held_submits.append(HeldSubmit("mine", "", (), (), False, now[0]))
                wait_out(app, now)
                self.assertEqual(sent(client), [])
                self.assertEqual(notices(app)[-1], AUTO_CONTINUE_HELD_NOTICE.format(why=AUTO_CONTINUE_QUEUED))

    def test_a_turn_start_read_in_the_step_that_makes_it_due_drops_it(self) -> None:
        app, client, now = interrupted_by_hermes()
        events = [[Event("message.start", SID, {})]]
        app.client.poll = lambda: events.pop(0) if events else []  # type: ignore[attr-defined]

        def read(timeout: float, wake: int | None = None) -> bytes:
            now[0] += AUTO_CONTINUE_SECONDS
            return b""

        app.terminal.read = read  # type: ignore[method-assign]
        app._step()
        self.assertEqual(sent(client), [])
        self.assertIsNone(app.auto_continue)

    def test_a_held_esc_past_the_due_time_does_not_spin_the_loop(self) -> None:
        app, _client, now = interrupted_by_hermes()
        app._take_input(b"\x1b")  # a lone Esc, held until input is quiet
        self.assertTrue(app.decoder.holding)
        now[0] = app.auto_continue[1] + 0.001
        self.assertGreater(app._read_timeout(), 0.0)

    def test_its_own_continue_never_comes_back_into_the_draft(self) -> None:
        app, client, now = interrupted_by_hermes()
        app.default_route = ("some/model", "provider")  # the prompt waits in `starting` for the default check
        wait_out(app, now)
        self.assertEqual(app.starting[0], "continue")
        app._adopt_session({"session_id": "live-2", "stored_session_id": STORED, "info": {}})  # it never went
        self.assertIsNone(app.starting)
        self.assertEqual(app.composer.text, "")
        self.assertEqual(notices(app)[-1], AUTO_CONTINUE_HELD_NOTICE.format(why=AUTO_CONTINUE_UNSENT))

    def test_the_persons_own_continue_still_comes_back_into_the_draft(self) -> None:
        app, client, now = interrupted_by_hermes()
        wait_out(app, now)
        answer(app, client, error={"code": 5000, "message": "busy"})  # Hermes refused the TUI's `continue`
        self.assertFalse(app._busy())
        app.default_route = ("some/model", "provider")
        type_text(app, "continue")  # the person's own, which waits in `starting`
        app._on_input(Key(ENTER))
        self.assertEqual(app.starting[0], "continue")
        app._adopt_session({"session_id": "live-2", "stored_session_id": STORED, "info": {}})
        self.assertEqual(app.composer.text, "continue")

    def test_a_reconnect_mid_turn_keeps_the_turn_the_tuis_own(self) -> None:
        # The machine sleeps with the turn running: the attach connection drops, the gateway takes the session back
        # still running, and then Hermes interrupts the turn (its lease lost): the `continue` goes on the new one.
        new = RespawnClient(resume={**SHARED_RESUMED, "session_id": SID, "running": True})
        app, old, _spawner, now = crashing(spawner=Spawner(new))
        app.sid = SID
        app.shared_gateway = True
        streaming(app, ours=True)
        crash(app, old, 1)
        self.assertTrue(app._busy())
        app._on_event(Event("message.complete", SID, dict(HERMES_STOPPED)))
        self.assertIn(RESUMING, notices(app))
        wait_out(app, now)
        self.assertEqual(sent(new), ["continue"])


class GatewaySilenceTests(unittest.TestCase):
    """Finding 1's other half: with no keepalive, a gateway that says nothing during a turn is named, never closed."""

    def test_the_working_row_says_how_long_the_gateway_has_been_silent(self) -> None:
        rows = "\n".join(self.rows(GATEWAY_SILENCE_SECONDS + 5))
        self.assertIn("no word from Hermes' gateway for 50 s", rows)

    def test_a_shorter_silence_says_nothing(self) -> None:
        rows = "\n".join(self.rows(GATEWAY_SILENCE_SECONDS - 5))
        self.assertNotIn("no word from Hermes' gateway", rows)

    def test_a_running_tool_is_never_silence(self) -> None:
        # Hermes sends nothing between a terminal tool's start and its end: a long build is not a quiet gateway.
        now = [100.0]
        app, _client = make_app(clock=lambda: now[0])
        streaming(app)
        app._on_event(Event("tool.start", SID, {"tool_id": "t1", "name": "terminal", "args": {"command": "make"}}))
        app.inbound_at = now[0]
        now[0] += GATEWAY_SILENCE_SECONDS + 15
        self.assertNotIn("no word from", "\n".join(line_text(line) for line in app._tail(120)))
        app._on_event(Event("tool.complete", SID, {"tool_id": "t1", "name": "terminal"}))
        now[0] += GATEWAY_SILENCE_SECONDS + 15
        self.assertIn("no word from", "\n".join(line_text(line) for line in app._tail(120)))

    def test_a_tool_running_after_a_finished_one_still_holds_back_the_silence(self) -> None:
        now = [100.0]
        app, _client = make_app(clock=lambda: now[0])
        streaming(app)
        app._on_event(Event("tool.start", SID, {"tool_id": "t1", "name": "terminal"}))
        app._on_event(Event("tool.complete", SID, {"tool_id": "t1", "name": "terminal", "result": "ok"}))
        app._on_event(Event("tool.start", SID, {"tool_id": "t2", "name": "terminal"}))
        app.inbound_at = now[0]
        now[0] += GATEWAY_SILENCE_SECONDS + 15
        self.assertTrue(app.transcript.tool_running())
        self.assertNotIn("no word from", "\n".join(line_text(line) for line in app._tail(120)))

    def test_a_tool_kept_across_a_reconnect_does_not_hold_back_the_silence(self) -> None:
        # The reconnect's notices close the group's place at the end of the transcript, so the row no longer counts.
        new = RespawnClient(resume={**SHARED_RESUMED, "session_id": SID, "running": True})
        app, old, _spawner, _now = crashing(spawner=Spawner(new))
        app.sid, app.shared_gateway = SID, True
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("tool.start", SID, {"tool_id": "t1", "name": "terminal"}))
        crash(app, old, 1)
        self.assertTrue(app._busy())
        self.assertFalse(app.transcript.tool_running())

    def test_anything_from_the_gateway_restarts_the_count(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        streaming(app)
        now[0] += GATEWAY_SILENCE_SECONDS + 5
        client.inbox.append(Event("message.delta", SID, {"text": " more"}))
        app._drain_gateway()
        self.assertNotIn("no word from", "\n".join(line_text(line) for line in app._tail(120)))
        self.assertIsNone(app.exit_code)

    def rows(self, quiet: float) -> list[str]:
        now = [100.0]
        app, _client = make_app(clock=lambda: now[0])
        streaming(app)
        app.inbound_at = now[0]
        now[0] += quiet
        rows = [line_text(line) for line in app._tail(120)]
        self.assertIsNone(app.exit_code)  # said, never acted on
        return rows


if __name__ == "__main__":
    unittest.main()
