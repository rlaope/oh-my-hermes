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
    )

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
