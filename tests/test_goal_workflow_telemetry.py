from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.paths import resolve_paths
from omh.workflows.goal_ledger import complete_goal_ledger, create_goal_ledger, record_goal_checkpoint, read_goal_ledger


class GoalWorkflowTelemetryTests(unittest.TestCase):
    def test_goal_ledger_records_bounded_metadata_only_lifecycle_events(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            goal = create_goal_ledger(paths, "private raw objective", ["tests pass"], goal_id="telemetry-goal")
            self.assertEqual(goal["telemetry"][0]["event"], "start")
            self.assertNotIn("private raw objective", str(goal["telemetry"]))
            updated = record_goal_checkpoint(paths, "telemetry-goal", "Tests pass", status="in_progress")
            self.assertEqual([e["event"] for e in updated["telemetry"]], ["start", "checkpoint"])
            self.assertEqual(updated["telemetry"][-1]["checkpoint_id"], updated["checkpoints"][-1]["checkpoint_id"])
            self.assertEqual(read_goal_ledger(paths, "telemetry-goal")["telemetry"], updated["telemetry"])
    def test_blocker_adds_metadata_only_blocked_telemetry(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(paths, "private goal text", ["completion proof"], goal_id="blocked-telemetry")
            from omh.workflows.goal_ledger import record_goal_blocker

            goal = record_goal_blocker(paths, "blocked-telemetry", "Permission unavailable", mark_goal_blocked=True)
            self.assertEqual(goal["telemetry"][-1]["event"], "blocked")
            self.assertEqual(goal["telemetry"][-1]["status"], "blocked")
            self.assertNotIn("Permission unavailable", str(goal["telemetry"]))

    def test_completion_adds_finish_event_and_elapsed_duration(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            create_goal_ledger(paths, "bounded objective", ["tests pass"], goal_id="finish-telemetry")
            record_goal_checkpoint(
                paths, "finish-telemetry", "Tests pass", criteria_refs=["AC001"],
                evidence_refs=["artifact:test-report"], status="done",
            )
            result = complete_goal_ledger(
                paths, "finish-telemetry", evidence_refs=["artifact:completion-report"]
            )
            self.assertTrue(result["completed"])
            events = result["goal"]["telemetry"]
            self.assertEqual([event["event"] for event in events], ["start", "checkpoint", "finish"])
            self.assertGreaterEqual(events[-1]["duration_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
