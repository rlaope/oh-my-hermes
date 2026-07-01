from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()
from omh.agentic_playbook import AGENTIC_PLAYBOOK_SCHEMA_VERSION, classify_agentic_playbook
from omh.coding_delegation import build_coding_delegation_payload
from omh.routing.chat import public_chat_route_payload


class AgenticPlaybookTests(unittest.TestCase):
    def test_classifier_attaches_for_coding_delegation_with_selected_executor(self) -> None:
        message = "risky refactor with tests"
        route_payload = public_chat_route_payload(message, source="discord")
        delegation_payload = build_coding_delegation_payload(message, source="discord", executor_target="codex")

        classification = classify_agentic_playbook(
            message,
            route_payload=route_payload,
            delegation_payload=delegation_payload,
        )

        self.assertEqual(classification["schema_version"], AGENTIC_PLAYBOOK_SCHEMA_VERSION)
        self.assertEqual(classification["decision"], "attach_playbook")
        self.assertEqual(classification["confidence"], "high")
        self.assertIn("delegation_action_delegate", classification["reasons"])
        self.assertIn("selected_executor_profile", classification["source_contracts"])
        self.assertNotIn(message, json.dumps(classification))

    def test_builder_expected_outputs_stays_single_contract_item(self) -> None:
        delegation_payload = build_coding_delegation_payload(
            "risky refactor with tests",
            source="discord",
            executor_target="codex",
        )

        playbook = delegation_payload["agentic_playbook"]
        steps = {step["id"]: step for step in playbook["steps"]}

        self.assertEqual(
            steps["builder"]["expected_outputs"],
            ["implementation evidence from the selected owner"],
        )

    def test_classifier_keeps_trackpad_question_on_light_path(self) -> None:
        message = "why does my trackpad scroll feel reversed?"
        route_payload = public_chat_route_payload(message, source="discord")

        classification = classify_agentic_playbook(message, route_payload=route_payload)

        self.assertEqual(classification["decision"], "light_path")
        self.assertEqual(classification["confidence"], "high")
        self.assertIn("non_coding_troubleshooting", classification["anti_signals"])
        self.assertNotIn("clarification", classification)

    def test_classifier_uses_existing_clarification_for_boundary_code_tweak(self) -> None:
        message = "can you check if this needs a small code tweak?"
        route_payload = public_chat_route_payload(message, source="discord")

        classification = classify_agentic_playbook(message, route_payload=route_payload)

        self.assertEqual(classification["decision"], "clarify")
        self.assertEqual(classification["confidence"], "low")
        self.assertIn("route_action_clarify", classification["source_contracts"])
        self.assertEqual(
            classification["clarification"],
            "Do you want a quick answer, or should I prepare the staged implementation workflow?",
        )


if __name__ == "__main__":
    unittest.main()
