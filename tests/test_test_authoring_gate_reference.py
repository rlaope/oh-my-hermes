"""`ultrawork`'s TDD reference carries the checks a new test must pass (issue #2049).

`references/tdd-red-green.md` already demands a red run before any
implementation line. A red run says nothing about whether the test that went
red guards anything, so the reference also names four questions a new test
answers first, the shapes of tests that guard nothing, and the rule that a
bug's regression test fails on the unfixed code for the bug's own reason.

`ultrawork` already has its one entry in `MECHANISM_POINTERS` (the
file-ownership manifest), so this file asserts the same contract for this
reference directly: the always-loaded body names it, its named
mechanism tokens are present, and it records no date or volatile count. The
body itself is not edited by this change, so the body byte ceiling is owned by
`tests/test_skill_reference_mechanisms.py` and is not repeated here.

Content is read from the producer, never from the generated `skills/` tree.
"""

from __future__ import annotations

import unittest

from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates
from test_skill_reference_mechanisms import _DATE, _VOLATILE_COUNT

SKILL = "ultrawork"
REFERENCE_PATH = "references/tdd-red-green.md"

# One token per pre-add question; each is that question's lead label.
QUESTION_TOKENS = (
    "Behavior protected",
    "Plausible regression",
    "Why existing coverage misses it",
    "Production seam",
)

# One token per shape of a test that guards nothing.
GUARDS_NOTHING_TOKENS = (
    "No-assertion probe",
    "Self-comparison",
    "Expected value from the code under test",
    "Negative control passing for an unrelated reason",
    "Name promising more than the inputs",
)

# The bug-regression rule: the test fails on the code before the fix, for the
# bug's own reason.
PRE_FIX_TOKENS = (
    "must fail on the code before the fix",
    "fail because of that bug",
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


class TestAuthoringGateReferenceTests(unittest.TestCase):
    def test_ultrawork_body_names_the_tdd_reference(self) -> None:
        bodies = {template.name: template.content for template in builtin_skill_templates()}
        self.assertIn(REFERENCE_PATH, bodies[SKILL], f"{SKILL} body no longer names {REFERENCE_PATH}")

    def test_reference_names_each_of_the_four_pre_add_questions(self) -> None:
        content = _reference()
        for token in QUESTION_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, content, f"{REFERENCE_PATH} lost the pre-add question {token!r}")

    def test_reference_names_each_shape_of_a_test_that_guards_nothing(self) -> None:
        content = _reference()
        for token in GUARDS_NOTHING_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, content, f"{REFERENCE_PATH} lost the shape {token!r}")

    def test_reference_requires_a_bug_regression_to_fail_before_the_fix(self) -> None:
        content = _reference()
        for token in PRE_FIX_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, content, f"{REFERENCE_PATH} lost the pre-fix failure rule ({token!r})")

    def test_reference_records_no_date_or_volatile_count(self) -> None:
        content = _reference()
        self.assertIsNone(_DATE.search(content), f"{REFERENCE_PATH} records a date")
        self.assertIsNone(_VOLATILE_COUNT.search(content), f"{REFERENCE_PATH} records a volatile count")


if __name__ == "__main__":
    unittest.main()
