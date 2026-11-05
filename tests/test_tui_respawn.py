"""Gateway crash recovery (approved boundary change, owner decision 10): respawn, resume, at most 3 in 60 s.

When the `tui_gateway` child exits on its own with a failure, the TUI spawns
it again from the environment the launcher handed it and resumes the session
that was open, as Hermes' own TUI does (ui-tui `app/gatewayRecovery.ts`). The
question the old gateway asked closes unanswered, a running turn is reported
lost and never sent again, and the queue is held as after an interrupt. A
normal exit, the person's quit, or a gateway another runtime owns is never
respawned; past the cap the TUI leaves as it did before, naming
`hermes --tui`. Every case drives an `App` over recording clients; the
clock is the test's.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from _tui_lines import line_text
from test_tui_app import FakePoller, ScriptedTerminal, Step
from test_tui_choice_ui import drawn
from test_tui_modes import SID, RecordingClient, make_app, notices, type_text
from omh.tui import gateway_contract as contract
from omh.tui.app import (
    CALL_ANSWER_SECONDS,
    RESPAWN_LIMIT,
    RESPAWN_NOTICE,
    RESPAWN_READY_SECONDS,
    RESPAWN_WINDOW_SECONDS,
    RESPAWNED_NOTICE,
    RESPAWNED_WHY,
    STEER_LOST_NOTICE,
    STEER_LOST_OUTCOME,
    TURN_LOST_NOTICE,
    App,
    QueuedLine,
    _run,
)
from omh.tui.gateway import (
    Event,
    GatewayCallError,
    GatewayClient,
    GatewayExited,
    GatewayUnavailable,
    ServerRequest,
    gateway_spawn,
)
from omh.tui.keys import CHAR, ENTER, Key
from omh.tui.transcript import CommandBlock

STORED = "20261016_101010_abcdef"
ENVIRON = {
    "HERMES_PYTHON": "/opt/hermes/venv/bin/python",
    "HERMES_PYTHON_SRC_ROOT": "/opt/hermes",
    "OMH_TUI_GATEWAY_PYTHONPATH": "/opt/hermes/site",
    "HERMES_CWD": "/work/project",
}
RESUMED = {"session_id": "live-2", "stored_session_id": STORED, "info": {"model": "m"}, "messages": []}


class RespawnClient(RecordingClient):
    """A recording client that also starts, answers the blocking `session.resume`, and is closed."""

    def __init__(self, spawn: object = None, first_id: int = 1, *, start_error: Exception | None = None,
                 resume: dict | Exception = RESUMED) -> None:
        super().__init__()
        self.spawn, self.first_id = spawn, first_id
        self.start_error, self.resume = start_error, resume
        self.blocking: list[tuple[str, dict]] = []
        self.closed = 0
        self.ready_timeout: float | None = None

    def start(self, ready_timeout: float = 60.0, cancel: object = None) -> Event:
        self.ready_timeout = ready_timeout
        if self.start_error is not None:
            raise self.start_error
        return Event("gateway.ready", None, {})

    def call(self, method: str, params: dict, timeout: float = 30.0, cancel: object = None) -> dict:
        self.blocking.append((method, params))
        if isinstance(self.resume, Exception):
            raise self.resume
        return self.resume

    def request(self, method: str, params: dict) -> int:
        problem = contract.call_problem(method, params)
        if problem:
            raise ValueError(problem)
        self.calls.append((method, params))
        return self.first_id + len(self.calls) - 1

    def close(self, grace: float = 3.0, terminate_grace: float | None = None) -> int | None:
        self.closed += 1
        return 1

    def stderr_tail(self) -> list[str]:
        return []


class Spawner:
    """`make_client` for the app: hands out the next scripted client and keeps every one it made."""

    def __init__(self, *clients: RespawnClient) -> None:
        self.queued = list(clients)
        self.made: list[RespawnClient] = []

    def __call__(self, spawn: object, first_id: int = 1) -> RespawnClient:
        client = self.queued.pop(0) if self.queued else RespawnClient()
        client.spawn, client.first_id = spawn, first_id
        self.made.append(client)
        return client


def crashing(**options: object) -> tuple[App, RespawnClient, Spawner, list[float]]:
    now = [100.0]
    spawner = options.pop("spawner", None) or Spawner()
    app, _recording = make_app(environ=dict(options.pop("environ", ENVIRON)), clock=lambda: now[0], make_client=spawner,
                               **options)
    old = RespawnClient()
    app.client = old  # type: ignore[assignment]
    app.stored_id = STORED
    return app, old, spawner, now


def crash(app: App, client: RespawnClient, code: int | None = 1) -> None:
    client.inbox.append(GatewayExited(code))
    app._drain_gateway()
    if app.respawn_reason:
        app._respawn_gateway()


class RespawnTests(unittest.TestCase):
    def test_a_crash_spawns_the_gateway_again_as_the_launcher_said_and_resumes_the_session(self) -> None:
        app, old, spawner, _now = crashing()
        crash(app, old)
        self.assertIsNone(app.exit_code)
        (new,) = spawner.made
        self.assertIs(app.client, new)
        self.assertEqual(new.spawn, gateway_spawn(ENVIRON))  # same interpreter, import path and environment
        self.assertEqual(new.blocking, [("session.resume", {"session_id": STORED, "cols": 80})])
        self.assertEqual((app.sid, app.stored_id), ("live-2", STORED))
        self.assertEqual(old.closed, 1)
        said = notices(app)
        self.assertIn(RESPAWN_NOTICE.format(reason="The Hermes gateway exited (code 1)", session=STORED, attempt=1,
                                            limit=RESPAWN_LIMIT, window=RESPAWN_WINDOW_SECONDS), said)
        self.assertIn(f"The Hermes gateway exited (code 1): starting it again and resuming session {STORED} (1 of 3 in 60 s); "
                      "what you type waits until it is back, and ctrl+c leaves.", said)
        self.assertEqual(said[-1], RESPAWNED_NOTICE.format(session=STORED))
        # It reads the session's settings and command list again, as a session that opens does.
        self.assertEqual([method for method, _params in new.calls], ["config.get", "commands.catalog"])

    def test_the_open_question_and_the_waiting_ones_close_unanswered(self) -> None:
        app, old, _spawner, now = crashing()
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        app._on_server_request(ServerRequest("srq-2", "clarify", {"questions": [{"qid": "q", "question": "?"}]}))
        crash(app, old)
        self.assertIsNone(app.slot)
        self.assertEqual(list(app.waiting_requests), [])
        self.assertEqual(old.answers, [])
        self.assertEqual(app.client.answers, [])  # type: ignore[attr-defined]
        self.assertIn("Hermes' approval request closed unanswered: the gateway that asked has exited.", notices(app))

    def test_a_running_turn_is_reported_lost_and_never_sent_again(self) -> None:
        app, old, spawner, _now = crashing(busy=True)
        crash(app, old)
        self.assertIn(TURN_LOST_NOTICE, notices(app))
        self.assertFalse(app._busy())
        self.assertEqual(spawner.made[0].named("prompt.submit"), [])

    def test_the_queue_is_held_as_after_an_interrupt(self) -> None:
        app, old, spawner, _now = crashing(busy=True)
        app.queued.extend([QueuedLine("next one"), QueuedLine("and this")])
        crash(app, old)
        self.assertEqual(app.composer.text, "next one\nand this")
        self.assertIn(f"{RESPAWNED_WHY}: what you queued is back in the composer, not sent.", notices(app))
        self.assertEqual(spawner.made[0].named("prompt.submit"), [])

    def test_calls_still_waiting_are_forgotten_and_the_new_client_starts_past_their_ids(self) -> None:
        app, old, spawner, _now = crashing()
        type_text(app, "/usage")
        app._on_input(Key(ENTER))
        waiting = max(app.pending)
        crash(app, old)
        self.assertEqual(spawner.made[0].first_id, waiting + 1)
        self.assertNotIn(waiting, app.pending)  # the gateway that would answer it is gone

    def test_a_write_the_dead_gateway_refuses_respawns_too(self) -> None:
        app, old, spawner, _now = crashing()

        def refuse(method: str, params: dict) -> int:
            raise GatewayUnavailable("the gateway stopped reading its input")

        old.request = refuse  # type: ignore[method-assign]
        type_text(app, "hello")
        app._on_input(Key(ENTER))
        self.assertTrue(app.respawn_reason)
        app._respawn_gateway()
        self.assertIs(app.client, spawner.made[0])
        self.assertIn(TURN_LOST_NOTICE, notices(app))  # the prompt never went out: it is lost, not sent again
        self.assertEqual(old.closed, 1)

    def test_the_old_gateway_is_reaped_before_the_new_one_is_spawned(self) -> None:
        # One child at a time, also where the old one may still run: an exit whose code never arrived.
        for code in (1, None):
            with self.subTest(code=code):
                app, old, spawner, _now = crashing()
                closed_when_spawned: list[int] = []

                def make(spawn: object, first_id: int = 1) -> RespawnClient:
                    closed_when_spawned.append(old.closed)
                    return spawner(spawn, first_id=first_id)

                app.make_client = make  # type: ignore[assignment]
                crash(app, old, code=code)
                self.assertEqual(closed_when_spawned, [1])
                self.assertEqual(old.closed, 1)


class LostCallTests(unittest.TestCase):
    """What the exited gateway never answered is settled as the respawn starts, not when its 120 s run out."""

    def test_a_steer_comes_back_at_once_and_its_row_says_the_gateway_exited(self) -> None:
        app, old, _spawner, now = crashing(busy=True, cols=120)
        type_text(app, "steer me")
        app._on_input(Key(ENTER, ctrl=True))
        self.assertEqual(app.client.named("session.steer"), [{"session_id": SID, "text": "steer me"}])  # type: ignore[attr-defined]
        crash(app, old)
        self.assertEqual(app.composer.text, "steer me")  # never sent again: Hermes may have taken it
        self.assertEqual([call.method for call in app.pending.values()], ["config.get", "commands.catalog"])
        self.assertIn(f"⧗ {STEER_LOST_OUTCOME} · steer me", drawn(app))
        said = notices(app)
        self.assertIn(STEER_LOST_NOTICE.format(count=1, s=""), said)
        self.assertFalse([text for text in said if "you had left" in text])
        now[0] += CALL_ANSWER_SECONDS + 1
        app._expire_calls()  # only the new gateway's own calls are left to expire
        self.assertFalse([text for text in notices(app)[len(said):] if "steer" in text])
        self.assertEqual(app.composer.text, "steer me")

    def test_an_agent_steer_comes_back_too(self) -> None:
        from test_tui_agent_list import focused

        spawner = Spawner()
        app, _recording = focused(environ=dict(ENVIRON), make_client=spawner)
        old = RespawnClient()
        app.client = old  # type: ignore[assignment]
        app.stored_id = STORED
        app._on_input(Key(CHAR, "s"))
        type_text(app, "skip the tests folder")
        app._on_input(Key(ENTER))
        self.assertEqual([method for method, _params in old.calls], ["subagent.steer"])
        crash(app, old)
        self.assertEqual(app.composer.text, "skip the tests folder")
        self.assertIn(STEER_LOST_NOTICE.format(count=1, s=""), notices(app))

    def test_other_calls_are_forgotten_without_a_word_and_their_echoes_close(self) -> None:
        for streaming in (False, True):  # typed during a reply, the echo is held under it, out of the blocks
            with self.subTest(streaming=streaming):
                app, old, _spawner, now = crashing(busy=streaming)
                if streaming:
                    app._on_event(Event("message.start", SID, {}))
                    app._on_event(Event("message.delta", SID, {"text": "still streaming"}))
                type_text(app, "/usage")
                app._on_input(Key(ENTER))
                transcript = app.transcript
                (echo,) = [block for block in transcript.blocks + transcript._held if isinstance(block, CommandBlock)]
                self.assertFalse(echo.done)  # open while its call is out
                app._request("model.options", {"session_id": SID}, lambda result: None)  # one whose expiry says so
                before = notices(app)
                crash(app, old)
                self.assertTrue(echo.done)
                now[0] += CALL_ANSWER_SECONDS + 1
                app._expire_calls()
                said = " ".join(notices(app)[len(before):])
                for method in ("slash.exec", "model.options"):  # only the new gateway's own calls are left to expire
                    self.assertNotIn(method, said)


class TellFieldAcrossARespawnTests(unittest.TestCase):
    def test_what_the_open_tell_field_held_comes_back_to_the_draft_with_a_notice(self) -> None:
        from test_tui_choice_ui import armed, press
        from test_tui_questions import TELL_APPROVAL

        from omh.tui.app import TELL_LOST_NOTICE
        from omh.tui.keys import DOWN

        for typed in ("half a tell", ""):
            with self.subTest(typed=typed):
                app, old, _spawner, _now = crashing(busy=True)
                type_text(app, "my draft")
                app._on_server_request(TELL_APPROVAL)
                armed(app)
                press(app, *[Key(DOWN)] * 3, Key(ENTER))
                type_text(app, typed)
                crash(app, old)
                self.assertIsNone(app.tell_draft)
                self.assertEqual(app.composer.text, f"my draft\n{typed}" if typed else "my draft")
                self.assertEqual(TELL_LOST_NOTICE in notices(app), bool(typed))
                self.assertEqual(app.client.named("session.steer"), [])  # type: ignore[attr-defined]  # never sent


class AgentsAcrossARespawnTests(unittest.TestCase):
    """The subagents the agent view held stay in it across a respawn: they never move to the HUD's agents block."""

    def test_finished_agents_stay_in_the_view_and_running_ones_are_marked_interrupted(self) -> None:
        from test_tui_agent_view import agent_event
        from test_tui_panels import agent_row, hud_payload, with_agents
        from test_tui_subagents import FIRST, SECOND

        from omh.tui.panels import HudSnapshot
        from omh.tui.subagents import COMPLETED, INTERRUPTED

        app, old, _spawner, _now = crashing(busy=True)
        agent_event(app, "start", FIRST, goal="Run the shell command one")
        agent_event(app, "start", SECOND, goal="Run the shell command two")
        agent_event(app, "complete", FIRST, goal="Run the shell command one", status="completed")
        app.agent_steer = SECOND  # the person picked the running one to steer
        app.hud = HudSnapshot(STORED, with_agents(hud_payload(), [agent_row(0), agent_row(1)]), 0.0)
        crash(app, old)
        self.assertEqual({agent.subagent_id: agent.status for agent in app.roster.agents.values()},
                         {FIRST: COMPLETED, SECOND: INTERRUPTED})  # the gateway that ran it is gone
        self.assertIsNone(app.agent_steer)
        view = [line_text(line) for line in app._agent_view(120, 30)]
        self.assertTrue(view[1].startswith("  ✓ Run the shell command one"), view)
        self.assertTrue(view[2].startswith("  ▪ Run the shell command two"), view)
        self.assertFalse([row for row in view if "│" in row], "no HUD agents block header beside them")


