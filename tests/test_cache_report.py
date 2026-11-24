from __future__ import annotations

import io
import json
import sqlite3
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.commands.main import main as omh_main  # noqa: E402
from omh.hud import build_hud_payload  # noqa: E402
from omh.maintenance import cache_report  # noqa: E402
from omh.maintenance.cache_report import (  # noqa: E402
    build_cache_report,
    job_key,
    main_read_share,
    redact_line,
    render_cache_report,
)
from omh.paths import OmhPaths  # noqa: E402
from omh.surfaces.hud import _cache_field  # noqa: E402

NOW = 1_800_000_000.0
H = 3600.0
PROMPT_A = "You are Kami.\nMEMORY (your personal notes) [92% — 4,067/4,400 chars]\nSkills: a, b\n"
PROMPT_B = "You are Kami.\nMEMORY (your personal notes) [95% — 4,194/4,400 chars]\nSkills: a, b\n"


def _state_db(home: Path) -> Path:
    """A synthetic Hermes state.db: the columns the report reads plus one it must ignore."""
    home.mkdir(parents=True, exist_ok=True)
    path = home / "state.db"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, title TEXT, started_at REAL, last_activity_at REAL,
            message_count INTEGER, input_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
            system_prompt_hash TEXT, system_prompt TEXT, parent_session_id TEXT, unrelated TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL);
        CREATE TABLE system_prompts (hash TEXT PRIMARY KEY, prompt TEXT);
        """
    )
    db.executemany("INSERT INTO system_prompts VALUES (?, ?)", [("aaaa1111", PROMPT_A), ("bbbb2222", PROMPT_B)])
    sessions = [
        # brief: cold first run (write 100), +30m same hash (write 120: prefix 100 other + 20 other),
        # +40m changed hash (write 150: churn 100 + other 50), +5h cold (write 100).
        ("c1", "cron", "brief · run 1", NOW - 20 * H, 3, 0, 900, 100, "aaaa1111"),
        ("c2", "cron", "brief · run 2", NOW - 20 * H + 1800, 3, 0, 900, 120, "aaaa1111"),
        ("c3", "cron", "brief · run 3", NOW - 20 * H + 4200, 3, 0, 900, 150, "bbbb2222"),
        ("c4", "cron", "brief · run 4", NOW - 15 * H + 4200, 3, 0, 900, 100, "bbbb2222"),
        # script-gated runs: no model call, no title separator.
        ("c5", "cron", "gate check", NOW - 10 * H, 0, 0, 0, 0, None),
        ("c6", "cron", None, NOW - 9 * H, 0, 0, 0, 0, None),
        # outside the 7d window: must not count.
        ("c0", "cron", "brief · old", NOW - 8 * 86400, 3, 0, 9999, 9999, "aaaa1111"),
        ("d1", "discord", "chat", NOW - 2 * H, 6, 10, 900, 90, "x"),
        ("d2", "discord", "old chat", NOW - 30 * H, 6, 100, 0, 0, "x"),
        ("s1", "subagent", "child", NOW - 2 * H, 4, 50, 50, 0, "y"),
    ]
    db.executemany(
        """INSERT INTO sessions (id, source, title, started_at, last_activity_at, message_count, input_tokens,
               cache_read_tokens, cache_write_tokens, system_prompt_hash, parent_session_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(*row[:4], row[3], *row[4:], "d1" if row[0] == "s1" else None) for row in sessions],
    )
    base = NOW - 2 * H
    messages = [
        ("d1", "user", base), ("d1", "assistant", base + 10), ("d1", "user", base + 60),  # <5m
        ("d1", "user", base + 60 + 600),  # 5-60m
        ("d1", "user", base + 660 + 2 * H),  # >1h
        ("s1", "user", base), ("s1", "user", base + 5),  # machine-paced: ignored
    ]
    db.executemany("INSERT INTO messages (session_id, role, timestamp) VALUES (?, ?, ?)", messages)
    db.commit()
    db.close()
    return path


class CacheReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / ".hermes"
        self.db_path = _state_db(self.home)

    def test_job_key_matches_the_cron_cache_scripts(self) -> None:
        self.assertEqual(job_key("omher-brief · 2026-11-24 09:26"), "omher-brief")
        self.assertEqual(job_key("gate check"), "?")
        self.assertEqual(job_key(None), "?")

    def test_cron_totals_and_per_job_rows(self) -> None:
        cron = build_cache_report(self.home, days=7, now=NOW)["cron"]
        self.assertEqual((cron["sessions"], cron["model_runs"], cron["write_tokens"]), (6, 4, 470))
        brief = next(job for job in cron["jobs"] if job["job"] == "brief")
        self.assertEqual((brief["runs"], brief["model_runs"], brief["write_tokens"]), (4, 4, 470))
        self.assertEqual(brief["prompt_hashes"], 2)
        self.assertEqual(brief["prefix_estimate"], 100)
        self.assertEqual(brief["median_gap_minutes"], 40.0)  # gaps 30m, 40m, 5h
        gated = next(job for job in cron["jobs"] if job["job"] == "?")
        self.assertEqual((gated["runs"], gated["model_runs"], gated["write_tokens"]), (2, 0, 0))

    def test_write_split_cold_churn_other(self) -> None:
        split = build_cache_report(self.home, days=7, now=NOW)["cron"]["split"]
        self.assertEqual({name: split[name]["tokens"] for name in split}, {"cold": 200, "churn": 100, "other": 170})
        self.assertAlmostEqual(split["cold"]["share"], round(200 / 470, 4))

    def test_top_churn_names_the_first_differing_prompt_line(self) -> None:
        churn = build_cache_report(self.home, days=7, now=NOW)["cron"]["top_churn"]
        self.assertEqual(churn["job"], "brief")
        self.assertEqual((churn["from_hash"], churn["to_hash"], churn["line"]), ("aaaa1111", "bbbb2222", 2))
        self.assertIn("92%", churn["before"])
        self.assertIn("95%", churn["after"])

    def test_read_share_per_source_inside_the_window(self) -> None:
        sources = {item["source"]: item for item in build_cache_report(self.home, days=7, now=NOW)["sources"]}
        self.assertEqual(sources["discord"]["sessions"], 2)
        self.assertEqual(sources["discord"]["read_share"], round(900 / (110 + 900 + 90), 4))
        self.assertTrue(sources["discord"]["human"])
        self.assertFalse(sources["cron"]["human"])
        self.assertEqual(sources["cron"]["read_share"], round(3600 / (3600 + 470), 4))

    def test_idle_gaps_count_only_human_user_messages(self) -> None:
        gaps = build_cache_report(self.home, days=7, now=NOW)["idle_gaps"]
        self.assertEqual(gaps["buckets"], {"<5m": 1, "5-60m": 1, ">1h": 1})

    def test_suggestions_follow_the_split_order(self) -> None:
        report = build_cache_report(self.home, days=7, now=NOW)
        self.assertEqual(len(report["suggestions"]), 3)
        self.assertIn("cold", report["suggestions"][0])
        self.assertIn("system prompt changed", report["suggestions"][2])
        self.assertEqual(
            cache_report.suggestions({n: {"tokens": 0, "share": None} for n in ("cold", "churn", "other")}),
            ["No cron cache writes in this window; nothing to change."],
        )

    def test_redact_line_masks_secrets_and_caps_length(self) -> None:
        self.assertNotIn("sk-abcdefghijkl", redact_line("key sk-abcdefghijklmnop here"))
        self.assertEqual(len(redact_line("x " * 400)), 160)

    def test_database_opened_read_only(self) -> None:
        before = self.db_path.stat().st_mtime_ns
        real_connect = sqlite3.connect
        seen: list[str] = []

        def spy(target, *args, **kwargs):
            seen.append(str(target))
            return real_connect(target, *args, **kwargs)

        with mock.patch.object(cache_report.sqlite3, "connect", spy):
            build_cache_report(self.home, days=7, now=NOW)
        self.assertTrue(seen and all(target.endswith("?mode=ro") for target in seen))
        self.assertEqual(self.db_path.stat().st_mtime_ns, before)

    def test_cli_prints_text_and_json(self) -> None:
        with mock.patch.dict("os.environ", {"HERMES_HOME": str(self.home)}):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(omh_main(["cache", "--days", "3650"]), 0)
            self.assertIn("Write split:", out.getvalue())
            self.assertIn("Suggestions:", out.getvalue())
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(omh_main(["cache", "--json"]), 0)
            self.assertIn("cron", json.loads(out.getvalue()))

    def test_cli_reports_a_missing_state_db(self) -> None:
        with mock.patch.dict("os.environ", {"HERMES_HOME": str(Path(self._tmp.name) / "none")}):
            self.assertEqual(omh_main(["cache"]), 1)

    def test_render_explains_the_split(self) -> None:
        text = render_cache_report(build_cache_report(self.home, days=7, now=NOW))
        self.assertIn("cold 200", text)
        self.assertIn("churn = prefix write", text)
        self.assertIn("first differing line 2", text)


