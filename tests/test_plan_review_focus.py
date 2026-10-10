"""Contract for the plan Review Focus and ralplan ideal-state rules (issue #2049).

`plan` gains three rules: a capped `Review Focus` list of inputs the
requirements imply but no task's tests exercise, each pinned to the task that
owns its test; one checkable action per step; and a proportion check. `ralplan`
gains the ideal-state contract: the affected user and the ideal state before
options, a `Success criteria` table mapping each gap to a task and a
verification scenario, an `Ideal-state fidelity` check whose shortfall becomes
a new task, no MVP or phase-1 cut the user did not ask for, and effort as fixed
bands.

Every assertion re-derives from the producers, never from the generated
`skills/` or `agent-skills/` trees, so dropping a rule from the catalog fails
here while a stale generated file still sits on disk. The tokens are the named
artifacts each rule is built from -- the section name, the cap, the owning
task, the table columns -- so a rewrite that keeps the topic and loses the
mechanism fails.

`ralplan` has a `portable_overrides` quality bar that replaces the Hermes one
wholesale in the portable projection, so the portable body is checked on its
own: a rule that reaches only one target is half shipped.
"""

from __future__ import annotations

import unittest

from omh.quality.skill_density import skill_density_measurements, skill_density_violations
from omh.skills.catalog import builtin_definitions
from omh.skills.render import agent_skill_templates, workflow_skill_from_definition
from omh.skills.validation import STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING

PLAN_TOKENS = (
    "`Review Focus`",   # the section name
    "at most 5",        # the cap
    "owning task",      # each line is pinned to the task that adds its test
    "found none",       # an empty section is a recorded check, not a skipped one
    "checkable result",  # one action per step
    "proportion check",  # plan length against the code it describes
)

RALPLAN_TOKENS = (
    "ideal state",
    "who the change affects",
    "`Success criteria`",
    "`Criterion | Task | Verification scenario`",  # the table columns
    "`Ideal-state fidelity`",
    "becomes a new task, never a note",  # shortfall direction, the whole mechanism
    "MVP or phase 1 the user did not ask for",
    "when the user asks for a split or phases, plan that split",  # the condition that keeps requested splits legal
    "`Quick`, `S`, `M`, `L`, or `XL`",
    "never as hours or days",
)


def _hermes_body(name: str) -> str:
    definition = next(item for item in builtin_definitions() if item.name == name)
    return workflow_skill_from_definition(definition, definition.name).content


def _portable_body(name: str) -> str:
    return next(item.content for item in agent_skill_templates() if item.name == name).replace(
        "\n", " "
    )


class PlanReviewFocusTests(unittest.TestCase):
    def test_plan_body_carries_review_focus_step_and_proportion_rules(self) -> None:
        body = _hermes_body("plan")
        for token in PLAN_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, body)

    def test_ralplan_body_carries_the_ideal_state_contract(self) -> None:
        body = _hermes_body("ralplan")
        for token in RALPLAN_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, body)

    def test_ralplan_completion_checklist_requires_the_fidelity_check(self) -> None:
        definition = next(item for item in builtin_definitions() if item.name == "ralplan")
        self.assertTrue(
            any("`Ideal-state fidelity`" in line for line in definition.final_checklist),
            "ralplan can finish without checking the ideal-state mapping",
        )

    def test_portable_projection_carries_the_same_rules(self) -> None:
        cases = {"ulw-plan": RALPLAN_TOKENS, "omh-plan": PLAN_TOKENS}
        for name, tokens in cases.items():
            body = _portable_body(name)
            for token in tokens:
                with self.subTest(skill=name, token=token):
                    self.assertIn(token, body)

    def test_bodies_stay_under_the_ceiling_and_dense(self) -> None:
        for name in ("plan", "ralplan"):
            with self.subTest(skill=name):
                self.assertLessEqual(
                    len(_hermes_body(name).encode("utf-8")), STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING
                )
        measured = {item.skill for item in skill_density_measurements()}
        self.assertTrue({"plan", "ralplan"} <= measured)
        flagged = {item["skill"] for item in skill_density_violations()}
        self.assertFalse({"plan", "ralplan"} & flagged, skill_density_violations())


if __name__ == "__main__":
    unittest.main()