class NoRespawnTests(unittest.TestCase):
    def test_a_normal_exit_is_never_respawned(self) -> None:
        app, old, spawner, _now = crashing()
        crash(app, old, code=0)
        self.assertEqual((app.exit_code, spawner.made), (1, []))
        self.assertIn(f"hermes --tui --resume {STORED}", app.farewell)

    def test_the_persons_quit_is_never_respawned(self) -> None:
        app, old, spawner, _now = crashing()
        type_text(app, "/quit")
        app._on_input(Key(ENTER))
        crash(app, old)
        self.assertEqual((app.exit_code, spawner.made), (0, []))

    def test_a_gateway_another_runtime_owns_is_never_respawned(self) -> None:
        app, old, spawner, _now = crashing(environ={**ENVIRON, contract.ATTACH_ENV: "ws://127.0.0.1:9/x"})
        crash(app, old)
        self.assertEqual((app.exit_code, spawner.made), (1, []))

    def test_without_a_way_to_spawn_the_tui_leaves_as_before(self) -> None:
        app, _client = make_app(environ=ENVIRON)
        app.stored_id = STORED  # an app made without make_client
        app.client.inbox.append(GatewayExited(1))  # type: ignore[attr-defined]
        app._drain_gateway()
        self.assertEqual(app.exit_code, 1)


