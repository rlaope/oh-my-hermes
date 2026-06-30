from __future__ import annotations

import json
import unittest

from _cli_harness import run_cli
from omh.quality.context_brief_coverage import build_context_brief_coverage_demo


class ContextBriefCoverageTests(unittest.TestCase):
    def test_context_brief_coverage_demo_checks_hermes_facing_context(self) -> None:
        payload = build_context_brief_coverage_demo(source="discord")

        self.assertEqual(payload["schema_version"], "context_brief_coverage/v1")
        self.assertEqual(payload["source"], "discord")
        self.assertTrue(payload["summary"]["all_passing"])
        self.assertEqual(payload["summary"]["case_count"], 8)
        self.assertEqual(payload["summary"]["passing_count"], 8)
        self.assertEqual(payload["summary"]["route_hint_count"], 7)
        self.assertEqual(payload["summary"]["catalog_question_count"], 1)
        self.assertIn("metadata-only", payload["check_basis"][0])
        self.assertIn("does not prove live Hermes chat rendering", payload["claim_boundary"])

        cases = {case["id"]: case for case in payload["cases"]}
        visual = cases["visual-summary-before-image-tool"]
        self.assertEqual(visual["observed"]["primary_workflow"], "img-summary")
        self.assertEqual(visual["observed"]["primary_next_action"], "prepare_visual_prompt_card")
        self.assertFalse(visual["observed"]["sensitive_token_leaked"])
        self.assertTrue(visual["observed"]["prompt_context_has_route_hint"])

        catalog = cases["catalog-picker-without-shell-approval"]
        self.assertTrue(catalog["observed"]["catalog_question"])
        self.assertEqual(catalog["observed"]["catalog_next_action"], "show_workflow_picker")
        self.assertEqual(catalog["observed"]["catalog_recommended_tool"], "omh_capabilities")

    def test_context_brief_coverage_cli_outputs_summary_and_json(self) -> None:
        status, stdout, stderr = run_cli(["demo", "context-brief-coverage", "--summary"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        self.assertIn("OMH context brief coverage", stdout)
        self.assertIn("8/8 context brief cases passing", stdout)
        self.assertIn("catalog picker hints: 1", stdout)
        self.assertIn(
            "Visual summary before generic image tools: ok; "
            "img-summary -> preparing an image prompt card (`prepare_visual_prompt_card`)",
            stdout,
        )
        self.assertIn(
            "Catalog picker without shell approval: ok; "
            "catalog -> opening the workflow picker (`show_workflow_picker`)",
            stdout,
        )

        status, stdout, stderr = run_cli(["demo", "context-brief-coverage", "--json"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "context_brief_coverage/v1")
        self.assertTrue(payload["summary"]["all_passing"])


if __name__ == "__main__":
    unittest.main()
