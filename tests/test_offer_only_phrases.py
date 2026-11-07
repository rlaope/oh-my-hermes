"""An offer-only phrase names its skill as the candidate and can never dispatch it."""

from __future__ import annotations

import json
import unittest

from omh.routing.chat import route_chat_message
from omh.routing.localization import normalized_phrase, phrase_is_spoken
from omh.routing.recommend import _prepared_routable_definitions, recommend_skills
from omh.routing.trigger_language_packs import (
    ORIGIN_USER,
    merged_offer_only_phrases,
    merged_trigger_phrases,
    parse_trigger_language_pack,
    shipped_trigger_language_packs,
)
from omh.skills.catalog import builtin_definitions


def _known() -> frozenset[str]:
    return frozenset(definition.name for definition in builtin_definitions())


def _parse(document: dict[str, object]):
    return parse_trigger_language_pack(
        {"schema_version": "trigger_language_pack/v1", "language": "xx", **document},
        language="xx",
        origin=ORIGIN_USER,
        source="test",
        known_skills=frozenset({"cancel"}),
    )


def _route(message: str) -> dict[str, object]:
    return route_chat_message(message, source="discord")


class PackFieldTests(unittest.TestCase):
    def test_a_pack_may_hold_only_offer_only_phrases(self) -> None:
        pack, status = _parse({"offer_only_phrases": {"cancel": ["stop it all"]}})
        self.assertEqual(status, "applied")
        self.assertEqual(merged_offer_only_phrases((pack,)), {"cancel": frozenset({"stop it all"})})
        # It is no trigger: not in the catalog, not in a skill's rendered signals.
        self.assertEqual(merged_trigger_phrases((pack,)), {})

    def test_an_offer_only_phrase_is_validated_like_a_trigger(self) -> None:
        pack, status = _parse({"offer_only_phrases": {"nope": ["stop it all"]}})
        self.assertIsNone(pack)
        self.assertIn("unknown skill id", status)
        pack, status = _parse({"offer_only_phrases": {"cancel": ["...", "stop"]}})
        self.assertIsNone(pack)
        self.assertIn("carries no word characters", status)

    def test_a_pack_with_neither_table_is_invalid(self) -> None:
        pack, status = _parse({})
        self.assertIsNone(pack)
        self.assertIn("skills must be an object", status)