class CapTests(unittest.TestCase):
    def test_three_respawns_in_a_minute_then_the_tui_leaves_naming_hermes_tui(self) -> None:
        app, client, spawner, now = crashing()
        for attempt in range(RESPAWN_LIMIT):
            crash(app, client)
            self.assertIsNone(app.exit_code, attempt)
            client = app.client  # type: ignore[assignment]
            now[0] += 10.0
        crash(app, client)
        self.assertEqual(app.exit_code, 1)
        self.assertEqual(len(spawner.made), RESPAWN_LIMIT)
        self.assertIn(f"hermes --tui --resume {STORED}", app.farewell)

    def test_under_omh_the_tui_leaves_past_the_cap_naming_omh_resume(self) -> None:
        from omh.tui.launch import SESSION_FILE_ENV

        app, client, _spawner, now = crashing(environ={**ENVIRON, SESSION_FILE_ENV: "/private/omh-tui-x/session"})
        for _ in range(RESPAWN_LIMIT + 1):
            crash(app, client)
            client = app.client  # type: ignore[assignment]
            now[0] += 10.0
        self.assertEqual(app.exit_code, 1)
        self.assertTrue(app.farewell.endswith(f"Resume the session: omh --resume {STORED}"), app.farewell)
        self.assertNotIn("hermes --tui", app.farewell)

    def test_under_omh_the_farewell_carries_the_whole_id_and_a_named_profile(self) -> None:
        from omh.tui.launch import SESSION_FILE_ENV

        long_id = "local-" + "b3c800dd" * 8  # Hermes' newer stored ids: 70 characters, never shortened
        for profile, expected in (("", f"omh --resume {long_id}"), ("default", f"omh --resume {long_id}"),
                                  ("work", f"omh -p work --resume {long_id}")):
            with self.subTest(profile=profile):
                app, client, _spawner, _now = crashing(environ={**ENVIRON, SESSION_FILE_ENV: "/private/omh-tui-x/session"})
                app.stored_id, app.launch_profile = long_id, profile
                crash(app, client, code=0)  # a normal exit is never respawned: the TUI leaves at once
                self.assertTrue(app.farewell.endswith(f"Resume the session: {expected}"), app.farewell)

    def test_under_omh_a_profile_or_id_that_cannot_be_typed_back_names_hermes_instead(self) -> None:
        from omh.tui.launch import SESSION_FILE_ENV

        for stored, profile in ((STORED, "Bad Name"), ("sess alpha", "")):
            with self.subTest(stored=stored, profile=profile):
                app, client, _spawner, _now = crashing(environ={**ENVIRON, SESSION_FILE_ENV: "/private/omh-tui-x/session"})
                app.stored_id, app.launch_profile = stored, profile
                crash(app, client, code=0)  # a normal exit is never respawned: the TUI leaves at once
                self.assertIn("Resume the session in Hermes' own terminal: hermes --tui", app.farewell)

    def test_the_window_slides(self) -> None:
        app, client, spawner, now = crashing()
        for _ in range(RESPAWN_LIMIT):
            crash(app, client)
            client = app.client  # type: ignore[assignment]
        now[0] += RESPAWN_WINDOW_SECONDS + 1
        crash(app, client)
        self.assertIsNone(app.exit_code)
        self.assertEqual(len(spawner.made), RESPAWN_LIMIT + 1)

    def test_a_gateway_that_does_not_start_again_uses_an_attempt_and_the_next_is_tried(self) -> None:
        for error in ("the gateway exited with code 1 before gateway.ready",
                      f"the gateway sent no gateway.ready within {RESPAWN_READY_SECONDS:g}s"):
            with self.subTest(error=error):
                spawner = Spawner(RespawnClient(start_error=GatewayUnavailable(error)), RespawnClient())
                app, old, _spawner, _now = crashing(spawner=spawner)
                crash(app, old)
                self.assertIsNone(app.exit_code)
                self.assertEqual(len(spawner.made), 2)
                self.assertIs(app.client, spawner.made[1])
                self.assertEqual(sum("starting it again" in text for text in notices(app)), 2)
                self.assertIn(error, notices(app)[1])  # the second attempt's notice names why the first failed

    def test_the_wait_honours_the_startup_timeout_hermes_own_tui_reads(self) -> None:
        # ui-tui gatewayClient.ts: Math.max(5000, parseInt(HERMES_TUI_STARTUP_TIMEOUT_MS ?? '15000') || 15000) ms.
        for value, seconds in (("20000", 20.0), ("1000", 5.0), ("0", 15.0), ("soon", 15.0), (None, 15.0)):
            with self.subTest(value=value):
                environ = {**ENVIRON, **({"HERMES_TUI_STARTUP_TIMEOUT_MS": value} if value is not None else {})}
                app, old, spawner, _now = crashing(environ=environ)
                crash(app, old)
                self.assertEqual(spawner.made[0].ready_timeout, seconds)

    def test_the_first_notice_is_on_screen_before_the_old_gateway_is_waited_on(self) -> None:
        # Closing a child that hangs takes seconds (stdin, terminate, kill): the screen says why first.
        app, old, _spawner, _now = crashing()
        screens: list[str] = []

        def close(grace: float = 3.0, terminate_grace: float | None = None) -> int | None:
            screens.append("\n".join(app.terminal.screen.lines()))  # type: ignore[attr-defined]
            return 1

        old.close = close  # type: ignore[method-assign]
        crash(app, old)
        self.assertIn("starting it again", screens[0])

    def test_a_resize_as_the_gateway_is_lost_still_shows_the_notice_before_the_wait(self) -> None:
        # A resize waits for the size to settle before it redraws; the respawn blocks before that, so it is drawn now.
        app, old, _spawner, _now = crashing()
        screens: list[str] = []

        def close(grace: float = 3.0, terminate_grace: float | None = None) -> int | None:
            screens.append("\n".join(app.terminal.screen.lines()))  # type: ignore[attr-defined]
            return 1

        old.close = close  # type: ignore[method-assign]
        app.terminal.screen.resize(24, 100)  # type: ignore[attr-defined]
        app.terminal._resized = True  # type: ignore[attr-defined]
        crash(app, old)
        self.assertIn("starting it again", screens[0])
        self.assertEqual(app.size, (100, 24))

    def test_a_respawn_waits_seconds_not_a_minute_for_the_new_gateway(self) -> None:
        # Hermes' own TUI reports a gateway with no `gateway.ready` after 15 s (ui-tui `STARTUP_TIMEOUT_MS`); the keys
        # wait meanwhile, so three hung attempts hold them for 45 s rather than 3 minutes.
        app, old, spawner, _now = crashing()
        crash(app, old)
        self.assertEqual(spawner.made[0].ready_timeout, RESPAWN_READY_SECONDS)
        self.assertLessEqual(RESPAWN_READY_SECONDS, 15.0)

    def test_none_starting_ends_it_after_the_cap(self) -> None:
        spawner = Spawner(*[RespawnClient(start_error=GatewayCallError("client.capabilities", 4000, "no")) for _ in range(5)])
        app, old, _spawner, _now = crashing(spawner=spawner)
        crash(app, old)
        self.assertEqual(app.exit_code, 1)
        self.assertEqual(len(spawner.made), RESPAWN_LIMIT)
        self.assertIn("the new Hermes gateway did not start", app.farewell)

    def test_a_resume_the_new_gateway_refuses_ends_it(self) -> None:
        refused = RespawnClient(resume=GatewayCallError("session.resume", 4007, "session is owned by another process"))
        app, old, _spawner, _now = crashing(spawner=Spawner(refused))
        crash(app, old)
        self.assertEqual(app.exit_code, 1)
        self.assertEqual(refused.closed, 1)
        self.assertIn(f"did not resume session {STORED}", app.farewell)

    def test_a_new_gateway_that_exits_while_it_resumes_uses_an_attempt_and_the_next_resumes(self) -> None:
        # Hermes' own TUI keeps the session to recover across a gateway that dies before its resume lands (ui-tui
        # `gatewayRecovery.ts` recoverSid) and tries it again within the same budget.
        died = RespawnClient(resume=GatewayUnavailable("the gateway exited while session.resume was waiting for an answer"))
        spawner = Spawner(died, RespawnClient())
        app, old, _spawner, _now = crashing(spawner=spawner)
        crash(app, old)
        self.assertIsNone(app.exit_code)
        self.assertEqual(died.closed, 1)
        self.assertIs(app.client, spawner.made[1])
        self.assertEqual(spawner.made[1].blocking, [("session.resume", {"session_id": STORED, "cols": 80})])
        self.assertIn(f"exited before it resumed session {STORED}", notices(app)[1])

    def test_none_resuming_ends_it_after_the_cap(self) -> None:
        dying = [RespawnClient(resume=GatewayUnavailable("the gateway exited")) for _ in range(5)]
        app, old, spawner, _now = crashing(spawner=Spawner(*dying))
        crash(app, old)
        self.assertEqual(app.exit_code, 1)
        self.assertEqual(len(spawner.made), RESPAWN_LIMIT)
        self.assertEqual([client.closed for client in spawner.made], [1] * RESPAWN_LIMIT)
        self.assertIn(f"exited before it resumed session {STORED}", app.farewell)

    def test_with_no_stored_session_there_is_nothing_to_resume(self) -> None:
        app, old, spawner, _now = crashing()
        app.stored_id = ""
        crash(app, old)
        self.assertEqual((app.exit_code, spawner.made), (1, []))


