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
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import fcntl
except ImportError:  # Windows: msvcrt; the lock tests below use flock
    fcntl = None

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402
from test_bridge import MAIN_STORED, BridgeCase, Env, FakeClient  # noqa: E402

THREAD = "stored-th-1"
SLACK = "20261108_235229_aaaf70c4"
LOCK = "folder-chats.lock"  # beside the record; every omher bridge on the computer takes it to write


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
            if os.name == "posix":  # Windows reports its own modes for a chmod
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            rows = json.loads(path.read_text(encoding="utf-8"))["chats"]
            self.assertEqual([(x["profile"], x["cwd"], x["stored"]) for x in rows],
                             [("kami", os.path.normcase(os.path.realpath(self.folder)), r["stored"])])
            # no temp left; the lock every omher on this computer takes sits beside the record
            self.assertEqual(sorted(p.name for p in env.bridge.omher_home.iterdir()),
                             sorted([ob.FOLDER_CHATS_FILE, LOCK]))
            self.assertIs(r["recorded"], True)
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



def _rows(home: Path) -> list[dict]:
    return json.loads((home / ob.FOLDER_CHATS_FILE).read_text(encoding="utf-8"))["chats"]


def _backdate(home: Path, days: float) -> None:
    """Every record in the file made `days` ago (the file written as the bridge writes it)."""
    rows = _rows(home)
    for r in rows:
        r["created_at"] = time.time() - days * 86400
    (home / ob.FOLDER_CHATS_FILE).write_text(json.dumps({"version": 1, "chats": rows}) + "\n", encoding="utf-8")


# A second process that adds one record: it waits until every writer is ready, then reads, holds that snapshot
# a moment, and replaces the file, so two such processes overlap unless the lock serializes them.
_WRITER = r"""
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import omher_bridge as ob
home, cwd, label = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
read = ob.read_folder_chats
def held(path):
    rows = read(path)
    time.sleep(0.4)
    return rows
ob.read_folder_chats = held
(home / ("ready-" + label)).touch()
deadline = time.monotonic() + 5
while not all((home / ("ready-" + x)).exists() for x in sys.argv[5].split(",")):
    if time.monotonic() > deadline:
        raise SystemExit("the other writer never got ready")
    time.sleep(0.005)
ob.record_folder_chat(home, "kami", cwd, label)
"""


