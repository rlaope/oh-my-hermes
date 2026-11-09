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
                self.assertEqual(set(a), {"id", "source", "label", "title", "started_at", "last_active", "message_count", "running", "url", "place", "last_reply", "last_reply_at"})
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
        src = (HERE.parent / "omher_bridge.py").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"prompt\.submit", src)), 1)
        sites = re.findall(r"self\._submit\(([^)]*)\)", src)
        self.assertEqual(sites, ["conn, main, text, input_id"])

    def test_bridge_makes_no_model_or_http_call(self):
        src = (HERE.parent / "omher_bridge.py").read_text(encoding="utf-8")
        for needle in ("urllib.request", "requests", "httpx", "aiohttp", "openai", "anthropic"):
            self.assertNotIn(needle, src, needle)

    def test_the_only_program_it_runs_is_read_only_git(self):
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
        self.assertEqual(uses, ["_git"])
        self.assertNotIn("create_subprocess", src)
        self.assertNotIn("os.system", src)
        self.assertEqual(ob.GIT_READS, {("worktree", "list"), ("rev-parse",), ("status",), ("diff",), ("log",)})
        for bad in (["push"], ["commit", "-m", "x"], ["checkout", "main"], ["worktree", "add", "x"], ["reset", "--hard"],
                    ["apply"], ["clean", "-fd"], ["config", "user.name", "x"]):
            with self.assertRaises(ValueError, msg=bad):
                ob._git(bad, ".")


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
        self.assertTrue(runs[0]["output"].endswith("…"))

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
            states = [r["state"] for r in runs]
            self.assertEqual(states, sorted(states, key=lambda s: s != "running"))  # running first
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


CLI_FIX = HERE / "fixtures" / "cli"
CLAUDE_SID = "ec38bc0b-8eb7-936b-b856-daaee28015c4"
CODEX_ROOT = "c5e14c89-54b2-c703-769f-a6207ed501ea"
FIXED_NOW = 1793700000.0  # 2026-11-03, after both fixture sessions; `since=0` keeps them in range


def _cli_home(root: Path) -> dict[str, Path]:
    """A copy of the redacted CLI fixtures as Claude Code and Codex homes; pi/omp/grok absent."""
    import shutil
    shutil.copytree(CLI_FIX, root / "cli")
    return {"claude": root / "cli" / "claude-home", "codex": root / "cli" / "codex",
            "pi": root / "none-pi", "omp": root / "none-omp", "grok": root / "none-grok"}


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
