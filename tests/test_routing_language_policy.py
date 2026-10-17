"""Global language policy for routing.

OMH targets a global audience with English as the primary language. Its
deterministic trigger tables only ever grew in Latin and Hangul, and these
tests used to hold that state still on the reasoning that per-language trigger
tables do not scale, so non-English intent resolution belonged to model
selection rather than to more tokens.

Trigger language packs (`src/routing/trigger_language_packs.py`) changed the
premise. A language's phrases are validated data merged into the catalog, so
adding one is authoring `src/routing/trigger_packs/<lang>.json` rather than
editing the router, and the cost that made the old policy sensible -- source
churn per language, paid by whoever owns the catalog -- is not there any more.
So the tests keep what was actually load-bearing and drop what was a
consequence of the old storage:

* The per-skill Korean freeze stays, restated: an existing skill's table must
  not be padded to make a routing miss go away. It reads the merged catalog, so
  moving Korean into `ko.json` did not weaken it by a single entry, and padding
  the pack fails exactly the way padding the source did.
* Which scripts are trigger-backed is measured from the catalog rather than
  declared in a constant, so shipping a pack is what makes a script supported.
* Every routable skill must still be reachable in English: English is the base
  corpus, and a skill that only a pack can reach is a skill most users cannot.
"""

from __future__ import annotations

import collections
import unittest

from omh.routing.input_language import (
    SCRIPT_HAN,
    SCRIPT_HANGUL,
    SCRIPT_KANA,
    SCRIPT_LATIN,
    SUPPORT_MODEL_SELECTION_REQUIRED,
    SUPPORT_TRIGGER_BACKED,
    detect_input_script,
    routing_input_language,
    routing_language_support,
    trigger_backed_scripts,
)
from omh.routing.trigger_language_packs import shipped_trigger_pack_languages
from omh.skills.catalog import routable_definitions


# Frozen per skill on 2026-07-27, not as a global total.
#
# The first version of this gate froze the sum, and it fired on the very next
# merge: three new skills arrived carrying their own Korean triggers and the
# total moved 766 -> 774. That is not the habit worth stopping. A new skill
# paying for its own triggers is proportional work; padding an existing skill's
# Korean table to paper over a routing miss is the unbounded one, and a sum
# cannot tell the two apart.
#
# So the freeze is per skill, and only for skills that existed at freeze time.
# A new skill is exempt here and constrained instead by
# `test_every_routable_skill_is_reachable_in_english`. Raising an entry below
# means an existing Korean table grew: do it only with a stated reason, and
# never to make a routing miss go away.
#
# 2026-08-30: these phrases moved from source literals into
# `src/routing/trigger_packs/ko.json`. The counts below did not move with them
# -- they are read off the merged catalog, which is where the router reads them
# too -- so the freeze covers the pack exactly as it covered the source.
# The specialist-domain set is an explicit task exception to the no-growth policy:
# every new skill carries exactly its three approved narrow Korean phrases.
SPECIALIST_DOMAIN_HANGUL_TRIGGER_COUNTS: dict[str, int] = {
    "finance-analysis": 3,
    "people-ops": 3,
    "legal-compliance-review": 3,
    "support-operations": 3,
    "curriculum-design": 3,
    "localization-review": 3,
    "sales-development": 3,
    "product-brief": 3,
}


