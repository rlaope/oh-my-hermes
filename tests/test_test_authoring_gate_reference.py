"""The test-authoring contract, shared by every lane that writes a test.

Issue #2049 put four questions a new test answers first and the shapes of
tests that guard nothing into `ultrawork`'s `references/tdd-red-green.md`.
That page loads only in tests-first mode, so a backend, frontend, or debugging
handoff that asked for tests never met them. The authoring checks now live in
one shared page, `verification-gate`'s `references/test-authoring.md`, which
adds tests coupled to internals, fakes only at system boundaries, and the
outcome when no correct seam exists for a regression test. `tdd-red-green.md`
keeps only what is TDD-specific (the red-commit and witness rules) and points
at the shared page instead of holding a second copy.

This file pins three things: each named mechanism sits in the page that owns
it; the TDD page loads the shared page and does not restate its shapes; and
every code skill that hands off tests names the shared page in both
projections, so the page is reachable rather than a file in the pack.

Content is read from the producers, never from the generated `skills/` tree.
"""

from __future__ import annotations

import unittest

from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates
from omh.skills.render import agent_skill_reference_templates, agent_skill_templates
from test_skill_reference_mechanisms import _DATE, _VOLATILE_COUNT

SHARED_SKILL = "verification-gate"
SHARED_PATH = "references/test-authoring.md"
SHARED_HERMES_POINTER = "skill_view(name='omh-verification-gate', file_path='references/test-authoring.md')"
SHARED_PORTABLE_POINTER = "../omh-verification-gate/references/test-authoring.md"

TDD_SKILL = "ultrawork"
TDD_PATH = "references/tdd-red-green.md"

BACKEND_TESTS_PATH = "references/contract-tests.md"

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

# One token per shape of a test coupled to internals.
COUPLED_TOKENS = (
    "Own-module fake",
    "Call-count assertion",
    "Side-channel read",
)

# The boundary rule: stand-ins by dependency category, the same database
# engine, and the code change that makes a boundary fakeable.
BOUNDARY_TOKENS = (
    "Fakes Only at System Boundaries",
    "a local throwaway instance of the same engine",
    "pass the external client in",
)

# A regression test with no seam that runs the bug's pattern is recorded, not
# written shallow.
NO_SEAM_TOKENS = (
    "regression_seam: none_correct",
    "keep the reproduction loop as the fix's verification",
    "omh-refactor-plan",
)

# An expected value from a reviewed artifact or an oracle is not self-derived.
INDEPENDENT_EXPECTED_TOKEN = "a committed, reviewed artifact or an independent oracle does not count as the code under test"

# The bug-regression rule: the test fails on the code before the fix, for the
# bug's own reason.
PRE_FIX_TOKENS = (
    "must fail on the code before the fix",
    "fail because of that bug",
)

# The existing-test branch of question 3 in a tests-first lane: the existing
# test's red run is the Evidence Ledger witness, and an already-green run
# means nothing to build.
EXISTING_WITNESS_TOKENS = (
    "its red run on the unimplemented code is the witness the Evidence Ledger asks for",
    "if it is already green the behavior exists and there is nothing to implement",
)

# A guards-nothing shape found after the red commit: rewrite, re-run red, and
# explain the diff under the red-commit rule.
AFTER_RED_COMMIT_TOKENS = (
    "If the shape is found after the red commit",
    "run it red again, and explain the test diff in the lane report",
)

# H3: each contract row is tied to the test that proves it.
BACKEND_TEST_PLAN_TOKENS = (
    "auth_boundary_map/v1",
    "caller A requests B's id",
    "error_path_table/v1",
    "status, machine code, and envelope shape asserted together",
    "never a different engine",
    "not by querying the table",
    "Migrations run on populated data",
)

# Skills whose body must load the shared page.
POINTING_SKILLS = ("backend", "frontend", "app-debugging")


def _reference(skill: str, path: str) -> str:
    matches = [
        template.content
        for template in builtin_skill_reference_templates()
        if template.skill_name == skill and template.relative_path == path
    ]
    if len(matches) != 1:
        raise AssertionError(f"{skill} ships {len(matches)} copies of {path}")
    return matches[0]


