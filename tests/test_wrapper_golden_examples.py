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
            "handoff_prepared",
            "dispatched_executor_not_observed",
            "review_pending",
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


if __name__ == "__main__":
    unittest.main()
