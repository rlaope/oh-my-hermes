"""Golden routing-quality gate for the deterministic meta-router.

These cases are intentionally small and user-shaped. They protect the public
route decision contract and make changes to catalog scoring visible as an
accuracy/guardrail regression instead of only a low-level fixture diff.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.routing.chat import route_chat_message


class RoutingQualityGateTests(unittest.TestCase):
    DISPATCH_CASES = (
        ("find official docs for the current OpenAI API version", "best-practice-research"),
        ("plan a safe implementation for this feature", "plan"),
        ("fix the failing test in this repository", "ultraprocess"),
        ("remember this decision for later", "memory-new"),
        ("explain this paper at expert level", "paper-learning"),
        ("create an image summary card", "img-summary"),
        ("customers say checkout click path is broken", "feedback-triage"),
    )

    def test_known_lanes_meet_dispatch_accuracy_baseline(self) -> None:
        results = [
            route_chat_message(message, source="discord")
            for message, _expected_skill in self.DISPATCH_CASES
        ]
        correct = sum(
            decision.get("selected_skill") == expected_skill
            for decision, (_message, expected_skill) in zip(results, self.DISPATCH_CASES)
        )

        self.assertEqual(correct, len(self.DISPATCH_CASES))
        self.assertEqual(correct / len(self.DISPATCH_CASES), 1.0)
        for decision in results:
            self.assertEqual(decision["action"], "dispatch")
            contract = decision["route_decision"]
            self.assertEqual(contract["schema_version"], "route_decision/v1")
            self.assertIn(contract["confidence"], {"medium", "high"})

    def test_ambiguous_requests_remain_guarded(self) -> None:
        decision = route_chat_message("help me with this", source="discord")

        self.assertEqual(decision["action"], "clarify")
        contract = decision["route_decision"]
        self.assertTrue(contract["ambiguous"])
        self.assertIn(contract["confidence"], {"low", "medium"})
        self.assertGreaterEqual(len(contract["candidates"]), 2)
        self.assertEqual(contract["threshold"], "high")

    def test_unknown_requests_use_explicit_fallback(self) -> None:
        decision = route_chat_message("zzzzunknownphrase", source="discord")

        self.assertEqual(decision["action"], "fallback")
        contract = decision["route_decision"]
        self.assertTrue(contract["fallback"])
        self.assertEqual(contract["router_stage"], "fallback")
        self.assertEqual(contract["confidence"], "low")
        self.assertGreaterEqual(len(contract["candidates"]), 1)


if __name__ == "__main__":
    unittest.main()
