"""Re-fixed commits reach `instinct-ledger`; two review rules; other routing stays put.

Base verdicts below were measured on 65796e68f with
`build_chat_interaction_payload(msg, source="discord")["route"]` (action,
selected_skill, candidate_skill). Two requests reach the ledger (it takes a re-fix phrase AND a lesson cue;
"nightly lessons from merged work" went back to its base route, clarify on
verification-gate). Before the fix they were fallback and clarify on code-review; the thirty messages use the same nouns (fix, lesson, commit,
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

# The reviewer's 30 messages (base verdicts, 65796e68f); 9 of them used to select the ledger.
REVIEWER_30 = (
    ("Review yesterday's billing patch for an off-by-one error.", 'clarify', 'oh-my-hermes', 'code-review'),
    ('Fix the release branch merge and keep the changelog entries.', 'dispatch', 'ultrawork', 'ultrawork'),
    ("Turn yesterday's commits into customer-facing release notes.", 'dispatch', 'content-operator', 'content-operator'),
    ('Check whether the last commit fixed the regression in export.', 'dispatch', 'verification-gate', 'verification-gate'),
    ("List the merged PR titles for yesterday's standup.", 'clarify', 'oh-my-hermes', 'verification-gate'),
    ('Write a lesson for onboarding engineers to git commit signing.', 'clarify', 'oh-my-hermes', 'lifecycle-growth'),
    ('Review my lesson plan before I commit it to the course repo.', 'clarify', 'oh-my-hermes', 'code-review'),
    ('Merge the lesson-plan branch once its tests pass.', 'clarify', 'oh-my-hermes', 'verification-gate'),
    ('Fix the script that counts commits made yesterday.', 'clarify', 'oh-my-hermes', 'ultrawork'),
    ("Review the fixes in yesterday's security patch, not our habits.", 'clarify', 'oh-my-hermes', 'code-review'),
    ("Shorten the re-fixed commits' messages to fit our subject limit.", 'clarify', 'oh-my-hermes', 'ultrawork'),
    ('Translate the phrase fixes of fixes into Korean for this article.', 'fallback', 'oh-my-hermes', 'oh-my-hermes'),
    ('Fix the display of lessons from merged work in the report UI.', 'fallback', 'oh-my-hermes', 'oh-my-hermes'),
    ('The test is named fixes of fixes; review its assertion failure.', 'clarify', 'oh-my-hermes', 'code-review'),
    ('Do not extract lessons from merged work; fix the merge conflict instead.', 'dispatch', 'git-workflow', 'git-workflow'),
    ('어제 배포한 수정에서 로그인 에러가 났어요. 원인 찾아주세요.', 'dispatch', 'browser-operator', 'browser-operator'),
    ('리뷰 받은 커밋을 합치고 테스트를 실행해 주세요.', 'dispatch', 'code-review', 'code-review'),
    ('어제 머지한 PR 제목을 회의 자료에 넣어 주세요.', 'clarify', 'oh-my-hermes', 'meeting-brief'),
    ('교훈 문서 오타 수정 후 커밋해 주세요.', 'clarify', 'oh-my-hermes', 'materials-package'),
    ('커밋 서명에 관한 수업 교안을 리뷰해 주세요.', 'clarify', 'oh-my-hermes', 'code-review'),
    ('지난주 머지 충돌을 고친 내역을 릴리스 노트로 써 주세요.', 'clarify', 'oh-my-hermes', 'verification-gate'),
    ('어제 수업에서 쓴 git 예제의 커밋 메시지를 고쳐 주세요.', 'clarify', 'oh-my-hermes', 'build-failure-triage'),
    ('다시 고친 커밋 메시지가 너무 길어요. 짧게 바꿔 주세요.', 'clarify', 'oh-my-hermes', 'voice-operator'),
    ('다시 고친 것들 중 README 오타만 이번 릴리스에 머지해 주세요.', 'clarify', 'oh-my-hermes', 'code-review'),
    ('다시 고친 커밋을 취소하고 이전 버전으로 롤백해 주세요.', 'clarify', 'oh-my-hermes', 'deploy-and-monitor'),
    ('다시 고친 커밋에서 파일 하나가 빠졌어요. 추가해 주세요.', 'clarify', 'oh-my-hermes', 'materials-package'),
    ('교훈 목록 API의 merge 필드 타입을 고쳐 주세요.', 'dispatch', 'oh-my-hermes', 'oh-my-hermes'),
    ('어제 커밋한 강의 자료를 코드 리뷰해 주세요.', 'dispatch', 'code-review', 'code-review'),
    ('이번 리뷰 의견을 반영하고 fix 커밋으로 올려 주세요.', 'dispatch', 'code-review', 'code-review'),
    ('배포 브랜치에 어제 고친 커밋을 cherry-pick 해 주세요.', 'clarify', 'oh-my-hermes', 'build-failure-triage'),
)

# 20 messages holding a re-fix phrase without asking for lessons (base verdicts).
REFIX_WITHOUT_LESSONS = (
    ('Revert the fixes of fixes on the release branch.', 'clarify', 'oh-my-hermes', 'ultrawork'),
    ('Squash the fix of fix commits before we open the PR.', 'clarify', 'oh-my-hermes', 'ultrawork'),
    ('Rename the branch that holds the re-fixed commits.', 'dispatch', 'ultrawork', 'ultrawork'),
    ('Cherry-pick the refixed commits onto hotfix/2.1.', 'dispatch', 'git-workflow', 'git-workflow'),
    ('Who authored the fixes of fixes in the payments module?', 'clarify', 'oh-my-hermes', 'ultrawork'),
    ('Open an issue titled fix of fix for the flaky login test.', 'clarify', 'oh-my-hermes', 'build-failure-triage'),
    ('Add a CI check that blocks fix of fix commits from merging.', 'clarify', 'oh-my-hermes', 'build-failure-triage'),
    ('Reword the subject of the re-fixed commits to start with a verb.', 'clarify', 'oh-my-hermes', 'ultrawork'),
    ('Show me the diff of the refixed commits from last night.', 'clarify', 'oh-my-hermes', 'live-info-operator'),
    ('Delete the fixes of fixes from the changelog draft.', 'clarify', 'oh-my-hermes', 'ultrawork'),
    ('Translate fixes of fixes into French for the docs page.', 'fallback', 'oh-my-hermes', 'oh-my-hermes'),
    ('Write a regex that detects the phrase fix of fix in commit subjects.', 'fallback', 'oh-my-hermes', 'oh-my-hermes'),
    ('Run the tests again on the re-fixed commits and report failures.', 'dispatch', 'verification-gate', 'verification-gate'),
    ('Tag the refixed commits as v2.0.1-rc1.', 'clarify', 'oh-my-hermes', 'release-cut'),
    ('다시 고친 커밋들을 하나로 합쳐 주세요.', 'fallback', 'oh-my-hermes', 'oh-my-hermes'),
    ('다시 고친 커밋 목록을 CSV로 내보내 주세요.', 'dispatch', 'oh-my-hermes', 'oh-my-hermes'),
    ('다시 고친 것들만 따로 브랜치로 빼 주세요.', 'fallback', 'oh-my-hermes', 'oh-my-hermes'),
    ('다시 고친 커밋의 작성자에게 슬랙으로 알려 주세요.', 'clarify', 'oh-my-hermes', 'automation-blueprint'),
    ('다시 고친 것들 때문에 빌드가 깨졌는지 확인해 주세요.', 'fallback', 'oh-my-hermes', 'oh-my-hermes'),
    ('다시 고친 커밋을 main에 리베이스해 주세요.', 'fallback', 'oh-my-hermes', 'oh-my-hermes'),
)

# Known limit, not pinned: phrases cannot tell negation apart, so these still reach
# the ledger because they hold a re-fix phrase and a lesson cue.
NEGATIONS_THAT_STILL_FLIP = (
    'Do not write lessons about the fixes of fixes, just revert them.',
    'No lessons needed for the re-fixed commits; squash them and push.',
    '교훈은 필요 없고 다시 고친 커밋만 롤백해 주세요.',
    'Skip the lessons and the retro, simply delete the fix of fix commits.',
    "I don't want any lesson from the refixed commits, cherry-pick them to release.",
)

# One negative per English trigger phrase: the words appear, but only inside
# longer words, so the phrase was not said.
PHRASE_NEGATIVES = {
    "fix of fix": "the fix of fixing the build should wait",
    "fixes of fixes": "list the fixes of fixesque names",
    "re-fixed commits": "list the re-fixed commitsmen",
    "refixed commits": "list the refixed commitsmen",
}


def _route(message: str) -> dict[str, object]:
    return build_chat_interaction_payload(message, source="discord")["route"]


def _definition(name: str):
    return next(definition for definition in builtin_definitions() if definition.name == name)


class InstinctLedgerRoutingTests(unittest.TestCase):
    def test_the_two_requests_dispatch_the_ledger(self) -> None:
        for message in REACHES_THE_LEDGER:
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual(route["action"], "dispatch")
                self.assertEqual(route["selected_skill"], SKILL)

    def test_a_lesson_request_without_a_re_fix_phrase_keeps_its_base_route(self) -> None:
        route = _route("nightly lessons from merged work")
        self.assertEqual((route["action"], route["selected_skill"], route["candidate_skill"]), ("clarify", "oh-my-hermes", "verification-gate"))

    def test_a_re_fix_phrase_without_a_lesson_cue_never_dispatches_the_ledger(self) -> None:
        self.assertEqual(len(REVIEWER_30), 30)
        self.assertEqual(len(REFIX_WITHOUT_LESSONS), 20)
        for message, action, selected, candidate in REVIEWER_30 + REFIX_WITHOUT_LESSONS:
            with self.subTest(message=message):
                route = _route(message)
                self.assertNotEqual(route["selected_skill"], SKILL)
                self.assertEqual((route["action"], route["selected_skill"], route["candidate_skill"]), (action, selected, candidate))

    def test_negation_is_a_known_limit(self) -> None:
        self.assertEqual(len(NEGATIONS_THAT_STILL_FLIP), 5)
        for message in NEGATIONS_THAT_STILL_FLIP:
            with self.subTest(message=message):
                self.assertEqual(_route(message)["selected_skill"], SKILL)

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
        self.assertNotIn("on the first-parent history of the default branch", body)
        for needle in (
            "non-merge fix commits in the window that are reachable from the default branch",
            "follow the first-parent merges only here",
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
