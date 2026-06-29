from __future__ import annotations

import json
import unittest
from unittest import mock

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
from omh.routing import chat as chat_router_impl
from omh.routing.localization import normalized_phrase
from omh.plugin_bundle.omh.awareness import awareness_route_hint
from omh.skills.catalog import primary_harness_for_skill, routable_definitions


def sionic_omh_usage_evaluation_prompt() -> str:
    return """이번 Sionic 작업에서 OMH가 얼마나 관여했는지 사용성 평가하고,
왜 OMH를 덜 썼는지 분석해서 라우터 강화 플랜으로 잡아줘.
Sionic은 마크다운 노트뿐 아니라 위키 페이지/site 생성도 포함했어.
결과창에는 Background process proc_d5eb61ddcf80 finished with exit code 0~
Here's the final output: 같은 raw output, turn.completed usage, Self-improvement review 줄이 보였고
이걸 프리티하게 OMH wrapper report로 정리해야 했어.

[OMH Awareness]
status=prepared_not_observed; Evidence boundary: pasted status is diagnostic evidence.
[OMH Route Hint]
intent=delivery_intent; selected=ultraprocess; confidence=medium.
mentioned_workflows=ultraprocess.
not_executed=Codex.
[omh]
selected_workflow=ultraprocess
latest_runtime_run=not_executed=Codex
execution_observed=false
review_observed=false
ci_observed=false
merge_observed=false
"""


