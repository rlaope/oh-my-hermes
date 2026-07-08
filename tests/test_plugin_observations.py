from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli


class PluginHostObservationTests(unittest.TestCase):
    def test_plugin_observations_accepts_json_flag_for_operator_smoke_checks(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            self.assertEqual(
                run_cli(
                    base
                    + [
                        "plugin",
                        "observe-host",
                        "--host",
                        "hermes-agent",
                        "--session",
                        "session-json-smoke",
                        "--event",
                        "tool_call",
                        "--tool",
                        "omh_status",
                        "--evidence-ref",
                        "plugin:tool_call:omh_status",
                    ]
                )[0],
                0,
            )

            status, stdout, stderr = run_cli(base + ["plugin", "observations", "--json"], output_json=False)

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "omh_plugin_host_observations/v1")
            self.assertEqual(payload["observations"][0]["tool"], "omh_status")

    def test_plugin_host_observation_records_runtime_load_without_execution_claims(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            self.assertEqual(run_cli(base + ["setup", "--with-plugin"])[0], 0)

            status, stdout, stderr = run_cli(
                base
                + [
                    "plugin",
                    "observe-host",
                    "--host",
                    "hermes-agent",
                    "--session",
                    "session-123",
                    "--event",
                    "plugin_load",
                ]
            )

            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertIn("require at least one --evidence-ref", stderr)

            status, stdout, stderr = run_cli(
                base
                + [
                    "plugin",
                    "observe-host",
                    "--host",
                    "hermes-agent",
                    "--session",
                    "session-123",
                    "--event",
                    "plugin_load",
                    "--status",
                    "observed",
                    "--evidence-ref",
                    "host-log:plugin-loaded",
                    "--message",
                    "Hermes host reported OMH plugin loaded.",
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            observation = json.loads(stdout)["observation"]
            self.assertEqual(observation["schema_version"], "omh_plugin_host_observation/v1")
            self.assertTrue(observation["observed"])
            self.assertEqual(observation["host"], "hermes-agent")
            self.assertEqual(observation["session_id"], "session-123")
            self.assertEqual(observation["event"], "plugin_load")
            self.assertEqual(observation["evidence_refs"], ["host-log:plugin-loaded"])
            self.assertEqual(observation["runtime_readiness"], "active_runtime_observed")
            self.assertTrue(observation["native_integration_active"])
            self.assertEqual(observation["redaction_policy"], "metadata_only_bounded")
            self.assertIn("plugin event", observation["claim_boundary"])
            self.assertIn("not coding dispatch", observation["claim_boundary"])
            state = json.loads((root / ".omh" / "runtime" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["last_plugin_runtime_observed"]["session_id"], "session-123")
            self.assertEqual(state["last_plugin_runtime_readiness"], "active_runtime_observed")

            status, stdout, stderr = run_cli(base + ["plugin", "observations", "--limit", "1"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            observations = json.loads(stdout)["observations"]
            self.assertEqual(len(observations), 1)
            self.assertEqual(observations[0]["session_id"], "session-123")

            status, stdout, stderr = run_cli(base + ["probe", "--parity", "--json"], output_json=False)
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            caps = {capability["name"]: capability for capability in payload["capabilities"]}
            self.assertTrue(payload["plugin_distribution_ready"])
            self.assertTrue(payload["plugin_runtime_observed"])
            self.assertTrue(payload["plugin_runtime_active"])
            self.assertTrue(payload["native_integration_claim_ready"])
            self.assertEqual(caps["plugin_runtime_observed"]["status"], "available")
            self.assertIn("session-123", caps["plugin_runtime_observed"]["message"])
            self.assertEqual(payload["parity_matrix"]["probe_alignment"]["plugin_runtime_observed"], "available")
            self.assertEqual(payload["parity_matrix"]["probe_alignment"]["plugin_runtime_active"], "available")
            self.assertNotIn(
                "observed-plugin-load",
                {item["id"] for item in payload["parity_matrix"]["recommended_next_prs"]},
            )

            status, stdout, stderr = run_cli(base + ["doctor", "--json"], output_json=False)
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            checks = {check["name"]: check for check in json.loads(stdout)["checks"]}
            self.assertTrue(checks["plugin_runtime_observed"]["ok"])
            self.assertTrue(checks["plugin_runtime_observed"]["observed"])
            self.assertEqual(checks["plugin_runtime_observed"]["severity"], "ok")
            self.assertIn("session-123", checks["plugin_runtime_observed"]["message"])

    def test_plugin_host_not_observed_records_do_not_claim_native_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            self.assertEqual(run_cli(base + ["setup", "--with-plugin"])[0], 0)

            status, stdout, stderr = run_cli(
                base
                + [
                    "plugin",
                    "observe-host",
                    "--host",
                    "hermes-agent",
                    "--session",
                    "session-124",
                    "--event",
                    "plugin_load",
                    "--status",
                    "not_observed",
                    "--message",
                    "Host checked but did not see the plugin loaded.",
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertFalse(json.loads(stdout)["observation"]["observed"])

            status, stdout, stderr = run_cli(base + ["probe", "--json"], output_json=False)
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            caps = {capability["name"]: capability for capability in payload["capabilities"]}
            self.assertTrue(payload["plugin_distribution_ready"])
            self.assertFalse(payload["plugin_runtime_observed"])
            self.assertFalse(payload["plugin_runtime_active"])
            self.assertFalse(payload["native_integration_claim_ready"])
            self.assertEqual(caps["plugin_runtime_observed"]["status"], "unverified")
            self.assertIn("not_observed", caps["plugin_runtime_observed"]["message"])
            state = json.loads((root / ".omh" / "runtime" / "state.json").read_text(encoding="utf-8"))
            self.assertIsNone(state["last_plugin_runtime_observed"])
            self.assertEqual(state["last_plugin_runtime_readiness"], "not_observed")

    def test_latest_not_observed_record_stops_stale_plugin_ready_claim(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            self.assertEqual(run_cli(base + ["setup", "--with-plugin"])[0], 0)
            self.assertEqual(
                run_cli(
                    base
                    + [
                        "plugin",
                        "observe-host",
                        "--host",
                        "hermes-agent",
                        "--session",
                        "session-128",
                        "--event",
                        "plugin_load",
                        "--evidence-ref",
                        "host-log:plugin-loaded",
                    ]
                )[0],
                0,
            )
            self.assertEqual(
                run_cli(
                    base
                    + [
                        "plugin",
                        "observe-host",
                        "--host",
                        "hermes-agent",
                        "--session",
                        "session-128",
                        "--event",
                        "status_query",
                        "--status",
                        "not_observed",
                        "--message",
                        "Host checked the session and did not see OMH plugin status.",
                    ]
                )[0],
                0,
            )

            status, stdout, stderr = run_cli(base + ["probe", "--json"], output_json=False)
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            caps = {capability["name"]: capability for capability in payload["capabilities"]}
            self.assertFalse(payload["plugin_runtime_observed"])
            self.assertFalse(payload["plugin_runtime_active"])
            self.assertFalse(payload["native_integration_claim_ready"])
            self.assertEqual(caps["plugin_runtime_observed"]["status"], "unverified")
            self.assertIn("not_observed", caps["plugin_runtime_observed"]["message"])

            status, stdout, stderr = run_cli(base + ["doctor", "--json"], output_json=False)
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            checks = {check["name"]: check for check in json.loads(stdout)["checks"]}
            self.assertTrue(checks["plugin_runtime_observed"]["ok"])
            self.assertFalse(checks["plugin_runtime_observed"]["observed"])
            self.assertEqual(checks["plugin_runtime_observed"]["severity"], "warning")
            self.assertIn("not_observed", checks["plugin_runtime_observed"]["message"])
            state = json.loads((root / ".omh" / "runtime" / "state.json").read_text(encoding="utf-8"))
            self.assertIsNone(state["last_plugin_runtime_observed"])
            self.assertEqual(state["last_plugin_runtime_readiness"], "not_observed")

    def test_latest_blocked_record_stops_stale_plugin_ready_claim(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            self.assertEqual(run_cli(base + ["setup", "--with-plugin"])[0], 0)
            self.assertEqual(
                run_cli(
                    base
                    + [
                        "plugin",
                        "observe-host",
                        "--host",
                        "hermes-agent",
                        "--session",
                        "session-129",
                        "--event",
                        "plugin_load",
                        "--evidence-ref",
                        "host-log:plugin-loaded",
                    ]
                )[0],
                0,
            )
            self.assertEqual(
                run_cli(
                    base
                    + [
                        "plugin",
                        "observe-host",
                        "--host",
                        "hermes-agent",
                        "--session",
                        "session-129",
                        "--event",
                        "status_query",
                        "--status",
                        "blocked",
                        "--message",
                        "Host could not inspect the current plugin session.",
                    ]
                )[0],
                0,
            )

            status, stdout, stderr = run_cli(base + ["probe", "--json"], output_json=False)
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            caps = {capability["name"]: capability for capability in payload["capabilities"]}
            self.assertFalse(payload["plugin_runtime_observed"])
            self.assertFalse(payload["plugin_runtime_active"])
            self.assertFalse(payload["native_integration_claim_ready"])
            self.assertEqual(caps["plugin_runtime_observed"]["status"], "unverified")
            self.assertIn("blocked", caps["plugin_runtime_observed"]["message"])
            state = json.loads((root / ".omh" / "runtime" / "state.json").read_text(encoding="utf-8"))
            self.assertIsNone(state["last_plugin_runtime_observed"])
            self.assertEqual(state["last_plugin_runtime_readiness"], "blocked")

    def test_plugin_host_observation_rejects_sensitive_or_unbounded_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(
                base
                + [
                    "plugin",
                    "observe-host",
                    "--host",
                    "hermes-agent",
                    "--session",
                    "session-130",
                    "--event",
                    "plugin_load",
                    "--evidence-ref",
                    "host-log:plugin-loaded",
                    "--message",
                    "raw prompt included private-token-123",
                ]
            )
            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertIn("metadata-only", stderr)

            status, stdout, stderr = run_cli(
                base
                + [
                    "plugin",
                    "observe-host",
                    "--host",
                    "hermes-agent",
                    "--session",
                    "session-131",
                    "--event",
                    "plugin_load",
                    "--evidence-ref",
                    "secret:abc",
                ]
            )
            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertIn("metadata-only", stderr)

            status, stdout, stderr = run_cli(
                base
                + [
                    "plugin",
                    "observe-host",
                    "--host",
                    "hermes-agent",
                    "--session",
                    "session-132",
                    "--event",
                    "plugin_load",
                    "--evidence-ref",
                    "host-log:plugin-loaded",
                    "--message",
                    "x" * 281,
                ]
            )
            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertIn("280 characters or fewer", stderr)

    def test_plugin_unload_observation_is_runtime_evidence_not_native_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            self.assertEqual(run_cli(base + ["setup", "--with-plugin"])[0], 0)

            status, stdout, stderr = run_cli(
                base
                + [
                    "plugin",
                    "observe-host",
                    "--host",
                    "hermes-agent",
                    "--session",
                    "session-127",
                    "--event",
                    "plugin_unload",
                    "--status",
                    "observed",
                    "--evidence-ref",
                    "host-log:plugin-unloaded",
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertTrue(json.loads(stdout)["observation"]["observed"])

            status, stdout, stderr = run_cli(base + ["probe", "--json"], output_json=False)
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            caps = {capability["name"]: capability for capability in payload["capabilities"]}
            self.assertTrue(payload["plugin_runtime_observed"])
            self.assertFalse(payload["plugin_runtime_active"])
            self.assertFalse(payload["native_integration_claim_ready"])
            self.assertEqual(caps["plugin_runtime_observed"]["status"], "available")
            self.assertIn("plugin_unload", caps["plugin_runtime_observed"]["message"])
            self.assertIn("historical", caps["plugin_runtime_observed"]["message"])
            state = json.loads((root / ".omh" / "runtime" / "state.json").read_text(encoding="utf-8"))
            self.assertIsNone(state["last_plugin_runtime_observed"])
            self.assertEqual(state["last_plugin_runtime_readiness"], "historical_runtime_observed")

    def test_plugin_host_tool_and_hook_observations_require_names(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(
                base
                + [
                    "plugin",
                    "observe-host",
                    "--host",
                    "hermes-agent",
                    "--session",
                    "session-125",
                    "--event",
                    "tool_call",
                    "--evidence-ref",
                    "host-log:tool",
                ]
            )
            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertIn("requires --tool", stderr)

            status, stdout, stderr = run_cli(
                base
                + [
                    "plugin",
                    "observe-host",
                    "--host",
                    "hermes-agent",
                    "--session",
                    "session-126",
                    "--event",
                    "hook_call",
                    "--evidence-ref",
                    "host-log:hook",
                ]
            )
            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertIn("requires --hook", stderr)


if __name__ == "__main__":
    unittest.main()
