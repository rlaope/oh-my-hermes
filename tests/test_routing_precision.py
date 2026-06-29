from __future__ import annotations

import json
import unittest

from _cli_harness import run_cli
from omh.quality.routing_precision import build_routing_precision_demo, routing_precision_errors


class RoutingPrecisionTests(unittest.TestCase):
    def test_routing_precision_demo_checks_negative_controls(self) -> None:
        payload = build_routing_precision_demo(source="discord")

        self.assertEqual(payload["schema_version"], "routing_precision/v1")
        self.assertEqual(payload["source"], "discord")
        self.assertTrue(payload["summary"]["all_passing"])
        self.assertEqual(payload["summary"]["case_count"], 5)
        self.assertEqual(payload["summary"]["passing_count"], 5)
        self.assertEqual(payload["summary"]["direct_answer_count"], 3)
        self.assertEqual(payload["summary"]["file_lookup_count"], 2)
        self.assertEqual(payload["summary"]["overroute_count"], 0)
        self.assertEqual(payload["summary"]["catalog_picker_count"], 0)
        self.assertEqual(payload["summary"]["generic_ack_count"], 0)
        self.assertEqual(routing_precision_errors(payload), [])
        self.assertIn("over-intervention guards", payload["claim_boundary"])

        cases = {case["id"]: case for case in payload["cases"]}
        self.assertEqual(cases["repo-file-list"]["observed"]["next_action"], "answer_file_lookup")
        self.assertEqual(cases["general-python-help"]["observed"]["next_action"], "answer_directly")
        for case in cases.values():
            self.assertFalse(case["observed"]["overrouted"])
            self.assertFalse(case["observed"]["catalog_picker_opened"])
            self.assertEqual(case["observed"]["route_action"], "fallback")
            self.assertEqual(case["observed"]["route_workflow"], "oh-my-hermes")

    def test_routing_precision_cli_outputs_summary_and_json(self) -> None:
        status, stdout, stderr = run_cli(["demo", "routing-precision", "--summary"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        self.assertIn("OMH routing precision", stdout)
        self.assertIn("5/5 negative-control cases passing", stdout)
        self.assertIn("overroutes: 0", stdout)
        self.assertIn("catalog pickers: 0", stdout)
        self.assertIn("generic ack: 0", stdout)

        status, stdout, stderr = run_cli(["demo", "routing-precision", "--json"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "routing_precision/v1")
        self.assertTrue(payload["summary"]["all_passing"])


if __name__ == "__main__":
    unittest.main()
