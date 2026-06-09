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


if __name__ == "__main__":
    unittest.main()
