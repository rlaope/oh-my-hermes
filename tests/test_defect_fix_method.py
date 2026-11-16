"""A request to fix a code defect carries OMH's debugging method; every other turn reads as before.

Hermes' skills index tells the model not to open process skills, so the method of
`omh-app-debugging` and `omh-verification-gate` reaches a coding turn only as this
block (`defect_fix_method`). The negative cases assert absence on questions,
reviews, features, non-code fixes and host-written turns, and the byte-identity
case compares a whole non-fix context with the block switched off.
"""
from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from unittest import mock

from omh.plugin_bundle.omh import defect_fix_method
from omh.plugin_bundle.omh.defect_fix_method import (
    METHOD_BLOCK,
    asks_to_fix_code,
    claim_method_block,
    reset_method_block_state,
)
from omh.plugin_bundle.omh.hooks import llm_hooks
from omh.plugin_bundle.omh.plan_follow_on import reset_plan_follow_on_state
from omh.plugin_bundle.omh.skill_shortlist import reset_candidate_line_state

HEAD = "[OMH Debugging Method]"

FIX_REQUESTS = (
    "python3 -m unittest tests.test_invoice fails: the tax on some invoices comes out wrong. Find the cause and fix it.",
    "load_lots(inventory, path) then inventory.oldest_lot_age(sku, today) crashes with a TypeError. Fix it.",
    "minikit/duration.py parse_duration() gives wrong values. Make python3 -m unittest tests.test_duration pass.",
    "the login endpoint returns 500 since yesterday, can you debug it?",
    "there is a bug in the checkout code, please fix it",
    "make the CI tests pass again",
    "fix stockroom.inventory.load_lots",
    "이 함수 버그 고쳐줘",
    "테스트가 실패하는데 원인 찾아서 수정해줘",
)

NOT_FIX_REQUESTS = (
    # Questions about code, not a change.
    "What is a race condition?",
    "Explain how Python's GIL works",
    "why does this test fail sometimes?",
    # A review, a feature, a refactor: work on code that is not a defect fix.
    "review this PR for bugs before merge",
    "add a dark mode toggle to the settings page",
    "add a function stockroom.report.monthly_totals(sales, year) that returns 12 totals",
    # A fix of something that is not code.
    "Fix the leaky faucet in my bathroom before the guests arrive",
    "Can you fix my resume formatting?",
    "fix the typo in the README",
    "fix the typo in readme.md",
    "fix the link to example.com in the newsletter",
    "fix my sleep schedule",
    # Other work.
    "plan my weekend trip to Busan",
    "write a blog post about our Q3 results",
    "내일 회의 일정 정리해줘",
    "",
)


class PredicateTests(unittest.TestCase):
    def test_a_request_to_fix_code_is_read_as_one(self) -> None:
        for message in FIX_REQUESTS:
            with self.subTest(message=message):
                self.assertTrue(asks_to_fix_code(message))

    def test_questions_reviews_features_and_non_code_fixes_are_not(self) -> None:
        for message in NOT_FIX_REQUESTS:
            with self.subTest(message=message):
                self.assertFalse(asks_to_fix_code(message))

    def test_a_non_string_is_not_a_request(self) -> None:
        for value in (None, 3, ["fix the bug in the code"], b"fix the bug in the code"):
            with self.subTest(value=value):
                self.assertFalse(asks_to_fix_code(value))  # type: ignore[arg-type]

    def test_a_change_verb_alone_or_a_code_object_alone_is_not_enough(self) -> None:
        self.assertFalse(asks_to_fix_code("please fix it"))
        self.assertFalse(asks_to_fix_code("the parse_amount() function and its tests"))


