"""`ultrawork`'s execution-rulings reference (issue #2049).

`references/execution-rulings.md` lets the coordinator settle small mid-run
questions itself and record each one, caps review rounds with a new reviewer
each time, and limits which earlier evidence a later increment may keep.

The risk this file guards is that the rulings rule reads as permission to
skip a stop. So beyond the mechanism tokens it pins the sentences that tie the
four stop cases to the existing "decision the user owns" stop and keep the
follow-up authority rule in force.

`ultrawork` already has its one entry in `MECHANISM_POINTERS` (the
file-ownership manifest), so the same contract is asserted here directly: the
always-loaded body names this reference on exactly one line, the body stays
under the per-skill byte ceiling that pointer was added against, and the
reference records no date or volatile count.

Content is read from the producers, never from the generated `skills/` tree.
"""

from __future__ import annotations

import unittest

from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.validation import STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING
from test_skill_reference_mechanisms import _DATE, _VOLATILE_COUNT, _bodies_by_name

SKILL = "ultrawork"
REFERENCE_PATH = "references/execution-rulings.md"

# The ledger line shape, written once in the reference.
RULING_LINE = "Ruling: <decision> — <reason> — <cost if wrong>"

# The four stop cases, each by its lead words.
STOP_CASE_TOKENS = (
    "An irreversible or destructive step",
    "A security-sensitive step",
    "A side effect outside the worktree",
    "every way forward is a guess",
)

# The sentences that keep the stop cases subordinate to the existing rules.
# Removing any of these turns "the four stop cases" into "the only stops".
USER_OWNED_LINK_TOKENS = (
    "Each of the following is a decision the user owns",
    "These four are cases of that one rule, not its full extent.",
    "is described first and started only on approval",
    "Where it is unclear whether a choice qualifies as a ruling, it does not",
)

REVIEW_ROUND_TOKENS = (
    "at most two re-reviews",
    "A new reviewer each time.",
    "A lane never starts its own reviewer",
    "After the second re-review",
    "A ruling never closes one",
)

EVIDENCE_REUSE_TOKENS = (
    "observed_tree",
    "the whole set runs once more against the final tree",
    "never proof of completion",
    "stale_tree",
)

BLAST_RADIUS_TOKENS = (
    "Defects Outside the Blast Radius",
    "tracked issue",
    "never turns an acceptance criterion it touches into a pass",
)


def _reference() -> str:
    matches = [
        template.content
        for template in builtin_skill_reference_templates()
        if template.skill_name == SKILL and template.relative_path == REFERENCE_PATH
    ]
    if len(matches) != 1:
        raise AssertionError(f"{SKILL} ships {len(matches)} copies of {REFERENCE_PATH}")
    return matches[0]


class ExecutionRulingsReferenceTests(unittest.TestCase):
    def _assert_tokens(self, tokens: tuple[str, ...], what: str) -> None:
        content = _reference()
        for token in tokens:
            with self.subTest(token=token):
                self.assertIn(token, content, f"{REFERENCE_PATH} lost {what} ({token!r})")

    def test_reference_states_the_ruling_line_shape(self) -> None:
        self.assertIn(RULING_LINE, _reference(), f"{REFERENCE_PATH} lost the ruling ledger line")

    def test_reference_names_each_stop_case(self) -> None:
        self._assert_tokens(STOP_CASE_TOKENS, "a stop case")

    def test_stop_cases_stay_under_the_user_owned_decision_rule(self) -> None:
        self._assert_tokens(USER_OWNED_LINK_TOKENS, "the link to the user-owned decision stop")

    def test_reference_caps_review_rounds_with_a_new_reviewer(self) -> None:
        self._assert_tokens(REVIEW_ROUND_TOKENS, "the review-round rule")

    def test_reference_keys_evidence_reuse_to_the_observed_tree(self) -> None:
        self._assert_tokens(EVIDENCE_REUSE_TOKENS, "the evidence-reuse rule")

    def test_reference_scopes_defects_to_the_blast_radius(self) -> None:
        self._assert_tokens(BLAST_RADIUS_TOKENS, "the blast-radius rule")

    def test_reference_records_no_date_or_volatile_count(self) -> None:
        content = _reference()
        self.assertIsNone(_DATE.search(content), f"{REFERENCE_PATH} records a date")
        self.assertIsNone(_VOLATILE_COUNT.search(content), f"{REFERENCE_PATH} records a volatile count")

    def test_body_names_the_reference_on_exactly_one_line(self) -> None:
        body = _bodies_by_name()[SKILL]
        naming = [line for line in body.splitlines() if REFERENCE_PATH in line]
        self.assertEqual(
            len(naming),
            1,
            f"{SKILL} names {REFERENCE_PATH} on {len(naming)} lines; the pointer is one line",
        )

    def test_body_stays_under_the_per_skill_ceiling(self) -> None:
        size = len(_bodies_by_name()[SKILL].encode("utf-8"))
        self.assertLessEqual(
            size,
            STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING,
            f"{SKILL} body is {size} bytes; shorten the pointer before raising the ceiling",
        )


if __name__ == "__main__":
    unittest.main()