class FolderChatRecord(unittest.TestCase):
    """The record's retention, size and cross-process write (review round 2, R2-B1 and R2-B2)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / ".omher"
        self.folder = Path(self.tmp.name) / "web-app"
        self.folder.mkdir()

    def test_records_made_in_the_last_30_days_are_all_kept(self):
        """R2-B1: the count cap applies only to records older than 30 days (and not attached)."""
        ob.record_folder_chat(self.home, "kami", str(self.folder), "closed-oldest")
        _backdate(self.home, 40)
        for i in range(ob.FOLDER_CHATS_MAX + 5):
            ob.record_folder_chat(self.home, "other", str(self.folder), f"recent-{i}")
        ids = [r["stored"] for r in ob.read_folder_chats(self.home)]
        self.assertEqual(ids, ["closed-oldest"] + [f"recent-{i}" for i in range(ob.FOLDER_CHATS_MAX + 5)])
        # once they are old, the newest 512 of them stay
        _backdate(self.home, 40)
        ob.record_folder_chat(self.home, "other", str(self.folder), "new")
        ids = [r["stored"] for r in ob.read_folder_chats(self.home)]
        self.assertEqual(ids, [f"recent-{i}" for i in range(5, ob.FOLDER_CHATS_MAX + 5)] + ["new"])  # "new" is recent: not counted

    def test_the_writer_never_publishes_a_file_the_reader_refuses(self):
        """R2-B1: with long folder paths the writer drops the oldest unprotected records to stay under the reader's
        limit; when even the protected ones do not fit it fails and leaves the old file. The reader takes every file
        the writer produced."""
        deep = self.folder / ("a" * 190) / ("b" * 190) / ("c" * 190)
        deep.mkdir(parents=True)
        for i in range(400):
            if i == 300:
                _backdate(self.home, 40)
            ob.record_folder_chat(self.home, "kami", str(deep), f"old-{i}")
            self.assertLessEqual((self.home / ob.FOLDER_CHATS_FILE).stat().st_size, ob._FOLDER_CHATS_BYTES)
            self.assertEqual(ob.read_folder_chats(self.home)[-1]["stored"], f"old-{i}")  # the reader takes it
        ids = [r["stored"] for r in ob.read_folder_chats(self.home)]
        self.assertNotIn("old-0", ids)  # the oldest went first
        self.assertEqual(ids[-100:], [f"old-{i}" for i in range(300, 400)])  # recent ones all stay
        # every record recent: nothing may go, so a write that would not fit fails and the file stays as it was
        _backdate(self.home, 0)
        before = (self.home / ob.FOLDER_CHATS_FILE).read_bytes()
        with self.assertRaises(OSError):
            for i in range(400):
                ob.record_folder_chat(self.home, "kami", str(deep), f"recent-{i}")
                before = (self.home / ob.FOLDER_CHATS_FILE).read_bytes()
        self.assertEqual((self.home / ob.FOLDER_CHATS_FILE).read_bytes(), before)
        self.assertTrue(ob.read_folder_chats(self.home))
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), sorted([ob.FOLDER_CHATS_FILE, LOCK]))

    def test_two_processes_writing_at_once_both_keep_their_record(self):
        """R2-B2: two bridge processes that add a record at the same moment, each holding what it read, both end
        with their ids in the file."""
        ob.record_folder_chat(self.home, "kami", str(self.folder), "seed")
        labels = ("A", "B")
        procs = [subprocess.Popen([sys.executable, "-B", "-c", _WRITER, str(HERE.parent), str(self.home),
                                   str(self.folder), x, ",".join(labels)]) for x in labels]
        try:
            self.assertEqual([p.wait(timeout=10) for p in procs], [0, 0])
        finally:
            for p in procs:
                if p.poll() is None:
                    p.kill()
                    p.wait(timeout=2)
        self.assertEqual(sorted(r["stored"] for r in ob.read_folder_chats(self.home)), ["A", "B", "seed"])

    @unittest.skipIf(fcntl is None, "POSIX flock")
    def test_a_lock_held_too_long_fails_the_write_and_leaves_the_file(self):
        ob.record_folder_chat(self.home, "kami", str(self.folder), "seed")
        before = (self.home / ob.FOLDER_CHATS_FILE).read_bytes()
        fd = os.open(self.home / LOCK, os.O_RDWR)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        with mock.patch.object(ob, "FOLDER_CHATS_LOCK_WAIT", 0.2, create=True):
            started = time.monotonic()
            with self.assertRaises(OSError):
                ob.record_folder_chat(self.home, "kami", str(self.folder), "late")
            self.assertLess(time.monotonic() - started, 2)
        self.assertEqual((self.home / ob.FOLDER_CHATS_FILE).read_bytes(), before)
        fcntl.flock(fd, fcntl.LOCK_UN)
        ob.record_folder_chat(self.home, "kami", str(self.folder), "late")
        self.assertTrue(ob.is_folder_chat(self.home, "kami", str(self.folder), "late"))

    def test_the_lock_is_refused_when_it_is_not_a_plain_file(self):
        self.home.mkdir()
        (self.home / LOCK).mkdir()
        with self.assertRaises(OSError):
            ob.record_folder_chat(self.home, "kami", str(self.folder), "x")
        self.assertFalse((self.home / ob.FOLDER_CHATS_FILE).exists())


class AttachedChatKeepsItsRecord(BridgeCase):
    async def test_the_oldest_record_survives_512_newer_while_its_chat_is_attached(self):
        """R2-B1 (the reviewer's live-oldest): a folder chat folder.open made 40 days ago and still attached keeps
        its record after 512 newer folder chats this bridge opened and closed; folder.resume still takes it, and an
        old record no bridge holds is the one dropped. With its record gone, a chat attached in the bridge is still
        never listed as a thread."""
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "web-app"
            folder.mkdir()
            async with ResumeEnv() as env:
                b = env.bridge
                p = {"bot": "kami", "cwd": str(folder)}
                live = await b.op_folder_open(p)
                ob.record_folder_chat(b.omher_home, "deepseek", str(folder), "closed-oldest")
                _backdate(b.omher_home, 40)
                for _ in range(ob.FOLDER_CHATS_MAX):
                    churn = await b.op_folder_open(p)
                    await b.op_folder_close({"bot": "kami", "session": churn["session"]})
                _backdate(b.omher_home, 40)
                await b.op_folder_close({"bot": "kami", "session": (await b.op_folder_open(p))["session"]})
                ids = [r["stored"] for r in ob.read_folder_chats(b.omher_home)]
                self.assertIn(live["stored"], ids)
                self.assertNotIn("closed-oldest", ids)
                env.saved([(live["stored"], "tui", "omher · web-app", str(folder))])
                back = await b.op_folder_resume({**p, "stored": live["stored"]})
                self.assertEqual(back.result["session"], live["session"])
                # its record gone: still attached here, still not a thread
                rows = [r for r in _rows(b.omher_home) if r["stored"] != live["stored"]]
                (b.omher_home / ob.FOLDER_CHATS_FILE).write_text(json.dumps({"version": 1, "chats": rows}), encoding="utf-8")
                env.clients["kami"].sessions = [{"id": live["stored"], "title": "omher · web-app", "started_at": 1}]
                self.assertIn(live["session"], b.conns["kami"].folders)
                self.assertEqual((await b.op_thread_list(p))["threads"], [])


class FolderOpenUnrecorded(BridgeCase):
    @unittest.skipIf(fcntl is None, "POSIX flock")
    async def test_folder_open_still_opens_and_says_recorded_false_when_another_omher_holds_the_lock(self):
        """R2-B2: the lock not free in time: the chat opens, the bridge log says loudly that it was not recorded,
        and the reply carries ``recorded: false``."""
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "web-app"
            folder.mkdir()
            async with ResumeEnv() as env:
                home = env.bridge.omher_home
                home.mkdir(parents=True, exist_ok=True)
                fd = os.open(home / LOCK, os.O_RDWR | os.O_CREAT, 0o600)
                self.addCleanup(os.close, fd)
                fcntl.flock(fd, fcntl.LOCK_EX)
                s = await self.open(env)
                with mock.patch.object(ob, "FOLDER_CHATS_LOCK_WAIT", 0.2, create=True), \
                        self.assertLogs("omher.bridge", "ERROR") as logs:
                    r = ok(await s.req("folder.open", bot="kami", cwd=str(folder)))
                self.assertIs(r["recorded"], False)
                self.assertTrue(r["session"].startswith("f"))
                self.assertIn("NOT recorded", "\n".join(logs.output))
                self.assertFalse((home / ob.FOLDER_CHATS_FILE).exists())
                ok(await s.req("chat.send", bot="kami", session=r["session"], text="still works"))


class AnotherBotsWriteKeepsAResumedRecord(BridgeCase):
    """R4-B1: bot kami's folder.resume checks its record and attaches while bot deepseek's folder.open write is on
    its way in the same bridge. The write asks which chats the bridge holds when it publishes, under the lock, so
    kami's row stays: after kami closes the chat, folder.resume takes it again."""

    async def _setup(self, env, folder: Path):
        """kami's closed folder chat, 40 days old, behind 512 newer unprotected rows of another bot: the next write
        drops it unless the bridge holds it."""
        b = env.bridge
        p = {"bot": "kami", "cwd": str(folder)}
        first = await b.op_folder_open(p)
        await b.op_folder_close({**p, "session": first["session"]})
        ancient = time.time() - 40 * 86400
        rows = ob.read_folder_chats(b.omher_home)
        rows[0]["created_at"] = ancient
        rows.extend({"profile": "deepseek", "cwd": str(folder), "stored": f"old-{i}", "created_at": ancient + 1}
                    for i in range(ob.FOLDER_CHATS_MAX))
        (b.omher_home / ob.FOLDER_CHATS_FILE).write_bytes(ob._folder_chats_doc(rows))
        env.saved([(first["stored"], "tui", "omher · web-app", str(folder))])
        return p, first["stored"]

    async def _after(self, env, p: dict, stored: str, written: dict, restored) -> None:
        b = env.bridge
        self.assertIs(written["recorded"], True)
        self.assertIn(restored.result["session"], b.conns["kami"].folders)
        self.assertTrue(ob.is_folder_chat(b.omher_home, "kami", p["cwd"], stored))
        await b.op_folder_close({**p, "session": restored.result["session"]})
        again = await b.op_folder_resume({**p, "stored": stored})
        self.assertIn(again.result["session"], b.conns["kami"].folders)

    async def test_a_resume_while_the_other_bots_write_is_queued_keeps_its_record(self):
        """The reviewer's interleaving: deepseek's write is held before it takes the lock."""
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "web-app"
            folder.mkdir()
            async with ResumeEnv(("kami", "deepseek")) as env:
                p, stored = await self._setup(env, folder)
                entered, go = asyncio.Event(), asyncio.Event()
                real = asyncio.to_thread

                async def hold(func, /, *args, **kwargs):
                    if func is ob.record_folder_chat and args[1] == "deepseek":
                        entered.set()
                        await asyncio.wait_for(go.wait(), 5)
                    return await real(func, *args, **kwargs)

                with mock.patch.object(ob.asyncio, "to_thread", hold):
                    writer = asyncio.create_task(env.bridge.op_folder_open({**p, "bot": "deepseek"}))
                    try:
                        await asyncio.wait_for(entered.wait(), 5)
                        restored = await env.bridge.op_folder_resume({**p, "stored": stored})
                    finally:
                        go.set()
                        written = await asyncio.wait_for(writer, 5)
                await self._after(env, p, stored, written, restored)

    async def test_a_resume_while_the_other_bots_write_holds_its_snapshot_keeps_its_record(self):
        """deepseek's write has read the record under the lock and not yet published when kami's resume starts."""
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "web-app"
            folder.mkdir()
            async with ResumeEnv(("kami", "deepseek")) as env:
                p, stored = await self._setup(env, folder)
                entered, go = threading.Event(), threading.Event()
                real, armed = ob.read_folder_chats, [True]

                def held_read(home):
                    rows = real(home)
                    if armed:
                        armed.clear()
                        entered.set()
                        go.wait(5)
                    return rows

                with mock.patch.object(ob, "read_folder_chats", held_read):
                    writer = asyncio.create_task(env.bridge.op_folder_open({**p, "bot": "deepseek"}))
                    resume = None
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                        resume = asyncio.create_task(env.bridge.op_folder_resume({**p, "stored": stored}))
                        await asyncio.sleep(0.1)
                    finally:
                        go.set()
                        written = await asyncio.wait_for(writer, 5)
                    restored = await asyncio.wait_for(resume, 5)
                await self._after(env, p, stored, written, restored)

    async def test_a_resume_after_the_write_looked_waits_for_it_and_never_attaches_a_dropped_record(self):
        """deepseek's write has asked which chats the bridge holds (kami's is not) and not yet published when kami's
        resume checks its record: the check waits for that write and reads what it published, so kami's dropped
        row is refused and nothing is attached with no record behind it."""
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "web-app"
            folder.mkdir()
            async with ResumeEnv(("kami", "deepseek")) as env:
                p, stored = await self._setup(env, folder)
                entered, go = threading.Event(), threading.Event()
                real = ob._kept_folder_chats

                def held_keep(rows, attached, now):
                    entered.set()
                    go.wait(5)
                    return real(rows, attached, now)

                with mock.patch.object(ob, "_kept_folder_chats", held_keep):
                    writer = asyncio.create_task(env.bridge.op_folder_open({**p, "bot": "deepseek"}))
                    resume = None
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                        resume = asyncio.create_task(env.bridge.op_folder_resume({**p, "stored": stored}))
                        await asyncio.sleep(0.1)
                    finally:
                        go.set()
                        written = await asyncio.wait_for(writer, 5)
                    out = await asyncio.wait_for(asyncio.gather(resume, return_exceptions=True), 5)
                self.assertIs(written["recorded"], True)
                self.assertEqual(getattr(out[0], "code", out[0]), "not_found")
                self.assertFalse(ob.is_folder_chat(env.bridge.omher_home, "kami", str(folder), stored))
                self.assertEqual([f for f in env.bridge.conns["kami"].folders.values() if f.stored_id == stored], [])


if __name__ == "__main__":
    unittest.main()
