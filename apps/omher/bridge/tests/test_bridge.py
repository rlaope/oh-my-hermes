"""Bridge tests: a FakeGateway stands in for Hermes' gateway (no Hermes, no network beyond loopback)."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402
from websockets.exceptions import InvalidStatus  # noqa: E402

FIXTURE = HERE / "real-turn-events.json"
TOKEN = "t0ken"
MAIN_STORED = "local-main-stored"
MAIN_RUNTIME = "rt-main"


class GatewayRPCError(Exception):  # same class name Hermes uses; the bridge matches on the name
    pass


class GatewayClientError(ValueError):
    pass


class FakeClient:
    """The slice of ``GatewayClient`` the bridge uses: ``rpc`` and ``events``."""

    def __init__(self, name: str, *, bot_chat: bool = True, sessions=None, history=None, caps=None, lacks=(), ready=None):
        self.name = name
        # setup.runtime_check answers in order (a dict, or an exception to raise); the last one repeats
        self.ready = list(ready) if ready else [{"ok": True, "provider": "claude-proxy", "model": "claude-opus-5-5", "source": "pool"}]
        self.lacks = set(lacks)  # methods this gateway does not have: they fail as Hermes' do, `unknown_method`
        self.caps = caps if caps is not None else {}  # client.capabilities answer, or an exception to raise
        self.events: asyncio.Queue = asyncio.Queue()
        self.calls: list[tuple[str, dict]] = []
        self.bot_chat = bot_chat
        self.sessions = sessions if sessions is not None else []
        self.active: list[dict] = []
        self.history = history or {}
        self.model_info = {"model": "claude-opus-5-5", "provider": "claude-proxy", "reasoning_effort": "high"}
        self.revision = 7

    def find(self, method: str) -> list[dict]:
        return [p for m, p in self.calls if m == method]

    async def rpc(self, method, *, _timeout=None, **params):
        self.calls.append((method, params))
        if method in self.lacks:
            raise GatewayRPCError("unknown_method")
        if method == "session.list":
            if params.get("title") == ob.BOT_CHAT_TITLE:
                rows = [{"id": MAIN_STORED, "title": ob.BOT_CHAT_TITLE, "source": "tui"}] if self.bot_chat else []
                return {"sessions": rows, "scope": "stored"}
            rows = [dict(r) for r in self.sessions]
            return {"sessions": rows, "scope": params.get("scope", "live")}
        if method == "session.active_list":
            return {"sessions": self.active}
        if method == "session.resume":
            return {"session_id": MAIN_RUNTIME, "stored_session_id": params["session_id"], "running": False,
                    "messages": [
                        {"role": "user", "text": "hi", "timestamp": 100.5, "row_id": 1},
                        {"role": "tool", "text": "{}", "timestamp": 101.0, "row_id": 2},
                        {"role": "assistant", "text": "hello", "timestamp": 102.0, "row_id": 3},
                        {"role": "user", "text": "secret", "display_kind": "hidden", "row_id": 4}],
                    "info": dict(self.model_info), "revision": self.revision, "execution_generation": 3,
                    "prompts": []}
        if method == "setup.runtime_check":
            answer = self.ready.pop(0) if len(self.ready) > 1 else self.ready[0]
            if isinstance(answer, Exception):
                raise answer
            return dict(answer)
        if method == "client.capabilities":
            if isinstance(self.caps, Exception):
                raise self.caps
            return dict(self.caps)
        if method == "clarify.lock":
            return {"status": "ok", "remaining": []}
        if method == "session.create":
            if params.get("cwd"):  # a folder chat (SESSIONS > oh-my-hermes)
                n = len(self.find("session.create")) - 1
                return {"session_id": f"rt-folder-{n}", "stored_session_id": f"stored-folder-{n}", "messages": [],
                        "subscription_id": f"sub-folder-{n}",
                        "info": {**self.model_info, "cwd": params["cwd"]}, "revision": 0, "execution_generation": 0}
            return {"session_id": MAIN_RUNTIME, "stored_session_id": MAIN_STORED, "messages": [],
                    "info": dict(self.model_info), "revision": 0, "execution_generation": 0}
        if method == "session.title":
            return {"title": params["title"]}
        if method == "session.history":
            return {"count": len(self.history.get(params["session_id"], [])),
                    "messages": self.history.get(params["session_id"], [])}
        if method == "prompt.submit":
            return {"status": "started", "admission_id": "adm1", "execution_generation": 4}
        if method == "profiles.list":
            return {"profiles": [{"name": "kami", "display_name": "Kami!", "model": "m", "provider": "p",
                                  "description": "d"}]}
        if method == "model.options":
            return {"providers": [{"slug": "claude-proxy", "name": "Claude", "models": ["claude-opus-5-5", "x"]}],
                    "model": "claude-opus-5-5", "provider": "claude-proxy"}
        if method == "session.mutate":
            return {"session_id": params["session_id"], "operation": params["operation"]}
        if method == "image.attach_bytes":
            if params["content_base64"] == "bad":
                return {"attached": False, "message": "unsupported image"}
            return {"attached": True, "path": "/h/images/upload_1.png", "text": "[User attached image: upload_1.png]"}
        if method == "pdf.attach":
            return {"attached": True, "text": f"[User attached PDF: {params['filename']} (2 page(s))]"}
        if method == "file.attach":
            return {"attached": True, "name": params["name"], "ref_text": f"@file:attachments/{params['name']}"}
        if method == "cron.manage":
            if params.get("action") == "add" and params.get("schedule") == "whenever":
                return {"success": False, "error": "Invalid schedule 'whenever'. Use: 30m, every 2h, 0 9 * * *"}
            if params.get("action") == "add":
                return {"success": True, "job_id": "new1", "name": params.get("name")}
            return {"success": True, "job": {"id": params.get("name")}}
        if method == "plugins.manage":
            act = params.get("action")
            if act == "list":
                return {"plugins": [
                    {"name": "homeassistant", "key": "homeassistant", "version": "1.0", "description": "Home devices",
                     "source": "user", "status": "enabled", "tools": ["ha_on", "ha_off"], "catalog_name": "homeassistant",
                     "catalog_tier": "official", "settings_schema": []},
                    {"name": "browserbase", "key": "browserbase", "description": "Cloud browser", "source": "bundled",
                     "status": "not enabled", "tools": [], "settings_schema": [
                         {"key": "api_key", "type": "secret", "env": "BROWSERBASE_API_KEY", "has_value": False}]}]}
            if act == "inspect":
                return {"ok": True, "agent": True, "desktop": False, "sha": "abc1234def", "warnings": []}
            if act == "install":
                return {"ok": True, "plugin_name": params.get("catalog_name"), "enabled": True, "restart_required": True}
            return {"ok": True, "name": params.get("name") or params.get("key")}
        return {}

    def push(self, typ: str, payload: dict | None = None, sid: str = MAIN_RUNTIME, **extra) -> None:
        self.events.put_nowait({"jsonrpc": "2.0", "method": "event",
                                "params": {"type": typ, "session_id": sid, "payload": payload or {}, **extra}})


class Env:
    """A temp Hermes home with the profiles given, a Bridge on a loopback port and a FakeClient per profile."""

    def __init__(self, profiles=("kami",), *, fail=(), **client_kw):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / "config.yaml").write_text("model:\n  default: base-model\n  provider: base-prov\n")
        for p in profiles:
            d = self.home / "profiles" / p
            d.mkdir(parents=True)
            (d / "config.yaml").write_text("model:\n  default: claude-opus-5-5\n  provider: claude-proxy\nagent:\n  reasoning_effort: high\n")
        (self.home / "profiles" / "kami" / "profile.yaml").write_text('description: "Kami bot"\n') if "kami" in profiles else None
        self.fail = set(fail)
        self.client_kw = client_kw
        self.clients: dict[str, FakeClient] = {}
        self.connects: list[str] = []
        self.bridge = ob.Bridge(token=TOKEN, hermes_home=self.home, gateway_factory=self.factory, poll_s=3600)

    async def factory(self, stack, path: Path):
        name = "default" if path == self.home else path.name
        self.connects.append(name)
        if name in self.fail:
            raise OSError("gateway refused")
        c = self.clients[name] = FakeClient(name, **self.client_kw)
        return c

    async def __aenter__(self):
        self.port = await self.bridge.start(port=0, watch=False)
        return self

    async def __aexit__(self, *exc):
        await self.bridge.close()
        self.tmp.cleanup()

    def url(self, token=TOKEN):
        return f"ws://127.0.0.1:{self.port}/?token={token}"


class Session:
    """A websocket client that separates replies from events."""

    def __init__(self, ws):
        self.ws, self.n = ws, 0
        self.events: list[dict] = []
        self.orphans: list[dict] = []
        self._replies: dict[str, asyncio.Future] = {}
        self.task = asyncio.ensure_future(self._read())

    async def _read(self):
        try:
            async for raw in self.ws:
                f = json.loads(raw)
                if "event" in f:
                    self.events.append(f)
                else:
                    fut = self._replies.get(f.get("id"))
                    if fut is None or fut.done():
                        self.orphans.append(f)  # a reply to no pending request (e.g. a frame with no usable id)
                    else:
                        fut.set_result(f)
        except Exception:
            pass

    async def req(self, op: str, **params) -> dict:
        self.n += 1
        rid = f"r{self.n}"
        fut = self._replies.setdefault(rid, asyncio.get_running_loop().create_future())
        await self.ws.send(json.dumps({"id": rid, "op": op, **params}))
        return await asyncio.wait_for(fut, 5)

    async def until(self, pred, timeout=5.0):
        end = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < end:
            if pred(self.events):
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"timed out; events so far: {[e['event'] for e in self.events]}")

    def kinds(self, skip=("bot.status",)):
        return [e["event"] for e in self.events if e["event"] not in skip]


class BridgeCase(unittest.IsolatedAsyncioTestCase):
    async def open(self, env: Env) -> Session:
        ws = await connect(env.url(), proxy=None)
        self.addAsyncCleanup(ws.close)
        s = Session(ws)
        self.addCleanup(s.task.cancel)
        return s


class ProtocolBasics(BridgeCase):
    async def test_hello(self):
        async with Env() as env:
            s = await self.open(env)
            r = await s.req("hello")
            self.assertTrue(r["ok"])
            self.assertEqual(r["result"]["bridge"], "real")
            self.assertEqual(r["result"]["version"], ob.VERSION)
            self.assertEqual(r["result"]["hermes"]["home"], str(env.home))

    async def test_wrong_token_is_refused(self):
        async with Env() as env:
            with self.assertRaises(InvalidStatus) as cm:
                async with connect(env.url("nope"), proxy=None):
                    pass
            self.assertEqual(cm.exception.response.status_code, 403)
            with self.assertRaises(InvalidStatus):
                async with connect(f"ws://127.0.0.1:{env.port}/", proxy=None):
                    pass

    async def test_binds_loopback_only(self):
        async with Env() as env:
            host = env.bridge.server.sockets[0].getsockname()[0]
            self.assertEqual(host, "127.0.0.1")

    async def test_bad_frames_reply_bad_request_and_connection_survives(self):
        async with Env() as env:
            s = await self.open(env)
            for raw in ("not json", "[1,2]", json.dumps({"op": "hello"}), json.dumps({"id": 5, "op": "hello"}),
                        json.dumps({"id": "x"})):
                await s.ws.send(raw)
            await s.ws.send(json.dumps({"id": "has-id", "op": 5}))
            for _ in range(300):
                if len(s.orphans) >= 6:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(len(s.orphans), 6)  # every bad frame got exactly one bad_request reply
            self.assertEqual(sorted(str(f["id"]) for f in s.orphans), ["None"] * 4 + ["has-id", "x"])
            for f in s.orphans:
                self.assertFalse(f["ok"])
                self.assertEqual(f["error"]["code"], "bad_request")
            self.assertTrue((await s.req("hello"))["ok"])  # still alive
            r = await s.req("no.such.op")
            self.assertEqual(r["error"]["code"], "unknown_op")
            r = await s.req("chat.open")  # no bot
            self.assertEqual(r["error"]["code"], "bad_request")
            r = await s.req("chat.open", bot="ghost")
            self.assertEqual(r["error"]["code"], "unknown_bot")

    async def test_offline_bot_replies_bot_offline(self):
        async with Env(fail=("kami",)) as env:
            s = await self.open(env)
            r = await s.req("chat.open", bot="kami")
            self.assertFalse(r["ok"])
            self.assertEqual(r["error"]["code"], "bot_offline")
            r = await s.req("chat.send", bot="kami", text="hi")
            self.assertEqual(r["error"]["code"], "bot_offline")
            bots = (await s.req("bots.list"))["result"]["bots"]
            self.assertEqual([b["status"] for b in bots if b["name"] == "kami"], ["offline"])
            self.assertEqual(env.connects.count("kami"), 1)  # the cooldown stops a reconnect storm


class BotsAndChat(BridgeCase):
    async def test_bots_list_does_not_start_gateways(self):
        async with Env(("kami", "deepseek")) as env:
            s = await self.open(env)
            bots = (await s.req("bots.list"))["result"]["bots"]
            self.assertEqual(env.connects, [])
            by = {b["name"]: b for b in bots}
            self.assertEqual(set(by), {"default", "kami", "deepseek"})
            self.assertEqual(by["default"]["display_name"], "Hermes")
            self.assertTrue(by["default"]["is_default"])
            self.assertEqual(by["deepseek"]["display_name"], "Deepseek")
            self.assertEqual(by["kami"]["description"], "Kami bot")
            self.assertEqual(by["kami"]["model"], "claude-opus-5-5")
            self.assertTrue(all(b["status"] == "offline" and b["running"] is False for b in bots))

    async def test_chat_open_existing_bot_chat(self):
        async with Env() as env:
            s = await self.open(env)
            r = await s.req("chat.open", bot="kami")
            self.assertTrue(r["ok"], r)
            res = r["result"]
            c = env.clients["kami"]
            self.assertEqual(c.find("session.list")[0], {"title": "Bot Chat", "include_hidden": True, "limit": 5})
            self.assertEqual(c.find("session.resume"), [{"session_id": MAIN_STORED}])
            self.assertEqual(c.find("session.create"), [])
            self.assertEqual(res["session_id"], MAIN_RUNTIME)
            self.assertEqual([(m["role"], m["text"]) for m in res["messages"]], [("user", "hi"), ("assistant", "hello")])
            self.assertEqual(res["messages"][0]["ts"], 100.5)
            self.assertEqual((res["model"], res["provider"], res["reasoning"]), ("claude-opus-5-5", "claude-proxy", "high"))
            self.assertFalse(res["running"])
            bots = (await s.req("bots.list"))["result"]["bots"]
            kami = [b for b in bots if b["name"] == "kami"][0]
            self.assertEqual(kami["status"], "online")
            self.assertEqual(kami["display_name"], "Kami!")  # live profiles.list wins once a gateway is attached

    async def test_chat_open_existing_only_never_creates_a_bot_chat(self):
        # a bot outside the sidebar list is asked for its waiting prompts; asking must not make its Bot Chat
        async with Env(bot_chat=False) as env:
            s = await self.open(env)
            r = await s.req("chat.open", bot="kami", existing_only=True)
            self.assertFalse(r["ok"], r)
            self.assertEqual(r["error"]["code"], "not_found")
            c = env.clients["kami"]
            self.assertEqual(c.find("session.create"), [])
            self.assertEqual(c.find("session.title"), [])

    async def test_chat_open_existing_only_resumes_an_existing_bot_chat(self):
        async with Env() as env:
            s = await self.open(env)
            r = await s.req("chat.open", bot="kami", existing_only=True)
            self.assertTrue(r["ok"], r)
            c = env.clients["kami"]
            self.assertEqual(c.find("session.resume"), [{"session_id": MAIN_STORED}])
            self.assertEqual(c.find("session.create"), [])

    async def test_chat_open_creates_missing_bot_chat(self):
        async with Env(bot_chat=False) as env:
            s = await self.open(env)
            r = await s.req("chat.open", bot="kami")
            self.assertTrue(r["ok"], r)
            c = env.clients["kami"]
            create = c.find("session.create")
            self.assertEqual(len(create), 1)
            self.assertEqual(create[0]["title"], "Bot Chat")
            self.assertTrue(create[0]["follow_profile_config"])
            self.assertEqual(c.find("session.resume"), [])
            self.assertEqual(c.find("session.title"), [{"session_id": MAIN_RUNTIME, "title": "Bot Chat"}])
            self.assertEqual(r["result"]["session_id"], MAIN_RUNTIME)
            self.assertEqual(r["result"]["messages"], [])

    async def test_chat_send_passes_input_id_and_only_the_main_id(self):
        async with Env() as env:
            s = await self.open(env)
            r = await s.req("chat.send", bot="kami", text="hello there")  # no chat.open first: the bridge attaches itself
            self.assertTrue(r["ok"], r)
            c = env.clients["kami"]
            sub = c.find("prompt.submit")
            self.assertEqual(len(sub), 1)
            self.assertEqual(sub[0]["session_id"], MAIN_RUNTIME)
            self.assertEqual(sub[0]["text"], "hello there")
            self.assertRegex(sub[0]["input_id"], r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
            self.assertEqual(r["result"], {"input_id": sub[0]["input_id"]})
            # a client-supplied session_id is ignored, never forwarded
            r = await s.req("chat.send", bot="kami", text="again", session_id="20261108_235229_aaaf70c4")
            self.assertTrue(r["ok"])
            self.assertEqual({p["session_id"] for p in c.find("prompt.submit")}, {MAIN_RUNTIME})
            self.assertEqual((await s.req("chat.send", bot="kami", text="  "))["error"]["code"], "bad_request")

    async def test_interrupt_and_responses_target_the_main_chat(self):
        async with Env() as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            c = env.clients["kami"]
            c.push("approval.request", {"prompt_id": "ap1", "kind": "approval", "execution_generation": 5,
                                        "command": "rm -rf /tmp/x", "description": "Delete files", "choices": ["once", "deny"]})
            c.push("clarify.request", {"prompt_id": "cl1", "kind": "clarify", "execution_generation": 5,
                                       "question": "Which one?", "choices": ["a", "b"]})
            await s.until(lambda ev: any(e["event"] == "clarify.request" for e in ev))
            ap = [e for e in s.events if e["event"] == "approval.request"][0]
            self.assertEqual((ap["bot"], ap["request_id"], ap["command"], ap["title"], ap["choices"]),
                             ("kami", "ap1", "rm -rf /tmp/x", "Delete files", ["once", "deny"]))
            cl = [e for e in s.events if e["event"] == "clarify.request"][0]
            self.assertEqual((cl["request_id"], cl["question"], cl["choices"]), ("cl1", "Which one?", ["a", "b"]))
            self.assertTrue((await s.req("approval.respond", bot="kami", request_id="ap1", choice="once"))["ok"])
            self.assertTrue((await s.req("clarify.respond", bot="kami", request_id="cl1", answer="a"))["ok"])
            self.assertTrue((await s.req("chat.interrupt", bot="kami"))["ok"])
            self.assertEqual(c.find("approval.respond"),
                             [{"session_id": MAIN_RUNTIME, "prompt_id": "ap1", "choice": "once", "execution_generation": 5}])
            self.assertEqual(c.find("clarify.respond"),
                             [{"session_id": MAIN_RUNTIME, "prompt_id": "cl1", "answer": "a", "execution_generation": 5}])
            self.assertEqual(len(c.find("session.interrupt")), 1)
            self.assertEqual(c.find("session.interrupt")[0]["session_id"], MAIN_RUNTIME)
            bad = await s.req("approval.respond", bot="kami", request_id="ap1", choice="maybe")
            self.assertEqual(bad["error"]["code"], "bad_request")

    async def test_set_model_uses_session_mutate_on_the_main_chat(self):
        async with Env() as env:
            s = await self.open(env)
            r = await s.req("chat.set_model", bot="kami", model="claude-sonnet-5-5", provider="claude-proxy", reasoning="low")
            self.assertTrue(r["ok"], r)
            muts = env.clients["kami"].find("session.mutate")
            self.assertEqual([(m["operation"], m["payload"]) for m in muts],
                             [("model", {"model": "claude-sonnet-5-5", "provider": "claude-proxy"}),
                              ("reasoning", {"effort": "low"})])
            for m in muts:
                self.assertEqual(m["session_id"], MAIN_RUNTIME)
                self.assertEqual((m["expected_revision"], m["expected_generation"]), (7, 3))
            self.assertEqual((await s.req("chat.set_model", bot="kami", reasoning="turbo"))["error"]["code"], "bad_request")
            self.assertEqual((await s.req("chat.set_model", bot="kami"))["error"]["code"], "bad_request")

    async def test_models_options_shape(self):
        async with Env() as env:
            s = await self.open(env)
            r = (await s.req("models.options", bot="kami"))["result"]
            self.assertEqual(r["providers"], [{"slug": "claude-proxy", "name": "Claude", "models": ["claude-opus-5-5", "x"]}])
            self.assertEqual(r["current"]["model"], "claude-opus-5-5")
            self.assertEqual(r["reasoning_levels"], ["none", "low", "medium", "high", "xhigh"])


class BotsReady(BridgeCase):
    """bots.ready: the bot's own setup.runtime_check, read-only, answered as {ok, provider, model, error}."""

    NOT_READY = {"ok": False, "error": "Hermes is not connected to any AI provider yet. Run `hermes model` to pick one."}

    async def test_ready_bot(self):
        async with Env() as env:
            s = await self.open(env)
            r = (await s.req("bots.ready", bot="kami"))["result"]
            self.assertEqual(r, {"ok": True, "provider": "claude-proxy", "model": "claude-opus-5-5", "error": ""})
            c = env.clients["kami"]
            self.assertEqual(c.find("setup.runtime_check"), [{}])
            # read-only: no chat is opened, nothing is changed
            for m in ("session.create", "session.mutate", "prompt.submit", "config.set"):
                self.assertEqual(c.find(m), [], m)

    async def test_not_ready_bot_carries_hermes_error(self):
        async with Env(ready=[self.NOT_READY]) as env:
            s = await self.open(env)
            r = (await s.req("bots.ready", bot="kami"))["result"]
            self.assertEqual(r, {"ok": False, "provider": "", "model": "", "error": self.NOT_READY["error"]})

    async def test_a_sign_in_provider_asks_the_strict_check(self):
        async with Env() as env:
            s = await self.open(env)
            for pid in ("openai-codex", "anthropic", "nous"):
                self.assertTrue((await s.req("bots.ready", bot="kami", provider=pid))["ok"])
            self.assertEqual(env.clients["kami"].find("setup.runtime_check"),
                             [{"provider": "openai-codex"}, {"provider": "anthropic"}, {"provider": "nous"}])
            for bad in ("", 3, "anthropic --x", "Nous", "-x", "a/b", "$(id)"):
                r = await s.req("bots.ready", bot="kami", provider=bad)
                self.assertEqual(r["error"]["code"], "bad_request", bad)
            self.assertEqual((await s.req("bots.ready", bot="ghost"))["error"]["code"], "unknown_bot")

    async def test_still_checking_is_asked_again_then_reported_unknown(self):
        busy = GatewayRPCError("readiness_in_progress")
        with mock.patch.object(ob, "READY_RETRY", (0.0, 0.0, None)):
            async with Env(ready=[busy, self.NOT_READY]) as env:
                s = await self.open(env)
                r = (await s.req("bots.ready", bot="kami"))["result"]
                self.assertFalse(r["ok"])
                self.assertEqual(len(env.clients["kami"].find("setup.runtime_check")), 2)
            async with Env(ready=[busy]) as env:
                s = await self.open(env)
                r = (await s.req("bots.ready", bot="kami"))["result"]
                self.assertEqual((r["ok"], r.get("unknown")), (True, True))
                self.assertEqual(len(env.clients["kami"].find("setup.runtime_check")), 3)

    async def test_an_older_gateway_without_the_probe_shows_no_block(self):
        async with Env(lacks={"setup.runtime_check"}) as env:
            s = await self.open(env)
            r = (await s.req("bots.ready", bot="kami"))["result"]
            self.assertEqual((r["ok"], r.get("unknown")), (True, True))

    async def test_an_offline_bot_is_an_error_not_a_verdict(self):
        async with Env(fail={"kami"}) as env:
            s = await self.open(env)
            self.assertEqual((await s.req("bots.ready", bot="kami"))["error"]["code"], "bot_offline")


