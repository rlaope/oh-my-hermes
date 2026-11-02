"""The OMH TUI on a shared Hermes gateway that is slow or busy, as Hermes' own Ink TUI rides it out.

A dropped attach connection is not a dead gateway: the respawn resumes the
session and keeps a turn the resume says still runs. A launch's `--resume`
that Hermes refuses as itself is said and exits 1, rather than falling back to
Hermes' TUI, which opens a new session in its place. The session calls of a
launch and a respawn wait `CALL_ANSWER_SECONDS`, as in-session calls do.
`session.replay_gap` resumes the live session; `skills.changed` asks for the
command catalog again; a turn Hermes interrupted itself says so. Every case
drives an `App` over recording clients; the clock is the test's.
"""

from __future__ import annotations

import io
import unittest

from _tui_lines import line_text
from test_tui_app import FakePoller, ScriptedTerminal
from test_tui_modes import SID, make_app, notices, type_text
from test_tui_respawn import ENVIRON, STORED, RespawnClient, Spawner, crash, crashing
from omh.tui.app import (
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
    QueuedLine,
    _run,
    _Told,
)
from omh.tui.gateway import Event, GatewayCallError, Response
from omh.tui.keys import ENTER, Key
from omh.tui.launch import FALLBACK_EXIT
from omh.tui.transcript import HERMES_INTERRUPTED_NOTICE, INTERRUPTED_NOTICE

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


def streaming(app: object) -> None:
    """The live session's turn is under way, its reply half streamed."""
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

    def test_a_turn_hermes_still_holds_as_queued_or_started_is_live(self) -> None:
        for status, live in (("queued", True), ("started", True), ("unknown", False)):
            with self.subTest(status=status):
                resumed = {**SHARED_RESUMED, "session_id": SID, "running": False,
                           "pending": [{"admission_id": "a1", "status": status}]}
                app, _spawner = self.dropped(resumed)
                self.assertEqual(app._busy(), live)  # type: ignore[attr-defined]
                self.assertEqual(TURN_ENDED_UNSEEN_NOTICE in notices(app), not live)

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
                    Spawner())
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
        self.answer(app, client, {"session_id": "live-tip", "running": True})
        self.assertEqual(app.sid, "live-tip")
        app._on_event(Event("message.complete", "live-tip", {"text": "done", "status": "complete"}))
        self.assertFalse(app._busy())

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
        streaming(app)
        app.interrupting = interrupting
        app._on_event(Event("message.complete", SID, {"text": "", "status": "interrupted"}))
        return notices(app)

    def test_an_interrupt_omh_did_not_send_says_hermes_stopped_it(self) -> None:
        said = self.ended_interrupted(interrupting=False)
        self.assertIn(HERMES_INTERRUPTED_NOTICE, said)
        self.assertNotIn(INTERRUPTED_NOTICE, said)
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

    def test_the_stop_asked_is_for_one_turn_only(self) -> None:
        app, _client = make_app()
        streaming(app)
        app.stop_asked = True
        app._on_event(Event("message.complete", SID, {"text": "", "status": "interrupted"}))
        streaming(app)
        app._on_event(Event("message.complete", SID, {"text": "", "status": "interrupted"}))
        self.assertEqual(notices(app), [INTERRUPTED_NOTICE, HERMES_INTERRUPTED_NOTICE])


class GatewaySilenceTests(unittest.TestCase):
    """Finding 1's other half: with no keepalive, a gateway that says nothing during a turn is named, never closed."""

    def test_the_working_row_says_how_long_the_gateway_has_been_silent(self) -> None:
        rows = "\n".join(self.rows(GATEWAY_SILENCE_SECONDS + 5))
        self.assertIn("no word from Hermes' gateway for 50 s", rows)

    def test_a_shorter_silence_says_nothing(self) -> None:
        rows = "\n".join(self.rows(GATEWAY_SILENCE_SECONDS - 5))
        self.assertNotIn("no word from Hermes' gateway", rows)

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
