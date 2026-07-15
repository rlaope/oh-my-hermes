from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.coding.coding_delegation import build_coding_delegation_payload, coding_delegation_record_payload
from omh.coding.product_quality_harnesses import (
    PRODUCT_QUALITY_HARNESS_SCHEMA_VERSION,
    product_quality_harness,
    validate_product_quality_harness,
)


class ProductQualityHarnessTests(unittest.TestCase):
    def test_each_supported_family_has_a_strict_prepared_harness(self) -> None:
        expected_stage_ids = {
            "web": ["reproduce", "functional_accuracy", "responsive_layout", "accessibility", "performance", "report"],
            "mobile": ["reproduce", "functional_accuracy", "device_layout", "touch_accessibility", "performance", "report"],
            "desktop": ["reproduce", "functional_accuracy", "window_layout", "keyboard_accessibility", "performance", "report"],
            "api": ["reproduce", "contract_accuracy", "error_security", "performance", "report"],
        }

        for family, stage_ids in expected_stage_ids.items():
            with self.subTest(family=family):
                harness = product_quality_harness(family)

                self.assertEqual(harness["schema_version"], PRODUCT_QUALITY_HARNESS_SCHEMA_VERSION)
                self.assertEqual(harness["status"], "prepared_not_observed")
                self.assertEqual([stage["id"] for stage in harness["stages"]], stage_ids)
                self.assertEqual(validate_product_quality_harness(harness), [])
                self.assertIn("does not run", harness["claim_boundary"])

    def test_harness_rejects_tampered_observation_claim(self) -> None:
        harness = product_quality_harness("web")
        harness["status"] = "completed"

        errors = validate_product_quality_harness(harness)

        self.assertTrue(any("status is invalid" in error for error in errors))

    def test_delegate_attaches_harness_and_runtime_compaction_keeps_it(self) -> None:
        payload = build_coding_delegation_payload(
            "Implement the responsive checkout layout and verify keyboard navigation in the application code.",
            executor_target="hermes",
            product_family="web",
            force_coding_handoff=True,
        )
        handoff = payload["runtime_handoff"]

        self.assertIn("product_quality_harness", handoff)
        self.assertEqual(handoff["product_quality_harness"]["family"], "web")
        record = coding_delegation_record_payload(payload, "Implement the responsive checkout layout and verify keyboard navigation in the application code.")
        self.assertEqual(record["runtime_handoff"]["product_quality_harness"], handoff["product_quality_harness"])


if __name__ == "__main__":
    unittest.main()