class LoopTests(unittest.TestCase):
    def test_the_loop_respawns_and_the_respawned_gateway_is_reaped_on_exit(self) -> None:
        first = RespawnClient()
        first.inbox.append(GatewayExited(1))
        spawner = Spawner()
        terminal = ScriptedTerminal(24, 80)
        terminal.script(Step(b"\x04", when=lambda: bool(spawner.made), label="respawned"))

        def poller(omh_home: object, hermes_home: object) -> FakePoller:
            return FakePoller()

        first.resume = {"session_id": SID, "stored_session_id": STORED, "info": {}}
        environ = {**ENVIRON, "HERMES_TUI_RESUME": STORED}
        code = _run(first, environ, _Sink(), lambda: terminal, poller, spawner, contain_faults=False)  # type: ignore[arg-type]
        self.assertEqual(code, 0)
        (new,) = spawner.made
        self.assertEqual(new.closed, 1)  # reaped by `_run`; the first one is the caller's to close
        self.assertEqual(new.blocking, [("session.resume", {"session_id": STORED, "cols": 80})])


class SignalDuringRespawnTests(unittest.TestCase):
    """SIGTERM or SIGHUP (`_exit_on_signal`'s SystemExit) while a respawned gateway starts or resumes: it is reaped."""

    def run_until_signalled(self, new: RespawnClient) -> RespawnClient:
        first = RespawnClient()
        first.inbox.append(GatewayExited(1))
        first.resume = {"session_id": SID, "stored_session_id": STORED, "info": {}}
        terminal = ScriptedTerminal(24, 80)

        def poller(omh_home: object, hermes_home: object) -> FakePoller:
            return FakePoller()

        environ = {**ENVIRON, "HERMES_TUI_RESUME": STORED}
        with self.assertRaises(SystemExit):
            _run(first, environ, _Sink(), lambda: terminal, poller, Spawner(new), contain_faults=False)  # type: ignore[arg-type]
        self.assertEqual(terminal.exited, 1)  # the terminal was handed back first
        return first

    def test_a_signal_while_it_starts_or_resumes_leaves_no_gateway_behind(self) -> None:
        for where in ("start", "resume"):
            with self.subTest(during=where):
                new = SignalledClient(where)
                first = self.run_until_signalled(new)
                self.assertEqual(new.closed, 1)
                self.assertEqual(first.closed, 1)  # reaped before the new one was spawned


