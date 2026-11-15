"""`runs.node_session`: one node's session as a chat, read-only (Hermes child from the bot's own state.db; Claude
Code / Codex sessions from the CLI homes). Fixtures: two real kami subagent sessions, trimmed and redacted, and one
real fanout units file (fixtures/node_session)."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402

FIX = HERE / "fixtures" / "node_session"
SECRET = "sk-" + "liveTokenABCDEFGH1234"


def make_profile(root: Path, plant_secret: bool = True) -> Path:
    prof = root / "profiles" / "kami"
    prof.mkdir(parents=True)
    data = json.loads((FIX / "subagents.json").read_text(encoding="utf-8"))
    con = sqlite3.connect(prof / "state.db")
    con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, parent_session_id TEXT, model TEXT,"
                " billing_provider TEXT, started_at REAL, ended_at REAL, end_reason TEXT, title TEXT)")
    con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT,"
                " tool_calls TEXT, tool_name TEXT, tool_call_id TEXT, timestamp REAL, reasoning TEXT,"
                " reasoning_content TEXT)")
    for s in data["sessions"]:
        con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)", tuple(s[k] for k in (
            "id", "source", "parent_session_id", "model", "billing_provider", "started_at", "ended_at", "end_reason",
            "title")))
    # the bot's own sessions those subagents ran under (rule 15: a ref is read only through such a lineage)
    for parent, source in (("local-3bd80316ea6eacd3e888009bce3974ddc49efef85f0d7acfeb64ce37cb07a241", "local"),
                           ("20261108_213859_c9a97486", "discord")):
        con.execute("INSERT INTO sessions (id, source, title) VALUES (?,?,?)", (parent, source, "main"))
    first_tool = True
    for m in data["messages"]:
        content = m["content"]
        if plant_secret and m["role"] == "tool" and first_tool:
            content = f"export OPENAI_API_KEY={SECRET}\n" + (content or "")
            first_tool = False
        con.execute("INSERT INTO messages (session_id, role, content, tool_calls, tool_name, tool_call_id, timestamp,"
                    " reasoning, reasoning_content) VALUES (?,?,?,?,?,?,?,?,?)",
                    (m["session_id"], m["role"], content, m["tool_calls"], m["tool_name"], m["tool_call_id"],
                     m["timestamp"], "PRIVATE-THINKING " + str(m.get("reasoning") or ""),
                     "PRIVATE-THINKING " + str(m.get("reasoning_content") or "")))
    con.commit()
    con.close()
    return prof


def bot_of(prof: Path) -> dict:
    return {"name": "kami", "path": prof, "display_name": "Kami"}


class HermesChild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prof = make_profile(self.root)
        self.ns = ob.NodeSessions(homes={"claude": self.root / "claude", "codex": self.root / "codex"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_found_by_dag_mark_and_read(self):
        sid = self.ns.hermes_find(self.prof, goal_mark="[dag:omher-channel-watch/collector]")
        self.assertEqual(sid, "20261115_210457_2b5242")
        s = self.ns.hermes_read(self.prof, sid, "Kami")
        self.assertEqual(s["kind"], "hermes")
        self.assertEqual(s["model"], "claude-opus-5-5")
        self.assertEqual(s["parent"], "Kami")
        # prompt = first user message, the dag marker taken out
        self.assertEqual(s["prompt"], "Slack/Discord collector script")
        self.assertEqual(s["items"][0]["type"], "user")
        # steps in order, each a tool with its input and matching result
        self.assertGreaterEqual(len(s["steps"]), 8)
        self.assertTrue(all(st["tool"] == "terminal" for st in s["steps"]))
        self.assertIn("command", s["steps"][0]["input"])
        self.assertIn("channel watch dag run", s["steps"][0]["result"])
        # the answer is the child's last words, the last item
        self.assertTrue(s["answer"].startswith("The collector is built"))
        self.assertEqual(s["items"][-1]["type"], "assistant")

    def test_secret_masked_and_clipped(self):
        sid = self.ns.hermes_find(self.prof, goal_mark="[dag:omher-channel-watch/collector]")
        dump = json.dumps(self.ns.hermes_read(self.prof, sid), ensure_ascii=False)
        self.assertTrue(SECRET not in dump, "secret leaked")
        self.assertTrue("sk-•••" in dump, "mask missing")
        s = self.ns.hermes_read(self.prof, sid)
        for st in s["steps"]:
            self.assertLessEqual(len(st["input"].encode()), ob.NS_CLIP + 40)
            self.assertLessEqual(len(st["result"].encode()), ob.NS_CLIP + 40)

    def test_thinking_absent(self):
        for sid in ("20261115_210457_2b5242", "20261114_171334_22863c"):
            dump = json.dumps(self.ns.hermes_read(self.prof, sid), ensure_ascii=False)
            self.assertTrue("PRIVATE-THINKING" not in dump, "thinking leaked")

    def test_codex_model_child_is_still_hermes(self):
        s = self.ns.hermes_read(self.prof, "20261114_171334_22863c")
        self.assertEqual(s["kind"], "hermes")
        self.assertEqual(s["provider"], "openai-codex")
        self.assertEqual([x["tool"] for x in s["steps"][:2]], ["read_file", "read_file"])
        self.assertIn("PR #2876", s["answer"])

    def test_children_listed(self):
        con = sqlite3.connect(self.prof / "state.db")
        con.execute("INSERT INTO sessions VALUES ('20261115_210600_aaaaaa','subagent','20261115_210457_2b5242',"
                    "'glm-5','og',1794744400,1794744500,'agent_close','Subagent: grandchild')")
        con.execute("INSERT INTO messages (session_id, role, content) VALUES ('20261115_210600_aaaaaa','user','Count lines')")
        con.execute("INSERT INTO messages (session_id, role, content) VALUES ('20261115_210600_aaaaaa','assistant','42 lines')")
        con.commit()
        con.close()
        s = self.ns.hermes_read(self.prof, "20261115_210457_2b5242")
        kid = s["children"][0]
        self.assertEqual(kid["ref"], "hermes:20261115_210600_aaaaaa")
        self.assertEqual((kid["goal"], kid["summary"], kid["state"]), ("Count lines", "42 lines", "done"))
        again = self.ns.read(bot_of(self.prof), None, None, None, kid["ref"])["session"]
        self.assertEqual(again["prompt"], "Count lines")

    def test_db_opened_read_only(self):
        before = (self.prof / "state.db").stat().st_mtime_ns
        self.ns.hermes_read(self.prof, "20261115_210457_2b5242")
        self.assertEqual((self.prof / "state.db").stat().st_mtime_ns, before)
        self.assertFalse((self.prof / "state.db-wal").exists())

    def test_bad_ref_refused(self):
        for ref in ("hermes:../../etc", "claude:../x/y", "nope:1", "claude-sub:a/b"):
            with self.assertRaises(ob.BridgeError):
                self.ns.read(bot_of(self.prof), None, None, None, ref)

    def test_every_string_field_masked(self):
        """F1: a token in the session title, a child's first message (its goal) or last words (its summary), a
        grandchild's goal, or the parent's name never leaves the bridge whole."""
        planted = "sk-" + "PLANTEDfake0123456789"
        sid = "20261115_210457_2b5242"
        con = sqlite3.connect(self.prof / "state.db")
        con.execute("UPDATE sessions SET title=? WHERE id=?", ("Subagent " + planted, sid))
        con.execute("INSERT INTO sessions VALUES ('grandchild','subagent',?,'claude-opus-5-5','claude-proxy',"
                    "1794744400,1794744500,'agent_close','child')", (sid,))
        con.execute("INSERT INTO messages (session_id, role, content) VALUES ('grandchild','user',?)", ("Check " + planted,))
        con.execute("INSERT INTO messages (session_id, role, content) VALUES ('grandchild','assistant',?)", ("Used " + planted,))
        con.execute("INSERT INTO sessions VALUES ('great','subagent','grandchild','glm-5','og',1794744410,NULL,NULL,'x')")
        con.execute("INSERT INTO messages (session_id, role, content) VALUES ('great','user',?)", ("Deeper " + planted,))
        con.commit()
        con.close()
        for got in (self.ns.hermes_read(self.prof, sid, "Kami " + planted),
                    self.ns.read(bot_of(self.prof), None, None, None, "hermes:grandchild")["session"]):
            dump = json.dumps(got, ensure_ascii=False)
            self.assertFalse(planted in dump, "planted token leaked")
            self.assertIn("sk-•••", dump)
        s = self.ns.hermes_read(self.prof, sid)
        self.assertEqual(s["title"], "Subagent sk-•••")
        self.assertEqual((s["children"][0]["goal"], s["children"][0]["summary"]), ("Check sk-•••", "Used sk-•••"))


def write_claude(home: Path, folder: str, sid: str, prompt: str, tool_cmd: str, answer: str, ts="2026-11-02T15:40:00Z"):
    d = home / "projects" / ob.claude_slug(folder)
    d.mkdir(parents=True, exist_ok=True)
    lines = [
        {"type": "user", "timestamp": ts, "cwd": folder, "sessionId": sid, "message": {"role": "user", "content": prompt}},
        {"type": "assistant", "timestamp": ts, "cwd": folder, "message": {"model": "claude-opus-5-5", "role": "assistant",
         "content": [{"type": "thinking", "thinking": "PRIVATE-THINKING"},
                     {"type": "tool_use", "id": "tu1", "name": "Bash", "input": {"command": tool_cmd}}]}},
        {"type": "user", "timestamp": ts, "cwd": folder, "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu1", "content": f"ok token {SECRET}"}]}},
        {"type": "assistant", "timestamp": ts, "cwd": folder, "message": {"model": "claude-opus-5-5", "role": "assistant",
         "content": [{"type": "text", "text": answer}]}},
    ]
    p = d / f"{sid}.jsonl"
    p.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return p


def write_codex(home: Path, folder: str, tid: str, prompt: str, cmd: str, answer: str):
    d = home / "sessions" / "2026" / "11" / "02"
    d.mkdir(parents=True, exist_ok=True)
    ts = "2026-11-02T15:40:00Z"
    lines = [
        {"timestamp": ts, "type": "session_meta", "payload": {"id": tid, "timestamp": ts, "cwd": folder}},
        {"timestamp": ts, "type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
        {"timestamp": ts, "type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "# AGENTS.md instructions\nnoise"}]}},
        {"timestamp": ts, "type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt}]}},
        {"timestamp": ts, "type": "response_item", "payload": {"type": "reasoning", "summary": [{"text": "PRIVATE-THINKING"}]}},
        {"timestamp": ts, "type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
         "arguments": json.dumps({"cmd": cmd}), "call_id": "c1"}},
        {"timestamp": ts, "type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1",
         "output": "Process exited with code 0"}},
        {"timestamp": ts, "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": answer}]}},
        {"timestamp": ts, "type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": answer}},
    ]
    p = d / f"rollout-2026-11-02T15-40-00-{tid}.jsonl"
    p.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return p


class CliSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.claude, self.codex = self.root / "claude", self.root / "codex"
        self.ns = ob.NodeSessions(homes={"claude": self.claude, "codex": self.codex})
        self.wt = str(self.root / "wt" / "codex-coexist-t1")
        os.makedirs(self.wt)

    def tearDown(self):
        self.tmp.cleanup()

    def test_claude_read(self):
        p = write_claude(self.claude, self.wt, "s1", "Fix the fence", "pytest -q", "Fence fixed.")
        s = self.ns.claude_read(p, "claude:x/s1", "Kami")
        self.assertEqual((s["kind"], s["prompt"], s["answer"]), ("claude", "Fix the fence", "Fence fixed."))
        self.assertEqual(s["steps"][0]["tool"], "Bash")
        self.assertIn("pytest -q", s["steps"][0]["input"])
        dump = json.dumps(s)
        self.assertNotIn("PRIVATE-THINKING", dump)
        self.assertNotIn(SECRET, dump)

    def test_symlinked_transcript_refused(self):
        real = write_claude(self.root / "elsewhere", self.wt, "s2", "secret prompt", "ls", "x")
        d = self.claude / "projects" / ob.claude_slug(self.wt)
        d.mkdir(parents=True)
        link = d / "s2.jsonl"
        link.symlink_to(real)
        with self.assertRaises(ob.BridgeError):
            self.ns.claude_read(link, "claude:x/s2")
        self.assertIsNone(self.ns.claude_find(self.wt, 0.0))
        # a ref through the op is refused the same way
        with self.assertRaises(ob.BridgeError):
            self.ns.read({"name": "kami", "path": self.root}, None, None, None, f"claude:{d.name}/s2")

    def test_other_folders_session_not_picked(self):
        other = str(self.root / "wt" / "codex-coexist-t1-other")
        os.makedirs(other)
        write_claude(self.claude, other, "s3", "Other work", "ls", "Other answer")
        self.assertIsNone(self.ns.claude_find(self.wt, 0.0))
        mine = write_claude(self.claude, self.wt, "s4", "My work", "ls", "My answer")
        self.assertEqual(self.ns.claude_find(self.wt, 0.0), mine)

    def test_codex_read_and_find_by_worktree(self):
        write_codex(self.codex, str(self.root / "wt" / "other"), "t-other", "Other", "ls", "no")
        p = write_codex(self.codex, self.wt, "t-mine", "Codex skill discovery reads .agents/skills", "pytest tests/x.py",
                        "Discovery reads .agents/skills now.")
        self.assertEqual(self.ns.codex_find(self.wt, 0.0), p)
        s = self.ns.codex_read(p, "Kami")
        self.assertEqual(s["kind"], "codex")
        self.assertEqual(s["prompt"], "Codex skill discovery reads .agents/skills")
        self.assertEqual([x["tool"] for x in s["steps"]], ["exec_command"])
        self.assertIn("pytest tests/x.py", s["steps"][0]["input"])
        self.assertEqual(s["answer"], "Discovery reads .agents/skills now.")
        self.assertNotIn("PRIVATE-THINKING", json.dumps(s))
        self.assertNotIn("AGENTS.md", json.dumps(s["items"]))

    def test_fanout_node_resolves_to_codex_session(self):
        """A dag node owned by codex: units file -> binding worktree -> that folder's rollout."""
        omh = self.root / "omh"
        run_dir = omh / "runtime" / "dag" / "20261102_235818_fcfb1bdd-96bc7f91f27a766c" / "codex-coexist"
        run_dir.mkdir(parents=True)
        (run_dir / "fanout-a1692394be85-units.json").write_text((FIX / "fanout-a1692394be85-units.json").read_text())
        b = omh / "runtime" / "runs" / "fanout-a1692394be85-t1-hermes" / "executor_progress"
        b.mkdir(parents=True)
        (b / "binding.json").write_text(json.dumps({"executor": "codex", "created_at": "2026-11-02T15:39:03Z",
                                                    "correlation_aliases": [{"kind": "worktree", "value": self.wt}]}))
        got = self.ns.fanout_binding(omh, run_dir, "t1-hermes")
        self.assertEqual((got["owner"], got["worktree"]), ("codex", self.wt))
        self.assertIsNone(self.ns.fanout_binding(omh, run_dir, "t9-none"))
        p = write_codex(self.codex, self.wt, "t-mine", "Do t1", "ls", "done t1")
        self.assertEqual(self.ns.codex_find(got["worktree"], got["since"]), p)


class Op(unittest.IsolatedAsyncioTestCase):
    async def test_op_registered_and_validates(self):
        with tempfile.TemporaryDirectory() as t:
            br = ob.Bridge(token="x" * 32, hermes_home=Path(t))
            self.assertIn("runs.node_session", br.ops)
            self.assertIn("runs.node_session", ob.PEER_FORWARD)
            with self.assertRaises(ob.BridgeError):
                await br.op_runs_node_session({"bot": "nobody", "run": "r", "node": "n"})


if __name__ == "__main__":
    unittest.main()
