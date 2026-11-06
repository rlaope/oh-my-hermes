"""`/gateway restart`: Hermes' own restart command, confirmed in the slot, then the same session reattached.

The person types `/gateway restart`; the slot names what the gateway's record
says the restart interrupts and offers Restart or Cancel. Restart runs
`hermes gateway restart --yes --detach` on Hermes' interpreter for the
session's profile (`gateway_restart.restart_spawn`), a crash respawn waits
while it runs, and once it ended the TUI reattaches to the same session id,
keeping the composer's draft and sending nothing again, however long Hermes'
command takes (a service-run gateway lets running work finish first). A named
profile the shared gateway serves picks between that profile and the whole
gateway. A failure says so with the command to run instead.
Every case drives an `App` over recording clients and a fake restart run: no
gateway, no Hermes, no process.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from test_hermes_gateway_health import iso, write_home
from test_tui_modes import SID, drawn, make_app, notices, type_text
from test_tui_respawn import ENVIRON, RESUMED, STORED, RespawnClient, Spawner
from omh.tui import bot_board, gateway_restart, slash
from omh.tui.app import (
    GATEWAY_CANCEL_CHOICE,
    GATEWAY_EXTERNAL_REATTACH_SECONDS,
    GATEWAY_EXTERNAL_REATTACHING_NOTICE,
    GATEWAY_STOPPED_REASON,
    GATEWAY_NOW_RUNS_NOTICE,
    GATEWAY_REATTACH_SECONDS,
    GATEWAY_REATTACHED_NOTICE,
    GATEWAY_REATTACHING_NOTICE,
    GATEWAY_RESTART_ALREADY,
    GATEWAY_RESTART_CANCELLED,
    GATEWAY_RESTART_CHOICE,
    GATEWAY_RESTART_HELD_NOTICE,
    GATEWAY_RESTART_QUESTION,
    GATEWAY_PROFILE_CHOICE,
    GATEWAY_PROFILE_REATTACHED_NOTICE,
    GATEWAY_RESTART_SECONDS,
    GATEWAY_RESTART_SLOW,
    GATEWAY_RESTART_STARTED,
    GATEWAY_RESTART_STDIO,
    GATEWAY_RESTART_UNREATTACHABLE,
    GATEWAY_SAME_OWNER_NOTICE,
    GATEWAY_UNKNOWN_OWNER_NOTICE,
    GATEWAY_WHOLE_CHOICE,
    RECONNECTED_NOTICE,
    RESPAWN_LEFT_REASON,
    RESPAWNED_NOTICE,
    RECORD_FAILED,
    RECORD_RESTARTING,
    RECORD_STOPPED,
    SLOT_ARM_SECONDS,
    App,
    record_verdict,
)
from omh.tui.bot_board import Gateway, Platform
from omh.tui.gateway import GatewayCallError, GatewayExited, GatewayTimeout, GatewayUnavailable
from omh.tui.gateway_restart import RestartImpact, RestartResult
from omh.tui.keys import DOWN, ENTER, ESCAPE, Key
from omh.tui.transcript import NOTICE_ERROR, NOTICE_WARN

HOST = Gateway(
    "running", True, 4242, active_agents=2, served=("default", "kami"), supervised=True,
    platforms=(Platform("kami:discord", "connected", current=True), Platform("telegram", "connected", current=True),
               Platform("feishu", "connected", current=False)),
)
RESTART_ARGV = ("/opt/hermes/venv/bin/python", "-m", "hermes_cli.main", "-p", "default", "gateway", "restart", "--yes",
                "--detach")
EPOCH_BEFORE, EPOCH_AFTER = 7, 8


class FakeRun:
    """A restart command in flight: `finish` ends it."""

    def __init__(self) -> None:
        self.ended: RestartResult | None = None

    def result(self) -> RestartResult | None:
        return self.ended

    def finish(self, code: int | None = 0, output: tuple[str, ...] = (), error: str = "") -> None:
        self.ended = RestartResult(code, output, error)


def restart_app(*, busy: bool = False, impact: RestartImpact | None = None, spawner: Spawner | None = None,
                resume: dict | None = None) -> tuple[App, RespawnClient, Spawner, list, list[float]]:
    """An app attached to a shared gateway, session `STORED` open, with the restart's seams recorded."""
    now = [100.0]
    spawner = spawner or Spawner(RespawnClient(resume=resume or {**RESUMED, "authority_epoch": EPOCH_AFTER}))
    app, _recording = make_app(busy=busy, environ=dict(ENVIRON), clock=lambda: now[0], make_client=spawner)
    app.terminal.read = lambda timeout, wake=None: b""  # type: ignore[method-assign]  # no input: a step never waits
    old = RespawnClient()
    app.client = old  # type: ignore[assignment]
    app.stored_id = STORED
    app.shared_gateway = True
    app.launch_profile = "default"
    app.authority_epoch = EPOCH_BEFORE
    started: list = []

    def start(spawn: object, wake: object) -> FakeRun:
        run = FakeRun()
        started.append((spawn, wake, run))
        return run

    app.start_restart = start
    app.read_restart_impact = lambda environ, profile: impact or RestartImpact(None, HOST)  # type: ignore[assignment]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    app.sleep = sleep
    return app, old, spawner, started, now


def ask(app: App, now: list[float]) -> None:
    type_text(app, "/gateway restart")
    app._on_input(Key(ENTER))
    now[0] += SLOT_ARM_SECONDS


def pick(app: App, choice: str) -> None:
    (question,) = app.slot.params["questions"]  # type: ignore[union-attr]
    for _ in range(question["choices"].index(choice)):
        app._on_input(Key(DOWN))
    app._on_input(Key(ENTER))


def confirm(app: App, now: list[float]) -> None:
    ask(app, now)
    pick(app, GATEWAY_RESTART_CHOICE)


def served(**overrides: object) -> RestartImpact:
    """The shared gateway's record, for a session in profile kami that it serves."""
    return RestartImpact(None, HOST, "kami", **overrides)  # type: ignore[arg-type]