class EventMapping(BridgeCase):
    def fixture_frames(self):
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    async def test_real_turn_maps_to_protocol_events(self):
        async with Env() as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            c = env.clients["kami"]
            for ev in self.fixture_frames():
                c.push(ev["type"], ev["payload"], execution_generation=1)
            await s.until(lambda ev: any(e["event"] == "turn.end" for e in ev))
            ev = [e for e in s.events if e["event"] != "bot.status"]
            kinds = [e["event"] for e in ev]
            self.assertEqual(kinds[0], "turn.start")
            self.assertEqual(kinds[-1], "turn.end")
            self.assertEqual(kinds[-2], "message")
            self.assertEqual(kinds.count("turn.start"), 1)
            self.assertEqual(kinds.count("turn.end"), 1)
            self.assertTrue(all(e["bot"] == "kami" for e in ev))
            st = [e for e in ev if e["event"] == "status"]
            self.assertEqual([e["text"] for e in st], ["🧠 OMH — recalled 6 memories"])
            self.assertEqual(kinds.count("thinking"), 1)  # throttled to 1 per second
            ts = [e for e in ev if e["event"] == "tool.start"][0]
            self.assertEqual((ts["tool_id"], ts["name"], ts["detail"]), ("toolu_015CxWBfJRCfcovenJzxsdNd", "terminal", "echo omher-probe"))
            te = [e for e in ev if e["event"] == "tool.end"][0]
            self.assertEqual((te["tool_id"], te["name"], te["ok"], te["ms"]), ("toolu_015CxWBfJRCfcovenJzxsdNd", "terminal", True, 152))
            self.assertLess(kinds.index("tool.start"), kinds.index("tool.end"))
            deltas = "".join(e["text"] for e in ev if e["event"] == "delta")
            self.assertEqual(deltas, "\n\n`echo omher-probe` 실행 결과 `omher-probe`가 출력됐고 exit code는 0입니다.")
            msg = [e for e in ev if e["event"] == "message"][0]
            self.assertEqual(msg["text"], "`echo omher-probe` 실행 결과 `omher-probe`가 출력됐고 exit code는 0입니다.")
            self.assertEqual(msg["id"], "48182")
            self.assertEqual([e for e in ev if e["event"] == "turn.end"][0]["outcome"], "done")
            self.assertNotIn("skill", kinds)
            running = [(e["status"], e["running"]) for e in s.events if e["event"] == "bot.status"]
            self.assertEqual(running[-2:], [("online", True), ("online", False)])

    async def test_a_real_fan_out_becomes_subagent_events_clipped_with_no_thinking_text(self):
        """kami's Bot Chat, one real turn asking two subagents for `date +%F` and `uname -s` (gateway frames as
        recorded; the two `subagent.complete` frames came after the parent's turn ended and are rebuilt from the
        children's own task logs, `rebuilt_from_task_log`)."""
        frames = json.loads((HERE / "fixtures" / "real-subagent-turn.json").read_text(encoding="utf-8"))
        async with Env() as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            c = env.clients["kami"]
            for f in frames:
                c.push(f["type"], f["payload"], execution_generation=1)
            await s.until(lambda ev: sum(e["event"] == "subagent" and e.get("state") == "done" for e in ev) == 2)
            ev = [e for e in s.events if e["event"] != "bot.status"]
            sub = [e for e in ev if e["event"] == "subagent"]
            # every subagent.* frame but none dropped: 2 spawn, 2 start, 3 thinking, 1 tool, 2 complete
            self.assertEqual([e["state"] for e in sub], ["queued", "queued", "running", "running", "thinking", "thinking",
                                                        "running", "thinking", "done", "done"])
            self.assertEqual({e["id"] for e in sub}, {"sa-0-ab7aca17", "sa-1-0a3ce8a1"})
            self.assertEqual({(e["index"], e["count"]) for e in sub}, {(0, 2), (1, 2)})
            self.assertTrue(all(e["bot"] == "kami" and "session" not in e for e in sub))
            first = sub[0]
            self.assertEqual(set(first), {"event", "bot", "id", "index", "count", "goal", "model", "state"})
            self.assertEqual(first["model"], "claude-fable-5-2")
            started = [e for e in sub if e["state"] == "running" and "step" not in e]
            self.assertEqual({e["delegation"] for e in started}, {"deleg_40dc82e8"})
            # the goal, clipped: no frame's text runs past the caps
            self.assertTrue(all(len(e["goal"]) <= ob.SUBAGENT_GOAL for e in sub))
            self.assertTrue(first["goal"].startswith("Run the shell command `date +%F` in the terminal"))
            tool = next(e for e in sub if e.get("tool"))
            self.assertEqual((tool["id"], tool["tool"], tool["step"]), ("sa-1-0a3ce8a1", "terminal", "uname -s"))
            # thinking: the state only, never a text field
            self.assertTrue(all(set(e) & {"text", "step", "summary"} == set() for e in sub if e["state"] == "thinking"))
            done = {e["id"]: e for e in sub if e["state"] == "done"}
            self.assertEqual((done["sa-0-ab7aca17"]["summary"], done["sa-0-ab7aca17"]["seconds"]), ("2026-11-11", 8.8))
            self.assertEqual((done["sa-1-0a3ce8a1"]["summary"], done["sa-1-0a3ce8a1"]["seconds"]), ("Darwin", 6.1))
            # the parent's turn: one start, one end; the late subagent frames open no second turn
            kinds = [e["event"] for e in ev]
            self.assertEqual((kinds.count("turn.start"), kinds.count("turn.end")), (1, 1))
            self.assertLess(kinds.index("turn.end"), max(i for i, k in enumerate(kinds) if k == "subagent"))
            ts = next(e for e in ev if e["event"] == "tool.start")
            self.assertEqual(ts["name"], "delegate_task")
            self.assertLess(kinds.index("tool.start"), kinds.index("subagent"))

    def test_subagent_fields_clip_every_text_and_take_the_dag_mark_off_the_goal(self):
        long = "x" * 900
        f = ob.subagent_fields("subagent.start", {"subagent_id": "sa-0", "task_index": 0, "task_count": 3,
                                                  "goal": "[dag:docs-dark/contrast] Check the contrast " + long,
                                                  "delegation_id": "deleg_1", "model": "m" * 300})
        self.assertEqual(f["dag"], {"run": "docs-dark", "node": "contrast"})
        self.assertTrue(f["goal"].startswith("Check the contrast"))
        self.assertEqual((len(f["goal"]), len(f["model"])), (ob.SUBAGENT_GOAL, 80))
        t = ob.subagent_fields("subagent.tool", {"subagent_id": "sa-0", "tool_name": "terminal", "text": long})
        self.assertEqual(len(t["step"]), ob.SUBAGENT_STEP)
        c = ob.subagent_fields("subagent.complete", {"subagent_id": "sa-0", "status": "failed", "summary": long,
                                                     "duration_seconds": 12.345, "output_tail": [long]})
        self.assertEqual((c["state"], len(c["summary"]), c["seconds"]), ("failed", ob.SUBAGENT_SUMMARY, 12.3))
        self.assertNotIn("output_tail", c)
        th = ob.subagent_fields("subagent.thinking", {"subagent_id": "sa-0", "text": "my secret chain of thought"})
        self.assertNotIn("my secret", json.dumps(th))
        pr = ob.subagent_fields("subagent.progress", {"subagent_id": "sa-0", "text": "🔀 [1] read_file, terminal"})
        self.assertEqual(pr["step"], "[1] read_file, terminal")
        self.assertIsNone(ob.subagent_fields("subagent.text", {"subagent_id": "sa-0", "text": "tok"}))
        self.assertIsNone(ob.subagent_fields("subagent.start", {"goal": "no id"}))
        self.assertEqual(ob.subagent_fields("subagent.complete", {"subagent_id": "s", "status": "interrupted"})["state"],
                         "cancelled")

    async def test_subagent_events_of_another_session_are_not_forwarded(self):
        async with Env() as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            c = env.clients["kami"]
            c.push("subagent.start", {"subagent_id": "sa-x", "goal": "elsewhere"}, sid="someone-else")
            c.push("subagent.start", {"subagent_id": "sa-y", "goal": "mine"})
            await s.until(lambda ev: any(e["event"] == "subagent" for e in ev))
            await asyncio.sleep(0.05)
            self.assertEqual([e["id"] for e in s.events if e["event"] == "subagent"], ["sa-y"])

    async def test_skill_view_also_emits_skill(self):
        async with Env() as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            c = env.clients["kami"]
            c.push("tool.start", {"tool_id": "t1", "name": "skill_view", "context": "omh-plan", "args": {"name": "omh-plan"}})
            c.push("tool.start", {"tool_id": "t2", "name": "terminal", "context": "x" * 400})
            await s.until(lambda ev: sum(e["event"] == "tool.start" for e in ev) == 2)
            skills = [e for e in s.events if e["event"] == "skill"]
            self.assertEqual([e["name"] for e in skills], ["omh-plan"])
            details = [e["detail"] for e in s.events if e["event"] == "tool.start"]
            self.assertEqual(len(details[1]), 160)

    async def test_interrupted_and_error_outcomes(self):
        async with Env() as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            c = env.clients["kami"]
            c.push("message.start")
            c.push("message.complete", {"text": "", "status": "interrupted"})
            c.push("message.start")
            c.push("message.complete", {"text": "", "status": "error", "error": "boom"})
            await s.until(lambda ev: sum(e["event"] == "turn.end" for e in ev) == 2)
            ends = [e for e in s.events if e["event"] == "turn.end"]
            self.assertEqual([e["outcome"] for e in ends], ["interrupted", "error"])
            self.assertEqual(ends[1]["error"], "boom")
            self.assertNotIn("message", s.kinds())  # empty text -> no message event

    async def test_events_of_other_sessions_are_dropped(self):
        async with Env() as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            c = env.clients["kami"]
            for sid in ("20261108_235229_aaaf70c4", "some-slack-runtime"):
                c.push("message.start", sid=sid)
                c.push("tool.start", {"tool_id": "x", "name": "terminal", "context": "leak"}, sid=sid)
                c.push("message.delta", {"text": "leak"}, sid=sid)
                c.push("message.complete", {"text": "leak"}, sid=sid)
            c.push("message.start")  # a sentinel from the main chat
            c.push("message.delta", {"text": "mine"})
            await s.until(lambda ev: any(e["event"] == "delta" for e in ev))
            self.assertEqual([e["text"] for e in s.events if e["event"] == "delta"], ["mine"])
            self.assertNotIn("tool.start", s.kinds())
            self.assertNotIn("message", s.kinds())
            self.assertEqual(s.kinds().count("turn.start"), 1)
            self.assertIn("elsewhere.update", s.kinds())  # another session moving only refreshes the elsewhere list

    async def test_gateway_loss_turns_the_bot_offline_and_ends_the_turn(self):
        async with Env() as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            c = env.clients["kami"]
            c.push("message.start")
            await s.until(lambda ev: any(e["event"] == "turn.start" for e in ev))
            c.events.put_nowait(GatewayClientError("Gateway disconnected; turn outcome is unknown."))
            await s.until(lambda ev: any(e["event"] == "turn.end" for e in ev))
            end = [e for e in s.events if e["event"] == "turn.end"][0]
            self.assertEqual(end["outcome"], "error")
            last = [e for e in s.events if e["event"] == "bot.status"][-1]
            self.assertEqual((last["status"], last["running"]), ("offline", False))
            self.assertEqual((await s.req("chat.send", bot="kami", text="x"))["error"]["code"], "bot_offline")


class NeedsYou(BridgeCase):
    """Asks raised while omher looks elsewhere: an interview (one clarify request with several questions),
    expiry when the gateway stops waiting, and the clarify_batch flag on submit only when the gateway offers it."""

    QUESTIONS = [{"qid": "q1", "question": "Who reads it?", "choices": ["Users", "Devs"], "multi_select": False},
                 {"qid": "q2", "question": "Sections?", "choices": ["Fixes", "Thanks"], "multi_select": True},
                 {"qid": "q3", "question": "Leave anything out?", "choices": None, "multi_select": False}]

    def ask(self, c, rid="srq-abc123", sid=MAIN_RUNTIME, questions=None, **extra):
        c.events.put_nowait({"jsonrpc": "2.0", "id": rid, "method": "clarify",
                             "params": {"session_id": sid, "questions": questions or self.QUESTIONS, **extra}})

    async def test_batch_clarify_is_one_interview_answered_by_locking_each_question(self):
        async with Env() as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            c = env.clients["kami"]
            self.ask(c, rid="srq-foreign", sid="20261108_235229_aaaf70c4")  # another session's ask: not ours
            self.ask(c)
            await s.until(lambda ev: any(e["event"] == "clarify.request" for e in ev))
            asks = [e for e in s.events if e["event"] == "clarify.request"]
            self.assertEqual(len(asks), 1)
            self.assertEqual(asks[0]["request_id"], "srq-abc123")
            self.assertEqual(asks[0]["question"], "Who reads it?")
            self.assertEqual([q["qid"] for q in asks[0]["questions"]], ["q1", "q2", "q3"])
            self.assertTrue(asks[0]["questions"][1]["multi_select"])
            self.assertNotIn("choices", asks[0]["questions"][2])
            r = await s.req("clarify.respond", bot="kami", request_id="srq-abc123",
                            answers={"q1": "Users", "q2": None, "q3": "the beta"})
            self.assertTrue(r["ok"], r)
            self.assertEqual(c.find("clarify.lock"), [
                {"request_id": "srq-abc123", "question_id": "q1", "answer": "Users"},
                {"request_id": "srq-abc123", "question_id": "q2", "answer": None},
                {"request_id": "srq-abc123", "question_id": "q3", "answer": "the beta"}])
            self.assertEqual(c.find("clarify.respond"), [])
            bad = await s.req("clarify.respond", bot="kami", request_id="x", answers={"q1": 3})
            self.assertEqual(bad["error"]["code"], "bad_request")

    async def test_a_single_question_batch_keeps_its_choices(self):
        async with Env() as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            c = env.clients["kami"]
            self.ask(c, questions=self.QUESTIONS[1:2])
            await s.until(lambda ev: any(e["event"] == "clarify.request" for e in ev))
            ask = [e for e in s.events if e["event"] == "clarify.request"][0]
            self.assertEqual((ask["question"], ask["choices"], ask["multi_select"]), ("Sections?", ["Fixes", "Thanks"], True))
            self.assertNotIn("questions", ask)
            self.assertTrue((await s.req("clarify.respond", bot="kami", request_id="srq-abc123", answer='["Fixes"]'))["ok"])
            self.assertEqual(c.find("clarify.lock"), [{"request_id": "srq-abc123", "question_id": "q2", "answer": '["Fixes"]'}])

    async def test_settled_or_cancelled_asks_expire_with_a_reason(self):
        async with Env() as env:
            t = [1000.0]
            env.bridge.clock = lambda: t[0]
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            c = env.clients["kami"]
            c.push("approval.request", {"prompt_id": "ap1", "kind": "approval", "execution_generation": 5,
                                        "command": "rm -rf build/", "choices": ["once", "deny"], "timeout_s": 60})
            c.push("clarify.request", {"prompt_id": "cl1", "kind": "clarify", "execution_generation": 5,
                                       "question": "Which?", "choices": ["a"], "timeout_s": 300})
            await s.until(lambda ev: any(e["event"] == "clarify.request" for e in ev))
            ap = [e for e in s.events if e["event"] == "approval.request"][0]
            self.assertEqual(ap["timeout_s"], 60)
            t[0] = 1061.0
            c.push("approval.settled", {"prompt_id": "ap1", "execution_generation": 5})  # past its 60 s: timed out
            c.push("clarify.settled", {"prompt_id": "cl1", "execution_generation": 5})   # early: answered elsewhere
            c.push("approval.settled", {"prompt_id": "never-seen", "execution_generation": 5})
            self.ask(c, rid="srq-iv")
            await s.until(lambda ev: any(e["event"] == "clarify.request" and e["request_id"] == "srq-iv" for e in ev))
            c.push("request.cancel", {"id": "srq-iv", "method": "clarify", "reason": "timeout"})
            c.push("request.cancel", {"id": "srq-unknown", "method": "sudo", "reason": "timeout"})
            await s.until(lambda ev: sum(e["event"] == "prompt.expired" for e in ev) == 3)
            await asyncio.sleep(0.05)
            got = [(e["request_id"], e["reason"]) for e in s.events if e["event"] == "prompt.expired"]
            self.assertEqual(got, [("ap1", "timeout"), ("cl1", "resolved"), ("srq-iv", "timeout")])
            # an expired ask cannot be answered through omher any more
            r = await s.req("clarify.respond", bot="kami", request_id="srq-iv", answers={"q1": "Users"})
            self.assertTrue(r["ok"])
            self.assertEqual(c.find("clarify.lock"), [])

    async def test_submit_declares_clarify_batch_only_when_the_gateway_offers_it(self):
        for caps, want in (({"canonical_clarify_batch": True}, True), ({}, False),
                           (GatewayRPCError("unknown_method"), False)):
            async with Env(caps=caps) as env:
                s = await self.open(env)
                for text in ("one", "two"):
                    self.assertTrue((await s.req("chat.send", bot="kami", text=text))["ok"])
                c = env.clients["kami"]
                self.assertEqual(c.find("client.capabilities"), [{}])  # asked once, with no flags
                subs = c.find("prompt.submit")
                self.assertEqual([p.get("clarify_batch") for p in subs], [True, True] if want else [None, None])
                self.assertEqual({p["session_id"] for p in subs}, {MAIN_RUNTIME})


class Elsewhere(BridgeCase):
    SESSIONS = [
        {"id": "s-slack", "title": "gateway 502", "source": "slack", "started_at": 1000.0, "message_count": 12, "running": True},
        {"id": "s-discord", "title": "", "source": "discord", "started_at": 3000.0, "message_count": 3, "running": False},
        {"id": "s-tui", "title": "local", "source": "tui", "started_at": 5000.0, "message_count": 1},
        {"id": "s-cli", "title": "cli", "source": "cli", "started_at": 5000.0},
        {"id": "s-omher", "title": "mine", "source": "omher", "started_at": 5000.0},
        {"id": MAIN_STORED, "title": "Bot Chat", "source": "telegram", "started_at": 6000.0},
        {"id": "s-cron", "title": "nightly", "source": "cron", "started_at": 2000.0, "message_count": 2},
    ]

    async def test_filtering_labels_order_and_dedupe(self):
        async with Env(sessions=[dict(r) for r in self.SESSIONS]) as env:
            env.client_kw  # noqa: B018
            s = await self.open(env)
            r = await s.req("elsewhere.list", bot="kami")
            self.assertTrue(r["ok"], r)
            rows = r["result"]["sessions"]
            self.assertEqual([a["id"] for a in rows], ["s-discord", "s-cron", "s-slack"])  # newest first, local+main out, deduped
            by = {a["id"]: a for a in rows}
            self.assertEqual(by["s-discord"]["label"], "Discord session")  # empty title -> "<Source> session"
            self.assertEqual(by["s-discord"]["title"], "")
            self.assertEqual(by["s-slack"]["label"], "gateway 502")
            self.assertTrue(by["s-slack"]["running"])
            self.assertEqual(by["s-slack"]["message_count"], 12)
            for a in rows:
                self.assertEqual(set(a), {"id", "source", "label", "title", "started_at", "last_active", "message_count", "running", "url", "place", "last_reply", "last_reply_at", "reply_target"})
                self.assertTrue(a["label"])

    async def test_active_list_adds_live_sessions_and_caps_at_twenty(self):
        many = [{"id": f"s{i}", "title": f"t{i}", "source": "slack", "started_at": float(i)} for i in range(30)]
        async with Env(sessions=many) as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            env.clients["kami"].active = [{"id": "live-only", "title": "live", "source": "discord", "started_at": 99.0,
                                           "last_active": 500.0, "message_count": 4, "status": "streaming"}]
            rows = (await s.req("elsewhere.list", bot="kami"))["result"]["sessions"]
            self.assertEqual(len(rows), 20)
            self.assertEqual(rows[0]["id"], "live-only")
            self.assertTrue(rows[0]["running"])
            self.assertEqual(rows[0]["last_active"], 500.0)
            self.assertEqual(rows[1]["id"], "s29")

    async def test_peek_parses_slack_author_and_reads_only(self):
        hist = {"s-slack": [
            {"role": "user", "text": "[김희망 (Khope) | Slack user <@U0ABC123>] 게이트웨이 502 났어요", "timestamp": 10.0},
            {"role": "assistant", "text": "확인할게요", "timestamp": 11.0},
            {"role": "tool", "text": "{}", "timestamp": 12.0},
            {"role": "user", "text": "plain without header", "timestamp": 13.0},
            {"role": "assistant", "text": "x" * 900, "timestamp": 14.0},
        ]}
        async with Env(history=hist) as env:
            s = await self.open(env)
            r = await s.req("elsewhere.peek", bot="kami", session_id="s-slack", limit=3)
            self.assertTrue(r["ok"], r)
            msgs, total = r["result"]["messages"], r["result"]["total"]
            self.assertEqual(total, 4)
            self.assertEqual([m["role"] for m in msgs], ["assistant", "user", "assistant"])
            self.assertNotIn("author", msgs[0])
            self.assertNotIn("author", msgs[1])
            self.assertEqual(len(msgs[2]["text"]), 400)
            r = await s.req("elsewhere.peek", bot="kami", session_id="s-slack", limit=10)
            first = r["result"]["messages"][0]
            self.assertEqual(first["author"], "김희망 (Khope)")
            self.assertEqual(first["text"], "게이트웨이 502 났어요")
            self.assertEqual(first["ts"], 10.0)
            c = env.clients["kami"]
            self.assertEqual({p["session_id"] for p in c.find("session.history")}, {"s-slack"})
            for m in ("session.resume", "session.create", "prompt.submit", "session.interrupt"):
                self.assertEqual(c.find(m), [], m)  # a peek never attaches to or writes the session
            self.assertEqual((await s.req("elsewhere.peek", bot="kami"))["error"]["code"], "bad_request")

    async def test_split_author(self):
        self.assertEqual(ob.split_author("[Bob | Discord user <@1>] hi | there"), ("Bob", "hi | there"))
        self.assertEqual(ob.split_author("no header"), (None, "no header"))
        self.assertEqual(ob.split_author("[just brackets] x"), (None, "[just brackets] x"))


class Routines(BridgeCase):
    def write_jobs(self, env: Env, jobs):
        p = env.home / "profiles" / "kami" / "cron"
        p.mkdir(exist_ok=True)
        f = p / "jobs.json"
        f.write_text(json.dumps({"jobs": jobs}))
        st = f.stat()
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000 * (getattr(self, "_bump", 0) + 1)))
        self._bump = getattr(self, "_bump", 0) + 1

    JOB = {"id": "j1", "name": "daily", "schedule_display": "0 9 * * *", "next_run_at": "2026-11-10T09:00:00+09:00",
           "last_run_at": "2026-11-09T09:00:01+09:00", "last_status": "ok", "enabled": True}

    async def test_routines_list_reads_jobs_json(self):
        async with Env() as env:
            self.write_jobs(env, [dict(self.JOB), {"id": "j2", "name": "off", "schedule": {"display": "weekly"}, "enabled": False}])
            s = await self.open(env)
            rows = (await s.req("routines.list", bot="kami"))["result"]["routines"]
            self.assertEqual(rows[0], {"id": "j1", "name": "daily", "schedule": "0 9 * * *", "next_run_at": "2026-11-10T09:00:00+09:00",
                                       "last_run_at": "2026-11-09T09:00:01+09:00", "last_status": "ok", "enabled": True})
            self.assertEqual((rows[1]["schedule"], rows[1]["enabled"], rows[1]["last_run_at"]), ("weekly", False, None))
            self.assertEqual(env.connects, [])  # files only, no gateway
            self.assertEqual((await s.req("routines.list", bot="default"))["result"]["routines"], [])

    async def test_bare_list_format_is_accepted(self):
        async with Env() as env:
            (env.home / "profiles" / "kami" / "cron").mkdir()
            (env.home / "profiles" / "kami" / "cron" / "jobs.json").write_text(json.dumps([dict(self.JOB)]))
            self.assertEqual([r["id"] for r in ob.read_routines(env.home / "profiles" / "kami")], ["j1"])

    async def test_changed_last_run_emits_routine_ran(self):
        async with Env() as env:
            self.write_jobs(env, [dict(self.JOB)])
            s = await self.open(env)
            self.assertEqual(env.bridge.poll_routines(), [])  # first look is the baseline
            self.assertEqual(env.bridge.poll_routines(), [])  # unchanged mtime
            self.write_jobs(env, [{**self.JOB, "last_run_at": "2026-11-10T09:00:02+09:00", "last_status": "error"}])
            self.assertEqual(await env.bridge.poll_routines_once(), 1)
            await s.until(lambda ev: any(e["event"] == "routine.ran" for e in ev))
            ev = [e for e in s.events if e["event"] == "routine.ran"][0]
            self.assertEqual((ev["bot"], ev["routine_id"], ev["name"], ev["status"]), ("kami", "j1", "daily", "error"))
            self.assertAlmostEqual(ev["ts"], 1794268802.0, delta=1)
            self.write_jobs(env, [{**self.JOB, "last_run_at": "2026-11-10T09:00:02+09:00", "last_status": "error", "enabled": False}])
            self.assertEqual(env.bridge.poll_routines(), [])  # same last_run_at -> not a new run
            self.write_jobs(env, [{**self.JOB, "last_run_at": "2026-11-10T09:00:02+09:00"},
                                  {"id": "j9", "name": "new", "last_run_at": "2026-11-10T10:00:00+09:00", "last_status": "ok"}])
            self.assertEqual([j["id"] for _, j in env.bridge.poll_routines()], ["j9"])


