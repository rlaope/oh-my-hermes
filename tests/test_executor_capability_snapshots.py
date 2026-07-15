from __future__ import annotations

import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.coding.executor_capability_snapshots import (
    ExecutorCapabilitySnapshotError,
    build_executor_capability_snapshot,
    read_executor_capability_snapshot,
    read_matching_executor_capability_snapshot,
    validate_executor_capability_snapshot,
    write_executor_capability_snapshot,
)


class ExecutorCapabilitySnapshotTests(unittest.TestCase):
    def test_builds_host_observed_capability_with_bounded_evidence(self) -> None:
        snapshot = build_executor_capability_snapshot(
            executor="codex",
            capabilities={
                "parallel_agents": {
                    "status": "host_observed",
                    "scope": {"host": "local", "surface": "native_subagents"},
                    "evidence_ref": "host-probe:codex-subagents",
                    "observed_at": "2026-07-15T00:00:00Z",
                },
                "visual_qa": {"status": "unknown"},
            },
            recorded_at="2026-07-15T00:00:01Z",
        )

        self.assertEqual(snapshot["schema_version"], "executor_capability_snapshot/v1")
        self.assertEqual(snapshot["executor"], "codex")
        self.assertEqual(snapshot["capabilities"]["parallel_agents"]["status"], "host_observed")
        self.assertEqual(validate_executor_capability_snapshot(snapshot), [])

    def test_rejects_host_observed_capability_without_scope_or_evidence(self) -> None:
        with self.assertRaisesRegex(ExecutorCapabilitySnapshotError, "scope"):
            build_executor_capability_snapshot(
                executor="codex",
                capabilities={
                    "parallel_agents": {
                        "status": "host_observed",
                        "evidence_ref": "host-probe:codex-subagents",
                        "observed_at": "2026-07-15T00:00:00Z",
                    }
                },
            )

        invalid = {
            "schema_version": "executor_capability_snapshot/v1",
            "executor": "codex",
            "recorded_at": "2026-07-15T00:00:01Z",
            "capabilities": {
                "parallel_agents": {
                    "status": "host_observed",
                    "scope": {"host": "local"},
                    "observed_at": "2026-07-15T00:00:00Z",
                }
            },
        }
        self.assertIn("parallel_agents host_observed capability requires a nonempty evidence_ref", validate_executor_capability_snapshot(invalid))

    def test_persists_private_snapshot_and_rejects_lifecycle_or_raw_material(self) -> None:
        snapshot = build_executor_capability_snapshot(
            executor="claude-code",
            capabilities={
                "worktree_isolation": {"status": "prepared"},
                "browser_or_computer_use": {"status": "unavailable"},
            },
            recorded_at="2026-07-15T00:00:01Z",
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots" / "claude-code.json"
            write_executor_capability_snapshot(path, snapshot)

            self.assertEqual(read_executor_capability_snapshot(path), snapshot)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

        for forbidden_key in ("execution", "verification", "review", "ci", "merge", "raw_log", "transcript", "reasoning"):
            invalid = dict(snapshot)
            invalid[forbidden_key] = "forbidden"
            self.assertTrue(validate_executor_capability_snapshot(invalid), forbidden_key)
            with self.assertRaises(ExecutorCapabilitySnapshotError):
                write_executor_capability_snapshot(Path("/tmp") / "should-not-write.json", invalid)

    def test_rejects_sensitive_metadata_and_ignores_mismatched_snapshot(self) -> None:
        with self.assertRaisesRegex(ExecutorCapabilitySnapshotError, "sensitive metadata"):
            build_executor_capability_snapshot(
                executor="codex",
                capabilities={
                    "parallel_agents": {
                        "status": "host_observed",
                        "scope": {"api_key": "local"},
                        "evidence_ref": "probe:sk-live-secret",
                        "observed_at": "2026-07-15T00:00:00Z",
                    }
                },
            )
        snapshot = build_executor_capability_snapshot(
            executor="codex", capabilities={"parallel_agents": {"status": "unknown"}}
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "codex.json"
            write_executor_capability_snapshot(path, snapshot)
            self.assertEqual(read_matching_executor_capability_snapshot(path, expected_executor="codex"), snapshot)
            self.assertIsNone(read_matching_executor_capability_snapshot(path, expected_executor="claude-code"))

    def test_rejects_raw_scope_key(self) -> None:
        with self.assertRaisesRegex(ExecutorCapabilitySnapshotError, "scope keys"):
            build_executor_capability_snapshot(
                executor="codex",
                capabilities={
                    "parallel_agents": {
                        "status": "host_observed",
                        "scope": {"raw_message": "not-secret-but-not-metadata"},
                        "evidence_ref": "probe:local",
                        "observed_at": "2026-07-15T00:00:00Z",
                    }
                },
            )