class ConfirmTests(unittest.TestCase):
    def test_the_slot_names_what_the_restart_interrupts_and_offers_restart_or_cancel(self) -> None:
        app, _old, _spawner, started, now = restart_app(busy=True)
        ask(app, now)
        slot = app.slot
        self.assertIsNotNone(slot)
        self.assertTrue(slot.picking)
        (question,) = slot.params["questions"]
        self.assertEqual(question["choices"], [GATEWAY_RESTART_CHOICE, GATEWAY_CANCEL_CHOICE])
        self.assertEqual(question["question"].splitlines(), [
            "profiles: default, kami · bots: kami:discord, telegram · 2 running",  # not the old process's feishu
            "Running work (turns, cron jobs, this session's turn included) finishes first, up to 30 min (Hermes' "
            "restart_after_turn_timeout); new turns wait meanwhile.",
            GATEWAY_RESTART_QUESTION,
        ])
        self.assertIn(GATEWAY_RESTART_QUESTION, "\n".join(drawn(app)))
        self.assertEqual(started, [])  # nothing runs before the person picks

    def test_cancel_and_esc_run_nothing(self) -> None:
        for key in ("cancel", "esc"):
            with self.subTest(key=key):
                app, old, spawner, started, now = restart_app()
                ask(app, now)
                if key == "cancel":
                    pick(app, GATEWAY_CANCEL_CHOICE)
                else:
                    app._on_input(Key(ESCAPE))
                self.assertIsNone(app.slot)
                self.assertEqual(started, [])
                self.assertIsNone(app.gateway_restart)
                self.assertIn(GATEWAY_RESTART_CANCELLED, notices(app))
                self.assertEqual(old.answers, [])  # the TUI's own question: nothing went to Hermes
                app._step()
                self.assertEqual(spawner.made, [])

    def test_restart_runs_hermes_own_command_once_for_the_sessions_profile(self) -> None:
        app, _old, _spawner, started, now = restart_app()
        confirm(app, now)
        ((spawn, wake, _run),) = started
        self.assertEqual(spawn.argv, RESTART_ARGV)
        self.assertEqual(spawn.cwd, ENVIRON["HERMES_PYTHON_SRC_ROOT"])
        self.assertEqual(spawn.env["PYTHONPATH"], os.pathsep.join(("/opt/hermes", "/opt/hermes/site")))
        self.assertEqual(wake, app._wake_loop)
        self.assertIn(GATEWAY_RESTART_STARTED.format(command="hermes gateway restart"), notices(app))
        self.assertIn("restarting Hermes' gateway… 0s", "\n".join(drawn(app)))
        type_text(app, "/gateway restart")
        app._on_input(Key(ENTER))  # a second one while it runs asks nothing and runs nothing
        self.assertIsNone(app.slot)
        self.assertEqual(len(started), 1)
        self.assertIn(GATEWAY_RESTART_ALREADY, notices(app))

    def test_it_is_unavailable_where_it_cannot_reattach(self) -> None:
        app, _old, _spawner, started, now = restart_app()
        app.shared_gateway = False  # Hermes' stdio entry: the session's gateway is the child itself
        ask(app, now)
        self.assertIsNone(app.slot)
        self.assertIn(GATEWAY_RESTART_STDIO.format(command="hermes gateway restart"), notices(app, NOTICE_WARN))
        app, _old, _spawner, started, now = restart_app()
        app.make_client = None  # nothing can spawn the gateway child again
        ask(app, now)
        self.assertIsNone(app.slot)
        self.assertIn(GATEWAY_RESTART_UNREATTACHABLE.format(command="hermes gateway restart"), notices(app, NOTICE_WARN))
        self.assertEqual(started, [])

    def test_bare_gateway_goes_to_hermes_as_typed(self) -> None:
        app, client = make_app()
        type_text(app, "/gateway")
        app._on_input(Key(ENTER))
        self.assertEqual(client.named("slash.exec"), [{"command": "gateway", "session_id": SID}])
        self.assertIsNone(app.slot)

    def test_help_and_completion_list_it(self) -> None:
        self.assertIn("gateway", [completion.name for completion in slash.completions("gat")])
        command = slash.parse_slash("/gateway restart")
        self.assertEqual((command.command.name, command.command.route, command.arg), ("gateway", slash.LOCAL, "restart"))
        app, _client = make_app()
        type_text(app, "/help")
        app._on_input(Key(ENTER))
        self.assertTrue(any("/gateway" in said and "Restart Hermes' gateway" in said for said in notices(app)))


class ProfileChoiceTests(unittest.TestCase):
    def test_a_served_profile_picks_between_itself_and_the_whole_gateway(self) -> None:
        app, _old, _spawner, started, now = restart_app(impact=served())
        app.launch_profile = "kami"
        ask(app, now)
        (question,) = app.slot.params["questions"]  # type: ignore[union-attr]
        self.assertEqual(question["choices"], [GATEWAY_PROFILE_CHOICE.format(profile="kami"), GATEWAY_WHOLE_CHOICE,
                                               GATEWAY_CANCEL_CHOICE])
        screen = "\n".join(drawn(app))
        self.assertIn("Restart this profile (kami)", screen)
        # The choice's dim description: Hermes re-serves the profile without draining, so its turns stop now.
        self.assertIn("its running turns stop now; only kami reconnects; no new OMH code", screen)
        self.assertIn("Restart the whole gateway", screen)
        self.assertEqual(question["question"].splitlines()[1],
                         "On a whole-gateway restart, running work (turns, cron jobs) finishes first, up to 30 min "
                         "(Hermes' restart_after_turn_timeout); new turns wait meanwhile.",
                         "the drain is the whole gateway's, not the profile's")
        self.assertEqual(started, [])

    def test_this_profile_runs_hermes_restart_for_it_and_says_hermes_words_after(self) -> None:
        app, _old, spawner, started, now = restart_app(impact=served())
        app.launch_profile = "kami"
        ask(app, now)
        pick(app, GATEWAY_PROFILE_CHOICE.format(profile="kami"))
        ((spawn, _wake, run),) = started
        self.assertEqual(spawn.argv[-6:], ("-p", "kami", "gateway", "restart", "--yes", "--detach"))
        self.assertIn(GATEWAY_RESTART_STARTED.format(command="hermes -p kami gateway restart"), notices(app))
        run.finish(0, ("Profile 'kami' restarted by the host gateway.",))
        app._step()
        said = notices(app)
        self.assertIn(GATEWAY_PROFILE_REATTACHED_NOTICE.format(session=STORED, profile="kami"), said)
        self.assertIn("Profile 'kami' restarted by the host gateway.", "\n".join(said))
        self.assertFalse([line for line in said if "now runs OMH" in line])
        self.assertEqual(len(spawner.made), 1)

    def test_the_whole_gateway_is_hermes_restart_of_the_default_profile(self) -> None:
        app, _old, _spawner, started, now = restart_app(impact=served())
        app.launch_profile = "kami"
        ask(app, now)
        pick(app, GATEWAY_WHOLE_CHOICE)
        ((spawn, _wake, _run),) = started
        self.assertEqual(spawn.argv, RESTART_ARGV)  # `-p default`, as Hermes' Desktop addresses the shared process
        self.assertIn(GATEWAY_RESTART_STARTED.format(command="hermes -p default gateway restart"), notices(app))

    def test_the_default_profile_keeps_one_restart(self) -> None:
        app, _old, _spawner, _started, now = restart_app()
        ask(app, now)
        (question,) = app.slot.params["questions"]  # type: ignore[union-attr]
        self.assertEqual(question["choices"], [GATEWAY_RESTART_CHOICE, GATEWAY_CANCEL_CHOICE])