def _portable_reference(label: str, path: str) -> str:
    matches = [
        template.content
        for template in agent_skill_reference_templates()
        if template.skill_name == label and template.relative_path == path
    ]
    if len(matches) != 1:
        raise AssertionError(f"the portable pack ships {len(matches)} copies of {label}/{path}")
    return matches[0]


def _hermes_body(name: str) -> str:
    return next(template.content for template in builtin_skill_templates() if template.name == name)


def _portable_body(label: str) -> str:
    return next(template.content for template in agent_skill_templates() if template.name == label)


class SharedTestAuthoringReferenceTests(unittest.TestCase):
    def test_shared_page_carries_every_authoring_mechanism(self) -> None:
        content = _reference(SHARED_SKILL, SHARED_PATH)
        for group in (QUESTION_TOKENS, GUARDS_NOTHING_TOKENS, COUPLED_TOKENS, BOUNDARY_TOKENS, NO_SEAM_TOKENS):
            for token in group:
                with self.subTest(token=token):
                    self.assertIn(token, content, f"{SHARED_PATH} lost {token!r}")
        self.assertIn(INDEPENDENT_EXPECTED_TOKEN, content, f"{SHARED_PATH} lost the independent-oracle clause")

    def test_tdd_page_keeps_its_own_rules_and_loads_the_shared_page(self) -> None:
        content = _reference(TDD_SKILL, TDD_PATH)
        for token in PRE_FIX_TOKENS + EXISTING_WITNESS_TOKENS + AFTER_RED_COMMIT_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, content, f"{TDD_PATH} lost {token!r}")
        self.assertIn(SHARED_HERMES_POINTER, content, f"{TDD_PATH} no longer loads the shared authoring page")

    def test_tdd_page_holds_no_second_copy_of_the_shared_shapes(self) -> None:
        content = _reference(TDD_SKILL, TDD_PATH)
        for token in GUARDS_NOTHING_TOKENS + COUPLED_TOKENS + (INDEPENDENT_EXPECTED_TOKEN,):
            with self.subTest(token=token):
                self.assertNotIn(token, content, f"{TDD_PATH} restates {token!r}; point at {SHARED_PATH} instead")

    def test_each_code_skill_loads_the_shared_page_in_both_projections(self) -> None:
        for name in POINTING_SKILLS:
            with self.subTest(skill=name):
                if name == "backend":
                    # Backend reaches the shared page through its contract-tests page.
                    self.assertIn(BACKEND_TESTS_PATH, _hermes_body(name))
                    self.assertIn(BACKEND_TESTS_PATH, _portable_body("omh-backend"))
                    continue
                self.assertIn(SHARED_HERMES_POINTER, _hermes_body(name))
                portable = _portable_body(f"omh-{name}")
                self.assertIn(SHARED_PORTABLE_POINTER, portable)
                self.assertNotIn(SHARED_HERMES_POINTER, portable)

    def test_backend_contract_tests_tie_each_row_to_a_test_and_load_the_shared_page(self) -> None:
        content = _reference("backend", BACKEND_TESTS_PATH)
        for token in BACKEND_TEST_PLAN_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, content, f"backend {BACKEND_TESTS_PATH} lost {token!r}")
        self.assertIn(SHARED_HERMES_POINTER, content)
        portable = _portable_reference("omh-backend", BACKEND_TESTS_PATH)
        self.assertNotIn("skill_view(", portable)
        self.assertIn("../../omh-verification-gate/references/test-authoring.md", portable)

    def test_portable_shared_page_names_no_hermes_only_page(self) -> None:
        portable = _portable_reference("omh-verification-gate", SHARED_PATH)
        self.assertNotIn(TDD_PATH, portable)
        self.assertNotIn("skill_view(", portable)

    def test_app_debugging_fix_handoff_records_a_missing_seam(self) -> None:
        body = _hermes_body("app-debugging")
        self.assertIn("regression_seam: none_correct", body)

    def test_pages_record_no_date_or_volatile_count(self) -> None:
        for skill, path in ((SHARED_SKILL, SHARED_PATH), (TDD_SKILL, TDD_PATH), ("backend", BACKEND_TESTS_PATH)):
            content = _reference(skill, path)
            with self.subTest(path=path):
                self.assertIsNone(_DATE.search(content), f"{path} records a date")
                self.assertIsNone(_VOLATILE_COUNT.search(content), f"{path} records a volatile count")


if __name__ == "__main__":
    unittest.main()
