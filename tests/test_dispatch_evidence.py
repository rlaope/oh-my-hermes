"""A confident score dispatches only when the winner's own labels name the job.

`routing/dispatch_evidence.py` reads a scored winner's matched labels and
classifies the evidence; a `weak` winner becomes a clarify with the
`weak_dispatch_evidence` reason and a candidate handoff. These tests pin the
classifier on label sets directly, and the route-level shape on sentences built
from the collisions the design traced: everyday words that are also trigger
tokens ("before I merge"), and a guard boost carrying a skill with no evidence
of its own ("last time").
"""

from __future__ import annotations

import unittest

from omh.routing.candidate_handoff import WEAK_DISPATCH_EVIDENCE
from omh.routing.chat import route_chat_message
from omh.routing.dispatch_evidence import (
    EVIDENCE_DIRECT,
    EVIDENCE_EXPLICIT,
    EVIDENCE_FAST_PATH,
    EVIDENCE_NON_ASCII_EXEMPT,
    EVIDENCE_TRIGGER_PHRASE,
    EVIDENCE_TRUSTED_GUARD,
    EVIDENCE_WEAK,
    dispatch_evidence,
    own_evidence_score,
)
from omh.routing import policy
from omh.routing.policy import GUARD_CONTEXT_ONLY, GUARD_DISPATCH_TRUST, GUARD_TRUSTED

TRUST = {"guard:trusted_shape": GUARD_TRUSTED, "guard:topic_words": GUARD_CONTEXT_ONLY}


def _classify(labels: list[str], *, others: list[list[str]] = (), message: str = "plain ascii") -> str:
    return dispatch_evidence(
        {"skill": "x", "score": 20, "matched": labels},
        [{"skill": f"o{index}", "score": 9, "matched": other} for index, other in enumerate(others)],
        message=message,
        guard_trust=TRUST,
    )


class DispatchEvidenceClassifierTests(unittest.TestCase):
    def test_explicit_direct_and_domain_labels_keep_the_dispatch(self) -> None:
        self.assertEqual(_classify(["explicit_invocation", "name:x"]), EVIDENCE_EXPLICIT)
        self.assertEqual(_classify(["direct:x_specialist", "trigger:review"]), EVIDENCE_DIRECT)
        self.assertEqual(_classify(["domain:contract"]), EVIDENCE_DIRECT)

    def test_a_label_the_scorer_does_not_produce_is_a_fast_path(self) -> None:
        self.assertEqual(_classify(["operator_surface_fast_path:status"]), EVIDENCE_FAST_PATH)

    def test_an_own_phrase_dispatches_only_when_no_other_skill_said_one(self) -> None:
        self.assertEqual(_classify(["trigger:code review", "trigger:review"]), EVIDENCE_TRIGGER_PHRASE)
        self.assertEqual(_classify(["trigger:$ulw"]), EVIDENCE_TRIGGER_PHRASE)
        self.assertEqual(_classify(["name:code review"]), EVIDENCE_TRIGGER_PHRASE)
        # Two skills each said a phrase of their own: a choice, not a decision.
        self.assertEqual(
            _classify(["trigger:code review"], others=[["trigger:security review"]]),
            EVIDENCE_WEAK,
        )

    def test_tokens_alone_never_dispatch_however_rare(self) -> None:
        self.assertEqual(_classify(["trigger:segfault", "trigger:coredump", "trigger:review"]), EVIDENCE_WEAK)
        self.assertEqual(_classify(["name:plan", "trigger:plan"]), EVIDENCE_WEAK)

    def test_a_trusted_guard_dispatches_on_its_own(self) -> None:
        # "fix the login bug": an imperative plus a code object, no trigger word.
        self.assertEqual(_classify(["guard:trusted_shape"]), EVIDENCE_TRUSTED_GUARD)

    def test_a_context_only_or_unknown_guard_does_not(self) -> None:
        self.assertEqual(_classify(["guard:topic_words", "trigger:review", "trigger:before"]), EVIDENCE_WEAK)
        self.assertEqual(_classify(["guard:unlisted", "trigger:segfault"]), EVIDENCE_WEAK)

    def test_non_ascii_input_is_left_to_the_frozen_tables(self) -> None:
        self.assertEqual(_classify(["trigger:리뷰"], message="PR 리뷰 좀 해줘"), EVIDENCE_NON_ASCII_EXEMPT)

    def test_own_evidence_counts_neither_guards_nor_metadata(self) -> None:
        self.assertEqual(own_evidence_score(["guard:x", "metadata:a", "metadata:b"]), 0)
        self.assertEqual(own_evidence_score(["trigger:code review", "trigger:review", "name:x"]), 6 + 3 + 5)


