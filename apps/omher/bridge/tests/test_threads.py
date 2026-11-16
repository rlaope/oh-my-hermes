"""Threads under a bot (`thread.*`): create, list (also after a bridge restart), open, send, remove = interrupt +
withdraw asks + Hermes `session.archive`. A FakeGateway stands in for Hermes; no Hermes, no network beyond loopback."""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402
from test_bridge import BridgeCase, Env, FakeClient, GatewayRPCError, MAIN_STORED  # noqa: E402


class HermesStore:
    """What survives a bridge restart: the profile's saved sessions (Hermes' state.db) and its idempotency keys."""

    def __init__(self):
        self.rows: dict[str, dict] = {}   # stored id -> {id, title, started_at, message_count, archived}
        self.keys: dict[str, str] = {}    # idempotency_key -> stored id
        self.n = 0


class ThreadClient(FakeClient):
    """FakeClient plus the session calls threads use, over a HermesStore shared by every connect."""

    def __init__(self, name, store: HermesStore, **kw):
        super().__init__(name, **kw)
        self.store = store
        self.running: set[str] = set()   # runtime ids whose turn runs
        self.pending_prompts: dict[str, list] = {}

    async def rpc(self, method, *, _timeout=None, **params):
        st = self.store
        if method == "session.create" and str(params.get("title", "")).startswith(ob.THREAD_PREFIX):
            self.calls.append((method, params))
            key = params.get("idempotency_key")
            if key and key in st.keys:
                sid = st.keys[key]
            else:
                st.n += 1
                sid = f"stored-th-{st.n}"
                # a row only after the first prompt, as Hermes does (no "Untitled" litter)
                st.rows[sid] = {"id": sid, "title": params["title"], "started_at": 1000.0 + st.n, "message_count": 0,
                                "archived": False, "saved": False}
                if key:
                    st.keys[key] = sid
            return {"session_id": f"rt-{sid}", "stored_session_id": sid, "messages": [], "subscription_id": f"sub-{sid}",
                    "info": {**self.model_info, "cwd": params.get("cwd") or "/home/me"}, "revision": 0,
                    "execution_generation": 0}
        if method == "session.list" and params.get("title") is None:
            self.calls.append((method, params))
            rows = [{k: r[k] for k in ("id", "title", "started_at", "message_count")} | {"source": "tui", "preview": ""}
                    for r in st.rows.values() if r["saved"] and not r["archived"]]
            rows.append({"id": MAIN_STORED, "title": "omher · not a thread really", "source": "tui"})  # never listed
            return {"sessions": sorted(rows, key=lambda r: -float(r.get("started_at") or 0))}
        if method == "prompt.submit" and params["session_id"].startswith("rt-stored-th-"):
            self.calls.append((method, params))
            st.rows[params["session_id"][3:]]["saved"] = True
            st.rows[params["session_id"][3:]]["message_count"] += 1
            return {"status": "started", "admission_id": "adm", "execution_generation": 4}
        if method == "session.title" and params["session_id"].startswith("rt-stored-th-"):
            self.calls.append((method, params))
            if any(r["title"] == params["title"] for r in st.rows.values()):
                raise GatewayRPCError("Title already in use")
            st.rows[params["session_id"][3:]]["title"] = params["title"]
            return {"pending": False, "title": params["title"]}
        if method == "session.resume" and str(params.get("session_id", "")).startswith("stored-th-"):
            self.calls.append((method, params))
            sid = params["session_id"]
            return {"session_id": f"rt-{sid}", "stored_session_id": sid, "running": f"rt-{sid}" in self.running,
                    "messages": [{"role": "user", "text": "first", "timestamp": 1.0, "row_id": 1},
                                 {"role": "assistant", "text": "answer", "timestamp": 2.0, "row_id": 2}],
                    "info": dict(self.model_info), "execution_generation": 5,
                    "prompts": self.pending_prompts.get(sid, [])}
        if method == "session.archive":
            self.calls.append((method, params))
            st.rows[params["session_id"]]["archived"] = params.get("archived", True)
            return {"archived": True, "session_key": params["session_id"]}
        return await super().rpc(method, _timeout=_timeout, **params)


