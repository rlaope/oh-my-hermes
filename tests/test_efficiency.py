from __future__ import annotations

import json
import unittest

from _local_package import load_local_package


load_local_package()
from omh.skill_pack import builtin_definitions, builtin_skill_templates
from omh.routing import recommend as recommend_module
from omh.skills import render as render_module
from omh.release import (
    AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT,
    AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT,
    AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT,
    FULL_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
    FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
    STANDALONE_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
    STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
)
from omh.capabilities.skills import skill_capabilities
from omh.plugin_bundle.omh.tools.capability_tool import standalone_skill_capability_items
from omh.plugin_bundle.omh.awareness import (
    awareness_context_matches_message,
    awareness_primer_payload,
    awareness_primer_context,
    awareness_primer_markdown,
    awareness_workflow_context_markdown,
    workflow_context_card_for_workflow,
)
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

    def test_omh_awareness_context_is_strong_but_bounded(self) -> None:
        workflow_skill_names = {template.name for template in builtin_skill_templates()} - {"oh-my-hermes"}
        workflow_context_lengths = {
            name: len(awareness_workflow_context_markdown(name))
            for name in workflow_skill_names
        }
        combined = "\n".join(template.content for template in builtin_skill_templates())

        self.assertLessEqual(len(awareness_primer_context()), AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT)
        self.assertLessEqual(len(awareness_primer_markdown()), AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT)
        self.assertLessEqual(max(workflow_context_lengths.values()), AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT)
        self.assertIn("Common cues:", awareness_primer_context())
        self.assertIn("Pattern cards:", awareness_primer_context())
        self.assertIn("image cards/infographics -> img-summary", awareness_primer_context())
        self.assertIn("Workflow context cards", awareness_primer_markdown())
        self.assertIn("Common cues before generic tools", awareness_primer_markdown())
        self.assertEqual(combined.count("## OMH Context Rail"), len(workflow_skill_names))
        self.assertEqual(combined.count("## OMH Awareness Primer"), 1)

    def test_omh_awareness_lanes_cover_installable_skills(self) -> None:
        payload = awareness_primer_payload()
        cards = {str(card["id"]): card for card in payload["workflow_context_cards"]}
        lane_skills = {
            str(skill)
            for lane in payload["lanes"]
            if isinstance(lane, dict)
            for skill in lane.get("skills", [])
        }
        installable_skills = {definition.name for definition in builtin_definitions()}

        self.assertFalse(installable_skills - lane_skills)
        self.assertIn("img-summary", cards["materials_and_visuals"]["representative_workflows"])
        self.assertIn("ultraprocess", cards["coding_handoff"]["representative_workflows"])
        self.assertIn("not_evidence_until_observed", cards["intent_to_plan"])
        for card in cards.values():
            self.assertTrue(card["label"])
            self.assertTrue(card["user_examples"])
            self.assertIn("evidence", card["first_response_shape"])

    def test_workflow_context_cards_cover_installable_workflow_families(self) -> None:
        workflow_skills = {definition.name for definition in builtin_definitions()} - {"oh-my-hermes", "cancel"}
        unmapped = sorted(name for name in workflow_skills if not workflow_context_card_for_workflow(name))

        self.assertEqual(unmapped, [])
        self.assertEqual(workflow_context_card_for_workflow("img-summary")["id"], "materials_and_visuals")
        self.assertEqual(workflow_context_card_for_workflow("feedback-triage")["id"], "research_and_ops")
        self.assertEqual(workflow_context_card_for_workflow("automation-blueprint")["id"], "automation_and_status")
        self.assertEqual(workflow_context_card_for_workflow("code-review")["id"], "coding_handoff")

    def test_mid_session_awareness_detector_is_bounded(self) -> None:
        self.assertTrue(awareness_context_matches_message("회의록을 세로 요약 이미지 카드로 만들어줘"))
        self.assertTrue(awareness_context_matches_message("PR 요약 포스터 만들어줘"))
        self.assertTrue(awareness_context_matches_message("make a poster explaining cron automation"))
        self.assertTrue(awareness_context_matches_message("作成して、PRの要約画像"))
        self.assertTrue(awareness_context_matches_message("生成一张发布说明海报"))
        self.assertTrue(awareness_context_matches_message("make a PR summary card for reviewers"))
        self.assertTrue(awareness_context_matches_message("what is the coding handoff status?"))
        self.assertFalse(awareness_context_matches_message("prepare a sandwich"))
        self.assertFalse(awareness_context_matches_message(""))

    def test_capability_context_is_strong_but_bounded(self) -> None:
        full_items = skill_capabilities()
        standalone_items = standalone_skill_capability_items()
        full_section_chars = len(json.dumps(full_items, sort_keys=True, ensure_ascii=False))
        standalone_section_chars = len(json.dumps(standalone_items, sort_keys=True, ensure_ascii=False))
        max_full_item_chars = max(len(json.dumps(item, sort_keys=True, ensure_ascii=False)) for item in full_items)
        max_standalone_item_chars = max(
            len(json.dumps(item, sort_keys=True, ensure_ascii=False)) for item in standalone_items
        )

        self.assertLessEqual(full_section_chars, FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT)
        self.assertLessEqual(standalone_section_chars, STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT)
        self.assertLessEqual(max_full_item_chars, FULL_CAPABILITY_SKILL_ITEM_CHAR_LIMIT)
        self.assertLessEqual(max_standalone_item_chars, STANDALONE_CAPABILITY_SKILL_ITEM_CHAR_LIMIT)
        self.assertIn(
            "ambitious goal -> loopability check",
            " ".join(next(item for item in full_items if item["id"] == "loop")["cross_lane_examples"]),
        )
        self.assertIn(
            "meeting notes -> meeting-brief",
            " ".join(next(item for item in full_items if item["id"] == "img-summary")["cross_lane_examples"]),
        )

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

    def test_recommendation_metadata_cache_is_reused_without_payload_poisoning(self) -> None:
        recommend_module._prepared_routable_definitions.cache_clear()

        first = recommend_module.recommend_skills("risky refactor", limit=2)
        first[0]["skill"] = "mutated"
        second = recommend_module.recommend_skills("risky refactor", limit=2)
        cache_info = recommend_module._prepared_routable_definitions.cache_info()

        self.assertNotEqual(second[0]["skill"], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)


if __name__ == "__main__":
    unittest.main()