class ChatRouterTests(unittest.TestCase):
    def test_high_confidence_chat_dispatches_to_workflow(self) -> None:
        decision = route_chat_message("risky refactor", source="discord")

        self.assertEqual(decision["action"], "dispatch")
        self.assertEqual(decision["selected_skill"], "ralplan")
        self.assertEqual(decision["selected_harness"], "planning")
        self.assertEqual(decision["confidence"], "high")
        self.assertIn("User message:\nrisky refactor", decision["routing_prompt"])

    def test_safe_feature_chat_routes_to_reviewed_plan_across_common_phrasings(self) -> None:
        cases = (
            ("safely add a feature", None),
            ("add a feature safely", None),
            ("안전하게 기능 추가하고 싶어", "locale:ko:safe_feature"),
            ("새 기능 안전하게 넣고 싶어", "locale:ko:safe_feature"),
            ("Quiero agregar una función de forma segura a este repo", "locale:es:safe_feature"),
            ("Je veux ajouter une fonctionnalité en toute sécurité à ce repo", "locale:fr:safe_feature"),
            ("Ich möchte sicher eine Funktion hinzufügen", "locale:de:safe_feature"),
        )

        for message, locale_match in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "ralplan")
                self.assertEqual(decision["selected_harness"], "planning")
                self.assertIn("guard:safe_feature_change", decision["recommendations"][0]["matched"])
                if locale_match is not None:
                    self.assertIn(locale_match, decision["recommendations"][0]["matched"])

    def test_chat_route_hints_align_with_operator_status_and_planning_phrases(self) -> None:
        cases = (
            (
                "what is the coding handoff status?",
                "ultraprocess",
                "show_coding_handoff_status",
                None,
            ),
            (
                "코딩 작업 지금 어디까지 됐어?",
                "ultraprocess",
                "show_coding_handoff_status",
                None,
            ),
            (
                "이미지 생성 요청에서 OMH 안 썼어. 다음엔 img-summary 쓰게 기록해줘",
                "workflow-learning",
                "record_missed_route",
                None,
            ),
            (
                "웹서치해서 최신 자료 정리해줘",
                "web-research",
                "gather_source_backed_evidence",
                None,
            ),
            (
                "I want to safely add a feature to this repo",
                "ralplan",
                "present_plan",
                None,
            ),
            (
                "위험한 리팩터링 같아",
                "ralplan",
                "present_plan",
                None,
            ),
            (
                "이 이슈 PR로 만들 수 있게 정리해줘",
                "ralplan",
                "present_plan",
                None,
            ),
            (
                "./loop star-worthy OSS 만들기",
                "loop",
                "assess_loopability",
                None,
            ),
            (
                "Use OMH ultraprocess for: improve README and open PR",
                "ultraprocess",
                "prepare_one_cycle_delivery",
                None,
            ),
        )

        for message, selected_skill, hint_action, task_type in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")
                hint = awareness_route_hint(message)

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], selected_skill)
                self.assertEqual(hint["status"], "hinted")
                self.assertEqual(hint["primary_workflow"], selected_skill)
                self.assertEqual(hint["primary_next_action"], hint_action)
                if task_type is None:
                    self.assertIsNone(decision["task_card"])
                else:
                    self.assertEqual(decision["task_card"]["task_type"], task_type)

    def test_coding_handoff_status_is_not_router_design_feedback(self) -> None:
        decision = route_chat_message("what is the coding handoff status?", source="discord")

        self.assertEqual(decision["selected_skill"], "ultraprocess")
        self.assertIsNone(decision["task_card"])
        self.assertNotIn("task_card:router_design_feedback", decision["recommendations"][0]["matched"])

        meta_feedback = route_chat_message("Codex handoff라는 용어를 쓰면 라우팅이 오해되는 것 같아.", source="discord")
        self.assertEqual(meta_feedback["selected_skill"], "workflow-learning")
        self.assertEqual(meta_feedback["task_card"]["task_type"], "router_design_feedback")

    def test_multilingual_chat_routes_content_workflows_without_external_translation(self) -> None:
        cases = (
            ("haz una imagen que explique la función cron", "img-summary", "locale:es:visual_summary"),
            ("erstelle ein Bild, das die Cron-Funktion erklärt", "img-summary", "locale:de:visual_summary"),
            ("cron機能を説明する画像を作って", "img-summary", "locale:ja:visual_summary"),
            ("生成一张解释 cron 功能的图片", "img-summary", "locale:zh:visual_summary"),
            ("explícame este paper en un nivel fácil", "paper-learning", "locale:es:paper_learning"),
            ("explique ce PDF de recherche simplement", "paper-learning", "locale:fr:paper_learning"),
            ("erkläre dieses Paper einfach", "paper-learning", "locale:de:paper_learning"),
            ("この論文PDFをやさしく説明して", "paper-learning", "locale:ja:paper_learning"),
            ("encuentra el paper y el dataset para este tema", "source-finder", "locale:es:source_finder"),
            ("trouve le dépôt GitHub et le PDF public", "source-finder", "locale:fr:source_finder"),
            ("finde paper und dataset zu diesem thema", "source-finder", "locale:de:source_finder"),
            ("このテーマの論文PDFとデータセットを探して", "source-finder", "locale:ja:source_finder"),
            ("帮我找这个主题的论文PDF和数据集", "source-finder", "locale:zh:source_finder"),
            ("convierte este PDF en una presentación", "materials-package", "trigger:pdf"),
            ("transforme ce PDF en présentation", "materials-package", "trigger:pdf"),
            ("mach daraus eine PDF und Excel Datei", "materials-package", "trigger:pdf"),
        )

        for message, skill, locale_match in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], skill)
                self.assertEqual(decision["selected_harness"], primary_harness_for_skill(skill))
                self.assertEqual(decision["recommendations"][0]["skill"], skill)
                self.assertEqual(decision["confidence"], "high")
                self.assertIn(locale_match, decision["recommendations"][0]["matched"])

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

    def test_direct_picker_alias_uses_fast_catalog_route(self) -> None:
        for message in ("./omh", "/omh", "./skills", "/skills"):
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "oh-my-hermes")
                self.assertEqual(decision["candidate_skill"], "oh-my-hermes")
                self.assertTrue(decision["explicit"])
                self.assertEqual(decision["recommendations"][0]["skill"], "oh-my-hermes")
                self.assertEqual(decision["recommendations"][0]["next_action"], "choose_skill")
                self.assertEqual(decision["recommendations"][0]["matched"], ["direct_picker_alias"])
                public = public_route_payload(decision)
                self.assertEqual(public["route_explanation"]["next_action"], "choose_skill")

    def test_generic_omh_catalog_question_uses_fast_catalog_route(self) -> None:
        for message in (
            "what OMH workflows are available?",
            "what workflows can OMH do?",
            "show me the OMH commands",
            "show me OMH workflows",
        ):
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "oh-my-hermes")
                self.assertFalse(decision["explicit"])
                self.assertEqual(decision["recommendations"][0]["skill"], "oh-my-hermes")
                self.assertEqual(decision["recommendations"][0]["next_action"], "choose_skill")
                self.assertEqual(decision["recommendations"][0]["matched"], ["catalog_question"])

    def test_explicit_skill_invocation_wins_over_router_feedback_card(self) -> None:
        for message, skill in (
            ("$deep-interview before planning Discord and Slack routing, ask what each channel owns.", "deep-interview"),
            ("$code-review review this PR for install/update UX regressions and missing tests.", "code-review"),
        ):
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], skill)
                self.assertEqual(decision["selected_harness"], primary_harness_for_skill(skill))
                self.assertTrue(decision["explicit"])
                self.assertIsNone(decision["task_card"])
                self.assertEqual(decision["reason"], "Explicit workflow invocation wins over heuristic routing.")

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
                "Can OMH run a release reliability review before launch?",
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
            (
                "Can OMH make an automation blueprint for a daily research digest?",
                "automation-blueprint",
                "scheduled-ops-blueprint",
            ),
        )

        for message, skill, harness in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], skill)
                self.assertEqual(decision["selected_harness"], harness)
                self.assertEqual(decision["confidence"], "high")

    def test_operator_surface_good_examples_route_without_skill_names(self) -> None:
        cases = (
            (
                "can this task run in Codex, Claude Code, or Hermes coding?",
                "executor-runtime-readiness",
            ),
            (
                "내 코딩 에이전트 연결 상태 한번만 확인하고 안되면 물어봐",
                "executor-runtime-readiness",
            ),
            (
                "FAL_KEY 없어서 이미지 생성이 막히면 어떻게 연결해야 해?",
                "toolbelt-readiness",
            ),
            (
                "Obsidian 말고 markdown folder에 리서치 결과 저장하고 싶어",
                "research-department",
            ),
            (
                "coordinate PM, CTO, QA, and release agents on this launch checklist.",
                "agent-board",
            ),
            (
                "release before lunch, check risky parts from mobile.",
                "voice-operator",
            ),
            (
                "turn this research into PPT and PDF with attachment status.",
                "deliverable-package",
            ),
            (
                "summarize this PDF deck into action items",
                "materials-package",
            ),
            (
                "after omh update says setup is next but Hermes skills still look stale.",
                "doctor",
            ),
            (
                "Track the Codex work session and tell me what changed.",
                "ultraprocess",
            ),
            (
                "finish the invoice export recovery until the smoke test passes or a blocker is recorded.",
                "ralph",
            ),
            (
                "compare three onboarding analytics vendors using customer notes and confidence gaps.",
                "research-brief",
            ),
            (
                "Help me decide what to build next from these customer notes.",
                "feedback-triage",
            ),
            (
                "The app keeps crashing after login.",
                "feedback-triage",
            ),
            (
                "Users say checkout is broken.",
                "feedback-triage",
            ),
            (
                "This issue should become a PR.",
                "github-event-ops",
            ),
            (
                "What did the coding agent do while I was away?",
                "ultraprocess",
            ),
            (
                "PR 42 has failing CI, summarize the risk and next fix path.",
                "github-event-ops",
            ),
            (
                "このPRをレビューしやすい計画にして",
                "github-event-ops",
            ),
            (
                "Quiero preparar este issue para un PR",
                "github-event-ops",
            ),
            (
                "The Claude Code session looks stuck; what is it doing and what should I do next?",
                "ultraprocess",
            ),
            (
                "Voice note: release risky. check fast and ask before action.",
                "voice-operator",
            ),
            (
                "omh setup says done but Hermes cannot see the skills.",
                "doctor",
            ),
            (
                "CI is red after my latest push, help me triage the failure.",
                "github-event-ops",
            ),
            (
                "A reviewer left comments on my PR; summarize what to fix first.",
                "github-event-ops",
            ),
            (
                "Customers keep asking for refunds after checkout timeouts.",
                "feedback-triage",
            ),
            (
                "The dashboard 500s after login; make a repro plan before coding.",
                "feedback-triage",
            ),
            (
                "Use Codex to implement the accepted plan and keep me posted.",
                "ultraprocess",
            ),
            (
                "Claude Code says done; what evidence is still missing?",
                "ultraprocess",
            ),
            (
                "The coding agent says tests passed and PR is open; what is still missing?",
                "ultraprocess",
            ),
            (
                "What is the latest status of the Codex handoff?",
                "ultraprocess",
            ),
            (
                "I installed it but omh is not found in a new terminal.",
                "doctor",
            ),
            (
                "Hermes skills list does not show OMH after setup.",
                "doctor",
            ),
            (
                "Every morning collect AI agent news, synthesize it, and brief me.",
                "research-department",
            ),
            (
                "Every Monday remind the team to review stale issues.",
                "automation-blueprint",
            ),
            (
                "A Telegram user sent an attachment; decide delivery and thread policy.",
                "gateway-intent-card",
            ),
            (
                "Slack message has a file attachment and should update the thread quietly.",
                "gateway-intent-card",
            ),
            (
                "Make this OSS star-worthy by repeatedly reducing first-run friction.",
                "loop",
            ),
            (
                "Make a 100k star open source project from this repo.",
                "loop",
            ),
            (
                "Let Hermes itself code this with workers and worktrees.",
                "team",
            ),
            (
                "decide whether our onboarding should prioritize solo founders or enterprise buyers.",
                "strategy-brief",
            ),
            (
                "turn this onboarding idea into a scoped plan, implementation handoff, QA gate, and release path.",
                "idea-to-deploy",
            ),
            (
                "run the PM, dev, QA, security, and ops loop for this risky billing launch.",
                "cto-loop",
            ),
            (
                "test the setup wizard with hostile install paths, stale config, and missing PATH cases.",
                "ultraqa",
            ),
            (
                "remove duplicated router branches and lock behavior with regression tests before refactoring.",
                "ai-slop-cleaner",
            ),
            (
                "keep researching AI agent memory practices until the evidence gaps are closed or logged.",
                "autoresearch-goal",
            ),
        )

        for message, skill in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], skill)
                self.assertEqual(decision["selected_harness"], primary_harness_for_skill(skill))
                self.assertEqual(decision["recommendations"][0]["skill"], skill)
                self.assertEqual(decision["confidence"], "high")

    def test_route_quality_pass_handles_real_chat_misroutes(self) -> None:
        cases = (
            (
                "I need a 10k-star OSS loop to improve first-run experience",
                "loop",
                "guard:loop_goal",
            ),
            (
                "what did the codex session do so far?",
                "ultraprocess",
                "guard:coding_progress_status",
            ),
            (
                "coding-agent status for the codex handoff",
                "ultraprocess",
                "guard:coding_handoff_status",
            ),
            (
                "record stale memories and ask me what to keep",
                "memory-curation-review",
                "guard:memory_curation",
            ),
            (
                "run a deep interview before planning",
                "deep-interview",
                "guard:deep_interview",
            ),
            (
                "show me quality, blockers, and throughput for AI-agent work",
                "agent-ops-review",
                "trigger:throughput",
            ),
            (
                "what's going on?",
                "agent-ops-review",
                "trigger:" + normalized_phrase("what's going on"),
            ),
            (
                "what are you working on?",
                "agent-ops-review",
                f"trigger:{normalized_phrase('what are you working on')}",
            ),
            (
                "I want to understand this paper PDF",
                "paper-learning",
                "guard:paper_learning",
            ),
            (
                "논문 PDF 이해하고 싶어",
                "paper-learning",
                "guard:paper_learning",
            ),
            (
                "open this in codex",
                "executor-runtime-readiness",
                "guard:executor_runtime_readiness",
            ),
            (
                "attach existing codex session",
                "executor-runtime-readiness",
                "guard:executor_runtime_readiness",
            ),
            (
                "claude code로 이어서 작업해줘",
                "executor-runtime-readiness",
                "guard:executor_runtime_readiness",
            ),
            (
                "setup이 잘 됐는지 봐줘",
                "doctor",
                "guard:doctor_health",
            ),
            (
                "설치 잘 됐어?",
                "doctor",
                "guard:doctor_health",
            ),
            (
                "update 했는데 잘 된거야?",
                "doctor",
                "guard:doctor_health",
            ),
            (
                "setup에서 위아래키 누르면 느려",
                "doctor",
                "guard:doctor_health",
            ),
            (
                "今何してる？",
                "agent-ops-review",
                f"trigger:{normalized_phrase('今何してる')}",
            ),
            (
                "现在在做什么？",
                "agent-ops-review",
                f"trigger:{normalized_phrase('现在在做什么')}",
            ),
            (
                "qué está pasando?",
                "agent-ops-review",
                f"trigger:{normalized_phrase('qué está pasando')}",
            ),
            (
                "qu'est-ce qui se passe?",
                "agent-ops-review",
                "trigger:" + normalized_phrase("qu'est-ce qui se passe"),
            ),
            (
                "was ist los?",
                "agent-ops-review",
                f"trigger:{normalized_phrase('was ist los')}",
            ),
            (
                "무슨일이노",
                "agent-ops-review",
                f"trigger:{normalized_phrase('무슨일이노')}",
            ),
            (
                "지금 뭐 하고 있어?",
                "agent-ops-review",
                f"trigger:{normalized_phrase('지금 뭐 하고 있어')}",
            ),
            (
                "I want Hermes to learn from this workflow and improve the skill next time",
                "workflow-learning",
                "guard:workflow_learning",
            ),
            (
                "FAL_KEY 없어서 이미지 생성이 막히면 어떻게 연결해야 해?",
                "toolbelt-readiness",
                "guard:toolbelt_readiness",
            ),
            (
                "내 코딩 에이전트 연결 상태 한번만 확인하고 안되면 물어봐",
                "executor-runtime-readiness",
                "guard:executor_runtime_readiness",
            ),
            (
                "claude code 연결돼 있어?",
                "executor-runtime-readiness",
                "guard:executor_runtime_readiness",
            ),
            (
                "I want to use codex as my coding agent",
                "executor-runtime-readiness",
                "guard:executor_runtime_readiness",
            ),
            (
                "is Codex installed?",
                "executor-runtime-readiness",
                "guard:executor_runtime_readiness",
            ),
            (
                "코딩 에이전트 codex로 바꾸고 싶어",
                "executor-runtime-readiness",
                "guard:executor_runtime_readiness",
            ),
            (
                "codex 깔려있어?",
                "executor-runtime-readiness",
                "guard:executor_runtime_readiness",
            ),
            (
                "how do I see the current Codex session?",
                "ultraprocess",
                "guard:coding_progress_status",
            ),
            (
                "Obsidian 말고 markdown folder에 리서치 결과 저장하고 싶어",
                "research-department",
                "guard:research_department",
            ),
        )

        for message, skill, marker in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], skill)
                self.assertIn(marker, decision["recommendations"][0]["matched"])

    def test_visual_summary_chat_dispatches_to_img_summary(self) -> None:
        cases = (
            "이미지 요약 카드 만들어줘",
            "이 내용을 공유용 요약 카드로 만들어줘",
            "회의록을 공유용 카드로 만들어줘",
            "회의록을 보기 좋은 세로 이미지로 요약해줘",
            "회의록을 사람들한테 공유할 세로 이미지로 만들어줘",
            "PR 요약 포스터 만들어줘",
            "PR 내용을 리뷰어에게 공유할 이미지 카드로 만들어줘",
            "Create an image summary card from these notes.",
            "make a poster explaining cron automation",
            "make an image explaining the cron feature",
            "크론 기능 설명 사진 하나 만들어줘",
            "PR 요약을 이미지가 아니라 사진처럼 만들어줘",
            "create a picture card from these meeting notes",
            "make a visual one-pager for this release",
            "作成して、PRの要約画像",
            "生成一张发布说明海报",
            "make a workflow learning image card",
            "Can you generate an image with GPT from this meeting summary?",
            "사진 생성해줘",
            "사진 만들어줘",
        )

        for message in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "img-summary")
                self.assertEqual(decision["selected_harness"], "img-summary")
                self.assertEqual(decision["confidence"], "high")

    def test_catalog_questions_cover_installed_workflow_language(self) -> None:
        cases = (
            "what workflows are installed?",
            "which skills are installed?",
            "what installed commands does OMH have?",
            "설치된 스킬 뭐 있어?",
            "깔린 워크플로우 알려줘",
        )

        for message in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "oh-my-hermes")
                self.assertEqual(decision["confidence"], "high")
                self.assertIn("Catalog question", decision["reason"])

    def test_specific_capability_questions_route_to_the_named_workflow_card(self) -> None:
        cases = (
            (
                "what can OMH do for workflow learning?",
                "workflow-learning",
                "workflow-learning",
            ),
            (
                "what can OMH do for Discord gateway routing?",
                "gateway-intent-card",
                "gateway-intent-card",
            ),
            (
                "route this Telegram message into a workflow card",
                "gateway-intent-card",
                "gateway-intent-card",
            ),
            (
                "what coding agents can OMH use?",
                "executor-runtime-readiness",
                "executor-runtime-readiness",
            ),
            (
                "what can OMH do for research department?",
                "research-department",
                "research-department",
            ),
            (
                "what can OMH do for research brief?",
                "research-brief",
                "business-research",
            ),
            (
                "what can OMH do for GitHub event ops?",
                "github-event-ops",
                "github-event-ops",
            ),
            (
                "what can OMH do for coding agents?",
                "executor-runtime-readiness",
                "executor-runtime-readiness",
            ),
            (
                "what can OMH do for reliability review?",
                "reliability-review",
                "reliability-review",
            ),
            (
                "what can OMH do for deploy and monitor?",
                "deploy-and-monitor",
                "app-delivery-loop",
            ),
            (
                "what can OMH do for CTO loop?",
                "cto-loop",
                "app-delivery-loop",
            ),
        )

        for message, skill, harness in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], skill)
                self.assertEqual(decision["selected_harness"], harness)
                self.assertEqual(decision["confidence"], "high")

    def test_exact_skill_id_capability_questions_use_catalog_metadata(self) -> None:
        excluded = {"oh-my-hermes", "ask", "cancel", "plan", "skill", "team"}
        skills = tuple(definition.name for definition in routable_definitions() if definition.name not in excluded)
        self.assertGreaterEqual(len(skills), 40)

        for skill in skills:
            for phrase in (skill, skill.replace("-", " ")):
                with self.subTest(phrase=phrase):
                    decision = route_chat_message(f"what can OMH do for {phrase}?", source="discord")

                    self.assertEqual(decision["action"], "dispatch")
                    self.assertEqual(decision["selected_skill"], skill)
                    self.assertEqual(decision["selected_harness"], primary_harness_for_skill(skill))

    def test_exact_skill_id_capability_questions_use_fast_path_without_full_scoring(self) -> None:
        chat_router_impl._route_chat_message_cached.cache_clear()
        chat_router_impl._public_chat_route_payload_cached.cache_clear()

        with mock.patch.object(
            chat_router_impl,
            "recommend_skills",
            side_effect=AssertionError("exact workflow-id capability questions should use the catalog fast path"),
        ), mock.patch.object(
            chat_router_impl,
            "build_workflow_route_plan",
            side_effect=AssertionError("exact workflow-id capability questions should render a card, not a route plan"),
        ):
            decision = route_chat_message("what can OMH do for paper-learning?", source="discord")

        self.assertEqual(decision["action"], "dispatch")
        self.assertEqual(decision["selected_skill"], "paper-learning")
        self.assertEqual(decision["selected_harness"], "paper-learning")
        self.assertEqual(decision["confidence"], "high")
        self.assertEqual(decision["recommendations"][0]["next_action"], "prepare_paper_learning")
        self.assertEqual(
            decision["recommendations"][0]["matched"],
            ["catalog_question", "name:paper-learning"],
        )
        self.assertIn("exact OMH capability", decision["recommendations"][0]["why"])
        self.assertNotIn("workflow_route_plan", public_route_payload(decision))

    def test_generic_short_operator_skill_names_do_not_hijack_catalog_picker(self) -> None:
        for phrase in ("plan", "team", "ask"):
            with self.subTest(phrase=phrase):
                decision = route_chat_message(f"what can OMH do for {phrase}?", source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "oh-my-hermes")
                self.assertIn("Catalog question", decision["reason"])

    def test_specific_capability_phrase_patterns_are_compiled_once(self) -> None:
        chat_router_impl._specific_capability_phrase_map.cache_clear()
        try:
            with mock.patch.object(
                chat_router_impl,
                "_compile_specific_capability_phrase",
                wraps=chat_router_impl._compile_specific_capability_phrase,
            ) as compile_phrase:
                self.assertEqual(
                    chat_router_impl._specific_capability_named_hits("what can OMH do for CTO loop?"),
                    ("cto-loop",),
                )
                first_call_count = compile_phrase.call_count
                self.assertGreater(first_call_count, 40)

                self.assertEqual(
                    chat_router_impl._specific_capability_named_hits("what can OMH do for deploy and monitor?"),
                    ("deploy-and-monitor",),
                )
                self.assertEqual(compile_phrase.call_count, first_call_count)
        finally:
            chat_router_impl._specific_capability_phrase_map.cache_clear()

    def test_paper_learning_routes_paper_explanation_without_stealing_related_lanes(self) -> None:
        explanation_cases = (
            "이 논문 PDF 아주 쉽게 설명해줘",
            "이 PDF 쉽게 설명해줘",
            "Explain this arXiv paper at expert level without dropping details",
            "explain this PDF at an easy level",
            "what can OMH do for papers?",
            "what can OMH do for PDF papers?",
            "./paper-explainer explain the attached paper at moderate difficulty",
            "Can OMH help me summarize a paper PDF?",
            "Can OMH help with paper summaries?",
            "¿Puede OMH ayudar con un resumen de paper PDF?",
            "OMHで論文PDFを説明できる？",
            "OMH可以解释论文PDF吗？",
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

        short_ppt_export = route_chat_message("PPT 만들어줘", source="discord")
        self.assertEqual(short_ppt_export["selected_skill"], "materials-package")
        self.assertEqual(short_ppt_export["selected_harness"], "materials-package")

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
            "find paper pdf links and dataset links for this topic",
            "what can OMH do for source finding?",
            "what can OMH do for datasets?",
            "what can OMH do for GitHub repos?",
            "./source-finder find docs and specs for browser automation standards",
            "paper pdf link 찾아줘",
            "논문 pdf 링크 찾아줘",
            "dataset 링크 찾아줘",
            "공개 데이터셋 찾아줘",
            "논문 데이터셋 찾아서 후보로 정리해줘",
            "공개 프레젠테이션 자료를 찾아서 요약해줘",
            "github oss repo 찾아서 비교해줘",
            "이 주제 관련 소스 후보 찾아줘",
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
            "프리렌이 OMH 기능을 안 썼어",
            "이번 요청에서 왜 OMH를 안 썼는지 학습해줘",
            "이미지 생성 요청에서 OMH 안 썼어. workflow-learning으로 기록해줘",
            "OMH 안 썼어",
            "missed route: Hermes skipped OMH for my image request",
            "Can OMH help me improve a workflow that went wrong?",
        )

        for message in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "workflow-learning")
                self.assertEqual(decision["selected_harness"], "workflow-learning")
                self.assertEqual(decision["confidence"], "high")
                self.assertIn("guard:workflow_learning", decision["recommendations"][0]["matched"])

    def test_missed_omh_feedback_recovers_to_domain_workflow_when_not_learning_request(self) -> None:
        cases = (
            ("Hermes가 OMH 안 쓰고 그냥 이미지 만들었어", "img-summary", "img-summary"),
            ("이미지 생성 요청을 했는데 OMH를 안 썼어", "img-summary", "img-summary"),
            ("리서치 요청했는데 OMH를 안 썼어", "web-research", "research"),
            ("회의록 요약을 부탁했는데 OMH 안 쓰고 일반 답변했어", "operating-rhythm", "operating-rhythm"),
        )

        for message, skill, harness in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], skill)
                self.assertEqual(decision["selected_harness"], harness)
                self.assertEqual(decision["confidence"], "high")

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
        self.assertNotEqual(decision["selected_skill"], "doctor")
        self.assertNotIn("guard:doctor_health", decision["recommendations"][0]["matched"])

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

    def test_explicit_learn_request_prepares_skill_candidate_card(self) -> None:
        decision = route_chat_message(
            "learn this: when opening PRs, run git diff --check before gh pr create",
            source="discord",
        )
        card = decision["learning_candidate_card"]
        prompt = card["learn_prompt"]["copy_text"]

        self.assertEqual(decision["action"], "dispatch")
        self.assertEqual(decision["selected_skill"], "workflow-learning")
        self.assertEqual(card["schema_version"], "learning_candidate_card/v1")
        self.assertEqual(card["status"], "prepared_not_observed")
        self.assertEqual(card["persistence_target"], "skill_candidate")
        self.assertEqual(card["primary_action"], "copy_learn_prompt")
        self.assertIn("/learn", prompt)
        self.assertIn("Use observed facts only", prompt)
        self.assertIn("reusable Hermes skill", prompt)
        self.assertIn("Trigger conditions", prompt)
        self.assertIn("Exact steps", prompt)
        self.assertIn("Pitfalls", prompt)
        self.assertIn("Verification commands", prompt)
        self.assertIn("When not to use", prompt)
        self.assertIn("prepared_not_observed", card["claim_boundary"])
        self.assertIn("skill creation", card["not_observed"])
        self.assertIn("memory write", card["not_observed"])

    def test_user_correction_becomes_memory_candidate_not_skill_prompt(self) -> None:
        decision = route_chat_message("다음부터 이렇게 답해줘: 짧게 한국어로 요약해", source="discord")
        card = decision["learning_candidate_card"]

        self.assertEqual(decision["action"], "dispatch")
        self.assertEqual(decision["selected_skill"], "memory-curation-review")
        self.assertEqual(card["persistence_target"], "memory_candidate")
        self.assertEqual(card["primary_action"], "prepare_memory_curation_review")
        self.assertEqual(card["review"]["review_workflow"], "memory-curation-review")
        self.assertNotIn("learn_prompt", card)
        self.assertIn("Durable user preference", card["summary"])

    def test_learning_classification_separates_memory_skill_and_session_state(self) -> None:
        skill = route_chat_message(
            "이 패턴 기억해: after CI fails, run gh pr checks --watch before pushing fixes",
            source="discord",
        )["learning_candidate_card"]
        memory = route_chat_message(
            "from now on prefer concise Korean final summaries",
            source="discord",
        )["learning_candidate_card"]
        session = route_chat_message("learn this: PR #123 is blocked on CI", source="discord")["learning_candidate_card"]

        self.assertEqual(skill["persistence_target"], "skill_candidate")
        self.assertIn("learn_prompt", skill)
        self.assertEqual(memory["persistence_target"], "memory_candidate")
        self.assertNotIn("learn_prompt", memory)
        self.assertEqual(session["persistence_target"], "session_only")
        self.assertNotIn("learn_prompt", session)

    def test_learning_channel_term_collision_routes_to_review_first(self) -> None:
        decision = route_chat_message(
            "in channel #ops, learn this pattern from PR #123 for the other thread",
            source="discord",
        )
        card = decision["learning_candidate_card"]
        serialized = json.dumps(card)

        self.assertEqual(decision["selected_skill"], "memory-curation-review")
        self.assertEqual(card["persistence_target"], "review_first")
        self.assertEqual(card["primary_action"], "prepare_memory_curation_review")
        self.assertIn("channel_or_thread_ref", card["sanitization"]["transient_identifier_categories"])
        self.assertIn("pull_request_number", card["sanitization"]["transient_identifier_categories"])
        self.assertNotIn("#ops", serialized)
        self.assertNotIn("#123", serialized)

    def test_learning_candidate_excludes_transient_pr_state_from_summary_and_prompt(self) -> None:
        message = (
            "make a skill from this: for PR #123 on commit abcdef123456 and run_abc123def456 "
            "with pid 9876, run git diff --check before gh pr create"
        )

        card = route_chat_message(message, source="discord")["learning_candidate_card"]
        serialized = json.dumps(card)

        self.assertEqual(card["persistence_target"], "skill_candidate")
        self.assertIn("pull_request_number", card["sanitization"]["transient_identifier_categories"])
        self.assertIn("commit_sha", card["sanitization"]["transient_identifier_categories"])
        self.assertIn("run_id", card["sanitization"]["transient_identifier_categories"])
        self.assertIn("process_id", card["sanitization"]["transient_identifier_categories"])
        self.assertNotIn("#123", serialized)
        self.assertNotIn("abcdef123456", serialized)
        self.assertNotIn("run_abc123def456", serialized)
        self.assertNotIn("9876", serialized)
        self.assertIn("git diff --check", card["learn_prompt"]["copy_text"])

    def test_skill_forcing_transient_only_request_stays_session_only(self) -> None:
        card = route_chat_message("make a skill from this: PR #123 is blocked on CI", source="discord")[
            "learning_candidate_card"
        ]
        serialized = json.dumps(card)

        self.assertEqual(card["persistence_target"], "session_only")
        self.assertEqual(card["primary_action"], "show_learning_candidate")
        self.assertNotIn("learn_prompt", card)
        self.assertNotIn("#123", serialized)
        self.assertIn("do not persist transient task", card["summary"])

    def test_pasted_omh_awareness_evaluation_routes_learning_before_delivery(self) -> None:
        message = sionic_omh_usage_evaluation_prompt()

        decision = route_chat_message(message, source="discord", limit=8)
        task_card = decision["task_card"]
        intent = classify_workflow_intent(message)
        route_plan = public_route_payload(decision)["workflow_route_plan"]
        stages = [step["stage"] for step in route_plan["steps"]]
        skills = [step["skill"] for step in route_plan["steps"]]

        self.assertEqual(decision["action"], "dispatch")
        self.assertEqual(decision["selected_skill"], "workflow-learning")
        self.assertEqual(decision["selected_harness"], "workflow-learning")
        self.assertEqual(task_card["task_type"], "router_design_feedback")
        self.assertIn("task_card:router_design_feedback", decision["recommendations"][0]["matched"])
        self.assertIn(intent.intent_class, {"feedback_signal", "meta_discussion"})
        self.assertFalse(intent.explicit_execution)
        self.assertIn("diagnostic_status_context", intent.structural_cues)
        self.assertIn("ultraprocess", intent.not_executed)
        self.assertIn("Codex", intent.not_executed)
        self.assertIn("learn", stages)
        self.assertIn("deliver", stages)
        self.assertLess(stages.index("learn"), stages.index("deliver"))
        self.assertLess(skills.index("workflow-learning"), skills.index("ultraprocess"))
        self.assertTrue(all(step["status"] == "prepared_not_observed" for step in route_plan["steps"]))

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

        domain = route_chat_message("고객 관여도 분석해서 Sionic 위키 페이지 개선해줘.", source="discord")
        self.assertNotEqual(domain["selected_skill"], "workflow-learning")
        self.assertIsNone(domain["task_card"])

    def test_domain_work_with_pasted_status_does_not_become_omh_quality_loop(self) -> None:
        message = """Sionic 위키 페이지 사용성 평가하고 더 보기 좋게 만들어줘.

[omh] v1.0.1 | plugin:ready | target:single | coding-agent:runtime(codex)
[OMH] Native bridge status context.
Evidence boundary: prepared handoffs are not execution evidence.
Latest runtime run: 20260625T090917585910Z-loop-goal-loop-8b5bec.
"""

        decision = route_chat_message(message, source="discord")
        intent = classify_workflow_intent(message)

        self.assertNotEqual(decision["selected_skill"], "workflow-learning")
        self.assertNotEqual(decision["selected_skill"], "agent-ops-review")
        self.assertIsNone(decision["task_card"])
        self.assertNotIn("task_card:router_design_feedback", decision["recommendations"][0]["matched"])
        self.assertNotIn(intent.intent_class, {"feedback_signal", "meta_discussion"})

    def test_status_context_before_user_instruction_is_not_discarded(self) -> None:
        message = """[omh] v1.0.1 | plugin:ready | target:single | coding-agent:runtime(codex)
[OMH] Native bridge status context.
Evidence boundary: prepared handoffs are not execution evidence.
Latest runtime run: 20260625T090917585910Z-loop-goal-loop-8b5bec.

Sionic 작업 말고 OMH 라우터 강화 플랜으로 잡아줘.
"""

        decision = route_chat_message(message, source="discord")
        intent = classify_workflow_intent(message)

        self.assertEqual(decision["selected_skill"], "workflow-learning")
        self.assertEqual(decision["task_card"]["task_type"], "router_design_feedback")
        self.assertIn(intent.intent_class, {"feedback_signal", "meta_discussion"})

        same_line = route_chat_message("[OMH] 라우터 강화 플랜으로 잡아줘", source="discord")
        self.assertEqual(same_line["selected_skill"], "workflow-learning")
        self.assertEqual(same_line["task_card"]["task_type"], "router_design_feedback")

    def test_bounded_omh_usage_review_cues_survive_without_domain_stealing(self) -> None:
        status = """
[OMH Awareness]
status=prepared_not_observed; Evidence boundary: pasted status is diagnostic evidence.
selected_workflow=ultraprocess
"""
        prefixes = (
            "이번 작업에서 OMH를 덜 쓴 이유를 분석해줘.",
            "이번 작업에서 OMH를 덜 썼는지 분석해줘.",
            "이번 작업에서 OMH 관여도 분석해줘.",
            "이번 작업에서 OMH가 부족했던 점을 분석해줘.",
            "status=prepared_not_observed; 이번 작업에서 OMH를 덜 쓴 이유를 분석해줘.",
        )
        for prefix in prefixes:
            with self.subTest(prefix=prefix):
                decision = route_chat_message(prefix + status, source="discord")
                self.assertEqual(decision["selected_skill"], "workflow-learning")
                self.assertEqual(decision["task_card"]["task_type"], "router_design_feedback")

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
            "README 파일 찾아줘",
            "README 보여줘",
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
                explanation = public_payload["route_explanation"]
                self.assertEqual(explanation["headline"], "Answer as a file or text lookup.")
                self.assertIn("Answer directly as a file or text lookup", explanation["summary"])
                self.assertIn("I will answer this as a file or text lookup", explanation["recommended_reply"])
                self.assertNotIn("target is clear", explanation["recommended_reply"])
                self.assertIn("file inspection", explanation["claim_boundary"])
                self.assertIn("file inspection", explanation["not_evidence_yet"])
                self.assertNotIn("review", explanation["not_evidence_yet"])

    def test_korean_file_lookup_does_not_steal_readme_edit_requests(self) -> None:
        lookup = route_chat_message("README 파일 찾아줘", source="discord")
        edit = route_chat_message("README 제목 수정해줘", source="discord")

        self.assertEqual(lookup["action"], "fallback")
        self.assertEqual(lookup["selected_skill"], "oh-my-hermes")
        self.assertIn("File or text lookup", lookup["reason"])
        self.assertNotEqual(edit["reason"], lookup["reason"])
        self.assertNotEqual(edit["action"], "fallback")

    def test_web_search_chat_dispatches_to_research_harness(self) -> None:
        cases = (
            "웹서치해서 최신 자료와 출처 정리해줘",
            "search the web for current sources and citations",
            "Search the web for current best practices on Python packaging.",
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

        generic_status = route_chat_message("What is the current status?", source="discord")
        self.assertNotEqual(generic_status["selected_skill"], "web-research")

    def test_delivery_cycle_chat_beats_research_department_for_pr_requests(self) -> None:
        cases = (
            "daily research plan implement and open a PR",
            "every morning competitor research then prepare a PR",
            "codex로 이 기능 구현 맡겨줘",
            "이 이슈를 Codex로 구현하게 맡기고 진행상태 추적해줘",
            "$ultraprocess로 이 repo 변경을 PR-ready까지 준비해줘",
            "Can OMH do one full research plan implementation review cycle?",
        )

        for message in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "ultraprocess")
                self.assertEqual(decision["selected_harness"], "goal-execution")
                self.assertEqual(decision["confidence"], "high")

    def test_direct_small_coding_tasks_route_to_one_cycle_delivery(self) -> None:
        cases = (
            "fix the login bug",
            "implement dark mode toggle",
            "add a settings button",
            "change the button color to blue",
            "make the navbar sticky",
            "update the README title",
            "rename this variable",
            "버튼 색 파란색으로 바꿔줘",
            "로그인 버그 고쳐줘",
            "다크모드 토글 추가해줘",
            "README 제목 수정해줘",
        )

        for message in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "ultraprocess")
                self.assertEqual(decision["selected_harness"], "goal-execution")
                self.assertEqual(decision["confidence"], "high")
                self.assertIn("guard:direct_coding_task", decision["recommendations"][0]["matched"])

    def test_direct_coding_guard_preserves_non_coding_and_review_routes(self) -> None:
        cases = (
            ("결제 실패 이슈가 자주 나와", "feedback-triage"),
            ("릴리즈 전에 README claim이 실제 코드와 맞는가 봐줘", "code-review"),
            ("회의록 요약 이미지 카드 만들어줘", "img-summary"),
        )

        for message, selected_skill in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["selected_skill"], selected_skill)
                self.assertNotIn("guard:direct_coding_task", decision["recommendations"][0]["matched"])

    def test_multi_workflow_route_plan_exposes_research_plan_delivery_review_order(self) -> None:
        decision = route_chat_message(
            "Research current install friction, make a reviewed plan, implement with Codex, "
            "run code review, and sync docs for a PR.",
            source="discord",
            limit=8,
        )
        public_payload = public_route_payload(decision)
        route_plan = public_payload["workflow_route_plan"]

        self.assertEqual(decision["action"], "dispatch")
        self.assertEqual(decision["selected_skill"], "ultraprocess")
        self.assertEqual(route_plan["schema_version"], "workflow_route_plan/v1")
        self.assertEqual(route_plan["mode"], "multi_workflow")
        self.assertEqual(
            [(step["stage"], step["skill"]) for step in route_plan["steps"]],
            [
                ("research", "web-research"),
                ("plan", "ralplan"),
                ("deliver", "ultraprocess"),
                ("review", "code-review"),
            ],
        )
        self.assertIn("routing guidance only", route_plan["claim_boundary"])
        self.assertTrue(all(step["status"] == "prepared_not_observed" for step in route_plan["steps"]))

    def test_product_bug_route_plan_triages_before_coding_and_review(self) -> None:
        decision = route_chat_message(
            "결제 실패 이슈가 자주 나와. 재현 계획 세우고 codex로 고쳐서 리뷰까지 추적해줘",
            source="discord",
            limit=8,
        )
        route_plan = public_route_payload(decision)["workflow_route_plan"]

        self.assertEqual(decision["selected_skill"], "feedback-triage")
        self.assertEqual(
            [(step["stage"], step["skill"]) for step in route_plan["steps"]],
            [
                ("triage", "feedback-triage"),
                ("plan", "plan"),
                ("deliver", "ultraprocess"),
                ("review", "code-review"),
            ],
        )
        self.assertIn("not a roadmap decision", route_plan["steps"][0]["evidence_boundary"])
        self.assertIn("not dispatch", route_plan["steps"][2]["evidence_boundary"])

    def test_risky_refactor_route_plan_keeps_ralplan_before_delivery(self) -> None:
        capability_question = route_chat_message("What OMH workflow should I use for a risky refactor?", source="discord")

        self.assertEqual(capability_question["action"], "dispatch")
        self.assertEqual(capability_question["selected_skill"], "ralplan")
        self.assertEqual(capability_question["selected_harness"], "planning")

        decision = route_chat_message(
            "위험한 리팩터링 같아. 코드베이스 조사하고 계획 세운 뒤 구현 리뷰 문서 PR까지",
            source="discord",
            limit=8,
        )
        route_plan = public_route_payload(decision)["workflow_route_plan"]

        self.assertEqual(decision["selected_skill"], "ralplan")
        self.assertEqual(
            [(step["stage"], step["skill"]) for step in route_plan["steps"]],
            [
                ("research", "web-research"),
                ("plan", "ralplan"),
                ("deliver", "ultraprocess"),
                ("review", "code-review"),
            ],
        )
        self.assertLess(
            [step["skill"] for step in route_plan["steps"]].index("ralplan"),
            [step["skill"] for step in route_plan["steps"]].index("ultraprocess"),
        )

    def test_memory_context_chat_dispatches_to_curation_review(self) -> None:
        for message in (
            "Hermes가 기억하는 맥락을 점검하고 정리해줘",
            "메모리 업데이트 할 거 있는지 검사해줘",
            "현재 hermes가 기억하는 맥락을 점검하고 피드백 받아줘",
        ):
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "memory-curation-review")
                self.assertEqual(decision["selected_harness"], "memory-curation-review")
                self.assertEqual(decision["confidence"], "high")

        cross_channel = route_chat_message(
            "시간이 지나며 메모리 압축되고 다른 채널 용어가 겹쳐서 OMH 맥락 관리가 필요해",
            source="discord",
        )

        self.assertEqual(cross_channel["action"], "dispatch")
        self.assertEqual(cross_channel["selected_skill"], "memory-curation-review")
        self.assertEqual(cross_channel["selected_harness"], "memory-curation-review")
        self.assertEqual(cross_channel["confidence"], "high")

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

    def test_public_route_payload_includes_human_route_explanation(self) -> None:
        message = "FAL_KEY 없어서 이미지 생성이 막히면 어떻게 연결해야 해?"
        decision = route_chat_message(message, source="discord")

        public = public_route_payload(decision)
        explanation = public["route_explanation"]

        self.assertEqual(explanation["schema_version"], "route_explanation/v1")
        self.assertEqual(explanation["selected_workflow"], "toolbelt-readiness")
        self.assertEqual(explanation["selected_harness"], "toolbelt-readiness")
        self.assertEqual(explanation["action"], "dispatch")
        self.assertEqual(explanation["next_action"], "prepare_toolbelt_readiness")
        self.assertNotIn("Matched guard/trigger metadata", explanation["why_this_workflow"])
        self.assertTrue(str(explanation["why_this_workflow"]).startswith("Missing tool"))
        self.assertIn("not MCP server installation", explanation["claim_boundary"])
        self.assertIn("API access", explanation["claim_boundary"])
        self.assertIn("connector invocation", explanation["not_evidence_yet"])
        self.assertIn("toolbelt-readiness", explanation["recommended_reply"])
        self.assertIn("prepare toolbelt readiness", explanation["recommended_reply"])
        self.assertEqual(explanation["primary_action_label"], "Open toolbelt-readiness")
        self.assertIn("do not claim", explanation["primary_action_hint"])
        self.assertIn("execution", explanation["primary_action_hint"])
        self.assertIn("why / next / not-yet-evidence", explanation["rendering_hint"])
        self.assertNotIn(message, json.dumps(explanation, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
