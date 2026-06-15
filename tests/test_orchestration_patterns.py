from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.capabilities.orchestration import orchestration_patterns


class OrchestrationPatternTests(unittest.TestCase):
    def test_orchestration_patterns_include_team_worktree_loop_and_handoff_without_claiming_execution(self) -> None:
        patterns = {item["id"]: item for item in orchestration_patterns()}

        for expected in {
            "single_lane",
            "clarify_then_plan",
            "plan_execute_verify",
            "team_staged_pipeline",
            "swarm_batch",
            "worktree_isolated_workers",
            "loop_run_once",
            "executor_session_handoff",
            "materials_generation_handoff",
        }:
            self.assertIn(expected, patterns)

        handoff = patterns["executor_session_handoff"]
        self.assertEqual(handoff["owner_role"], "coding-handoff")
        self.assertIn("choose_executor", handoff["wrapper_actions"])
        self.assertIn("dispatch_observed", handoff["observed_evidence_required"])
        self.assertIn("not execution", handoff["prepared_is_not"])

        worktree = patterns["worktree_isolated_workers"]
        self.assertIn("worktree_creation_observed", worktree["observed_evidence_required"])
        self.assertIn("Do not claim worktrees exist", worktree["do_not_use_when"])
