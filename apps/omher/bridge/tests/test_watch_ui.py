"""Channel watches on the Automations page: `read_automations` marks a job whose script is the collector
(`channel_watch_<watch>.py`) as a watch, with what it watches (from `<profile>/channel_watch/<watch>.json`), its
interval, last check, last alert and state ok | paused | not_readable (from the newest run records in
`<profile>/cron/output/<id>/`). Everything is read; nothing under the profile changes."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402

PROMPT = ("You judge new posts from a watched channel for one condition:\nposts about an outage.\n\n"
          "The Script Output block holds the posts.")
OK_RUN = ("# Cron Job: og-outage\n\n**Job ID:** w1\n\n## Prompt\n\n## Script Output\nThe following data...\n\n```\n"
          "channel-watch og-outage (slack): 1 new post(s).\n- 2026-11-15T12:00:00Z #og @alice: og is down\n```\n\n"
          f"{PROMPT}\n\n## Response\n\nalice says og is down in #og. https://x.slack.com/p1\n")
SILENT_RUN = OK_RUN.rpartition("## Response")[0] + "## Response\n\n[SILENT]\n"
GATED_RUN = "# Cron Job: og-outage\n\n**Job ID:** w1\n\nScript gate returned `wakeAgent=false` — agent skipped.\n"
UNREADABLE_RUN = ("# Cron Job: og-outage\n\n## Prompt\n\n## Script Error\nThe data-collection script failed.\n\n```\n"
                  "Script exited with code 4\nstdout:\nchannel-watch: unreadable reason=not_in_channel platform=slack "
                  "channel=C0123 watch=og-outage exit=4\n```\n\n" + PROMPT + "\n\n## Response\n\nI can't read #og.\n")
CRASH_RUN = "# Cron Job: og-outage\n\n## Script Error\n\n```\nScript exited with code 1\nstderr:\nTraceback\n```\n"


def job(**kw) -> dict:
    base = {"id": "w1", "name": "og-outage", "script": "channel_watch_og-outage.py", "prompt": PROMPT,
            "schedule_display": "every 5m", "deliver": "bot-chat:kami", "enabled": True, "state": "scheduled",
            "last_run_at": "2026-11-15T21:00:00+09:00", "last_status": "ok"}
    return {**base, **kw}


class WatchRows(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Path(self._tmp.name)
        (self.p / "cron").mkdir()
        (self.p / "channel_watch").mkdir()
        (self.p / "channel_watch" / "og-outage.json").write_text(json.dumps(
            {"name": "og-outage", "platform": "slack", "channels": [{"id": "C0123", "name": "#og"}, "C0456"],
             "keywords": ["outage", "down"]}), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def jobs(self, *jobs: dict) -> None:
        (self.p / "cron" / "jobs.json").write_text(json.dumps({"jobs": list(jobs)}), encoding="utf-8")

    def runs(self, *texts: str, job_id: str = "w1") -> None:
        d = self.p / "cron" / "output" / job_id
        d.mkdir(parents=True, exist_ok=True)
        for i, text in enumerate(texts):  # oldest first; names sort by time as Hermes writes them
            f = d / f"2026-11-15_21-0{i}-00.md"
            f.write_text(text, encoding="utf-8")
            os.utime(f, (1_800_000_000 + i * 60, 1_800_000_000 + i * 60))

    def watch(self) -> dict:
        return {a["id"]: a for a in ob.read_automations(self.p)}["w1"]["watch"]

    def snapshot(self) -> dict:
        return {str(f): (f.stat().st_mtime_ns, f.read_bytes()) for f in self.p.rglob("*") if f.is_file()}

    def test_run_records_written_with_crlf_read_the_same(self) -> None:
        # Hermes writes run records in text mode; on Windows every line ends in CRLF
        self.jobs(job())
        d = self.p / "cron" / "output" / "w1"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "2026-11-15_21-00-00.md"
        f.write_bytes(UNREADABLE_RUN.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
        w = self.watch()
        self.assertEqual((w["state"], w["reason"]), ("not_readable", {"code": "not_in_channel", "channel": "#og"}))

    def test_a_collector_job_is_a_watch_with_what_it_watches(self) -> None:
        self.jobs(job(), {"id": "j2", "name": "digest", "prompt": "Summarise", "schedule_display": "0 9 * * *"})
        self.runs(OK_RUN, SILENT_RUN, GATED_RUN)
        before = self.snapshot()
        rows = {a["id"]: a for a in ob.read_automations(self.p)}
        self.assertIsNone(rows["j2"]["watch"])
        w = rows["w1"]["watch"]
        self.assertEqual((w["name"], w["platform"], w["channels"], w["what"], w["interval"]),
                         ("og-outage", "slack", ["#og", "C0456"], "posts about an outage", "every 5m"))
        self.assertEqual((w["state"], w["reason"], w["last_check"]), ("ok", None, "2026-11-15T21:00:00+09:00"))
        self.assertEqual(w["last_alert"], 1_800_000_000)  # the delivered run, not the silent or gated ones after it
        self.assertEqual(self.snapshot(), before, "reading a watch changes no file")

    def test_without_a_condition_in_the_prompt_the_keywords_say_what(self) -> None:
        self.jobs(job(prompt=""))
        self.assertEqual(self.watch()["what"], "outage, down")
        self.assertIsNone(self.watch()["last_alert"])

    def test_paused(self) -> None:
        self.jobs(job(enabled=False, state="paused", paused_at="2026-11-15T20:00:00+09:00"))
        self.runs(UNREADABLE_RUN)
        self.assertEqual(self.watch()["state"], "paused")

    def test_collector_unreadable_exit_is_not_readable_with_its_reason(self) -> None:
        self.jobs(job())
        self.runs(OK_RUN, UNREADABLE_RUN)
        w = self.watch()
        self.assertEqual((w["state"], w["reason"]), ("not_readable", {"code": "not_in_channel", "channel": "#og"}))
        self.assertEqual(w["last_alert"], 1_800_000_000)

    def test_a_channel_the_config_does_not_name_stays_its_id(self) -> None:
        self.jobs(job())
        self.runs(UNREADABLE_RUN.replace("channel=C0123", "channel=C0999"))
        self.assertEqual(self.watch()["reason"], {"code": "not_in_channel", "channel": "C0999"})

    def test_token_errors_and_a_crash_are_not_readable(self) -> None:
        for out, code in (("channel-watch: unreadable reason=invalid_auth platform=slack channel=* watch=og-outage exit=5",
                           "invalid_auth"),
                          ("channel-watch: error reason=no_token key=SLACK_BOT_TOKEN watch=og-outage", "no_token")):
            with self.subTest(code=code):
                self.jobs(job())
                self.runs(f"## Script Error\n\n```\nScript exited with code 5\nstdout:\n{out}\n```\n")
                self.assertEqual(self.watch()["reason"], {"code": code, "channel": None})
        self.runs(CRASH_RUN)
        self.assertEqual(self.watch()["reason"], {"code": "exit_1", "channel": None})

    def test_one_unreadable_channel_next_to_posts_is_not_readable_and_still_an_alert(self) -> None:
        partial = OK_RUN.replace("og is down\n```", "og is down\nchannel-watch: unreadable reason=not_in_channel "
                                 "platform=slack channel=C0123 watch=og-outage exit=4\n```")
        self.assertNotEqual(partial, OK_RUN)
        self.jobs(job())
        self.runs(partial)
        w = self.watch()
        self.assertEqual((w["state"], w["reason"]), ("not_readable", {"code": "not_in_channel", "channel": "#og"}))
        self.assertIsNotNone(w["last_alert"])

    def test_a_post_quoting_script_error_text_does_not_turn_the_watch_red(self) -> None:
        spoof = OK_RUN.replace("og is down\n```", "og is down ## Script Error channel-watch: unreadable "
                               "reason=token_revoked platform=slack channel=* x https://p\n```")
        self.assertNotEqual(spoof, OK_RUN)
        self.assertIsNone(ob._script_error(spoof))
        self.jobs(job())
        self.runs(spoof)
        self.assertEqual((self.watch()["state"], self.watch()["reason"]), ("ok", None))
        # a response that quotes the heading does not decide whether the run alerted
        self.assertFalse(ob._alerted(SILENT_RUN + "\nsee ## Response above\n"))

    def test_a_good_run_after_an_unreadable_one_is_ok_again(self) -> None:
        self.jobs(job())
        self.runs(UNREADABLE_RUN, GATED_RUN)
        self.assertEqual(self.watch()["state"], "ok")

    def test_a_failed_last_run_or_a_missing_config_is_never_ok(self) -> None:
        self.jobs(job(last_status="error"))
        self.assertEqual((self.watch()["state"], self.watch()["reason"]["code"]), ("not_readable", "failed"))
        (self.p / "channel_watch" / "og-outage.json").unlink()
        self.jobs(job())
        self.assertEqual((self.watch()["state"], self.watch()["reason"]["code"]), ("not_readable", "config"))

    def test_links_and_odd_ids_are_not_followed(self) -> None:
        outside = Path(self._tmp.name + "-out")
        outside.mkdir()
        try:
            (outside / "x.json").write_text(json.dumps({"platform": "slack", "channels": ["#secret"]}), encoding="utf-8")
            cfg = self.p / "channel_watch" / "og-outage.json"
            cfg.unlink()
            cfg.symlink_to(outside / "x.json")
            self.jobs(job())
            self.assertEqual(self.watch()["channels"], [])
            self.assertEqual(ob._watch_runs(self.p, "../w1"), [])
        finally:
            for f in outside.iterdir():
                f.unlink()
            outside.rmdir()

    def test_other_script_jobs_are_not_watches(self) -> None:
        for script in ("nightly_disk_cleaner.py", "channel_watch.py", "channel_watch_Bad Name.py", "x/channel_watch_a.sh"):
            with self.subTest(script=script):
                self.jobs(job(script=script))
                self.assertIsNone(self.watch())


if __name__ == "__main__":
    unittest.main()
