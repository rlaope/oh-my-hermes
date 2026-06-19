from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.isolation import build_isolation_plan


class IsolationPlanTests(unittest.TestCase):
    def test_multilingual_risky_refactor_recommends_worktree(self) -> None:
        plan = build_isolation_plan(
            "위험한 리팩터링 같아",
            intent="implementation",
            workflow="ralplan",
            work_owner_mode="executor_handoff",
            selected_executor_profile="codex",
        )

        self.assertEqual(plan["schema_version"], "worktree_session_isolation/v1")
        self.assertEqual(plan["strategy"], "worktree_recommended")
        self.assertEqual(plan["risk_level"], "high")
        self.assertIn("prepare_worktree", plan["wrapper_actions"])

    def test_parallel_multilingual_terms_require_worktree(self) -> None:
        plan = build_isolation_plan(
            "병렬로 팀 작업해줘",
            intent="implementation",
            workflow="ultrawork",
            work_owner_mode="runtime_handoff",
            selected_executor_profile="omx-runtime",
        )

        self.assertEqual(plan["strategy"], "worktree_required")
        self.assertIn("open_executor_session", plan["required_before"])
        self.assertIn("prepare_worktree", plan["wrapper_actions"])


if __name__ == "__main__":
    unittest.main()
