from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.capabilities.registry import capability_snapshot, inspect_capability, list_capabilities


class CapabilityManifestTests(unittest.TestCase):
    def test_capability_snapshot_is_deterministic_and_boundary_safe(self) -> None:
        first = capability_snapshot()
        second = capability_snapshot()

        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], "omh_capability_manifest/v1")
        self.assertEqual(first["determinism"], "static_projection_no_runtime_clock")
        self.assertGreaterEqual(first["summary"]["skills"], 30)
        self.assertGreaterEqual(first["summary"]["agent_roles"], 4)
        self.assertIn("no runtime_topology schema in this PR", first["non_goals"])
        self.assertNotIn("runtime_topology", first)
        self.assertIn("Prepared OMH capability", first["evidence_boundaries"]["prepared_is_not"])

    def test_capability_sections_have_expected_ids(self) -> None:
        listing = list_capabilities()
        sections = {section["section"]: section["ids"] for section in listing["sections"]}

        self.assertIn("coding-handoff", sections["agent_roles"])
        self.assertIn("ultragoal", sections["skills"])
        self.assertIn("omh_capabilities", sections["hooks"])
        self.assertIn("executor_session_handoff", sections["orchestration_patterns"])
        self.assertIn("ultragoal", sections["tool_requirements"])

    def test_capability_inspect_finds_skill_and_role_without_runtime_claim(self) -> None:
        skill = inspect_capability("ultragoal", section="skills")["capability"]
        role = inspect_capability("coding-handoff", section="agent_roles")["capability"]

        self.assertEqual(skill["schema_version"], "skill_capability/v1")
        self.assertEqual(skill["tool_requirements"]["derivation_status"], "partial")
        self.assertIn("prepared_not_observed", skill["evidence_boundary"])
        self.assertEqual(role["runtime_claim"], "descriptor_not_runtime_agent")
        self.assertIn("executor_session_handoff", role["default_orchestration_patterns"])

    def test_cli_export_list_and_inspect(self) -> None:
        status, stdout, stderr = run_cli(["capabilities", "export", "--json"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "omh_capability_manifest/v1")

        status, stdout, stderr = run_cli(["capabilities", "list"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertIn("OMH capabilities", stdout)
        self.assertIn("For machine-readable output", stdout)

        status, stdout, stderr = run_cli(["capabilities", "inspect", "executor_session_handoff", "--json"], output_json=False)

        self.assertEqual(status, 0, stderr)
        inspected = json.loads(stdout)
        self.assertEqual(inspected["section"], "orchestration_patterns")
        self.assertEqual(inspected["capability"]["owner_role"], "coding-handoff")

    def test_package_metadata_includes_capabilities_package(self) -> None:
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        packages = set(pyproject["tool"]["setuptools"]["packages"])

        self.assertIn("omh.capabilities", packages)
        self.assertEqual(pyproject["tool"]["setuptools"]["package-dir"]["omh.capabilities"], "src/capabilities")

    def test_runtime_topology_is_deferred_from_first_pr(self) -> None:
        self.assertFalse(Path("src/capabilities/runtime_topology.py").exists())
        payload = capability_snapshot()
        exported = json.dumps(payload, sort_keys=True)

        self.assertNotIn('"runtime_topology"', exported)
        self.assertIn("no runtime_topology schema in this PR", payload["non_goals"])
