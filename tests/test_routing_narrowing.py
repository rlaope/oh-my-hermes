"""What the reach round narrowed: matcher edges and gap words that named a tool."""

from __future__ import annotations

import unittest

from omh.routing.chat import route_chat_message
from omh.routing.localization import normalized_phrase, phrase_is_spoken
from omh.routing.recommend import recommend_skills


def _route(message: str) -> dict[str, object]:
    return route_chat_message(message, source="discord")


class MatcherTests(unittest.TestCase):
    def test_an_open_hangul_syllable_is_not_the_syllable_with_a_final(self) -> None:
        self.assertFalse(phrase_is_spoken(normalized_phrase("팀 주간 회의"), normalized_phrase("주가")))
        self.assertTrue(phrase_is_spoken(normalized_phrase("오늘 주가 알려줘"), normalized_phrase("주가")))
        self.assertTrue(phrase_is_spoken(normalized_phrase("삼성 주가가 올랐어"), normalized_phrase("주가")))

    def test_a_short_last_word_is_not_extended(self) -> None:
        self.assertFalse(phrase_is_spoken("at the same time instead of", "time in"))
        self.assertTrue(phrase_is_spoken("what is the time in tokyo", "time in"))
        self.assertTrue(phrase_is_spoken("list the attack scenarios", "attack scenario"))
        self.assertTrue(phrase_is_spoken("split this into reviewable prs", "reviewable pr"))
        self.assertFalse(phrase_is_spoken("make a print", "make a pr"))

    def test_the_weekly_and_the_stock_price_are_apart_in_the_guard(self) -> None:
        self.assertNotEqual(_route("팀 주간 운영 리듬 만들어줘")["selected_skill"], "live-info-operator")
        self.assertEqual(_route("삼성 주가 알려줘")["selected_skill"], "live-info-operator")

    def test_time_instead_is_not_a_time_lookup(self) -> None:
        self.assertNotEqual(
            _route("Can you read these five files at the same time instead of one by one?")["selected_skill"],
            "live-info-operator",
        )
        self.assertEqual(_route("time in tokyo")["selected_skill"], "live-info-operator")


class ShortlistedPhraseTests(unittest.TestCase):
    def test_a_named_phrase_a_rival_leads_is_still_offered(self) -> None:
        for message, skill in (
            ("someone is exfiltrating customer data", "security-event-response"),
            ("instrumentation audit for this agent", "agent-ops-review"),
            ("do a tracing audit for this agent", "agent-ops-review"),
        ):
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual(route["action"], "clarify")
                offered = [row.get("skill") for row in route["candidate_handoff"]["candidates"]]
                self.assertIn(skill, offered)


class ToolbeltGapWordTests(unittest.TestCase):
    def test_a_gap_word_alone_names_no_tool(self) -> None:
        for message in ("the report is missing a chart", "홈, 탐색, 설정 탭 숨겨줘", "several screens are missing"):
            with self.subTest(message=message):
                self.assertNotEqual(_route(message)["selected_skill"], "toolbelt-readiness")

    def test_a_named_tool_with_a_gap_word_still_opens_it(self) -> None:
        for message in ("the mcp server is missing", "외부 도구 설정이 필요해", "API 키 설정해줘", "weather plugin is missing, check provider setup"):
            with self.subTest(message=message):
                self.assertEqual(_route(message)["selected_skill"], "toolbelt-readiness")


class MarketResearchKoreanTests(unittest.TestCase):
    def test_a_korean_request_for_the_method_names_the_skill(self) -> None:
        for message in ("치과 시장 규모 추정해줘", "우리 앱 경쟁사 분석 정리해줘"):
            with self.subTest(message=message):
                self.assertEqual(_route(message)["candidate_skill"], "market-research")

    def test_the_words_under_another_verb_or_no_request_do_not(self) -> None:
        for message in ("시장 규모 슬라이드 보내줘", "시장 규모가 작아서 걱정이야", "경쟁사 분석 회의 잡아줘", "경쟁사 분석 보고서 번역해줘", "광장시장 규모 계산해줘", "시장 규모 뜻 정리해줘", "경쟁사 분석 코드 정리해줘"):
            with self.subTest(message=message):
                self.assertNotEqual(_route(message)["candidate_skill"], "market-research")



class OpsReviewPairTests(unittest.TestCase):
    _PAIR = "direct:ops_review_risks_and_blockers"

    def _top(self, message: str) -> dict[str, object]:
        return recommend_skills(message, limit=1)[0]

    def test_both_words_in_any_order_or_joiner_name_the_review(self) -> None:
        for message in ("이번 주 리스크와 블로커 정리해줘", "블로커, 리스크 정리", "블로커랑 리스크 알려줘"):
            with self.subTest(message=message):
                top = self._top(message)
                self.assertEqual(top["skill"], "ops-review")
                self.assertIn(self._PAIR, top["matched"])

    def test_one_word_alone_is_not_the_pair(self) -> None:
        for message in ("이 PR 리스크 알려줘", "블로커만 정리해줘"):
            with self.subTest(message=message):
                self.assertNotIn(self._PAIR, self._top(message)["matched"])


if __name__ == "__main__":
    unittest.main()