class ReattachTests(unittest.TestCase):
    def test_a_finished_restart_reattaches_to_the_same_session_and_keeps_the_draft(self) -> None:
        app, old, spawner, started, now = restart_app()
        confirm(app, now)
        type_text(app, "half a thought")
        old.inbox.append(GatewayExited(69))  # the gateway went down with going-away
        app._step()
        self.assertEqual(spawner.made, [])  # no respawn while Hermes' command runs
        self.assertTrue(app.respawn_reason)
        started[0][2].finish(0)
        app._step()
        (new,) = spawner.made
        self.assertIs(app.client, new)
        self.assertEqual(new.blocking, [("session.resume", {"session_id": STORED, "cols": 80})])
        self.assertEqual(app.stored_id, STORED)
        self.assertEqual(app.composer.text, "half a thought")
        self.assertEqual(new.named("prompt.submit"), [])
        said = notices(app)
        self.assertIn(GATEWAY_REATTACHING_NOTICE.format(session=STORED), said)
        self.assertIn(GATEWAY_REATTACHED_NOTICE.format(session=STORED), said)
        self.assertNotIn(RESPAWNED_NOTICE.format(session=STORED), said)
        self.assertEqual(app.respawned_at, [])  # not one of the crash respawn's three
        self.assertIsNone(app.gateway_restart)

    def test_a_child_still_connected_when_it_finished_is_reattached_too(self) -> None:
        app, old, spawner, started, now = restart_app()
        confirm(app, now)
        started[0][2].finish(0)
        app._step()
        self.assertEqual(old.closed, 1)
        self.assertEqual(len(spawner.made), 1)
        self.assertEqual(app.stored_id, STORED)

    def test_a_gateway_not_answering_yet_is_tried_again_until_it_is(self) -> None:
        later = RespawnClient(resume={**RESUMED, "authority_epoch": EPOCH_AFTER})
        spawner = Spawner(RespawnClient(start_error=GatewayUnavailable("starting", returncode=69)),
                          RespawnClient(start_error=GatewayUnavailable("starting", returncode=69)), later)
        app, _old, spawner, started, now = restart_app(spawner=spawner)
        confirm(app, now)
        started[0][2].finish(0)
        app._step()
        self.assertEqual(len(spawner.made), 3)
        self.assertIs(app.client, later)
        self.assertIsNone(app.exit_code)
        self.assertEqual(notices(app).count(GATEWAY_REATTACHING_NOTICE.format(session=STORED)), 1)

    def test_a_gateway_that_never_comes_back_ends_the_wait_with_the_way_back(self) -> None:
        spawner = Spawner(*[RespawnClient(start_error=GatewayUnavailable("starting", returncode=69))
                            for _ in range(200)])
        app, _old, spawner, started, now = restart_app(spawner=spawner)
        confirm(app, now)
        started[0][2].finish(0)
        app._step()
        self.assertEqual(app.exit_code, 1)  # as a crash respawn that gave up: the way back is the farewell
        self.assertIn("Resume the session in Hermes' own terminal", app.farewell)
        self.assertIn(f"did not come back within {GATEWAY_REATTACH_SECONDS:g} s of its restart",
                      notices(app, NOTICE_ERROR)[-1])
        self.assertLess(len(spawner.made), 200)  # tried once a second, not without a pause
        self.assertEqual(app.respawned_at, [])

    def test_an_exit_0_with_the_same_owner_or_none_named_is_said_with_hermes_words(self) -> None:
        linger = ("Cannot restart gateway as a service — linger is not enabled.",)
        for epoch, notice in ((EPOCH_BEFORE, GATEWAY_SAME_OWNER_NOTICE), (None, GATEWAY_UNKNOWN_OWNER_NOTICE)):
            with self.subTest(epoch=epoch):
                resumed = {**RESUMED, "authority_epoch": epoch} if epoch is not None else dict(RESUMED)
                app, _old, _spawner, started, now = restart_app(resume=resumed)
                confirm(app, now)
                started[0][2].finish(0, linger)
                app._step()
                said = notices(app)
                self.assertIn(notice.format(session=STORED), notices(app, NOTICE_WARN))
                self.assertIn(linger[0], "\n".join(said))
                self.assertNotIn(GATEWAY_REATTACHED_NOTICE.format(session=STORED), said)

    def test_a_prompt_sent_while_it_restarts_stays_in_the_composer(self) -> None:
        app, old, _spawner, _started, now = restart_app()
        confirm(app, now)
        type_text(app, "hello")
        app._on_input(Key(ENTER))
        self.assertEqual(old.named("prompt.submit"), [])
        self.assertEqual(app.composer.text, "hello")
        self.assertIn(GATEWAY_RESTART_HELD_NOTICE, notices(app, NOTICE_WARN))
        self.assertIn("Esc or Ctrl+C still interrupts", GATEWAY_RESTART_HELD_NOTICE)

    def test_stop_goes_while_it_restarts(self) -> None:
        app, old, _spawner, _started, now = restart_app(busy=True)
        confirm(app, now)
        type_text(app, "/stop")
        app._on_input(Key(ENTER))
        self.assertEqual(old.named("slash.exec"), [{"command": "stop", "session_id": SID}])
        self.assertNotIn(GATEWAY_RESTART_HELD_NOTICE, notices(app, NOTICE_WARN))

    def test_commands_that_call_the_gateway_wait_and_the_tuis_own_go(self) -> None:
        for line in ("/gateway", "/gateway status", "/new", "/sessions other-1", "/steer go on", "/model gpt-x",
                     "/effort high", "!ls", "/usage", "/image shot.png", "/paste"):
            with self.subTest(line=line):
                app, old, _spawner, _started, now = restart_app()
                confirm(app, now)
                calls = list(old.calls)
                type_text(app, line)
                app._on_input(Key(ENTER))
                self.assertEqual(old.calls, calls)
                self.assertEqual(app.composer.text, line)
                self.assertIn(GATEWAY_RESTART_HELD_NOTICE, notices(app, NOTICE_WARN))
        app, old, _spawner, _started, now = restart_app()
        confirm(app, now)
        type_text(app, "/details")
        app._on_input(Key(ENTER))
        self.assertNotIn(GATEWAY_RESTART_HELD_NOTICE, notices(app, NOTICE_WARN))

    def test_a_resume_refused_or_unanswered_is_tried_again(self) -> None:
        for error in (GatewayCallError("session.resume", 4003, "runtime_draining"), GatewayTimeout("session.resume", 30)):
            with self.subTest(error=type(error).__name__):
                later = RespawnClient(resume={**RESUMED, "authority_epoch": EPOCH_AFTER})
                app, _old, spawner, started, now = restart_app(spawner=Spawner(RespawnClient(resume=error), later))
                confirm(app, now)
                started[0][2].finish(0)
                app._step()
                self.assertEqual(len(spawner.made), 2)
                self.assertIs(app.client, later)
                self.assertIsNone(app.exit_code)
                self.assertEqual(spawner.made[0].closed, 1)

    def test_ctrl_c_while_the_reattach_waits_leaves(self) -> None:
        spawner = Spawner(*[RespawnClient(start_error=GatewayUnavailable("starting", returncode=69)) for _ in range(5)])
        app, _old, spawner, started, now = restart_app(spawner=spawner)
        confirm(app, now)
        app.terminal.read = lambda timeout, wake=None: b"\x03" if timeout == 0.0 else b""  # type: ignore[method-assign]
        started[0][2].finish(0)
        app._step()
        self.assertEqual(app.exit_code, 1)
        self.assertEqual(len(spawner.made), 1)  # it left in the pause after the first try
        self.assertIn("you left while the Hermes gateway was starting again", app.farewell)

    def test_a_running_turn_on_the_old_gateway_is_said_lost(self) -> None:
        app, old, _spawner, started, now = restart_app(busy=True)
        confirm(app, now)
        old.inbox.append(GatewayExited(1))
        app._step()
        started[0][2].finish(0)
        app._step()
        self.assertIn("The running turn was lost when the Hermes gateway exited; it was not sent again.", notices(app))


