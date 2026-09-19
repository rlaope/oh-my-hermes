"""Contracts for the bounded fanout-root scan both per-turn readers share.

`pre_llm_call` reads the fanout root twice on every turn. Before #1734 the
running-work board opened four JSON files for every fanout directory the
machine had ever created, so a turn cost 0.8 ms on a fresh home and 150 ms on
one with a thousand fanouts, and nothing prunes the root.

Two things are pinned here, and the second is the one that is easy to get
wrong. The scan must be BOUNDED -- the expensive per-directory reads happen
for a fixed number of directories however many exist. And it must be bounded
BY RECENCY, not by name: a fanout id is `fanout-<sha256(goal)[:12]>`, a
content hash with no order in it, so slicing a sorted name list would keep an
arbitrary eight of a thousand and silently drop running units. The
disagreement between name order and disk order is written into the fixtures
on purpose, so a name sort cannot pass these tests.
"""

import json
import os
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from omh.plugin_bundle.omh import status_board_reader
from omh.plugin_bundle.omh.dispatch_outcomes import unacknowledged_outcomes
from omh.plugin_bundle.omh.fanout_scan import (
    RECENT_FANOUT_DIR_LIMIT,
    newest_fanout_dirs,
    path_mtime,
)
from omh.plugin_bundle.omh.status_board_reader import read_running_work_board
from omh.plugin_bundle.omh.todo_store import build_todo_record, write_todo

NOW = 1_787_040_000.0


def fanout_id(index: int) -> str:
    """A real-shaped id: the hash of a goal, carrying no order at all."""
    return "fanout-" + sha256(f"goal-{index}".encode("utf-8")).hexdigest()[:12]


class FanoutScanHelperTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "fanout"
        self.root.mkdir(parents=True)

    def _dir(self, name: str, *, mtime: float) -> Path:
        child = self.root / name
        child.mkdir()
        os.utime(child, (mtime, mtime))
        return child

    def test_the_newest_directories_survive_and_the_rest_are_counted(self):
        for index in range(20):
            self._dir(fanout_id(index), mtime=NOW + index)
        listed, dirs, omitted = newest_fanout_dirs(self.root, limit=8, activity_of=path_mtime)
        self.assertTrue(listed)
        self.assertEqual([child.name for child in dirs], [fanout_id(i) for i in range(19, 11, -1)])
        self.assertEqual(omitted, 12)

    def test_recency_decides_and_not_the_name(self):
        # Newest on disk is whichever name sorts FIRST, so a scan that sorted
        # names and sliced would return the exact opposite set.
        names = sorted(fanout_id(index) for index in range(20))
        for rank, name in enumerate(names):
            self._dir(name, mtime=NOW + (len(names) - rank))
        _listed, dirs, _omitted = newest_fanout_dirs(self.root, limit=4, activity_of=path_mtime)
        self.assertEqual([child.name for child in dirs], names[:4])

    def test_a_directory_with_no_activity_stamp_is_dropped_not_ordered(self):
        self._dir(fanout_id(0), mtime=NOW)
        self._dir(fanout_id(1), mtime=NOW + 1)
        _listed, dirs, omitted = newest_fanout_dirs(
            self.root,
            limit=8,
            activity_of=lambda child: None if child.name == fanout_id(1) else NOW,
        )
        self.assertEqual([child.name for child in dirs], [fanout_id(0)])
        self.assertEqual(omitted, 0)

    def test_files_symlinks_and_filtered_names_are_not_candidates(self):
        self._dir(fanout_id(0), mtime=NOW)
        (self.root / "notes.txt").write_text("x", encoding="utf-8")
        (self.root / "stale").mkdir()
        try:
            (self.root / "link").symlink_to(self.root / fanout_id(0), target_is_directory=True)
        except (OSError, NotImplementedError):  # pragma: no cover - restricted hosts
            pass
        _listed, dirs, _omitted = newest_fanout_dirs(
            self.root,
            limit=8,
            activity_of=path_mtime,
            name_filter=lambda name: name.startswith("fanout-"),
        )
        self.assertEqual([child.name for child in dirs], [fanout_id(0)])

    def test_an_unlistable_root_reports_a_failed_listing(self):
        missing = Path(self._tmp.name) / "never-created"
        self.assertEqual(newest_fanout_dirs(missing, limit=8, activity_of=path_mtime), (False, [], 0))


