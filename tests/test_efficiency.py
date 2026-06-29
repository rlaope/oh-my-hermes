from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from _local_package import load_local_package


load_local_package()
from omh.skill_pack import builtin_definitions, builtin_skill_templates
from omh.routing import chat as chat_module
from omh.routing import catalog_questions as catalog_questions_module
from omh.routing import localization as localization_module
from omh.routing import recommend as recommend_module
from omh.routing import policy as policy_module
from omh.routing import route_plan as route_plan_module
from omh.catalogs import playbooks as playbooks_module
from omh.skills import render as render_module
from omh.workflows import hermes_planning as hermes_planning_module
from omh.workflows import learning_candidate as learning_candidate_module
from omh.wrapper import contract as contract_module
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
from omh.plugin_bundle.omh import awareness as awareness_module
from omh.plugin_bundle.omh.awareness import (
    awareness_context_matches_message,
    awareness_generic_tool_checkpoint_payload,
    awareness_primer_payload,
    awareness_primer_context,
    awareness_primer_markdown,
    awareness_route_hint,
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
from omh.quality import grounded_score as grounded_score_module
from omh.quality import route_hint_alignment as route_hint_alignment_module
from omh.quality.grounded_score import GroundedScenario
from omh.quality.route_hint_alignment import RouteHintAlignmentCase


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

        primer_context = awareness_primer_context()

        self.assertLessEqual(len(primer_context), AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT)
        self.assertLessEqual(len(primer_context), 900)
        self.assertLessEqual(len(awareness_primer_markdown()), AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT)
        self.assertLessEqual(max(workflow_context_lengths.values()), AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT)
        self.assertIn("Hermes-native workflow", primer_context)
        self.assertIn("consider OMH before generic tools", primer_context)
        self.assertIn("Use message-specific route hints", primer_context)
        self.assertIn("not observed execution", primer_context)
        self.assertIn("omh_context", primer_context)
        self.assertIn("omh_capabilities", primer_context)
        self.assertIn("omh_status/omh_hud", primer_context)
        self.assertNotIn("Common cues:", primer_context)
        self.assertNotIn("Pattern cards:", primer_context)
        self.assertNotIn("Tools:", primer_context)
        self.assertIn("Workflow context cards", awareness_primer_markdown())
        self.assertIn("Common cues before generic tools", awareness_primer_markdown())
        self.assertIn("check OMH prep/status/learning", awareness_primer_markdown())
        self.assertIn("Generic tool map", awareness_primer_markdown())
        self.assertEqual(combined.count("## OMH Context Rail"), len(workflow_skill_names))
        self.assertEqual(combined.count("## OMH Awareness Primer"), 1)
        for name in workflow_skill_names:
            self.assertIn(
                "Generic-tool checkpoint: image->img-summary",
                awareness_workflow_context_markdown(name),
            )

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
        self.assertIn("prep/status/learning", payload["generic_tool_checkpoint"])
        tool_routes = {route["tool_family"]: route for route in payload["generic_tool_checkpoint_routes"]}
        self.assertEqual(tool_routes["image_tools"]["primary_workflow"], "img-summary")
        self.assertEqual(tool_routes["file_tools"]["primary_workflow"], "materials-package")
        self.assertEqual(tool_routes["search_tools"]["primary_workflow"], "web-research")
        self.assertEqual(tool_routes["coding_tools"]["primary_workflow"], "ultraprocess")
        self.assertIn("visual QA", tool_routes["image_tools"]["not_evidence_yet"])
        self.assertEqual(
            awareness_generic_tool_checkpoint_payload()["schema_version"],
            "omh_generic_tool_checkpoint/v1",
        )
        self.assertIn("prep/status/learning", awareness_generic_tool_checkpoint_payload()["body"])
        checkpoint_routes = {
            route["tool_family"]: route for route in awareness_generic_tool_checkpoint_payload()["routes"]
        }
        self.assertEqual(checkpoint_routes["coding_tools"]["fallback_action"], "choose_coding_agent_or_runtime")
        self.assertIn("executor dispatch", checkpoint_routes["coding_tools"]["not_evidence_yet"])
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
        self.assertTrue(awareness_context_matches_message("크론 기능 설명 사진 하나 만들어줘"))
        self.assertTrue(awareness_context_matches_message("PR 요약을 이미지가 아니라 사진처럼 만들어줘"))
        self.assertTrue(awareness_context_matches_message("현재 hermes가 기억하는 맥락을 점검하고 피드백 받아줘"))
        self.assertTrue(awareness_context_matches_message("作成して、PRの要約画像"))
        self.assertTrue(awareness_context_matches_message("生成一张发布说明海报"))
        self.assertTrue(awareness_context_matches_message("make a PR summary card for reviewers"))
        self.assertTrue(awareness_context_matches_message("what is the coding handoff status?"))
        self.assertFalse(awareness_context_matches_message("prepare a sandwich"))
        self.assertFalse(awareness_context_matches_message(""))

        doctor_hint = awareness_route_hint("update 했는데 잘 된거야?")
        self.assertEqual(doctor_hint["primary_workflow"], "doctor")
        self.assertEqual(doctor_hint["primary_next_action"], "check_install_or_setup_health")

        source_finder_messages = (
            "논문 pdf 링크 찾아줘",
            "source candidates for this market research",
            "공개 데이터셋 찾아줘",
            "github oss repo 찾아서 비교해줘",
        )
        for message in source_finder_messages:
            with self.subTest(message=message):
                route_hint = awareness_route_hint(message)

                self.assertEqual(route_hint["primary_workflow"], "source-finder")
                self.assertEqual(route_hint["primary_next_action"], "prepare_source_finder_plan")

        multilingual_hint_cases = (
            ("haz una imagen que explique la función cron", "img-summary", "prepare_visual_prompt_card"),
            ("erstelle ein Bild, das die Cron-Funktion erklärt", "img-summary", "prepare_visual_prompt_card"),
            ("生成一张解释 cron 功能的图片", "img-summary", "prepare_visual_prompt_card"),
            ("trouve le dépôt GitHub et le PDF public", "source-finder", "prepare_source_finder_plan"),
            ("このテーマの論文PDFとデータセットを探して", "source-finder", "prepare_source_finder_plan"),
            ("帮我找这个主题的论文PDF和数据集", "source-finder", "prepare_source_finder_plan"),
            ("convierte este PDF en una presentación", "materials-package", "prepare_material_package"),
            ("transforme ce PDF en présentation", "materials-package", "prepare_material_package"),
            ("mach daraus eine PDF und Excel Datei", "materials-package", "prepare_material_package"),
        )
        for message, workflow, next_action in multilingual_hint_cases:
            with self.subTest(message=message):
                route_hint = awareness_route_hint(message)

                self.assertEqual(route_hint["primary_workflow"], workflow)
                self.assertEqual(route_hint["primary_next_action"], next_action)

    def test_awareness_route_hint_cache_is_reused_without_payload_poisoning(self) -> None:
        awareness_module._awareness_route_hint_cached.cache_clear()

        first = awareness_route_hint("show token cost latency run history for this automation loop")
        first["status"] = "mutated"
        first["hints"][0]["workflow"] = "mutated"
        first["hints"][0]["workflow_context_card"]["representative_workflows"][0] = "mutated"
        first["privacy"]["stored_fields"][0] = "mutated"

        second = awareness_route_hint("show token cost latency run history for this automation loop")
        cache_info = awareness_module._awareness_route_hint_cached.cache_info()

        self.assertEqual(second["status"], "hinted")
        self.assertEqual(second["primary_workflow"], "ops-observability-card")
        self.assertEqual(second["hints"][0]["workflow"], "ops-observability-card")
        self.assertNotEqual(
            second["hints"][0]["workflow_context_card"]["representative_workflows"][0],
            "mutated",
        )
        self.assertNotEqual(second["privacy"]["stored_fields"][0], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_quality_demos_reuse_interaction_route(self) -> None:
        alignment_case = RouteHintAlignmentCase(
            "synthetic",
            "synthetic-route",
            "Synthetic route reuse",
            "synthetic message that should not hit the real router",
            "synthetic-workflow",
        )
        fake_interaction = {
            "route": {
                "selected_skill": "synthetic-workflow",
                "action": "dispatch",
                "confidence": "high",
                "score": 11,
                "explicit": True,
            },
            "next_action": "synthetic_next_action",
            "chat_response": {
                "kind": "synthetic_card",
                "claim_boundary": "Synthetic boundary.",
            },
        }
        fake_route_hint = {
            "status": "hinted",
            "primary_workflow": "synthetic-workflow",
            "primary_next_action": "synthetic_next_action",
            "hints": [{"workflow_context_card": {"id": "intent_to_plan"}}],
            "claim_boundary": "Synthetic hints are not workflow execution evidence.",
        }

        with (
            patch.object(
                route_hint_alignment_module,
                "build_chat_interaction_payload",
                return_value=fake_interaction,
            ),
            patch.object(
                route_hint_alignment_module,
                "awareness_route_hint",
                return_value=fake_route_hint,
            ),
        ):
            row = route_hint_alignment_module._evaluate_alignment_case(alignment_case, source="discord")

        self.assertTrue(row["aligned"])
        self.assertEqual(row["observed"]["route_workflow"], "synthetic-workflow")
        self.assertEqual(row["observed"]["hint_workflow"], "synthetic-workflow")

        grounded_scenario = GroundedScenario(
            "synthetic-grounded",
            "Synthetic grounded route reuse",
            "synthetic grounded message that should not hit the real router",
            "synthetic-workflow",
            "synthetic_card",
            "synthetic_next_action",
            "fallback",
            False,
            invocation_mode="direct_skill",
        )
        fake_delegation = {
            "delegation": {
                "action": "fallback",
                "recommended_workflow": "synthetic-workflow",
            }
        }
        with (
            patch.object(
                grounded_score_module,
                "build_chat_interaction_payload",
                return_value=fake_interaction,
            ),
            patch.object(
                grounded_score_module,
                "build_coding_delegation_payload",
                return_value=fake_delegation,
            ),
        ):
            scenario_row = grounded_score_module._evaluate_grounded_scenario(grounded_scenario, source="discord")

        self.assertEqual(scenario_row["score"], 10)
        self.assertEqual(scenario_row["observed"]["skill"], "synthetic-workflow")

    def test_route_hint_alignment_reuses_precomputed_quality_routes(self) -> None:
        alignment_case = RouteHintAlignmentCase(
            "grounded_score",
            "synthetic-grounded",
            "Synthetic precomputed route reuse",
            "synthetic message with precomputed route",
            "synthetic-workflow",
        )
        grounded_payload = {
            "scenarios": [
                {
                    "id": "synthetic-grounded",
                    "observed": {
                        "skill": "synthetic-workflow",
                        "route_action": "dispatch",
                        "next_action": "synthetic_next_action",
                    },
                }
            ]
        }
        fake_route_hint = {
            "status": "hinted",
            "primary_workflow": "synthetic-workflow",
            "primary_next_action": "synthetic_next_action",
            "hints": [{"workflow_context_card": {"id": "intent_to_plan"}}],
            "claim_boundary": "Synthetic hints are not workflow execution evidence.",
        }

        with (
            patch.object(route_hint_alignment_module, "route_hint_alignment_cases", return_value=(alignment_case,)),
            patch.object(
                route_hint_alignment_module,
                "build_chat_interaction_payload",
                side_effect=AssertionError("precomputed routes should avoid rebuilding interaction payloads"),
            ),
            patch.object(route_hint_alignment_module, "awareness_route_hint", return_value=fake_route_hint),
        ):
            payload = route_hint_alignment_module.build_route_hint_alignment_demo(
                source="discord",
                grounded_score=grounded_payload,
            )

        self.assertTrue(payload["summary"]["all_aligned"])
        self.assertEqual(payload["summary"]["aligned_count"], 1)
        self.assertEqual(payload["cases"][0]["observed"]["route_workflow"], "synthetic-workflow")
        self.assertEqual(payload["cases"][0]["observed"]["route_confidence"], "precomputed")

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
        recommend_module._recommend_skills_cached.cache_clear()

        first = recommend_module.recommend_skills("risky refactor", limit=2)
        first[0]["skill"] = "mutated"
        recommend_module._recommend_skills_cached.cache_clear()
        second = recommend_module.recommend_skills("risky refactor", limit=2)
        cache_info = recommend_module._prepared_routable_definitions.cache_info()

        self.assertNotEqual(second[0]["skill"], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_recommendation_result_cache_is_reused_without_payload_poisoning(self) -> None:
        recommend_module._recommend_skills_cached.cache_clear()

        first = recommend_module.recommend_skills("risky refactor", limit=2)
        first[0]["skill"] = "mutated"
        first[0]["matched"].append("mutated")
        second = recommend_module.recommend_skills("risky refactor", limit=2)
        cache_info = recommend_module._recommend_skills_cached.cache_info()

        self.assertNotEqual(second[0]["skill"], "mutated")
        self.assertNotIn("mutated", second[0]["matched"])
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_routing_guard_cache_is_reused_for_repeated_recommendations(self) -> None:
        policy_module._active_routing_guard_rules_cached.cache_clear()
        recommend_module._recommend_skills_cached.cache_clear()

        first = recommend_module.recommend_skills("risky refactor", limit=2)
        recommend_module._recommend_skills_cached.cache_clear()
        second = recommend_module.recommend_skills("risky refactor", limit=2)
        cache_info = policy_module._active_routing_guard_rules_cached.cache_info()

        self.assertEqual(first, second)
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_normalized_phrase_cache_reuses_folded_text(self) -> None:
        localization_module._fold_for_match.cache_clear()

        first = localization_module.normalized_phrase("Café risky refactor")
        second = localization_module.normalized_phrase("Café risky refactor")
        cache_info = localization_module._fold_for_match.cache_info()

        self.assertEqual(first, "cafe risky refactor")
        self.assertEqual(first, second)
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_routing_token_cache_reuses_terms_without_payload_poisoning(self) -> None:
        localization_module._routing_terms_cached.cache_clear()
        localization_module._routing_tokens_cached.cache_clear()

        first_terms = localization_module.routing_terms("Risky refactor with code-review")
        first_terms.add("mutated")
        second_terms = localization_module.routing_terms("Risky refactor with code-review")

        self.assertIn("risky", second_terms)
        self.assertIn("code-review", second_terms)
        self.assertNotIn("mutated", second_terms)
        terms_cache = localization_module._routing_terms_cached.cache_info()
        self.assertEqual(terms_cache.misses, 1)
        self.assertGreaterEqual(terms_cache.hits, 1)

        first_tokens = localization_module.routing_tokens("Risky refactor with code-review", stopwords=set())
        first_tokens.add("mutated")
        second_tokens = localization_module.routing_tokens("Risky refactor with code-review", stopwords=set())
        tokens_cache = localization_module._routing_tokens_cached.cache_info()

        self.assertIn("risky", second_tokens)
        self.assertIn("code-review", second_tokens)
        self.assertNotIn("mutated", second_tokens)
        self.assertEqual(tokens_cache.misses, 1)
        self.assertGreaterEqual(tokens_cache.hits, 1)

    def test_playbook_token_cache_reuses_static_terms_without_payload_poisoning(self) -> None:
        playbooks_module._playbook_scoring_profiles.cache_clear()
        playbooks_module._tokens_cached.cache_clear()
        playbooks_module._terms_cached.cache_clear()
        playbooks_module._normalized_term_tokens.cache_clear()

        first_terms = playbooks_module._terms("Risky refactor with code-review")
        first_terms.add("mutated")
        second_terms = playbooks_module._terms("Risky refactor with code-review")

        self.assertIn("risky", second_terms)
        self.assertIn("code-review", second_terms)
        self.assertNotIn("mutated", second_terms)
        terms_cache = playbooks_module._terms_cached.cache_info()
        self.assertEqual(terms_cache.misses, 1)
        self.assertGreaterEqual(terms_cache.hits, 1)

        first_tokens = playbooks_module._tokens("Risky refactor with code-review")
        first_tokens.add("mutated")
        second_tokens = playbooks_module._tokens("Risky refactor with code-review")
        tokens_cache = playbooks_module._tokens_cached.cache_info()

        self.assertIn("risky", second_tokens)
        self.assertIn("code-review", second_tokens)
        self.assertNotIn("mutated", second_tokens)
        self.assertEqual(tokens_cache.misses, 1)
        self.assertGreaterEqual(tokens_cache.hits, 1)

    def test_playbook_recommendation_cache_is_reused_without_payload_poisoning(self) -> None:
        playbooks_module._recommend_playbooks_cached.cache_clear()
        playbooks_module._playbook_scoring_profiles.cache_clear()
        playbooks_module._tokens_cached.cache_clear()
        playbooks_module._terms_cached.cache_clear()
        playbooks_module._normalized_term_tokens.cache_clear()

        first = playbooks_module.recommend_playbooks("risky refactor", limit=2)
        first["recommendations"][0]["id"] = "mutated"
        first["recommendations"][0]["matched"].append("mutated")
        first["recommendations"][0]["pipeline"][0] = "mutated"
        second = playbooks_module.recommend_playbooks("risky refactor", limit=2)
        result_cache = playbooks_module._recommend_playbooks_cached.cache_info()
        profile_cache = playbooks_module._playbook_scoring_profiles.cache_info()
        term_cache = playbooks_module._normalized_term_tokens.cache_info()

        self.assertNotEqual(second["recommendations"][0]["id"], "mutated")
        self.assertNotIn("mutated", second["recommendations"][0]["matched"])
        self.assertNotEqual(second["recommendations"][0]["pipeline"][0], "mutated")
        self.assertEqual(result_cache.misses, 1)
        self.assertGreaterEqual(result_cache.hits, 1)
        self.assertEqual(profile_cache.misses, 1)
        self.assertGreater(term_cache.misses, 0)

    def test_phrase_match_cache_reuses_repeated_recommendation_pairs(self) -> None:
        recommend_module._phrase_match.cache_clear()
        recommend_module._recommend_skills_cached.cache_clear()

        first = recommend_module.recommend_skills("risky refactor", limit=2)
        recommend_module._recommend_skills_cached.cache_clear()
        second = recommend_module.recommend_skills("risky refactor", limit=2)
        cache_info = recommend_module._phrase_match.cache_info()

        self.assertEqual(first, second)
        self.assertGreater(cache_info.misses, 0)
        self.assertGreater(cache_info.hits, 0)

    def test_catalog_question_caches_repeated_search_and_token_checks(self) -> None:
        catalog_questions_module._catalog_search_texts.cache_clear()
        catalog_questions_module._contains_catalog_token.cache_clear()

        first = catalog_questions_module.is_skill_catalog_question("what OMH workflows are available?")
        second = catalog_questions_module.is_skill_catalog_question("what OMH workflows are available?")
        search_cache = catalog_questions_module._catalog_search_texts.cache_info()
        token_cache = catalog_questions_module._contains_catalog_token.cache_info()

        self.assertTrue(first)
        self.assertEqual(first, second)
        self.assertEqual(search_cache.misses, 1)
        self.assertGreaterEqual(search_cache.hits, 1)
        self.assertGreater(token_cache.misses, 0)
        self.assertGreater(token_cache.hits, 0)

    def test_chat_route_decision_cache_is_reused_without_payload_poisoning(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()

        first = chat_module.route_chat_message("risky refactor with implementation and review", source="discord")
        first["selected_skill"] = "mutated"
        first["recommendations"][0]["skill"] = "mutated"
        first["workflow_route_plan"]["steps"][0]["skill"] = "mutated"

        second = chat_module.route_chat_message("risky refactor with implementation and review", source="discord")
        cache_info = chat_module._route_chat_message_cached.cache_info()

        self.assertNotEqual(second["selected_skill"], "mutated")
        self.assertNotEqual(second["recommendations"][0]["skill"], "mutated")
        self.assertNotEqual(second["workflow_route_plan"]["steps"][0]["skill"], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_public_chat_route_payload_cache_is_reused_without_payload_poisoning(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()
        chat_module._public_chat_route_payload_cached.cache_clear()

        first = chat_module.public_chat_route_payload(
            "risky refactor with implementation and review",
            source="discord",
        )
        first["selected_skill"] = "mutated"
        first["recommendations"][0]["skill"] = "mutated"
        first["route_explanation"]["selected_workflow"] = "mutated"

        second = chat_module.public_chat_route_payload(
            "risky refactor with implementation and review",
            source="discord",
        )
        cache_info = chat_module._public_chat_route_payload_cached.cache_info()

        self.assertNotEqual(second["selected_skill"], "mutated")
        self.assertNotEqual(second["recommendations"][0]["skill"], "mutated")
        self.assertNotEqual(second["route_explanation"]["selected_workflow"], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_route_boundary_gap_labels_reuse_static_extractors(self) -> None:
        self.assertIsInstance(chat_module._BOUNDARY_MARKER_LABELS, tuple)
        self.assertIsInstance(chat_module._BOUNDARY_REGEX_LABELS, tuple)

        boundary = "Status guidance is not proof that a runtime, tool, MCP server, CI job, or platform action ran."
        with patch.object(chat_module.re, "search", side_effect=AssertionError("use precompiled route-boundary patterns")):
            labels = chat_module._not_evidence_from_boundary(boundary)

        self.assertEqual(labels, ["runtime proof", "tool invocation", "MCP server", "platform action", "CI"])

    def test_learning_candidate_detection_cache_reuses_negative_messages(self) -> None:
        learning_candidate_module._detect_learning_signal_cached.cache_clear()

        first = learning_candidate_module.detect_learning_signal("risky refactor with implementation and review")
        second = learning_candidate_module.detect_learning_signal("risky refactor with implementation and review")
        cache_info = learning_candidate_module._detect_learning_signal_cached.cache_info()

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_learning_candidate_detection_cache_is_reused_without_payload_poisoning(self) -> None:
        learning_candidate_module._detect_learning_signal_cached.cache_clear()

        first = learning_candidate_module.detect_learning_signal("learn this: always run the focused tests first")
        self.assertIsNotNone(first)
        assert first is not None
        first["matched"] = "mutated"

        second = learning_candidate_module.detect_learning_signal("learn this: always run the focused tests first")
        cache_info = learning_candidate_module._detect_learning_signal_cached.cache_info()

        self.assertIsNotNone(second)
        assert second is not None
        self.assertEqual(second["matched"], "learn this")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_chat_interaction_uses_public_route_projection_cache(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()
        chat_module._public_chat_route_payload_cached.cache_clear()

        first = contract_module.build_chat_interaction_payload(
            "risky refactor with implementation and review",
            source="discord",
        )
        second = contract_module.build_chat_interaction_payload(
            "risky refactor with implementation and review",
            source="discord",
        )
        cache_info = chat_module._public_chat_route_payload_cached.cache_info()

        self.assertEqual(first["route"]["selected_skill"], second["route"]["selected_skill"])
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_chat_interaction_reuses_executor_target_hint_cache(self) -> None:
        contract_module._executor_target_from_message.cache_clear()

        first, first_resolution = contract_module._resolve_delegate_executor_target(
            "choose",
            None,
            message="open this in Codex and prepare the coding handoff",
        )
        second, second_resolution = contract_module._resolve_delegate_executor_target(
            "choose",
            None,
            message="open this in Codex and prepare the coding handoff",
        )
        cache_info = contract_module._executor_target_from_message.cache_info()

        self.assertEqual(first, "codex")
        self.assertEqual(second, "codex")
        self.assertEqual(first_resolution["source"], "message_mention")
        self.assertEqual(second_resolution["resolved_executor_target"], "codex")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_messenger_safe_body_cache_is_reused_without_transform_poisoning(self) -> None:
        contract_module._messenger_safe_body_cached.cache_clear()
        body = "| Field | Value |\n| --- | --- |\n| Status | Ready |"

        first_body, first_transforms = contract_module._messenger_safe_body(body)
        first_transforms.append("mutated")
        second_body, second_transforms = contract_module._messenger_safe_body(body)
        cache_info = contract_module._messenger_safe_body_cached.cache_info()

        self.assertEqual(first_body, second_body)
        self.assertIn("markdown_table_to_bullets", second_transforms)
        self.assertNotIn("mutated", second_transforms)
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_messenger_body_blocks_cache_is_reused_without_payload_poisoning(self) -> None:
        contract_module._messenger_body_blocks_cached.cache_clear()
        body = "Intro\n\n- first\n1. second"

        first = contract_module._messenger_body_blocks(body)
        first[0]["text"] = "mutated"
        second = contract_module._messenger_body_blocks(body)
        cache_info = contract_module._messenger_body_blocks_cached.cache_info()

        self.assertNotEqual(second[0]["text"], "mutated")
        self.assertEqual(second[1]["type"], "bullet")
        self.assertEqual(second[2]["type"], "numbered")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_hermes_plan_payload_cache_is_reused_without_payload_poisoning(self) -> None:
        hermes_planning_module._build_hermes_plan_payload_cached.cache_clear()

        first = hermes_planning_module.build_hermes_plan_payload(
            "risky refactor with implementation and review",
            source="discord",
            executor_target="codex",
        )
        first["plan"]["recommended_workflow"] = "mutated"
        first["wrapper_contract"]["coding_delegate"]["selected_executor_profile"] = "mutated"
        first["recommendations"][0]["skill"] = "mutated"

        second = hermes_planning_module.build_hermes_plan_payload(
            "risky refactor with implementation and review",
            source="discord",
            executor_target="codex",
        )
        cache_info = hermes_planning_module._build_hermes_plan_payload_cached.cache_info()

        self.assertNotEqual(second["plan"]["recommended_workflow"], "mutated")
        self.assertNotEqual(second["wrapper_contract"]["coding_delegate"]["selected_executor_profile"], "mutated")
        self.assertNotEqual(second["recommendations"][0]["skill"], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_workflow_route_plan_cache_is_reused_without_payload_poisoning(self) -> None:
        route_plan_module._build_workflow_route_plan_cached.cache_clear()
        route_plan_module._routable_definition_names.cache_clear()

        recommendations = recommend_module.recommend_skills("risky refactor", limit=10)
        first = route_plan_module.build_workflow_route_plan(
            "risky refactor",
            recommendations,
            selected_skill="ralplan",
            action="dispatch",
        )
        self.assertIsNotNone(first)
        assert first is not None
        first["steps"][0]["skill"] = "mutated"
        first["steps"][0]["matched"].append("mutated")

        second = route_plan_module.build_workflow_route_plan(
            "risky refactor",
            recommendations,
            selected_skill="ralplan",
            action="dispatch",
        )
        cache_info = route_plan_module._build_workflow_route_plan_cached.cache_info()
        definition_names_cache = route_plan_module._routable_definition_names.cache_info()

        self.assertIsNotNone(second)
        assert second is not None
        self.assertNotEqual(second["steps"][0]["skill"], "mutated")
        self.assertNotIn("mutated", second["steps"][0]["matched"])
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)
        self.assertEqual(definition_names_cache.misses, 1)
        self.assertGreaterEqual(definition_names_cache.hits, 0)

    def test_catalog_capability_summary_cache_is_reused_without_payload_poisoning(self) -> None:
        contract_module._catalog_capability_summary_cached.cache_clear()

        first = contract_module._catalog_capability_summary()
        first["lanes"][0]["id"] = "mutated"
        first["workflow_context_cards"][0]["user_examples"][0] = "mutated"
        second = contract_module._catalog_capability_summary()
        cache_info = contract_module._catalog_capability_summary_cached.cache_info()

        self.assertIsNot(first, second)
        self.assertNotEqual(second["lanes"][0]["id"], "mutated")
        self.assertNotEqual(second["workflow_context_cards"][0]["user_examples"][0], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_context_primer_cache_is_reused_without_payload_poisoning(self) -> None:
        contract_module._context_primer_state_cached.cache_clear()

        first = contract_module._context_primer_state()
        first["workflow_groups"][0]["id"] = "mutated"
        first["workflow_context_cards"][0]["user_examples"][0] = "mutated"
        second = contract_module._context_primer_state()
        cache_info = contract_module._context_primer_state_cached.cache_info()

        self.assertIsNot(first, second)
        self.assertNotEqual(second["workflow_groups"][0]["id"], "mutated")
        self.assertNotEqual(second["workflow_context_cards"][0]["user_examples"][0], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_skill_picker_static_state_cache_preserves_dynamic_fields_without_payload_poisoning(self) -> None:
        contract_module._skill_picker_static_state_cached.cache_clear()

        first = contract_module._skill_picker_state("./omh", source="discord")
        first["options"][0]["id"] = "mutated"
        second = contract_module._skill_picker_state("/omh", source="slack")
        cache_info = contract_module._skill_picker_static_state_cached.cache_info()

        self.assertIsNot(first, second)
        self.assertEqual(first["trigger"], "./omh")
        self.assertEqual(first["source"], "discord")
        self.assertEqual(second["trigger"], "/omh")
        self.assertEqual(second["source"], "slack")
        self.assertNotEqual(second["options"][0]["id"], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_skill_picker_family_body_lines_cache_is_reused_without_list_poisoning(self) -> None:
        contract_module._skill_picker_family_body_lines_cached.cache_clear()

        first = contract_module._skill_picker_family_body_lines()
        first[0] = "mutated"
        second = contract_module._skill_picker_family_body_lines()
        cache_info = contract_module._skill_picker_family_body_lines_cached.cache_info()

        self.assertIsNot(first, second)
        self.assertNotEqual(second[0], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)


if __name__ == "__main__":
    unittest.main()
