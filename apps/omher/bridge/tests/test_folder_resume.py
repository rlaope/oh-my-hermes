"""`folder.resume`: after omher (or the bridge) restarts, an oh-my-hermes folder chat is reattached by the stored id
`folder.open` returned. Only a session `folder.open` recorded for that bot and folder in omher's own folder
(`folder-chats.json`) is taken, and its saved title in the bot's state.db (read-only) must still be
`omher · <folder name>`; the main chat, a thread (even one titled like the folder), a Slack session, a session made
before the record existed and an unknown id are refused before anything is attached. Admission is one at a time per
bot: overlapping resumes of one id attach it once, and the folder chat cap holds for overlapping requests. No Hermes,
no network beyond loopback."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402
from test_bridge import MAIN_STORED, BridgeCase, Env, FakeClient  # noqa: E402

THREAD = "stored-th-1"
SLACK = "20261108_235229_aaaf70c4"


class ResumeClient(FakeClient):
    """FakeClient whose `session.resume` of a stored id answers that session's own runtime id."""

    pending_prompts: list = []

    async def rpc(self, method, *, _timeout=None, **params):
        if method == "session.resume" and params.get("session_id") != MAIN_STORED:
            self.calls.append((method, params))
            sid = params["session_id"]
            return {"session_id": f"rt-{sid}", "stored_session_id": sid, "running": False,
                    "messages": [{"role": "user", "text": "what is here?", "timestamp": 1.0, "row_id": 1},
                                 {"role": "assistant", "text": "two files", "timestamp": 2.0, "row_id": 2}],
                    "info": {**self.model_info, "cwd": "/ignored"}, "execution_generation": 6, "revision": 2,
                    "subscription_id": f"sub-{sid}", "prompts": list(self.pending_prompts)}
        return await super().rpc(method, _timeout=_timeout, **params)


class ResumeEnv(Env):
    async def factory(self, stack, path: Path):
        name = "default" if path == self.home else path.name
        self.connects.append(name)
        c = self.clients[name] = ResumeClient(name, **self.client_kw)
        return c

    def saved(self, rows: list[tuple[str, str, str | None, str | None]]) -> None:
        """The bot's state.db as Hermes keeps it: (id, source, title, cwd) rows."""
        con = sqlite3.connect(self.home / "profiles" / "kami" / "state.db")
        con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, title TEXT, cwd TEXT)")
        con.executemany("INSERT INTO sessions VALUES (?, ?, ?, ?)", rows)
        con.commit()
        con.close()

    def recorded(self, *rows: tuple[str, str]) -> None:
        """What `folder.open` would have recorded for the bot: (cwd, stored id) pairs."""
        for cwd, stored in rows:
            ob.record_folder_chat(self.bridge.omher_home, "kami", cwd, stored)


def ok(r: dict) -> dict:
    assert r["ok"], r
    return r["result"]