class Automations(BridgeCase):
    """The Automations page: jobs read from jobs.json; every change through the bot's own `cron.manage`."""

    JOB = {"id": "j1", "name": "PR digest", "prompt": "Summarise open PRs\nin five lines", "schedule": {"kind": "cron",
           "expr": "0 9 * * 1-5", "display": "0 9 * * 1-5"}, "schedule_display": "0 9 * * 1-5", "enabled": True,
           "state": "scheduled", "deliver": "origin", "repeat": {"times": None, "completed": 4},
           "origin": {"platform": "discord", "chat_id": "1", "chat_name": "OMH Community / #cron / thread"},
           "created_at": "2026-11-03T09:00:00+09:00", "next_run_at": "2026-11-12T09:00:00+09:00",
           "last_run_at": "2026-11-11T09:00:00+09:00", "last_status": "error", "last_error": "timeout"}

    write_jobs = Routines.write_jobs

    async def test_list_tags_each_bot_and_reads_detail_fields(self):
        async with Env(profiles=("kami", "friren")) as env:
            self.write_jobs(env, [dict(self.JOB), {"id": "j2", "name": "off", "enabled": False, "state": "paused",
                                                   "deliver": "bot-chat:kami", "repeat": {"times": 1, "completed": 0}}])
            s = await self.open(env)
            rows = (await s.req("automations.list"))["result"]["automations"]
            self.assertEqual([(r["bot"], r["id"]) for r in rows], [("kami", "j1"), ("kami", "j2")])
            a = rows[0]
            self.assertEqual((a["prompt"], a["deliver"], a["origin"], a["last_error"], a["repeat"], a["paused"]),
                             ("Summarise open PRs\nin five lines", "origin", {"platform": "discord", "place": "#cron"},
                              "timeout", {"times": None, "completed": 4}, False))
            self.assertEqual((rows[1]["paused"], rows[1]["deliver"], rows[1]["repeat"]), (True, "bot-chat:kami", {"times": 1, "completed": 0}))
            self.assertEqual((a["script"], rows[1]["script"]), (None, None))

    async def test_a_script_job_names_its_script_file_only(self):
        """A no-agent job has no prompt; the page shows the script's file name, never its folder."""
        async with Env() as env:
            self.write_jobs(env, [{"id": "s1", "name": "sso", "prompt": "", "script": "/Users/x/scripts/refresh.sh", "no_agent": True}])
            s = await self.open(env)
            row = (await s.req("automations.list"))["result"]["automations"][0]
            self.assertEqual((row["prompt"], row["script"]), ("", "refresh.sh"))
            self.assertEqual(env.connects, [])  # a file read, no gateway

    async def test_writes_go_only_through_cron_manage_with_the_job_id(self):
        async with Env() as env:
            self.write_jobs(env, [dict(self.JOB)])
            s = await self.open(env)
            for op in ("automations.pause", "automations.resume", "automations.remove"):
                self.assertTrue((await s.req(op, bot="kami", job="j1"))["ok"], op)
            r = await s.req("automations.add", bot="kami", name="Digest", schedule="every weekday at 9",
                            prompt="Summarise PRs", deliver="bot-chat:kami")
            self.assertEqual(r["result"], {"job": "new1", "name": "Digest"})
            calls = [(m, p) for m, p in env.clients["kami"].calls if m not in ("client.capabilities",)]
            self.assertEqual(calls, [
                ("cron.manage", {"action": "pause", "name": "j1"}), ("cron.manage", {"action": "resume", "name": "j1"}),
                ("cron.manage", {"action": "remove", "name": "j1"}),
                ("cron.manage", {"action": "add", "name": "Digest", "schedule": "every weekday at 9",
                                 "prompt": "Summarise PRs", "deliver": "bot-chat:kami"})])

    async def test_refusals_and_bad_input_come_back_as_one_line(self):
        async with Env() as env:
            self.write_jobs(env, [dict(self.JOB)])
            s = await self.open(env)
            r = await s.req("automations.add", bot="kami", name="x", schedule="whenever", prompt="y")
            self.assertEqual(r["error"]["code"], "cron_refused")
            self.assertIn("Invalid schedule 'whenever'", r["error"]["message"])
            for bad in ({"job": "nope"}, {"job": "../j1"}, {}):
                self.assertFalse((await s.req("automations.pause", bot="kami", **bad))["ok"], bad)
            r = await s.req("automations.add", bot="kami", name="x", schedule="30m", prompt="y", deliver="discord:1")
            self.assertEqual(r["error"]["code"], "bad_request")
            self.assertEqual([p["action"] for m, p in env.clients["kami"].calls if m == "cron.manage"], ["add"])

    async def test_an_offline_bot_is_one_short_error(self):
        async with Env(fail=("kami",)) as env:
            self.write_jobs(env, [dict(self.JOB)])
            s = await self.open(env)
            r = await s.req("automations.pause", bot="kami", job="j1")
            self.assertEqual(r["error"]["code"], "bot_offline")

    async def test_poll_emits_update_and_added_for_new_ids_but_not_for_omher_own(self):
        async with Env() as env:
            self.write_jobs(env, [dict(self.JOB)])
            s = await self.open(env)
            env.bridge.poll_routines()  # baseline
            self.write_jobs(env, [dict(self.JOB), {"id": "j7", "name": "Made in chat", "schedule_display": "every 30m",
                                                   "deliver": "bot-chat:kami", "created_at": "2026-11-11T10:00:00+09:00"}])
            await env.bridge.poll_routines_once()
            await s.until(lambda ev: any(e["event"] == "routine.added" for e in ev))
            added = [e for e in s.events if e["event"] == "routine.added"]
            self.assertEqual([(e["bot"], e["routine_id"], e["name"], e["schedule"], e["deliver"]) for e in added],
                             [("kami", "j7", "Made in chat", "every 30m", "bot-chat:kami")])
            self.assertIn("routines.update", s.kinds())
            # a job omher added itself through cron.manage is not announced as the bot's
            env.bridge._own_jobs.add(("kami", "j8"))
            self.write_jobs(env, [dict(self.JOB), {"id": "j7", "name": "Made in chat"}, {"id": "j8", "name": "mine"}])
            await env.bridge.poll_routines_once()
            await asyncio.sleep(0.05)
            self.assertEqual(len([e for e in s.events if e["event"] == "routine.added"]), 1)

    async def test_cron_changed_from_the_gateway_triggers_a_reread(self):
        async with Env() as env:
            self.write_jobs(env, [dict(self.JOB)])
            s = await self.open(env)
            env.bridge.poll_routines()
            await s.req("chat.open", bot="kami")
            self.write_jobs(env, [dict(self.JOB), {"id": "j5", "name": "fresh"}])
            env.clients["kami"].push("cron.changed", sid="")
            await s.until(lambda ev: any(e["event"] == "routine.added" for e in ev))

    def test_jobs_json_is_never_opened_for_writing(self):
        """BOUNDARY rule 24: the bridge reads jobs.json and never writes it; changes go through cron.manage."""
        src = (HERE.parent / "omher_bridge.py").read_text(encoding="utf-8")
        import ast
        tree = ast.parse(src)
        jobs_fns = {fn.name for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and any(isinstance(c, ast.Constant) and c.value == "jobs.json" for c in ast.walk(fn))}
        self.assertEqual(jobs_fns, {"_read_jobs", "poll_routines"})
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name in jobs_fns:
                body = ast.unparse(fn)
                for bad in ("write_text", "write_bytes", "open(", "unlink", "rename", "replace(", "os.remove"):
                    self.assertNotIn(bad, body, f"{fn.name}: {bad}")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cron"
            p.mkdir()
            (p / "jobs.json").write_text(json.dumps({"jobs": [dict(self.JOB)]}))
            real_open = open
            modes = []

            def spy(file, mode="r", *a, **k):
                modes.append((str(file), mode))
                return real_open(file, mode, *a, **k)
            with mock.patch("builtins.open", spy), mock.patch("io.open", spy):
                ob.read_automations(Path(tmp))
                ob.read_routines(Path(tmp))
            self.assertTrue(all("w" not in m and "a" not in m and "+" not in m for _, m in modes), modes)

    def test_the_only_gateway_writes_are_cron_and_plugins_manage_with_allowed_actions(self):
        """Every `cron.manage` / `plugins.manage` call site goes through `_cron` / `_plugins`, which refuse any
        action outside the allow-lists (no run, update_all, settings, install from a Git URL)."""
        import ast
        src = (HERE.parent / "omher_bridge.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        owners = {}
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for c in ast.walk(fn):
                    if isinstance(c, ast.Constant) and c.value in ("cron.manage", "plugins.manage"):
                        owners.setdefault(c.value, set()).add(fn.name)
        self.assertEqual(owners, {"cron.manage": {"_cron"}, "plugins.manage": {"_plugins"}})
        self.assertEqual(ob.CRON_ACTIONS, {"add", "pause", "resume", "remove"})
        self.assertEqual(ob.PLUGIN_ACTIONS, {"list", "toggle", "inspect", "install", "update", "remove"})
        for name in ("identifier", "repo", "settings", "update_all", "auto_update", "force", "install_desktop"):
            self.assertNotIn(f'"{name}"', src[src.index("async def _cron("):src.index("def poll_routines(")], name)


class Plugins(BridgeCase):
    CATALOG = {"generated_at": "2026-11-11T00:00:00Z", "entries": [
        {"name": "babysit", "repo": "https://github.com/x/babysit", "sha": "a" * 40, "description": "Watches logs",
         "tier": "community", "category": "automation", "version": "0.2.0",
         "capabilities": {"provides_tools": ["watch_log", "stop_watch"], "provides_hooks": ["on_end"], "requires_env": []}},
        {"name": "homeassistant", "repo": "r", "description": "Home devices", "tier": "official", "category": "platform",
         "capabilities": {"provides_tools": ["ha_on"], "provides_hooks": [], "requires_env": ["HASS_TOKEN"]}},
        {"name": "or-picker", "description": "gone", "tier": "community", "category": "models"}],
        "removed": [{"name": "or-picker", "reason": "folded"}]}

    def write_catalog(self, env: Env, where="profile"):
        d = (env.home / "profiles" / "kami" / "cache") if where == "profile" else (env.home / "cache")
        d.mkdir(parents=True, exist_ok=True)
        (d / "plugin-catalog.json").write_text(json.dumps(self.CATALOG))

    async def test_catalog_reads_the_cache_drops_removed_and_ranks_official_first(self):
        async with Env() as env:
            s = await self.open(env)
            r = (await s.req("plugins.catalog", bot="kami"))["result"]
            self.assertEqual((r["total"], r["entries"]), (0, []))  # no cache: empty, the page asks the bot
            self.write_catalog(env, "root")
            r = (await s.req("plugins.catalog", bot="kami"))["result"]
            self.assertEqual([e["name"] for e in r["entries"]], ["homeassistant", "babysit"])
            self.assertEqual(r["categories"]["automation"], 1)
            self.assertEqual((await s.req("plugins.catalog", bot="kami", query="logs"))["result"]["matched"], 1)
            self.assertEqual((await s.req("plugins.catalog", bot="kami", category="platform"))["result"]["matched"], 1)
            self.assertFalse((await s.req("plugins.catalog", bot="kami", category="nope"))["ok"])
            self.assertEqual(env.connects, [])

    async def test_install_inspects_first_and_passes_the_inspected_sha(self):
        async with Env() as env:
            self.write_catalog(env)
            s = await self.open(env)
            ins = (await s.req("plugins.inspect", bot="kami", catalog_name="babysit"))["result"]
            self.assertEqual((ins["sha"], ins["entry"]["tools"], ins["entry"]["hooks"]), ("abc1234def", ["watch_log", "stop_watch"], ["on_end"]))
            r = (await s.req("plugins.install", bot="kami", catalog_name="babysit", inspected_sha=ins["sha"]))["result"]
            self.assertEqual((r["name"], r["restart_required"]), ("babysit", True))
            self.assertFalse((await s.req("plugins.install", bot="kami", catalog_name="babysit"))["ok"])  # no sha
            self.assertFalse((await s.req("plugins.inspect", bot="kami", catalog_name="not-there"))["ok"])
            # a Git URL or `owner/repo` never reaches Hermes: the catalog by name only (BOUNDARY rule 25)
            for src in ("https://github.com/x/babysit", "x/babysit", "git@github.com:x/babysit.git"):
                r = await s.req("plugins.install", bot="kami", catalog_name=src, inspected_sha="abc1234")
                self.assertEqual(r["error"]["code"], "bad_request", src)
                self.assertEqual((await s.req("plugins.inspect", bot="kami", catalog_name=src))["error"]["code"], "bad_request")
            calls = [p for m, p in env.clients["kami"].calls if m == "plugins.manage"]
            self.assertEqual(calls, [{"action": "inspect", "catalog_name": "babysit"},
                                     {"action": "install", "catalog_name": "babysit", "enable": True, "inspected_sha": "abc1234def"}])

    async def test_list_toggle_update_remove_through_plugins_manage(self):
        async with Env() as env:
            self.write_catalog(env)
            s = await self.open(env)
            rows = (await s.req("plugins.list", bot="kami"))["result"]["plugins"]
            self.assertEqual([(r["name"], r["enabled"], r["tier"], r["needs_env"]) for r in rows],
                             [("homeassistant", True, "official", []), ("browserbase", False, "bundled", ["BROWSERBASE_API_KEY"])])
            # live_tools: what the plugin registered in the running gateway (Hermes' loader record), never the catalog
            self.assertEqual([r["live_tools"] for r in rows], [2, 0])
            self.assertTrue((await s.req("plugins.toggle", bot="kami", key="homeassistant", enable=False))["ok"])
            self.assertFalse((await s.req("plugins.toggle", bot="kami", key="homeassistant"))["ok"])
            self.assertTrue((await s.req("plugins.update", bot="kami", name="homeassistant"))["ok"])
            self.assertTrue((await s.req("plugins.remove", bot="kami", name="homeassistant"))["ok"])
            acts = [p for m, p in env.clients["kami"].calls if m == "plugins.manage"]
            self.assertEqual(acts, [{"action": "list"}, {"action": "toggle", "key": "homeassistant", "enable": False},
                                    {"action": "update", "name": "homeassistant"}, {"action": "remove", "name": "homeassistant"}])

    async def test_a_new_plugin_folder_emits_plugin_added_once(self):
        async with Env() as env:
            self.write_catalog(env)
            s = await self.open(env)
            env.bridge.poll_plugins()  # baseline
            (env.home / "profiles" / "kami" / "plugins" / "babysit").mkdir(parents=True)
            self.assertEqual(await env.bridge.poll_plugins_once(), 1)
            await s.until(lambda ev: any(e["event"] == "plugin.added" for e in ev))
            ev = [e for e in s.events if e["event"] == "plugin.added"][0]
            self.assertEqual((ev["bot"], ev["name"], ev["tools"], ev["hooks"]), ("kami", "babysit", 2, 1))
            self.assertEqual(await env.bridge.poll_plugins_once(), 0)
            env.bridge._own_plugins.add(("kami", "mine"))
            (env.home / "profiles" / "kami" / "plugins" / "mine").mkdir()
            self.assertEqual(await env.bridge.poll_plugins_once(), 0)


class ReadOnlyRule(BridgeCase):
    """No Hermes call that attaches to or writes a session may carry any id but the bot's main chat."""

    GUARDED = ("prompt.submit", "session.resume", "session.interrupt", "approval.respond", "clarify.respond",
               "session.mutate", "session.title", "session.steer", "session.redirect", "session.activate",
               "image.attach_bytes", "pdf.attach", "file.attach")

    async def test_no_guarded_call_carries_a_foreign_session_id(self):
        foreign = "20261108_235229_aaaf70c4"
        hist = {foreign: [{"role": "user", "text": "[A | Slack user <@U1>] hi", "timestamp": 1.0}]}
        sessions = [{"id": foreign, "title": "slack thing", "source": "slack", "started_at": 1.0, "running": True}]
        async with Env(sessions=sessions, history=hist) as env:
            s = await self.open(env)
            for op, kw in [("chat.open", {}), ("chat.send", {"text": "hi", "session_id": foreign}),
                           ("elsewhere.list", {}), ("elsewhere.peek", {"session_id": foreign}),
                           ("chat.interrupt", {"session_id": foreign}),
                           ("approval.respond", {"request_id": "ap-x", "choice": "deny", "session_id": foreign}),
                           ("clarify.respond", {"request_id": "cl-x", "answer": "x", "session_id": foreign}),
                           ("chat.set_model", {"reasoning": "low", "session_id": foreign}),
                           ("chat.attach", {"kind": "image", "name": "a.png", "data_base64": "iVBO", "session_id": foreign}),
                           ("models.options", {}), ("routines.list", {})]:
                await s.req(op, bot="kami", **kw)
            c = env.clients["kami"]
            allowed = {MAIN_RUNTIME, MAIN_STORED}
            seen = 0
            for method, params in c.calls:
                if method in self.GUARDED:
                    seen += 1
                    self.assertIn(params.get("session_id"), allowed, f"{method} carried {params.get('session_id')}")
                for k, v in params.items():  # and the foreign id appears nowhere but a history read
                    if v == foreign:
                        self.assertEqual(method, "session.history", f"{method}.{k}")
            self.assertGreaterEqual(seen, 7)
            self.assertEqual(len(c.find("prompt.submit")), 1)

    def test_source_has_exactly_one_submit_call_site(self):
        src = (HERE.parent / "omher_bridge.py").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"prompt\.submit", src)), 1)
        sites = re.findall(r"self\._submit\(([^)]*)\)", src)
        self.assertEqual(sites, ["conn, main, text, input_id"])

    def test_bridge_makes_no_model_or_http_call(self):
        src = (HERE.parent / "omher_bridge.py").read_text(encoding="utf-8")
        # Whole words: the gateway's own `open_requests` snapshot key is not the `requests` library.
        for needle in ("urllib.request", "requests", "httpx", "aiohttp", "openai", "anthropic"):
            self.assertIsNone(re.search(rf"\b{re.escape(needle)}\b", src), needle)

    def test_the_only_programs_it_runs_are_read_only_git_one_gh_read_and_hermes_restart(self):
        """BOUNDARY rules 10, 21 and 29: `git` reads in _git, `gh pr view` in gh_pr_view (RunsPr pins its argv), and
        Hermes' own `gateway restart` for one bot in run_hermes_restart (RestartArgv pins its argv)."""
        import ast
        src = (HERE.parent / "omher_bridge.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        uses = []
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for n in ast.walk(fn):
                    if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "subprocess" \
                            and n.attr in ("run", "Popen", "call", "check_call", "check_output"):
                        uses.append(fn.name)
        self.assertEqual(uses, ["_git", "gh_pr_view", "run_hermes_restart"])
        self.assertNotIn("create_subprocess", src)
        self.assertNotIn("os.system", src)
        self.assertEqual(ob.GIT_READS, {("worktree", "list"), ("rev-parse",), ("status",), ("diff",), ("log",),
                                        ("version",), ("config",)})
        for bad in (["push"], ["commit", "-m", "x"], ["checkout", "main"], ["worktree", "add", "x"], ["reset", "--hard"],
                    ["apply"], ["clean", "-fd"], ["config", "user.name", "x"], ["config", "--list"],
                    ["config", "--get-regexp", "x"]):
            with self.assertRaises(ValueError, msg=bad):
                ob._git(bad, ".")


class FolderChats(BridgeCase):
    """SESSIONS > oh-my-hermes: a Hermes chat in a picked folder, through the same event path as the bot chat."""

    async def test_open_send_events_answer_and_close(self):
        with tempfile.TemporaryDirectory() as folder:
            async with Env() as env:
                s = await self.open(env)
                r = await s.req("folder.open", bot="kami", cwd=folder)
                self.assertTrue(r["ok"], r)
                fid = r["result"]["session"]
                self.assertEqual(r["result"]["cwd"], folder)
                c = env.clients["kami"]
                create = c.find("session.create")
                self.assertEqual(len(create), 1)
                self.assertEqual(create[0]["cwd"], folder)
                self.assertTrue(create[0]["cwd_explicit"])
                self.assertEqual(create[0]["title"], "omher · " + Path(folder).name)
                self.assertEqual(c.find("session.list"), [])  # never looks for or touches the Bot Chat

                await s.req("chat.send", bot="kami", session=fid, text="list the files")
                sub = c.find("prompt.submit")
                self.assertEqual([x["session_id"] for x in sub], ["rt-folder-0"])
                # the folder chat's events carry its id; the main chat's do not
                c.push("message.start", {}, sid="rt-folder-0")
                c.push("tool.start", {"tool_id": "t1", "name": "terminal", "args": {"command": "ls"}}, sid="rt-folder-0")
                c.push("approval.request", {"prompt_id": "ap9", "command": "rm x", "description": "Delete", "choices": ["once", "deny"]},
                       sid="rt-folder-0", execution_generation=2)
                await s.until(lambda ev: any(e["event"] == "approval.request" for e in ev))
                folder_ev = [e for e in s.events if e["event"] in ("turn.start", "tool.start", "approval.request")]
                self.assertTrue(all(e.get("session") == fid for e in folder_ev), folder_ev)
                self.assertNotIn("bot.status", [e["event"] for e in s.events if e.get("session")])
                r = await s.req("approval.respond", bot="kami", session=fid, request_id="ap9", choice="once")
                self.assertTrue(r["ok"], r)
                self.assertEqual(c.find("approval.respond")[-1], {"session_id": "rt-folder-0", "prompt_id": "ap9", "choice": "once",
                                                                  "execution_generation": 2})
                await s.req("chat.interrupt", bot="kami", session=fid)
                self.assertEqual(c.find("session.interrupt")[-1]["session_id"], "rt-folder-0")
                c.push("message.complete", {"text": "two files", "status": "complete"}, sid="rt-folder-0")
                await s.until(lambda ev: any(e["event"] == "turn.end" for e in ev))
                msg = [e for e in s.events if e["event"] == "message"][0]
                self.assertEqual((msg["session"], msg["text"]), (fid, "two files"))

                self.assertTrue((await s.req("folder.close", bot="kami", session=fid))["ok"])
                self.assertEqual(c.find("session.detach"), [{"session_id": "rt-folder-0", "subscription_id": "sub-folder-0",
                                                             "end_reason": "omher_close"}])
                self.assertEqual(c.find("session.close"), [])
                r = await s.req("chat.send", bot="kami", session=fid, text="again")
                self.assertEqual(r["error"]["code"], "not_found")
                self.assertEqual(len(c.find("prompt.submit")), 1)

    async def test_close_ends_the_hermes_conversation_on_a_gateway_without_session_close(self):
        """Hermes 0.23's gateway has `session.detach` and no `session.close`: closing the folder chat detaches the
        subscription `session.create` gave, as a close (`end_reason`), so Hermes ends the conversation, and the
        close reports no error. A gateway that has no `session.detach` gets `session.close`, as before."""
        with tempfile.TemporaryDirectory() as folder:
            async with Env(lacks={"session.close"}) as env:
                s = await self.open(env)
                fid = (await s.req("folder.open", bot="kami", cwd=folder))["result"]["session"]
                c = env.clients["kami"]
                r = await s.req("folder.close", bot="kami", session=fid)
                self.assertTrue(r["ok"], r)
                self.assertEqual([m for m, _ in c.calls if m in ("session.detach", "session.close")], ["session.detach"])
                self.assertEqual(c.find("session.detach")[0], {"session_id": "rt-folder-0", "subscription_id": "sub-folder-0",
                                                               "end_reason": "omher_close"})
            async with Env(lacks={"session.detach"}) as env:
                s = await self.open(env)
                fid = (await s.req("folder.open", bot="kami", cwd=folder))["result"]["session"]
                c = env.clients["kami"]
                r = await s.req("folder.close", bot="kami", session=fid)
                self.assertTrue(r["ok"], r)
                self.assertEqual([m for m, _ in c.calls if m in ("session.detach", "session.close")], ["session.detach", "session.close"])
                self.assertEqual(c.find("session.close"), [{"session_id": "rt-folder-0"}])
            # any other refusal of the detach is the close's error, and nothing else is tried
            async with Env() as env:
                s = await self.open(env)
                fid = (await s.req("folder.open", bot="kami", cwd=folder))["result"]["session"]
                c = env.clients["kami"]
                real_rpc = c.rpc

                async def refuse(method, **params):
                    if method == "session.detach":
                        c.calls.append((method, params))
                        raise GatewayRPCError("invalid_params")
                    return await real_rpc(method, **params)

                c.rpc = refuse
                r = await s.req("folder.close", bot="kami", session=fid)
                self.assertEqual(r["error"]["code"], "invalid_params")
                self.assertEqual(c.find("session.close"), [])

    async def test_hermes_titles_reach_the_folder_chat_and_the_create_name_does_not(self):
        with tempfile.TemporaryDirectory() as folder:
            async with Env() as env:
                s = await self.open(env)
                fid = (await s.req("folder.open", bot="kami", cwd=folder))["result"]["session"]
                c = env.clients["kami"]
                c.push("session.title", {"session_id": "rt-folder-0", "title": "omher · " + Path(folder).name}, sid="rt-folder-0")
                c.push("session.title", {"session_id": "rt-folder-0", "title": "Fix the  login\nredirect"}, sid="rt-folder-0")
                c.push("session.title", {"session_id": "main", "title": "Bot Chat"})
                await s.until(lambda ev: any(e["event"] == "session.title" for e in ev))
                titles = [e for e in s.events if e["event"] == "session.title"]
                self.assertEqual([(e["bot"], e["session"], e["title"]) for e in titles], [("kami", fid, "Fix the login redirect")])

    async def test_refuses_bad_folders_and_foreign_ids(self):
        async with Env() as env:
            s = await self.open(env)
            for cwd in (None, "", "relative/dir", "/no/such/folder/x9", 5):
                r = await s.req("folder.open", bot="kami", cwd=cwd)
                self.assertEqual(r["error"]["code"], "bad_request", cwd)
            for op, kw in (("chat.send", {"text": "x"}), ("chat.interrupt", {}), ("folder.close", {}),
                           ("approval.respond", {"request_id": "a", "choice": "deny"})):
                for sid in ("20261108_235229_aaaf70c4", MAIN_RUNTIME, "rt-folder-0", 3):
                    r = await s.req(op, bot="kami", session=sid, **kw)
                    self.assertEqual(r["error"]["code"], "not_found", (op, sid))
            c = env.clients["kami"]
            self.assertEqual(c.find("prompt.submit"), [])
            self.assertEqual(c.find("session.close"), [])
            self.assertEqual(c.find("session.create"), [])

    async def test_folder_chat_asks_share_the_needs_you_path(self):
        """A folder chat's asks take the main chat's path: clarify_batch on submit, an interview answered by
        clarify.lock per question, timeouts and expiry, all tagged with the folder chat and kept apart from
        the main chat's."""
        with tempfile.TemporaryDirectory() as folder:
            async with Env(caps={"canonical_clarify_batch": True}) as env:
                t = [1000.0]
                env.bridge.clock = lambda: t[0]
                s = await self.open(env)
                fid = (await s.req("folder.open", bot="kami", cwd=folder))["result"]["session"]
                c = env.clients["kami"]
                self.assertTrue((await s.req("chat.send", bot="kami", session=fid, text="plan it"))["ok"])
                self.assertEqual([(p["session_id"], p.get("clarify_batch")) for p in c.find("prompt.submit")],
                                 [("rt-folder-0", True)])
                c.events.put_nowait({"jsonrpc": "2.0", "id": "srq-f", "method": "clarify",
                                     "params": {"session_id": "rt-folder-0", "timeout_s": 120,
                                                "questions": NeedsYou.QUESTIONS[:2]}})
                c.push("approval.request", {"prompt_id": "apf", "command": "rm x", "choices": ["once", "deny"],
                                            "timeout_s": 30}, sid="rt-folder-0", execution_generation=3)
                await s.until(lambda ev: any(e["event"] == "approval.request" for e in ev))
                await s.until(lambda ev: any(e["event"] == "clarify.request" for e in ev))
                iv = [e for e in s.events if e["event"] == "clarify.request"][0]
                self.assertEqual((iv["session"], iv["request_id"], iv["timeout_s"]), (fid, "srq-f", 120))
                self.assertEqual([q["qid"] for q in iv["questions"]], ["q1", "q2"])
                # answered without `session`, the id is the main chat's business: no lock, nothing reaches the folder chat
                await s.req("clarify.respond", bot="kami", request_id="srq-f", answers={"q1": "x"})
                self.assertEqual(c.find("clarify.lock"), [])
                self.assertEqual({p["session_id"] for p in c.find("clarify.respond")}, {MAIN_RUNTIME})
                r = await s.req("clarify.respond", bot="kami", session=fid, request_id="srq-f",
                                answers={"q1": "Users", "q2": None})
                self.assertTrue(r["ok"], r)
                self.assertEqual(c.find("clarify.lock"), [
                    {"request_id": "srq-f", "question_id": "q1", "answer": "Users"},
                    {"request_id": "srq-f", "question_id": "q2", "answer": None}])
                self.assertNotIn("rt-folder-0", {p["session_id"] for p in c.find("clarify.respond")})
                # the approval goes unanswered past its 30 s: settled -> expired as a timeout, tagged
                t[0] = 1031.0
                c.push("approval.settled", {"prompt_id": "apf"}, sid="rt-folder-0")
                await s.until(lambda ev: any(e["event"] == "prompt.expired" for e in ev))
                exp = [e for e in s.events if e["event"] == "prompt.expired"]
                self.assertEqual([(e["request_id"], e["reason"], e.get("session")) for e in exp], [("apf", "timeout", fid)])

    async def test_gateway_loss_closes_folder_chats(self):
        with tempfile.TemporaryDirectory() as folder:
            async with Env() as env:
                s = await self.open(env)
                fid = (await s.req("folder.open", bot="kami", cwd=folder))["result"]["session"]
                c = env.clients["kami"]
                c.push("message.start", {}, sid="rt-folder-0")
                await s.until(lambda ev: any(e["event"] == "turn.start" for e in ev))
                c.events.put_nowait(GatewayClientError("gateway went away"))
                await s.until(lambda ev: any(e["event"] == "folder.closed" for e in ev))
                end = [e for e in s.events if e["event"] == "turn.end" and e.get("session") == fid]
                self.assertEqual(end[0]["outcome"], "error")


class Attach(BridgeCase):
    """chat.attach: Hermes' own attach calls, in the main chat only, with the bytes the app sent."""

    async def test_each_kind_takes_its_hermes_call_with_the_main_id(self):
        async with Env() as env:
            s = await self.open(env)
            img = await s.req("chat.attach", bot="kami", kind="image", name="a.png", data_base64="iVBO")
            pdf = await s.req("chat.attach", bot="kami", kind="pdf", name="r.pdf", data_base64="JVBERi0=")
            fil = await s.req("chat.attach", bot="kami", kind="file", name="clip.mp4", data_base64="AAAA",
                              session_id="20261108_235229_aaaf70c4", path="/etc/hosts")
            self.assertEqual(img["result"], {"kind": "image", "name": "a.png", "text": "[User attached image: upload_1.png]",
                                             "ref_text": ""})
            self.assertEqual(pdf["result"]["text"], "[User attached PDF: r.pdf (2 page(s))]")
            self.assertEqual(fil["result"]["ref_text"], "@file:attachments/clip.mp4")
            c = env.clients["kami"]
            self.assertEqual(c.find("image.attach_bytes"), [{"session_id": MAIN_RUNTIME, "content_base64": "iVBO", "filename": "a.png"}])
            self.assertEqual(c.find("pdf.attach"), [{"session_id": MAIN_RUNTIME, "content_base64": "JVBERi0=", "filename": "r.pdf"}])
            # the client's session_id and path are never forwarded: bytes only, main chat only
            self.assertEqual(c.find("file.attach"), [{"session_id": MAIN_RUNTIME, "name": "clip.mp4",
                                                      "data_url": "data:application/octet-stream;base64,AAAA"}])
            self.assertEqual(c.find("prompt.submit"), [])  # attaching never sends

    async def test_refusals(self):
        async with Env() as env:
            s = await self.open(env)
            bad = await s.req("chat.attach", bot="kami", kind="image", name="a.png", data_base64="bad")
            self.assertEqual(bad["error"]["code"], "attach_failed")
            self.assertIn("unsupported image", bad["error"]["message"])
            for kw in ({"kind": "exe", "name": "a", "data_base64": "AA"}, {"kind": "file", "name": "", "data_base64": "AA"},
                       {"kind": "file", "name": "a"}):
                r = await s.req("chat.attach", bot="kami", **kw)
                self.assertEqual(r["error"]["code"], "bad_request", kw)
            big = await s.req("chat.attach", bot="kami", kind="file", name="big.bin", data_base64="A" * (ob.ATTACH_B64_MAX + 4))
            self.assertEqual(big["error"]["code"], "too_big")
            # only the well-formed one reached Hermes
            self.assertEqual([m for m, _ in env.clients["kami"].calls if "attach" in m], ["image.attach_bytes"])


class Discovery(unittest.TestCase):
    def test_discover_bots_reads_files(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            (home / "config.yaml").write_text("model: plain-model\n")
            (home / "profiles" / "a").mkdir(parents=True)
            (home / "profiles" / "a" / "config.yaml").write_text("model:\n  default: m\n  provider: p\n")
            (home / "profiles" / "a" / "profile.yaml").write_text("display_name: Alpha\ndescription: first\n")
            (home / "profiles" / "junk").mkdir()  # no config.yaml -> not a profile
            bots = {b["name"]: b for b in ob.discover_bots(home)}
            self.assertEqual(set(bots), {"default", "a"})
            self.assertEqual((bots["default"]["display_name"], bots["default"]["model"]), ("Hermes", "plain-model"))
            self.assertEqual((bots["a"]["display_name"], bots["a"]["description"], bots["a"]["provider"]), ("Alpha", "first", "p"))

    def test_parsed_yaml_is_cached_until_the_file_changes(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "config.yaml"
            path.write_text("model: one\n", encoding="utf-8")
            first = ob._load_yaml(path)
            self.assertEqual(first, {"model": "one"})
            self.assertIs(ob._load_yaml(path), first)  # unchanged file: no second parse
            st = path.stat()
            path.write_text("model: two\n", encoding="utf-8")  # same size: only the mtime tells them apart
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
            self.assertEqual(ob._load_yaml(path), {"model": "two"})
            path.unlink()
            self.assertEqual(ob._load_yaml(path), {})


if __name__ == "__main__":
    unittest.main()


class HermesPath(unittest.TestCase):
    """D1: starting a gateway imports Hermes' top-level modules (hermes_dir_acl, …) that its venv does
    not install; the bridge must put the checkout on sys.path even when `hermes_cli` already imports."""

    def test_root_is_added_even_when_hermes_cli_imports(self):
        import omher_bridge
        with tempfile.TemporaryDirectory() as d:
            path: list = ["/somewhere/site-packages"]
            omher_bridge.ensure_hermes_on_path(Path(d), path)
            self.assertEqual(path[0], d)
            omher_bridge.ensure_hermes_on_path(Path(d), path)
            self.assertEqual(path.count(d), 1)

    def test_missing_root_is_ignored(self):
        import omher_bridge
        path: list = []
        omher_bridge.ensure_hermes_on_path(Path("/nonexistent/hermes-agent"), path)
        self.assertEqual(path, [])

    def test_pm_install_activates_its_committed_dependencies(self):
        import types
        import omher_bridge
        calls: list = []
        envs = types.ModuleType("pm.environments")
        setattr(envs, "activate_dependencies", calls.append)
        with mock.patch.dict(sys.modules, {"pm": types.ModuleType("pm"), "pm.environments": envs}):
            omher_bridge.activate_hermes_dependencies(Path("/h/hermes-agent"))
        self.assertEqual(calls, [Path("/h/hermes-agent")])

    def test_install_without_pm_keeps_its_own_path(self):
        import omher_bridge
        with mock.patch.dict(sys.modules, {"pm": None, "pm.environments": None}):
            omher_bridge.activate_hermes_dependencies(Path("/h/hermes-agent"))

    def test_read_only_uri_survives_odd_folder_names(self):
        import sqlite3
        import omher_bridge
        with tempfile.TemporaryDirectory() as d:
            # '#', '%' and spaces are legal everywhere; '?' only outside Windows
            folder = Path(d) / ("a b#c%e@f" if os.name == "nt" else "a b#c?d%e@f")
            folder.mkdir()
            db = folder / "state.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE t (x)")
            con.execute("INSERT INTO t VALUES (1)")
            con.commit()
            con.close()
            uri = omher_bridge.ro_uri(db)
            self.assertTrue(uri.startswith("file:///") or uri.startswith("file://"), uri)
            self.assertTrue(uri.endswith("?mode=ro"), uri)
            ro = sqlite3.connect(uri, uri=True)
            try:
                self.assertEqual(ro.execute("SELECT x FROM t").fetchall(), [(1,)])
                with self.assertRaises(sqlite3.OperationalError):
                    ro.execute("INSERT INTO t VALUES (2)")
            finally:
                ro.close()

    def test_default_home_follows_hermes_on_each_platform(self):
        import omher_bridge
        home = omher_bridge.default_hermes_home
        self.assertEqual(home({}, "darwin"), Path.home() / ".hermes")
        self.assertEqual(home({}, "linux"), Path.home() / ".hermes")
        self.assertEqual(home({"LOCALAPPDATA": "C:/Users/k/AppData/Local"}, "win32"),
                         Path("C:/Users/k/AppData/Local") / "hermes")
        self.assertEqual(home({}, "win32"), Path.home() / "AppData" / "Local" / "hermes")
        self.assertEqual(home({"HERMES_HOME": "/srv/h", "LOCALAPPDATA": "C:/L"}, "win32"), Path("/srv/h"))
        self.assertEqual(home({"HERMES_HOME": "  "}, "darwin"), Path.home() / ".hermes")

    def test_a_url_in_the_last_reply_stays_readable(self):
        import omher_bridge
        g = omher_bridge.reply_gist
        self.assertEqual(g("배포가 끝나면 https://omher.app/docs/skills/ 에서 열립니다."),
                         "배포가 끝나면 omher.app/docs/skills 에서 열립니다.")
        long = "See https://github.com/rlaope/oh-my-hermes/pull/2705/files?diff=split&w=1 for the diff."
        self.assertEqual(g(long), "See github.com for the diff.")
        self.assertEqual(g("Link: [the PR](https://x.y/1) is up."), "Link: the PR is up.")

    def test_a_url_stops_at_the_korean_particle_glued_to_it(self):
        g = ob.reply_gist
        self.assertEqual(g("자세한 건 https://github.com/rlaope/oh-my-hermes/pull/2695에서 확인하세요."),
                         "자세한 건 github.com/rlaope/oh-my-hermes/pull/2695에서 확인하세요.")
        # a path over 40 chars is cut to its host, and the particle still stays
        self.assertEqual(g("자세한 건 https://github.com/rlaope/oh-my-hermes/pull/2695/files에서 확인하세요."),
                         "자세한 건 github.com에서 확인하세요.")
        self.assertEqual(g("https://omher.app/docs를 보세요"), "omher.app/docs를 보세요")

    def test_markdown_strip_leaves_underscores_inside_urls(self):
        g = ob.reply_gist
        self.assertEqual(g("Repo: https://github.com/foo_bar/baz_qux is __new__."),
                         "Repo: github.com/foo_bar/baz_qux is new.")
        self.assertEqual(g("**https://x.y/a_b**"), "x.y/a_b")

    def test_files_the_bot_sent_show_as_clip_and_name_never_a_path(self):
        g = ob.reply_gist
        self.assertEqual(g("Here is the chart.\n\nMEDIA:/Users/k/media/chart_v2.png\nMEDIA:/Users/k/report.zip"),
                         "Here is the chart. \U0001f4ce chart_v2.png \U0001f4ce report.zip")
        self.assertEqual(g("MEDIA:C:\\Users\\k\\shot.png"), "\U0001f4ce shot.png")
        self.assertNotIn("/Users/k", g("Done:\nMEDIA:/Users/k/media/a.png"))
        # a MEDIA line inside fenced code is text, as the UI and media.read read it
        self.assertEqual(g("```\nMEDIA:/a/b.png\n```"), "MEDIA:/a/b.png")

    def test_query_and_fragment_are_never_shown(self):
        g = ob.reply_gist
        self.assertEqual(g("Open https://example.com/p?token=abc123 now"), "Open example.com/p now")
        self.assertEqual(g("Open https://example.com?token=abc123"), "Open example.com")
        self.assertEqual(g("See https://x.y/doc#secret-part."), "See x.y/doc.")
        self.assertNotIn("abc123", g("https://a.b/c?x=1&token=abc123#f"))

    def test_trailing_punctuation_and_brackets_stay_outside_the_url(self):
        g = ob.reply_gist
        self.assertEqual(g("(see https://x.y/a)"), "(see x.y/a)")
        self.assertEqual(g("Done: https://x.y/a."), "Done: x.y/a.")
        self.assertEqual(g("Read https://en.wikipedia.org/wiki/Foo_(bar), then go."),
                         "Read en.wikipedia.org/wiki/Foo_(bar), then go.")
        self.assertEqual(g("끝 (https://x.y/a)."), "끝 (x.y/a).")

    def test_a_profile_home_shows_every_bot(self):
        # omher started from a profile-scoped shell (HERMES_HOME=<root>/profiles/kami) must still list the root
        # Hermes and every profile, not only that one profile as "Hermes".
        import omher_bridge
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / ".hermes"
            (root / "profiles" / "kami").mkdir(parents=True)
            (root / "config.yaml").write_text("model: a\n", encoding="utf-8")
            (root / "profiles" / "kami" / "config.yaml").write_text("model: b\n", encoding="utf-8")
            home = omher_bridge.default_hermes_home({"HERMES_HOME": str(root / "profiles" / "kami")}, "darwin")
            self.assertEqual(home, root)
            self.assertEqual([b["name"] for b in omher_bridge.discover_bots(home)], ["default", "kami"])
            # a custom home that only looks like a profile (no root config) is kept as given
            lone = Path(d) / "x" / "profiles" / "p"
            lone.mkdir(parents=True)
            self.assertEqual(omher_bridge.default_hermes_home({"HERMES_HOME": str(lone)}, "darwin"), lone)

    def test_signal_setup_survives_a_loop_without_signal_handlers(self):
        import omher_bridge

        class WindowsLoop:
            def add_signal_handler(self, *a):
                raise NotImplementedError

        omher_bridge._stop_on_signals(WindowsLoop(), asyncio.Event())  # must not raise

    def test_default_root_on_windows_reads_scripts_python(self):
        import omher_bridge
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "hermes-agent"
            (root / "hermes_cli").mkdir(parents=True)
            (root / "venv" / "Scripts").mkdir(parents=True)
            real = sys.executable
            try:
                sys.executable = str(root / "venv" / "Scripts" / "python.exe")
                self.assertEqual(omher_bridge._default_hermes_root(), root)
            finally:
                sys.executable = real

    def test_default_root_comes_from_the_interpreter_venv(self):
        import omher_bridge
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "hermes-agent"
            (root / "hermes_cli").mkdir(parents=True)
            (root / "venv" / "bin").mkdir(parents=True)
            fake = root / "venv" / "bin" / "python"
            real = sys.executable
            try:
                sys.executable = str(fake)
                self.assertEqual(omher_bridge._default_hermes_root(), root)
            finally:
                sys.executable = real


class ToolDetail(unittest.TestCase):
    """The activity line shows what actually ran, not Hermes' summary ("date + 1 command")."""

    def test_terminal_shows_the_real_command(self):
        import omher_bridge
        self.assertEqual(omher_bridge.tool_detail("terminal", {"command": "date &&\n  sw_vers -productVersion"},
                                                  "date + 1 command"), "date && sw_vers -productVersion")

    def test_path_url_query_and_helper_goal(self):
        import omher_bridge
        self.assertEqual(omher_bridge.tool_detail("read_file", {"path": "gateway/run.py"}, "run.py"), "gateway/run.py")
        self.assertEqual(omher_bridge.tool_detail("web_extract", {"urls": ["https://a.b/c"]}, "a.b"), "https://a.b/c")
        self.assertEqual(omher_bridge.tool_detail("delegate_task", {"tasks": [{"goal": "Fix A"}, {"goal": "Fix B"}]},
                                                  "2 tasks"), "Fix A (+1 more)")

    def test_unknown_tool_or_missing_arg_keeps_hermes_context_and_clips(self):
        import omher_bridge
        self.assertEqual(omher_bridge.tool_detail("mystery", {}, "ctx"), "ctx")
        self.assertEqual(omher_bridge.tool_detail("terminal", {}, "fallback"), "fallback")
        self.assertEqual(len(omher_bridge.tool_detail("terminal", {"command": "x" * 500}, "")), 160)


class OriginLinks(unittest.TestCase):
    """Elsewhere sessions link to their thread; the origin comes from the profile's state.db, read-only."""

    def _db(self, d: Path, rows, messages=()):
        import sqlite3
        con = sqlite3.connect(d / "state.db")
        con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, origin_json TEXT)")
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL)")
        con.executemany("INSERT INTO sessions VALUES (?, ?)", [(i, json.dumps(o) if o else None) for i, o in rows])
        con.executemany("INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)", messages)
        con.commit()
        con.close()

    def test_last_reply_is_the_bots_latest_answer_as_plain_text(self):
        import omher_bridge
        with tempfile.TemporaryDirectory() as d:
            self._db(Path(d), [("s1", {"platform": "slack", "chat_id": "C1"}), ("s2", None)], [
                ("s1", "assistant", "old answer", 1.0),
                ("s1", "user", "question", 2.0),
                ("s1", "assistant", "**배포 끝났습니다.** <@U1> [PR](https://x/y)를 보세요.\n\n- detail", 3.0),
                ("s1", "assistant", "   ", 4.0),
                ("s2", "user", "only a question", 1.0),
            ])
            f = omher_bridge.read_session_facts(Path(d), ["s1", "s2"])
        self.assertEqual(f["s1"]["last_reply"], "배포 끝났습니다. PR를 보세요.")
        self.assertEqual(f["s1"]["last_reply_at"], 3.0)
        self.assertNotIn("s2", f)

    def test_reply_gist_clips_at_a_sentence(self):
        import omher_bridge
        long = "첫 문장입니다. " * 10 + "x" * 300
        g = omher_bridge.reply_gist(long, n=100)
        self.assertTrue(g.endswith("다."), g)
        self.assertLessEqual(len(g), 100)
        self.assertEqual(omher_bridge.reply_gist("y" * 300, n=50), "y" * 50 + "…")

    def test_slack_and_discord_links_and_places(self):
        import omher_bridge
        with tempfile.TemporaryDirectory() as d:
            self._db(Path(d), [
                ("s1", {"platform": "slack", "chat_id": "C9", "chat_name": "product-opengateway", "thread_id": "1794186944.520669",
                        "guild_id": "T5"}),
                ("d1", {"platform": "discord", "chat_id": "456", "guild_id": "123",
                        "chat_name": "Oh-My-Hermes Community / #cron / long thread title"}),
                ("c1", None),
            ])
            o = omher_bridge.read_origins(Path(d), ["s1", "d1", "c1", "missing"])
        self.assertEqual(set(o), {"s1", "d1"})
        self.assertEqual(omher_bridge.origin_link("slack", o["s1"]),
                         ("slack://channel?team=T5&id=C9&thread_ts=1794186944.520669", "#product-opengateway"))
        self.assertEqual(omher_bridge.origin_link("discord", o["d1"]), ("https://discord.com/channels/123/456", "#cron"))
        self.assertEqual(omher_bridge.origin_link("cron", {}), (None, None))

    def test_db_is_opened_read_only(self):
        import omher_bridge
        with tempfile.TemporaryDirectory() as d:
            self._db(Path(d), [("s1", {"platform": "slack", "chat_id": "C1"})])
            before = (Path(d) / "state.db").stat().st_mtime_ns
            omher_bridge.read_origins(Path(d), ["s1"])
            self.assertEqual((Path(d) / "state.db").stat().st_mtime_ns, before)

    def test_missing_db_gives_nothing(self):
        import omher_bridge
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(omher_bridge.read_origins(Path(d), ["x"]), {})


