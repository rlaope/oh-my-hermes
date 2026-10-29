"""Tests for the opt-in omh-dap tool (`debug_python`), its session logic and DAP client."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from omh.plugin_bundle.omh import dap_client  # noqa: E402
from omh.plugin_bundle.omh.dap_client import DapError, encode, read_message  # noqa: E402
from omh.plugin_bundle.omh.dap_session import SessionManager  # noqa: E402
from omh.plugin_bundle.omh.tools import dap_tool  # noqa: E402
from omh.plugin_bundle.omh.tools.dap_tool import (  # noqa: E402
    OMH_DAP_DEBUG_PYTHON_SCHEMA,
    _dap_tools_enabled,
    debug_python_handler,
)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


class FakeClient:
    """Stands in for DapClient: answers requests from a table and plays scripted events."""

    def __init__(self, events=None, answers=None, fail=None):
        self.events = list(events or [])
        self.answers = answers or {}
        self.fail = fail or {}
        self.sent = []
        self.closed = 0
        self.output = ""
        self.is_alive = True
        self._seq = 0

    def send(self, command, arguments=None):
        self._seq += 1
        self.sent.append((command, arguments))
        return self._seq

    def wait_response(self, seq, timeout=None):
        command = self.sent[seq - 1][0]
        if command in self.fail:
            raise self.fail[command]
        answer = self.answers.get(command, {})
        return answer(self.sent[seq - 1][1]) if callable(answer) else answer

    def request(self, command, arguments=None, timeout=None):
        return self.wait_response(self.send(command, arguments), timeout)

    def wait_event(self, names, timeout):
        for index, event in enumerate(self.events):
            if event["event"] in names:
                return self.events.pop(index)
        raise DapError("timeout", "no event")

    def discard_events(self, names):
        pass

    def drain_output(self):
        text, self.output = self.output, ""
        return text

    def alive(self):
        return self.is_alive

    def stderr_tail(self, limit=2000):
        return "No module named debugpy"

    def close(self):
        self.closed += 1

    def commands(self):
        return [c for c, _ in self.sent]


def _stopped(reason="breakpoint", thread=1):
    return {"event": "stopped", "body": {"reason": reason, "threadId": thread}}


def _frames(root, count=1, name="total"):
    path = os.path.join(root, "src", "app", "cart.py")
    return {"stackFrames": [{"id": 100 + i, "name": f"{name}{i or ''}", "line": 9 + i, "source": {"path": path}}
                            for i in range(count)]}


class _Root(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        _write(os.path.join(self.root, "src", "app", "cart.py"), "def total(prices):\n    return sum(prices)\n")
        _write(os.path.join(self.root, "tests", "test_cart.py"), "def test_x():\n    assert True\n")
        self.python = sys.executable
        self.clients = []
        self.now = [0.0]
        self.next_client = None
        self.factory_call = None

        def factory(argv, cwd, env):
            self.factory_call = (argv, cwd, env)
            client = self.next_client or self.make_client()
            self.next_client = None
            self.clients.append(client)
            return client

        self.manager = SessionManager(factory, clock=lambda: self.now[0])
        patcher = mock.patch.object(dap_tool, "SESSIONS", self.manager)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(dap_tool, "_workspace_root", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_client(self, events=None, **answers):
        table = {"stackTrace": _frames(self.root), "setBreakpoints": lambda a: {
            "breakpoints": [{"line": b["line"], "verified": True} for b in a["breakpoints"]]}}
        table.update(answers)
        return FakeClient(events=[{"event": "initialized"}, _stopped()] if events is None else events, answers=table)

    def call(self, task="t1", **args):
        return json.loads(debug_python_handler(args, task_id=task))

    def launch(self, task="t1", **extra):
        args = {"action": "launch", "python": self.python, "args": ["-q", "tests"],
                "breakpoints": [{"path": os.path.join("src", "app", "cart.py"), "line": 9}]}
        args.update(extra)
        return self.call(task=task, **args)


class LaunchTests(_Root):
    def test_launch_runs_the_handshake_in_order_and_returns_the_stop(self):
        reply = self.launch()
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["stopped"], {"reason": "breakpoint", "function": "total",
                                            "path": os.path.join("src", "app", "cart.py"), "line": 9})
        self.assertEqual(reply["breakpoints"], [{"path": os.path.join("src", "app", "cart.py"), "line": 9,
                                                 "verified": True}])
        client = self.clients[0]
        self.assertEqual(client.commands()[:4], ["initialize", "launch", "setBreakpoints", "configurationDone"])
        launch_args = client.sent[1][1]
        self.assertEqual(launch_args["module"], "pytest")
        self.assertEqual(launch_args["python"], [self.python])
        self.assertEqual(launch_args["cwd"], self.root)
        self.assertEqual(launch_args["env"], {"PYTHONPATH": os.path.join(self.root, "src")})
        self.assertEqual(launch_args["console"], "internalConsole")
        argv, cwd, env = self.factory_call
        self.assertEqual(argv, [self.python, "-m", "debugpy.adapter"])
        self.assertEqual(cwd, self.root)
        self.assertEqual(env["PYTHONPATH"], os.path.join(self.root, "src"))
        self.assertNotIn("OPENROUTER_API_KEY", env)

    def test_program_is_confined_and_passed_as_a_path(self):
        reply = self.launch(program=os.path.join("src", "app", "cart.py"), breakpoints=[])
        self.assertTrue(reply["ok"], reply)
        launch_args = self.clients[0].sent[1][1]
        self.assertEqual(launch_args["program"], os.path.join(self.root, "src", "app", "cart.py"))
        self.assertNotIn("module", launch_args)

    def test_launch_that_exits_without_stopping_reports_the_exit(self):
        self.next_client = self.make_client(events=[{"event": "initialized"},
                                                    {"event": "exited", "body": {"exitCode": 0}},
                                                    {"event": "terminated"}])
        self.next_client.output = "1 passed\n"
        reply = self.launch()
        self.assertEqual(reply["exited"], True)
        self.assertEqual(reply["exit_code"], 0)
        self.assertIn("1 passed", reply["output_tail"])
        self.assertEqual(self.clients[0].closed, 1)
        self.assertEqual(self.call(action="inspect")["error"], "no_session")

    def test_second_launch_replaces_the_live_session(self):
        # Live smoke: every edit-then-relaunch cost launch -> session_active -> terminate -> launch.
        self.assertTrue(self.launch()["ok"])
        first = self.clients[0]
        reply = self.launch()
        self.assertTrue(reply["ok"])
        self.assertEqual(len(self.clients), 2)
        self.assertTrue(first.closed)
        self.assertIs(self.manager._sessions["t1"].client, self.clients[1])

    def test_reap_closes_idle_sessions_without_a_call(self):
        # Smoke runs left adapters and paused pytest alive: a finished chat never calls the tool again.
        self.assertTrue(self.launch(task="a")["ok"])
        self.assertTrue(self.launch(task="b")["ok"])
        self.now[0] += 30
        self.call(task="b", action="inspect")
        self.now[0] += 600
        self.assertEqual(self.manager.reap(), 1)
        self.assertTrue(self.clients[0].closed)
        self.assertFalse(self.clients[1].closed)
        self.assertEqual(list(self.manager._sessions), ["b"])
        self.assertTrue(self.manager._reaper.daemon)

    def test_stop_at_module_import_says_to_continue(self):
        self.next_client = self.make_client(stackTrace={"stackFrames": [
            {"id": 100, "name": "<module>", "line": 1,
             "source": {"path": os.path.join(self.root, "src", "app", "cart.py")}}]})
        reply = self.launch()
        self.assertIn("continue", reply["stopped"]["hint"])
        self.assertNotIn("hint", self.launch()["stopped"])

    def test_parallel_launches_on_one_task_start_one_adapter(self):
        # Adversarial case j: two launches racing on one task_id must not orphan an adapter.
        import threading

        gate, entered = threading.Event(), threading.Event()
        inner = self.manager.factory

        def slow_factory(argv, cwd, env):
            entered.set()
            gate.wait(5)
            return inner(argv, cwd, env)

        self.manager.factory = slow_factory
        replies = []
        first = threading.Thread(target=lambda: replies.append(self.launch()))
        first.start()
        self.assertTrue(entered.wait(5))
        second = self.launch()
        gate.set()
        first.join(5)
        self.assertEqual(second["error"], "session_active")
        self.assertTrue(replies[0]["ok"])
        self.assertEqual(len(self.clients), 1)
        self.assertEqual(self.manager._launching, set())

    def test_failed_launch_releases_the_reservation(self):
        self.next_client = self.make_client(events=[])
        reply = self.launch(timeout=5)
        self.assertFalse(reply["ok"])
        self.assertEqual(self.manager._launching, set())
        self.assertTrue(self.launch()["ok"])

    def test_sessions_are_keyed_by_task(self):
        self.assertTrue(self.launch(task="a")["ok"])
        self.assertTrue(self.launch(task="b")["ok"])
        self.assertEqual(len(self.clients), 2)
        self.assertTrue(self.call(task="a", action="terminate")["ok"])
        self.assertEqual(self.call(task="b", action="inspect")["ok"], True)

    def test_bad_arguments(self):
        cases = [
            {"python": ""},
            {"python": os.path.join(self.root, "missing-python")},
            {"module": "pytest; rm -rf /"},
            {"module": "pytest", "program": "x.py"},
            {"args": "-q"},
            {"breakpoints": [{"path": os.path.join("src", "app", "cart.py"), "line": 0}]},
            {"breakpoints": "src/app/cart.py:9"},
            {"timeout": 0},
            {"timeout": 181},
            {"timeout": True},
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                self.assertEqual(self.launch(**extra)["error"], "invalid_argument")
        self.assertEqual(self.clients, [])
        self.assertEqual(self.call(action="nope")["error"], "invalid_argument")

    def test_adapter_unavailable_when_the_adapter_exits_at_start(self):
        client = self.make_client()
        client.fail = {"initialize": DapError("adapter_exited", "eof")}
        client.is_alive = False
        self.next_client = client
        reply = self.launch()
        self.assertEqual(reply["error"], "adapter_unavailable")
        self.assertIn("-m pip install debugpy", reply["hint"])
        self.assertIn("No module named debugpy", reply["stderr_tail"])
        self.assertEqual(client.closed, 1)
        self.assertTrue(self.launch()["ok"])  # nothing left behind

    def test_adapter_unavailable_when_spawn_fails(self):
        def factory(argv, cwd, env):
            raise DapError("adapter_unavailable", "cannot start")

        self.manager.factory = factory
        reply = self.launch()
        self.assertEqual(reply["error"], "adapter_unavailable")
        self.assertIn("pip install debugpy", reply["hint"])

    def test_adapter_error_on_launch_carries_the_message(self):
        client = self.make_client()
        client.fail = {"launch": DapError("adapter_error", "No module named pytest")}
        self.next_client = client
        reply = self.launch()
        self.assertEqual(reply["error"], "adapter_error")
        self.assertIn("No module named pytest", reply["hint"])
        self.assertEqual(client.closed, 1)

    def test_launch_timeout_keeps_the_session_for_continue(self):
        self.next_client = self.make_client(events=[{"event": "initialized"}])
        reply = self.launch(timeout=1)
        self.assertEqual(reply["error"], "timeout")
        self.clients[0].events.append(_stopped())
        reply = self.call(action="continue")
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["stopped"]["line"], 9)


class PathConfinementTests(_Root):
    def test_outside_paths_are_scope_mismatch(self):
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        _write(os.path.join(outside, "evil.py"), "x = 1\n")
        for path in (os.path.join("..", os.path.basename(outside), "evil.py"), os.path.join(outside, "evil.py")):
            with self.subTest(path=path):
                reply = self.launch(breakpoints=[{"path": path, "line": 1}])
                self.assertEqual(reply["error"], "scope_mismatch")
        self.assertEqual(self.launch(program=os.path.join(outside, "evil.py"), breakpoints=[])["error"],
                         "scope_mismatch")
        self.assertEqual(self.clients, [])

    @unittest.skipIf(not hasattr(os, "symlink"), "no symlink support")
    def test_symlink_escape_is_refused(self):
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        _write(os.path.join(outside, "evil.py"), "x = 1\n")
        try:
            os.symlink(os.path.join(outside, "evil.py"), os.path.join(self.root, "link.py"))
        except OSError:
            self.skipTest("symlinks not permitted")
        self.assertEqual(self.launch(breakpoints=[{"path": "link.py", "line": 1}])["error"], "scope_mismatch")
        self.assertTrue(self.launch()["ok"])
        self.assertEqual(self.call(action="set_breakpoints", path="link.py", lines=[1])["error"], "scope_mismatch")

    def test_missing_file_is_invalid_argument(self):
        self.assertEqual(self.launch(breakpoints=[{"path": "nope.py", "line": 1}])["error"], "invalid_argument")


class StoppedActionTests(_Root):
    def setUp(self):
        super().setUp()
        self.assertTrue(self.launch()["ok"])
        self.client = self.clients[0]

    def test_inspect_defaults_to_frame_zero_and_caps(self):
        self.client.answers["stackTrace"] = _frames(self.root, count=12)
        self.client.answers["scopes"] = {"scopes": [{"name": "Globals", "variablesReference": 2},
                                                    {"name": "Locals", "variablesReference": 1}]}
        variables = [{"name": "special variables", "value": ""}]
        variables += [{"name": f"v{i}", "value": "x" * 500} for i in range(45)]
        self.client.answers["variables"] = lambda a: {"variables": variables if a["variablesReference"] == 1 else []}
        reply = self.call(action="inspect")
        self.assertEqual(len(reply["frames"]), 8)
        self.assertEqual(reply["frames"][0], {"function": "total", "path": os.path.join("src", "app", "cart.py"),
                                              "line": 9})
        self.assertEqual(len(reply["locals"]), 40)
        self.assertNotIn("special variables", reply["locals"])
        self.assertEqual(reply["locals_omitted"], 5)
        self.assertTrue(all(len(v) <= 200 for v in reply["locals"].values()))
        scopes = [a for c, a in self.client.sent if c == "scopes"]
        self.assertEqual(scopes[-1], {"frameId": 100})

    def test_inspect_selects_a_frame_and_rejects_a_missing_one(self):
        self.client.answers["stackTrace"] = _frames(self.root, count=3)
        self.client.answers["scopes"] = {"scopes": [{"name": "Locals", "variablesReference": 7}]}
        self.client.answers["variables"] = {"variables": [{"name": "cart", "value": "[1, 2]"}]}
        reply = self.call(action="inspect", frame=2)
        self.assertEqual(reply["locals"], {"cart": "[1, 2]"})
        self.assertEqual([a for c, a in self.client.sent if c == "scopes"][-1], {"frameId": 102})
        self.assertEqual(self.call(action="inspect", frame=5)["error"], "invalid_argument")
        self.assertEqual(self.call(action="inspect", frame=-1)["error"], "invalid_argument")

    def test_evaluate_uses_the_watch_context_and_caps(self):
        self.client.answers["evaluate"] = lambda a: {"result": "r" * 5000, "type": "str"}
        reply = self.call(action="evaluate", expression="add.__defaults__")
        self.assertEqual(len(reply["result"]), 2000)
        self.assertEqual([a for c, a in self.client.sent if c == "evaluate"][-1],
                         {"expression": "add.__defaults__", "frameId": 100, "context": "watch"})
        self.assertEqual(self.call(action="evaluate", expression=" ")["error"], "invalid_argument")

    def test_evaluate_error_is_adapter_error_and_keeps_the_session(self):
        self.client.fail["evaluate"] = DapError("adapter_error", "NameError: name 'nope' is not defined")
        reply = self.call(action="evaluate", expression="nope")
        self.assertEqual(reply["error"], "adapter_error")
        self.assertIn("NameError", reply["hint"])
        self.assertTrue(self.call(action="inspect")["ok"])

    def test_statement_in_evaluate_says_how_to_read_a_module_value(self):
        # Live smoke: qwen sent `import benchapp.pricing; benchapp.pricing.X` five times on a bare SyntaxError.
        self.client.fail["evaluate"] = DapError("adapter_error", "SyntaxError: invalid syntax (<string>, line 1)")
        reply = self.call(action="evaluate", expression="import pkg.mod; pkg.mod.X")
        self.assertEqual(reply["error"], "not_an_expression")
        self.assertIn("__import__('pkg.mod', fromlist=['X']).X", reply["hint"])
        self.assertTrue(self.call(action="inspect")["ok"])

    def test_evaluate_budget_per_stop_resets_on_a_new_stop_and_caps_the_session(self):
        # Live smoke: qwen evaluated `build_order(...).lines[i]` for i = 0..541 at one stop (27.4M tokens).
        from omh.plugin_bundle.omh import dap_session

        self.client.answers["evaluate"] = lambda a: {"result": "1", "type": "int"}
        for i in range(dap_session.EVALS_PER_STOP):
            self.assertTrue(self.call(action="evaluate", expression=f"xs[{i}]")["ok"])
        over = self.call(action="evaluate", expression="xs[99]")
        self.assertEqual(over["error"], "evaluate_budget")
        self.assertIn("patch", over["hint"])
        self.assertTrue(self.call(action="inspect")["ok"])
        sent = len([c for c, _ in self.client.sent if c == "evaluate"])
        self.assertEqual(sent, dap_session.EVALS_PER_STOP)
        session = self.manager._sessions["t1"]
        session.evals_at_stop = 0  # what a new `stopped` event does
        session.evals_total = dap_session.EVALS_PER_SESSION
        self.assertEqual(self.call(action="evaluate", expression="y")["error"], "evaluate_budget")

    def test_set_breakpoints_replaces_and_reports_verified(self):
        reply = self.call(action="set_breakpoints", path=os.path.join("src", "app", "cart.py"), lines=[1, 2],
                          condition="p > 1")
        self.assertEqual(reply["breakpoints"], [{"line": 1, "verified": True}, {"line": 2, "verified": True}])
        sent = [a for c, a in self.client.sent if c == "setBreakpoints"][-1]
        self.assertEqual(sent["breakpoints"], [{"line": 1, "condition": "p > 1"}, {"line": 2, "condition": "p > 1"}])
        self.assertEqual(self.call(action="set_breakpoints", path=os.path.join("src", "app", "cart.py"), lines="1")["error"],
                         "invalid_argument")

    def test_step_actions_send_their_dap_command(self):
        for action, command in (("step_over", "next"), ("step_in", "stepIn"), ("step_out", "stepOut"),
                                ("continue", "continue")):
            with self.subTest(action=action):
                self.client.events.append(_stopped(reason="step"))
                reply = self.call(action=action)
                self.assertEqual(reply["stopped"]["reason"], "step")
                self.assertEqual(self.client.sent[-2], (command, {"threadId": 1}))

    def test_continue_to_exit_ends_the_session(self):
        self.client.events += [{"event": "exited", "body": {"exitCode": 1}}, {"event": "terminated"}]
        self.client.output = "FAILED tests/test_cart.py\n"
        reply = self.call(action="continue")
        self.assertEqual((reply["exited"], reply["exit_code"]), (True, 1))
        self.assertIn("FAILED", reply["output_tail"])
        self.assertEqual(self.client.closed, 1)
        self.assertEqual(self.call(action="continue")["error"], "no_session")

    def test_not_stopped_while_running(self):
        reply = self.call(action="continue", timeout=1)  # no event scripted: still running
        self.assertEqual(reply["error"], "timeout")
        for action, extra in (("inspect", {}), ("evaluate", {"expression": "1"}), ("step_over", {}),
                              ("set_breakpoints", {"path": os.path.join("src", "app", "cart.py"), "lines": [1]})):
            with self.subTest(action=action):
                self.assertEqual(self.call(action=action, **extra)["error"], "not_stopped")

    def test_terminate_returns_the_output_tail(self):
        self.client.output = "x" * 3000
        reply = self.call(action="terminate")
        self.assertEqual(reply["terminated"], True)
        self.assertEqual(len(reply["output_tail"]), 2000)
        self.assertEqual(self.client.closed, 1)
        self.assertEqual(self.call(action="terminate")["error"], "no_session")

    def test_output_ring_is_capped(self):
        session = self.manager._sessions["t1"]
        for _ in range(3):
            self.client.output = "y" * 40000
            session.collect_output()
        self.assertEqual(len(session.output), 64 * 1024)

    def test_idle_timeout_closes_the_session_on_the_next_call(self):
        self.now[0] += 601
        reply = self.call(action="inspect")
        self.assertEqual(reply["error"], "no_session")
        self.assertIn("idle", reply["hint"])
        self.assertEqual(self.client.closed, 1)
        self.assertTrue(self.launch()["ok"])

    def test_activity_resets_the_idle_clock(self):
        self.now[0] += 500
        self.assertTrue(self.call(action="inspect")["ok"])
        self.now[0] += 500
        self.assertTrue(self.call(action="inspect")["ok"])

    def test_adapter_death_mid_session_is_adapter_error(self):
        self.client.fail["stackTrace"] = DapError("adapter_exited", "eof")
        self.client.is_alive = False
        reply = self.call(action="inspect")
        self.assertEqual(reply["error"], "adapter_error")
        self.assertEqual(self.client.closed, 1)
        self.assertEqual(self.call(action="inspect")["error"], "no_session")

    def test_no_session(self):
        for action in ("inspect", "evaluate", "continue", "step_over", "set_breakpoints", "terminate"):
            with self.subTest(action=action):
                self.assertEqual(self.call(task="other", action=action, expression="1")["error"], "no_session")


class CheckFnGatingTests(unittest.TestCase):
    def setUp(self):
        old = os.environ.pop("OMH_DAP_TOOLS", None)
        if old is not None:
            self.addCleanup(os.environ.__setitem__, "OMH_DAP_TOOLS", old)
        self.addCleanup(os.environ.pop, "OMH_DAP_TOOLS", None)
        self._profile(None)

    def _profile(self, text):
        from omh.plugin_bundle.omh import runtime_paths

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        if text is not None:
            (home / "config.yaml").write_text(text, encoding="utf-8")
        patcher = mock.patch.object(runtime_paths, "default_hermes_home", return_value=home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_env(self):
        self.assertFalse(_dap_tools_enabled())
        for value in ("1", "true", "On", "yes"):
            os.environ["OMH_DAP_TOOLS"] = value
            self.assertTrue(_dap_tools_enabled(), value)
        for value in ("0", "false", "", "maybe"):
            os.environ["OMH_DAP_TOOLS"] = value
            self.assertFalse(_dap_tools_enabled(), value)

    def test_profile_setting(self):
        self._profile("plugins:\n  entries:\n    omh:\n      settings:\n        dap_tools: true\n")
        self.assertTrue(_dap_tools_enabled())
        self._profile("plugins:\n  entries:\n    omh:\n      settings:\n        dap_tools: off\n")
        self.assertFalse(_dap_tools_enabled())
        self._profile("plugins:\n  entries:\n    omh:\n      settings:\n        lsp_tools: true\n")
        self.assertFalse(_dap_tools_enabled())

    def test_registration_uses_dedicated_toolset_and_check_fn(self):
        from omh.plugin_bundle.omh import register

        recorded = {}

        class Ctx:
            def register_tool(self, name, toolset, schema, handler, **kwargs):
                recorded[name] = (toolset, schema, handler, kwargs)

            def register_hook(self, name, handler):
                pass

        register(Ctx())
        toolset, schema, _handler, kwargs = recorded["debug_python"]
        self.assertEqual(toolset, "omh-dap")
        self.assertEqual(schema, OMH_DAP_DEBUG_PYTHON_SCHEMA)
        self.assertIs(kwargs.get("check_fn"), _dap_tools_enabled)

    def test_schema_documents_that_evaluate_runs_code(self):
        self.assertIn("evaluate runs code", OMH_DAP_DEBUG_PYTHON_SCHEMA["description"])


class FramingTests(unittest.TestCase):
    def test_round_trip_and_utf8_length(self):
        message = {"type": "event", "event": "output", "body": {"output": "한글 ✓\n"}}
        data = encode(message)
        header, body = data.split(b"\r\n\r\n", 1)
        self.assertEqual(int(header.split(b":")[1]), len(body))
        stream = io.BytesIO(data + encode({"type": "response", "request_seq": 1}))
        self.assertEqual(read_message(stream), message)
        self.assertEqual(read_message(stream), {"type": "response", "request_seq": 1})
        self.assertIsNone(read_message(stream))

    def test_truncated_body_is_eof(self):
        self.assertIsNone(read_message(io.BytesIO(b"Content-Length: 50\r\n\r\n{}")))


class ClientQueueTests(unittest.TestCase):
    """DapClient's matching and buffering, without a process."""

    def _client(self, messages):
        client = dap_client.DapClient.__new__(dap_client.DapClient)
        client.request_timeout = 1.0
        client._inbox = dap_client.queue.Queue()
        for message in messages:
            client._inbox.put(message)
        client._responses, client._events = {}, []
        client._output, client._output_size = dap_client.deque(), 0
        client._eof = False
        return client

    def test_response_matched_by_request_seq_and_early_event_kept(self):
        client = self._client([
            {"type": "event", "event": "stopped", "body": {"threadId": 3}},
            {"type": "response", "request_seq": 2, "success": True, "body": {"b": 2}},
            {"type": "event", "event": "output", "body": {"output": "hi\n"}},
            {"type": "response", "request_seq": 1, "success": True, "body": {"b": 1}},
        ])
        self.assertEqual(client.wait_response(1), {"b": 1})
        self.assertEqual(client.wait_response(2), {"b": 2})
        self.assertEqual(client.wait_event(("stopped",), 0.1)["body"], {"threadId": 3})
        self.assertEqual(client.drain_output(), "hi\n")

    def test_error_response_and_timeout_and_eof(self):
        client = self._client([{"type": "response", "request_seq": 1, "success": False, "message": "bad"}])
        with self.assertRaises(DapError) as caught:
            client.wait_response(1)
        self.assertEqual((caught.exception.code, caught.exception.message), ("adapter_error", "bad"))
        with self.assertRaises(DapError) as caught:
            client.wait_event(("stopped",), 0.05)
        self.assertEqual(caught.exception.code, "timeout")
        client._inbox.put(dap_client._EOF)
        with self.assertRaises(DapError) as caught:
            client.wait_response(9)
        self.assertEqual(caught.exception.code, "adapter_exited")

    def test_reverse_request_gets_an_error_response(self):
        client = self._client([])
        written = []
        client._write = written.append
        client._refuse_reverse_request({"type": "request", "seq": 7, "command": "runInTerminal"})
        self.assertEqual(written[0]["request_seq"], 7)
        self.assertFalse(written[0]["success"])
        self.assertEqual(written[0]["command"], "runInTerminal")

    def test_output_flood_while_running_stays_bounded(self):
        # Adversarial case j: a program printing forever must not grow the host between drains.
        chunk = "F" * 65536 + "\n"
        client = self._client([{"type": "event", "event": "output", "body": {"output": chunk}}] * 200)
        client._drain_nowait()
        held = sum(len(part) for part in client._output)
        self.assertLessEqual(held, dap_client._OUTPUT_RING + len(chunk))
        self.assertLessEqual(len(client.drain_output()), dap_client._OUTPUT_RING)
        self.assertEqual((len(client._output), client._output_size), (0, 0))

    def test_real_process_close_is_idempotent(self):
        script = "import sys; sys.stdin.read()"
        client = dap_client.DapClient([sys.executable, "-c", script], os.getcwd(), dict(os.environ))
        client.close()
        client.close()
        self.assertFalse(client.alive())


