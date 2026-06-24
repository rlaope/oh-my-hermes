from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()
from omh.context_safety import build_coding_progress_reporting_policy, build_progress_event, raw_output_artifact_ref


class ContextSafetyTests(unittest.TestCase):
    def test_coding_progress_reporting_policy_is_event_triggered_and_metadata_only(self) -> None:
        policy = build_coding_progress_reporting_policy(
            next_action="record_verification_evidence",
            lifecycle_status="awaiting_verification",
        )

        rendered = json.dumps(policy)
        self.assertEqual(policy["schema_version"], "coding_progress_reporting_policy/v1")
        self.assertEqual(policy["mode"], "event_triggered")
        self.assertTrue(policy["timed_polling_rejected"])
        self.assertTrue(policy["metadata_only"])
        self.assertFalse(policy["raw_content_included"])
        self.assertTrue(policy["language_policy"]["korean_friendly"])
        self.assertTrue(policy["language_policy"]["mirror_chat_language"])
        for event in (
            "workflow_started",
            "dispatch_to_executor",
            "blocker_encountered",
            "targeted_tests_failed",
            "root_cause_identified",
            "fix_strategy_selected",
            "targeted_tests_passed",
            "full_tests_started",
            "full_tests_passed",
            "commit_created",
            "pr_updated",
            "workflow_completed",
        ):
            self.assertIn(event, policy["reportable_events"])
        self.assertIn("full_tests_started", policy["state_guidance"]["reportable_events"])
        self.assertIn("not execution, review, CI", policy["evidence_boundary"])
        self.assertNotIn("private-token-123", rendered)

    def test_policy_reportable_events_are_progress_event_types(self) -> None:
        policy = build_coding_progress_reporting_policy(next_action="dispatch_to_executor")

        for event_type in policy["reportable_events"]:
            event = build_progress_event(event_type, f"{event_type} update")
            self.assertEqual(event["event_type"], event_type)

    def test_progress_event_compacts_raw_payloads_for_chat_context(self) -> None:
        raw_log = "traceback " + ("Z" * 5000)
        artifact = raw_output_artifact_ref(raw_log, source="codex-long-run.jsonl")

        event = build_progress_event(
            "root_cause_identified",
            "Root cause identified: setup default executor propagation was missing.\n```json\n" + raw_log + "\n```",
            status="observed",
            severity="warning",
            file_refs=["src/wrapper/contract.py", "src/coding/coding_delegation.py", "x" * 1000],
            artifact_refs=[artifact],
            evidence_refs=[f"ref-{index}" for index in range(20)],
        )

        rendered = json.dumps(event)
        self.assertEqual(event["schema_version"], "omh_progress_event/v1")
        self.assertEqual(event["event_type"], "root_cause_identified")
        self.assertEqual(event["status"], "observed")
        self.assertEqual(event["severity"], "warning")
        self.assertLessEqual(len(event["summary"]), 220)
        self.assertLessEqual(len(event["file_refs"]), 8)
        self.assertLessEqual(max(len(ref) for ref in event["file_refs"]), 160)
        self.assertLessEqual(len(event["evidence_refs"]), 8)
        self.assertEqual(event["artifact_refs"][0]["schema_version"], "omh_context_artifact_ref/v1")
        self.assertFalse(event["artifact_refs"][0]["raw_content_included"])
        self.assertNotIn("```", rendered)
        self.assertNotIn("Z" * 1000, rendered)
        self.assertIn("not execution", event["claim_boundary"])


if __name__ == "__main__":
    unittest.main()
