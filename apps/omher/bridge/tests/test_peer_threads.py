"""Threads on a bot on another computer (#3172, BOUNDARY rule 31): a second, real bridge on loopback stands in for the
other computer's (its gateway is a ThreadClient). The local bridge forwards `thread.*` with the bare name, takes
`session=<thread>` on the chat ops only for an id the peer's bridge answered as a thread, passes that thread's events
back under the namespaced name, ends its live turn when the link drops, and still refuses folder chats, Restart and a
folder on this computer. No Hermes, no network beyond loopback."""
from __future__ import annotations

import sys
import unittest
from contextlib import AsyncExitStack
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402
from test_bridge import BridgeCase  # noqa: E402
from test_threads import HermesStore, ThreadEnv, ok  # noqa: E402

PEER_TOKEN = "cd" * 16


class PeerThreads(BridgeCase):
    async def _two(self, stack):
        local = await stack.enter_async_context(ThreadEnv(profiles=("kami",)))
        remote = ThreadEnv(HermesStore(), profiles=("mini",))
        remote.bridge = ob.Bridge(token=PEER_TOKEN, hermes_home=remote.home, gateway_factory=remote.factory, poll_s=3600)
        await stack.enter_async_context(remote)
        s = await self.open(local)
        url = f"ws://127.0.0.1:{remote.port}/?token={PEER_TOKEN}"
        ok(await s.req("peers.attach", peer="mac", label="Mac mini", host="demo@host.example", url=url))
        ok(await s.req("chat.open", bot="mac:mini"))
        return local, remote, s

    async def test_create_send_stream_and_remove_a_thread_on_the_other_computer(self):
        async with AsyncExitStack() as stack:
            local, remote, s = await self._two(stack)
            made = ok(await s.req("thread.create", bot="mac:mini", key="press1"))
            tid = made["thread"]
            self.assertEqual(tid, "stored-th-1")
            self.assertEqual(made["cwd"], "")  # a folder over there is not a path here
            c = remote.clients["mini"]
            self.assertEqual(c.find("session.create")[-1]["request_id"], "omher-thread:mini:press1")  # the bare name
            self.assertEqual(local.connects, [])  # nothing local attached for a remote bot's thread
            await s.until(lambda ev: any(e["event"] == "thread.added" and e["bot"] == "mac:mini" for e in ev))
            ok(await s.req("chat.send", bot="mac:mini", session=tid, text="look at the nightly logs"))
            self.assertEqual(c.find("prompt.submit")[-1]["session_id"], "rt-stored-th-1")
            self.assertEqual(c.find("prompt.submit")[-1]["text"], "look at the nightly logs")
            c.push("message.start", {}, sid="rt-stored-th-1")
            c.push("message.delta", {"text": "rea"}, sid="rt-stored-th-1")
            c.push("message.complete", {"text": "reading", "status": "complete"}, sid="rt-stored-th-1")
            await s.until(lambda ev: any(e["event"] == "turn.end" and e.get("session") == tid for e in ev))
            ev = [e for e in s.events if e.get("session") == tid and e["event"] in ("turn.start", "delta", "message", "turn.end")]
            self.assertEqual([e["event"] for e in ev], ["turn.start", "delta", "message", "turn.end"])
            self.assertTrue(all(e["bot"] == "mac:mini" for e in ev), ev)
            # the main chat stays the main chat: no main-chat turn was started by the thread's send
            self.assertFalse(any(e["event"] == "turn.start" and e["bot"] == "mac:mini" and "session" not in e for e in s.events))
            listed = ok(await s.req("thread.list", bot="mac:mini"))["threads"]
            self.assertEqual([(t["thread"], t["cwd"]) for t in listed], [(tid, "")])
            opened = ok(await s.req("thread.open", bot="mac:mini", thread=tid))
            self.assertEqual([m["text"] for m in opened["messages"]], ["first", "answer"])
            ok(await s.req("chat.interrupt", bot="mac:mini", session=tid))
            gone = ok(await s.req("thread.remove", bot="mac:mini", thread=tid))
            self.assertEqual(gone, {"thread": tid, "archived": True})
            self.assertTrue(remote.store.rows[tid]["archived"])  # archived in that Hermes, never deleted
            # once removed, the id no longer crosses
            r = await s.req("chat.send", bot="mac:mini", session=tid, text="again")
            self.assertEqual(r["error"]["code"], "remote_bot")

    async def test_a_listed_thread_crosses_after_a_restart_of_this_bridge(self):
        async with AsyncExitStack() as stack:
            local, remote, s = await self._two(stack)
            tid = ok(await s.req("thread.create", bot="mac:mini", key="k"))["thread"]
            ok(await s.req("chat.send", bot="mac:mini", session=tid, text="first words"))
            # a fresh link (as after omher restarted) knows no thread until the peer lists it
            ok(await s.req("peers.detach", peer="mac"))
            url = f"ws://127.0.0.1:{remote.port}/?token={PEER_TOKEN}"
            ok(await s.req("peers.attach", peer="mac", label="Mac mini", host="demo@host.example", url=url))
            r = await s.req("chat.send", bot="mac:mini", session=tid, text="before list")
            self.assertEqual(r["error"]["code"], "remote_bot")
            self.assertEqual((await s.req("thread.open", bot="mac:mini", thread=tid))["error"]["code"], "not_found")
            listed = ok(await s.req("thread.list", bot="mac:mini"))["threads"]
            self.assertEqual([t["thread"] for t in listed], [tid])
            ok(await s.req("thread.open", bot="mac:mini", thread=tid))
            ok(await s.req("chat.send", bot="mac:mini", session=tid, text="after list"))
            self.assertEqual(remote.clients["mini"].find("prompt.submit")[-1]["text"], "after list")

    async def test_ids_the_peer_did_not_answer_and_this_computers_ops_stay_refused(self):
        async with AsyncExitStack() as stack:
            local, remote, s = await self._two(stack)
            c = remote.clients["mini"]
            before = len(c.find("prompt.submit"))
            # a made-up id, or the id of a folder chat over there: refused as a folder chat, nothing sent
            for sid in ("stored-folder-0", "stored-th-99", 7):
                r = await s.req("chat.send", bot="mac:mini", session=sid, text="x")
                self.assertEqual(r["error"]["code"], "remote_bot", sid)
                self.assertIn("Mac mini", r["error"]["message"])
            self.assertEqual(len(c.find("prompt.submit")), before)
            tid = ok(await s.req("thread.create", bot="mac:mini"))["thread"]
            # a thread id on an op that never takes a session there
            r = await s.req("panel.diff", bot="mac:mini", session=tid)
            self.assertEqual(r["error"]["code"], "remote_bot")
            # a folder here, folder chats and Restart: still this computer's
            r = await s.req("thread.create", bot="mac:mini", cwd=str(local.home))
            self.assertEqual(r["error"]["code"], "remote_bot")
            for op, extra in (("folder.open", {"cwd": "/tmp"}), ("folder.close", {"session": tid}),
                              ("folder.resume", {"stored": tid}), ("bots.restart", {})):
                r = await s.req(op, bot="mac:mini", **extra)
                self.assertEqual(r["error"]["code"], "remote_bot", op)
            # the thread's PRs are read on this computer only, so not for a bot over there
            r = await s.req("thread.prs", bot="mac:mini", thread=tid)
            self.assertEqual(r["error"]["code"], "remote_bot")
            self.assertNotIn("thread.prs", ob.PEER_FORWARD)

    async def test_events_of_a_session_that_is_not_a_thread_are_dropped(self):
        async with AsyncExitStack() as stack:
            local, remote, s = await self._two(stack)
            link = local.bridge.peers["mac"]
            await local.bridge._peer_event(link, {"event": "delta", "bot": "mini", "session": "stored-folder-0", "text": "x"})
            self.assertFalse(any(e.get("session") == "stored-folder-0" for e in s.events))
            await local.bridge._peer_event(link, {"event": "thread.added", "bot": "mini", "thread": "stored-th-7", "title": ""})
            await local.bridge._peer_event(link, {"event": "delta", "bot": "mini", "session": "stored-th-7", "text": "y"})
            await s.until(lambda ev: any(e.get("session") == "stored-th-7" and e["event"] == "delta" for e in ev))
            await local.bridge._peer_event(link, {"event": "thread.removed", "bot": "mini", "thread": "stored-th-7"})
            n = len([e for e in s.events if e.get("session") == "stored-th-7"])
            await local.bridge._peer_event(link, {"event": "delta", "bot": "mini", "session": "stored-th-7", "text": "z"})
            self.assertEqual(len([e for e in s.events if e.get("session") == "stored-th-7"]), n)

    async def test_a_dropped_link_ends_the_threads_live_turn_as_stopped(self):
        async with AsyncExitStack() as stack:
            local, remote, s = await self._two(stack)
            tid = ok(await s.req("thread.create", bot="mac:mini"))["thread"]
            ok(await s.req("chat.send", bot="mac:mini", session=tid, text="long job"))
            remote.clients["mini"].push("message.start", {}, sid="rt-stored-th-1")
            await s.until(lambda ev: any(e["event"] == "turn.start" and e.get("session") == tid for e in ev))
            await remote.bridge.close()
            await s.until(lambda ev: any(e["event"] == "turn.end" and e.get("session") == tid for e in ev))
            end = [e for e in s.events if e["event"] == "turn.end" and e.get("session") == tid]
            self.assertEqual(len(end), 1)
            self.assertEqual(end[0]["outcome"], "interrupted")
            self.assertIn("Mac mini", end[0]["error"])
            self.assertEqual(len(remote.clients["mini"].find("prompt.submit")), 1)  # never resent


if __name__ == "__main__":
    unittest.main()
