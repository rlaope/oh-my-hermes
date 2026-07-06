from __future__ import annotations

from copy import deepcopy
import unittest

from _local_package import load_local_package

load_local_package()

from omh.quality.common_request_coverage import (
    build_common_request_coverage_demo,
    common_request_coverage_errors,
    format_common_request_coverage_summary,
)
from omh.quality.popular_plugin_coverage import (
    POPULAR_PLUGIN_COVERAGE_SCHEMA_VERSION,
    build_popular_plugin_coverage_demo,
    popular_plugin_coverage_errors,
)


class CommonRequestCoverageTests(unittest.TestCase):
    def test_common_request_coverage_includes_weighted_popular_plugin_families(self) -> None:
        payload = build_common_request_coverage_demo(source="discord")

        self.assertEqual(common_request_coverage_errors(payload), [])
        summary = payload["summary"]
        self.assertEqual(summary["case_count"], 71)
        self.assertEqual(summary["popular_plugin_family_count"], 10)
        self.assertEqual(summary["popular_plugin_covered_family_count"], 10)
        self.assertEqual(summary["popular_plugin_weighted_coverage_percent"], 100.0)
        self.assertEqual(summary["popular_plugin_target_percent"], 95.0)

        plugin_coverage = payload["popular_plugin_coverage"]
        self.assertEqual(plugin_coverage["schema_version"], POPULAR_PLUGIN_COVERAGE_SCHEMA_VERSION)
        self.assertEqual(plugin_coverage["summary"]["total_weight"], 100)
        self.assertEqual(plugin_coverage["summary"]["covered_weight"], 100)
        self.assertGreater(
            plugin_coverage["summary"]["case_reference_count"],
            plugin_coverage["summary"]["unique_case_count"],
        )
        self.assertEqual(
            plugin_coverage["summary"]["covered_unique_case_count"],
            plugin_coverage["summary"]["unique_case_count"],
        )
        self.assertIn("plugin telemetry", plugin_coverage["claim_boundary"])

        human = format_common_request_coverage_summary(payload)
        self.assertIn("Popular plugin families: 10/10 (100.0%; target 95.0%)", human)

    def test_popular_plugin_failures_are_reported_through_common_request_gate(self) -> None:
        payload = build_common_request_coverage_demo(source="discord")
        cases = deepcopy(payload["cases"])
        for case in cases:
            if case["id"] == "web-research":
                case["passed"] = False
                case["issues"] = ["forced test failure"]
                break

        broken_plugin_coverage = build_popular_plugin_coverage_demo(cases=cases)
        self.assertTrue(
            any(
                "web_search_and_sources" in error
                for error in popular_plugin_coverage_errors(broken_plugin_coverage)
            )
        )

        broken_payload = dict(payload)
        broken_payload["popular_plugin_coverage"] = broken_plugin_coverage

        errors = common_request_coverage_errors(broken_payload)
        self.assertTrue(any("popular_plugin_coverage:" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
