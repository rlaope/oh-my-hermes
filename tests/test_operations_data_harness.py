from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.operations_data import build_operations_data_harness, validate_operations_data_harness


class OperationsDataHarnessTests(unittest.TestCase):
    def test_mixed_relational_analysis_stays_association_only(self) -> None:
        harness = build_operations_data_harness(data_shape="mixed", analysis_mode="relational")

        self.assertEqual(harness["status"], "prepared_not_observed")
        self.assertEqual(harness["relationship_claim"], "association_only")
        self.assertIn("structured_to_unstructured_join", harness["collection_requirements"])
        self.assertEqual(validate_operations_data_harness(harness), [])

    def test_causal_mode_requires_identification_before_a_causal_claim(self) -> None:
        harness = build_operations_data_harness(data_shape="structured", analysis_mode="causal")

        self.assertEqual(harness["relationship_claim"], "causal_not_established")
        self.assertIn("temporal_order", harness["causal_requirements"])
        self.assertIn("confounder_assessment", harness["causal_requirements"])
        self.assertIn("comparison_or_identification_strategy", harness["causal_requirements"])
        self.assertTrue(any("temperature and revenue" in example for example in harness["misinterpretation_examples"]))
        self.assertEqual(validate_operations_data_harness(harness), [])

    def test_tampered_causal_completion_claim_is_rejected(self) -> None:
        harness = build_operations_data_harness(data_shape="structured", analysis_mode="causal")
        harness["relationship_claim"] = "causal_established"

        errors = validate_operations_data_harness(harness)

        self.assertTrue(any("relationship_claim is invalid" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
