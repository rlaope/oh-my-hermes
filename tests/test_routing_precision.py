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
        self.assertEqual(payload["summary"]["case_count"], 17)
        self.assertEqual(payload["summary"]["passing_count"], 17)
        self.assertEqual(payload["summary"]["negative_case_count"], 17)
        self.assertEqual(payload["summary"]["negative_passing_count"], 17)
        self.assertEqual(payload["summary"]["direct_answer_count"], 15)
        self.assertEqual(payload["summary"]["file_lookup_count"], 2)
        self.assertEqual(payload["summary"]["overroute_count"], 0)
        self.assertEqual(payload["summary"]["catalog_picker_count"], 0)
        self.assertEqual(payload["summary"]["generic_ack_count"], 0)
        self.assertEqual(payload["summary"]["intervention_case_count"], 13)
        self.assertEqual(payload["summary"]["intervention_passing_count"], 13)
        self.assertEqual(payload["summary"]["missed_intervention_count"], 0)
        self.assertEqual(payload["summary"]["intervention_generic_ack_count"], 0)
        self.assertEqual(payload["summary"]["total_case_count"], 30)
        self.assertEqual(payload["summary"]["total_passing_count"], 30)
        self.assertEqual(routing_precision_errors(payload), [])
        self.assertIn("over-intervention and missed-intervention guards", payload["claim_boundary"])

        cases = {case["id"]: case for case in payload["cases"]}
        self.assertEqual(cases["repo-file-list"]["observed"]["next_action"], "answer_file_lookup")
        self.assertEqual(cases["general-python-help"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["python-virtualenv-help"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["soft-prefix-python-help"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["paragraph-summary"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["python-loop-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["strategy-pattern-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["memory-leak-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["source-control-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["kubernetes-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["graphql-korean-explanation"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["kubernetes-korean-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["korean-error-meaning"]["observed"]["next_action"], "answer_directly")
        for case in cases.values():
            self.assertFalse(case["observed"]["overrouted"])
            self.assertFalse(case["observed"]["catalog_picker_opened"])
            self.assertEqual(case["observed"]["route_action"], "fallback")
            self.assertEqual(case["observed"]["route_workflow"], "oh-my-hermes")

        interventions = {case["id"]: case for case in payload["intervention_cases"]}
        self.assertEqual(interventions["safe-feature-plan"]["observed"]["route_workflow"], "ralplan")
        self.assertEqual(interventions["source-acquisition"]["observed"]["route_workflow"], "source-finder")
        self.assertEqual(interventions["visual-summary"]["observed"]["route_workflow"], "img-summary")
        self.assertEqual(interventions["feedback-triage"]["observed"]["route_workflow"], "feedback-triage")
        self.assertEqual(interventions["catalog-picker"]["observed"]["response_kind"], "skill_picker")
        self.assertEqual(interventions["omh-risky-refactor-context"]["observed"]["response_kind"], "context_brief")
        self.assertEqual(interventions["exact-ops-review-capability"]["observed"]["route_workflow"], "ops-review")
        self.assertEqual(interventions["exact-github-event-capability"]["observed"]["route_workflow"], "github-event-ops")
        self.assertEqual(interventions["exact-paper-learning-capability"]["observed"]["route_workflow"], "paper-learning")
        self.assertEqual(interventions["loopable-project"]["observed"]["route_workflow"], "loop")
        self.assertEqual(interventions["one-cycle-delivery"]["observed"]["route_workflow"], "ultraprocess")
        self.assertEqual(interventions["scheduled-research-blueprint"]["observed"]["route_workflow"], "automation-blueprint")
        self.assertEqual(interventions["workflow-learning"]["observed"]["route_workflow"], "workflow-learning")
        for case in interventions.values():
            self.assertTrue(case["passed"])
            self.assertNotEqual(case["observed"]["response_kind"], "ack")

    def test_routing_precision_cli_outputs_summary_and_json(self) -> None:
        status, stdout, stderr = run_cli(["demo", "routing-precision", "--summary"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        self.assertIn("OMH routing precision", stdout)
        self.assertIn("17/17 negative-control cases passing", stdout)
        self.assertIn("Interventions: 13/13 expected workflow cases passing", stdout)
        self.assertIn("overroutes: 0", stdout)
        self.assertIn("catalog pickers: 0", stdout)
        self.assertIn("generic ack: 0", stdout)
        self.assertIn("missed interventions: 0", stdout)

        status, stdout, stderr = run_cli(["demo", "routing-precision", "--json"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "routing_precision/v1")
        self.assertTrue(payload["summary"]["all_passing"])
        self.assertEqual(payload["summary"]["missed_intervention_count"], 0)


if __name__ == "__main__":
    unittest.main()
