"""Bridge tests: a FakeGateway stands in for Hermes' gateway (no Hermes, no network beyond loopback)."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import unittest
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

    def __init__(self, name: str, *, bot_chat: bool = True, sessions=None, history=None):
        self.name = name
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
        if method == "session.create":
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
            self.assertEqual(r["result"]["version"], "0.1.0")
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


class EventMapping(BridgeCase):
    def fixture_frames(self):
        return json.loads(FIXTURE.read_text())

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
                self.assertEqual(set(a), {"id", "source", "label", "title", "started_at", "last_active", "message_count", "running"})
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


class ReadOnlyRule(BridgeCase):
    """No Hermes call that attaches to or writes a session may carry any id but the bot's main chat."""

    GUARDED = ("prompt.submit", "session.resume", "session.interrupt", "approval.respond", "clarify.respond",
               "session.mutate", "session.title", "session.steer", "session.redirect", "session.activate")

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
            self.assertGreaterEqual(seen, 6)
            self.assertEqual(len(c.find("prompt.submit")), 1)

    def test_source_has_exactly_one_submit_call_site(self):
        src = (HERE.parent / "omher_bridge.py").read_text()
        self.assertEqual(len(re.findall(r"prompt\.submit", src)), 1)
        sites = re.findall(r"self\._submit\(([^)]*)\)", src)
        self.assertEqual(sites, ["conn, main, text, input_id"])

    def test_bridge_makes_no_model_or_http_call(self):
        src = (HERE.parent / "omher_bridge.py").read_text()
        for needle in ("urllib.request", "requests", "httpx", "aiohttp", "openai", "anthropic", "subprocess"):
            self.assertNotIn(needle, src, needle)


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
