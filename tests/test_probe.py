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
            self.assertEqual(caps["omhm_plugin_bundle"]["status"], "missing")
            self.assertEqual(caps["plugin_import_smoke"]["status"], "unknown")
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
            self.assertEqual(caps["omhm_plugin_bundle"]["status"], "missing")
            self.assertFalse(json.loads(stdout)["plugin_distribution_ready"])

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
            self.assertEqual(caps["omhm_plugin_bundle"]["status"], "available")
            self.assertEqual(caps["plugin_import_smoke"]["status"], "available")
            self.assertEqual(caps["plugin_register_smoke"]["status"], "available")
            self.assertEqual(caps["plugin_runtime_observed"]["status"], "unverified")
            self.assertTrue(payload["plugin_distribution_ready"])
            self.assertFalse(payload["native_integration_claim_ready"])


if __name__ == "__main__":
    unittest.main()