_CART = (
    "def add(item, items=[]):\n"
    "    items.append(item)\n"
    "    return items\n"
    "\n"
    "def total(prices):\n"
    "    cart = []\n"
    "    for p in prices:\n"
    "        cart = add(p)\n"
    "    return sum(cart)\n"
)
_TEST = "from app.cart import total\n\ndef test_total_twice():\n    assert total([1, 2]) == 3\n    assert total([5]) == 5\n"


@unittest.skipIf(importlib.util.find_spec("debugpy") is None, "debugpy is not importable by sys.executable")
class RealDebugpyIntegrationTests(unittest.TestCase):
    """The probe scenario against a live debugpy adapter (mutable default argument)."""

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        _write(os.path.join(self.root, "src", "app", "__init__.py"), "")
        _write(os.path.join(self.root, "src", "app", "cart.py"), _CART)
        _write(os.path.join(self.root, "tests", "test_cart.py"), _TEST)
        self.manager = SessionManager(dap_tool._new_client)
        for target, value in ((dap_tool, "SESSIONS"), (dap_tool, "_workspace_root")):
            patcher = mock.patch.object(target, value, self.manager if value == "SESSIONS" else (lambda _t: self.root))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(lambda: [s.close() for s in list(self.manager._sessions.values())])

    def call(self, **args):
        return json.loads(debug_python_handler(args, task_id="it"))

    def test_probe_scenario(self):
        cart = os.path.join("src", "app", "cart.py")
        reply = self.call(action="launch", python=sys.executable, args=["-q", "-x", "tests"],
                          breakpoints=[{"path": cart, "line": 9}], timeout=120)
        self.assertTrue(reply.get("ok"), reply)
        self.assertEqual(reply["stopped"], {"reason": "breakpoint", "function": "total", "path": cart, "line": 9})
        self.assertEqual(reply["breakpoints"], [{"path": cart, "line": 9, "verified": True}])
        inspect = self.call(action="inspect")
        self.assertEqual(inspect["locals"]["cart"], "[1, 2]")
        self.assertEqual(inspect["frames"][0]["path"], cart)
        self.assertEqual(self.call(action="evaluate", expression="add.__defaults__")["result"], "([1, 2],)")
        second = self.call(action="continue")
        self.assertEqual(second["stopped"]["line"], 9)
        self.assertEqual(self.call(action="evaluate", expression="cart")["result"], "[1, 2, 5]")
        self.assertTrue(self.call(action="set_breakpoints", path=cart, lines=[])["ok"])
        done = self.call(action="continue")
        self.assertEqual((done.get("exited"), done.get("exit_code")), (True, 1), done)
        self.assertIn("assert 8 == 5", done["output_tail"])
        self.assertEqual(self.call(action="terminate")["error"], "no_session")

    def test_terminate_mid_session(self):
        cart = os.path.join("src", "app", "cart.py")
        reply = self.call(action="launch", python=sys.executable, args=["-q", "tests"],
                          breakpoints=[{"path": cart, "line": 9}], timeout=120)
        self.assertTrue(reply.get("ok"), reply)
        self.assertTrue(self.call(action="terminate")["terminated"])
        self.assertEqual(self.manager._sessions, {})


if __name__ == "__main__":
    unittest.main()
