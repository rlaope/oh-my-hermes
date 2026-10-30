"""The rendered route hint drops text that repeats other text in the same block.

Four exact duplicates go: a hint's `adjacent_workflows=` line equal to the
block's top-level one, a `fallback_action_label=` that only respells the
action's underscores, the same for `next_action_label=`, and a meaning line
(`first_response_shape=`, `not_evidence_yet=`, `plan_todo=`) that an earlier
hint in the same block already rendered word for word -- two hints in one lane
share a context card. Each test pins both ways (the duplicate removed, a
differing value kept), and a meaning line seen once renders as before.
"""

from __future__ import annotations

import unittest

from omh.plugin_bundle.omh.awareness import (
    PLAN_TODO_DECLARATION_RULE,
    awareness_route_hint,
    awareness_route_hint_context_from_payload,
)


def _payload(**hint_fields: object) -> dict[str, object]:
    hint: dict[str, object] = {
        "id": "test_hint",
        "workflow": "code-review",
        "lane": "review",
        "next_action": "review_the_diff",
        "next_action_label": "reading the diff for bugs",
        "reason": "The user asked for a review.",
        "adjacent_workflows": ["ulw-plan", "agent-ops-review"],
        "fallback_action": "ask_for_the_diff",
        "fallback_action_label": "asking which diff to read",
        "not_evidence_yet": ["review", "CI"],
        "workflow_context_card": {"first_response_shape": "Name the diff, then the findings."},
    }
    hint.update(hint_fields)
    return {
        "status": "hinted",
        "intent_class": "review_intent",
        "selected_workflow": hint["workflow"],
        "adjacent_workflows": ["ulw-plan", "agent-ops-review"],
        "mentioned_workflows": [],
        "not_executed": [],
        "hints": [hint],
        "claim_boundary": "OMH route hints are local deterministic prompt context only.",
    }


def _lines(payload: dict[str, object]) -> list[str]:
    return awareness_route_hint_context_from_payload(payload).splitlines()


class AdjacentWorkflowsDedupTest(unittest.TestCase):
    def test_hint_line_equal_to_top_level_is_dropped(self) -> None:
        lines = _lines(_payload())
        self.assertIn("adjacent_workflows=ulw-plan, agent-ops-review.", lines)
        self.assertNotIn("  adjacent_workflows=ulw-plan, agent-ops-review.", lines)

    def test_hint_line_that_differs_is_kept(self) -> None:
        payload = _payload(adjacent_workflows=["ulw-loop", "code-review"])
        lines = _lines(payload)
        self.assertIn("adjacent_workflows=ulw-plan, agent-ops-review.", lines)
        self.assertIn("  adjacent_workflows=ulw-loop, code-review.", lines)

    def test_hint_line_is_kept_when_there_is_no_top_level_line(self) -> None:
        payload = _payload()
        payload["adjacent_workflows"] = []
        lines = _lines(payload)
        self.assertNotIn("adjacent_workflows=ulw-plan, agent-ops-review.", lines)
        self.assertIn("  adjacent_workflows=ulw-plan, agent-ops-review.", lines)


class FallbackActionLabelDedupTest(unittest.TestCase):
    def test_label_that_respells_the_action_is_dropped(self) -> None:
        lines = _lines(_payload(fallback_action_label="ask for the diff"))
        self.assertIn("  fallback_action=ask_for_the_diff.", lines)
        self.assertFalse(any("fallback_action_label=" in line for line in lines))

    def test_prose_label_is_kept(self) -> None:
        lines = _lines(_payload())
        self.assertIn(
            "  fallback_action_label=asking which diff to read; fallback_action=ask_for_the_diff.", lines
        )


class NextActionLabelDedupTest(unittest.TestCase):
    def test_label_that_respells_the_action_is_dropped(self) -> None:
        lines = _lines(_payload(next_action_label="review the diff"))
        self.assertIn(
            "- selected=code-review; lane=review; next_action=review_the_diff; reason=The user asked for a review.",
            lines,
        )

    def test_prose_label_is_kept(self) -> None:
        lines = _lines(_payload())
        self.assertIn(
            "- selected=code-review; lane=review; next_action_label=reading the diff for bugs; "
            "next_action=review_the_diff; reason=The user asked for a review.",
            lines,
        )


