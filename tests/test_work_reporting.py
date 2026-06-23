from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()
from omh.work_reporting import (
    build_markdown_export,
    build_work_observation_summary,
    build_work_observation_summary_from_status,
    render_status_report,
    render_blocker_report,
    render_completion_report,
    render_progress_report,
    validate_markdown_export,
    validate_work_observation_summary,
)


class WorkReportingTests(unittest.TestCase):
    def test_plain_text_reports_are_default_and_not_json_or_code_fences(self) -> None:
        summary = build_work_observation_summary(
            work_id="run-123",
            title="Observation reporting vertical slice",
            report_kind="progress",
            status="in_progress",
            workflow="ultragoal",
            harness="goal-execution",
            source_message="private user request with token-secret-123",
            progress_events=[
                {
                    "event_type": "workflow_started",
                    "status": "running",
                    "summary": "Implementation is underway and scoped to reporting contracts.",
                    "evidence_refs": ["tests/test_work_reporting.py"],
                }
            ],
            next_action="run_targeted_tests",
        )

        progress = render_progress_report(summary)
        completion = render_completion_report({**summary, "report_kind": "completion", "status": "completed"})

        self.assertEqual(validate_work_observation_summary(summary), [])
        self.assertEqual(summary["user_report"]["default_format"], "plain_text")
        self.assertFalse(summary["user_report"]["json_default"])
        self.assertFalse(summary["user_report"]["code_block_default"])
        status_report = render_status_report(summary)

        for rendered in (progress, completion, status_report):
            self.assertNotIn("```", rendered)
            self.assertNotIn("{", rendered)
            self.assertNotIn("}", rendered)
            self.assertNotIn("schema_version", rendered)
            self.assertNotIn("token-secret-123", rendered)

    def test_structured_summary_is_metadata_only_with_evidence_boundaries(self) -> None:
        secret_message = "ship the reporting feature with private-token-456"
        summary = build_work_observation_summary(
            work_id="runtime:abc",
            title="Runtime observation",
            report_kind="completion",
            status="completed",
            workflow="agent-ops-review",
            harness="agent-ops-review",
            source_message=secret_message,
            evidence_refs=["runtime/run.json", "runtime/runtime_observations.jsonl"],
            prepared_refs=["coding_runtime_handoff/v1:runtime:abc"],
            observed_events=[
                {"event_type": "worker_result", "status": "observed", "evidence_refs": ["runtime/runtime_observations.jsonl"]},
                {"event_type": "verification", "status": "observed", "evidence_refs": ["pytest"]},
            ],
        )

        serialized = json.dumps(summary, sort_keys=True)

        self.assertEqual(validate_work_observation_summary(summary), [])
        self.assertEqual(summary["schema_version"], "work_observation_summary/v1")
        self.assertTrue(summary["privacy"]["metadata_only"])
        self.assertFalse(summary["privacy"]["raw_prompt_stored"])
        self.assertFalse(summary["privacy"]["raw_logs_stored"])
        self.assertEqual(summary["source"]["message_length"], len(secret_message))
        self.assertRegex(summary["source"]["message_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("prepared_not_observed", summary["evidence_boundary"]["not_evidence_until_observed"])
        self.assertIn("review", summary["evidence_boundary"]["not_evidence_until_observed"])
        self.assertIn("runtime/run.json", summary["observations"]["evidence_refs"])
        self.assertNotIn(secret_message, serialized)
        self.assertNotIn("private-token-456", serialized)
        self.assertNotIn("source_message", serialized)

        mutated = json.loads(json.dumps(summary))
        mutated["source"]["raw_message_stored"] = True
        self.assertIn("source raw message must not be stored", validate_work_observation_summary(mutated))

    def test_markdown_export_is_opt_in_secondary_wiki_shape(self) -> None:
        summary = build_work_observation_summary(
            work_id="run-456",
            title="Progress package",
            report_kind="progress",
            status="blocked",
            blockers=["CI evidence has not been observed."],
            evidence_refs=["runtime/ci.json"],
            next_action="record_ci_evidence",
        )

        self.assertNotIn("markdown", summary)
        self.assertEqual(summary["exports"]["markdown"]["default"], False)
        self.assertEqual(summary["exports"]["markdown"]["intended_surface"], "wiki_or_markdown")

        export = build_markdown_export(summary)
        markdown = export["markdown"]

        self.assertEqual(export["schema_version"], "work_report_markdown_export/v1")
        self.assertEqual(validate_markdown_export(export), [])
        self.assertEqual(export["export_mode"], "opt_in")
        self.assertIn("# Progress package", markdown)
        self.assertIn("## Evidence", markdown)
        self.assertIn("runtime/ci.json", markdown)
        self.assertNotIn("```", markdown)
        self.assertNotIn("schema_version", markdown)

    def test_learning_hints_are_bounded_and_sanitized(self) -> None:
        long_note = "```raw``` " + "A" * 400
        summary = build_work_observation_summary(
            work_id="run-learning",
            title="Learning candidate",
            report_kind="completion",
            status="completed",
            workflow="workflow-learning",
            harness="workflow-learning",
            learning_candidate=True,
            learning_notes=long_note,
            evidence_refs=[f"evidence-{index}" for index in range(20)],
        )

        learning = summary["learning"]

        self.assertTrue(learning["candidate"])
        self.assertLessEqual(len(learning["notes"]), 180)
        self.assertNotIn("```", learning["notes"])
        self.assertEqual(len(learning["evidence_refs"]), 8)
        self.assertEqual(learning["omitted"]["evidence_ref_count"], 12)
        self.assertFalse(learning["raw_logs_included"])
        self.assertFalse(learning["raw_prompt_included"])
        self.assertEqual(validate_work_observation_summary(summary), [])

    def test_status_integration_keeps_prepared_boundaries_plain(self) -> None:
        status_payload = {
            "schema_version": "delegated_coding_status/v1",
            "run_id": "run-prepared",
            "prepared": {
                "workflow": "plan",
                "harness": "coding-handling",
                "status": "prepared_not_observed",
                "executor_target": "codex",
            },
            "execution": {"observed": False, "status": "not_observed", "evidence_refs": []},
            "verification": {"observed": False, "expected": ["pytest"]},
            "review": {"required": True, "status": "not_observed", "evidence_refs": []},
            "ci": {"status": "not_observed", "evidence_refs": []},
            "merge": {"status": "not_observed", "evidence_refs": []},
            "runtime_observation": {
                "observed_events": [],
                "missing_events": ["worker_result", "verification", "review", "ci", "merge"],
            },
            "next_action": "dispatch_to_executor",
            "safe_summary": "Coding handoff is prepared, but execution is not observed.",
        }

        summary = build_work_observation_summary_from_status(status_payload, report_kind="progress")
        rendered = render_blocker_report({**summary, "report_kind": "blocker", "status": "blocked"})

        self.assertEqual(validate_work_observation_summary(summary), [])
        self.assertEqual(summary["status"], "prepared_not_observed")
        self.assertEqual(summary["observations"]["prepared_refs"], ["delegated_coding_status/v1:run-prepared"])
        self.assertIn("not observed", rendered.lower())
        self.assertIn("dispatch_to_executor", summary["next_action"])
        self.assertIn("execution", summary["evidence_boundary"]["not_evidence_until_observed"])
        self.assertNotIn("```", rendered)
        self.assertNotIn("{", rendered)

    def test_status_projection_does_not_complete_or_render_unobserved_refs(self) -> None:
        status_payload = {
            "schema_version": "delegated_coding_status/v1",
            "run_id": "run-overclaim",
            "prepared": {
                "workflow": "plan",
                "harness": "coding-handling",
                "status": "prepared_not_observed",
                "executor_target": "codex",
            },
            "execution": {"observed": False, "status": "not_observed", "evidence_refs": ["unobserved-exec.log"]},
            "verification": {"observed": False, "expected": ["pytest"]},
            "review": {"required": True, "observed": False, "status": "pending", "evidence_refs": ["pending-review.md"]},
            "ci": {"required": True, "observed": False, "status": "pending", "evidence_refs": ["pending-ci"]},
            "merge": {"required": True, "observed": False, "status": "not_observed", "evidence_refs": ["pending-merge"]},
            "next_action": "report_completion_with_evidence",
            "lifecycle_status": "reportable",
            "safe_summary": "Terminal labels are inconsistent with observed evidence.",
        }

        summary = build_work_observation_summary_from_status(status_payload, report_kind="completion")
        rendered = render_completion_report(summary)

        self.assertEqual(validate_work_observation_summary(summary), [])
        self.assertEqual(summary["status"], "prepared_not_observed")
        self.assertEqual(summary["observations"]["evidence_refs"], [])
        self.assertIn("Completion is not observed yet", rendered)
        self.assertNotIn("Completed:", rendered)
        self.assertNotIn("unobserved-exec.log", rendered)
        self.assertNotIn("pending-review.md", rendered)
        self.assertNotIn("pending-ci", rendered)

    def test_status_projection_completes_only_with_observed_stage_evidence(self) -> None:
        status_payload = {
            "schema_version": "delegated_coding_status/v1",
            "run_id": "run-complete",
            "prepared": {
                "workflow": "plan",
                "harness": "coding-handling",
                "status": "prepared_not_observed",
                "executor_target": "codex",
            },
            "execution": {"observed": True, "status": "completed", "evidence_refs": ["executor-result.json"]},
            "verification": {"observed": True, "expected": ["pytest"]},
            "review": {"required": False, "observed": True, "status": "not_required", "satisfied": True, "evidence_refs": []},
            "ci": {"required": False, "observed": True, "status": "not_required", "satisfied": True, "evidence_refs": []},
            "merge": {"required": False, "observed": True, "status": "not_required", "satisfied": True, "evidence_refs": []},
            "next_action": "report_completion_with_evidence",
            "lifecycle_status": "reportable",
        }

        summary = build_work_observation_summary_from_status(status_payload, report_kind="completion")
        rendered = render_completion_report(summary)

        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["observations"]["evidence_refs"], ["executor-result.json"])
        self.assertIn("Completed: Work status for run-complete.", rendered)
        self.assertIn("executor-result.json", rendered)


if __name__ == "__main__":
    unittest.main()
