"""A request to review a code change reaches code-review, and never memory-sync.

Verdicts as (action, selected skill, top recommendation) measured on d7981d324,
the tree without the guard:

benchmark review task (below): dispatch / memory-sync / memory-sync
review this diff for bugs: clarify / oh-my-hermes / code-review
can you review my PR?: clarify / oh-my-hermes / code-review
does this change introduce a bug?: clarify / oh-my-hermes / feedback-triage
이 diff 리뷰해줘: clarify / oh-my-hermes / code-review
이 PR 버그 있는지 봐줘: clarify / oh-my-hermes / feedback-triage
코드 리뷰 해줘: dispatch / code-review / code-review
check this patch for regressions: clarify / oh-my-hermes / biomedical-evidence

The benchmark task dispatched memory-sync because "the files ... are under
context/" put the token `context` (a memory-store word) beside "Review" (a
curation verb). A path segment no longer counts as a memory store, and a request
the code-review guard reads stands memory curation down.

`tests/fixtures/code_review_request_routing.json` holds the base verdicts of 50
look-alikes saved before the guard was written (must_not_change) and of 25
negatives written after it (overreach_probe). Every one keeps its base verdict.
"""
import json
import unittest
from pathlib import Path

from omh.routing import policy
from omh.routing.localization import normalized_phrase, prepare_routing_text
from omh.wrapper.contract import build_chat_interaction_payload

BENCHMARK_TASK = (
    "Review a code change. The unified diff is in diff.patch in the current directory, and the files as they "
    "are after the change are under context/ (you may read any of them).\n"
    "Decide whether the change introduces a bug.\n"
    "End your reply with exactly one line in one of these two forms, and nothing after it:\n"
    "VERDICT: clean\n"
    "VERDICT: bug <path>:<line>"
)
POSITIVE = (
    BENCHMARK_TASK,
    "review this diff for bugs",
    "can you review my PR?",
    "does this change introduce a bug?",
    "이 diff 리뷰해줘",
    "이 PR 버그 있는지 봐줘",
    "코드 리뷰 해줘",
    "check this patch for regressions",
    "review this PR",
    "review PR 1234 for bugs",
    "find bugs in this diff",
    "이 커밋 리뷰해 주세요",
    "이 diff에서 버그 찾아줘",
    # Both dispatched memory-sync on the base tree: a review request that also
    # names a real memory word ("context", "memory") in another sentence.
    "review this diff for bugs. The context is in the PR description.",
    "can you review my PR? It changes how Hermes stores memory.",
)
# Fix requests keep their lane (ultrawork through the direct-coding guard).
FIX_REQUESTS_KEEP_LANE = (
    ("fix this bug in the login handler", ("dispatch", "ultrawork")),
    ("이 버그 고쳐줘", ("dispatch", "ultrawork")),
)
# memory-sync's own requests, including ones that name a real memory path.
MEMORY_SYNC_KEEPS = (
    "review stale memories and ask me what to keep",
    "메모리 정리해줘",
    "헤르메스가 기억하는 맥락 점검해줘",
    "review stale memories in memories/MEMORY.md",
    "review the context/ notes Hermes remembers",
)
# One stand-down per cue: the same words with something outside the shape.
STAND_DOWN = (
    "review my essay",
    "review the changes",
    "review the change to our refund policy",
    "review this PR and merge it",
    "review my change for the export feature",
    "who should review my PR?",
    "how do I review a pull request well?",
    "review this PR description",
    "can you review my PR strategy?",
    "find bugs in the garden",
    "does this change introduce a delay to the shipment?",
    "check this diff",
    "검토해줘",
    "리뷰해줘",
    "변경사항 검토해 주세요",
    "이 계약 변경 검토해줘",
    "버그 있는지 봐줘",
    "코드 리뷰 일정 잡아줘",
)
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "code_review_request_routing.json").read_text(encoding="utf-8"))


def _route(message: str) -> dict:
    return build_chat_interaction_payload(message, source="discord")["route"]


def _verdict(message: str) -> tuple:
    route = _route(message)
    recommendations = route.get("recommendations") or []
    top = recommendations[0].get("skill") if recommendations else None
    return route.get("action"), route.get("selected_skill"), top


