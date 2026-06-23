from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()
from omh.work_reporting import (
    build_background_completion_report,
    build_markdown_export,
    build_work_observation_summary,
    build_work_observation_summary_from_status,
    format_check_rollup,
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

    def test_status_projection_advances_after_dispatch_even_if_prepared_status_remains(self) -> None:
        status_payload = {
            "schema_version": "delegated_coding_status/v1",
            "run_id": "run-dispatched",
            "prepared": {
                "workflow": "plan",
                "harness": "coding-handling",
                "status": "prepared_not_observed",
                "executor_target": "codex",
            },
            "wrapper": {"prompt_dispatched": True, "completion_status": "started"},
            "execution": {"observed": False, "status": "not_observed", "evidence_refs": []},
            "verification": {"observed": False, "status": "not_observed", "satisfied": False, "expected": ["pytest"]},
            "review": {"required": False, "observed": True, "status": "not_required", "satisfied": True, "evidence_refs": []},
            "ci": {"required": False, "observed": True, "status": "not_required", "satisfied": True, "evidence_refs": []},
            "merge": {"required": False, "observed": True, "status": "not_required", "satisfied": True, "evidence_refs": []},
            "next_action": "wait_for_executor_evidence",
            "lifecycle_status": "dispatched",
            "safe_summary": "A codex coding handoff was dispatched, but executor completion is not observed yet.",
        }

        summary = build_work_observation_summary_from_status(status_payload, report_kind="progress")
        rendered = render_progress_report(summary)

        self.assertEqual(validate_work_observation_summary(summary), [])
        self.assertEqual(summary["status"], "in_progress")
        self.assertIn("in progress", rendered)
        self.assertNotIn("prepared but not observed", rendered)
        self.assertIn("execution", summary["evidence_boundary"]["not_evidence_until_observed"])

    def test_status_projection_advances_after_executor_result_even_if_prepared_status_remains(self) -> None:
        status_payload = {
            "schema_version": "delegated_coding_status/v1",
            "run_id": "run-awaiting-verification",
            "prepared": {
                "workflow": "plan",
                "harness": "coding-handling",
                "status": "prepared_not_observed",
                "executor_target": "codex",
            },
            "wrapper": {"prompt_dispatched": True, "completion_status": "started"},
            "execution": {"observed": True, "status": "completed", "evidence_refs": ["executor-result.json"]},
            "verification": {"observed": False, "status": "not_observed", "satisfied": False, "expected": ["pytest"]},
            "review": {"required": False, "observed": True, "status": "not_required", "satisfied": True, "evidence_refs": []},
            "ci": {"required": False, "observed": True, "status": "not_required", "satisfied": True, "evidence_refs": []},
            "merge": {"required": False, "observed": True, "status": "not_required", "satisfied": True, "evidence_refs": []},
            "next_action": "record_verification_evidence",
            "lifecycle_status": "awaiting_verification",
            "safe_summary": "The codex executor is observed as completed, but verification evidence is not observed yet.",
        }

        summary = build_work_observation_summary_from_status(status_payload, report_kind="progress")
        rendered = render_progress_report(summary)

        self.assertEqual(validate_work_observation_summary(summary), [])
        self.assertEqual(summary["status"], "in_progress")
        self.assertEqual(summary["observations"]["evidence_refs"], ["executor-result.json"])
        self.assertIn("in progress", rendered)
        self.assertIn("executor-result.json", rendered)
        self.assertNotIn("prepared but not observed", rendered)

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
            "verification": {"observed": True, "status": "passed", "satisfied": True, "expected": ["pytest"]},
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

    def test_completion_report_does_not_render_default_boundaries_as_active_gaps(self) -> None:
        summary = build_work_observation_summary(
            work_id="run-complete-boundary",
            title="Completed runtime report",
            report_kind="completion",
            status="completed",
            observed_events=[
                {"event_type": "execution", "status": "observed", "evidence_refs": ["executor-result.json"]},
                {"event_type": "verification", "status": "observed", "evidence_refs": ["pytest"]},
            ],
        )

        rendered = render_completion_report(summary)

        self.assertEqual(validate_work_observation_summary(summary), [])
        self.assertIn("execution", summary["evidence_boundary"]["not_evidence_until_observed"])
        self.assertEqual(summary["evidence_boundary"]["active_not_observed_gaps"], [])
        self.assertIn("Completed: Completed runtime report.", rendered)
        self.assertIn("Claim rule:", rendered)
        self.assertNotIn("Still waiting on observed proof", rendered)
        self.assertNotIn("prepared_not_observed", rendered)

    def test_status_report_renders_only_actual_unobserved_gaps(self) -> None:
        summary = build_work_observation_summary(
            work_id="run-ci-gap",
            title="Runtime report with CI gap",
            report_kind="status",
            status="in_progress",
            observed_events=[
                {"event_type": "execution", "status": "observed", "evidence_refs": ["executor-result.json"]},
                {"event_type": "ci", "status": "not_observed", "evidence_refs": ["ci-placeholder"]},
            ],
            next_action="record_ci_evidence",
        )

        rendered = render_status_report(summary)

        self.assertEqual(validate_work_observation_summary(summary), [])
        self.assertEqual(summary["evidence_boundary"]["active_not_observed_gaps"], ["ci"])
        self.assertIn("Still waiting on observed proof for: ci.", rendered)
        self.assertNotIn("Still waiting on observed proof for: prepared_not_observed", rendered)
        self.assertNotIn("execution, verification, review", rendered)
        self.assertNotIn("ci-placeholder", rendered)

    def test_status_projection_rejects_terminal_completion_when_verification_failed(self) -> None:
        status_payload = {
            "schema_version": "delegated_coding_status/v1",
            "run_id": "run-failed-verification",
            "prepared": {
                "workflow": "plan",
                "harness": "coding-handling",
                "status": "prepared_not_observed",
                "executor_target": "codex",
            },
            "execution": {"observed": True, "status": "completed", "evidence_refs": ["executor-result.json"]},
            "verification": {
                "observed": True,
                "status": "failed",
                "satisfied": False,
                "expected": ["pytest"],
                "evidence_refs": ["pytest-failed"],
            },
            "review": {"required": False, "observed": True, "status": "not_required", "satisfied": True, "evidence_refs": []},
            "ci": {"required": False, "observed": True, "status": "not_required", "satisfied": True, "evidence_refs": []},
            "merge": {"required": False, "observed": True, "status": "not_required", "satisfied": True, "evidence_refs": []},
            "next_action": "report_completion_with_evidence",
            "lifecycle_status": "reportable",
            "safe_summary": "Verification failed after executor completion.",
        }

        summary = build_work_observation_summary_from_status(status_payload, report_kind="completion")
        rendered = render_completion_report(summary)

        self.assertEqual(validate_work_observation_summary(summary), [])
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["observations"]["evidence_refs"], ["executor-result.json", "pytest-failed"])
        self.assertIn("Completion is not observed yet", rendered)
        self.assertIn("pytest-failed", rendered)
        self.assertNotIn("Completed:", rendered)

    def test_runtime_observation_terminal_events_override_in_progress_status(self) -> None:
        for field, event_status, expected_status in (
            ("failed_events", "failed", "failed"),
            ("blocked_events", "blocked", "blocked"),
        ):
            with self.subTest(field=field):
                status_payload = {
                    "schema_version": "delegated_coding_status/v1",
                    "run_id": f"run-runtime-{event_status}",
                    "prepared": {
                        "workflow": "team",
                        "harness": "coding-handling",
                        "status": "prepared_not_observed",
                        "executor_target": "omx-runtime",
                    },
                    "wrapper": {"prompt_dispatched": True, "completion_status": "started"},
                    "execution": {"observed": False, "status": "not_observed", "evidence_refs": []},
                    "verification": {"observed": False, "status": "not_observed", "satisfied": False, "evidence_refs": []},
                    "review": {"required": False, "observed": True, "status": "not_required", "satisfied": True},
                    "ci": {"required": False, "observed": True, "status": "not_required", "satisfied": True},
                    "merge": {"required": False, "observed": True, "status": "not_required", "satisfied": True},
                    "runtime_observation": {
                        "observed_events": [],
                        field: ["worker_result"],
                        "latest": {
                            "worker_result": {
                                "event_type": "worker_result",
                                "status": event_status,
                                "summary": f"worker result is {event_status}",
                                "evidence_refs": [f"runtime/runtime_observations.jsonl#{event_status}"],
                            },
                        },
                    },
                    "next_action": "wait_for_executor_evidence",
                    "lifecycle_status": "running",
                    "safe_summary": f"Runtime observation is {event_status}.",
                }

                summary = build_work_observation_summary_from_status(status_payload, report_kind="status")

                self.assertEqual(validate_work_observation_summary(summary), [])
                self.assertEqual(summary["status"], expected_status)
                self.assertIn(f"runtime/runtime_observations.jsonl#{event_status}", summary["observations"]["evidence_refs"])

    def test_status_projection_preserves_runtime_latest_event_evidence(self) -> None:
        status_payload = {
            "schema_version": "delegated_coding_status/v1",
            "run_id": "run-runtime-latest",
            "prepared": {
                "workflow": "team",
                "harness": "coding-handling",
                "status": "prepared_not_observed",
                "executor_target": "omx-runtime",
            },
            "wrapper": {"prompt_dispatched": True, "completion_status": "started"},
            "execution": {"observed": False, "status": "not_observed", "evidence_refs": []},
            "verification": {"observed": False, "status": "not_observed", "satisfied": False, "evidence_refs": []},
            "review": {"required": False, "observed": True, "status": "not_required", "satisfied": True, "evidence_refs": []},
            "ci": {"required": True, "observed": False, "status": "pending", "evidence_refs": []},
            "merge": {"required": True, "observed": False, "status": "not_observed", "evidence_refs": []},
            "runtime_observation": {
                "observed_events": ["worker_result", "verification"],
                "blocked_events": [],
                "failed_events": [],
                "not_observed_events": ["ci"],
                "missing_events": ["review", "merge"],
                "latest": {
                    "worker_result": {
                        "event_type": "worker_result",
                        "status": "observed",
                        "summary": "worker reported completion metadata",
                        "evidence_refs": ["runtime/runtime_observations.jsonl#worker_result"],
                    },
                    "verification": {
                        "event_type": "verification",
                        "status": "observed",
                        "summary": "focused tests passed",
                        "evidence_refs": ["pytest tests/test_work_reporting.py -v"],
                    },
                    "ci": {
                        "event_type": "ci",
                        "status": "not_observed",
                        "summary": "CI is pending",
                        "evidence_refs": ["ci-placeholder"],
                    },
                },
            },
            "next_action": "record_ci_evidence",
            "lifecycle_status": "awaiting_ci",
            "safe_summary": "Runtime handoff has worker and verification observations; CI is not observed.",
        }

        summary = build_work_observation_summary_from_status(status_payload, report_kind="progress")
        rendered = render_progress_report(summary)
        events = {event["event_type"]: event for event in summary["observations"]["events"]}

        self.assertEqual(validate_work_observation_summary(summary), [])
        self.assertEqual(summary["status"], "in_progress")
        self.assertEqual(
            summary["observations"]["evidence_refs"],
            ["runtime/runtime_observations.jsonl#worker_result", "pytest tests/test_work_reporting.py -v"],
        )
        self.assertEqual(events["worker_result"]["summary"], "worker reported completion metadata")
        self.assertEqual(events["worker_result"]["evidence_refs"], ["runtime/runtime_observations.jsonl#worker_result"])
        self.assertEqual(events["verification"]["evidence_refs"], ["pytest tests/test_work_reporting.py -v"])
        self.assertEqual(events["ci"]["status"], "not_observed")
        self.assertEqual(events["ci"]["evidence_refs"], [])
        self.assertIn("ci", summary["observations"]["not_observed_events"])
        self.assertIn("runtime/runtime_observations.jsonl#worker_result", rendered)
        self.assertIn("pytest tests/test_work_reporting.py -v", rendered)
        self.assertNotIn("ci-placeholder", summary["observations"]["evidence_refs"])
        self.assertNotIn("ci-placeholder", rendered)

    def test_not_observed_event_refs_do_not_render_as_evidence(self) -> None:
        summary = build_work_observation_summary(
            work_id="run-event-boundary",
            title="Runtime event boundary",
            report_kind="status",
            status="blocked",
            observed_events=[
                {"event_type": "worker_result", "status": "observed", "evidence_refs": ["runtime/result.json"]},
                {"event_type": "verification", "status": "failed", "evidence_refs": ["pytest-failed"]},
                {"event_type": "ci", "status": "not_observed", "evidence_refs": ["ci-placeholder"]},
            ],
            next_action="record_ci_evidence",
        )
        rendered = render_status_report(summary)

        ci_event = next(event for event in summary["observations"]["events"] if event["event_type"] == "ci")

        self.assertEqual(validate_work_observation_summary(summary), [])
        self.assertEqual(summary["observations"]["evidence_refs"], ["runtime/result.json", "pytest-failed"])
        self.assertEqual(ci_event["evidence_refs"], [])
        self.assertIn("ci", summary["observations"]["not_observed_events"])
        self.assertIn("runtime/result.json", rendered)
        self.assertIn("pytest-failed", rendered)
        self.assertNotIn("ci-placeholder", summary["observations"]["evidence_refs"])
        self.assertNotIn("ci-placeholder", rendered)

    def test_pending_observation_status_does_not_promote_placeholder_evidence(self) -> None:
        summary = build_work_observation_summary(
            work_id="run-pending-ci",
            title="Pending CI",
            observed_events=[{"event_type": "ci", "status": "pending", "evidence_refs": ["ci-placeholder"]}],
        )
        rendered = render_status_report(summary)
        ci_event = next(event for event in summary["observations"]["events"] if event["event_type"] == "ci")

        self.assertEqual(validate_work_observation_summary(summary), [])
        self.assertEqual(ci_event["status"], "not_observed")
        self.assertEqual(ci_event["evidence_refs"], [])
        self.assertIn("ci", summary["observations"]["not_observed_events"])
        self.assertNotIn("ci-placeholder", summary["observations"]["evidence_refs"])
        self.assertNotIn("ci-placeholder", rendered)

    def test_minimal_completed_status_payload_does_not_report_absent_optional_gates_as_gaps(self) -> None:
        status_payload = {
            "run_id": "run-minimal-complete",
            "prepared": {"status": "prepared_not_observed", "workflow": "plan", "harness": "coding"},
            "execution": {"observed": True, "status": "completed", "evidence_refs": ["exec"]},
            "verification": {"observed": True, "status": "passed", "satisfied": True, "evidence_refs": ["pytest"]},
            "next_action": "report_completion_with_evidence",
            "lifecycle_status": "reportable",
        }

        summary = build_work_observation_summary_from_status(status_payload, report_kind="completion")
        rendered = render_completion_report(summary)

        self.assertEqual(validate_work_observation_summary(summary), [])
        self.assertEqual(summary["status"], "completed")
        self.assertNotIn("review", summary["observations"]["not_observed_events"])
        self.assertNotIn("ci", summary["observations"]["not_observed_events"])
        self.assertNotIn("merge", summary["observations"]["not_observed_events"])
        self.assertNotIn("Still waiting on observed proof for", rendered)

    def test_runtime_observation_only_completion_overrides_legacy_stage_gaps(self) -> None:
        status_payload = {
            "run_id": "run-runtime-complete",
            "prepared": {"status": "prepared_not_observed", "workflow": "team", "harness": "coding"},
            "execution": {"observed": False, "status": "not_observed", "evidence_refs": []},
            "verification": {"observed": False, "status": "not_observed", "evidence_refs": []},
            "runtime_observation": {
                "observed_events": ["worker_result", "verification"],
                "blocked_events": [],
                "failed_events": [],
                "not_observed_events": [],
                "missing_events": [],
                "latest": {
                    "worker_result": {
                        "status": "observed",
                        "summary": "runtime worker completed",
                        "evidence_refs": ["runtime/result.jsonl#worker_result"],
                    },
                    "verification": {
                        "status": "passed",
                        "summary": "runtime verification passed",
                        "evidence_refs": ["runtime/result.jsonl#verification"],
                    },
                },
            },
            "next_action": "report_runtime_observed",
            "lifecycle_status": "reportable",
        }

        summary = build_work_observation_summary_from_status(status_payload, report_kind="completion")
        rendered = render_completion_report(summary)

        self.assertEqual(validate_work_observation_summary(summary), [])
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["observations"]["not_observed_events"], [])
        self.assertIn("runtime/result.jsonl#worker_result", summary["observations"]["evidence_refs"])
        self.assertIn("runtime/result.jsonl#verification", summary["observations"]["evidence_refs"])
        self.assertNotIn("Still waiting on observed proof for", rendered)

    def test_empty_successful_background_completion_is_silent(self) -> None:
        rendered = build_background_completion_report(
            output="[Background process proc_b05484479563 finished with exit code 0~ Here's the final output:]",
        )

        self.assertIsNone(rendered)

    def test_background_check_output_renders_compact_rollup_not_watch_transcript(self) -> None:
        raw_watch_output = "\n".join(
            [
                "Refreshing checks status every 10 seconds. Press Ctrl+C to quit.",
                "DCO\tpass\t4s\thttps://github.example/checks/dco",
                "unit tests\tpass\t2m10s\thttps://github.example/checks/tests",
                "Codex review\tpending\t\thttps://github.example/checks/review",
                "Refreshing checks status every 10 seconds. Press Ctrl+C to quit.",
                "DCO\tpass\t4s\thttps://github.example/checks/dco",
                "unit tests\tpass\t2m10s\thttps://github.example/checks/tests",
                "Codex review\tpending\t\thttps://github.example/checks/review",
            ]
        )

        rendered = build_background_completion_report(
            exit_code=0,
            command="gh pr checks --watch",
            output=raw_watch_output,
        )

        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertIn("Checks: 1 pending, 2 pass.", rendered)
        self.assertIn("- DCO: pass (4s) https://github.example/checks/dco.", rendered)
        self.assertIn("- unit tests: pass (2m10s) https://github.example/checks/tests.", rendered)
        self.assertIn("- Codex review: pending https://github.example/checks/review.", rendered)
        self.assertNotIn("Refreshing checks status", rendered)
        self.assertNotIn("Press Ctrl+C", rendered)
        self.assertNotIn("Background process", rendered)
        self.assertNotIn("Here's the final output", rendered)

    def test_background_completion_does_not_mislabel_plain_command_output_as_checks(self) -> None:
        rendered = build_background_completion_report(
            exit_code=0,
            command="pytest tests/test_work_reporting.py",
            output="1 passed in 0.2s",
        )

        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertIn("completed successfully", rendered)
        self.assertIn("1 passed in 0.2s", rendered)
        self.assertNotIn("Checks:", rendered)
        self.assertNotIn("Checks: 1 pass", rendered)

    def test_background_completion_can_summarize_tabular_check_output_without_command_hint(self) -> None:
        rendered = build_background_completion_report(
            exit_code=0,
            output="DCO\tpass\t4s\thttps://github.example/checks/dco",
        )

        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertIn("Checks: 1 pass.", rendered)
        self.assertIn("- DCO: pass (4s) https://github.example/checks/dco.", rendered)

    def test_structured_check_rollup_keeps_status_duration_and_links(self) -> None:
        rendered = format_check_rollup(
            [
                {
                    "name": "DCO",
                    "status": "completed",
                    "conclusion": "success",
                    "duration": "3s",
                    "url": "https://github.example/checks/dco",
                },
                {
                    "name": "integration tests",
                    "status": "in_progress",
                    "duration": "1m",
                    "url": "https://github.example/checks/integration",
                },
            ]
        )

        self.assertIn("Checks: 1 pending, 1 pass.", rendered)
        self.assertIn("- DCO: pass (3s) https://github.example/checks/dco.", rendered)
        self.assertIn("- integration tests: pending (1m) https://github.example/checks/integration.", rendered)

    def test_structured_check_completed_without_success_conclusion_is_unknown(self) -> None:
        rendered = format_check_rollup(
            [
                {
                    "name": "lint",
                    "status": "completed",
                    "duration": "5s",
                    "url": "https://github.example/checks/lint",
                }
            ]
        )

        self.assertIn("Checks: 1 unknown.", rendered)
        self.assertIn("- lint: unknown (5s) https://github.example/checks/lint.", rendered)
        self.assertNotIn("1 pass", rendered)
        self.assertNotIn("lint: pass", rendered)

    def test_friendly_korean_progress_report_uses_channel_voice(self) -> None:
        summary = build_work_observation_summary(
            work_id="run-ko-friendly",
            title="PR #259",
            report_kind="progress",
            status="in_progress",
            safe_summary="CI는 통과했고, 지금은 리뷰만 다시 확인 중이야.",
            progress_events=[
                {
                    "event_type": "status_update",
                    "status": "observed",
                    "summary": "CI는 통과했고, 지금은 리뷰만 다시 확인 중이야.",
                }
            ],
            evidence_refs=["https://github.example/checks/tests"],
            next_action="record_review_evidence",
        )

        rendered = render_progress_report(summary, locale="ko", voice="friendly")

        self.assertIn("PR #259 작업은 진행 중이야.", rendered)
        self.assertIn("CI는 통과했고, 지금은 리뷰만 다시 확인 중이야.", rendered)
        self.assertIn("확인한 근거: https://github.example/checks/tests.", rendered)
        self.assertIn("다음은 record_review_evidence 쪽을 볼게.", rendered)
        self.assertNotIn("Progress:", rendered)
        self.assertNotIn("Next:", rendered)
        self.assertNotIn("Evidence boundary", rendered)
        self.assertNotIn("한다", rendered)

    def test_korean_progress_report_voice_is_explicit_and_deterministic(self) -> None:
        summary = build_work_observation_summary(
            work_id="run-ko-voice",
            title="PR #259",
            report_kind="progress",
            status="in_progress",
            safe_summary="CI는 통과했고, 리뷰 결과를 다시 확인 중입니다.",
            progress_events=[
                {
                    "event_type": "status_update",
                    "status": "observed",
                    "summary": "CI는 통과했고, 리뷰 결과를 다시 확인 중입니다.",
                }
            ],
            evidence_refs=["https://github.example/checks/tests"],
            next_action="record_review_evidence",
        )

        friendly = render_progress_report(summary, locale="ko", voice="friendly")
        polite = render_progress_report(summary, locale="ko", voice="polite")
        formal = render_progress_report(summary, locale="ko", voice="formal")
        default_ko = render_progress_report(summary, locale="ko")

        self.assertIn("PR #259 작업은 진행 중이야.", friendly)
        self.assertIn("다음은 record_review_evidence 쪽을 볼게.", friendly)
        self.assertIn("PR #259 작업은 진행 중입니다.", polite)
        self.assertIn("다음은 record_review_evidence 항목을 확인하겠습니다.", polite)
        self.assertEqual(formal, polite)
        self.assertEqual(default_ko, polite)
        self.assertNotIn("진행 중이야", polite)
        self.assertNotIn("볼게", polite)
        self.assertNotIn("Progress:", polite)

    def test_user_report_scrubs_awareness_and_native_bridge_context(self) -> None:
        internal_context = """
        [OMH Awareness]
        ## OMH Awareness Primer
        [OMH] Native bridge status context.
        Evidence boundary: prepared handoffs are not execution, review, CI, merge-readiness, or merge evidence.
        Latest runtime run: run-raw.
        """
        summary = build_work_observation_summary(
            work_id="run-internal-rails",
            title="Native bridge context",
            report_kind="progress",
            status="in_progress",
            safe_summary=internal_context,
            progress_events=[
                {
                    "event_type": "status_update",
                    "status": "observed",
                    "summary": internal_context,
                }
            ],
        )

        rendered = render_progress_report(summary, locale="ko", voice="friendly")

        self.assertIn("내부 OMH 상태는 확인했고", rendered)
        self.assertNotIn("[OMH Awareness]", rendered)
        self.assertNotIn("Native bridge status context", rendered)
        self.assertNotIn("Evidence boundary: prepared handoffs", rendered)


if __name__ == "__main__":
    unittest.main()