class GuardDispatchTrustTableTests(unittest.TestCase):
    def test_every_guard_rule_is_classified(self) -> None:
        # A new guard must be a visible choice, not a silent default.
        rules = {value.id for value in vars(policy).values() if isinstance(value, policy.RoutingGuardRule)}
        self.assertEqual(rules, set(GUARD_DISPATCH_TRUST))

    def test_every_entry_is_a_known_trust_with_a_reason(self) -> None:
        for guard_id, (trust, reason) in GUARD_DISPATCH_TRUST.items():
            with self.subTest(guard=guard_id):
                self.assertIn(trust, {GUARD_TRUSTED, GUARD_CONTEXT_ONLY})
                self.assertTrue(reason.strip())


class WeakEvidenceRouteTests(unittest.TestCase):
    """Negative half: a high score built from everyday words does not dispatch."""

    def _assert_weak_clarify(self, message: str) -> dict:
        route = route_chat_message(message, source="discord")
        self.assertEqual(route["action"], "clarify")
        self.assertEqual(route["selected_skill"], "oh-my-hermes")
        self.assertEqual(route.get("ambiguity_kind"), WEAK_DISPATCH_EVIDENCE)
        handoff = route["candidate_handoff"]
        self.assertIn(WEAK_DISPATCH_EVIDENCE, handoff["reasons"])
        self.assertTrue(handoff["candidates"])
        self.assertIn("route_question", route)
        return route

    def test_a_review_verb_without_a_change_set_asks(self) -> None:
        # `review` alone is a token twenty skills list; with no PR, diff, or
        # change as its object it is not the review shape.
        self._assert_weak_clarify("review the onboarding flow for rough edges")

    def test_the_declined_winner_leads_even_where_the_ranking_would_not(self) -> None:
        from omh.routing.lexical_shortlist import lexical_ranking
        from omh.routing.recommend import recommend_skills

        message = "refactor the auth module"
        declined_winner = recommend_skills(message, limit=1)[0]["skill"]
        lexical_first = lexical_ranking(message)[0][0]
        # The case is only a test of the rule when the two disagree.
        self.assertNotEqual(declined_winner, lexical_first)
        route = self._assert_weak_clarify(message)
        self.assertEqual(route["candidate_handoff"]["candidates"][0]["skill"], declined_winner)
        self.assertEqual(route["candidate_skill"], declined_winner)

    def test_last_time_does_not_carry_a_live_information_guard(self) -> None:
        # `what` plus `time` fired the live-information guard for +42 on a
        # request about a past decision; the guard now needs a live cue.
        route = route_chat_message("what did we settle on last time for the queue design?", source="discord")
        self.assertNotEqual(route["action"], "dispatch")
        self.assertNotEqual(route["candidate_skill"], "live-info-operator")


class StrongEvidenceRouteTests(unittest.TestCase):
    """Positive half: a winner whose own labels name the job still dispatches."""

    def test_an_own_trigger_phrase_dispatches(self) -> None:
        route = route_chat_message("why is the build failing on main?", source="discord")
        self.assertEqual(route["action"], "dispatch")
        self.assertNotIn("ambiguity_kind", route)

    def test_an_explicit_invocation_dispatches(self) -> None:
        route = route_chat_message("$code-review this change", source="discord")
        self.assertEqual(route["action"], "dispatch")
        self.assertEqual(route["selected_skill"], "code-review")

    def test_a_non_ascii_request_is_not_gated(self) -> None:
        route = route_chat_message("기억이 잘못 저장된 것 같아 확인해줘", source="slack")
        self.assertEqual(route["action"], "dispatch")


class NarrowedGuardTests(unittest.TestCase):
    """The guards narrowed beside the gate keep their own shapes."""

    def test_canonical_code_edits_still_dispatch_delivery(self) -> None:
        for message in ("fix the login bug", "implement dark mode toggle", "rename this variable"):
            with self.subTest(message=message):
                route = route_chat_message(message, source="discord")
                self.assertEqual(route["action"], "dispatch")
                self.assertEqual(route["selected_skill"], "ultrawork")

    def test_writing_a_prompt_for_a_named_agent_is_not_a_delivery(self) -> None:
        route = route_chat_message("draft instructions for codex about the parser fix", source="discord")
        self.assertNotEqual(route["selected_skill"], "ultrawork")
        route = route_chat_message("have codex fix the flaky checkout test", source="discord")
        self.assertEqual(route["selected_skill"], "ultrawork")