class FailureTests(unittest.TestCase):
    def test_a_refused_restart_names_why_and_the_command_and_sends_nothing(self) -> None:
        app, old, spawner, started, now = restart_app()
        confirm(app, now)
        started[0][2].finish(78, ("The host gateway runs under profile 'kami'.", "  hermes -p kami gateway restart"))
        app._step()
        said = notices(app)
        self.assertIn("Hermes' gateway restart failed (exit code 78), so the gateway may not have restarted; run "
                      "`hermes gateway restart` in a terminal.", said)
        self.assertIn("The host gateway runs under profile 'kami'.", "\n".join(said))
        self.assertEqual(spawner.made, [])  # the child is still attached: nothing to reattach
        self.assertIsNone(app.gateway_restart)
        self.assertIs(app.client, old)

    def test_a_command_that_could_not_start_says_so(self) -> None:
        app, _old, _spawner, started, now = restart_app()
        confirm(app, now)
        started[0][2].finish(None, error="could not start /opt/hermes/venv/bin/python: no such file")
        app._step()
        self.assertIn("could not start /opt/hermes/venv/bin/python", notices(app, NOTICE_ERROR)[-1])

    def test_a_command_still_draining_past_the_cap_holds_the_respawn_until_it_ends(self) -> None:
        app, old, spawner, started, now = restart_app(busy=True)
        confirm(app, now)
        now[0] += GATEWAY_RESTART_SECONDS + 1
        app._step()
        slow = GATEWAY_RESTART_SLOW.format(seconds=GATEWAY_RESTART_SECONDS)
        self.assertIn(slow, notices(app, NOTICE_WARN))
        old.inbox.append(GatewayExited(69))  # Hermes' drain ended and the old gateway went down
        app._step()
        now[0] += 600
        app._step()
        self.assertEqual(spawner.made, [])  # no crash respawn while Hermes' command still runs
        self.assertEqual(notices(app, NOTICE_WARN).count(slow), 1)
        self.assertIn("restarting Hermes' gateway…", "\n".join(drawn(app)))
        started[0][2].finish(0)
        app._step()
        self.assertEqual(len(spawner.made), 1)
        self.assertEqual(app.respawned_at, [])  # the restart's reattach, not one of the crash respawn's three
        self.assertIn(GATEWAY_REATTACHED_NOTICE.format(session=STORED), notices(app))
        self.assertNotIn(RESPAWNED_NOTICE.format(session=STORED), notices(app))

    def test_a_failure_after_the_gateway_went_away_respawns_as_after_a_crash(self) -> None:
        app, old, spawner, started, now = restart_app()
        confirm(app, now)
        old.inbox.append(GatewayExited(1))
        app._step()
        started[0][2].finish(1, ("✗ Gateway service restart failed.",))
        app._step()
        self.assertEqual(len(spawner.made), 1)
        self.assertEqual(len(app.respawned_at), 1)
        self.assertIn(RESPAWNED_NOTICE.format(session=STORED), notices(app))


class GenerationNoteTests(unittest.TestCase):
    def setUp(self) -> None:
        top = tempfile.mkdtemp(prefix="omh-gateway-restart-")
        self.addCleanup(shutil.rmtree, top, ignore_errors=True)
        self.home = Path(top) / ".hermes"

    def test_the_new_omh_version_is_named_once_the_gateways_start_passes_the_bundles_install(self) -> None:
        installed = time.time() - 60
        write_home(self.home, starts=[installed - 3600], installed_at=iso(installed))
        manifest = self.home / "plugins" / "omh" / ".omh-plugin-manifest.json"
        manifest.write_text(json.dumps({**json.loads(manifest.read_text()), "version": "4.0.7"}), encoding="utf-8")
        app, _old, _spawner, started, now = restart_app(impact=RestartImpact(self.home, HOST))
        confirm(app, now)
        write_home(self.home, starts=[installed - 3600, time.time()])  # the new gateway's start
        started[0][2].finish(0)
        app._step()
        self.assertIn(GATEWAY_NOW_RUNS_NOTICE.format(version="4.0.7"), notices(app))

    def test_nothing_is_said_when_the_gateway_was_not_behind(self) -> None:
        installed = time.time() - 60
        write_home(self.home, starts=[installed + 10], installed_at=iso(installed))
        app, _old, _spawner, started, now = restart_app(impact=RestartImpact(self.home, HOST))
        confirm(app, now)
        started[0][2].finish(0)
        app._step()
        self.assertFalse([said for said in notices(app) if "now runs OMH" in said])


