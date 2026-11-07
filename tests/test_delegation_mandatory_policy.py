from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.coding_delegation import (  # noqa: E402
    DELEGATION_POLICY_SCHEMA_VERSION,
    build_coding_delegation_payload,
)
from omh.coding.executors import executor_selection_for_target  # noqa: E402
from omh.routing.coding_route_actions import resolve_coding_route_decision  # noqa: E402
from omh.skills.catalog import retained_delegation_skill_names  # noqa: E402
from omh.wrapper.contract import build_chat_response_from_delegation  # noqa: E402

_RETAINED = set(retained_delegation_skill_names())

# Coding-shaped requests that historically could fall into clarify/fallback
# (low score, no file reference, retained top workflow, score-0 fallbacks) —
# the exact paths where "Hermes keeps it" must never read as "Hermes codes it".
_CODING_SHAPED_MESSAGES = (
    "fix the bug",
    "implement the new login feature in src/auth/login.py with tests",
    "refactor this code",
    "refactor this function",
    "리팩토링 해줘",
    "write code for the parser and fix the failing tests",
    "코딩 해줘",
    "깡으로 코딩해줘",
    "패치 좀",
    "write it",
    "너가 직접 구현해",
)

_NON_CODING_MESSAGES = (
    "what skills do you have",
    "research the best database for this workload",
)


class InlineCodingProhibitionTests(unittest.TestCase):
    def test_coding_shaped_messages_never_present_hermes_as_coding_owner(self) -> None:
        # The invariant, asserted from the spec side rather than from the
        # implementation's own gate: whenever a coding-shaped message resolves
        # to retained_hermes (or an unresolved-owner delegate), the payload
        # MUST carry the prohibition — including score-0 fallbacks like a bare
        # "코딩 해줘", the exact shape the user banned.
        for message in _CODING_SHAPED_MESSAGES:
            with self.subTest(message=message):
                payload = build_coding_delegation_payload(message)
                delegation = payload["delegation"]
                action = str(delegation["action"])
                if payload["work_owner_mode"] == "retained_hermes" or (
                    action == "delegate" and payload["executor_selection"]["choice_required"]
                ):
                    policy = payload.get("delegation_policy")
                    self.assertIsInstance(policy, dict, f"{message!r} lacks the delegation policy block")
                    self.assertTrue(policy["inline_coding_prohibited"])
                    self.assertEqual(policy["schema_version"], DELEGATION_POLICY_SCHEMA_VERSION)
                    self.assertIn("never implements main coding work inline", policy["policy"])
                if action == "delegate" and not payload["executor_selection"]["choice_required"]:
                    self.assertNotEqual(payload["work_owner_mode"], "retained_hermes")

    def test_score_zero_fallback_carries_policy_and_fallback_card_state(self) -> None:
        payload = build_coding_delegation_payload("깡으로 코딩해줘")
        delegation = payload["delegation"]
        self.assertEqual(str(delegation["action"]), "fallback")
        self.assertEqual(payload["work_owner_mode"], "retained_hermes")
        self.assertIn("delegation_policy", payload)
        response = build_chat_response_from_delegation(payload)
        self.assertIn("delegation_policy", response["state"])
        self.assertTrue(response["state"]["delegation_policy"]["inline_coding_prohibited"])

    def test_non_coding_messages_do_not_carry_the_policy_block(self) -> None:
        for message in _NON_CODING_MESSAGES:
            with self.subTest(message=message):
                payload = build_coding_delegation_payload(message)
                if str(payload["delegation"]["intent"]) in {"coding", "review"}:
                    continue
                self.assertNotIn("delegation_policy", payload)

    def test_retained_hermes_selection_is_never_dispatchable_and_never_delegate(self) -> None:
        selection = executor_selection_for_target("codex", action="clarify")
        self.assertEqual(selection.work_owner_mode, "retained_hermes")
        self.assertFalse(selection.dispatchable)
        for target in ("codex", "claude-code", "hermes", "generic", "choose"):
            with self.subTest(target=target):
                delegate_selection = executor_selection_for_target(target, action="delegate")
                self.assertNotEqual(delegate_selection.work_owner_mode, "retained_hermes")

    def test_unresolved_owner_with_no_setup_requires_user_choice(self) -> None:
        decision = resolve_coding_route_decision("fix the login bug please")
        self.assertTrue(decision.choice_required)
        self.assertEqual(decision.next_action, "choose_executor")
        self.assertEqual(decision.selected_owner, "")

    def test_hermes_is_never_auto_selected_without_explicit_naming(self) -> None:
        for query in ("fix the login bug", "refactor the parser", "write tests for src/x.py"):
            with self.subTest(query=query):
                decision = resolve_coding_route_decision(query)
                self.assertNotEqual(decision.selected_owner, "hermes")


class PolicyCardStateTests(unittest.TestCase):
    def test_retained_workflow_clarify_card_omits_policy_while_payload_carries_it(self) -> None:
        # "fix the bug" → coding intent, clarify, retained build-failure-triage:
        # the payload must carry the prohibition for wrappers, while the
        # retained chat card keeps its existing copy (its body never renders
        # the policy text — retained cards own their own wording contract).
        payload = build_coding_delegation_payload("fix the bug")
        delegation = payload["delegation"]
        self.assertEqual(str(delegation["action"]), "clarify")
        self.assertIn(str(delegation["recommended_workflow"]), _RETAINED)
        self.assertIn("delegation_policy", payload)
        response = build_chat_response_from_delegation(payload)
        self.assertNotIn("delegation_policy", response["state"])
        self.assertNotIn("never implements main coding work inline", json.dumps(response))

    def test_non_retained_clarify_card_carries_the_policy_block(self) -> None:
        payload = build_coding_delegation_payload("코드 고쳐줘")
        delegation = payload["delegation"]
        self.assertEqual(str(delegation["action"]), "clarify")
        self.assertNotIn(str(delegation["recommended_workflow"]), _RETAINED)
        self.assertIn("delegation_policy", payload)
        response = build_chat_response_from_delegation(payload)
        self.assertIn("delegation_policy", response["state"])
        self.assertTrue(response["state"]["delegation_policy"]["inline_coding_prohibited"])

    def test_choice_required_delegate_carries_policy_context_and_delegation_first_copy(self) -> None:
        payload = build_coding_delegation_payload(
            "implement pagination in src/api/list.py and run the tests",
            executor_target="choose",
        )
        delegation = payload["delegation"]
        self.assertEqual(str(delegation["action"]), "delegate")
        self.assertTrue(payload["executor_selection"]["choice_required"])
        self.assertIn("delegation_policy", payload)
        # The wrapper lane attaches this from cached readiness state; the card
        # must pass it through untouched.
        payload["executor_choice_context"] = {
            "candidates": [{"profile": "codex", "readiness_status": "ready"}],
            "claim_boundary": "test",
        }
        response = build_chat_response_from_delegation(payload)
        state = response["state"]
        self.assertIn("delegation_policy", state)
        self.assertTrue(state["delegation_policy"]["inline_coding_prohibited"])
        self.assertEqual(state["executor_choice_context"]["candidates"][0]["profile"], "codex")
        # Coding-shaped choice cards never lead with keeping the work in
        # Hermes; delegation is the premise, the choice is only who owns it.
        self.assertNotIn("Keep this in Hermes", str(response["body"]))
        self.assertIn("stays delegated", str(response["body"]))


if __name__ == "__main__":
    unittest.main()