class ThreadEnv(Env):
    def __init__(self, store: HermesStore | None = None, **kw):
        super().__init__(**kw)
        self.store = store or HermesStore()

    async def factory(self, stack, path: Path):
        name = "default" if path == self.home else path.name
        self.connects.append(name)
        c = self.clients[name] = ThreadClient(name, self.store, **self.client_kw)
        return c


def ok(r: dict) -> dict:
    assert r["ok"], r
    return r["result"]


class Threads(BridgeCase):
    async def open(self, env):
        """A client as the app is one: the bot's main chat is open before its threads are listed."""
        s = await super().open(env)
        ok(await s.req("chat.open", bot="kami"))
        return s

    async def test_create_list_restart_lists_it_once(self):
        store = HermesStore()
        async with ThreadEnv(store) as env:
            s = await self.open(env)
            made = ok(await s.req("thread.create", bot="kami", key="press1"))
            tid = made["thread"]
            self.assertEqual(tid, "stored-th-1")
            self.assertEqual(made["title"], "")
            create = env.clients["kami"].find("session.create")[-1]
            self.assertTrue(create["title"].startswith("omher · new thread "))
            self.assertNotIn("cwd", create)  # no cwd: the profile's own default
            self.assertEqual(create["idempotency_key"], "omher-thread:kami:press1")
            # the same press again (a retry racing a restart) is the same thread, listed once
            again = ok(await s.req("thread.create", bot="kami", key="press1"))
            self.assertEqual(again["thread"], tid)
            listed = ok(await s.req("thread.list", bot="kami"))["threads"]
            self.assertEqual([t["thread"] for t in listed], [tid])
            ok(await s.req("chat.send", bot="kami", session=tid, text="OG 대시보드 502 원인 찾기 — gateway 로그부터 봐줘"))
            c = env.clients["kami"]
            self.assertEqual(c.find("prompt.submit")[-1]["session_id"], "rt-stored-th-1")
            self.assertEqual(c.find("session.title")[-1]["title"], "omher · OG 대시보드 502 원인 찾기 — gateway 로그부터 봐줘")
            await s.until(lambda ev: any(e["event"] == "session.title" and e.get("session") == tid for e in ev))
        # a new bridge on the same Hermes: the thread comes back from session.list, once, named
        async with ThreadEnv(store) as env2:
            s2 = await self.open(env2)
            again = ok(await s2.req("thread.list", bot="kami"))["threads"]
            self.assertEqual([(t["thread"], t["title"]) for t in again],
                             [(tid, "OG 대시보드 502 원인 찾기 — gateway 로그부터 봐줘")])
            self.assertNotIn(MAIN_STORED, [t["thread"] for t in again])  # the main chat is never a thread
            ok(await s2.req("thread.create", bot="kami", key="press1"))  # the old key, after the restart
            self.assertEqual(len(ok(await s2.req("thread.list", bot="kami"))["threads"]), 1)
            opened = ok(await s2.req("thread.open", bot="kami", thread=tid))
            self.assertEqual([m["text"] for m in opened["messages"]], ["first", "answer"])
            ok(await s2.req("chat.send", bot="kami", session=tid, text="and the retry policy?"))
            self.assertEqual(env2.clients["kami"].find("prompt.submit")[-1]["session_id"], "rt-stored-th-1")
            self.assertEqual(env2.clients["kami"].find("session.title"), [])  # already named

    async def test_a_listed_thread_carries_the_folder_hermes_saved(self):
        """F6: after a restart a thread is listed before it is attached; its row carries the cwd Hermes saved for the
        session (state.db `sessions.cwd`, read-only), so the terminal's next tab starts there. None saved: ""."""
        import sqlite3
        store = HermesStore()
        async with ThreadEnv(store) as env:
            s = await self.open(env)
            tid = ok(await s.req("thread.create", bot="kami"))["thread"]
            ok(await s.req("chat.send", bot="kami", session=tid, text="first"))
            other = ok(await s.req("thread.create", bot="kami"))["thread"]
            ok(await s.req("chat.send", bot="kami", session=other, text="second"))
        async with ThreadEnv(store) as env2:  # a new bridge on the same Hermes: nothing attached yet
            con = sqlite3.connect(env2.home / "profiles" / "kami" / "state.db")
            con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, cwd TEXT)")
            con.execute("INSERT INTO sessions VALUES (?, 'tui', '/work/restored')", (tid,))
            con.execute("INSERT INTO sessions VALUES (?, 'tui', NULL)", (other,))
            con.commit()
            con.close()
            s2 = await self.open(env2)
            rows = {t["thread"]: t["cwd"] for t in ok(await s2.req("thread.list", bot="kami"))["threads"]}
            self.assertEqual(rows, {tid: "/work/restored", other: ""})

    async def test_send_to_unknown_refused_and_main_cannot_be_removed(self):
        async with ThreadEnv() as env:
            s = await self.open(env)
            r = await s.req("chat.send", bot="kami", session="stored-th-99", text="hi")
            self.assertEqual(r["error"]["code"], "not_found")
            for tid in (MAIN_STORED, "rt-main"):
                r = await s.req("thread.remove", bot="kami", thread=tid)
                self.assertFalse(r["ok"])
                self.assertEqual(r["error"]["code"], "bad_request")
            r = await s.req("thread.remove", bot="kami", thread="someone-elses-session")
            self.assertEqual(r["error"]["code"], "not_found")
            r = await s.req("thread.open", bot="kami", thread="someone-elses-session")
            self.assertEqual(r["error"]["code"], "not_found")
            c = env.clients["kami"]
            self.assertEqual(c.find("session.archive"), [])
            self.assertEqual([x["session_id"] for x in c.find("prompt.submit")], [])

    async def test_steer_in_a_thread_carries_that_threads_generation_and_a_foreign_id_is_refused(self):
        """Steer queue in a thread: `chat.steer {session}` steers that thread's running turn (its runtime id and its
        own execution_generation, not the main chat's); an id the bridge did not create or list is refused."""
        from test_steer_queue import steer_answers
        async with ThreadEnv() as env:
            s = await self.open(env)
            tid = ok(await s.req("thread.create", bot="kami"))["thread"]
            ok(await s.req("chat.send", bot="kami", session=tid, text="first running task"))
            c = env.clients["kami"]
            c.push("message.start", {}, sid="rt-" + tid, execution_generation=7)
            await s.until(lambda ev: any(e["event"] == "turn.start" and e.get("session") == tid for e in ev))
            steer_answers(env, {"status": "queued"})
            self.assertEqual(ok(await s.req("chat.steer", bot="kami", session=tid, text="keep the old timeout")),
                             {"status": "queued"})
            [call] = c.find("session.steer")
            self.assertEqual((call["session_id"], call["text"], call["execution_generation"]),
                             ("rt-" + tid, "keep the old timeout", 7))
            for sid in ("someone-elses-session", MAIN_STORED, "rt-" + tid):
                r = await s.req("chat.steer", bot="kami", session=sid, text="x")
                self.assertEqual(r["error"]["code"], "not_found", sid)
            self.assertEqual(len(c.find("session.steer")), 1)
            self.assertEqual([x["session_id"] for x in c.find("prompt.submit")], ["rt-" + tid])

    async def test_remove_interrupts_then_archives_in_order(self):
        async with ThreadEnv() as env:
            s = await self.open(env)
            tid = ok(await s.req("thread.create", bot="kami"))["thread"]
            ok(await s.req("chat.send", bot="kami", session=tid, text="long job"))
            c = env.clients["kami"]
            c.push("message.start", {}, sid="rt-" + tid)
            await s.until(lambda ev: any(e["event"] == "turn.start" and e.get("session") == tid for e in ev))
            res = ok(await s.req("thread.remove", bot="kami", thread=tid))
            self.assertEqual(res, {"thread": tid, "archived": True})
            order = [m for m, _ in c.calls if m in ("session.interrupt", "session.archive", "session.detach")]
            self.assertEqual(order, ["session.interrupt", "session.archive", "session.detach"])
            self.assertEqual(c.find("session.interrupt")[-1]["session_id"], "rt-" + tid)
            self.assertEqual(c.find("session.archive")[-1], {"session_id": tid, "archived": True})
            self.assertEqual(c.find("session.detach")[-1]["end_reason"], "omher_archive")
            await s.until(lambda ev: any(e["event"] == "thread.removed" and e["thread"] == tid for e in ev))
            ends = [e for e in s.events if e["event"] == "turn.end" and e.get("session") == tid]
            self.assertEqual([e["outcome"] for e in ends], ["interrupted"])
            # gone: no longer listed, sends refused, archived (not deleted) in Hermes
            self.assertEqual(ok(await s.req("thread.list", bot="kami"))["threads"], [])
            r = await s.req("chat.send", bot="kami", session=tid, text="still there?")
            self.assertEqual(r["error"]["code"], "not_found")
            self.assertTrue(env.store.rows[tid]["archived"])
            self.assertNotIn("session.delete", [m for m, _ in c.calls])

    async def test_remove_idle_thread_archives_without_interrupt(self):
        async with ThreadEnv() as env:
            s = await self.open(env)
            tid = ok(await s.req("thread.create", bot="kami"))["thread"]
            ok(await s.req("thread.remove", bot="kami", thread=tid))
            c = env.clients["kami"]
            self.assertEqual(c.find("session.interrupt"), [])
            self.assertEqual(len(c.find("session.archive")), 1)

    async def test_remove_withdraws_a_waiting_approval(self):
        async with ThreadEnv() as env:
            s = await self.open(env)
            tid = ok(await s.req("thread.create", bot="kami"))["thread"]
            ok(await s.req("chat.send", bot="kami", session=tid, text="clean up build/"))
            c = env.clients["kami"]
            c.push("message.start", {}, sid="rt-" + tid)
            c.push("approval.request", {"prompt_id": "ap1", "command": "rm -rf build", "description": "Delete"},
                   sid="rt-" + tid, execution_generation=2)
            await s.until(lambda ev: any(e["event"] == "approval.request" and e.get("session") == tid for e in ev))
            ok(await s.req("thread.remove", bot="kami", thread=tid))
            await s.until(lambda ev: any(e["event"] == "prompt.expired" and e.get("session") == tid for e in ev))
            gone = [e for e in s.events if e["event"] == "prompt.expired"][0]
            self.assertEqual((gone["request_id"], gone["reason"]), ("ap1", "cancelled"))
            # the expiry comes before the archive's thread.removed, so the Needs-you list drops it first
            kinds = [e["event"] for e in s.events if e.get("session") == tid or e.get("thread") == tid]
            self.assertLess(kinds.index("prompt.expired"), kinds.index("thread.removed"))
            # and nothing answers it on the person's behalf
            self.assertEqual(c.find("approval.respond"), [])

    async def test_cancel_makes_no_call(self):
        """The confirm's Cancel sends nothing: the bridge sees no thread op, Hermes sees no interrupt or archive."""
        async with ThreadEnv() as env:
            s = await self.open(env)
            tid = ok(await s.req("thread.create", bot="kami"))["thread"]
            before = list(env.clients["kami"].calls)
            # (the app's Cancel is a no-op; the bridge side of that is that nothing arrives)
            await asyncio.sleep(0.05)
            self.assertEqual(env.clients["kami"].calls, before)
            self.assertEqual([t["thread"] for t in ok(await s.req("thread.list", bot="kami"))["threads"]], [tid])

    async def test_thread_create_validates(self):
        async with ThreadEnv() as env:
            s = await self.open(env)
            for bad in ({"cwd": "relative/path"}, {"cwd": "/no/such/folder/xyz"}, {"title": ""}, {"key": "has space"}):
                r = await s.req("thread.create", bot="kami", **bad)
                self.assertEqual(r["error"]["code"], "bad_request", bad)
            r = await s.req("thread.create", bot="kami", cwd=str(HERE), title="Docs dark mode")
            res = ok(r)
            self.assertEqual(res["title"], "Docs dark mode")
            create = env.clients["kami"].find("session.create")[-1]
            self.assertEqual((create["cwd"], create["cwd_explicit"], create["title"]), (str(HERE), True, "omher · Docs dark mode"))

    async def test_folder_chats_are_not_threads(self):
        async with ThreadEnv() as env:
            s = await self.open(env)
            fid = ok(await s.req("folder.open", bot="kami", cwd=str(HERE)))["session"]
            r = await s.req("thread.remove", bot="kami", thread=fid)
            self.assertEqual(r["error"]["code"], "not_found")
            self.assertEqual(ok(await s.req("thread.list", bot="kami"))["threads"], [])

    def test_thread_name(self):
        self.assertEqual(ob.thread_name("omher · new thread 1a2b3c"), "")
        self.assertEqual(ob.thread_name("omher · OG 대시보드 502 원인 찾기"), "OG 대시보드 502 원인 찾기")


if __name__ == "__main__":
    unittest.main()