class ExternalRestartTests(unittest.TestCase):
    """A restart this screen did not ask for (`hermes gateway restart` elsewhere, `omh update`, launchd): the screen
    waits with one status row and reattaches the same session; a stop elsewhere ends it at once."""

    BACK_RESUME = {**RESUMED, "authority_epoch": EPOCH_AFTER}
    DRAINING = Gateway("draining", True, 4242, active_agents=1, updated=50.0, restart_requested=True)
    NEW = Gateway("running", True, 4343, updated=90.0)  # the service's new pid

    def external(self, *clients: RespawnClient, record=None, impact: RestartImpact | None = None,
                 make=None):
        """An attached app whose gateway record is `record(now)`; `make(now)` scripts the next client by time."""
        spawner = Spawner(*clients)
        app, old, spawner, _started, now = restart_app(spawner=spawner, impact=impact or RestartImpact(None, None))
        spawned: list[float] = []

        def make_client(spawn: object, first_id: int = 1) -> RespawnClient:
            spawned.append(now[0])
            if make is not None:
                spawner.queued.insert(0, make(now[0]))
            return spawner(spawn, first_id)

        app.make_client = make_client  # type: ignore[assignment]
        app.read_gateway_record = (  # type: ignore[assignment]
            lambda environ, profile: record(now[0]) if record is not None else None)
        return app, old, spawner, now, spawned

    @staticmethod
    def not_up() -> RespawnClient:
        return RespawnClient(start_error=GatewayUnavailable("draining", returncode=69))

    def test_a_service_restart_draining_for_minutes_is_tried_every_5_s_then_reattached(self) -> None:
        rows: list[list[str]] = []

        def record(at: float) -> Gateway:
            if at < 700.0:  # the old pid drains its running turn for ten minutes, past any fixed budget
                if 130.0 <= at < 140.0 and not rows:
                    rows.append(drawn(app))
                return self.DRAINING
            return self.NEW

        app, old, spawner, now, spawned = self.external(record=record, make=lambda at: (
            self.not_up() if at < 700.0 else RespawnClient(resume=self.BACK_RESUME)))
        type_text(app, "half a thought")
        old.inbox.append(GatewayExited(1))  # the drain closed this screen's connection
        app._step()
        self.assertIsNone(app.exit_code)
        gaps = {round(later - earlier) for earlier, later in zip(spawned, spawned[1:])}
        self.assertEqual(gaps, {5})  # one try each 5 s while it drains, never a burst
        self.assertGreaterEqual(spawned[-1], 700.0)
        self.assertIs(app.client, spawner.made[-1])
        self.assertEqual(spawner.made[-1].blocking, [("session.resume", {"session_id": STORED, "cols": 80})])
        self.assertEqual(app.stored_id, STORED)
        self.assertEqual(app.composer.text, "half a thought")
        self.assertEqual(notices(app, NOTICE_WARN), [GATEWAY_EXTERNAL_REATTACHING_NOTICE.format(session=STORED)])
        self.assertIn(GATEWAY_REATTACHED_NOTICE.format(session=STORED), notices(app))  # a new owner epoch
        self.assertEqual(app.respawned_at, [])  # none of the crash respawn's three
        self.assertIsNone(app.reattach_since)
        (screen,) = rows
        self.assertTrue(any("Hermes' gateway is restarting… 0:3" in line and "ctrl+c leaves" in line
                            for line in screen), screen)
        self.assertFalse(any("restarting…" in line for line in drawn(app)))

    def test_the_after_turn_wait_admits_a_try_so_a_parked_question_can_be_answered(self) -> None:
        app, old, spawner, _now, _spawned = self.external(
            RespawnClient(resume=dict(RESUMED, authority_epoch=EPOCH_BEFORE)), record=lambda at: self.DRAINING)
        old.inbox.append(GatewayExited(1))
        app._step()
        self.assertIsNone(app.exit_code)
        self.assertEqual(len(spawner.made), 1)  # tried at once, while it drains
        self.assertIn(RECONNECTED_NOTICE.format(session=STORED), notices(app))  # the same owner, still draining

    def test_a_stop_elsewhere_leaves_at_once_without_starting_the_service_again(self) -> None:
        records = {
            "draining to stop": Gateway("draining", True, 4242, updated=50.0),
            "stopped": Gateway("stopped", False, 4242, updated=50.0),
        }
        for name, stopped in records.items():
            for code in (1, 69):
                with self.subTest(record=name, code=code):
                    app, old, spawner, _now, _spawned = self.external(record=lambda at, stopped=stopped: stopped)
                    old.inbox.append(GatewayExited(code))
                    app._step()
                    self.assertEqual(app.exit_code, 1)
                    self.assertEqual(spawner.made, [])
                    self.assertIn(GATEWAY_STOPPED_REASON, app.farewell)
                    self.assertIn("Resume the session in Hermes' own terminal", app.farewell)

    def test_a_stopped_gateway_is_said_plainly_with_how_to_start_it(self) -> None:
        # A state and the command that starts it again: not a crash, and nothing the person did wrong.
        app, old, _spawner, _now, _spawned = self.external(record=lambda at: Gateway("stopped", False, 4242, updated=50.0))
        old.inbox.append(GatewayExited(1))
        app._step()
        self.assertTrue(app.farewell.startswith(
            "omh: Hermes' gateway is stopped; `hermes gateway start` starts it again. Resume the session"), app.farewell)

    def test_a_stop_during_the_wait_ends_it(self) -> None:
        def record(at: float) -> Gateway:
            return self.DRAINING if at < 120.0 else Gateway("stopped", False, 4242, updated=119.0)

        app, old, spawner, now, _spawned = self.external(record=record, make=lambda at: self.not_up())
        old.inbox.append(GatewayExited(1))
        app._step()
        self.assertEqual(app.exit_code, 1)
        self.assertLess(now[0], 130.0)
        self.assertIn(GATEWAY_STOPPED_REASON, app.farewell)

    def test_a_start_that_failed_after_the_drop_ends_the_wait_with_hermes_reason(self) -> None:
        failed = Gateway("startup_failed", False, 4343, updated=60.0, exit_reason="config.yaml: bad model")

        app, old, spawner, now, _spawned = self.external(
            record=lambda at: self.DRAINING if at < 110.0 else failed, make=lambda at: self.not_up())
        old.inbox.append(GatewayExited(1))
        app._step()
        self.assertEqual(app.exit_code, 1)
        self.assertLess(now[0], 120.0)
        self.assertIn("the new Hermes gateway did not start (config.yaml: bad model)", app.farewell)

    def test_a_restart_without_a_service_is_tried_again_with_growing_pauses(self) -> None:
        app, old, spawner, now, spawned = self.external(
            *[self.not_up() for _ in range(5)], RespawnClient(resume=self.BACK_RESUME))
        old.inbox.append(GatewayExited(1))
        app._step()
        self.assertIsNone(app.exit_code)
        self.assertEqual(len(spawner.made), 6)
        gaps = [round(later - earlier) for earlier, later in zip(spawned, spawned[1:])]
        self.assertEqual(gaps, [1, 2, 4, 5, 5])
        warned = notices(app, NOTICE_WARN)
        self.assertEqual(len(warned), 2)  # the drop's first try, then one wait: not a line per try
        self.assertIn("(1 of 3 in 60 s)", warned[0])
        self.assertEqual(warned[1], GATEWAY_EXTERNAL_REATTACHING_NOTICE.format(session=STORED))
        self.assertEqual(len(app.respawned_at), 1)
        self.assertEqual(app.stored_id, STORED)

    def test_a_dead_pids_draining_record_is_not_a_drain(self) -> None:
        dead = Gateway("draining", False, 4242, updated=50.0, restart_requested=True)
        app, old, spawner, _now, spawned = self.external(
            *[self.not_up() for _ in range(3)], RespawnClient(resume=self.BACK_RESUME), record=lambda at: dead)
        old.inbox.append(GatewayExited(1))
        app._step()
        self.assertIsNone(app.exit_code)
        self.assertEqual([round(later - earlier) for earlier, later in zip(spawned, spawned[1:])], [1, 2, 4])
        self.assertEqual(app.respawned_at, [])  # the record's restart asked: the wait began at the drop

    def test_a_going_away_exit_69_waits_from_the_drop(self) -> None:
        app, old, spawner, _now, _spawned = self.external(*[self.not_up() for _ in range(2)],
                                                          RespawnClient(resume=dict(RESUMED)))
        old.inbox.append(GatewayExited(69))
        app._step()
        self.assertIsNone(app.exit_code)
        self.assertEqual(notices(app, NOTICE_WARN), [GATEWAY_EXTERNAL_REATTACHING_NOTICE.format(session=STORED)])
        self.assertEqual(app.respawned_at, [])
        # No owner epoch named: the same gateway over a new connection, not a restart the screen can confirm.
        self.assertIn(RECONNECTED_NOTICE.format(session=STORED), notices(app))

    def test_exit_69_waits_only_on_a_shared_gateway_with_a_session_to_resume(self) -> None:
        for shared, stored in ((False, STORED), (True, "")):
            with self.subTest(shared=shared, stored=stored):
                app, _old, _spawner, _now, _spawned = self.external()
                app.shared_gateway, app.stored_id = shared, stored
                self.assertIsNone(app._external_restart(True))

    def test_a_gateway_that_never_comes_back_ends_after_the_budget_with_the_way_back(self) -> None:
        app, old, spawner, now, _spawned = self.external(make=lambda at: self.not_up())
        old.inbox.append(GatewayExited(69))
        app._step()
        self.assertEqual(app.exit_code, 1)
        self.assertGreaterEqual(now[0] - 100.0, GATEWAY_EXTERNAL_REATTACH_SECONDS)
        self.assertLess(len(spawner.made), 40)
        self.assertIn(f"did not come back within {GATEWAY_EXTERNAL_REATTACH_SECONDS:g} s",
                      notices(app, NOTICE_ERROR)[-1])
        self.assertIn("Resume the session", app.farewell)
        self.assertIn(STORED, app.farewell)

    def test_a_wedged_draining_record_waits_no_longer_than_hermes_after_turn_timeout_and_the_budget(self) -> None:
        impact = RestartImpact(None, None, wait_seconds=60.0)
        app, old, spawner, now, _spawned = self.external(
            record=lambda at: self.DRAINING, impact=impact, make=lambda at: self.not_up())
        old.inbox.append(GatewayExited(1))
        app._step()
        self.assertEqual(app.exit_code, 1)
        self.assertLessEqual(now[0] - 100.0, 60.0 + GATEWAY_EXTERNAL_REATTACH_SECONDS)
        self.assertGreaterEqual(now[0] - 100.0, GATEWAY_EXTERNAL_REATTACH_SECONDS)

    def test_a_try_that_fails_another_way_spends_the_crash_respawns_tries(self) -> None:
        app, old, spawner, now, _spawned = self.external(
            make=lambda at: RespawnClient(start_error=GatewayUnavailable("refused", returncode=1)))
        old.inbox.append(GatewayExited(69))
        app._step()
        self.assertEqual(app.exit_code, 1)
        self.assertEqual(len(spawner.made), 4)  # three spent, the fourth failure finds none left
        self.assertLess(now[0] - 100.0, 60.0)
        self.assertIn("did not start", notices(app, NOTICE_ERROR)[-1])

    def test_a_refused_resume_spends_a_crash_try_and_an_unanswered_one_keeps_waiting(self) -> None:
        refused = GatewayCallError("session.resume", 4003, "session_not_found")
        app, old, spawner, now, _spawned = self.external(make=lambda at: RespawnClient(resume=refused))
        old.inbox.append(GatewayExited(69))
        app._step()
        self.assertEqual(app.exit_code, 1)
        self.assertEqual(len(spawner.made), 4)
        self.assertLess(now[0] - 100.0, 60.0)
        silent = [RespawnClient(resume=GatewayTimeout("session.resume", 30)) for _ in range(3)]
        app, old, spawner, _now, _spawned = self.external(*silent, RespawnClient(resume=self.BACK_RESUME))
        old.inbox.append(GatewayExited(69))
        app._step()
        self.assertIsNone(app.exit_code)
        self.assertEqual(app.respawned_at, [])

    def test_ctrl_c_while_it_drains_leaves(self) -> None:
        app, old, spawner, _now, _spawned = self.external(record=lambda at: self.DRAINING,
                                                          make=lambda at: self.not_up())
        app.terminal.read = lambda timeout, wake=None: b"\x03" if timeout == 0.0 else b""  # type: ignore[method-assign]
        old.inbox.append(GatewayExited(1))
        app._step()
        self.assertEqual(app.exit_code, 1)
        self.assertEqual(len(spawner.made), 1)  # it left in the pause after the first try
        self.assertIn(RESPAWN_LEFT_REASON, app.farewell)

    def test_the_new_omh_version_is_named_once_the_restarted_gateway_loaded_it(self) -> None:
        home = Path("/nonexistent/.hermes")
        app, old, _spawner, _now, _spawned = self.external(
            record=lambda at: self.DRAINING if at < 110.0 else self.NEW, impact=RestartImpact(home, None),
            make=lambda at: self.not_up() if at < 110.0 else RespawnClient(resume=self.BACK_RESUME))
        old.inbox.append(GatewayExited(1))
        with patch("omh.maintenance.hermes_gateway.stale_bundle_version", side_effect=["4.0.7", None]) as stale:
            app._step()
        self.assertEqual([call.args for call in stale.call_args_list], [(home,), (home,)])
        said = notices(app)
        self.assertIn(GATEWAY_REATTACHED_NOTICE.format(session=STORED), said)
        self.assertIn(GATEWAY_NOW_RUNS_NOTICE.format(version="4.0.7"), said)

    def test_a_plain_drop_on_a_running_gateway_stays_the_crash_respawn(self) -> None:
        app, old, spawner, _now, _spawned = self.external(
            RespawnClient(resume=dict(RESUMED)), record=lambda at: Gateway("running", True, 4242, updated=50.0))
        old.inbox.append(GatewayExited(1))
        app._step()
        self.assertIsNone(app.exit_code)
        self.assertEqual(len(app.respawned_at), 1)
        self.assertNotIn(GATEWAY_EXTERNAL_REATTACHING_NOTICE.format(session=STORED), notices(app))