class HudCacheFieldTests(unittest.TestCase):
    def test_main_read_share_counts_parentless_human_sessions_of_the_last_day(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / ".hermes"
            _state_db(home)
            field = main_read_share(home, hours=24, now=NOW)
        # d1 only: d2 is 30h old, s1 is a subagent with a parent, cron is machine-paced.
        self.assertEqual(field, {"window_hours": 24, "sessions": 1, "read_share": round(900 / 1000, 4)})

    def test_hud_payload_carries_the_cache_field(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _state_db(root / ".hermes")
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            with mock.patch.object(cache_report.time, "time", return_value=NOW):
                payload = build_hud_payload(paths, delegation_graph=False)
        self.assertEqual(payload["cache"]["read_share"], 0.9)

    def test_hud_payload_skips_the_field_on_any_error(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir()
            (root / ".hermes" / "state.db").write_bytes(b"not a database")
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            payload = build_hud_payload(paths, delegation_graph=False)
        self.assertNotIn("cache", payload)
        self.assertIn("display", payload)

    def _hud_text(self, root: Path) -> str:
        out = io.StringIO()
        argv = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"), "hud"]
        with mock.patch.object(cache_report.time, "time", return_value=NOW), redirect_stdout(out):
            self.assertEqual(omh_main(argv), 0)
        return out.getvalue()

    def test_plain_hud_text_shows_the_cache_segment(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _state_db(root / ".hermes")
            line = self._hud_text(root).splitlines()[0]
        self.assertIn(" | cache:90%", line)

    def test_plain_hud_text_leaves_the_segment_out_without_the_field(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir()
            text = self._hud_text(root)
        self.assertTrue(text.startswith("[omh] v"))
        self.assertNotIn("cache:", text)

    def test_hud_cache_read_gives_up_at_once_on_a_locked_state_db(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = _state_db(root / ".hermes")
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            writer = sqlite3.connect(db_path, isolation_level=None)
            # Close inside the with-block: Windows cannot delete state.db while this handle is open, so an
            # addCleanup close (run after TemporaryDirectory.__exit__) fails the cleanup with WinError 32.
            try:
                writer.execute("BEGIN EXCLUSIVE")
                took = []
                for _ in range(3):
                    start = time.perf_counter()
                    self.assertIsNone(_cache_field(paths))
                    took.append(time.perf_counter() - start)
                payload = build_hud_payload(paths, delegation_graph=False)
                writer.execute("ROLLBACK")
            finally:
                writer.close()
        self.assertLess(sorted(took)[1], 0.2)
        self.assertNotIn("cache", payload)
        self.assertNotIn("cache:", payload["display"]["line"])


if __name__ == "__main__":
    unittest.main()
