from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.goal_loop import (
    LOOP_CYCLE_SCHEMA,
    LOOP_START_CARD_SCHEMA,
    LOOP_STATUS_CARD_SCHEMA,
    block_loop_queue_item,
    build_loop_queue_handoff,
    build_loop_start_card,
    build_loop_status_card,
    create_loop_cycle,
    inspect_loop_queue_item,
    list_loop_queue,
    observe_loop_queue_item,
    record_loop_feedback,
    tick_loop_runtime,
    update_loop_permission,
    validate_loop_cycle,
)
from omh.paths import resolve_paths


class GoalLoopTests(unittest.TestCase):
    def test_loop_start_card_redacts_goal_and_exposes_start_contract(self) -> None:
        card = build_loop_start_card(
            "Make OMH a 10k-star quality Hermes-native project",
            source="discord",
            default_permission_profile="handoff_only",
        )
        serialized = str(card)

        self.assertEqual(card["schema_version"], LOOP_START_CARD_SCHEMA)
        self.assertEqual(card["status"], "interview_required")
        self.assertEqual(card["goal_summary"], "{message}")
        self.assertEqual(card["next_action"], "choose_permission_profile")
        self.assertEqual(card["backend_contract"]["operation"], "loop.start")
        self.assertIn("goal_reframe", card["backend_contract"]["required_fields"])
        self.assertIn("handoff_only", {option["id"] for option in card["permission_profiles"]})
        self.assertIn("loop_cycle/v1", card["backend_contract"]["creates_artifact"])
        self.assertEqual(card["loop_engineering"]["schema_version"], "loop_engineering/v1")
        self.assertEqual(
            [step["id"] for step in card["loop_engineering"]["pipeline"]],
            ["task_discovery", "distribution", "execution", "verification", "next_task_decision"],
        )
        self.assertEqual(
            {block["id"] for block in card["loop_engineering"]["building_blocks"]},
            {"automation", "worktree", "skill", "connector", "subagent"},
        )
        self.assertEqual(card["loop_engineering"]["context_policy"]["read_model"], "bounded_state_and_evidence_refs")
        self.assertTrue(card["loop_engineering"]["cost_policy"]["reuse_schema_scaffold"])
        self.assertEqual(card["loop_engineering"]["cost_policy"]["default_verifier_lanes"], 1)
        self.assertNotIn("10k-star quality", serialized)

        visible = build_loop_start_card("Make OMH public launch-ready", include_goal=True)
        self.assertEqual(visible["goal_summary"], "Make OMH public launch-ready")

    def test_loop_cycle_records_permission_profile_without_completion_claim(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            cycle = create_loop_cycle(
                paths,
                goal_summary="Become a 10k-star OSS by building comparable capability and public proof",
                goal_reframe="Analyze strong projects, implement missing local workflows, verify them, and prepare launch material.",
                success_criteria=["Comparable workflow coverage exists", "Release proof is documented"],
                permission_profile="handoff_only",
                allowed_executors=["codex"],
            )
            card = build_loop_status_card(paths, cycle["loop_id"])

        self.assertEqual(cycle["schema_version"], LOOP_CYCLE_SCHEMA)
        self.assertEqual(card["schema_version"], LOOP_STATUS_CARD_SCHEMA)
        self.assertEqual(cycle["authority_envelope"]["permission_profile"], "handoff_only")
        self.assertIn("executor_handoff", cycle["authority_envelope"]["allowed_actions"])
        self.assertIn("executor_dispatch", cycle["authority_envelope"]["blocked_actions"])
        self.assertIn("executor_dispatch", cycle["authority_envelope"]["approval_checkpoints"])
        self.assertEqual(cycle["authority_envelope"]["forbidden_actions"], [])
        self.assertEqual(cycle["authority_envelope"]["budget_limits"]["external_spend"], "not_allowed")
        self.assertFalse(cycle["completion_claim_allowed"])
        self.assertFalse(card["completion_claim_allowed"])
        self.assertEqual(validate_loop_cycle(cycle), {"ok": True, "errors": []})

    def test_loop_feedback_external_wait_blocks_continuation_copy(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            cycle = create_loop_cycle(
                paths,
                goal_summary="Reach major OSS adoption",
                goal_reframe="Ship implementation-quality improvements and wait for adoption signals separately.",
                success_criteria=["Internal implementation work has proof"],
            )

            updated = record_loop_feedback(paths, cycle["loop_id"], external_wait="Waiting for public adoption data")
            card = build_loop_status_card(paths, cycle["loop_id"])

        self.assertEqual(updated["phase"], "waiting")
        self.assertEqual(updated["wait_reason"], "waiting_external_observation")
        self.assertEqual(card["next_action"], "record_external_wait")
        self.assertIn("external evidence", card["safe_copy"]["next_step"])

    def test_loop_permission_can_explicitly_add_merge_without_execution_claim(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            cycle = create_loop_cycle(
                paths,
                goal_summary="Finish all release-quality cleanup",
                goal_reframe="Continue implementation, review, CI, and release prep inside explicit gates.",
                success_criteria=["Release gate evidence exists"],
                permission_profile="execute_with_gates",
            )

            updated = update_loop_permission(paths, cycle["loop_id"], allow_actions=["merge"])
            card = build_loop_status_card(paths, cycle["loop_id"])

        self.assertEqual(updated["authority_envelope"]["permission_profile"], "custom")
        self.assertIn("merge", updated["authority_envelope"]["allowed_actions"])
        self.assertEqual(updated["authority_envelope"]["merge_authority"], "granted")
        self.assertFalse(card["completion_claim_allowed"])

    def test_loop_permission_preserves_explicit_forbidden_actions(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            cycle = create_loop_cycle(
                paths,
                goal_summary="Prepare public launch without publishing yet",
                goal_reframe="Create launch materials while keeping public posting behind explicit approval.",
                success_criteria=["Launch draft exists"],
                permission_profile="full_loop",
                forbid_actions=["external_posting"],
            )

            updated = update_loop_permission(paths, cycle["loop_id"], allow_actions=["external_posting_prep"])

        self.assertIn("external_posting", updated["authority_envelope"]["forbidden_actions"])
        self.assertNotIn("external_posting", updated["authority_envelope"]["allowed_actions"])
        self.assertEqual(updated["authority_envelope"]["external_action_authority"], "prepare_only")

    def test_empty_permission_profile_waits_for_permission_before_continue(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            cycle = create_loop_cycle(
                paths,
                goal_summary="Loop that still needs authority",
                goal_reframe="Wait until the wrapper records what this loop is allowed to do.",
                success_criteria=["Permission gate is explicit"],
                permission_profile="custom",
            )
            card = build_loop_status_card(paths, cycle["loop_id"])

        self.assertEqual(cycle["phase"], "waiting")
        self.assertEqual(cycle["wait_reason"], "permission_required")
        self.assertEqual(cycle["next_action"], "request_permission")
        self.assertEqual(card["next_action"], "request_permission")

    def test_permission_grant_clears_stale_request_permission_action(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            cycle = create_loop_cycle(
                paths,
                goal_summary="Loop that needs a later permit",
                goal_reframe="Resume once the user grants a concrete allowed action.",
                success_criteria=["Permission can be granted after start"],
                permission_profile="custom",
            )

            updated = update_loop_permission(paths, cycle["loop_id"], allow_actions=["research"])
            card = build_loop_status_card(paths, cycle["loop_id"])

        self.assertEqual(updated["wait_reason"], "none")
        self.assertEqual(updated["next_action"], "continue_loop")
        self.assertEqual(card["next_action"], "continue_loop")

    def test_loop_tick_prepares_runtime_queue_without_observed_execution(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            cycle = create_loop_cycle(
                paths,
                goal_summary="Become a loop engineering reference implementation",
                goal_reframe="Prepare repeated research, planning, handoff, and feedback slices with strict evidence boundaries.",
                success_criteria=["Runtime tick queue exists"],
                permission_profile="handoff_only",
                allowed_executors=["codex", "claude-code"],
            )

            updated = tick_loop_runtime(
                paths,
                cycle["loop_id"],
                trigger="scheduled",
                cadence="daily",
                worktree_base=".worktrees",
                subagent_role="researcher",
                connector="linear",
                connector_action="create_triage_comment",
                workflow_pattern="fan_out_synthesize",
            )
            card = build_loop_status_card(paths, cycle["loop_id"])

        queue = updated["runtime"]["queue"]
        self.assertEqual(updated["runtime"]["schema_version"], "loop_runtime/v1")
        self.assertEqual(updated["runtime"]["heartbeat_count"], 1)
        self.assertEqual(updated["next_action"], "observe_runtime_queue")
        self.assertEqual(queue[0]["schema_version"], "loop_queue_item/v1")
        self.assertEqual(queue[0]["planned_action"], "research")
        self.assertEqual(queue[0]["workflow_pattern"], "fan_out_synthesize")
        self.assertEqual(queue[0]["pipeline_step"], "task_discovery")
        self.assertEqual(queue[0]["cost_policy_ref"], "loop_engineering.cost_policy")
        self.assertEqual(queue[0]["loop_engineering"]["schema_version"], "loop_engineering/v1")
        self.assertEqual(queue[0]["loop_engineering"]["cost_policy_ref"], "loop_engineering.cost_policy")
        self.assertEqual(
            queue[0]["subagent_plan"]["result_contract"]["schema_version"],
            "loop_subagent_result_contract/v1",
        )
        self.assertIn("do not paste the full transcript", queue[0]["subagent_plan"]["result_contract"]["parent_context_policy"])
        self.assertTrue(queue[0]["subagent_plan"]["result_contract"]["cost_policy"]["bounded_reads"])
        self.assertEqual(queue[0]["status"], "prepared_not_observed")
        self.assertFalse(queue[0]["observed"])
        self.assertFalse(queue[0]["worktree_plan"]["created"])
        self.assertFalse(queue[0]["subagent_plan"]["dispatched"])
        self.assertFalse(queue[0]["connector_plan"]["dispatched"])
        self.assertEqual(queue[0]["connector_plan"]["connector"], "linear")
        self.assertEqual(card["runtime_summary"]["pending_queue_count"], 1)
        self.assertEqual(card["loop_engineering"]["current_pipeline_step"], "task_discovery")
        self.assertEqual(card["loop_engineering"]["workflow_patterns"]["used"], {"fan_out_synthesize": 1})
        self.assertEqual(card["loop_engineering"]["pipeline"][0]["state"], "observed")
        self.assertIn("structured result objects", card["loop_engineering"]["context_policy"]["subagent_return"])
        self.assertIn("Add verifier lanes only", card["loop_engineering"]["cost_policy"]["extra_verifier_policy"])
        self.assertIn("not worktree creation", card["runtime_summary"]["claim_boundary"])
        self.assertIn("prepared runtime queue", card["safe_copy"]["next_step"])
        self.assertEqual(validate_loop_cycle(updated), {"ok": True, "errors": []})

    def test_loop_queue_lifecycle_lists_handoffs_observes_and_blocks_items(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            cycle = create_loop_cycle(
                paths,
                goal_summary="Make loop queue work actionable",
                goal_reframe="Prepare runtime queue items and require explicit observation evidence before claiming they ran.",
                success_criteria=["Queue items can be listed", "Observation evidence is required"],
                permission_profile="handoff_only",
                allowed_executors=["codex"],
            )
            ticked = tick_loop_runtime(
                paths,
                cycle["loop_id"],
                worktree_base=".worktrees",
                subagent_role="researcher",
                connector="linear",
                connector_action="comment",
            )
            queue_id = ticked["runtime"]["queue"][0]["queue_id"]

            listing = list_loop_queue(paths, cycle["loop_id"])
            inspected = inspect_loop_queue_item(paths, cycle["loop_id"], queue_id)
            handoff = build_loop_queue_handoff(paths, cycle["loop_id"], queue_id)
            observed = observe_loop_queue_item(
                paths,
                cycle["loop_id"],
                queue_id,
                evidence_refs=["wrapper:queue-observation:1"],
                summary="Wrapper observed the queued research handoff.",
            )
            card = build_loop_status_card(paths, cycle["loop_id"])

        item = observed["runtime"]["queue"][0]
        self.assertEqual(listing["schema_version"], "loop_queue_list/v1")
        self.assertEqual(listing["pending_queue_count"], 1)
        self.assertEqual(listing["queue"][0]["workflow_pattern"], "single_step")
        self.assertEqual(listing["queue"][0]["pipeline_step"], "task_discovery")
        self.assertEqual(inspected["queue_item"]["queue_id"], queue_id)
        self.assertEqual(
            inspected["queue_item"]["subagent_plan"]["result_contract"]["required_fields"],
            ["status", "summary", "evidence_refs", "next_actions"],
        )
        self.assertEqual(handoff["schema_version"], "loop_queue_handoff/v1")
        self.assertIn("Continue OMH loop", handoff["handoff_text"])
        self.assertIn("Workflow pattern: single_step", handoff["handoff_text"])
        self.assertIn("Result contract: return status, summary, evidence_refs", handoff["handoff_text"])
        self.assertEqual(handoff["next_action"], "observe_or_block_loop_queue")
        self.assertEqual(item["status"], "observed")
        self.assertTrue(item["observed"])
        self.assertEqual(item["observed_evidence_refs"], ["wrapper:queue-observation:1"])
        self.assertFalse(item["worktree_plan"]["created"])
        self.assertFalse(item["subagent_plan"]["dispatched"])
        self.assertFalse(item["connector_plan"]["dispatched"])
        self.assertEqual(observed["phase"], "feedback")
        self.assertEqual(observed["next_action"], "record_feedback")
        self.assertEqual(card["runtime_summary"]["pending_queue_count"], 0)
        self.assertEqual(card["runtime_summary"]["observed_queue_count"], 1)
        self.assertEqual(validate_loop_cycle(observed), {"ok": True, "errors": []})

        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            cycle = create_loop_cycle(
                paths,
                goal_summary="Observe typed loop queue effects",
                goal_reframe="Only typed evidence should mark worktree, subagent, or connector effects observed.",
                success_criteria=["Typed evidence controls subplan observation"],
                permission_profile="handoff_only",
            )
            ticked = tick_loop_runtime(
                paths,
                cycle["loop_id"],
                connector="linear",
                connector_action="comment",
            )
            queue_id = ticked["runtime"]["queue"][0]["queue_id"]
            observed = observe_loop_queue_item(
                paths,
                cycle["loop_id"],
                queue_id,
                evidence_refs=["wrapper:queue-observation:2"],
                worktree_evidence_refs=["worktree:created:1"],
                subagent_evidence_refs=["subagent:dispatch:1"],
                connector_evidence_refs=["connector:linear:comment:1"],
            )

        typed_item = observed["runtime"]["queue"][0]
        self.assertTrue(typed_item["worktree_plan"]["created"])
        self.assertEqual(typed_item["worktree_plan"]["evidence_refs"], ["worktree:created:1"])
        self.assertTrue(typed_item["subagent_plan"]["dispatched"])
        self.assertEqual(typed_item["subagent_plan"]["evidence_refs"], ["subagent:dispatch:1"])
        self.assertTrue(typed_item["connector_plan"]["dispatched"])
        self.assertEqual(typed_item["connector_plan"]["evidence_refs"], ["connector:linear:comment:1"])
        self.assertEqual(validate_loop_cycle(observed), {"ok": True, "errors": []})

        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            cycle = create_loop_cycle(
                paths,
                goal_summary="Block a queue item safely",
                goal_reframe="Record queue blockers without creating observation evidence.",
                success_criteria=["Blocked queue items preserve evidence boundaries"],
                permission_profile="handoff_only",
            )
            ticked = tick_loop_runtime(paths, cycle["loop_id"])
            queue_id = ticked["runtime"]["queue"][0]["queue_id"]
            blocked = block_loop_queue_item(paths, cycle["loop_id"], queue_id, reason="Need maintainer approval")
            card = build_loop_status_card(paths, cycle["loop_id"])

        blocked_item = blocked["runtime"]["queue"][0]
        self.assertEqual(blocked_item["status"], "blocked")
        self.assertFalse(blocked_item["observed"])
        self.assertEqual(blocked_item["blocker_reason"], "Need maintainer approval")
        self.assertEqual(blocked["phase"], "blocked")
        self.assertEqual(blocked["next_action"], "resolve_runtime_queue_blocker")
        self.assertEqual(card["runtime_summary"]["blocked_queue_count"], 1)
        self.assertFalse(blocked_item["worktree_plan"]["created"])
        self.assertFalse(blocked_item["subagent_plan"]["dispatched"])
        self.assertEqual(validate_loop_cycle(blocked), {"ok": True, "errors": []})

    def test_loop_tick_respects_external_wait_and_permission_gate(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            waiting = create_loop_cycle(
                paths,
                goal_summary="Reach public adoption",
                goal_reframe="Keep internal work separate from public response waiting.",
                success_criteria=["External wait is respected"],
            )
            record_loop_feedback(paths, waiting["loop_id"], external_wait="Waiting for market response")

            blocked_by_wait = tick_loop_runtime(paths, waiting["loop_id"], trigger="automation")

            permission = create_loop_cycle(
                paths,
                goal_summary="Start only after the user picks authority",
                goal_reframe="Ask for an allowed action before queueing work.",
                success_criteria=["Permission is requested"],
                permission_profile="custom",
            )
            blocked_by_permission = tick_loop_runtime(paths, permission["loop_id"], trigger="wrapper")

        self.assertEqual(blocked_by_wait["next_action"], "record_external_wait")
        self.assertEqual(blocked_by_wait["runtime"]["queue"][0]["status"], "blocked_by_wait")
        self.assertEqual(blocked_by_wait["runtime"]["queue"][0]["planned_action"], "wait_for_external_observation")
        self.assertEqual(blocked_by_wait["runtime"]["queue"][0]["worktree_plan"]["strategy"], "none")
        self.assertEqual(blocked_by_wait["runtime"]["queue"][0]["subagent_plan"]["strategy"], "none")
        self.assertEqual(blocked_by_permission["next_action"], "request_permission")
        self.assertEqual(blocked_by_permission["runtime"]["queue"][0]["status"], "blocked_by_permission")
        self.assertEqual(blocked_by_permission["runtime"]["queue"][0]["planned_action"], "request_permission")
        self.assertEqual(blocked_by_permission["runtime"]["queue"][0]["worktree_plan"]["strategy"], "none")

    def test_loop_runtime_validation_rejects_prepared_items_with_observed_claims(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            cycle = create_loop_cycle(
                paths,
                goal_summary="Protect prepared observed boundaries",
                goal_reframe="Reject local runtime queue entries that pretend prepared work already happened.",
                success_criteria=["Contradictory runtime evidence is rejected"],
                permission_profile="execute_with_gates",
            )

            updated = tick_loop_runtime(paths, cycle["loop_id"], connector="linear")

        item = updated["runtime"]["queue"][0]
        item["observed"] = True
        item["worktree_plan"]["created"] = True
        item["subagent_plan"]["dispatched"] = True
        item["connector_plan"]["dispatched"] = True
        validation = validate_loop_cycle(updated)

        self.assertFalse(validation["ok"])
        self.assertIn("runtime.queue[0].observed must be false unless status is observed", validation["errors"])
        self.assertIn("runtime.queue[0].worktree_plan.created must be false before observation", validation["errors"])
        self.assertIn("runtime.queue[0].subagent_plan.dispatched must be false before observation", validation["errors"])
        self.assertIn("runtime.queue[0].connector_plan.dispatched must be false before observation", validation["errors"])

    def test_loop_runtime_validation_rejects_observed_status_without_observed_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            cycle = create_loop_cycle(
                paths,
                goal_summary="Protect observed status boundaries",
                goal_reframe="Reject runtime queue entries that claim observed status without evidence flags.",
                success_criteria=["Observed status requires observed evidence"],
                permission_profile="execute_with_gates",
            )

            updated = tick_loop_runtime(paths, cycle["loop_id"], connector="linear")

        item = updated["runtime"]["queue"][0]
        item["status"] = "observed"
        validation = validate_loop_cycle(updated)

        self.assertFalse(validation["ok"])
        self.assertIn("runtime.queue[0].observed must be true when status is observed", validation["errors"])
        self.assertIn("runtime.queue[0].observed_evidence_refs must include at least one evidence ref when observed", validation["errors"])

    def test_loop_runtime_validation_rejects_typed_observed_subplans_without_typed_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            cycle = create_loop_cycle(
                paths,
                goal_summary="Protect typed subplan boundaries",
                goal_reframe="Reject runtime queue entries that mark subplans observed without typed evidence refs.",
                success_criteria=["Typed observed effects require typed evidence"],
                permission_profile="execute_with_gates",
            )

            updated = tick_loop_runtime(paths, cycle["loop_id"], connector="linear")

        item = updated["runtime"]["queue"][0]
        item["status"] = "observed"
        item["observed"] = True
        item["observed_evidence_refs"] = ["wrapper:queue:observed"]
        item["worktree_plan"]["created"] = True
        item["worktree_plan"]["observed"] = True
        item["subagent_plan"]["dispatched"] = True
        item["subagent_plan"]["observed"] = True
        item["connector_plan"]["dispatched"] = True
        item["connector_plan"]["observed"] = True
        validation = validate_loop_cycle(updated)

        self.assertFalse(validation["ok"])
        self.assertIn("runtime.queue[0].worktree_plan.evidence_refs must include at least one typed evidence ref when observed", validation["errors"])
        self.assertIn("runtime.queue[0].subagent_plan.evidence_refs must include at least one typed evidence ref when observed", validation["errors"])
        self.assertIn("runtime.queue[0].connector_plan.evidence_refs must include at least one typed evidence ref when observed", validation["errors"])

    def test_loop_runtime_validation_rejects_invalid_engineering_and_result_contracts(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            cycle = create_loop_cycle(
                paths,
                goal_summary="Keep loop context bounded",
                goal_reframe="Reject runtime entries that lose the structured loop engineering and subagent result contract.",
                success_criteria=["Loop engineering contracts are validated"],
                permission_profile="handoff_only",
            )

            updated = tick_loop_runtime(paths, cycle["loop_id"], workflow_pattern="tournament")

        item = updated["runtime"]["queue"][0]
        item["workflow_pattern"] = "unknown_pattern"
        item["pipeline_step"] = "unknown_step"
        item["loop_engineering"]["schema_version"] = "wrong"
        item["subagent_plan"]["result_contract"]["schema_version"] = "wrong"
        validation = validate_loop_cycle(updated)

        self.assertFalse(validation["ok"])
        self.assertIn("runtime.queue[0].workflow_pattern is unsupported", validation["errors"])
        self.assertIn("runtime.queue[0].pipeline_step is unsupported", validation["errors"])
        self.assertIn("runtime.queue[0].loop_engineering.schema_version must be loop_engineering/v1", validation["errors"])
        self.assertIn(
            "runtime.queue[0].subagent_plan.result_contract.schema_version must be loop_subagent_result_contract/v1",
            validation["errors"],
        )

        item["subagent_plan"].pop("result_contract")
        validation = validate_loop_cycle(updated)

        self.assertFalse(validation["ok"])
        self.assertIn("runtime.queue[0].subagent_plan.result_contract must be an object", validation["errors"])


if __name__ == "__main__":
    unittest.main()
