from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from _local_package import load_local_package

load_local_package()
from omh.catalogs.specialists import recommend_specialist, specialist_definitions, validate_specialist_catalog
from omh.coding_delegation import build_coding_delegation_payload, coding_delegation_record_payload
from omh.quality.specialist_work import (
    build_specialist_work_quality_contract,
    evaluate_observed_goal_achievement,
)
from omh.routing.route_plan import build_workflow_route_plan
from omh.runtime.records import validate_coding_delegation_record


class SpecialistWorkTests(unittest.TestCase):
    def test_catalog_keeps_specialists_distinct_from_skills_roles_and_executors(self) -> None:
        catalog = validate_specialist_catalog()

        self.assertTrue(catalog["ok"], catalog["errors"])
        self.assertGreaterEqual(len(specialist_definitions()), 6)
        self.assertTrue(
            all(profile.activation_policy in {"router_suggested", "plan_selected", "handoff_selected"} for profile in specialist_definitions())
        )
        self.assertTrue(all(profile.runtime_claim == "prepared_profile_not_runtime_agent" for profile in specialist_definitions()))

    def test_prepared_contract_never_counts_as_observed_goal_achievement(self) -> None:
        contract = build_specialist_work_quality_contract(
            "ultragoal",
            phase="implementation",
            acceptance_criteria=("The requested capability is implemented.", "Verification evidence is recorded."),
        )

        self.assertEqual(contract["status"], "prepared_not_observed")
        self.assertEqual(contract["specialist"]["id"], "implementation-handoff")
        self.assertEqual(contract["progress"]["prepared_coverage_percent"], 100)
        self.assertEqual(contract["progress"]["observed_goal_achievement_percent"], 0)
        self.assertEqual(contract["claim_integrity"]["state"], "unverified")
        self.assertIn("prepared_state_is_not_observed_completion", contract["claim_integrity"]["anti_cheating_rules"])

    def test_recommender_selects_only_an_eligible_prepared_specialist(self) -> None:
        recommendation = recommend_specialist("visual-qa", task_phase="verification")

        self.assertIsNotNone(recommendation)
        assert recommendation is not None
        self.assertEqual(recommendation["status"], "prepared_not_observed")
        self.assertEqual(recommendation["specialist"]["id"], "visual-quality")
        self.assertIsNone(recommend_specialist("visual-qa", task_phase="implementation"))
        self.assertIsNone(recommend_specialist("not-an-installed-skill", task_phase="implementation"))

    def test_foreign_stale_or_self_attested_evidence_cannot_raise_observed_progress(self) -> None:
        contract = build_specialist_work_quality_contract(
            "ultragoal",
            phase="implementation",
            acceptance_criteria=("The requested capability is implemented.",),
        )
        goal = contract["goal"]
        binding = contract["evidence_binding"]
        stale = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        evidence = [
            {
                "criterion_id": "AC001",
                "status": "observed",
                "source_kind": "self_report",
                "goal_binding_digest": goal["binding_digest"],
                "selected_skill": "ultragoal",
                "specialist_id": binding["specialist_id"],
                "plan_digest": binding["plan_digest"],
                "observed_at": stale,
            },
            {
                "criterion_id": "AC001",
                "status": "observed",
                "source_kind": "command",
                "goal_binding_digest": "foreign",
                "selected_skill": "ultragoal",
                "specialist_id": binding["specialist_id"],
                "plan_digest": binding["plan_digest"],
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "criterion_id": "AC001",
                "status": "observed",
                "source_kind": "command",
                "goal_binding_digest": goal["binding_digest"],
                "selected_skill": "ultragoal",
                "specialist_id": "foreign-specialist",
                "plan_digest": binding["plan_digest"],
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
        ]

        result = evaluate_observed_goal_achievement(contract, evidence)

        self.assertEqual(result["observed_goal_achievement_percent"], 0)
        self.assertEqual(result["claim_integrity"]["state"], "failed")
        self.assertIn("self_attested_evidence", result["claim_integrity"]["violations"])
        self.assertIn("foreign_goal_binding", result["claim_integrity"]["violations"])
        self.assertIn("foreign_specialist_profile", result["claim_integrity"]["violations"])

    def test_future_dated_evidence_cannot_bypass_freshness(self) -> None:
        contract = build_specialist_work_quality_contract(
            "ultragoal",
            phase="implementation",
            acceptance_criteria=("The requested capability is implemented.",),
        )
        goal = contract["goal"]
        binding = contract["evidence_binding"]
        evidence = [
            {
                "criterion_id": "AC001",
                "status": "observed",
                "source_kind": "command",
                "goal_binding_digest": goal["binding_digest"],
                "selected_skill": "ultragoal",
                "specialist_id": binding["specialist_id"],
                "plan_digest": binding["plan_digest"],
                "observed_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
            }
        ]

        result = evaluate_observed_goal_achievement(contract, evidence)

        self.assertEqual(result["observed_goal_achievement_percent"], 0)
        self.assertIn("future_evidence", result["claim_integrity"]["violations"])

    def test_matching_fresh_observed_evidence_is_the_only_path_to_goal_progress(self) -> None:
        contract = build_specialist_work_quality_contract(
            "ultragoal",
            phase="implementation",
            acceptance_criteria=("The requested capability is implemented.",),
        )
        goal = contract["goal"]
        binding = contract["evidence_binding"]
        evidence = [
            {
                "criterion_id": "AC001",
                "status": "observed",
                "source_kind": "command",
                "goal_binding_digest": goal["binding_digest"],
                "selected_skill": "ultragoal",
                "specialist_id": binding["specialist_id"],
                "plan_digest": binding["plan_digest"],
                "observed_at": datetime.now(timezone.utc).isoformat(),
            }
        ]

        result = evaluate_observed_goal_achievement(contract, evidence)

        self.assertEqual(result["observed_goal_achievement_percent"], 100)
        self.assertEqual(result["claim_integrity"]["state"], "verified")

    def test_route_and_handoff_project_the_specialist_contract_without_claiming_execution(self) -> None:
        route_plan = build_workflow_route_plan(
            "implement a verified feature",
            [
                {"skill": "plan", "score": 7, "confidence": "high", "matched": ["plan"]},
                {"skill": "ultragoal", "score": 9, "confidence": "high", "matched": ["implement"]},
            ],
            selected_skill="ultragoal",
            action="dispatch",
        )
        handoff = build_coding_delegation_payload(
            "Implement a small Python capability with tests.",
            executor_target="codex",
            preferred_workflow="ultragoal",
            preferred_workflow_score=9,
            force_coding_handoff=True,
        )

        self.assertIsNotNone(route_plan)
        assert route_plan is not None
        self.assertEqual(route_plan["specialist_work_quality"]["status"], "prepared_not_observed")
        self.assertEqual(route_plan["specialist_work_quality"]["specialist"]["id"], "implementation-handoff")
        self.assertEqual(handoff["specialist_work_quality"]["status"], "prepared_not_observed")
        self.assertIn("specialist_work_quality", handoff["executor_handoff"])
        self.assertIn("not execution", handoff["specialist_work_quality"]["claim_boundary"].lower())
        record = coding_delegation_record_payload(
            handoff,
            "Implement a small Python capability with tests.",
        )
        record["updated_at"] = "2026-07-16T00:00:00Z"
        self.assertEqual(validate_coding_delegation_record(record), [])