class FolderResume(BridgeCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = str(Path(self.tmp.name) / "web-app")
        Path(self.folder).mkdir()
        self.addCleanup(self.tmp.cleanup)

    async def test_folder_open_returns_the_stored_id(self):
        async with Env() as env:
            s = await self.open(env)
            r = ok(await s.req("folder.open", bot="kami", cwd=self.folder))
            self.assertEqual(r["stored"], "stored-folder-0")
            self.assertTrue(r["session"].startswith("f"))

    async def test_its_own_folder_chat_resumes_and_takes_messages_again(self):
        async with ResumeEnv() as env:
            env.saved([("stored-folder-0", "tui", "omher · web-app", self.folder)])
            env.recorded((self.folder, "stored-folder-0"))
            s = await self.open(env)
            r = ok(await s.req("folder.resume", bot="kami", cwd=self.folder, stored="stored-folder-0"))
            self.assertEqual(r["stored"], "stored-folder-0")
            self.assertTrue(r["session"].startswith("f"))
            self.assertEqual(r["cwd"], "/ignored")
            self.assertEqual((r["model"], r["provider"], r["reasoning"]), ("claude-opus-5-5", "claude-proxy", "high"))
            self.assertEqual([m["text"] for m in r["messages"]], ["what is here?", "two files"])
            self.assertFalse(r["running"])
            c = env.clients["kami"]
            self.assertEqual(c.find("session.resume"), [{"session_id": "stored-folder-0"}])
            self.assertEqual(c.find("session.create"), [])  # nothing new is made
            # it is a folder chat again: a message goes to its own runtime id, with its own generation
            ok(await s.req("chat.send", bot="kami", session=r["session"], text="and now?"))
            self.assertEqual([x["session_id"] for x in c.find("prompt.submit")], ["rt-stored-folder-0"])
            # the same stored id again is the same chat, never a second one
            again = ok(await s.req("folder.resume", bot="kami", cwd=self.folder, stored="stored-folder-0"))
            self.assertEqual(again["session"], r["session"])
            self.assertEqual(sum(1 for f in env.bridge.conns["kami"].folders.values() if f.kind == "folder"), 1)
            # and folder.close closes it as it would a new one
            ok(await s.req("folder.close", bot="kami", session=r["session"]))
            self.assertEqual(c.find("session.detach")[-1]["session_id"], "rt-stored-folder-0")

    async def test_waiting_prompts_are_sent_again_after_the_reply(self):
        async with ResumeEnv() as env:
            env.saved([("stored-folder-0", "tui", "omher · web-app", None)])
            env.recorded((self.folder, "stored-folder-0"))
            ResumeClient.pending_prompts = [{"prompt_id": "ap1", "kind": "approval", "command": "rm x",
                                             "description": "Delete", "choices": ["once", "deny"],
                                             "execution_generation": 6}]
            self.addCleanup(setattr, ResumeClient, "pending_prompts", [])
            s = await self.open(env)
            r = ok(await s.req("folder.resume", bot="kami", cwd=self.folder, stored="stored-folder-0"))
            await s.until(lambda ev: any(e["event"] == "approval.request" and e.get("session") == r["session"] for e in ev))

    async def test_any_other_session_is_refused_before_anything_is_attached(self):
        other = str(Path(self.tmp.name) / "api")
        Path(other).mkdir()
        async with ResumeEnv() as env:
            env.saved([
                (MAIN_STORED, "tui", ob.BOT_CHAT_TITLE, None),
                (THREAD, "tui", "omher · Fix the 502", self.folder),  # a thread under the bot
                ("bare", "tui", "omher · new thread 1a2b3c", None),
                (SLACK, "slack", "slack thing", None),
                ("other-folder", "tui", "omher · api", other),  # another folder's chat
                ("moved", "tui", "omher · web-app", other),  # the same name, saved in another folder
                ("untitled", "tui", None, None),
            ])
            s = await self.open(env)
            ok(await s.req("chat.open", bot="kami"))  # the main chat is attached: its ids are known
            for stored in (MAIN_STORED, "rt-main", THREAD, "bare", SLACK, "other-folder", "moved", "untitled", "nope"):
                r = await s.req("folder.resume", bot="kami", cwd=self.folder, stored=stored)
                self.assertFalse(r["ok"], stored)
                self.assertEqual(r["error"]["code"], "not_found", stored)
            for bad in ({"stored": ""}, {"stored": 5}, {"stored": "x" * 201}, {"cwd": "relative"}, {"cwd": "/no/such/dir"}):
                r = await s.req("folder.resume", bot="kami", **{"cwd": self.folder, "stored": "stored-folder-0", **bad})
                self.assertEqual(r["error"]["code"], "bad_request", bad)
            c = env.clients["kami"]
            self.assertEqual([x["session_id"] for x in c.find("session.resume")], [MAIN_STORED])  # chat.open's only
            self.assertEqual(c.find("prompt.submit"), [])
            self.assertEqual([f for f in env.bridge.conns["kami"].folders.values() if f.kind == "folder"], [])

    async def test_a_thread_this_bridge_holds_is_refused(self):
        async with ResumeEnv() as env:
            env.saved([("stored-folder-0", "tui", "omher · web-app", None)])
            s = await self.open(env)
            conn = await env.bridge._conn("kami")
            conn.folders["stored-folder-0"] = ob.FolderChat("stored-folder-0", self.folder, "rt-x", "stored-folder-0",
                                                            kind="thread")
            r = await s.req("folder.resume", bot="kami", cwd=self.folder, stored="stored-folder-0")
            self.assertEqual(r["error"]["code"], "not_found")
            self.assertEqual(env.clients["kami"].find("session.resume"), [])

    async def test_the_folder_chat_cap_holds(self):
        async with ResumeEnv() as env:
            env.saved([("stored-folder-0", "tui", "omher · web-app", None)])
            env.recorded((self.folder, "stored-folder-0"))
            s = await self.open(env)
            conn = await env.bridge._conn("kami")
            for n in range(ob.MAX_FOLDER_CHATS):
                conn.folders[f"f{n}"] = ob.FolderChat(f"f{n}", self.folder, f"rt-{n}", f"st-{n}")
            r = await s.req("folder.resume", bot="kami", cwd=self.folder, stored="stored-folder-0")
            self.assertEqual(r["error"]["code"], "bad_request")
            self.assertEqual(env.clients["kami"].find("session.resume"), [])

    async def test_no_state_db_means_no_resume(self):
        async with ResumeEnv() as env:
            s = await self.open(env)
            r = await s.req("folder.resume", bot="kami", cwd=self.folder, stored="stored-folder-0")
            self.assertEqual(r["error"]["code"], "not_found")
            self.assertEqual(env.clients["kami"].find("session.resume"), [])

    async def test_a_thread_titled_like_the_folder_is_refused_on_a_fresh_connection(self):
        """Finding 1: the title is not proof. A thread a person named for its own folder has the folder chat's title
        and folder in state.db, and a fresh connection has listed no threads; without folder.open's record it is
        refused before anything is attached."""
        async with ResumeEnv() as env:
            env.saved([(THREAD, "tui", "omher · web-app", self.folder)])
            s = await self.open(env)
            r = await s.req("folder.resume", bot="kami", cwd=self.folder, stored=THREAD)
            self.assertEqual(r["error"]["code"], "not_found")
            self.assertEqual(env.clients["kami"].find("session.resume"), [])
            # a legacy folder chat (made before the record existed) is refused the same way: its row stays paused
            self.assertFalse(ob.is_folder_chat(env.bridge.omher_home, "kami", self.folder, THREAD))

    async def test_the_record_is_bound_to_the_bot_and_the_folder(self):
        other = str(Path(self.tmp.name) / "other" / "web-app")
        Path(other).mkdir(parents=True)
        async with ResumeEnv() as env:
            env.saved([("stored-folder-0", "tui", "omher · web-app", None)])
            ob.record_folder_chat(env.bridge.omher_home, "deepseek", self.folder, "stored-folder-0")  # another bot
            env.recorded((other, "stored-folder-0"))  # another folder of the same name
            s = await self.open(env)
            r = await s.req("folder.resume", bot="kami", cwd=self.folder, stored="stored-folder-0")
            self.assertEqual(r["error"]["code"], "not_found")
            self.assertEqual(env.clients["kami"].find("session.resume"), [])
            # the folder is compared by its real path: a link to it is the same folder
            link = Path(self.tmp.name) / "link-to-web-app"
            os.symlink(self.folder, link)
            env.recorded((str(link), "stored-folder-0"))
            ok(await s.req("folder.resume", bot="kami", cwd=self.folder, stored="stored-folder-0"))

    async def test_folder_open_records_its_chat_owner_only_and_thread_list_leaves_it_out(self):
        """folder.open writes the record (bot, real folder, stored id) in omher's own folder, mode 600, replaced
        whole; thread.list never lists a recorded folder chat as a thread, even on a fresh connection that has not
        attached it, so folder.resume still takes it afterwards."""
        async with ResumeEnv() as env:
            s = await self.open(env)
            r = ok(await s.req("folder.open", bot="kami", cwd=self.folder))
            path = env.bridge.omher_home / ob.FOLDER_CHATS_FILE
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            rows = json.loads(path.read_text(encoding="utf-8"))["chats"]
            self.assertEqual([(x["profile"], x["cwd"], x["stored"]) for x in rows],
                             [("kami", os.path.normcase(os.path.realpath(self.folder)), r["stored"])])
            self.assertEqual([p.name for p in env.bridge.omher_home.iterdir()], [ob.FOLDER_CHATS_FILE])  # no temp left
            # a restarted bridge: nothing attached; the saved folder chat shows in session.list with the thread prefix
            conn = await env.bridge._conn("kami")
            conn.folders.clear()
            env.clients["kami"].sessions = [{"id": r["stored"], "title": "omher · web-app", "started_at": 1},
                                            {"id": THREAD, "title": "omher · Fix the 502", "started_at": 2}]
            threads = ok(await s.req("thread.list", bot="kami"))["threads"]
            self.assertEqual([t["thread"] for t in threads], [THREAD])
            env.saved([(r["stored"], "tui", "omher · web-app", self.folder)])
            back = ok(await s.req("folder.resume", bot="kami", cwd=self.folder, stored=r["stored"]))
            self.assertEqual(back["stored"], r["stored"])

    async def test_overlapping_resumes_of_one_id_attach_it_once(self):
        """Finding 2: two folder.resume requests for one stored id that overlap make one session.resume and get one
        bridge id; the folder chat is kept once."""
        async with ResumeEnv() as env:
            env.saved([("stored-folder-0", "tui", "omher · web-app", self.folder)])
            env.recorded((self.folder, "stored-folder-0"))
            await env.bridge._conn("kami")
            c = env.clients["kami"]
            gate = asyncio.Event()
            real = c.rpc

            async def held(method, **params):
                if method == "session.resume":
                    await gate.wait()
                return await real(method, **params)

            c.rpc = held
            p = {"bot": "kami", "cwd": self.folder, "stored": "stored-folder-0"}
            a = asyncio.ensure_future(env.bridge.op_folder_resume(dict(p)))
            b = asyncio.ensure_future(env.bridge.op_folder_resume(dict(p)))
            for _ in range(20):
                await asyncio.sleep(0)
            gate.set()
            ra, rb = await asyncio.wait_for(asyncio.gather(a, b), 5)
            self.assertEqual(ra.result["session"], rb.result["session"])
            self.assertEqual(len(c.find("session.resume")), 1)
            folders = [f for f in env.bridge.conns["kami"].folders.values() if f.kind == "folder"]
            self.assertEqual([f.stored_id for f in folders], ["stored-folder-0"])
            self.assertEqual(env.bridge.conns["kami"].resuming, {})

    async def test_a_refusal_reaches_every_overlapping_request(self):
        async with ResumeEnv() as env:
            env.saved([("stored-folder-0", "tui", "omher · web-app", self.folder)])
            await env.bridge._conn("kami")
            p = {"bot": "kami", "cwd": self.folder, "stored": "stored-folder-0"}
            out = await asyncio.gather(env.bridge.op_folder_resume(dict(p)), env.bridge.op_folder_resume(dict(p)),
                                       return_exceptions=True)
            self.assertEqual([getattr(e, "code", e) for e in out], ["not_found", "not_found"])
            self.assertEqual(env.bridge.conns["kami"].resuming, {})

    async def test_overlapping_admissions_at_the_cap_admit_one(self):
        """Finding 2: one slot left under MAX_FOLDER_CHATS and two overlapping requests for different ids (a resume
        and a resume, then a resume and an open): one is admitted, the other refused, and the cap is never passed."""
        async with ResumeEnv() as env:
            env.saved([("stored-a", "tui", "omher · web-app", self.folder), ("stored-b", "tui", "omher · web-app", self.folder)])
            env.recorded((self.folder, "stored-a"), (self.folder, "stored-b"))
            conn = await env.bridge._conn("kami")
            for n in range(ob.MAX_FOLDER_CHATS - 1):
                conn.folders[f"f{n}"] = ob.FolderChat(f"f{n}", self.folder, f"rt-{n}", f"st-{n}")
            c = env.clients["kami"]
            real = c.rpc

            async def slow(method, **params):
                await asyncio.sleep(0.01)
                return await real(method, **params)

            c.rpc = slow
            out = await asyncio.gather(
                env.bridge.op_folder_resume({"bot": "kami", "cwd": self.folder, "stored": "stored-a"}),
                env.bridge.op_folder_resume({"bot": "kami", "cwd": self.folder, "stored": "stored-b"}),
                return_exceptions=True)
            self.assertEqual(sorted(type(x).__name__ for x in out), ["BridgeError", "Reply"])
            self.assertEqual([x.code for x in out if isinstance(x, ob.BridgeError)], ["bad_request"])
            self.assertEqual(len(c.find("session.resume")), 1)
            self.assertEqual(sum(1 for f in conn.folders.values() if f.kind == "folder"), ob.MAX_FOLDER_CHATS)
            # one slot again: an open and a resume that overlap share the same admission
            conn.folders.pop("f0")
            out = await asyncio.gather(
                env.bridge.op_folder_open({"bot": "kami", "cwd": self.folder}),
                env.bridge.op_folder_resume({"bot": "kami", "cwd": self.folder,
                                             "stored": "stored-b" if any(f.stored_id == "stored-a" for f in conn.folders.values()) else "stored-a"}),
                return_exceptions=True)
            self.assertEqual(sum(1 for x in out if isinstance(x, ob.BridgeError)), 1)
            self.assertEqual(sum(1 for f in conn.folders.values() if f.kind == "folder"), ob.MAX_FOLDER_CHATS)

    def test_the_record_file_is_refused_when_it_is_not_a_plain_file(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ob.FOLDER_CHATS_FILE).mkdir()
            self.assertEqual(ob.read_folder_chats(home), [])
            (home / ob.FOLDER_CHATS_FILE).rmdir()
            real = home / "elsewhere.json"
            real.write_text(json.dumps({"chats": [{"profile": "kami", "cwd": d, "stored": "x"}]}), encoding="utf-8")
            os.symlink(real, home / ob.FOLDER_CHATS_FILE)
            self.assertEqual(ob.read_folder_chats(home), [])  # never through a link
            (home / ob.FOLDER_CHATS_FILE).unlink()
            (home / ob.FOLDER_CHATS_FILE).write_text("not json", encoding="utf-8")
            self.assertEqual(ob.read_folder_chats(home), [])
            ob.record_folder_chat(home, "kami", d, "x")  # a broken file is replaced whole, never appended to
            self.assertTrue(ob.is_folder_chat(home, "kami", d, "x"))

    def test_the_reader_opens_state_db_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "state.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, cwd TEXT)")
            con.execute("INSERT INTO sessions VALUES ('a', 'omher · x', '/w/x')")
            con.commit()
            con.close()
            before = db.read_bytes()
            self.assertEqual(ob.read_session_title(Path(d), "a"), ("omher · x", "/w/x"))
            self.assertIsNone(ob.read_session_title(Path(d), "b"))
            self.assertIsNone(ob.read_session_title(Path(d), ""))
            self.assertEqual(db.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
