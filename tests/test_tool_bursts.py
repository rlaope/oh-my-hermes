"""Contracts for parallel tool-call burst observation.

Hermes dispatches a model turn's batched tool calls concurrently, but the
transcript renders only a collapsed "Tool calls (N)" group. The
pre_tool_call hook ticks this ledger per call; ticks inside one short
window are the concurrent batch, and the HUD brands the latest fresh one
as a parallel shot.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from omh.plugin_bundle.omh.awareness_delivery import (
    LOCK_MECHANISM_NONE,
    _awareness_delivery_lock,
)
from omh.plugin_bundle.omh.runtime_reader import read_omh_hud
from omh.plugin_bundle.omh.tool_bursts import (
    BURST_FRESH_SECONDS,
    MAX_OPEN_TOOL_CALLS,
    MAX_TOOL_BURST_ENTRIES,
    TOOL_CALL_OPEN_TTL_SECONDS,
    _clear_pending_write_failures,
    latest_parallel_shot,
    record_tool_call,
    record_tool_call_close,
    tool_bursts_path,
    tool_call_activity,
    tool_call_projection,
)

NOW = 1_787_040_000.0


class ToolBurstLedgerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = str(Path(self._tmp.name) / "omh")

    def test_calls_within_the_window_group_into_one_parallel_shot(self):
        for offset, tool in ((0.0, "read_file"), (0.1, "read_file"), (0.2, "terminal"), (0.3, "search_files")):
            record_tool_call(tool, omh_home=self.home, now=NOW + offset)
        shot = latest_parallel_shot(self.home, now=NOW + 5)
        self.assertEqual(shot["status"], "observed")
        self.assertEqual(shot["size"], 4)
        self.assertEqual(shot["distinct_tools"], 3)
        self.assertIn("not proof", shot["claim_boundary"])

    def test_sequential_calls_separated_by_round_trips_never_form_a_shot(self):
        for offset in (0.0, 10.0, 25.0):
            record_tool_call("terminal", omh_home=self.home, now=NOW + offset)
        self.assertEqual(latest_parallel_shot(self.home, now=NOW + 30)["status"], "idle")

    def test_a_stale_burst_expires_from_the_projection(self):
        record_tool_call("read_file", omh_home=self.home, now=NOW)
        record_tool_call("read_file", omh_home=self.home, now=NOW + 0.2)
        self.assertEqual(latest_parallel_shot(self.home, now=NOW + 1)["status"], "observed")
        self.assertEqual(
            latest_parallel_shot(self.home, now=NOW + BURST_FRESH_SECONDS + 1)["status"],
            "idle",
        )

    def test_the_ledger_is_capped_and_a_blank_tool_name_is_ignored(self):
        record_tool_call("", omh_home=self.home, now=NOW)
        self.assertFalse(tool_bursts_path(self.home).exists())
        for index in range(MAX_TOOL_BURST_ENTRIES + 10):
            record_tool_call("terminal", omh_home=self.home, now=NOW + index * 5)
        import json

        record = json.loads(tool_bursts_path(self.home).read_text(encoding="utf-8"))
        self.assertEqual(len(record["entries"]), MAX_TOOL_BURST_ENTRIES)

    def test_open_call_stays_live_until_a_matching_close(self):
        record_tool_call("terminal", omh_home=self.home, now=NOW, tool_call_id="call-1", turn_id="turn-1")

        activity = tool_call_activity(self.home, now=NOW + 5)

        self.assertTrue(activity["live"])
        self.assertEqual(activity["open_call_count"], 1)
        self.assertEqual(activity["oldest_open_elapsed_seconds"], 5)
        self.assertTrue(activity["oldest_open_started_at"])

        record_tool_call_close("call-1", omh_home=self.home, now=NOW + 5.5)
        closed = tool_call_activity(self.home, now=NOW + 6)

        self.assertFalse(closed["live"])
        self.assertEqual(closed["open_call_count"], 0)
        self.assertEqual(closed["oldest_open_elapsed_seconds"], None)

    def test_a_call_with_no_tool_call_id_never_opens(self):
        record_tool_call("terminal", omh_home=self.home, now=NOW)

        activity = tool_call_activity(self.home, now=NOW + 1)

        self.assertFalse(activity["live"])
        self.assertEqual(activity["open_call_count"], 0)

    def test_an_open_call_expires_after_the_ttl_instead_of_staying_live_forever(self):
        record_tool_call("terminal", omh_home=self.home, now=NOW, tool_call_id="call-1", turn_id="turn-1")

        still_open = tool_call_activity(self.home, now=NOW + TOOL_CALL_OPEN_TTL_SECONDS - 1)
        expired = tool_call_activity(self.home, now=NOW + TOOL_CALL_OPEN_TTL_SECONDS + 1)

        self.assertTrue(still_open["live"])
        self.assertFalse(expired["live"])
        self.assertEqual(expired["open_call_count"], 0)

    def test_a_close_with_no_matching_open_closes_nothing_but_is_still_observed(self):
        record_tool_call_close("never-opened", omh_home=self.home, now=NOW)

        # Nothing to close, but the file now exists -- post_tool_call firing
        # at all is the evidence the HUD needs, independent of pairing (P2-1).
        self.assertTrue(tool_bursts_path(self.home).exists())
        self.assertTrue(tool_call_activity(self.home, now=NOW)["post_tool_call_observed"])

    def test_liveness_is_unanswerable_until_post_tool_call_is_ever_observed(self):
        record_tool_call("terminal", omh_home=self.home, now=NOW, tool_call_id="call-1")

        unanswered = tool_call_activity(self.home, now=NOW + 1)
        self.assertFalse(unanswered["post_tool_call_observed"])
        # `live` still reports what the ledger has, but the flag beside it
        # is what tells the widget whether to trust that reading at all.
        self.assertTrue(unanswered["live"])

        record_tool_call_close("call-1", omh_home=self.home, now=NOW + 2)

        answered = tool_call_activity(self.home, now=NOW + 3)
        self.assertTrue(answered["post_tool_call_observed"])
        self.assertFalse(answered["live"])

    def test_tool_call_projection_matches_the_separate_calls_from_one_read(self):
        record_tool_call("read_file", omh_home=self.home, now=NOW, tool_call_id="call-1")
        record_tool_call("terminal", omh_home=self.home, now=NOW + 0.1, tool_call_id="call-2")
        record_tool_call_close("call-2", omh_home=self.home, now=NOW + 0.2)

        projection = tool_call_projection(self.home, now=NOW + 1)

        self.assertEqual(projection["parallel_shot"], latest_parallel_shot(self.home, now=NOW + 1))
        self.assertEqual(projection["activity"], tool_call_activity(self.home, now=NOW + 1))
        # The activity block's own latest_shot is the identical object the
        # top-level parallel_shot key carries -- one computation, not two.
        self.assertEqual(projection["activity"]["latest_shot"], projection["parallel_shot"])

    def test_the_open_ledger_is_capped_under_pathological_growth(self):
        for index in range(MAX_OPEN_TOOL_CALLS + 10):
            record_tool_call(
                "terminal",
                omh_home=self.home,
                now=NOW + index,
                tool_call_id=f"call-{index}",
                turn_id="turn-1",
            )

        activity = tool_call_activity(self.home, now=NOW + MAX_OPEN_TOOL_CALLS + 10)

        self.assertLessEqual(activity["open_call_count"], MAX_OPEN_TOOL_CALLS)

    def test_the_latest_shot_reports_its_open_and_closed_split(self):
        record_tool_call("read_file", omh_home=self.home, now=NOW, tool_call_id="call-1", turn_id="turn-1")
        record_tool_call("terminal", omh_home=self.home, now=NOW + 0.1, tool_call_id="call-2", turn_id="turn-1")
        record_tool_call_close("call-2", omh_home=self.home, now=NOW + 0.2)

        shot = latest_parallel_shot(self.home, now=NOW + 1)
        activity = tool_call_activity(self.home, now=NOW + 1)

        self.assertEqual(shot["status"], "observed")
        self.assertEqual(shot["open_count"], 1)
        # Not "completed" -- an entry with no tool_call_id or an expired
        # entry lands here too, and neither was observed finishing (P3-1).
        self.assertEqual(shot["closed_or_unobserved_count"], 1)
        self.assertEqual(activity["latest_shot"]["open_count"], 1)
        self.assertTrue(activity["live"])

    def test_the_latest_shot_reports_peak_concurrency_not_dispatch_size(self):
        # Four strictly SEQUENTIAL calls, each closing before the next opens,
        # chained into one burst by the 1.5s grouping window. `size` is 4,
        # but at no point were more than 1 open at once -- the badge must
        # read the true peak, not the dispatch count (P1-2).
        for index in range(4):
            call_id = f"call-{index}"
            record_tool_call("terminal", omh_home=self.home, now=NOW + index * 0.3, tool_call_id=call_id)
            record_tool_call_close(call_id, omh_home=self.home, now=NOW + index * 0.3 + 0.05)

        shot = latest_parallel_shot(self.home, now=NOW + 1)

        self.assertEqual(shot["status"], "observed")
        self.assertEqual(shot["size"], 4)
        self.assertEqual(shot["peak_open_count"], 1)

    def test_the_latest_shot_reports_true_overlap_when_calls_genuinely_stack(self):
        # call-1 opens and is still open when call-2 and call-3 open too --
        # a real 3-way overlap.
        record_tool_call("read_file", omh_home=self.home, now=NOW, tool_call_id="call-1")
        record_tool_call("read_file", omh_home=self.home, now=NOW + 0.1, tool_call_id="call-2")
        record_tool_call("terminal", omh_home=self.home, now=NOW + 0.2, tool_call_id="call-3")
        record_tool_call_close("call-1", omh_home=self.home, now=NOW + 0.3)
        record_tool_call_close("call-2", omh_home=self.home, now=NOW + 0.4)
        record_tool_call_close("call-3", omh_home=self.home, now=NOW + 0.5)

        shot = latest_parallel_shot(self.home, now=NOW + 1)

        self.assertEqual(shot["peak_open_count"], 3)

    def test_the_hud_payload_carries_the_latest_shot(self):
        # The reader checks freshness against wall time, so record against
        # wall time here.
        import time

        base = time.time()
        record_tool_call("read_file", omh_home=self.home, now=base)
        record_tool_call("terminal", omh_home=self.home, now=base + 0.3)
        hermes = str(Path(self._tmp.name) / "hermes")
        payload = read_omh_hud(self.home, hermes)
        shot = payload["parallel_shot"]
        self.assertEqual(shot["status"], "observed")
        self.assertEqual(shot["size"], 2)
        self.assertEqual(shot["distinct_tools"], 2)
        self.assertIn("activity", payload)
        self.assertFalse(payload["activity"]["live"])
        self.assertEqual(payload["activity"]["open_call_count"], 0)

    def test_the_hud_payload_carries_live_open_call_activity(self):
        import time

        base = time.time()
        record_tool_call("terminal", omh_home=self.home, now=base, tool_call_id="call-1", turn_id="turn-1")
        hermes = str(Path(self._tmp.name) / "hermes")

        payload = read_omh_hud(self.home, hermes)

        self.assertTrue(payload["activity"]["live"])
        self.assertEqual(payload["activity"]["open_call_count"], 1)


class SwallowedLedgerWriteTest(unittest.TestCase):
    """Every writer here fails open, and now says how often it did.

    The swallow itself is right: a hook that raised would vanish into
    Hermes's own try/except-and-log wrapper and the model would lose the
    awareness this ledger feeds. What was wrong is that the drop left no
    trace, so an entry left open read identically whether the call was still
    running or its close had lost the lock. Measured 2026-09-20 on this
    machine: eight concurrent writers lose nothing at all, twenty-four lose
    466 of 9,648 writes. These tests pin the counter, never the rate.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = str(Path(self._tmp.name) / "omh")
        # Process-global, because a failed write cannot record itself where
        # it happens. Reset around every case so one test's drop is never
        # another test's count.
        _clear_pending_write_failures()
        self.addCleanup(_clear_pending_write_failures)

    def _ledger(self):
        import json

        return json.loads(tool_bursts_path(self.home).read_text(encoding="utf-8"))

    def test_a_successful_write_counts_nothing(self):
        record_tool_call("terminal", omh_home=self.home, now=NOW, tool_call_id="c1")
        self.assertEqual(self._ledger()["write_failures"], {"lock_timeout": 0, "other": 0})
        self.assertEqual(
            tool_call_activity(self.home, now=NOW + 1)["write_failures"],
            {"lock_timeout": 0, "other": 0},
        )

    def test_a_held_lock_times_a_write_out_and_the_next_write_records_it(self):
        path = tool_bursts_path(self.home)
        with _awareness_delivery_lock(path) as mechanism:
            if mechanism == LOCK_MECHANISM_NONE:  # pragma: no cover - no lock backend
                self.skipTest("host has neither a POSIX nor a Windows lock backend")
            # Held by this very process on a separate file description, so
            # the hook's own acquire cannot take it and gives up after
            # `_LOCK_TIMEOUT_SECONDS`. The tick is lost, by design.
            record_tool_call("terminal", omh_home=self.home, now=NOW, tool_call_id="lost")
            self.assertFalse(path.exists(), "the write must not have landed")
        # The count rides along with the next write that does take the lock.
        record_tool_call("terminal", omh_home=self.home, now=NOW + 1, tool_call_id="kept")
        ledger = self._ledger()
        self.assertEqual(ledger["write_failures"], {"lock_timeout": 1, "other": 0})
        self.assertEqual([entry["id"] for entry in ledger["entries"]], ["kept"])
        activity = tool_call_activity(self.home, now=NOW + 2)
        self.assertEqual(activity["write_failures"], {"lock_timeout": 1, "other": 0})
        self.assertIn("LOWER bound", activity["write_failures_claim_boundary"])

    def test_a_dropped_close_is_counted_and_the_entry_stays_open(self):
        record_tool_call("terminal", omh_home=self.home, now=NOW, tool_call_id="c1")
        path = tool_bursts_path(self.home)
        with _awareness_delivery_lock(path) as mechanism:
            if mechanism == LOCK_MECHANISM_NONE:  # pragma: no cover - no lock backend
                self.skipTest("host has neither a POSIX nor a Windows lock backend")
            record_tool_call_close("c1", omh_home=self.home, now=NOW + 1)
        activity = tool_call_activity(self.home, now=NOW + 2)
        # Exactly the ambiguity the counter exists to bound: the call reads
        # as open, and only the count says its close was dropped.
        self.assertEqual(activity["open_call_count"], 1)
        self.assertEqual(activity["write_failures"], {"lock_timeout": 1, "other": 0})

    def test_a_non_timeout_write_failure_is_counted_apart(self):
        from omh.plugin_bundle.omh import tool_bursts

        def exploding_write(*args, **kwargs):
            raise OSError("no space left on device")

        with patch.object(tool_bursts, "_write_delivery_record", exploding_write):
            record_tool_call("terminal", omh_home=self.home, now=NOW, tool_call_id="c1")
        record_tool_call("terminal", omh_home=self.home, now=NOW + 1, tool_call_id="c2")
        self.assertEqual(self._ledger()["write_failures"], {"lock_timeout": 0, "other": 1})

    def test_a_ledger_written_before_the_counter_existed_reads_as_zero(self):
        import json

        path = tool_bursts_path(self.home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": "omh_tool_bursts/v1",
                    "entries": [{"tool": "terminal", "ts": NOW, "id": "", "open_at_tick": 1}],
                    "open_calls": {},
                    "repeat_streaks": {},
                    "post_tool_call_observed_at": 0.0,
                }
            ),
            encoding="utf-8",
        )
        # Zero means "nobody was counting when this file was written", which
        # is the truth about it -- never a claim that nothing was lost.
        self.assertEqual(
            tool_call_activity(self.home, now=NOW + 1)["write_failures"],
            {"lock_timeout": 0, "other": 0},
        )


if __name__ == "__main__":
    unittest.main()