class RunningWorkBoardScanBoundTest(unittest.TestCase):
    """The board reads a bounded number of fanouts and says which it skipped."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "omh"
        self.root = self.home / "coding" / "fanout"

    def _fanout(self, index: int, *, marker_mtime: float, running_units=(), summary_units=()):
        directory = self.root / fanout_id(index)
        inflight = directory / "inflight"
        inflight.mkdir(parents=True)
        for unit_id in running_units:
            (inflight / f"{unit_id}.json").write_text(
                json.dumps({"schema_version": "omh_inflight_marker/v1", "owner": "codex"}),
                encoding="utf-8",
            )
        if summary_units:
            (directory / "dispatch_summary.json").write_text(
                json.dumps({"units": [{"unit_id": u, "status": "completed"} for u in summary_units]}),
                encoding="utf-8",
            )
        os.utime(inflight, (marker_mtime, marker_mtime))
        # Deliberately NOT the marker stamp: the fanout directory above the
        # markers is untouched when one is added or removed, which is why the
        # board orders by the marker directory and not by this.
        os.utime(directory, (NOW, NOW))
        return directory

    def test_only_the_bounded_set_is_opened_and_the_rest_are_reported(self):
        for index in range(30):
            self._fanout(index, marker_mtime=NOW + index, running_units=(f"unit-{index}",))
        opened: list[Path] = []
        real_read = status_board_reader._read_json_object_result

        def recording_read(path):
            opened.append(path)
            return real_read(path)

        with patch.object(status_board_reader, "_read_json_object_result", recording_read):
            board = read_running_work_board(self.home)

        self.assertEqual(board["sources"]["fanout_dirs_scanned"], RECENT_FANOUT_DIR_LIMIT)
        self.assertEqual(board["sources"]["fanout_dirs_omitted"], 30 - RECENT_FANOUT_DIR_LIMIT)
        newest = {fanout_id(index) for index in range(30 - RECENT_FANOUT_DIR_LIMIT, 30)}
        self.assertTrue(opened, "the board must still open the fanouts it kept")
        touched = {part for path in opened for part in path.parts if part.startswith("fanout-")}
        # Equality, not containment: an unbounded scan opens the other 22 as
        # well, and a scan bounded to the wrong eight opens eight wrong ones.
        self.assertEqual(touched, newest)

    def test_a_unit_running_in_a_kept_fanout_is_still_reported(self):
        for index in range(12):
            self._fanout(index, marker_mtime=NOW + index, running_units=(f"unit-{index}",))
        board = read_running_work_board(self.home, limit=20)
        reported = {unit["unit_id"] for unit in board["units"]}
        self.assertEqual(reported, {f"unit-{index}" for index in range(4, 12)})
        self.assertEqual(board["running_count"], RECENT_FANOUT_DIR_LIMIT)
        # The four the bound dropped are not silently absent.
        self.assertEqual(board["sources"]["fanout_dirs_omitted"], 4)

    def test_a_fresh_marker_makes_an_otherwise_old_fanout_current(self):
        # Eight fanouts whose markers are old, and one whose directory stamp
        # is the oldest of all but whose marker directory just changed. The
        # marker is the activity, so that one wins.
        for index in range(8):
            self._fanout(index, marker_mtime=NOW - 10_000 + index, running_units=(f"unit-{index}",))
        revived = self._fanout(99, marker_mtime=NOW + 500, running_units=("unit-99",))
        os.utime(revived, (NOW - 1_000_000, NOW - 1_000_000))
        board = read_running_work_board(self.home, limit=20)
        self.assertIn("unit-99", {unit["unit_id"] for unit in board["units"]})
        self.assertEqual(board["sources"]["fanout_dirs_omitted"], 1)

    def test_an_empty_root_still_reads_as_absent(self):
        board = read_running_work_board(self.home)
        self.assertEqual(board["sources"]["fanout_root"], "absent")
        self.assertEqual(board["sources"]["fanout_dirs_omitted"], 0)


class DispatchOutcomeScanBoundTest(unittest.TestCase):
    """The reminder keeps its own recency key: when a summary was written."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "omh"
        record = build_todo_record("plan", [{"text": "unrelated", "state": "active"}], source="test")
        write_todo(self.home, record)
        from datetime import datetime

        self.plan_updated_at = datetime.fromisoformat(record["updated_at"].replace("Z", "+00:00"))

    def _summary(self, index: int, *, mtime: float):
        directory = self.home / "coding" / "fanout" / fanout_id(index)
        directory.mkdir(parents=True)
        from datetime import timedelta

        # Strictly after the plan's own stamp: a unit that finished at the
        # same second as the last plan touch is not yet unacknowledged.
        finished = (self.plan_updated_at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        path = directory / "dispatch_summary.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "fanout_dispatch_summary/v1",
                    "fanout_id": directory.name,
                    "units": [
                        {
                            "unit_id": f"unit-{index}",
                            "status": "completed",
                            "process_succeeded": True,
                            "finished_at": finished,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        os.utime(path, (mtime, mtime))
        return directory

    def test_the_newest_summaries_win_however_the_names_sort(self):
        import time as _time

        base = _time.time()
        for index in range(20):
            self._summary(index, mtime=base + index)
        outcomes = unacknowledged_outcomes(str(self.home))
        reported = {outcome["unit_id"] for outcome in outcomes}
        self.assertEqual(reported, {f"unit-{index}" for index in range(12, 20)})

    def test_a_fanout_that_never_wrote_a_summary_is_not_a_candidate(self):
        import time as _time

        (self.home / "coding" / "fanout" / fanout_id(50)).mkdir(parents=True)
        self._summary(1, mtime=_time.time())
        outcomes = unacknowledged_outcomes(str(self.home))
        self.assertEqual({outcome["unit_id"] for outcome in outcomes}, {"unit-1"})


if __name__ == "__main__":
    unittest.main()
