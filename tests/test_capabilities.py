from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.capabilities.registry import capability_snapshot, inspect_capability, list_capabilities
from omh.capabilities.schema import normalize_capability_section
from omh.skills.catalog import installable_skill_names


LEGACY_ROLE_ALIASES = {
    "coding-handoff": "handoff-guide",
    "planning-lead": "planner",
    "research-lead": "researcher",
    "review-gate": "reviewer",
}


class CapabilityManifestTests(unittest.TestCase):
    def test_capability_snapshot_is_deterministic_and_boundary_safe(self) -> None:
        first = capability_snapshot()
        second = capability_snapshot()

        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], "omh_capability_manifest/v1")
        self.assertEqual(first["determinism"], "static_projection_no_runtime_clock")
        self.assertEqual(first["omh_awareness"]["schema_version"], "omh_awareness/v1")
        self.assertIn("workflow-shaped requests", first["omh_awareness"]["purpose"])
        self.assertIn("Hermes-native workflow pack", first["omh_awareness"]["product_context"])
        self.assertIn("across every OMH skill", first["omh_awareness"]["all_skill_context_rule"])
        self.assertIn("Every generated workflow skill", first["omh_awareness"]["skill_coverage"])
        self.assertIn("meeting notes -> meeting-brief", " ".join(first["omh_awareness"]["cross_lane_examples"]))
        self.assertIn("img-summary", json.dumps(first["omh_awareness"], sort_keys=True))
        self.assertGreaterEqual(first["summary"]["skills"], 30)
        self.assertGreaterEqual(first["summary"]["agent_roles"], 8)
        self.assertGreaterEqual(first["summary"]["playbooks"], 20)
        self.assertIn("no runtime_topology schema in this PR", first["non_goals"])
        self.assertNotIn("runtime_topology", first)
        self.assertIn("Prepared OMH capability", first["evidence_boundaries"]["prepared_is_not"])

    def test_awareness_lanes_cover_every_generated_workflow_skill(self) -> None:
        awareness = capability_snapshot()["omh_awareness"]
        lane_skills = {
            str(skill)
            for lane in awareness["lanes"]
            for skill in lane["skills"]
        }
        generated_skills = set(installable_skill_names()) - {"oh-my-hermes"}
        conceptual_surfaces = {"request-to-handoff", "executor selection", "coding runtime handoff"}

        self.assertFalse(generated_skills - lane_skills)
        self.assertLessEqual(lane_skills - generated_skills, conceptual_surfaces)

    def test_capability_sections_have_expected_ids(self) -> None:
        listing = list_capabilities()
        sections = {section["section"]: section["ids"] for section in listing["sections"]}

        self.assertIn("omh_awareness", sections["omh_awareness"])
        self.assertIn("handoff-guide", sections["agent_roles"])
        self.assertIn("ultragoal", sections["skills"])
        self.assertIn("omh_capabilities", sections["hooks"])
        self.assertIn("executor_session_handoff", sections["orchestration_patterns"])
        self.assertIn("hermes_coding_team_path", sections["orchestration_patterns"])
        self.assertIn("request-to-handoff", sections["playbooks"])
        self.assertIn("research-department", sections["playbooks"])
        self.assertIn("ultragoal", sections["tool_requirements"])
        self.assertEqual(normalize_capability_section("roles"), "agent_roles")
        self.assertEqual(normalize_capability_section("patterns"), "orchestration_patterns")
        self.assertEqual(normalize_capability_section("tools"), "tool_requirements")

    def test_capability_inspect_finds_skill_and_role_without_runtime_claim(self) -> None:
        skill = inspect_capability("ultragoal", section="skills")["capability"]
        hidden_surface = inspect_capability("ops-observability-card", section="skills")["capability"]
        awareness = inspect_capability("omh_awareness", section="omh_awareness")["capability"]
        role = inspect_capability("handoff-guide", section="agent_roles")["capability"]
        playbook = inspect_capability("request-to-handoff", section="playbooks")["capability"]
        legacy_role = inspect_capability("coding-handoff", section="agent_roles")

        self.assertEqual(skill["schema_version"], "skill_capability/v1")
        self.assertEqual(skill["tool_requirements"]["derivation_status"], "partial")
        self.assertIn("prepared_not_observed", skill["evidence_boundary"])
        self.assertEqual(skill["awareness_lane"], "intent_to_plan")
        self.assertIn("Use `ultragoal`", skill["workflow_routing_hint"])
        self.assertIn("across every OMH skill", skill["workflow_context_rule"])
        self.assertIn("Normal users talk to Hermes", skill["chat_rule"])
        self.assertIn("missing", skill["fallback_rule"])
        self.assertIn("omh_capabilities", awareness["tool_hints"][0])
        self.assertIn("ambitious goal -> loopability check", " ".join(skill["cross_lane_examples"]))
        self.assertEqual(hidden_surface["exposure"], "harness_only")
        self.assertEqual(awareness["schema_version"], "omh_awareness/v1")
        self.assertIn("materials", awareness["first_turn_rule"])
        self.assertIn("meeting-brief", json.dumps(awareness, sort_keys=True))
        self.assertIn("capability manifest", awareness["context_surfaces"])
        self.assertFalse(hidden_surface["install_visibility"])
        self.assertTrue(hidden_surface["compatibility_alias"])
        self.assertIn("preferred_usage", hidden_surface)
        self.assertEqual(role["runtime_claim"], "descriptor_not_runtime_agent")
        self.assertIn("OMH workflow-layer responsibility context", role["workflow_context_rule"])
        self.assertIn("Normal users talk to Hermes", role["chat_rule"])
        self.assertIn("prepared guidance only", role["role_boundary_rule"])
        self.assertIn("executor_session_handoff", role["default_orchestration_patterns"])
        self.assertEqual(playbook["schema_version"], "playbook_capability/v1")
        self.assertEqual(playbook["runtime_claim"], "playbook_guidance_not_execution")
        self.assertIn("situation-level workflow maps", playbook["workflow_context_rule"])
        self.assertIn("Normal users talk to Hermes", playbook["chat_rule"])
        self.assertIn("route_request", playbook["pipeline"])
        self.assertEqual(playbook["primary_owner_role"], "planner")
        self.assertIn("handoff-guide", playbook["stage_owners"])
        self.assertIn("show_recommendation", playbook["available_wrapper_actions"])
        self.assertEqual(playbook["first_stage"]["id"], "route_request")
        self.assertEqual(playbook["first_stage"]["contract"], "playbook_recommendation/v1")
        self.assertIn("Prepared OMH capability", playbook["prepared_is_not"])
        self.assertEqual(legacy_role["requested_id"], "coding-handoff")
        self.assertEqual(legacy_role["resolved_id"], "handoff-guide")
        self.assertEqual(legacy_role["capability"]["id"], "handoff-guide")

        for alias, expected_role in LEGACY_ROLE_ALIASES.items():
            with self.subTest(alias=alias):
                inspected = inspect_capability(alias, section="agent_roles")
                self.assertEqual(inspected["requested_id"], alias)
                self.assertEqual(inspected["resolved_id"], expected_role)
                self.assertEqual(inspected["capability"]["id"], expected_role)

        with self.assertRaisesRegex(ValueError, "capability not found"):
            inspect_capability("retained-cognition", section="agent_roles")

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
        self.assertEqual(inspected["capability"]["owner_role"], "handoff-guide")

        status, stdout, stderr = run_cli(
            ["capabilities", "inspect", "handoff-guide", "--section", "roles", "--json"],
            output_json=False,
        )

        self.assertEqual(status, 0, stderr)
        role = json.loads(stdout)
        self.assertEqual(role["section"], "agent_roles")
        self.assertEqual(role["resolved_id"], "handoff-guide")

        status, stdout, stderr = run_cli(["capabilities", "list", "--section", "agents", "--json"], output_json=False)

        self.assertEqual(status, 0, stderr)
        role_list = json.loads(stdout)
        self.assertEqual(role_list["sections"][0]["section"], "agent_roles")
        self.assertIn("planner", role_list["sections"][0]["ids"])

        status, stdout, stderr = run_cli(
            ["capabilities", "inspect", "request-to-handoff", "--section", "playbooks", "--json"],
            output_json=False,
        )

        self.assertEqual(status, 0, stderr)
        playbook = json.loads(stdout)
        self.assertEqual(playbook["section"], "playbooks")
        self.assertEqual(playbook["capability"]["schema_version"], "playbook_capability/v1")
        self.assertIn("status_card", playbook["capability"]["pipeline"])
        self.assertIn("first_stage", playbook["capability"])

        for alias, expected_role in LEGACY_ROLE_ALIASES.items():
            with self.subTest(alias=alias):
                status, stdout, stderr = run_cli(
                    ["capabilities", "inspect", alias, "--section", "agent_roles", "--json"],
                    output_json=False,
                )

                self.assertEqual(status, 0, stderr)
                legacy = json.loads(stdout)
                self.assertEqual(legacy["requested_id"], alias)
                self.assertEqual(legacy["resolved_id"], expected_role)
                self.assertEqual(legacy["capability"]["id"], expected_role)

        status, stdout, stderr = run_cli(
            ["capabilities", "inspect", "retained-cognition", "--section", "agent_roles", "--json"],
            output_json=False,
        )

        self.assertNotEqual(status, 0)
        self.assertIn("capability not found: retained-cognition", stderr)

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
