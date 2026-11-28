"""Settings › Computer (BOUNDARY rule 52): Hermes' computer-use readiness read through its own
`computer-use permissions status --json`, each bot's `computer_use` switch read from its gateway's `profiles.describe`,
and the four fixed argvs a press runs. A chat step of the tool names its action and app and never what the bot types.
Every test uses a temp Hermes home, a fake runner and a fake gateway: no real profile, no real `hermes`."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402

BOT = "demo-bot"
FIXTURE = HERE / "fixtures" / "computer_use_status_missing.json"


def payload(**over) -> str:
    base = json.loads(FIXTURE.read_text(encoding="utf-8"))
    base.update(over)
    return json.dumps(base, indent=2, sort_keys=True)


class Argv(unittest.TestCase):
    def test_four_fixed_argvs(self):
        self.assertEqual(ob.computer_argv("/h", "status"),
                         ["/h", "-p", "default", "computer-use", "permissions", "status", "--json"])
        self.assertEqual(ob.computer_argv("/h", "install"), ["/h", "-p", "default", "computer-use", "install"])
        self.assertEqual(ob.computer_argv("/h", "grant"), ["/h", "-p", "default", "computer-use", "permissions", "grant"])
        self.assertEqual(ob.computer_argv("/h", "enable", BOT), ["/h", "-p", BOT, "tools", "enable", "computer_use"])
        self.assertEqual(ob.computer_argv("/h", "disable", BOT), ["/h", "-p", BOT, "tools", "disable", "computer_use"])

    def test_refuses_any_other_verb_or_profile(self):
        for verb in ("doctor", "post-setup", "list", "status --json", ""):
            with self.assertRaises(ValueError):
                ob.computer_argv("/h", verb)
        for bad in ("-h", "--help", "x;rm", "a b", "$(id)", "Bad.Name", "../x", "", None, 7):
            with self.assertRaises(ValueError):
                ob.computer_argv("/h", "enable", bad)
        # the driver is the whole computer's: its commands never run through another profile
        for verb in ("status", "install", "grant"):
            with self.assertRaises(ValueError):
                ob.computer_argv("/h", verb, BOT)

    def test_each_runs_through_the_shared_runner(self):
        seen = []
        with mock.patch.object(ob, "_run_hermes_argv", lambda argv, home, timeout: seen.append((argv, home, timeout)) or (0, "")):
            ob.run_hermes_computer("/h", "enable", BOT, Path("/root"), 60.0)
        self.assertEqual(seen, [(["/h", "-p", BOT, "tools", "enable", "computer_use"], Path("/root"), 60.0)])


class Payload(unittest.TestCase):
    def test_the_real_payload_of_a_computer_without_the_driver(self):
        # captured from `hermes -p default computer-use permissions status --json` (exit 1) on macOS
        got = ob.computer_status(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(got, {"platform": "darwin", "platform_supported": True, "installed": False, "version": None,
                               "ready": None, "can_grant": True, "checks": [], "error": None,
                               "accessibility": None, "screen_recording": None})

    def test_a_warning_before_the_json_and_fields_checked_and_clipped(self):
        out = "⚠ Hermes has an update available\n" + payload(
            installed=True, version="cua-driver 0.4.2\x1b[31m", ready=False, accessibility=True, screen_recording=False,
            checks=[{"label": "Screen Recording", "status": "fail", "message": "Not granted‮" + "x" * 400}] * 40,
            source={"path": "/private"}, platform="darwin; rm", can_grant="yes", error=7)
        got = ob.computer_status(out)
        self.assertEqual(got["version"], "cua-driver 0.4.2")
        self.assertEqual((got["ready"], got["accessibility"], got["screen_recording"]), (False, True, False))
        self.assertEqual(len(got["checks"]), ob.COMPUTER_CHECKS)
        self.assertEqual(got["checks"][0]["label"], "Screen Recording")
        self.assertLessEqual(len(got["checks"][0]["message"]), 300)
        self.assertNotIn("‮", got["checks"][0]["message"])
        self.assertEqual((got["platform"], got["can_grant"], got["error"]), ("", False, None))
        self.assertNotIn("source", got)

    def test_a_json_warning_line_before_the_payload_is_passed_over(self):
        out = '{"level": "warning", "message": "update available"}\n[1]\n' + payload(installed=True, ready=True)
        got = ob.computer_status(out)
        self.assertIsNotNone(got)
        self.assertTrue(got["installed"])

    def test_no_payload_is_none(self):
        for out in ("", "Computer Use: no backend\n", "{not json", "[1, 2]\n", '{"platform": "darwin"}\n'):
            self.assertIsNone(ob.computer_status(out), out)

    def test_another_backend_reads_as_hermes_reports_it(self):
        got = ob.computer_status(payload(installed=True, ready=True, can_grant=False,
                                         version="Remote VM (computer_use.backend: vm)"))
        self.assertEqual((got["installed"], got["ready"], got["can_grant"]), (True, True, False))
        self.assertIn("computer_use.backend", got["version"])

    def test_the_switch_from_profiles_describe(self):
        row = lambda on: {"toolsets": [{"name": "web", "enabled": True}, {"name": "computer_use", "enabled": on}],
                          "soul": "my persona"}
        self.assertEqual(ob.computer_switch(row(True)), "on")
        self.assertEqual(ob.computer_switch(row(False)), "off")
        for bad in ({"toolsets": [{"name": "web", "enabled": True}]}, {"toolsets": [{"name": "computer_use", "enabled": "yes"}]},
                    {}, None, "x", {"toolsets": "computer_use"}):
            self.assertEqual(ob.computer_switch(bad), "unknown", bad)

    def test_pinned_by_the_environment(self):
        self.assertTrue(ob.computer_pinned({"HERMES_TUI_TOOLSETS": "web,terminal"}))
        self.assertFalse(ob.computer_pinned({"HERMES_TUI_TOOLSETS": "  "}))
        self.assertFalse(ob.computer_pinned({}))


class Gateway:
    """A bot's gateway client: `profiles.describe` answers from `self.on` (None: it does not list the toolset)."""

    def __init__(self, on: bool | None = True, error: Exception | None = None):
        self.on, self.error, self.calls = on, error, []

    async def rpc(self, method: str, **params):
        self.calls.append((method, params))
        if self.error is not None:
            raise self.error
        rows = [] if self.on is None else [{"name": "computer_use", "label": "Computer Use", "enabled": self.on}]
        return {"name": params.get("name"), "soul": "persona text", "toolsets": rows}


