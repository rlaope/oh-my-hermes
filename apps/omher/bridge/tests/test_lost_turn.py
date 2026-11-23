"""A chat whose turn Hermes lost when its gateway died mid-turn (#3123). Hermes' canonical gateway keeps a durable
queue of admissions per session: a turn running when the gateway is killed comes back `unknown`, and every later
message of that session waits behind it (`queued`) until someone acknowledges it with `prompt.resolve_unknown`.
Nothing runs and no event comes, so the chat looked dead: "Read" under the message, no answer, and the message gone
from the transcript after a restart. The fake below keeps that queue across gateway processes, as Hermes' state.db
does, and the test kills the gateway (and the bridge) in the middle of a turn. No Hermes, no network beyond loopback."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402
from test_bridge import TOKEN, BridgeCase, Env, GatewayRPCError, MAIN_RUNTIME, MAIN_STORED  # noqa: E402
from test_folder_resume import ResumeClient, ResumeEnv  # noqa: E402
from test_threads import HermesStore, ThreadClient  # noqa: E402



class Ledger:
    """Hermes' admission queue (per session id), which outlives the gateway process that wrote it."""

    def __init__(self):
        self.rows: list[dict] = []
        self.n = 0
        self.generation = 3

    def of(self, sid: str) -> list[dict]:
        return [r for r in self.rows if r["sid"] == sid]

    def crash(self) -> None:
        """The gateway is killed: a turn it was running is recovered `unknown` at the next start."""
        for r in self.rows:
            if r["status"] == "started":
                r["status"] = "unknown"


class LedgerClient(ThreadClient):
    """ThreadClient (main chat and threads) whose `prompt.submit` goes through the Ledger as Hermes' does."""

    def __init__(self, name, store, ledger: Ledger, **kw):
        super().__init__(name, store, **kw)
        self.ledger = ledger

    def _start_next(self, sid: str) -> None:
        rows = self.ledger.of(sid)
        if any(r["status"] in ("started", "unknown") for r in rows):
            return  # a running turn, or a lost one nobody acknowledged: the queue waits
        head = next((r for r in rows if r["status"] == "queued"), None)
        if head is not None:
            self.ledger.generation += 1
            head.update(status="started", execution_generation=self.ledger.generation)
            self.push("message.start", {}, sid=sid)

    async def rpc(self, method, *, _timeout=None, **params):
        if method == "prompt.submit":
            self.calls.append((method, params))
            thread = self.store.rows.get(params["session_id"][3:])
            if thread is not None:  # a thread's first prompt saves its row, as Hermes does
                thread["saved"] = True
            self.ledger.n += 1
            row = {"sid": params["session_id"], "admission_id": f"a{self.ledger.n}", "sequence": self.ledger.n,
                   "status": "queued", "text": params["text"], "execution_generation": None}
            self.ledger.rows.append(row)
            receipt = {k: v for k, v in row.items() if k != "sid"}  # Hermes' receipt reads `queued` even when it starts
            self._start_next(params["session_id"])
            return receipt
        if method == "prompt.resolve_unknown":
            self.calls.append((method, params))
            row = next((r for r in self.ledger.rows if r["admission_id"] == params["admission_id"]), None)
            if row is None:
                raise GatewayRPCError("not_found")
            if row["status"] != "unknown" or row["execution_generation"] != params["execution_generation"]:
                raise GatewayRPCError("stale_generation")
            row.update(status="terminal", outcome="interrupted")
            self._start_next(row["sid"])
            return {"admission_id": row["admission_id"], "status": "terminal", "outcome": "interrupted"}
        snap = await super().rpc(method, _timeout=_timeout, **params)
        if method in ("session.resume", "session.create") and isinstance(snap, dict):
            sid = snap.get("session_id")
            snap["pending"] = [{k: v for k, v in r.items() if k != "sid"} for r in self.ledger.of(sid)
                               if r["status"] != "terminal"]
            snap["running"] = any(r["status"] == "started" for r in self.ledger.of(sid))
        return snap


class LedgerEnv(Env):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.store, self.ledger = HermesStore(), Ledger()

    async def factory(self, stack, path: Path, endpoint=None):
        name = "default" if path == self.home else path.name
        self.connects.append(name)
        c = self.clients[name] = LedgerClient(name, self.store, self.ledger, **self.client_kw)
        return c

    async def restart_after_crash(self) -> None:
        """omher (and the gateway with it) is killed mid-turn, then started again on the same Hermes home."""
        self.ledger.crash()
        await self.bridge.close()
        self.bridge = ob.Bridge(token=TOKEN, hermes_home=self.home, gateway_factory=self.factory, poll_s=3600,
                                omher_home=self.home / ".omher", gateway_probe=self.probe)
        self.port = await self.bridge.start(port=0, watch=False)


