"""The plugin's per-turn skill line ranks exactly as the core shortlist does.

`omh docs skill-shortlist` projects `routing/lexical_shortlist.py`'s index into
`src/plugin_bundle/omh/tools/skill_shortlist.json`, and the bundle's
`skill_shortlist.py` rebuilds the BM25 ranking from that file alone, because
the bundle cannot import `omh`. These tests hold the two equal and pin the
admission rule that decides whether a turn gets a candidate line at all.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import unittest
from unittest import mock

from omh.plugin_bundle.omh import skill_shortlist as bundle
from omh.plugin_bundle.omh.awareness import awareness_route_hint
from omh.plugin_bundle.omh.hooks import llm_hooks
from omh.routing import lexical_shortlist as core
from omh.routing.recommend import recommend_skills
from omh.routing.skill_shortlist_sidecar import standalone_skill_shortlist_json
from omh.skills.catalog import routable_definitions
from omh.skills.catalog_types import omh_skill_display_name

# Fixed parity messages: work requests across lanes, everyday chat that shares
# words with the catalog, hyphens, apostrophes, accents, digits, and scripts
# the index drops.
PARITY_MESSAGES = (
    "review this PR for bugs before merge",
    "Our week-one retention dropped from 40% to 28%; where do users churn in onboarding?",
    "Write the postmortem for last night's outage and propose SLO follow-ups.",
    "Here's our CRM export. Review pipeline health and the Q4 forecast.",
    "Threat-model our payment service: assets, trust boundaries, attack paths.",
    "I have a 600-page technical manual as a PDF; read all of it.",
    "Remember that our API always uses snake_case field names, for future sessions.",
    "Our C++ service segfaults under load and valgrind shows heap corruption.",
    "Roll out v2.4 to production and watch error rates and latency.",
    "We want to self-host Llama on four A100s. Pick the serving engine.",
    "Help me plan a relaxing weekend in Busan with my partner.",
    "How's the build quality of the IKEA Poang chair?",
    "The doctor said my vitamin D is low. What foods have a lot of it?",
    "My plan for the weekend is to repaint the bedroom.",
    "Café résumé naïve coöperate -- déjà vu",
    "it's we're don't can't e.g. i.e. pr-ready re-run",
    "issues pages services notes queries fixes failing failed running stopped class status analysis boxes",
    "the series goes on; news caches does styling for species and gas lens atlas",
    "결제 모듈 코드 리뷰해줘",
    "",
    "the and of to",
    "CI fails on the typecheck step since this morning's merge.",
    "Design the REST API and database schema for a multi-tenant invoicing service.",
    "Turn this analysis into a 10-slide PowerPoint deck and an Excel appendix.",
)

WORK_REQUESTS = (
    ("Activation fell after we changed the signup flow and new users churn in their first week. "
     "Where does retention break?", "omh-lifecycle-growth"),
    ("Draft a postmortem for yesterday's outage with SLO and error-budget follow-ups.", "omh-reliability-review"),
    ("Attached is a CRM export of open deals; judge pipeline health and whether the quarter forecast holds.",
     "omh-sales-pipeline-review"),
    ("We want to self-host an open-weights LLM on our own GPUs; choose the serving engine and quantization.",
     "omh-inference-serving"),
    ("The Rust borrow checker rejects my async closure with a lifetime error; help me restructure the ownership.",
     "omh-rust"),
)

# Everyday messages that share words with skill names and situations.
EVERYDAY_MESSAGES = (
    "My plan for the weekend is to finally repaint the bedroom. Any color tips?",
    "How is the build quality of this chair? Is it worth buying?",
    "The doctor said my iron is low. What should I eat?",
    "The doctor said my cholesterol is a bit high. What foods should I cut back on?",
    "My grandma keeps forgetting names lately. How can I support her?",
    "Can you look over my monthly budget? Rent 1200, food 500, car 350.",
    "Is it worth fixing my old bike or buying a new one?",
    # Conversational requests whose topic words reach a skill.
    "tell me a short joke about secret-token-123",
    "recommend a good movie about hackers and security",
    "I feel stressed about my team deadline and my manager, any advice?",
)

SMALL_TALK_AND_FACTS = (
    "Hello there, good morning!",
    "Thank you so much!",
    "What is the tallest mountain in Africa?",
    "How many legs does a spider have?",
    "Who wrote Pride and Prejudice?",
)


def _candidates(message: str) -> tuple[tuple[str, str], ...]:
    return bundle.skill_candidates_for_turn(message, route_hint_payload=awareness_route_hint(message))


class SidecarParityTests(unittest.TestCase):
    def test_the_sidecar_is_the_producer_output(self) -> None:
        path = Path(bundle.__file__).resolve().parent / "tools" / "skill_shortlist.json"
        self.assertEqual(path.read_text(encoding="utf-8"), standalone_skill_shortlist_json())

    def test_terms_match_the_core_tokenizer(self) -> None:
        for message in PARITY_MESSAGES:
            with self.subTest(message=message):
                self.assertEqual(bundle.lexical_terms(message), core.lexical_terms(message))

    def test_host_scanner_exclusion_is_projected_without_weakening_the_explicit_route(self) -> None:
        sidecar = standalone_skill_shortlist_json()
        self.assertIn("monero", core.SIDECAR_EXCLUDED_TERMS)
        self.assertNotIn("monero", sidecar.casefold())
        self.assertEqual(
            bundle.lexical_terms("assess the monero gateway connector"),
            core.lexical_terms("assess the monero gateway connector"),
        )
        connector = next(
            item
            for item in recommend_skills("assess the monero gateway connector", limit=5)
            if item["skill"] == "external-connector-readiness"
        )
        self.assertIn("trigger:monero gateway", connector["matched"])

    def test_the_stemmer_matches_the_core_stemmer(self) -> None:
        for token in ("issues", "pages", "queries", "fixes", "matches", "failing", "failed", "running",
                      "stopped", "calling", "class", "status", "analysis", "bus", "ties", "ing", "s", "sees",
                      "caches", "cache", "goes", "does", "series", "news", "styling", "style", "services",
                      "issue", "note", "page", "free", "agree"):
            with self.subTest(token=token):
                self.assertEqual(bundle._stem(token, core._STEM_EXCEPTIONS), core.stem(token))

    def test_the_stemmer_matches_on_every_catalog_word(self) -> None:
        from omh.routing.localization import routing_terms

        words: set[str] = set()
        for definition in routable_definitions():
            for field, _weight in core.FIELD_WEIGHTS:
                for raw in routing_terms(core._field_text(definition, field)):
                    words.update(part for part in raw.split("-") if part.isascii() and part.isalnum())
        self.assertGreater(len(words), 1000)
        mismatched = sorted(word for word in words if bundle._stem(word, core._STEM_EXCEPTIONS) != core.stem(word))
        self.assertEqual(mismatched, [])

    def test_ranking_matches_the_core_ranking(self) -> None:
        for message in PARITY_MESSAGES:
            with self.subTest(message=message):
                self.assertEqual(bundle.lexical_ranking(message)[:10], core.lexical_ranking(message)[:10])
                self.assertEqual(
                    [name for name, _ in bundle.lexical_ranking(message)],
                    [name for name, _ in core.lexical_ranking(message)],
                )

    def test_anchors_match_the_core_anchor_rule(self) -> None:
        index = bundle._index()
        assert index is not None
        for message in PARITY_MESSAGES:
            terms = frozenset(bundle.lexical_terms(message))
            for skill in index.skills:
                with self.subTest(message=message, skill=skill.name):
                    self.assertEqual(terms & skill.anchors, core.lexical_anchor_terms(message, skill.name))

    def test_labels_are_the_names_the_skill_index_shows(self) -> None:
        index = bundle._index()
        assert index is not None
        expected = {definition.name: omh_skill_display_name(definition.name) for definition in routable_definitions()}
        self.assertEqual({skill.name: skill.label for skill in index.skills}, expected)
        for skill in index.skills:
            self.assertTrue(skill.situation)
            self.assertNotIn("[omh]", skill.situation)

    def _with_sidecar_text(self, text: str) -> tuple[tuple[str, float], ...]:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "skill_shortlist.json"
            path.write_text(text, encoding="utf-8")
            bundle._index.cache_clear()
            bundle.lexical_ranking.cache_clear()
            try:
                with mock.patch.object(bundle, "SIDECAR_PATH", path):
                    return bundle.lexical_ranking(WORK_REQUESTS[0][0])
            finally:
                bundle._index.cache_clear()
                bundle.lexical_ranking.cache_clear()

    def test_a_corrupt_sidecar_ranks_nothing(self) -> None:
        self.assertEqual(self._with_sidecar_text('{"schema_version": '), ())

    def test_a_sidecar_of_another_schema_ranks_nothing(self) -> None:
        payload = json.loads(standalone_skill_shortlist_json())
        payload["schema_version"] = "omh_skill_shortlist_index/v0"
        self.assertEqual(self._with_sidecar_text(json.dumps(payload)), ())

    def test_a_malformed_row_ranks_nothing(self) -> None:
        payload = json.loads(standalone_skill_shortlist_json())
        del payload["skills"][0]["terms"]
        self.assertEqual(self._with_sidecar_text(json.dumps(payload)), ())
        payload = json.loads(standalone_skill_shortlist_json())
        payload["skills"][1]["terms"] = {"heavy": "word"}
        self.assertEqual(self._with_sidecar_text(json.dumps(payload)), ())

    def test_a_missing_sidecar_ranks_nothing(self) -> None:
        bundle._index.cache_clear()
        bundle.lexical_ranking.cache_clear()
        try:
            with mock.patch.object(bundle, "SIDECAR_PATH", Path("/nonexistent/skill_shortlist.json")):
                self.assertEqual(bundle.lexical_ranking(WORK_REQUESTS[0][0]), ())
                self.assertEqual(_candidates(WORK_REQUESTS[0][0]), ())
        finally:
            bundle._index.cache_clear()
            bundle.lexical_ranking.cache_clear()


class AdmissionTests(unittest.TestCase):
    def test_a_work_request_names_the_skill_its_situation_describes(self) -> None:
        for message, skill in WORK_REQUESTS:
            with self.subTest(message=message):
                labels = [label for label, _situation in _candidates(message)]
                self.assertIn(skill, labels)
                self.assertLessEqual(len(labels), bundle.MAX_CANDIDATES)

    def test_conversational_requests_are_held_back_by_their_kind_not_their_topic(self) -> None:
        for message in EVERYDAY_MESSAGES[-3:]:
            with self.subTest(message=message):
                # The ranking alone would admit each of them.
                self.assertTrue(bundle.skill_candidates(message))
                self.assertTrue(bundle._conversational(message))

    def test_everyday_chat_with_skill_words_gets_no_line(self) -> None:
        for message in EVERYDAY_MESSAGES:
            with self.subTest(message=message):
                self.assertEqual(_candidates(message), ())

    def test_small_talk_and_direct_facts_get_no_line(self) -> None:
        for message in SMALL_TALK_AND_FACTS:
            with self.subTest(message=message):
                self.assertEqual(_candidates(message), ())

    def test_the_conversational_skips_hold_back_what_the_ranking_would_admit(self) -> None:
        # Each would get a line on the ranking alone; the skip is what stops it.
        for message in (
            "What is an SLO error budget in a postmortem?",
            "How many churn cohorts does retention analysis need?",
            "churn retention",
            "postmortem outage",
        ):
            with self.subTest(message=message):
                self.assertTrue(bundle.skill_candidates(message))
                self.assertEqual(_candidates(message), ())

    def test_every_listed_skill_shares_an_anchor_with_the_message(self) -> None:
        index = bundle._index()
        assert index is not None
        by_label = {skill.label: skill for skill in index.skills}
        for message, _skill in WORK_REQUESTS:
            terms = frozenset(bundle.lexical_terms(message))
            for label, _situation in _candidates(message):
                with self.subTest(message=message, label=label):
                    self.assertTrue(terms & by_label[label].anchors)

    def test_a_named_workflow_gets_no_alternatives(self) -> None:
        message = "use omh plan to plan the churn and onboarding retention analysis"
        self.assertEqual(awareness_route_hint(message)["hints"][0]["id"], "direct_workflow_invocation")
        self.assertEqual(_candidates(message), ())

    def test_a_mixed_message_keeps_the_ascii_line(self) -> None:
        # The Korean words here reach one anchored word ("온보딩"), which the
        # Hangul admission does not take alone; the ASCII words do admit it.
        korean_only = "리텐션이 떨어졌어. 온보딩에서 어디서 이탈하는지 찾아줘."
        self.assertEqual(_candidates(korean_only), ())
        self.assertTrue(bundle.hangul_ranking(korean_only))
        # A particle glued to an English word makes a non-ASCII token, so the
        # English words here stand apart.
        mixed = "activation, retention, churn 지표가 온보딩 직후에 나빠졌어. 원인 찾아줘"
        self.assertIn("omh-lifecycle-growth", [label for label, _ in _candidates(mixed)])

    def test_the_maestro_lane_is_never_listed(self) -> None:
        message = "I already chose Claude Code as coding owner; prepare the maestro handoff prompt for it"
        self.assertIn("maestro", [name for name, _ in bundle.lexical_ranking(message)[:3]])
        self.assertNotIn("ulw-maestro", [label for label, _ in bundle.skill_candidates(message)])

    def test_admission_reads_only_the_head_of_the_ranking(self) -> None:
        # Only the fourth-ranked skill would admit this message. The ranking
        # is IDF-weighted, so a new skill moves it: once `iac-change` (#1566)
        # joined the skills that say "change", `external-connector-readiness`
        # overtook `model-setup` by 0.035 in the old wording and ranked third.
        # "setup" keeps the admitting skill fourth.
        message = "The provider changed how their model handles tools; adapt our routing setup to it."
        self.assertEqual(bundle.skill_candidates(message), ())
        with mock.patch.object(bundle, "ADMISSION_HEAD", bundle.ADMISSION_HEAD + 2):
            self.assertTrue(bundle.skill_candidates(message))

    def test_three_content_words_are_enough_two_are_not(self) -> None:
        self.assertEqual(len(set(bundle.lexical_terms("retention churn onboarding"))), 3)
        self.assertTrue(_candidates("retention churn onboarding"))
        self.assertEqual(_candidates("churn retention"), ())

    def test_a_factual_question_is_skipped_up_to_the_word_limit(self) -> None:
        at_limit = "What is the difference between an SLO and an error budget in a postmortem?"
        over = "What is the difference between an SLO and an error budget in a postmortem review?"
        self.assertEqual(len(at_limit.split()), bundle._FACTUAL_MAX_WORDS)
        self.assertEqual(_candidates(at_limit), ())
        self.assertTrue(_candidates(over))

    def test_no_jev_skill_is_ever_listed(self) -> None:
        message = "flag auth and migration risk on this diff under review before I approve it"
        self.assertTrue(any(name.startswith("jev-") for name, _ in bundle.lexical_ranking(message)[:5]))
        self.assertFalse(any(label.startswith("omh-jev-") for label, _ in _candidates(message)))

    def test_one_common_anchor_is_held_below_the_single_anchor_score(self) -> None:
        # "doctor" is an anchor of omh-doctor and the message clears the
        # shortlist floor; only the single-anchor score keeps it out.
        message = "The doctor said my cholesterol is a bit high. What foods should I cut back on?"
        ranking = bundle.lexical_ranking(message)
        # `release-cut` (#1693) outranks doctor here on "cut" and "back", from
        # "cut a release" and "roll back the deploy"; both words are held back
        # for it, so it shares no anchor with the message and is never listed.
        # The claim is about doctor, read from its own row.
        self.assertEqual([name for name, _ in ranking[:2]], ["release-cut", "doctor"])
        self.assertTrue(core.only_held_back_overlap(message, "release-cut"))
        doctor = dict(ranking)["doctor"]
        self.assertGreaterEqual(doctor, core.LEXICAL_SCORE_FLOOR)
        self.assertLess(doctor, bundle.ADMISSION_SINGLE_ANCHOR_SCORE)
        with mock.patch.object(bundle, "ADMISSION_SINGLE_ANCHOR_SCORE", core.LEXICAL_SCORE_FLOOR):
            self.assertIn("omh-doctor", [label for label, _ in bundle.skill_candidates(message)])

    def test_two_anchors_admit_below_the_single_anchor_score(self) -> None:
        message = WORK_REQUESTS[1][0]
        name, score = bundle.lexical_ranking(message)[0]
        index = bundle._index()
        assert index is not None
        skill = next(item for item in index.skills if item.name == name)
        self.assertGreaterEqual(len(frozenset(bundle.lexical_terms(message)) & skill.anchors), 2)
        with mock.patch.object(bundle, "ADMISSION_MIN_ANCHORS", 99), mock.patch.object(
            bundle, "ADMISSION_SINGLE_ANCHOR_SCORE", score + 1.0
        ):
            self.assertEqual(bundle.skill_candidates(message), ())
        self.assertTrue(bundle.skill_candidates(message))

    def test_the_score_floor_holds_back_a_weak_anchor(self) -> None:
        # Raise the floor above this request's best score and the line goes:
        # the floor, not the anchors, is what admits it.
        message = WORK_REQUESTS[0][0]
        best = bundle.lexical_ranking(message)[0][1]
        index = bundle._index()
        assert index is not None
        with mock.patch.object(bundle, "_index", return_value=dataclasses.replace(index, score_floor=best + 1.0)):
            self.assertEqual(bundle.skill_candidates(message), ())


# Korean work requests in their own words, not the catalog's: each shares a
# phrase's worth of words with its skill's existing Hangul triggers.
KOREAN_WORK_REQUESTS = (
    ("배포 파이프라인이 깨졌는데 빌드 로그 보고 고쳐줘", "omh-build-failure-triage"),
    ("고객 피드백을 모아서 버그랑 기능 요청으로 나눠줘", "omh-feedback-triage"),
    ("로그 파일에서 오류 패턴 분석해줘", "omh-data-analysis"),
    ("브라우저 열어서 링크 클릭하고 캡처해줘", "omh-browser"),
    ("회의록을 보기 좋게 요약 카드로 만들어줘", "omh-image-cards"),
    ("이거 프로젝트 기억에 추가해줘", "omh-memory-new"),
    ("실행 중인 작업 보여줘", "omh-running-work-board"),
    ("웹 검색해서 최신 자료 찾아줘", "omh-web-research"),
    ("채용 면접 평가표 초안 잡아줘", "omh-people-ops"),
)

# Everyday Korean: weather, food, weekend plans, feelings, family. Several
# share a bigram with a skill's triggers ("날씨", "같이", "감사", and
# "다이어트" two with "다이어그램").
KOREAN_EVERYDAY_MESSAGES = (
    "오늘 날씨 진짜 덥다",
    "날씨가 쌀쌀해졌네",
    "이번 주말에 가족이랑 바다 보러 갈 건데 날씨가 좋았으면 좋겠다",
    "점심 뭐 먹지",
    "엄마가 해주신 김치찌개가 제일 맛있어",
    "다이어트 중인데 야식이 땡겨",
    "주말에 등산 갈 건데 같이 갈래?",
    "요즘 너무 지쳐서 아무것도 하기 싫어",
    "스트레스 받아",
    "아빠 생신이 다가와",
    "감사합니다",
    "동생 결혼식에서 사진 공유해줄게",
)


class HangulSidecarTests(unittest.TestCase):
    def test_hangul_terms_match_the_core_tokenizer(self) -> None:
        for message in (*PARITY_MESSAGES, *(m for m, _ in KOREAN_WORK_REQUESTS), *KOREAN_EVERYDAY_MESSAGES):
            with self.subTest(message=message):
                self.assertEqual(bundle.hangul_terms(message), core.hangul_terms(message))

    def test_every_skill_carries_exactly_its_trigger_bigrams(self) -> None:
        index = bundle._index()
        assert index is not None
        for skill in index.skills:
            with self.subTest(skill=skill.name):
                self.assertEqual(skill.hangul, core.hangul_trigger_terms(skill.name))
                self.assertEqual(skill.hangul_anchors, core.hangul_anchor_terms(skill.name))
                self.assertLessEqual(skill.hangul_anchors, skill.hangul)

    def test_the_hangul_field_is_read_from_triggers_only(self) -> None:
        # The index adds no Korean vocabulary: a skill without a Hangul
        # trigger has no Hangul terms, and every term is a trigger's bigram.
        index = bundle._index()
        assert index is not None
        definitions = {definition.name: definition for definition in routable_definitions()}
        for skill in index.skills:
            hangul_triggers = [t for t in definitions[skill.name].triggers if not t.isascii()]
            with self.subTest(skill=skill.name):
                if not hangul_triggers:
                    self.assertEqual(skill.hangul, frozenset())
                for term in skill.hangul:
                    self.assertTrue(any(term in trigger for trigger in hangul_triggers), term)

    def test_bigrams_stay_inside_a_word_and_drop_request_filler(self) -> None:
        self.assertEqual(core.hangul_terms("코드 리뷰해줘"), ["리뷰", "뷰해", "코드"])
        self.assertEqual(core.hangul_terms("코드리뷰"), ["드리", "리뷰", "코드"])
        self.assertEqual(core.hangul_terms("만들어줘 보여줘"), [])
        # Syllables compose first, so decomposed input meets composed triggers.
        import unicodedata

        self.assertEqual(core.hangul_terms(unicodedata.normalize("NFD", "빌드 실패")), ["빌드", "실패"])

    def test_containing_a_trigger_phrase_contains_its_bigrams(self) -> None:
        for definition in routable_definitions():
            for trigger in definition.triggers:
                if trigger.isascii():
                    continue
                message = f"어제부터 {trigger}를 봐야 해"
                with self.subTest(trigger=trigger):
                    self.assertLessEqual(set(core.hangul_terms(trigger)), set(core.hangul_terms(message)))


class HangulAdmissionTests(unittest.TestCase):
    def test_a_korean_work_request_names_its_skill(self) -> None:
        for message, skill in KOREAN_WORK_REQUESTS:
            with self.subTest(message=message):
                labels = [label for label, _situation in _candidates(message)]
                self.assertIn(skill, labels)
                self.assertLessEqual(len(labels), bundle.MAX_CANDIDATES)

    def test_everyday_korean_gets_no_line(self) -> None:
        for message in KOREAN_EVERYDAY_MESSAGES:
            with self.subTest(message=message):
                self.assertEqual(_candidates(message), ())

    def test_one_word_is_not_enough_below_the_single_word_score(self) -> None:
        # "다이어트" shares two anchor bigrams with omh-codebase-uml's
        # "다이어그램", in one word, above the floor and below the single-word
        # score.
        message = "다이어트 중인데 야식이 땡겨"
        name, score = bundle.hangul_ranking(message)[0]
        self.assertEqual(name, "codebase-uml")
        self.assertGreaterEqual(score, bundle.HANGUL_ADMISSION_SCORE_FLOOR)
        self.assertLess(score, bundle.HANGUL_ADMISSION_SINGLE_WORD_SCORE)
        with mock.patch.object(bundle, "HANGUL_ADMISSION_MIN_WORDS", 1):
            self.assertIn("omh-codebase-uml", [label for label, _ in bundle.hangul_skill_candidates(message)])

    def test_one_rare_word_at_the_single_word_score_admits(self) -> None:
        message = "포스트모템 써줘"
        name, score = bundle.hangul_ranking(message)[0]
        self.assertEqual(name, "reliability-review")
        self.assertGreaterEqual(score, bundle.HANGUL_ADMISSION_SINGLE_WORD_SCORE)
        self.assertIn("omh-reliability-review", [label for label, _ in _candidates(message)])
        with mock.patch.object(bundle, "HANGUL_ADMISSION_SINGLE_WORD_SCORE", score + 1.0):
            self.assertEqual(bundle.hangul_skill_candidates(message), ())

    def test_the_hangul_floor_holds_back_two_common_words(self) -> None:
        # Two anchored words, one family message: only the floor keeps it out.
        message = "동생 결혼식에서 사진 공유해줄게"
        self.assertLess(bundle.hangul_ranking(message)[0][1], bundle.HANGUL_ADMISSION_SCORE_FLOOR)
        # 3.0 -> 2.5: the lowered floor must sit below img-summary, the one
        # skill with anchors in two words here. Each new skill grows the
        # document count and shifts every IDF; with `release-cut` (#1693)
        # img-summary measures 2.9996, a hair under the old 3.0.
        with mock.patch.object(bundle, "HANGUL_ADMISSION_SCORE_FLOOR", 2.5):
            self.assertTrue(bundle.hangul_skill_candidates(message))
        self.assertEqual(_candidates(message), ())

    def test_the_hangul_floor_holds_back_a_two_word_match(self) -> None:
        message = KOREAN_WORK_REQUESTS[2][0]
        best = bundle.hangul_ranking(message)[0][1]
        with mock.patch.object(bundle, "HANGUL_ADMISSION_SCORE_FLOOR", best + 1.0):
            self.assertEqual(bundle.hangul_skill_candidates(message), ())
        self.assertTrue(bundle.hangul_skill_candidates(message))

    def test_english_turns_never_reach_the_hangul_ranking(self) -> None:
        for message in (*EVERYDAY_MESSAGES, *SMALL_TALK_AND_FACTS, *(m for m, _ in WORK_REQUESTS)):
            with self.subTest(message=message):
                self.assertEqual(bundle.hangul_ranking(message), ())

    def test_a_named_workflow_gets_no_alternatives_in_korean_either(self) -> None:
        message = "use omh plan: 배포 파이프라인 빌드 실패 고쳐줘"
        self.assertEqual(awareness_route_hint(message)["hints"][0]["id"], "direct_workflow_invocation")
        self.assertTrue(bundle.hangul_skill_candidates(message))
        self.assertEqual(_candidates(message), ())


class LineTests(unittest.TestCase):
    def test_the_line_names_each_candidate_by_its_situation(self) -> None:
        candidates = _candidates(WORK_REQUESTS[0][0])
        line = bundle.skill_candidate_line(candidates)
        for label, situation in candidates:
            self.assertIn(f"{label} ({situation})", line)
        self.assertIn(f'skill_view(name="{candidates[0][0]}")', line)
        self.assertIn("no category prefix", line)
        self.assertNotIn("OMH", line)
        self.assertEqual(bundle.skill_candidate_line(()), "")

    def setUp(self) -> None:
        bundle.reset_candidate_line_state()
        self.addCleanup(bundle.reset_candidate_line_state)

    def test_a_session_sees_a_candidate_set_once(self) -> None:
        first = _candidates(WORK_REQUESTS[0][0])
        second = _candidates(WORK_REQUESTS[1][0])
        self.assertNotEqual(first, second)
        self.assertTrue(bundle.claim_candidate_line("s1", first))
        self.assertFalse(bundle.claim_candidate_line("s1", first))
        self.assertTrue(bundle.claim_candidate_line("s2", first))
        self.assertTrue(bundle.claim_candidate_line("s1", second))
        self.assertTrue(bundle.claim_candidate_line("s1", first))
        self.assertFalse(bundle.claim_candidate_line("s1", ()))

    def test_pre_llm_call_repeats_the_line_only_when_the_set_changes(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            kwargs = {"omh_home": f"{tmp}/omh", "hermes_home": f"{tmp}/hermes", "is_first_turn": False}

            def context(message: str) -> str:
                return str((llm_hooks.pre_llm_call(user_message=message, session_id="s-dedup", **kwargs) or {}).get("context", ""))

            self.assertIn("Skills that may fit this request", context(WORK_REQUESTS[0][0]))
            self.assertNotIn("Skills that may fit this request", context(WORK_REQUESTS[0][0] + " Please."))
            self.assertIn("Skills that may fit this request", context(WORK_REQUESTS[1][0]))

    def test_pre_llm_call_carries_the_line_for_work_and_not_for_chat(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            kwargs = {"omh_home": f"{tmp}/omh", "hermes_home": f"{tmp}/hermes", "is_first_turn": False}
            work = llm_hooks.pre_llm_call(user_message=WORK_REQUESTS[0][0], session_id="s-work", **kwargs) or {}
            self.assertIn("Skills that may fit this request: ", str(work.get("context", "")))
            self.assertIn("omh-lifecycle-growth (", str(work.get("context", "")))
            chat = llm_hooks.pre_llm_call(user_message=EVERYDAY_MESSAGES[3], session_id="s-chat", **kwargs) or {}
            self.assertNotIn("Skills that may fit this request", str(chat.get("context", "")))
            opted_out = llm_hooks.pre_llm_call(
                user_message=WORK_REQUESTS[0][0], session_id="s-off", include_omh_awareness=False, **kwargs
            ) or {}
            self.assertNotIn("Skills that may fit this request", str(opted_out.get("context", "")))


if __name__ == "__main__":
    unittest.main()
