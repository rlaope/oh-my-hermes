from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.inflight import (  # noqa: E402
    INFLIGHT_CLAIM_BOUNDARY,
    INFLIGHT_MARKER_FIELDS,
    INFLIGHT_MARKER_SCHEMA_VERSION,
    INFLIGHT_MARKER_STATUSES,
    InflightMarkerError,
    clear_inflight_marker,
    read_inflight_markers,
    write_inflight_marker,
)
from omh.system.paths import OmhPaths  # noqa: E402

_FANOUT_ID = "fanout-0123456789ab"
_OTHER_FANOUT_ID = "fanout-ba9876543210"


def _paths(root: Path) -> OmhPaths:
    return OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")


def _fields(**overrides: str) -> dict[str, str]:
    fields = {
        "owner": "codex",
        "owner_host": "local",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "medium",
        "run_ref": "run-core",
        "worktree": "/tmp/worktrees/core",
        "started_at": "2026-08-03T09:00:00Z",
    }
    fields.update(overrides)
    return fields


class WriteReadRoundTripTest(unittest.TestCase):
    def test_written_marker_is_read_back_with_its_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            marker_path = write_inflight_marker(paths, _FANOUT_ID, "core", _fields())

            self.assertTrue(marker_path.exists())
            self.assertEqual(marker_path.name, "core.json")
            self.assertEqual(marker_path.parent.name, "inflight")
            self.assertEqual(marker_path.parent.parent.name, _FANOUT_ID)

            markers = read_inflight_markers(paths)
            self.assertEqual(len(markers), 1)
            marker = markers[0]
            self.assertEqual(marker["schema_version"], INFLIGHT_MARKER_SCHEMA_VERSION)
            self.assertEqual(marker["claim_boundary"], INFLIGHT_CLAIM_BOUNDARY)
            self.assertEqual(marker["fanout_id"], _FANOUT_ID)
            self.assertEqual(marker["unit_id"], "core")
            self.assertEqual(marker["marker_status"], "present")
            self.assertEqual(marker["owner"], "codex")
            self.assertEqual(marker["model"], "gpt-5.6-sol")
            self.assertEqual(marker["reasoning_effort"], "medium")
            self.assertEqual(marker["run_ref"], "run-core")
            self.assertEqual(marker["worktree"], "/tmp/worktrees/core")
            self.assertEqual(marker["started_at"], "2026-08-03T09:00:00Z")
            self.assertTrue(marker["written_at"])

    def test_marker_never_claims_liveness(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            marker = read_inflight_markers(paths)[0]
            self.assertEqual(marker["liveness"], "unknown")
            self.assertNotIn("stale", marker)
            self.assertNotIn("running", marker)
            self.assertNotIn("alive", marker)

    def test_persisted_payload_is_flat_and_scalar(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            marker_path = write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            import json

            payload = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], INFLIGHT_MARKER_SCHEMA_VERSION)
            self.assertEqual(payload["claim_boundary"], INFLIGHT_CLAIM_BOUNDARY)
            for key, value in payload.items():
                self.assertIsInstance(value, str, msg=f"{key} must persist as a string")

    def test_missing_started_at_defaults_to_write_time(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_inflight_marker(paths, _FANOUT_ID, "core", {"owner": "codex"})
            marker = read_inflight_markers(paths)[0]
            self.assertTrue(marker["started_at"])
            self.assertEqual(marker["started_at"], marker["written_at"])

    def test_unknown_field_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with self.assertRaises(InflightMarkerError):
                write_inflight_marker(paths, _FANOUT_ID, "core", _fields(prompt="secret"))

    def test_non_scalar_field_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with self.assertRaises(InflightMarkerError):
                write_inflight_marker(paths, _FANOUT_ID, "core", {"owner": {"nested": "value"}})

    def test_invalid_ids_are_rejected_on_write(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with self.assertRaises(InflightMarkerError):
                write_inflight_marker(paths, "../escape", "core", _fields())
            with self.assertRaises(InflightMarkerError):
                write_inflight_marker(paths, _FANOUT_ID, "../escape", _fields())


class ClearIdempotencyTest(unittest.TestCase):
    def test_clear_twice_returns_true_then_false(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            marker_path = write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            self.assertTrue(clear_inflight_marker(paths, _FANOUT_ID, "core"))
            self.assertFalse(marker_path.exists())
            self.assertFalse(clear_inflight_marker(paths, _FANOUT_ID, "core"))
            self.assertEqual(read_inflight_markers(paths), [])

    def test_clear_never_written_marker_returns_false(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            self.assertFalse(clear_inflight_marker(paths, _FANOUT_ID, "never-written"))

    def test_clear_with_invalid_ids_returns_false_without_raising(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            self.assertFalse(clear_inflight_marker(paths, "../escape", "core"))
            self.assertFalse(clear_inflight_marker(paths, _FANOUT_ID, "../escape"))

    def test_clear_in_finally_does_not_mask_the_dispatch_exception(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            cleared: list[bool] = []

            def dispatch(unit_id: str) -> None:
                try:
                    raise RuntimeError("spawn failed")
                finally:
                    cleared.append(clear_inflight_marker(paths, _FANOUT_ID, unit_id))

            with self.assertRaises(RuntimeError) as never_written:
                dispatch("never-written")
            self.assertEqual(str(never_written.exception), "spawn failed")

            write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            with self.assertRaises(RuntimeError) as written:
                dispatch("core")
            self.assertEqual(str(written.exception), "spawn failed")

            with self.assertRaises(RuntimeError) as bad_id:
                dispatch("../escape")
            self.assertEqual(str(bad_id.exception), "spawn failed")

            self.assertEqual(cleared, [False, True, False])


class ReadResilienceTest(unittest.TestCase):
    def test_missing_root_reads_as_empty_list(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            self.assertEqual(read_inflight_markers(paths), [])

    def test_malformed_marker_is_reported_unreadable_without_raising(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            good = write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            (good.parent / "broken.json").write_text("{not json", encoding="utf-8")
            (good.parent / "listy.json").write_text("[1, 2, 3]", encoding="utf-8")
            (good.parent / "wrong-schema.json").write_text('{"schema_version": "other/v9"}', encoding="utf-8")

            markers = read_inflight_markers(paths)
            by_unit = {marker["unit_id"]: marker for marker in markers}
            self.assertEqual(by_unit["core"]["marker_status"], "present")
            self.assertEqual(by_unit["broken"]["marker_status"], "unreadable")
            self.assertEqual(by_unit["listy"]["marker_status"], "unreadable")
            self.assertEqual(by_unit["wrong-schema"]["marker_status"], "unreadable")

    def test_unreadable_entry_leaks_no_path_or_error_text(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            marker_path = write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            (marker_path.parent / "broken.json").write_text("{not json", encoding="utf-8")
            clear_inflight_marker(paths, _FANOUT_ID, "core")

            markers = read_inflight_markers(paths)
            self.assertEqual(len(markers), 1)
            broken = markers[0]
            self.assertEqual(broken["marker_status"], "unreadable")
            self.assertEqual(broken["owner"], "")
            self.assertEqual(broken["worktree"], "")
            self.assertEqual(broken["started_at"], "")
            self.assertNotIn("error", broken)
            self.assertNotIn("path", broken)
            self.assertNotIn(tmp, repr(broken))

    def test_absent_and_unreadable_are_distinguished(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            marker_path = write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            inflight_dir = marker_path.parent
            # A dangling symlink is listed by the directory scan but is not
            # there when read: that is "absent", not "unreadable".
            (inflight_dir / "vanished.json").symlink_to(inflight_dir / "no-such-file.json")
            # A directory that looks like a marker file fails on read: that is
            # "unreadable", not "absent".
            (inflight_dir / "notafile.json").mkdir()

            statuses = {marker["unit_id"]: marker["marker_status"] for marker in read_inflight_markers(paths)}
            self.assertEqual(statuses["core"], "present")
            self.assertEqual(statuses["vanished"], "absent")
            self.assertEqual(statuses["notafile"], "unreadable")
            for status in statuses.values():
                self.assertIn(status, INFLIGHT_MARKER_STATUSES)

    def test_non_marker_entries_are_ignored(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            marker_path = write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            (marker_path.parent / "notes.txt").write_text("ignored", encoding="utf-8")
            (marker_path.parent / "Bad Unit.json").write_text("{}", encoding="utf-8")
            stray = paths.fanout_contracts_dir / "not-a-fanout" / "inflight"
            stray.mkdir(parents=True)
            (stray / "core.json").write_text("{}", encoding="utf-8")

            markers = read_inflight_markers(paths)
            self.assertEqual([marker["unit_id"] for marker in markers], ["core"])


class OrderingAndLimitTest(unittest.TestCase):
    def test_results_sort_by_started_at_then_unit_id(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_inflight_marker(paths, _FANOUT_ID, "zeta", _fields(started_at="2026-08-03T09:00:00Z"))
            write_inflight_marker(paths, _FANOUT_ID, "alpha", _fields(started_at="2026-08-03T09:00:00Z"))
            write_inflight_marker(paths, _FANOUT_ID, "beta", _fields(started_at="2026-08-03T08:00:00Z"))
            write_inflight_marker(paths, _OTHER_FANOUT_ID, "alpha", _fields(started_at="2026-08-03T09:00:00Z"))

            order = [(marker["started_at"], marker["unit_id"], marker["fanout_id"]) for marker in read_inflight_markers(paths)]
            self.assertEqual(
                order,
                [
                    ("2026-08-03T08:00:00Z", "beta", _FANOUT_ID),
                    ("2026-08-03T09:00:00Z", "alpha", _FANOUT_ID),
                    ("2026-08-03T09:00:00Z", "alpha", _OTHER_FANOUT_ID),
                    ("2026-08-03T09:00:00Z", "zeta", _FANOUT_ID),
                ],
            )
            self.assertEqual(read_inflight_markers(paths), read_inflight_markers(paths))

    def test_limit_truncates_after_sorting(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_inflight_marker(paths, _FANOUT_ID, "zeta", _fields(started_at="2026-08-03T09:00:00Z"))
            write_inflight_marker(paths, _FANOUT_ID, "beta", _fields(started_at="2026-08-03T08:00:00Z"))

            self.assertEqual([marker["unit_id"] for marker in read_inflight_markers(paths, limit=1)], ["beta"])
            self.assertEqual(read_inflight_markers(paths, limit=0), [])
            self.assertEqual(read_inflight_markers(paths, limit=-3), [])

    def test_every_entry_carries_the_full_field_surface(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            marker = read_inflight_markers(paths)[0]
            for name in INFLIGHT_MARKER_FIELDS:
                self.assertIn(name, marker)


if __name__ == "__main__":
    unittest.main()