class LinkPlaces(unittest.TestCase):
    """links.places: channel names for Slack / Discord link chips, from the bot's own sessions' origins, read-only."""

    def _db(self, d: Path, origins, messages=False):
        import sqlite3
        con = sqlite3.connect(d / "state.db")
        con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, origin_json TEXT)")
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT)")
        con.executemany("INSERT INTO sessions VALUES (?, ?)",
                        [(f"s{i}", o if isinstance(o, str) or o is None else json.dumps(o)) for i, o in enumerate(origins)])
        if messages:
            con.execute("INSERT INTO messages (session_id, role, content) VALUES ('s0', 'user', '#secret-channel C9')")
        con.commit()
        con.close()

    def test_names_slack_and_discord_channels_by_id(self):
        import omher_bridge
        with tempfile.TemporaryDirectory() as d:
            self._db(Path(d), [
                {"platform": "slack", "chat_id": "C0BLC924P1P", "chat_name": "docs-harness-ai-agent-loop", "thread_id": "1.2"},
                {"platform": "slack", "chat_id": "C2", "chat_name": "#already-hashed"},
                {"platform": "slack", "chat_id": "D0CDK7XJL72", "chat_name": "Slack", "chat_type": "dm"},
                {"platform": "discord", "chat_id": "1564465746325545000", "parent_chat_id": "1544259371528232980",
                 "chat_name": "Oh-My-Hermes Community / #cron / https://github.com/x 이 피알 확인"},
                {"platform": "discord", "chat_id": "77", "chat_name": "#general"},
                {"platform": "telegram", "chat_id": "5", "chat_name": "Reading"},
                {"platform": "slack", "chat_id": "bad id!", "chat_name": "x"},
                {"platform": "slack", "chat_id": "C3"},
                "not json", None,
            ], messages=True)
            p = omher_bridge.read_link_places(Path(d))
        self.assertEqual(p["slack"], {"C0BLC924P1P": "#docs-harness-ai-agent-loop", "C2": "#already-hashed"})
        self.assertEqual(p["discord"], {"1564465746325545000": "#cron", "1544259371528232980": "#cron", "77": "#general"})
        self.assertEqual(set(p), {"slack", "discord"})

    def test_newest_session_wins_and_names_are_short(self):
        import omher_bridge
        with tempfile.TemporaryDirectory() as d:
            self._db(Path(d), [{"platform": "slack", "chat_id": "C1", "chat_name": "old-name"},
                               {"platform": "slack", "chat_id": "C1", "chat_name": "new-name"},
                               {"platform": "slack", "chat_id": "C2", "chat_name": "x" * 200}])
            p = omher_bridge.read_link_places(Path(d))
        self.assertEqual(p["slack"]["C1"], "#new-name")
        self.assertEqual(len(p["slack"]["C2"]), 60)

    def test_read_only_missing_db_and_no_message_read(self):
        import omher_bridge
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(omher_bridge.read_link_places(Path(d)), {"slack": {}, "discord": {}})
            self._db(Path(d), [{"platform": "slack", "chat_id": "C1", "chat_name": "a"}], messages=True)
            before = (Path(d) / "state.db").stat().st_mtime_ns
            omher_bridge.read_link_places(Path(d))
            self.assertEqual((Path(d) / "state.db").stat().st_mtime_ns, before)
        src = (HERE.parent / "omher_bridge.py").read_text(encoding="utf-8")
        body = src[src.index("def read_link_places"):src.index("def reply_block")]
        self.assertNotIn("messages", body.split('"""')[2])  # the query reads sessions only
        for bad in ("urllib", "http", "socket", "subprocess", ".write", "INSERT", "UPDATE", "DELETE"):
            self.assertNotIn(bad, body.split('"""')[2], bad)

    def test_op_is_registered(self):
        import omher_bridge as ob
        self.assertIn("links.places", ob.Bridge(token=TOKEN, hermes_home=Path(tempfile.gettempdir())).ops)


PNG_1PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/"
           "iZk9HQAAAABJRU5ErkJggg==")


class BotIdentity(BridgeCase):
    """Rename and picture: the only profile writes, both presentation-only; facts are read-only."""

    async def test_rename_sets_only_the_display_name_and_keeps_the_rest(self):
        async with Env() as env:
            s = await self.open(env)
            meta = env.home / "profiles" / "kami" / "profile.yaml"
            r = await s.req("bots.rename", bot="kami", name="  Kami   the Helper ")
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["result"]["display_name"], "Kami the Helper")
            text = meta.read_text(encoding="utf-8")
            self.assertIn("display_name: Kami the Helper", text)
            self.assertIn("Kami bot", text)  # the description written by Env survives
            await s.until(lambda ev: any(e["event"] == "bots.update" and e["bot"] == "kami" for e in ev))
            bots = (await s.req("bots.list"))["result"]["bots"]
            self.assertEqual(next(b for b in bots if b["name"] == "kami")["display_name"], "Kami the Helper")
            self.assertTrue((env.home / "profiles" / "kami").is_dir())  # the id and folder never move
            # empty goes back to the profile's own name
            r = await s.req("bots.rename", bot="kami", name="")
            self.assertEqual(r["result"]["display_name"], "Kami")
            self.assertNotIn("display_name", meta.read_text(encoding="utf-8"))

    async def test_rename_refuses_bad_input(self):
        async with Env() as env:
            s = await self.open(env)
            for name, code in [("x" * 65, "bad_request"), (12, "bad_request")]:
                r = await s.req("bots.rename", bot="kami", name=name)
                self.assertEqual(r["error"]["code"], code)
            r = await s.req("bots.rename", bot="ghost", name="x")
            self.assertEqual(r["error"]["code"], "unknown_bot")
            self.assertFalse((env.home / "profiles" / "kami" / "profile.yaml").read_text(encoding="utf-8").count("display_name"))

    async def test_picture_goes_through_hermes_set_asset_when_the_gateway_runs(self):
        async with Env() as env:
            s = await self.open(env)
            r = await s.req("bots.set_avatar", bot="kami", data=PNG_1PX)
            self.assertTrue(r["ok"], r)
            calls = env.clients["kami"].find("profiles.set_asset")
            self.assertEqual(calls, [{"name": "kami", "asset": "avatar", "data": PNG_1PX}])
            r = await s.req("bots.set_avatar", bot="kami", clear=True)
            self.assertEqual(env.clients["kami"].find("profiles.set_asset")[-1], {"name": "kami", "asset": "avatar", "clear": True})

    async def test_picture_is_written_the_same_way_when_the_gateway_is_down(self):
        async with Env(fail=("kami",)) as env:
            s = await self.open(env)
            r = await s.req("bots.set_avatar", bot="kami", data=PNG_1PX)
            self.assertTrue(r["ok"], r)
            pic = env.home / "profiles" / "kami" / "assets" / "avatar.png"
            self.assertTrue(pic.read_bytes().startswith(b"\x89PNG"))
            self.assertIsInstance(r["result"]["avatar_rev"], int)
            got = (await s.req("bots.avatar", bot="kami"))["result"]
            self.assertEqual(got["data"], PNG_1PX)
            bots = (await s.req("bots.list"))["result"]["bots"]
            self.assertEqual(next(b for b in bots if b["name"] == "kami")["avatar_rev"], r["result"]["avatar_rev"])
            # not an image: refused, the old picture stays
            bad = "data:image/png;base64," + __import__("base64").b64encode(b"GIF89a....").decode()
            r = await s.req("bots.set_avatar", bot="kami", data=bad)
            self.assertEqual(r["error"]["code"], "bad_request")
            self.assertTrue(pic.is_file())
            r = await s.req("bots.set_avatar", bot="kami", data="https://example.com/x.png")
            self.assertEqual(r["error"]["code"], "bad_request")
            await s.req("bots.set_avatar", bot="kami", clear=True)
            self.assertFalse(pic.exists())
            self.assertEqual((await s.req("bots.avatar", bot="kami"))["result"], {"rev": None, "data": None})

    async def test_info_counts_sessions_per_place_from_a_read_only_db(self):
        import sqlite3
        async with Env() as env:
            d = env.home / "profiles" / "kami"
            con = sqlite3.connect(d / "state.db")
            con.execute("CREATE TABLE sessions (id TEXT, source TEXT, started_at REAL, last_activity_at REAL)")
            con.executemany("INSERT INTO sessions VALUES (?,?,?,?)", [
                ("a", "slack", 100.0, 150.0), ("b", "slack", 200.0, None), ("c", "discord", 50.0, 400.0),
                ("d", "subagent", 10.0, 900.0), ("e", "tui", 5.0, 999.0)])
            con.commit()
            con.close()
            (d / "skills" / "x").mkdir(parents=True)
            (d / "skills" / "x" / "SKILL.md").write_text("x")
            before = (d / "state.db").stat().st_mtime_ns
            s = await self.open(env)
            r = (await s.req("bots.info", bot="kami"))["result"]
            self.assertEqual(r["places"], {"slack": 2, "discord": 1})
            self.assertEqual(list(r["places"]), ["slack", "discord"])  # most first
            self.assertEqual((r["first_active"], r["last_active"]), (50.0, 400.0))  # subagent/tui ignored
            self.assertEqual((r["skills"], r["routines"]), (1, 0))
            self.assertEqual((d / "state.db").stat().st_mtime_ns, before)
            r = (await s.req("bots.info", bot="default"))["result"]
            self.assertEqual(r["places"], {})


class Skills(BridgeCase):
    """`skills.list`: each skill's `/command` slug and one-line description from its SKILL.md frontmatter, read-only."""

    FILES = {
        "plan/SKILL.md": "---\nname: plan\ndescription: Plan the work before doing it.\n---\n# Plan\n",
        "dev/review/SKILL.md": '---\nname: "review"\ndescription: "Review a diff: \\"axes\\" first"\n---\n',
        "quoted/SKILL.md": "---\nname: 'it''s'\ndescription: 'Single quoted'\n---\n",
        "folded/SKILL.md": "---\nname: folded\ndescription: >\n  First line of a folded text\n  second line\nlicense: MIT\n---\n",
        "literal/SKILL.md": "---\ndescription: |\n  Literal first line\n  more\n---\n",  # no name: the folder's
        "comment/SKILL.md": "---\nname: comment # trailing\ndescription:\n---\n",
        "crlf/SKILL.md": "\ufeff---\r\nname: crlf\r\ndescription: Windows line ends\r\n---\r\n",
        "long/SKILL.md": "---\nname: long\ndescription: " + "word " * 60 + "\n---\n",
        "spaced/SKILL.md": "---\nname: Git  Helper_Tool!\ndescription: spaces, case and marks\n---\n",
        "spaced2/SKILL.md": "---\nname: git-helper-tool\ndescription: the same slug, later in path order\n---\n",
        "x-dup/SKILL.md": "---\nname: plan\ndescription: a second plan\n---\n",  # after plan/ in path order
        "nofm/SKILL.md": "# No frontmatter\nname: nope\n",
        "open/SKILL.md": "---\nname: open\n",  # never closed
        "plan/references/SKILL.md": "---\nname: support\n---\n",  # a support folder of a skill
        ".archive/old/SKILL.md": "---\nname: archived\n---\n",
        ".hub/x/SKILL.md": "---\nname: hubbed\n---\n",
        "node_modules/y/SKILL.md": "---\nname: vendored\n---\n",
    }

    def _write(self, root: Path) -> None:
        for rel, text in self.FILES.items():
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(text.encode("utf-8"))

    def _links(self, pairs) -> None:
        try:
            for link, target in pairs:
                link.symlink_to(target, target_is_directory=target.is_dir())
        except (OSError, NotImplementedError):
            self.skipTest("this system cannot make symlinks (Windows without the privilege)")

    @staticmethod
    def _tree(root: Path):
        return sorted((str(p), p.lstat().st_mtime_ns, p.lstat().st_size) for p in root.rglob("*"))

    async def test_lists_slugs_and_one_line_descriptions_sorted(self):
        async with Env() as env:
            skills = env.home / "profiles" / "kami" / "skills"
            self._write(skills)
            s = await self.open(env)
            r = await s.req("skills.list", bot="kami")
            self.assertTrue(r["ok"], r)
            got = {x["name"]: x["description"] for x in r["result"]["skills"]}
            self.assertEqual(list(got), sorted(got))
            self.assertEqual(sorted(got), ["comment", "crlf", "folded", "git-helper-tool", "its", "literal", "long",
                                           "plan", "review"])
            self.assertEqual(got["plan"], "Plan the work before doing it.")  # the first in path order wins (as in Hermes' scan)
            self.assertEqual(got["git-helper-tool"], "spaces, case and marks")  # one row per slug
            self.assertEqual(got["review"], 'Review a diff: "axes" first')
            self.assertEqual(got["its"], "Single quoted")
            self.assertEqual(got["folded"], "First line of a folded text")
            self.assertEqual(got["literal"], "Literal first line")
            self.assertEqual(got["comment"], "")
            self.assertEqual(got["crlf"], "Windows line ends")
            self.assertEqual(len(got["long"]), 120)
            self.assertTrue(got["long"].endswith("…"))

    def test_slug_is_hermes_command_key(self):
        cases = {"plan": "plan", "Git Helper": "git-helper", "Foo  Bar_baz": "foo-bar-baz", "--x--": "x",
                 "C++ Tools": "c-tools", "it's": "its", "한국어 스킬": "한국어-스킬", "!!!": ""}
        for name, slug in cases.items():
            self.assertEqual(ob.skill_slug(name), slug, name)

    async def test_symlinked_skills_are_listed_and_nothing_is_written(self):
        async with Env() as env:
            skills = env.home / "profiles" / "kami" / "skills"
            self._write(skills)
            outside = env.home / "outside"
            (outside / "linked").mkdir(parents=True)
            (outside / "linked" / "SKILL.md").write_text("---\nname: linked-dir\ndescription: from a linked folder\n---\n")
            (outside / "file.md").write_text("---\nname: linked-file\n---\n")
            (outside / "big.md").write_bytes(b"---\nname: late\n" + b"x: y\n" * 4000 + b"---\n")  # past the 8 KB read
            (skills / "lf").mkdir()
            (skills / "big").mkdir()
            (skills / "media").mkdir()
            self._links([(skills / "media" / "linked", outside / "linked"), (skills / "lf" / "SKILL.md", outside / "file.md"),
                         (skills / "big" / "SKILL.md", outside / "big.md")])
            before = self._tree(env.home)
            s = await self.open(env)
            got = {x["name"]: x["description"] for x in (await s.req("skills.list", bot="kami"))["result"]["skills"]}
            self.assertEqual(got["linked-dir"], "from a linked folder")
            self.assertIn("linked-file", got)
            self.assertNotIn("late", got)  # its frontmatter does not close inside the bytes read
            self.assertIn("plan", got)
            self.assertEqual(self._tree(env.home), before)
            # the whole skills folder as a symlink is followed too
            moved = env.home / "moved-skills"
            skills.rename(moved)
            self._links([(skills, moved)])
            again = {x["name"] for x in (await s.req("skills.list", bot="kami"))["result"]["skills"]}
            self.assertEqual(again, set(got))

    async def test_a_symlink_cycle_is_read_once(self):
        async with Env() as env:
            skills = env.home / "profiles" / "kami" / "skills"
            (skills / "a" / "plan").mkdir(parents=True)
            (skills / "a" / "plan" / "SKILL.md").write_text("---\nname: plan\n---\n")
            (skills / "b").mkdir()
            self._links([(skills / "a" / "up", skills), (skills / "b" / "to-a", skills / "a"), (skills / "a" / "to-b", skills / "b")])
            s = await self.open(env)
            r = await s.req("skills.list", bot="kami")
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["result"]["skills"], [{"name": "plan", "description": ""}])
            with mock.patch.object(ob, "read_skill_head", wraps=ob.read_skill_head) as head:
                ob.read_skills(skills.parent)
            self.assertEqual(head.call_count, 1)  # three links back into the tree, one read

    async def test_external_dirs_of_the_profile_config_are_listed_after_its_own(self):
        """oh-my-hermes registers its skills in `skills.external_dirs` (not the profile's own folder): `skills.list`
        reads those folders too, after the profile's own, as Hermes' skill scan does; a missing folder is skipped."""
        async with Env() as env:
            prof = env.home / "profiles" / "kami"
            own = prof / "skills" / "plan"
            own.mkdir(parents=True)
            (own / "SKILL.md").write_text("---\nname: plan\ndescription: the bot's own\n---\n")
            omh = env.home / "omh-skills"
            for name, desc in (("omh-model-setup", "Model and provider configuration"), ("plan", "OMH's plan")):
                (omh / "guide" / name).mkdir(parents=True)
                (omh / "guide" / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n")
            rel = prof / "more"
            (rel / "x").mkdir(parents=True)
            (rel / "x" / "SKILL.md").write_text("---\nname: relative-one\n---\n")
            cfg = prof / "config.yaml"
            cfg.write_text(cfg.read_text() + f"skills:\n  external_dirs:\n    - {omh}\n    - {env.home}/missing\n    - more\n    - {omh}\n")
            before = self._tree(env.home)
            s = await self.open(env)
            got = {x["name"]: x["description"] for x in (await s.req("skills.list", bot="kami"))["result"]["skills"]}
            self.assertEqual(sorted(got), ["omh-model-setup", "plan", "relative-one"])
            self.assertEqual(got["plan"], "the bot's own")  # the profile's own folder wins, as in Hermes
            self.assertEqual(got["omh-model-setup"], "Model and provider configuration")
            self.assertEqual(self._tree(env.home), before)
            self.assertEqual(env.connects, [])
            # one entry as a plain string (Hermes reads a scalar too)
            cfg.write_text(cfg.read_text().split("skills:")[0] + f"skills:\n  external_dirs: {omh}\n")
            again = {x["name"] for x in (await s.req("skills.list", bot="kami"))["result"]["skills"]}
            self.assertEqual(again, {"omh-model-setup", "plan"})

    async def test_no_skills_folder_and_unknown_bot(self):
        async with Env() as env:
            s = await self.open(env)
            self.assertEqual((await s.req("skills.list", bot="kami"))["result"], {"skills": []})
            self.assertEqual((await s.req("skills.list", bot="ghost"))["error"]["code"], "unknown_bot")
            self.assertEqual(env.connects, [])  # a file read: no gateway started for it


class ReplyThere(BridgeCase):
    """"Reply there": omher passes a thread reference to the bot as one context block; it posts nothing."""

    SLACK = {"platform": "slack", "chat_id": "C0C7ABCDE12", "chat_name": "product-opengateway-ai-loop", "chat_type": "group",
             "thread_id": "1794224935.556179", "guild_id": "T058XXXX"}
    DISCORD = {"platform": "discord", "chat_id": "1569310397687791637", "thread_id": "1569310397687791637",
               "chat_name": "Oh-My-Hermes Community / #cron / OMH 스킬 \"홍보\" 리스트업", "chat_type": "thread",
               "guild_id": "1544", "parent_chat_id": "1544259371528232980"}
    SESSIONS = [
        {"id": "s-slack", "title": "loop", "source": "slack", "started_at": 3000.0},
        {"id": "s-discord", "title": "promo", "source": "discord", "started_at": 2000.0},
        {"id": "s-cron", "title": "nightly", "source": "cron", "started_at": 1000.0},
        {"id": "s-bare", "title": "no origin", "source": "slack", "started_at": 500.0},
    ]

    def _db(self, profile: Path) -> None:
        import sqlite3
        con = sqlite3.connect(profile / "state.db")
        con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, origin_json TEXT)")
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL)")
        con.executemany("INSERT INTO sessions VALUES (?, ?)", [
            ("s-slack", json.dumps(self.SLACK)), ("s-discord", json.dumps(self.DISCORD)),
            ("s-cron", json.dumps({"platform": "local", "chat_id": "local"})), ("s-bare", None)])
        con.commit()
        con.close()

    def test_reply_target_for_slack_thread_discord_thread_and_channels(self):
        self.assertEqual(ob.reply_target(self.SLACK),
                         ("slack:C0C7ABCDE12:1794224935.556179", "#product-opengateway-ai-loop"))
        self.assertEqual(ob.reply_target(self.DISCORD),
                         ("discord:1569310397687791637:1569310397687791637", "#cron / OMH 스킬 '홍보' 리스트업"))
        self.assertEqual(ob.reply_target({"platform": "discord", "chat_id": "42", "chat_name": "G / #ops"}),
                         ("discord:42", "#ops"))
        self.assertEqual(ob.reply_target({"platform": "slack", "chat_id": "D0CB1", "chat_type": "dm",
                                          "chat_name": "김희망 (Khope)", "thread_id": "1793.5"}),
                         ("slack:D0CB1:1793.5", "김희망 (Khope)"))
        # no messenger thread -> no chip
        for origin in ({}, {"platform": "local", "chat_id": "local"}, {"platform": "slack"},
                       {"platform": "slack", "chat_id": "C1 ; rm -rf"}, {"platform": "discord", "chat_id": "1", "thread_id": "a:b"},
                       {"platform": "cron", "chat_id": "x"}):
            self.assertIsNone(ob.reply_target(origin), origin)

    def test_block_is_one_line_naming_the_target_and_round_trips(self):
        block = ob.reply_block("slack:C1:1794.5", "#og-dev")
        self.assertEqual(block, '[omher] Reply target: slack:C1:1794.5 (thread "#og-dev"). Post there only if the user '
                                'asked; use your own messaging tool or `hermes send --to slack:C1:1794.5`.')
        self.assertNotIn("\n", block)
        self.assertIn('(channel "#ops")', ob.reply_block("discord:42", "#ops"))
        typed, ref = ob.split_reply_block(f"결과 요약해서 남겨줘\n\n{block}")
        self.assertEqual((typed, ref), ("결과 요약해서 남겨줘", {"target": "slack:C1:1794.5", "label": "#og-dev"}))
        self.assertEqual(ob.split_reply_block("plain"), ("plain", None))
        rows = ob.chat_messages([{"role": "user", "text": f"post it\n\n{block}", "row_id": 9},
                                 {"role": "assistant", "text": block, "row_id": 10}])
        self.assertEqual(rows[0]["text"], "post it")
        self.assertEqual(rows[0]["reply_to"], {"target": "slack:C1:1794.5", "label": "#og-dev"})
        self.assertNotIn("reply_to", rows[1])  # only the person's own rows carry a reference

    async def test_elsewhere_list_carries_the_target_only_for_threads(self):
        async with Env(sessions=[dict(r) for r in self.SESSIONS]) as env:
            self._db(env.home / "profiles" / "kami")
            s = await self.open(env)
            rows = {a["id"]: a for a in (await s.req("elsewhere.list", bot="kami"))["result"]["sessions"]}
            self.assertEqual(rows["s-slack"]["reply_target"], "slack:C0C7ABCDE12:1794224935.556179")
            self.assertEqual(rows["s-discord"]["reply_target"], "discord:1569310397687791637:1569310397687791637")
            self.assertIsNone(rows["s-cron"]["reply_target"])
            self.assertIsNone(rows["s-bare"]["reply_target"])

    async def test_send_with_reply_to_submits_once_to_the_main_chat_with_one_block(self):
        async with Env(sessions=[dict(r) for r in self.SESSIONS]) as env:
            self._db(env.home / "profiles" / "kami")
            s = await self.open(env)
            r = await s.req("chat.send", bot="kami", text="결과 요약해서 남겨줘  ", reply_to="s-slack")
            self.assertTrue(r["ok"], r)
            c = env.clients["kami"]
            sub = c.find("prompt.submit")
            self.assertEqual(len(sub), 1)
            self.assertEqual(sub[0]["session_id"], MAIN_RUNTIME)
            text = sub[0]["text"]
            self.assertEqual(text, "결과 요약해서 남겨줘\n\n" + ob.reply_block("slack:C0C7ABCDE12:1794224935.556179",
                                                                         "#product-opengateway-ai-loop"))
            self.assertEqual(text.count("[omher] Reply target:"), 1)
            # the referenced thread is never resumed, created or written
            for m, p in c.calls:
                self.assertNotIn("s-slack", json.dumps(p), m)
            # Discord thread
            await s.req("chat.send", bot="kami", text="there", reply_to="s-discord")
            self.assertIn("discord:1569310397687791637:1569310397687791637", c.find("prompt.submit")[-1]["text"])
            # no thread to reply in -> refused, nothing submitted
            for sid in ("s-cron", "s-bare", "nope"):
                r = await s.req("chat.send", bot="kami", text="post", reply_to=sid)
                self.assertEqual(r["error"]["code"], "bad_request", sid)
            for bad in ("", 5, ["s-slack"]):
                r = await s.req("chat.send", bot="kami", text="post", reply_to=bad)
                self.assertEqual(r["error"]["code"], "bad_request", bad)
            r = await s.req("chat.send", bot="kami", text="post", reply_to=MAIN_STORED)
            self.assertEqual(r["error"]["code"], "bad_request")
            self.assertEqual(len(c.find("prompt.submit")), 2)

    async def test_there_without_a_chip_adds_nothing(self):
        """'거기'/'there' with no chip is an ordinary turn: the bridge never guesses a target."""
        async with Env(sessions=[dict(r) for r in self.SESSIONS]) as env:
            self._db(env.home / "profiles" / "kami")
            s = await self.open(env)
            await s.req("elsewhere.list", bot="kami")
            for text in ("거기 슬랙에 남겨줘", "leave it there"):
                await s.req("chat.send", bot="kami", text=text)
            self.assertEqual([p["text"] for p in env.clients["kami"].find("prompt.submit")],
                             ["거기 슬랙에 남겨줘", "leave it there"])


