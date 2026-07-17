from __future__ import annotations

from copy import deepcopy
import unittest

from _local_package import load_local_package

load_local_package()
from omh.product_evidence_loop import (
    PRODUCT_EVIDENCE_LOOP_DECISIONS,
    build_product_evidence_loop,
    compact_product_evidence_loop,
    validate_product_evidence_loop,
)


SCOPE_ID = "scope_0123456789abcdef"
REFERENCE_ID = "ref_0123456789abcdef"


class ProductEvidenceLoopTests(unittest.TestCase):
    def _build_valid_card(self, *, proposed_next_decision: str = "research") -> dict[str, object]:
        return build_product_evidence_loop(
            decision_scope_id=SCOPE_ID,
            proposed_next_decision=proposed_next_decision,
            research_availability="reference_supplied",
            research_reference_id=REFERENCE_ID,
            research_provenance="hermes_reference",
            feedback_availability="reference_supplied",
            feedback_reference_id=REFERENCE_ID,
            feedback_provenance="user_supplied_reference",
            supplied_data_availability="reference_supplied",
            supplied_data_reference_id=REFERENCE_ID,
            supplied_data_provenance="local_record_reference",
            causal_identification_availability="reference_supplied",
            causal_identification_reference_id=REFERENCE_ID,
            causal_identification_provenance="hermes_reference",
        )

    def test_valid_card_is_prepared_and_has_a_fixed_shape(self) -> None:
        card = self._build_valid_card()

        self.assertEqual(card["status"], "prepared_not_observed")
        self.assertEqual(card["causal_claim_status"], "unavailable_not_established")
        self.assertEqual(
            set(card),
            {
                "schema_version",
                "status",
                "decision_scope_id",
                "source_descriptors",
                "epistemic_status_policy",
                "causal_claim_status",
                "causal_identification_reference",
                "proposed_next_decision",
                "decision_status",
                "decision_rules",
                "stop_conditions",
                "not_evidence_until_observed",
                "claim_boundary",
            },
        )
        self.assertEqual(set(card["source_descriptors"]), {"research", "feedback", "supplied_data"})
        self.assertEqual(validate_product_evidence_loop(card), [])

    def test_every_caller_proposed_decision_is_valid(self) -> None:
        for decision in PRODUCT_EVIDENCE_LOOP_DECISIONS:
            with self.subTest(decision=decision):
                card = self._build_valid_card(proposed_next_decision=decision)
                self.assertEqual(card["proposed_next_decision"], decision)
                self.assertEqual(validate_product_evidence_loop(card), [])

    def test_source_descriptor_availability_and_metadata_are_coupled(self) -> None:
        with self.assertRaisesRegex(ValueError, "research reference_id"):
            build_product_evidence_loop(
                decision_scope_id=SCOPE_ID,
                proposed_next_decision="research",
                research_availability="reference_supplied",
            )
        with self.assertRaisesRegex(ValueError, "feedback provenance"):
            build_product_evidence_loop(
                decision_scope_id=SCOPE_ID,
                proposed_next_decision="research",
                feedback_availability="reference_supplied",
                feedback_reference_id=REFERENCE_ID,
            )
        with self.assertRaisesRegex(ValueError, "supplied_data"):
            build_product_evidence_loop(
                decision_scope_id=SCOPE_ID,
                proposed_next_decision="research",
                supplied_data_reference_id=REFERENCE_ID,
            )

    def test_identifiers_reject_raw_urls_multiline_and_oversized_values(self) -> None:
        invalid_scope_ids = (
            "https://example.test/scope",
            "scope_0123456789abcdef\nraw-body",
            "scope_" + ("a" * 65),
        )
        for scope_id in invalid_scope_ids:
            with self.subTest(scope_id=scope_id):
                with self.assertRaisesRegex(ValueError, "decision_scope_id"):
                    build_product_evidence_loop(
                        decision_scope_id=scope_id,
                        proposed_next_decision="research",
                    )

        for reference_id in ("https://example.test/ref", "ref_0123456789abcdef\nraw-body", "ref_" + ("a" * 65)):
            with self.subTest(reference_id=reference_id):
                with self.assertRaisesRegex(ValueError, "research reference_id"):
                    build_product_evidence_loop(
                        decision_scope_id=SCOPE_ID,
                        proposed_next_decision="research",
                        research_availability="reference_supplied",
                        research_reference_id=reference_id,
                        research_provenance="hermes_reference",
                    )

    def test_tampering_cannot_convert_a_prepared_card_into_causal_or_accepted_evidence(self) -> None:
        card = self._build_valid_card()
        card["causal_claim_status"] = "causal_established"
        card["decision_status"] = "accepted"
        card["dispatch"] = {"status": "observed"}

        errors = validate_product_evidence_loop(card)

        self.assertTrue(any("keys are invalid" in error for error in errors))
        self.assertTrue(any("causal_claim_status is invalid" in error for error in errors))
        self.assertTrue(any("decision_status is invalid" in error for error in errors))

    def test_compaction_returns_only_valid_deep_copied_cards(self) -> None:
        card = self._build_valid_card()
        compacted = compact_product_evidence_loop(card)

        self.assertEqual(compacted, card)
        self.assertIsNot(compacted, card)
        self.assertIsNot(compacted["source_descriptors"], card["source_descriptors"])
        self.assertEqual(compact_product_evidence_loop({}), {})
        self.assertEqual(compact_product_evidence_loop(deepcopy(card) | {"raw_body": "no"}), {})


if __name__ == "__main__":
    unittest.main()
