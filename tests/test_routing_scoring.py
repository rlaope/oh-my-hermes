"""Scorer-level contracts for trigger matching.

These live apart from `tests/test_routing_precision.py` because the corpus there
also asserts that the raw message never appears in the machine payload, which a
one-word message always violates. The bare-word cases below are exactly the ones
that exposed the defect, so they need a home where a single common word is a
legal input.
"""

from __future__ import annotations

import unittest

from omh.routing.localization import normalized_phrase, phrase_is_spoken
from omh.routing.policy import _browser_operator_guard_applies
from omh.routing.recommend import (
    _inference_serving_explicit_match,
    _phrase_match,
    _refactor_plan_split_match,
    _tokens,
    _trigger_phrase_match,
    recommend_skills,
)
from omh.skills.catalog import routable_definitions


class TriggerPhraseDirectionTests(unittest.TestCase):
    def test_trigger_fires_only_when_the_message_contains_the_phrase(self) -> None:
        self.assertTrue(_trigger_phrase_match("please run npm test now", "npm test"))
        self.assertTrue(_trigger_phrase_match("test", "test"))
        # The reverse arm is what inflated ambiguous single words.
        self.assertFalse(_trigger_phrase_match("test", "npm test"))
        self.assertFalse(_trigger_phrase_match("design", "design system contract"))

    def test_a_trigger_does_not_fire_inside_a_longer_word(self) -> None:
        # `reliability-review` owned every Slack sentence through this: its
        # `sla` trigger is spelled inside `slack` (#1688).
        self.assertFalse(_trigger_phrase_match("one-off slack digest", "sla"))
        self.assertFalse(_trigger_phrase_match("pods in crashloopbackoff", "loop"))
        self.assertTrue(_trigger_phrase_match("investigate slack sla alerts", "sla"))

    def test_general_phrase_match_keeps_both_directions(self) -> None:
        # `_phrase_match` still backs description and use_when scoring, where a
        # short query legitimately appears inside a long prose field. Narrowing
        # it globally would delete that signal for every skill.
        self.assertTrue(_phrase_match("test", "npm test"))
        self.assertTrue(_phrase_match("please run npm test now", "npm test"))

    def test_one_ambiguous_word_does_not_inherit_multi_word_trigger_scores(self) -> None:
        # Before the fix: command-operator at 73, high confidence, from
        # trigger:`npm test`, `cargo test`, `pytest`, `python -m unittest`.
        top = recommend_skills("test", limit=1)[0]
        self.assertNotEqual(top["skill"], "command-operator")
        self.assertLess(top["score"], 30)

        for word, stolen_by in (("design", "design-quality-gate"), ("review", "security-safety-review")):
            with self.subTest(word=word):
                first = recommend_skills(word, limit=1)[0]
                self.assertNotEqual(first["skill"], stolen_by)
                self.assertLess(first["score"], 30)

    def test_a_message_that_contains_the_command_phrase_still_reaches_it(self) -> None:
        top = recommend_skills("npm test", limit=1)[0]
        self.assertEqual(top["skill"], "command-operator")
        self.assertIn("trigger:npm test", top["matched"])


class SpokenPhraseEdgeTests(unittest.TestCase):
    """#1688. Containment cannot tell a phrase said from a phrase spelled."""

    def test_a_phrase_does_not_match_inside_a_longer_latin_word(self) -> None:
        self.assertFalse(phrase_is_spoken("pods stuck in crashloopbackoff", "loop"))
        self.assertFalse(phrase_is_spoken("a user asked us to delete their data", "ask"))
        self.assertFalse(phrase_is_spoken("the auditor wants proof", "audit"))
        # `reliability-review` won every Slack sentence this way: its `sla`
        # trigger is inside `slack`, and the test guarding it had the same
        # hole, so the two agreed.
        self.assertFalse(phrase_is_spoken("one-off slack digest for this incident", "sla"))
        self.assertTrue(phrase_is_spoken("investigate slack sla alert failures", "sla"))

    def test_the_same_phrase_still_matches_when_it_is_the_word(self) -> None:
        self.assertTrue(phrase_is_spoken("keep the loop running", "loop"))
        self.assertTrue(phrase_is_spoken("loop", "loop"))
        self.assertTrue(phrase_is_spoken("ask claude about this", "ask"))
        self.assertTrue(phrase_is_spoken("$loop", "loop"))

    def test_a_multi_word_phrase_may_be_inflected_on_its_last_word(self) -> None:
        # The leading words have already pinned the sense, so a plural or a
        # participle on the end is the same phrase, not a different one.
        self.assertTrue(phrase_is_spoken("add smooth scrolling to the site", "smooth scroll"))
        self.assertTrue(phrase_is_spoken("list the attack scenarios", "attack scenario"))

    def test_a_one_word_phrase_may_not_be_inflected(self) -> None:
        # This is the arm that separates `asked` from `attack scenarios`.
        self.assertFalse(phrase_is_spoken("asked", "ask"))
        self.assertFalse(phrase_is_spoken("looping over the rows", "loop"))

    def test_cjk_has_no_spaces_so_the_left_edge_is_ascii_only(self) -> None:
        # A script-agnostic left edge would reject every CJK trigger, because
        # the character before the phrase is always a word character there.
        self.assertTrue(phrase_is_spoken("大きなpdfのアップロードが失敗", "アップロード"))
        self.assertTrue(phrase_is_spoken("大きなpdfのアップロード", "pdf"))
        self.assertTrue(phrase_is_spoken("모델 서빙을 어떻게 하죠", "모델 서빙"))
        self.assertTrue(phrase_is_spoken("把那个ultrawork搞定", "ultrawork"))