class SignalledClient(RespawnClient):
    """A respawned client during whose `start` or blocking `session.resume` SIGTERM's handler raises."""

    def __init__(self, where: str) -> None:
        super().__init__()
        self.where = where

    def start(self, ready_timeout: float = 60.0, cancel: object = None) -> Event:
        if self.where == "start":
            raise SystemExit(143)
        return super().start(ready_timeout)

    def call(self, method: str, params: dict, timeout: float = 30.0, cancel: object = None) -> dict:
        if self.where == "resume":
            raise SystemExit(143)
        return super().call(method, params, timeout)


class WaitingClient(RespawnClient):
    """A respawned client whose start or resume waits, asking `cancel` each poll as `GatewayClient` does."""

    def __init__(self, where: str, polls: int = 5) -> None:
        super().__init__()
        self.where, self.polls = where, polls

    def start(self, ready_timeout: float = 60.0, cancel: object = None) -> Event:
        self.ready_timeout = ready_timeout
        if self.where == "start":
            self.wait(cancel, reaps=True)
        return Event("gateway.ready", None, {})

    def call(self, method: str, params: dict, timeout: float = 30.0, cancel: object = None) -> dict:
        if self.where == "resume":
            self.wait(cancel, reaps=False)
        return super().call(method, params, timeout)

    def wait(self, cancel: object, reaps: bool) -> None:
        from omh.tui.gateway import GatewayCancelled

        for _ in range(self.polls):
            if cancel():  # type: ignore[operator]
                self.closed += int(reaps)  # GatewayClient.start reaps its own child before it raises
                raise GatewayCancelled("the person left")


