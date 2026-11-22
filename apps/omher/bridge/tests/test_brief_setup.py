"""The briefing omher sets up by itself (BOUNDARY rule 24): `brief_plan` decides per local bot, `install_brief` copies
the collector, writes its config and runs one fixed `hermes -p <bot> cron create`. Every test uses a temp Hermes
home and a fake runner: no real profile, no real `hermes`."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402

SECRET = "xoxb-SECRET-value-never-read-123"


class BriefSetup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / "hermes"
        self.omher = self.root / "omher"
        self.p = self.home / "profiles" / "kami"
        (self.p / "cron").mkdir(parents=True)
        (self.home / "config.yaml").write_text("model: x\n", encoding="utf-8")
        (self.p / "config.yaml").write_text("model: x\n", encoding="utf-8")
        kit = self.p / "skills" / "operator" / "omh-automation-blueprint" / "toolkit" / "scripts"
        kit.mkdir(parents=True)
        (kit / "channel_watch.py").write_text("# collector\n", encoding="utf-8")
        self.env(f"SLACK_BOT_TOKEN={SECRET}\nSLACK_ALLOWED_USERS=UOWNER1\n")
        self.calls: list[list[str]] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def env(self, text: str) -> None:
        (self.p / ".env").write_text(text, encoding="utf-8")

    def jobs(self, *jobs: dict) -> None:
        (self.p / "cron" / "jobs.json").write_text(json.dumps({"jobs": list(jobs)}), encoding="utf-8")

    def sessions(self, *origins: dict) -> None:
        con = sqlite3.connect(self.p / "state.db")
        con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, origin_json TEXT)")
        con.executemany("INSERT INTO sessions VALUES (?, ?)", [(f"s{i}", json.dumps(o)) for i, o in enumerate(origins)])
        con.commit()
        con.close()

    def plan(self, optout=frozenset()) -> dict:
        return ob.brief_plan(self.p, self.home, set(optout), "kami")

    def runner(self, code=0, out=""):
        def run(argv, home, timeout):
            self.calls.append(argv)
            self.assertEqual((Path(home), timeout), (self.home, ob.BRIEF_TIMEOUT))
            if code == 0:
                self.jobs({"id": "b1", "name": "omher-brief", "script": ob.BRIEF_SCRIPT})
            return code, out
        return run

    # -- detection

    def test_no_slack_token_key_skips(self) -> None:
        self.env("DISCORD_BOT_TOKEN=x\n")
        self.assertEqual(self.plan()["reason"], "no_slack")

    def test_owner_from_a_one_id_allow_list(self) -> None:
        p = self.plan()
        self.assertEqual((p["state"], p["owner"]), ("install", "UOWNER1"))

    def test_owner_from_the_dm_majority_with_the_alias_dropped(self) -> None:
        self.env(f"export SLACK_BOT_TOKEN='{SECRET}'\nSLACK_ALLOWED_USERS=UA1,UB2\n")
        dm = lambda u, n: {"platform": "slack", "chat_type": "dm", "user_id": u, "user_name": n}  # noqa: E731
        self.sessions(dm("UA1", "Ann"), dm("UB2", "김희망 (Khope)"), dm("UB2", "김희망 (Khope)"),
                      {"platform": "slack", "chat_type": "group", "user_id": "UA1", "user_name": "Ann"},
                      {"platform": "slack", "chat_type": "group", "user_id": "UA1", "user_name": "Ann"},
                      {"platform": "discord", "chat_type": "dm", "user_id": "UA1"})
        before = (self.p / "state.db").stat().st_mtime_ns
        p = self.plan()
        self.assertEqual((p["state"], p["owner"], p["owner_name"]), ("install", "UB2", "김희망"))
        self.assertEqual((self.p / "state.db").stat().st_mtime_ns, before)

    def test_no_owner_skips(self) -> None:
        self.env(f"SLACK_BOT_TOKEN={SECRET}\n")
        self.assertEqual(self.plan()["reason"], "no_owner")

    def test_an_existing_or_other_briefing_skips(self) -> None:
        for job, reason in (({"id": "a", "name": "omher-brief"}, "exists"),
                            ({"id": "a", "name": "x", "script": ob.BRIEF_SCRIPT}, "exists"),
                            ({"id": "a", "name": "superagent-brief"}, "has_brief")):
            with self.subTest(job=job):
                self.jobs(job)
                self.assertEqual(self.plan()["reason"], reason)

    def test_optout_and_missing_collector_skip(self) -> None:
        self.assertEqual(self.plan({"kami"})["reason"], "optout")
        (self.p / "skills" / "operator" / "omh-automation-blueprint" / "toolkit" / "scripts" / "channel_watch.py").unlink()
        self.assertEqual(self.plan()["reason"], "no_collector")

    def test_collector_found_in_an_external_skill_dir(self) -> None:
        ext = self.root / "omh-skills"
        kit = ext / "omh-automation-blueprint" / "toolkit" / "scripts"
        kit.mkdir(parents=True)
        (kit / "channel_watch.py").write_text("# ext\n", encoding="utf-8")
        (self.p / "skills" / "operator" / "omh-automation-blueprint" / "toolkit" / "scripts" / "channel_watch.py").unlink()
        (self.p / "config.yaml").write_text(f"skills:\n  external_dirs:\n    - {ext.as_posix()}\n", encoding="utf-8")
        ob._YAML_CACHE.clear()
        self.assertEqual(Path(self.plan()["collector"]), kit / "channel_watch.py")

    def test_the_token_value_never_leaves_detection(self) -> None:
        self.assertNotIn(SECRET, json.dumps(ob._env_entries(self.p)))
        with self.assertLogs("omher.bridge", level="INFO") as logs:
            ob.log.info("probe")
            p = self.plan()
            ob.install_brief(self.p, self.home, "/bin/hermes", "kami", p, self.runner(code=1, out="boom"))
        self.assertNotIn(SECRET, json.dumps(p) + "\n".join(logs.output))

    # -- install

    def test_argv_is_exact(self) -> None:
        self.assertEqual(ob.brief_create_argv("/x/hermes", "kami"),
                         ["/x/hermes", "-p", "kami", "cron", "create", "--name", "omher-brief", "--script",
                          "channel_watch_omher-brief.py", "--deliver", "bot-chat:kami", "--continuity", "every 15m",
                          ob.BRIEF_PROMPT])
        for bad in ("Kami", "-p", "a b", "../x", ""):
            with self.assertRaises(ValueError):
                ob.brief_create_argv("/x/hermes", bad)

    def test_install_writes_two_files_and_is_idempotent(self) -> None:
        res = ob.install_brief(self.p, self.home, "/x/hermes", "kami", self.plan(), self.runner())
        self.assertTrue(res["ok"])
        script, cfg = self.p / "scripts" / ob.BRIEF_SCRIPT, self.p / "channel_watch" / "omher-brief.json"
        self.assertEqual(script.read_text(encoding="utf-8"), "# collector\n")
        self.assertEqual(json.loads(cfg.read_text(encoding="utf-8")),
                         {"name": "omher-brief", "platform": "slack", "mode": "brief", "owner": "UOWNER1",
                          "owner_name": "UOWNER1", "max_per_day": 6})
        if sys.platform != "win32":
            self.assertEqual((script.stat().st_mode & 0o777, cfg.stat().st_mode & 0o777), (0o600, 0o600))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.plan()["reason"], "exists")

    def test_a_failed_create_removes_what_it_wrote(self) -> None:
        res = ob.install_brief(self.p, self.home, "/x/hermes", "kami", self.plan(), self.runner(code=2, out="nope"))
        self.assertEqual(res["reason"], "hermes")
        self.assertFalse((self.p / "scripts" / ob.BRIEF_SCRIPT).exists())
        self.assertFalse((self.p / "channel_watch" / "omher-brief.json").exists())

    def test_an_existing_file_is_never_overwritten(self) -> None:
        (self.p / "scripts").mkdir()
        (self.p / "scripts" / ob.BRIEF_SCRIPT).write_text("mine\n", encoding="utf-8")
        res = ob.install_brief(self.p, self.home, "/x/hermes", "kami", self.plan(), self.runner())
        self.assertEqual(res["reason"], "exists")
        self.assertEqual((self.p / "scripts" / ob.BRIEF_SCRIPT).read_text(encoding="utf-8"), "mine\n")
        self.assertFalse((self.p / "channel_watch" / "omher-brief.json").exists())
        self.assertEqual(self.calls, [])

    def test_a_brief_job_reads_as_kind_brief(self) -> None:
        ob.install_brief(self.p, self.home, "/x/hermes", "kami", self.plan(), self.runner())
        rows = ob.read_automations(self.p)
        self.assertEqual(rows[0]["watch"]["kind"], "brief")

    # -- the bridge

    def test_bridge_sets_up_once_after_the_first_bots_list_and_honours_remove(self) -> None:
        async def go():
            bridge = ob.Bridge(token="t", hermes_home=self.home, brief_setup=True, omher_home=self.omher,
                               brief_runner=self.runner())
            events = []

            async def emit(event, bot, **f):
                events.append((event, bot, f))
            bridge.emit = emit
            orig = ob.hermes_path
            ob.hermes_path = lambda *a, **k: "/x/hermes"
            try:
                done = await bridge.setup_briefs()
                again = await bridge.setup_briefs()
            finally:
                ob.hermes_path = orig
            return done, again, events
        done, again, events = asyncio.run(go())
        self.assertEqual(done, [{"bot": "kami", "owner_name": "UOWNER1"}])
        self.assertEqual(again, [])
        self.assertEqual(events, [("brief.ready", "kami", {"owner_name": "UOWNER1"})])
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.omher / "brief-optout.json").exists())
        ob.add_brief_optout(self.omher, "kami")
        self.assertEqual(ob.read_brief_optout(self.omher), {"kami"})
        self.jobs()
        self.assertEqual(self.plan(ob.read_brief_optout(self.omher))["reason"], "optout")

    def test_remove_of_the_brief_job_opts_the_bot_out(self) -> None:
        self.jobs({"id": "b1", "name": "omher-brief", "script": ob.BRIEF_SCRIPT, "enabled": True})

        async def go():
            bridge = ob.Bridge(token="t", hermes_home=self.home, omher_home=self.omher)
            sent = []

            async def conn(name):
                return name

            async def cron(c, action, **params):
                sent.append((action, params))
                return {"success": True}

            async def poll():
                return None
            bridge._conn, bridge._cron, bridge.poll_routines_once = conn, cron, poll
            await bridge.op_automations_remove({"bot": "kami", "job": "b1"})
            return sent
        self.assertEqual(asyncio.run(go()), [("remove", {"name": "b1"})])
        self.assertEqual(ob.read_brief_optout(self.omher), {"kami"})


class BriefPrompt(unittest.TestCase):
    """What the briefing says first (khope, 2026-11-22: a brief that opened with what the bot did or could not do left
    him guessing what it was about)."""

    def test_it_opens_with_a_greeting_and_what_it_is_about(self) -> None:
        p = ob.BRIEF_PROMPT
        self.assertIn("open with a short greeting", p)
        self.assertIn("안녕하세요.", p)
        self.assertIn("which channel or thread it is about, what happened and whether they need to do anything", p)
        self.assertIn("never open with what you did or could not do", p)

    def test_the_skill_reference_shows_the_same_prompt(self) -> None:
        # the automation-blueprint reference quotes the prompt omher installs; the two must not drift apart
        root = HERE.parents[3]
        flat = lambda s: " ".join(s.split())  # noqa: E731
        for rel in ("src/skills/render.py", "skills/omh-automation-blueprint/references/channel-watch.md"):
            text = (root / rel).read_text(encoding="utf-8")
            start = text.index("```text\nYou brief the person this bot works for.") + len("```text\n")
            quoted = text[start:text.index("\n```", start)]
            with self.subTest(rel=rel):
                self.assertEqual(flat(quoted), flat(ob.BRIEF_PROMPT))


if __name__ == "__main__":
    unittest.main()
