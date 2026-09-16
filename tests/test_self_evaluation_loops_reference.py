"""The self-evaluation-loops reference carries the clauses that keep a score honest.

Each locked string prevents a specific failure: a rubric reached for on code
a machine could simply run, a loop with no ceiling or no convergence break, a
threshold invented after the score, criteria derived from the output they are
meant to test, a self-judgement reported as verification, or a judge score
read as correctness. A rewrite that drops one should fail here rather than
ship.
"""

from __future__ import annotations

import unittest

from omh.skills.catalog import builtin_definitions
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import agent_evaluation_reference_templates

REFERENCE = ("agent-evaluation", "references/self-evaluation-loops.md")


class SelfEvaluationLoopsReferenceTests(unittest.TestCase):
    def _content(self) -> str:
        templates = agent_evaluation_reference_templates()
        self.assertEqual([(t.skill_name, t.relative_path) for t in templates], [REFERENCE])
        return templates[0].content

    def test_the_packaged_set_includes_it(self) -> None:
        packaged = {(t.skill_name, t.relative_path) for t in builtin_skill_reference_templates()}
        self.assertIn(REFERENCE, packaged)

    def test_the_three_shapes_survive_with_their_judge(self) -> None:
        content = self._content()
        for shape in ("Reflection", "Evaluator-optimizer", "Test-driven refinement"):
            with self.subTest(shape=shape):
                row = [line for line in content.splitlines() if line.startswith(f"| {shape} |")]
                self.assertEqual(len(row), 1, f"{shape} needs exactly one row")

    def test_an_executable_check_outranks_a_judge(self) -> None:
        content = self._content()
        self.assertIn("**An executable check outranks a judge whenever one exists.**", content)
        self.assertIn("A test that\nfails is a fact", content)
        self.assertIn("confident garbage", content)

    def test_all_three_stop_rules_survive(self) -> None:
        content = self._content()
        for rule in (
            "**A maximum iteration count.**",
            "**A score threshold**",
            "**A no-improvement break.**",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, content)
        self.assertIn("a threshold set afterwards is a\n   description of the score that happened", content)
        self.assertIn('only stop is "it looks good now" is a defect', content)
        self.assertIn("**which of the three rules ended it**", content)

    def test_criteria_precede_generation(self) -> None:
        content = self._content()
        self.assertIn("written **before generation**", content)
        self.assertIn("criteria derived from an output describe it rather than test it", content)
        self.assertIn("a single\nnumber hides which dimension failed", content)

    def test_self_judgement_is_labelled_the_weakest_class(self) -> None:
        content = self._content()
        self.assertIn("**Self-judgement is the weakest evidence class in the ladder**", content)
        self.assertIn("A judge score is never correctness", content)

    def test_the_evidence_boundary_survives(self) -> None:
        content = self._content()
        self.assertIn("is prepared analysis", content)
        self.assertIn("a refined output is not a\nverified output", content)
        self.assertIn("an improved score is a statement about the rubric, not\nabout the world", content)

    def test_the_bands_state_that_they_are_unverified_here(self) -> None:
        # The bands are the conventional reading of a chance-corrected
        # statistic and were measured on no judge this repository uses. A
        # reader applying the table correctly still reads their own figure
        # against numbers nobody checked, so the table says so itself. The
        # first row is a rule, not a calibration, and survives whatever a
        # later measurement shows (#1612).
        content = self._content()
        self.assertIn("not a figure measured here", content)
        self.assertIn("no grader model and no hand-labeled sample of its own", content)
        self.assertIn("The first row is a rule rather than a calibration", content)
        self.assertIn(
            "| not measured | unqualified; reported as unqualified, never quoted as a result |",
            content,
        )
        self.assertIn("too small to separate 0.4 from\n0.6, that is the result", content)

    def test_the_skill_body_points_at_the_reference(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        evaluation = definitions["agent-evaluation"]
        quality_bar = "\n".join(evaluation.quality_bar)
        self.assertIn("omh-agent-evaluation/references/self-evaluation-loops.md", quality_bar)
        self.assertIn("an executable check outranks a judge", quality_bar)
        self.assertIn("Declare all three stop rules before the loop runs", quality_bar)
        safety = "\n".join(evaluation.safety_rules)
        self.assertIn("A judge score is never correctness", safety)
        self.assertIn("weakest evidence class", safety)


if __name__ == "__main__":
    unittest.main()
