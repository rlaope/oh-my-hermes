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
            "프리렌이 OMH 안 쓰고 일반 도구로 이미지 만들었어",
            "The Hermes agent did not use OMH for this summary image.",
        )

        for message in cases:
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")

                self.assertEqual(decision["action"], "dispatch")
                self.assertEqual(decision["selected_skill"], "img-summary")
                self.assertEqual(decision["selected_harness"], "img-summary")
                self.assertEqual(decision["confidence"], "high")

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
