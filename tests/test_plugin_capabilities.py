from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.capabilities.families import capability_family_projection
from omh.capabilities.registry import capability_summary
from omh.capabilities.schema import CAPABILITY_SECTIONS
from omh.plugin_bundle.omh.metadata import PROVIDED_HOOKS, PROVIDED_TOOLS
from test_plugin_distribution import FakeHermesContext, load_installed_plugin


LEGACY_ROLE_ALIASES = {
    "coding-handoff": "handoff-guide",
    "implementation-owner": "builder",
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
            summary_families = {family["id"]: family for family in summary["capability_families"]}
            self.assertEqual(summary["schema_version"], "omh_capability_summary/v1")
            self.assertFalse(summary.get("degraded", False))
            self.assertIn("without requiring shell catalog approval", summary["purpose"])
            self.assertEqual(summary_families["plan_and_decide"]["label"], "Plan and decide")
            self.assertIn("paper-learning", summary_families["learn_and_gather"]["primary_workflows"])
            self.assertIn("wiki", summary_families["retain_knowledge"]["primary_workflows"])
            self.assertIn("img-summary", summary_families["create_materials_and_visuals"]["primary_workflows"])
            self.assertNotIn("wiki", summary_families["create_materials_and_visuals"]["primary_workflows"])
            self.assertIn("Claude Code", summary_families["delegate_coding_and_ship"]["executor_choices"])
            self.assertEqual(summary["workflow_to_family"]["paper-learning"], "learn_and_gather")
            self.assertEqual(summary["workflow_to_family"]["wiki"], "retain_knowledge")
            self.assertEqual(summary["workflow_to_family"]["code-review"], "delegate_coding_and_ship")
            self.assertIn("wiki", summary_lanes["retained_knowledge"]["primary_skills"])
            self.assertIn("img-summary", summary_lanes["materials_and_visuals"]["primary_skills"])
            self.assertNotIn("wiki", summary_lanes["materials_and_visuals"]["primary_skills"])
            self.assertIn("roles", summary["section_aliases"])
            summary_cards = {card["id"]: card for card in summary["workflow_context_cards"]}
            self.assertIn("feedback-triage", summary_cards["research_and_ops"]["representative_workflows"])
            self.assertIn("wiki", summary_cards["retained_knowledge"]["representative_workflows"])
            self.assertIn("img-summary", summary_cards["materials_and_visuals"]["representative_workflows"])

            inspected = json.loads(handler({"action": "inspect", "id": "handoff-guide"}))
            builder = json.loads(handler({"action": "inspect", "id": "builder", "section": "agent_roles"}))
            builder_alias = json.loads(handler({"action": "inspect", "id": "implementation-owner", "section": "agent_roles"}))
            inspected_by_alias_section = json.loads(handler({"action": "inspect", "id": "handoff-guide", "section": "roles"}))
            legacy_inspected = json.loads(handler({"action": "inspect", "id": "coding-handoff"}))
            self.assertEqual(inspected["section"], "agent_roles")
            self.assertEqual(inspected_by_alias_section["section"], "agent_roles")
            self.assertEqual(inspected_by_alias_section["resolved_id"], "handoff-guide")
            self.assertEqual(inspected["capability"]["runtime_claim"], "descriptor_not_runtime_agent")
            self.assertEqual(builder["resolved_id"], "builder")
            self.assertEqual(builder["capability"]["runtime_claim"], "descriptor_not_runtime_agent")
            self.assertIn("selected executor/runtime", " ".join(builder["capability"]["owns"]))
            self.assertIn("hidden runtime execution", builder["capability"]["does_not_own"])
            self.assertIn("unobserved worker dispatch", builder["capability"]["does_not_own"])
            self.assertEqual(builder_alias["resolved_id"], "builder")
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

    def test_plugin_tool_and_hook_can_self_record_host_observation_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            base = ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home)]
            status, _, stderr = run_cli(base + ["setup", "--with-plugin"])
            self.assertEqual(status, 0, stderr)

            module = load_installed_plugin(hermes_home / "plugins" / "omh")
            ctx = FakeHermesContext()
            module.register(ctx)

            interact_handler = ctx.tools["omh_interact"]["args"][2]
            probe_handler = ctx.tools["omh_probe"]["args"][2]
            interaction = json.loads(
                interact_handler(
                    {
                        "omh_home": str(omh_home),
                        "hermes_home": str(hermes_home),
                        "message": "I want to safely add a feature to this repo with secret-token-123",
                        "source": "discord",
                        "mode": "plan",
                        "source_metadata": {
                            "source_event_id": "msg-1",
                            "channel_ref": "chan-1",
                            "user_ref": "user-1",
                            "target_ref": "secret-token-123",
                            "runtime_ref": "sk-proj-example",
                        },
                        "observation": {
                            "host": "hermes-agent",
                            "session_id": "session-interact-1",
                            "evidence_ref": "host-tool-call:omh_interact",
                        },
                    }
                )
            )
            self.assertEqual(interaction["schema_version"], "chat_interaction/v1")
            self.assertEqual(interaction["mode"], "plan")
            self.assertTrue(interaction["wrapper_session"]["recorded"])
            self.assertEqual(interaction["wrapper_session"]["session_status"], "plan_presented")
            self.assertEqual(interaction["wrapper_session"]["record_provenance"]["producer"], "plugin_tool")
            self.assertEqual(interaction["plugin_host_observation"]["tool"], "omh_interact")
            serialized_interaction = json.dumps(interaction, sort_keys=True)
            self.assertNotIn("secret-token-123", serialized_interaction)
            self.assertNotIn("sk-proj-example", serialized_interaction)

            probe = json.loads(
                probe_handler(
                    {
                        "omh_home": str(omh_home),
                        "hermes_home": str(hermes_home),
                        "include_roadmap": True,
                        "observation": {
                            "host": "hermes-agent",
                            "session_id": "session-tool-1",
                            "evidence_ref": "host-tool-call:omh_probe",
                        },
                    }
                )
            )

            self.assertTrue(probe["plugin_runtime_observed"])
            self.assertTrue(probe["native_integration_claim_ready"])
            self.assertEqual(probe["plugin_host_observation"]["event"], "tool_call")
            self.assertEqual(probe["plugin_host_observation"]["tool"], "omh_probe")
            self.assertEqual(probe["plugin_host_observation"]["runtime_readiness"], "active_runtime_observed")
            roadmap_actions = {item["id"] for item in probe["capability_gap_roadmap"]["next_actions"]}
            self.assertNotIn("observe_plugin_runtime", roadmap_actions)
            self.assertNotIn("record_wrapper_usage", roadmap_actions)
            caps = {item["name"]: item for item in probe["capabilities"]}
            self.assertEqual(caps["wrapper_metadata"]["status"], "available")

            pre_llm = ctx.hooks["pre_llm_call"]
            pre_llm(
                omh_home=str(omh_home),
                hermes_home=str(hermes_home),
                user_message="summarize this without storing secret-token-123",
                observation={
                    "host": "hermes-agent",
                    "session_id": "session-hook-1",
                    "evidence_ref": "host-hook-call:pre_llm_call",
                },
            )

            status, stdout, stderr = run_cli(base + ["plugin", "observations", "--limit", "5"])
            self.assertEqual(status, 0, stderr)
            observations = json.loads(stdout)["observations"]
            latest = observations[0]
            self.assertEqual(latest["event"], "hook_call")
            self.assertEqual(latest["hook"], "pre_llm_call")
            self.assertEqual(latest["host"], "hermes-agent")
            serialized = json.dumps(observations, sort_keys=True)
            self.assertIn("host-tool-call:omh_probe", serialized)
            self.assertIn("host-hook-call:pre_llm_call", serialized)
            self.assertNotIn("secret-token-123", serialized)

    def test_plugin_interact_backend_errors_are_redacted(self) -> None:
        from omh.plugin_bundle.omh.tools.chat_tool import omh_interact_handler

        with patch(
            "omh.plugin_bundle.omh.tools.chat_tool._package_interaction",
            side_effect=RuntimeError("sk-proj-secret leaked-token-value"),
        ):
            payload = json.loads(
                omh_interact_handler(
                    {
                        "message": "route this request",
                        "source": "discord",
                        "source_metadata": {
                            "source_event_id": "msg-1",
                            "channel_ref": "chan-1",
                            "runtime_ref": "sk-proj-secret",
                        },
                    }
                )
            )

        serialized = json.dumps(payload, sort_keys=True)
        self.assertEqual(payload["schema_version"], "omh_interact_result/v1")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "package_backend_error")
        self.assertEqual(payload["error_type"], "RuntimeError")
        self.assertFalse(payload["wrapper_session"]["recorded"])
        self.assertNotIn("sk-proj-secret", serialized)
        self.assertNotIn("leaked-token-value", serialized)

    def test_installed_plugin_capabilities_tool_loads_without_installed_omh_package(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            status, _, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup", "--with-plugin"])
            self.assertEqual(status, 0, stderr)
            plugin_dir = hermes_home / "plugins" / "omh"
            sionic_prompt_fixture = """이번 Sionic 작업에서 OMH가 얼마나 관여했는지 사용성 평가하고,
왜 OMH를 덜 썼는지 분석해서 라우터 강화 플랜으로 잡아줘.
Sionic은 마크다운 노트뿐 아니라 위키 페이지/site 생성도 포함했어.
결과창에는 Background process proc_d5eb61ddcf80 finished with exit code 0~
Here's the final output: 같은 raw output, turn.completed usage, Self-improvement review 줄이 보였고
이걸 프리티하게 OMH wrapper report로 정리해야 했어.

[OMH Awareness]
status=prepared_not_observed; Evidence boundary: pasted status is diagnostic evidence.
[OMH Route Hint]
intent=delivery_intent; selected=ultraprocess; confidence=medium.
mentioned_workflows=ultraprocess.
not_executed=Codex.
[omh]
selected_workflow=ultraprocess
latest_runtime_run=not_executed=Codex
execution_observed=false
review_observed=false
ci_observed=false
merge_observed=false
"""
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
                context_handler = ctx.tools["omh_context"]["args"][2]
                interact_handler = ctx.tools["omh_interact"]["args"][2]
                recommend_handler = ctx.tools["omh_recommend"]["args"][2]
                probe_handler = ctx.tools["omh_probe"]["args"][2]
                keywords = json.loads(handler({{"action": "export", "section": "keywords"}}))
                exported = json.loads(handler({{"action": "export"}}))
                summary = json.loads(handler({{"action": "summary"}}))
                recommendation = json.loads(
                    recommend_handler({{"message": "make an image summary for this PR with secret-token-123", "limit": 2}})
                )
                context_brief = json.loads(
                    context_handler({{
                        "message": "make an image summary for this PR with secret-token-123",
                        "source": "discord",
                        "limit": 2,
                        "include_prompt_context": True,
                    }})
                )
                context_catalog = json.loads(
                    context_handler({{
                        "message": "what OMH workflows are available with secret-token-123?",
                        "source": "discord",
                        "limit": 2,
                    }})
                )
                context_meta = json.loads(
                    context_handler({{
                        "message": "왜 ultraprocess 로그가 떠? Codex handoff 테스트 용어일 뿐이야.",
                        "source": "discord",
                        "limit": 2,
                        "include_prompt_context": True,
                    }})
                )
                sionic_prompt = {sionic_prompt_fixture!r}
                context_sionic = json.loads(
                    context_handler({{
                        "message": sionic_prompt,
                        "source": "discord",
                        "limit": 3,
                        "include_prompt_context": True,
                    }})
                )
                interaction = json.loads(
                    interact_handler({{
                        "message": "make an image summary for this PR with secret-token-123",
                        "source": "discord",
                        "record_session": True,
                        "source_metadata": {{"source_event_id": "standalone-msg-1", "channel_ref": "standalone-chan-1"}},
                    }})
                )
                probe = json.loads(
                    probe_handler({{
                        "omh_home": {str(omh_home)!r},
                        "hermes_home": {str(hermes_home)!r},
                        "include_roadmap": True,
                        "include_parity": True,
                    }})
                )
                observed_probe = json.loads(
                    probe_handler({{
                        "omh_home": {str(omh_home)!r},
                        "hermes_home": {str(hermes_home)!r},
                        "include_roadmap": True,
                        "include_parity": True,
                        "observation": {{
                            "host": "hermes-agent",
                            "session_id": "standalone-session-1",
                            "evidence_ref": "standalone-host-call:omh_probe",
                        }},
                    }})
                )
                sensitive_probe = json.loads(
                    probe_handler({{
                        "omh_home": {str(omh_home)!r},
                        "hermes_home": {str(hermes_home)!r},
                        "observation": {{
                            "host": "secret-token-123",
                            "session_id": "session-secret-token-123",
                            "evidence_ref": "standalone-host-call:sensitive",
                        }},
                    }})
                )
                observation_text = ({str(omh_home / "runtime" / "plugin_host_observations.jsonl")!r})
                observation_text = open(observation_text, encoding="utf-8").read() if __import__("os").path.exists(observation_text) else ""
                state_path = {str(omh_home / "runtime" / "state.json")!r}
                state = json.load(open(state_path, encoding="utf-8")) if __import__("os").path.exists(state_path) else {{}}
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
                    "context_schema": context_brief["schema_version"],
                    "context_source": context_brief["source_backend"],
                    "context_plugin_tool": context_brief["plugin_tool"],
                    "context_primary_workflow": context_brief["route_hint"]["primary_workflow"],
                    "context_prompt_context": context_brief["prompt_context"],
                    "context_serialized": json.dumps(context_brief, sort_keys=True),
                    "context_catalog_status": context_catalog["catalog_question"]["status"],
                    "context_catalog_next_action": context_catalog["catalog_question"]["next_action"],
                    "context_catalog_tool": context_catalog["catalog_question"]["recommended_tool"],
                    "context_catalog_serialized": json.dumps(context_catalog, sort_keys=True),
                    "context_meta_primary_workflow": context_meta["route_hint"]["primary_workflow"],
                    "context_meta_mentioned_workflows": context_meta["route_hint"]["mentioned_workflows"],
                    "context_meta_runtime_terms": context_meta["route_hint"]["mentioned_runtime_terms"],
                    "context_meta_prompt_context": context_meta["prompt_context"],
                    "context_sionic_primary_workflow": context_sionic["route_hint"]["primary_workflow"],
                    "context_sionic_intent_class": context_sionic["route_hint"]["intent_class"],
                    "context_sionic_mentioned_workflows": context_sionic["route_hint"]["mentioned_workflows"],
                    "context_sionic_runtime_terms": context_sionic["route_hint"]["mentioned_runtime_terms"],
                    "context_sionic_not_executed": context_sionic["route_hint"]["not_executed"],
                    "context_sionic_first_hint": context_sionic["route_hint"]["hints"][0]["workflow"],
                    "context_sionic_prompt_context": context_sionic["prompt_context"],
                    "interaction_schema": interaction["schema_version"],
                    "interaction_degraded": interaction["degraded"],
                    "interaction_source": interaction["source_backend"],
                    "interaction_recorded": interaction["wrapper_session"]["recorded"],
                    "interaction_serialized": json.dumps(interaction, sort_keys=True),
                    "probe_schema": probe["schema_version"],
                    "probe_source": probe["source"],
                    "probe_degraded": probe["degraded"],
                    "probe_tool": probe["plugin_tool"],
                    "probe_runtime_observed": probe["plugin_runtime_observed"],
                    "probe_native_ready": probe["native_integration_claim_ready"],
                    "probe_capability_names": sorted(item["name"] for item in probe["capabilities"]),
                    "probe_roadmap_schema": probe["capability_gap_roadmap"]["schema_version"],
                    "probe_roadmap_actions": [item["id"] for item in probe["capability_gap_roadmap"]["next_actions"]],
                    "probe_parity_status": probe["parity_matrix"]["status"],
                    "observed_probe_runtime_observed": observed_probe["plugin_runtime_observed"],
                    "observed_probe_native_ready": observed_probe["native_integration_claim_ready"],
                    "observed_probe_public": observed_probe["plugin_host_observation"],
                    "observed_probe_roadmap_actions": [
                        item["id"] for item in observed_probe["capability_gap_roadmap"]["next_actions"]
                    ],
                    "standalone_observation_text": observation_text,
                    "standalone_state_readiness": state.get("last_plugin_runtime_readiness"),
                    "sensitive_probe_serialized": json.dumps(sensitive_probe, sort_keys=True),
                    "sensitive_probe_public": sensitive_probe.get("plugin_host_observation"),
                    "summary_lanes": [lane["id"] for lane in summary["lanes"]],
                    "summary_families": summary["capability_families"],
                    "summary_guidance": summary["direct_response_guidance"],
                    "summary_family_workflows": [
                        workflow
                        for family in summary["capability_families"]
                        for workflow in family["primary_workflows"]
                    ],
                    "summary_workflow_to_family": summary["workflow_to_family"],
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
            self.assertEqual(
                len(payload["summary_family_workflows"]),
                len(set(payload["summary_family_workflows"])),
            )
            canonical_families = {
                family["id"]: family
                for family in capability_family_projection()["families"]
            }
            standalone_families = {
                family["id"]: family
                for family in payload["summary_families"]
            }
            self.assertEqual(standalone_families.keys(), canonical_families.keys())
            for family_id, canonical_family in canonical_families.items():
                with self.subTest(family_id=family_id):
                    standalone_family = standalone_families[family_id]
                    self.assertEqual(standalone_family, canonical_family)
            self.assertEqual(payload["summary_guidance"], capability_summary()["direct_response_guidance"])
            self.assertEqual(payload["summary_workflow_to_family"]["paper-learning"], "learn_and_gather")
            self.assertEqual(payload["summary_workflow_to_family"]["code-review"], "delegate_coding_and_ship")
            self.assertEqual(payload["summary_workflow_to_family"]["request-to-handoff"], "delegate_coding_and_ship")
            self.assertEqual(payload["summary_workflow_to_family"]["ask"], "operate_and_observe")
            self.assertEqual(payload["recommend_schema"], "omh_recommend_result/v1")
            self.assertEqual(payload["recommend_source"], "standalone_plugin_bundle_fallback")
            self.assertEqual(payload["recommend_status"], "recommended")
            self.assertFalse(payload["recommend_raw_prompt_echoed"])
            self.assertEqual(payload["recommend_first_skill"], "img-summary")
            self.assertIn("<current user request>", payload["recommend_serialized"])
            self.assertNotIn("secret-token-123", payload["recommend_serialized"])
            self.assertEqual(payload["context_schema"], "omh_context_brief/v1")
            self.assertEqual(payload["context_source"], "standalone_plugin_bundle_fallback")
            self.assertEqual(payload["context_plugin_tool"], "omh_context")
            self.assertEqual(payload["context_primary_workflow"], "img-summary")
            self.assertIn("selected=img-summary", payload["context_prompt_context"])
            self.assertIn("generic tool can render", payload["context_serialized"])
            self.assertNotIn("secret-token-123", payload["context_serialized"])
            self.assertEqual(payload["context_catalog_status"], "matched")
            self.assertEqual(payload["context_catalog_next_action"], "show_workflow_picker")
            self.assertEqual(payload["context_catalog_tool"], "omh_capabilities")
            self.assertNotIn("secret-token-123", payload["context_catalog_serialized"])
            self.assertEqual(payload["context_meta_primary_workflow"], "workflow-learning")
            self.assertIn("ultraprocess", payload["context_meta_mentioned_workflows"])
            self.assertIn("Codex", payload["context_meta_runtime_terms"])
            self.assertIn("selected=workflow-learning", payload["context_meta_prompt_context"])
            self.assertNotIn("selected=ultraprocess", payload["context_meta_prompt_context"])
            self.assertEqual(payload["context_sionic_primary_workflow"], "workflow-learning")
            self.assertIn(payload["context_sionic_intent_class"], {"feedback_signal", "meta_discussion"})
            self.assertIn("ultraprocess", payload["context_sionic_mentioned_workflows"])
            self.assertIn("Codex", payload["context_sionic_runtime_terms"])
            self.assertIn("ultraprocess", payload["context_sionic_not_executed"])
            self.assertIn("Codex", payload["context_sionic_not_executed"])
            self.assertEqual(payload["context_sionic_first_hint"], "workflow-learning")
            self.assertIn("selected=workflow-learning", payload["context_sionic_prompt_context"])
            self.assertNotIn("selected=ultraprocess", payload["context_sionic_prompt_context"])
            self.assertEqual(payload["interaction_schema"], "chat_interaction/v1")
            self.assertTrue(payload["interaction_degraded"])
            self.assertEqual(payload["interaction_source"], "standalone_plugin_bundle_fallback")
            self.assertFalse(payload["interaction_recorded"])
            self.assertNotIn("secret-token-123", payload["interaction_serialized"])
            self.assertEqual(payload["probe_schema"], 1)
            self.assertEqual(payload["probe_source"], "standalone_plugin_bundle_fallback")
            self.assertTrue(payload["probe_degraded"])
            self.assertEqual(payload["probe_tool"], "omh_probe")
            self.assertFalse(payload["probe_runtime_observed"])
            self.assertFalse(payload["probe_native_ready"])
            self.assertIn("omh_plugin_bundle", payload["probe_capability_names"])
            self.assertIn("plugin_tool_context", payload["probe_capability_names"])
            self.assertEqual(payload["probe_roadmap_schema"], "omh_capability_gap_roadmap/v1")
            self.assertIn("observe_plugin_runtime", payload["probe_roadmap_actions"])
            self.assertEqual(payload["probe_parity_status"], "unavailable_without_package_backend")
            self.assertTrue(payload["observed_probe_runtime_observed"])
            self.assertTrue(payload["observed_probe_native_ready"])
            self.assertEqual(payload["observed_probe_public"]["event"], "tool_call")
            self.assertEqual(payload["observed_probe_public"]["tool"], "omh_probe")
            self.assertEqual(payload["observed_probe_public"]["host"], "hermes-agent")
            self.assertIn("standalone-host-call:omh_probe", payload["standalone_observation_text"])
            self.assertIn("standalone-session-1", payload["standalone_observation_text"])
            self.assertEqual(payload["standalone_state_readiness"], "active_runtime_observed")
            self.assertNotIn("observe_plugin_runtime", payload["observed_probe_roadmap_actions"])
            self.assertEqual(payload["sensitive_probe_public"]["status"], "not_recorded")
            self.assertEqual(payload["sensitive_probe_public"]["host"], "")
            self.assertEqual(payload["sensitive_probe_public"]["session_id"], "")
            self.assertNotIn("secret-token-123", payload["sensitive_probe_serialized"])
            self.assertNotIn("secret-token-123", payload["standalone_observation_text"])
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