class LeavingDuringARespawnTests(unittest.TestCase):
    """A respawn waits inside one loop step; Ctrl+C or Ctrl+D read meanwhile ends the TUI, the new child reaped."""

    def crashing_with(self, client: WaitingClient, reads: list[bytes]) -> tuple[App, RespawnClient, Spawner]:
        spawner = Spawner(client)
        app, old, _spawner, _now = crashing(spawner=spawner, busy=True)
        app.terminal.read = lambda timeout, wake=None: reads.pop(0) if reads else b""  # type: ignore[method-assign]
        return app, old, spawner

    def test_ctrl_c_or_ctrl_d_while_it_waits_leaves_naming_hermes_tui(self) -> None:
        for where in ("start", "resume"):
            for key in (b"\x03", b"\x04"):
                with self.subTest(during=where, key=key):
                    new = WaitingClient(where)
                    app, old, spawner = self.crashing_with(new, [b"", key])
                    crash(app, old)
                    self.assertEqual(app.exit_code, 1)
                    self.assertIn("you left while the Hermes gateway was starting again", app.farewell)
                    self.assertIn(f"hermes --tui --resume {STORED}", app.farewell)
                    self.assertEqual(new.closed, 1)  # reaped, by its start or by the TUI
                    self.assertEqual(len(spawner.made), 1)  # no attempt after it

    def test_other_keys_read_while_it_waits_are_typed_once_it_is_back(self) -> None:
        app, old, _spawner = self.crashing_with(WaitingClient("start", polls=3), [b"h", b"i"])
        type_text(app, "draft ")
        crash(app, old)
        self.assertIsNone(app.exit_code)
        app._take_input(b"!")  # the next read: what came while it waited goes first
        self.assertEqual(app.composer.text, "draft hi!")


class FirstIdTests(unittest.TestCase):
    def test_a_client_made_to_replace_another_starts_its_ids_where_it_is_told(self) -> None:
        client = GatewayClient(gateway_spawn(ENVIRON), first_id=7)
        with patch.object(client, "_write"):  # nothing spawned: the request is only recorded as waited for
            self.assertEqual([client.request("session.list", {}), client.request("session.list", {})], [7, 8])
        self.assertEqual(GatewayClient(gateway_spawn(ENVIRON))._next_id, 1)  # a first client starts at 1


class _Sink:
    def write(self, text: str) -> None:
        pass

    def flush(self) -> None:
        pass


if __name__ == "__main__":
    unittest.main()
