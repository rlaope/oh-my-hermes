from __future__ import annotations

import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from _local_package import load_local_package

load_local_package()
from omh.paths import resolve_paths
from omh.workflow_learning import (
    WorkflowLearningError,
    attach_learning_trace_ref_to_interaction,
    build_improvement_candidate,
    build_improvement_candidate_review_card,
    build_improvement_patch_proposal,
    build_self_improvement_store_routing,
    build_self_improvement_store_route_record,
    build_workflow_learning_review_queue,
    build_learning_export_bundle,
    build_regression_case_from_trace,
    build_trace_from_chat_interaction,
    build_workflow_eval_result,
    build_workflow_learning_audit,
    check_learning_index,
    learning_trace_ref,
    list_learning_traces,
    rebuild_learning_index,
    record_missed_route,
    replay_regression_cases,
    review_improvement_candidate,
    review_self_improvement_store_route,
    self_improvement_store_route_ref,
    validate_improvement_candidate_review_card,
    validate_improvement_patch_proposal,
    validate_self_improvement_store_route_record,
    validate_self_improvement_store_routing,
    validate_workflow_learning_review_queue,
    validate_learning_audit_card,
    validate_workflow_learning_trace,
    validate_workflow_learning_export,
    write_learning_trace,
    write_improvement_candidate,
    write_improvement_patch_proposal,
    write_learning_export,
    write_workflow_eval,
    write_regression_case,
    write_self_improvement_store_route,
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
        self.assertEqual(trace["workflow"]["selected_workflow"], "ralplan")
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

            self.assertEqual(candidate["schema_version"], "improvement_candidate/v1")
            self.assertTrue(candidate["human_gate"]["required"])
            self.assertEqual(candidate["human_gate"]["decision"], "pending")
            self.assertFalse(candidate["diff_preview"]["available"])
            review_card = candidate["review_card"]
            self.assertEqual(review_card["schema_version"], "improvement_candidate_review_card/v1")
            self.assertEqual(review_card["status"], "review_required")
            self.assertEqual(review_card["primary_action"], "review_improvement")
            self.assertEqual(review_card["review_gate"]["decision"], "pending")
            self.assertIn("approve_improvement", review_card["wrapper_actions"])
            self.assertIn("reject_improvement", review_card["wrapper_actions"])
            self.assertIn("source patch applied", review_card["not_evidence_yet"])
            self.assertIn("human review", json.dumps(review_card).lower())
            validate_improvement_candidate_review_card(review_card, candidate=candidate)
            broken_card = dict(review_card)
            broken_card["primary_action"] = "missing_action"
            with self.assertRaises(WorkflowLearningError):
                validate_improvement_candidate_review_card(broken_card, candidate=candidate)
            raw_card = json.loads(json.dumps(review_card))
            raw_card["debug"] = {"event_json": "RAW EVENT SHOULD FAIL"}
            with self.assertRaises(WorkflowLearningError):
                validate_improvement_candidate_review_card(raw_card, candidate=candidate)
            raw_payload_card = json.loads(json.dumps(review_card))
            raw_payload_card["debug"] = {"rawPayload": "RAW PAYLOAD SHOULD FAIL"}
            with self.assertRaises(WorkflowLearningError):
                validate_improvement_candidate_review_card(raw_payload_card, candidate=candidate)
            raw_candidate = json.loads(json.dumps(candidate))
            raw_candidate["debug"] = {"platform_event": "RAW PLATFORM EVENT SHOULD FAIL"}
            with self.assertRaises(WorkflowLearningError):
                write_improvement_candidate(paths, raw_candidate)
            stale_candidate = json.loads(json.dumps(candidate))
            stale_candidate["human_gate"]["decision"] = "approve"
            with self.assertRaises(WorkflowLearningError):
                validate_improvement_candidate_review_card(stale_candidate["review_card"], candidate=stale_candidate)
            pending_proposal = build_improvement_patch_proposal(paths, candidate)
            self.assertEqual(pending_proposal["schema_version"], "improvement_patch_proposal/v1")
            self.assertEqual(pending_proposal["status"], "needs_candidate_review")
            self.assertEqual(pending_proposal["primary_action"], "review_improvement")
            self.assertIn("source patch applied", pending_proposal["not_evidence_yet"])
            self.assertFalse(pending_proposal["patch_scope"]["apply_path_available"])
            approved_without_regression = json.loads(json.dumps(candidate))
            approved_without_regression["status"] = "accepted"
            approved_without_regression["human_gate"]["decision"] = "approve"
            approved_without_regression["review_card"] = build_improvement_candidate_review_card(approved_without_regression)
            no_regression_proposal = build_improvement_patch_proposal(paths, approved_without_regression)
            self.assertEqual(no_regression_proposal["status"], "needs_regression_case")
            self.assertEqual(no_regression_proposal["primary_action"], "add_regression_case")
            self.assertEqual(no_regression_proposal["regression_gate"]["snapshot"], [])
            case = write_regression_case(paths, build_regression_case_from_trace(trace, redacted_message=fixture))
            replay = replay_regression_cases(paths)
            self.assertEqual(case["schema_version"], "regression_case/v1")
            self.assertEqual(case["fixture"]["fixture_text"], fixture)
            self.assertFalse(case["fixture"]["privacy"]["raw_prompt_stored"])
            self.assertTrue(case["fixture"]["privacy"]["operator_must_redact_private_content"])
            self.assertFalse(case["fixture"]["privacy"]["redaction_provable_by_omh"])
            self.assertEqual(replay["status"], "passed")
            self.assertEqual(replay["passed"], 1)
            ready_proposal = build_improvement_patch_proposal(paths, approved_without_regression)
            self.assertEqual(ready_proposal["status"], "ready_for_human_patch")
            self.assertEqual(ready_proposal["primary_action"], "copy_patch_handoff")
            self.assertEqual(ready_proposal["regression_gate"]["replay_status"], "passed")
            self.assertNotEqual(ready_proposal["proposal_id"], no_regression_proposal["proposal_id"])
            self.assertEqual(ready_proposal["regression_gate"]["snapshot"][0]["status"], "passed")
            self.assertIn("src/workflows/workflow_learning.py", ready_proposal["target"]["source_files"])
            validate_improvement_patch_proposal(ready_proposal, candidate=approved_without_regression)
            raw_proposal = json.loads(json.dumps(ready_proposal))
            raw_proposal["debug"] = {"event_json": "RAW PATCH EVENT SHOULD FAIL"}
            with self.assertRaises(WorkflowLearningError):
                validate_improvement_patch_proposal(raw_proposal, candidate=approved_without_regression)
            inconsistent_review_gate = json.loads(json.dumps(ready_proposal))
            inconsistent_review_gate["review_gate"]["candidate_decision"] = "pending"
            with self.assertRaises(WorkflowLearningError):
                validate_improvement_patch_proposal(inconsistent_review_gate)
            with self.assertRaises(WorkflowLearningError):
                validate_improvement_patch_proposal(inconsistent_review_gate, candidate=approved_without_regression)
            applying_proposal = json.loads(json.dumps(ready_proposal))
            applying_proposal["patch_scope"]["apply_path_available"] = True
            with self.assertRaises(WorkflowLearningError):
                validate_improvement_patch_proposal(applying_proposal, candidate=approved_without_regression)
            loose_action_proposal = json.loads(json.dumps(ready_proposal))
            loose_action_proposal["wrapper_actions"].append(7)
            with self.assertRaises(WorkflowLearningError):
                validate_improvement_patch_proposal(loose_action_proposal, candidate=approved_without_regression)
            mismatched_regression_proposal = json.loads(json.dumps(ready_proposal))
            mismatched_regression_proposal["regression_gate"]["passed"] = False
            with self.assertRaises(WorkflowLearningError):
                validate_improvement_patch_proposal(mismatched_regression_proposal, candidate=approved_without_regression)
            write_improvement_candidate(paths, approved_without_regression)
            write_improvement_patch_proposal(paths, ready_proposal)
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

    def test_missed_route_helper_records_review_bundle_without_raw_prompt_output(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "make an image explaining the cron feature"
            interaction = build_chat_interaction_payload(message, source="discord")

            payload = record_missed_route(
                paths,
                interaction,
                source_ref="discord:message-1",
                expected_workflow="img-summary",
                expected_harness="img-summary",
                expected_next_action="prepare_visual_prompt_card",
                fixture_message=message,
            )
            serialized = json.dumps(payload)

            self.assertEqual(payload["schema_version"], "learning_missed_route_result/v1")
            self.assertTrue(payload["recorded"])
            self.assertEqual(payload["status"], "review_ready")
            self.assertEqual(payload["selected"]["workflow"], "img-summary")
            self.assertEqual(payload["expected"]["workflow"], "img-summary")
            self.assertEqual(payload["candidate"]["target_type"], "routing")
            self.assertEqual(payload["candidate"]["primary_action"], "review_improvement")
            self.assertTrue(payload["regression_case"]["replay_ready"])
            self.assertNotIn(message, serialized)
            self.assertEqual(len(list_learning_traces(paths)), 1)
            self.assertEqual(replay_regression_cases(paths)["status"], "passed")

    def test_missed_route_helper_dry_run_does_not_write_records(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "make an image explaining the cron feature"
            interaction = build_chat_interaction_payload(message, source="discord")

            payload = record_missed_route(
                paths,
                interaction,
                expected_workflow="img-summary",
                fixture_message=message,
                dry_run=True,
            )

            self.assertFalse(payload["recorded"])
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["status"], "review_ready")
            self.assertEqual(list_learning_traces(paths), [])
            self.assertEqual(replay_regression_cases(paths)["status"], "no_cases")

    def test_patch_proposal_regression_snapshot_is_order_stable(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            interaction = build_chat_interaction_payload("I want to safely add a feature to this repo", source="discord")
            trace = write_learning_trace(paths, build_trace_from_chat_interaction(interaction))
            candidate = build_improvement_candidate(trace, build_workflow_eval_result(trace))
            candidate["status"] = "accepted"
            candidate["human_gate"]["decision"] = "approve"
            candidate["review_card"] = build_improvement_candidate_review_card(candidate)
            write_regression_case(
                paths,
                build_regression_case_from_trace(
                    trace,
                    case_id="case_b",
                    redacted_message="I want to safely add a feature to this repo",
                ),
            )
            write_regression_case(
                paths,
                build_regression_case_from_trace(
                    trace,
                    case_id="case_a",
                    redacted_message="safely add a feature to this repo",
                ),
            )

            proposal = build_improvement_patch_proposal(paths, candidate)

            self.assertEqual(
                [item["case_id"] for item in proposal["regression_gate"]["snapshot"]],
                ["case_a", "case_b"],
            )
            self.assertEqual(
                proposal["source_refs"]["regression_case_refs"],
                ["omh-learning-regression_case:case_a", "omh-learning-regression_case:case_b"],
            )

    def test_empty_learning_review_queue_has_valid_primary_action(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            queue = build_workflow_learning_review_queue(paths, limit=None)

            self.assertEqual(queue["status"], "empty")
            self.assertEqual(queue["primary_action"], "record_workflow_learning_trace")
            self.assertIn("record_workflow_learning_trace", queue["wrapper_actions"])
            validate_workflow_learning_review_queue(queue)

    def test_self_improvement_store_routing_separates_learning_destinations(self) -> None:
        cases = (
            (
                "Please remember I prefer Korean polite replies.",
                "memory_candidate",
                "memory-sync",
                "prepare_memory_sync",
                "user_preference",
            ),
            (
                "When the workflow is ambiguous, the skill should ask one concise question instead of asking every time.",
                "skill_update_candidate",
                "workflow-learning",
                "review_improvement",
                "workflow_behavior",
            ),
            (
                "According to the Hermes Agent docs, the LLM wiki uses SCHEMA.md, index.md, and source-backed pages.",
                "wiki_candidate",
                "wiki",
                "prepare_wiki_guidance",
                "source_backed_knowledge",
            ),
            (
                "CI failed twice because the release smoke missed a generated docs check; capture the root cause.",
                "failure_retrospective_candidate",
                "workflow-learning",
                "record_workflow_learning_trace",
                "failure_or_regression",
            ),
            (
                "Suggest a daily background self-improvement review, but do not create cron automatically.",
                "automation_suggestion_candidate",
                "automation-blueprint",
                "prepare_automation_blueprint",
                "recurring_automation",
            ),
            (
                "Temporary shell PATH was wrong in this local session only.",
                "discard_transient",
                "none",
                "do_not_store",
                "transient_local_state",
            ),
        )

        for text, destination, workflow, next_action, reason in cases:
            with self.subTest(destination=destination):
                routing = build_self_improvement_store_routing(text, source_kind="operator_feedback")
                serialized = json.dumps(routing)

                self.assertEqual(routing["schema_version"], "self_improvement_store_routing/v1")
                self.assertEqual(routing["status"], "prepared")
                self.assertEqual(routing["classification"]["destination"], destination)
                self.assertEqual(routing["classification"]["target_workflow"], workflow)
                self.assertEqual(routing["next_action"], next_action)
                self.assertIn(reason, routing["classification"]["routing_reasons"])
                self.assertTrue(routing["review_gate"]["required"])
                self.assertFalse(routing["signal"]["raw_text_stored"])
                self.assertFalse(routing["writes_observed"])
                self.assertIn("memory write", routing["not_evidence_yet"])
                self.assertNotIn(text, serialized)
                validate_self_improvement_store_routing(routing)

        protected = build_self_improvement_store_routing(
            "Remember my API token secret-token-123 for future deployments.",
            source_kind="operator_feedback",
        )
        self.assertEqual(protected["classification"]["destination"], "discard_transient")
        self.assertIn("private_or_raw_content", protected["classification"]["routing_reasons"])
        self.assertNotIn("secret-token-123", json.dumps(protected))

        broken = json.loads(json.dumps(protected))
        broken["debug"] = {"raw_text": "private raw text should fail"}
        with self.assertRaises(WorkflowLearningError):
            validate_self_improvement_store_routing(broken)

        for forbidden_key in ("transcript", "conversation", "stdout", "stderr"):
            with self.subTest(forbidden_key=forbidden_key):
                broken = json.loads(json.dumps(protected))
                broken["debug"] = {forbidden_key: "private raw text should fail"}
                with self.assertRaises(WorkflowLearningError):
                    validate_self_improvement_store_routing(broken)

        nested_raw_flag = json.loads(json.dumps(protected))
        nested_raw_flag["debug"] = {"raw_text_stored": "private raw text should fail"}
        with self.assertRaises(WorkflowLearningError):
            validate_self_improvement_store_routing(nested_raw_flag)

        invalid_signal_flag = json.loads(json.dumps(protected))
        invalid_signal_flag["signal"]["raw_text_stored"] = "private raw text should fail"
        with self.assertRaises(WorkflowLearningError):
            validate_self_improvement_store_routing(invalid_signal_flag)

    def test_self_improvement_store_route_review_queue_records_metadata_only_decisions(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "According to the Hermes Agent docs, the LLM wiki uses SCHEMA.md and source-backed pages."
            routing = build_self_improvement_store_routing(message, source_kind="operator_feedback")
            route = write_self_improvement_store_route(
                paths,
                build_self_improvement_store_route_record(
                    routing,
                    source_ref="chat:msg-1",
                    title="Route wiki learning",
                ),
            )

            pending_queue = build_workflow_learning_review_queue(paths, limit=None)

            self.assertEqual(route["schema_version"], "self_improvement_store_route_record/v1")
            self.assertEqual(route["status"], "pending_review")
            self.assertEqual(route["destination_review"]["current_destination"], "wiki_candidate")
            self.assertEqual(route["destination_review"]["next_action"], "prepare_wiki_guidance")
            self.assertEqual(route["review_gate"]["decision"], "pending")
            self.assertEqual(pending_queue["status"], "needs_review")
            self.assertEqual(pending_queue["summary"]["pending_store_routes"], 1)
            self.assertEqual(pending_queue["entries"][0]["kind"], "self_improvement_store_route")
            self.assertEqual(pending_queue["entries"][0]["status"], "needs_store_route_review")
            self.assertEqual(pending_queue["entries"][0]["primary_action"], "review_self_improvement_store_route")
            self.assertIn(self_improvement_store_route_ref(str(route["route_id"])), pending_queue["entries"][0]["refs"])
            self.assertIn("review_self_improvement_store_route", pending_queue["wrapper_actions"])
            self.assertNotIn(message, json.dumps(route))
            validate_self_improvement_store_route_record(route)
            validate_workflow_learning_review_queue(pending_queue)

            reviewed = review_self_improvement_store_route(
                paths,
                str(route["route_id"]),
                decision="change_destination",
                destination="memory_candidate",
                reviewer_ref="operator:test",
                review_note="private operator note should not be stored",
            )
            serialized_reviewed = json.dumps(reviewed)

            self.assertEqual(reviewed["status"], "changed")
            self.assertEqual(reviewed["destination_review"]["current_destination"], "memory_candidate")
            self.assertEqual(reviewed["destination_review"]["target_workflow"], "memory-sync")
            self.assertEqual(reviewed["destination_review"]["next_action"], "prepare_memory_sync")
            self.assertEqual(reviewed["review_gate"]["decision"], "change_destination")
            self.assertIn("review_note_sha256", reviewed["review_gate"])
            self.assertIn("review_note_length", reviewed["review_gate"])
            self.assertFalse(reviewed["review_gate"]["review_note_stored"])
            self.assertFalse(reviewed["writes_observed"])
            self.assertNotIn("private operator note", serialized_reviewed)
            validate_self_improvement_store_route_record(reviewed)

            approved_queue = build_workflow_learning_review_queue(paths, limit=None)

            self.assertEqual(approved_queue["status"], "empty")
            self.assertEqual(approved_queue["summary"]["pending_store_routes"], 0)
            export = build_learning_export_bundle(paths)
            self.assertNotIn("store_routes", export["records"])
            self.assertEqual(export["provenance"]["source_trace_count"], 0)

    def test_learning_review_queue_tracks_candidate_decisions_without_raw_review_note(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "I want to safely add a feature to this repo"
            interaction = build_chat_interaction_payload(message, source="discord")
            trace = write_learning_trace(paths, build_trace_from_chat_interaction(interaction))
            candidate = write_improvement_candidate(
                paths,
                build_improvement_candidate(trace, build_workflow_eval_result(trace)),
            )

            pending_queue = build_workflow_learning_review_queue(paths)

            self.assertEqual(pending_queue["schema_version"], "workflow_learning_review_queue/v1")
            self.assertEqual(pending_queue["status"], "needs_review")
            self.assertEqual(pending_queue["summary"]["pending_candidates"], 1)
            self.assertEqual(pending_queue["entries"][0]["status"], "needs_candidate_review")
            self.assertEqual(pending_queue["entries"][0]["primary_action"], "review_improvement")
            self.assertIn("show_learning_review_queue", pending_queue["wrapper_actions"])
            validate_workflow_learning_review_queue(pending_queue)

            reviewed = review_improvement_candidate(
                paths,
                str(candidate["candidate_id"]),
                decision="approve",
                reviewer_ref="operator:test",
                review_note="private operator note should not be stored",
            )
            serialized_reviewed = json.dumps(reviewed)

            self.assertEqual(reviewed["status"], "accepted")
            self.assertEqual(reviewed["human_gate"]["decision"], "approve")
            self.assertEqual(reviewed["review_card"]["status"], "approved")
            self.assertIn("review_note_sha256", reviewed["human_gate"])
            self.assertIn("review_note_length", reviewed["human_gate"])
            self.assertNotIn("private operator note", serialized_reviewed)

            revision = review_improvement_candidate(
                paths,
                str(candidate["candidate_id"]),
                decision="revise",
                reviewer_ref="operator:second-pass",
            )

            self.assertEqual(revision["status"], "proposed")
            self.assertEqual(revision["human_gate"]["decision"], "revise")
            self.assertNotIn("review_note_sha256", revision["human_gate"])
            self.assertNotIn("review_note_length", revision["human_gate"])

            reviewed = review_improvement_candidate(
                paths,
                str(candidate["candidate_id"]),
                decision="approve",
                reviewer_ref="operator:test",
                review_note="private operator note should not be stored",
            )

            approved_queue = build_workflow_learning_review_queue(paths)

            self.assertEqual(approved_queue["status"], "needs_review")
            self.assertEqual(approved_queue["summary"]["approved_without_proposal"], 1)
            self.assertEqual(approved_queue["entries"][0]["status"], "needs_patch_proposal")
            self.assertEqual(approved_queue["entries"][0]["primary_action"], "prepare_patch_proposal")

            write_regression_case(
                paths,
                build_regression_case_from_trace(trace, redacted_message="safely add a feature to this repo"),
            )
            ready_proposal = write_improvement_patch_proposal(paths, build_improvement_patch_proposal(paths, reviewed))
            ready_queue = build_workflow_learning_review_queue(paths)

            self.assertEqual(ready_queue["status"], "ready")
            self.assertEqual(ready_queue["summary"]["ready_patch_proposals"], 1)
            self.assertEqual(ready_queue["entries"][0]["proposal_id"], ready_proposal["proposal_id"])
            self.assertEqual(ready_queue["entries"][0]["primary_action"], "copy_patch_handoff")
            self.assertIn("source patch applied", ready_queue["not_evidence_yet"])

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

    def test_learning_index_rebuild_repairs_stale_index(self) -> None:
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
            second_case = write_regression_case(
                paths,
                build_regression_case_from_trace(second_trace, redacted_message="diagnose installation health"),
            )
            stale_index = json.loads(paths.learning_index_path.read_text(encoding="utf-8"))
            stale_index["records"] = [
                record
                for record in stale_index["records"]
                if not (
                    (record["kind"] == "trace" and record["id"] == second_trace["trace_id"])
                    or (record["kind"] == "regression_case" and record["id"] == first_case["case_id"])
                )
            ]
            paths.learning_index_path.write_text(json.dumps(stale_index), encoding="utf-8")

            stale_check = check_learning_index(paths)
            dry_run = rebuild_learning_index(paths, dry_run=True)

            self.assertEqual(stale_check["status"], "stale")
            self.assertEqual(dry_run["status"], "dry_run")
            self.assertFalse(dry_run["wrote"])
            self.assertEqual([trace["trace_id"] for trace in list_learning_traces(paths)], [first_trace["trace_id"]])

            rebuilt = rebuild_learning_index(paths)
            repaired_check = check_learning_index(paths)
            replay = replay_regression_cases(paths)

            self.assertEqual(rebuilt["status"], "rebuilt")
            self.assertTrue(rebuilt["wrote"])
            self.assertEqual(rebuilt["counts"]["trace"], 2)
            self.assertEqual(rebuilt["counts"]["regression_case"], 2)
            self.assertEqual(repaired_check["status"], "passed")
            self.assertEqual(replay["status"], "passed")
            self.assertEqual({item["case_id"] for item in replay["results"]}, {first_case["case_id"], second_case["case_id"]})

    def test_learning_index_rebuild_reports_invalid_records_without_writing(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_learning_trace(
                paths,
                build_trace_from_chat_interaction(build_chat_interaction_payload("safely add a feature", source="discord")),
            )
            before = paths.learning_index_path.read_text(encoding="utf-8")
            bad_path = paths.learning_traces_dir / "broken.json"
            bad_path.write_text('{"schema_version":"wrong"}', encoding="utf-8")

            rebuilt = rebuild_learning_index(paths)

            self.assertEqual(rebuilt["status"], "failed")
            self.assertFalse(rebuilt["wrote"])
            self.assertEqual(paths.learning_index_path.read_text(encoding="utf-8"), before)
            self.assertEqual(rebuilt["invalid_records"][0]["kind"], "trace")

    def test_learning_index_check_allows_empty_first_install_state(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            check = check_learning_index(paths)

            self.assertEqual(check["status"], "no_records")
            self.assertTrue(check["ok"])
            self.assertEqual(check["records_total"], 0)

    def test_learning_export_bundle_is_metadata_only_and_redacts_fixture_text(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "I want to safely add a feature with secret-token-123"
            interaction = build_chat_interaction_payload(message, source="discord")
            trace = write_learning_trace(paths, build_trace_from_chat_interaction(interaction))
            eval_result = write_workflow_eval(paths, build_workflow_eval_result(trace))
            candidate = write_improvement_candidate(paths, build_improvement_candidate(trace, eval_result))
            case = write_regression_case(
                paths,
                build_regression_case_from_trace(trace, redacted_message="feature request with secret-token-123"),
            )
            trace_path = paths.learning_traces_dir / f"{trace['trace_id']}.json"
            stored_trace = json.loads(trace_path.read_text(encoding="utf-8"))
            stored_trace["source"]["raw_text"] = "RAW SECRET PROMPT SHOULD NOT EXPORT"
            stored_trace["route"]["matched"] = ["PRIVATE MATCHED ROUTE TEXT SHOULD NOT EXPORT"]
            stored_trace["workflow"]["next_action"] = "PRIVATE NEXT ACTION SHOULD NOT EXPORT"
            stored_trace["reasoning_summary"]["why_this_workflow"] = "PRIVATE ROUTING REASON SHOULD NOT EXPORT"
            stored_trace["reasoning_summary"]["next_action"] = "PRIVATE REASONING ACTION SHOULD NOT EXPORT"
            stored_trace["reasoning_summary"]["not_evidence_yet"] = [
                "PRIVATE NOT EVIDENCE TEXT SHOULD NOT EXPORT"
            ]
            stored_trace["reasoning_summary"]["claim_boundary"] = "PRIVATE CLAIM BOUNDARY SHOULD NOT EXPORT"
            stored_trace["prepared_refs"] = [{"kind": "handoff", "ref": "PRIVATE PREPARED REF SHOULD NOT EXPORT"}]
            stored_trace["observed_refs"] = [{"kind": "review", "ref": "PRIVATE OBSERVED REF SHOULD NOT EXPORT"}]
            stored_trace["status"]["feedback_summary"] = "PRIVATE USER FEEDBACK SHOULD NOT EXPORT"
            stored_trace["overclaim_guard"] = ["PRIVATE OVERCLAIM GUARD SHOULD NOT EXPORT"]
            trace_path.write_text(json.dumps(stored_trace), encoding="utf-8")
            eval_path = paths.learning_evals_dir / f"{eval_result['eval_id']}.json"
            stored_eval = json.loads(eval_path.read_text(encoding="utf-8"))
            stored_eval["diagnostics"] = {"rawPayload": "RAW EVAL PAYLOAD SHOULD NOT EXPORT"}
            stored_eval["summary"] = "PRIVATE EVAL SUMMARY SHOULD NOT EXPORT"
            stored_eval["checks"][0]["summary"] = "PRIVATE CHECK SUMMARY SHOULD NOT EXPORT"
            stored_eval["checks"][0]["evidence_refs"] = ["PRIVATE EVAL EVIDENCE REF SHOULD NOT EXPORT"]
            eval_path.write_text(json.dumps(stored_eval), encoding="utf-8")
            candidate_path = paths.learning_candidates_dir / f"{candidate['candidate_id']}.json"
            stored_candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            stored_candidate["title"] = "PRIVATE CANDIDATE TITLE SHOULD NOT EXPORT"
            stored_candidate["proposal"]["problem_summary"] = "PRIVATE CANDIDATE PROBLEM SHOULD NOT EXPORT"
            stored_candidate["proposal"]["suggested_change"] = "PRIVATE CANDIDATE CHANGE SHOULD NOT EXPORT"
            candidate_path.write_text(json.dumps(stored_candidate), encoding="utf-8")
            case_path = paths.learning_regressions_dir / f"{case['case_id']}.json"
            stored_case = json.loads(case_path.read_text(encoding="utf-8"))
            stored_case["expected"]["claim_boundary_contains"] = "PRIVATE REGRESSION CLAIM SHOULD NOT EXPORT"
            stored_case["expected"]["not_evidence_yet_includes"] = [
                "PRIVATE REGRESSION NOT EVIDENCE SHOULD NOT EXPORT"
            ]
            stored_case["replay_policy"]["skip_reason"] = "PRIVATE REGRESSION SKIP SHOULD NOT EXPORT"
            case_path.write_text(json.dumps(stored_case), encoding="utf-8")

            bundle = build_learning_export_bundle(paths, trace_ids=[trace["trace_id"]])
            written = write_learning_export(paths, bundle)
            serialized = json.dumps(written)
            index_check = check_learning_index(paths)

            validate_workflow_learning_export(written)
            self.assertEqual(written["schema_version"], "workflow_learning_export/v1")
            self.assertEqual(written["status"], "ready")
            self.assertEqual(written["privacy"]["mode"], "metadata_only")
            self.assertFalse(written["privacy"]["raw_prompt_stored"])
            self.assertFalse(written["privacy"]["fixture_text_stored"])
            self.assertEqual(written["summary"]["counts"]["traces"], 1)
            self.assertEqual(written["summary"]["counts"]["evals"], 1)
            self.assertEqual(written["summary"]["counts"]["candidates"], 1)
            self.assertEqual(written["summary"]["counts"]["regression_cases"], 1)
            self.assertEqual(written["study_cards"][0]["candidate_refs"], [f"omh-learning-candidate:{candidate['candidate_id']}"])
            self.assertEqual(written["study_cards"][0]["why_this_workflow"], "omitted_from_metadata_export")
            self.assertEqual(written["study_cards"][0]["next_action"], "omitted_free_text")
            self.assertTrue(written["study_cards"][0]["not_evidence_yet_omitted"])
            self.assertEqual(written["records"]["traces"][0]["route"]["matched_count"], 1)
            self.assertTrue(written["records"]["traces"][0]["route"]["matched_values_omitted"])
            self.assertEqual(written["records"]["traces"][0]["reasoning_summary"]["why_this_workflow"], "omitted_from_metadata_export")
            self.assertEqual(written["records"]["traces"][0]["reasoning_summary"]["next_action"], "omitted_free_text")
            self.assertTrue(written["records"]["traces"][0]["reasoning_summary"]["not_evidence_yet_omitted"])
            self.assertTrue(written["records"]["traces"][0]["prepared_refs"][0]["ref_value_omitted"])
            self.assertTrue(written["records"]["traces"][0]["observed_refs"][0]["ref_value_omitted"])
            self.assertEqual(written["records"]["regression_cases"][0]["case_id"], case["case_id"])
            self.assertTrue(written["records"]["regression_cases"][0]["fixture"]["fixture_text_omitted"])
            self.assertNotIn("fixture_text", written["records"]["regression_cases"][0]["fixture"])
            self.assertNotIn("redacted_message", written["records"]["regression_cases"][0]["fixture"])
            self.assertFalse(written["provenance"]["canonical_learning_index_includes_exports"])
            self.assertNotIn(message, serialized)
            self.assertNotIn("secret-token-123", serialized)
            self.assertNotIn("feature request with secret-token-123", serialized)
            self.assertNotIn("RAW SECRET PROMPT SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE MATCHED ROUTE TEXT SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE NEXT ACTION SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE ROUTING REASON SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE REASONING ACTION SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE NOT EVIDENCE TEXT SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE CLAIM BOUNDARY SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE PREPARED REF SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE OBSERVED REF SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE USER FEEDBACK SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE OVERCLAIM GUARD SHOULD NOT EXPORT", serialized)
            self.assertNotIn("RAW EVAL PAYLOAD SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE EVAL SUMMARY SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE CHECK SUMMARY SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE EVAL EVIDENCE REF SHOULD NOT EXPORT", serialized)
            self.assertNotIn("RAW CANDIDATE EVENT SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE CANDIDATE TITLE SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE CANDIDATE PROBLEM SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE CANDIDATE CHANGE SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE REGRESSION CLAIM SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE REGRESSION NOT EVIDENCE SHOULD NOT EXPORT", serialized)
            self.assertNotIn("PRIVATE REGRESSION SKIP SHOULD NOT EXPORT", serialized)
            self.assertNotIn("raw_text", serialized)
            self.assertNotIn("rawPayload", serialized)
            self.assertNotIn("event_json", serialized)
            self.assertEqual(index_check["status"], "passed")
            self.assertTrue((paths.learning_exports_dir / f"{written['export_id']}.json").exists())

    def test_learning_export_bundle_empty_state_is_not_written(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            bundle = build_learning_export_bundle(paths)

            validate_workflow_learning_export(bundle)
            self.assertEqual(bundle["status"], "no_records")
            with self.assertRaises(WorkflowLearningError):
                write_learning_export(paths, bundle)

    def test_learning_audit_tracks_readiness_without_raw_prompt(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            message = "I want to safely add a feature with secret-token-123"

            empty = build_workflow_learning_audit(paths)
            self.assertEqual(empty["schema_version"], "workflow_learning_audit/v1")
            self.assertEqual(empty["status"], "no_records")
            self.assertTrue(empty["ok"])
            self.assertEqual(empty["learning_audit_card"]["schema_version"], "learning_audit_card/v1")
            self.assertEqual(empty["learning_audit_card"]["status"], "no_records")
            self.assertEqual(empty["learning_audit_card"]["primary_action"], "record_workflow_learning_trace")
            self.assertEqual(empty["learning_audit_card"]["warning_count"], 0)
            self.assertIn("record_workflow_learning_trace", empty["learning_audit_card"]["wrapper_actions"])
            self.assertIn("propose_skill_improvement", empty["learning_audit_card"]["wrapper_actions"])
            self.assertIn("show_status", empty["learning_audit_card"]["wrapper_actions"])
            self.assertIn("automatic skill patch", empty["learning_audit_card"]["not_evidence_yet"])
            validate_learning_audit_card(empty["learning_audit_card"])

            trace = write_learning_trace(
                paths,
                build_trace_from_chat_interaction(build_chat_interaction_payload(message, source="discord")),
            )
            attention = build_workflow_learning_audit(paths)
            self.assertEqual(attention["status"], "needs_attention")
            self.assertEqual(attention["counts"]["traces"], 1)
            self.assertEqual(attention["coverage"]["eval_coverage_percent"], 0)
            self.assertIn("trace_without_eval", {item["id"] for item in attention["warnings"]})
            self.assertEqual(attention["learning_audit_card"]["status"], "needs_attention")
            self.assertEqual(attention["learning_audit_card"]["primary_action"], "show_learning_eval")
            attention_steps = {step["id"]: step for step in attention["learning_audit_card"]["steps"]}
            self.assertEqual(attention_steps["trace"]["state"], "ready")
            self.assertEqual(attention_steps["eval"]["state"], "missing")
            self.assertNotIn(message, json.dumps(attention))
            self.assertNotIn("secret-token-123", json.dumps(attention))

            write_workflow_eval(paths, build_workflow_eval_result(trace))
            write_regression_case(
                paths,
                build_regression_case_from_trace(trace, redacted_message="safely add a feature"),
            )
            pending_candidate = write_improvement_candidate(paths, build_improvement_candidate(trace, build_workflow_eval_result(trace)))
            pending_audit = build_workflow_learning_audit(paths)
            self.assertEqual(pending_audit["status"], "needs_attention")
            self.assertIn("pending_improvement_candidate", {item["id"] for item in pending_audit["warnings"]})
            self.assertEqual(pending_audit["learning_audit_card"]["primary_action"], "review_improvement")
            self.assertIn("review_improvement", pending_audit["learning_audit_card"]["wrapper_actions"])
            self.assertIn("reject_improvement", pending_audit["learning_audit_card"]["wrapper_actions"])
            self.assertEqual(pending_candidate["review_card"]["primary_action"], "review_improvement")
            pending_candidate["status"] = "accepted"
            pending_candidate["human_gate"]["decision"] = "approve"
            pending_candidate["review_card"] = build_improvement_candidate_review_card(pending_candidate)
            write_improvement_candidate(paths, pending_candidate)
            write_learning_export(paths, build_learning_export_bundle(paths, trace_ids=[trace["trace_id"]]))

            ready = build_workflow_learning_audit(paths)

            self.assertEqual(ready["status"], "ready")
            self.assertTrue(ready["ok"])
            self.assertEqual(ready["coverage"]["eval_coverage_percent"], 100)
            self.assertEqual(ready["coverage"]["regression_coverage_percent"], 100)
            self.assertEqual(ready["regression_replay"]["status"], "passed")
            self.assertEqual(ready["warnings"], [])
            card = ready["learning_audit_card"]
            self.assertEqual(card["schema_version"], "learning_audit_card/v1")
            self.assertEqual(card["status"], "ready")
            self.assertEqual(card["severity"], "ok")
            self.assertEqual(card["primary_action"], "audit_learning_readiness")
            self.assertEqual(card["blocking_issue_count"], 0)
            self.assertEqual(card["warning_count"], 0)
            self.assertEqual(card["coverage"]["eval_coverage_percent"], 100)
            self.assertEqual(card["regression_replay"]["status"], "passed")
            self.assertTrue(
                {"audit_learning_readiness", "propose_skill_improvement", "export_learning_bundle", "replay_regression_cases"}
                <= set(card["wrapper_actions"])
            )
            ready_steps = {step["id"]: step for step in card["steps"]}
            self.assertEqual(ready_steps["eval"]["state"], "ready")
            self.assertEqual(ready_steps["regression"]["state"], "ready")
            self.assertEqual(ready_steps["export"]["state"], "ready")
            self.assertIn("model training", card["not_evidence_yet"])
            self.assertIn("automatic skill patch", card["not_evidence_yet"])
            validate_learning_audit_card(card)
            self.assertNotIn("safely add a feature", json.dumps(ready))

            broken_card = json.loads(json.dumps(card))
            broken_card["primary_action"] = "missing_action"
            with self.assertRaises(WorkflowLearningError):
                validate_learning_audit_card(broken_card)

    def test_learning_audit_blocks_on_stale_index(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            trace = write_learning_trace(
                paths,
                build_trace_from_chat_interaction(build_chat_interaction_payload("diagnose installation health", source="discord")),
            )
            index = json.loads(paths.learning_index_path.read_text(encoding="utf-8"))
            index["records"] = [item for item in index["records"] if item["id"] != trace["trace_id"]]
            paths.learning_index_path.write_text(json.dumps(index), encoding="utf-8")

            audit = build_workflow_learning_audit(paths)

            self.assertEqual(audit["status"], "blocked")
            self.assertFalse(audit["ok"])
            self.assertEqual(audit["index"]["status"], "stale")
            self.assertIn("learning_index_not_clean", {item["id"] for item in audit["blocking_issues"]})

    def test_learning_audit_blocks_on_invalid_records_without_valid_traces(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            paths.learning_traces_dir.mkdir(parents=True, exist_ok=True)
            (paths.learning_traces_dir / "broken.json").write_text(
                json.dumps({"schema_version": "workflow_learning_trace/v1"}),
                encoding="utf-8",
            )

            audit = build_workflow_learning_audit(paths)

            self.assertEqual(audit["status"], "blocked")
            self.assertFalse(audit["ok"])
            self.assertEqual(audit["counts"]["traces"], 0)
            self.assertEqual(audit["counts"]["invalid_records"], 1)
            self.assertIn("invalid_learning_record", {item["id"] for item in audit["blocking_issues"]})

    def test_learning_review_queue_orders_invalid_records_stably(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            paths.learning_traces_dir.mkdir(parents=True, exist_ok=True)
            (paths.learning_traces_dir / "z-broken.json").write_text(
                json.dumps({"schema_version": "workflow_learning_trace/v1"}),
                encoding="utf-8",
            )
            (paths.learning_traces_dir / "a-broken.json").write_text(
                json.dumps({"schema_version": "workflow_learning_trace/v1"}),
                encoding="utf-8",
            )

            first = build_workflow_learning_review_queue(paths, limit=None)
            second = build_workflow_learning_review_queue(paths, limit=None)

            self.assertEqual(first["status"], "blocked")
            self.assertEqual([item["entry_id"] for item in first["entries"]], [item["entry_id"] for item in second["entries"]])
            self.assertEqual([item["created_at"] for item in first["entries"]], [item["created_at"] for item in second["entries"]])
            self.assertTrue(all(str(item["created_at"]).startswith("invalid:") for item in first["entries"]))


if __name__ == "__main__":
    unittest.main()
