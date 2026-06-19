from __future__ import annotations

import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from _local_package import load_local_package

load_local_package()
from omh.paths import resolve_paths
from omh.workflow_learning import (
    attach_learning_trace_ref_to_interaction,
    build_improvement_candidate,
    build_regression_case_from_trace,
    build_trace_from_chat_interaction,
    build_workflow_eval_result,
    learning_trace_ref,
    list_learning_traces,
    replay_regression_cases,
    validate_workflow_learning_trace,
    write_learning_trace,
    write_regression_case,
)
from omh.wrapper.contract import build_chat_interaction_payload


class WorkflowLearningTests(unittest.TestCase):
    def test_chat_trace_is_metadata_only_and_ref_is_explicit_attachment(self) -> None:
        message = "I want to safely add a feature with secret-token-123"
        interaction = build_chat_interaction_payload(message, source="discord")

        self.assertNotIn("learning_trace_ref", json.dumps(interaction))
        trace = build_trace_from_chat_interaction(interaction, source_ref="discord:msg-1", outcome="useful")
        validate_workflow_learning_trace(trace)
        serialized = json.dumps(trace)

        self.assertEqual(trace["schema_version"], "workflow_learning_trace/v1")
        self.assertEqual(trace["privacy"]["mode"], "metadata_only")
        self.assertFalse(trace["privacy"]["raw_prompt_stored"])
        self.assertEqual(trace["source"]["message_length"], len(message))
        self.assertEqual(trace["workflow"]["selected_workflow"], "plan")
        self.assertIn("plan acceptance", trace["reasoning_summary"]["not_evidence_yet"])
        self.assertNotIn(message, serialized)
        self.assertNotIn("secret-token-123", serialized)
        self.assertNotIn("body_text", serialized)

        enriched = attach_learning_trace_ref_to_interaction(interaction, trace)
        ref = learning_trace_ref(trace["trace_id"])
        self.assertEqual(enriched["learning_trace_ref"], ref)
        self.assertEqual(enriched["chat_response"]["state"]["learning_trace_ref"], ref)

    def test_eval_blocks_observed_claim_without_observed_refs(self) -> None:
        interaction = build_chat_interaction_payload("make a risky refactor plan", source="discord")
        trace = build_trace_from_chat_interaction(interaction)
        trace["status"]["evidence_state"] = "observed"

        result = build_workflow_eval_result(trace)
        checks = {check["id"]: check for check in result["checks"]}

        self.assertEqual(result["status"], "failed")
        self.assertEqual(checks["prepared_vs_observed_boundary"]["status"], "failed")

    def test_candidate_is_review_only_and_regression_replay_is_deterministic(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "I want to safely add a feature to this repo"
            fixture = "safely add a feature to this repo"
            interaction = build_chat_interaction_payload(message, source="discord")
            trace = write_learning_trace(paths, build_trace_from_chat_interaction(interaction))
            eval_result = build_workflow_eval_result(trace)
            candidate = build_improvement_candidate(trace, eval_result)
            case = write_regression_case(paths, build_regression_case_from_trace(trace, redacted_message=fixture))
            replay = replay_regression_cases(paths)

            self.assertEqual(candidate["schema_version"], "improvement_candidate/v1")
            self.assertTrue(candidate["human_gate"]["required"])
            self.assertEqual(candidate["human_gate"]["decision"], "pending")
            self.assertFalse(candidate["diff_preview"]["available"])
            self.assertEqual(case["schema_version"], "regression_case/v1")
            self.assertEqual(case["fixture"]["fixture_text"], fixture)
            self.assertFalse(case["fixture"]["privacy"]["raw_prompt_stored"])
            self.assertTrue(case["fixture"]["privacy"]["operator_must_redact_private_content"])
            self.assertFalse(case["fixture"]["privacy"]["redaction_provable_by_omh"])
            self.assertEqual(replay["status"], "passed")
            self.assertEqual(replay["passed"], 1)
            self.assertEqual(list_learning_traces(paths, limit=0), [])
            limited_replay = replay_regression_cases(paths, limit=0)
            self.assertEqual(limited_replay["status"], "no_cases")
            self.assertEqual(limited_replay["total"], 0)
            self.assertEqual(limited_replay["passed"], 0)

    def test_regression_replay_does_not_pass_when_cases_are_skipped(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            interaction = build_chat_interaction_payload("I want to safely add a feature to this repo", source="discord")
            trace = write_learning_trace(paths, build_trace_from_chat_interaction(interaction))
            write_regression_case(paths, build_regression_case_from_trace(trace))

            replay = replay_regression_cases(paths)

            self.assertEqual(replay["status"], "skipped")
            self.assertEqual(replay["total"], 1)
            self.assertEqual(replay["passed"], 0)
            self.assertEqual(replay["skipped"], 1)

    def test_regression_case_id_includes_fixture_and_expected_shape(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            interaction = build_chat_interaction_payload("I want to safely add a feature to this repo", source="discord")
            trace = write_learning_trace(paths, build_trace_from_chat_interaction(interaction))
            first = write_regression_case(
                paths,
                build_regression_case_from_trace(trace, redacted_message="safely add a feature"),
            )
            second = write_regression_case(
                paths,
                build_regression_case_from_trace(
                    trace,
                    redacted_message="risky refactor",
                    expected_workflow="ai-slop-cleaner",
                    expected_harness="code-quality",
                ),
            )

            replay = replay_regression_cases(paths)

            self.assertNotEqual(first["case_id"], second["case_id"])
            self.assertEqual(replay["total"], 2)

    def test_learning_index_is_read_before_directory_scan(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            first_trace = write_learning_trace(
                paths,
                build_trace_from_chat_interaction(build_chat_interaction_payload("safely add a feature", source="discord")),
            )
            second_trace = write_learning_trace(
                paths,
                build_trace_from_chat_interaction(build_chat_interaction_payload("diagnose installation health", source="discord")),
            )
            first_case = write_regression_case(
                paths,
                build_regression_case_from_trace(first_trace, redacted_message="safely add a feature"),
            )
            second_case = write_regression_case(paths, build_regression_case_from_trace(second_trace))
            index = json.loads(paths.learning_index_path.read_text(encoding="utf-8"))
            index["records"] = [
                record
                for record in index["records"]
                if not (
                    (record["kind"] == "trace" and record["id"] == second_trace["trace_id"])
                    or (record["kind"] == "regression_case" and record["id"] == first_case["case_id"])
                )
            ]
            paths.learning_index_path.write_text(json.dumps(index), encoding="utf-8")

            traces = list_learning_traces(paths)
            replay = replay_regression_cases(paths)

            self.assertEqual([trace["trace_id"] for trace in traces], [first_trace["trace_id"]])
            self.assertEqual(replay["status"], "skipped")
            self.assertEqual(replay["results"][0]["case_id"], second_case["case_id"])


if __name__ == "__main__":
    unittest.main()