FROZEN_HANGUL_TRIGGERS_BY_SKILL: dict[str, int] = {
    "accessibility-audit": 11,
    "achievements": 5,
    "agent-board": 13,
    "agent-debug": 7,
    "agent-evaluation": 4,
    "agent-ops-review": 18,
    "ai-slop-cleaner": 5,
    "ask": 2,
    # 15 -> 18 (2026-09-15, #1582): a continuous watch with no cadence word
    # ("계속 감시해줘") reached nothing -- and neither did its English form
    # ("keep watching this", "keep monitoring the build"). Every phrasing this
    # lane already recognised named a cadence ("매일", "every morning") or the
    # word automation itself, so what was missing was the intent, not the
    # language. The English base corpus ("keep watching", "keep monitoring",
    # "watch continuously", "monitor continuously") and the ja/zh packs ship in
    # the same commit: new capability reach, not padding over a Korean-only
    # miss.
    "automation-blueprint": 18,
    "browser-operator": 15,
    "build-failure-triage": 14,
    "code-review": 7,
    "codebase-onboarding": 5,
    "codegraph-refresh": 6,
    "command-operator": 10,
    "connector-operator": 14,
    "content-operator": 12,
    "context-budget-review": 4,
    "cto-loop": 6,
    "data-analysis": 13,
    # 0 -> 36 (2026-10-15, owner decision D.4 of the upstream-audit follow-up
    # triage, KO-2): Korean admission for the two safety gates. A Korean
    # request to protect personal data leaving the team reached no gate
    # ("고객 정보 마스킹해서 벤더한테 보내줘" dispatched gateway-intent-card).
    # Its phrases live in `data_share_cues`, read by its Korean admission
    # rule, so they score only in a request that rule admits. A new
    # capability for a skill that had no Korean, frozen at what it carries so
    # a later miss is not papered over by padding it.
    "data-share-review": 36,
    "deep-interview": 5,
    # 2026-07-27: bare "자료" removed - a generic research-shaded noun that stole
    # reference/data-finding prompts from the research lane via substring phrase
    # match; "첨부"/"전달" phrases still cover the deliverables intent.
    "deliverable-package": 3,
    "deploy-and-monitor": 9,
    "design-orchestration": 4,
    "design-quality-gate": 5,
    "executor-runtime-readiness": 16,
    "external-connector-readiness": 24,
    "failure-signal-audit": 10,
    "feedback-triage": 12,
    # 16 -> 20 (2026-09-08): the scroll-motion lane arrived as owner-spoken
    # Korean ("부드러운 스크롤", "스크롤 부드럽게", "스크롤 애니메이션", "패럴랙스")
    # WITH its English base corpus in the same commit ("smooth scroll",
    # "smooth scrolling", "scroll animation", "parallax scroll", and the
    # rest) and its Japanese/Chinese packs — new capability reach for a
    # lane the catalog had no trigger for in any language, not padding
    # over a routing miss on an intent already covered.
    # 20 -> 28 (2026-10-07): the design-reference lane (chart styling, footer
    # design, neobrutalism, logo marquee, split text) arrived with its English
    # phrases ("chart styling", "footer design", "neobrutalism style", "logo
    # marquee", "split text animation") and its Japanese/Chinese packs in the
    # same commit. "네오브루탈리즘 스타일로 바꿔줘" fell back with no candidate
    # and "차트 스타일 우리 디자인 시스템에 맞춰줘" named award-bar-score:
    # new capability reach, not padding over a covered intent. The everyday
    # Korean words inside the phrases (차트, 스타일, 테마, 푸터, 로고, 마키,
    # 텍스트, 스플릿) are held back to whole-phrase matches in the ko pack.
    "frontend": 28,
    "gateway-intent-card": 10,
    "github-event-ops": 9,
    "github-issue-intake": 8,
    "harness-session-inventory": 10,
    "idea-to-deploy": 8,
    "img-summary": 55,
    "instinct-ledger": 6,
    "live-info-operator": 13,
    "loop": 8,
    "materials-package": 27,
    "media-input-operator": 19,
    "meeting-brief": 7,
    "memory-new": 7,
    # 25 -> 27 (2026-08-31): the memory-interview intent arrived as English
    # phrases ("memory interview", "your memories", "memories still true")
    # WITH the owner-spoken Korean forms in the same commit ("메모리 인터뷰",
    # "기억 인터뷰") — new capability reach, not padding over a routing miss.
    "memory-sync": 27,
    # 5 -> 7 (2026-08-19): provider-switch / quota-relogin intents arrived as
    # owner-spoken Korean ("프로바이더 전환", "다른 계정으로 로그인") WITH their
    # English equivalents in the same commit ("switch provider account",
    # "provider quota exceeded") — new capability reach, not padding over a
    # routing miss.
    "model-setup": 10,  # +3 (모델 세팅/모델 체인/카테고리별 모델): chain-interview vocabulary, owner request 2026-08-21
    "morning-brief": 4,
    "oh-my-hermes": 2,
    "operating-rhythm": 7,
    # 9 -> 7 (2026-10-15): bare "비용" and "토큰" removed. Each dispatched the
    # card on its own -- an auth token's storage, the cost of a function call --
    # and the usage reading moved to whole phrases in the card's guard.
    "ops-observability-card": 7,
    "ops-review": 7,
    "paper-learning": 10,
    "parallel-tools": 4,
    "physical-device-readiness": 7,
    "plan": 8,
    "production-audit": 5,
    "prompt-import-readiness": 6,
    "ralplan": 11,
    "reliability-review": 9,
    "report-package": 9,
    "research-brief": 5,
    "research-department": 7,
    "rules-distill": 4,
    "security-safety-review": 5,
    "skill-health": 6,
    "skill-scout": 13,
    "source-finder": 8,
    # 0 -> 24 (2026-10-15, owner decision D.4, KO-1): the other safety gate,
    # on the same terms. "내 카드로 결제해줘" fell back with score 0. Its
    # phrases live in `spend_signals` and score only in a request its Korean
    # admission rule admits.
    "spend-gate": 24,
    "strategy-brief": 6,
    "toolbelt-readiness": 5,
    "ultragoal": 4,
    "ultraprocess": 19,
    "ultraqa": 5,
    "verification-gate": 5,
    "visual-qa": 17,
    "voice-operator": 12,
    # 2026-08: `web-research` became `research`, the merged deep research
    # engine. Five Korean deep-grounding cues joined the table (딥리서치,
    # 딥 리서치, 심층 리서치, 레퍼런스 구현, 오픈소스 깊게 참고); the other Korean
    # deep phrases were left out because they contain the existing `조사`
    # trigger and route here already.
    # 2026-09: the lookup half of the table moved to `web-research` when that
    # lane split off. Ten phrases left and ten stayed, so the catalog's Hangul
    # total is unchanged -- a partition, not growth. Both halves are frozen at
    # what they hold now, which is stricter than leaving the new skill under the
    # "new skills may carry their own Korean triggers" exemption.
    "research": 10,
    "web-research": 10,
    "websearch-setup": 4,
    "wiki": 7,
    "workflow-learning": 11,
    "workspace-audit": 4,
    "workspace-file-operator": 12,
}


