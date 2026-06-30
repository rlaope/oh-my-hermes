from __future__ import annotations

import json
import unittest

from _cli_harness import run_cli
from omh.quality.router_fast_path import build_router_fast_path_demo, router_fast_path_errors


class RouterFastPathTests(unittest.TestCase):
    def test_router_fast_path_demo_locks_common_chat_fast_paths(self) -> None:
        payload = build_router_fast_path_demo(source="discord")

        self.assertEqual(payload["schema_version"], "router_fast_path/v1")
        self.assertEqual(payload["source"], "discord")
        self.assertEqual(payload["summary"]["case_count"], 11)
        self.assertEqual(payload["summary"]["passing_count"], 11)
        self.assertEqual(payload["summary"]["missing_marker_count"], 0)
        self.assertEqual(payload["summary"]["route_mismatch_count"], 0)
        self.assertEqual(payload["summary"]["next_action_mismatch_count"], 0)
        self.assertTrue(payload["summary"]["all_passing"])
        self.assertEqual(router_fast_path_errors(payload), [])
        cases = {case["id"]: case for case in payload["cases"]}
        self.assertIn("agent_ops_status_fast_path", cases["status-slang-ko"]["observed"]["matched"])
        self.assertIn("file_lookup_fast_path", cases["file-lookup-ko"]["observed"]["matched"])
        self.assertIn(
            "guard_fast_path:coding_progress_status_before_clarify",
            cases["coding-progress-ko"]["observed"]["matched"],
        )

    def test_router_fast_path_cli_outputs_summary_and_json(self) -> None:
        status, stdout, stderr = run_cli(["demo", "router-fast-path", "--summary"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        with self.assertRaises(json.JSONDecodeError):
            json.loads(stdout)
        self.assertIn("OMH router fast-path quality", stdout)
        self.assertIn("Result: 11/11 fast-path cases passing", stdout)
        self.assertIn("Missing markers: 0", stdout)
        self.assertIn("Korean short status slang opens agent ops fast path: ok", stdout)

        status, stdout, stderr = run_cli(["demo", "router-fast-path", "--json"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "router_fast_path/v1")
        self.assertTrue(payload["summary"]["all_passing"])


if __name__ == "__main__":
    unittest.main()