class CanonicalRequestsAskWithTheRightSkillFirstTests(unittest.TestCase):
    """Shortlist-first: a canonical request without a phrase of its own asks,
    and the intended skill is the FIRST candidate -- pinned by position."""

    CASES = (
        ("the CI build is failing on main", "build-failure-triage"),
        ("deploy the app to production", "deploy-and-monitor"),
        ("file this bug on GitHub for the team", "github-issue-intake"),
        ("change the login page style to match the brand", "frontend"),
    )

    def test_a_whole_sentence_pr_review_dispatches_code_review(self) -> None:
        # Moved out of CASES: the code-review request guard reads a sentence
        # that is wholly a review of a numbered PR and dispatches it.
        route = route_chat_message("review PR 1234", source="discord")
        self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "code-review"))

    def test_each_asks_with_the_intended_skill_first(self) -> None:
        for message, skill in self.CASES:
            with self.subTest(message=message):
                route = route_chat_message(message, source="discord")
                self.assertEqual(route["action"], "clarify")
                self.assertEqual(route["candidate_skill"], skill)
                self.assertEqual(route["candidate_handoff"]["candidates"][0]["skill"], skill)

    def test_everyday_sentences_with_the_same_words_do_not_dispatch(self) -> None:
        for message in (
            "my lint roller is broken again",
            "promote Sarah to production manager",
            "release the doves live at the wedding",
            "change the color of the app icon on my phone",
            "look over the commits my accountant made to the ledger",
        ):
            with self.subTest(message=message):
                self.assertNotEqual(route_chat_message(message, source="discord")["action"], "dispatch")

    def test_opening_a_page_is_still_the_browser(self) -> None:
        route = route_chat_message("open the login page and fill the form", source="discord")
        self.assertEqual(route["selected_skill"], "browser-operator")

    def test_system_memory_is_not_the_memory_store(self) -> None:
        route = route_chat_message("investigate why memory usage keeps growing in prod", source="discord")
        self.assertNotEqual(route["selected_skill"], "memory-sync")
        self.assertNotEqual(route["candidate_skill"], "memory-sync")


class RecurringIssueDigestTests(unittest.TestCase):
    """`new github issue` is a substring of `new github issues`.

    The filing guard's explicit phrase handed a recurring digest of new issues a
    +44 filing boost. A cadence word now takes the filing guard off; filing
    requests keep it.
    """

    def test_a_daily_digest_of_new_issues_is_not_issue_filing(self) -> None:
        route = route_chat_message("every weekday, post the new github issues to our team channel daily", source="discord")
        self.assertNotEqual(route["selected_skill"], "github-issue-intake")
        route = route_chat_message("weekly, list the new github issues in our repo", source="discord")
        self.assertNotEqual(route["selected_skill"], "github-issue-intake")

    def test_filing_a_new_issue_still_reaches_intake(self) -> None:
        for message in (
            "file a new github issue for this crash",
            "open a new GitHub issue for the flaky login test",
        ):
            with self.subTest(message=message):
                route = route_chat_message(message, source="discord")
                self.assertEqual(route["action"], "dispatch")
                self.assertEqual(route["selected_skill"], "github-issue-intake")


