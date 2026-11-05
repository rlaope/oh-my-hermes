from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.skills.catalog import builtin_definitions  # noqa: E402
from omh.skills.catalog_types import (  # noqa: E402
    PROCEDURE_BAIL_LEVELS,
    ProcedureBail,
    ProcedureStep,
)
from omh.skills import procedure_validation, structure_lint  # noqa: E402
from omh.skills.catalog_types import (  # noqa: E402
    _CATEGORY_RECOVERY_NOTES,
    _GENERAL_RECOVERY_NOTES,
    _HANDOFF_RECOVERY_NOTES,
)
from omh.skills.validation import skill_structure_lint_payload  # noqa: E402
from omh.skills.procedure_rendering import (  # noqa: E402
    copy_procedure_step_payloads,
    procedure_markdown,
    procedure_reference_lines,
    procedure_step_payloads,
)


class ProcedureBailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.finance = next(item for item in builtin_definitions() if item.name == "finance-analysis")
        self.bail = ProcedureBail((), "unresolved", "Return the inspected sources and missing periods.")
        self.bailed = replace(
            self.finance,
            procedure_steps=tuple(
                replace(step, on_fail=self.bail if step.kind in {"production", "validation"} else None)
                for step in self.finance.procedure_steps
            ),
        )
        self.validation_index = next(
            index for index, step in enumerate(self.bailed.procedure_steps) if step.kind == "validation"
        )

    def _with_bail(self, bail, index=None):
        target = self.validation_index if index is None else index
        return replace(
            self.bailed,
            procedure_steps=tuple(
                replace(step, on_fail=bail) if index == target else step
                for index, step in enumerate(self.bailed.procedure_steps)
            ),
        )

    def _violations(self, definition):
        with patch.object(
            procedure_validation,
            "PROCEDURE_BAIL_PENDING",
            procedure_validation.PROCEDURE_BAIL_PENDING - {self.finance.name},
        ):
            return procedure_validation.procedure_violation_ids(definition)

    def test_bail_is_frozen_and_levels_are_closed(self) -> None:
        self.assertEqual(PROCEDURE_BAIL_LEVELS, ("tentative", "unresolved", "not_observed"))
        self.assertEqual(self.bail.fallback_skill, "")
        with self.assertRaises(FrozenInstanceError):
            self.bail.handback = "Changed."

    def test_required_bail_missing_fires_alone(self) -> None:
        self.assertEqual(self._violations(self._with_bail(None)), ["procedure_bail_required"])
        steps = list(self.bailed.procedure_steps)
        steps[self.validation_index] = replace(steps[self.validation_index], kind="production", on_fail=None)
        self.assertEqual(
            self._violations(replace(self.bailed, procedure_steps=tuple(steps))),
            ["procedure_bail_required"],
        )

    def test_analysis_without_bail_and_empty_stands_are_valid(self) -> None:
        self.assertEqual(self._violations(self.bailed), [])
        self.assertEqual(self._violations(self._with_bail(self.bail, index=0)), [])

    def test_unknown_level_fires_alone(self) -> None:
        self.assertEqual(
            self._violations(self._with_bail(replace(self.bail, downgrade_to="complete"))),
            ["procedure_bail_unknown_level"],
        )

    def test_stands_must_come_from_an_earlier_step(self) -> None:
        earlier = self.bailed.procedure_steps[0].output_refs
        self.assertEqual(self._violations(self._with_bail(replace(self.bail, still_stands=earlier))), [])
        current = self.bailed.procedure_steps[self.validation_index].output_refs
        later = self.bailed.procedure_steps[-1].output_refs
        for refs in (("missing/v1",), current, later):
            with self.subTest(refs=refs):
                self.assertEqual(
                    self._violations(self._with_bail(replace(self.bail, still_stands=refs))),
                    ["procedure_bail_unknown_stands_ref"],
                )

    def test_handback_must_be_nonempty_and_not_placeholder(self) -> None:
        for handback in ("", "   ", "TODO finish", "[TBD]", "\ufeffＴＯＤＯ prepare"):
            with self.subTest(handback=handback):
                self.assertEqual(
                    self._violations(self._with_bail(replace(self.bail, handback=handback))),
                    ["procedure_bail_handback_required"],
                )

    def test_fallback_requires_another_installable_canonical_skill(self) -> None:
        for name in ("missing-skill", "omh-plan", self.finance.name):
            with self.subTest(name=name):
                self.assertEqual(
                    self._violations(self._with_bail(replace(self.bail, fallback_skill=name))),
                    ["procedure_bail_unknown_fallback"],
                )
        self.assertEqual(self._violations(self._with_bail(replace(self.bail, fallback_skill="plan"))), [])

    def test_optional_analysis_bail_is_validated(self) -> None:
        self.assertEqual(
            self._violations(self._with_bail(replace(self.bail, downgrade_to="complete"), index=0)),
            ["procedure_bail_unknown_level"],
        )

    def test_pending_exempts_only_missing_bails_and_rejects_stale_entry(self) -> None:
        with patch.object(procedure_validation, "PROCEDURE_BAIL_PENDING", frozenset({self.finance.name})):
            unbailed = replace(
                self.finance,
                procedure_steps=tuple(replace(step, on_fail=None) for step in self.finance.procedure_steps),
            )
            self.assertEqual(procedure_validation.procedure_violation_ids(unbailed), [])
            self.assertEqual(
                procedure_validation.procedure_violation_ids(self.bailed),
                ["procedure_bail_pending_stale"],
            )
            malformed = replace(self.bail, downgrade_to="complete")
            self.assertEqual(
                procedure_validation.procedure_violation_ids(self._with_bail(malformed, index=0)),
                ["procedure_bail_unknown_level", "procedure_bail_pending_stale"],
            )

    def test_pending_all_analysis_contract_is_not_a_stale_bail_entry(self) -> None:
        analysis_only = replace(
            self.finance,
            procedure_steps=tuple(
                replace(step, kind="analysis", on_fail=None) for step in self.finance.procedure_steps
            ),
        )
        with patch.object(procedure_validation, "PROCEDURE_BAIL_PENDING", frozenset({self.finance.name})):
            self.assertEqual(
                procedure_validation.procedure_violation_ids(analysis_only),
                ["procedure_missing_validation_step"],
            )

    def test_render_fail_line_follows_check_ids_in_both_formats(self) -> None:
        ref = self.bailed.procedure_steps[0].output_refs[0]
        bail = replace(self.bail, still_stands=(ref,), fallback_skill="plan")
        definition = self._with_bail(bail)
        step = definition.procedure_steps[self.validation_index]
        check_line = f"- Check IDs: {', '.join(f'`{value}`' for value in step.check_ids)}"
        fail_line = (
            f"- If this step fails: unresolved; still stands: `{ref}`; hand back: {bail.handback}"
        )
        fallback_line = "- Then continue with: `omh-plan`"
        self.assertIn(f"{check_line}\n{fail_line}\n{fallback_line}", procedure_markdown(definition))
        self.assertIn(
            f"    {check_line}\n    {fail_line}\n    {fallback_line}",
            "\n".join(procedure_reference_lines(definition)),
        )

    def test_render_empty_stands_and_omit_unset_fallback(self) -> None:
        expected = (
            f"- If this step fails: unresolved; still stands: nothing yet; hand back: {self.bail.handback}"
        )
        for text in (procedure_markdown(self.bailed), "\n".join(procedure_reference_lines(self.bailed))):
            with self.subTest(text=text):
                self.assertIn(expected, text)
                self.assertNotIn("- Then continue with:", text)
        unbailed = replace(
            self.finance,
            procedure_steps=tuple(replace(step, on_fail=None) for step in self.finance.procedure_steps),
        )
        self.assertNotIn("- If this step fails:", procedure_markdown(unbailed))
        self.assertNotIn("- If this step fails:", "\n".join(procedure_reference_lines(unbailed)))

    def test_payload_includes_bail_only_when_set_and_copy_is_independent(self) -> None:
        payloads = procedure_step_payloads(self.bailed)
        self.assertNotIn("on_fail", payloads[0])
        expected = {
            "still_stands": [],
            "downgrade_to": "unresolved",
            "handback": self.bail.handback,
            "fallback_skill": "",
        }
        self.assertEqual(payloads[self.validation_index].get("on_fail"), expected)
        copied = copy_procedure_step_payloads(payloads)
        self.assertEqual(copied, payloads)
        copied[self.validation_index]["on_fail"]["still_stands"].append("changed/v1")
        copied[self.validation_index]["on_fail"]["handback"] = "Changed."
        self.assertEqual(payloads[self.validation_index]["on_fail"], expected)
        self.assertNotIn("on_fail", copied[0])

    def test_existing_positional_step_defaults_to_no_bail(self) -> None:
        step = ProcedureStep("scope", "analysis", ("input",), ("output",), ("check",), "Inspect scope.")
        self.assertIn("on_fail", step.__dataclass_fields__)
        self.assertIsNone(step.on_fail)


class RecoverySpecificLintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.finance = next(item for item in builtin_definitions() if item.name == "finance-analysis")

    def _findings(self, definitions=None):
        return [
            item for item in skill_structure_lint_payload(definitions=definitions)["violations"]
            if item["rule"] == "SKILL_RECOVERY_SPECIFIC"
        ]

    def test_default_library_notes_fail_outside_ratchet(self) -> None:
        with patch.object(structure_lint, "RECOVERY_DEFAULT_ONLY_ALLOWED", ()):
            for notes in (_GENERAL_RECOVERY_NOTES, _HANDOFF_RECOVERY_NOTES, *_CATEGORY_RECOVERY_NOTES.values()):
                with self.subTest(notes=notes):
                    findings = self._findings([replace(self.finance, recovery_notes=notes)])
                    self.assertEqual(len(findings), 1)
                    self.assertEqual(findings[0]["skill"], self.finance.name)

    def test_specific_note_makes_ratchet_entry_stale(self) -> None:
        specific = replace(self.finance, recovery_notes=(
            "If source totals cannot tie, keep the finance scope record, mark reconciliation unresolved, and return the missing periods.",
        ))
        with patch.object(structure_lint, "RECOVERY_DEFAULT_ONLY_ALLOWED", (self.finance.name,)):
            findings = self._findings([specific])
            self.assertEqual(len(findings), 1)
            self.assertIn("remove it from RECOVERY_DEFAULT_ONLY_ALLOWED", findings[0]["detail"])
        with patch.object(structure_lint, "RECOVERY_DEFAULT_ONLY_ALLOWED", ()):
            self.assertEqual(self._findings([specific]), [])

    def test_only_installable_skills_count(self) -> None:
        with patch.object(structure_lint, "RECOVERY_DEFAULT_ONLY_ALLOWED", ()):
            self.assertEqual(self._findings([replace(
                self.finance, name="not-installable", recovery_notes=_GENERAL_RECOVERY_NOTES,
            )]), [])

    def test_rule_is_registered_sorted_and_current_tree_passes(self) -> None:
        self.assertIn("SKILL_RECOVERY_SPECIFIC", structure_lint.STRUCTURE_LINT_RULE_IDS)
        self.assertEqual(tuple(sorted(structure_lint.STRUCTURE_LINT_RULE_IDS)), structure_lint.STRUCTURE_LINT_RULE_IDS)
        self.assertEqual(self._findings(), [])


