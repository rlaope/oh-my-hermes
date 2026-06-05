from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.coding_lifecycle import (
    CodingLifecycleError,
    record_codex_dispatch,
    record_codex_result,
    record_codex_verification,
    report_codex_delegation_lifecycle,
    start_codex_delegation_lifecycle,
)
from omh.paths import resolve_paths


class CodingLifecycleTests(unittest.TestCase):
    def test_start_codex_lifecycle_creates_prepared_handoff_without_raw_message(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "risky refactor with private-token-123"

            payload = start_codex_delegation_lifecycle(paths, message, source="discord", source_metadata={"source_event_id": "m1"})

            run_id = payload["run"]["run_id"]
            record = payload["coding_delegation"]
            self.assertEqual(payload["schema_version"], "coding_lifecycle/v1")
            self.assertEqual(payload["status"]["lifecycle_status"], "prepared")
            self.assertEqual(payload["status"]["next_action"], "dispatch_to_executor")
            self.assertEqual(record["executor_handoff"]["executor_target"], "codex")
            self.assertFalse(payload["status"]["execution"]["observed"])
            self.assertNotIn(message, json.dumps(payload))
            self.assertTrue((paths.runtime_runs_dir / run_id / "coding_delegation.json").exists())

    def test_lifecycle_records_never_persist_raw_task_message(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "diagnose installation health with private-token-123"

            started = start_codex_delegation_lifecycle(paths, message)
            run_id = started["run"]["run_id"]
            record_codex_dispatch(paths, run_id)
            record_codex_result(paths, run_id, result="completed", evidence_refs=["codex-log"])
            record_codex_verification(paths, run_id)

            run_dir = paths.runtime_runs_dir / run_id
            for artifact in ("coding_delegation.json", "wrapper.json", "delegation.json"):
                self.assertNotIn(message, (run_dir / artifact).read_text(encoding="utf-8"))

    def test_record_codex_dispatch_advances_to_waiting_for_executor_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = start_codex_delegation_lifecycle(paths, "diagnose installation health")

            payload = record_codex_dispatch(paths, started["run"]["run_id"])

            self.assertTrue(payload["wrapper"]["prompt_dispatched"])
            self.assertEqual(payload["status"]["next_action"], "wait_for_executor_evidence")
            self.assertEqual(payload["status"]["lifecycle_status"], "dispatched")
            self.assertFalse(payload["status"]["can_report_completion"])

    def test_record_codex_result_requires_dispatch_first(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = start_codex_delegation_lifecycle(paths, "diagnose installation health")

            with self.assertRaises(CodingLifecycleError):
                record_codex_result(paths, started["run"]["run_id"], result="completed")

    def test_blocked_codex_result_surfaces_blocker(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = start_codex_delegation_lifecycle(paths, "diagnose installation health")
            run_id = started["run"]["run_id"]
            record_codex_dispatch(paths, run_id)

            payload = record_codex_result(paths, run_id, result="blocked", evidence_refs=["codex-log"])

            self.assertEqual(payload["status"]["next_action"], "surface_executor_blocker")
            self.assertEqual(payload["status"]["lifecycle_status"], "blocked")
            self.assertFalse(payload["status"]["can_report_completion"])

    def test_review_required_blocks_completion_even_after_verification(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = start_codex_delegation_lifecycle(paths, "risky refactor")
            run_id = started["run"]["run_id"]
            record_codex_dispatch(paths, run_id)
            record_codex_result(paths, run_id, result="completed", evidence_refs=["codex-log"])

            payload = record_codex_verification(paths, run_id)

            self.assertTrue(payload["status"]["review"]["required"])
            self.assertEqual(payload["status"]["next_action"], "record_review_evidence")
            self.assertFalse(payload["status"]["can_report_completion"])
            self.assertIn("review evidence", payload["status"]["blocking_reason"])

    def test_completion_requires_dispatch_execution_and_verification(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = start_codex_delegation_lifecycle(paths, "diagnose installation health")
            run_id = started["run"]["run_id"]
            record_codex_dispatch(paths, run_id)
            record_codex_result(paths, run_id, result="completed", evidence_refs=["codex-log"])

            before = report_codex_delegation_lifecycle(paths, run_id)
            self.assertEqual(before["next_action"], "record_verification_evidence")
            self.assertFalse(before["can_report_completion"])

            after = record_codex_verification(paths, run_id)
            self.assertEqual(after["status"]["next_action"], "report_completion_with_evidence")
            self.assertTrue(after["status"]["can_report_completion"])

    def test_failed_or_gapped_verification_is_not_reportable(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = start_codex_delegation_lifecycle(paths, "diagnose installation health")
            run_id = started["run"]["run_id"]
            record_codex_dispatch(paths, run_id)
            record_codex_result(paths, run_id, result="completed", evidence_refs=["codex-log"])

            payload = record_codex_verification(paths, run_id, completion_status="failed", gaps=["tests failed"])

            self.assertFalse(payload["wrapper"]["verification_observed"])
            self.assertEqual(payload["wrapper"]["completion_status"], "failed")
            self.assertEqual(payload["status"]["next_action"], "record_verification_evidence")
            self.assertFalse(payload["status"]["can_report_completion"])
            self.assertIn("tests failed", payload["status"]["wrapper"]["unobserved_gaps"])

    def test_verification_before_executor_result_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = start_codex_delegation_lifecycle(paths, "diagnose installation health")
            run_id = started["run"]["run_id"]
            record_codex_dispatch(paths, run_id)

            with self.assertRaises(CodingLifecycleError):
                record_codex_verification(paths, run_id)


if __name__ == "__main__":
    unittest.main()
