from __future__ import annotations

import unittest

from _local_package import load_local_package


load_local_package()
from omh.skill_pack import builtin_definitions, builtin_skill_templates
from omh.skills import render as render_module
from omh.skills.catalog import (
    builtin_harnesses,
    catalog_intent_delegation_skill_names,
    coding_skills_for_intent,
    explicit_memory_context_skill_names,
    memory_context_policy_for_skill,
    retained_delegation_skill_names,
)


class EfficiencyContractTests(unittest.TestCase):
    def test_memory_schema_guidance_is_scoped_to_handoff_sensitive_skills(self) -> None:
        templates = {template.name: template.content for template in builtin_skill_templates()}
        definitions = {definition.name: definition for definition in builtin_definitions()}

        explicit_schema_skills = {
            name
            for name, content in templates.items()
            if name != "oh-my-hermes"
            and ("memory_review_card/v1" in content or "handoff_context_pack/v1" in content)
        }
        expected_explicit = set(explicit_memory_context_skill_names())

        self.assertEqual(explicit_schema_skills, expected_explicit)
        self.assertIn("ralph", explicit_schema_skills)
        self.assertIn("plan", explicit_schema_skills)
        self.assertIn("code-review", explicit_schema_skills)

        retained_low_handoff_skills = {
            name
            for name, definition in definitions.items()
            if name != "oh-my-hermes"
            and name in templates
            and memory_context_policy_for_skill(definition.name) == "compact"
        }
        self.assertTrue(retained_low_handoff_skills)
        for name in retained_low_handoff_skills:
            self.assertNotIn("memory_review_card/v1", templates[name], name)
            self.assertNotIn("handoff_context_pack/v1", templates[name], name)
            self.assertIn("advisory local context", templates[name], name)

    def test_generated_skill_pack_keeps_memory_guidance_under_budget(self) -> None:
        combined = "\n".join(template.content for template in builtin_skill_templates())
        explicit_budget = len(explicit_memory_context_skill_names()) + 1
        compact_budget = (
            sum(
                1
                for definition in builtin_definitions()
                if definition.name != "oh-my-hermes" and memory_context_policy_for_skill(definition.name) == "compact"
            )
            + 1
        )

        self.assertLessEqual(combined.count("memory_review_card/v1"), explicit_budget)
        self.assertLessEqual(combined.count("handoff_context_pack/v1"), explicit_budget)
        self.assertLessEqual(combined.count("advisory local context"), compact_budget)

    def test_workflow_reference_markdown_reuses_cached_render(self) -> None:
        render_module._workflow_reference_markdown_cached.cache_clear()

        first = render_module.workflow_reference_markdown()
        second = render_module.workflow_reference_markdown()
        cache_info = render_module._workflow_reference_markdown_cached.cache_info()

        self.assertIs(first, second)
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)
        self.assertIn("# Workflow Reference", first)
        self.assertIn("## Representative Harnesses", first)

    def test_workflow_reference_payload_cache_is_mutation_safe(self) -> None:
        render_module._workflow_reference_payload_cached.cache_clear()

        first = render_module.workflow_reference_payload()
        first["skills"][0]["name"] = "mutated"

        second = render_module.workflow_reference_payload()
        cache_info = render_module._workflow_reference_payload_cached.cache_info()

        self.assertIsNot(first, second)
        self.assertNotEqual(second["skills"][0]["name"], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_catalog_derived_views_are_reusable_without_list_poisoning(self) -> None:
        definitions = builtin_definitions()
        harnesses = builtin_harnesses()

        definitions.clear()
        harnesses.clear()

        self.assertTrue(builtin_definitions())
        self.assertTrue(builtin_harnesses())
        self.assertIn("feedback-triage", catalog_intent_delegation_skill_names())
        self.assertIn("code-review", coding_skills_for_intent("review"))
        self.assertIn("research-brief", retained_delegation_skill_names())


if __name__ == "__main__":
    unittest.main()