class Ops(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "hermes"
        for path in (self.home / "config.yaml", self.home / "profiles" / BOT / "config.yaml"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("model: x\n", encoding="utf-8")
        self.bridge = ob.Bridge(token="t", hermes_home=self.home)
        self.gw = Gateway(on=False)
        conn = ob.Conn(next(b for b in ob.discover_bots(self.home) if b["name"] == BOT))
        conn.client = self.gw
        self.bridge.conns[BOT] = conn
        self.runs: list[tuple] = []
        self.effect = lambda verb, bot: (0, "")
        self._run = mock.patch.object(ob, "run_hermes_computer", self.fake)
        self._path = mock.patch.object(ob, "hermes_path", lambda *a, **k: "/stub/hermes")
        self._env = mock.patch.dict(os.environ, {"HERMES_TUI_TOOLSETS": ""})
        for m in (self._run, self._path, self._env):
            m.start()

    def tearDown(self) -> None:
        for m in (self._env, self._path, self._run):
            m.stop()
        self._tmp.cleanup()

    def fake(self, hermes, verb, bot, home, timeout):
        self.runs.append((hermes, verb, bot, Path(home), timeout))
        return self.effect(verb, bot)

    def op(self, name: str, **p):
        return asyncio.run(getattr(self.bridge, f"op_computer_{name}")({"bot": BOT, **p}))

    def refused(self, name: str, code: str, **p) -> ob.BridgeError:
        with self.assertRaises(ob.BridgeError) as cm:
            self.op(name, **p)
        self.assertEqual(cm.exception.code, code, cm.exception.message)
        return cm.exception

    def test_status_reads_the_payload_even_when_hermes_exits_1(self):
        self.effect = lambda verb, bot: (1, FIXTURE.read_text(encoding="utf-8"))
        got = asyncio.run(self.bridge.op_computer_status({}))
        self.assertTrue(got["read"])
        self.assertFalse(got["installed"])
        self.assertFalse(got["pinned"])
        self.assertEqual(self.runs, [("/stub/hermes", "status", "default", self.home, ob.COMPUTER_TIMEOUT["status"])])

    def test_status_that_is_not_json_says_what_hermes_said(self):
        self.effect = lambda verb, bot: (2, "  ✗ Computer Use: unknown backend 'x'\n")
        got = asyncio.run(self.bridge.op_computer_status({}))
        self.assertEqual(got, {"read": False, "pinned": False, "line": "✗ Computer Use: unknown backend 'x'"})
        self.effect = lambda verb, bot: (None, "")
        got = asyncio.run(self.bridge.op_computer_status({}))
        self.assertEqual(got["line"], f"Hermes did not finish in {int(ob.COMPUTER_TIMEOUT['status'])} seconds.")
        with mock.patch.object(ob, "hermes_path", lambda *a, **k: None):
            self.assertEqual(asyncio.run(self.bridge.op_computer_status({}))["line"], "Hermes is not on this computer.")

    def test_bot_switch_is_read_from_its_gateway_only(self):
        self.assertEqual(self.op("bot"), {"state": "off", "why": "", "code_focus": False})
        self.assertEqual(self.gw.calls, [("profiles.describe", {"name": BOT})])
        self.gw.on = None
        self.assertEqual(self.op("bot"), {"state": "unknown", "why": "unread", "code_focus": False})
        self.gw.error = type("GatewayRPCError", (Exception,), {})("boom")
        self.assertEqual(self.op("bot"), {"state": "unknown", "why": "unread", "code_focus": False})
        # a bot omher is not attached to is not dialled: cannot tell, nothing started
        self.bridge.conns[BOT].client = None
        self.assertEqual(self.op("bot"), {"state": "unknown", "why": "offline", "code_focus": False})
        self.assertEqual(self.runs, [])

    def test_toggle_runs_the_fixed_argv_and_reads_the_switch_back(self):
        def effect(verb, bot):
            self.gw.on = verb == "enable"
            return 0, "✓ Enabled: computer_use\n"
        self.effect = effect
        self.assertEqual(self.op("toggle", on=True), {"outcome": "ok", "state": "on", "why": ""})
        self.assertEqual(self.runs, [("/stub/hermes", "enable", BOT, self.home, ob.COMPUTER_TIMEOUT["enable"])])
        self.assertEqual(self.op("toggle", on=False), {"outcome": "ok", "state": "off", "why": ""})
        self.assertEqual(self.runs[-1][1:3], ("disable", BOT))
        # already as asked: nothing runs
        self.assertEqual(self.op("toggle", on=False), {"outcome": "ok", "state": "off", "why": ""})
        self.assertEqual(len(self.runs), 2)

    def test_an_exit_0_whose_readback_disagrees_is_a_failure_with_hermes_words(self):
        # `hermes tools enable` exits 0 even when it refused: the switch read back decides
        self.effect = lambda verb, bot: (0, "⚠ Hermes 1.2 is available: run hermes update\n✗ Unknown toolset 'computer_use'\n")
        got = self.op("toggle", on=True)
        self.assertEqual(got, {"outcome": "failed", "state": "off", "why": "", "line": "✗ Unknown toolset 'computer_use'"})
        self.effect = lambda verb, bot: (0, "")
        got = self.op("toggle", on=True)
        self.assertEqual(got["line"], f"Hermes left computer use off for {BOT.capitalize()}.")

    def test_disabled_toolsets_make_the_switch_off_and_enable_clears_it(self):
        # describe says on (platform_toolsets.cli lists it) but agent.disabled_toolsets drops it from every new session
        self.gw.on = True
        config = self.home / "profiles" / BOT / "config.yaml"
        for listed in ("[computer_use, browser]", "\"['computer_use']\"", "computer_use"):
            config.write_text(f"model: x\nagent:\n  disabled_toolsets: {listed}\n", encoding="utf-8")
            self.assertEqual(self.op("bot"), {"state": "off", "why": "disabled", "code_focus": False}, listed)
        config.write_text("model: x\nagent:\n  disabled_toolsets: [browser]\n", encoding="utf-8")
        self.assertEqual(self.op("bot"), {"state": "on", "why": "", "code_focus": False})
        # turning it on runs Hermes' enable, which takes the name out of agent.disabled_toolsets
        config.write_text("model: x\nagent:\n  disabled_toolsets: [computer_use]\n", encoding="utf-8")

        def enable(verb, bot):
            config.write_text("model: x\nagent:\n  disabled_toolsets: []\n", encoding="utf-8")
            return 0, "✓ Enabled: computer_use\n"
        self.effect = enable
        self.assertEqual(self.op("toggle", on=True), {"outcome": "ok", "state": "on", "why": ""})
        self.assertEqual([r[1] for r in self.runs], ["enable"])

    def test_a_flip_without_hermes_is_a_refusal_nothing_ran(self):
        with mock.patch.object(ob, "hermes_path", lambda *a, **k: None):
            e = self.refused("toggle", "no_hermes", on=True)
        self.assertEqual(e.message, "Hermes is not on this computer.")
        self.assertEqual(self.runs, [])

    def test_an_ok_flip_keeps_the_reason_its_readback_gave(self):
        # turned off, and the profile's agent.disabled_toolsets also names it: the row keeps that reason
        self.gw.on = True
        config = self.home / "profiles" / BOT / "config.yaml"

        def disable(verb, bot):
            self.gw.on = False
            config.write_text("model: x\nagent:\n  disabled_toolsets: [computer_use]\n", encoding="utf-8")
            return 0, "✓ Disabled: computer_use\n"
        self.effect = disable
        self.assertEqual(self.op("toggle", on=False), {"outcome": "ok", "state": "off", "why": ""})
        self.gw.on = True  # describe says on; the list still drops it: off, why disabled
        self.assertEqual(self.op("toggle", on=False), {"outcome": "ok", "state": "off", "why": "disabled"})

    def test_code_focus_is_read_as_hermes_normalizes_it(self):
        config = self.home / "profiles" / BOT / "config.yaml"
        for value, focus in (("focus", True), ("Strict", True), ("lean", True), ("auto", False), ("on", False),
                             ("off", False), ("'focus '", True), ("[focus]", False)):
            config.write_text(f"model: x\nagent:\n  coding_context: {value}\n", encoding="utf-8")
            self.assertIs(self.op("bot")["code_focus"], focus, value)
        config.write_text("model: x\n", encoding="utf-8")  # Hermes' default is auto
        self.assertIs(self.op("bot")["code_focus"], False)

    def test_an_install_whose_state_cannot_be_read_after_is_not_a_failure(self):
        self.effect = lambda verb, bot: (0, "✓ cua-driver installed\n") if verb == "install" else (1, "Traceback: boom\n")
        got = asyncio.run(self.bridge.op_computer_install({}))
        self.assertEqual(got["outcome"], "ok")
        self.assertTrue(got["unconfirmed"])
        self.assertFalse(got["status"]["read"])

    def test_a_readback_that_cannot_be_read_says_so(self):
        def effect(verb, bot):
            self.gw.on = None
            return 0, "✓ Enabled: computer_use\n"
        self.effect = effect
        got = self.op("toggle", on=True)
        self.assertEqual(got["outcome"], "failed")
        self.assertEqual(got["state"], "unknown")
        self.assertTrue(got["line"].startswith(f"omher could not read {BOT.capitalize()}'s switch back."), got["line"])

    def test_toggle_takes_a_bot_and_on_only(self):
        for bad in ("yes", 1, None, "computer_use"):
            self.refused("toggle", "bad_request", on=bad)
        # a toolset name, a command or an argument from the page is never read
        self.gw.on = False
        self.effect = lambda verb, bot: (setattr(self.gw, "on", True), (0, ""))[1]
        asyncio.run(self.bridge.op_computer_toggle({"bot": BOT, "on": True, "name": "terminal", "names": ["terminal"],
                                                    "toolset": "terminal", "argv": ["rm"], "command": "x", "platform": "discord"}))
        self.assertEqual(self.runs, [("/stub/hermes", "enable", BOT, self.home, ob.COMPUTER_TIMEOUT["enable"])])
        with self.assertRaises(ob.BridgeError) as cm:
            asyncio.run(self.bridge.op_computer_toggle({"bot": "nobody", "on": True}))
        self.assertEqual(cm.exception.code, "unknown_bot")

    def test_a_profile_hermes_would_refuse_never_runs(self):
        path = self.home / "profiles" / "Bad.Name" / "config.yaml"
        path.parent.mkdir(parents=True)
        path.write_text("model: x\n", encoding="utf-8")
        with self.assertRaises(ob.BridgeError) as cm:
            asyncio.run(self.bridge.op_computer_toggle({"bot": "Bad.Name", "on": True}))
        self.assertEqual(cm.exception.code, "bad_request")
        self.assertEqual(self.runs, [])

    def test_toggle_is_refused_when_the_state_cannot_be_told_or_is_pinned(self):
        self.bridge.conns[BOT].client = None
        e = self.refused("toggle", "cannot_tell", on=True)
        self.assertIn("is offline", e.message)
        self.bridge.conns[BOT].client = self.gw
        with mock.patch.dict(os.environ, {"HERMES_TUI_TOOLSETS": "web"}):
            self.refused("toggle", "pinned", on=True)
            self.assertTrue(asyncio.run(self.bridge.op_computer_status({}))["pinned"])
        self.assertEqual([r[1] for r in self.runs], ["status"])

    def test_one_run_at_a_time(self):
        self.bridge._computer_busy = True
        self.refused("toggle", "busy", on=True)
        with self.assertRaises(ob.BridgeError) as cm:
            asyncio.run(self.bridge.op_computer_install({}))
        self.assertEqual(cm.exception.code, "busy")
        self.assertEqual(self.runs, [])

    def test_install_is_ok_only_when_the_driver_reads_installed_after(self):
        state = {"installed": False}

        def effect(verb, bot):
            if verb == "install":
                state["installed"] = True
                return 0, "Installing cua-driver…\n✓ cua-driver installed\n"
            return 1, payload(installed=state["installed"])
        self.effect = effect
        got = asyncio.run(self.bridge.op_computer_install({}))
        self.assertEqual(got["outcome"], "ok")
        self.assertTrue(got["status"]["installed"])
        self.assertEqual([r[1:3] for r in self.runs], [("install", "default"), ("status", "default")])
        self.assertEqual(self.runs[0][4], ob.COMPUTER_TIMEOUT["install"])
        state["installed"] = False
        self.effect = lambda verb, bot: (1, "    cua-driver preparation failed: no network\n") if verb == "install" else (1, payload())
        got = asyncio.run(self.bridge.op_computer_install({}))
        self.assertEqual((got["outcome"], got["line"]), ("failed", "cua-driver preparation failed: no network"))
        self.assertFalse(got["status"]["installed"])

    def test_grant_only_on_macos(self):
        with mock.patch.object(ob.sys, "platform", "linux"):
            with self.assertRaises(ob.BridgeError) as cm:
                asyncio.run(self.bridge.op_computer_grant({}))
        self.assertEqual(cm.exception.code, "bad_request")
        self.assertEqual(self.runs, [])
        with mock.patch.object(ob.sys, "platform", "darwin"):
            self.effect = lambda verb, bot: (2, "cua-driver: not installed. Run: hermes computer-use install\n") \
                if verb == "grant" else (1, payload())
            got = asyncio.run(self.bridge.op_computer_grant({}))
        self.assertEqual(got["outcome"], "failed")
        self.assertIn("not installed", got["line"])
        self.assertEqual([r[1] for r in self.runs], ["grant", "status"])


class Peer(unittest.TestCase):
    def test_a_bot_on_another_computer_is_refused_with_the_reason(self):
        bridge = ob.Bridge(token="t", hermes_home=Path(tempfile.gettempdir()) / "omher-no-home")
        link = ob.PeerLink("mac", "Mac mini", "demo@host.example", "ws://127.0.0.1:1/?token=" + "0" * 32)
        link.rows = [{"name": "mini"}]
        bridge.peers["mac"] = link
        for op in ("computer.bot", "computer.toggle"):
            with self.assertRaises(ob.BridgeError) as cm:
                asyncio.run(bridge._peer_op({"op": op, "bot": "mac:mini", "on": True}))
            self.assertEqual(cm.exception.code, "remote_bot", op)
            self.assertIn("Mac mini's own screen", cm.exception.message)
            self.assertNotIn(op, ob.PEER_FORWARD)
        # the driver ops take no bot at all: they never reach another computer
        for op in ("computer.status", "computer.install", "computer.grant"):
            self.assertNotIn(op, ob.PEER_FORWARD)
            self.assertNotIn(op, ob.PEER_REFUSED)


class ChatStep(unittest.TestCase):
    def test_the_step_names_the_action_and_app_never_what_it_types(self):
        for args in ({"action": "type", "app": "Notes", "text": "hunter2"}, {"action": "set_value", "app": "Notes", "value": "hunter2"},
                     {"action": "key", "app": "Notes", "keys": "cmd+v"}):
            self.assertEqual(ob.tool_detail("computer_use", args, "hunter2 cmd+v"), "Notes")
            self.assertEqual(ob.computer_step(args), (args["action"], "Notes"))
        # no app: nothing, never Hermes' preview (it can quote the typed text)
        self.assertEqual(ob.tool_detail("computer_use", {"action": "type", "text": "hunter2"}, "hunter2"), "")
        self.assertEqual(ob.computer_step({"action": "launch_rockets", "app": "Safari\x1b[2J"}), ("", "Safari"))
        self.assertEqual(ob.computer_step("x"), ("", ""))

    def test_tool_events_carry_action_and_app_and_never_the_result(self):
        bridge = ob.Bridge(token="t", hermes_home=Path(tempfile.gettempdir()) / "omher-no-home")
        conn = ob.Conn({"name": BOT, "path": Path("/nowhere"), "display_name": "Demo"})
        sent = []

        async def emit(c, chat, event, **fields):
            sent.append((event, fields))

        async def begin(c, chat=None):
            return None
        bridge._chat_emit = emit
        bridge._begin_turn = begin
        args = {"action": "type", "app": "Notes", "text": "hunter2", "keys": "cmd+a"}
        asyncio.run(bridge._main_event(conn, "tool.start", {}, {"tool_id": "t1", "name": "computer_use", "context": "hunter2",
                                                               "args": args}))
        asyncio.run(bridge._main_event(conn, "tool.complete", {}, {
            "tool_id": "t1", "name": "computer_use", "args": args, "image_path": "/tmp/shot.png",
            "result": {"image": "data:image/png;base64," + "A" * 5000, "text": "hunter2"}}))
        self.assertEqual(sent[0], ("tool.start", {"tool_id": "t1", "name": "computer_use", "detail": "Notes", "action": "type"}))
        self.assertEqual(sent[1], ("tool.end", {"tool_id": "t1", "name": "computer_use", "ok": True, "ms": 0}))
        self.assertNotIn("hunter2", json.dumps(sent))
        self.assertNotIn("base64", json.dumps(sent))

    def test_a_child_step_never_carries_hermes_preview_of_computer_use(self):
        # Hermes builds no preview for computer_use: its fallback preview of a `type` call is the typed text
        for key in ("tool_preview", "text"):
            got = ob.subagent_fields("subagent.tool", {"subagent_id": "s1", "tool_name": "computer_use", key: "hunter2-password"})
            self.assertEqual(got["tool"], "computer_use")
            self.assertNotIn("step", got)
            self.assertNotIn("hunter2", json.dumps(got))
        # another tool's preview is still its step
        got = ob.subagent_fields("subagent.tool", {"subagent_id": "s1", "tool_name": "terminal", "tool_preview": "ls -la"})
        self.assertEqual(got["step"], "ls -la")

    def test_a_session_view_drops_typed_text_and_the_whole_result(self):
        self.assertEqual(ob.computer_args(json.dumps({"action": "type", "app": "Notes", "text": "hunter2", "value": "v", "keys": "k"})),
                         {"action": "type", "app": "Notes"})
        self.assertEqual(ob.computer_args("not json"), {})
        # a recorded row, read the way Plans reads a child session
        with tempfile.TemporaryDirectory() as tmp:
            prof = Path(tmp) / "profiles" / "kami"
            prof.mkdir(parents=True)
            con = sqlite3.connect(prof / "state.db")
            con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, parent_session_id TEXT, model TEXT,"
                        " billing_provider TEXT, started_at REAL, ended_at REAL, end_reason TEXT, title TEXT)")
            con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,"
                        " content TEXT, tool_calls TEXT, tool_name TEXT, tool_call_id TEXT, timestamp REAL)")
            sid = "20261128_101500_c0ffee"
            con.execute("INSERT INTO sessions (id, source, started_at, ended_at, title) VALUES (?,?,?,?,?)",
                        (sid, "delegate", 1.0, 2.0, "child"))
            calls = [{"id": "c1", "function": {"name": "computer_use", "arguments": json.dumps(
                {"action": "type", "app": "Notes", "text": "hunter2-password"})}},
                     {"id": "c2", "function": {"name": "computer_use", "arguments": json.dumps({"action": "capture", "app": "Notes"})}}]
            rows = [("user", "Fill in the form", None, None, None),
                    ("assistant", "", json.dumps(calls), None, None),
                    ("tool", '{"ok": true, "typed": "hunter2-password"}', None, "computer_use", "c1"),
                    ("tool", json.dumps({"image": "data:image/png;base64," + "A" * 400,
                                         "elements": ['#4 AXTextField = "secret-field-value"']}), None, "computer_use", "c2"),
                    ("assistant", "Done.", None, None, None)]
            for role, content, tc, tname, tcid in rows:
                con.execute("INSERT INTO messages (session_id, role, content, tool_calls, tool_name, tool_call_id, timestamp)"
                            " VALUES (?,?,?,?,?,?,?)", (sid, role, content, tc, tname, tcid, 1.5))
            con.commit()
            con.close()
            got = ob.NodeSessions(homes={"claude": Path(tmp) / "c", "codex": Path(tmp) / "x"}).hermes_read(prof, sid)
        dump = json.dumps(got)
        for leak in ("hunter2", "base64", "secret-field-value"):
            self.assertNotIn(leak, dump, leak)
        steps = got["steps"]
        self.assertEqual([st["tool"] for st in steps], ["computer_use", "computer_use"])
        self.assertIn('"app": "Notes"', steps[0]["input"])
        self.assertEqual([st["result"] for st in steps], ["", ""])
        self.assertTrue(all(st["ok"] for st in steps))


if __name__ == "__main__":
    unittest.main()
