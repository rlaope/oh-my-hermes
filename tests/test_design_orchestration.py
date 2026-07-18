from __future__ import annotations

from copy import deepcopy
import unittest

from _local_package import load_local_package

load_local_package()
from omh.design_orchestration import (
    DESIGN_ORCHESTRATION_SCHEMA_VERSION,
    build_design_orchestration,
    compact_design_orchestration,
    validate_design_orchestration,
)


def _build_card() -> dict[str, object]:
    return build_design_orchestration(
        surface="application_shell",
        audience="operator",
        primary_task="manage",
        platform="web",
        mode="redesign",
        context_references=(
            ("design_system", "design_ref_0123456789abcdef", "project_local"),
        ),
        hierarchy="task_first",
        palette="restrained_neutral",
        typography="system_sans",
        layout="split_panel",
        signature_element="evidence_rail",
        avoid_patterns=("generic_glass", "card_wall"),
    )


class DesignOrchestrationTests(unittest.TestCase):
    def test_builds_prepared_executor_neutral_contract(self) -> None:
        card = _build_card()

        self.assertEqual(card["schema_version"], DESIGN_ORCHESTRATION_SCHEMA_VERSION)
        self.assertEqual(card["status"], "prepared_not_observed")
        self.assertEqual(
            card["lane_composition"],
            ["design-quality-gate", "frontend", "accessibility-audit", "visual-qa"],
        )
        self.assertEqual(card["executor_handoff"]["status"], "executor_selection_required")
        self.assertEqual(card["required_visual_evidence"]["visual_verdict"], "not_observed")
        self.assertEqual(validate_design_orchestration(card), [])

    def test_rejects_raw_content_and_observed_claims(self) -> None:
        cases = (
            ("surface", "make this page look premium"),
            ("direction.hierarchy", "https://private.example/design"),
            ("context_references.0.reference_kind", "private /Users/owner/brief.md"),
            ("required_visual_evidence.visual_verdict", "PASS"),
            ("executor_handoff.dispatch_observed", True),
        )

        for path, replacement in cases:
            with self.subTest(path=path):
                card = deepcopy(_build_card())
                target: object = card
                for part in path.split(".")[:-1]:
                    target = target[int(part)] if part.isdigit() else target[part]
                target[path.split(".")[-1]] = replacement
                self.assertTrue(validate_design_orchestration(card))

    def test_requires_unique_opaque_context_references(self) -> None:
        card = _build_card()
        card["context_references"] = [
            {
                "reference_id": "design_ref_0123456789abcdef",
                "provenance": "project_local",
                "reference_kind": "design_system",
                "content_retained": False,
            },
            {
                "reference_id": "design_ref_0123456789abcdef",
                "provenance": "project_local",
                "reference_kind": "component_inventory",
                "content_retained": False,
            },
        ]

        self.assertTrue(validate_design_orchestration(card))

    def test_compact_returns_independent_card_or_empty(self) -> None:
        card = _build_card()
        compact = compact_design_orchestration(card)
        compact["intent"]["surface"] = "mixed"

        self.assertEqual(card["intent"]["surface"], "application_shell")
        self.assertEqual(compact_design_orchestration({"status": "prepared_not_observed"}), {})


if __name__ == "__main__":
    unittest.main()
