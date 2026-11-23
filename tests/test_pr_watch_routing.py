"""A request to wait on one pull request reaches `github-event-ops`' PR watch recipe.

Measured on `ad5abb69a` (origin/main) before the `pr_watch_before_loop_or_ultrawork`
guard, chat route:

- "watch PR 42 until its checks finish": clarify (candidates led by ultrawork).
- "keep an eye on my pull request until CI is done": dispatch `ultrawork`.
- "babysit PR #3137 until it is merged", "monitor the PR until CI passes": clarify.
- "PR 42 체크 끝날 때까지 지켜봐줘", "PR 올렸으니 CI 끝날 때까지 지켜봐줘",
  "이 PR 머지될 때까지 지켜보다가 알려줘": clarify.

The neighbours keep the verdicts they had there: "review PR 42" dispatches
`code-review`, "monitor CI on main until the build is green" dispatches
`verification-gate`, and "watch the PR queue", "watch this video" and "how do
I watch a PR until checks finish?" clarify without `github-event-ops`.
"""

from __future__ import annotations

import unittest

from omh.routing import policy
from omh.wrapper.contract import build_chat_interaction_payload


def _route(message: str) -> dict:
    return build_chat_interaction_payload(message, source="discord")["route"]


def _applies(message: str) -> bool:
    return policy.pr_watch_guard_applies(policy.normalized_phrase(message))


class PrWatchRoutingTests(unittest.TestCase):
    WATCH_REQUESTS = (
        "watch PR 42 until its checks finish",
        "watch PR 42 until its checks finish and tell me",
        "keep an eye on my pull request until CI is done",
        "babysit PR #3137 until it is merged",
        "monitor the PR until CI passes",
        "PR 42 체크 끝날 때까지 지켜봐줘",
        "PR 올렸으니 CI 끝날 때까지 지켜봐줘",
        "이 PR 머지될 때까지 지켜보다가 알려줘",
        "wait for the checks on PR 42 to finish",
        "PR #12 머지될 때까지 기다려줘",
    )

    # The PR is mentioned, but something else is watched, or the PR is what the
    # wait produces rather than what it waits on.
    SOMETHING_ELSE_WATCHED = (
        "monitor PR review turnaround times until the end of the quarter and report",
        "배포 끝날 때까지 지켜보다가 PR 올려줘",
        "PR 머지 완료되면 배포 모니터링해줘",
        "keep an eye on the staging deploy until it is green, the PR is already merged",
        "monitor the release until it ships, then open a PR",
        "watch the build on main until it passes and then merge my PR",
        "wait for the deploy to finish before you merge the PR",
        "keep an eye on CI until it's green, I'll open the PR later",
        "watch the PR count until the sprint is done",
        "monitor how long PRs wait until review",
        "monitor PR throughput until Friday",
        "watch the docs site until it rebuilds after my PR merges",
        "wait until the migration finishes, then open the PR",
        "watch the nightly job until it passes; the fix PR is merged",
        "스테이징 배포 끝날 때까지 지켜보고 PR 머지해줘",
        "릴리즈 끝날 때까지 기다렸다가 PR 올려줘",
        "CI 끝날 때까지 기다렸다가 PR 만들어줘",
        "PR 리뷰 통계 이번 분기 끝날 때까지 모니터링해줘",
        "PR 올리고 나서 로그 끝날 때까지 지켜봐줘",
        "테스트 끝날 때까지 기다렸다가 PR 리뷰 요청해줘",
        "PR 올리기 전에 빌드 끝날 때까지 지켜봐줘",
    )

    def test_the_pr_must_be_what_is_watched(self) -> None:
        for message in self.SOMETHING_ELSE_WATCHED:
            with self.subTest(message=message):
                self.assertFalse(_applies(message))
                route = _route(message)
                self.assertNotEqual((route["action"], route["selected_skill"]), ("dispatch", "github-event-ops"))

    def test_waits_on_one_pr_dispatch_github_event_ops(self) -> None:
        for message in self.WATCH_REQUESTS:
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "github-event-ops"))
                self.assertTrue(_applies(message))

    def test_the_guard_needs_all_three_parts(self) -> None:
        for message in (
            "watch the PR queue until Friday",       # a queue, not one PR
            "watch this video until it finishes",    # no PR
            "유튜브 영상 끝날 때까지 지켜봐줘",          # no PR
            "how do I watch a PR until checks finish?",  # a how-to question
            "how do CI checks work?",                # no PR, no watch
            "watch out for this PR, it breaks the build",  # no settle cue
            "review PR 42",                          # no watch verb
            "wait, is PR 42 merged?",                # `wait` alone is not a wait verb
            "watch the prompt until it finishes",    # `pr` inside a word is not a PR
            "monitor CI on main until the build is green",  # no PR
        ):
            with self.subTest(message=message):
                self.assertFalse(_applies(message))

    def test_owned_neighbours_keep_their_routes(self) -> None:
        for message, verdict in (
            ("review PR 42", ("dispatch", "code-review")),
            ("monitor CI on main until the build is green", ("dispatch", "verification-gate")),
        ):
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual((route["action"], route["selected_skill"]), verdict)


if __name__ == "__main__":
    unittest.main()
