"""After plan acceptance the planning surfaces name `dag-ulw` as a follow-on.

The skill bodies' engine-fit rule already listed it, while the structured
surfaces around them (route hints, the intent-to-plan card, the router's lane
map, `ralplan`'s recovery note, the `/plan` reference) still steered only to
deep-interview and ultrawork. Each test pins one of those surfaces. `dag-ulw`
ships only in the Hermes projection, so the portable bodies must not name it.
"""
from __future__ import annotations

import unittest

from omh.catalogs.playbooks import inspect_playbook
from omh.install.agent_skills_projection import agent_skill_files
from omh.plugin_bundle.omh.awareness import (
    awareness_lane_examples,
    awareness_route_hint,
    workflow_context_card_for_workflow,
)
from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates


def _hermes_body(name: str) -> str:
    return next(template.content for template in builtin_skill_templates() if template.name == name)


def _portable_body(path: str) -> str:
    content = agent_skill_files()[path]
    return content.decode() if isinstance(content, bytes) else content


class PlanOffersDagUlwTests(unittest.TestCase):
    def test_safe_feature_and_picker_hints_name_dag_ulw_as_adjacent(self) -> None:
        for message in ("safely add a feature to the export page", "open the omh picker"):
            with self.subTest(message=message):
                self.assertIn("dag-ulw", awareness_route_hint(message)["adjacent_workflows"])

    def test_intent_to_plan_card_names_dag_ulw(self) -> None:
        card = workflow_context_card_for_workflow("plan")
        self.assertEqual(card["id"], "intent_to_plan")
        self.assertIn("dag-ulw", card["representative_workflows"])
        self.assertIn("dag-ulw", card["omh_pattern"])

    def test_intent_to_plan_example_continues_past_the_accepted_plan(self) -> None:
        self.assertIn(
            "fuzzy feature request -> deep-interview -> ralplan -> accepted plan -> dag-ulw or ultrawork on go-ahead",
            awareness_lane_examples("intent_to_plan"),
        )

    def test_router_lane_map_and_engine_gate_name_dag_ulw(self) -> None:
        router = _hermes_body("oh-my-hermes")
        self.assertIn("- Intent -> plan: `deep-interview`, `ralplan`, `plan`, `dag-ulw`, `loop`.", router)
        self.assertIn("starting a follow-on workflow engine (`dag-ulw`, `ultrawork`", router)

    def test_ralplan_hands_on_to_dag_ulw_in_hermes_only(self) -> None:
        hermes = _hermes_body("ralplan")
        self.assertIn("(`dag-ulw` when the accepted lanes form a graph with a verification lane, `ultrawork`", hermes)
        self.assertIn("so `dag-ulw` nodes or `ultrawork` board rows come from the plan", hermes)
        self.assertNotIn("dag-ulw", _portable_body("ulw-plan/SKILL.md"))

    def test_refactor_plan_approval_gate_names_dag_ulw_in_hermes_only(self) -> None:
        self.assertIn("name `dag-ulw` as the way to run them", _hermes_body("refactor-plan"))
        self.assertNotIn("dag-ulw", _portable_body("omh-refactor-plan/SKILL.md"))

    def test_hermes_plan_reference_points_the_carry_out_offer_at_dag_ulw(self) -> None:
        reference = next(
            template.content
            for template in builtin_skill_reference_templates()
            if template.skill_name == "plan" and template.relative_path == "references/hermes-plan-mode.md"
        )
        self.assertIn("name `dag-ulw` beside carrying it out directly", reference)
        self.assertIn("start neither until the user picks one", reference)

    def test_deep_interview_playbook_plan_stage_names_dag_ulw(self) -> None:
        stages = inspect_playbook("deep-interview-to-plan")["playbook"]["stages"]
        plan_stage = next(stage for stage in stages if stage["id"] == "plan")
        self.assertIn("name dag-ulw among them, started only on the user's go-ahead", plan_stage["purpose"])


if __name__ == "__main__":
    unittest.main()