class RecordTests(unittest.TestCase):
    """`read_record`: the serving gateway's record, live or not, for a drop to be read by."""

    def setUp(self) -> None:
        top = tempfile.mkdtemp(prefix="omh-gateway-record-")
        self.addCleanup(shutil.rmtree, top, ignore_errors=True)
        self.root = Path(top) / ".hermes"

    def write(self, home: Path, **record: object) -> None:
        home.mkdir(parents=True, exist_ok=True)
        (home / "gateway_state.json").write_text(json.dumps(record), encoding="utf-8")

    def test_a_stopped_gateways_record_is_read_though_its_pid_is_gone(self) -> None:
        self.write(self.root, pid=999999, gateway_state="stopped", restart_requested=False,
                   updated_at="2026-11-06T00:00:00+00:00")
        record = gateway_restart.read_record({"HERMES_HOME": str(self.root)}, "default")
        self.assertIsNotNone(record)
        self.assertEqual((record.state, record.live), ("stopped", False))  # type: ignore[union-attr]
        self.assertIsNone(gateway_restart.read_impact({"HERMES_HOME": str(self.root)}, "default").gateway)

    def test_no_home_or_no_record_is_none(self) -> None:
        self.assertIsNone(gateway_restart.read_record({}, "default"))
        self.assertIsNone(gateway_restart.read_record({"HERMES_HOME": str(self.root)}, "default"))

    def test_the_verdicts(self) -> None:
        cases = (
            (Gateway("draining", True, 1, restart_requested=True), RECORD_RESTARTING),
            (Gateway("stopped", False, 1, restart_requested=True), RECORD_RESTARTING),
            (Gateway("starting", True, 1), RECORD_RESTARTING),
            (Gateway("draining", True, 1), RECORD_STOPPED),
            (Gateway("stopped", False, 1), RECORD_STOPPED),
            (Gateway("startup_failed", False, 1, updated=60.0), RECORD_FAILED),
            (Gateway("running", True, 1), ""),
            (Gateway("running", False, 1), ""),  # an unexpected signal: Hermes keeps "running" for a restart
            (Gateway("draining", False, 1), ""),
            (None, ""),
        )
        for gateway, verdict in cases:
            with self.subTest(gateway=gateway):
                self.assertEqual(record_verdict(gateway), verdict)
        old_failure = Gateway("startup_failed", False, 1, updated=40.0)
        self.assertEqual(record_verdict(old_failure, seen=50.0), "")