def _hangul_triggers_by_skill() -> dict[str, int]:
    return {
        definition.name: sum(1 for trigger in definition.triggers if detect_input_script(trigger) == SCRIPT_HANGUL)
        for definition in routable_definitions()
        if any(detect_input_script(trigger) == SCRIPT_HANGUL for trigger in definition.triggers)
    }


def _trigger_script_counts() -> collections.Counter[str]:
    counts: collections.Counter[str] = collections.Counter()
    for definition in routable_definitions():
        for trigger in definition.triggers:
            counts[detect_input_script(trigger)] += 1
    return counts


class RoutingLanguagePolicyTests(unittest.TestCase):
    def test_no_existing_korean_trigger_table_grows(self) -> None:
        observed = _hangul_triggers_by_skill()

        for skill, frozen in sorted(FROZEN_HANGUL_TRIGGERS_BY_SKILL.items()):
            with self.subTest(skill=skill):
                self.assertLessEqual(observed.get(skill, 0), frozen)

    def test_new_specialist_domain_skills_use_the_approved_three_hangul_triggers(self) -> None:
        observed = _hangul_triggers_by_skill()

        for skill, expected in sorted(SPECIALIST_DOMAIN_HANGUL_TRIGGER_COUNTS.items()):
            with self.subTest(skill=skill):
                self.assertEqual(observed.get(skill), expected)

    def test_other_new_skills_may_carry_their_own_korean_triggers(self) -> None:
        # The exemption is deliberate and bounded: a skill absent from the freeze
        # is new, and its Korean triggers are its own cost rather than growth of
        # an existing table. It still has to be reachable in English.
        observed = _hangul_triggers_by_skill()
        new_skills = (
            set(observed)
            - set(FROZEN_HANGUL_TRIGGERS_BY_SKILL)
            - set(SPECIALIST_DOMAIN_HANGUL_TRIGGER_COUNTS)
        )

        for skill in sorted(new_skills):
            with self.subTest(skill=skill):
                self.assertGreater(observed[skill], 0)

    def test_trigger_backed_scripts_are_measured_from_the_shipped_packs(self) -> None:
        counts = _trigger_script_counts()

        # English is the base corpus the catalog is authored in; every other
        # script is here because a pack put it here. Han and Kana were 5 and 1
        # entries before `ja.json` and `zh.json` shipped -- a handful of tokens
        # that could not resolve an ordinary Japanese or Chinese request, which
        # is why the old constant did not claim them.
        self.assertGreater(counts[SCRIPT_LATIN], 1000)
        self.assertGreater(counts[SCRIPT_HANGUL], 100)
        self.assertGreater(counts[SCRIPT_HAN], 50)
        self.assertGreater(counts[SCRIPT_KANA], 50)
        self.assertEqual(
            set(trigger_backed_scripts()),
            {SCRIPT_LATIN, SCRIPT_HANGUL, SCRIPT_HAN, SCRIPT_KANA},
        )

    def test_the_shipped_packs_are_what_makes_a_script_trigger_backed(self) -> None:
        # The link the old constant hid: Hangul, Han, and Kana are supported
        # because ko/ja/zh packs ship, not because a tuple in
        # `input_language.py` says so. Deleting a pack has to remove its script.
        #
        # `id` is the first Latin-script pack and deliberately does not move
        # `trigger_backed_scripts()`: Latin was already backed by the English
        # catalog, so a Latin pack adds a language to a supported script rather
        # than a script to the supported set.
        self.assertEqual(set(shipped_trigger_pack_languages()), {"ko", "ja", "zh", "id"})

    def test_every_routable_skill_is_reachable_in_english(self) -> None:
        missing = [
            definition.name
            for definition in routable_definitions()
            if not any(detect_input_script(trigger) == SCRIPT_LATIN for trigger in definition.triggers)
        ]

        self.assertEqual(missing, [])

    def test_a_latin_sentence_is_latin(self) -> None:
        self.assertEqual(detect_input_script("why is the build failing on main?"), SCRIPT_LATIN)

    def test_a_product_name_does_not_make_a_korean_request_latin(self) -> None:
        # Product names, commands, and identifiers stay Latin inside otherwise
        # non-Latin sentences, so a Latin majority must not win the vote.
        self.assertEqual(detect_input_script("Claude Code로 바로 열어줘"), SCRIPT_HANGUL)

    def test_scripts_without_a_trigger_table_are_marked_model_selection(self) -> None:
        # Cyrillic and Devanagari ship no pack, so a deterministic trigger score
        # is not evidence of intent for them and the contract has to say so --
        # the same statement the Kana and Han rows made before their packs
        # existed.
        for message, expected_script in (
            ("почему сборка падает", "cyrillic"),
            ("बिल्ड क्यों फेल हो रहा है", "devanagari"),
        ):
            with self.subTest(message=message):
                script = detect_input_script(message)
                self.assertEqual(script, expected_script)
                self.assertEqual(routing_language_support(script), SUPPORT_MODEL_SELECTION_REQUIRED)

    def test_trigger_backed_scripts_report_trigger_support(self) -> None:
        for message in (
            "refactor this module",
            "빌드 실패 원인 봐줘",
            "ビルドが失敗した理由を教えて",
            "为什么构建失败了",
        ):
            with self.subTest(message=message):
                self.assertEqual(routing_language_support(detect_input_script(message)), SUPPORT_TRIGGER_BACKED)

    def test_routing_input_language_states_the_boundary(self) -> None:
        payload = routing_input_language("почему сборка падает")

        self.assertEqual(payload["schema_version"], "routing_input_language/v1")
        self.assertEqual(payload["script"], "cyrillic")
        self.assertEqual(payload["trigger_support"], SUPPORT_MODEL_SELECTION_REQUIRED)
        self.assertIn("not evidence of intent", str(payload["boundary"]))
        self.assertIn(SCRIPT_KANA, payload["trigger_backed_scripts"])


if __name__ == "__main__":
    unittest.main()
