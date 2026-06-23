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
from omh.routing.intent import classify_workflow_intent
from omh.skills.catalog import primary_harness_for_skill


class ChatRouterTests(unittest.TestCase):
    def test_high_confidence_chat_dispatches_to_workflow(self) -> None:
        decision = route_chat_message("risky refactor", source="discord")

        self.assertEqual(decision["action"], "dispatch")
        self.assertEqual(decision["selected_skill"], "ralplan")
        self.assertEqual(decision["selected_harness"], "planning")
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

    def test_operations_surfaces_dispatch_to_dedicated_harnesses(self) -> None:
        cases = (
            (
                "회의록 히스토리 관리하고 스크럼 스프린트 회고 운영 리듬 정리해줘",
                "operating-rhythm",
                "operating-rhythm",
            ),
            (
                "회의록 요약을 부탁했는데 OMH 안 쓰고 일반 답변했어",
                "operating-rhythm",
                "operating-rhythm",
            ),
            (
                "리서치 요청했는데 OMH를 안 썼어",
                "web-research",
                "research",
            ),
            (
                "create a PPT report package for a monthly leadership status deck",
                "report-package",
                "report-package",
            ),
            (
                "run an incident postmortem SLO error budget service reliability review",
                "reliability-review",
                "reliability-review",
            ),
            (
                "엑셀 매출 리포트를 PDF로 만들고 렌더 QA까지 준비해줘",
                "materials-package",
                "materials-package",
            ),
            (
                "every morning check competitor news and send a Slack digest only if something changed",
                "research-department",
                "research-department",
            ),
        )

        for message, skill, harness in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], skill)
                self.assertEqual(decision["selected_harness"], harness)
                self.assertEqual(decision["confidence"], "high")

    def test_visual_summary_chat_dispatches_to_img_summary(self) -> None:
        cases = (
            "이미지 요약 카드 만들어줘",
            "이 내용을 공유용 요약 카드로 만들어줘",
            "회의록을 공유용 카드로 만들어줘",
            "회의록을 보기 좋은 세로 이미지로 요약해줘",
            "PR 요약 포스터 만들어줘",
            "PR 내용을 리뷰어에게 공유할 이미지 카드로 만들어줘",
            "Create an image summary card from these notes.",
            "make a poster explaining cron automation",
            "make an image explaining the cron feature",
            "create a picture card from these meeting notes",
            "make a visual one-pager for this release",
            "作成して、PRの要約画像",
            "生成一张发布说明海报",
            "make a workflow learning image card",
        )

        for message in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "img-summary")
                self.assertEqual(decision["selected_harness"], "img-summary")
                self.assertEqual(decision["confidence"], "high")

    def test_paper_learning_routes_paper_explanation_without_stealing_related_lanes(self) -> None:
        explanation_cases = (
            "이 논문 PDF 아주 쉽게 설명해줘",
            "Explain this arXiv paper at expert level without dropping details",
            "./paper-explainer explain the attached paper at moderate difficulty",
        )
        for message in explanation_cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "paper-learning")
                self.assertEqual(decision["selected_harness"], "paper-learning")
                self.assertEqual(decision["confidence"], "high")

        recurring = route_chat_message("weekly paper review", source="discord")
        self.assertEqual(recurring["selected_skill"], "research-department")
        self.assertEqual(recurring["selected_harness"], "research-department")

        citation_check = route_chat_message("explain this paper and verify citations", source="discord")
        self.assertEqual(citation_check["selected_skill"], "web-research")
        self.assertEqual(citation_check["selected_harness"], "research")

        file_export = route_chat_message("PDF를 PPT로 바꿔줘", source="discord")
        self.assertEqual(file_export["selected_skill"], "materials-package")
        self.assertEqual(file_export["selected_harness"], "materials-package")

        mixed_export_cases = (
            "explain this paper and make a PPT",
            "explain this paper as a deck",
            "explain this paper PDF and export a PDF",
            "explain this paper and package it as a PDF",
        )
        for message in mixed_export_cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "materials-package")
                self.assertEqual(decision["selected_harness"], "materials-package")

    def test_source_finder_routes_typed_acquisition_without_stealing_related_lanes(self) -> None:
        acquisition_cases = (
            "find papers and datasets for browser agent benchmarks",
            "find GitHub repos, datasets, and public presentations for this idea",
            "./source-finder find docs and specs for browser automation standards",
            "논문 데이터셋 찾아서 후보로 정리해줘",
        )
        for message in acquisition_cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "source-finder")
                self.assertEqual(decision["selected_harness"], "source-finder")
                self.assertEqual(decision["confidence"], "high")

        citation_check = route_chat_message("find current citations for this claim", source="discord")
        self.assertEqual(citation_check["selected_skill"], "web-research")
        self.assertEqual(citation_check["selected_harness"], "research")

        paper_explanation = route_chat_message("explain this paper at expert level", source="discord")
        self.assertEqual(paper_explanation["selected_skill"], "paper-learning")
        self.assertEqual(paper_explanation["selected_harness"], "paper-learning")

        recurring = route_chat_message("weekly paper review", source="discord")
        self.assertEqual(recurring["selected_skill"], "research-department")
        self.assertEqual(recurring["selected_harness"], "research-department")

        file_export = route_chat_message("turn this PDF into a PPT package", source="discord")
        self.assertEqual(file_export["selected_skill"], "materials-package")
        self.assertEqual(file_export["selected_harness"], "materials-package")

        image_card = route_chat_message("make an image summary card from this research", source="discord")
        self.assertEqual(image_card["selected_skill"], "img-summary")
        self.assertEqual(image_card["selected_harness"], "img-summary")

        official_docs = route_chat_message("find official docs for the current OpenAI API version", source="discord")
        self.assertEqual(official_docs["selected_skill"], "best-practice-research")
        self.assertEqual(official_docs["selected_harness"], "research")

        best_practice = route_chat_message("find best practice docs for Python packaging", source="discord")
        self.assertEqual(best_practice["selected_skill"], "best-practice-research")
        self.assertEqual(best_practice["selected_harness"], "research")

    def test_explicit_workflow_learning_feedback_wins_over_domain_terms(self) -> None:
        cases = (
            "Hermes did not use OMH for my image request; record this as workflow learning",
            "이미지 생성 요청에서 OMH 안 썼어. workflow-learning으로 기록해줘",
            "OMH 안 썼어",
            "missed route: Hermes skipped OMH for my image request",
        )

        for message in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "workflow-learning")
                self.assertEqual(decision["selected_harness"], "workflow-learning")
                self.assertEqual(decision["confidence"], "high")
                self.assertIn("guard:workflow_learning", decision["recommendations"][0]["matched"])

    def test_runtime_portability_task_card_sits_above_workflow_route(self) -> None:
        message = (
            "I want to reproduce this Hermes and Friren setup on another MacBook, "
            "back it up to a private GitHub repo, move the Discord gateway, and make sure only one bot answers."
        )

        decision = route_chat_message(message, source="discord")
        task_card = decision["task_card"]

        self.assertEqual(decision["action"], "dispatch")
        self.assertEqual(decision["selected_skill"], "agent-ops-review")
        self.assertEqual(decision["recommendations"][0]["skill"], "agent-ops-review")
        self.assertIn("task_card:runtime_portability", decision["recommendations"][0]["matched"])
        self.assertEqual(task_card["schema_version"], "omh_task_card/v1")
        self.assertEqual(task_card["task_type"], "runtime_portability")
        self.assertEqual(task_card["route_level"], "task_abstraction")
        self.assertEqual(task_card["selected_workflow_rail"], "agent-ops-review")
        self.assertIn("migration", task_card["not_a_workflow"])
        self.assertTrue(
            {
                "inventory",
                "package",
                "credential_policy",
                "distribution",
                "restore",
                "verify",
                "gateway_ownership_transfer",
            }
            <= set(task_card["operation_primitives"])
        )
        self.assertTrue({"secrets", "duplicate_gateway_responders"} <= set(task_card["risk_domains"]))
        workflow_rails = {rail["skill"] for rail in task_card["workflow_rails"]}
        self.assertTrue(
            {
                "agent-ops-review",
                "toolbelt-readiness",
                "gateway-intent-card",
                "workflow-learning",
                "doctor",
            }
            <= workflow_rails
        )
        self.assertEqual(task_card["evidence_boundary"]["prepared"], "task card, inventory plan, package plan, restore checklist")
        self.assertIn("runtime restore on the second machine", task_card["evidence_boundary"]["not_observed"])
        self.assertIn("encrypt before private GitHub upload", task_card["secret_policy"]["recommended_action"])
        self.assertIn("residual risk", task_card["secret_policy"]["if_user_proceeds"])
        self.assertEqual(task_card["gateway_transfer"]["invariant"], "exactly_one_active_responder")
        self.assertIn("one responder", task_card["user_facing_summary"])

    def test_korean_runtime_portability_task_card(self) -> None:
        decision = route_chat_message(
            "다른 맥북에 헤르메스 프리렌 세팅 재현하고 개인 깃허브에 백업하고 "
            "디스코드 게이트웨이 응답자가 하나만 되게 해줘",
            source="discord",
        )

        self.assertEqual(decision["action"], "dispatch")
        self.assertEqual(decision["selected_skill"], "agent-ops-review")
        self.assertEqual(decision["task_card"]["task_type"], "runtime_portability")
        self.assertGreaterEqual(decision["recommendations"][0]["score"], 60)
        self.assertIn("task_card:runtime_portability", decision["recommendations"][0]["matched"])

    def test_plain_backup_or_migration_without_runtime_context_does_not_task_cardify(self) -> None:
        for message in (
            "backup my photos to private GitHub",
            "migrate this setup to another laptop",
        ):
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertIsNone(decision["task_card"])
                self.assertNotIn("task_card:runtime_portability", decision["recommendations"][0]["matched"])

    def test_short_omh_maintenance_commands_use_operator_task_card(self) -> None:
        cases = (
            ("omh update", "update", "oh-my-hermes"),
            ("omh setup", "setup", "oh-my-hermes"),
            ("omh doctor", "doctor", "doctor"),
            ("omh install", "install", "oh-my-hermes"),
            ("omh list", "list", "oh-my-hermes"),
            ("omh 업데이트해줘", "update", "oh-my-hermes"),
            ("omh 닥터 돌려줘", "doctor", "doctor"),
            ("omh 셋업해줘", "setup", "oh-my-hermes"),
            ("./omh update", "update", "oh-my-hermes"),
        )

        for message, command, selected_skill in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")
                task_card = decision["task_card"]

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], selected_skill)
                self.assertEqual(decision["recommendations"][0]["skill"], selected_skill)
                self.assertIn("task_card:omh_cli_maintenance", decision["recommendations"][0]["matched"])
                self.assertIn("operator_maintenance_command", decision["recommendations"][0]["matched"])
                self.assertEqual(task_card["schema_version"], "omh_task_card/v1")
                self.assertEqual(task_card["task_type"], "omh_cli_maintenance")
                self.assertEqual(task_card["route_level"], "operator_maintenance_command")
                self.assertEqual(task_card["command"], command)
                self.assertEqual(task_card["command_argv"], ["omh", command])
                self.assertEqual(task_card["recommended_next_action"], f"run_omh_{command}")
                self.assertIn("code changes require a separate request", task_card["user_facing_summary"])
                self.assertTrue(
                    {
                        "coding_handoff",
                        "router_design_feedback",
                        "runtime_portability",
                        "migration",
                        "workflow_implementation",
                    }
                    <= set(task_card["not_a_workflow"])
                )
                self.assertTrue(
                    {
                        "run_requested_command",
                        "optional_health_check",
                        "report_observed_output",
                        "avoid_repo_mutation",
                    }
                    <= set(task_card["operation_primitives"])
                )
                self.assertTrue(
                    {"stale_context_inheritance", "over_execution", "unrequested_repo_mutation"}
                    <= set(task_card["risk_domains"])
                )
                self.assertIn("Hermes restart or plugin reload", task_card["evidence_boundary"]["not_observed"])

    def test_omh_maintenance_guard_does_not_swallow_code_change_request(self) -> None:
        decision = route_chat_message("fix the omh update router implementation", source="discord")

        self.assertIsNone(decision["task_card"])
        self.assertNotIn("task_card:omh_cli_maintenance", decision["recommendations"][0]["matched"])

        explanation = route_chat_message("omh update 설명해줘", source="discord")
        self.assertIsNone(explanation["task_card"])
        self.assertNotIn("task_card:omh_cli_maintenance", explanation["recommendations"][0]["matched"])

    def test_issue_251_representative_routes_stay_compact_and_correct(self) -> None:
        cases = (
            ("웹서치해서 최신 자료 정리해줘", "web-research", None),
            ("PDF를 PPT로 바꿔줘", "materials-package", None),
            ("이미지 요약 카드 만들어줘", "img-summary", None),
            ("OMH 업데이트해줘", "oh-my-hermes", "omh_cli_maintenance"),
            ("왜 OMH 라우팅 틀렸어?", "workflow-learning", "router_design_feedback"),
            ("다른 맥북에 프리렌 세팅 옮겨줘", "agent-ops-review", "runtime_portability"),
        )

        for message, selected_skill, task_type in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], selected_skill)
                if task_type is None:
                    self.assertIsNone(decision["task_card"])
                else:
                    self.assertEqual(decision["task_card"]["task_type"], task_type)

    def test_router_design_feedback_prefers_workflow_learning_over_feedback_triage(self) -> None:
        cases = (
            "This should be a higher-level task abstraction, not a migration workflow.",
            "Why did OMH route this wrong? Fix the router design.",
            "피드백인데 OMH 라우팅 설계가 잘못됐어.",
            "더 상위레벨에서 마이그레이션이라는 개념을 한 task로 인식해야지.",
            "이번 작업 회고하면서 OMH가 얼마나 관여했는지 봐줘.",
        )

        for message in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")
                task_card = decision["task_card"]

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "workflow-learning")
                self.assertEqual(decision["selected_harness"], "workflow-learning")
                self.assertEqual(task_card["task_type"], "router_design_feedback")
                self.assertEqual(task_card["selected_workflow_rail"], "workflow-learning")
                self.assertNotEqual(decision["selected_skill"], "feedback-triage")
                self.assertIn("task_card:router_design_feedback", decision["recommendations"][0]["matched"])

    def test_workflow_vocabulary_meta_discussion_does_not_select_delivery(self) -> None:
        cases = (
            "왜 ultraprocess 로그가 떠?",
            "ultraprocess 용어를 테스트해보자",
            "Codex handoff라는 용어를 쓰면 라우팅이 오해되는 것 같아.",
            "가상 프로젝트로 OMH 라우팅을 테스트해보자. 아직 요구사항은 없어.",
            "OMH developer note: one-cycle delivery is only vocabulary in this setup test.",
            "OMH developer test: Codex handoff vocabulary, not asking to implement.",
            "OMH route: `$ultraprocess` ≠ ejecutar; Codex handoff token only.",
        )

        for message in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")
                task_card = decision["task_card"]

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "workflow-learning")
                self.assertEqual(decision["selected_harness"], "workflow-learning")
                self.assertEqual(task_card["task_type"], "router_design_feedback")
                self.assertFalse(decision["explicit"])
                self.assertNotEqual(decision["selected_skill"], "ultraprocess")

    def test_workflow_intent_prefers_structural_cues_over_language_tables(self) -> None:
        intent = classify_workflow_intent("OMH route: `$ultraprocess` ≠ ejecutar; Codex handoff token only.")

        self.assertEqual(intent.intent_class, "meta_discussion")
        self.assertFalse(intent.explicit_execution)
        self.assertIn("quoted_known_term", intent.structural_cues)
        self.assertIn("reference_context_token", intent.structural_cues)
        self.assertIn("ultraprocess", intent.not_executed)
        self.assertIn("Codex", intent.not_executed)

        delivery = classify_workflow_intent("$ultraprocess implement this change")
        self.assertEqual(delivery.intent_class, "delivery_intent")
        self.assertTrue(delivery.explicit_execution)

    def test_generic_korean_omh_feedback_does_not_become_router_design_card(self) -> None:
        decision = route_chat_message("피드백인데 OMH 문서가 좋아요.", source="discord")

        self.assertIsNone(decision["task_card"])
        self.assertNotIn("task_card:router_design_feedback", decision["recommendations"][0]["matched"])

    def test_catalog_question_dispatches_to_router_without_shell_approval(self) -> None:
        for message in (
            "OMH로 할 수 있는 workflow가 뭐야?",
            "what can OMH do?",
            "how can OMH help my team?",
            "Can OMH help with planning, research, and coding?",
            "what can OMH do for planning/research/coding?",
            "Can OMH help with planning/research/coding?",
            "OMH로 뭐 할 수 있어?",
            "OMH는 뭘 도와줘?",
            "OMH로 계획/리서치/코딩까지 도와줄 수 있어?",
            "OMH에서 deep-interview/ralplan/loop는 뭐야?",
        ):
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "oh-my-hermes")
                self.assertEqual(decision["selected_harness"], "coding-handling")
                self.assertEqual(decision["confidence"], "high")
                self.assertIn("Catalog question", decision["reason"])

    def test_specific_capability_catalog_questions_dispatch_to_matching_workflow(self) -> None:
        cases = (
            ("does OMH support scheduled automation?", "automation-blueprint"),
            ("can OMH help with MCP setup?", "toolbelt-readiness"),
            ("does OMH support memory cleanup?", "memory-curation-review"),
            ("does OMH support voice commands?", "voice-operator"),
            ("OMH로 GitHub issue webhook 처리 가능해?", "github-event-ops"),
        )

        for message, selected_skill in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], selected_skill)
                self.assertEqual(decision["selected_harness"], primary_harness_for_skill(selected_skill))
                self.assertEqual(decision["recommendations"][0]["skill"], selected_skill)
                self.assertEqual(decision["confidence"], "high")
                self.assertIn("Specific OMH capability question", decision["reason"])

    def test_file_lookup_does_not_dispatch_to_workflow_keyword(self) -> None:
        for message in (
            "search docs/WORKFLOWS.md for loop",
            "show img-summary in README.md",
            "what does OMH do in docs/ARCHITECTURE.md?",
        ):
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "fallback")
                self.assertEqual(decision["selected_skill"], "oh-my-hermes")
                self.assertEqual(decision["selected_harness"], "coding-handling")
                self.assertEqual(decision["confidence"], "low")
                self.assertIn("File or text lookup", decision["reason"])
                self.assertIn("file or text lookup", decision["clarification"])
                self.assertIn("do not dispatch to a workflow keyword", decision["routing_prompt"])

                public_payload = public_route_payload(decision)
                self.assertIn("file or text lookup", public_payload["routing_instruction"])
                self.assertNotIn("ask one concise clarification", public_payload["routing_instruction"])

    def test_web_search_chat_dispatches_to_research_harness(self) -> None:
        cases = (
            "웹서치해서 최신 자료와 출처 정리해줘",
            "search the web for current sources and citations",
            "查一下最新资料和来源",
            "web-research로 Hermes Agent와 Oh My Codex/OpenCode 계열을 비교해서 OMHM 포지셔닝 근거를 찾아줘.",
        )

        for message in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "web-research")
                self.assertEqual(decision["selected_harness"], "research")
                self.assertEqual(decision["confidence"], "high")
                top = decision["recommendations"][0]
                self.assertIn("freshness", str(top["wrapper_guidance"]).lower())
                self.assertIn("retrieval", str(top["evidence_boundary"]).lower())

    def test_delivery_cycle_chat_beats_research_department_for_pr_requests(self) -> None:
        cases = (
            "daily research plan implement and open a PR",
            "every morning competitor research then prepare a PR",
            "codex로 이 기능 구현 맡겨줘",
            "이 이슈를 Codex로 구현하게 맡기고 진행상태 추적해줘",
            "$ultraprocess로 이 repo 변경을 PR-ready까지 준비해줘",
        )

        for message in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "ultraprocess")
                self.assertEqual(decision["selected_harness"], "goal-execution")
                self.assertEqual(decision["confidence"], "high")

    def test_memory_context_chat_dispatches_to_curation_review(self) -> None:
        decision = route_chat_message("Hermes가 기억하는 맥락을 점검하고 정리해줘", source="discord")

        self.assertEqual(decision["action"], "dispatch")
        self.assertEqual(decision["selected_skill"], "memory-curation-review")
        self.assertEqual(decision["selected_harness"], "memory-curation-review")
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