class OneWordSkillNameTests(unittest.TestCase):
    """#1688. One occurrence of a one-word name is one piece of evidence."""

    ONE_WORD_NAMES = tuple(
        sorted(
            definition.name
            for definition in routable_definitions()
            if "-" not in definition.name and " " not in definition.name
        )
    )

    def test_the_catalog_still_has_one_word_names_to_protect(self) -> None:
        # The rule is derived from the catalog, so an empty set would make
        # every assertion below vacuously true.
        self.assertGreaterEqual(len(self.ONE_WORD_NAMES), 15)

    def test_a_name_spelled_inside_a_longer_word_is_not_a_name_match(self) -> None:
        # The `name:` credit is +5, below the dispatch bar, so no corpus case
        # fails when this arm regresses -- only the evidence list is wrong,
        # and a wrong evidence list is what the person is shown.
        rows = {row["skill"]: row for row in recommend_skills("pods stuck in CrashLoopBackOff", limit=8)}
        self.assertNotIn("name:loop", rows.get("loop", {}).get("matched", ()))

    def test_a_bare_mention_scores_once_and_stays_under_the_dispatch_bar(self) -> None:
        # Before: name +5, the identically-spelled trigger phrase +6, that
        # trigger's token +3, and the same token from the metadata fold +1.
        top = next(
            row for row in recommend_skills("should I hire a backend engineer", limit=8)
            if row["skill"] == "backend"
        )
        self.assertEqual([label for label in top["matched"] if label.endswith("backend")], ["name:backend"])
        self.assertLess(top["score"], 8)

    def test_a_hangul_particle_marks_the_token_as_the_name(self) -> None:
        # Korean attaches the particle to the noun with no space, so "loop로"
        # is the name being referred to and not the English word. Folding
        # matters here: `normalized_phrase` decomposes Hangul into jamo, so a
        # composed particle literal never matches a normalized query.
        top = recommend_skills("웹사이트 버튼 색 바꾸는 것도 loop로 해야해?", limit=1)[0]
        self.assertEqual(top["skill"], "loop")
        self.assertGreaterEqual(top["score"], 8)

    def test_a_name_heading_its_noun_phrase_keeps_its_weight(self) -> None:
        # The two senses the score alone cannot separate, because their
        # evidence is identical: what the sentence is ABOUT is the backend in
        # the first and an engineer in the second, and the only place it says
        # so is the word after the name.
        heads = recommend_skills("implement the backend for observer lookup", limit=1)[0]
        self.assertEqual(heads["skill"], "backend")
        self.assertGreaterEqual(heads["score"], 8)
        modifies = next(
            row for row in recommend_skills("should I hire a backend engineer", limit=8)
            if row["skill"] == "backend"
        )
        self.assertLess(modifies["score"], 8)

    def test_a_handoff_to_the_name_keeps_its_weight(self) -> None:
        # How this repo's own `do_not_use_when` text hands a request to a
        # sibling. Without it the one-word names lost their own handoff
        # sentences to two-word siblings that kept every credit.
        top = recommend_skills(
            "The user wants new UI built or redesigned rather than restructured; use frontend.",
            limit=1,
        )[0]
        self.assertEqual(top["skill"], "frontend")

    def test_the_bare_first_word_test_credits_the_candidate_it_is_testing(self) -> None:
        # #1638 decides whether a leading catalog name is an invocation or the
        # sentence's verb by scoring the field WITHOUT the invocation bonus.
        # Scoring the candidate as though its own name were an ordinary word
        # assumes the answer, and left `research` at 7 against
        # `research-brief` at 10 on a sentence research owns.
        top = recommend_skills("Research the market and competitors for this category.", limit=1)[0]
        self.assertEqual(top["skill"], "research")
        self.assertIn("explicit_invocation", top["matched"])

    def test_every_one_word_name_still_answers_its_explicit_forms(self) -> None:
        # Derived from the catalog, so a new one-word skill joins this gate
        # without anyone listing it. `research` is excluded: its bare form
        # reaches `research-department` on main too, which is #1638's lane,
        # not this one.
        for name in self.ONE_WORD_NAMES:
            if name == "research":
                continue
            for form in (f"${name}", name, f"use the {name} skill"):
                with self.subTest(form=form):
                    self.assertEqual(recommend_skills(form, limit=1)[0]["skill"], name)