class SidePanel(unittest.TestCase):
    """Terminal / Worktrees / Diff tabs: read-only reads of state.db and git."""

    def _db(self, d: Path, cwd: str):
        import sqlite3
        con = sqlite3.connect(d / "state.db")
        con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT)")
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,"
                    " tool_call_id TEXT, tool_calls TEXT, tool_name TEXT, timestamp REAL)")
        con.execute("INSERT INTO sessions VALUES ('s1', 'slack'), ('s2', 'tui')")
        call = lambda cid, cmd: json.dumps([{"id": cid, "type": "function", "function": {
            "name": "terminal", "arguments": json.dumps({"command": cmd})}}])
        rows = [
            ("s1", "assistant", "", None, call("t1", "git status"), None, 1.0),
            ("s1", "tool", json.dumps({"output": "clean", "exit_code": 0, "cwd": cwd}), "t1", None, "terminal", 2.0),
            ("s2", "assistant", "", None, call("t2", "false"), None, 3.0),
            ("s2", "tool", json.dumps({"output": "x" * 5000, "exit_code": 1, "cwd": cwd}), "t2", None, "terminal", 4.0),
            ("s2", "assistant", "", None, json.dumps([{"id": "r1", "function": {"name": "read_file",
                                                                             "arguments": "{}"}}]), None, 5.0),
            ("s2", "tool", "file text", "r1", None, "read_file", 6.0),
        ]
        con.executemany("INSERT INTO messages (session_id, role, content, tool_call_id, tool_calls, tool_name, timestamp)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        con.commit()
        con.close()

    def _repo(self, d: Path) -> Path:
        import subprocess
        repo = d / "repo"
        repo.mkdir()
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "first"]):
            subprocess.run(["git", *args], cwd=repo, check=True, env=env)
        (repo / "a.txt").write_text("one\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True, env=env)
        subprocess.run(["git", "commit", "-q", "-m", "add a"], cwd=repo, check=True, env=env)
        (repo / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
        return repo

    def test_terminal_runs_pair_each_command_with_its_output_newest_first(self):
        with tempfile.TemporaryDirectory() as d:
            self._db(Path(d), "/x")
            runs = ob.read_terminal_runs(Path(d))
        self.assertEqual([r["command"] for r in runs], ["false", "git status"])
        self.assertEqual(runs[0]["exit_code"], 1)
        self.assertEqual(runs[0]["source"], "tui")
        self.assertEqual(runs[1]["source"], "slack")
        self.assertEqual(runs[1]["output"], "clean")
        self.assertLessEqual(len(runs[0]["output"]), ob.PANEL_OUT)
        self.assertIn("\n…\n", runs[0]["output"])  # head and tail kept, clipped before the reply is encoded

    def test_no_state_db_means_no_runs(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ob.read_terminal_runs(Path(d)), [])

    def test_worktrees_and_diff_come_from_folders_the_bot_used_and_change_nothing(self):
        import shutil
        if not shutil.which("git"):
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(Path(d))
            prof = Path(d) / "prof"
            prof.mkdir()
            self._db(prof, str(repo))
            before = {p: p.stat().st_mtime_ns for p in (repo / ".git").rglob("*") if p.is_file()}
            trees = ob.read_worktrees(prof)
            self.assertEqual(len(trees), 1)
            self.assertEqual(Path(trees[0]["path"]).resolve(), repo.resolve())
            self.assertEqual(trees[0]["branch"], "main")
            self.assertEqual(trees[0]["dirty"], 1)
            diff = ob.read_diff(prof, trees[0]["path"])
            self.assertEqual(diff["scope"], "uncommitted")
            self.assertEqual(diff["files"], [{"path": "a.txt", "add": 1, "del": 0}])
            self.assertIn("+two", diff["patch"])
            after = {p: p.stat().st_mtime_ns for p in (repo / ".git").rglob("*") if p.is_file()}
            self.assertEqual(after, before, "a git read wrote into .git")
            # a clean tree shows its last commit instead
            (repo / "a.txt").write_text("one\n", encoding="utf-8")
            self.assertEqual(ob.read_diff(prof, trees[0]["path"])["scope"], "last commit")
            # a folder the bot never worked in is refused
            with self.assertRaises(ob.BridgeError) as e:
                ob.read_diff(prof, str(Path(d)))
            self.assertEqual(e.exception.code, "not_found")

    def test_reads_run_no_program_the_repository_names(self):
        """core.fsmonitor, a diff textconv and filter clean/process drivers (named from .gitattributes and from
        .git/info/attributes) all run programs during a plain `git status`/`git diff`; the panel's reads must not."""
        import shutil
        import subprocess
        if not shutil.which("git") or os.name == "nt":
            self.skipTest("needs git and a POSIX shell hook")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                   "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
            marks = d / "marks"
            marks.mkdir()

            def repo(name: str, setup) -> Path:
                r = d / name
                r.mkdir()
                git = lambda *a: subprocess.run(["git", *a], cwd=r, check=True, env=env, capture_output=True)
                git("init", "-q", "-b", "main")
                (r / "a.txt").write_text("one\n", encoding="utf-8")
                git("add", "a.txt")
                git("commit", "-q", "-m", "a")
                hook = d / f"hook-{name}"
                hook.write_text(f"#!/bin/sh\ntouch '{marks}/{name}'\ncat\n", encoding="utf-8")
                hook.chmod(0o755)
                setup(r, git, str(hook))
                (r / "a.txt").write_text("two\n", encoding="utf-8")  # same size: git must look at the content
                return r

            def attrs(path: Path, line: str):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(line + "\n", encoding="utf-8")

            repos = [
                repo("fsmonitor", lambda r, git, h: git("config", "core.fsmonitor", h)),
                repo("textconv", lambda r, git, h: (attrs(r / ".gitattributes", "*.txt diff=x"),
                                                    git("config", "diff.x.textconv", h))),
                repo("clean", lambda r, git, h: (attrs(r / ".gitattributes", "*.txt filter=y"),
                                                 git("config", "filter.y.clean", h))),
                repo("info-process", lambda r, git, h: (attrs(r / ".git" / "info" / "attributes", "*.txt filter=z diff=x"),
                                                        git("config", "filter.z.process", h),
                                                        git("config", "filter.z.required", "true"),
                                                        git("config", "diff.x.textconv", h))),
                repo("ext-diff", lambda r, git, h: git("config", "diff.external", h)),
            ]
            # every hook really runs under a plain git read (the threat is real on this git)
            for r in repos:
                for a in (["status", "--porcelain"], ["diff", "HEAD"]):
                    subprocess.run(["git", *a], cwd=r, env=env, capture_output=True, stdin=subprocess.DEVNULL)
            self.assertEqual(sorted(p.name for p in marks.iterdir()),
                             ["clean", "ext-diff", "fsmonitor", "info-process", "textconv"])
            for m in marks.iterdir():
                m.unlink()
            prof = d / "prof"
            prof.mkdir()
            self._db_many(prof, [str(r) for r in repos])
            trees = ob.read_worktrees(prof)
            self.assertEqual(len(trees), len(repos))
            self.assertTrue(all(w["dirty"] for w in trees), trees)
            for w in trees:
                diff = ob.read_diff(prof, w["path"])
                self.assertEqual(diff["scope"], "uncommitted")
                self.assertEqual([f["path"] for f in diff["files"] if not f.get("untracked")], ["a.txt"])
                self.assertIn("+two", diff["patch"])  # the raw content, no textconv
                self.assertIsNotNone(ob._git(["status", "--porcelain"], w["path"]))
                self.assertIsNotNone(ob._git(["log", "-1", "--patch"], w["path"]))
            self.assertEqual([p.name for p in marks.iterdir()], [], "a repository-configured program ran")

    def _db_many(self, prof: Path, cwds: list[str]) -> None:
        import sqlite3
        con = sqlite3.connect(prof / "state.db")
        con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT)")
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,"
                    " tool_call_id TEXT, tool_calls TEXT, tool_name TEXT, timestamp REAL)")
        con.execute("INSERT INTO sessions VALUES ('s1', 'tui')")
        for i, cwd in enumerate(cwds):
            call = json.dumps([{"id": f"t{i}", "function": {"name": "terminal", "arguments": json.dumps({"command": "ls"})}}])
            con.execute("INSERT INTO messages (session_id, role, content, tool_call_id, tool_calls, tool_name, timestamp)"
                        " VALUES ('s1', 'assistant', '', NULL, ?, NULL, ?)", (call, float(2 * i)))
            con.execute("INSERT INTO messages (session_id, role, content, tool_call_id, tool_calls, tool_name, timestamp)"
                        " VALUES ('s1', 'tool', ?, ?, NULL, 'terminal', ?)",
                        (json.dumps({"output": "", "exit_code": 0, "cwd": cwd}), f"t{i}", float(2 * i + 1)))
        con.commit()
        con.close()

    def test_diff_lists_non_ascii_names_and_untracked_files(self):
        import shutil
        import subprocess
        if not shutil.which("git"):
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(Path(d))
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                   "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
            (repo / "새파일.txt").write_text("가\n", encoding="utf-8")
            subprocess.run(["git", "add", "새파일.txt"], cwd=repo, check=True, env=env)
            subprocess.run(["git", "commit", "-q", "-m", "ko"], cwd=repo, check=True, env=env)
            (repo / "새파일.txt").write_text("가\n나\n", encoding="utf-8")
            (repo / "new.txt").write_text("fresh\n", encoding="utf-8")
            (repo / "새 폴더").mkdir()
            (repo / "새 폴더" / "메모.md").write_text("x\n", encoding="utf-8")
            prof = Path(d) / "prof"
            prof.mkdir()
            self._db(prof, str(repo))
            trees = ob.read_worktrees(prof)
            self.assertEqual(trees[0]["dirty"], 4)  # a.txt, 새파일.txt, new.txt, 새 폴더/
            diff = ob.read_diff(prof, trees[0]["path"])
            self.assertEqual(diff["scope"], "uncommitted")
            self.assertEqual(diff["files"], [
                {"path": "a.txt", "add": 1, "del": 0},
                {"path": "새파일.txt", "add": 1, "del": 0},
                {"path": "new.txt", "add": 0, "del": 0, "untracked": True},
                {"path": "새 폴더/", "add": 0, "del": 0, "untracked": True},
            ])
            # only new files: still "uncommitted", not the last commit
            subprocess.run(["git", "checkout", "-q", "--", "."], cwd=repo, check=True, env=env)
            diff = ob.read_diff(prof, trees[0]["path"])
            self.assertEqual(diff["scope"], "uncommitted")
            self.assertEqual([f["path"] for f in diff["files"]], ["new.txt", "새 폴더/"])

    def test_quoted_diff_paths_are_unquoted(self):
        self.assertEqual(ob._unquote(r"\355\225\234.txt"), "한.txt")
        self.assertEqual(ob._unquote(r"tab\there \"q\" back\\slash"), 'tab\there "q" back\\slash')
        m = ob._DIFF_FILE.match('diff --git "a/x\\ty" "b/x\\ty"')
        self.assertEqual(ob._unquote(m.group("q")), "x\ty")

    def test_diff_reuses_the_worktree_scan_and_skips_known_folders(self):
        import shutil
        if not shutil.which("git"):
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as d:
            repo = self._repo(Path(d))
            (repo / "sub").mkdir()
            prof = Path(d) / "prof"
            prof.mkdir()
            self._db_many(prof, [str(repo), str(repo / "sub"), str(repo)])
            calls = []
            real = ob._git

            def spy(args, cwd, timeout=ob.GIT_TIMEOUT, hardened=None):
                calls.append(args[0])
                return real(args, cwd, timeout, hardened)
            with mock.patch.object(ob, "_git", spy):
                trees = ob.read_worktrees(prof)
                self.assertEqual(calls.count("rev-parse"), 1, calls)  # repo/sub is inside a known worktree
                calls.clear()
                ob.read_diff(prof, trees[0]["path"])
                self.assertNotIn("rev-parse", calls)  # the kept scan, not a rescan
                self.assertNotIn("worktree", calls)
                calls.clear()
                with mock.patch.object(ob.time, "monotonic", return_value=time.monotonic() + ob.WORKTREES_TTL + 1):
                    ob.read_diff(prof, trees[0]["path"])
                self.assertIn("rev-parse", calls)  # stale: scanned again



class Media(BridgeCase):
    """media.read: only files the bot named in a MEDIA: line of its main chat or an elsewhere session."""

    def _db(self, prof: Path, rows: list[tuple[str, str, str]]):
        import sqlite3
        con = sqlite3.connect(prof / "state.db")
        con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, title TEXT)")
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT)")
        con.executemany("INSERT INTO sessions VALUES (?, ?, ?)",
                        [("main", "tui", ob.BOT_CHAT_TITLE), ("sl", "slack", None), ("cli", "cli", "scratch"),
                         ("sub", "subagent", None)])
        con.executemany("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)", rows)
        con.commit()
        con.close()

    def _files(self, d: Path) -> dict[str, Path]:
        out = d / "out"
        out.mkdir()
        f = {"png": out / "a.png", "slack": out / "s.mp4", "user": out / "u.png", "cli": out / "c.png",
             "sub": out / "sub.png", "prose": out / "p.png", "secret": d / "secret.txt"}
        for p in f.values():
            p.write_bytes(b"\x89PNG-ish")
        (out / "link.png").symlink_to(f["secret"])
        (out / "inner.png").symlink_to(f["png"])
        (out / "dir.png").mkdir()
        return f

    async def test_serves_only_named_files(self):
        async with Env() as env:
            prof = env.home / "profiles" / "kami"
            f = self._files(prof)
            out = f["png"].parent
            self._db(prof, [
                ("main", "assistant", f"Here.\n\nMEDIA:{f['png']}\nMEDIA:{out / 'link.png'}\nMEDIA:{out / 'inner.png'}"
                                      f"\nMEDIA:{out / 'dir.png'}"),
                ("sl", "assistant", f"MEDIA:{f['slack']}"),
                ("main", "user", f"MEDIA:{f['user']}"),
                ("cli", "assistant", f"MEDIA:{f['cli']}"),
                ("sub", "assistant", f"MEDIA:{f['sub']}"),
                ("main", "assistant", f"see MEDIA:{f['prose']} and\n```\nMEDIA:{f['secret']}\n```"),
            ])
            s = await self.open(env)
            r = await s.req("media.read", bot="kami", path=str(f["png"]))
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["result"]["mime"], "image/png")
            self.assertEqual(r["result"]["size"], 8)
            self.assertEqual(r["result"]["name"], "a.png")
            import base64
            self.assertEqual(base64.b64decode(r["result"]["data_base64"]), b"\x89PNG-ish")
            info = await s.req("media.read", bot="kami", path=str(f["png"]), info=True)
            self.assertNotIn("data_base64", info["result"])
            self.assertEqual(info["result"]["size"], 8)
            self.assertTrue((await s.req("media.read", bot="kami", path=str(f["slack"])))["ok"], "elsewhere session")
            self.assertTrue((await s.req("media.read", bot="kami", path=str(out / "inner.png")))["ok"],
                            "a symlink inside its own folder")
            for path, why in [(f["user"], "a user message"), (f["cli"], "a cli session"), (f["sub"], "a subagent"),
                              (f["prose"], "not a whole line"), (f["secret"], "fenced code"),
                              (out / "link.png", "symlink escape"), (out / "dir.png", "a directory"),
                              (out / "never.png", "never named"), (Path("/etc/hosts"), "never named")]:
                r = await s.req("media.read", bot="kami", path=str(path))
                self.assertFalse(r["ok"], why)
                self.assertEqual(r["error"]["code"], "not_found", why)
            r = await s.req("media.read", bot="kami", path="")
            self.assertEqual(r["error"]["code"], "bad_request")

    def test_too_big_is_never_read(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            prof = Path(d)
            big = prof / "big.mp4"
            with open(big, "wb") as fh:  # sparse: 25 MB + 1 without writing it
                fh.truncate(ob.MEDIA_MAX + 1)
            self._db(prof, [("main", "assistant", f"MEDIA:{big}")])
            real_open = open
            opened = []

            def spy(path, *a, **kw):
                opened.append(str(path))
                return real_open(path, *a, **kw)

            with mock.patch("builtins.open", spy):
                r = ob.read_media(prof, str(big))
            self.assertEqual(r["too_big"], True)
            self.assertEqual(r["size"], ob.MEDIA_MAX + 1)
            self.assertNotIn("data_base64", r)
            self.assertNotIn(os.path.realpath(big), [os.path.realpath(p) for p in opened])

    def test_state_db_is_opened_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            prof = Path(d)
            (prof / "a.png").write_bytes(b"x")
            self._db(prof, [("main", "assistant", f"MEDIA:{prof / 'a.png'}")])
            before = (prof / "state.db").stat().st_mtime_ns
            self.assertEqual(ob.read_media(prof, str(prof / "a.png"))["size"], 1)
            self.assertEqual((prof / "state.db").stat().st_mtime_ns, before)

    def test_media_lines_match_the_ui_parser(self):
        text = "Done.\nMEDIA:/w/a.png\n  MEDIA: `/w/b c.mp4`\nsee MEDIA:/w/x.png\nMEDIA:rel.png\n```\nMEDIA:/w/f.png\n```"
        self.assertEqual(ob.media_paths(text), ["/w/a.png", "/w/b c.mp4"])

DAG_FIXTURES = HERE / "fixtures" / "dag"
FAN, CANCELLED, SMALL = (
    "20261102_235818_fcfb1bdd-96bc7f91f27a766c", "20261026_134438_3ae70257-dac2fb5045223e90",
    "20261028_093610_1b12a114-ba5ac497c940e83f")


def _runs_profile(root: Path, sessions, dag_src: Path = DAG_FIXTURES) -> tuple[Path, Path]:
    """A profile whose config points OMH at `root/omh`, a copy of the dag dir there, and a state.db holding
    `sessions`. Returns (profile dir, dag dir)."""
    import shutil
    import sqlite3
    prof, dag = root / "prof", root / "omh" / "runtime" / "dag"
    prof.mkdir(parents=True)
    shutil.copytree(dag_src, dag, symlinks=True)
    (prof / "config.yaml").write_text(
        f"plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: '{root / 'omh'}'\n", encoding="utf-8")
    con = sqlite3.connect(prof / "state.db")
    con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT)")
    con.executemany("INSERT INTO sessions VALUES (?, 'discord')", [(s,) for s in sessions])
    con.commit()
    con.close()
    return prof, dag


def _mtimes(*roots: Path) -> dict:
    return {p: p.lstat().st_mtime_ns for r in roots for p in ([r] if r.is_file() else r.rglob("*"))}


