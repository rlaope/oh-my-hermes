"""Contracts for effective approval-bypass (yolo) observation.

The Shift+Tab yolo toggle lives only in the host process's
``tools.approval`` session state, so the HUD reports what the plugin's
``pre_llm_call`` and ``pre_tool_call`` hooks last observed in-process.
The ledger stores one boolean and a timestamp — never a session key,
command, or prompt — and an unobserved or stale ledger projects idle so
the widget renders nothing rather than a guess.
"""

import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

from omh.plugin_bundle.omh.approval_bypass import (
    APPROVAL_BYPASS_FRESH_SECONDS,
    APPROVAL_BYPASS_REFRESH_SECONDS,
    approval_bypass_path,
    effective_approval_bypass,
    latest_approval_bypass,
    record_approval_bypass,
)
from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

NOW = 1_787_040_000.0


class ApprovalBypassLedgerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = str(Path(self._tmp.name) / "omh")

    def _install_host_approval(self, enabled: bool) -> None:
        previous = {name: sys.modules.get(name) for name in ("tools", "tools.approval")}

        def restore():
            for name, module in previous.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

        self.addCleanup(restore)
        tools_module = types.ModuleType("tools")
        approval_module = types.ModuleType("tools.approval")
        approval_module.is_approval_bypass_active = lambda: enabled
        tools_module.approval = approval_module
        sys.modules["tools"] = tools_module
        sys.modules["tools.approval"] = approval_module

    def test_an_enabled_observation_projects_on(self):
        self._install_host_approval(True)
        record_approval_bypass(omh_home=self.home, now=NOW)
        state = latest_approval_bypass(self.home, now=NOW + 5)
        self.assertEqual(state["status"], "observed")
        self.assertTrue(state["enabled"])
        self.assertIn("never approval", state["claim_boundary"])

    def test_a_disabled_observation_projects_off(self):
        self._install_host_approval(False)
        record_approval_bypass(omh_home=self.home, now=NOW)
        state = latest_approval_bypass(self.home, now=NOW + 5)
        self.assertEqual(state["status"], "observed")
        self.assertFalse(state["enabled"])

    def test_without_the_host_surface_nothing_is_recorded(self):
        # No tools.approval in this process: the hook records nothing rather
        # than a guess, and the projection stays idle.
        record_approval_bypass(omh_home=self.home, now=NOW)
        self.assertFalse(approval_bypass_path(self.home).exists())
        self.assertEqual(latest_approval_bypass(self.home, now=NOW)["status"], "idle")

    def test_a_stale_observation_expires_to_idle(self):
        # A host restart resets the in-memory flag without any hook firing,
        # so an old observation must stop claiming a state no process holds.
        self._install_host_approval(True)
        record_approval_bypass(omh_home=self.home, now=NOW)
        fresh = latest_approval_bypass(self.home, now=NOW + APPROVAL_BYPASS_FRESH_SECONDS - 1)
        self.assertEqual(fresh["status"], "observed")
        stale = latest_approval_bypass(self.home, now=NOW + APPROVAL_BYPASS_FRESH_SECONDS + 1)
        self.assertEqual(stale["status"], "idle")

    def test_the_ledger_stores_metadata_only(self):
        import json

        self._install_host_approval(True)
        record_approval_bypass(omh_home=self.home, now=NOW)
        record = json.loads(approval_bypass_path(self.home).read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(record), ["claim_boundary", "enabled", "observed_ts", "schema_version"]
        )

    def test_the_hud_payload_carries_the_state(self):
        self._install_host_approval(True)
        record_approval_bypass(omh_home=self.home, now=time.time())
        hermes = str(Path(self._tmp.name) / "hermes")
        payload = read_omh_hud(self.home, hermes)
        self.assertEqual(payload["yolo"]["status"], "observed")
        self.assertTrue(payload["yolo"]["enabled"])
        self.assertEqual(payload["privacy"], "metadata_only")

    def test_both_hooks_tick_the_ledger(self):
        from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
        from omh.plugin_bundle.omh.hooks.tool_hooks import pre_tool_call

        self._install_host_approval(True)
        pre_tool_call(tool_name="terminal", omh_home=self.home)
        self.assertTrue(approval_bypass_path(self.home).exists())
        approval_bypass_path(self.home).unlink()
        pre_llm_call(user_message="hello", omh_home=self.home, include_omh_awareness=False)
        self.assertTrue(approval_bypass_path(self.home).exists())