def _query(message: str) -> str:
    return normalized_phrase(prepare_routing_text(message).scoring_text)


class CodeReviewRequestRoutingTests(unittest.TestCase):
    def test_review_requests_dispatch_code_review(self) -> None:
        for message in POSITIVE:
            with self.subTest(message=message[:60]):
                route = _route(message)
                self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "code-review"))

    def test_a_code_review_request_never_selects_memory_sync(self) -> None:
        for message in POSITIVE:
            with self.subTest(message=message[:60]):
                route = _route(message)
                self.assertNotEqual(route["selected_skill"], "memory-sync")
                self.assertNotEqual(route.get("candidate_skill"), "memory-sync")

    def test_benchmark_task_does_not_activate_memory_curation(self) -> None:
        query = _query(BENCHMARK_TASK)
        guards = {rule.id for rule in policy.active_routing_guard_rules(query, policy.routing_tokens(query))}
        self.assertIn("code_review_request_before_generic_clarify", guards)
        self.assertNotIn("memory_curation_before_generic_clarification", guards)

    def test_a_review_request_stands_memory_curation_down(self) -> None:
        for message in POSITIVE[-2:]:
            with self.subTest(message=message):
                query = _query(message)
                self.assertTrue(policy._memory_curation_guard_applies(query, policy.routing_tokens(query)))
                guards = {rule.id for rule in policy.active_routing_guard_rules(query, policy.routing_tokens(query))}
                self.assertNotIn("memory_curation_before_generic_clarification", guards)

    def test_a_path_segment_is_not_a_memory_store(self) -> None:
        query = _query("review the files under context/ for typos")
        self.assertFalse(policy._memory_curation_guard_applies(query, policy.routing_tokens(query)))
        query = _query("review the context notes Hermes remembers")
        self.assertTrue(policy._memory_curation_guard_applies(query, policy.routing_tokens(query)))

    def test_memory_sync_keeps_its_own_requests(self) -> None:
        for message in MEMORY_SYNC_KEEPS:
            with self.subTest(message=message):
                self.assertEqual(_verdict(message)[:2], ("dispatch", "memory-sync"))

    def test_fix_requests_keep_their_lane(self) -> None:
        for message, expected in FIX_REQUESTS_KEEP_LANE:
            with self.subTest(message=message):
                self.assertEqual(_verdict(message)[:2], expected)
                self.assertFalse(
                    "code_review_request_before_generic_clarify"
                    in {r.id for r in policy.active_routing_guard_rules(_query(message), policy.routing_tokens(_query(message)))}
                )

    def test_predicate_reads_one_whole_sentence(self) -> None:
        for message in POSITIVE:
            with self.subTest(message=message[:60]):
                self.assertTrue(policy.code_review_request_guard_applies(_query(message)))
        self.assertEqual(policy.code_review_request_sentence(_query(BENCHMARK_TASK)), "review a code change")

    def test_predicate_stands_down_outside_the_shapes(self) -> None:
        for message in STAND_DOWN:
            with self.subTest(message=message):
                self.assertFalse(policy.code_review_request_guard_applies(_query(message)))

    def test_must_not_change_fixture_keeps_base_verdicts(self) -> None:
        for row in FIXTURE["must_not_change"]:
            with self.subTest(message=row["message"]):
                self.assertEqual(_verdict(row["message"])[:2], (row["action"], row["selected"]))

    def test_overreach_probe_keeps_base_verdicts(self) -> None:
        for row in FIXTURE["overreach_probe"]:
            with self.subTest(message=row["message"]):
                self.assertEqual(_verdict(row["message"])[:2], (row["action"], row["selected"]))

    def test_guard_is_classified_and_injected(self) -> None:
        from omh.routing.recommend import _GUARDRAIL_CANDIDATE_INJECTION_IDS

        self.assertIn("code_review_request_before_generic_clarify", policy.GUARD_DISPATCH_TRUST)
        self.assertIn("code_review_request_before_generic_clarify", _GUARDRAIL_CANDIDATE_INJECTION_IDS)


if __name__ == "__main__":
    unittest.main()
