"""`folder.resume`: after omher (or the bridge) restarts, an oh-my-hermes folder chat is reattached by the stored id
`folder.open` returned. Only a session the bridge made for that folder is taken (its saved title in the bot's state.db,
read-only, is `omher · <folder name>`); the main chat, a thread, a Slack session and an unknown id are refused before
anything is attached. No Hermes, no network beyond loopback."""
from __future__ import annotations

import sqlite3
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
