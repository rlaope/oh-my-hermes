from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli


class ProbeCliTests(unittest.TestCase):
    def test_probe_reports_unknown_and_missing_without_install(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, stdout, stderr = run_cli(["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"), "probe"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            caps = {capability["name"]: capability for capability in payload["capabilities"]}
            self.assertEqual(caps["external_skill_dirs"]["status"], "unknown")
            self.assertEqual(caps["managed_skills"]["status"], "missing")
            self.assertEqual(caps["native_hooks"]["status"], "unknown")
            self.assertEqual(caps["mcp_preference"]["status"], "unknown")
            self.assertEqual(caps["mcp_host_session"]["status"], "unverified")
            self.assertEqual(caps["mcp_host_config"]["status"], "unknown")
            self.assertEqual(caps["omh_plugin_bundle"]["status"], "missing")
            self.assertEqual(caps["plugin_import_smoke"]["status"], "unknown")
            self.assertEqual(caps["target_registry"]["status"], "missing")
            self.assertEqual(payload["target_topology"]["mode"], "unknown")
            self.assertFalse(payload["plugin_distribution_ready"])
            self.assertFalse(payload["native_integration_claim_ready"])

    def test_probe_reports_available_local_evidence_after_install_and_wrapper_record(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "install"])[0], 0)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "apply"])[0], 0)
            status, stdout, _ = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "runtime",
                    "record",
                    "--skill",
                    "oh-my-hermes",
                    "--harness",
                    "coding-handling",
                ]
            )
            self.assertEqual(status, 0)
            run_id = json.loads(stdout)["run"]["run_id"]
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "runtime", "wrapper", "--run", run_id, "--prompt-dispatched"])[0], 0)

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "probe"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            caps = {capability["name"]: capability for capability in json.loads(stdout)["capabilities"]}
            self.assertEqual(caps["external_skill_dirs"]["status"], "available")
            self.assertEqual(caps["managed_skills"]["status"], "available")
            self.assertEqual(caps["wrapper_metadata"]["status"], "available")
            self.assertEqual(caps["omh_plugin_bundle"]["status"], "missing")
            self.assertEqual(caps["target_registry"]["status"], "missing")
            self.assertFalse(json.loads(stdout)["plugin_distribution_ready"])

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup"])[0], 0)
            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "probe"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            caps = {capability["name"]: capability for capability in payload["capabilities"]}
            self.assertEqual(caps["target_registry"]["status"], "available")
            self.assertEqual(payload["target_topology"]["mode"], "single_agent_target")

    def test_probe_separates_mcp_preference_from_host_config(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-mcp"])[0], 0)

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "probe"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            caps = {capability["name"]: capability for capability in payload["capabilities"]}
            self.assertEqual(caps["mcp_preference"]["status"], "unverified")
            self.assertIn("bridge preference was requested", caps["mcp_preference"]["message"])
            self.assertIn("runtime/state.json", caps["mcp_preference"]["evidence"])
            self.assertEqual(caps["mcp_bridge_server"]["status"], "available")
            self.assertIn("omh_status", caps["mcp_bridge_server"]["message"])
            self.assertEqual(caps["mcp_bridge_runtime"]["status"], "unverified")
            self.assertEqual(caps["mcp_host_session"]["status"], "unverified")
            self.assertEqual(caps["mcp_host_config"]["status"], "unknown")
            self.assertIn("No Hermes MCP host config", caps["mcp_host_config"]["message"])
            self.assertFalse(payload["native_integration_claim_ready"])

            (hermes_home / ".mcp.json").write_text("{}", encoding="utf-8")
            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "probe"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            caps = {capability["name"]: capability for capability in json.loads(stdout)["capabilities"]}
            self.assertEqual(caps["mcp_preference"]["status"], "unverified")
            self.assertEqual(caps["mcp_host_config"]["status"], "unverified")
            self.assertIn("MCP host config exists", caps["mcp_host_config"]["message"])
            self.assertNotIn("mcp", {capability["name"] for capability in json.loads(stdout)["capabilities"]})

    def test_probe_reports_plugin_distribution_without_native_runtime_claim(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-plugin"])[0], 0)

            status, stdout, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "probe"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            caps = {capability["name"]: capability for capability in payload["capabilities"]}
            self.assertIn("dedicated plugin capabilities", caps["plugin_bundles"]["message"])
            self.assertNotIn("no stable Hermes plugin bundle contract", caps["plugin_bundles"]["message"])
            self.assertEqual(caps["omh_plugin_bundle"]["status"], "available")
            self.assertEqual(caps["plugin_import_smoke"]["status"], "available")
            self.assertEqual(caps["plugin_register_smoke"]["status"], "available")
            self.assertEqual(caps["plugin_runtime_observed"]["status"], "unverified")
            self.assertTrue(payload["plugin_distribution_ready"])
            self.assertFalse(payload["native_integration_claim_ready"])


if __name__ == "__main__":
    unittest.main()
