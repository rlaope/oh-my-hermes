"""A plain knowledge question gets no skill candidate line; a work request keeps its hint."""

from __future__ import annotations

import unittest

from omh.plugin_bundle.omh.awareness import awareness_route_hint
from omh.plugin_bundle.omh.plain_question_cues import plain_question
from omh.plugin_bundle.omh.skill_shortlist import skill_candidates_for_turn

PLAIN = (
    "Explain TCP vs UDP briefly",
    "Explain what a closure is in JavaScript",
    "Explain Big O notation simply",
    "Explain the CAP theorem",
    "Can you explain what a hash map is?",
    "What's the difference between git merge and rebase?",
    "Explain the difference between let and const",
    "Best way to learn SQL?",
    "Explain what a JWT is",
    "Quick question: what is a webhook?",
    "빅오 표기법 쉽게 설명해줘",
    "TCP랑 UDP 차이 간단히 설명해줘",
    "깃 머지랑 리베이스 차이",
    "SQL 배우는 제일 좋은 방법?",
    "클로저가 뭐야?",
)

WORK = (
    "Explain this paper at beginner level",
    "explain this arxiv paper without dropping details",
    "Explain the attached PDF",
    "Explain why my CI fails after the merge",
    "Explain this stack trace from our server",
    "merge this PR after review",
    "review my PR #12",
    "What's the difference between these two files in my repo?",
    "Explain the code in src/main.py",
    "이 논문 쉽게 설명해줘",
    "첨부한 논문을 초보자 수준으로 설명해줘",
    "우리 레포 PR 머지해줘",
    "이 코드 설명해줘",
    "Explain TCP. Then explain UDP.",
    "Explain TCP\nand UDP",
    "Explain the difference between TCP and UDP and how each one handles loss, ordering, retransmission, "
    "flow control, windowing, and congestion control",
    "Explain what a closure is https://example.com/closure",
    "Explain this:\n```py\nx = 1\n```",
    "Explain `git rebase`",
    "TCP랑 UDP 차이를 아주 자세하게 처음부터 끝까지 빠짐없이 설명해줘 제발",
    "",
    # Raw shape: a newline anywhere, a Windows path, a URL or fence the routing projection masks.
    "\nExplain TCP vs UDP briefly",
    "Explain TCP vs UDP briefly\n",
    "Explain C:\\repo\\README",
    "Explain TCP https://example.com",
    "Explain ```TCP```",
    # Work and status questions: an opener that is not a concept cue, a work owner, OMH vocabulary.
    "Do a competitive pricing analysis of Figma versus Sketch",
    "Can you do market sizing for dental clinics in Korea?",
    "Why was my saved response preference not used?",
    "Explain the OMH capability catalog",
    "Explain the OMH memory system",
    "How does OMH store local state?",
    "explain OMH model routing",
    "what can OMH do for github-event-ops?",
    "how would an attacker get from the public API to the customer database",
    "Is it safe to switch memory provider from mem9 to remnic?",
    "Is the OMH route hint vocabulary and set of trigger words documented?",
    "explain how to set up my models",
    "what should I learn next to solve my current blocker?",
    "why does the jev check in doctor say key missing",
    "which consumers break if I remove this field from the OpenAPI spec",
    "do we hire, outsource, or cut scope for this quarters demand",
    "best-practice-research",
    "why did that agent run cost so many tokens",
    "do a behavior-preserving refactor of the billing module without changing its outputs",
    "how is the skill portfolio health looking, any skill failure patterns",
    "what should the commit message say for this refactor",
    "explain analyze shows a sequential scan on the users table, which index should I add",
    "is this dependency's license OK for us",
    "which dashboards depend on this dbt model",
    "should we use rlvr or dpo for the math model",
    "can we split the api, ui and docs work into parallel lanes?",
    "how does workflow learning work in omh and why did it pick doctor",
    "how long does it take to become a doctor",
    "arxiv 링크 찾아서 쉽게 설명해줘",
    "어디까지 됐어?",
    "CI 통과했어?",
    "코덱스가 지금 뭐하고있는지 알려줘",
    "omh 업데이트했는데 뭔가 이상해, 설치 상태 좀 점검해줘",
    # Re-verification counterexamples: a concept opener followed by a task.
    "Explain the failing deployment and fix it",
    "Explain the failing tests and fix them",
    "Explain and fix the broken checkout flow",
    "Explain the incident and draft a mitigation plan",
    "Explain the quarterly revenue variance and draft a board memo",
    "Explain the attached contract and flag legal risks",
    "Explain this outage and write a postmortem",
    "Explain the deployment failure and write a rollback plan",
    "Explain the error and produce a patch",
    "What should go in the launch announcement for Acme?",
    "Describe the broken login flow and fix the regression",
    "Explain the failing build and repair the configuration",
    "Can you explain the crash and patch the regression?",
    "Explain the customer complaint and draft a reply",
    "Explain the production outage and create an incident report",
    "Explain this deployment failure and recommend a fix",
    "고객 불만 요약하고 답장 방법 알려줘",
    "Explain how to fix the failing deployment",
)


class PlainQuestionTest(unittest.TestCase):
    def test_plain_questions_are_plain(self) -> None:
        for message in PLAIN:
            with self.subTest(message=message):
                self.assertTrue(plain_question(message))

    def test_work_requests_are_not_plain(self) -> None:
        for message in WORK:
            with self.subTest(message=message):
                self.assertFalse(plain_question(message))

    def test_candidate_line_is_empty_for_a_plain_question(self) -> None:
        for message in PLAIN:
            with self.subTest(message=message):
                self.assertEqual(skill_candidates_for_turn(message), ())

    def test_phrase_match_keeps_its_hint(self) -> None:
        payload = awareness_route_hint("Explain this paper at beginner level")
        ids = [str(hint.get("id")) for hint in (payload or {}).get("hints", []) if isinstance(hint, dict)]
        self.assertTrue(any("paper" in hint_id for hint_id in ids), ids)


if __name__ == "__main__":
    unittest.main()