class LostTurnAfterCrash(BridgeCase):
    async def test_main_chat_lost_turn_is_shown_and_discard_lets_the_waiting_message_run(self):
        async with LedgerEnv() as env:
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            r = await s.req("chat.send", bot="kami", text="hello")
            self.assertEqual(r["result"], {"input_id": env.clients["kami"].find("prompt.submit")[0]["input_id"]})
            await s.until(lambda ev: any(e["event"] == "turn.start" for e in ev))  # its turn is running

            await env.restart_after_crash()  # killed mid-turn
            s = await self.open(env)
            opened = (await s.req("chat.open", bot="kami"))["result"]
            self.assertFalse(opened["running"])
            self.assertEqual(opened["lost"], [{"id": "a1", "text": "hello"}])

            # a message now waits in Hermes' queue behind the lost turn: the reply says so (not just "sent")
            r = await s.req("chat.send", bot="kami", text="you there?")
            self.assertTrue(r["ok"], r)
            self.assertIs(r["result"]["paused"], True)
            self.assertFalse(any(e["event"] == "turn.start" for e in s.events))

            # it is not in the transcript, but a reopened chat still shows it, waiting
            again = (await s.req("chat.open", bot="kami"))["result"]
            waiting = [m for m in again["messages"] if m.get("queued")]
            self.assertEqual([(m["id"], m["role"], m["text"]) for m in waiting], [("q-a2", "user", "you there?")])

            # Discard: the lost turn is acknowledged with its own generation, then the waiting message runs
            c = env.clients["kami"]
            d = await s.req("chat.discard", bot="kami")
            self.assertEqual(d["result"], {"discarded": 1})
            self.assertEqual(c.find("prompt.resolve_unknown"),
                             [{"session_id": MAIN_RUNTIME, "admission_id": "a1", "execution_generation": 4}])
            await s.until(lambda ev: any(e["event"] == "turn.start" and not e.get("session") for e in ev))
            self.assertEqual([r["status"] for r in env.ledger.rows], ["terminal", "started"])
            # nothing is lost any more: a new message is a plain send, and a second Discard does nothing
            reopened = (await s.req("chat.open", bot="kami"))["result"]
            self.assertEqual(reopened["lost"], [])
            self.assertEqual((await s.req("chat.discard", bot="kami"))["result"], {"discarded": 0})
            self.assertEqual(len(c.find("prompt.resolve_unknown")), 1)

    async def test_a_send_before_any_open_still_learns_the_pause(self):
        async with LedgerEnv() as env:
            s = await self.open(env)
            await s.req("chat.send", bot="kami", text="hello")
            await env.restart_after_crash()
            s = await self.open(env)
            r = await s.req("chat.send", bot="kami", text="you there?")  # the bridge attaches the main chat itself
            self.assertIs(r["result"]["paused"], True)

    async def test_a_turn_settled_elsewhere_counts_as_discarded(self):
        async with LedgerEnv() as env:
            s = await self.open(env)
            await s.req("chat.send", bot="kami", text="hello")
            await env.restart_after_crash()
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            env.ledger.rows[0].update(status="terminal")  # Hermes' own Discard (desktop, `/discard`) got there first
            d = await s.req("chat.discard", bot="kami")
            self.assertTrue(d["ok"], d)
            self.assertEqual(d["result"], {"discarded": 1})

    async def test_another_refusal_is_an_error_and_keeps_the_pause(self):
        async with LedgerEnv() as env:
            s = await self.open(env)
            await s.req("chat.send", bot="kami", text="hello")
            await env.restart_after_crash()
            s = await self.open(env)
            await s.req("chat.open", bot="kami")
            orig = LedgerClient.rpc

            async def refuse(self, method, *, _timeout=None, **params):
                if method == "prompt.resolve_unknown":
                    raise GatewayRPCError("session_busy")
                return await orig(self, method, _timeout=_timeout, **params)
            LedgerClient.rpc = refuse
            self.addCleanup(setattr, LedgerClient, "rpc", orig)
            d = await s.req("chat.discard", bot="kami")
            self.assertFalse(d["ok"])
            r = await s.req("chat.send", bot="kami", text="you there?")
            self.assertIs(r["result"]["paused"], True)

    async def test_a_thread_lost_in_a_crash_is_shown_and_discarded_in_that_thread_only(self):
        async with LedgerEnv() as env:
            s = await self.open(env)
            tid = (await s.req("thread.create", bot="kami"))["result"]["thread"]
            await s.req("chat.send", bot="kami", session=tid, text="build it")
            await env.restart_after_crash()
            s = await self.open(env)
            await s.req("thread.list", bot="kami")
            opened = (await s.req("thread.open", bot="kami", thread=tid))["result"]
            self.assertEqual(opened["lost"], [{"id": "a1", "text": "build it"}])
            main = (await s.req("chat.open", bot="kami"))["result"]
            self.assertEqual(main["lost"], [])  # the main chat is not paused by its thread
            r = await s.req("chat.send", bot="kami", session=tid, text="still there?")
            self.assertIs(r["result"]["paused"], True)
            self.assertEqual((await s.req("chat.discard", bot="kami", session=tid))["result"], {"discarded": 1})
            c = env.clients["kami"]
            self.assertEqual([p["admission_id"] for p in c.find("prompt.resolve_unknown")], ["a1"])
            self.assertEqual(env.ledger.rows[-1]["status"], "started")


