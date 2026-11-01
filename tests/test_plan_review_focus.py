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
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import agent_skill_templates, workflow_skill_from_definition

PLAN_TOKENS = (
    "When the plan describes code changes",  # the scope: triage and hub requests are plans too
    "`Review Focus`",   # the section name
    "at most 5",        # the cap
    "id of the owning task",  # each line is assigned, by id, to the task that adds its test
    "found none",       # an empty section is a recorded check, not a skipped one
    "outcome can be checked",  # one action per step
    "proportion check",  # plan length against the code it leads to
)

# Execution shape (borrowed from OMC ultragoal's stories and final gate, adapted):
# each task carries its dependencies, write scope and done check, and the last
# task is a closing gate whose unclean review adds a bounded fix task.
PLAN_TASK_SHAPE_TOKENS = (
    "stable id (`T1`, `T2`, ...)",
    "the ids it depends on",
    "the files it may write",
    "its done check",
    # dag-ulw refuses a shared write scope unless one node lists the other
    # directly (dag_core.shared_scope_pairs); an order through a third does not count
    "when two tasks write the same file, one lists the other directly among its dependencies",
    "an order through a third task does not count",
)
PLAN_CLOSING_GATE_TOKENS = (
    "its last task is the closing gate",
    "named as the verification task",  # dag-ulw recognises a verification node by its name
    "depends on every other task",
    "runs the real verification commands",
    "someone other than the agent that built the work",  # never the builder's own reading
    "ends with a review",
    "adds a fix task with its own id and done check",  # an unclean review is not done
    "instead of ending the plan",
    "at most two fix rounds",  # bounded, unlike ultragoal's open-ended blocker stories
    "open findings are reported",
)
# Only the Hermes projection ships `dag-ulw`, so only its body may name it.
PLAN_DAG_ULW_TOKENS = (
    "`dag-ulw` for an accepted plan whose tasks form a graph",  # the follow-on path
    "plus a separate verification task",  # its fit reason
    "carry a `dag-ulw` node's id, depends_on and write_scope",  # the mapping
    "the done check feeds its VERIFY and STOP WHEN",
    "converting still adds each node's label, category and full prompt",  # not a ready-made graph
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

    def test_plan_body_carries_task_shape_and_closing_gate_tokens(self) -> None:
        hermes = _hermes_body("plan")
        portable = _portable_body("omh-plan")
        for token in PLAN_TASK_SHAPE_TOKENS + PLAN_CLOSING_GATE_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, hermes)
                self.assertIn(token, portable)

    def test_plan_completion_checklist_requires_task_fields_and_the_closing_gate(self) -> None:
        checklist = " ".join(_definition("plan").final_checklist)
        for token in (
            "owning task ids",
            "every task has an id, its dependencies, the files it may write, and a done check",
            "the last task is the closing gate",
        ):
            with self.subTest(token=token):
                self.assertIn(token, checklist)

    def test_plan_file_adoption_adds_the_task_fields_and_the_closing_gate(self) -> None:
        # A `/plan` file adopted as the draft must gain what the checklist requires.
        reference = next(
            item.content
            for item in builtin_skill_reference_templates()
            if item.skill_name == "plan" and item.relative_path == "references/hermes-plan-mode.md"
        )
        line = next(line for line in reference.splitlines() if line.startswith("- Add what the file lacks"))
        for token in ("`Review Focus`", "each task's id, dependencies, write scope and done check", "the closing gate task"):
            with self.subTest(token=token):
                self.assertIn(token, line)

    def test_dag_ulw_reaches_only_the_hermes_planning_bodies(self) -> None:
        for name in ("plan", "ralplan"):
            body = _hermes_body(name)
            with self.subTest(skill=name, target="hermes"):
                self.assertIn(PLAN_DAG_ULW_TOKENS[0], body)
                self.assertIn(PLAN_DAG_ULW_TOKENS[1], body)
        for token in PLAN_DAG_ULW_TOKENS[2:]:
            with self.subTest(skill="plan", token=token):
                self.assertIn(token, _hermes_body("plan"))
        for name in ("omh-plan", "ulw-plan"):
            with self.subTest(skill=name, target="agent-skills"):
                self.assertNotIn("dag-ulw", _portable_body(name))

    def test_portable_projection_carries_the_same_tokens(self) -> None:
        cases = {"ulw-plan": RALPLAN_TOKENS, "omh-plan": PLAN_TOKENS}
        for name, tokens in cases.items():
            body = _portable_body(name)
            for token in tokens:
                with self.subTest(skill=name, token=token):
                    self.assertIn(token, body)


if __name__ == "__main__":
    unittest.main()