class TriggerTokenHoldbackTests(unittest.TestCase):
    """#1688. The phrasings added for `plan` must not widen it by their verbs."""

    def test_the_verbs_that_carry_the_new_plan_phrases_do_not_score_alone(self) -> None:
        # Without the `_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS` entry, `write` alone
        # made `plan` the top recommendation for this sentence. The corpus
        # cannot express this: its `forbidden_candidate` also reads the
        # clarify's shortlist, where `plan` legitimately appears either way.
        top = recommend_skills("write a zero downtime migration to add a not-null column", limit=1)[0]
        self.assertNotEqual(top["skill"], "plan")

    def test_the_complete_phrases_still_reach_plan(self) -> None:
        for message in ("make a plan for the onboarding rewrite", "write the plan for this experiment"):
            with self.subTest(message=message):
                self.assertEqual(recommend_skills(message, limit=1)[0]["skill"], "plan")


class UnreachableLaneTests(unittest.TestCase):
    """#1689. Three shipped skills could not be reached by ordinary phrasing."""

    @staticmethod
    def _folded(message: str) -> tuple[str, set[str]]:
        return normalized_phrase(message), _tokens(message)

    def test_a_live_incident_is_not_a_browser_errand(self) -> None:
        # `checkout` and `open` are a browser context token and a browser
        # action token, and together they crossed the guard at 42 -- enough
        # that no trigger evidence could outscore it.
        self.assertFalse(_browser_operator_guard_applies(
            *self._folded("we have an incident open right now, the checkout API is down")
        ))

    def test_the_browser_guard_keeps_a_real_page_operation(self) -> None:
        self.assertTrue(_browser_operator_guard_applies(
            *self._folded("open the checkout page in staging and click through the form")
        ))
        self.assertTrue(_browser_operator_guard_applies(
            *self._folded("log into the admin page and capture a screenshot")
        ))

    def test_the_model_has_to_be_what_is_served(self) -> None:
        # `serve` takes people as its object too, and a blocker list cannot
        # hold that shape: "serve our customers" misses "serve our SUPPORT
        # customers" the way "serve the model" missed "serve a 7B model".
        # Which side of the verb the noun sits on is what separates them.
        self.assertTrue(_inference_serving_explicit_match(
            *self._folded("serve a 7B model at 50 requests per second")
        ))
        self.assertTrue(_inference_serving_explicit_match(*self._folded("deploy the llm with vllm")))
        self.assertFalse(_inference_serving_explicit_match(
            *self._folded("which model should we use to serve our support customers")
        ))
        self.assertFalse(_inference_serving_explicit_match(
            *self._folded("the CDN should serve static assets from the edge")
        ))

    def test_breaking_something_up_has_to_be_breaking_up_code(self) -> None:
        self.assertTrue(_refactor_plan_split_match(
            *self._folded("this 900 line function needs to be broken up")
        ))
        self.assertFalse(_refactor_plan_split_match(*self._folded("the crowd was broken up by police")))

    def test_each_lane_reaches_its_own_sentence_end_to_end(self) -> None:
        for message, owner in (
            ("we have an incident open right now, the checkout API is down", "live-incident-response"),
            ("serve a 7B model at 50 requests per second", "inference-serving"),
            ("this 900 line function needs to be broken up", "refactor-plan"),
        ):
            with self.subTest(message=message):
                top = recommend_skills(message, limit=1)[0]
                self.assertEqual(top["skill"], owner)
                self.assertGreaterEqual(top["score"], 8)


class GreenfieldBuildGuardTests(unittest.TestCase):
    GREENFIELD = (
        "build a todo list",
        "build a react app",
        "build a dashboard",
        "build a chrome extension",
        "let's build a react todo list",
        "웹사이트 하나 만들어줘",
    )

    def test_greenfield_requests_reach_the_interview_lane_whatever_the_noun(self) -> None:
        for message in self.GREENFIELD:
            with self.subTest(message=message):
                self.assertEqual(recommend_skills(message, limit=1)[0]["skill"], "deep-interview")

    def test_the_guard_is_a_floor_not_an_override(self) -> None:
        # Each of these opens with a creation phrase but was already claimed by
        # a lane that matched real vocabulary; the greenfield guard must lose.
        for message, owner in (
            ("make me a landing page", "frontend"),
            ("build a login component", "ultrawork"),
            ("create a research brief for the auth migration", "research-brief"),
            ("웹 검색 싸게 만들어줘", "websearch-setup"),
        ):
            with self.subTest(message=message):
                self.assertEqual(recommend_skills(message, limit=1)[0]["skill"], owner)

    def test_asking_how_something_is_created_is_not_a_build_request(self) -> None:
        top = recommend_skills("how do I create a virtualenv in Python?", limit=1)[0]
        self.assertNotEqual(top["skill"], "deep-interview")


if __name__ == "__main__":
    unittest.main()
