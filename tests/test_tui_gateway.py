"""The OMH TUI's gateway child: spawn rules, and the real client against replayed Hermes frames."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import threading
import time
import unittest
from unittest.mock import patch

from _test_temp_root import make_test_tempdir
from _tui_gateway_replay import EXIT, HANG, Scenario, load_fixture, materialize, replay_env, spans
from omh.tui import gateway_contract as contract
from omh.tui.gateway import (
    GATEWAY_SCRIPT,
    PREVIEW_CHARS,
    STDERR_TAIL_LINES,
    Event,
    GatewayCallError,
    GatewayClient,
    GatewayExited,
    GatewayTimeout,
    GatewayUnavailable,
    ProtocolError,
    Response,
    ServerRequest,
    attach_refused,
    gateway_spawn,
)
from omh.tui.launch import FALLBACK_SENTINEL_ENV

LAUNCHER_ENV = {
    "HERMES_PYTHON": "/hermes/runtime/bin/python3",
    "HERMES_PYTHON_SRC_ROOT": "/hermes/agent",
    "HERMES_HOME": "/home/person/.hermes",
    "PATH": "/usr/bin",
    "OMH_HOME": "/home/person/.omh",
}
FAST_GRACE = 0.3
READY_TIMEOUT = 10.0


def _kind(item: object) -> str:
    if isinstance(item, Event):
        return item.type
    if isinstance(item, ServerRequest):
        return f"request:{item.method}"
    return type(item).__name__


def _recorded_kinds(rows: list[dict]) -> list[str]:
    """What `poll` should yield for these recorded rows when every call goes through `call()`."""
    kinds = []
    for row in rows:
        frame = row["frame"]
        if row["dir"] != "in" or "method" not in frame:
            continue
        kinds.append(frame["params"]["type"] if frame["method"] == "event" else f"request:{frame['method']}")
    return kinds


def _segment_rows(fixture: str, segment: str) -> list[dict]:
    (start, stop), = spans(fixture, segment)
    return load_fixture(fixture)[1][start:stop]


class GatewaySpawnTests(unittest.TestCase):
    def test_argv_runs_the_attach_script_on_the_launchers_interpreter(self) -> None:
        # The script attaches to Hermes' shared gateway, or runs `tui_gateway.entry` where this Hermes has no other way.
        spawn = gateway_spawn(LAUNCHER_ENV)
        self.assertEqual(spawn.argv, ("/hermes/runtime/bin/python3", str(GATEWAY_SCRIPT)))

    def test_cwd_is_the_launchers_working_directory_else_the_hermes_root(self) -> None:
        self.assertEqual(gateway_spawn({**LAUNCHER_ENV, "HERMES_CWD": "/work/project"}).cwd, "/work/project")
        self.assertEqual(gateway_spawn({**LAUNCHER_ENV, "HERMES_CWD": ""}).cwd, "/hermes/agent")
        self.assertEqual(gateway_spawn(LAUNCHER_ENV).cwd, "/hermes/agent")

    def test_import_path_is_the_hermes_root_then_the_launchers_path(self) -> None:
        handed_over = os.pathsep.join(["/runtime/site-packages", "/extra"])
        env = {**LAUNCHER_ENV, "OMH_TUI_GATEWAY_PYTHONPATH": handed_over, "PYTHONPATH": "/omh/should/not/leak"}
        spawn = gateway_spawn(env)
        self.assertEqual(spawn.env["PYTHONPATH"], os.pathsep.join(["/hermes/agent", handed_over]))
        self.assertEqual(spawn.env["HERMES_PYTHON_SRC_ROOT"], "/hermes/agent")

    def test_import_path_is_just_the_hermes_root_when_nothing_was_handed_over(self) -> None:
        self.assertEqual(gateway_spawn(LAUNCHER_ENV).env["PYTHONPATH"], "/hermes/agent")

    def test_herdrs_pane_id_stays_with_the_tui_and_the_rest_of_herdrs_environment_goes_on(self) -> None:
        # herdr's Hermes plugin, loaded where the gateway runs, would report a `herdr:hermes` session for the pane,
        # and herdr then refuses the TUI's own state reports (measured on herdr 0.9.5). The plugin needs the pane id;
        # herdr's CLI and skill need the rest (its socket, `HERDR_ENV=1`), as for herdr's own pane-less popups.
        herdr_env = {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": "/run/herdr.sock", "HERDR_WORKSPACE_ID": "w1",
                     "HERDR_TAB_ID": "w1:t1", "HERDR_BIN_PATH": "/opt/herdr"}
        child = gateway_spawn({**LAUNCHER_ENV, **herdr_env, "HERDR_PANE_ID": "w1:p1"}).env
        self.assertNotIn("HERDR_PANE_ID", child)
        self.assertEqual({name: child.get(name) for name in herdr_env}, herdr_env)

    def test_sidecar_attach_and_frontend_names_are_removed_and_the_rest_kept(self) -> None:
        env = {
            **LAUNCHER_ENV,
            "HERMES_TUI_GATEWAY_URL": "ws://127.0.0.1:9/attach",
            "HERMES_TUI_SIDECAR_URL": "ws://127.0.0.1:9/sidecar",
            "OMH_TUI_PYTHON": "/omh/venv/bin/python",
            "OMH_TUI_GATEWAY_PYTHONPATH": "/runtime/site-packages",
            FALLBACK_SENTINEL_ENV: "/tmp/omh-tui-x/fallback",
        }
        child = gateway_spawn(env).env
        for name in (
            "HERMES_TUI_GATEWAY_URL", "HERMES_TUI_SIDECAR_URL", "OMH_TUI_PYTHON", "OMH_TUI_GATEWAY_PYTHONPATH",
            FALLBACK_SENTINEL_ENV,
        ):
            with self.subTest(name=name):
                self.assertNotIn(name, child)
        for name in ("HERMES_HOME", "PATH", "OMH_HOME", "HERMES_PYTHON"):
            with self.subTest(name=name):
                self.assertEqual(child[name], LAUNCHER_ENV[name])

    def test_windows_system_variables_reach_the_child(self) -> None:
        # Without SYSTEMROOT a Windows child cannot load Winsock and `import asyncio` fails (WinError 10106).
        system = {"SYSTEMROOT": r"C:\Windows", "SystemDrive": "C:", "WINDIR": r"C:\Windows", "COMSPEC": r"C:\cmd.exe"}
        child = gateway_spawn({**LAUNCHER_ENV, **system}).env
        self.assertEqual({name: child.get(name) for name in system}, system)

    def test_the_callers_environment_is_not_mutated(self) -> None:
        env = {**LAUNCHER_ENV, "OMH_TUI_PYTHON": "/omh/venv/bin/python"}
        before = dict(env)
        gateway_spawn(env)
        self.assertEqual(env, before)

    def test_a_missing_interpreter_or_root_is_could_not_start(self) -> None:
        for name in ("HERMES_PYTHON", "HERMES_PYTHON_SRC_ROOT"):
            with self.subTest(name=name):
                env = {key: value for key, value in LAUNCHER_ENV.items() if key != name}
                with self.assertRaises(GatewayUnavailable) as raised:
                    gateway_spawn(env)
                self.assertIn(name, str(raised.exception))
                with self.assertRaises(GatewayUnavailable):
                    gateway_spawn({**LAUNCHER_ENV, name: ""})

    def test_an_attach_hand_off_is_refused(self) -> None:
        self.assertTrue(attach_refused({**LAUNCHER_ENV, contract.ATTACH_ENV: "ws://127.0.0.1:9/attach"}))
        self.assertFalse(attach_refused(LAUNCHER_ENV))
        self.assertFalse(attach_refused({**LAUNCHER_ENV, contract.ATTACH_ENV: ""}))
        self.assertFalse(attach_refused({**LAUNCHER_ENV, contract.ATTACH_ENV: " \t\n"}))


class FixtureTests(unittest.TestCase):
    def test_fixtures_name_their_hermes_commit_and_cover_every_row_with_segments(self) -> None:
        for name in ("session", "approval"):
            with self.subTest(fixture=name):
                header, rows = load_fixture(name)
                self.assertTrue(header["hermes_commit"].startswith(contract.DECLARED_AGAINST_HERMES))
                bounds = sorted(tuple(span) for span in header["segments"].values())
                self.assertEqual(bounds[0][0], 0)
                self.assertEqual(bounds[-1][1], len(rows))
                for (_start, stop), (next_start, _next_stop) in zip(bounds, bounds[1:]):
                    self.assertEqual(stop, next_start)

    def test_fixtures_carry_no_host_paths(self) -> None:
        for name in ("session", "approval"):
            with self.subTest(fixture=name):
                text = json.dumps(load_fixture(name)[1])
                for needle in ("/Users/", "/private/", "/tmp/", "/home/", ":\\\\"):
                    self.assertNotIn(needle, text)


class ReplayTestCase(unittest.TestCase):
    def make_client(self, scenario: Scenario) -> GatewayClient:
        root = Path(self.enterContext(make_test_tempdir("omh-tui-gateway-")))
        materialize(root, scenario)
        client = GatewayClient(gateway_spawn(replay_env(root)))
        self.addCleanup(client.close, FAST_GRACE)
        return client

    def started(self, scenario: Scenario) -> GatewayClient:
        client = self.make_client(scenario)
        client.start(ready_timeout=READY_TIMEOUT)
        return client

    def collect(self, client: GatewayClient, count: int, timeout: float = 10.0) -> list[object]:
        """Poll until `count` items arrived; a gateway exit before then fails with its stderr."""
        items: list[object] = []
        deadline = time.monotonic() + timeout
        while len(items) < count and time.monotonic() < deadline:
            for item in client.poll(timeout=0.2):
                if isinstance(item, GatewayExited):
                    self.fail(f"the fake gateway exited ({item.returncode}): {client.stderr_tail()}")
                items.append(item)
        self.assertEqual(len(items), count, f"items so far: {[_kind(item) for item in items]}")
        return items

    def create_session(self, client: GatewayClient) -> str:
        return client.call("session.create", {"cols": 100, "cwd": "/fixture/project"})["session_id"]


class GatewayStartupTests(ReplayTestCase):
    def test_start_returns_ready_after_declaring_server_requests(self) -> None:
        client = self.make_client(Scenario("session", spans("session", "startup")))
        ready = client.start(ready_timeout=READY_TIMEOUT)
        self.assertEqual(ready.type, "gateway.ready")
        self.assertEqual(ready.payload["skin"]["name"], "default")
        # The answer to client.capabilities, which the replay only sends after reading that call.
        self.assertEqual(sorted(client.capabilities["server_requests"]), sorted(contract.SERVER_REQUESTS))
        self.assertEqual(client.poll(), [])
        self.assertEqual(client.close(grace=5.0), 0)

    def test_session_create_answers_the_live_and_stored_session_ids(self) -> None:
        client = self.started(Scenario("session", spans("session", "startup", "create")))
        created = client.call("session.create", {"cols": 100, "cwd": "/fixture/project"})
        self.assertEqual(created["session_id"], "b6af062a")
        self.assertEqual(created["stored_session_id"], "20261013_115656_e709ea")

    def test_a_gateway_that_exits_before_ready_is_unavailable_with_its_stderr(self) -> None:
        crash = (
            "Traceback (most recent call last):",
            "ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'",
        )
        client = self.make_client(Scenario("session", stderr=crash, after=EXIT, exit_code=1))
        with self.assertRaises(GatewayUnavailable) as raised:
            client.start(ready_timeout=READY_TIMEOUT)
        self.assertIn("code 1", str(raised.exception))
        self.assertEqual(raised.exception.stderr_tail[-2:], crash)

    def test_a_silent_gateway_is_unavailable_and_reaped_when_ready_never_comes(self) -> None:
        # No frames at all: the fake says nothing and exits only when its stdin closes.
        client = self.make_client(Scenario("session"))
        with self.assertRaises(GatewayUnavailable) as raised:
            client.start(ready_timeout=0.5)
        self.assertIn("no gateway.ready within 0.5s", str(raised.exception))
        # start() already closed stdin and reaped the child; close() reports the same exit.
        self.assertEqual(client.close(grace=FAST_GRACE), 0)

    def test_a_cancel_ends_the_wait_for_ready_and_the_child_is_reaped_with_short_waits(self) -> None:
        # A respawn waits inside one loop step: the person's Ctrl+C must end it (`App._respawn_cancel`).
        from omh.tui.gateway import UNREADY_CLOSE_GRACE_SECONDS, GatewayCancelled

        client = self.make_client(Scenario("session"))  # silent until its stdin closes
        asked = []
        closes = []
        close = client.close

        def recorded(grace: float = 3.0, terminate_grace: float | None = None) -> int | None:
            closes.append((grace, terminate_grace))
            return close(grace, terminate_grace)

        client.close = recorded  # type: ignore[method-assign]
        started = time.monotonic()
        with self.assertRaises(GatewayCancelled):
            client.start(ready_timeout=30.0, cancel=lambda: asked.append(1) or len(asked) >= 3)
        self.assertLess(time.monotonic() - started, 5.0)  # three polls, not the 30 s
        self.assertEqual(closes[0], (UNREADY_CLOSE_GRACE_SECONDS, UNREADY_CLOSE_GRACE_SECONDS))
        self.assertEqual(close(FAST_GRACE), 0)  # reaped already

    def test_a_start_that_fails_closes_its_child_with_the_short_waits_too(self) -> None:
        from omh.tui.gateway import UNREADY_CLOSE_GRACE_SECONDS

        client = self.make_client(Scenario("session"))
        closes = []
        close = client.close
        def recorded(grace: float = 3.0, terminate_grace: float | None = None) -> int | None:
            closes.append((grace, terminate_grace))
            return close(grace, terminate_grace)

        client.close = recorded  # type: ignore[method-assign]
        with self.assertRaises(GatewayUnavailable):
            client.start(ready_timeout=0.3)
        self.assertEqual(closes[0], (UNREADY_CLOSE_GRACE_SECONDS, UNREADY_CLOSE_GRACE_SECONDS))

    def test_stderr_is_drained_while_starting_and_kept_to_a_bounded_tail(self) -> None:
        # Far more than a pipe buffer: an undrained stderr would block the fake before ready.
        flood = tuple(f"warning {index}" for index in range(5000))
        client = self.started(Scenario("session", spans("session", "startup"), stderr=flood))
        # Ready only proves the pipe never filled; the drain thread can still be a few
        # thousand lines behind the fake's last write, so wait for it to catch up.
        deadline = time.monotonic() + 10.0
        tail = client.stderr_tail()
        while tail[-1:] != ["warning 4999"] and time.monotonic() < deadline:
            time.sleep(0.02)
            tail = client.stderr_tail()
        self.assertEqual(len(tail), STDERR_TAIL_LINES)
        self.assertEqual(tail[-1], "warning 4999")

    def test_a_garbage_line_before_ready_stays_queued_as_a_bounded_protocol_error(self) -> None:
        garbage = "not json " + "x" * 400
        scenario = Scenario("session", spans("session", "startup"), inject=((0, garbage),))
        client = self.started(scenario)
        self.assertEqual(client.poll(), [ProtocolError(preview=garbage[:PREVIEW_CHARS])])


class GatewayTurnTests(ReplayTestCase):
    def test_a_plain_turn_streams_every_recorded_event_in_order(self) -> None:
        client = self.started(Scenario("session", spans("session", "startup", "create", "plain_turn")))
        session_id = self.create_session(client)
        submitted = client.call("prompt.submit", {"session_id": session_id, "text": "Reply with exactly the word: ok"})
        self.assertEqual(submitted, {"status": "streaming", "user_row_id": 1})
        expected = _recorded_kinds(_segment_rows("session", "plain_turn"))
        items = self.collect(client, len(expected))
        self.assertEqual([_kind(item) for item in items], expected)
        complete = next(item for item in items if _kind(item) == "message.complete")
        self.assertEqual(complete.session_id, session_id)
        self.assertEqual(complete.payload["status"], "complete")
        deltas = "".join(item.payload["text"] for item in items if _kind(item) == "message.delta")
        self.assertEqual(deltas.strip(), complete.payload["text"].strip())
        self.assertEqual(client.close(grace=5.0), 0)

    def test_a_clarify_request_is_answered_through_respond(self) -> None:
        client = self.started(Scenario("session", spans("session", "startup", "create", "clarify_turn")))
        session_id = self.create_session(client)
        client.call("prompt.submit", {"session_id": session_id, "text": "Ask me red or blue."})
        expected = _recorded_kinds(_segment_rows("session", "clarify_turn"))
        before = self.collect(client, expected.index("request:clarify") + 1)
        request = before[-1]
        self.assertEqual(request.id, "srq-c7e7e10e23ab")
        self.assertEqual(request.params["questions"][0]["qid"], "q0")
        # The replay checks this answer against the one real Hermes accepted.
        client.respond(request.id, {"result": {"answers": {"q0": "blue"}}})
        after = self.collect(client, len(expected) - len(before))
        complete = next(item for item in after if _kind(item) == "message.complete")
        self.assertEqual(complete.payload["text"], "blue")

    def test_a_manual_approval_is_answered_with_the_contracts_explicit_deny(self) -> None:
        client = self.started(Scenario("approval", spans("approval", "startup", "create", "approval_turn")))
        session_id = self.create_session(client)
        client.call("prompt.submit", {"session_id": session_id, "text": "Run rm -rf ./omh-m0-probe-dir"})
        expected = _recorded_kinds(_segment_rows("approval", "approval_turn"))
        before = self.collect(client, expected.index("request:approval") + 1)
        request = before[-1]
        self.assertEqual(request.params["command"], "rm -rf ./omh-m0-probe-dir")
        # The replay only continues if this frame equals the deny real Hermes received.
        client.respond(request.id, contract.server_request_treatment("approval").decline)
        after = self.collect(client, len(expected) - len(before))
        tool = next(item for item in after if _kind(item) == "tool.complete")
        self.assertEqual(tool.payload["result"]["status"], "blocked")
        self.assertEqual(client.close(grace=5.0), 0)

    def test_an_interrupt_ends_the_turn_and_events_sent_during_the_call_stay_queued(self) -> None:
        client = self.started(Scenario("session", spans("session", "startup", "create", "interrupted_turn")))
        session_id = self.create_session(client)
        client.call("prompt.submit", {"session_id": session_id, "text": "Count to 300."})
        expected = _recorded_kinds(_segment_rows("session", "interrupted_turn"))
        # The recording interrupted right after the first message.delta.
        self.collect(client, expected.index("message.delta") + 1)
        self.assertEqual(client.call("session.interrupt", {"session_id": session_id}), {"status": "interrupted"})
        # The gateway wrote a thinking.delta before answering; call() left it queued, in order.
        rest = self.collect(client, len(expected) - expected.index("message.delta") - 1)
        self.assertEqual(_kind(rest[0]), "thinking.delta")
        complete = next(item for item in rest if _kind(item) == "message.complete")
        self.assertEqual(complete.payload["status"], "interrupted")

    def test_a_request_answer_arrives_through_poll(self) -> None:
        client = self.started(Scenario("session", spans("session", "startup", "session_list")))
        request_id = client.request("session.list", {})
        (answer,) = self.collect(client, 1)
        self.assertIsInstance(answer, Response)
        self.assertEqual(answer.id, request_id)
        self.assertEqual(answer.result["sessions"][0]["id"], "20261013_115656_e709ea")


class GatewayForgetTests(unittest.TestCase):
    def test_an_answer_to_a_forgotten_request_is_dropped(self) -> None:
        client = GatewayClient(gateway_spawn(LAUNCHER_ENV))
        with patch.object(client, "_write"):  # nothing spawned: the request is only recorded as waited for
            kept, forgotten = client.request("session.list", {}), client.request("session.list", {})
        client.forget(forgotten)
        client._deliver(Response(forgotten, {"sessions": []}, None))  # what the reader thread does with a line
        client._deliver(Response(kept, {"sessions": []}, None))
        self.assertEqual([item.id for item in client.poll()], [kept])  # type: ignore[union-attr]


@unittest.skipIf(os.name == "nt", "select() waits on sockets only on Windows, and the TUI's loop is POSIX-only")
class GatewayWakeTests(ReplayTestCase):
    """`wake_fd` is readable while an item waits for `poll`, so the loop can sleep until the gateway has something."""

    def readable(self, fd: int, timeout: float = 0.0) -> bool:
        import select

        return bool(select.select([fd], [], [], timeout)[0])

    def test_an_item_for_poll_wakes_and_poll_empties_the_wake(self) -> None:
        client = self.started(Scenario("session", spans("session", "startup", "create", "session_list")))
        wake = client.wake_fd()
        self.assertFalse(self.readable(wake))
        client.call("session.create", {"cols": 100, "cwd": "/fixture/project"})
        self.assertFalse(self.readable(wake, 0.2))  # a blocking call's answer goes to its caller, not to poll
        client.request("session.list", {})
        self.assertTrue(self.readable(wake, 10.0))
        (answer,) = client.poll()
        self.assertIsInstance(answer, Response)
        self.assertFalse(self.readable(wake))

    def test_wake_from_another_thread_is_emptied_by_poll(self) -> None:
        client = self.started(Scenario("session", spans("session", "startup")))
        descriptor = client.wake_fd()
        self.assertFalse(self.readable(descriptor))
        waker = threading.Thread(target=client.wake)  # the HUD poller's thread, with a new snapshot
        waker.start()
        waker.join()
        self.assertTrue(self.readable(descriptor))
        self.assertEqual(client.poll(), [])
        self.assertFalse(self.readable(descriptor))

    def test_items_queued_before_the_first_ask_wake_at_once(self) -> None:
        garbage = "not json"
        client = self.started(Scenario("session", spans("session", "startup"), inject=((0, garbage),)))
        self.assertTrue(self.readable(client.wake_fd()))
        self.assertEqual(client.wake_fd(), client.wake_fd())


class GatewayErrorTests(ReplayTestCase):
    def test_an_unknown_method_reply_is_a_drift_call_error(self) -> None:
        # Hermes 6c61c3e27d's real answer: `session.info` is an event, not a method. The
        # contract declares no keys for it, so it goes out with none.
        client = self.started(Scenario("session", spans("session", "startup", "drift_reply")))
        with self.assertRaises(GatewayCallError) as raised:
            client.call("session.info", {})
        self.assertEqual(raised.exception.method, "session.info")
        self.assertEqual(raised.exception.code, contract.METHOD_NOT_FOUND)
        self.assertTrue(raised.exception.drift)
        self.assertIn("out of sync", raised.exception.message)

    def test_an_undeclared_param_is_refused_before_anything_is_sent(self) -> None:
        client = self.started(Scenario("session", spans("session", "startup", "session_list")))
        with self.assertRaises(ValueError):
            client.request("session.create", {"cols": 80, "title": "not declared"})
        with self.assertRaises(ValueError):
            client.call("session.create", {"cols": 80, "title": "not declared"})
        # The replay's next expected frame is session.list: had either frame gone out, it would
        # have reported a mismatch and exited instead of answering.
        self.assertIn("sessions", client.call("session.list", {}))

    def test_a_config_set_beyond_one_session_is_refused_before_anything_is_sent(self) -> None:
        client = self.started(Scenario("session", spans("session", "startup", "session_list")))
        for params in (
            {"key": "yolo", "value": "on"},  # no session: Hermes would flip the gateway process's switch
            {"key": "yolo", "value": "on", "session_id": ""},
            {"key": "yolo", "session_id": "b6af062a"},  # no value: a toggle
            {"key": "yolo", "value": "on", "session_id": "b6af062a", "scope": "global"},
            {"key": "approvals.mode", "value": "off", "session_id": "b6af062a"},
        ):
            with self.subTest(params=params), self.assertRaises(ValueError):
                client.request("config.set", params)
        self.assertIn("sessions", client.call("session.list", {}))

    def test_a_call_without_an_answer_times_out_and_the_client_stays_usable(self) -> None:
        (startup,) = spans("session", "startup")
        (listing_start, _stop), = spans("session", "session_list")
        scenario = Scenario("session", (startup, (listing_start, listing_start + 1)))
        client = self.started(scenario)
        with self.assertRaises(GatewayTimeout):
            client.call("session.list", {}, timeout=0.3)
        self.assertEqual(client.poll(), [])
        self.assertEqual(client.close(grace=5.0), 0)

    def test_a_cancel_ends_a_call_left_unanswered_and_a_later_call_still_times_out(self) -> None:
        # A respawn's resume waits this way (`App._respawn_cancel`): a real child that reads each call and answers none.
        from omh.tui.gateway import GatewayCancelled

        (startup,) = spans("session", "startup")
        (listing_start, _stop), = spans("session", "session_list")
        unanswered = (listing_start, listing_start + 1)  # the recorded session.list call: read, never answered
        client = self.started(Scenario("session", (startup, unanswered, unanswered, unanswered)))
        asked = []
        started = time.monotonic()
        with self.assertRaises(GatewayCancelled):
            client.call("session.list", {}, timeout=5.0, cancel=lambda: asked.append(1) or len(asked) >= 3)
        self.assertLess(time.monotonic() - started, 2.0)  # three polls, not the 5 s
        self.assertEqual(len(asked), 3)
        self.assertEqual(client._awaited, set())  # its answer, should it come, is dropped

        def broken() -> bool:
            raise OSError("the terminal read failed")

        with self.assertRaises(OSError):  # a cancel that fails ends the wait with its own error, nothing left behind
            client.call("session.list", {}, timeout=5.0, cancel=broken)
        self.assertEqual(client._awaited, set())
        with self.assertRaises(GatewayTimeout):
            client.call("session.list", {}, timeout=0.3)
        self.assertEqual(client._awaited, set())
        self.assertEqual(client.poll(), [])
        self.assertEqual(client.close(grace=5.0), 0)

    def test_lines_that_are_not_gateway_frames_are_protocol_errors(self) -> None:
        not_frames = (
            "{truncated",
            "[1, 2]",
            '{"jsonrpc": "2.0", "id": "srq-1", "result": {}}',  # an answer, but to a string id
            '{"jsonrpc": "2.0", "id": 9, "result": {}, "error": {}}',  # both answer shapes
        )
        scenario = Scenario("session", spans("session", "startup"), inject=tuple((3, line) for line in not_frames))
        client = self.started(scenario)
        items = self.collect(client, len(not_frames))
        self.assertEqual(items, [ProtocolError(preview=line) for line in not_frames])

    def test_a_gateway_exiting_mid_call_is_unavailable_and_its_exit_stays_queued(self) -> None:
        (startup,) = spans("session", "startup")
        (listing_start, _stop), = spans("session", "session_list")
        scenario = Scenario("session", (startup, (listing_start, listing_start + 1)), after=EXIT, exit_code=7)
        client = self.started(scenario)
        with self.assertRaises(GatewayUnavailable):
            client.call("session.list", {})
        self.assertEqual(client.poll(), [GatewayExited(returncode=7)])

    def test_respond_refuses_a_frame_that_is_not_one_result_or_error(self) -> None:
        client = self.started(Scenario("session", spans("session", "startup")))
        for frame in ({}, {"result": {}, "error": {}}, {"choice": "deny"}):
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                client.respond("srq-1", frame)


class GatewayCloseTests(ReplayTestCase):
    def test_a_gateway_ignoring_eof_is_terminated(self) -> None:
        client = self.started(Scenario("session", spans("session", "startup"), after=HANG))
        started = time.monotonic()
        code = client.close(grace=FAST_GRACE)
        self.assertEqual(code, 1 if os.name == "nt" else -signal.SIGTERM)
        self.assertLess(time.monotonic() - started, 5.0)

    @unittest.skipIf(os.name == "nt", "TerminateProcess cannot be ignored, so the kill step is unreachable")
    def test_a_gateway_ignoring_eof_and_sigterm_is_killed(self) -> None:
        scenario = Scenario("session", spans("session", "startup"), after=HANG, ignore_sigterm=True)
        client = self.started(scenario)
        started = time.monotonic()
        self.assertEqual(client.close(grace=FAST_GRACE), -signal.SIGKILL)
        self.assertLess(time.monotonic() - started, 5.0)

    @unittest.skipIf(os.name == "nt", "TerminateProcess cannot be ignored, so the kill step is unreachable")
    def test_the_wait_after_terminate_has_its_own_grace(self) -> None:
        scenario = Scenario("session", spans("session", "startup"), after=HANG, ignore_sigterm=True)
        client = self.started(scenario)
        started = time.monotonic()
        self.assertEqual(client.close(grace=0.1, terminate_grace=1.0), -signal.SIGKILL)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 1.0)
        self.assertLess(elapsed, 5.0)

    def test_close_is_idempotent_and_a_closed_client_refuses_to_send(self) -> None:
        client = self.started(Scenario("session", spans("session", "startup")))
        self.assertEqual(client.close(grace=5.0), 0)
        self.assertEqual(client.close(grace=5.0), 0)
        with self.assertRaises(GatewayUnavailable):
            client.request("session.list", {})

    def test_close_before_start_returns_nothing(self) -> None:
        self.assertIsNone(GatewayClient(gateway_spawn(LAUNCHER_ENV)).close())


if __name__ == "__main__":
    unittest.main()
