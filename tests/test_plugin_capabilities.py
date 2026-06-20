from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.capabilities.schema import CAPABILITY_SECTIONS
from omh.plugin_bundle.omh.metadata import PROVIDED_HOOKS, PROVIDED_TOOLS
from test_plugin_distribution import FakeHermesContext, load_installed_plugin


LEGACY_ROLE_ALIASES = {
    "coding-handoff": "handoff-guide",
    "planning-lead": "planner",
    "research-lead": "researcher",
    "review-gate": "reviewer",
}


class PluginCapabilitiesTests(unittest.TestCase):
    def test_installed_plugin_registers_capabilities_tool_and_returns_bounded_json(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            status, _, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-plugin"])
            self.assertEqual(status, 0, stderr)

            module = load_installed_plugin(hermes_home / "plugins" / "omh")
            ctx = FakeHermesContext()
            module.register(ctx)

            self.assertIn("omh_capabilities", ctx.tools)
            handler = ctx.tools["omh_capabilities"]["args"][2]
            payload = json.loads(handler({"action": "export", "section": "keywords"}))
            self.assertEqual(payload["schema_version"], "omh_capability_manifest/v1")
            self.assertEqual(payload["section"], "keywords")
            self.assertIn("explicit_invocation_prefixes", payload["keywords"])

            summary = json.loads(handler({"action": "summary"}))
            summary_lanes = {lane["id"]: lane for lane in summary["lanes"]}
            self.assertEqual(summary["schema_version"], "omh_capability_summary/v1")
            self.assertFalse(summary.get("degraded", False))
            self.assertIn("without requiring shell catalog approval", summary["purpose"])
            self.assertIn("img-summary", summary_lanes["materials_and_visuals"]["primary_skills"])
            self.assertIn("roles", summary["section_aliases"])
            summary_cards = {card["id"]: card for card in summary["workflow_context_cards"]}
            self.assertIn("feedback-triage", summary_cards["research_and_ops"]["representative_workflows"])
            self.assertIn("img-summary", summary_cards["materials_and_visuals"]["representative_workflows"])

            inspected = json.loads(handler({"action": "inspect", "id": "handoff-guide"}))
            inspected_by_alias_section = json.loads(handler({"action": "inspect", "id": "handoff-guide", "section": "roles"}))
            legacy_inspected = json.loads(handler({"action": "inspect", "id": "coding-handoff"}))
            self.assertEqual(inspected["section"], "agent_roles")
            self.assertEqual(inspected_by_alias_section["section"], "agent_roles")
            self.assertEqual(inspected_by_alias_section["resolved_id"], "handoff-guide")
            self.assertEqual(inspected["capability"]["runtime_claim"], "descriptor_not_runtime_agent")
            self.assertEqual(legacy_inspected["section"], "agent_roles")
            self.assertEqual(legacy_inspected["requested_id"], "coding-handoff")
            self.assertEqual(legacy_inspected["resolved_id"], "handoff-guide")
            self.assertEqual(legacy_inspected["capability"]["id"], "handoff-guide")
            for alias, expected_role in LEGACY_ROLE_ALIASES.items():
                with self.subTest(alias=alias):
                    legacy = json.loads(handler({"action": "inspect", "id": alias, "section": "agent_roles"}))
                    self.assertEqual(legacy["section"], "agent_roles")
                    self.assertEqual(legacy["requested_id"], alias)
                    self.assertEqual(legacy["resolved_id"], expected_role)
                    self.assertEqual(legacy["capability"]["id"], expected_role)

            retained = json.loads(handler({"action": "inspect", "id": "retained-cognition", "section": "agent_roles"}))
            self.assertIn("capability not found: retained-cognition", retained["error"])

    def test_installed_plugin_capabilities_tool_loads_without_installed_omh_package(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            status, _, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-plugin"])
            self.assertEqual(status, 0, stderr)
            plugin_dir = hermes_home / "plugins" / "omh"
            script = textwrap.dedent(
                f"""
                import importlib.util
                import json
                import sys

                class FakeCtx:
                    def __init__(self):
                        self.tools = {{}}
                        self.hooks = {{}}

                    def register_tool(self, name, *args, **kwargs):
                        self.tools[name] = {{"args": args, "kwargs": kwargs}}

                    def register_hook(self, name, handler):
                        self.hooks[name] = handler

                spec = importlib.util.spec_from_file_location(
                    "_standalone_omh_plugin",
                    {str(plugin_dir / "__init__.py")!r},
                    submodule_search_locations=[{str(plugin_dir)!r}],
                )
                module = importlib.util.module_from_spec(spec)
                sys.modules["_standalone_omh_plugin"] = module
                spec.loader.exec_module(module)
                ctx = FakeCtx()
                module.register(ctx)
                handler = ctx.tools["omh_capabilities"]["args"][2]
                recommend_handler = ctx.tools["omh_recommend"]["args"][2]
                keywords = json.loads(handler({{"action": "export", "section": "keywords"}}))
                exported = json.loads(handler({{"action": "export"}}))
                summary = json.loads(handler({{"action": "summary"}}))
                recommendation = json.loads(
                    recommend_handler({{"message": "make an image summary for this PR with secret-token-123", "limit": 2}})
                )
                listed_tools = json.loads(handler({{"action": "list", "section": "tool_requirements"}}))
                evidence = json.loads(handler({{"action": "export", "section": "evidence_boundaries"}}))
                inspected = json.loads(handler({{"action": "inspect", "id": "handoff-guide"}}))
                alias_results = {{}}
                alias_section = json.loads(handler({{"action": "inspect", "id": "handoff-guide", "section": "roles"}}))
                alias_list = json.loads(handler({{"action": "list", "section": "agents"}}))
                for alias in {LEGACY_ROLE_ALIASES!r}:
                    alias_results[alias] = json.loads(
                        handler({{"action": "inspect", "id": alias, "section": "agent_roles"}})
                    )
                retained = json.loads(
                    handler({{"action": "inspect", "id": "retained-cognition", "section": "agent_roles"}})
                )
                inspected_loop = json.loads(handler({{"action": "inspect", "section": "skills", "id": "loop"}}))
                inspected_visual = json.loads(handler({{"action": "inspect", "section": "skills", "id": "img-summary"}}))
                inspected_process = json.loads(handler({{"action": "inspect", "section": "skills", "id": "ultraprocess"}}))
                inspected_playbook = json.loads(
                    handler({{"action": "inspect", "section": "playbooks", "id": "research-department"}})
                )
                inspected_boundary = json.loads(
                    handler({{"action": "inspect", "section": "evidence_boundaries", "id": "prepared_is_not"}})
                )
                invalid_section = json.loads(handler({{"action": "inspect", "section": "missing", "id": "loop"}}))
                print(json.dumps({{
                    "tool_registered": "omh_capabilities" in ctx.tools,
                    "sections": sorted(key for key in exported if key in {set(CAPABILITY_SECTIONS)!r}),
                    "plugin_tools": sorted(item["name"] for item in exported["hooks"]["plugin_tools"]),
                    "plugin_hooks": sorted(item["name"] for item in exported["hooks"]["plugin_hooks"]),
                    "source": exported["source"],
                    "summary_schema": summary["schema_version"],
                    "summary_source": summary["source"],
                    "recommend_schema": recommendation["schema_version"],
                    "recommend_source": recommendation["source"],
                    "recommend_status": recommendation["status"],
                    "recommend_raw_prompt_echoed": recommendation["message"]["raw_prompt_echoed"],
                    "recommend_first_skill": recommendation["recommendations"][0]["skill"],
                    "recommend_serialized": json.dumps(recommendation, sort_keys=True),
                    "summary_lanes": [lane["id"] for lane in summary["lanes"]],
                    "summary_visual_skills": [
                        lane["primary_skills"]
                        for lane in summary["lanes"]
                        if lane["id"] == "materials_and_visuals"
                    ][0],
                    "summary_intent_playbooks": [
                        playbook["id"]
                        for lane in summary["lanes"]
                        if lane["id"] == "intent_to_plan"
                        for playbook in lane["representative_playbooks"]
                    ],
                    "summary_context_cards": {{
                        card["id"]: card["representative_workflows"]
                        for card in summary["workflow_context_cards"]
                    }},
                    "summary_alias_roles": summary["section_aliases"]["roles"],
                    "keyword_schema": keywords["keywords"]["schema_version"],
                    "skill_ids": sorted(item["id"] for item in exported["skills"]),
                    "tool_requirement_schema": exported["tool_requirements"]["schema_version"],
                    "tool_requirement_ids": listed_tools["ids"],
                    "evidence_section": evidence["section"],
                    "prepared_boundary": inspected_boundary["capability"],
                    "inspect_section": inspected["section"],
                    "alias_section": alias_section["section"],
                    "alias_section_resolved": alias_section["resolved_id"],
                    "alias_list_section": alias_list["section"],
                    "alias_list_ids": alias_list["ids"],
                    "alias_results": {{
                        alias: result["resolved_id"]
                        for alias, result in alias_results.items()
                    }},
                    "retained_error": retained["error"],
                    "loop_section": inspected_loop["section"],
                    "loop_runtime_claim": inspected_loop["capability"]["runtime_claim"],
                    "loop_routing_hint": inspected_loop["capability"]["workflow_routing_hint"],
                    "loop_chat_rule": inspected_loop["capability"]["chat_rule"],
                    "loop_context_rule": inspected_loop["capability"]["workflow_context_rule"],
                    "loop_fallback_rule": inspected_loop["capability"]["fallback_rule"],
                    "loop_evidence_boundary": inspected_loop["capability"]["evidence_boundary"],
                    "loop_cross_lane_examples": inspected_loop["capability"]["cross_lane_examples"],
                    "visual_lane": inspected_visual["capability"]["awareness_lane"],
                    "visual_owner": inspected_visual["capability"]["primary_owner_role"],
                    "process_lane": inspected_process["capability"]["awareness_lane"],
                    "process_owner": inspected_process["capability"]["primary_owner_role"],
                    "playbook_section": inspected_playbook["section"],
                    "playbook_runtime_claim": inspected_playbook["capability"]["runtime_claim"],
                    "playbook_context_rule": inspected_playbook["capability"]["workflow_context_rule"],
                    "playbook_chat_rule": inspected_playbook["capability"]["chat_rule"],
                    "playbook_pipeline": inspected_playbook["capability"]["pipeline"],
                    "playbook_owner": inspected_playbook["capability"]["primary_owner_role"],
                    "playbook_actions": inspected_playbook["capability"]["available_wrapper_actions"],
                    "playbook_first_stage": inspected_playbook["capability"]["first_stage"],
                    "playbook_prepared_boundary": inspected_playbook["capability"]["prepared_is_not"],
                    "runtime_claim": inspected["capability"]["runtime_claim"],
                    "invalid_section_error": invalid_section["error"],
                    "degraded": inspected["degraded"],
                }}, sort_keys=True))
                """
            )

            result = subprocess.run(
                [sys.executable, "-S", "-c", script],
                cwd=str(root),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["tool_registered"])
            self.assertEqual(payload["sections"], sorted(CAPABILITY_SECTIONS))
            self.assertEqual(payload["plugin_tools"], sorted(PROVIDED_TOOLS))
            self.assertEqual(payload["plugin_hooks"], sorted(PROVIDED_HOOKS))
            self.assertEqual(payload["source"], "standalone_plugin_bundle_fallback")
            self.assertEqual(payload["summary_schema"], "omh_capability_summary/v1")
            self.assertEqual(payload["summary_source"], "standalone_plugin_bundle_fallback")
            self.assertEqual(payload["recommend_schema"], "omh_recommend_result/v1")
            self.assertEqual(payload["recommend_source"], "standalone_plugin_bundle_fallback")
            self.assertEqual(payload["recommend_status"], "recommended")
            self.assertFalse(payload["recommend_raw_prompt_echoed"])
            self.assertEqual(payload["recommend_first_skill"], "img-summary")
            self.assertIn("<current user request>", payload["recommend_serialized"])
            self.assertNotIn("secret-token-123", payload["recommend_serialized"])
            self.assertIn("intent_to_plan", payload["summary_lanes"])
            self.assertIn("img-summary", payload["summary_visual_skills"])
            self.assertIn("request-to-handoff", payload["summary_intent_playbooks"])
            self.assertIn("feedback-triage", payload["summary_context_cards"]["research_and_ops"])
            self.assertIn("ultraprocess", payload["summary_context_cards"]["coding_handoff"])
            self.assertEqual(payload["summary_alias_roles"], "agent_roles")
            self.assertEqual(payload["keyword_schema"], "keyword_detector_manifest/v1")
            for skill in (
                "img-summary",
                "ultraprocess",
                "research-department",
                "materials-package",
                "automation-blueprint",
                "code-review",
            ):
                with self.subTest(skill=skill):
                    self.assertIn(skill, payload["skill_ids"])
                    self.assertIn(skill, payload["tool_requirement_ids"])
            self.assertEqual(payload["tool_requirement_schema"], "tool_requirement_manifest/v1")
            self.assertIn("loop", payload["tool_requirement_ids"])
            self.assertEqual(payload["evidence_section"], "evidence_boundaries")
            self.assertIn("Prepared OMH capability", payload["prepared_boundary"])
            self.assertEqual(payload["inspect_section"], "agent_roles")
            self.assertEqual(payload["alias_section"], "agent_roles")
            self.assertEqual(payload["alias_section_resolved"], "handoff-guide")
            self.assertEqual(payload["alias_list_section"], "agent_roles")
            self.assertIn("planner", payload["alias_list_ids"])
            self.assertEqual(payload["alias_results"], LEGACY_ROLE_ALIASES)
            self.assertIn("unknown capability id: retained-cognition", payload["retained_error"])
            self.assertEqual(payload["loop_section"], "skills")
            self.assertEqual(payload["loop_runtime_claim"], "skill_guidance_not_execution")
            self.assertIn("Use `loop`", payload["loop_routing_hint"])
            self.assertIn("Normal users talk to Hermes", payload["loop_chat_rule"])
            self.assertIn("every OMH skill", payload["loop_context_rule"])
            self.assertIn("generic tool can render or execute", payload["loop_context_rule"])
            self.assertIn("missing", payload["loop_fallback_rule"])
            self.assertIn("not observed execution", payload["loop_evidence_boundary"])
            self.assertIn("ambitious goal -> loopability check", " ".join(payload["loop_cross_lane_examples"]))
            self.assertEqual(payload["visual_lane"], "materials_and_visuals")
            self.assertEqual(payload["visual_owner"], "operator")
            self.assertEqual(payload["process_lane"], "intent_to_plan")
            self.assertEqual(payload["process_owner"], "planner")
            self.assertEqual(payload["playbook_section"], "playbooks")
            self.assertEqual(payload["playbook_runtime_claim"], "playbook_guidance_not_execution")
            self.assertIn("situation-level workflow maps", payload["playbook_context_rule"])
            self.assertIn("Normal users talk to Hermes", payload["playbook_chat_rule"])
            self.assertIn("analysis_brief", payload["playbook_pipeline"])
            self.assertEqual(payload["playbook_owner"], "researcher")
            self.assertIn("show_status", payload["playbook_actions"])
            self.assertEqual(payload["playbook_first_stage"]["id"], "topic_scope")
            self.assertIn("Prepared OMH capability", payload["playbook_prepared_boundary"])
            self.assertEqual(payload["runtime_claim"], "descriptor_not_runtime_agent")
            self.assertIn("unknown capability section", payload["invalid_section_error"])
            self.assertTrue(payload["degraded"])
