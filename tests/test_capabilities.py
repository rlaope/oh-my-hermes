from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.capabilities.families import capability_family_projection, family_for_workflow
from omh.capabilities.registry import capability_snapshot, capability_summary, inspect_capability, list_capabilities
from omh.capabilities.schema import normalize_capability_section
from omh.skills.catalog import builtin_definitions, installable_skill_names


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
        first["summary"]["skills"] = -1
        first["skills"].clear()
        third = capability_snapshot()

        self.assertEqual(second, third)
        self.assertEqual(third["schema_version"], "omh_capability_manifest/v1")
        self.assertEqual(third["determinism"], "static_projection_no_runtime_clock")
        self.assertEqual(third["omh_awareness"]["schema_version"], "omh_awareness/v1")
        self.assertIn("workflow-shaped requests", third["omh_awareness"]["purpose"])
        self.assertIn("Hermes-native workflow pack", third["omh_awareness"]["product_context"])
        self.assertIn("every OMH skill", third["omh_awareness"]["all_skill_context_rule"])
        self.assertIn("generic tool can render or execute", third["omh_awareness"]["all_skill_context_rule"])
        self.assertIn("Every generated workflow skill", third["omh_awareness"]["skill_coverage"])
        self.assertIn("meeting notes -> meeting-brief", " ".join(third["omh_awareness"]["cross_lane_examples"]))
        self.assertIn("img-summary", json.dumps(third["omh_awareness"], sort_keys=True))
        self.assertGreaterEqual(third["summary"]["skills"], 30)
        self.assertGreaterEqual(third["summary"]["agent_roles"], 8)
        self.assertGreaterEqual(third["summary"]["playbooks"], 20)
        self.assertIn("no runtime_topology schema in this PR", third["non_goals"])
        self.assertNotIn("runtime_topology", third)
        self.assertIn("Prepared OMH capability", third["evidence_boundaries"]["prepared_is_not"])

    def test_awareness_lanes_cover_every_catalog_workflow_surface(self) -> None:
        awareness = capability_snapshot()["omh_awareness"]
        lane_skills = {
            str(skill)
            for lane in awareness["lanes"]
            for skill in lane["skills"]
        }
        generated_skills = set(installable_skill_names())
        catalog_surfaces = {definition.name for definition in builtin_definitions()}
        conceptual_surfaces = {"request-to-handoff", "executor selection", "coding runtime handoff"}

        self.assertFalse(generated_skills - lane_skills)
        self.assertLessEqual(lane_skills - catalog_surfaces, conceptual_surfaces)

    def test_capability_families_are_user_facing_front_door_projection(self) -> None:
        projection = capability_family_projection()
        families = {family["id"]: family for family in projection["families"]}

        self.assertEqual(projection["schema_version"], "omh_capability_families/v1")
        self.assertEqual(
            [family["label"] for family in projection["families"]],
            [
                "Plan and decide",
                "Learn and gather",
                "Retain knowledge",
                "Create materials and visuals",
                "Delegate coding and ship",
                "Operate and observe",
            ],
        )
        self.assertIn("deep-interview", families["plan_and_decide"]["primary_workflows"])
        self.assertIn("paper-learning", families["learn_and_gather"]["primary_workflows"])
        self.assertIn("wiki", families["retain_knowledge"]["primary_workflows"])
        self.assertIn("img-summary", families["create_materials_and_visuals"]["primary_workflows"])
        self.assertIn("frontend", families["create_materials_and_visuals"]["primary_workflows"])
        self.assertIn("visual-qa", families["create_materials_and_visuals"]["primary_workflows"])
        self.assertNotIn("wiki", families["create_materials_and_visuals"]["primary_workflows"])
        self.assertIn("ultraprocess", families["delegate_coding_and_ship"]["primary_workflows"])
        self.assertIn("verification-gate", families["delegate_coding_and_ship"]["primary_workflows"])
        self.assertIn("doctor", families["operate_and_observe"]["primary_workflows"])
        self.assertIn("workspace-audit", families["operate_and_observe"]["primary_workflows"])
        self.assertIn("production-audit", families["operate_and_observe"]["primary_workflows"])
        self.assertIn("agent-evaluation", families["operate_and_observe"]["primary_workflows"])
        self.assertIn("rules-distill", families["operate_and_observe"]["primary_workflows"])
        self.assertIn("agent-debug", families["operate_and_observe"]["primary_workflows"])
        self.assertIn("instinct-ledger", families["operate_and_observe"]["primary_workflows"])
        self.assertIn("skill-scout", families["operate_and_observe"]["primary_workflows"])
        self.assertIn("skill-health", families["operate_and_observe"]["primary_workflows"])
        self.assertEqual(projection["workflow_to_family"]["img-summary"], "create_materials_and_visuals")
        self.assertEqual(projection["workflow_to_family"]["frontend"], "create_materials_and_visuals")
        self.assertEqual(projection["workflow_to_family"]["visual-qa"], "create_materials_and_visuals")
        self.assertEqual(projection["workflow_to_family"]["wiki"], "retain_knowledge")
        self.assertEqual(projection["workflow_to_family"]["paper-learning"], "learn_and_gather")
        self.assertEqual(projection["workflow_to_family"]["ultraprocess"], "delegate_coding_and_ship")
        self.assertEqual(projection["workflow_to_family"]["verification-gate"], "delegate_coding_and_ship")
        self.assertEqual(projection["workflow_to_family"]["workspace-audit"], "operate_and_observe")
        self.assertEqual(projection["workflow_to_family"]["production-audit"], "operate_and_observe")
        self.assertEqual(projection["workflow_to_family"]["agent-evaluation"], "operate_and_observe")
        self.assertEqual(projection["workflow_to_family"]["rules-distill"], "operate_and_observe")
        self.assertEqual(projection["workflow_to_family"]["agent-debug"], "operate_and_observe")
        self.assertEqual(projection["workflow_to_family"]["instinct-ledger"], "operate_and_observe")
        self.assertEqual(projection["workflow_to_family"]["skill-scout"], "operate_and_observe")
        self.assertEqual(projection["workflow_to_family"]["skill-health"], "operate_and_observe")
        self.assertEqual(family_for_workflow("wiki")["id"], "retain_knowledge")
        self.assertEqual(family_for_workflow("code-review")["id"], "delegate_coding_and_ship")
        self.assertEqual(family_for_workflow("workflow-learning")["id"], "operate_and_observe")
        self.assertEqual(family_for_workflow("agent-debug")["id"], "operate_and_observe")
        self.assertEqual(family_for_workflow("instinct-ledger")["id"], "operate_and_observe")
        self.assertEqual(family_for_workflow("skill-scout")["id"], "operate_and_observe")
        self.assertEqual(family_for_workflow("skill-health")["id"], "operate_and_observe")
        self.assertEqual(family_for_workflow("workspace-audit")["id"], "operate_and_observe")
        self.assertEqual(family_for_workflow("verification-gate")["id"], "delegate_coding_and_ship")
        self.assertIn("Codex", families["delegate_coding_and_ship"]["executor_choices"])
        self.assertIn("Claude Code", families["delegate_coding_and_ship"]["executor_choices"])
        self.assertIn("Hermes", families["delegate_coding_and_ship"]["executor_choices"])
        self.assertIn("executor dispatch", families["delegate_coding_and_ship"]["not_evidence_until_observed"])
        self.assertIn("not observed execution", projection["claim_boundary"])
        seen_workflows: dict[str, str] = {}
        for family in projection["families"]:
            family_id = family["id"]
            for workflow in family["primary_workflows"]:
                self.assertNotIn(workflow, seen_workflows, f"{workflow} appears in multiple families")
                seen_workflows[workflow] = family_id
                self.assertEqual(projection["workflow_to_family"][workflow], family_id)

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

    def test_capability_summary_is_human_facing_catalog_context(self) -> None:
        summary = capability_summary()
        summary["capability_families"].clear()
        summary["totals"]["skills"] = -1
        summary = capability_summary()
        families = {family["id"]: family for family in summary["capability_families"]}
        lanes = {lane["id"]: lane for lane in summary["lanes"]}
        context_cards = {card["id"]: card for card in summary["workflow_context_cards"]}

        self.assertEqual(summary["schema_version"], "omh_capability_summary/v1")
        self.assertIn("without requiring shell catalog approval", summary["purpose"])
        self.assertIn("Normal users talk to Hermes", summary["chat_rule"])
        self.assertIn("capability families", " ".join(summary["direct_response_guidance"]))
        self.assertEqual(summary["section_aliases"]["roles"], "agent_roles")
        self.assertEqual(summary["section_aliases"]["tools"], "tool_requirements")
        self.assertIn("Prepared OMH capability", summary["evidence_boundary"])
        self.assertEqual(families["plan_and_decide"]["label"], "Plan and decide")
        self.assertIn("paper-learning", families["learn_and_gather"]["primary_workflows"])
        self.assertIn("wiki", families["retain_knowledge"]["primary_workflows"])
        self.assertIn("img-summary", families["create_materials_and_visuals"]["primary_workflows"])
        self.assertIn("frontend", families["create_materials_and_visuals"]["primary_workflows"])
        self.assertIn("visual-qa", families["create_materials_and_visuals"]["primary_workflows"])
        self.assertNotIn("wiki", families["create_materials_and_visuals"]["primary_workflows"])
        self.assertIn("Claude Code", families["delegate_coding_and_ship"]["executor_choices"])
        self.assertIn("verification-gate", families["delegate_coding_and_ship"]["primary_workflows"])
        self.assertIn("workspace-audit", families["operate_and_observe"]["primary_workflows"])
        self.assertIn("instinct-ledger", families["operate_and_observe"]["primary_workflows"])
        self.assertEqual(summary["workflow_to_family"]["code-review"], "delegate_coding_and_ship")
        self.assertEqual(summary["workflow_to_family"]["verification-gate"], "delegate_coding_and_ship")
        self.assertEqual(summary["workflow_to_family"]["workspace-audit"], "operate_and_observe")
        self.assertEqual(summary["workflow_to_family"]["instinct-ledger"], "operate_and_observe")
        self.assertEqual(summary["workflow_to_family"]["wiki"], "retain_knowledge")
        self.assertEqual(lanes["intent_to_plan"]["owner_role"], "planner")
        self.assertEqual(lanes["retained_knowledge"]["owner_role"], "memory-keeper")
        self.assertIn("loop", lanes["intent_to_plan"]["primary_skills"])
        self.assertIn("wiki", lanes["retained_knowledge"]["primary_skills"])
        self.assertIn("img-summary", lanes["materials_and_visuals"]["primary_skills"])
        self.assertIn("frontend", lanes["materials_and_visuals"]["primary_skills"])
        self.assertIn("visual-qa", lanes["materials_and_visuals"]["primary_skills"])
        self.assertNotIn("wiki", lanes["materials_and_visuals"]["primary_skills"])
        self.assertIn("research-department", lanes["research_and_ops"]["primary_skills"])
        self.assertIn("workspace-audit", lanes["automation_and_status"]["primary_skills"])
        self.assertIn("agent-evaluation", lanes["automation_and_status"]["primary_skills"])
        self.assertIn("agent-debug", lanes["automation_and_status"]["primary_skills"])
        self.assertIn("instinct-ledger", lanes["automation_and_status"]["primary_skills"])
        self.assertIn("skill-scout", lanes["automation_and_status"]["primary_skills"])
        self.assertIn("skill-health", lanes["automation_and_status"]["primary_skills"])
        self.assertIn("verification-gate", lanes["coding_handoff"]["primary_skills"])
        self.assertIn("request-to-handoff", {item["id"] for item in lanes["intent_to_plan"]["representative_playbooks"]})
        self.assertIn("materials-processing", {item["id"] for item in lanes["materials_and_visuals"]["representative_playbooks"]})
        self.assertTrue(lanes["coding_handoff"]["wrapper_actions"])
        self.assertIn("feedback-triage", context_cards["research_and_ops"]["representative_workflows"])
        self.assertEqual(context_cards["research_and_ops"]["label"], "Research and ops")
        self.assertIn("Payment failures keep coming up", context_cards["research_and_ops"]["user_examples"])
        self.assertIn("wiki", context_cards["retained_knowledge"]["representative_workflows"])
        self.assertIn("write/query proof", context_cards["retained_knowledge"]["first_response_shape"])
        self.assertIn("img-summary", context_cards["materials_and_visuals"]["representative_workflows"])
        self.assertIn("frontend", context_cards["materials_and_visuals"]["representative_workflows"])
        self.assertIn("visual-qa", context_cards["materials_and_visuals"]["representative_workflows"])
        self.assertIn("revise/copy/generate/record", context_cards["materials_and_visuals"]["first_response_shape"])
        self.assertIn("workspace-audit", context_cards["automation_and_status"]["representative_workflows"])
        self.assertIn("rules-distill", context_cards["automation_and_status"]["representative_workflows"])
        self.assertIn("agent-debug", context_cards["automation_and_status"]["representative_workflows"])
        self.assertIn("instinct-ledger", context_cards["automation_and_status"]["representative_workflows"])
        self.assertIn("skill-scout", context_cards["automation_and_status"]["representative_workflows"])
        self.assertIn("skill-health", context_cards["automation_and_status"]["representative_workflows"])
        self.assertIn("implementation", context_cards["coding_handoff"]["not_evidence_until_observed"])

    def test_capability_inspect_finds_skill_and_role_without_runtime_claim(self) -> None:
        skill = inspect_capability("ultragoal", section="skills")["capability"]
        wiki_skill = inspect_capability("wiki", section="skills")["capability"]
        ops_surface = inspect_capability("ops-observability-card", section="skills")["capability"]
        codegraph_skill = inspect_capability("codegraph-refresh", section="skills")["capability"]
        agent_debug_skill = inspect_capability("agent-debug", section="skills")["capability"]
        instinct_ledger_skill = inspect_capability("instinct-ledger", section="skills")["capability"]
        awareness = inspect_capability("omh_awareness", section="omh_awareness")["capability"]
        role = inspect_capability("handoff-guide", section="agent_roles")["capability"]
        playbook = inspect_capability("request-to-handoff", section="playbooks")["capability"]
        legacy_role = inspect_capability("coding-handoff", section="agent_roles")

        self.assertEqual(skill["schema_version"], "skill_capability/v1")
        self.assertEqual(skill["tool_requirements"]["derivation_status"], "partial")
        self.assertIn("prepared_not_observed", skill["evidence_boundary"])
        self.assertEqual(skill["awareness_lane"], "intent_to_plan")
        self.assertIn("Use `ultragoal`", skill["workflow_routing_hint"])
        self.assertEqual(wiki_skill["awareness_lane"], "retained_knowledge")
        self.assertIn("Retained knowledge", wiki_skill["workflow_routing_hint"])
        self.assertIn("every OMH skill", skill["workflow_context_rule"])
        self.assertIn("generic tool can render or execute", skill["workflow_context_rule"])
        self.assertIn("Normal users talk to Hermes", skill["chat_rule"])
        self.assertIn("missing", skill["fallback_rule"])
        self.assertIn("omh_context", awareness["tool_hints"][0])
        self.assertIn("omh_capabilities", " ".join(awareness["tool_hints"]))
        self.assertIn("ambitious goal -> loopability check", " ".join(skill["cross_lane_examples"]))
        self.assertEqual(ops_surface["exposure"], "workflow_skill")
        self.assertEqual(awareness["schema_version"], "omh_awareness/v1")
        self.assertIn("materials", awareness["first_turn_rule"])
        self.assertIn("generic tools", awareness["first_turn_rule"])
        self.assertIn("meeting-brief", json.dumps(awareness, sort_keys=True))
        self.assertIn("capability manifest", awareness["context_surfaces"])
        self.assertTrue(ops_surface["install_visibility"])
        self.assertFalse(ops_surface["compatibility_alias"])
        self.assertIn("preferred_usage", ops_surface)
        self.assertIn("secret values", " ".join(codegraph_skill["safety_rules"]))
        self.assertIn("codebase-onboarding", " ".join(codegraph_skill["quality_bar"]))
        self.assertTrue(codegraph_skill["artifact_expectations"])
        self.assertIn("codegraph", " ".join(codegraph_skill["artifact_expectations"]))
        self.assertIn("agent_debug_report/v1", agent_debug_skill["artifact_expectations"])
        self.assertIn("instinct_candidate/v1", instinct_ledger_skill["artifact_expectations"])
        self.assertIn("instinct_export_review/v1", " ".join(instinct_ledger_skill["expected_outputs"]))
        self.assertIn("+", " ".join(instinct_ledger_skill["triggers"]))
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

        status, stdout, stderr = run_cli(["capabilities", "summary"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertIn("OMH capability summary", stdout)
        self.assertIn("Families are the user-facing front door", stdout)
        self.assertIn("Materials and visual summaries", stdout)

        status, stdout, stderr = run_cli(["capabilities", "summary", "--json"], output_json=False)

        self.assertEqual(status, 0, stderr)
        summary = json.loads(stdout)
        self.assertEqual(summary["schema_version"], "omh_capability_summary/v1")
        self.assertIn("roles", summary["section_aliases"])

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
        packages = pyproject["tool"]["setuptools"]["packages"]
        package_dir = pyproject["tool"]["setuptools"]["package-dir"]
        source_root = Path("src")

        self.assertIn("omh", packages)
        self.assertIn("omh.capabilities", packages)
        self.assertIn("omh.routing", packages)
        self.assertEqual(package_dir["omh"], "src/omh")
        self.assertEqual(package_dir["omh.capabilities"], "src/capabilities")
        self.assertEqual(package_dir["omh.routing"], "src/routing")
        for package_path in (
            "capabilities",
            "coding",
            "install",
            "maintenance",
            "mcp",
            "quality",
            "surfaces",
            "system",
            "workflows",
        ):
            with self.subTest(package_path=package_path):
                self.assertTrue((source_root / package_path / "__init__.py").is_file())
        self.assertTrue((source_root / "omh" / "cli" / "__init__.py").is_file())
        for compatibility_module in (
            "coding_delegation.py",
            "materials.py",
            "version.py",
        ):
            with self.subTest(compatibility_module=compatibility_module):
                self.assertTrue((source_root / "omh" / compatibility_module).is_file())

    def test_runtime_topology_is_deferred_from_first_pr(self) -> None:
        self.assertFalse(Path("src/capabilities/runtime_topology.py").exists())
        payload = capability_snapshot()
        exported = json.dumps(payload, sort_keys=True)

        self.assertNotIn('"runtime_topology"', exported)
        self.assertIn("no runtime_topology schema in this PR", payload["non_goals"])