class ScoringTests(unittest.TestCase):
    def test_no_shipped_offer_only_phrase_is_also_a_plain_trigger(self) -> None:
        # A phrase in both tables would score as a trigger and silently dispatch.
        for prepared in _prepared_routable_definitions():
            with self.subTest(skill=prepared.definition.name):
                self.assertFalse(set(prepared.offer_only_phrases) & set(prepared.plain_trigger_phrases))

    def test_a_phrase_alone_names_the_skill_and_asks(self) -> None:
        for message, skill in (
            ("stop everything that is running", "cancel"),
            ("작업 취소해줘", "cancel"),
            ("add an S3 bucket with terraform", "iac-change"),
            ("이 쿼리 프로파일링 해줘", "ultraperf"),
        ):
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual(route["action"], "clarify")
                self.assertEqual(route["candidate_skill"], skill)

    def test_several_phrases_stay_below_the_dispatch_band(self) -> None:
        message = "my coworker said the cold outreach and outreach sequence and cold email sequence were fine"
        top = recommend_skills(message, limit=1)[0]
        self.assertEqual(top["skill"], "sales-development")
        self.assertLess(top["score"], 8)
        self.assertNotEqual(_route(message)["action"], "dispatch")

    def test_every_shipped_phrase_alone_never_dispatches_its_own_skill_by_itself(self) -> None:
        # The promise, over the whole table: where a phrase's own skill leads on
        # nothing but its offer-only labels, the score is under the dispatch band.
        packs = shipped_trigger_language_packs(_known())
        for skill, phrases in merged_offer_only_phrases(packs).items():
            for phrase in phrases:
                with self.subTest(skill=skill, phrase=phrase):
                    own = [row for row in recommend_skills(phrase, limit=200) if row["skill"] == skill]
                    for row in own:
                        labels = [label for label in row["matched"] if not label.startswith(("metadata:", "locale:"))]
                        if all(label.startswith("offer:") for label in labels):
                            self.assertLess(row["score"], 8)

    def test_its_words_do_not_score_apart_from_it(self) -> None:
        # `outreach` is held by the phrase, so a sentence with the word alone gets nothing from it.
        row = [r for r in recommend_skills("our outreach to the school went well", limit=200) if r["skill"] == "sales-development"]
        self.assertFalse([label for r in row for label in r["matched"] if label.startswith("offer:")])

    def test_the_table_stays_a_few_phrases_per_skill_per_language(self) -> None:
        # The bound the Korean trigger freeze gives triggers: offers can move no
        # dispatch, but a table padded per miss would still bury the candidate.
        for pack in shipped_trigger_language_packs(_known()):
            for skill, phrases in pack.offer_only_phrases:
                with self.subTest(language=pack.language, skill=skill):
                    self.assertLessEqual(len(phrases), 12)

    def test_it_opens_a_gate_only_to_the_candidate(self) -> None:
        # The skill's gate refuses this sentence, so nothing but the phrase may lift it.
        route = _route("give me a native mac app design direction")
        self.assertEqual(route["action"], "clarify")
        self.assertEqual(route["candidate_skill"], "apple-design")

    def test_word_credits_yield_to_a_phrase_that_says_the_need(self) -> None:
        route = _route("에이전트가 계속 같은 툴만 반복 호출해")
        self.assertEqual(route["action"], "clarify")
        self.assertEqual(route["candidate_skill"], "agent-debug")

    def test_a_guard_dispatch_is_not_taken_away(self) -> None:
        route = _route("rename the s3 bucket variable in this script")
        self.assertEqual(route["action"], "dispatch")
        self.assertEqual(route["selected_skill"], "ultrawork")


class MatcherTests(unittest.TestCase):
    def test_an_open_hangul_syllable_is_not_the_syllable_with_a_final(self) -> None:
        self.assertFalse(phrase_is_spoken(normalized_phrase("팀 주간 회의"), normalized_phrase("주가")))
        self.assertTrue(phrase_is_spoken(normalized_phrase("오늘 주가 알려줘"), normalized_phrase("주가")))
        self.assertTrue(phrase_is_spoken(normalized_phrase("삼성 주가가 올랐어"), normalized_phrase("주가")))

    def test_a_short_last_word_is_not_extended(self) -> None:
        self.assertFalse(phrase_is_spoken("at the same time instead of", "time in"))
        self.assertTrue(phrase_is_spoken("what is the time in tokyo", "time in"))
        self.assertTrue(phrase_is_spoken("list the attack scenarios", "attack scenario"))

    def test_the_weekly_and_the_stock_price_are_apart_in_the_guard(self) -> None:
        self.assertNotEqual(_route("팀 주간 운영 리듬 만들어줘")["selected_skill"], "live-info-operator")
        self.assertEqual(_route("삼성 주가 알려줘")["selected_skill"], "live-info-operator")


class ToolbeltGapWordTests(unittest.TestCase):
    def test_a_gap_word_alone_names_no_tool(self) -> None:
        for message in ("the report is missing a chart", "홈, 탐색, 설정 탭 숨겨줘", "several screens are missing"):
            with self.subTest(message=message):
                self.assertNotEqual(_route(message)["selected_skill"], "toolbelt-readiness")

    def test_a_named_tool_with_a_gap_word_still_opens_it(self) -> None:
        for message in ("the mcp server is missing", "외부 도구 설정이 필요해"):
            with self.subTest(message=message):
                self.assertEqual(_route(message)["selected_skill"], "toolbelt-readiness")


class ShippedDataTests(unittest.TestCase):
    def test_en_pack_carries_only_offer_only_phrases(self) -> None:
        from importlib.resources import files

        document = json.loads(files("omh.routing.trigger_packs").joinpath("en.json").read_text(encoding="utf-8"))
        self.assertEqual(set(document), {"schema_version", "language", "offer_only_phrases"})


if __name__ == "__main__":
    unittest.main()