class BailCoverageTests(unittest.TestCase):
    """The run that introduced bail points finished both migrations; these pins keep them finished."""

    def test_both_ratchets_are_empty(self) -> None:
        self.assertEqual(procedure_validation.PROCEDURE_BAIL_PENDING, frozenset())
        self.assertEqual(structure_lint.RECOVERY_DEFAULT_ONLY_ALLOWED, ())

    def test_every_production_and_validation_step_carries_a_bail(self) -> None:
        missing = sorted(
            (definition.name, step.step_id)
            for definition in builtin_definitions()
            for step in definition.procedure_steps
            if step.kind in {"production", "validation"} and step.on_fail is None
        )
        self.assertEqual(missing, [])

    def test_recovery_notes_name_siblings_by_their_loadable_label(self) -> None:
        from omh.catalogs.skill_display_names import omh_skill_display_name
        from omh.skills.packaging import builtin_skill_templates
        import re

        from omh.skills.catalog import installable_skill_names

        installable = set(installable_skill_names())
        stale = []
        for template in builtin_skill_templates():
            match = re.search(r"^## Recovery Notes\n\n(.*?)(?:\n\n## |\Z)", template.content, re.S | re.M)
            if match is None:
                continue
            for token in re.findall(r"`([a-z0-9][a-z0-9-]*)`", match.group(1)):
                if token in installable and omh_skill_display_name(token) != token:
                    stale.append((template.name, token))
        self.assertEqual(stale, [])


if __name__ == "__main__":
    unittest.main()
