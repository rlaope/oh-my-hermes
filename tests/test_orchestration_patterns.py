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
            "scheduled_ops_blueprint",
            "research_department_workflow",
            "executor_session_handoff",
            "hermes_coding_team_path",
            "materials_generation_handoff",
        }:
            self.assertIn(expected, patterns)

        handoff = patterns["executor_session_handoff"]
        self.assertEqual(handoff["owner_role"], "handoff-guide")
        self.assertIn("choose_executor", handoff["wrapper_actions"])
        self.assertIn("dispatch_observed", handoff["observed_evidence_required"])
        self.assertIn("not execution", handoff["prepared_is_not"])

        worktree = patterns["worktree_isolated_workers"]
        self.assertIn("worktree_creation_observed", worktree["observed_evidence_required"])
        self.assertIn("Do not claim worktrees exist", worktree["do_not_use_when"])

        scheduled = patterns["scheduled_ops_blueprint"]
        self.assertIn("automation-blueprint", scheduled["compatible_skills"])
        self.assertIn("host_schedule_observed", scheduled["observed_evidence_required"])
        self.assertIn("Do not claim host cron", scheduled["do_not_use_when"])

        research_department = patterns["research_department_workflow"]
        self.assertIn("research-department", research_department["compatible_skills"])
        self.assertIn("research_department_plan/v1", research_department["prepared_artifacts"])
        self.assertIn("source retrieval", research_department["do_not_use_when"])

        hermes_team = patterns["hermes_coding_team_path"]
        self.assertIn("record_runtime_observation", hermes_team["wrapper_actions"])
        self.assertIn("merge_observed", hermes_team["observed_evidence_required"])
