"""The launch while the Hermes gateway is not answering: what the shell's terminal says, the retries, the bound.

Before the TUI draws, the launch waits for the gateway to come up and to open the session (`_LaunchWait` in
`omh.tui.app`). A gateway that is restarting (the attach child exits `GATEWAY_NOT_READY_EXIT`: Hermes' `starting` /
`draining` verdict, or a refused socket) or that drops the connection while the session opens is tried again
within `LAUNCH_WAIT_SECONDS`, saying so; past it the launch says what to do and exits 1 (never Hermes' own TUI,
which would ask the same gateway). A gateway draining for a restart (`runtime_draining` on the session call, or
its record's `restart_requested`) is waited through up to the drain's cap, the line naming the work it lets
finish. A normal launch says nothing at all.
"""

from __future__ import annotations

from collections.abc import Callable
import io
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from _tui_gateway_replay import EXIT, Scenario, materialize, replay_env, spans
from test_tui_app import FAST_GRACE, NO_TERMIOS, AppTestCase, Run, Step, TtyStream, startup_answers
from omh.tui import app as app_module
from omh.tui.attach import gateway_attach
from omh.tui.bot_board import Gateway
from omh.tui.gateway import (
    GATEWAY_NOT_READY_EXIT,
    GatewayCallError,
    GatewayClient,
    GatewayTimeout,
    GatewayUnavailable,
    gateway_spawn,
)
from omh.tui.gateway_restart import RestartImpact

REFUSED_LINE = "omh-attach: could not reach Hermes' gateway: [Errno 61] Connection refused"
RESTARTING = "the Hermes gateway is restarting; waiting…"
OPENING = "waiting for the Hermes gateway to open a session…"
CONNECTING = "connecting to the Hermes gateway…"
GAVE_UP = "did not answer within"
DRAINING = "the Hermes gateway restarts after"
DRAIN_GAVE_UP = "was still restarting after"


def fast_wait(**overrides: float):
    """The launch's waits shortened for a test: no quiet, a short pause, and the bound given."""
    values = {"LAUNCH_WAIT_QUIET_SECONDS": 0.0, "LAUNCH_RETRY_SECONDS": 0.05, **overrides}
    return patch.multiple(app_module, **values)


