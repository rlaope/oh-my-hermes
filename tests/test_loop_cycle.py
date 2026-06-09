from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.goal_loop import (
    LOOP_CYCLE_SCHEMA,
    LOOP_STATUS_CARD_SCHEMA,
    build_loop_status_card,
    create_loop_cycle,
    record_loop_feedback,
    tick_loop_runtime,
    update_loop_permission,
    validate_loop_cycle,
)
from omh.paths import resolve_paths


class GoalLoopTests(unittest.TestCase):
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
            )
            card = build_loop_status_card(paths, cycle["loop_id"])

        queue = updated["runtime"]["queue"]
        self.assertEqual(updated["runtime"]["schema_version"], "loop_runtime/v1")
        self.assertEqual(updated["runtime"]["heartbeat_count"], 1)
        self.assertEqual(updated["next_action"], "observe_runtime_queue")
        self.assertEqual(queue[0]["schema_version"], "loop_queue_item/v1")
        self.assertEqual(queue[0]["planned_action"], "research")
        self.assertEqual(queue[0]["status"], "prepared_not_observed")
        self.assertFalse(queue[0]["observed"])
        self.assertFalse(queue[0]["worktree_plan"]["created"])
        self.assertFalse(queue[0]["subagent_plan"]["dispatched"])
        self.assertFalse(queue[0]["connector_plan"]["dispatched"])
        self.assertEqual(queue[0]["connector_plan"]["connector"], "linear")
        self.assertEqual(card["runtime_summary"]["pending_queue_count"], 1)
        self.assertIn("not worktree creation", card["runtime_summary"]["claim_boundary"])
        self.assertIn("prepared runtime queue", card["safe_copy"]["next_step"])
        self.assertEqual(validate_loop_cycle(updated), {"ok": True, "errors": []})

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
        self.assertIn("runtime.queue[0].worktree_plan.created must be true when observed", validation["errors"])
        self.assertIn("runtime.queue[0].subagent_plan.dispatched must be true when observed", validation["errors"])
        self.assertIn("runtime.queue[0].connector_plan.dispatched must be true when observed", validation["errors"])


if __name__ == "__main__":
    unittest.main()