class ApprovalBypassWriteEconomyTest(unittest.TestCase):
    """An unchanged observation costs no write.

    The hooks observe this flag twice per tool call and once per turn, and
    it changes when a person presses Shift+Tab -- so nearly every one of
    those locks, temp files and renames wrote bytes identical to the ones
    already on disk. The skip is safe only because the timestamp is
    load-bearing in exactly one place, `latest_approval_bypass`'s
    `APPROVAL_BYPASS_FRESH_SECONDS` cut, and a bounded refresh keeps that
    cut answerable. No other reader reads the stamp: the widget renders
    `status` and `enabled`, and the permission rehearsal reads the same two.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = str(Path(self._tmp.name) / "omh")
        self.host_enabled = True
        previous = {name: sys.modules.get(name) for name in ("tools", "tools.approval")}

        def restore():
            for name, module in previous.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

        self.addCleanup(restore)
        tools_module = types.ModuleType("tools")
        approval_module = types.ModuleType("tools.approval")
        approval_module.is_approval_bypass_active = lambda: self.host_enabled
        tools_module.approval = approval_module
        sys.modules["tools"] = tools_module
        sys.modules["tools.approval"] = approval_module

    def _generation(self):
        """Something that changes on a write and not otherwise."""
        path = approval_bypass_path(self.home)
        stat = path.stat()
        return (stat.st_ino, stat.st_size, path.read_bytes())

    def test_repeated_identical_observations_produce_one_write(self):
        record_approval_bypass(omh_home=self.home, now=NOW)
        first = self._generation()
        for offset in range(1, 200):
            record_approval_bypass(omh_home=self.home, now=NOW + offset)
        self.assertEqual(self._generation(), first)
        # And the state it is still serving is the right one.
        self.assertTrue(latest_approval_bypass(self.home, now=NOW + 199)["enabled"])

    def test_a_changed_value_writes_immediately(self):
        record_approval_bypass(omh_home=self.home, now=NOW)
        first = self._generation()
        self.host_enabled = False
        record_approval_bypass(omh_home=self.home, now=NOW + 1)
        self.assertNotEqual(self._generation(), first)
        self.assertFalse(latest_approval_bypass(self.home, now=NOW + 2)["enabled"])

    def test_an_unchanged_value_is_refreshed_before_it_can_expire(self):
        record_approval_bypass(omh_home=self.home, now=NOW)
        first = self._generation()
        record_approval_bypass(omh_home=self.home, now=NOW + APPROVAL_BYPASS_REFRESH_SECONDS - 1)
        self.assertEqual(self._generation(), first)
        record_approval_bypass(omh_home=self.home, now=NOW + APPROVAL_BYPASS_REFRESH_SECONDS + 1)
        self.assertNotEqual(self._generation(), first)
        # The whole point of the refresh: the record can never age into the
        # staleness cut while the hooks are still observing it.
        self.assertLess(APPROVAL_BYPASS_REFRESH_SECONDS, APPROVAL_BYPASS_FRESH_SECONDS)

    def test_a_deleted_or_corrupt_record_is_rewritten(self):
        record_approval_bypass(omh_home=self.home, now=NOW)
        approval_bypass_path(self.home).unlink()
        record_approval_bypass(omh_home=self.home, now=NOW + 1)
        self.assertTrue(approval_bypass_path(self.home).exists())
        approval_bypass_path(self.home).write_text("{not json", encoding="utf-8")
        record_approval_bypass(omh_home=self.home, now=NOW + 2)
        self.assertEqual(latest_approval_bypass(self.home, now=NOW + 3)["status"], "observed")

    def test_a_clock_that_moved_backwards_does_not_freeze_the_record(self):
        record_approval_bypass(omh_home=self.home, now=NOW)
        first = self._generation()
        record_approval_bypass(omh_home=self.home, now=NOW - 60)
        self.assertNotEqual(self._generation(), first)


if __name__ == "__main__":
    unittest.main()


class HostStateYoloTest(unittest.TestCase):
    """The HUD reads the host's persisted /yolo surfaces in real time.

    A host that persists the toggle writes the session row's
    model_config.yolo_mode (the classic CLI does; the Modern TUI gains the
    same persist upstream), so the reader projects that row for the most
    recently active LIVE TUI session — scoped by source, liveness, and the
    ledger's freshness bound so a foreign or dead row can never answer for
    the session a widget is rendering ("yolomode onoff 실시간 반영이 안됨").
    The hook ledger answers whenever no persisted surface speaks.
    """

    def setUp(self):
        import sqlite3

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.omh_home = str(Path(self._tmp.name) / "omh")
        self.hermes_home = Path(self._tmp.name) / "hermes"
        self.hermes_home.mkdir()
        self._sqlite3 = sqlite3

    def _build_db(self, rows):
        """rows: (id, config, activity, source='tui', ended_at=None, archived=0, hidden=0)."""
        connection = self._sqlite3.connect(self.hermes_home / "state.db")
        connection.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, source TEXT, model TEXT,
                model_config TEXT, started_at REAL NOT NULL,
                last_activity_at REAL, ended_at REAL,
                archived INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0
            );
            """
        )
        import json as json_module

        for row in rows:
            session_id, config, activity = row[0], row[1], row[2]
            source = row[3] if len(row) > 3 else "tui"
            ended_at = row[4] if len(row) > 4 else None
            raw = (
                config
                if isinstance(config, (str, int, type(None)))
                else json_module.dumps(config)
            )
            connection.execute(
                "INSERT INTO sessions (id, source, model, model_config, started_at,"
                " last_activity_at, ended_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, source, "gpt-5.6-sol", raw, activity - 100, activity, ended_at),
            )
        connection.commit()
        connection.close()

    def _write_ledger(self, enabled: bool, *, observed_ts: float) -> None:
        approval_bypass_path(self.omh_home).parent.mkdir(parents=True, exist_ok=True)
        approval_bypass_path(self.omh_home).write_text(
            '{"schema_version": "omh_approval_bypass/v1", '
            f'"enabled": {"true" if enabled else "false"}, '
            f'"observed_ts": {observed_ts}}}',
            encoding="utf-8",
        )

    def _effective(self):
        return effective_approval_bypass(self.omh_home, str(self.hermes_home), now=NOW)

    def test_a_persisted_toggle_projects_on_without_any_hook_observation(self):
        self._build_db([("s1", {"yolo_mode": True}, NOW - 60)])
        state = self._effective()
        self.assertEqual(state["status"], "observed")
        self.assertTrue(state["enabled"])
        self.assertEqual(state["source"], "host_state")

    def test_a_toggle_off_beats_a_stale_hook_observation(self):
        # The reported bug: the ledger observed ON at the last turn, the
        # user toggled OFF between turns, and the HUD kept saying on.
        self._write_ledger(True, observed_ts=NOW - 30)
        self._build_db([("s1", {"yolo_mode": False}, NOW - 60)])
        state = self._effective()
        self.assertEqual(state["status"], "observed")
        self.assertFalse(state["enabled"])

    def test_only_a_live_tui_row_may_answer(self):
        # A cron --yolo run and a closed TUI must never flip the display of
        # the session a widget is actually rendering.
        self._build_db(
            [
                ("cron", {"yolo_mode": True}, NOW - 5, "tool"),
                ("closed", {"yolo_mode": True}, NOW - 10, "tui", NOW - 9),
                ("cli", {"yolo_mode": True}, NOW - 15, "cli"),
                ("live", {"yolo_mode": False}, NOW - 60),
            ]
        )
        state = self._effective()
        self.assertFalse(state["enabled"])
        self.assertEqual(state["source"], "host_state")

    def test_an_old_stamped_row_never_dominates_the_ledger(self):
        # The freshest live TUI row is beyond the freshness bound: a stamp
        # from a long-dead session says nothing about today.
        self._build_db([("old", {"yolo_mode": True}, NOW - 7 * 3600)])
        self._write_ledger(False, observed_ts=NOW - 30)
        state = self._effective()
        self.assertFalse(state["enabled"])
        self.assertNotIn("source", state)

    def test_a_child_row_is_skipped_and_the_next_live_row_answers(self):
        self._build_db(
            [
                ("child", {"yolo_mode": True, "_delegate_from": "main"}, NOW - 5),
                ("main", {"yolo_mode": False}, NOW - 60),
            ]
        )
        self.assertFalse(self._effective()["enabled"])

    def test_a_crowd_of_live_children_cannot_push_the_main_row_out(self):
        # Delegate children are source='tui' too; the WHERE-level skip keeps
        # them from consuming the row limit ahead of the eligible session.
        rows = [
            (f"child-{index}", {"yolo_mode": True, "_delegate_from": "main"}, NOW - index)
            for index in range(40)
        ]
        rows.append(("main", {"yolo_mode": False}, NOW - 300))
        self._build_db(rows)
        state = self._effective()
        self.assertFalse(state["enabled"])
        self.assertEqual(state["source"], "host_state")

    def test_an_undecodable_row_is_skipped_and_the_next_row_answers(self):
        # A BLOB model_config exercises the decode guard; the eligible row
        # below it still answers instead of the whole read failing.
        import sqlite3

        self._build_db([("main", {"yolo_mode": False}, NOW - 60)])
        connection = self._sqlite3.connect(self.hermes_home / "state.db")
        connection.execute(
            "INSERT INTO sessions (id, source, model, model_config, started_at,"
            " last_activity_at) VALUES (?, 'tui', 'm', ?, ?, ?)",
            ("blob", sqlite3.Binary(b"\x00\xff\xfe"), NOW - 200, NOW - 5),
        )
        connection.commit()
        connection.close()
        self.assertFalse(self._effective()["enabled"])

    def test_an_unstamped_newest_session_falls_back_to_the_ledger(self):
        self._build_db([("s1", {}, NOW - 60)])
        self._write_ledger(True, observed_ts=NOW - 30)
        state = self._effective()
        self.assertEqual(state["status"], "observed")
        self.assertTrue(state["enabled"])
        self.assertNotIn("source", state)

    def test_the_row_activity_timestamp_is_carried_not_restamped(self):
        self._build_db([("s1", {"yolo_mode": True}, NOW - 60)])
        state = self._effective()
        from datetime import datetime, timezone

        expected = (
            datetime.fromtimestamp(NOW - 60, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        self.assertEqual(state["observed_at"], expected)

    def test_approvals_mode_off_dominates_a_toggled_off_row(self):
        # The host's own /yolo refuses to override approvals.mode: off, so
        # the projection must not either.
        (self.hermes_home / "config.yaml").write_text(
            "approvals:\n  mode: off\n", encoding="utf-8"
        )
        self._build_db([("s1", {"yolo_mode": False}, NOW - 60)])
        state = self._effective()
        self.assertTrue(state["enabled"])

    def test_a_nested_or_manual_mode_never_reads_as_bypass(self):
        # approvals.tools.mode is a different key; mode: manual is not off;
        # a QUOTED 'false'/'no' is a plain string the host normalizes to
        # manual, so it must never read as the bypass.
        for content in (
            "approvals:\n  tools:\n    mode: off\n  mode: manual\n",
            "approvals:\n  mode: manual\n",
            "approvals:\n  mode: 'false'\n",
            "approvals:\n  mode: \"no\"\n",
            "other:\n  mode: off\n",
            "# approvals:\n#   mode: off\n",
        ):
            with self.subTest(content=content):
                (self.hermes_home / "config.yaml").write_text(content, encoding="utf-8")
                state = self._effective()
                self.assertEqual(state["status"], "idle")

    def test_a_bare_yaml_boolean_mode_reads_as_the_bypass_it_is(self):
        # YAML 1.1 reads bare false/no/off as boolean False and the host
        # normalizer maps False back to "off" — quoting is what opts out.
        for content in (
            "approvals:\n  mode: false\n",
            "approvals:\n  mode: no\n",
        ):
            with self.subTest(content=content):
                (self.hermes_home / "config.yaml").write_text(content, encoding="utf-8")
                self.assertTrue(self._effective()["enabled"])

    def test_unreadable_state_never_breaks_the_projection(self):
        for prepare in (
            lambda: (self.hermes_home / "state.db").write_bytes(b"not a database"),
            lambda: self._build_db([("s1", 42, NOW - 60)]),  # non-str model_config
            lambda: None,  # missing db entirely
        ):
            with self.subTest(prepare=prepare):
                db = self.hermes_home / "state.db"
                if db.exists():
                    db.unlink()
                prepare()
                state = self._effective()
                self.assertEqual(state["status"], "idle")

    def test_the_host_state_projection_carries_its_claim_boundary(self):
        self._build_db([("s1", {"yolo_mode": True}, NOW - 60)])
        state = self._effective()
        self.assertIn("never approval, execution", state["claim_boundary"])
        self.assertIn("real-time", state["claim_boundary"])

    def test_the_hud_payload_reads_the_persisted_toggle(self):
        # read_omh_hud runs on the wall clock, so the fixture row must be
        # fresh relative to it (the other cases pin the clock via now=NOW).
        self._build_db([("s1", {"yolo_mode": True}, time.time() - 60)])
        payload = read_omh_hud(self.omh_home, str(self.hermes_home))
        self.assertEqual(payload["yolo"]["status"], "observed")
        self.assertTrue(payload["yolo"]["enabled"])
