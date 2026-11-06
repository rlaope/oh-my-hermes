"""The cleanup-passes reference carries the clauses that prevent a wrong cleanup.

Each locked string is the sentence that stops a specific failure: a bundled
multi-smell diff nobody can review for behavior preservation, a silently
widened scope, a detector output treated as a verdict, or a red gate carried
into the next pass. A rewrite that drops one should fail here, not ship.
"""

from __future__ import annotations

import unittest

from omh.skills.catalog import builtin_definitions
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.catalog_portable import PORTABLE_REFERENCE_PATHS
from omh.skills.render import ai_slop_cleaner_reference_templates, ai_slop_ui_review_reference_templates


def _flat(text: str) -> str:
    return " ".join(text.split())


class AiSlopCleanerReferenceTests(unittest.TestCase):
    def _content(self) -> str:
        templates = ai_slop_cleaner_reference_templates()
        self.assertEqual(
            [(t.skill_name, t.relative_path) for t in templates],
            [("ai-slop-cleaner", "references/cleanup-passes.md")],
        )
        return templates[0].content

    def test_the_packaged_set_includes_it(self) -> None:
        packaged = {(t.skill_name, t.relative_path) for t in builtin_skill_reference_templates()}
        self.assertIn(("ai-slop-cleaner", "references/cleanup-passes.md"), packaged)

    def test_the_six_taxonomy_categories_are_named(self) -> None:
        content = self._content()
        for category in (
            "Duplication",
            "Dead code",
            "Needless abstraction",
            "Boundary violation",
            "Missing tests",
            "Templated defaults",
        ):
            with self.subTest(category=category):
                self.assertIn(category, content)

    def test_the_pass_order_is_fixed_and_gated(self) -> None:
        content = self._content()
        self.assertLess(content.index("**Dead code**"), content.index("**Duplicates**"))
        self.assertLess(content.index("**Duplicates**"), content.index("**Naming and error handling**"))
        self.assertLess(
            content.index("**Naming and error handling**"), content.index("**Test reinforcement**")
        )
        self.assertIn("Never carry a red gate forward", content)

    def test_scope_detection_and_report_contracts_survive(self) -> None:
        content = self._content()
        self.assertIn("never edited, and never used to justify widening the diff", _flat(content))
        self.assertIn("candidate list, not a verdict", content)
        self.assertIn("prepared_not_observed", content)
        for part in ("changed files", "simplifications", "behavior lock", "remaining risks"):
            with self.subTest(part=part):
                self.assertIn(part, content)
        self.assertIn("## Boundary", content)

    def test_the_body_points_at_the_reference_and_orders_the_passes(self) -> None:
        definition = next(d for d in builtin_definitions() if d.name == "ai-slop-cleaner")
        joined = "\n".join(definition.quality_bar)
        self.assertIn("omh-ai-slop-cleaner/references/cleanup-passes.md", joined)
        self.assertIn("never bundling categories", joined)
        self.assertIn("templated defaults", joined)
        safety = "\n".join(definition.safety_rules)
        self.assertIn("never widen it silently", safety)

    def test_review_mode_edits_nothing_and_reuses_the_code_review_shape(self) -> None:
        content = self._content()
        review = _flat(content[content.index("## Review mode"):content.index("## Boundary")])
        self.assertIn("opens no file for writing", review)
        for field in ("`priority` (`P0`-`P3`)", "`path`", "`line_range`", "`ship` or `no_ship`"):
            with self.subTest(field=field):
                self.assertIn(field, review)
        self.assertIn("No new verdict vocabulary", review)
        self.assertIn("separate writer pass", review)
        self.assertIn("A reviewer who applies its own fix has turned back into a writer", review)

    def test_the_body_names_review_mode_the_ui_checklist_and_the_closing_record(self) -> None:
        definition = next(d for d in builtin_definitions() if d.name == "ai-slop-cleaner")
        joined = "\n".join(definition.quality_bar)
        self.assertIn("`deslop review`", joined)
        self.assertIn("never a new verdict format", joined)
        self.assertIn("separate writer pass", joined)
        self.assertIn("omh-ai-slop-cleaner/references/ui-review-checklist.md", joined)
        self.assertIn("omh runtime record --skill ai-slop-cleaner", joined)
        self.assertIn("a review-mode run carries the ship or no_ship verdict and the finding count", joined)
        self.assertIn("not_observed", joined)


class AiSlopUiReviewChecklistTests(unittest.TestCase):
    def _content(self) -> str:
        templates = ai_slop_ui_review_reference_templates()
        self.assertEqual(
            [(t.skill_name, t.relative_path) for t in templates],
            [("ai-slop-cleaner", "references/ui-review-checklist.md")],
        )
        return templates[0].content

    def test_it_ships_in_both_projections(self) -> None:
        packaged = {(t.skill_name, t.relative_path) for t in builtin_skill_reference_templates()}
        self.assertIn(("ai-slop-cleaner", "references/ui-review-checklist.md"), packaged)
        self.assertIn("ai-slop-cleaner/references/ui-review-checklist.md", PORTABLE_REFERENCE_PATHS)

    def test_the_six_prompts_are_review_prompts_not_bans(self) -> None:
        content = self._content()
        for prompt in (
            "Korean body text below 14px",
            "Shadows everywhere",
            "Stacked section labels",
            "Default palette",
            "Uniform grid",
            "Extreme gradients",
        ):
            with self.subTest(prompt=prompt):
                self.assertIn(prompt, content)
        self.assertIn("Every item is a question, not a ban", content)
        self.assertIn("A stated reason", content)

    def test_it_defers_reasoning_to_frontend_and_redesign_to_its_owners(self) -> None:
        content = _flat(self._content())
        self.assertIn("omh-frontend/references/taste-foundations.md", content)
        self.assertIn("a redesign goes to `omh-frontend`", content)
        self.assertIn("`omh-frontend-refactor`", content)
        self.assertIn("needs the rendered page", content)


class LoopCleanerPassTests(unittest.TestCase):
    def test_both_loop_projections_scope_the_pass_and_never_report_a_skip_as_passed(self) -> None:
        definition = next(d for d in builtin_definitions() if d.name == "loop")
        for projection, lines in (
            ("hermes", definition.quality_bar),
            ("portable", definition.portable_overrides["quality_bar"]),
        ):
            with self.subTest(projection=projection):
                line = next(line for line in lines if "`ai-slop-cleaner` pass" in line)
                self.assertIn("`changed_files`", line)
                self.assertIn("never wider", line)
                self.assertIn("must not regress", line)
                self.assertIn("is an explicit `skipped`, and a reverted pass is `reverted`, never `passed`", line)
                self.assertIn("`omh runtime record --skill ai-slop-cleaner", line)
                self.assertIn("--cleanup-outcome passed|skipped|reverted", line)


if __name__ == "__main__":
    unittest.main()