class CadencePhraseNeedsARequestTests(unittest.TestCase):
    """#1892: a cadence phrase says when, not what.

    `every morning` is `automation-blueprint`'s own trigger. In a request it
    names the schedule; in a report it names a habit, and the own-phrase rule
    dispatched on it either way.
    """

    def test_the_classifier_drops_a_cadence_phrase_only_outside_a_request(self) -> None:
        labels = ["trigger:every morning", "trigger:morning"]
        self.assertEqual(_classify(labels, message="every morning send me the build status"), EVIDENCE_TRIGGER_PHRASE)
        self.assertEqual(_classify(labels, message="every morning the bus is late"), EVIDENCE_WEAK)
        # A phrase that names a job is not a cadence, request or not.
        self.assertEqual(_classify(["trigger:daily digest"], message="the daily digest was late"), EVIDENCE_TRIGGER_PHRASE)

    def test_cadence_phrase_is_frequency_and_time_only(self) -> None:
        for phrase in ("every morning", "every day", "each monday"):
            with self.subTest(phrase=phrase):
                self.assertTrue(policy.is_cadence_phrase(phrase))
        for phrase in ("daily digest", "every morning digest", "code review", "every"):
            with self.subTest(phrase=phrase):
                self.assertFalse(policy.is_cadence_phrase(phrase))

    def test_a_request_is_an_imperative_or_a_request_frame(self) -> None:
        for message in (
            "every morning send me the build status",
            "send me the open incidents every morning",
            "please, every day, summarize the new tickets",
            "I want a digest of failed deploys every morning",
            "remind me every day to stretch",
            "can the report go out every morning?",
        ):
            with self.subTest(message=message):
                self.assertTrue(policy.reads_as_a_request(message))
        for message in (
            "every morning I drink tea on the balcony",
            "every day my sister texts me a crossword clue",
            "each morning the office smells of toast",
            "we meet every morning at nine",
        ):
            with self.subTest(message=message):
                self.assertFalse(policy.reads_as_a_request(message))

    def test_a_clause_about_a_thing_asks_with_a_directive_modal_or_a_delivery_passive(self) -> None:
        for message in (
            "every morning the release notes should reach the support team",
            "each night the backup log has to go to the storage channel",
            "every week our churn chart gets emailed to finance",
            "the invoices are to be mailed every friday",
        ):
            with self.subTest(message=message):
                self.assertTrue(policy.reads_as_a_request(message))
        for message in (
            # A modal said of a person is advice, obligation, or belief.
            "every morning I should stretch more, honestly",
            "every night we must look ridiculous to the neighbours",
            # A thing with no modal and no delivery passive is described.
            "every day the elevator is broken again",
            "each morning the parking lot gets crowded",
        ):
            with self.subTest(message=message):
                self.assertFalse(policy.reads_as_a_request(message))

    def test_only_the_main_clause_carries_the_modal(self) -> None:
        for message in (
            "every week the coach feels the goalkeeper should train harder",
            "every morning the kettle whistles while the kids must find their shoes",
            "every night the neighbours know the band must stop at ten",
        ):
            with self.subTest(message=message):
                self.assertFalse(policy.reads_as_a_request(message))
        # `that` as the opener is a determiner, not a boundary.
        self.assertTrue(policy.reads_as_a_request("every morning that report should go to the leads"))

    def test_pure_non_ascii_input_reads_as_no_request(self) -> None:
        # `dispatch_evidence` must keep its non-ASCII exemption ahead of the
        # cadence branch; this is the reason.
        self.assertFalse(policy.reads_as_a_request("매일 아침 뉴스 요약 보내줘"))
        self.assertEqual(
            _classify(["trigger:매일 아침"], message="매일 아침 뉴스 요약 보내줘"), EVIDENCE_NON_ASCII_EXEMPT
        )

    def test_the_issue_sentence_asks_with_automation_first(self) -> None:
        route = route_chat_message("every morning I drink coffee before checking email", source="discord")
        self.assertEqual(route["action"], "clarify")
        self.assertEqual(route["candidate_skill"], "automation-blueprint")

    def test_the_recurring_request_still_dispatches(self) -> None:
        route = route_chat_message(
            "every morning check release risk and tell me on Slack only if something changed", source="discord"
        )
        self.assertEqual(route["action"], "dispatch")
        self.assertEqual(route["selected_skill"], "automation-blueprint")


class CommandedEditIsNotAFeedbackReportTests(unittest.TestCase):
    """#1892: a product noun beside a defect noun is a topic, not a report.

    The feedback guard's co-occurrence branch read "fix the ... crash in the
    checkout ..." as a customer report and dispatched triage on trust earned by
    the reporter-shaped branches. A command to change something is not a
    report; a named reporter still is.
    """

    def _guard(self, message: str) -> bool:
        from omh.routing.localization import normalized_phrase, routing_tokens

        normalized = normalized_phrase(message)
        return policy._feedback_before_coding_guard_applies(normalized, set(routing_tokens(normalized)))

    def test_a_commanded_edit_does_not_fire_the_co_occurrence_branch(self) -> None:
        for message in (
            "fix the null pointer crash in the checkout service",
            "fix the broken wheel on my shopping cart",
            "update my billing address because the old one keeps failing at the bank",
        ):
            with self.subTest(message=message):
                self.assertFalse(self._guard(message))

    def test_a_report_still_fires_it(self) -> None:
        for message in (
            "the checkout page crashes on submit",
            "checkout keeps crashing for users since yesterday",
            "users report the checkout crashes after login, fix it",
            "customers say billing fails, fix the refund issue",
        ):
            with self.subTest(message=message):
                self.assertTrue(self._guard(message))

    def test_the_issue_sentence_asks_with_a_coding_skill_first(self) -> None:
        route = route_chat_message("fix the null pointer crash in the checkout service", source="discord")
        self.assertEqual(route["action"], "clarify")
        self.assertNotEqual(route["candidate_skill"], "feedback-triage")
        self.assertEqual(route["candidate_skill"], "native-debugging")


if __name__ == "__main__":
    unittest.main()
