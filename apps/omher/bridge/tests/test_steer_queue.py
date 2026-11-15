"""Steer queue: the bridge's `chat.steer` op (Hermes' `session.steer`, main chat only; a refusal is passed back,
never sent another way)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402
from test_bridge import MAIN_RUNTIME, BridgeCase, Env, GatewayRPCError  # noqa: E402


def steer_answers(env: Env, *answers) -> None:
    """The kami client's `session.steer` answers, in order (a dict, or an exception to raise)."""
    c = env.clients["kami"]
    plain = c.rpc
    queue = list(answers)

    async def rpc(method, *, _timeout=None, **params):
        if method == "session.steer":
            c.calls.append((method, params))
            a = queue.pop(0)
            if isinstance(a, Exception):
                raise a
            return a
        return await plain(method, _timeout=_timeout, **params)

    c.rpc = rpc


class ChatSteer(BridgeCase):
    async def test_steer_goes_to_the_main_chat_and_passes_hermes_answer_back(self):
        async with Env() as env:
            s = await self.open(env)
            self.assertTrue((await s.req("chat.open", bot="kami"))["ok"])
            steer_answers(env, {"status": "queued", "text": "also check the logs"})
            r = await s.req("chat.steer", bot="kami", text="also check the logs")
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["result"], {"status": "queued"})
            c = env.clients["kami"]
            self.assertEqual(c.find("session.steer"), [{"session_id": MAIN_RUNTIME, "text": "also check the logs"}])
            self.assertEqual(c.find("prompt.submit"), [])
            self.assertEqual(c.find("session.interrupt"), [])

    async def test_rejected_is_passed_back_with_no_fallback_inside_the_bridge(self):
        async with Env() as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            steer_answers(env, {"status": "rejected", "text": "x"}, {"status": "weird"})
            r = await s.req("chat.steer", bot="kami", text="x")
            self.assertEqual(r["result"], {"status": "rejected"})
            # an answer Hermes never gives reads as not taken
            r = await s.req("chat.steer", bot="kami", text="y")
            self.assertEqual(r["result"], {"status": "rejected"})
            c = env.clients["kami"]
            self.assertEqual(len(c.find("session.steer")), 2)
            for m in ("prompt.submit", "session.interrupt", "session.redirect"):
                self.assertEqual(c.find(m), [], m)

    async def test_a_gateway_refusal_is_an_error_and_nothing_else_is_sent(self):
        async with Env() as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            steer_answers(env, GatewayRPCError("agent does not support steer"))
            r = await s.req("chat.steer", bot="kami", text="x")
            # Hermes answered no (4010): a definite refusal, the app may send it normally after the turn
            self.assertEqual(r["result"], {"status": "rejected"})
            self.assertEqual(env.clients["kami"].find("prompt.submit"), [])

    async def test_a_lost_answer_stays_an_error_never_rejected(self):
        async with Env() as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            steer_answers(env, TimeoutError())
            r = await s.req("chat.steer", bot="kami", text="x")
            self.assertFalse(r["ok"])
            self.assertEqual(r["error"]["code"], "timeout")
            self.assertEqual(env.clients["kami"].find("prompt.submit"), [])

    async def test_a_held_message_goes_out_queued(self):
        async with Env() as env:
            s = await self.open(env)
            self.assertTrue((await s.req("chat.send", bot="kami", text="held one", queued=True))["ok"])
            self.assertTrue((await s.req("chat.send", bot="kami", text="plain"))["ok"])
            sub = env.clients["kami"].find("prompt.submit")
            self.assertEqual([p.get("queued") for p in sub], [True, None])
            self.assertEqual({p["session_id"] for p in sub}, {MAIN_RUNTIME})

    async def test_refused_for_folder_chats_and_any_other_session(self):
        with tempfile.TemporaryDirectory() as folder:
            async with Env() as env:
                s = await self.open(env)
                fid = (await s.req("folder.open", bot="kami", cwd=folder))["result"]["session"]
                for sid in (fid, "20261108_235229_aaaf70c4", MAIN_RUNTIME, 3):
                    r = await s.req("chat.steer", bot="kami", session=sid, text="x")
                    self.assertEqual(r["error"]["code"], "bad_request", sid)
                # a client-supplied session_id is never used: the steer still targets the main chat
                steer_answers(env, {"status": "queued"})
                r = await s.req("chat.steer", bot="kami", text="x", session_id="20261108_235229_aaaf70c4")
                self.assertTrue(r["ok"], r)
                c = env.clients["kami"]
                self.assertEqual([p["session_id"] for p in c.find("session.steer")], [MAIN_RUNTIME])
                self.assertEqual(c.find("prompt.submit"), [])

    async def test_needs_text(self):
        async with Env() as env:
            s = await self.open(env)
            for text in (None, "", "   ", 5):
                r = await s.req("chat.steer", bot="kami", text=text)
                self.assertEqual(r["error"]["code"], "bad_request", text)
            self.assertNotIn("kami", env.clients)  # refused before reaching any gateway

    def test_a_peers_bot_takes_it_through_its_own_bridge(self):
        self.assertIn("chat.steer", ob.PEER_FORWARD)


if __name__ == "__main__":
    unittest.main()
