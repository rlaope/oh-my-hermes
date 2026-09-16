"""The decision-records reference carries the clauses that keep ADRs honest.

Each locked string prevents a specific failure: a record written for a
routine choice, an accepted record edited in place, a rejected record
deleted out from under decision-recall, a consequences section with no
negatives, or a silent file write before the user approved it. A rewrite
that drops one should fail here rather than ship.
"""

from __future__ import annotations

import unittest

from omh.skills.catalog import builtin_definitions
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import strategy_brief_reference_templates


class DecisionRecordsReferenceTests(unittest.TestCase):
    def _content(self) -> str:
        """Select the decision-records reference by name, not by position.

        This asserted that `strategy-brief`'s whole template list equalled one
        row, which located `templates[0]` by making it the only row. That is a
        stronger claim than any case here needs: every assertion below is about
        the decision-records document specifically -- the `docs/adr/`
        convention, the Proposed/Accepted lifecycle, the `decision-recall`
        corpus -- so a second reference on the skill sits outside their subject
        rather than violating it. `test_the_packaged_set_includes_it` already
        asks the membership question the right way, with `assertIn`. Selecting
        by name keeps every locked string and stops a later reference from
        failing cases that were never about it.
        """
        path = "references/decision-records.md"
        by_path = {t.relative_path: t for t in strategy_brief_reference_templates()}
        self.assertIn(path, by_path)
        self.assertEqual(by_path[path].skill_name, "strategy-brief")
        return by_path[path].content

    def test_the_packaged_set_includes_it(self) -> None:
        packaged = {(t.skill_name, t.relative_path) for t in builtin_skill_reference_templates()}
        self.assertIn(("strategy-brief", "references/decision-records.md"), packaged)

    def test_the_three_condition_trigger_survives(self) -> None:
        content = self._content()
        for marker in (
            "**Hard to reverse**",
            "**Surprising without its context**",
            "**A real trade-off**",
            "Two of three or fewer: no record",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, content)

    def test_the_file_convention_survives(self) -> None:
        content = self._content()
        self.assertIn("`docs/adr/`", content)
        self.assertIn("`NNNN-short-slug.md`", content)
        for field in (
            "**Status**",
            "**Context**",
            "**Drivers**",
            "**Considered Options**",
            "**Decision**",
            "**Consequences**",
            "**Related**",
        ):
            with self.subTest(field=field):
                self.assertIn(field, content)
        self.assertIn("a consequences section with no negatives has\n  not been finished", content)

    def test_the_lifecycle_and_supersede_rule_survive(self) -> None:
        content = self._content()
        self.assertIn("`Proposed -> Accepted -> Deprecated | Superseded`", content)
        self.assertIn("An accepted record is never edited", content)
        self.assertIn("status moves to Superseded with a forward link", content)
        self.assertIn("Rejected\n  records are the corpus `decision-recall` reads", content)
        self.assertIn("deleting one deletes the warning", content)

    def test_the_approval_and_evidence_boundary_survives(self) -> None:
        content = self._content()
        self.assertIn("nothing is written until the user\napproves the write", content)
        self.assertIn("never evidence that the decided work was implemented", content)

    def test_the_skill_body_points_at_the_reference(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        quality_bar = "\n".join(definitions["strategy-brief"].quality_bar)
        self.assertIn("omh-decide/references/decision-records.md", quality_bar)
        self.assertIn("all three or no record", quality_bar)
        self.assertIn("Never edit an accepted record", quality_bar)
        self.assertIn("`decision-recall` reads later", quality_bar)


if __name__ == "__main__":
    unittest.main()
