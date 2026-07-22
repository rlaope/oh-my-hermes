from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package


load_local_package()
from omh.skill_pack import builtin_definitions, builtin_skill_templates
from omh.routing import chat as chat_module
from omh.routing import catalog_questions as catalog_questions_module
from omh.routing import intent as intent_module
from omh.routing import localization as localization_module
from omh.routing import missed_route as missed_route_module
from omh.routing import recommend as recommend_module
from omh.routing import policy as policy_module
from omh.routing import route_plan as route_plan_module
from omh.catalogs import playbooks as playbooks_module
from omh.skills import render as render_module
from omh.workflows import hermes_planning as hermes_planning_module
from omh.workflows import learning_candidate as learning_candidate_module
from omh.wrapper import contract as contract_module
from omh.wrapper.route_hints import build_chat_route_hint_payload
from omh.paths import OmhPaths
from omh.release import (
    AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT,
    AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT,
    AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT,
    FULL_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
    FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
    STANDALONE_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
    STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
)
from omh.capabilities import families as families_module
from omh.capabilities.skills import skill_capabilities
from omh.coding import executor_readiness as executor_readiness_module
from omh.coding import executors as executors_module
from omh.context import build_context_brief
from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
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
    installable_skill_definitions,
    memory_context_policy_for_skill,
    retained_delegation_skill_names,
)
from omh.quality import grounded_score as grounded_score_module
from omh.quality import common_request_coverage as common_request_coverage_module
from omh.quality import context_brief_coverage as context_brief_coverage_module
from omh.quality import hermes_ux_quality as hermes_ux_quality_module
from omh.quality import localized_chat_copy as localized_chat_copy_module
from omh.quality import popular_plugin_coverage as popular_plugin_coverage_module
from omh.quality import router_fast_path as router_fast_path_module
from omh.quality import routing_precision as routing_precision_module
from omh.quality import route_hint_alignment as route_hint_alignment_module
from omh.quality.grounded_score import GroundedScenario
from omh.quality.route_hint_alignment import RouteHintAlignmentCase, route_hint_alignment_cases


