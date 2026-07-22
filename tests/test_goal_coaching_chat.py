from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

from _local_package import load_local_package

load_local_package()
from omh.wrapper.contract import build_chat_interaction_payload, build_goal_quality_coaching_card
from omh.workflows import goal_quality_coaching
from omh.workflows.goal_ledger import goal_message_states_acceptance_criteria


GOAL_WITHOUT_CRITERIA = "improve the onboarding experience"
GOAL_WITH_CRITERIA = (
    "improve the onboarding experience. done when new users complete signup in under 2 minutes."
)
NON_GOAL_MESSAGE = "please fix the typo in README"
KOREAN_GOAL_WITHOUT_CRITERIA = "온보딩을 개선해줘"

GOLDEN_PATH = Path("examples/wrapper-golden/goal-quality-coaching.json")


class GoalQualityCoachingChatTests(unittest.TestCase):
    def test_criteria_absent_goal_message_shows_coaching_card(self) -> None:
        payload = build_chat_interaction_payload(GOAL_WITHOUT_CRITERIA, source="slack")

        card = payload.get("goal_quality_coaching_card")
        self.assertIsInstance(card, dict)
        self.assertEqual(card["schema_version"], "goal_quality_coaching_card/v1")
        self.assertEqual(card["kind"], "goal_quality_coaching")
        self.assertEqual(card["next_action"], "state_goal_success_criteria")
        self.assertTrue(card["headline"])
        self.assertTrue(card["body"])

        state = payload["chat_response"]["state"]
        self.assertEqual(state.get("goal_quality_coaching_card"), card)
        self.assertIn(card["body"], payload["chat_response"]["body"])
        action_ids = {action["id"] for action in payload["chat_response"]["actions"]}
        self.assertIn("state_goal_success_criteria", action_ids)

    def test_criteria_present_goal_has_no_coaching_card(self) -> None:
        payload = build_chat_interaction_payload(GOAL_WITH_CRITERIA, source="slack")

        self.assertNotIn("goal_quality_coaching_card", payload)
        state = payload["chat_response"]["state"]
        self.assertNotIn("goal_quality_coaching_card", state)

    def test_non_goal_chat_has_no_coaching_card(self) -> None:
        payload = build_chat_interaction_payload(NON_GOAL_MESSAGE, source="slack")

        self.assertNotIn("goal_quality_coaching_card", payload)
        state = payload["chat_response"]["state"]
        self.assertNotIn("goal_quality_coaching_card", state)

    def test_non_goal_question_has_no_coaching_card(self) -> None:
        payload = build_chat_interaction_payload("what does OMH do?", source="slack")

        self.assertNotIn("goal_quality_coaching_card", payload)

    def test_korean_goal_without_criteria_shows_localized_coaching_card(self) -> None:
        card = build_goal_quality_coaching_card(KOREAN_GOAL_WITHOUT_CRITERIA)

        self.assertIsInstance(card, dict)
        self.assertIn("목표", card["headline"])
        self.assertIn("완료", card["body"])

    def test_coaching_path_reuses_goal_ledger_criteria_validation_single_source(self) -> None:
        # The coaching module must call into goal_ledger's shared criteria validation
        # instead of re-implementing "what counts as a stated criterion".
        source = Path("src/wrapper/contract.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_names = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        self.assertIn("goal_message_states_acceptance_criteria", imported_names)

        coaching_source = Path("src/workflows/goal_quality_coaching.py").read_text(encoding="utf-8")
        # The classification module must not define its own criteria-list validator;
        # it only decides whether a message is goal-classified.
        self.assertNotIn("acceptance criterion", coaching_source)

        ledger_source = Path("src/workflows/goal_ledger.py").read_text(encoding="utf-8")
        self.assertIn("def goal_message_states_acceptance_criteria", ledger_source)
        self.assertIn("_criteria_objects(candidates)", ledger_source)

        # Sanity: the shared helper actually works the way both callers expect.
        self.assertTrue(goal_message_states_acceptance_criteria("done when the tests pass"))
        self.assertFalse(goal_message_states_acceptance_criteria("no criteria mentioned here"))

    def test_coaching_card_body_is_plain_language_not_raw_json(self) -> None:
        card = build_goal_quality_coaching_card(GOAL_WITHOUT_CRITERIA)
        self.assertIsInstance(card, dict)
        for field_name in ("headline", "body"):
            text = card[field_name]
            self.assertNotIn("{", text)
            self.assertNotIn("}", text)
            self.assertNotIn('"schema_version"', text)

        payload = build_chat_interaction_payload(GOAL_WITHOUT_CRITERIA, source="slack")
        body = payload["chat_response"]["body"]
        self.assertNotIn("{", body)
        self.assertNotIn("}", body)

    def test_is_goal_classified_message_excludes_direct_tasks_and_external_wait(self) -> None:
        self.assertFalse(goal_quality_coaching.is_goal_classified_message(NON_GOAL_MESSAGE))
        self.assertFalse(goal_quality_coaching.is_goal_classified_message(""))
        self.assertTrue(goal_quality_coaching.is_goal_classified_message(GOAL_WITHOUT_CRITERIA))

    def test_golden_goal_quality_coaching_examples(self) -> None:
        payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "goal_quality_coaching_golden_examples/v1")

        for item in payload["scenarios"]:
            with self.subTest(item["scenario"]):
                live = build_chat_interaction_payload(item["message"], source=item["source"])
                expected_card = item["expected_goal_quality_coaching_card"]
                live_card = live.get("goal_quality_coaching_card")
                if expected_card is None:
                    self.assertIsNone(live_card)
                    continue
                self.assertIsInstance(live_card, dict)
                self.assertEqual(live_card["schema_version"], expected_card["schema_version"])
                self.assertEqual(live_card["kind"], expected_card["kind"])
                self.assertEqual(live_card["headline"], expected_card["headline"])
                self.assertEqual(live_card["next_action"], expected_card["next_action"])
                self.assertEqual(live_card["claim_boundary"], item["claim_boundary"])
                serialized = json.dumps(item).lower()
                for phrase in item.get("not_evidence", []):
                    self.assertNotIn(phrase.lower(), live_card["body"].lower())
                self.assertNotIn("token", serialized)


if __name__ == "__main__":
    unittest.main()