class SpawnTests(unittest.TestCase):
    def test_the_profile_flag_follows_hermes_profile_name(self) -> None:
        self.assertEqual(gateway_restart.profile_args("kami"), ("-p", "kami"))
        self.assertEqual(gateway_restart.profile_args("default"), ("-p", "default"))
        for name in ("", "custom", "Bad Name", "-p", "../x"):
            with self.subTest(name=name):
                self.assertEqual(gateway_restart.profile_args(name), ())
        self.assertEqual(gateway_restart.manual_command("kami"), "hermes -p kami gateway restart")
        self.assertEqual(gateway_restart.manual_command("default"), "hermes gateway restart")
        self.assertEqual(gateway_restart.manual_command("custom"), "hermes gateway restart")
        self.assertEqual(gateway_restart.manual_command("default", explicit=True), "hermes -p default gateway restart")

    def test_the_spawn_takes_no_tui_variable_and_runs_from_hermes_source_root(self) -> None:
        environ = {**ENVIRON, "OMH_TUI_SESSION_FILE": "/tmp/x", "HERDR_PANE_ID": "p1", "HERMES_HOME": "/h"}
        spawn = gateway_restart.restart_spawn(environ, "kami")
        self.assertEqual(spawn.argv[-6:], ("-p", "kami", "gateway", "restart", "--yes", "--detach"))
        self.assertNotIn("OMH_TUI_SESSION_FILE", spawn.env)
        self.assertNotIn("HERDR_PANE_ID", spawn.env)
        marked = gateway_restart.restart_spawn({**environ, "_HERMES_GATEWAY": "1", "HERMES_GATEWAY_MODE": "x"}, "kami")
        self.assertFalse(set(gateway_restart.GATEWAY_MARKERS) & set(marked.env))  # as Hermes' updater strips them
        self.assertEqual(spawn.env["HERMES_HOME"], "/h")
        self.assertEqual(spawn.cwd, "/opt/hermes")

    def test_the_run_is_its_own_session_with_no_stdin_and_keeps_the_outputs_tail(self) -> None:
        seen: dict = {}

        class Process:
            def wait(self) -> int:
                seen["stdout"].write(b"".join(f"line {n}\n".encode() for n in range(10)))
                return 3

        def popen(argv: list[str], **options: object) -> Process:
            seen.update(options, argv=argv)
            return Process()

        woken: list[bool] = []
        run = gateway_restart.RestartRun(gateway_restart.restart_spawn(ENVIRON, "default"), lambda: woken.append(True),
                                         popen=popen)
        deadline = time.monotonic() + 5
        while run.result() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(seen["argv"], list(RESTART_ARGV))
        self.assertIs(seen["start_new_session"], True)
        self.assertEqual(seen["stdin"], subprocess.DEVNULL)
        self.assertEqual(seen["stderr"], subprocess.STDOUT)
        self.assertNotIsInstance(seen["stdout"], int)  # a file, never a pipe the TUI's exit would break
        self.assertEqual(run.result(), RestartResult(3, tuple(f"line {n}" for n in range(4, 10))))
        self.assertEqual(woken, [True])

    def test_a_spawn_that_fails_is_a_result_at_once(self) -> None:
        def popen(argv: list[str], **options: object) -> object:
            raise FileNotFoundError(2, "No such file")

        run = gateway_restart.RestartRun(gateway_restart.restart_spawn(ENVIRON, "default"), lambda: None, popen=popen)
        result = run.result()
        self.assertIsNotNone(result)
        self.assertIsNone(result.returncode)
        self.assertIn("could not start /opt/hermes/venv/bin/python", result.error)

    def test_the_tail_is_bounded(self) -> None:
        output = io.BytesIO(b"x" * (gateway_restart.OUTPUT_TAIL_BYTES * 3) + b"\nlast\n")
        self.assertEqual(gateway_restart._tail(output)[-1], "last")