class BlockTests(unittest.TestCase):
    def test_the_block_carries_the_method_and_names_its_skills(self) -> None:
        self.assertTrue(METHOD_BLOCK.startswith(HEAD))
        for step in ("Reproduce first", "where it is first produced", "other valid variants", "whole test suite"):
            with self.subTest(step=step):
                self.assertIn(step, METHOD_BLOCK)
        self.assertIn("omh-app-debugging", METHOD_BLOCK)
        self.assertIn("omh-verification-gate", METHOD_BLOCK)
        self.assertIn("symptom mask", METHOD_BLOCK)

    def test_the_block_stays_short(self) -> None:
        # Rides once per session on a fix request only; a growth past this is a review decision.
        self.assertLessEqual(len(METHOD_BLOCK), 900)

    def test_claimed_once_per_session(self) -> None:
        reset_method_block_state()
        self.addCleanup(reset_method_block_state)
        self.assertTrue(claim_method_block("s1"))
        self.assertFalse(claim_method_block("s1"))
        self.assertTrue(claim_method_block("s2"))
        # No session id: nothing to remember it by, so it is always shown.
        self.assertTrue(claim_method_block(""))
        self.assertTrue(claim_method_block(""))

    def test_the_memory_is_bounded(self) -> None:
        reset_method_block_state()
        self.addCleanup(reset_method_block_state)
        for index in range(defect_fix_method._MAX_REMEMBERED_SESSIONS + 10):
            claim_method_block(f"s{index}")
        self.assertEqual(len(defect_fix_method._shown), defect_fix_method._MAX_REMEMBERED_SESSIONS)
        # The oldest was forgotten, so it gets the block again.
        self.assertTrue(claim_method_block("s0"))


class PreLlmCallTests(unittest.TestCase):
    session = "defect-fix-method-session"

    def context(self, message: str, *, first: bool = True, session: str | None = None, **kwargs: object) -> str:
        with TemporaryDirectory() as tmp:
            payload = llm_hooks.pre_llm_call(
                omh_home=tmp, hermes_home=tmp, session_id=session or self.session, user_message=message,
                is_first_turn=first, platform="cli",
                conversation_history=[{"role": "user", "content": message}], **kwargs,
            ) or {}
        return str(payload.get("context", ""))

    def setUp(self) -> None:
        for reset in (llm_hooks._reset_awareness_section_state, reset_candidate_line_state,
                      reset_plan_follow_on_state, reset_method_block_state):
            reset()
            self.addCleanup(reset)

    def test_a_fix_request_carries_the_block_once_per_session(self) -> None:
        context = self.context(FIX_REQUESTS[0])
        self.assertEqual(context.count(HEAD), 1)
        self.assertIn(METHOD_BLOCK, context)
        # Inside the OMH fence, as automated context.
        self.assertLess(context.index(llm_hooks.OMH_CONTEXT_FENCE_OPEN), context.index(HEAD))
        self.assertLess(context.index(HEAD), context.index(llm_hooks.OMH_CONTEXT_FENCE_CLOSE))
        later = self.context(FIX_REQUESTS[1], first=False)
        self.assertNotIn(HEAD, later)
        # Another session gets its own.
        self.assertIn(HEAD, self.context(FIX_REQUESTS[1], first=False, session="another-session"))

    def test_every_other_request_gets_no_block(self) -> None:
        for message in NOT_FIX_REQUESTS:
            with self.subTest(message=message):
                reset_method_block_state()
                self.assertNotIn(HEAD, self.context(message))

    def test_a_non_fix_turn_renders_exactly_what_it_rendered_before(self) -> None:
        for message in ("review this PR for bugs before merge", "plan my weekend trip to Busan"):
            with self.subTest(message=message):
                with_block = self.context(message)
                for reset in (llm_hooks._reset_awareness_section_state, reset_candidate_line_state,
                              reset_plan_follow_on_state):
                    reset()
                with mock.patch.object(llm_hooks, "asks_to_fix_code", lambda _message: False):
                    without_block = self.context(message)
                self.assertEqual(with_block, without_block)

    def test_a_host_written_turn_gets_no_block(self) -> None:
        # A finished background process opens the turn: there is no request to read.
        notice = "[Background process proc_1 finished with exit code 1] fix the failing test in tests/test_x.py"
        with TemporaryDirectory() as tmp:
            payload = llm_hooks.pre_llm_call(
                omh_home=tmp, hermes_home=tmp, session_id=self.session, user_message=notice, is_first_turn=False,
                platform="cli",
                conversation_history=[{"role": "user", "content": notice, "display_kind": "process_complete"}],
            ) or {}
        context = str(payload.get("context", ""))
        self.assertNotIn(HEAD, context)

    def test_awareness_off_gets_no_block(self) -> None:
        self.assertNotIn(HEAD, self.context(FIX_REQUESTS[0], include_omh_awareness=False))


if __name__ == "__main__":
    unittest.main()