class EfficiencyContractTests(unittest.TestCase):
    def test_quality_leakage_checks_avoid_full_payload_json_serialization(self) -> None:
        with patch.object(json, "dumps", side_effect=AssertionError("quality demos should scan payloads directly")):
            context_payload = context_brief_coverage_module.build_context_brief_coverage_demo(source="discord")
            precision_payload = routing_precision_module.build_routing_precision_demo(source="discord")

        self.assertTrue(all(row["passed"] for row in context_payload["cases"]))
        self.assertTrue(precision_payload["summary"]["all_passing"])
        self.assertTrue(all(row["passed"] for row in precision_payload["cases"]))
        self.assertTrue(all(row["passed"] for row in precision_payload["intervention_cases"]))

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
        installable_skills = {definition.name for definition in installable_skill_definitions()}

        self.assertFalse(installable_skills - lane_skills)
        retained_lane = next(lane for lane in payload["lanes"] if lane["id"] == "retained_knowledge")
        materials_lane = next(lane for lane in payload["lanes"] if lane["id"] == "materials_and_visuals")
        self.assertIn("wiki", retained_lane["skills"])
        self.assertNotIn("wiki", materials_lane["skills"])
        self.assertIn("wiki", cards["retained_knowledge"]["representative_workflows"])
        self.assertIn("img-summary", cards["materials_and_visuals"]["representative_workflows"])
        self.assertIn("frontend", cards["materials_and_visuals"]["representative_workflows"])
        self.assertIn("accessibility-audit", cards["materials_and_visuals"]["representative_workflows"])
        self.assertIn("visual-qa", cards["materials_and_visuals"]["representative_workflows"])
        self.assertNotIn("wiki", cards["materials_and_visuals"]["representative_workflows"])
        self.assertIn("workspace-audit", cards["automation_and_status"]["representative_workflows"])
        self.assertIn("production-audit", cards["automation_and_status"]["representative_workflows"])
        self.assertIn("agent-evaluation", cards["automation_and_status"]["representative_workflows"])
        self.assertIn("rules-distill", cards["automation_and_status"]["representative_workflows"])
        self.assertIn("agent-debug", cards["automation_and_status"]["representative_workflows"])
        self.assertIn("instinct-ledger", cards["automation_and_status"]["representative_workflows"])
        self.assertIn("skill-scout", cards["automation_and_status"]["representative_workflows"])
        self.assertIn("skill-health", cards["automation_and_status"]["representative_workflows"])
        self.assertIn("ultraprocess", cards["coding_handoff"]["representative_workflows"])
        self.assertIn("build-failure-triage", cards["coding_handoff"]["representative_workflows"])
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
        workflow_skills = {
            definition.name for definition in installable_skill_definitions()
        } - {"oh-my-hermes", "cancel"}
        unmapped = sorted(name for name in workflow_skills if not workflow_context_card_for_workflow(name))

        self.assertEqual(unmapped, [])
        self.assertEqual(workflow_context_card_for_workflow("wiki")["id"], "retained_knowledge")
        self.assertEqual(workflow_context_card_for_workflow("img-summary")["id"], "materials_and_visuals")
        self.assertEqual(workflow_context_card_for_workflow("frontend")["id"], "materials_and_visuals")
        self.assertEqual(workflow_context_card_for_workflow("accessibility-audit")["id"], "materials_and_visuals")
        self.assertEqual(workflow_context_card_for_workflow("visual-qa")["id"], "materials_and_visuals")
        self.assertEqual(workflow_context_card_for_workflow("feedback-triage")["id"], "research_and_ops")
        self.assertEqual(workflow_context_card_for_workflow("automation-blueprint")["id"], "automation_and_status")
        self.assertEqual(workflow_context_card_for_workflow("workspace-audit")["id"], "automation_and_status")
        self.assertEqual(workflow_context_card_for_workflow("production-audit")["id"], "automation_and_status")
        self.assertEqual(workflow_context_card_for_workflow("agent-evaluation")["id"], "automation_and_status")
        self.assertEqual(workflow_context_card_for_workflow("rules-distill")["id"], "automation_and_status")
        self.assertEqual(workflow_context_card_for_workflow("failure-signal-audit")["id"], "automation_and_status")
        self.assertIn("audit", workflow_context_card_for_workflow("failure-signal-audit")["first_response_shape"])
        self.assertEqual(workflow_context_card_for_workflow("instinct-ledger")["id"], "automation_and_status")
        self.assertEqual(workflow_context_card_for_workflow("build-failure-triage")["id"], "coding_handoff")
        self.assertEqual(workflow_context_card_for_workflow("verification-gate")["id"], "coding_handoff")
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
        self.assertTrue(awareness_context_matches_message("haz una imagen que explique la función cron"))
        self.assertTrue(awareness_context_matches_message("trouve le dépôt GitHub et le PDF public"))
        self.assertTrue(awareness_context_matches_message("erkläre dieses Paper einfach"))
        self.assertTrue(awareness_context_matches_message("make a PR summary card for reviewers"))
        self.assertTrue(awareness_context_matches_message("what is the coding handoff status?"))
        self.assertFalse(awareness_context_matches_message("prepare a sandwich"))
        self.assertFalse(awareness_context_matches_message("gracias"))
        self.assertFalse(awareness_context_matches_message("what is Discord?"))
        self.assertFalse(awareness_context_matches_message("what is QA?"))
        self.assertFalse(awareness_context_matches_message("what is onboarding?"))
        self.assertFalse(awareness_context_matches_message("what is refactoring?"))
        self.assertFalse(awareness_context_matches_message(""))

        doctor_hint = awareness_route_hint("update 했는데 잘 된거야?")
        self.assertEqual(doctor_hint["primary_workflow"], "doctor")
        self.assertEqual(doctor_hint["primary_next_action"], "run_local_operator_check")

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

    def test_ecc_operator_route_hints_match_explicit_skill_names(self) -> None:
        cases = (
            ("workspace-audit 레포 스킬이랑 MCP 표면 감사해줘", "workspace-audit", "prepare_workspace_audit"),
            ("production-audit 릴리즈 프로덕션 준비 상태 감사해줘", "production-audit", "prepare_production_audit"),
            ("verification-gate 머지 전 검증 게이트 준비해줘", "verification-gate", "prepare_verification_gate"),
            ("agent-evaluation Codex랑 Claude Code 에이전트 평가해줘", "agent-evaluation", "prepare_agent_evaluation"),
            ("rules-distill 실패 trace에서 스킬 원칙 규칙 증류해줘", "rules-distill", "prepare_rules_distillation"),
            ("codebase-onboarding 처음 보는 레포 구조 잡아줘", "codebase-onboarding", "prepare_codebase_onboarding"),
            ("agent-debug 에이전트 반복 실패 캡처해줘", "agent-debug", "prepare_agent_debug"),
            ("instinct-ledger 프로젝트 학습 패턴을 승격 검토해줘", "instinct-ledger", "prepare_instinct_ledger"),
            ("skill-scout 스킬 후보 찾아보고 만들지 결정해줘", "skill-scout", "prepare_skill_scout"),
            ("skill-health 스킬 포트폴리오 상태 대시보드 보여줘", "skill-health", "prepare_skill_health"),
            (
                "context-budget-review 장기 작업 컨텍스트 예산 잡아줘",
                "context-budget-review",
                "prepare_context_budget_review",
            ),
            (
                "security-safety-review 프롬프트 인젝션과 시크릿 위험 봐줘",
                "security-safety-review",
                "prepare_security_safety_review",
            ),
        )

        for message, workflow, next_action in cases:
            with self.subTest(message=message):
                route_hint = awareness_route_hint(message)

                self.assertEqual(route_hint["primary_workflow"], workflow)
                self.assertEqual(route_hint["primary_next_action"], next_action)

    def test_ecc_operator_route_hints_do_not_steal_generic_language(self) -> None:
        new_operator_workflows = {
            "workspace-audit",
            "verification-gate",
            "rules-distill",
            "codebase-onboarding",
            "agent-debug",
            "instinct-ledger",
            "skill-health",
            "context-budget-review",
            "security-safety-review",
        }
        generic_messages = (
            "verify the source before answering",
            "can you audit my plan for unclear requirements?",
            "show guidance for onboarding improvements",
            "what is application security?",
            "how much does this provider cost?",
            "what rules apply to python packaging?",
        )

        for message in generic_messages:
            with self.subTest(message=message):
                route_hint = awareness_route_hint(message)

                self.assertNotIn(route_hint["primary_workflow"], new_operator_workflows)

    def test_mid_session_awareness_detector_cache_reuses_locale_scan(self) -> None:
        awareness_module._awareness_context_matches_message_cached.cache_clear()

        message = "trouve le dépôt GitHub et le PDF public"
        self.assertTrue(awareness_context_matches_message(message))
        self.assertTrue(awareness_context_matches_message(message))
        cache_info = awareness_module._awareness_context_matches_message_cached.cache_info()

        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_mid_session_awareness_detector_covers_route_hint_alignment_corpus(self) -> None:
        misses = [
            case.id
            for case in route_hint_alignment_cases()
            if not awareness_context_matches_message(case.message)
        ]

        self.assertEqual(misses, [])

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

    def test_context_brief_prompt_context_reuses_route_hint_payload(self) -> None:
        awareness_module._awareness_route_hint_cached.cache_clear()

        payload = build_context_brief(
            "Codex 작업이 어디까지 진행됐는지 알려줘",
            source="discord",
            include_prompt_context=True,
        )
        cache_info = awareness_module._awareness_route_hint_cached.cache_info()

        self.assertEqual(payload["route_hint"]["primary_workflow"], "ultraprocess")
        self.assertEqual(payload["route_hint"]["primary_next_action"], "show_coding_handoff_status")
        self.assertIn("next_action=show_coding_handoff_status", payload["prompt_context"])
        self.assertEqual(cache_info.misses, 1)
        self.assertEqual(cache_info.hits, 0)

    def test_chat_route_hint_prompt_context_reuses_route_hint_payload(self) -> None:
        awareness_module._awareness_route_hint_cached.cache_clear()

        payload = build_chat_route_hint_payload(
            "Codex 작업이 어디까지 진행됐는지 알려줘",
            source="discord",
            include_prompt_context=True,
        )
        cache_info = awareness_module._awareness_route_hint_cached.cache_info()

        self.assertEqual(payload["route_hint"]["primary_workflow"], "ultraprocess")
        self.assertEqual(payload["route_hint"]["primary_next_action"], "show_coding_handoff_status")
        self.assertIn("next_action=show_coding_handoff_status", payload["prompt_context"])
        self.assertEqual(cache_info.misses, 1)
        self.assertEqual(cache_info.hits, 0)

    def test_pre_llm_call_reuses_route_hint_payload_for_context_brief(self) -> None:
        awareness_module._awareness_route_hint_cached.cache_clear()

        with TemporaryDirectory() as temp_dir:
            payload = pre_llm_call(
                omh_home=temp_dir,
                hermes_home=temp_dir,
                user_message="Codex 작업이 어디까지 진행됐는지 알려줘",
                is_first_turn=False,
            )
        cache_info = awareness_module._awareness_route_hint_cached.cache_info()

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["omh_context_brief"]["route_hint"]["primary_workflow"], "ultraprocess")
        self.assertEqual(
            payload["omh_context_brief"]["route_hint"]["primary_next_action"],
            "show_coding_handoff_status",
        )
        self.assertIn("next_action=show_coding_handoff_status", payload["context"])
        self.assertEqual(cache_info.misses, 1)
        self.assertEqual(cache_info.hits, 0)

    def test_pre_llm_call_suppressed_awareness_skips_route_hint_cache(self) -> None:
        awareness_module._awareness_route_hint_cached.cache_clear()

        with TemporaryDirectory() as temp_dir:
            payload = pre_llm_call(
                omh_home=temp_dir,
                hermes_home=temp_dir,
                user_message="make an image explaining the cron feature",
                is_first_turn=False,
                include_omh_awareness=False,
            )
        cache_info = awareness_module._awareness_route_hint_cached.cache_info()

        self.assertIsNone(payload)
        self.assertEqual(cache_info.misses, 0)
        self.assertEqual(cache_info.hits, 0)

    def test_pre_llm_call_generic_mid_session_skips_route_hint_cache(self) -> None:
        awareness_module._awareness_context_matches_message_cached.cache_clear()
        awareness_module._awareness_route_hint_cached.cache_clear()

        with TemporaryDirectory() as temp_dir:
            payload = pre_llm_call(
                omh_home=temp_dir,
                hermes_home=temp_dir,
                user_message="tell me a short joke",
                is_first_turn=False,
            )
        matcher_cache = awareness_module._awareness_context_matches_message_cached.cache_info()
        route_hint_cache = awareness_module._awareness_route_hint_cached.cache_info()

        self.assertIsNone(payload)
        self.assertEqual(matcher_cache.misses, 1)
        self.assertEqual(route_hint_cache.misses, 0)
        self.assertEqual(route_hint_cache.hits, 0)

    def test_quality_demos_reuse_interaction_route(self) -> None:
        alignment_case = RouteHintAlignmentCase(
            "synthetic",
            "synthetic-route",
            "Synthetic route reuse",
            "synthetic message that should not hit the real router",
            "synthetic-workflow",
            "synthetic_next_action",
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
            "synthetic_next_action",
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

    def test_localized_chat_copy_demo_cache_is_reused_without_payload_poisoning(self) -> None:
        localized_chat_copy_module._build_localized_chat_copy_demo_cached.cache_clear()

        first = localized_chat_copy_module.build_localized_chat_copy_demo(source="discord")
        first["summary"]["case_count"] = "mutated"
        first["cases"][0]["observed"]["locale"] = "mutated"

        second = localized_chat_copy_module.build_localized_chat_copy_demo(source="discord")
        cache_info = localized_chat_copy_module._build_localized_chat_copy_demo_cached.cache_info()

        self.assertNotEqual(second["summary"]["case_count"], "mutated")
        self.assertNotEqual(second["cases"][0]["observed"]["locale"], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_hermes_ux_quality_reuses_precomputed_gate_payloads(self) -> None:
        grounded_payload = {
            "summary": {
                "all_10": True,
                "scenario_count": 1,
                "minimum_score": 10,
                "average_score": 10,
                "maximum_score": 10,
            },
            "scenarios": [],
            "claim_boundary": "grounded boundary",
        }
        chat_card_payload = {
            "summary": {
                "all_passing": True,
                "case_count": 1,
                "passing_count": 1,
                "generic_ack_count": 0,
            },
            "cases": [],
            "claim_boundary": "chat card boundary",
        }
        route_hint_payload = {
            "summary": {
                "all_aligned": True,
                "case_count": 1,
                "aligned_count": 1,
                "missing_hint_count": 0,
                "mismatch_count": 0,
            },
            "cases": [],
            "claim_boundary": "route hint boundary",
        }
        context_payload = {
            "summary": {
                "all_passing": True,
                "case_count": 2,
                "passing_count": 2,
                "route_hint_count": 1,
                "catalog_question_count": 1,
            },
            "cases": [],
            "claim_boundary": "context boundary",
        }
        precision_payload = {
            "schema_version": routing_precision_module.ROUTING_PRECISION_SCHEMA_VERSION,
            "summary": {
                "all_passing": True,
                "case_count": 1,
                "passing_count": 1,
                "overroute_count": 0,
                "catalog_picker_count": 0,
                "generic_ack_count": 0,
                "intervention_case_count": 1,
                "intervention_passing_count": 1,
                "missed_intervention_count": 0,
                "intervention_generic_ack_count": 0,
            },
            "cases": [],
            "intervention_cases": [],
            "claim_boundary": "precision boundary",
        }
        localized_payload = {
            "schema_version": localized_chat_copy_module.LOCALIZED_CHAT_COPY_SCHEMA_VERSION,
            "summary": {
                "all_passing": True,
                "case_count": 1,
                "passing_count": 1,
                "locale_count": 1,
            },
            "cases": [],
            "claim_boundary": "localized boundary",
        }
        router_fast_path_payload = {
            "schema_version": router_fast_path_module.ROUTER_FAST_PATH_SCHEMA_VERSION,
            "summary": {
                "all_passing": True,
                "case_count": 1,
                "passing_count": 1,
                "missing_marker_count": 0,
                "route_mismatch_count": 0,
                "next_action_mismatch_count": 0,
            },
            "cases": [],
            "claim_boundary": "router fast-path boundary",
        }
        common_request_payload = {
            "schema_version": common_request_coverage_module.COMMON_REQUEST_COVERAGE_SCHEMA_VERSION,
            "summary": {
                "all_passing": True,
                "target_met": True,
                "case_count": 1,
                "passing_count": 1,
                "coverage_percent": 100.0,
                "target_percent": 95.0,
                "generic_ack_count": 0,
                "workflow_count": 1,
                "dispatch_count": 1,
                "fallback_count": 0,
                "popular_plugin_family_count": 1,
                "popular_plugin_covered_family_count": 1,
                "popular_plugin_weighted_coverage_percent": 100.0,
                "popular_plugin_target_percent": 95.0,
            },
            "families": [],
            "popular_plugin_coverage": {
                "schema_version": popular_plugin_coverage_module.POPULAR_PLUGIN_COVERAGE_SCHEMA_VERSION,
                "target_percent": 95.0,
                "summary": {
                    "family_count": 1,
                    "covered_family_count": 1,
                    "case_reference_count": 1,
                    "covered_case_reference_count": 1,
                    "unique_case_count": 1,
                    "covered_unique_case_count": 1,
                    "total_weight": 1,
                    "covered_weight": 1,
                    "weighted_coverage_percent": 100.0,
                    "target_met": True,
                    "generic_ack_count": 0,
                },
                "families": [],
                "claim_boundary": "popular plugin boundary",
            },
            "cases": [],
            "claim_boundary": "common request boundary",
        }

        with (
            patch.object(
                hermes_ux_quality_module,
                "build_grounded_score_demo",
                side_effect=AssertionError("precomputed grounded payload should be reused"),
            ),
            patch.object(
                hermes_ux_quality_module,
                "build_chat_card_coverage_demo",
                side_effect=AssertionError("precomputed chat-card payload should be reused"),
            ),
            patch.object(
                hermes_ux_quality_module,
                "build_route_hint_alignment_demo",
                side_effect=AssertionError("precomputed route-hint payload should be reused"),
            ),
            patch.object(
                hermes_ux_quality_module,
                "build_context_brief_coverage_demo",
                side_effect=AssertionError("precomputed context payload should be reused"),
            ),
            patch.object(
                hermes_ux_quality_module,
                "build_routing_precision_demo",
                side_effect=AssertionError("precomputed precision payload should be reused"),
            ),
            patch.object(
                hermes_ux_quality_module,
                "build_localized_chat_copy_demo",
                side_effect=AssertionError("precomputed localized payload should be reused"),
            ),
            patch.object(
                hermes_ux_quality_module,
                "build_router_fast_path_demo",
                side_effect=AssertionError("precomputed router fast-path payload should be reused"),
            ),
            patch.object(
                hermes_ux_quality_module,
                "build_common_request_coverage_demo",
                side_effect=AssertionError("precomputed common request payload should be reused"),
            ),
        ):
            payload = hermes_ux_quality_module.build_hermes_ux_quality_demo(
                source="discord",
                grounded_score=grounded_payload,
                chat_card_coverage=chat_card_payload,
                route_hint_alignment=route_hint_payload,
                context_brief_coverage=context_payload,
                routing_precision=precision_payload,
                localized_chat_copy=localized_payload,
                router_fast_path=router_fast_path_payload,
                common_request_coverage=common_request_payload,
            )

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["summary"]["passing_gate_count"], 8)
        self.assertEqual(payload["summary"]["localized_chat_copy_passing_count"], 1)
        self.assertEqual(payload["summary"]["router_fast_path_passing_count"], 1)
        self.assertEqual(payload["summary"]["common_request_passing_count"], 1)

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
        self.assertLessEqual(len(next(item for item in full_items if item["id"] == "img-summary")["triggers"]), 8)
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

    def test_recommendation_ranking_cache_is_reused_across_limits(self) -> None:
        recommend_module._recommend_skills_cached.cache_clear()

        first = recommend_module.recommend_skills("risky refactor", limit=2)
        second = recommend_module.recommend_skills("risky refactor", limit=8)
        cache_info = recommend_module._recommend_skills_cached.cache_info()

        self.assertEqual([item["skill"] for item in first], [item["skill"] for item in second[:2]])
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

    def test_routing_phrase_presence_cache_reuses_guard_checks(self) -> None:
        policy_module._contains_phrase.cache_clear()

        first = policy_module._contains_phrase(
            "this refactor feels risky",
            policy_module._RISKY_REFACTOR_RISK_PHRASES,
        )
        second = policy_module._contains_phrase(
            "this refactor feels risky",
            policy_module._RISKY_REFACTOR_RISK_PHRASES,
        )
        cache_info = policy_module._contains_phrase.cache_info()

        self.assertTrue(first)
        self.assertEqual(first, second)
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_missed_route_phrase_cache_reuses_feedback_checks(self) -> None:
        missed_route_module._contains_phrase.cache_clear()
        missed_route_module._contains_compact_phrase.cache_clear()

        first = missed_route_module.is_missed_route_feedback("missed route: OMH was not used")
        second = missed_route_module.is_missed_route_feedback("missed route: OMH was not used")
        phrase_cache = missed_route_module._contains_phrase.cache_info()

        self.assertTrue(first)
        self.assertEqual(first, second)
        self.assertEqual(phrase_cache.misses, 1)
        self.assertGreaterEqual(phrase_cache.hits, 1)

        missed_route_module._contains_compact_phrase.cache_clear()
        first_compact = missed_route_module.is_missed_route_feedback("라우팅 누락 기록해줘")
        second_compact = missed_route_module.is_missed_route_feedback("라우팅 누락 기록해줘")
        compact_cache = missed_route_module._contains_compact_phrase.cache_info()

        self.assertTrue(first_compact)
        self.assertEqual(first_compact, second_compact)
        self.assertEqual(compact_cache.misses, 1)
        self.assertGreaterEqual(compact_cache.hits, 1)

    def test_intent_classifier_cache_reuses_repeated_workflow_checks(self) -> None:
        intent_module.classify_workflow_intent.cache_clear()

        message = "OMH route: `$ultraprocess` ≠ ejecutar; Codex handoff token only."
        first = intent_module.classify_workflow_intent(message)
        second = intent_module.classify_workflow_intent(message)
        cache_info = intent_module.classify_workflow_intent.cache_info()

        self.assertIs(first, second)
        self.assertEqual(first.intent_class, "meta_discussion")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_omh_quality_classifier_cache_reuses_repeated_quality_checks(self) -> None:
        intent_module.classify_omh_quality_intent.cache_clear()

        first = intent_module.classify_omh_quality_intent("Improve OMH routing quality and handoff reliability")
        second = intent_module.classify_omh_quality_intent("Improve OMH routing quality and handoff reliability")
        cache_info = intent_module.classify_omh_quality_intent.cache_info()

        self.assertIs(first, second)
        self.assertTrue(second.applies)
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_diagnostic_status_scrub_cache_reuses_repeated_status_text(self) -> None:
        intent_module.scrub_diagnostic_status_text.cache_clear()

        status_text = "[omh] selected_workflow=ultraprocess | status=prepared\nWhy did OMH route this wrong?"
        first = intent_module.scrub_diagnostic_status_text(status_text)
        second = intent_module.scrub_diagnostic_status_text(status_text)
        cache_info = intent_module.scrub_diagnostic_status_text.cache_info()

        self.assertEqual(first, second)
        self.assertIn("why did omh route this wrong", second)
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

    def test_prepare_routing_text_cache_reuses_locale_alias_scan(self) -> None:
        localization_module._prepare_routing_text_cached.cache_clear()

        first = localization_module.prepare_routing_text("生成一张解释 cron 功能的图片")
        second = localization_module.prepare_routing_text("生成一张解释 cron 功能的图片")
        cache_info = localization_module._prepare_routing_text_cached.cache_info()

        self.assertIs(first, second)
        self.assertIn("visual summary", second.scoring_text)
        self.assertIn("zh:visual_summary", second.locale_matches)
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

    def test_direct_phrase_match_preserves_recommendation_scoring(self) -> None:
        recommend_module._recommend_skills_cached.cache_clear()

        first = recommend_module.recommend_skills("risky refactor", limit=2)
        recommend_module._recommend_skills_cached.cache_clear()
        second = recommend_module.recommend_skills("risky refactor", limit=2)

        self.assertEqual(first, second)
        self.assertTrue(recommend_module._phrase_match("risky refactor", "risky refactor planning"))
        self.assertTrue(recommend_module._phrase_match("risky refactor planning", "risky refactor"))
        self.assertFalse(recommend_module._phrase_match("payment failures", "risky refactor"))

    def test_catalog_question_caches_repeated_search_and_token_checks(self) -> None:
        catalog_questions_module.is_skill_catalog_question.cache_clear()
        catalog_questions_module._catalog_search_texts.cache_clear()
        catalog_questions_module._contains_catalog_token.cache_clear()

        first = catalog_questions_module.is_skill_catalog_question("what OMH workflows are available?")
        second = catalog_questions_module.is_skill_catalog_question("what OMH workflows are available?")
        question_cache = catalog_questions_module.is_skill_catalog_question.cache_info()
        search_cache = catalog_questions_module._catalog_search_texts.cache_info()
        token_cache = catalog_questions_module._contains_catalog_token.cache_info()

        self.assertTrue(first)
        self.assertEqual(first, second)
        self.assertEqual(question_cache.misses, 1)
        self.assertGreaterEqual(question_cache.hits, 1)
        self.assertEqual(search_cache.misses, 1)
        self.assertGreater(token_cache.misses, 0)

    def test_specific_capability_hits_cache_repeated_catalog_checks(self) -> None:
        chat_module._specific_capability_named_hits.cache_clear()
        chat_module._specific_capability_exact_id_hit.cache_clear()
        chat_module._is_broad_capability_catalog_question.cache_clear()

        first_hits = chat_module._specific_capability_named_hits("what can OMH do for paper-learning?")
        second_hits = chat_module._specific_capability_named_hits("what can OMH do for paper-learning?")
        first_exact = chat_module._specific_capability_exact_id_hit("what can OMH do for paper-learning?")
        second_exact = chat_module._specific_capability_exact_id_hit("what can OMH do for paper-learning?")
        first_broad = chat_module._is_broad_capability_catalog_question("paper-learning / web-research")
        second_broad = chat_module._is_broad_capability_catalog_question("paper-learning / web-research")
        hits_cache = chat_module._specific_capability_named_hits.cache_info()
        exact_cache = chat_module._specific_capability_exact_id_hit.cache_info()
        broad_cache = chat_module._is_broad_capability_catalog_question.cache_info()

        self.assertEqual(first_hits, second_hits)
        self.assertIn("paper-learning", second_hits)
        self.assertEqual(first_exact, "paper-learning")
        self.assertEqual(first_exact, second_exact)
        self.assertTrue(first_broad)
        self.assertEqual(first_broad, second_broad)
        self.assertEqual(hits_cache.misses, 2)
        self.assertGreaterEqual(hits_cache.hits, 1)
        self.assertEqual(exact_cache.misses, 1)
        self.assertGreaterEqual(exact_cache.hits, 1)
        self.assertEqual(broad_cache.misses, 1)
        self.assertGreaterEqual(broad_cache.hits, 1)

    def test_file_lookup_question_cache_reuses_repeated_lookup_checks(self) -> None:
        catalog_questions_module.is_file_or_text_lookup_question.cache_clear()
        catalog_questions_module._catalog_search_texts.cache_clear()

        first = catalog_questions_module.is_file_or_text_lookup_question("find the README file")
        second = catalog_questions_module.is_file_or_text_lookup_question("find the README file")
        lookup_cache = catalog_questions_module.is_file_or_text_lookup_question.cache_info()
        search_cache = catalog_questions_module._catalog_search_texts.cache_info()

        self.assertTrue(first)
        self.assertEqual(first, second)
        self.assertEqual(lookup_cache.misses, 1)
        self.assertGreaterEqual(lookup_cache.hits, 1)
        self.assertEqual(search_cache.misses, 1)

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

    def test_operator_surface_fast_paths_skip_full_recommendation_scan(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()
        cases = (
            ("how can I safely add a feature to this repo?", "ralplan"),
            ("risky refactor", "ralplan"),
            ("위험한 리팩터링 같아", "ralplan"),
            ("릴리즈 노트 썸네일로 만들어줘", "img-summary"),
            ("github oss repo 찾아서 비교해줘", "source-finder"),
            ("깃허브 repo 소스 찾아줘", "source-finder"),
            ("자료 출처 찾아줘 데이터셋이랑 깃허브까지", "source-finder"),
            ("find papers datasets github repos and public presentations about agent memory", "source-finder"),
            ("arxiv 링크 찾아서 쉽게 설명해줘", "source-finder"),
            ("코덱스로 이 이슈 PR 만들어줘", "ultraprocess"),
            ("오늘 아침 경쟁사 뉴스 요약 자동화해줘", "automation-blueprint"),
        )

        with patch.object(chat_module, "recommend_skills", side_effect=AssertionError("fast path should skip scoring")):
            for message, expected_skill in cases:
                with self.subTest(message=message):
                    decision = chat_module.route_chat_message(message, source="discord")

                    self.assertEqual(decision["selected_skill"], expected_skill)
                    self.assertEqual(decision["action"], "dispatch")
                    self.assertEqual(decision["confidence"], "high")
                    self.assertTrue(
                        any(
                            str(marker).startswith("operator_surface_fast_path")
                            for marker in decision["recommendations"][0]["matched"]
                        )
                    )

    def test_feedback_triage_fast_paths_skip_full_recommendation_scan(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()
        cases = (
            "결제 실패 이슈가 자주 나와",
            "Payment failures keep coming up.",
            "Users say checkout is broken.",
        )

        with patch.object(
            chat_module,
            "recommend_skills",
            side_effect=AssertionError("feedback-triage fast path should skip scoring"),
        ), patch.object(
            chat_module,
            "build_workflow_route_plan",
            side_effect=AssertionError("feedback-triage fast path should not build route plans"),
        ):
            for message in cases:
                chat_module._route_chat_message_cached.cache_clear()
                with self.subTest(message=message):
                    decision = chat_module.route_chat_message(message, source="discord")

                    self.assertEqual(decision["selected_skill"], "feedback-triage")
                    self.assertEqual(decision["action"], "dispatch")
                    self.assertEqual(decision["confidence"], "high")
                    self.assertIn("feedback_triage_fast_path", decision["recommendations"][0]["matched"])
                    self.assertIsNone(decision["workflow_route_plan"])

    def test_product_shaping_fast_paths_skip_full_recommendation_scan(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()
        cases = (
            "make onboarding feel smoother",
            "make the user experience smoother",
            "온보딩을 더 부드럽게 만들고 싶어",
        )

        with patch.object(
            chat_module,
            "recommend_skills",
            side_effect=AssertionError("product-shaping fast path should skip scoring"),
        ), patch.object(
            chat_module,
            "build_workflow_route_plan",
            side_effect=AssertionError("product-shaping fast path should not build route plans"),
        ):
            for message in cases:
                chat_module._route_chat_message_cached.cache_clear()
                with self.subTest(message=message):
                    decision = chat_module.route_chat_message(message, source="discord")

                    self.assertEqual(decision["selected_skill"], "deep-interview")
                    self.assertEqual(decision["action"], "dispatch")
                    self.assertEqual(decision["confidence"], "high")
                    self.assertIn("product_shaping_fast_path", decision["recommendations"][0]["matched"])
                    self.assertIsNone(decision["workflow_route_plan"])

    def test_product_shaping_fast_path_does_not_steal_compound_requests(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()
        cases = (
            ("make onboarding feel smoother and implement it", "oh-my-hermes", "start_ultraprocess"),
            ("improve onboarding conversion with a plan and implementation", "plan", "present_plan"),
            ("fix onboarding bug", "ultraprocess", "start_ultraprocess"),
        )

        for message, expected_skill, expected_action in cases:
            chat_module._route_chat_message_cached.cache_clear()
            with self.subTest(message=message):
                decision = chat_module.route_chat_message(message, source="discord")

                self.assertEqual(decision["selected_skill"], expected_skill)
                self.assertEqual(decision["recommendations"][0]["next_action"], expected_action)
                self.assertNotIn("product_shaping_fast_path", decision["recommendations"][0]["matched"])

    def test_single_workflow_operator_fast_paths_skip_route_plan_build(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()
        cases = (
            ("risky refactor", "ralplan"),
            ("논문 요약해줘", "paper-learning"),
            ("이 PDF 논문 초보자도 이해하게 풀어줘", "paper-learning"),
            ("첨부한 paper를 쉬운 난이도로 설명해줘", "paper-learning"),
            ("웹서치해서 최신 자료 정리해줘", "web-research"),
            ("이미지 생성해줘. 회의록을 세로 카드로 요약해줘", "img-summary"),
            ("PPT 만들어줘", "materials-package"),
            ("codex로 열어줘", "executor-runtime-readiness"),
            ("codex로 새 세션 만들어서 열어줘", "executor-runtime-readiness"),
            ("코딩 에이전트 뭘로 설정돼있어?", "executor-runtime-readiness"),
            ("codex로 지금 작업 열어줘", "executor-runtime-readiness"),
            ("claude code로 지금 작업 열어줘", "executor-runtime-readiness"),
            ("claude code로 새 세션 시작하게 해줘", "executor-runtime-readiness"),
            ("claude code 세션 연결해서 이어서 보게 해줘", "executor-runtime-readiness"),
            ("codex 세션 열고 방금 핸드오프 이어서 진행해줘", "executor-runtime-readiness"),
            ("merge할때도 프리렌 author로 머지해", "ultraprocess"),
            ("프리렌 author로 커밋하고 머지해", "ultraprocess"),
            ("github oss repo 찾아서 비교해줘", "source-finder"),
            ("코덱스로 이 이슈 PR 만들어줘", "ultraprocess"),
            ("오늘 아침 경쟁사 뉴스 요약 자동화해줘", "automation-blueprint"),
            ("매일 아침 리서치 요약을 보내게 준비해줘", "automation-blueprint"),
            ("workspace-audit 레포 스킬이랑 MCP 표면 감사해줘", "workspace-audit"),
            ("production-audit 릴리즈 프로덕션 준비 상태 감사해줘", "production-audit"),
            ("verification-gate 머지 전 검증 게이트 준비해줘", "verification-gate"),
            ("agent-evaluation Codex랑 Claude Code 에이전트 평가해줘", "agent-evaluation"),
            ("rules-distill 실패 trace에서 스킬 원칙 규칙 증류해줘", "rules-distill"),
            ("codebase-onboarding 처음 보는 레포 구조 잡아줘", "codebase-onboarding"),
            ("agent-debug 에이전트 반복 실패 캡처해줘", "agent-debug"),
            ("instinct-ledger 프로젝트 학습 패턴을 승격 검토해줘", "instinct-ledger"),
            ("skill-scout 스킬 후보 찾아보고 만들지 결정해줘", "skill-scout"),
            ("skill-health 스킬 포트폴리오 상태 대시보드 보여줘", "skill-health"),
            ("context-budget-review 장기 작업 컨텍스트 예산 잡아줘", "context-budget-review"),
            ("security-safety-review 프롬프트 인젝션과 시크릿 위험 봐줘", "security-safety-review"),
            ("hermes agent가 한개가 아니라 여러개일땐 어떻게 동작해?", "agent-board"),
            ("multiple Hermes agents target topology 어떻게 관리해?", "agent-board"),
            ("슬랙에서 /omh 치면 뭐가 떠야해?", "oh-my-hermes"),
            ("./ 쳤는데 omh가 안 떠", "oh-my-hermes"),
            ("Hermes가 omh list 승인하라고 하는데 굳이 쳐야해?", "oh-my-hermes"),
            ("what OMH workflows are available without running omh list?", "oh-my-hermes"),
            ("workflow trace 보고 다음에 스킬 고칠점 알려줘", "workflow-learning"),
            ("project-scoped instincts with promotion review", "instinct-ledger"),
        )

        with patch.object(
            chat_module,
            "build_workflow_route_plan",
            side_effect=AssertionError("single-workflow fast paths should not build route plans"),
        ):
            for message, expected_skill in cases:
                chat_module._route_chat_message_cached.cache_clear()
                with self.subTest(message=message):
                    decision = chat_module.route_chat_message(message, source="discord")

                    self.assertEqual(decision["selected_skill"], expected_skill)
                    self.assertIsNone(decision["workflow_route_plan"])

    def test_safe_feature_operator_fast_path_keeps_route_plan_when_visible(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()
        original_build_route_plan = chat_module.build_workflow_route_plan

        with patch.object(chat_module, "build_workflow_route_plan", wraps=original_build_route_plan) as build_route_plan:
            decision = chat_module.route_chat_message("how can I safely add a feature to this repo?", source="discord")

        self.assertEqual(decision["selected_skill"], "ralplan")
        self.assertIsNotNone(decision["workflow_route_plan"])
        self.assertEqual(build_route_plan.call_count, 1)

    def test_generic_catalog_fast_paths_skip_full_recommendation_scan(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()
        cases = (
            "what workflows are available?",
            "what skills are available?",
            "show workflows",
            "omh 뭐 할 수 있어?",
            "omh에서 쓸 수 있는 워크플로 알려줘",
            "omh에서 쓸 수 있는 기능 알려줘",
            "omh 스킬 뭐있어?",
            "스킬들은 뭐있어?",
        )

        with patch.object(
            chat_module,
            "recommend_skills",
            side_effect=AssertionError("catalog fast path should skip scoring"),
        ):
            for message in cases:
                with self.subTest(message=message):
                    decision = chat_module.route_chat_message(message, source="discord")

                    self.assertEqual(decision["selected_skill"], "oh-my-hermes")
                    self.assertEqual(decision["action"], "dispatch")
                    self.assertEqual(decision["confidence"], "high")
                    self.assertEqual(decision["recommendations"][0]["matched"], ["catalog_question"])
                    self.assertEqual(decision["recommendations"][0]["next_action"], "choose_skill")

    def test_guarded_operator_fast_paths_skip_full_recommendation_scan(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()
        cases = (
            ("setup 잘 됐어?", "doctor", "guard:doctor_health"),
            ("update 잘 됐어?", "doctor", "guard:doctor_health"),
            ("codex 연결돼 있어?", "executor-runtime-readiness", "guard:executor_runtime_readiness"),
            ("내 코딩 에이전트 연결 상태 확인해줘", "executor-runtime-readiness", "guard:executor_runtime_readiness"),
            ("codex 작업 어디까지 됐어?", "ultraprocess", "guard:coding_progress_status"),
            ("코덱스가 지금 뭐하고있는지 알려줘", "ultraprocess", "guard:coding_progress_status"),
            ("codex 세션이 살아있는지 확인해줘", "ultraprocess", "guard:coding_progress_status"),
            ("이미지 생성 툴 연결 안됐으면 뭐 써?", "toolbelt-readiness", "guard:toolbelt_readiness"),
            ("메모리 점검해줘", "memory-sync", "guard:memory_curation"),
            ("내 기억에 뭐 저장돼있는지 검토해줘", "memory-sync", "guard:memory_curation"),
            ("업데이트 됐는지 확인해줘", "doctor", "guard:doctor_health"),
            ("설치가 제대로 됐는지 확인해줘", "doctor", "guard:doctor_health"),
            ("setup 다시 해야 하는지 알려줘", "doctor", "guard:doctor_health"),
        )

        with patch.object(
            chat_module,
            "recommend_skills",
            side_effect=AssertionError("guarded operator fast paths should skip scoring"),
        ), patch.object(
            chat_module,
            "build_workflow_route_plan",
            side_effect=AssertionError("guarded operator fast paths should not build route plans"),
        ):
            for message, expected_skill, expected_marker in cases:
                chat_module._route_chat_message_cached.cache_clear()
                with self.subTest(message=message):
                    decision = chat_module.route_chat_message(message, source="discord")

                    self.assertEqual(decision["selected_skill"], expected_skill)
                    self.assertEqual(decision["action"], "dispatch")
                    self.assertEqual(decision["confidence"], "high")
                    self.assertIn(expected_marker, decision["recommendations"][0]["matched"])
                    self.assertTrue(
                        any(
                            str(marker).startswith("guard_fast_path:")
                            for marker in decision["recommendations"][0]["matched"]
                        )
                    )

    def test_agent_ops_status_fast_paths_skip_full_recommendation_scan(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()
        cases = (
            "현재 작업상황 보고해줘",
            "지금 진행중인 작업 알려줘",
            "이번 작업 끝났는지 확인해줘",
            "현재 PR 리뷰 통과했어?",
            "PR 머지됐는지 확인해줘",
            "CI 통과했어?",
            "이 기능 배포 준비됐어?",
            "메뉴바 모니터 다시 켜줘",
            "상단바 OMH 아이콘 안 보여",
            "작업상황 보고해줘",
            "what are you working on?",
        )

        with patch.object(
            chat_module,
            "recommend_skills",
            side_effect=AssertionError("agent-ops status fast path should skip scoring"),
        ), patch.object(
            chat_module,
            "build_workflow_route_plan",
            side_effect=AssertionError("agent-ops status fast path should not build route plans"),
        ):
            for message in cases:
                chat_module._route_chat_message_cached.cache_clear()
                with self.subTest(message=message):
                    decision = chat_module.route_chat_message(message, source="discord")

                    self.assertEqual(decision["selected_skill"], "agent-ops-review")
                    self.assertEqual(decision["action"], "dispatch")
                    self.assertEqual(decision["confidence"], "high")
                    self.assertEqual(decision["recommendations"][0]["matched"][0], "agent_ops_status_fast_path")
                    self.assertIsNone(decision["workflow_route_plan"])

    def test_natural_single_workflow_operator_fast_paths_skip_full_recommendation_scan(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()
        cases = (
            ("이미지 요약 카드 만들어줘", "img-summary", "operator_surface_fast_path:visual"),
            ("릴리즈 노트 이미지 만들어줘", "img-summary", "operator_surface_fast_path:visual"),
            ("이 PDF 쉽게 요약해줘", "paper-learning", "operator_surface_fast_path:paper"),
            ("이 PDF 논문 초보자도 이해하게 풀어줘", "paper-learning", "operator_surface_fast_path:paper"),
            ("첨부한 paper를 쉬운 난이도로 설명해줘", "paper-learning", "operator_surface_fast_path:paper"),
            ("paper pdf expert explanation please", "paper-learning", "operator_surface_fast_path:paper"),
            ("회의록 정리해줘", "operating-rhythm", "operator_surface_fast_path:operating"),
            ("논문 링크 찾아줘", "source-finder", "operator_surface_fast_path:source"),
            ("paper pdf를 찾아서 쉽게 설명해줘", "source-finder", "operator_surface_fast_path:source"),
            ("자료 찾아줘", "web-research", "operator_surface_fast_path:research"),
            ("성능 최적화해줘", "performance-goal", "operator_surface_fast_path:performance"),
            ("omh update 했는데 잘 된건지 모르겠어", "doctor", "operator_surface_fast_path:doctor"),
            ("PR 열렸는데 CI 실패했어 정리해줘", "github-event-ops", "operator_surface_fast_path:github_event"),
            (
                "Hermes가 내 기억을 잘못 기억하는 것 같아",
                "memory-sync",
                "operator_surface_fast_path:memory",
            ),
            ("merge할때도 프리렌 author로 머지해", "ultraprocess", "operator_surface_fast_path:delivery"),
            ("hermes agent가 한개가 아니라 여러개일땐 어떻게 동작해?", "agent-board", "operator_surface_fast_path:agent_board"),
            ("슬랙에서 /omh 치면 뭐가 떠야해?", "oh-my-hermes", "native_entrypoint_question"),
            ("./ 쳤는데 omh가 안 떠", "oh-my-hermes", "native_entrypoint_question"),
            ("Hermes가 omh list 승인하라고 하는데 굳이 쳐야해?", "oh-my-hermes", "catalog_question"),
            ("what OMH workflows are available without running omh list?", "oh-my-hermes", "catalog_question"),
            ("리드미 개선해줘", "ultraprocess", "operator_surface_fast_path:delivery"),
            ("workflow trace 보고 다음에 스킬 고칠점 알려줘", "workflow-learning", "workflow_learning_fast_path"),
            (
                "agent run stuck repeating the same command and burning tokens",
                "agent-debug",
                "operator_surface_fast_path:agent_debug",
            ),
            (
                "project-scoped instincts with promotion review",
                "instinct-ledger",
                "operator_surface_fast_path:instinct_ledger",
            ),
        )

        with patch.object(
            chat_module,
            "recommend_skills",
            side_effect=AssertionError("natural single-workflow fast paths should skip scoring"),
        ), patch.object(
            chat_module,
            "build_workflow_route_plan",
            side_effect=AssertionError("natural single-workflow fast paths should not build route plans"),
        ):
            for message, expected_skill, expected_marker in cases:
                chat_module._route_chat_message_cached.cache_clear()
                with self.subTest(message=message):
                    decision = chat_module.route_chat_message(message, source="discord")

                    self.assertEqual(decision["selected_skill"], expected_skill)
                    self.assertEqual(decision["action"], "dispatch")
                    self.assertEqual(decision["confidence"], "high")
                    self.assertIn(expected_marker, decision["recommendations"][0]["matched"])

    def test_specific_capability_catalog_fast_paths_skip_full_recommendation_scan(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()
        cases = (
            ("what can OMH do for papers?", "paper-learning"),
            ("what can OMH do for source finding?", "source-finder"),
            ("what can OMH do for workflow learning?", "workflow-learning"),
            ("what can OMH do for project instincts?", "instinct-ledger"),
            ("what can OMH do for agent debugging?", "agent-debug"),
            ("what can OMH do for Discord gateway routing?", "gateway-intent-card"),
            ("what can OMH do for coding agents?", "executor-runtime-readiness"),
            ("what can OMH do for image generation?", "img-summary"),
        )

        with patch.object(
            chat_module,
            "recommend_skills",
            side_effect=AssertionError("specific catalog fast path should skip scoring"),
        ):
            for message, expected_skill in cases:
                with self.subTest(message=message):
                    decision = chat_module.route_chat_message(message, source="discord")

                    self.assertEqual(decision["selected_skill"], expected_skill)
                    self.assertEqual(decision["action"], "dispatch")
                    self.assertEqual(decision["confidence"], "high")
                    self.assertIn("catalog_question", decision["recommendations"][0]["matched"])
                    self.assertTrue(
                        any(
                            str(item).startswith(("alias:", "name:"))
                            for item in decision["recommendations"][0]["matched"]
                        )
                    )

    def test_public_chat_route_payload_cache_is_reused_without_payload_poisoning(self) -> None:
        chat_module._route_chat_message_cached.cache_clear()
        chat_module._public_chat_route_payload_cached.cache_clear()

        first = chat_module.public_chat_route_payload(
            "risky refactor with implementation and review",
            source="discord",
        )
        first["selected_skill"] = "mutated"
        first["recommendations"][0]["skill"] = "mutated"
        first["recommendations"][0]["matched"].append("mutated")
        first["route_explanation"]["selected_workflow"] = "mutated"
        first["route_explanation"]["not_evidence_yet"].append("mutated")
        first["workflow_route_plan"]["steps"][0]["skill"] = "mutated"

        second = chat_module.public_chat_route_payload(
            "risky refactor with implementation and review",
            source="discord",
        )
        cache_info = chat_module._public_chat_route_payload_cached.cache_info()

        self.assertNotEqual(second["selected_skill"], "mutated")
        self.assertNotEqual(second["recommendations"][0]["skill"], "mutated")
        self.assertNotIn("mutated", second["recommendations"][0]["matched"])
        self.assertNotEqual(second["route_explanation"]["selected_workflow"], "mutated")
        self.assertNotIn("mutated", second["route_explanation"]["not_evidence_yet"])
        self.assertNotEqual(second["workflow_route_plan"]["steps"][0]["skill"], "mutated")
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
        contract_module._build_chat_interaction_payload_cached.cache_clear()

        first = contract_module.build_chat_interaction_payload(
            "risky refactor with implementation and review",
            source="discord",
            source_metadata={"source_event_id": "evt-1"},
        )
        second = contract_module.build_chat_interaction_payload(
            "risky refactor with implementation and review",
            source="discord",
            source_metadata={"source_event_id": "evt-1"},
        )
        cache_info = chat_module._public_chat_route_payload_cached.cache_info()

        self.assertEqual(first["route"]["selected_skill"], second["route"]["selected_skill"])
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_chat_interaction_cache_is_reused_without_payload_poisoning(self) -> None:
        contract_module._build_chat_interaction_payload_cached.cache_clear()

        first = contract_module.build_chat_interaction_payload(
            "risky refactor with implementation and review",
            source="discord",
        )
        first["route"]["selected_skill"] = "mutated"
        first["chat_response"]["state"]["workflow_explanation"]["why_this_workflow"] = "mutated"
        first["chat_response"]["actions"][0]["label"] = "mutated"

        second = contract_module.build_chat_interaction_payload(
            "risky refactor with implementation and review",
            source="discord",
        )
        cache_info = contract_module._build_chat_interaction_payload_cached.cache_info()

        self.assertNotEqual(second["route"]["selected_skill"], "mutated")
        self.assertNotEqual(second["chat_response"]["state"]["workflow_explanation"]["why_this_workflow"], "mutated")
        self.assertNotEqual(second["chat_response"]["actions"][0]["label"], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_chat_interaction_catalog_cache_is_reused_without_large_payload_poisoning(self) -> None:
        contract_module._build_chat_interaction_payload_cached.cache_clear()

        first = contract_module.build_chat_interaction_payload(
            "what OMH workflows are available?",
            source="discord",
        )
        state = first["chat_response"]["state"]
        state["skill_picker"]["options"][0]["payload"]["skill"] = "mutated"
        state["skill_picker"]["groups"][0]["options"][0]["id"] = "mutated"
        state["context_primer"]["workflow_context_cards"][0]["user_examples"][0] = "mutated"
        state["capability_summary"]["lanes"][0]["representative_playbooks"][0]["first_stage"]["id"] = "mutated"
        first["chat_response"]["actions"][0]["payload"]["options"][0]["payload"]["skill"] = "mutated"
        first["chat_response"]["messenger_rendering"]["body_blocks"][0]["text"] = "mutated"

        second = contract_module.build_chat_interaction_payload(
            "what OMH workflows are available?",
            source="discord",
        )
        second_state = second["chat_response"]["state"]
        cache_info = contract_module._build_chat_interaction_payload_cached.cache_info()

        self.assertNotEqual(second_state["skill_picker"]["options"][0]["payload"]["skill"], "mutated")
        self.assertNotEqual(second_state["skill_picker"]["groups"][0]["options"][0]["id"], "mutated")
        self.assertNotEqual(second_state["context_primer"]["workflow_context_cards"][0]["user_examples"][0], "mutated")
        self.assertNotEqual(
            second_state["capability_summary"]["lanes"][0]["representative_playbooks"][0]["first_stage"]["id"],
            "mutated",
        )
        self.assertNotEqual(second["chat_response"]["actions"][0]["payload"]["options"][0]["payload"]["skill"], "mutated")
        self.assertNotEqual(second["chat_response"]["messenger_rendering"]["body_blocks"][0]["text"], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_chat_interaction_cache_skips_event_metadata_calls(self) -> None:
        contract_module._build_chat_interaction_payload_cached.cache_clear()

        payload = contract_module.build_chat_interaction_payload(
            "risky refactor with implementation and review",
            source="discord",
            source_metadata={"source_event_id": "evt-123", "channel_ref": "chan-1"},
        )
        cache_info = contract_module._build_chat_interaction_payload_cached.cache_info()

        self.assertIn("evt-123", payload["thread_key"])
        self.assertEqual(cache_info.misses, 0)
        self.assertEqual(cache_info.hits, 0)

    def test_wrapper_intent_classifiers_cache_repeated_messages(self) -> None:
        classifier_cases = (
            (contract_module._is_omh_intro_question, "What is OMH and how should I use it?"),
            (contract_module._is_omh_quickstart_question, "OMH setup is done, what next?"),
            (contract_module._is_omh_status_question, "show OMH status"),
            (contract_module._is_command_preview_invocation, "./om"),
        )

        for classifier, message in classifier_cases:
            with self.subTest(classifier=classifier.__name__):
                classifier.cache_clear()

                first = classifier(message)
                second = classifier(message)
                cache_info = classifier.cache_info()

                self.assertTrue(first)
                self.assertEqual(first, second)
                self.assertEqual(cache_info.misses, 1)
                self.assertGreaterEqual(cache_info.hits, 1)

    def test_omh_status_probe_cache_reuses_probe_without_payload_poisoning(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            contract_module._omh_status_probe_cached.cache_clear()

            first = contract_module.build_chat_response_from_omh_status_roadmap(paths)
            first["state"]["probe_summary"]["plugin_distribution_ready"] = "mutated"
            second = contract_module.build_chat_response_from_omh_status_roadmap(paths)
            cache_info = contract_module._omh_status_probe_cached.cache_info()

            self.assertFalse(second["state"]["probe_summary"]["plugin_distribution_ready"])
            self.assertEqual(cache_info.misses, 1)
            self.assertGreaterEqual(cache_info.hits, 1)

            paths.hermes_home.mkdir(parents=True, exist_ok=True)
            paths.hermes_config_path.write_text("skills:\n  external_dirs: []\n", encoding="utf-8")
            contract_module.build_chat_response_from_omh_status_roadmap(paths)
            refreshed_cache_info = contract_module._omh_status_probe_cached.cache_info()

            self.assertEqual(refreshed_cache_info.misses, 2)

            session_dir = paths.runtime_wrapper_sessions_dir / "session-1"
            session_dir.mkdir(parents=True, exist_ok=True)
            session_path = session_dir / "session.json"
            session_path.write_text('{"session_id":"session-1"}\n', encoding="utf-8")
            before = contract_module._omh_status_probe_fingerprint(paths)
            session_path.write_text('{"session_id":"session-1","status":"updated"}\n', encoding="utf-8")
            after = contract_module._omh_status_probe_fingerprint(paths)

            self.assertNotEqual(before, after)

            run_dir = paths.runtime_runs_dir / "run-1"
            run_dir.mkdir(parents=True, exist_ok=True)
            contract_module._glob_fingerprint_paths_cached.cache_clear()
            self.assertEqual(contract_module._glob_fingerprints(paths.runtime_runs_dir, "*/wrapper.json"), ())
            wrapper_path = run_dir / "wrapper.json"
            wrapper_path.write_text('{"schema_version":"wrapper_observation/v1"}\n', encoding="utf-8")

            self.assertIn(
                contract_module._path_fingerprint(wrapper_path),
                contract_module._glob_fingerprints(paths.runtime_runs_dir, "*/wrapper.json"),
            )

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

    def test_executor_label_map_cache_is_reused(self) -> None:
        executors_module._executor_label_map.cache_clear()

        first = executors_module.executor_label("codex")
        second = executors_module.executor_label("codex")
        cache_info = executors_module._executor_label_map.cache_info()

        self.assertEqual(first, "Codex")
        self.assertEqual(first, second)
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_executor_readiness_contract_cache_is_reused_without_payload_poisoning(self) -> None:
        executor_readiness_module._executor_readiness_contract_cached.cache_clear()

        first = executor_readiness_module.executor_readiness_contract("codex")
        first["probe"]["args"][0] = "mutated"
        first["probe"]["captures"][0] = "mutated"
        first["fallback_policy"]["suggested_actions"][0] = "mutated"
        first["not_evidence"][0] = "mutated"

        second = executor_readiness_module.executor_readiness_contract("codex")
        cache_info = executor_readiness_module._executor_readiness_contract_cached.cache_info()

        self.assertIsNot(first, second)
        self.assertEqual(second["probe"]["args"], ["--version"])
        self.assertEqual(second["probe"]["captures"][0], "available")
        self.assertEqual(second["fallback_policy"]["suggested_actions"][0], "choose_executor")
        self.assertEqual(second["not_evidence"][0], "executor dispatch")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_executor_readiness_selection_cache_is_reused_without_profile_poisoning(self) -> None:
        executor_readiness_module._executor_readiness_contract_cached.cache_clear()

        first = executor_readiness_module.executor_readiness_for_selection(None, choice_required=True)
        first["profiles"][0]["profile"] = "mutated"
        first["profiles"][0]["probe"]["command"] = "mutated"

        second = executor_readiness_module.executor_readiness_for_selection(None, choice_required=True)
        cache_info = executor_readiness_module._executor_readiness_contract_cached.cache_info()

        self.assertIsNot(first, second)
        self.assertEqual(second["status"], "choice_required")
        self.assertEqual(second["profiles"][0]["profile"], "codex")
        self.assertEqual(second["profiles"][0]["probe"]["command"], "codex")
        self.assertGreaterEqual(cache_info.misses, 1)
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

        message = "risky refactor with implementation and review"
        recommendations = recommend_module.recommend_skills(message, limit=10)
        first = route_plan_module.build_workflow_route_plan(
            message,
            recommendations,
            selected_skill="ralplan",
            action="dispatch",
        )
        self.assertIsNotNone(first)
        assert first is not None
        first["steps"][0]["skill"] = "mutated"
        first["steps"][0]["matched"].append("mutated")

        second = route_plan_module.build_workflow_route_plan(
            message,
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

    def test_workflow_route_plan_signature_reads_recommendation_dicts(self) -> None:
        recommendations = (
            {"skill": "ralplan", "score": 10, "confidence": "high", "matched": ["risk", "plan"]},
            "ignored",
            {"skill": "", "score": 9, "confidence": "high", "matched": ["ignored"]},
            {"skill": "code-review", "score": 7, "confidence": "medium", "matched": ("review",)},
        )

        self.assertEqual(
            route_plan_module._recommendation_signature(recommendations),
            (
                ("ralplan", 10, "high", ("risk", "plan")),
                ("code-review", 7, "medium", ()),
            ),
        )

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

    def test_capability_family_projection_cache_is_reused_without_payload_poisoning(self) -> None:
        families_module._capability_family_projection_cached.cache_clear()

        first = families_module.capability_family_projection()
        first["families"][0]["id"] = "mutated"
        first["families"][0]["primary_workflows"][0] = "mutated"
        workflow_key = next(iter(first["workflow_to_family"]))
        first["workflow_to_family"][workflow_key] = "mutated"
        first["family_order"][0] = "mutated"

        second = families_module.capability_family_projection()
        cache_info = families_module._capability_family_projection_cached.cache_info()

        self.assertIsNot(first, second)
        self.assertNotEqual(second["families"][0]["id"], "mutated")
        self.assertNotEqual(second["families"][0]["primary_workflows"][0], "mutated")
        self.assertNotEqual(second["workflow_to_family"][workflow_key], "mutated")
        self.assertNotEqual(second["family_order"][0], "mutated")
        self.assertEqual(cache_info.misses, 1)
        self.assertGreaterEqual(cache_info.hits, 1)

    def test_capability_family_cards_cache_is_reused_without_payload_poisoning(self) -> None:
        families_module._capability_family_projection_cached.cache_clear()

        first = families_module.capability_family_cards()
        first[0]["primary_workflows"][0] = "mutated"
        second = families_module.capability_family_cards()
        cache_info = families_module._capability_family_projection_cached.cache_info()

        self.assertIsNot(first, second)
        self.assertNotEqual(second[0]["primary_workflows"][0], "mutated")
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