class ImpactTests(unittest.TestCase):
    def setUp(self) -> None:
        top = tempfile.mkdtemp(prefix="omh-gateway-impact-")
        self.addCleanup(shutil.rmtree, top, ignore_errors=True)
        self.top = Path(top)

    def test_a_served_profile_reads_the_shared_gateways_record(self) -> None:
        records = {Path("/r/profiles/kami"): Gateway("", False), Path("/r"): HOST}
        with patch.object(bot_board, "read_gateway", lambda home: records[Path(home)]):
            impact = gateway_restart.read_impact({"HERMES_HOME": "/r/profiles/kami"}, "kami")
        self.assertEqual((impact.home, impact.profile), (Path("/r"), "kami"))
        self.assertEqual(impact.platforms, ("kami:discord", "telegram"))
        self.assertEqual(gateway_restart.impact_lines(impact, busy=False)[0],
                         "profiles: default, kami · bots: kami:discord, telegram · 2 running")

    def test_a_profile_with_its_own_gateway_reads_its_own_record(self) -> None:
        own = Gateway("running", True, 99)
        with patch.object(bot_board, "read_gateway", lambda home: own):
            impact = gateway_restart.read_impact({"HERMES_HOME": "/r/profiles/solo"}, "solo")
        self.assertEqual((impact.home, impact.gateway, impact.profile), (Path("/r/profiles/solo"), own, ""))
        self.assertEqual(gateway_restart.impact_lines(impact, busy=False), ["no bots connected · nothing running"])

    def test_no_live_record_is_said_unknown(self) -> None:
        with patch.object(bot_board, "read_gateway", lambda home: Gateway("", False, problem="no gateway record")):
            impact = gateway_restart.read_impact({"HERMES_HOME": "/r"}, "default")
        self.assertIsNone(impact.gateway)
        lines = gateway_restart.impact_lines(impact, busy=True)
        self.assertIn("who else uses it is unknown here", lines[0])
        self.assertEqual(lines[1], "This session's running turn would be interrupted too.")
        records = {Path("/r/profiles/kami"): Gateway("", False), Path("/r"): Gateway("running", True, 1, served=("default",))}
        with patch.object(bot_board, "read_gateway", lambda home: records[Path(home)]):
            self.assertIsNone(gateway_restart.read_impact({"HERMES_HOME": "/r/profiles/kami"}, "kami").gateway)

    def test_a_service_run_gateway_lets_running_work_finish_and_any_other_interrupts_it(self) -> None:
        drained = RestartImpact(None, Gateway("running", True, 1, active_agents=1, supervised=True), wait_seconds=600)
        self.assertEqual(gateway_restart.impact_lines(drained, busy=False), [
            "no bots connected · 1 running",
            "Running work (turns, cron jobs) finishes first, up to 10 min (Hermes' restart_after_turn_timeout); new "
            "turns wait meanwhile.",
        ])
        # No `--external-supervisor` in its argv: Hermes' own systemd or launchd service still drains it (SIGUSR1),
        # which the record cannot tell, so neither "finishes first" nor "interrupted" is claimed alone.
        unflagged = RestartImpact(None, Gateway("running", True, 1, active_agents=1), wait_seconds=600)
        self.assertEqual(gateway_restart.impact_lines(unflagged, busy=False)[1],
                         "Running work (turns, cron jobs) finishes first, up to 10 min (Hermes' "
                         "restart_after_turn_timeout); new turns wait meanwhile if a service (systemd, launchd) runs "
                         "this gateway; otherwise it is interrupted.")
        no_wait = RestartImpact(None, Gateway("running", True, 1, supervised=True), wait_seconds=0)
        self.assertEqual(gateway_restart.impact_lines(no_wait, busy=True), [
            "no bots connected · 1 running",
            "Running work (turns, cron jobs, this session's turn included) would be interrupted.",
        ])

    def test_the_wait_is_read_from_the_gateway_homes_config(self) -> None:
        home = self.top / "home"
        home.mkdir()
        self.assertEqual(gateway_restart.after_turn_seconds(home), gateway_restart.DEFAULT_AFTER_TURN_SECONDS)
        (home / "config.yaml").write_bytes(b"agent:\n  restart_after_turn_timeout: 120\n")  # LF on every OS
        self.assertEqual(gateway_restart.after_turn_seconds(home), 120.0)
        (home / "config.yaml").write_bytes(b"agent:\n  restart_after_turn_timeout: soon\n")  # LF on every OS
        self.assertEqual(gateway_restart.after_turn_seconds(home), gateway_restart.DEFAULT_AFTER_TURN_SECONDS)
        (home / "config.yaml").write_bytes(b"agent:\n  restart_after_turn_timeout: '90'\n")  # YAML quotes a string
        self.assertEqual(gateway_restart.after_turn_seconds(home), 90.0)
        (home / "config.yaml").write_bytes(b"agent:\n  restart_after_turn_timeout: nan\n")  # Hermes' max(0.0, nan)
        self.assertEqual(gateway_restart.after_turn_seconds(home), 0.0)

    def test_hermes_after_turn_variable_wins_over_the_config_and_is_read_as_hermes_reads_it(self) -> None:
        # Hermes' gateway and its restart command read `HERMES_RESTART_AFTER_TURN_TIMEOUT` before the config key, with
        # `float()` (no quote stripping) and `max(0.0, value)`; a value that does not parse is Hermes' default.
        home = self.top / "env"
        home.mkdir()
        (home / "config.yaml").write_bytes(b"agent:\n  restart_after_turn_timeout: 120\n")  # LF on every OS
        default = gateway_restart.DEFAULT_AFTER_TURN_SECONDS
        cases = {"300": 300.0, " 45.5 ": 45.5, "0": 0.0, "-5": 0.0, "nan": 0.0, "soon": default, "'300'": default,
                 "inf": default,  # Hermes: no cap; the TUI keeps its reattach wait bounded (documented divergence)
                 "": 120.0, "  ": 120.0}
        for value, seconds in cases.items():
            with self.subTest(value=value):
                environ = {gateway_restart.AFTER_TURN_ENV: value}
                self.assertEqual(gateway_restart.after_turn_seconds(home, environ), seconds)
        self.assertEqual(gateway_restart.after_turn_seconds(home, {}), 120.0)
        own = Gateway("running", True, 99)
        with patch.object(bot_board, "read_gateway", lambda _home: own):
            impact = gateway_restart.read_impact(
                {"HERMES_HOME": str(home), gateway_restart.AFTER_TURN_ENV: "600"}, "default")
        self.assertEqual(impact.wait_seconds, 600.0)

    def test_the_board_reads_a_service_run_gateway_from_its_argv(self) -> None:
        home = self.top / "svc"
        home.mkdir()
        record = {"pid": 1, "start_time": 1, "gateway_state": "running",
                  "argv": ["/h/hermes_cli/main.py", "gateway", "run", "--external-supervisor"]}
        (home / "gateway_state.json").write_text(json.dumps(record), encoding="utf-8")
        self.assertTrue(bot_board.read_gateway(home).supervised)
        record["argv"] = ["/h/hermes_cli/main.py", "gateway", "run"]
        (home / "gateway_state.json").write_text(json.dumps(record), encoding="utf-8")
        self.assertFalse(bot_board.read_gateway(home).supervised)


if __name__ == "__main__":
    unittest.main()