class LaunchWaitCase(AppTestCase):
    def normal(self) -> Run:
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        run.terminal.script(Step(b"\x04", when=run.terminal.idle, label="the first frame"))
        return run

    def refusing_spawn(self, run: Run, name: str) -> object:
        """A gateway child that says the gateway refused it and exits `GATEWAY_NOT_READY_EXIT`, as a restart does."""
        root = run.root / name
        root.mkdir()
        materialize(root, Scenario("session", (), stderr=(REFUSED_LINE,), after=EXIT,
                                   exit_code=GATEWAY_NOT_READY_EXIT))
        return gateway_spawn({**run.environ, **replay_env(root)})

    def clients(self, run: Run, spawns: list[Callable[[object], object]]) -> Callable[..., GatewayClient]:
        """`make_client` that builds each next client from the next spawn picker (the run's own spawn, or another)."""
        build = self.make_client(run)
        pickers = iter(spawns)

        def make(spawn: object, **options: object) -> GatewayClient:
            return build(next(pickers, lambda own: own)(spawn), **options)

        return make

    def on_call(self, run: Run, method: str, act: Callable[[int, object], None]) -> Callable[..., GatewayClient]:
        """`make_client` whose clients run `act(client number, cancel)` before sending `method`; `act` may raise."""
        build = self.make_client(run)

        def make(spawn: object, **options: object) -> GatewayClient:
            client = build(spawn, **options)
            number, call = len(run.clients), client.call

            def acting(name: str, params: dict, timeout: float = 30.0, cancel: object = None) -> dict:
                if name == method:
                    act(number, cancel)
                return call(name, params, timeout, cancel)  # type: ignore[arg-type]

            client.call = acting  # type: ignore[method-assign]
            return client

        return make

    def assert_gave_up(self, run: Run) -> None:
        """Exit 1 and no fallback asked: Hermes' own TUI would ask the same gateway."""
        self.assertEqual(run.code, 1, run.stderr.getvalue())
        self.assertFalse(run.fallback_sentinel.exists(), "a gateway that was not answering asked for the fallback")

    @staticmethod
    def draining(root: Path, work: int, cap: float) -> Callable[[object, str], RestartImpact]:
        """`read_impact` reading a record of a live gateway with a restart asked: Hermes letting `work` turns finish."""
        impact = RestartImpact(root, Gateway("draining", True, restart_requested=True, active_agents=work),
                               wait_seconds=cap)
        return lambda environ, profile: impact

    @staticmethod
    def refusing_as_draining(times: int | None) -> Callable[[int, object], None]:
        """A session.create Hermes refuses as `runtime_draining`, as its session API answers one while the gateway
        drains for a restart: the first `times` calls, or every call with None."""
        calls: list[int] = []

        def refuse(number: int, _cancel: object) -> None:
            calls.append(number)
            if times is None or len(calls) <= times:
                raise GatewayCallError("session.create", 4001, "runtime_draining", {"reason": "runtime_draining"})

        return refuse

    def launch(self, run: Run, make_client: Callable[..., GatewayClient], stderr: io.StringIO | None = None) -> Run:
        run.stderr = TtyStream() if stderr is None else stderr
        run.code = app_module.main(
            run.environ,
            stdin=TtyStream(),
            stdout=TtyStream(),
            stderr=run.stderr,
            open_terminal=lambda: run.terminal,
            make_client=make_client,
            make_poller=lambda omh_home, hermes_home: run.poller,
            contain_faults=False,  # a render bug raises here (`App.contain_faults`)
        )
        return run


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class LaunchWaitTests(LaunchWaitCase):
    def test_the_not_ready_exit_is_one_number_on_both_sides(self) -> None:
        self.assertEqual(gateway_attach.NOT_READY_EXIT, GATEWAY_NOT_READY_EXIT)

    def test_a_normal_launch_says_nothing_while_it_starts(self) -> None:
        run = self.normal()
        self.launch(run, self.make_client(run))
        self.assert_clean_run(run)
        self.assertEqual(len(run.clients), 1)
        said = run.stderr.getvalue()
        for text in (CONNECTING, RESTARTING, OPENING, GAVE_UP):
            self.assertNotIn(text, said)

    def test_a_refused_gateway_is_waited_for_and_the_launch_opens_once_it_answers(self) -> None:
        run = self.normal()
        refused = [lambda _own, n=n: self.refusing_spawn(run, f"refused-{n}") for n in range(2)]
        with fast_wait():
            self.launch(run, self.clients(run, refused))
        self.assert_clean_run(run)
        self.assertEqual(len(run.clients), 3)  # two refused, then the one that answered
        said = run.stderr.getvalue()
        self.assertIn(RESTARTING, said)
        self.assertNotIn(GAVE_UP, said)
        self.assertTrue(said.endswith("\r\x1b[2K"), repr(said[-80:]))  # the waiting line is gone before the TUI draws
        for client in run.clients[:2]:
            self.assertEqual(client.close(grace=FAST_GRACE), GATEWAY_NOT_READY_EXIT)

    def test_a_gateway_that_keeps_refusing_is_given_up_on_with_what_to_do(self) -> None:
        run = self.normal()
        refused = [lambda _own, n=n: self.refusing_spawn(run, f"refused-{n}") for n in range(50)]
        with fast_wait(LAUNCH_WAIT_SECONDS=1.0, LAUNCH_MIN_TRY_SECONDS=0.4):
            self.launch(run, self.clients(run, refused))
        self.assert_gave_up(run)
        self.assertGreaterEqual(len(run.clients), 2)
        said = run.stderr.getvalue()
        self.assertIn(RESTARTING, said)
        self.assertRegex(said, r"omh: the Hermes gateway did not answer within [1-9]\d*s;")  # the seconds waited
        self.assertIn("`hermes gateway status`", said)
        self.assertIn(f"  {REFUSED_LINE}", said)
        self.assertNotIn(DRAINING, said)  # no record said the gateway drains: the plain restarting line

    def test_a_session_that_is_slow_to_open_says_what_it_waits_for_and_opens(self) -> None:
        run = self.normal()

        def silent(_number: int, cancel: object) -> None:
            for _ in range(3):  # the gateway accepted the call and is silent for a while
                cancel()  # type: ignore[operator]
                time.sleep(0.05)

        with fast_wait():
            self.launch(run, self.on_call(run, "session.create", silent))
        self.assert_clean_run(run)
        self.assertIn(OPENING, run.stderr.getvalue())
        self.assertEqual(len(run.clients), 1)

    def test_a_resumed_session_that_is_slow_to_open_waits_the_same_way(self) -> None:
        resumed = {"result": {"session_id": "20261013_000000_abc", "messages": [],
                              "info": {"model": "deepseek/deepseek-v4.1-flash-ultrafast", "cwd": "/fixture/project"}}}
        run = self.prepare(
            Scenario("session", spans("session", "startup"), answers=(*startup_answers(), ("session.resume", resumed))),
            env={"HERMES_TUI_RESUME": "20261013_000000_abc"},
        )
        run.terminal.script(Step(b"\x04", when=run.terminal.idle, label="the first frame"))
        with fast_wait():
            self.launch(run, self.on_call(run, "session.resume", lambda _number, cancel: cancel()))  # type: ignore[operator]
        self.assert_clean_run(run)
        self.assertIn(OPENING, run.stderr.getvalue())

    def test_a_session_call_that_times_out_gives_up_with_what_to_do(self) -> None:
        run = self.normal()

        def timed_out(_number: int, _cancel: object) -> None:
            raise GatewayTimeout("session.create", 30.0)

        with fast_wait():
            self.launch(run, self.on_call(run, "session.create", timed_out))
        self.assert_gave_up(run)
        said = run.stderr.getvalue()
        self.assertRegex(said, r"omh: the Hermes gateway did not answer within \d+s;")  # the seconds waited
        self.assertIn("`hermes gateway status`", said)
        self.assertEqual(len(run.clients), 1)

    def test_ctrl_c_while_the_line_shows_erases_it_before_saying_so(self) -> None:
        run = self.normal()

        def interrupted(_number: int, cancel: object) -> None:
            cancel()  # type: ignore[operator]  # the line is on the shell
            raise KeyboardInterrupt

        with fast_wait():
            self.launch(run, self.on_call(run, "session.create", interrupted))
        self.assertEqual(run.code, 130)
        said = run.stderr.getvalue()
        self.assertIn(OPENING, said)
        self.assertIn("\r\x1b[2Komh: the OMH TUI was interrupted.", said)

    def test_a_gateway_that_dropped_the_session_call_as_not_ready_is_tried_again(self) -> None:
        run = self.normal()
        second = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        build = self.on_call(run, "session.create", self.drops(first_only=True))

        def picked(spawn: object, **options: object) -> GatewayClient:
            # The second gateway is a fresh replay: the first one's script was spent on its start.
            own = spawn if not run.clients else gateway_spawn({**run.environ, **replay_env(Path(second.root))})
            return build(own, **options)

        with fast_wait():
            self.launch(run, picked)
        # The first replay is left waiting for the create it never got: only the second one's script must be whole.
        self.assertEqual((run.terminal.stalled, run.code), ("", 0), run.stderr.getvalue())
        self.assertFalse(run.fallback_sentinel.exists())
        self.assertFalse([line for line in run.clients[1].stderr_tail() if line.startswith("replay:")])
        self.assertEqual(len(run.clients), 2)
        self.assertIn(RESTARTING, run.stderr.getvalue())

    def test_session_call_retries_stop_at_their_limit(self) -> None:
        run = self.normal()
        roots = [self.prepare(Scenario("session", spans("session", "startup"), answers=startup_answers()))
                 for _ in range(4)]
        build = self.on_call(run, "session.create", self.drops(first_only=False))

        def picked(spawn: object, **options: object) -> GatewayClient:
            own = spawn if not run.clients else gateway_spawn({**run.environ, **replay_env(roots[len(run.clients)].root)})
            return build(own, **options)

        with fast_wait():
            self.launch(run, picked)
        self.assert_gave_up(run)  # the gateway kept going away as not ready: Hermes' own TUI would meet the same
        self.assertEqual(len(run.clients), 1 + app_module.SESSION_RETRY_LIMIT)
        self.assertIn(GAVE_UP, run.stderr.getvalue())

    def test_a_gateway_that_crashes_on_the_session_call_falls_back_at_once(self) -> None:
        # Not a restart: the child exits 1 while the create waits. No new gateway, no "restarting".
        run = self.prepare(Scenario("session", spans("session", "startup"), after=EXIT, exit_code=1))
        with fast_wait():
            self.launch(run, self.make_client(run))
        self.assert_fell_back(run)
        self.assertEqual(len(run.clients), 1)
        said = run.stderr.getvalue()
        self.assertNotIn(RESTARTING, said)
        self.assertIn("could not open a Hermes session", said)

    def test_a_session_refused_while_the_gateway_drains_is_asked_again_and_opens_once_admitted(self) -> None:
        # Hermes lets two bot turns finish before its restart: the create is refused as runtime_draining twice, on
        # the same live gateway, and the TUI opens on the third ask. Never Hermes' own TUI, which would be refused too.
        run = self.normal()
        with fast_wait(LAUNCH_DRAIN_RETRY_SECONDS=0.05), \
                patch.object(app_module, "read_impact", self.draining(run.root, 2, 1800.0)):
            self.launch(run, self.on_call(run, "session.create", self.refusing_as_draining(2)))
        self.assertEqual((run.terminal.stalled, run.code), ("", 0), run.stderr.getvalue())
        self.assertFalse(run.fallback_sentinel.exists())
        self.assertEqual(len(run.clients), 1)  # the gateway is live: the same client asks again
        said = run.stderr.getvalue()
        self.assertIn(f"{DRAINING} 2 running turns (it allows up to 30 min); waiting…", said)
        self.assertIn("ctrl+c leaves", said)
        self.assertNotIn(RESTARTING, said)

    def test_a_session_refused_as_draining_past_the_drain_cap_is_given_up_on_without_a_fallback(self) -> None:
        # The bound grows once to the drain's cap (plus the plain wait); a gateway still refusing past it is given
        # up on with the drain's own sentence, exit 1, no fallback.
        run = self.normal()
        with fast_wait(LAUNCH_WAIT_SECONDS=0.3, LAUNCH_MIN_TRY_SECONDS=0.2, LAUNCH_DRAIN_RETRY_SECONDS=0.05), \
                patch.object(app_module, "read_impact", self.draining(run.root, 1, 0.2)):
            self.launch(run, self.on_call(run, "session.create", self.refusing_as_draining(None)))
        self.assert_gave_up(run)
        self.assertEqual(len(run.clients), 1)
        said = run.stderr.getvalue()
        self.assertIn(f"{DRAINING} 1 running turn (it allows up to 0.2 s)", said)
        self.assertRegex(said, rf"omh: the Hermes gateway {DRAIN_GAVE_UP} [1-9]\d*s\.")
        self.assertIn("`hermes gateway status`", said)
        self.assertNotIn(GAVE_UP, said)

    def test_a_draining_refusal_without_a_readable_record_is_still_waited_through(self) -> None:
        # The refusal itself is the evidence: no record, so the line names the work generically and Hermes' default
        # cap bounds the wait.
        run = self.normal()
        with fast_wait(LAUNCH_DRAIN_RETRY_SECONDS=0.05), \
                patch.object(app_module, "read_impact", lambda environ, profile: RestartImpact(None, None)):
            self.launch(run, self.on_call(run, "session.create", self.refusing_as_draining(1)))
        self.assertEqual((run.terminal.stalled, run.code), ("", 0), run.stderr.getvalue())
        self.assertIn(f"{DRAINING} its running work (it allows up to 30 min)", run.stderr.getvalue())

    def test_an_attach_the_draining_gateway_refuses_is_waited_for_past_the_plain_bound(self) -> None:
        # The attach child exits not ready while the record says the gateway drains: the plain bound (0.5 s) would
        # give up, the drain-aware one waits the cap (0.6 s) and the plain wait on top, paced slower.
        run = self.normal()
        refused = [lambda _own, n=n: self.refusing_spawn(run, f"refused-{n}") for n in range(50)]
        started = time.monotonic()
        with fast_wait(LAUNCH_WAIT_SECONDS=0.5, LAUNCH_MIN_TRY_SECONDS=0.1, LAUNCH_DRAIN_RETRY_SECONDS=0.1), \
                patch.object(app_module, "read_impact", self.draining(run.root, 0, 0.6)):
            self.launch(run, self.clients(run, refused))
        self.assert_gave_up(run)
        self.assertGreaterEqual(time.monotonic() - started, 0.9)
        said = run.stderr.getvalue()
        self.assertIn(f"{DRAINING} its running work (it allows up to 0.6 s)", said)
        self.assertIn(GAVE_UP, said)
        self.assertNotIn(RESTARTING, said)

    def test_off_a_terminal_each_phase_is_one_line_and_nothing_is_rewritten(self) -> None:
        run = self.normal()
        refused = [lambda _own, n=n: self.refusing_spawn(run, f"refused-{n}") for n in range(2)]
        with fast_wait():
            self.launch(run, self.clients(run, refused), stderr=io.StringIO())
        self.assert_clean_run(run)
        said = run.stderr.getvalue()
        self.assertNotIn("\r", said)
        self.assertNotIn("\x1b", said)
        lines = [line for line in said.splitlines() if "Hermes gateway" in line]
        self.assertEqual([line.split(" (")[0] for line in lines],
                         ["omh: " + CONNECTING, "omh: " + RESTARTING, "omh: " + OPENING])

    @staticmethod
    def drops(first_only: bool) -> Callable[[int, object], None]:
        """A session.create the gateway drops as a restart drops it: the child gone with `GATEWAY_NOT_READY_EXIT`."""
        def drop(number: int, _cancel: object) -> None:
            if number == 1 or not first_only:
                raise GatewayUnavailable("the gateway exited while session.create was waiting for an answer",
                                         returncode=GATEWAY_NOT_READY_EXIT)

        return drop

if __name__ == "__main__":
    unittest.main()
