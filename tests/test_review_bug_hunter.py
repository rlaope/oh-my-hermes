"""Contract for the Hermes Bug Hunter discipline in code-review and its siblings.

`code-review`'s finding validation gains a drop gate: a candidate that cannot
be shown step by step, is intended or documented, needs a precondition the
threat model's user cannot have, is only theoretical, or is a style nit
presented as a bug never reaches the findings list. `code-review`,
`production-audit` and `verification-gate` each end their result with a
`Not checked` list, written `Not checked: none` only on complete coverage.

Assertions re-derive from the producers, never from the generated `skills/`
or `agent-skills/` trees, and pin mechanism tokens (the five conditions, the
state each one leads to, the explicit empty form), so a rewrite that keeps the
topic and loses the mechanism fails. Both projections are checked: a rule that
reaches only one target is half shipped.
"""

from __future__ import annotations

import unittest

from omh.skills.catalog import builtin_definitions
from omh.skills.render import agent_skill_templates, workflow_skill_from_definition
from omh.skills.review_methods import review_method_reference_templates

DROP_GATE_TOKENS = (
    "## Drop gate",
    "Then run the drop gate below.",  # the procedure step that sends candidates through it
    "No step-by-step trace now",
    "concrete input or state",
    "Intended or documented",
    "test assertion, or code comment",
    "Out-of-reach precondition",
    "privilege or precondition the attacker or user in the threat model cannot have",
    "Theoretical only",
    "no reachable trigger",
    "Style as bug",
    "record the candidate as `rejected` with that reason",
    "`unresolved` when it is a security or data-loss risk",
    "never reaches the findings list",
    "only a candidate that clears all five can be `confirmed`",
)

NOT_CHECKED_TOKENS = (
    "`Not checked` list",
    "one-line reason",
    "`Not checked: none` only when coverage was complete",
    "never leave the list out",
    "reads as if everything else were clean",
)

NOT_CHECKED_SKILLS = ("code-review", "production-audit", "verification-gate")


def _definition(name: str):
    return next(item for item in builtin_definitions() if item.name == name)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _hermes_body(name: str) -> str:
    definition = _definition(name)
    return _flat(workflow_skill_from_definition(definition, definition.name).content)


def _portable_body(name: str) -> str:
    return _flat(next(item.content for item in agent_skill_templates() if item.name == f"omh-{name}"))


class DropGateTests(unittest.TestCase):
    def test_finding_validation_carries_the_five_drop_conditions(self) -> None:
        content = _flat(
            next(
                item.content
                for item in review_method_reference_templates()
                if item.relative_path == "references/finding-validation.md"
            )
        )
        for token in DROP_GATE_TOKENS:
            with self.subTest(token=token):
                self.assertIn(_flat(token), content)

    def test_code_review_opening_names_the_discipline_and_points_at_the_gate(self) -> None:
        definition = _definition("code-review")
        self.assertIn("Hermes Bug Hunter", definition.why_this_exists)
        self.assertTrue(
            any("its drop gate" in note for note in definition.recovery_notes),
            "code-review no longer sends final findings through the drop gate",
        )


class NotCheckedTests(unittest.TestCase):
    def test_each_skill_body_requires_the_not_checked_list(self) -> None:
        for name in NOT_CHECKED_SKILLS:
            for target, body in (("hermes", _hermes_body(name)), ("agent-skills", _portable_body(name))):
                for token in NOT_CHECKED_TOKENS:
                    with self.subTest(skill=name, target=target, token=token):
                        self.assertIn(token, body)

    def test_each_completion_checklist_requires_the_list(self) -> None:
        for name in NOT_CHECKED_SKILLS:
            checklist = " ".join(_definition(name).final_checklist)
            with self.subTest(skill=name):
                self.assertIn("`Not checked` list", checklist)
                self.assertIn("`Not checked: none`", checklist)

    def test_the_rule_stays_out_of_the_capability_rows(self) -> None:
        # Capability rows render the first four quality-bar items; the rule sits after them.
        for name in NOT_CHECKED_SKILLS:
            with self.subTest(skill=name):
                head = " ".join(str(line) for line in _definition(name).quality_bar[:4])
                self.assertNotIn("`Not checked`", head)


if __name__ == "__main__":
    unittest.main()