class Runs(unittest.TestCase):
    """runs.list / runs.get over OMH dag records: read-only, owned by the bot through its state.db sessions."""

    def test_list_and_get_only_the_bots_runs_and_write_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            prof, dag = _runs_profile(Path(d), ["20261102_235818_fcfb1bdd", "20261026_134438_3ae70257"])
            before = _mtimes(dag, prof)
            runs = ob.DagRuns().list("kami", prof)
            self.assertEqual([r["id"] for r in runs], ["dag:20261102_235818_fcfb1bdd/codex-coexist",
                                                       "dag:20261026_134438_3ae70257/omh-dap"])  # newest first
            fan, cancelled = runs
            # the failed discovery node was fixed by its two repairs: repaired, not an open failure
            self.assertEqual((fan["state"], fan["counts"]), ("done", {"nodes": 6, "done": 5, "running": 0, "failed": 0,
                                                                      "repaired": 1}))
            self.assertEqual(cancelled["state"], "cancelled")
            self.assertNotIn("nodes", fan)
            got = ob.DagRuns().get("kami", prof, fan["id"])
            nodes = {n["id"]: n for n in got["run"]["nodes"]}
            self.assertEqual(nodes["t1-discovery"]["state"], "failed")
            self.assertEqual(nodes["t5-verify"]["layer"], 2)
            self.assertEqual(sum(len(n["deps"]) for n in nodes.values()), 4)
            self.assertEqual(sorted(got["handoffs"]), ["t1-hermes", "t2-status-update", "t3-doctor", "t4-fence", "t5-verify"])
            self.assertNotIn("handoff", nodes["t1-discovery"])
            self.assertTrue(all(len(t) <= ob.HANDOFF_MAX for t in got["handoffs"].values()))
            self.assertEqual(len(got["handoffs"]["t5-verify"]), ob.HANDOFF_MAX)  # 12.5k on disk, clipped
            with self.assertRaises(ob.BridgeError) as e:  # a run of another bot's session
                ob.DagRuns().get("kami", prof, "dag:20261028_093610_1b12a114/route-hint-dedup")
            self.assertEqual(e.exception.code, "not_found")
            self.assertEqual(_mtimes(dag, prof), before, "a runs read wrote something")

    def test_a_record_cut_mid_write_keeps_the_last_good_parse(self):
        with tempfile.TemporaryDirectory() as d:
            prof, dag = _runs_profile(Path(d), ["20261028_093610_1b12a114"])
            reader = ob.DagRuns()
            first = reader.list("kami", prof)
            self.assertEqual([r["state"] for r in first], ["done"])
            rec = dag / SMALL / "route-hint-dedup.json"
            rec.write_text((HERE / "fixtures" / "dag-truncated.json").read_text(encoding="utf-8"), encoding="utf-8")
            st = rec.stat()
            os.utime(rec, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
            self.assertEqual(reader.list("kami", prof), first)
            self.assertEqual(reader.get("kami", prof, first[0]["id"])["run"]["state"], "done")
            # a fresh reader that never saw it whole skips it rather than raising
            self.assertEqual(ob.DagRuns().list("kami", prof), [])

    def test_symlinked_handoffs_and_folders_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            prof, dag = _runs_profile(Path(d), ["20261028_093610_1b12a114", "20261026_134438_3ae70257"])
            secret = Path(d) / "outside.md"
            secret.write_text("outside the dag dir", encoding="utf-8")
            small = dag / SMALL / "route-hint-dedup"
            (small / "verify.md").unlink()
            try:
                (small / "verify.md").symlink_to(secret)
            except OSError:
                self.skipTest("this system cannot make symlinks (Windows without the privilege)")
            folder = dag / CANCELLED / "omh-dap"
            import shutil
            shutil.move(str(folder), str(Path(d) / "moved"))
            folder.symlink_to(Path(d) / "moved", target_is_directory=True)
            reader = ob.DagRuns()
            got = reader.get("kami", prof, "dag:20261028_093610_1b12a114/route-hint-dedup")
            self.assertEqual(sorted(got["handoffs"]), ["implement"])
            self.assertNotIn("handoff", got["run"]["nodes"][1])
            got = reader.get("kami", prof, "dag:20261026_134438_3ae70257/omh-dap")
            self.assertEqual(got["handoffs"], {})
            self.assertFalse(any("outside the dag dir" in t for t in got["handoffs"].values()))

    def test_a_running_run_quiet_for_a_day_with_no_helper_reporting_is_stale_not_live(self):
        from datetime import datetime, timezone
        v02 = "dag:20261108_213859_c9a97486/omher-v02"
        with tempfile.TemporaryDirectory() as d:
            prof, dag = _runs_profile(Path(d), ["20261108_213859_c9a97486"])
            rec = next(dag.glob("*/omher-v02.json"))
            updated = json.loads(rec.read_text(encoding="utf-8"))["updated_at"]
            os.utime(rec, (updated, updated))  # the file changed when the record says it did
            reader = ob.DagRuns(ob.Delegations(tz=timezone.utc))
            one = lambda now: next(r for r in reader.list("kami", prof, now=now) if r["id"] == v02)
            # ten minutes after its last change it is live
            self.assertEqual((one(updated + 600)["state"], one(updated + 600).get("stale")), ("running", None))
            # a day and a bit with no change: still "running" as the record says, but stale, and listed after
            # every live run (a run settled since sorts by its own time as before)
            quiet = one(updated + ob.QUIET_RUN + 60)
            self.assertEqual((quiet["state"], quiet["stale"]), ("running", True))
            self.assertEqual(quiet["counts"]["running"], 3)
            # runs.get marks it the same way runs.list does
            self.assertEqual(reader.get("kami", prof, v02)["run"].get("stale"), one(time.time()).get("stale"))
            # the file itself changed since (a newer write than its updated_at): live again
            os.utime(rec, (updated + ob.QUIET_RUN, updated + ob.QUIET_RUN))
            self.assertNotIn("stale", one(updated + ob.QUIET_RUN + 60))
            os.utime(rec, (updated, updated))
            # a helper of one of its nodes still writing its log: live, however old the record
            folder = prof / "cache" / "delegation" / "live" / "deleg_00aa11cc"
            folder.mkdir(parents=True)
            now = updated + 3 * ob.QUIET_RUN
            started = datetime.fromtimestamp(now - 7200, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            (folder / "manifest.json").write_text(json.dumps({"started": started, "tasks": [
                {"index": 0, "goal": "[dag:omher-v02/t2-attach] attach", "status": "running"}]}), encoding="utf-8")
            (folder / "task-0.log").write_text(f"goal: attach\nstarted: {started}\n", encoding="utf-8")
            for f in folder.iterdir():
                os.utime(f, (now - 120, now - 120))
            self.assertNotIn("stale", one(now))
            # the same helper silent for over an hour (stalled): stale
            for f in folder.iterdir():
                os.utime(f, (now - ob.STALE_AFTER - 60, now - ob.STALE_AFTER - 60))
            self.assertTrue(one(now)["stale"])

    def test_only_running_dag_runs_can_be_stale(self):
        run = {"id": "dag:s/x", "state": "done", "updated": 0.0, "nodes": []}
        self.assertNotIn("stale", ob.mark_stale(dict(run), None, [], 10 * ob.QUIET_RUN))
        self.assertTrue(ob.mark_stale(dict(run, state="running"), None, [], 10 * ob.QUIET_RUN)["stale"])
        self.assertNotIn("stale", ob.mark_stale(dict(run, state="running"), None, [], ob.QUIET_RUN - 1))

    def test_no_dag_dir_or_no_state_db_means_no_runs(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ob.DagRuns().list("kami", Path(d)), [])

    def test_a_cyclic_record_is_skipped_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            prof, dag = _runs_profile(Path(d), ["20261028_093610_1b12a114"])
            rec = dag / SMALL / "route-hint-dedup.json"
            data = json.loads(rec.read_text(encoding="utf-8"))
            data["nodes"][0]["depends_on"] = ["verify"]
            rec.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(ob.DagRuns().list("kami", prof), [])
            with self.assertRaises(ValueError):
                ob.layer_of([{"id": "a", "deps": ["b"]}, {"id": "b", "deps": ["a"]}])

    def test_a_copy_of_the_real_dag_dir_lists_runs(self):
        """Real `~/.omh/runtime/dag`, copied to a temp dir, owned through the real sessions it names."""
        real = Path.home() / ".omh" / "runtime" / "dag"
        if not real.is_dir() or not any(real.glob("*/*.json")):
            self.skipTest("no real dag runs on this machine")
        sids = set()
        for f in real.glob("*/*.json"):
            try:
                sids.add(json.loads(f.read_text(encoding="utf-8"))["session_id"])
            except (ValueError, KeyError, OSError):
                continue
        with tempfile.TemporaryDirectory() as d:
            prof, dag = _runs_profile(Path(d), sorted(sids), dag_src=real)
            runs = ob.DagRuns().list("kami", prof)
            self.assertGreaterEqual(len(runs), 1)
            live = [r["state"] == "running" and not r.get("stale") for r in runs]
            self.assertEqual(live, sorted(live, reverse=True))  # live runs first (a stale one sorts by its time)
            got = ob.DagRuns().get("kami", prof, runs[0]["id"])
            self.assertEqual(len(got["run"]["nodes"]), runs[0]["counts"]["nodes"])


FIX = HERE / "fixtures"


class RunsJoin(unittest.TestCase):
    """T5: who ran each node. Delegation folders give the helper's model, OMH's route records the category it went
    out under, a run's fanout unit files the agent CLI (codex) that took a fanout node. Read-only."""

    def test_route_table_keeps_the_newest_record_per_category_from_the_bots_sessions(self):
        records = ob.load_route_records(FIX)
        self.assertGreater(len(records), 5)
        table = ob.route_table(records, {"20261108_213859_c9a97486"})
        self.assertEqual(table["unspecified-high"]["model"], "claude-opus-5-5")
        self.assertEqual(table["review"], {"model": "claude-opus-5-5", "provider": "claude-proxy", "effort": "high"})
        # another session's records are not this bot's
        self.assertEqual(ob.route_table(records, {"nobody"}), {})

    def test_fanout_owners_name_the_agent_cli_and_skip_anything_else(self):
        folder = FIX / "dag" / "20261102_235818_fcfb1bdd-96bc7f91f27a766c" / "codex-coexist"
        owners = ob.fanout_owners(folder)
        self.assertEqual(owners, {"t1-discovery": "codex", "t2-status-update": "codex", "t3-doctor": "codex",
                                  "t1-hermes": "codex", "t4-fence": "codex"})
        with tempfile.TemporaryDirectory() as d:
            f = Path(d)
            (f / "fanout-abc123-units.json").write_text("{not json", encoding="utf-8")
            (f / "notes-units.json").write_text('{"units": [{"unit_id": "x", "owner": "codex"}]}', encoding="utf-8")
            self.assertEqual(ob.fanout_owners(f), {})
            self.assertEqual(ob.fanout_owners(f / "missing"), {})

    def test_every_node_of_the_live_fanout_gets_a_model_to_show(self):
        with tempfile.TemporaryDirectory() as d:
            prof, dag = _runs_profile(Path(d), ["20261102_235818_fcfb1bdd"])
            (Path(d) / "omh" / "routing").mkdir(parents=True)
            (Path(d) / "omh" / "routing" / "route-provenance.json").write_text(
                (FIX / "routing" / "route-provenance.json").read_text(encoding="utf-8"), encoding="utf-8")
            before = _mtimes(dag, Path(d) / "omh" / "routing")
            got = ob.DagRuns().get("kami", prof, "dag:20261102_235818_fcfb1bdd/codex-coexist")
            by = {n["id"]: n for n in got["run"]["nodes"]}
            self.assertEqual(by["t1-discovery"]["executor"], "codex")
            self.assertEqual(by["t5-verify"]["role"], "verify")
            self.assertEqual(_mtimes(dag, Path(d) / "omh" / "routing"), before, "a runs read wrote something")

    def test_a_finished_task_of_a_running_fan_out_ends_at_its_own_final_line(self):
        # two helpers: one finished after 120.5s, one still working; the manifest has no `completed` yet
        from datetime import timezone
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "cache" / "delegation" / "live" / "deleg_00aa11bb"
            folder.mkdir(parents=True)
            (folder / "manifest.json").write_text(json.dumps({
                "started": "2026-11-10 06:00:00", "model": "claude-opus-5-5",
                "tasks": [{"index": 0, "goal": "A", "status": "running"}, {"index": 1, "goal": "B", "status": "running"}]}),
                encoding="utf-8")
            head = "=== Hermes subagent live transcript ===\ngoal: {g}\nstarted: 2026-11-10 06:00:0{s}\n"
            (folder / "task-0.log").write_text(head.format(g="A", s=0) + "06:02:00 final    | status=completed duration=120.5s "
                                               "summary: Done.\n06:02:00 final    | end status=completed exit_reason=completed\n",
                                               encoding="utf-8")
            (folder / "task-1.log").write_text(head.format(g="B", s=2) + "06:01:00 tool     | -> terminal(ls)\n", encoding="utf-8")
            now = ob._local_ts("2026-11-10 06:05:00", timezone.utc)
            for f in folder.iterdir():
                os.utime(f, (now - 60, now - 60))  # the logs moved a minute ago: nothing has stalled
            delegs = ob.Delegations(tz=timezone.utc).list(Path(d), now=now)
            run = ob.delegation_to_run(delegs[0], "kami")
            a, b = run["nodes"]
            self.assertEqual((a["state"], b["state"], run["state"]), ("done", "running", "running"))
            self.assertEqual(a["ended"] - a["started"], 120.5)
            self.assertEqual(a["attempts"][0]["ended"], a["ended"])
            self.assertNotIn("ended", b)
            self.assertNotIn("ended", run)

    def test_a_failure_its_repairs_fixed_counts_as_repaired(self):
        nodes = [{"id": "a", "state": "failed"}, {"id": "b", "state": "done", "repairOf": "a"},
                 {"id": "c", "state": "failed"}, {"id": "d", "state": "running", "repairOf": "c"}]
        self.assertEqual(ob.repaired_ids(nodes), {"a"})
        self.assertEqual(ob.run_summary({"id": "x", "nodes": nodes})["counts"],
                         {"nodes": 4, "done": 1, "running": 1, "failed": 1, "repaired": 1})


class RunsOps(BridgeCase):
    async def test_runs_ops_over_the_socket(self):
        async with Env() as env:
            kami = env.home / "profiles" / "kami"
            (kami / "config.yaml").unlink()
            _runs_profile(env.home / "r", ["20261028_093610_1b12a114"])
            import shutil
            for f in (env.home / "r" / "prof").iterdir():
                shutil.move(str(f), str(kami / f.name))
            s = await self.open(env)
            r = await s.req("runs.list", bot="kami")
            self.assertTrue(r["ok"], r)
            self.assertEqual([x["title"] for x in r["result"]["runs"]], ["Route hint dedup"])
            run_id = r["result"]["runs"][0]["id"]
            r = await s.req("runs.get", bot="kami", run=run_id)
            self.assertEqual(sorted(r["result"]["handoffs"]), ["implement", "verify"])
            self.assertEqual((await s.req("runs.get", bot="kami"))["error"]["code"], "bad_request")
            self.assertEqual((await s.req("runs.get", bot="kami", run="dag:x/y"))["error"]["code"], "not_found")
            self.assertEqual((await s.req("runs.list", bot="nobody"))["error"]["code"], "unknown_bot")


class RunsPr(unittest.TestCase):
    """The PR a node produced: parsed from its attempts' reasons, summary and handoff; its state from the person's own
    `gh` (stubbed here), cached, with a hard timeout, and `unknown` whenever gh cannot say."""

    def test_the_newest_reference_wins_and_a_url_names_its_repo(self):
        self.assertIsNone(ob.find_pr(["no pull request here", None, "issue #12", "#99 alone"]))
        self.assertEqual(ob.find_pr(["opened PR #2746"]), {"number": 2746})
        self.assertEqual(ob.find_pr(["PR #2746 open", "merged https://github.com/rlaope/oh-my-hermes/pull/2750 as 4e68fd8b4"]),
                         {"number": 2750, "repo": "rlaope/oh-my-hermes", "url": "https://github.com/rlaope/oh-my-hermes/pull/2750"})
        # a bare number later in the texts is newer than an earlier URL; it takes the repo of the one repo named
        self.assertEqual(ob.find_pr(["see https://github.com/rlaope/deepseek-bot/pull/87", "PR #88 open, gh pr checks green"]),
                         {"number": 88, "repo": "rlaope/deepseek-bot", "url": "https://github.com/rlaope/deepseek-bot/pull/88"})
        # two repos and a bare number that neither names: no repo is guessed
        self.assertEqual(ob.find_pr(["https://github.com/a/b/pull/1 https://github.com/c/d/pull/2", "pull request #3"]), {"number": 3})
        self.assertEqual(ob.find_pr(["PRs: #5"]), {"number": 5})
        self.assertIsNone(ob.find_pr(["https://github.com/a/b/issues/4", "PR#"]))

    def test_attach_prs_reads_reasons_summary_and_the_whole_handoff(self):
        run = {"nodes": [
            {"id": "a", "attempts": [{"reason": "PR #2712 + 6cb284636"}, {"reason": "opened https://github.com/o/r/pull/2713"}]},
            {"id": "b", "attempts": [], "summary": "Opened PR #2714"},
            {"id": "c", "attempts": [{"reason": "tests pass"}]},
        ]}
        ob.attach_prs(run, {"c": "x" * 9000 + "\nPR: https://github.com/o/r/pull/2715\n"})
        prs = {n["id"]: n.get("pr") for n in run["nodes"]}
        self.assertEqual(prs["a"], {"number": 2713, "repo": "o/r", "url": "https://github.com/o/r/pull/2713"})
        self.assertEqual(prs["b"], {"number": 2714, "repo": "o/r", "url": "https://github.com/o/r/pull/2714"})  # the run's one repo
        self.assertEqual(prs["c"]["number"], 2715)

    def test_runs_get_carries_the_pr_and_reads_nothing_new(self):
        with tempfile.TemporaryDirectory() as d:
            prof, dag = _runs_profile(Path(d), ["20261028_093610_1b12a114"])
            (dag / SMALL / "route-hint-dedup" / "verify.md").write_text(
                "## Verify\n- gates green\n- opened https://github.com/rlaope/oh-my-hermes/pull/2341\n", encoding="utf-8")
            before = _mtimes(dag, prof)
            got = ob.DagRuns().get("kami", prof, "dag:20261028_093610_1b12a114/route-hint-dedup")
            nodes = {n["id"]: n for n in got["run"]["nodes"]}
            self.assertEqual(nodes["verify"]["pr"], {"number": 2341, "repo": "rlaope/oh-my-hermes",
                                                     "url": "https://github.com/rlaope/oh-my-hermes/pull/2341"})
            self.assertNotIn("pr", nodes["implement"])
            # the list carries no node, so no PR either: it never waits on one
            self.assertNotIn("nodes", ob.DagRuns().list("kami", prof)[0])
            self.assertEqual(_mtimes(dag, prof), before)

    def test_state_comes_from_github_not_from_words(self):
        for view, want in (({"state": "OPEN", "isDraft": False}, "open"), ({"state": "OPEN", "isDraft": True}, "draft"),
                           ({"state": "MERGED", "mergedAt": "2026-11-10T01:00:00Z"}, "merged"),
                           ({"state": "CLOSED", "mergedAt": None}, "closed"), ({"state": "CLOSED", "mergedAt": "x"}, "merged"),
                           ({}, "unknown"), ({"state": "WAT"}, "unknown")):
            self.assertEqual(ob.pr_state_of(view), want, view)

    def test_states_are_cached_for_five_minutes_and_a_miss_for_one(self):
        calls, now = [], [1000.0]
        answers = {101: {"state": "MERGED", "mergedAt": "t", "url": "https://github.com/o/r/pull/101"}, 102: None}

        def view(repo, n):
            calls.append((repo, n))
            return answers[n]

        prs = ob.PrStates(view=view, clock=lambda: now[0])
        run = {"nodes": [{"id": "a", "pr": {"number": 101, "repo": "o/r"}}, {"id": "b", "pr": {"number": 102, "repo": "o/r"}},
                         {"id": "c", "pr": {"number": 7}}, {"id": "d"}]}
        got = prs.states(run)
        self.assertEqual(got, {"a": {"number": 101, "repo": "o/r", "state": "merged", "url": "https://github.com/o/r/pull/101"},
                               "b": {"number": 102, "repo": "o/r", "state": "unknown"},
                               "c": {"number": 7, "state": "unknown"}})  # no repo: not asked
        self.assertEqual(sorted(calls), [("o/r", 101), ("o/r", 102)])
        now[0] += ob.PR_TTL_MISS + 1
        prs.states(run)
        self.assertEqual(sorted(calls), [("o/r", 101), ("o/r", 102), ("o/r", 102)])  # only the miss is asked again
        now[0] += ob.PR_TTL
        prs.states(run)
        self.assertEqual(len(calls), 5)
        self.assertEqual((ob.PR_TTL, ob.PR_TIMEOUT), (300.0, 3.0))

    def test_gh_pr_view_runs_one_fixed_argv_with_a_timeout_and_fails_soft(self):
        seen = {}

        def run(argv, **kw):
            seen.update(argv=argv, timeout=kw["timeout"], env=kw["env"])
            return mock.Mock(returncode=0, stdout='{"state":"OPEN","isDraft":true,"mergedAt":null,"url":"u"}')

        with mock.patch.object(ob.subprocess, "run", run):
            self.assertEqual(ob.gh_pr_view("rlaope/oh-my-hermes", 2360, gh="/bin/gh")["isDraft"], True)
        self.assertEqual(seen["argv"], ["/bin/gh", "pr", "view", "2360", "-R", "rlaope/oh-my-hermes", "--json", "state,isDraft,mergedAt,url"])
        self.assertEqual(seen["timeout"], ob.PR_TIMEOUT)
        self.assertEqual(seen["env"]["GH_PROMPT_DISABLED"], "1")

        def slow(argv, **kw):
            raise ob.subprocess.TimeoutExpired(argv, kw["timeout"])

        for fake in (slow, lambda a, **k: mock.Mock(returncode=1, stdout=""), lambda a, **k: mock.Mock(returncode=0, stdout="nope")):
            with mock.patch.object(ob.subprocess, "run", fake):
                self.assertIsNone(ob.gh_pr_view("o/r", 1, gh="/bin/gh"))
        with mock.patch.object(ob, "_gh_path", return_value=None):
            self.assertIsNone(ob.gh_pr_view("o/r", 1))  # no gh: no state, nothing run
        for repo, n in (("o/r; rm -rf /", 1), ("-R/x", 1), ("o/r", 0), ("o/r", True), ("o/r", "1")):
            with self.assertRaises(ValueError):
                ob.gh_pr_view(repo, n, gh="/bin/gh")


class RunsPrOps(BridgeCase):
    async def test_runs_prs_over_the_socket(self):
        async with Env() as env:
            kami = env.home / "profiles" / "kami"
            (kami / "config.yaml").unlink()
            _runs_profile(env.home / "r", ["20261028_093610_1b12a114"])
            import shutil
            for f in (env.home / "r" / "prof").iterdir():
                shutil.move(str(f), str(kami / f.name))
            dag = env.home / "r" / "omh" / "runtime" / "dag"
            (dag / SMALL / "route-hint-dedup" / "verify.md").write_text("opened PR https://github.com/o/r/pull/9\n", encoding="utf-8")
            env.bridge.prs = ob.PrStates(view=lambda repo, n: {"state": "OPEN", "isDraft": True})
            s = await self.open(env)
            run_id = "dag:20261028_093610_1b12a114/route-hint-dedup"
            r = await s.req("runs.get", bot="kami", run=run_id)
            self.assertEqual({n["id"]: n.get("pr", {}).get("number") for n in r["result"]["run"]["nodes"]}, {"implement": None, "verify": 9})
            r = await s.req("runs.prs", bot="kami", run=run_id)
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["result"], {"prs": {"verify": {"number": 9, "repo": "o/r", "url": "https://github.com/o/r/pull/9", "state": "draft"}}})
            self.assertEqual((await s.req("runs.prs", bot="kami"))["error"]["code"], "bad_request")
            self.assertEqual((await s.req("runs.prs", bot="kami", run="dag:x/y"))["error"]["code"], "not_found")
            self.assertEqual((await s.req("runs.prs", bot="kami", run="claude:abc"))["result"], {"prs": {}})


CLI_FIX = HERE / "fixtures" / "cli"
CLAUDE_SID = "ec38bc0b-8eb7-936b-b856-daaee28015c4"
CODEX_ROOT = "c5e14c89-54b2-c703-769f-a6207ed501ea"
FIXED_NOW = 1793700000.0  # 2026-11-03, after both fixture sessions; `since=0` keeps them in range


def _cli_home(root: Path) -> dict[str, Path]:
    """A copy of the redacted CLI fixtures as Claude Code and Codex homes; OmO (fixture at cli/omo), pi, omp, grok absent."""
    import shutil
    shutil.copytree(CLI_FIX, root / "cli")
    return {"claude": root / "cli" / "claude-home", "codex": root / "cli" / "codex",
            "omo": root / "none-omo", "pi": root / "none-pi", "omp": root / "none-omp", "grok": root / "none-grok"}


def _claude_layout(root: Path) -> Path:
    """Fixtures keep the project folder at `claude/<slug>`; Claude Code has it at `<home>/projects/<slug>`."""
    import shutil
    home = root / "cli" / "claude-home"
    (home / "projects").mkdir(parents=True)
    shutil.move(str(root / "cli" / "claude" / "-w-web-app"), str(home / "projects" / "-w-web-app"))
    return home / "projects" / "-w-web-app"


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")


def _age(path: Path, seconds: float, now: float = FIXED_NOW) -> None:
    os.utime(path, (now - seconds, now - seconds))


class CliRunsClaude(unittest.TestCase):
    """Claude Code Agent/Task subagents from a real (redacted) transcript: one run per session, one node per call."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.homes = _cli_home(self.root)
        self.proj = _claude_layout(self.root)
        self.main = self.proj / f"{CLAUDE_SID}.jsonl"
        self.subs = self.proj / CLAUDE_SID / "subagents"

    def cli(self, now: float = FIXED_NOW) -> ob.CliRuns:
        return ob.CliRuns(self.homes, clock=lambda: now)

    def test_the_real_session_is_one_layer_with_each_calls_state_model_and_final_text(self):
        before = _mtimes(self.root / "cli")
        cli = self.cli()
        listed = cli.list("claude", "/w/web-app", 0.0)
        self.assertEqual([r["id"] for r in listed["runs"]], [f"claude:{CLAUDE_SID}"])
        summary = listed["runs"][0]
        self.assertEqual((summary["kind"], summary["agent"], summary["title"], summary["cwd"]),
                         ("claude-task", "claude", "Ship the API fix", "/w/web-app"))
        self.assertEqual(summary["counts"], {"nodes": 3, "done": 2, "running": 0, "failed": 1})
        run = cli.get(summary["id"])["run"]
        self.assertEqual({n["layer"] for n in run["nodes"]}, {0})
        by = {n["label"]: n for n in run["nodes"]}
        # the first call came back as an error: failed, with the tool result as the reason
        bad = by["Review the API change"]
        self.assertEqual((bad["state"], bad["attempts"][0]["reason"]), ("failed", "Agent type not available in this folder."))
        # the two background agents finished through their task notifications, with their final text
        for label, text in (("Check the build on Windows", "The Windows build compiles; one warning about an unused import."),
                            ("Write the release note", "Release note drafted under Unreleased with the PR link.")):
            n = by[label]
            self.assertEqual((n["state"], n["summary"]), ("done", text))
            self.assertLessEqual(len(n["summary"]), ob.SUMMARY_MAX)
            self.assertLess(n["started"], n["ended"])
        # the subagent's own transcript names its model; the call only said "opus"
        self.assertEqual({n["model"] for n in run["nodes"]}, {"claude-opus-5-5"})
        self.assertTrue(all(n["executor"] == "claude" and n["lane"] == "executor" for n in run["nodes"]))
        self.assertEqual(run["state"], "failed")
        self.assertEqual(_mtimes(self.root / "cli"), before, "reading a transcript changed a file")

    def test_two_task_calls_with_results_are_a_done_run_of_two(self):
        rows = _jsonl(self.main)
        call = next(r for r in rows if r["type"] == "assistant")
        bad_id = call["message"]["content"][0]["id"]
        rows = [r for r in rows if r is not call and not any(
            isinstance(c, dict) and c.get("tool_use_id") == bad_id for c in (r.get("message") or {}).get("content") or [])]
        _write_jsonl(self.main, rows)
        run = self.cli().get(f"claude:{CLAUDE_SID}")["run"]
        self.assertEqual([(n["state"], n["layer"]) for n in run["nodes"]], [("done", 0), ("done", 0)])
        self.assertTrue(all(n["summary"] for n in run["nodes"]))
        self.assertEqual(run["state"], "done")
        self.assertEqual(run["ended"], max(n["ended"] for n in run["nodes"]))

    def _drop_notes(self):
        rows = [r for r in _jsonl(self.main) if "task-notification" not in json.dumps(r)]
        _write_jsonl(self.main, rows)
        import shutil
        shutil.rmtree(self.subs)

    def test_a_task_with_no_result_in_a_file_quiet_for_over_10_minutes_failed_no_result(self):
        self._drop_notes()
        _age(self.main, 11 * 60)
        run = self.cli().get(f"claude:{CLAUDE_SID}")["run"]
        quiet = [n for n in run["nodes"] if n["label"] != "Review the API change"]
        self.assertEqual([(n["state"], n["attempts"][0]["reason"]) for n in quiet], [("failed", "no result")] * 2)
        self.assertEqual(quiet[0]["summary"], "no result")

    def test_the_same_task_in_a_file_that_moved_recently_is_still_running(self):
        self._drop_notes()
        _age(self.main, 60)
        run = self.cli().get(f"claude:{CLAUDE_SID}")["run"]
        self.assertEqual(sorted(n["state"] for n in run["nodes"]), ["failed", "running", "running"])
        self.assertEqual(run["state"], "running")
        self.assertNotIn("ended", run)

    def test_a_subagent_still_writing_keeps_a_quiet_session_running(self):
        """The main transcript is quiet while a background agent works: the subagent's own file counts."""
        rows = [r for r in _jsonl(self.main) if "task-notification" not in json.dumps(r)]
        _write_jsonl(self.main, rows)
        for meta in self.subs.glob("*.meta.json"):
            m = json.loads(meta.read_text(encoding="utf-8"))
            m.pop("finished")
            meta.write_text(json.dumps(m), encoding="utf-8")
        _age(self.main, 30 * 60)
        for log in self.subs.glob("*.jsonl"):
            _age(log, 30)
        run = self.cli().get(f"claude:{CLAUDE_SID}")["run"]
        self.assertEqual(sorted(n["state"] for n in run["nodes"]), ["failed", "running", "running"])

    def test_bodies_never_leave_the_reader(self):
        """Prompts and step text stay in the transcript: only labels, the title and final text are sent."""
        rows = _jsonl(self.main)
        for r in rows:
            for c in (r.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    c["input"]["prompt"] = "SECRET-PROMPT " * 50
        _write_jsonl(self.main, rows)
        cli = self.cli()
        out = json.dumps([cli.list(None, None, 0.0), cli.get(f"claude:{CLAUDE_SID}")])
        self.assertNotIn("SECRET-PROMPT", out)
        self.assertNotIn("(step removed)", out)

    def test_appended_lines_are_read_incrementally_and_a_half_written_line_waits(self):
        cli = self.cli()
        self.assertEqual(cli.list("claude", None, 0.0)["runs"][0]["counts"]["nodes"], 3)
        call = {"type": "assistant", "isSidechain": False, "timestamp": "2026-10-27T03:10:00.000Z", "sessionId": CLAUDE_SID,
                "message": {"model": "claude-opus-5-5", "content": [{"type": "tool_use", "id": "toolu_new", "name": "Task",
                                                                     "input": {"description": "Trace the slow query"}}]}}
        line = json.dumps(call) + "\n"
        with open(self.main, "a", encoding="utf-8") as fh:
            fh.write(line[:40])  # mid-write
        self.assertEqual(cli.list("claude", None, 0.0)["runs"][0]["counts"]["nodes"], 3)
        with open(self.main, "a", encoding="utf-8") as fh:
            fh.write(line[40:])
        run = cli.get(f"claude:{CLAUDE_SID}")["run"]
        self.assertEqual(cli.list("claude", None, 0.0)["runs"][0]["counts"]["nodes"], 4)
        self.assertIn("Trace the slow query", [n["label"] for n in cli.get(f"claude:{CLAUDE_SID}")["run"]["nodes"]])
        self.assertEqual(len(run["nodes"]), 3)  # the earlier object is not mutated by the later read

    def test_cwd_and_since_filter_and_request_snapshots_are_not_calls(self):
        cli = self.cli()
        self.assertEqual(cli.list("claude", "/w/other", 0.0)["runs"], [])
        self.assertEqual(cli.list("claude", "/w/web-app", FIXED_NOW)["runs"], [])
        # an api-request snapshot repeats tool names; it must never count as a call
        with open(self.main, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "api-request-shape", "tools": [{"name": "Agent"}],
                                 "message": {"content": [{"type": "tool_use", "id": "x", "name": "Agent"}]}}) + "\n")
        self.assertEqual(cli.list("claude", None, 0.0)["runs"][0]["counts"]["nodes"], 3)

    def test_a_symlinked_project_folder_is_refused(self):
        import shutil
        outside = self.root / "elsewhere"
        shutil.move(str(self.proj), str(outside))
        self.proj.symlink_to(outside, target_is_directory=True)  # projects/-w-web-app -> a folder outside projects
        cli = self.cli()
        self.assertEqual(cli.list("claude", "/w/web-app", 0.0)["runs"], [])
        self.assertEqual(cli.list("claude", None, 0.0)["runs"], [])


