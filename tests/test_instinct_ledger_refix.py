"""Re-fixed commits reach `instinct-ledger`; two review rules; other routing stays put.

Base verdicts below were measured on 65796e68f with
`build_chat_interaction_payload(msg, source="discord")["route"]` (action,
selected_skill, candidate_skill). The three requests were fallback (generic
router, low), clarify on code-review (high) and clarify on verification-gate
(medium) there; the thirty messages use the same nouns (fix, lesson, commit,
merge, review) for other work and must keep the verdict they had.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.routing.chat import _INSTINCT_LEDGER_HISTORY_PHRASES
from omh.skills.catalog import builtin_definitions
from omh.skills.packaging import builtin_skill_reference_templates
from omh.wrapper.contract import build_chat_interaction_payload

SKILL = "instinct-ledger"
REFERENCE_PATH = "references/refixed-commits.md"

REACHES_THE_LEDGER = (
    "어제 머지된 커밋 중에 다시 고친 것들 찾아서 교훈으로 정리해줘",
    "review yesterday's merged commits for fixes of fixes and write the lessons",
    "nightly lessons from merged work",
)

# (message, action, selected_skill, candidate_skill) at the base commit.
MUST_NOT_CHANGE = (
    ('review this PR', 'clarify', 'oh-my-hermes', 'code-review'),
    ('review this pull request for bugs and missing tests', 'dispatch', 'ultraqa', 'ultraqa'),
    ('fix the merge conflict in my branch', 'dispatch', 'ultrawork', 'ultrawork'),
    ('resolve the merge conflict and push', 'dispatch', 'git-workflow', 'git-workflow'),
    ("write release notes from yesterday's commits", 'dispatch', 'content-operator', 'content-operator'),
    ('what did we merge yesterday', 'fallback', 'oh-my-hermes', 'oh-my-hermes'),
    ('list the commits merged last week', 'clarify', 'oh-my-hermes', 'reliability-review'),
    ('summarize the lessons from this book chapter', 'clarify', 'oh-my-hermes', 'instinct-ledger'),
    ('write a lesson plan for teaching fractions', 'clarify', 'oh-my-hermes', 'plan'),
    ('fix the failing test in the checkout module', 'dispatch', 'ultrawork', 'ultrawork'),
    ('fix a typo in the README', 'fallback', 'oh-my-hermes', 'oh-my-hermes'),
    ('rewrite this commit message to be shorter', 'fallback', 'oh-my-hermes', 'oh-my-hermes'),
    ('squash the last three commits', 'clarify', 'oh-my-hermes', 'git-workflow'),
    ('revert the merge commit from yesterday', 'clarify', 'oh-my-hermes', 'release-cut'),
    ('review the merged work of last sprint and rate its quality', 'clarify', 'oh-my-hermes', 'agent-ops-review'),
    ('who merged the auth change', 'clarify', 'oh-my-hermes', 'verification-gate'),
    ('nightly build is failing, look at it', 'clarify', 'oh-my-hermes', 'build-failure-triage'),
    ('what lessons did we learn from the outage', 'clarify', 'oh-my-hermes', 'workflow-learning'),
    ("write a postmortem for yesterday's incident", 'clarify', 'oh-my-hermes', 'reliability-review'),
    ('show me the git log for the last 3 days', 'clarify', 'oh-my-hermes', 'automation-blueprint'),
    ('어제 머지된 PR 리뷰해줘', 'clarify', 'oh-my-hermes', 'code-review'),
    ('커밋 메시지 고쳐줘', 'clarify', 'oh-my-hermes', 'buzz'),
    ('머지 충돌 해결해줘', 'clarify', 'oh-my-hermes', 'verification-gate'),
    ('어제 커밋으로 릴리스 노트 써줘', 'clarify', 'oh-my-hermes', 'content-operator'),
    ('이 PR 고쳐야 할 부분 알려줘', 'clarify', 'oh-my-hermes', 'browser-operator'),
    ('다시 고쳐줘 이 함수', 'fallback', 'oh-my-hermes', 'oh-my-hermes'),
    ('오늘 머지된 작업 요약해줘', 'clarify', 'oh-my-hermes', 'live-info-operator'),
    ('교훈을 정리해서 회고 문서 만들어줘', 'dispatch', 'deep-interview', 'deep-interview'),
    ('커밋 히스토리 정리해줘', 'clarify', 'oh-my-hermes', 'operating-rhythm'),
    ('고친 것들 목록 보여줘', 'dispatch', 'oh-my-hermes', 'oh-my-hermes'),
)

# One negative per English trigger phrase: the words appear, but only inside
# longer words, so the phrase was not said.
PHRASE_NEGATIVES = {
    "fix of fix": "the fix of fixing the build should wait",
    "fixes of fixes": "list the fixes of fixesque names",
    "re-fixed commits": "list the re-fixed commitsmen",
    "refixed commits": "list the refixed commitsmen",
    "lessons from merged work": "lessons from merged workflows in a retro",
}


def _route(message: str) -> dict[str, object]:
    return build_chat_interaction_payload(message, source="discord")["route"]


def _definition(name: str):
    return next(definition for definition in builtin_definitions() if definition.name == name)


class InstinctLedgerRoutingTests(unittest.TestCase):
    def test_the_three_requests_dispatch_the_ledger(self) -> None:
        for message in REACHES_THE_LEDGER:
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual(route["action"], "dispatch")
                self.assertEqual(route["selected_skill"], SKILL)

    def test_thirty_other_uses_of_the_same_nouns_keep_their_base_verdict(self) -> None:
        self.assertEqual(len(MUST_NOT_CHANGE), 30)
        for message, action, selected, candidate in MUST_NOT_CHANGE:
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual(
                    (route["action"], route["selected_skill"], route["candidate_skill"]),
                    (action, selected, candidate),
                )

    def test_every_english_trigger_phrase_has_a_negative_case(self) -> None:
        english = {phrase for phrase in _INSTINCT_LEDGER_HISTORY_PHRASES if phrase.isascii()}
        self.assertEqual(english, set(PHRASE_NEGATIVES))
        for phrase, message in PHRASE_NEGATIVES.items():
            with self.subTest(phrase=phrase):
                self.assertNotEqual(_route(message)["selected_skill"], SKILL)

    def test_a_korean_phrase_inside_another_sentence_shape_does_not_dispatch(self) -> None:
        for message in ("다시 고친 것 같은데 또 깨져", "다시 고친 것처럼 보여", "다시 고쳐줘 이 함수"):
            with self.subTest(message=message):
                self.assertNotEqual(_route(message)["selected_skill"], SKILL)

    def test_a_single_noun_never_dispatches_the_ledger(self) -> None:
        for message in ("fix the bug", "write a lesson", "review the commit", "merge it", "교훈 정리해줘"):
            with self.subTest(message=message):
                self.assertNotEqual(_route(message)["selected_skill"], SKILL)


class InstinctLedgerReferenceTests(unittest.TestCase):
    def test_the_reference_ships_and_the_skill_points_at_it(self) -> None:
        paths = {(template.skill_name, template.relative_path) for template in builtin_skill_reference_templates()}
        self.assertIn((SKILL, REFERENCE_PATH), paths)
        self.assertTrue(any(REFERENCE_PATH in line for line in _definition(SKILL).final_checklist))

    def test_the_reference_carries_the_method(self) -> None:
        body = next(
            template.content
            for template in builtin_skill_reference_templates()
            if template.skill_name == SKILL and template.relative_path == REFERENCE_PATH
        )
        for needle in (
            "git blame --porcelain -L",
            "<fix>^",
            "first-parent merge",
            "upper bound",
            "Two pairs from the same day count once",
            "the two commits",
            "the days seen",
            "REVIEW.md",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, body)


class CodeReviewQualityBarTests(unittest.TestCase):
    def test_the_two_review_rules_are_in_the_quality_bar(self) -> None:
        bar = " ".join(_definition("code-review").quality_bar)
        self.assertIn("A fix reaches every place of the same shape", bar)
        self.assertIn("means unknown, never empty, none, or equal", bar)
        self.assertIn("fails closed", bar)


if __name__ == "__main__":
    unittest.main()
