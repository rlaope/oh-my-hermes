from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()
from omh.chat_router import (
    extract_message_text,
    public_route_payload,
    route_chat_event,
    route_chat_message,
    routing_record_payload,
)


class ChatRouterTests(unittest.TestCase):
    def test_high_confidence_chat_dispatches_to_workflow(self) -> None:
        decision = route_chat_message("risky refactor", source="discord")

        self.assertEqual(decision["action"], "dispatch")
        self.assertEqual(decision["selected_skill"], "ai-slop-cleaner")
        self.assertEqual(decision["selected_harness"], "coding-handling")
        self.assertEqual(decision["confidence"], "high")
        self.assertIn("User message:\nrisky refactor", decision["routing_prompt"])

    def test_low_signal_chat_falls_back_to_router(self) -> None:
        decision = route_chat_message("zzzzunknownphrase", source="slack")

        self.assertEqual(decision["action"], "fallback")
        self.assertEqual(decision["selected_skill"], "oh-my-hermes")
        self.assertEqual(decision["candidate_skill"], "oh-my-hermes")
        self.assertEqual(decision["confidence"], "low")
        self.assertIn("Ask which workflow", decision["clarification"])

    def test_below_threshold_chat_clarifies_before_dispatch(self) -> None:
        decision = route_chat_message("architecture", min_confidence="high")

        self.assertEqual(decision["action"], "clarify")
        self.assertEqual(decision["selected_skill"], "oh-my-hermes")
        self.assertEqual(decision["candidate_skill"], "ralplan")
        self.assertEqual(decision["confidence"], "medium")

    def test_explicit_chat_invocation_dispatches_even_when_router_would_clarify(self) -> None:
        decision = route_chat_message("/plan implementation")

        self.assertEqual(decision["action"], "dispatch")
        self.assertEqual(decision["selected_skill"], "plan")
        self.assertTrue(decision["explicit"])
        self.assertEqual(decision["confidence"], "high")

    def test_event_text_extraction_supports_discord_slack_and_generic_shapes(self) -> None:
        self.assertEqual(extract_message_text({"message": {"content": "risky refactor"}}), "risky refactor")
        self.assertEqual(extract_message_text({"message": {"text": "risky refactor"}}), "risky refactor")
        self.assertEqual(extract_message_text({"event": {"text": "implementation plan"}}), "implementation plan")
        self.assertEqual(extract_message_text({"data": {"text": "implementation plan"}}), "implementation plan")
        self.assertEqual(extract_message_text({"prompt": "diagnose installation health"}), "diagnose installation health")

        decision = route_chat_event({"content": "diagnose installation health"}, source="hermes")
        self.assertEqual(decision["selected_skill"], "doctor")

    def test_routing_record_payload_does_not_store_raw_message(self) -> None:
        message = "risky refactor"
        decision = route_chat_message(message, source="discord")

        record = routing_record_payload(decision, message, source_event_id="m1", channel_ref="c1", user_ref="u1")

        self.assertEqual(record["message_length"], len(message))
        self.assertEqual(record["source_event_id"], "m1")
        self.assertNotIn(message, json.dumps(record))
        self.assertRegex(str(record["message_sha256"]), r"^[a-f0-9]{64}$")

    def test_public_route_payload_omits_raw_message_by_default(self) -> None:
        message = "risky refactor"
        decision = route_chat_message(message, source="discord")

        public = public_route_payload(decision)

        self.assertNotIn("routing_prompt", public)
        self.assertIn("routing_prompt_template", public)
        self.assertIn("{message}", str(public["routing_prompt_template"]))
        self.assertNotIn(message, json.dumps(public))

        expanded = public_route_payload(decision, include_message=True)
        self.assertIn(message, str(expanded["routing_prompt"]))


if __name__ == "__main__":
    unittest.main()
