from __future__ import annotations

import json
import unittest
from pathlib import Path


class WrapperGoldenExampleTests(unittest.TestCase):
    def test_status_ladder_golden_examples_cover_required_scenarios(self) -> None:
        payload = json.loads(Path("examples/wrapper-golden/status-ladder.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "wrapper_golden_examples/v1")
        scenarios = {item["scenario"]: item for item in payload["scenarios"]}

        required = {
            "clarify_needed",
            "plan_presented",
            "deep_interview_blocked_plan",
            "handoff_prepared",
            "dispatched_executor_not_observed",
            "review_pending",
            "status_card_review_pending",
            "ci_pending",
            "ci_failed",
            "merge_ready",
            "merged",
            "contradictory_merge_ready_without_ci",
        }
        self.assertEqual(set(scenarios), required)

        for item in payload["scenarios"]:
            response = item["expected_response"]
            self.assertEqual(response["schema_version"], "chat_response/v1")
            self.assertIn(item["source"], {"discord", "slack"})
            self.assertTrue(item["claim_boundary"])
            self.assertTrue(response["headline"])
            self.assertTrue(response["body"])
            self.assertIsInstance(response["action_ids"], list)
            self.assertNotIn("omh ", json.dumps(item).lower())
            self.assertNotIn("token", json.dumps(item).lower())
            if "expected_status_card" in item:
                card = item["expected_status_card"]
                self.assertEqual(card["schema_version"], "status_card/v1")
                self.assertIsInstance(card["steps"], list)
                self.assertTrue(all({"id", "state"} <= set(step) for step in card["steps"]))
            if "expected_deep_interview" in item:
                interview = item["expected_deep_interview"]
                self.assertEqual(interview["schema_version"], "deep_interview_contract/v1")
                self.assertTrue(interview["required"])
                self.assertEqual(interview["question_style"], "one_question")

    def test_discord_and_slack_examples_share_platform_neutral_action_ids(self) -> None:
        payload = json.loads(Path("examples/wrapper-golden/status-ladder.json").read_text(encoding="utf-8"))
        action_ids = {action_id for item in payload["scenarios"] for action_id in item["expected_response"]["action_ids"]}

        self.assertLessEqual(action_ids, {"answer:clarify", "accept_plan", "revise_plan", "send_to_codex", "show_status", "cancel"})
        self.assertIn("show_status", action_ids)

    def test_contradictory_fixture_names_upstream_blocker(self) -> None:
        payload = json.loads(Path("examples/wrapper-golden/status-ladder.json").read_text(encoding="utf-8"))
        item = next(item for item in payload["scenarios"] if item["scenario"] == "contradictory_merge_ready_without_ci")

        self.assertIn("CI evidence is still missing", item["expected_response"]["headline"])
        self.assertIn("cannot override", item["expected_response"]["body"])
        self.assertIn("upstream CI blocker", item["claim_boundary"])

    def test_status_card_fixture_keeps_review_pending_visible(self) -> None:
        payload = json.loads(Path("examples/wrapper-golden/status-ladder.json").read_text(encoding="utf-8"))
        item = next(item for item in payload["scenarios"] if item["scenario"] == "status_card_review_pending")
        steps = {step["id"]: step["state"] for step in item["expected_status_card"]["steps"]}

        self.assertEqual(item["expected_status_card"]["severity"], "attention")
        self.assertEqual(steps["execution"], "complete")
        self.assertEqual(steps["verification"], "complete")
        self.assertEqual(steps["review"], "pending")
        self.assertEqual(steps["merge_ready"], "pending")

    def test_deep_interview_fixture_is_one_question_before_plan(self) -> None:
        payload = json.loads(Path("examples/wrapper-golden/status-ladder.json").read_text(encoding="utf-8"))
        item = next(item for item in payload["scenarios"] if item["scenario"] == "deep_interview_blocked_plan")
        interview = item["expected_deep_interview"]

        self.assertEqual(item["expected_response"]["kind"], "clarification")
        self.assertEqual(interview["question_style"], "one_question")
        self.assertIn("target outcome", interview["missing_decisions"])
        self.assertEqual(interview["after_answer_next_action"], "rerun_hermes_plan")


if __name__ == "__main__":
    unittest.main()
