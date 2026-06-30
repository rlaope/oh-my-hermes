from __future__ import annotations

import json
import unittest

from _cli_harness import run_cli
from omh.quality.hermes_ux_quality import build_hermes_ux_quality_demo, hermes_ux_quality_errors


class HermesUxQualityTests(unittest.TestCase):
    def test_hermes_ux_quality_rolls_up_user_visible_contracts(self) -> None:
        payload = build_hermes_ux_quality_demo(source="discord")

        self.assertEqual(payload["schema_version"], "hermes_ux_quality/v1")
        self.assertEqual(payload["source"], "discord")
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["score"], 100)
        self.assertEqual(payload["summary"]["gate_count"], 5)
        self.assertEqual(payload["summary"]["passing_gate_count"], 5)
        self.assertEqual(payload["summary"]["grounded_score_scenarios"], 49)
        self.assertEqual(payload["summary"]["grounded_score_average"], 10.0)
        self.assertEqual(payload["summary"]["chat_card_cases"], 25)
        self.assertEqual(payload["summary"]["chat_card_generic_ack_count"], 0)
        self.assertEqual(payload["summary"]["route_hint_cases"], 131)
        self.assertEqual(payload["summary"]["route_hint_aligned_count"], 131)
        self.assertEqual(payload["summary"]["route_hint_missing_count"], 0)
        self.assertEqual(payload["summary"]["route_hint_mismatch_count"], 0)
        self.assertEqual(payload["summary"]["context_brief_cases"], 10)
        self.assertEqual(payload["summary"]["context_brief_passing_count"], 10)
        self.assertEqual(payload["summary"]["routing_precision_cases"], 41)
        self.assertEqual(payload["summary"]["routing_precision_passing_count"], 41)
        self.assertEqual(payload["summary"]["routing_precision_overroute_count"], 0)
        self.assertEqual(payload["summary"]["routing_precision_catalog_picker_count"], 0)
        self.assertEqual(payload["summary"]["routing_precision_generic_ack_count"], 0)
        self.assertEqual(payload["summary"]["routing_precision_intervention_cases"], 79)
        self.assertEqual(payload["summary"]["routing_precision_intervention_passing_count"], 79)
        self.assertEqual(payload["summary"]["routing_precision_missed_intervention_count"], 0)
        self.assertEqual(hermes_ux_quality_errors(payload), [])

        gates = {gate["id"]: gate for gate in payload["gates"]}
        self.assertEqual(
            set(gates),
            {
                "grounded_score",
                "chat_card_coverage",
                "route_hint_alignment",
                "context_brief_coverage",
                "routing_precision",
            },
        )
        self.assertIn("generic acknowledgement", gates["chat_card_coverage"]["user_value"])
        self.assertIn("before generic tools", gates["route_hint_alignment"]["user_value"])
        self.assertIn("raw prompt leakage", gates["context_brief_coverage"]["user_value"])
        self.assertIn("Ordinary questions", gates["routing_precision"]["user_value"])
        self.assertIn("does not prove live Hermes chat rendering", payload["claim_boundary"])

    def test_hermes_ux_quality_cli_outputs_summary_and_json(self) -> None:
        status, stdout, stderr = run_cli(["demo", "hermes-ux-quality", "--summary"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        self.assertIn("OMH Hermes UX quality", stdout)
        self.assertIn("Status: passed (100/100)", stdout)
        self.assertIn("Gates: 5/5", stdout)
        self.assertIn("generic ack 0", stdout)
        self.assertIn("route mismatches 0", stdout)
        self.assertIn("precision overroutes 0", stdout)
        self.assertIn("missed interventions 0", stdout)

        status, stdout, stderr = run_cli(["demo", "hermes-ux-quality", "--json"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "hermes_ux_quality/v1")
        self.assertEqual(payload["status"], "passed")


if __name__ == "__main__":
    unittest.main()