class CliRunsCodex(unittest.TestCase):
    """Codex spawned sub-agents from a real (redacted) parent rollout and its two child rollouts."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.homes = _cli_home(self.root)
        self.day = self.root / "cli" / "codex" / "sessions" / "2026" / "11" / "02"

    def test_children_are_nodes_with_their_own_model_effort_and_last_message(self):
        before = _mtimes(self.root / "cli")
        cli = ob.CliRuns(self.homes, clock=lambda: FIXED_NOW)
        listed = cli.list("codex", "/w/api-server", 0.0)
        self.assertEqual([r["id"] for r in listed["runs"]], [f"codex:{CODEX_ROOT}"])
        self.assertEqual(listed["runs"][0]["title"], "Harden the API server")
        self.assertEqual(listed["runs"][0]["counts"], {"nodes": 2, "done": 2, "running": 0, "failed": 0})
        run = cli.get(f"codex:{CODEX_ROOT}")["run"]
        self.assertEqual((run["kind"], run["agent"], run["state"]), ("codex-sub", "codex", "done"))
        self.assertEqual([n["label"] for n in run["nodes"]], ["Review api", "Check build"])
        for n, text in zip(run["nodes"], ("API review done: one missing null check, fixed.",
                                          "Build checked on both targets; no errors.")):
            # the child's own turn (after its copied parent history), never the parent's model
            self.assertEqual((n["model"], n["effort"], n["executor"]), ("gpt-6-astra", "low", "codex"))
            self.assertEqual((n["state"], n["summary"], n["layer"], n["deps"]), ("done", text, 0, []))
            self.assertLess(n["started"], n["ended"])
        self.assertEqual(_mtimes(self.root / "cli"), before)

    def test_an_aborted_child_is_cancelled_and_a_silent_one_fails_no_result(self):
        kid = next(p for p in self.day.glob("*.jsonl") if "dd005c2c" in p.name)
        rows = _jsonl(kid)
        rows = rows[:-1] + [{"timestamp": "2026-11-02T16:38:56.000Z", "ordinal": 9999, "type": "event_msg",
                             "payload": {"type": "turn_aborted", "reason": "interrupted"}}]
        _write_jsonl(kid, rows)
        other = next(p for p in self.day.glob("*.jsonl") if "72893de0" in p.name)
        _write_jsonl(other, _jsonl(other)[:-1])  # no task_complete yet
        _age(other, 20 * 60)
        run = ob.CliRuns(self.homes, clock=lambda: FIXED_NOW).get(f"codex:{CODEX_ROOT}")["run"]
        by = {n["label"]: n for n in run["nodes"]}
        self.assertEqual((by["Review api"]["state"], by["Review api"]["attempts"][0]["reason"]), ("cancelled", "interrupted"))
        self.assertEqual((by["Check build"]["state"], by["Check build"]["attempts"][0]["reason"]), ("failed", "no result"))
        self.assertEqual(run["state"], "failed")

    def test_the_parent_history_copy_is_not_the_childs_turn(self):
        """A child file opens with its parent's turns; before `subagent_history_start_ordinal` nothing counts."""
        kid = next(p for p in self.day.glob("*.jsonl") if "dd005c2c" in p.name)
        rows = _jsonl(kid)
        rows[0]["payload"]["subagent_history_start_ordinal"] = 10_000
        _write_jsonl(kid, rows)
        _age(kid, 60)
        node = next(n for n in ob.CliRuns(self.homes, clock=lambda: FIXED_NOW).get(f"codex:{CODEX_ROOT}")["run"]["nodes"]
                    if n["label"] == "Review api")
        self.assertEqual(node["state"], "running")
        self.assertNotIn("model", node)

    def test_a_session_without_sub_agents_is_not_a_run(self):
        for p in self.day.glob("*.jsonl"):
            if CODEX_ROOT not in p.name:
                p.unlink()
        self.assertEqual(ob.CliRuns(self.homes, clock=lambda: FIXED_NOW).list("codex", None, 0.0)["runs"], [])


class CliRunsOmo(unittest.TestCase):
    """OmO's subagents from its own task records (real, redacted: OmO 5.1.56, two background subagents)."""

    def test_the_real_records_are_one_session_run_with_each_subagents_answer_and_model(self):
        with tempfile.TemporaryDirectory() as d:
            homes = _cli_home(Path(d))
            homes["omo"] = Path(d) / "cli" / "omo"
            before = _mtimes(Path(d) / "cli")
            cli = ob.CliRuns(homes, clock=lambda: FIXED_NOW)
            self.assertEqual(cli.agents()["omo"], "found")
            listed = cli.list("omo", "/w/omo-proj", 0.0)["runs"]
            self.assertEqual([r["id"] for r in listed], ["omo:01a1ca26-77fa-7eeb-a2ba-d23056b97a50"])
            self.assertEqual((listed[0]["owner"], listed[0]["counts"]),
                             ({"type": "session", "id": "01a1ca26-77fa-7eeb-a2ba-d23056b97a50"},
                              {"nodes": 2, "done": 2, "running": 0, "failed": 0}))
            run = cli.get(listed[0]["id"])["run"]
            self.assertEqual([(n["label"], n["state"], n["summary"], n["model"], n["lane"]) for n in run["nodes"]],
                             [("Report the first line of a.txt", "done", "alpha line", "claude-haiku-5-5", "explore"),
                              (run["nodes"][1]["label"], "done", "2", "claude-haiku-5-5", run["nodes"][1]["lane"])])
            self.assertTrue(all(n["started"] < n["ended"] for n in run["nodes"]))
            self.assertEqual(cli.list("omo", "/w/elsewhere", 0.0)["runs"], [])
            self.assertEqual(_mtimes(Path(d) / "cli"), before, "reading OmO's records changed a file")

    def test_the_runs_time_is_its_first_subagents_start_to_its_last_ones_end(self):
        # the chat card's rule (#2800): the fan-out runs from the first subagent's start to the last one's end. On the
        # real records that is 10:28:41.062 -> 10:28:56.701, the span of the two rows the chat shows (9.9 s and
        # 15.5 s by OmO's own duration_ms, starting 0.14 s apart)
        with tempfile.TemporaryDirectory() as d:
            homes = _cli_home(Path(d))
            homes["omo"] = Path(d) / "cli" / "omo"
            run = ob.CliRuns(homes, clock=lambda: FIXED_NOW).get("omo:01a1ca26-77fa-7eeb-a2ba-d23056b97a50")["run"]
            self.assertEqual(run["started"], min(n["started"] for n in run["nodes"]))
            self.assertEqual(run["ended"], max(n["ended"] for n in run["nodes"]))
            self.assertAlmostEqual(run["ended"] - run["started"], 15.639, places=2)
            self.assertEqual([round(n["ended"] - n["started"], 1) for n in run["nodes"]], [9.9, 15.5])

    def test_a_running_record_quiet_for_over_10_minutes_failed_no_result(self):
        with tempfile.TemporaryDirectory() as d:
            homes = _cli_home(Path(d))
            homes["omo"] = Path(d) / "cli" / "omo"
            p = next((homes["omo"] / "agent" / "projects").glob("*/senpi-task/tasks/st_01a1ca28.json"))
            r = json.loads(p.read_text())
            r.update(status="running", terminal_at=None, final_response=None, updated_at="2026-01-01T00:00:00Z")
            p.write_text(json.dumps(r))
            run = ob.CliRuns(homes, clock=lambda: FIXED_NOW).get("omo:01a1ca26-77fa-7eeb-a2ba-d23056b97a50")["run"]
            n = next(x for x in run["nodes"] if x["id"] == "st_01a1ca28")
            self.assertEqual((n["state"], n["attempts"][0]["reason"]), ("failed", "no result"))


class CliRunsOmoFolder(unittest.TestCase):
    """O15: OmO keeps a folder's subagent records in that folder (`<folder>/.omo/senpi-task/tasks/`) when they are
    already there, and OmO 5.0 always does. Real records (redacted: OmO 5.0.0-beta.65, two subagents that failed on
    their first model and the two retries that answered), stored as `dot-omo/` because the repo ignores `.omo/`."""

    SID = "01a1ce7e-2a44-78c8-9e51-05926dd01556"

    def setUp(self):
        import shutil
        self._d = tempfile.TemporaryDirectory()
        root = Path(self._d.name)
        self.homes = _cli_home(root)
        self.homes["omo"] = root / "omo-home"
        (self.homes["omo"] / "agent" / "projects").mkdir(parents=True)
        self.folder = root / "omo-folder"
        shutil.copytree(CLI_FIX / "omo-folder" / "dot-omo", self.folder / ".omo")
        for p in (self.folder / ".omo" / "senpi-task" / "tasks").glob("*.json"):
            r = json.loads(p.read_text(encoding="utf-8"))
            r["spawn_spec"] = {"cwd": str(self.folder)}
            p.write_text(json.dumps(r), encoding="utf-8")

    def tearDown(self):
        self._d.cleanup()

    def test_the_sessions_folder_records_are_its_run_with_each_answer(self):
        before = _mtimes(self.folder)
        cli = ob.CliRuns(self.homes, clock=lambda: FIXED_NOW)
        listed = cli.list("omo", str(self.folder), 0.0)["runs"]
        self.assertEqual([r["id"] for r in listed], [f"omo:{self.SID}"])
        self.assertEqual(listed[0]["counts"], {"nodes": 4, "done": 2, "running": 0, "failed": 2})
        run = cli.get(f"omo:{self.SID}")["run"]
        self.assertEqual([(n["label"], n["state"]) for n in run["nodes"]],
                         [("Report the first line of a.txt", "failed"), ("Report how many lines b.txt has", "failed"),
                          ("Report the first line of a.txt", "done"), ("Report how many lines b.txt has", "done")])
        self.assertIn("alpha line", run["nodes"][2]["summary"])
        self.assertIn("3 lines", run["nodes"][3]["summary"])
        self.assertEqual(_mtimes(self.folder), before, "reading OmO's records changed a file")

    def test_another_folders_records_and_links_are_not_read(self):
        cli = ob.CliRuns(self.homes, clock=lambda: FIXED_NOW)
        # asked for another folder (or for none), the records inside this one are not read
        self.assertEqual(cli.list("omo", str(Path(self._d.name) / "elsewhere"), 0.0)["runs"], [])
        self.assertEqual(cli.list("omo", None, 0.0)["runs"], [])
        # a linked .omo, or a linked senpi-task inside it, is skipped
        for link in (".omo", "senpi-task"):
            other = Path(self._d.name) / f"linked-{link.strip('.')}"
            other.mkdir()
            if link == ".omo":
                (other / ".omo").symlink_to(self.folder / ".omo", target_is_directory=True)
            else:
                (other / ".omo").mkdir()
                (other / ".omo" / "senpi-task").symlink_to(self.folder / ".omo" / "senpi-task", target_is_directory=True)
            self.assertEqual(ob.CliRuns(self.homes, clock=lambda: FIXED_NOW).list("omo", str(other), 0.0)["runs"], [], link)


class ClaudeAnswer(unittest.TestCase):
    def test_a_subagents_answer_is_its_own_words_not_claude_codes_frame(self):
        # Claude Code 2.1.322: the tool result wraps the subagent's words; toolUseResult.content has them alone
        frame = ("[Subagent hand-back] The subagent finished. The report follows:\n```\nalpha line\n```\n"
                 "agentId: a1 (use SendMessage to continue)")
        self.assertEqual(ob._claude_answer({"content": [{"type": "text", "text": "alpha line"}]}, {"content": frame}), "alpha line")
        self.assertEqual(ob._claude_answer({}, {"content": frame}), "alpha line")
        used = "<tools-used-before-summary>Read a.txt</tools-used-before-summary>\n3 lines"
        self.assertEqual(ob._claude_answer({"content": [{"type": "text", "text": used}]}, {}), "3 lines")


class CliRunsAgents(unittest.TestCase):
    def test_pi_omp_and_grok_have_no_runs_and_say_why(self):
        with tempfile.TemporaryDirectory() as d:
            homes = _cli_home(Path(d))
            (Path(d) / "none-grok").mkdir()
            cli = ob.CliRuns(homes, clock=lambda: FIXED_NOW)
            for agent in ("pi", "omp", "grok"):
                self.assertEqual(cli.list(agent, None, 0.0)["runs"], [])
            self.assertEqual({k: v for k, v in cli.agents().items() if k in ("pi", "omp", "grok")},
                             {"pi": "not_installed", "omp": "not_installed", "grok": "no_adapter"})

    def test_missing_homes_mean_no_runs(self):
        with tempfile.TemporaryDirectory() as d:
            homes = {k: Path(d) / k for k in ob.CLI_AGENTS}
            out = ob.CliRuns(homes).list(None, None, None)
            self.assertEqual(out["runs"], [])
            self.assertEqual(set(out["agents"].values()), {"not_installed"})

    def test_claude_slug_matches_claude_codes_folder_names(self):
        self.assertEqual(ob.claude_slug("/Users/a.b@c.ai/Desktop/x_y"), "-Users-a-b-c-ai-Desktop-x-y")

    def test_cli_homes_follow_the_tools_own_env_vars(self):
        homes = ob.cli_homes({"CLAUDE_CONFIG_DIR": "/c", "CODEX_HOME": "/x"})
        self.assertEqual((homes["claude"], homes["codex"]), (Path("/c"), Path("/x")))


class CliRunsOps(BridgeCase):
    async def test_runs_cli_over_the_socket_and_runs_get_for_a_cli_run(self):
        async with Env() as env:
            homes = _cli_home(env.home / "r")
            _claude_layout(env.home / "r")
            env.bridge.cli = ob.CliRuns(homes, clock=lambda: FIXED_NOW)
            s = await self.open(env)
            r = await s.req("runs.cli", since=0)
            self.assertTrue(r["ok"], r)
            self.assertEqual(sorted(x["id"] for x in r["result"]["runs"]),
                             sorted([f"claude:{CLAUDE_SID}", f"codex:{CODEX_ROOT}"]))
            self.assertTrue(all("nodes" not in x for x in r["result"]["runs"]))
            r = await s.req("runs.cli", agent="codex", cwd="/w/api-server", since=0)
            self.assertEqual([x["agent"] for x in r["result"]["runs"]], ["codex"])
            r = await s.req("runs.get", bot="kami", run=f"claude:{CLAUDE_SID}")
            self.assertEqual((len(r["result"]["run"]["nodes"]), r["result"]["handoffs"]), (3, {}))
            for bad in ({"agent": "cursor"}, {"cwd": ""}, {"since": "yesterday"}, {"since": True}):
                self.assertEqual((await s.req("runs.cli", **bad))["error"]["code"], "bad_request", bad)
            self.assertEqual((await s.req("runs.get", bot="kami", run="codex:nope"))["error"]["code"], "not_found")
            # a SESSIONS chat asks for its own run with no bot: a CLI run is found by its id alone
            r = await s.req("runs.get", run=f"claude:{CLAUDE_SID}")
            self.assertEqual(len(r["result"]["run"]["nodes"]), 3)


