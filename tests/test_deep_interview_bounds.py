"""Deep-interview round bounds: visible counter, clarity indicator, stop rules.

The interview loop is instruction text a Hermes runtime follows, so these tests pin the
rendered contract rather than runtime behavior: the bound is stated on every surface that
mentions it, every surface derives its number from one constant, and the wording that
previously licensed unbounded questioning is gone.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from omh.skills.catalog import (
    DEEP_INTERVIEW_CLARITY_DIMENSIONS,
    DEEP_INTERVIEW_MAX_ROUNDS,
    DEEP_INTERVIEW_SOFT_CHECK_ROUND,
    installable_skill_definitions,
)
from omh.skills.render import deep_interview_skill
from omh.workflows.hermes_planning import _deep_interview_contract, _missing_decisions

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_MD = REPO_ROOT / "skills" / "ulw-interview" / "SKILL.md"

# Measured 9,469 chars at introduction. The ceiling keeps the always-loaded body from
# drifting upward unnoticed; the repo-wide gate is tests/test_efficiency.py.
# 10_000 -> 10_300: the rendered body measures 10,131 after every skill's
# Runtime Evidence tail gained the turn-ending sentence (a stop or a decision
# the user owns ends the turn by offering the next action as a question).
# One sentence of warranted always-loaded growth, not drift.
# 10_300 -> 10_600: the tail sentence grew to carry the reply rule (the
# user's words, the host's voice, record terms stay in records); the body
# measures 10,347. Headroom restored rather than cleared by a hair.
# 10_600 -> 10_900: the interview protocol gained the idea-approval sentence (a
# yes to an idea approves only the idea; a later plan, handoff, or change is
# accepted at its own gate); the body measures 10,688. Same headroom rule.
DEEP_INTERVIEW_SKILL_CHAR_CEILING = 10_900


def _skill_body() -> str:
    return deep_interview_skill().content


def _unwrapped_body() -> str:
    """Body with soft line wrapping collapsed, for assertions on sentences that wrap."""
    return " ".join(_skill_body().split())


def _definition():
    return next(item for item in installable_skill_definitions() if item.name == "deep-interview")


def _required_contract() -> dict[str, object]:
    task = "make onboarding smoother"
    return _deep_interview_contract(task, required=True, missing_decisions=_missing_decisions(task))


class DeepInterviewProtocolTest(unittest.TestCase):
    def test_protocol_block_states_the_round_budget_and_header(self) -> None:
        body = _skill_body()
        self.assertIn("## Interview Round Protocol", body)
        self.assertIn(f"at most {DEEP_INTERVIEW_MAX_ROUNDS} rounds, one question per round", body)
        self.assertIn(
            f"Round {{n}}/{DEEP_INTERVIEW_MAX_ROUNDS} · Clarity: {{percent}}% ({{resolved}}/3) · Targeting: {{dimension}}",
            body,
        )

    def test_clarity_indicator_has_a_fixed_denominator_and_percentage(self) -> None:
        body = _skill_body()
        self.assertIn("The denominator is always 3; `{percent}` is 0, 33, 67, or 100.", body)
        for dimension in DEEP_INTERVIEW_CLARITY_DIMENSIONS:
            self.assertIn(dimension, body)

    def test_korean_header_and_dimension_names_are_specified(self) -> None:
        body = _skill_body()
        self.assertIn(f"라운드 {{n}}/{DEEP_INTERVIEW_MAX_ROUNDS}", body)
        self.assertIn("명확도", body)
        self.assertIn("확인 중", body)
        for korean in ("목표", "제약과 비목표", "성공 기준"):
            self.assertIn(korean, body)

    def test_korean_dimension_names_do_not_collide_with_the_field_separator(self) -> None:
        # The header separator is "·"; a Korean dimension name containing it would make the
        # header ambiguous to read.
        body = _skill_body()
        self.assertNotIn("제약·비목표", body)

    def test_voice_rules_keep_the_question_conversational(self) -> None:
        body = _skill_body()
        self.assertIn("**Voice — the header is instrumentation; the question is a conversation.**", body)
        self.assertIn("Never fold counters, ratios, or dimension names into the question sentence.", body)
        self.assertIn("If it reads like a form field, rewrite it.", body)
        self.assertIn("Never mix languages in one message.", body)
        # QA caught a Korean run labeling its brief "클리어리파이드 브리프" — a transliteration
        # of the English term, which reads as broken Korean.
        self.assertIn("Translate those terms, never transliterate them.", _unwrapped_body())

    def test_every_question_offers_candidate_answers_plus_free_input(self) -> None:
        # Live ulw-interview runs forced free-text-only replies; the OMH-native equivalent of
        # a structured question UI is a numbered candidate list ending in a free-input entry
        # (the same shape the model-chains interview already uses).
        body = _skill_body()
        self.assertIn("**Answer options — every question ships with candidates.**", body)
        unwrapped = _unwrapped_body()
        self.assertIn("two to four real candidates, then one final free-input entry.", unwrapped)
        # English is the canonical rendering; Korean is the localized illustration.
        self.assertIn("Something else — type your answer", body)
        self.assertIn("기타 — 직접 입력", body)
        self.assertIn("free text is always accepted, even when it matches no option.", unwrapped)
        self.assertIn("Never re-ask because the reply was not a listed option.", unwrapped)
        # A candidate whose text is a bare number would make a numeric reply undecidable
        # between "option 3" and "the literal answer 3".
        self.assertIn("never a candidate whose text is itself a bare number", unwrapped)
        # The candidate list must not read as extra questions, or it would collide with the
        # one-question-per-round rule the header advertises.
        self.assertIn("it does not break the one-question rule.", unwrapped)
        # "no numbered sub-questions" (not the old "sub-parts") is what keeps the numbered
        # answer list from contradicting the voice rules.
        self.assertIn("no numbered sub-questions.", unwrapped)
        self.assertNotIn("no numbered sub-parts", body)

    def test_option_block_sits_between_voice_rules_and_the_soft_check(self) -> None:
        body = _skill_body()
        self.assertLess(body.index("**Voice —"), body.index("**Answer options —"))
        self.assertLess(body.index("**Answer options —"), body.index("**Mid-interview check"))

    def test_mid_interview_check_uses_the_same_option_shape(self) -> None:
        self.assertIn(
            "with the same option shape: keep going / plan now / free input.",
            _unwrapped_body(),
        )

    def test_catalog_quality_bar_names_the_option_contract(self) -> None:
        bar = _definition().quality_bar
        self.assertTrue(
            any("free-input option" in item and "free text" in item for item in bar),
            bar,
        )

    def test_harness_fallback_and_quality_bar_carry_the_option_contract(self) -> None:
        # The harness fallback used to prescribe the pre-change behavior (a bare direct
        # question); a runtime reading both surfaces must not get contradictory shapes.
        from omh.skills.catalog import builtin_harnesses

        harness = next(item for item in builtin_harnesses() if item.name == "deep-interview")
        self.assertIn("numbered list ending in a free-input entry", harness.fallback)
        self.assertTrue(
            any("free-input entry" in item and "free text" in item for item in harness.quality_bar),
            harness.quality_bar,
        )

    def test_soft_check_is_not_a_stop_rule_and_does_not_consume_a_round(self) -> None:
        body = _skill_body()
        self.assertIn("**Mid-interview check — this is not a stop rule.**", body)
        self.assertIn("The check is not a round: emit it without a header.", body)
        self.assertIn(
            f"Before asking the question that would be Round {DEEP_INTERVIEW_SOFT_CHECK_ROUND}",
            body,
        )
        # The mid-interview check must sit outside the numbered stop-rule list, otherwise a
        # reader applying "the first match ends the interview" stops at the soft check and the
        # round budget becomes unreachable.
        self.assertLess(body.index("Mid-interview check"), body.index("**Stop rules"))

    def test_stop_rules_cover_resolution_explicit_stop_and_budget(self) -> None:
        body = _skill_body()
        self.assertIn("**Stop rules — the first match ends the interview.**", body)
        self.assertIn("**All three dimensions resolved.**", body)
        self.assertIn("**The user asks to stop.**", body)
        self.assertIn(f"**Budget reached at Round {DEEP_INTERVIEW_MAX_ROUNDS}.**", body)

    def test_explicit_stop_is_honored_at_any_round(self) -> None:
        self.assertIn("ends questioning immediately, at any round", _unwrapped_body())

    def test_lost_round_count_fails_toward_stopping(self) -> None:
        body = _unwrapped_body()
        self.assertIn("do not restart at Round 1", body)
        self.assertIn(
            f"run the mid-interview check now and continue from Round {DEEP_INTERVIEW_SOFT_CHECK_ROUND}",
            body,
        )

    def test_bound_is_framed_as_a_stop_rule_not_enforcement(self) -> None:
        body = _skill_body()
        self.assertIn("These are stop rules you follow, not caps OMH enforces.", body)

    def test_unbounded_continuation_instruction_is_gone(self) -> None:
        # The inherited clarification-category recovery note told Hermes to ask the next
        # question whenever an answer surfaced new ambiguity, with no bound.
        self.assertNotIn("instead of planning too early", _skill_body())

    def test_protocol_block_states_numbers_only_through_the_constants(self) -> None:
        # Spelled-out ordinals cannot be interpolated, so they would silently desync if the
        # budget moved.
        body = _skill_body()
        for ordinal in ("fourth", "seventh", "fifth", "sixth"):
            self.assertNotIn(ordinal, body)

    def test_rendered_skill_stays_within_its_char_ceiling(self) -> None:
        self.assertLess(len(_skill_body()), DEEP_INTERVIEW_SKILL_CHAR_CEILING)

    def test_rendered_file_matches_the_renderer(self) -> None:
        self.assertEqual(SKILL_MD.read_text(encoding="utf-8"), _skill_body())


class DeepInterviewContractTest(unittest.TestCase):
    def test_required_branch_carries_the_static_interview_policy(self) -> None:
        contract = _required_contract()
        self.assertEqual(contract["max_rounds"], DEEP_INTERVIEW_MAX_ROUNDS)
        self.assertEqual(contract["soft_check_round"], DEEP_INTERVIEW_SOFT_CHECK_ROUND)
        self.assertEqual(contract["clarity_dimensions"], list(DEEP_INTERVIEW_CLARITY_DIMENSIONS))
        self.assertEqual(contract["schema_version"], "deep_interview_contract/v1")

    def test_non_required_branch_omits_interview_policy(self) -> None:
        contract = _deep_interview_contract("ship the parser fix", required=False, missing_decisions=())
        for key in ("max_rounds", "soft_check_round", "clarity_dimensions"):
            self.assertNotIn(key, contract)

    def test_no_live_round_field_is_emitted(self) -> None:
        # `rerun_hermes_plan` is stateless, so a round counter here would report the same
        # value forever. The live count lives in the thread header instead.
        contract = _required_contract()
        for key in ("round", "current_round", "rounds_remaining", "min_rounds_before_exit"):
            self.assertNotIn(key, contract)

    def test_policy_fields_are_stateless_across_calls(self) -> None:
        first = _required_contract()
        second = _required_contract()
        for key in ("max_rounds", "soft_check_round", "clarity_dimensions"):
            self.assertEqual(first[key], second[key])


class DeepInterviewSingleSourceOfTruthTest(unittest.TestCase):
    """Every surface that states the budget must derive it from the same constant."""

    def test_catalog_safety_rule_derives_from_the_constant(self) -> None:
        rules = _definition().safety_rules
        self.assertTrue(
            any(f"round {DEEP_INTERVIEW_MAX_ROUNDS} is reached" in rule for rule in rules),
            rules,
        )

    def test_catalog_recovery_notes_override_the_category_default(self) -> None:
        notes = _definition().recovery_notes
        self.assertGreaterEqual(len(notes), 2)
        self.assertTrue(
            any(f"once round {DEEP_INTERVIEW_MAX_ROUNDS} is reached" in note for note in notes),
            notes,
        )
        self.assertFalse(any("instead of planning too early" in note for note in notes), notes)

    def test_wrapper_clarification_ack_states_the_same_budget(self) -> None:
        from omh.wrapper.contract import build_chat_interaction_payload

        payload = build_chat_interaction_payload("deep-interview: our onboarding wording feels vague")
        body = str(payload["chat_response"]["body"])
        self.assertIn(f"at most {DEEP_INTERVIEW_MAX_ROUNDS} rounds", body)

    def test_harness_stop_conditions_name_the_budget(self) -> None:
        from omh.skills.catalog import builtin_harnesses

        harness = next(item for item in builtin_harnesses() if item.name == "deep-interview")
        self.assertIn("the round budget is exhausted or the user asked to stop", harness.stop_conditions)
        self.assertIn("round_budget_respected", harness.evidence_ladder)


class DeepInterviewBoundaryGuardTest(unittest.TestCase):
    def test_protocol_prose_stays_out_of_the_chat_payload(self) -> None:
        # The protocol is progressive disclosure inside SKILL.md. Leaking it into the routed
        # chat payload would spend the compact route budget on interview instructions.
        from omh.wrapper.contract import build_chat_interaction_payload

        payload = build_chat_interaction_payload("deep-interview: our onboarding wording feels vague")
        serialized = str(payload)
        self.assertNotIn("Interview Round Protocol", serialized)
        self.assertNotIn("the header is instrumentation", serialized)

    def test_clarification_ack_survives_messenger_safe_body_unchanged(self) -> None:
        from omh.wrapper.contract import _messenger_safe_body, build_chat_interaction_payload

        payload = build_chat_interaction_payload("deep-interview: our onboarding wording feels vague")
        body = str(payload["chat_response"]["body"])
        transformed, _ = _messenger_safe_body(body)
        self.assertEqual(transformed, body)


if __name__ == "__main__":
    unittest.main()