class QueuedWithoutLostTurn(BridgeCase):
    async def test_a_follow_up_queued_behind_a_running_turn_is_shown_without_a_pause(self):
        """A normal chat: a turn runs and a follow-up waits in Hermes' queue behind it. Nothing is lost, so nothing is
        paused; a reopen still shows the follow-up (it is not in the transcript yet), at the same time every read."""
        async with LedgerEnv() as env:
            s = await self.open(env)
            await s.req("chat.send", bot="kami", text="first")
            r = await s.req("chat.send", bot="kami", text="second", queued=True)
            self.assertEqual(set(r["result"]), {"input_id"})  # no `paused`
            opened = (await s.req("chat.open", bot="kami"))["result"]
            self.assertTrue(opened["running"])
            self.assertEqual(opened["lost"], [])
            q = [m for m in opened["messages"] if m.get("queued")]
            self.assertEqual([(m["id"], m["text"]) for m in q], [("q-a2", "second")])
            again = [m for m in (await s.req("chat.open", bot="kami"))["result"]["messages"] if m.get("queued")]
            self.assertEqual(again[0]["ts"], q[0]["ts"])  # Hermes gives it no time: the bridge keeps one

    async def test_hermes_saying_the_lost_turn_is_gone_unpauses_the_chat_at_once(self):
        """Discarded elsewhere (Hermes' Desktop, `/discard`): Hermes' `session.info` carries the new `pending`."""
        async with LedgerEnv() as env:
            s = await self.open(env)
            await s.req("chat.send", bot="kami", text="hello")
            await env.restart_after_crash()
            s = await self.open(env)
            self.assertEqual(len((await s.req("chat.open", bot="kami"))["result"]["lost"]), 1)
            c = env.clients["kami"]
            c.push("session.info", {"pending": [], "running": False})
            await s.until(lambda ev: any(e["event"] == "chat.lost" for e in ev))
            self.assertEqual([e["lost"] for e in s.events if e["event"] == "chat.lost"], [[]])
            r = await s.req("chat.send", bot="kami", text="you there?")
            self.assertNotIn("paused", r["result"])
            # a new lost turn reaches the page the same way; the same pending again sends nothing
            row = {"admission_id": "a9", "sequence": 9, "status": "unknown", "text": "later", "execution_generation": 8}
            c.push("session.info", {"pending": [row]})
            c.push("session.info", {"pending": [row]})
            c.push("session.info", {"running": True})  # no `pending`: changes nothing
            await s.until(lambda ev: sum(e["event"] == "chat.lost" for e in ev) >= 2)
            await s.req("hello")
            self.assertEqual([e["lost"] for e in s.events if e["event"] == "chat.lost"],
                             [[], [{"id": "a9", "text": "later"}]])


class PendingResumeClient(ResumeClient):
    """ResumeClient whose folder chats come back with Hermes' `pending` list, and which takes `prompt.resolve_unknown`."""

    pending: list = []

    async def rpc(self, method, *, _timeout=None, **params):
        if method == "prompt.resolve_unknown":
            self.calls.append((method, params))
            return {"admission_id": params["admission_id"], "status": "terminal", "outcome": "interrupted"}
        snap = await super().rpc(method, _timeout=_timeout, **params)
        if method == "session.resume" and params.get("session_id") != MAIN_STORED:
            snap["pending"] = [dict(r) for r in self.pending]
        return snap


