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

from test_tui_app import FakePoller, ScriptedTerminal
from test_tui_modes import SID, make_app, notices
from test_tui_respawn import ENVIRON, STORED, RespawnClient, Spawner, crash, crashing
from omh.tui.app import (
    CALL_ANSWER_SECONDS,
    RECONNECTED_NOTICE,
    RECONNECTED_WHY,
    REPLAY_GAP_REFUSED_NOTICE,
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
        self.assertIn("(4003: permission_denied). Hermes does not let this connection change that session: open it in "
                      "Hermes' own TUI (`hermes --tui`) instead. Nothing was opened in its place.", said)

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


if __name__ == "__main__":
    unittest.main()