class CliTitle(unittest.TestCase):
    """`cli.title`: the name a SESSIONS chat's conversation has in Claude Code's or Codex's own files."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.homes = _cli_home(self.root)
        self.proj = _claude_layout(self.root)
        self.main = self.proj / f"{CLAUDE_SID}.jsonl"

    def cli(self) -> ob.CliRuns:
        return ob.CliRuns(self.homes, clock=lambda: FIXED_NOW)

    def test_claude_code_title_by_folder_or_by_id_alone_and_codex_thread_name(self):
        before = _mtimes(self.root / "cli")
        cli = self.cli()
        self.assertEqual(cli.title("claude", CLAUDE_SID, "/w/web-app"), "Ship the API fix")
        # a folder that moved (or none): the transcript is found by its id in any project folder
        self.assertEqual(cli.title("claude", CLAUDE_SID, "/elsewhere"), "Ship the API fix")
        self.assertEqual(cli.title("claude", CLAUDE_SID), "Ship the API fix")
        self.assertEqual(cli.title("codex", CODEX_ROOT), "Harden the API server")
        self.assertEqual(cli.title("claude", "00000000-0000-4000-8000-000000000000", "/w/web-app"), "")
        self.assertEqual(cli.title("codex", "00000000-0000-4000-8000-000000000000"), "")
        self.assertEqual(cli.title("pi", CLAUDE_SID), "")
        self.assertEqual(_mtimes(self.root / "cli"), before)  # read-only

    def test_the_latest_title_wins_and_a_rename_in_claude_code_beats_the_ai_title(self):
        cli = self.cli()
        rows = _jsonl(self.main)
        rows.append({"type": "ai-title", "aiTitle": "  OAuth redirect\nloop  ", "sessionId": CLAUDE_SID})
        _write_jsonl(self.main, rows)
        self.assertEqual(cli.title("claude", CLAUDE_SID, "/w/web-app"), "OAuth redirect loop")
        rows.append({"type": "custom-title", "customTitle": "my name", "sessionId": CLAUDE_SID})
        rows.append({"type": "ai-title", "aiTitle": "later AI title", "sessionId": CLAUDE_SID})
        _write_jsonl(self.main, rows)
        self.assertEqual(cli.title("claude", CLAUDE_SID, "/w/web-app"), "my name")
        # one more title line is read without reading the transcript again (only appended lines)
        with open(self.main, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "custom-title", "customTitle": "x" * 300, "sessionId": CLAUDE_SID}) + "\n")
        self.assertEqual(len(cli.title("claude", CLAUDE_SID, "/w/web-app")), ob.CLI_TITLE)

    def test_message_text_that_mentions_a_title_is_not_a_title(self):
        rows = [r for r in _jsonl(self.main) if r.get("type") != "ai-title"]
        rows.append({"type": "user", "message": {"role": "user", "content": 'say {"type":"ai-title","aiTitle":"fake"}'},
                     "sessionId": CLAUDE_SID})
        _write_jsonl(self.main, rows)
        self.assertEqual(self.cli().title("claude", CLAUDE_SID, "/w/web-app"), "")

    def test_symlinked_transcripts_are_not_read(self):
        other = self.root / "outside.jsonl"
        _write_jsonl(other, [{"type": "ai-title", "aiTitle": "secret", "sessionId": CLAUDE_SID}])
        link_dir = self.proj.parent / "-w-linked"
        link_dir.mkdir()
        sid = "11111111-2222-4333-8444-555555555555"
        try:
            (link_dir / f"{sid}.jsonl").symlink_to(other)
        except OSError:
            self.skipTest("no symlinks here")
        self.assertEqual(self.cli().title("claude", sid, "/w/linked"), "")
        self.assertEqual(self.cli().title("claude", sid), "")


class CliTitleOps(BridgeCase):
    async def test_cli_title_over_the_socket_checks_its_params(self):
        async with Env() as env:
            homes = _cli_home(env.home / "r")
            _claude_layout(env.home / "r")
            env.bridge.cli = ob.CliRuns(homes, clock=lambda: FIXED_NOW)
            s = await self.open(env)
            r = await s.req("cli.title", agent="claude", session=CLAUDE_SID, cwd="/w/web-app")
            self.assertEqual(r["result"], {"title": "Ship the API fix"}, r)
            r = await s.req("cli.title", agent="codex", session=CODEX_ROOT)
            self.assertEqual(r["result"], {"title": "Harden the API server"}, r)
            for bad in ({"agent": "pi", "session": CLAUDE_SID}, {"agent": "claude", "session": "../../etc/passwd"},
                        {"agent": "claude", "session": CLAUDE_SID + "/x"}, {"agent": "claude"},
                        {"agent": "claude", "session": CLAUDE_SID, "cwd": ""}):
                self.assertEqual((await s.req("cli.title", **bad))["error"]["code"], "bad_request", bad)


# Lines copied from real session files on the author's Mac, redacted (ids, request ids, cwd, branch removed).
CODEX_LINE = ('{"timestamp":"2026-11-04T02:33:18.543Z","type":"event_msg","payload":{"type":"token_count","info":'
              '{"total_token_usage":{"input_tokens":44192374,"output_tokens":89083},"model_context_window":353400},'
              '"rate_limits":{"limit_id":"codex","limit_name":null,"primary":{"used_percent":15.0,"window_minutes":10080,'
              '"resets_at":1794331456},"secondary":null,"credits":{"has_credits":true,"unlimited":false},'
              '"individual_limit":null,"spend_control_reached":null,"plan_type":"pro","rate_limit_reached_type":null}}}')
CLAUDE_LINE = ('{"type":"assistant","timestamp":"2026-11-09T04:06:43.709Z","message":{"model":"<synthetic>","role":"assistant",'
               '"content":[{"type":"text","text":"You\'ve hit your weekly limit"}]},"apiError":"usage_limit_reached",'
               '"apiErrorParams":{"rate_limit_info":{"status":"rejected","resetsAt":1794211200,"rateLimitType":"seven_day",'
               '"overageStatus":"rejected","overageDisabledReason":"org_level_disabled","isUsingOverage":false}},'
               '"error":"rate_limit","isApiErrorMessage":true,"apiErrorStatus":429,"cwd":"/w/repo"}')


class Usage(unittest.TestCase):
    """usage.read: the CLIs' own session files, tail-read, newest event wins; never a number the source lacks."""

    def home(self) -> Path:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return Path(d.name)

    def write(self, path: Path, *lines: str, mtime: float | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def test_codex_weekly_percent_and_plan_from_a_real_line(self):
        h = self.home()
        self.write(h / ".codex/sessions/2026/11/03/rollout-a.jsonl", '{"type":"session_meta"}', CODEX_LINE)
        r = ob.read_usage(h, now=1794300000.0, which=lambda _: None)
        self.assertEqual(r["providers"], [{
            "id": "codex", "plan": "pro", "state": "ok", "source_mtime": (h / ".codex/sessions/2026/11/03/rollout-a.jsonl").stat().st_mtime,
            "windows": [{"label": "Weekly", "used_percent": 15.0, "resets_at": 1794331456.0}]}])

    def test_codex_newest_event_across_files_and_windows_and_near(self):
        h = self.home()
        old = CODEX_LINE.replace("2026-11-04T02:33:18", "2026-11-01T00:00:00")
        new = CODEX_LINE.replace('"primary":{"used_percent":15.0,"window_minutes":10080',
                                 '"primary":{"used_percent":73.0,"window_minutes":300').replace(
            '"secondary":null', '"secondary":{"used_percent":60.0,"window_minutes":10080,"resets_at":1794700000}')
        self.write(h / ".codex/sessions/2026/11/01/rollout-old.jsonl", old, mtime=1794000000)
        self.write(h / ".codex/sessions/2026/11/04/rollout-new.jsonl", new, '{"type":"event_msg","payload":{"type":"agent_message"}}',
                   mtime=1794100000)
        p = ob.read_usage(h, now=1794300000.0, which=lambda _: None)["providers"][0]
        self.assertEqual([(w["label"], w["used_percent"]) for w in p["windows"]], [("5 hours", 73.0), ("Weekly", 60.0)])
        self.assertEqual(p["state"], "near")
        self.assertEqual(ob._window_label(120), "2h")
        self.assertEqual(ob._window_label(2880), "2d")

    def test_claude_rejected_seven_day_is_limited_with_no_percent(self):
        h = self.home()
        self.write(h / ".claude/projects/-w-repo/s1.jsonl", '{"type":"user"}', CLAUDE_LINE)
        p = ob.read_usage(h, now=1794200000.0, which=lambda _: None)["providers"][0]
        self.assertEqual(p["id"], "claude")
        self.assertEqual(p["state"], "limited")
        self.assertEqual(p["windows"], [{"label": "Weekly", "resets_at": 1794211200.0}])
        self.assertNotIn("used_percent", json.dumps(p))
        self.assertNotIn("plan", p)

    def test_a_reset_time_in_the_past_is_stale_and_loses_its_number(self):
        h = self.home()
        self.write(h / ".codex/sessions/2026/11/03/rollout-a.jsonl", CODEX_LINE)
        self.write(h / ".claude/projects/-w-repo/s1.jsonl", CLAUDE_LINE)
        ps = {p["id"]: p for p in ob.read_usage(h, now=1794400000.0, which=lambda _: None)["providers"]}
        self.assertEqual(ps["codex"]["state"], "stale")
        self.assertEqual(ps["codex"]["windows"], [{"label": "Weekly", "resets_at": 1794331456.0, "stale": True}])
        self.assertEqual(ps["claude"]["state"], "stale")

    def test_no_record_is_connected_when_the_cli_is_on_path_else_omitted(self):
        h = self.home()
        on_path = {"grok", "claude"}
        r = ob.read_usage(h, now=1.0, which=lambda c: f"/bin/{c}" if c in on_path else None)
        self.assertEqual([(p["id"], p["state"], p["windows"]) for p in r["providers"]],
                         [("claude", "connected", []), ("grok", "connected", [])])
        self.assertEqual(ob.read_usage(h, now=1.0, which=lambda _: None), {"providers": []})

    def test_tail_read_only_reads_the_end_of_a_big_file_and_drops_the_cut_line(self):
        h = self.home()
        early = CODEX_LINE.replace('"used_percent":15.0', '"used_percent":99.0')
        f = self.write(h / ".codex/sessions/2026/11/03/rollout-big.jsonl", early, "x" * 2000, CODEX_LINE)
        lines = ob._tail_lines(f, '"rate_limits"', limit=len(CODEX_LINE) + 200)
        self.assertEqual(len(lines), 1)
        self.assertIn('"used_percent":15.0', lines[0])
        self.assertEqual(ob._tail_lines(h / "missing.jsonl", "x"), [])

    def test_usage_read_op_is_read_only_and_names_no_token(self):
        src = (HERE.parent / "omher_bridge.py").read_text(encoding="utf-8")
        body = src[src.index("# ---------------------------------------------------------------- usage meters"):
                   src.index("def read_routines(")]
        for bad in ("write_text", "write_bytes", "open(path, \"w", "unlink", "rename(", "auth.json", "token\"", "credentials"):
            self.assertNotIn(bad, body, bad)
        bridge = ob.Bridge(token=TOKEN, hermes_home=Path(tempfile.gettempdir()))
        self.assertIn("usage.read", bridge.ops)


TOKEN_KEYS = ("access_token", "refresh_token", "id_token", "api_key", "OPENAI_API_KEY")
SECRET = "sk-ant-oat01-SECRET-never-shown"


class Accounts(unittest.TestCase):
    """accounts.*: the coding-CLI logins on this computer (the CLI's own home first, then omher's added ones) with
    never a token; omher writes only under ~/.omher/accounts/<cli>/<id>/, and remove refuses every other path."""

    def home(self) -> Path:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return Path(d.name)

    def cpa(self, h: Path, n: int = 5) -> None:
        root = h / ".cli-proxy-api"
        root.mkdir(parents=True)
        (root / "config.yaml").write_text('server:\n  port: 8317\nmanagement:\n  secret-key: "k"\n', encoding="utf-8")
        for i in range(n):
            body = {"type": "claude", "email": f"a{i}@example.com", **{k: f"{SECRET}-{k}" for k in TOKEN_KEYS}}
            (root / f"claude-a{i}@example.com.json").write_text(json.dumps(body), encoding="utf-8")
        (root / "codex-x@example.com.json").write_text("{}", encoding="utf-8")

    def assert_no_token(self, payload) -> None:
        text = json.dumps(payload)
        for k in TOKEN_KEYS + (SECRET, "primaryApiKey", "secret-key", "tokens"):
            self.assertNotIn(k, text, k)

    def groups(self, h: Path, which=None, now: float = 1.0) -> dict:
        r = ob.read_accounts(h, now=now, which=which or (lambda c: f"/bin/{c}" if c == "claude" else None))
        self.assert_no_token(r)
        return {g["cli"]: g for g in r["groups"]}

    def test_every_cli_is_listed_with_installed_and_the_this_computer_row_first(self):
        h = self.home()
        (h / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "owner@example.com"}}), encoding="utf-8")
        gs = self.groups(h)
        self.assertEqual(list(gs), ["claude", "codex", "pi", "omp", "grok", "gemini"])
        self.assertEqual([c for c, g in gs.items() if g["installed"]], ["claude"])
        claude = gs["claude"]
        self.assertEqual(claude["active"], "default")
        self.assertEqual([(a["id"], a["email"], a["state"], a["label"]) for a in claude["accounts"]],
                         [("default", "owner@example.com", "active", "")])
        self.assertEqual(set(claude["accounts"][0]), {"id", "label", "email", "state", "dir", "usage"})
        self.assertNotIn("also", claude)
        # not on this computer, no login: one signed-out default row (the page hides the CLI)
        self.assertEqual([(a["id"], a["state"]) for a in gs["pi"]["accounts"]], [("default", "login")])

    def test_this_computer_login_is_a_stat_for_codex_pi_and_omp(self):
        h = self.home()
        for rel in (".codex/auth.json", ".pi/agent/auth.json", ".omp/agent/agent.db"):
            (h / rel).parent.mkdir(parents=True, exist_ok=True)
            (h / rel).write_text(json.dumps({k: SECRET for k in TOKEN_KEYS}), encoding="utf-8")
        gs = self.groups(h, which=lambda c: f"/bin/{c}")
        for cli in ("codex", "pi", "omp"):
            self.assertEqual(gs[cli]["accounts"][0]["state"], "active", cli)
        self.assertEqual(gs["claude"]["accounts"][0]["state"], "login")  # no email in ~/.claude.json
        self.assertEqual(gs["grok"]["accounts"][0]["state"], "login")

    def test_cpa_is_only_counted_and_never_opened(self):
        h = self.home()
        self.cpa(h)
        orig = Path.read_text

        def guard(p, *a, **k):
            self.assertNotIn(".json", Path(p).name if "cli-proxy-api" in str(p) else "", f"opened {p}")
            return orig(p, *a, **k)

        with mock.patch.object(Path, "read_text", guard):
            gs = self.groups(h)
        self.assertEqual(gs["claude"]["also"], {"name": "CLIProxyAPI", "accounts": 5})
        self.assertNotIn("also", gs["codex"])
        self.assertEqual(ob.cpa_count(self.home()), 0)
        # every CLIProxyAPI login is a row, from its file name only: read-only, no folder, no usage
        cpa = [a for a in gs["claude"]["accounts"] if a.get("source") == "cpa"]
        self.assertEqual([(a["id"], a["email"], a["state"], a["dir"], a["usage"]) for a in cpa],
                         [(f"cpa:{i + 1}", f"a{i}@example.com", "ready", None, None) for i in range(5)])
        self.assertEqual(gs["claude"]["active"], "default")

    def test_cpa_logins_join_the_claude_rows_by_email_from_real_file_names(self):
        h = self.home()
        root = h / ".cli-proxy-api"
        root.mkdir()
        (root / "config.yaml").write_text('oauth:\n  auth-dir: "~/.cli-proxy-api"\n', encoding="utf-8")
        for name in ("claude-2065f4ca-one@gmail.com.json", "claude-5012cc0d-Owner@Example.com.json",
                     "claude-a0538558-me@sionic.ai.json", "claude-nomail.json", "codex-x@example.com.json",
                     "claude-x.json.bak"):
            (root / name).write_text(json.dumps({k: SECRET for k in TOKEN_KEYS}), encoding="utf-8")
        (h / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "owner@example.com"}}), encoding="utf-8")
        claude = self.groups(h)["claude"]
        rows = [(a["id"], a["email"], a.get("source"), a.get("in_cpa")) for a in claude["accounts"]]
        # Claude Code's own login is one of CLIProxyAPI's (case-insensitive): marked, not listed twice
        self.assertEqual(rows, [("default", "owner@example.com", None, True), ("cpa:1", "one@gmail.com", "cpa", None),
                                ("cpa:3", "me@sionic.ai", "cpa", None), ("cpa:4", "", "cpa", None)])
        self.assertEqual(claude["also"], {"name": "CLIProxyAPI", "accounts": 4})
        self.assertEqual(ob.cpa_email("claude-89345c0d-rlaope0206@gmail.com.json"), "rlaope0206@gmail.com")
        self.assertEqual(ob.cpa_email("claude-rlaope0206@gmail.com.json"), "rlaope0206@gmail.com")
        self.assertEqual(ob.cpa_email("claude-../../x@y.z.json"), "")
        # a CLIProxyAPI login can never be made the account new sessions use (no folder under ~/.omher)
        with self.assertRaises(ob.BridgeError):
            ob.set_active_account("claude", "cpa:1", h)

    def test_the_claude_meter_lists_every_login_with_only_its_own_record(self):
        h = self.home()
        self.cpa(h, n=3)
        (h / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "a0@example.com"}}), encoding="utf-8")
        (h / ".claude/projects/-w").mkdir(parents=True)
        (h / ".claude/projects/-w/s.jsonl").write_text(CLAUDE_LINE + "\n", encoding="utf-8")
        orig = Path.read_text

        def guard(p, *a, **k):
            self.assertFalse("cli-proxy-api" in str(p) and Path(p).suffix == ".json", f"opened {p}")
            return orig(p, *a, **k)

        with mock.patch.object(Path, "read_text", guard):
            p = {x["id"]: x for x in ob.read_usage(h, now=1794200000.0, which=lambda _: None)["providers"]}["claude"]
        self.assertEqual(p["state"], "limited")
        self.assertEqual(p["accounts"], [
            {"email": "a0@example.com", "label": "", "source": "cli", "in_cpa": True, "state": "limited",
             "resets_at": 1794211200.0},
            {"email": "a1@example.com", "label": "", "source": "cpa", "in_cpa": False, "state": "no_record"},
            {"email": "a2@example.com", "label": "", "source": "cpa", "in_cpa": False, "state": "no_record"}])
        self.assert_no_token(p)
        # CLIProxyAPI logins alone (Claude Code not on PATH, no record) still give a Claude meter, with no number
        h2 = self.home()
        self.cpa(h2, n=2)
        p2 = ob.read_usage(h2, now=1.0, which=lambda _: None)["providers"]
        self.assertEqual([(x["id"], x["state"], x["windows"], len(x["accounts"])) for x in p2], [("claude", "connected", [], 2)])
        # one login: no list (the meter is the login); no CLIProxyAPI, nothing on PATH: no meter at all
        h3 = self.home()
        self.cpa(h3, n=1)
        self.assertNotIn("accounts", ob.read_usage(h3, now=1.0, which=lambda c: f"/bin/{c}")["providers"][0])
        self.assertEqual(ob.read_usage(self.home(), now=1.0, which=lambda _: None), {"providers": []})

    def test_fuzzed_token_keys_never_reach_any_payload(self):
        import random
        rnd = random.Random(7)
        for _ in range(20):
            h = self.home()
            self.cpa(h, n=2)
            for cli in ob.ACCOUNT_CLIS:
                folder = h / ".omher/accounts" / cli / "work"
                folder.mkdir(parents=True)
                junk = {rnd.choice(TOKEN_KEYS): SECRET for _ in range(3)}
                junk["label"] = rnd.choice(["Work", {"access_token": SECRET}, 7, None])
                (folder / "account.json").write_text(json.dumps(junk), encoding="utf-8")
                (folder / "auth.json").write_text(json.dumps({k: SECRET for k in TOKEN_KEYS}), encoding="utf-8")
                (folder / ".claude.json").write_text(json.dumps({"oauthAccount": rnd.choice([
                    {"emailAddress": "w@example.com"}, {"emailAddress": {"id_token": SECRET}}, SECRET]),
                    "primaryApiKey": SECRET}), encoding="utf-8")
            (h / ".omher/accounts/labels.json").write_text(json.dumps({"claude": {"refresh_token": SECRET}}),
                                                           encoding="utf-8")
            self.groups(h, which=lambda c: f"/bin/{c}")

    def test_add_label_activate_remove(self):
        h = self.home()
        which = lambda c: "/bin/codex" if c == "codex" else None  # noqa: E731
        a = ob.add_account("codex", "Work", h)
        self.assertEqual(a, {"id": "work", "dir": str(h / ".omher/accounts/codex/work")})
        if os.name != "nt":  # Windows has no POSIX mode bits: stat() reports 0o777 whatever mkdir asked for
            self.assertEqual(oct((h / ".omher/accounts/codex/work").stat().st_mode & 0o777), "0o700")
        self.assertEqual(ob.add_account("codex", "", h)["id"], "account-2")
        with self.assertRaises(ob.BridgeError):
            ob.add_account("codex", "Work", h)
        with self.assertRaises(ob.BridgeError):
            ob.add_account("bash", "x", h)
        g = self.groups(h, which)["codex"]
        self.assertEqual([(x["id"], x["state"], x["label"]) for x in g["accounts"]],
                         [("default", "login", ""), ("account-2", "login", ""), ("work", "login", "Work")])
        (h / ".omher/accounts/codex/work/auth.json").write_text("{}", encoding="utf-8")
        ob.set_active_account("codex", "work", h)
        self.assertEqual(json.loads((h / ".omher/accounts/active.json").read_text()), {"codex": "work"})
        ob.label_account("codex", "work", "  Side   job ", h)
        ob.label_account("codex", "default", "Personal", h)
        g = self.groups(h, which)["codex"]
        self.assertEqual(g["active"], "work")
        self.assertEqual([(x["id"], x["state"], x["label"]) for x in g["accounts"]],
                         [("default", "login", "Personal"), ("account-2", "login", ""), ("work", "active", "Side job")])
        ob.label_account("codex", "default", "", h)
        self.assertEqual(json.loads((h / ".omher/accounts/labels.json").read_text()), {})
        ob.remove_account("codex", "work", h)
        self.assertFalse((h / ".omher/accounts/codex/work").exists())
        self.assertEqual(json.loads((h / ".omher/accounts/active.json").read_text()), {})

    def test_discard_removes_only_an_empty_sign_in(self):
        h = self.home()
        ob.add_account("claude", "Two", h)
        ob.remove_account("claude", "two", h, only_if_empty=True)  # cancelled: nobody signed in
        self.assertFalse((h / ".omher/accounts/claude/two").exists())
        ob.add_account("claude", "Two", h)
        (h / ".omher/accounts/claude/two/.claude.json").write_text(
            json.dumps({"oauthAccount": {"emailAddress": "two@example.com"}}), encoding="utf-8")
        with self.assertRaises(ob.BridgeError) as e:
            ob.remove_account("claude", "two", h, only_if_empty=True)
        self.assertEqual(e.exception.code, "signed_in")
        self.assertTrue((h / ".omher/accounts/claude/two").is_dir())

    def test_remove_refuses_any_other_path(self):
        h = self.home()
        keep = h / "keep"
        keep.mkdir()
        (h / ".omher/accounts/claude").mkdir(parents=True)
        (h / ".omher/accounts/claude/link").symlink_to(keep)
        for cli, aid in (("claude", "../../keep"), ("claude", ".."), ("claude", "/tmp"), ("claude", "default"),
                         ("claude", "a/b"), ("claude", ""), ("bash", "x"), ("claude", None), ("claude", "link")):
            with self.assertRaises(ob.BridgeError, msg=(cli, aid)):
                ob.remove_account(cli, aid, h)
            with self.assertRaises(ob.BridgeError, msg=(cli, aid)):
                ob.remove_account(cli, aid, h, only_if_empty=True)
        self.assertTrue(keep.is_dir())
        for aid in ("nope", "../x", "link"):
            with self.assertRaises(ob.BridgeError):
                ob.label_account("claude", aid, "x", h)
        with self.assertRaises(ob.BridgeError):
            ob.set_active_account("claude", "nope", h)

    def test_claude_account_email_and_limited_state_from_its_own_folder(self):
        h = self.home()
        ob.add_account("claude", "Two", h)
        folder = h / ".omher/accounts/claude/two"
        (folder / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "two@example.com"}}))
        (folder / "projects/-w").mkdir(parents=True)
        (folder / "projects/-w/s.jsonl").write_text(CLAUDE_LINE + "\n", encoding="utf-8")
        two = self.groups(h, now=1794200000.0)["claude"]["accounts"][1]
        self.assertEqual((two["email"], two["state"], two["label"]), ("two@example.com", "limited", "Two"))
        self.assertIsNotNone(two["resets_at"])

    def test_ops_are_registered_and_accounts_code_runs_no_program_or_http(self):
        bridge = ob.Bridge(token=TOKEN, hermes_home=Path(tempfile.gettempdir()))
        for op in ("accounts.list", "accounts.add", "accounts.remove", "accounts.set_active", "accounts.label",
                   "accounts.discard"):
            self.assertIn(op, bridge.ops)
        self.assertNotIn("accounts.cpa_action", bridge.ops)
        src = (HERE.parent / "omher_bridge.py").read_text(encoding="utf-8")
        body = src[src.index("# ---------------------------------------------------------------- accounts"):
                   src.index("# ---------------------------------------------------------------- transcript helpers")]
        for bad in ("subprocess", "urllib", "http.client", ".send(", "sendall", "keyring", "os.environ[", "socket"):
            self.assertNotIn(bad, body, bad)


class VersionTest(unittest.TestCase):
    def test_the_bridge_reports_the_app_version(self):
        # hello's version is the app's: a release bump that misses the bridge fails here
        app = json.loads((HERE.parent.parent / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(ob.VERSION, app["version"])


STUB_HERMES = r"""#!/bin/sh
# omher test stub for `hermes`: records its argv, then answers like Hermes' restart does in $STUB_MODE.
printf '%s\n' "$@" > "$STUB_LOG"
printf 'HERMES_HOME=%s GW=%s\n' "$HERMES_HOME" "${_HERMES_GATEWAY:-}" >> "$STUB_LOG"
case "$STUB_MODE" in
  ok) echo "Profile '$2' restarted by the host gateway."; exit 0 ;;
  refused)
    for a in "$@"; do [ "$a" = "--yes" ] && { echo "⚠ --yes: restart proceeds: 2 live session(s) would be interrupted."; exit 0; }; done
    echo "✗ Refusing to restart the gateway: 3 live session(s) would be interrupted."
    echo "  • chat turn agent:kami:slack:dm:U1 pid 4242, running 3m [model claude-opus-5-5, tool terminal]"
    echo "  • cron job a1b2 (PR digest) in-process, running 40s"
    echo "  • chat turn agent:main:discord:group:C9 pid 4242, running 12s"
    echo "  Let them finish, or interrupt them deliberately:"
    echo "    hermes -p $2 gateway restart --yes   # interrupts 2 live session(s)"
    exit 1 ;;
  unconfirmed) echo "Profile '$2' restart was not confirmed: host control socket did not answer."; exit 0 ;;
  *) echo "Starting gateway..."; echo "✗ Gateway service restart failed."; echo "  Fix the service, then retry"; exit 1 ;;
esac
"""


class RestartArgv(unittest.TestCase):
    """Rule 29: the restart is Hermes' own command with a fixed argv; the bot is one checked element."""

    def test_fixed_argv_and_yes_only_when_asked(self):
        self.assertEqual(ob.restart_argv("/h/hermes", "kami", False), ["/h/hermes", "-p", "kami", "gateway", "restart", "--detach"])
        self.assertEqual(ob.restart_argv("/h/hermes", "kami", True)[-1], "--yes")
        self.assertNotIn("--yes", ob.restart_argv("/h/hermes", "kami", "true"))  # only the boolean True
        self.assertEqual(ob.restart_argv("/h/hermes", "default", False)[2], "default")

    def test_names_hermes_would_refuse_are_refused_here(self):
        for bad in ("Kami", "-p", "--all", "a b", "kami;rm -rf ~", "../x", "", "x" * 65, "kami\n", None, 3):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ob.restart_argv("/h/hermes", bad, False)

    def test_outcomes_read_from_hermes_text(self):
        self.assertEqual(ob.restart_outcome(0, "Profile 'kami' restarted by the host gateway.\n"), {"outcome": "ok"})
        r = ob.restart_outcome(1, "\x1b[31m✗ Refusing to restart the gateway: 1 live session(s) would be interrupted.\x1b[0m\n"
                                  "  • chat turn s1 pid 9, running 2m\n  Let them finish, or interrupt them deliberately:\n")
        self.assertEqual(r, {"outcome": "refused", "work": [{"kind": "chat", "name": None, "secs": 120, "bot": None}]})
        # every shape Hermes' describe_active_work_unit prints, read without ids, pids or brackets
        for line, want in (
            ("chat turn agent:kami:slack:dm:U1 pid 4242, running 3m05s [model claude-opus-5-5, tool terminal]", ("chat", None, 185, "kami")),
            ("chat turn agent:main:discord:group:C9, running 1m", ("chat", None, 60, "default")),
            ("chat turn agent:main~:x pid 1, running 1s", ("chat", None, 1, "main")),
            ("cron job a1b2 (PR digest) in-process, running 40s", ("cron", "PR digest", 40, "friren")),
            ("cron job zz9 in external worker pid 77, running 1m00s", ("cron", None, 60, None)),
            ("background delegation d9 pid 5, running 12s [fix the flaky test]", ("task", None, 12, None)),
            ("tui run 20261112_1, running 2m", ("run", "tui", 120, None)),
            ("webhook run agent:kami:hook:x pid 3, running 5s", ("run", "webhook", 5, "kami")),
            ("something new from Hermes, running 7s", ("work", None, 7, None)),
            # a shape Hermes adds later still says whose it is when it names the session; never from a word inside one
            ("drain wait for agent:main:telegram:dm:9, running 2m", ("work", None, 120, "default")),
            ("note xagent:kami:y", ("work", None, None, None)),
            ("??", ("work", None, None, None)),
        ):
            u = ob.work_unit(line, {"a1b2": "friren"})
            self.assertEqual((u["kind"], u["name"], u["secs"], u["bot"]), want, line)
        r = ob.restart_outcome(0, "Profile 'kami' restart was not confirmed: host operation is still pending.\n")
        self.assertEqual(r["outcome"], "failed")
        self.assertIn("not confirmed", r["line"])
        self.assertEqual(ob.restart_outcome(None, "")["outcome"], "failed")
        self.assertEqual(ob.restart_outcome(78, "✗ The host gateway already serves profile 'kami'.\n  more\n")["line"],
                         "The host gateway already serves profile 'kami'.")

    def test_which_gateway_serves_a_bot_and_who_goes_down_with_it(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            (home / "config.yaml").write_text("model: m\n")
            for n, cfg in (("kami", ""), ("solo", "gateway:\n  standalone: true\n"), ("parked", ""), ("friren", ""), ("own", "")):
                (home / "profiles" / n).mkdir(parents=True)
                (home / "profiles" / n / "config.yaml").write_text("model: m\n" + cfg)
            (home / "profiles" / "parked" / "gateway.parked").write_text("")
            own = home / "profiles" / "own"
            # a live gateway of its own, as Hermes' gateway.status.live_gateway_pid_for_home proves it
            with mock.patch.object(ob, "_hermes_gateway_pid", side_effect=lambda h: 4242 if Path(h) == own else None):
                self.assertEqual([ob.gateway_of(home, n) for n in ("kami", "solo", "default", "own", "ghost")],
                                 ["default", "solo", "default", "own", "default"])
                self.assertEqual([o["name"] for o in ob.gateway_bots(home, "default")], ["default", "friren", "kami"])
                self.assertEqual([o["name"] for o in ob.gateway_bots(home, "solo")], ["solo"])
            # a live host's own record of what it serves wins over the reading of configs
            with mock.patch.object(ob, "_hermes_served", return_value=["default", "kami"]):
                self.assertEqual([o["name"] for o in ob.gateway_bots(home, "default")], ["default", "kami"])
            # never `-p <served bot>`: that would be one profile's unserve/serve inside the host
            self.assertEqual(ob.restart_argv("/h/hermes", ob.gateway_of(home, "kami"), False)[2], "default")

    def test_plugin_load_follows_hermes_answer(self):
        self.assertEqual(ob.plugin_load({"restart_required": False, "gateway_reloaded": True}), "live")
        self.assertEqual(ob.plugin_load({"restart_required": True, "gateway_reloaded": False}), "reload")
        self.assertEqual(ob.plugin_load({"restart_required": True, "gateway_reloaded": True,
                                         "activation": {"missing_dependencies": ["numpy"], "missing_in": ["gateway"]}}), "restart")
        self.assertEqual(ob.plugin_load({"restart_required": True, "gateway_reloaded": True,
                                         "activation": {"missing_dependencies": ["numpy"], "missing_in": ["backend"]}}), "live")


@unittest.skipIf(os.name == "nt", "the stub `hermes` is a POSIX shell script")
class RestartThroughStubHermes(BridgeCase):
    """The real `bots.restart` op against a stub `hermes` on a scratch PATH: ok, refused with live work (then
    "Restart anyway"), failed. Never a real Hermes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        stub = d / "hermes"
        stub.write_text(STUB_HERMES)
        stub.chmod(0o755)
        self.log = d / "argv.txt"
        self.env = {"PATH": f"{d}{os.pathsep}/usr/bin{os.pathsep}/bin", "STUB_LOG": str(self.log),
                    "_HERMES_GATEWAY": "1"}

    def argv(self) -> list[str]:
        return self.log.read_text().splitlines()

    async def restart(self, s, mode, **params):
        with mock.patch.dict(os.environ, {**self.env, "STUB_MODE": mode}):
            return await s.req("bots.restart", **params)

    async def test_ok_restarts_the_host_gateway_and_reattaches_every_bot_on_it(self):
        with mock.patch.object(ob, "RESTART_POLL", 0.01):
            async with Env(("kami", "friren")) as env:
                s = await self.open(env)
                await s.req("chat.open", bot="kami")
                r = await self.restart(s, "ok", bot="kami")
                self.assertEqual(r["result"], {"outcome": "ok", "bots": ["default", "friren", "kami"]})
                argv = self.argv()
                # kami is served by the host: the host gateway's process restarts, never `-p kami` (unserve/serve)
                self.assertEqual(argv[:5], ["-p", "default", "gateway", "restart", "--detach"])  # the stub logs "$@"
                self.assertEqual(len(argv), 6)  # no --yes on the first press
                self.assertEqual(argv[5], f"HERMES_HOME={env.home} GW=")  # Hermes root, no gateway marker
                await s.until(lambda ev: {e["bot"] for e in ev if e["event"] == "bot.restarted"} >= {"default", "friren", "kami"})
                done = sorted(e["bot"] for e in s.events if e["event"] == "bot.restarted" and e["ok"])
                self.assertEqual(done, ["default", "friren", "kami"])
                self.assertEqual(env.connects.count("kami"), 2)  # the old connection dropped, a new one attached

    async def test_a_sticky_active_profile_never_changes_which_gateway_restarts(self):
        # Without -p Hermes follows `<root>/active_profile` (hermes_cli/main.py:525-536); omher names the profile on
        # every call, so a sticky non-default profile cannot turn the host's restart into kami's unserve/serve.
        with mock.patch.object(ob, "RESTART_POLL", 0.01):
            async with Env(("kami", "friren")) as env:
                (env.home / "active_profile").write_text("kami\n")
                s = await self.open(env)
                for bot in ("friren", "default"):
                    r = await self.restart(s, "ok", bot=bot)
                    self.assertEqual(r["result"]["outcome"], "ok")
                    self.assertEqual(self.argv()[:2], ["-p", "default"], bot)
                    await s.until(lambda ev: sum(e["event"] == "bot.restarted" for e in ev) >= 3)
                    s.events.clear()

    async def test_a_standalone_bot_restarts_its_own_gateway_alone(self):
        with mock.patch.object(ob, "RESTART_POLL", 0.01):
            async with Env(("kami", "solo")) as env:
                (env.home / "profiles" / "solo" / "config.yaml").write_text("model: m\ngateway:\n  standalone: true\n")
                s = await self.open(env)
                r = await self.restart(s, "ok", bot="solo")
                self.assertEqual(r["result"], {"outcome": "ok", "bots": ["solo"]})
                self.assertEqual(self.argv()[:5], ["-p", "solo", "gateway", "restart", "--detach"])
                r = await s.req("bots.restart_scope", bot="solo")
                self.assertEqual(r["result"], {"gateway": "solo", "bots": [{"name": "solo", "display_name": "Solo"}]})

    async def test_refused_names_the_live_work_then_restart_anyway_adds_yes(self):
        async with Env(("kami", "friren")) as env:
            (env.home / "profiles" / "friren" / "cron").mkdir()
            (env.home / "profiles" / "friren" / "cron" / "jobs.json").write_text('{"jobs": [{"id": "a1b2", "name": "PR digest"}]}')
            s = await self.open(env)
            r = await s.req("bots.restart", bot="kami", interrupt=True)
            self.assertEqual(r["error"]["code"], "bad_request")  # --yes never comes first
            r = await self.restart(s, "refused", bot="kami")
            self.assertEqual(r["result"]["outcome"], "refused")
            # each line says whose it is: a chat by its session key, a cron run by the jobs.json that holds it
            self.assertEqual(r["result"]["work"], [
                {"kind": "chat", "name": None, "secs": 180, "bot": "kami"},
                {"kind": "cron", "name": "PR digest", "secs": 40, "bot": "friren"},
                {"kind": "chat", "name": None, "secs": 12, "bot": "default"}])
            self.assertNotIn("lines", r["result"])
            self.assertNotIn("--yes", self.argv())
            with mock.patch.object(ob, "RESTART_POLL", 0.01):
                r = await self.restart(s, "refused", bot="kami", interrupt=True)
            self.assertEqual(r["result"]["outcome"], "ok")
            self.assertEqual(self.argv()[5], "--yes")
            r = await s.req("bots.restart", bot="kami", interrupt=True)
            self.assertEqual(r["error"]["code"], "bad_request")  # one refusal, one "anyway"

    async def test_failed_shows_hermes_last_line(self):
        async with Env(("kami",)) as env:
            s = await self.open(env)
            r = await self.restart(s, "broken", bot="kami")
            self.assertEqual(r["result"], {"outcome": "failed", "line": "Gateway service restart failed."})
            r = await self.restart(s, "unconfirmed", bot="kami")
            self.assertEqual(r["result"]["outcome"], "failed")
            self.assertEqual(env.connects, [])  # a failed restart attaches nothing

    async def test_only_known_bots_and_the_default_names_who_goes_down(self):
        async with Env(("kami", "friren")) as env:
            s = await self.open(env)
            self.assertEqual((await self.restart(s, "ok", bot="ghost"))["error"]["code"], "unknown_bot")
            self.assertFalse(self.log.exists())
            r = await s.req("bots.restart_scope", bot="default")
            self.assertEqual(r["result"]["gateway"], "default")
            self.assertEqual([o["name"] for o in r["result"]["bots"]], ["default", "friren", "kami"])
            r = await s.req("bots.restart_scope", bot="kami")  # a served bot: the same host, the same bots
            self.assertEqual((r["result"]["gateway"], [o["name"] for o in r["result"]["bots"]]), ("default", ["default", "friren", "kami"]))


class PluginReload(BridgeCase):
    async def test_reload_reports_live_restart_or_failed(self):
        answers = {"live": {"reloaded": True, "activations": [{"name": "omh", "key": "omh"}]},
                   "deps": {"reloaded": True, "activations": [{"name": "omh", "key": "omh", "missing_dependencies": ["numpy"]}]},
                   "none": None, "refused": {"reloaded": False, "error": "home is not served by this gateway"}}
        async with Env(("kami",)) as env:
            s = await self.open(env)
            for case, want in (("live", "live"), ("deps", "restart"), ("none", "failed"), ("refused", "failed")):
                with mock.patch.object(ob, "reload_plugins", return_value=answers[case]) as rp:
                    r = (await s.req("plugins.reload", bot="kami", name="omh"))["result"]
                self.assertEqual(r["load"], want, case)
                rp.assert_called_once_with(env.home / "profiles" / "kami", env.home)
            self.assertEqual(env.connects, [])  # a reload never attaches or restarts
