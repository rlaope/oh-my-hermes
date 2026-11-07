"""The a11y-rules reference carries the clauses that keep an audit comparable.

Each locked string prevents a specific failure: a finding written as prose
instead of a rule ID, a meaning-dependent fix marked auto-fixable (which
ships confident, wrong alternative text), a half-structural fix rounded to
one side, a rerun that cannot say what was resolved, or a fix class read as
evidence the fix was applied. A rewrite that drops one should fail here
rather than ship.
"""

from __future__ import annotations

import re
import unittest

from omh.skills.catalog import builtin_definitions
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import accessibility_audit_reference_templates

# Every rule the audit can cite. A category that loses its rules stops being
# reportable, so the set is the contract, not the count.
EXPECTED_RULE_IDS = (
    "IMG-1", "IMG-2",
    "LNK-1", "LNK-2", "LNK-3", "BTN-1",
    "FORM-1", "FORM-2", "FORM-3",
    "ARIA-1", "ARIA-2", "ARIA-3",
    "KEY-1", "KEY-2", "KEY-3", "KEY-4",
    "RFL-1", "TGT-1", "STAT-1",
    "SEM-1", "SEM-2", "SEM-3", "SEM-4", "SEM-5",
    "COL-1", "COL-2", "COL-3",
)


class A11yRulesReferenceTests(unittest.TestCase):
    def _content(self) -> str:
        templates = accessibility_audit_reference_templates()
        self.assertEqual(
            [(t.skill_name, t.relative_path) for t in templates],
            [("accessibility-audit", "references/a11y-rules.md")],
        )
        return templates[0].content

    def test_the_packaged_set_includes_it(self) -> None:
        packaged = {(t.skill_name, t.relative_path) for t in builtin_skill_reference_templates()}
        self.assertIn(("accessibility-audit", "references/a11y-rules.md"), packaged)

    def test_every_rule_id_survives_with_a_wcag_criterion(self) -> None:
        content = self._content()
        for rule_id in EXPECTED_RULE_IDS:
            with self.subTest(rule=rule_id):
                row = [line for line in content.splitlines() if line.startswith(f"| {rule_id} |")]
                self.assertEqual(len(row), 1, f"{rule_id} needs exactly one rule row")
                # A rule without a criterion is an opinion; the WCAG number is
                # what makes the finding arguable against a standard.
                self.assertRegex(row[0], r"\|\s*\d\.\d\.\d")

    def test_each_rule_row_declares_a_fix_class(self) -> None:
        content = self._content()
        for rule_id in EXPECTED_RULE_IDS:
            with self.subTest(rule=rule_id):
                row = next(line for line in content.splitlines() if line.startswith(f"| {rule_id} |"))
                self.assertTrue(
                    "`auto`" in row or "`manual`" in row,
                    f"{rule_id} must say whether its fix is auto or manual",
                )

    def test_the_derivability_test_for_auto_survives(self) -> None:
        content = self._content()
        self.assertIn("only when the correct output is derivable from the markup", content)
        self.assertIn("is `manual` whenever producing it requires knowing what the", content)
        self.assertIn("content *means*", content)
        self.assertIn("is a defect in the audit", content)
        self.assertIn("confident, wrong alternative text", content)

    def test_a_half_structural_fix_is_split_not_rounded(self) -> None:
        content = self._content()
        self.assertIn("split\ninto its `auto` half and its `manual` half rather than rounded", content)
        self.assertIn("split: role and focusability `auto`, the key handler `manual`", content)

    def test_the_report_shape_and_rerun_contract_survive(self) -> None:
        content = self._content()
        self.assertIn("Read the target surface completely, collect every finding, then report", content)
        self.assertIn("`rule ID | severity | location | WCAG criterion | fix class | the fix`", content)
        self.assertIn("resolved when its ID no longer matches at that location", content)

    def test_severity_stays_separate_from_the_verdict(self) -> None:
        content = self._content()
        self.assertIn("it is not the audit\nverdict, which stays PASS/HOLD/BLOCK on observed evidence", content)

    def test_the_evidence_boundary_survives(self) -> None:
        content = self._content()
        self.assertIn("neither is\nevidence the fix was applied", content)
        self.assertIn("a scan that\nproduced these findings is not a keyboard walk", content)

    def test_the_skill_body_points_at_the_reference(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        audit = definitions["accessibility-audit"]
        quality_bar = "\n".join(audit.quality_bar)
        self.assertIn("omh-accessibility-audit/references/a11y-rules.md", quality_bar)
        self.assertIn("stable rule ID", quality_bar)
        self.assertIn("A meaning-dependent fix marked `auto` is a defect", quality_bar)
        safety = "\n".join(audit.safety_rules)
        self.assertIn("never evidence it was applied", safety)

    def test_rule_ids_use_one_scheme(self) -> None:
        # A stray scheme (lowercase, no number, a different separator) breaks
        # the string match a rerun uses to reconcile findings.
        content = self._content()
        cited = {
            match
            for match in re.findall(r"^\| ([A-Z][A-Z0-9-]*) \|", content, flags=re.MULTILINE)
            if match != "ID"  # the table header, not a rule
        }
        self.assertEqual(cited, set(EXPECTED_RULE_IDS))


if __name__ == "__main__":
    unittest.main()
