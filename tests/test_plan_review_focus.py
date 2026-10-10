"""Contract for the plan Review Focus and ralplan target-state rules (issue #2049).

`plan` gains three rules, each scoped to plans that describe code changes: a
capped `Review Focus` list of inputs the requirements imply but no planned test
covers, each assigned to the task that owns its test; one checkable action per
step; and a proportion check. Its completion checklist requires the section.
`ralplan` gains the target-state contract: each consumer of the result and its
target state before options, a `Success criteria` table mapping each
difference to a task and a verification scenario, a `Target-state coverage`
check that adds a task for an unmapped difference unless the user excluded it,
no MVP or first phase the user did not request, and per-task sizing bands.

Every assertion re-derives from the producers, never from the generated
`skills/` or `agent-skills/` trees, so dropping a rule from the catalog fails
here while a stale generated file still sits on disk. The tokens are the named
artifacts each rule is built from -- the section name, the cap, the owning
task, the table columns, the exits from the coverage rule -- so a rewrite that
keeps the topic and loses the mechanism fails.

`ralplan` has a `portable_overrides` quality bar that replaces the Hermes one
wholesale in the portable projection, so the portable body is checked on its
own: a rule that reaches only one target is half shipped.
"""

from __future__ import annotations

import unittest

from omh.skills.catalog import builtin_definitions
from omh.skills.render import agent_skill_templates, workflow_skill_from_definition
from omh.skills.validation import STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING

PLAN_TOKENS = (
    "When the plan describes code changes",  # the scope: triage and hub requests are plans too
    "`Review Focus`",   # the section name
    "at most 5",        # the cap
    "owning task",      # each line is assigned to the task that adds its test
    "found none",       # an empty section is a recorded check, not a skipped one
    "outcome can be checked",  # one action per step
    "proportion check",  # plan length against the code it leads to
)

RALPLAN_TOKENS = (
    "target state",
    "each consumer of the result",
    "`Success criteria`",
    "`Criterion | Task | Verification scenario`",  # the table columns
    "acceptance criteria above",  # the table extends the existing criteria, not a second set
    "`Target-state coverage`",
    "is added to the plan as its own task",  # shortfall direction, the whole mechanism
    "unless the user excluded it",  # exit 1: a user exclusion is not forced into a task
    "records it as a non-goal with that reason",
    "stays in the evidence-gap record",  # exit 2: a gap blocked on evidence is recorded, not tasked
    "only when the user requested one",
    "plan a split or phasing the user requested as given",  # the condition that keeps requested splits legal
    "Size each task as one band",
    "never as hours or days",
)


def _definition(name: str):
    return next(item for item in builtin_definitions() if item.name == name)


def _hermes_body(name: str) -> str:
    definition = _definition(name)
    return workflow_skill_from_definition(definition, definition.name).content


def _portable_body(name: str) -> str:
    return next(item.content for item in agent_skill_templates() if item.name == name).replace(
        "\n", " "
    )


class PlanReviewFocusTests(unittest.TestCase):
    def test_plan_body_carries_review_focus_step_and_proportion_tokens(self) -> None:
        body = _hermes_body("plan")
        for token in PLAN_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, body)

    def test_ralplan_body_carries_the_target_state_tokens(self) -> None:
        body = _hermes_body("ralplan")
        for token in RALPLAN_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, body)

    def test_ralplan_completion_checklist_requires_the_coverage_check(self) -> None:
        definition = _definition("ralplan")
        self.assertTrue(
            any("`Target-state coverage`" in line for line in definition.final_checklist),
            "ralplan can finish without checking the target-state mapping",
        )

    def test_plan_completion_checklist_requires_the_review_focus_section(self) -> None:
        definition = _definition("plan")
        self.assertTrue(
            any("`Review Focus`" in line for line in definition.final_checklist),
            "plan can finish without the Review Focus section",
        )

    def test_portable_projection_carries_the_same_tokens(self) -> None:
        cases = {"ulw-plan": RALPLAN_TOKENS, "omh-plan": PLAN_TOKENS}
        for name, tokens in cases.items():
            body = _portable_body(name)
            for token in tokens:
                with self.subTest(skill=name, token=token):
                    self.assertIn(token, body)

    def test_plan_and_ralplan_bodies_stay_under_the_byte_ceiling(self) -> None:
        for name in ("plan", "ralplan"):
            with self.subTest(skill=name):
                self.assertLessEqual(
                    len(_hermes_body(name).encode("utf-8")), STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING
                )


if __name__ == "__main__":
    unittest.main()
