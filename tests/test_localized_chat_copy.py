from __future__ import annotations

import json
import unittest

from _cli_harness import run_cli
from omh.quality.localized_chat_copy import build_localized_chat_copy_demo, localized_chat_copy_errors


class LocalizedChatCopyTests(unittest.TestCase):
    def test_localized_chat_copy_demo_checks_non_english_card_frames(self) -> None:
        payload = build_localized_chat_copy_demo(source="discord")

        self.assertEqual(payload["schema_version"], "localized_chat_copy/v1")
        self.assertEqual(payload["source"], "discord")
        self.assertEqual(payload["summary"]["case_count"], 7)
        self.assertEqual(payload["summary"]["passing_count"], 7)
        self.assertEqual(payload["summary"]["locale_count"], 6)
        self.assertTrue(payload["summary"]["all_passing"])
        self.assertEqual(localized_chat_copy_errors(payload), [])
        self.assertIn("translation service quality", payload["claim_boundary"])
        cases = {case["id"]: case for case in payload["cases"]}
        self.assertEqual(cases["catalog-picker-ja"]["observed"]["locale"], "ja")
        self.assertEqual(cases["catalog-picker-zh"]["observed"]["kind"], "skill_picker")
        self.assertEqual(cases["source-finder-fr"]["observed"]["next_action"], "prepare_source_finder_plan")
        self.assertEqual(cases["img-summary-ko"]["observed"]["kind"], "img_summary")

    def test_localized_chat_copy_cli_outputs_summary_and_json(self) -> None:
        status, stdout, stderr = run_cli(["demo", "localized-chat-copy", "--summary"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        with self.assertRaises(json.JSONDecodeError):
            json.loads(stdout)
        self.assertIn("OMH localized chat copy", stdout)
        self.assertIn("Result: 7/7 localized card cases passing", stdout)
        self.assertIn("Locales: 6", stdout)
        self.assertIn("Japanese catalog picker: ok", stdout)
        self.assertIn("Korean image summary: ok", stdout)

        status, stdout, stderr = run_cli(["demo", "localized-chat-copy", "--json"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "localized_chat_copy/v1")
        self.assertEqual(payload["summary"]["passing_count"], 7)


if __name__ == "__main__":
    unittest.main()