class PendingResumeEnv(ResumeEnv):
    async def factory(self, stack, path: Path):
        name = "default" if path == self.home else path.name
        self.connects.append(name)
        c = self.clients[name] = PendingResumeClient(name, **self.client_kw)
        return c


class FolderChatLostTurn(BridgeCase):
    async def test_a_folder_chat_resumed_after_a_crash_shows_its_lost_turn_and_discards_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = str(Path(tmp) / "web-app")
            Path(folder).mkdir()
            self.addCleanup(setattr, PendingResumeClient, "pending", [])
            PendingResumeClient.pending = [
                {"admission_id": "f1", "sequence": 1, "status": "unknown", "text": "build it", "execution_generation": 6},
                {"admission_id": "f2", "sequence": 2, "status": "queued", "text": "still there?"}]
            async with PendingResumeEnv() as env:
                env.saved([("stored-folder-0", "tui", "omher · web-app", folder)])
                env.recorded((folder, "stored-folder-0"))
                s = await self.open(env)
                r = (await s.req("folder.resume", bot="kami", cwd=folder, stored="stored-folder-0"))["result"]
                self.assertEqual(r["lost"], [{"id": "f1", "text": "build it"}])
                self.assertEqual([(m["id"], m["text"]) for m in r["messages"] if m.get("queued")], [("q-f2", "still there?")])
                sent = await s.req("chat.send", bot="kami", session=r["session"], text="hello?")
                self.assertIs(sent["result"]["paused"], True)
                d = await s.req("chat.discard", bot="kami", session=r["session"])
                self.assertEqual(d["result"], {"discarded": 1})
                self.assertEqual(env.clients["kami"].find("prompt.resolve_unknown"),
                                 [{"session_id": "rt-stored-folder-0", "admission_id": "f1", "execution_generation": 6}])
                self.assertNotIn("paused", (await s.req("chat.send", bot="kami", session=r["session"], text="go"))["result"])


class PendingTurns(unittest.TestCase):
    def test_reads_lost_and_waiting_rows_in_order_and_strips_what_the_bridge_added(self):
        hinted = "you there?\n\n" + ob.PEER_HINT
        lost, shown, waiting = ob.pending_turns({"pending": [
            {"admission_id": "a3", "sequence": 3, "status": "queued", "text": hinted},
            {"admission_id": "a1", "sequence": 1, "status": "unknown", "text": "hello", "execution_generation": 7},
            {"admission_id": "a2", "sequence": 2, "status": "queued", "text": "steering", "steering": True},
            {"admission_id": "a4", "sequence": 4, "status": "unknown", "text": "no generation"},
            {"status": "queued", "text": "no id"}, "junk"]})
        self.assertEqual(lost, {"a1": 7})
        self.assertEqual(shown, [{"id": "a1", "text": "hello"}])
        self.assertEqual([(w["id"], w["text"], w["queued"]) for w in waiting], [("q-a3", "you there?", True)])

    def test_a_watch_delivery_is_left_out_and_a_reply_target_comes_back(self):
        watch = '[Cronjob "inbox" output — scheduled job, not the user.]\nnew mail'
        reply = "post it\n\n" + ob.reply_block("slack:C1:171.2", "#ops")
        _, _, queued = ob.pending_turns({"pending": [
            {"admission_id": "w1", "sequence": 1, "status": "queued", "text": watch},
            {"admission_id": "r1", "sequence": 2, "status": "queued", "text": reply}]}, watch_names={"inbox"})
        self.assertEqual([(q["id"], q["text"], q.get("reply_to")) for q in queued],
                         [("q-r1", "post it", {"target": "slack:C1:171.2", "label": "#ops"})])

    def test_a_queued_row_keeps_the_time_it_was_first_seen_and_a_gone_one_is_forgotten(self):
        seen: dict[str, float] = {"old": 1.0}
        row = {"admission_id": "a2", "sequence": 2, "status": "queued", "text": "second"}
        first = ob.pending_turns({"pending": [row]}, seen=seen)[2][0]["ts"]
        second = ob.pending_turns({"pending": [row]}, seen=seen)[2][0]["ts"]
        self.assertEqual(first, second)
        self.assertEqual(set(seen), {"a2"})

    def test_a_snapshot_without_pending_has_none(self):
        self.assertEqual(ob.pending_turns({}), ({}, [], []))
        self.assertEqual(ob.pending_turns({"pending": None}), ({}, [], []))


if __name__ == "__main__":
    unittest.main()
