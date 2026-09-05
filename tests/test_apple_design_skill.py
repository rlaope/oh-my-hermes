from __future__ import annotations

from pathlib import Path
import unittest

from omh.capabilities.families import capability_family_projection
from omh.skills.catalog import builtin_definitions, installable_skill_names
from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates
from omh.wrapper.contract import build_chat_interaction_payload


class AppleDesignSkillTests(unittest.TestCase):
    def test_apple_design_skill_registers_routes_and_ships_its_generated_files(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        templates = {template.name: template.content for template in builtin_skill_templates()}
        references = {
            (template.skill_name, template.relative_path): template.content
            for template in builtin_skill_reference_templates()
        }

        definition = definitions["apple-design"]
        self.assertEqual(definition.category, "materials")
        self.assertEqual(definition.phase, "apple-design")
        self.assertIn("apple-design", installable_skill_names())
        self.assertIn("apple_design_brief/v1", definition.expected_outputs)
        self.assertIn("apple_visual_direction/v1", definition.expected_outputs)

        payload = build_chat_interaction_payload(
            "Review our iOS checkout against Apple HIG and prepare the frontend remediation",
            source="discord",
        )
        state = payload["chat_response"]["state"]
        self.assertEqual(state["selected_workflow"], "apple-design")
        self.assertEqual(state["next_action"], "prepare_design_orchestration")
        self.assertEqual(state["workflow_explanation"]["workflow_context_id"], "materials_and_visuals")

        product_visual_payload = build_chat_interaction_payload(
            "Create an Apple-style 3D hero with a product render and studio lighting for our landing page.",
            source="discord",
        )
        self.assertEqual(product_visual_payload["chat_response"]["state"]["selected_workflow"], "apple-design")

        generic_gsap_payload = build_chat_interaction_payload(
            "Animate our logo reveal with GSAP and add a reduced-motion fallback.",
            source="discord",
        )
        self.assertNotEqual(generic_gsap_payload["chat_response"]["state"].get("selected_workflow"), "apple-design")

        family = next(
            item
            for item in capability_family_projection()["families"]
            if item["id"] == "create_materials_and_visuals"
        )
        self.assertIn("apple-design", family["primary_workflows"])

        self.assertIn("apple-design", templates)
        for relative_path in (
            "references/platform-foundations.md",
            "references/materials-and-accessibility.md",
            "references/product-visual-production.md",
            "references/web-production-libraries.md",
            "references/review-playbook.md",
        ):
            with self.subTest(reference=relative_path):
                expected = references[("apple-design", relative_path)]
                actual = Path("skills/omh-apple-design", relative_path).read_text(encoding="utf-8")
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
