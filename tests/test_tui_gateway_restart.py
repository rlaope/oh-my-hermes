"""`/gateway restart`: Hermes' own restart command, confirmed in the slot, then the same session reattached.

The person types `/gateway restart`; the slot names what the gateway's record
says the restart interrupts and offers Restart or Cancel. Restart runs
`hermes gateway restart --yes --detach` on Hermes' interpreter for the
session's profile (`gateway_restart.restart_spawn`), a crash respawn waits
while it runs, and once it ended the TUI reattaches to the same session id,
keeping the composer's draft and sending nothing again. A failure, or a
command still running past its wait, says so with the command to run instead.
Every case drives an `App` over recording clients and a fake restart run: no
gateway, no Hermes, no process.
"""

from __future__ import annotations

import io
import json
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
    GATEWAY_NOW_RUNS_NOTICE,
    GATEWAY_REATTACH_SECONDS,
    GATEWAY_REATTACHED_NOTICE,
    GATEWAY_REATTACHING_NOTICE,
    GATEWAY_RESTART_ALREADY,
    GATEWAY_RESTART_CANCELLED,
    GATEWAY_RESTART_CHOICE,
    GATEWAY_RESTART_HELD_NOTICE,
    GATEWAY_RESTART_QUESTION,
    GATEWAY_RESTART_SECONDS,
    GATEWAY_RESTART_STARTED,
    GATEWAY_RESTART_STDIO,
    GATEWAY_RESTART_UNREATTACHABLE,
    GATEWAY_SAME_OWNER_NOTICE,
    RESPAWNED_NOTICE,
    SLOT_ARM_SECONDS,
    App,
)
from omh.tui.bot_board import Gateway, Platform
from omh.tui.gateway import GatewayExited, GatewayUnavailable
from omh.tui.gateway_restart import RestartImpact, RestartResult
from omh.tui.keys import DOWN, ENTER, ESCAPE, Key
from omh.tui.transcript import NOTICE_ERROR, NOTICE_WARN

HOST = Gateway(
    "running", True, 4242, active_agents=2, served=("default", "kami"),
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
    if choice == GATEWAY_CANCEL_CHOICE:
        app._on_input(Key(DOWN))
    app._on_input(Key(ENTER))


def confirm(app: App, now: list[float]) -> None:
    ask(app, now)
    pick(app, GATEWAY_RESTART_CHOICE)


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
            "Hermes' gateway (pid 4242) serves 2 profiles: default, kami.",
            "Messenger bots stop answering until it is back: kami:discord, telegram.",  # not the old process's feishu
            "2 running turns would be interrupted, this session's included.",
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
        self.assertEqual(spawn.env["PYTHONPATH"], "/opt/hermes:/opt/hermes/site")
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

    def test_the_same_owner_after_the_restart_is_said(self) -> None:
        app, _old, _spawner, started, now = restart_app(resume={**RESUMED, "authority_epoch": EPOCH_BEFORE})
        confirm(app, now)
        started[0][2].finish(0)
        app._step()
        self.assertIn(GATEWAY_SAME_OWNER_NOTICE.format(session=STORED), notices(app, NOTICE_WARN))

    def test_a_prompt_sent_while_it_restarts_stays_in_the_composer(self) -> None:
        app, old, _spawner, _started, now = restart_app()
        confirm(app, now)
        type_text(app, "hello")
        app._on_input(Key(ENTER))
        self.assertEqual(old.named("prompt.submit"), [])
        self.assertEqual(app.composer.text, "hello")
        self.assertIn(GATEWAY_RESTART_HELD_NOTICE, notices(app, NOTICE_WARN))

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

    def test_past_its_wait_it_says_so_and_a_gone_gateway_respawns_as_after_a_crash(self) -> None:
        app, old, spawner, _started, now = restart_app()
        confirm(app, now)
        old.inbox.append(GatewayExited(1))
        app._step()
        self.assertEqual(spawner.made, [])
        now[0] += GATEWAY_RESTART_SECONDS + 1
        app._step()
        self.assertTrue(any(f"has not finished after {GATEWAY_RESTART_SECONDS:g} s" in said
                            for said in notices(app, NOTICE_WARN)))
        self.assertEqual(len(spawner.made), 1)  # the crash respawn, under its own limit
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

    def test_the_spawn_takes_no_tui_variable_and_runs_from_hermes_source_root(self) -> None:
        environ = {**ENVIRON, "OMH_TUI_SESSION_FILE": "/tmp/x", "HERDR_PANE_ID": "p1", "HERMES_HOME": "/h"}
        spawn = gateway_restart.restart_spawn(environ, "kami")
        self.assertEqual(spawn.argv[-6:], ("-p", "kami", "gateway", "restart", "--yes", "--detach"))
        self.assertNotIn("OMH_TUI_SESSION_FILE", spawn.env)
        self.assertNotIn("HERDR_PANE_ID", spawn.env)
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
    def test_the_shared_gateway_of_a_served_profile_restarts_only_that_profile(self) -> None:
        records = {"/r/profiles/kami": Gateway("", False), "/r": HOST}
        with patch.object(bot_board, "read_gateway", lambda home: records[str(home)]):
            impact = gateway_restart.read_impact({"HERMES_HOME": "/r/profiles/kami"}, "kami")
        self.assertEqual((str(impact.home), impact.profile), ("/r", "kami"))
        self.assertEqual(impact.platforms, ("kami:discord",))
        lines = gateway_restart.impact_lines(impact, busy=False)
        self.assertEqual(lines[0], "Hermes restarts only profile kami inside its shared gateway (pid 4242).")
        self.assertIn("those in profile kami would be interrupted", lines[2])

    def test_a_profile_with_its_own_gateway_reads_its_own_record(self) -> None:
        own = Gateway("running", True, 99)
        with patch.object(bot_board, "read_gateway", lambda home: own):
            impact = gateway_restart.read_impact({"HERMES_HOME": "/r/profiles/solo"}, "solo")
        self.assertEqual((str(impact.home), impact.gateway, impact.profile), ("/r/profiles/solo", own, ""))
        self.assertEqual(gateway_restart.impact_lines(impact, busy=False), [
            "Hermes' gateway (pid 99).", "No messenger platform is connected to it.", "No turn is running on it.",
        ])

    def test_no_live_record_is_said_unknown(self) -> None:
        with patch.object(bot_board, "read_gateway", lambda home: Gateway("", False, problem="no gateway record")):
            impact = gateway_restart.read_impact({"HERMES_HOME": "/r"}, "default")
        self.assertIsNone(impact.gateway)
        lines = gateway_restart.impact_lines(impact, busy=True)
        self.assertIn("who else uses it is unknown here", lines[0])
        self.assertEqual(lines[1], "This session's running turn would be interrupted too.")
        records = {"/r/profiles/kami": Gateway("", False), "/r": Gateway("running", True, 1, served=("default",))}
        with patch.object(bot_board, "read_gateway", lambda home: records[str(home)]):
            self.assertIsNone(gateway_restart.read_impact({"HERMES_HOME": "/r/profiles/kami"}, "kami").gateway)

    def test_turn_counts(self) -> None:
        idle = RestartImpact(None, Gateway("running", True, 1, active_agents=1))
        self.assertEqual(gateway_restart.impact_lines(idle, busy=False)[2],
                         "1 running turn in other sessions would be interrupted.")
        lone = RestartImpact(None, Gateway("running", True, 1))
        self.assertEqual(gateway_restart.impact_lines(lone, busy=True)[2],
                         "This session's running turn would be interrupted.")


if __name__ == "__main__":
    unittest.main()