class MeaningLinesUnchangedTest(unittest.TestCase):
    def test_first_response_shape_and_not_evidence_yet_render_as_before(self) -> None:
        lines = _lines(_payload(fallback_action_label="ask for the diff", next_action_label="review the diff"))
        self.assertIn("  first_response_shape=Name the diff, then the findings.", lines)
        self.assertIn("  not_evidence_yet=review, CI.", lines)
        self.assertEqual(lines[-1], "Boundary: OMH route hints are local deterministic prompt context only.")

    def test_plan_todo_renders_as_before(self) -> None:
        lines = _lines(_payload(workflow="ulw-work"))
        self.assertIn(f"  plan_todo={PLAN_TODO_DECLARATION_RULE}", lines)

    def test_live_routed_request_keeps_its_meaning_lines(self) -> None:
        payload = awareness_route_hint("review this PR for bugs before merge")
        text = awareness_route_hint_context_from_payload(payload)
        self.assertIn("  first_response_shape=", text)
        self.assertIn("  not_evidence_yet=", text)
        self.assertIn("  plan_todo=", text)
        self.assertIn("\nadjacent_workflows=", text)
        self.assertNotIn("\n  adjacent_workflows=", text)



class SameLaneMeaningLineDedupTest(unittest.TestCase):
    def _two_hints(self, **second_fields: object) -> dict[str, object]:
        payload = _payload()
        first = dict(payload["hints"][0])
        second = {**first, "id": "second_hint", "workflow": "agent-ops-review", "next_action": "read_the_gates"}
        second.update(second_fields)
        payload["hints"] = [first, second]
        return payload

    def test_a_second_hint_with_the_same_card_renders_its_meaning_lines_once(self) -> None:
        lines = _lines(self._two_hints())
        self.assertEqual(lines.count("  first_response_shape=Name the diff, then the findings."), 1)
        self.assertEqual(lines.count("  not_evidence_yet=review, CI."), 1)
        # The hint itself still renders, so its workflow and action stay visible.
        self.assertTrue(any(line.startswith("- selected=agent-ops-review;") for line in lines))

    def test_a_second_hint_with_a_different_card_keeps_its_own_lines(self) -> None:
        payload = self._two_hints(
            workflow_context_card={"first_response_shape": "Name the gate, then its state."},
            not_evidence_yet=["merge"],
        )
        lines = _lines(payload)
        self.assertIn("  first_response_shape=Name the diff, then the findings.", lines)
        self.assertIn("  first_response_shape=Name the gate, then its state.", lines)
        self.assertIn("  not_evidence_yet=review, CI.", lines)
        self.assertIn("  not_evidence_yet=merge.", lines)

    def test_the_plan_todo_rule_renders_once_for_two_checklist_hints(self) -> None:
        payload = _payload(workflow="ulw-work")
        first = dict(payload["hints"][0])
        payload["hints"] = [first, {**first, "id": "second_hint", "workflow": "ulw-plan"}]
        lines = _lines(payload)
        self.assertEqual(lines.count(f"  plan_todo={PLAN_TODO_DECLARATION_RULE}"), 1)

    def test_a_live_two_hint_route_drops_only_the_repeated_lines(self) -> None:
        payload = awareness_route_hint(
            "Use OMH to fix the failing test in billing.py, then run the tests with python -m pytest -q."
        )
        hints = [hint for hint in payload.get("hints", []) if isinstance(hint, dict)]
        self.assertGreaterEqual(len(hints), 2, payload)
        text = awareness_route_hint_context_from_payload(payload)
        for line in text.splitlines():
            if line.startswith(("  first_response_shape=", "  not_evidence_yet=", "  plan_todo=")):
                self.assertEqual(text.splitlines().count(line), 1, line)
        self.assertEqual(text.count("- selected="), len(hints))

if __name__ == "__main__":
    unittest.main()
