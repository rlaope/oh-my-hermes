"""After omher (and so its bridge) starts again while Hermes' gateway ran on, a thread mid-turn or waiting on an
approval is not attached in this run. thread.list reads what Hermes' gateway says each session is doing
(`session.active_list`, read only), so the row runs and waits on the person before any click, and thread.open then
replays the waiting ask. FakeGateway only; no Hermes, no model."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from test_bridge import BridgeCase, GatewayRPCError  # noqa: E402
from test_threads import HermesStore, ThreadEnv, ok  # noqa: E402


class RestartState(BridgeCase):
    async def open(self, env):
        """A client as the app is one: the bot's main chat is open before its threads are listed."""
        s = await super().open(env)
        ok(await s.req("chat.open", bot="kami"))
        return s

    async def made(self, store: HermesStore) -> str:
        """A thread with a saved message, made by an earlier bridge on the same Hermes."""
        async with ThreadEnv(store) as env:
            s = await self.open(env)
            tid = ok(await s.req("thread.create", bot="kami"))["thread"]
            ok(await s.req("chat.send", bot="kami", session=tid, text="clean up build/"))
        return tid

    async def test_a_thread_waiting_on_an_approval_lists_as_needing_the_person_and_opens_with_the_ask(self):
        store = HermesStore()
        tid = await self.made(store)
        async with ThreadEnv(store) as env:
            s = await self.open(env)
            c = env.clients["kami"]
            c.active = [{"id": "rt-other", "session_key": tid, "status": "waiting"},
                        {"id": "rt-x", "session_key": "someone-else", "status": "working"}]
            row = ok(await s.req("thread.list", bot="kami"))["threads"][0]
            self.assertEqual((row["thread"], row["running"], row["needs"]), (tid, True, True))
            c.running.add("rt-" + tid)
            c.pending_prompts[tid] = [{"prompt_id": "ap1", "kind": "approval", "command": "rm -rf build",
                                       "description": "Delete"}]
            opened = ok(await s.req("thread.open", bot="kami", thread=tid))
            self.assertTrue(opened["running"])
            await s.until(lambda ev: any(e["event"] == "approval.request" and e.get("session") == tid for e in ev))
            ask = [e for e in s.events if e["event"] == "approval.request"][0]
            self.assertEqual((ask["request_id"], ask["command"]), ("ap1", "rm -rf build"))

    async def test_a_running_thread_lists_as_running_and_an_idle_one_as_idle(self):
        store = HermesStore()
        tid = await self.made(store)
        async with ThreadEnv(store) as env:
            s = await self.open(env)
            c = env.clients["kami"]
            c.active = [{"id": "rt-other", "session_key": tid, "status": "working"}]
            row = ok(await s.req("thread.list", bot="kami"))["threads"][0]
            self.assertEqual((row["running"], row["needs"]), (True, False))
            c.active = [{"id": "rt-other", "session_key": tid, "status": "idle"}]
            row = ok(await s.req("thread.list", bot="kami"))["threads"][0]
            self.assertEqual((row["running"], row["needs"]), (False, False))

    async def test_a_gateway_without_active_list_still_lists_the_threads(self):
        store = HermesStore()
        tid = await self.made(store)
        async with ThreadEnv(store) as env:
            s = await self.open(env)
            env.clients["kami"].answers["session.active_list"] = GatewayRPCError("unknown_method")
            row = ok(await s.req("thread.list", bot="kami"))["threads"][0]
            self.assertEqual((row["thread"], row["running"], row["needs"]), (tid, False, False))

    async def test_an_attached_thread_is_never_read_from_active_list(self):
        async with ThreadEnv() as env:
            s = await self.open(env)
            ok(await s.req("thread.create", bot="kami"))
            c = env.clients["kami"]
            ok(await s.req("thread.list", bot="kami"))
            self.assertEqual(c.find("session.active_list"), [])

if __name__ == "__main__":
    unittest.main()
