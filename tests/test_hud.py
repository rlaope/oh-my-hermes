from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli


class HudCliTests(unittest.TestCase):
    def test_hud_prints_compact_line_without_runtime_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, stdout, stderr = run_cli(
                ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"), "hud"],
                output_json=False,
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertIn("[omh] v1.0.0", stdout)
            self.assertIn("plugin:not-installed", stdout)
            self.assertIn("coding-agent:idle(ask)", stdout)
            self.assertNotIn("tokens:unobserved", stdout)
            self.assertNotIn("executor:", stdout)
            self.assertNotIn("handoff:", stdout)

    def test_hud_reports_setup_plugin_target_and_prepared_runtime_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup"])[0], 0)
            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "coding",
                    "delegate",
                    "--record",
                    "--executor",
                    "codex",
                    "Safely add feature without overclaiming.",
                ]
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            run_id = json.loads(stdout)["runtime"]["run"]["run_id"]

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "hud",
                    "--json",
                    "--preset",
                    "full",
                    "--tokens-remaining",
                    "1200",
                    "--token-budget",
                    "4000",
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "omh_hud/v1")
            self.assertEqual(payload["version"], "1.0.0")
            self.assertEqual(payload["plugin"]["status"], "ready")
            self.assertNotIn("skills", payload)
            self.assertEqual(payload["target_topology"]["mode"], "single_agent_target")
            self.assertEqual(payload["runtime"]["latest_run_id"], run_id)
            self.assertEqual(payload["runtime"]["evidence_state"], "prepared_not_observed")
            self.assertEqual(payload["tokens"]["status"], "observed_from_host_metadata")
            self.assertEqual(payload["tokens"]["values"]["tokens_remaining"], 1200)
            self.assertEqual(payload["tokens"]["values"]["token_budget"], 4000)
            self.assertEqual(payload["tokens"]["summary"], "30%")
            self.assertNotIn("tokens:", payload["display"]["line"])
            self.assertIn("plugin:ready", payload["display"]["line"])
            self.assertIn("coding-agent:prepared(codex)", payload["display"]["line"])
            self.assertNotIn("plan:prepared", payload["display"]["line"])
            self.assertNotRegex(payload["display"]["line"], r"#[0-9a-f]{6}")
            self.assertNotIn("skills:", payload["display"]["line"])
            self.assertNotIn("executor:", payload["display"]["line"])
            self.assertNotIn("handoff:", payload["display"]["line"])
            self.assertIn("evidence:prepared_not_observed", payload["display"]["line"])
            self.assertIn("Prepared handoffs are not execution", payload["evidence_boundary"])

    def test_hud_marks_older_plugin_bundle_as_stale(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            plugin_dir = hermes_home / "plugins" / "omh"
            tools_dir = plugin_dir / "tools"
            tools_dir.mkdir(parents=True)
            (plugin_dir / "__init__.py").write_text("def register(ctx):\n    pass\n", encoding="utf-8")
            (plugin_dir / "plugin.yaml").write_text(
                "\n".join(
                    [
                        "name: omh",
                        'version: "0.9.0"',
                        "provides_tools:",
                        "  - omh_status",
                        "provides_hooks:",
                        "  - pre_llm_call",
                    ]
                ),
                encoding="utf-8",
            )
            (tools_dir / "status_tool.py").write_text("OMH_STATUS_SCHEMA = {}\n", encoding="utf-8")

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "hud", "--json"]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["plugin"]["status"], "stale")
            self.assertTrue(payload["plugin"]["stale"])
            self.assertFalse(payload["plugin"]["capabilities"]["tools"]["omh_hud"])
            self.assertTrue(payload["plugin"]["capabilities"]["tools"]["omh_status"])
            self.assertIn("plugin:update-needed", payload["display"]["line"])

    def test_hud_plugin_tool_tolerates_untrusted_limit_argument(self) -> None:
        from omh.plugin_bundle.omh.tools.hud_tool import omh_hud_handler

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = json.loads(
                omh_hud_handler(
                    {
                        "omh_home": str(root / ".omh"),
                        "hermes_home": str(root / ".hermes"),
                        "limit": "not-a-number",
                    }
                )
            )

            self.assertEqual(payload["schema_version"], "omh_hud/v1")
            self.assertEqual(payload["runtime"]["recent_run_count"], 0)


if __name__ == "__main__":
    unittest.main()
