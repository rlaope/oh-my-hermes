"""Rules the build holds, reference use, and options shown as pictures.

Bodies are re-derived from the producers, so the assertions follow the text
the skills actually ship rather than a copy of it.
"""

from __future__ import annotations

import re
import unittest

from omh.skills.catalog import builtin_definitions
from omh.skills.render import (
    _component_registry_adoption_reference,
    _design_system_contract_reference,
    _reference_token_extraction_reference,
)

_ORCHESTRATION_LINES = (
    "The options in `design_direction_set/v1` are shown as rendered images; "
    "an option described only in words is not yet an option.",
    "Running to the end without asking is for runs nobody can answer "
    "(scheduled, batch) or when the user handed the choice over.",
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(body: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", body, re.S | re.M)
    assert match, f"missing section {heading}"
    return _flat(match.group(1))


def _orchestration():
    for definition in builtin_definitions():
        if definition.name == "design-orchestration":
            return definition
    raise AssertionError("design-orchestration definition missing")


class ContractRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.body = _design_system_contract_reference()
        self.rules = _section(self.body, "Rules the build holds")

    def test_section_is_present_and_body_numbering_untouched(self) -> None:
        self.assertIn("## Rules the build holds", self.body)
        self.assertLess(self.body.index("## Workflow"), self.body.index("## Rules the build holds"))
        self.assertLess(self.body.index("## Rules the build holds"), self.body.index("## Boundary"))
        self.assertIn("12. **Research Log**", self.body)
        self.assertNotIn("13. **", self.body)

    def test_source_checks_run_in_the_build(self) -> None:
        for token in ("becomes a test", "build", "emoji used as icons", "motion profiles", "danger"):
            self.assertIn(token, self.rules)

    def test_one_escape_marker(self) -> None:
        for token in ("One escape marker", "one named attribute or comment", "skips only that element", "lists those files"):
            self.assertIn(token, self.rules)

    def test_closed_sets_tied_to_roles_and_radius_knob_kept(self) -> None:
        for token in ("Closed sets", "control heights", "heading steps", "fixed count", "in-between value", "size names"):
            self.assertIn(token, self.rules)
        self.assertIn("One radius knob.", _flat(self.body))
        self.assertIn("complements the one radius knob", self.rules)

    def test_rule_history(self) -> None:
        for token in ("date", "what the user asked for", "what went wrong"):
            self.assertIn(token, self.rules)

    def test_decided_and_open(self) -> None:
        for token in ("Decided and open are separate lists", "not the source of truth", "both variants are not shipped as product options"):
            self.assertIn(token, self.rules)

    def test_components_are_source_of_truth(self) -> None:
        for token in ("Components are the source of truth", "Reuse the control", "copying classes", "corner and height"):
            self.assertIn(token, self.rules)

    def test_styleguide_page_with_openable_states(self) -> None:
        for token in ("styleguide page", "real components and tokens", "loading", "empty", "error", "opened directly", "never as an empty result"):
            self.assertIn(token, self.rules)

    def test_check_counts_only_when_it_ran(self) -> None:
        self.assertIn("counts only when it ran", self.rules)
        self.assertIn("`not_observed`", self.rules)

    def test_no_brand_decision_or_effect_claim(self) -> None:
        lowered = self.rules.lower()
        for banned in ("pill", "never fill", "rounded-full", "improves", "boosts", "increases conversion"):
            self.assertNotIn(banned, lowered)
        self.assertNotRegex(self.rules, r"\d+\s?%")
        self.assertNotRegex(self.rules, r"#[0-9a-fA-F]{3,6}\b")


class ReferenceExtractionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.body = _reference_token_extraction_reference()
        self.skeleton = _section(self.body, "Skeleton versus brand")
        self.traces = _section(self.body, "Remove traces before it leaves the team")

    def test_skeleton_versus_brand(self) -> None:
        for token in ("skeleton and motion from the reference", "colour and type from its own brand", "no brand exists", "asked to match"):
            self.assertIn(token, self.skeleton)

    def test_several_references_share_one_system(self) -> None:
        for token in ("one spacing unit", "one grid", "one type scale", "one transition treatment", "several sites"):
            self.assertIn(token, self.skeleton)

    def test_owner_specific_material_dropped(self) -> None:
        for token in ("mascot", "seasonal banner", "menu names"):
            self.assertIn(token, self.skeleton)

    def test_trace_removal(self) -> None:
        for token in ("name in titles", "comments", "redrawn copies", "working notes", "search", "does not name the reference"):
            self.assertIn(token, self.traces)


class RegistryLicenceTest(unittest.TestCase):
    def test_redistribution_clause_already_covered(self) -> None:
        body = _flat(_component_registry_adoption_reference())
        self.assertIn("restricts redistributing the components themselves", body)


class OrchestrationBarTest(unittest.TestCase):
    def test_lines_sit_after_the_existing_items(self) -> None:
        bar = _orchestration().quality_bar
        for line in _ORCHESTRATION_LINES:
            self.assertEqual(bar.count(line), 1)
        self.assertEqual(bar[-2:], _ORCHESTRATION_LINES)
        # The capability rows read bar[:4]; the original three keep their places.
        self.assertTrue(bar[0].startswith("Make the design job"))
        self.assertTrue(bar[2].startswith("Require the selected executor"))

    def test_no_portable_override_to_splice(self) -> None:
        overrides = _orchestration().portable_overrides or {}
        self.assertNotIn("quality_bar", overrides)


if __name__ == "__main__":
    unittest.main()
