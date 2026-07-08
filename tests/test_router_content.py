from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
import unittest

from _local_package import load_local_package

load_local_package()
from omh.routing import recommend as recommend_module
from omh.routing import chat as chat_module
from omh.routing import policy as policy_module
from omh.routing.action_copy import next_action_label
from omh.routing.materials_cues import OFFICE_FILE_MATERIAL_CATALOG_TRIGGERS, OFFICE_FILE_MATERIAL_PHRASES
from omh.routing.visual_qa_cues import BROWSER_VISUAL_QA_PHRASES, CUSTOMER_SYMPTOM_REPORT_PHRASES
from omh.capabilities.orchestration import orchestration_patterns
from omh.wrapper.contract import VISIBLE_ACTIONS
from omh.roles import role_definitions, role_file_markdown, roles_reference_markdown
from omh.skill_pack import (
    builtin_definitions,
    builtin_harnesses,
    builtin_skill_reference_templates,
    builtin_skill_templates,
    installable_skill_definitions,
    routable_definitions,
    skill_exposure_payload,
)
from omh.playbooks import inspect_playbook, list_playbooks
from omh.plugin_bundle.omh.awareness import ROUTER_KEYWORD_SKILLS, _ROUTE_HINT_RULES, router_keyword_summary
from omh.quality.grounded_score import GROUNDED_SCENARIOS
from omh.runtime.records import validate_harness_quality
from omh.skills.catalog import (
    SkillDefinition,
    catalog_intent_delegation_skill_names,
    harness_quality_contract,
    primary_harness_for_skill,
    retained_delegation_skill_names,
)
from omh.skills.render import workflow_reference_markdown, workflow_reference_payload
from omh.snippet import WORKSPACE_SNIPPET
from omh.use_cases import USE_CASES, list_use_cases


FLAGSHIP_SKILLS = {
    "oh-my-hermes",
    "ultragoal",
    "loop",
    "ultraprocess",
    "deep-interview",
    "ultrawork",
    "meeting-brief",
    "feedback-triage",
    "code-review",
    "doctor",
}

FEATURE_SURFACE_EXPOSURES = {
    "automation-blueprint": ("workflow_skill", True),
    "github-event-ops": ("workflow_skill", True),
    "agent-board": ("workflow_skill", True),
    "memory-curation-review": ("workflow_skill", True),
    "gateway-intent-card": ("workflow_skill", True),
    "executor-runtime-readiness": ("workflow_skill", True),
    "deliverable-package": ("workflow_skill", True),
    "design-quality-gate": ("workflow_skill", True),
    "frontend": ("workflow_skill", True),
    "accessibility-audit": ("workflow_skill", True),
    "visual-qa": ("workflow_skill", True),
    "browser-operator": ("workflow_skill", True),
    "workspace-file-operator": ("workflow_skill", True),
    "command-operator": ("workflow_skill", True),
    "connector-operator": ("workflow_skill", True),
    "live-info-operator": ("workflow_skill", True),
    "content-operator": ("workflow_skill", True),
    "media-input-operator": ("workflow_skill", True),
    "data-analysis": ("workflow_skill", True),
    "build-failure-triage": ("workflow_skill", True),
    "voice-operator": ("workflow_skill", True),
    "toolbelt-readiness": ("workflow_skill", True),
    "harness-session-inventory": ("workflow_skill", True),
    "ops-observability-card": ("workflow_skill", True),
    "achievements": ("workflow_skill", True),
    "agent-ops-review": ("workflow_skill", True),
    "agent-debug": ("workflow_skill", True),
    "failure-signal-audit": ("workflow_skill", True),
    "instinct-ledger": ("workflow_skill", True),
    "skill-scout": ("workflow_skill", True),
    "skill-health": ("workflow_skill", True),
    "workflow-learning": ("workflow_skill", True),
}


class RouterContentTests(unittest.TestCase):
    def test_docs_readme_does_not_reference_removed_readme_anchors(self) -> None:
        docs_index = Path("docs/README.md").read_text(encoding="utf-8")
        root_readme = Path("README.md").read_text(encoding="utf-8")
        headings = {
            re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")
            for heading in re.findall(r"^#{1,6}\s+(.+)$", root_readme, flags=re.MULTILINE)
        }

        for anchor in re.findall(r"\]\(\.\./README\.md#([^)]+)\)", docs_index):
            self.assertIn(anchor, headings, f"docs/README.md links to missing README anchor #{anchor}")

    def test_router_documents_best_effort_and_recovery(self) -> None:
        router = next(skill for skill in builtin_skill_templates() if skill.name == "oh-my-hermes")
        references = {
            str(Path(template.skill_name) / template.relative_path): template.content
            for template in builtin_skill_reference_templates()
        }
        workflow_registry = references["oh-my-hermes/references/workflow-registry.md"]
        wrapper_routing = references["oh-my-hermes/references/wrapper-routing.md"]
        progress_reporting = references["oh-my-hermes/references/coding-handoff-progress-reporting.md"]
        maintenance = references["oh-my-hermes/references/operator-maintenance.md"]
        evidence = references["oh-my-hermes/references/evidence-boundaries.md"]

        self.assertLess(len(router.content.encode("utf-8")), 12_000)
        self.assertIn("best-effort Hermes prompt guidance", router.content)
        self.assertIn("does not override Hermes core routing", router.content)
        self.assertIn(router_keyword_summary(), router.content)
        self.assertIn(router_keyword_summary(), WORKSPACE_SNIPPET)
        for skill_name in ROUTER_KEYWORD_SKILLS:
            self.assertIn(f"`{skill_name}`", workflow_registry)
            self.assertIn(f"`{skill_name}`", WORKSPACE_SNIPPET)
        self.assertIn(
            "`workflow-learning`: `workflow-learning`, `workflow learning`, `route-signal`, "
            "`self-improvement store routing`, `store route review`, `memory skill wiki routing`, `learning trace`",
            workflow_registry,
        )
        self.assertIn("OMH Awareness Primer", router.content)
        self.assertIn("Retained knowledge", router.content)
        self.assertIn("`wiki`", router.content)
        self.assertIn("Materials and visual summaries", router.content)
        self.assertIn(
            "`design-quality-gate`, `frontend`, `accessibility-audit`, `visual-qa`, `materials-package`, `img-summary`, `report-package`, `deliverable-package`",
            router.content,
        )
        self.assertNotIn("`frontend`, `accessibility-audit`, `visual-qa`, `materials-package`, `img-summary`, `report-package`, `deliverable-package`, `wiki`", router.content)
        self.assertIn("Coding handoff", router.content)
        self.assertIn("omh chat route", router.content)
        self.assertIn("omh coding delegate", wrapper_routing)
        self.assertIn("deterministic wrapper-side decision layer", router.content)
        self.assertIn("Normal users should talk to Hermes Agent", router.content)
        self.assertIn("Direct Picker Aliases", router.content)
        self.assertIn("show a command preview with exactly one top-level suggestion: `omh`", router.content)
        self.assertIn("omh chat native-command --source discord", router.content)
        self.assertIn("omh_command_fallback_card/v1", router.content)
        self.assertIn("`./omh`, `/omh`, `./skills`, or `/skills`", router.content)
        self.assertIn("coding-handoff-progress-reporting.md", router.content)
        self.assertIn("Active Narration", progress_reporting)
        self.assertIn("observed executor handle", progress_reporting)
        self.assertIn("PR metadata", progress_reporting)
        self.assertIn("merge records", progress_reporting)
        self.assertIn("Keep real skill names unchanged", router.content)
        self.assertIn("chat_response.state.skill_picker.options", router.content)
        self.assertIn("Do not make the user approve `omh list`", router.content)
        self.assertIn("executor_readiness/v1", router.content)
        self.assertIn("retry only after that state changes", wrapper_routing)
        self.assertIn("Hermes-native install paths should converge", router.content)
        self.assertIn("skills.external_dirs", router.content)
        self.assertIn("workflow-registry.md", router.content)
        self.assertIn("harness-registry.md", router.content)
        self.assertIn("wrapper-routing.md", router.content)
        self.assertIn("operator-maintenance.md", router.content)
        self.assertIn("evidence-boundaries.md", router.content)
        self.assertIn("Role Registry", workflow_registry)
        self.assertIn("Installed workflow skill policies live in generated workflow skills", workflow_registry)
        self.assertIn("Hermes should retain routing, web/source research, deep interview, planning, status, and evidence narration", router.content)
        self.assertIn("selected executor/runtime profile", router.content)
        self.assertIn("prepared_not_observed", router.content)
        self.assertIn("operator_maintenance_command", maintenance)
        self.assertIn("run_requested_command", maintenance)
        self.assertIn("compact human summaries", maintenance)
        self.assertIn("Multi-Agent Target Awareness", evidence)
        self.assertIn("omh_target_topology/v1", evidence)
        self.assertIn("single_to_multi", evidence)
        self.assertIn("skills_list", router.content)
        self.assertIn("skill_view", router.content)
        self.assertIn("name collides", router.content)

    def test_context_surfaces_stay_within_compact_budgets(self) -> None:
        from omh.plugin_bundle.omh.tools.capability_tool import OMH_CAPABILITIES_SCHEMA
        from omh.plugin_bundle.omh.tools.chat_tool import OMH_INTERACT_SCHEMA
        from omh.plugin_bundle.omh.tools.context_tool import OMH_CONTEXT_SCHEMA
        from omh.plugin_bundle.omh.tools.evidence_tool import OMH_EVIDENCE_SCHEMA
        from omh.plugin_bundle.omh.tools.hud_tool import OMH_HUD_SCHEMA
        from omh.plugin_bundle.omh.tools.probe_tool import OMH_PROBE_SCHEMA
        from omh.plugin_bundle.omh.tools.recommend_tool import OMH_RECOMMEND_SCHEMA
        from omh.plugin_bundle.omh.tools.role_tool import OMH_ROLE_SCHEMA
        from omh.plugin_bundle.omh.tools.status_tool import OMH_STATUS_SCHEMA
        from omh.wrapper.contract import build_chat_interaction_payload

        router = next(skill for skill in builtin_skill_templates() if skill.name == "oh-my-hermes")
        self.assertLess(len(router.content.encode("utf-8")), 12_000)
        for template in builtin_skill_reference_templates():
            self.assertLess(len(template.content.encode("utf-8")), 24_000, template.relative_path)

        schemas = (
            OMH_CAPABILITIES_SCHEMA,
            OMH_CONTEXT_SCHEMA,
            OMH_EVIDENCE_SCHEMA,
            OMH_HUD_SCHEMA,
            OMH_INTERACT_SCHEMA,
            OMH_PROBE_SCHEMA,
            OMH_RECOMMEND_SCHEMA,
            OMH_ROLE_SCHEMA,
            OMH_STATUS_SCHEMA,
        )
        for schema in schemas:
            with self.subTest(tool=schema["name"]):
                self.assertLessEqual(len(schema["description"]), 260)

        maintenance_payload = build_chat_interaction_payload("omh update", source="discord")
        route_payload = build_chat_interaction_payload("웹서치해서 최신 자료 정리해줘", source="discord")
        context_payload = build_chat_interaction_payload("what can OMH do?", source="discord")
        self.assertLess(len(json.dumps(maintenance_payload, sort_keys=True)), 25_000)
        self.assertLess(len(json.dumps(route_payload, sort_keys=True)), 15_000)
        self.assertLess(len(json.dumps(context_payload, sort_keys=True)), 60_000)

    def test_role_surface_docs_match_catalog_and_avoid_runtime_claims(self) -> None:
        roles_doc = Path("docs/ROLES.md").read_text(encoding="utf-8")

        self.assertEqual(roles_doc, roles_reference_markdown())
        self.assertIn("request-to-handoff", roles_doc)
        self.assertIn("OMH Role Context", roles_doc)
        self.assertIn("OMH workflow-layer responsibility context", roles_doc)
        self.assertIn("Normal users talk to Hermes", roles_doc)
        self.assertIn("roles are responsibility descriptors, not runtime agents", roles_doc.lower())
        for role in role_definitions():
            role_file = Path("roles") / f"{role.id}.md"
            plugin_role_file = Path("src/plugin_bundle/omh/references") / f"role-{role.id}.md"
            text = role_file.read_text(encoding="utf-8")
            self.assertEqual(text, role_file_markdown(role))
            if plugin_role_file.exists():
                self.assertEqual(plugin_role_file.read_text(encoding="utf-8"), role_file_markdown(role))
            self.assertIn("responsibility descriptor, not a runtime agent", text)
            self.assertIn("OMH Role Context", text)
            self.assertIn("prepared guidance only", text)
            self.assertIn(role.evidence_boundary, text)
            self.assertNotIn("secretly", text.lower())
            if role.id == "handoff-guide":
                self.assertIn("not executor/runtime dispatch", text)

    def test_core_skill_set_contains_major_installed_workflows(self) -> None:
        names = {skill.name for skill in builtin_skill_templates()}
        installable_names = {definition.name for definition in installable_skill_definitions()}

        for expected in {
            "ralph",
            "ultragoal",
            "ultrawork",
            "deep-interview",
            "web-research",
            "research-brief",
            "research-department",
            "strategy-brief",
            "meeting-brief",
            "feedback-triage",
            "ops-review",
            "operating-rhythm",
            "report-package",
            "materials-package",
            "img-summary",
            "frontend",
            "accessibility-audit",
            "visual-qa",
            "browser-operator",
            "workspace-file-operator",
            "command-operator",
            "connector-operator",
            "live-info-operator",
            "data-analysis",
            "build-failure-triage",
            "workspace-audit",
            "production-audit",
            "verification-gate",
            "agent-evaluation",
            "rules-distill",
            "codebase-onboarding",
            "codegraph-refresh",
            "skill-scout",
            "skill-health",
            "context-budget-review",
            "security-safety-review",
            "automation-blueprint",
            "reliability-review",
            "idea-to-deploy",
            "cto-loop",
            "deploy-and-monitor",
            "loop",
            "ultraprocess",
            "team",
            "ultraqa",
            "plan",
            "ralplan",
            "code-review",
            "memory-curation-review",
            "deliverable-package",
        }:
            self.assertIn(expected, names)
        self.assertEqual(names, installable_names)

    def test_feature_surface_exposure_projection_is_explicit(self) -> None:
        installable_names = {definition.name for definition in installable_skill_definitions()}
        routable_names = {definition.name for definition in routable_definitions()}
        template_names = {skill.name for skill in builtin_skill_templates()}

        for name, (exposure, installable) in FEATURE_SURFACE_EXPOSURES.items():
            with self.subTest(name=name):
                payload = skill_exposure_payload(name)
                self.assertEqual(payload["exposure"], exposure)
                self.assertEqual(payload["install_visibility"], installable)
                self.assertIn(name, routable_names)
                self.assertEqual(name in installable_names, installable)
                self.assertEqual(name in template_names, installable)
                self.assertIn("preferred_usage", payload)
                if installable:
                    self.assertIn("installable", payload["projections"])
                    self.assertFalse(payload["compatibility_alias"])
                else:
                    self.assertNotIn("installable", payload["projections"])
                    self.assertTrue(payload["compatibility_alias"])

    def test_feature_surface_exposure_contract_is_explicit_for_every_generated_surface(self) -> None:
        feature_surface_names = {
            definition.name
            for definition in builtin_definitions()
            if definition.quality_tier == "workflow-surface-gated"
        }
        generated_surface_exposures = set(FEATURE_SURFACE_EXPOSURES) - {
            "automation-blueprint",
            "design-quality-gate",
            "frontend",
            "accessibility-audit",
            "visual-qa",
            "build-failure-triage",
        }

        self.assertEqual(feature_surface_names, generated_surface_exposures)
        for name in feature_surface_names:
            with self.subTest(name=name):
                self.assertNotEqual(skill_exposure_payload(name)["exposure"], "direct_skill")

    def test_g1_to_g10_use_case_catalog_is_complete_and_boundary_safe(self) -> None:
        payload = list_use_cases()

        self.assertEqual(payload["schema_version"], "omh_use_case_catalog/v1")
        self.assertEqual(payload["count"], 10)
        self.assertEqual([case.goal for case in USE_CASES], [f"G{index}" for index in range(1, 11)])
        installable_names = {skill.name for skill in builtin_skill_templates()}
        routable_names = {definition.name for definition in routable_definitions()}
        harnesses = {harness.name for harness in builtin_harnesses()}
        playbooks = {playbook["id"] for playbook in list_playbooks()["playbooks"]}
        playbook_doc = Path("docs/APPLICATION_CASES.md").read_text(encoding="utf-8")
        readme = Path("README.md").read_text(encoding="utf-8")
        for case in USE_CASES:
            with self.subTest(case=case.id):
                exposure = skill_exposure_payload(case.primary_skill)
                self.assertIn(case.primary_skill, routable_names)
                self.assertEqual(case.primary_skill in installable_names, exposure["install_visibility"])
                self.assertIn(case.harness, harnesses)
                self.assertIn(case.playbook, playbooks)
                self.assertTrue(case.feature_surface.startswith(f"{case.primary_skill} "))
                self.assertTrue(case.direct_skill_invocation.startswith(f"${case.primary_skill} "))
                self.assertIn(case.primary_skill, case.hermes_chat_prompt)
                self.assertNotIn("secret", case.evidence_boundary.lower())
                self.assertNotIn("hidden", case.evidence_boundary.lower())
                self.assertIn(case.goal, playbook_doc)
                self.assertIn(case.primary_skill, playbook_doc)
        self.assertIn("G1-G10", playbook_doc)
        self.assertIn("omh cases list --json", playbook_doc)

    def test_recommendation_policies_are_data_driven_for_business_categories(self) -> None:
        expected = {
            "research": "run_hermes_research",
            "strategy": "prepare_strategy_brief",
            "meeting": "prepare_meeting_brief",
            "triage": "triage_feedback",
            "operations": "prepare_ops_review",
            "delivery": "present_app_delivery_loop",
            "leadership": "run_cto_loop",
            "monitoring": "prepare_deploy_monitor_plan",
            "goal-loop": "assess_loopability",
            "process": "start_ultraprocess",
            "materials": "prepare_material_package",
        }

        for category, next_action in expected.items():
            with self.subTest(category=category):
                self.assertEqual(recommend_module._CATEGORY_POLICIES[category].next_action, next_action)

        self.assertEqual(recommend_module._SKILL_POLICIES["cancel"].next_action, "cancel")
        self.assertEqual(recommend_module._SKILL_POLICIES["operating-rhythm"].next_action, "prepare_operating_record")
        self.assertEqual(recommend_module._SKILL_POLICIES["report-package"].next_action, "prepare_report_package")
        self.assertEqual(recommend_module._SKILL_POLICIES["materials-package"].next_action, "prepare_material_package")
        self.assertEqual(recommend_module._SKILL_POLICIES["img-summary"].next_action, "prepare_visual_prompt_card")
        self.assertEqual(recommend_module._SKILL_POLICIES["frontend"].next_action, "prepare_frontend_handoff")
        self.assertEqual(recommend_module._SKILL_POLICIES["accessibility-audit"].next_action, "prepare_accessibility_audit")
        self.assertIn("WCAG 2.2", recommend_module._SKILL_POLICIES["accessibility-audit"].wrapper_guidance)
        self.assertIn("screen-reader", recommend_module._SKILL_POLICIES["accessibility-audit"].evidence_boundary)
        self.assertEqual(recommend_module._SKILL_POLICIES["visual-qa"].next_action, "prepare_visual_qa")
        self.assertIn("browser_interaction_trace/v1", recommend_module._SKILL_POLICIES["visual-qa"].wrapper_guidance)
        self.assertIn("click-path", recommend_module._SKILL_POLICIES["visual-qa"].evidence_boundary)
        self.assertEqual(recommend_module._SKILL_POLICIES["browser-operator"].next_action, "prepare_browser_operator_card")
        self.assertIn("browser_task_card/v1", recommend_module._SKILL_POLICIES["browser-operator"].wrapper_guidance)
        self.assertIn("credential", recommend_module._SKILL_POLICIES["browser-operator"].evidence_boundary)
        self.assertEqual(
            recommend_module._SKILL_POLICIES["workspace-file-operator"].next_action,
            "prepare_workspace_file_operator_card",
        )
        self.assertIn(
            "workspace_file_task_card/v1",
            recommend_module._SKILL_POLICIES["workspace-file-operator"].wrapper_guidance,
        )
        self.assertIn("destructive", recommend_module._SKILL_POLICIES["workspace-file-operator"].evidence_boundary)
        self.assertEqual(recommend_module._SKILL_POLICIES["workspace-audit"].next_action, "prepare_workspace_audit")
        self.assertEqual(recommend_module._SKILL_POLICIES["production-audit"].next_action, "prepare_production_audit")
        self.assertEqual(
            recommend_module._SKILL_POLICIES["build-failure-triage"].next_action,
            "prepare_build_failure_triage",
        )
        self.assertIn(
            "failure_log_digest/v1",
            recommend_module._SKILL_POLICIES["build-failure-triage"].wrapper_guidance,
        )
        self.assertIn(
            "command rerun",
            recommend_module._SKILL_POLICIES["build-failure-triage"].evidence_boundary,
        )
        self.assertEqual(recommend_module._SKILL_POLICIES["verification-gate"].next_action, "prepare_verification_gate")
        self.assertEqual(recommend_module._SKILL_POLICIES["agent-evaluation"].next_action, "prepare_agent_evaluation")
        self.assertEqual(recommend_module._SKILL_POLICIES["rules-distill"].next_action, "prepare_rules_distillation")
        self.assertEqual(recommend_module._SKILL_POLICIES["codebase-onboarding"].next_action, "prepare_codebase_onboarding")
        self.assertEqual(recommend_module._SKILL_POLICIES["codegraph-refresh"].next_action, "prepare_codegraph_refresh")
        self.assertEqual(recommend_module._SKILL_POLICIES["skill-scout"].next_action, "prepare_skill_scout")
        self.assertIn("skill_scout_recommendation/v1", recommend_module._SKILL_POLICIES["skill-scout"].wrapper_guidance)
        self.assertIn("external source trust", recommend_module._SKILL_POLICIES["skill-scout"].evidence_boundary)
        self.assertEqual(recommend_module._SKILL_POLICIES["skill-health"].next_action, "prepare_skill_health")
        self.assertIn("skill_portfolio_health_dashboard/v1", recommend_module._SKILL_POLICIES["skill-health"].wrapper_guidance)
        self.assertIn("future routing is fixed", recommend_module._SKILL_POLICIES["skill-health"].evidence_boundary)
        self.assertEqual(recommend_module._SKILL_POLICIES["agent-debug"].next_action, "prepare_agent_debug")
        self.assertIn("agent_debug_report/v1", recommend_module._SKILL_POLICIES["agent-debug"].wrapper_guidance)
        self.assertIn("hidden state mutation", recommend_module._SKILL_POLICIES["agent-debug"].evidence_boundary)
        self.assertEqual(
            recommend_module._SKILL_POLICIES["failure-signal-audit"].next_action,
            "prepare_failure_signal_audit",
        )
        self.assertIn(
            "failure_signal_audit_plan/v1",
            recommend_module._SKILL_POLICIES["failure-signal-audit"].wrapper_guidance,
        )
        self.assertIn(
            "hidden failures no longer exist",
            recommend_module._SKILL_POLICIES["failure-signal-audit"].evidence_boundary,
        )
        self.assertEqual(recommend_module._SKILL_POLICIES["instinct-ledger"].next_action, "prepare_instinct_ledger")
        self.assertIn("instinct_ledger_plan/v1", recommend_module._SKILL_POLICIES["instinct-ledger"].wrapper_guidance)
        self.assertIn("global promotion", recommend_module._SKILL_POLICIES["instinct-ledger"].evidence_boundary)
        self.assertEqual(
            recommend_module._SKILL_POLICIES["context-budget-review"].next_action,
            "prepare_context_budget_review",
        )
        self.assertEqual(
            recommend_module._SKILL_POLICIES["security-safety-review"].next_action,
            "prepare_security_safety_review",
        )
        self.assertEqual(recommend_module._SKILL_POLICIES["paper-learning"].next_action, "prepare_paper_learning")
        self.assertEqual(recommend_module._SKILL_POLICIES["source-finder"].next_action, "prepare_source_finder_plan")
        self.assertEqual(recommend_module._SKILL_POLICIES["automation-blueprint"].next_action, "prepare_scheduled_ops_blueprint")
        self.assertEqual(recommend_module._SKILL_POLICIES["reliability-review"].next_action, "prepare_reliability_review")
        self.assertEqual(recommend_module._SKILL_POLICIES["github-event-ops"].next_action, "prepare_github_event_ops_card")
        self.assertEqual(recommend_module._SKILL_POLICIES["agent-board"].next_action, "prepare_agent_board_card")
        self.assertEqual(
            recommend_module._SKILL_POLICIES["memory-curation-review"].next_action,
            "prepare_memory_curation_review",
        )
        self.assertEqual(recommend_module._SKILL_POLICIES["gateway-intent-card"].next_action, "prepare_gateway_intent_card")
        self.assertEqual(
            recommend_module._SKILL_POLICIES["executor-runtime-readiness"].next_action,
            "prepare_executor_runtime_readiness",
        )
        self.assertEqual(recommend_module._SKILL_POLICIES["deliverable-package"].next_action, "prepare_deliverable_package")
        self.assertEqual(recommend_module._SKILL_POLICIES["voice-operator"].next_action, "prepare_voice_operator_card")
        self.assertEqual(recommend_module._SKILL_POLICIES["toolbelt-readiness"].next_action, "prepare_toolbelt_readiness")
        self.assertEqual(
            recommend_module._SKILL_POLICIES["harness-session-inventory"].next_action,
            "prepare_harness_session_inventory",
        )
        self.assertEqual(
            recommend_module._SKILL_POLICIES["ops-observability-card"].next_action,
            "prepare_ops_observability_card",
        )

        for helper in (
            recommend_module._next_action,
            recommend_module._evidence_boundary,
            recommend_module._wrapper_guidance,
        ):
            source = inspect.getsource(helper)
            self.assertIn("_policy_for", source)
            self.assertNotIn("if definition.category", source)

    def test_route_next_action_labels_cover_recommendation_policies(self) -> None:
        policies = (
            *recommend_module._SKILL_POLICIES.values(),
            *recommend_module._CATEGORY_POLICIES.values(),
            *recommend_module._HERMES_ROLE_POLICIES.values(),
            recommend_module._DEFAULT_POLICY,
        )
        actions = sorted({policy.next_action for policy in policies})

        missing = [
            action
            for action in actions
            if next_action_label(action) == action.replace("_", " ")
        ]

        self.assertEqual(missing, [])

    def test_repo_root_tap_skills_match_generated_templates(self) -> None:
        templates = {template.name: template for template in builtin_skill_templates()}
        reference_templates = {
            Path(template.skill_name) / template.relative_path: template for template in builtin_skill_reference_templates()
        }

        for name, template in templates.items():
            path = Path("skills") / name / "SKILL.md"
            self.assertTrue(path.exists(), f"{path} should be present for Hermes skill taps")
            self.assertEqual(path.read_text(encoding="utf-8"), template.content)
        for rel_path, template in reference_templates.items():
            path = Path("skills") / rel_path
            self.assertTrue(path.exists(), f"{path} should be present for Hermes skill tap references")
            self.assertEqual(path.read_text(encoding="utf-8"), template.content)

        self.assertEqual({path.parent.name for path in Path("skills").glob("*/SKILL.md")}, set(templates))
        self.assertEqual(
            {path.relative_to(Path("skills")) for path in Path("skills").glob("*/references/*.md")},
            set(reference_templates),
        )
        installable_surfaces = {name for name, (_, installable) in FEATURE_SURFACE_EXPOSURES.items() if installable}
        self.assertLessEqual(installable_surfaces, set(templates))
        hidden = set(FEATURE_SURFACE_EXPOSURES) - installable_surfaces
        for name in hidden:
            self.assertFalse((Path("skills") / name / "SKILL.md").exists(), f"{name} should stay routable only")

    def test_all_tap_skills_include_subagent_fallback_contract(self) -> None:
        required_fragments = (
            "subagent/delegation features when available",
            "native subagents -> Hermes delegation when available, otherwise sequential lanes",
            "Record observed delegation results",
            "not_observed",
        )
        templates = {template.name: template.content for template in builtin_skill_templates()}
        rendered_files = {
            path.parent.name: path.read_text(encoding="utf-8")
            for path in Path("skills").glob("*/SKILL.md")
        }

        for source, contents in (("template", templates), ("tap", rendered_files)):
            with self.subTest(source=source):
                missing = {
                    name: [fragment for fragment in required_fragments if fragment not in content]
                    for name, content in sorted(contents.items())
                }
                missing = {name: fragments for name, fragments in missing.items() if fragments}
                self.assertEqual(missing, {})

    def test_router_renders_representative_harness_registry(self) -> None:
        references = {
            str(Path(template.skill_name) / template.relative_path): template.content
            for template in builtin_skill_reference_templates()
        }
        harness_registry = references["oh-my-hermes/references/harness-registry.md"]
        harnesses = {harness.name for harness in builtin_harnesses()}

        self.assertEqual(
            {
                "coding-handling",
                "goal-execution",
                "planning",
                "research",
                "research-department",
                "paper-learning",
                "source-finder",
                "business-research",
                "strategy-synthesis",
                "meeting-facilitation",
                "customer-insight-triage",
                "ops-review",
                "operating-rhythm",
                "report-package",
                "materials-package",
                "img-summary",
                "design-quality-gate",
                "frontend",
                "accessibility-audit",
                "visual-qa",
                "browser-operator",
                "workspace-file-operator",
                "command-operator",
                "connector-operator",
                "live-info-operator",
                "content-operator",
                "media-input-operator",
                "data-analysis",
                "build-failure-triage",
                "workspace-audit",
                "production-audit",
                "verification-gate",
                "agent-evaluation",
                "rules-distill",
                "codebase-onboarding",
                "codegraph-refresh",
                "context-budget-review",
                "security-safety-review",
                "scheduled-ops-blueprint",
                "reliability-review",
                "app-delivery-loop",
                "goal-loop",
                "deep-interview",
                "architect",
                "critic",
                "qa-specialist",
                "docs-specialist",
                "github-event-ops",
                "agent-board",
                "memory-curation-review",
                "gateway-intent-card",
                "executor-runtime-readiness",
                "deliverable-package",
                "voice-operator",
                "toolbelt-readiness",
                "harness-session-inventory",
                "ops-observability-card",
                "agent-ops-review",
                "agent-debug",
                "failure-signal-audit",
                "instinct-ledger",
                "skill-scout",
                "skill-health",
                "workflow-learning",
            },
            harnesses,
        )
        self.assertIn("Representative Harnesses", harness_registry)
        self.assertIn("not proof that a separate runtime role exists", harness_registry)
        for harness in harnesses:
            self.assertIn(f"`{harness}`", harness_registry)
        self.assertIn("Tier `", harness_registry)
        self.assertIn("Ladder:", harness_registry)
        self.assertIn("Actions:", harness_registry)
        self.assertIn("Privacy `metadata_only`", harness_registry)
        design_line = next(
            line for line in harness_registry.splitlines() if line.startswith("- `design-quality-gate`:")
        )
        self.assertIn("visual_qa_observed_when_available", design_line)
        self.assertIn("record_visual_qa", design_line)
        self.assertIn("prepare_frontend_handoff", design_line)
        codebase_line = next(
            line for line in harness_registry.splitlines() if line.startswith("- `codebase-onboarding`:")
        )
        self.assertIn("first_task_runway_prepared", codebase_line)
        self.assertIn("record_first_task_runway", codebase_line)
        codegraph_line = next(
            line for line in harness_registry.splitlines() if line.startswith("- `codegraph-refresh`:")
        )
        self.assertIn("codegraph_handoff_prepared_when_task_scoped", codegraph_line)
        self.assertIn("codegraph_handoff_observed_when_available", codegraph_line)
        self.assertIn("record_codegraph_handoff", codegraph_line)
        skill_scout_line = next(
            line for line in harness_registry.splitlines() if line.startswith("- `skill-scout`:")
        )
        self.assertIn("external_candidates_reviewed_when_observed", skill_scout_line)
        self.assertIn("record_skill_candidate", skill_scout_line)
        skill_health_line = next(
            line for line in harness_registry.splitlines() if line.startswith("- `skill-health`:")
        )
        self.assertIn("failure_signals_clustered_when_observed", skill_health_line)
        self.assertIn("record_skill_health_signal", skill_health_line)
        agent_debug_line = next(
            line for line in harness_registry.splitlines() if line.startswith("- `agent-debug`:")
        )
        self.assertIn("failure_state_captured", agent_debug_line)
        self.assertIn("record_agent_failure_capture", agent_debug_line)
        instinct_ledger_line = next(
            line for line in harness_registry.splitlines() if line.startswith("- `instinct-ledger`:")
        )
        self.assertIn("atomic_instinct_candidates_prepared", instinct_ledger_line)
        self.assertIn("record_instinct_candidate", instinct_ledger_line)
        context_budget_line = next(
            line for line in harness_registry.splitlines() if line.startswith("- `context-budget-review`:")
        )
        self.assertIn("overflow_recovery_route_prepared", context_budget_line)
        security_safety_line = next(
            line for line in harness_registry.splitlines() if line.startswith("- `security-safety-review`:")
        )
        self.assertIn("safe_action_policy_recorded", security_safety_line)
        self.assertIn("prepare_remediation_handoff", security_safety_line)
        self.assertNotIn("Inputs:", harness_registry)
        self.assertNotIn("Quality Bar:", harness_registry)

    def test_harness_session_inventory_uses_inventory_specific_completion_copy(self) -> None:
        templates = {template.name: template.content for template in builtin_skill_templates()}
        content = templates["harness-session-inventory"]
        workflow_reference = workflow_reference_markdown()

        self.assertIn("The inventory scope names the harnesses", content)
        self.assertIn("Prepared, observed, missing, stale, and drifted entries", content)
        self.assertIn("The inventory scope names the harnesses", workflow_reference)
        self.assertNotIn("provider metrics", content)
        self.assertNotIn("cost or latency", content)

    def test_research_harness_exposes_source_quality_ladder(self) -> None:
        contract = harness_quality_contract("research")

        self.assertEqual(contract["quality_tier"], "source-gated")
        self.assertIn("source_boundaries_recorded", contract["evidence_ladder"])
        self.assertIn("source_diversity_checked", contract["evidence_ladder"])
        self.assertIn("record_source", contract["wrapper_actions"])
        self.assertTrue(
            any("source plan is not observed source retrieval" in guard for guard in contract["overclaim_guards"])
        )

    def test_research_department_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        playbooks = {playbook["id"]: playbook for playbook in list_playbooks()["playbooks"]}
        patterns = {pattern["id"]: pattern for pattern in orchestration_patterns()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("research-department", definitions)
        self.assertIn("research-department", harnesses)
        self.assertIn("research-department", playbooks)
        self.assertEqual(primary_harness_for_skill("research-department"), "research-department")
        self.assertIn("research_department_workflow", patterns)
        self.assertIn("research-department", patterns["research_department_workflow"]["compatible_skills"])
        self.assertTrue(
            {
                "show_research_department_plan",
                "revise_research_sources",
                "confirm_cadence_delivery_tooling",
                "record_source_observation",
            }.issubset(
                set(VISIBLE_ACTIONS)
            )
        )
        self.assertIn("knowledge-store preference", definitions["research-department"].required_inputs)
        self.assertIn("synthesis-tool preference", definitions["research-department"].required_inputs)
        self.assertIn("knowledge-store preference", harnesses["research-department"].required_inputs)
        self.assertIn("synthesis-tool preference", harnesses["research-department"].required_inputs)
        self.assertIn("source_inbox/v1", harnesses["research-department"].expected_outputs)
        self.assertIn("source_inbox_prepared", harnesses["research-department"].evidence_ladder)
        self.assertIn("briefing_status", playbooks["research-department"]["pipeline"])
        self.assertTrue(
            any(
                "confirm_cadence_delivery_tooling" in stage["wrapper_actions"]
                for stage in inspect_playbook("research-department")["playbook"]["stages"]
            )
        )
        self.assertIn("briefing_status/v1", inspect_playbook("research-department")["playbook"]["stages"][-1]["contract"])
        self.assertIn("research-department", templates)
        self.assertIn("Scout", templates["research-department"].content)

    def test_wiki_contract_surfaces_external_knowledge_connection(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        templates = {template.name: template for template in builtin_skill_templates()}
        wiki = definitions["wiki"]
        content = templates["wiki"].content

        self.assertEqual(wiki.category, "knowledge")
        self.assertEqual(wiki.hermes_role, "memory-keeper")
        self.assertIn("external knowledge store", wiki.triggers)
        self.assertIn("Obsidian", wiki.triggers)
        self.assertTrue(any("destination preference" in item for item in wiki.required_inputs))
        self.assertIn("destination-aware", " ".join(wiki.expected_outputs))
        self.assertIn("Current lane: **Retained knowledge** (`wiki`)", content)
        self.assertIn("observed external write", content)
        self.assertNotIn("Current lane: **Materials and visual summaries** (`wiki`)", content)
        self.assertNotEqual(wiki.category, "materials")

    def test_visual_summary_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("img-summary", definitions)
        self.assertIn("img-summary", harnesses)
        self.assertIn("img-summary", templates)
        self.assertEqual(primary_harness_for_skill("img-summary"), "img-summary")
        self.assertEqual(definitions["img-summary"].category, "materials")
        self.assertEqual(definitions["img-summary"].phase, "visual-prompt-card")
        self.assertIn("visual_prompt_card/v1", definitions["img-summary"].expected_outputs)
        self.assertIn("detected domain_key", definitions["img-summary"].expected_outputs)
        self.assertIn("poster_archetype/v1", definitions["img-summary"].expected_outputs)
        self.assertIn("image_generation_setup/v1 when generator capability is missing", definitions["img-summary"].expected_outputs)
        self.assertIn("image_generation_setup/v1", " ".join(definitions["img-summary"].safety_rules))
        self.assertIn("visual_observation/v1", " ".join(definitions["img-summary"].safety_rules))
        self.assertIn("visual_prompt_card/v1", harnesses["img-summary"].expected_outputs)
        self.assertIn("detected domain_key", harnesses["img-summary"].expected_outputs)
        self.assertIn("poster_archetype/v1", harnesses["img-summary"].expected_outputs)
        self.assertIn("poster_archetype_selected", harnesses["img-summary"].evidence_ladder)
        self.assertIn("generated_image_observed_when_available", harnesses["img-summary"].evidence_ladder)
        self.assertIn("choose_image_generator", harnesses["img-summary"].wrapper_actions)
        self.assertIn("setup_image_generator", harnesses["img-summary"].wrapper_actions)
        self.assertIn("record_visual_delivery", harnesses["img-summary"].wrapper_actions)
        self.assertTrue(
            {
                "show_visual_prompt_card",
                "copy_visual_prompt",
                "revise_visual_card",
                "change_visual_language",
                "choose_image_generator",
                "setup_image_generator",
                "generate_visual_image",
                "record_visual_image",
                "record_visual_qa",
                "record_visual_delivery",
                "show_visual_status",
            }.issubset(set(VISIBLE_ACTIONS))
        )
        self.assertIn("domain-aware image prompt cards", templates["img-summary"].content)
        self.assertIn("poster_archetype/v1", templates["img-summary"].content)
        self.assertIn("Do not call image providers", templates["img-summary"].content)
        self.assertIn("image_generation_setup/v1", templates["img-summary"].content)
        self.assertIn("Preferred harness for this skill: `img-summary`", templates["img-summary"].content)

    def test_design_quality_gate_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("design-quality-gate", definitions)
        self.assertIn("design-quality-gate", harnesses)
        self.assertIn("design-quality-gate", templates)
        self.assertEqual(primary_harness_for_skill("design-quality-gate"), "design-quality-gate")
        self.assertEqual(definitions["design-quality-gate"].category, "materials")
        self.assertEqual(definitions["design-quality-gate"].phase, "design-quality-gate")
        self.assertEqual(definitions["design-quality-gate"].quality_tier, "design-pro-gated")
        self.assertIn("design_quality_gate/v1", definitions["design-quality-gate"].expected_outputs)
        self.assertIn("visual_qa_evidence/v1 when observed", definitions["design-quality-gate"].expected_outputs)
        self.assertIn("surface_quality_matrix/v1", definitions["design-quality-gate"].expected_outputs)
        self.assertIn("comparative_quality_rubric/v1", definitions["design-quality-gate"].expected_outputs)
        self.assertIn("CJK", " ".join(definitions["design-quality-gate"].safety_rules))
        self.assertIn("web: responsive viewport", " ".join(definitions["design-quality-gate"].artifact_expectations))
        self.assertIn("deck/PPT: slide rhythm", " ".join(definitions["design-quality-gate"].artifact_expectations))
        self.assertIn("PDF/poster: print-safe", " ".join(definitions["design-quality-gate"].artifact_expectations))
        self.assertIn("better than ordinary output", " ".join(definitions["design-quality-gate"].quality_bar))
        self.assertIn("design_quality_gate/v1", harnesses["design-quality-gate"].expected_outputs)
        self.assertIn("surface_quality_matrix/v1", harnesses["design-quality-gate"].expected_outputs)
        self.assertIn("reference_packet_selected", harnesses["design-quality-gate"].evidence_ladder)
        self.assertIn("surface_quality_matrix_prepared", harnesses["design-quality-gate"].evidence_ladder)
        self.assertIn("comparative_quality_rubric_prepared", harnesses["design-quality-gate"].evidence_ladder)
        self.assertIn("visual_qa_observed_when_available", harnesses["design-quality-gate"].evidence_ladder)
        self.assertTrue(
            {
                "prepare_design_quality_gate",
                "show_design_quality_gate",
                "record_design_reference",
                "record_content_qa",
                "record_layout_qa",
                "record_surface_quality_matrix",
                "prepare_frontend_handoff",
            }.issubset(set(VISIBLE_ACTIONS))
        )
        self.assertIn("superior design", templates["design-quality-gate"].content)
        self.assertIn("surface_quality_matrix/v1", templates["design-quality-gate"].content)
        self.assertIn("comparative_quality_rubric/v1", templates["design-quality-gate"].content)
        self.assertIn("better than ordinary output", templates["design-quality-gate"].content)
        self.assertIn("visual_qa_evidence/v1", templates["design-quality-gate"].content)
        self.assertIn("Preferred harness for this skill: `design-quality-gate`", templates["design-quality-gate"].content)

    def test_frontend_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("frontend", definitions)
        self.assertIn("frontend", harnesses)
        self.assertIn("frontend", templates)
        self.assertEqual(primary_harness_for_skill("frontend"), "frontend")
        self.assertEqual(definitions["frontend"].category, "materials")
        self.assertEqual(definitions["frontend"].phase, "frontend-design")
        self.assertEqual(definitions["frontend"].quality_tier, "frontend-design-gated")
        self.assertIn("frontend_design_brief/v1", definitions["frontend"].expected_outputs)
        self.assertIn("frontend_initial_generation_contract/v1 when greenfield", definitions["frontend"].expected_outputs)
        self.assertIn("design_system_contract/v1", definitions["frontend"].expected_outputs)
        self.assertIn("design_reference_selection/v1", definitions["frontend"].expected_outputs)
        self.assertIn("frontend_route_state_matrix/v1", definitions["frontend"].expected_outputs)
        self.assertIn("frontend_component_state_inventory/v1", definitions["frontend"].expected_outputs)
        self.assertIn("visual_qa_required/v1", definitions["frontend"].expected_outputs)
        self.assertIn("initial generation contract", " ".join(definitions["frontend"].safety_rules))
        self.assertIn("AI-looking", " ".join(definitions["frontend"].safety_rules))
        self.assertIn("fresh rendered evidence", " ".join(definitions["frontend"].safety_rules))
        self.assertIn("CJK", " ".join(definitions["frontend"].artifact_expectations))
        self.assertIn("frontend_initial_generation_contract/v1 when greenfield", harnesses["frontend"].expected_outputs)
        self.assertIn("design_system_contract/v1", harnesses["frontend"].expected_outputs)
        self.assertIn("frontend_route_state_matrix/v1", harnesses["frontend"].expected_outputs)
        self.assertIn("frontend_component_state_inventory/v1", harnesses["frontend"].expected_outputs)
        self.assertIn("initial_generation_contract_prepared_when_greenfield", harnesses["frontend"].evidence_ladder)
        self.assertIn("design_system_contract_prepared", harnesses["frontend"].evidence_ladder)
        self.assertIn("component_state_inventory_prepared", harnesses["frontend"].evidence_ladder)
        self.assertIn("frontend_implementation_handoff_prepared", harnesses["frontend"].evidence_ladder)
        self.assertIn("visual_qa_observed_when_available", harnesses["frontend"].evidence_ladder)
        self.assertTrue(
            {
                "prepare_frontend_handoff",
                "show_frontend_handoff",
                "record_browser_capture",
                "record_accessibility_check",
                "record_performance_check",
                "prepare_visual_qa",
            }.issubset(set(VISIBLE_ACTIONS))
        )
        self.assertIn("frontend_design_brief/v1", templates["frontend"].content)
        self.assertIn("frontend_initial_generation_contract/v1", templates["frontend"].content)
        self.assertIn("design_system_contract/v1", templates["frontend"].content)
        self.assertIn("frontend_component_state_inventory/v1", templates["frontend"].content)
        self.assertIn("visual_qa_required/v1", templates["frontend"].content)
        self.assertIn("Preferred harness for this skill: `frontend`", templates["frontend"].content)

    def test_accessibility_audit_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("accessibility-audit", definitions)
        self.assertIn("accessibility-audit", harnesses)
        self.assertIn("accessibility-audit", templates)
        self.assertEqual(primary_harness_for_skill("accessibility-audit"), "accessibility-audit")
        self.assertEqual(definitions["accessibility-audit"].category, "accessibility")
        self.assertEqual(definitions["accessibility-audit"].phase, "accessibility-audit")
        self.assertEqual(definitions["accessibility-audit"].quality_tier, "accessibility-audit-gated")
        self.assertIn("accessibility_audit_plan/v1", definitions["accessibility-audit"].expected_outputs)
        self.assertIn("wcag_success_criteria_matrix/v1", definitions["accessibility-audit"].expected_outputs)
        self.assertIn("semantic_structure_review/v1", definitions["accessibility-audit"].expected_outputs)
        self.assertIn("focus_and_keyboard_trace/v1 when observed", definitions["accessibility-audit"].expected_outputs)
        self.assertIn("screen_reader_announcement_map/v1 when observed", definitions["accessibility-audit"].expected_outputs)
        self.assertIn("target_size_and_pointer_review/v1", definitions["accessibility-audit"].expected_outputs)
        self.assertIn("contrast_and_reflow_review/v1", definitions["accessibility-audit"].expected_outputs)
        self.assertIn("WCAG PASS", " ".join(definitions["accessibility-audit"].safety_rules))
        self.assertIn("Automated accessibility scans", " ".join(definitions["accessibility-audit"].safety_rules))
        self.assertIn("screen_reader_announcement_map/v1", " ".join(definitions["accessibility-audit"].artifact_expectations))
        self.assertIn("wcag_success_criteria_matrix/v1", harnesses["accessibility-audit"].expected_outputs)
        self.assertIn("focus_keyboard_trace_recorded_when_available", harnesses["accessibility-audit"].evidence_ladder)
        self.assertIn("screen_reader_map_recorded_when_available", harnesses["accessibility-audit"].evidence_ladder)
        self.assertIn("target_size_pointer_review_prepared", harnesses["accessibility-audit"].evidence_ladder)
        self.assertTrue(
            {
                "prepare_accessibility_audit",
                "show_accessibility_audit",
                "record_accessibility_check",
                "record_focus_flow",
                "record_screen_reader_check",
                "record_wcag_mapping",
                "record_target_size_review",
                "route_to_frontend_or_visual_qa",
            }.issubset(set(VISIBLE_ACTIONS))
        )
        self.assertIn("accessibility_audit_plan/v1", templates["accessibility-audit"].content)
        self.assertIn("wcag_success_criteria_matrix/v1", templates["accessibility-audit"].content)
        self.assertIn("screen_reader_announcement_map/v1", templates["accessibility-audit"].content)
        self.assertIn("Preferred harness for this skill: `accessibility-audit`", templates["accessibility-audit"].content)

    def test_visual_qa_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("visual-qa", definitions)
        self.assertIn("visual-qa", harnesses)
        self.assertIn("visual-qa", templates)
        self.assertEqual(primary_harness_for_skill("visual-qa"), "visual-qa")
        self.assertEqual(definitions["visual-qa"].category, "materials")
        self.assertEqual(definitions["visual-qa"].phase, "visual-qa")
        self.assertEqual(definitions["visual-qa"].quality_tier, "visual-qa-gated")
        self.assertIn("visual_qa_plan/v1", definitions["visual-qa"].expected_outputs)
        self.assertIn("web_visual_qa_package/v1", definitions["visual-qa"].expected_outputs)
        self.assertIn("viewport_state_capture_matrix/v1", definitions["visual-qa"].expected_outputs)
        self.assertIn("message_attachment_projection/v1 for chat attachments", definitions["visual-qa"].expected_outputs)
        self.assertIn("render_capture_manifest/v1 when observed", definitions["visual-qa"].expected_outputs)
        self.assertIn("browser_interaction_trace/v1 when observed", definitions["visual-qa"].expected_outputs)
        self.assertIn("console_network_health/v1 when observed", definitions["visual-qa"].expected_outputs)
        self.assertIn("click_path_state_trace/v1 when observed", definitions["visual-qa"].expected_outputs)
        self.assertIn("accessibility_keyboard_trace/v1 when observed", definitions["visual-qa"].expected_outputs)
        self.assertIn("visual_diff_evidence/v1 when observed", definitions["visual-qa"].expected_outputs)
        self.assertIn("visual_hotspot_review/v1 when observed", definitions["visual-qa"].expected_outputs)
        self.assertIn("motion_interaction_capture/v1 when observed", definitions["visual-qa"].expected_outputs)
        self.assertIn("dual_oracle_visual_review/v1 when observed", definitions["visual-qa"].expected_outputs)
        self.assertIn("browser qa", definitions["visual-qa"].triggers)
        self.assertIn("click path", definitions["visual-qa"].triggers)
        self.assertTrue(set(BROWSER_VISUAL_QA_PHRASES).issubset(set(definitions["visual-qa"].triggers)))
        self.assertIn("fresh rendered evidence", " ".join(definitions["visual-qa"].safety_rules))
        self.assertIn("sample only one good page", " ".join(definitions["visual-qa"].safety_rules))
        self.assertIn("settled frames", " ".join(definitions["visual-qa"].safety_rules))
        self.assertIn("destructive browser journeys", " ".join(definitions["visual-qa"].safety_rules))
        self.assertIn("automated scan output alone", " ".join(definitions["visual-qa"].safety_rules))
        self.assertIn("CJK", " ".join(definitions["visual-qa"].safety_rules))
        self.assertIn("console_network_health/v1", " ".join(definitions["visual-qa"].artifact_expectations))
        self.assertIn("click_path_state_trace/v1", " ".join(definitions["visual-qa"].artifact_expectations))
        self.assertIn("web_visual_qa_package/v1", " ".join(definitions["visual-qa"].artifact_expectations))
        self.assertIn("message_attachment_projection/v1", " ".join(definitions["visual-qa"].artifact_expectations))
        self.assertIn("accessibility_keyboard_trace/v1", " ".join(definitions["visual-qa"].artifact_expectations))
        self.assertIn("dimensionsMatch", " ".join(definitions["visual-qa"].artifact_expectations))
        self.assertIn("PASS unavailable", " ".join(definitions["visual-qa"].artifact_expectations))
        self.assertIn("visual_qa_plan/v1", harnesses["visual-qa"].expected_outputs)
        self.assertIn("web_visual_qa_package/v1", harnesses["visual-qa"].expected_outputs)
        self.assertIn("viewport_state_capture_matrix/v1", harnesses["visual-qa"].expected_outputs)
        self.assertIn("message_attachment_projection/v1 for chat attachments", harnesses["visual-qa"].expected_outputs)
        self.assertIn("render_capture_manifest/v1 when observed", harnesses["visual-qa"].expected_outputs)
        self.assertIn("browser_interaction_trace/v1 when observed", harnesses["visual-qa"].expected_outputs)
        self.assertIn("console_network_health/v1 when observed", harnesses["visual-qa"].expected_outputs)
        self.assertIn("click_path_state_trace/v1 when observed", harnesses["visual-qa"].expected_outputs)
        self.assertIn("accessibility_keyboard_trace/v1 when observed", harnesses["visual-qa"].expected_outputs)
        self.assertIn("visual_hotspot_review/v1 when observed", harnesses["visual-qa"].expected_outputs)
        self.assertIn("motion_interaction_capture/v1 when observed", harnesses["visual-qa"].expected_outputs)
        self.assertIn("viewport_state_capture_matrix_prepared", harnesses["visual-qa"].evidence_ladder)
        self.assertIn("web_visual_qa_package_prepared", harnesses["visual-qa"].evidence_ladder)
        self.assertIn("message_attachment_projection_prepared", harnesses["visual-qa"].evidence_ladder)
        self.assertIn("browser_interaction_trace_observed_when_available", harnesses["visual-qa"].evidence_ladder)
        self.assertIn("console_network_health_observed_when_available", harnesses["visual-qa"].evidence_ladder)
        self.assertIn("click_path_state_trace_observed_when_available", harnesses["visual-qa"].evidence_ladder)
        self.assertIn("accessibility_keyboard_trace_observed_when_available", harnesses["visual-qa"].evidence_ladder)
        self.assertIn("visual_diff_observed_when_available", harnesses["visual-qa"].evidence_ladder)
        self.assertIn("visual_hotspot_review_observed_when_available", harnesses["visual-qa"].evidence_ladder)
        self.assertIn("motion_interaction_capture_observed_when_available", harnesses["visual-qa"].evidence_ladder)
        self.assertIn("visual_qa_verdict_recorded", harnesses["visual-qa"].evidence_ladder)
        self.assertTrue(
            {
                "prepare_visual_qa",
                "show_visual_qa",
                "show_capture_package",
                "prepare_message_attachment_projection",
                "record_browser_capture",
                "record_accessibility_check",
                "record_render_capture",
                "record_visual_diff",
                "record_visual_oracle_review",
                "record_multimodal_review",
                "record_cjk_layout_findings",
                "record_visual_qa_verdict",
            }.issubset(set(VISIBLE_ACTIONS))
        )
        self.assertIn("visual_qa_plan/v1", templates["visual-qa"].content)
        self.assertIn("web_visual_qa_package/v1", templates["visual-qa"].content)
        self.assertIn("viewport_state_capture_matrix/v1", templates["visual-qa"].content)
        self.assertIn("message_attachment_projection/v1", templates["visual-qa"].content)
        self.assertIn("render_capture_manifest/v1", templates["visual-qa"].content)
        self.assertIn("browser_interaction_trace/v1", templates["visual-qa"].content)
        self.assertIn("console_network_health/v1", templates["visual-qa"].content)
        self.assertIn("click_path_state_trace/v1", templates["visual-qa"].content)
        self.assertIn("accessibility_keyboard_trace/v1", templates["visual-qa"].content)
        self.assertIn("visual_hotspot_review/v1", templates["visual-qa"].content)
        self.assertIn("motion_interaction_capture/v1", templates["visual-qa"].content)
        self.assertIn("dual_oracle_visual_review/v1", templates["visual-qa"].content)
        self.assertIn("fresh rendered evidence", templates["visual-qa"].content)
        self.assertIn("Preferred harness for this skill: `visual-qa`", templates["visual-qa"].content)

        route_rules = {str(rule["id"]): rule for rule in _ROUTE_HINT_RULES}
        self.assertTrue(set(BROWSER_VISUAL_QA_PHRASES).issubset(set(route_rules["visual_qa_gate"]["phrases"])))
        self.assertTrue(set(CUSTOMER_SYMPTOM_REPORT_PHRASES).issubset(set(route_rules["customer_signal"]["phrases"])))

    def test_browser_operator_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("browser-operator", definitions)
        self.assertIn("browser-operator", harnesses)
        self.assertIn("browser-operator", templates)
        self.assertEqual(primary_harness_for_skill("browser-operator"), "browser-operator")
        self.assertEqual(definitions["browser-operator"].category, "browser")
        self.assertEqual(definitions["browser-operator"].phase, "browser-task")
        self.assertEqual(definitions["browser-operator"].quality_tier, "workflow-surface-gated")
        self.assertIn("browser_task_card/v1", definitions["browser-operator"].expected_outputs)
        self.assertIn("browser_interaction_scope/v1", definitions["browser-operator"].expected_outputs)
        self.assertIn("browser_auth_boundary/v1", definitions["browser-operator"].expected_outputs)
        self.assertIn("browser_observation_manifest/v1 when observed", definitions["browser-operator"].expected_outputs)
        self.assertIn("browser_confirmation_gate/v1 when destructive", definitions["browser-operator"].expected_outputs)
        self.assertIn("browser task", definitions["browser-operator"].triggers)
        self.assertIn("open url", definitions["browser-operator"].triggers)
        self.assertIn("click page", definitions["browser-operator"].triggers)
        self.assertIn("login page", definitions["browser-operator"].triggers)
        self.assertIn("웹페이지", definitions["browser-operator"].triggers)
        self.assertIn("로그인", definitions["browser-operator"].triggers)
        self.assertIn("credential", " ".join(definitions["browser-operator"].safety_rules).lower())
        self.assertIn("destructive", " ".join(definitions["browser-operator"].safety_rules).lower())
        self.assertIn("browser_task_card/v1", " ".join(definitions["browser-operator"].artifact_expectations))
        self.assertIn("browser_task_card/v1", harnesses["browser-operator"].expected_outputs)
        self.assertIn("browser_interaction_scope/v1", harnesses["browser-operator"].expected_outputs)
        self.assertIn("browser_auth_boundary/v1", harnesses["browser-operator"].expected_outputs)
        self.assertIn("browser_observation_manifest/v1 when observed", harnesses["browser-operator"].expected_outputs)
        self.assertIn("scope_recorded", harnesses["browser-operator"].evidence_ladder)
        self.assertIn("auth_boundary_recorded", harnesses["browser-operator"].evidence_ladder)
        self.assertIn("confirmation_recorded_when_destructive", harnesses["browser-operator"].evidence_ladder)
        self.assertIn("browser_task_card/v1", templates["browser-operator"].content)
        self.assertIn("browser_confirmation_gate/v1", templates["browser-operator"].content)
        self.assertIn("Preferred harness for this skill: `browser-operator`", templates["browser-operator"].content)

        route_rules = {str(rule["id"]): rule for rule in _ROUTE_HINT_RULES}
        self.assertIn("browser_operator", route_rules)
        self.assertIn("browser-operator", route_rules["browser_operator"]["workflow"])
        self.assertIn("open url", route_rules["browser_operator"]["phrases"])

    def test_workspace_file_operator_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("workspace-file-operator", definitions)
        self.assertIn("workspace-file-operator", harnesses)
        self.assertIn("workspace-file-operator", templates)
        self.assertEqual(primary_harness_for_skill("workspace-file-operator"), "workspace-file-operator")
        self.assertEqual(definitions["workspace-file-operator"].category, "filesystem")
        self.assertEqual(definitions["workspace-file-operator"].phase, "file-task")
        self.assertEqual(definitions["workspace-file-operator"].quality_tier, "workflow-surface-gated")
        self.assertIn("workspace_file_task_card/v1", definitions["workspace-file-operator"].expected_outputs)
        self.assertIn("file_operation_scope/v1", definitions["workspace-file-operator"].expected_outputs)
        self.assertIn(
            "file_observation_manifest/v1 when observed",
            definitions["workspace-file-operator"].expected_outputs,
        )
        self.assertIn(
            "file_confirmation_gate/v1 when destructive",
            definitions["workspace-file-operator"].expected_outputs,
        )
        self.assertIn("file operation", definitions["workspace-file-operator"].triggers)
        self.assertIn("list files", definitions["workspace-file-operator"].triggers)
        self.assertIn("move file", definitions["workspace-file-operator"].triggers)
        self.assertIn("delete file", definitions["workspace-file-operator"].triggers)
        self.assertIn("파일 정리", definitions["workspace-file-operator"].triggers)
        self.assertIn("파일 삭제", definitions["workspace-file-operator"].triggers)
        self.assertIn("destructive", " ".join(definitions["workspace-file-operator"].safety_rules).lower())
        self.assertIn("workspace_file_task_card/v1", " ".join(definitions["workspace-file-operator"].artifact_expectations))
        self.assertIn("workspace_file_task_card/v1", harnesses["workspace-file-operator"].expected_outputs)
        self.assertIn("file_operation_scope/v1", harnesses["workspace-file-operator"].expected_outputs)
        self.assertIn(
            "file_observation_manifest/v1 when observed",
            harnesses["workspace-file-operator"].expected_outputs,
        )
        self.assertIn("path_scope_recorded", harnesses["workspace-file-operator"].evidence_ladder)
        self.assertIn("confirmation_recorded_when_destructive", harnesses["workspace-file-operator"].evidence_ladder)
        self.assertIn("workspace_file_task_card/v1", templates["workspace-file-operator"].content)
        self.assertIn("file_confirmation_gate/v1", templates["workspace-file-operator"].content)
        self.assertIn("Preferred harness for this skill: `workspace-file-operator`", templates["workspace-file-operator"].content)

        route_rules = {str(rule["id"]): rule for rule in _ROUTE_HINT_RULES}
        self.assertIn("workspace_file_operator", route_rules)
        self.assertIn("workspace-file-operator", route_rules["workspace_file_operator"]["workflow"])
        self.assertIn("list files", route_rules["workspace_file_operator"]["phrases"])

    def test_data_analysis_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("data-analysis", definitions)
        self.assertIn("data-analysis", harnesses)
        self.assertIn("data-analysis", templates)
        self.assertEqual(primary_harness_for_skill("data-analysis"), "data-analysis")
        self.assertEqual(definitions["data-analysis"].category, "analysis")
        self.assertEqual(definitions["data-analysis"].phase, "data-task")
        self.assertEqual(definitions["data-analysis"].quality_tier, "workflow-surface-gated")
        self.assertIn("data_analysis_task_card/v1", definitions["data-analysis"].expected_outputs)
        self.assertIn("dataset_scope/v1", definitions["data-analysis"].expected_outputs)
        self.assertIn("analysis_method_plan/v1", definitions["data-analysis"].expected_outputs)
        self.assertIn("analysis_result_summary/v1 when observed", definitions["data-analysis"].expected_outputs)
        self.assertIn("csv analysis", definitions["data-analysis"].triggers)
        self.assertIn("json analysis", definitions["data-analysis"].triggers)
        self.assertIn("log analysis", definitions["data-analysis"].triggers)
        self.assertIn("데이터 분석", definitions["data-analysis"].triggers)
        self.assertIn("hallucination", " ".join(definitions["data-analysis"].safety_rules).lower())
        self.assertIn("data_analysis_task_card/v1", " ".join(definitions["data-analysis"].artifact_expectations))
        self.assertIn("data_analysis_task_card/v1", harnesses["data-analysis"].expected_outputs)
        self.assertIn("dataset_scope/v1", harnesses["data-analysis"].expected_outputs)
        self.assertIn("schema_or_columns_recorded", harnesses["data-analysis"].evidence_ladder)
        self.assertIn("analysis_method_selected", harnesses["data-analysis"].evidence_ladder)
        self.assertIn("data_analysis_task_card/v1", templates["data-analysis"].content)
        self.assertIn("analysis_result_summary/v1", templates["data-analysis"].content)
        self.assertIn("Preferred harness for this skill: `data-analysis`", templates["data-analysis"].content)

        route_rules = {str(rule["id"]): rule for rule in _ROUTE_HINT_RULES}
        self.assertIn("data_analysis", route_rules)
        self.assertIn("data-analysis", route_rules["data_analysis"]["workflow"])
        self.assertIn("csv analysis", route_rules["data_analysis"]["phrases"])

    def test_office_file_material_cues_stay_shared_across_surfaces(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        route_rules = {str(rule["id"]): rule for rule in _ROUTE_HINT_RULES}
        office_phrases = set(OFFICE_FILE_MATERIAL_PHRASES)

        self.assertTrue(
            set(OFFICE_FILE_MATERIAL_CATALOG_TRIGGERS).issubset(
                set(definitions["materials-package"].triggers)
            )
        )
        self.assertTrue(office_phrases.issubset(set(policy_module._MATERIALS_PACKAGE_PHRASES)))
        self.assertTrue(
            office_phrases.issubset(set(policy_module._WORKSPACE_FILE_OPERATOR_MATERIALS_BLOCKERS))
        )
        self.assertTrue(office_phrases.issubset(set(route_rules["materials_package"]["phrases"])))

    def test_command_operator_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("command-operator", definitions)
        self.assertIn("command-operator", harnesses)
        self.assertIn("command-operator", templates)
        self.assertEqual(primary_harness_for_skill("command-operator"), "command-operator")
        self.assertEqual(definitions["command-operator"].category, "command")
        self.assertEqual(definitions["command-operator"].phase, "command-task")
        self.assertEqual(definitions["command-operator"].quality_tier, "workflow-surface-gated")
        self.assertIn("command_task_card/v1", definitions["command-operator"].expected_outputs)
        self.assertIn("command_scope/v1", definitions["command-operator"].expected_outputs)
        self.assertIn("command_safety_gate/v1", definitions["command-operator"].expected_outputs)
        self.assertIn("command_result_manifest/v1 when observed", definitions["command-operator"].expected_outputs)
        self.assertIn("run command", definitions["command-operator"].triggers)
        self.assertIn("terminal command", definitions["command-operator"].triggers)
        self.assertIn("터미널 명령", definitions["command-operator"].triggers)
        self.assertIn("destructive", " ".join(definitions["command-operator"].safety_rules).lower())
        self.assertIn("command_task_card/v1", " ".join(definitions["command-operator"].artifact_expectations))
        self.assertIn("command_task_card/v1", harnesses["command-operator"].expected_outputs)
        self.assertIn("command_scope/v1", harnesses["command-operator"].expected_outputs)
        self.assertIn("command_safety_gate/v1", harnesses["command-operator"].expected_outputs)
        self.assertIn("command_text_recorded", harnesses["command-operator"].evidence_ladder)
        self.assertIn("working_directory_recorded", harnesses["command-operator"].evidence_ladder)
        self.assertIn("command_task_card/v1", templates["command-operator"].content)
        self.assertIn("command_result_manifest/v1", templates["command-operator"].content)
        self.assertIn("Preferred harness for this skill: `command-operator`", templates["command-operator"].content)

        route_rules = {str(rule["id"]): rule for rule in _ROUTE_HINT_RULES}
        self.assertIn("command_operator", route_rules)
        self.assertIn("command-operator", route_rules["command_operator"]["workflow"])
        self.assertIn("run command", route_rules["command_operator"]["phrases"])

    def test_connector_operator_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("connector-operator", definitions)
        self.assertIn("connector-operator", harnesses)
        self.assertIn("connector-operator", templates)
        self.assertEqual(primary_harness_for_skill("connector-operator"), "connector-operator")
        self.assertEqual(definitions["connector-operator"].category, "connector")
        self.assertEqual(definitions["connector-operator"].phase, "connector-task")
        self.assertEqual(definitions["connector-operator"].quality_tier, "workflow-surface-gated")
        self.assertIn("connector_task_card/v1", definitions["connector-operator"].expected_outputs)
        self.assertIn("connector_scope/v1", definitions["connector-operator"].expected_outputs)
        self.assertIn("connector_auth_boundary/v1", definitions["connector-operator"].expected_outputs)
        self.assertIn("connector_result_manifest/v1 when observed", definitions["connector-operator"].expected_outputs)
        self.assertIn("send email", definitions["connector-operator"].triggers)
        self.assertIn("linear ticket", definitions["connector-operator"].triggers)
        self.assertIn("notion page", definitions["connector-operator"].triggers)
        self.assertIn("이메일 보내", definitions["connector-operator"].triggers)
        self.assertIn("credential", " ".join(definitions["connector-operator"].safety_rules).lower())
        self.assertIn("connector_task_card/v1", " ".join(definitions["connector-operator"].artifact_expectations))
        self.assertIn("connector_task_card/v1", harnesses["connector-operator"].expected_outputs)
        self.assertIn("connector_scope/v1", harnesses["connector-operator"].expected_outputs)
        self.assertIn("connector_auth_boundary/v1", harnesses["connector-operator"].expected_outputs)
        self.assertIn("connector_action_recorded", harnesses["connector-operator"].evidence_ladder)
        self.assertIn("provider_boundary_recorded", harnesses["connector-operator"].evidence_ladder)
        self.assertIn("connector_task_card/v1", templates["connector-operator"].content)
        self.assertIn("connector_result_manifest/v1", templates["connector-operator"].content)
        self.assertIn("Preferred harness for this skill: `connector-operator`", templates["connector-operator"].content)

        route_rules = {str(rule["id"]): rule for rule in _ROUTE_HINT_RULES}
        self.assertIn("connector_operator", route_rules)
        self.assertIn("connector-operator", route_rules["connector_operator"]["workflow"])
        self.assertIn("send email", route_rules["connector_operator"]["phrases"])

    def test_live_info_operator_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("live-info-operator", definitions)
        self.assertIn("live-info-operator", harnesses)
        self.assertIn("live-info-operator", templates)
        self.assertEqual(primary_harness_for_skill("live-info-operator"), "live-info-operator")
        self.assertEqual(definitions["live-info-operator"].category, "live-info")
        self.assertEqual(definitions["live-info-operator"].phase, "live-info-task")
        self.assertEqual(definitions["live-info-operator"].quality_tier, "workflow-surface-gated")
        self.assertIn("live_info_task_card/v1", definitions["live-info-operator"].expected_outputs)
        self.assertIn("live_info_scope/v1", definitions["live-info-operator"].expected_outputs)
        self.assertIn("freshness_boundary/v1", definitions["live-info-operator"].expected_outputs)
        self.assertIn("live_info_result_manifest/v1 when observed", definitions["live-info-operator"].expected_outputs)
        self.assertIn("weather today", definitions["live-info-operator"].triggers)
        self.assertIn("stock price", definitions["live-info-operator"].triggers)
        self.assertIn("sports score", definitions["live-info-operator"].triggers)
        self.assertIn("오늘 날씨", definitions["live-info-operator"].triggers)
        self.assertIn("provider", " ".join(definitions["live-info-operator"].safety_rules).lower())
        self.assertIn("live_info_task_card/v1", " ".join(definitions["live-info-operator"].artifact_expectations))
        self.assertIn("live_info_task_card/v1", harnesses["live-info-operator"].expected_outputs)
        self.assertIn("live_info_scope/v1", harnesses["live-info-operator"].expected_outputs)
        self.assertIn("freshness_boundary/v1", harnesses["live-info-operator"].expected_outputs)
        self.assertIn("provider_boundary_recorded", harnesses["live-info-operator"].evidence_ladder)
        self.assertIn("freshness_boundary_recorded", harnesses["live-info-operator"].evidence_ladder)
        self.assertIn("live_info_task_card/v1", templates["live-info-operator"].content)
        self.assertIn("live_info_result_manifest/v1", templates["live-info-operator"].content)
        self.assertIn("Preferred harness for this skill: `live-info-operator`", templates["live-info-operator"].content)

        route_rules = {str(rule["id"]): rule for rule in _ROUTE_HINT_RULES}
        self.assertIn("live_info_operator", route_rules)
        self.assertIn("live-info-operator", route_rules["live_info_operator"]["workflow"])
        self.assertIn("weather today", route_rules["live_info_operator"]["phrases"])

    def test_content_operator_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("content-operator", definitions)
        self.assertIn("content-operator", harnesses)
        self.assertIn("content-operator", templates)
        self.assertEqual(primary_harness_for_skill("content-operator"), "content-operator")
        self.assertEqual(definitions["content-operator"].category, "content")
        self.assertEqual(definitions["content-operator"].phase, "content-task")
        self.assertEqual(definitions["content-operator"].quality_tier, "workflow-surface-gated")
        self.assertIn("content_task_card/v1", definitions["content-operator"].expected_outputs)
        self.assertIn("source_scope/v1", definitions["content-operator"].expected_outputs)
        self.assertIn("audience_tone_style/v1", definitions["content-operator"].expected_outputs)
        self.assertIn("content_output_manifest/v1 when observed", definitions["content-operator"].expected_outputs)
        self.assertIn("release notes", definitions["content-operator"].triggers)
        self.assertIn("newsletter draft", definitions["content-operator"].triggers)
        self.assertIn("고객 공지문", definitions["content-operator"].triggers)
        self.assertIn("hallucination", " ".join(definitions["content-operator"].safety_rules).lower())
        self.assertIn("content_task_card/v1", " ".join(definitions["content-operator"].artifact_expectations))
        self.assertIn("content_task_card/v1", harnesses["content-operator"].expected_outputs)
        self.assertIn("source_scope/v1", harnesses["content-operator"].expected_outputs)
        self.assertIn("audience_tone_style/v1", harnesses["content-operator"].expected_outputs)
        self.assertIn("audience_recorded", harnesses["content-operator"].evidence_ladder)
        self.assertIn("content_task_card/v1", templates["content-operator"].content)
        self.assertIn("content_output_manifest/v1", templates["content-operator"].content)
        self.assertIn("Preferred harness for this skill: `content-operator`", templates["content-operator"].content)

        route_rules = {str(rule["id"]): rule for rule in _ROUTE_HINT_RULES}
        self.assertIn("content_operator", route_rules)
        self.assertIn("content-operator", route_rules["content_operator"]["workflow"])
        self.assertIn("release notes", route_rules["content_operator"]["phrases"])

    def test_media_input_operator_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("media-input-operator", definitions)
        self.assertIn("media-input-operator", harnesses)
        self.assertIn("media-input-operator", templates)
        self.assertEqual(primary_harness_for_skill("media-input-operator"), "media-input-operator")
        self.assertEqual(definitions["media-input-operator"].category, "media")
        self.assertEqual(definitions["media-input-operator"].phase, "media-input-task")
        self.assertEqual(definitions["media-input-operator"].quality_tier, "workflow-surface-gated")
        self.assertIn("media_input_task_card/v1", definitions["media-input-operator"].expected_outputs)
        self.assertIn("media_source_scope/v1", definitions["media-input-operator"].expected_outputs)
        self.assertIn("transcript_boundary/v1", definitions["media-input-operator"].expected_outputs)
        self.assertIn("media_result_manifest/v1 when observed", definitions["media-input-operator"].expected_outputs)
        self.assertIn("youtube summary", definitions["media-input-operator"].triggers)
        self.assertIn("transcribe audio", definitions["media-input-operator"].triggers)
        self.assertIn("유튜브 요약", definitions["media-input-operator"].triggers)
        self.assertIn("transcript", " ".join(definitions["media-input-operator"].safety_rules).lower())
        self.assertIn("media_input_task_card/v1", " ".join(definitions["media-input-operator"].artifact_expectations))
        self.assertIn("media_input_task_card/v1", harnesses["media-input-operator"].expected_outputs)
        self.assertIn("media_source_scope/v1", harnesses["media-input-operator"].expected_outputs)
        self.assertIn("transcript_boundary/v1", harnesses["media-input-operator"].expected_outputs)
        self.assertIn("media_source_scope_recorded", harnesses["media-input-operator"].evidence_ladder)
        self.assertIn("transcript_boundary_recorded", harnesses["media-input-operator"].evidence_ladder)
        self.assertIn("media_input_task_card/v1", templates["media-input-operator"].content)
        self.assertIn("media_result_manifest/v1", templates["media-input-operator"].content)
        self.assertIn("Preferred harness for this skill: `media-input-operator`", templates["media-input-operator"].content)

        route_rules = {str(rule["id"]): rule for rule in _ROUTE_HINT_RULES}
        self.assertIn("media_input_operator", route_rules)
        self.assertIn("media-input-operator", route_rules["media_input_operator"]["workflow"])
        self.assertIn("youtube summary", route_rules["media_input_operator"]["phrases"])

    def test_build_failure_triage_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("build-failure-triage", definitions)
        self.assertIn("build-failure-triage", harnesses)
        self.assertIn("build-failure-triage", templates)
        self.assertEqual(primary_harness_for_skill("build-failure-triage"), "build-failure-triage")
        self.assertEqual(definitions["build-failure-triage"].category, "verification")
        self.assertEqual(definitions["build-failure-triage"].phase, "build-failure-triage")
        self.assertEqual(definitions["build-failure-triage"].quality_tier, "build-failure-triage-gated")
        self.assertIn("build_failure_triage_plan/v1", definitions["build-failure-triage"].expected_outputs)
        self.assertIn("failure_log_digest/v1", definitions["build-failure-triage"].expected_outputs)
        self.assertIn("failure_cluster_matrix/v1", definitions["build-failure-triage"].expected_outputs)
        self.assertIn("root_cause_hypothesis_set/v1", definitions["build-failure-triage"].expected_outputs)
        self.assertIn("minimal_fix_handoff/v1 when remediation is requested", definitions["build-failure-triage"].expected_outputs)
        self.assertIn("build_failure_triage_verdict/v1", definitions["build-failure-triage"].expected_outputs)
        self.assertIn("Do not claim the build", " ".join(definitions["build-failure-triage"].safety_rules))
        self.assertIn("rerun_plan/v1", " ".join(definitions["build-failure-triage"].artifact_expectations))
        self.assertIn("failure_log_digest/v1", harnesses["build-failure-triage"].expected_outputs)
        self.assertIn("failure_cluster_matrix_prepared", harnesses["build-failure-triage"].evidence_ladder)
        self.assertIn("root_cause_hypotheses_ranked", harnesses["build-failure-triage"].evidence_ladder)
        self.assertTrue(
            {
                "prepare_build_failure_triage",
                "show_build_failure_triage",
                "record_failure_log",
                "record_failure_cluster",
                "record_root_cause_hypothesis",
                "prepare_minimal_fix_handoff",
                "record_rerun_plan",
                "route_to_verification_gate",
            }.issubset(set(VISIBLE_ACTIONS))
        )
        self.assertIn("failure_log_digest/v1", templates["build-failure-triage"].content)
        self.assertIn("failure_cluster_matrix/v1", templates["build-failure-triage"].content)
        self.assertIn("minimal_fix_handoff/v1", templates["build-failure-triage"].content)
        self.assertIn("Preferred harness for this skill: `build-failure-triage`", templates["build-failure-triage"].content)

        route_rules = {str(rule["id"]): rule for rule in _ROUTE_HINT_RULES}
        self.assertEqual(route_rules["build_failure_triage"]["workflow"], "build-failure-triage")
        self.assertEqual(route_rules["build_failure_triage"]["next_action"], "prepare_build_failure_triage")
        self.assertIn("CI pass", route_rules["build_failure_triage"]["not_evidence_yet"])

    def test_ecc_inspired_operator_skill_contracts_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}
        expected = {
            "workspace-audit": {
                "category": "operations",
                "phase": "workspace-audit",
                "quality_tier": "workspace-audit-gated",
                "output": "surface_inventory/v1",
                "ladder": "capability_gap_matrix_prepared",
                "action": "prepare_workspace_audit",
                "template": "config_security_findings/v1",
            },
            "production-audit": {
                "category": "review",
                "phase": "production-readiness",
                "quality_tier": "production-readiness-gated",
                "output": "readiness_matrix/v1",
                "ladder": "release_gate_verdict_recorded",
                "action": "prepare_production_audit",
                "template": "rollback_and_monitoring_plan/v1",
            },
            "verification-gate": {
                "category": "verification",
                "phase": "verification-gate",
                "quality_tier": "verification-gated",
                "output": "verification_matrix/v1",
                "ladder": "claim_verdict_recorded",
                "action": "prepare_verification_gate",
                "template": "observed_check_results/v1",
            },
            "build-failure-triage": {
                "category": "verification",
                "phase": "build-failure-triage",
                "quality_tier": "build-failure-triage-gated",
                "output": "failure_log_digest/v1",
                "ladder": "failure_cluster_matrix_prepared",
                "action": "prepare_build_failure_triage",
                "template": "minimal_fix_handoff/v1",
            },
            "agent-evaluation": {
                "category": "operations",
                "phase": "agent-evaluation",
                "quality_tier": "agent-eval-gated",
                "output": "task_benchmark_set/v1",
                "ladder": "selection_recommendation_recorded",
                "action": "prepare_agent_evaluation",
                "template": "run_result_matrix/v1",
            },
            "rules-distill": {
                "category": "knowledge",
                "phase": "rules-distillation",
                "quality_tier": "rules-distillation-gated",
                "output": "principle_candidate_set/v1",
                "ladder": "review_state_recorded",
                "action": "prepare_rules_distillation",
                "template": "duplication_conflict_report/v1",
            },
            "codebase-onboarding": {
                "category": "planning",
                "phase": "codebase-onboarding",
                "quality_tier": "onboarding-gated",
                "output": "repo_map/v1",
                "ladder": "first_task_runway_prepared",
                "action": "prepare_codebase_onboarding",
                "template": "first_task_runway/v1",
            },
            "codegraph-refresh": {
                "category": "planning",
                "phase": "codegraph-refresh",
                "quality_tier": "codegraph-gated",
                "output": "codegraph_command_plan/v1",
                "ladder": "codegraph_handoff_observed_when_available",
                "action": "prepare_codegraph_refresh",
                "template": ".omh/codegraph/codegraph.json",
            },
            "skill-scout": {
                "category": "operations",
                "phase": "skill-scout",
                "quality_tier": "workflow-surface-gated",
                "output": "skill_scout_recommendation/v1",
                "ladder": "external_candidates_reviewed_when_observed",
                "action": "prepare_skill_scout",
                "template": "skill_adoption_decision_matrix/v1",
            },
            "agent-debug": {
                "category": "operations",
                "phase": "agent-debug",
                "quality_tier": "workflow-surface-gated",
                "output": "agent_debug_report/v1",
                "ladder": "failure_state_captured",
                "action": "prepare_agent_debug",
                "template": "contained_recovery_action/v1",
            },
            "failure-signal-audit": {
                "category": "review",
                "phase": "failure-signal-audit",
                "quality_tier": "workflow-surface-gated",
                "output": "failure_signal_audit_plan/v1",
                "ladder": "fallback_risk_matrix_prepared",
                "action": "prepare_failure_signal_audit",
                "template": "false_green_status_review/v1",
            },
            "accessibility-audit": {
                "category": "accessibility",
                "phase": "accessibility-audit",
                "quality_tier": "accessibility-audit-gated",
                "output": "wcag_success_criteria_matrix/v1",
                "ladder": "focus_keyboard_trace_recorded_when_available",
                "action": "prepare_accessibility_audit",
                "template": "screen_reader_announcement_map/v1",
            },
            "instinct-ledger": {
                "category": "optimization",
                "phase": "instinct-ledger",
                "quality_tier": "workflow-surface-gated",
                "output": "instinct_ledger_plan/v1",
                "ladder": "atomic_instinct_candidates_prepared",
                "action": "prepare_instinct_ledger",
                "template": "instinct_candidate/v1",
            },
            "context-budget-review": {
                "category": "observability",
                "phase": "context-budget-review",
                "quality_tier": "context-budget-gated",
                "output": "must_keep_context_pack/v1",
                "ladder": "overflow_recovery_route_prepared",
                "action": "prepare_context_budget_review",
                "template": "budget_risk_register/v1",
            },
            "security-safety-review": {
                "category": "review",
                "phase": "security-safety-review",
                "quality_tier": "security-safety-gated",
                "output": "threat_surface_map/v1",
                "ladder": "safe_action_policy_recorded",
                "action": "prepare_security_safety_review",
                "template": "prompt_injection_risk_review/v1",
            },
        }

        for name, contract in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, definitions)
                self.assertIn(name, harnesses)
                self.assertIn(name, templates)
                self.assertEqual(primary_harness_for_skill(name), name)
                self.assertEqual(definitions[name].category, contract["category"])
                self.assertEqual(definitions[name].phase, contract["phase"])
                self.assertEqual(definitions[name].quality_tier, contract["quality_tier"])
                self.assertIn(contract["output"], definitions[name].expected_outputs)
                self.assertIn(contract["output"], harnesses[name].expected_outputs)
                self.assertIn(contract["ladder"], harnesses[name].evidence_ladder)
                self.assertIn(contract["action"], harnesses[name].wrapper_actions)
                self.assertIn(contract["action"], VISIBLE_ACTIONS)
                self.assertIn(contract["template"], templates[name].content)
                self.assertIn(f"Preferred harness for this skill: `{name}`", templates[name].content)
                self.assertIn("not_observed", templates[name].content)

    def test_paper_learning_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("paper-learning", definitions)
        self.assertIn("paper-learning", harnesses)
        self.assertIn("paper-learning", templates)
        self.assertEqual(primary_harness_for_skill("paper-learning"), "paper-learning")
        self.assertEqual(definitions["paper-learning"].category, "research")
        self.assertEqual(definitions["paper-learning"].phase, "paper-learning")
        self.assertIn("paper_learning_card/v1", definitions["paper-learning"].expected_outputs)
        self.assertIn("source_state boundary", definitions["paper-learning"].expected_outputs)
        self.assertIn("coverage ledger", definitions["paper-learning"].expected_outputs)
        self.assertIn("metadata_only", " ".join(definitions["paper-learning"].quality_bar))
        self.assertIn("file_text_extraction_observed", " ".join(definitions["paper-learning"].quality_bar))
        self.assertIn("full_pdf_extraction", " ".join(definitions["paper-learning"].final_checklist))
        self.assertIn("paper_learning_card/v1", harnesses["paper-learning"].expected_outputs)
        self.assertIn("coverage_ledger_prepared", harnesses["paper-learning"].evidence_ladder)
        self.assertIn("show_coverage_ledger", harnesses["paper-learning"].wrapper_actions)
        self.assertIn("record_file_text_extraction_observed", harnesses["paper-learning"].wrapper_actions)
        self.assertTrue(
            {
                "prepare_paper_learning",
                "choose_explanation_level",
                "show_paper_source_requirements",
                "record_paper_metadata",
                "record_paper_excerpt_observed",
                "record_file_text_extraction_observed",
                "show_paper_learning",
                "continue_next_section",
                "revise_explanation_level",
                "show_coverage_ledger",
                "record_user_review",
            }.issubset(set(VISIBLE_ACTIONS))
        )
        self.assertIn("paper_learning_card/v1", templates["paper-learning"].content)
        self.assertIn("coverage ledger", templates["paper-learning"].content)
        self.assertIn("Preferred harness for this skill: `paper-learning`", templates["paper-learning"].content)

    def test_source_finder_contract_surfaces_stay_in_sync(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        harnesses = {harness.name: harness for harness in builtin_harnesses()}
        templates = {template.name: template for template in builtin_skill_templates()}

        self.assertIn("source-finder", definitions)
        self.assertIn("source-finder", harnesses)
        self.assertIn("source-finder", templates)
        self.assertEqual(primary_harness_for_skill("source-finder"), "source-finder")
        self.assertEqual(definitions["source-finder"].category, "research")
        self.assertEqual(definitions["source-finder"].phase, "source-acquisition")
        self.assertIn("source_finder_plan/v1", definitions["source-finder"].expected_outputs)
        self.assertIn("source_candidate_set/v1", definitions["source-finder"].expected_outputs)
        self.assertIn("source_acquisition_status/v1", harnesses["source-finder"].expected_outputs)
        self.assertIn("candidate_set_prepared", harnesses["source-finder"].evidence_ladder)
        self.assertIn("record_source_link_observed", harnesses["source-finder"].wrapper_actions)
        self.assertIn("route_to_downstream_workflow", harnesses["source-finder"].wrapper_actions)
        self.assertTrue(
            {
                "prepare_source_finder_plan",
                "show_source_candidates",
                "record_source_candidate",
                "record_source_link_observed",
                "record_download_observed",
                "record_file_hash",
                "record_text_extraction_observed",
                "record_license_check",
                "choose_source",
                "route_to_downstream_workflow",
                "show_acquisition_status",
            }.issubset(set(VISIBLE_ACTIONS))
        )
        self.assertIn("source_finder_plan/v1", templates["source-finder"].content)
        self.assertIn("source_candidate_set/v1", templates["source-finder"].content)
        self.assertIn("Preferred harness for this skill: `source-finder`", templates["source-finder"].content)

    def test_catalog_definitions_expose_required_metadata_fields(self) -> None:
        for definition in builtin_definitions():
            self.assertTrue(definition.description.startswith("[omh] "), definition.name)
            self.assertTrue(definition.category, definition.name)
            self.assertTrue(definition.phase, definition.name)
            self.assertTrue(definition.quality_tier, definition.name)
            self.assertGreaterEqual(len(definition.quality_bar), 1, definition.name)
            self.assertGreaterEqual(len(definition.required_inputs), 1, definition.name)
            self.assertGreaterEqual(len(definition.expected_outputs), 1, definition.name)
            self.assertGreaterEqual(len(definition.artifact_expectations), 1, definition.name)
            self.assertGreaterEqual(len(definition.safety_rules), 1, definition.name)
            self.assertTrue(definition.why_this_exists, definition.name)
            self.assertGreaterEqual(len(definition.do_not_use_when), 1, definition.name)
            self.assertIsNotNone(definition.good_example, definition.name)
            self.assertIsNotNone(definition.bad_example, definition.name)
            self.assertTrue(definition.good_example.prompt, definition.name)
            self.assertTrue(definition.good_example.expected, definition.name)
            self.assertTrue(definition.good_example.why, definition.name)
            self.assertTrue(definition.bad_example.prompt, definition.name)
            self.assertTrue(definition.bad_example.expected, definition.name)
            self.assertTrue(definition.bad_example.why, definition.name)
            self.assertTrue(definition.hermes_role, definition.name)
            self.assertIn(definition.delegation_boundary, {"default", "retained", "retained-catalog-intent"}, definition.name)
            self.assertTrue(definition.handoff_policy, definition.name)
        for template in builtin_skill_templates():
            self.assertIn("description: [omh] ", template.content.split("---", 2)[1], template.name)

    def test_default_examples_are_concrete_and_trigger_safe(self) -> None:
        definition = SkillDefinition(
            "empty-trigger-safe",
            "Example skill for empty trigger safety.",
            (),
            "Use when validating catalog defaults.",
        )

        self.assertIn("empty-trigger-safe:", definition.good_example.prompt)
        self.assertIn("empty-trigger-safe:", definition.bad_example.prompt)

        combined = workflow_reference_markdown() + "\n".join(
            template.content for template in builtin_skill_templates()
        )
        self.assertNotIn("<task that matches this workflow>", combined)
        self.assertNotIn("<unrelated or unaccepted work>", combined)

    def test_flagship_skills_render_quality_rubric_examples(self) -> None:
        templates = {template.name: template.content for template in builtin_skill_templates()}
        definitions = {definition.name: definition for definition in builtin_definitions()}

        for name in FLAGSHIP_SKILLS:
            with self.subTest(name=name):
                self.assertIn(name, templates)
                definition = definitions[name]
                content = templates[name]

                self.assertIn("## Why This Exists", content)
                self.assertIn("## Do Not Use When", content)
                self.assertIn("## Examples", content)
                self.assertIn("Good example:", content)
                self.assertIn("Bad example:", content)
                self.assertIn(definition.why_this_exists, content)
                for rule in definition.do_not_use_when:
                    self.assertIn(rule, content)
                self.assertIn(definition.good_example.prompt, content)
                self.assertIn(definition.good_example.expected, content)
                self.assertIn(definition.good_example.why, content)
                self.assertIn(definition.bad_example.prompt, content)
                self.assertIn(definition.bad_example.expected, content)
                self.assertIn(definition.bad_example.why, content)
                self.assertNotIn("<task that matches this workflow>", definition.good_example.prompt)
                self.assertNotIn("<unrelated or unaccepted work>", definition.bad_example.prompt)

    def test_catalog_marks_retained_and_codex_handoff_skills(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        retained = set(retained_delegation_skill_names())
        catalog_intent_retained = set(catalog_intent_delegation_skill_names())

        self.assertEqual(definitions["deep-interview"].hermes_role, "planner")
        self.assertEqual(definitions["web-research"].hermes_role, "researcher")
        self.assertEqual(definitions["ralplan"].hermes_role, "planner")
        self.assertEqual(definitions["ultraprocess"].hermes_role, "handoff-guide")
        self.assertEqual(
            definitions["ultraprocess"].description,
            "[omh] Ultra Process - Research - Ralplan - Ultragoal - Code Review - Sync Circle: one PR-ready delivery cycle.",
        )
        self.assertEqual(definitions["ultrawork"].hermes_role, "handoff-guide")
        self.assertEqual(definitions["ai-slop-cleaner"].hermes_role, "handoff-guide")
        self.assertIn("ulw", definitions["ultrawork"].triggers)
        self.assertIn("$ulw", definitions["ultrawork"].triggers)
        self.assertIn("selected runtime", definitions["ultrawork"].handoff_policy)
        self.assertIn("selected executor/runtime handoff", definitions["ultraprocess"].handoff_policy)
        self.assertTrue(any("source or web evidence" in item for item in definitions["ralplan"].required_inputs))
        self.assertIn("verification commands", definitions["ralplan"].expected_outputs)
        self.assertTrue(any("rejected options" in item for item in definitions["ralplan"].quality_bar))
        self.assertTrue(any("prepared_not_observed" in item for item in definitions["ralplan"].final_checklist))
        self.assertEqual(primary_harness_for_skill("web-research"), "research")
        self.assertEqual(primary_harness_for_skill("research-brief"), "business-research")
        self.assertEqual(primary_harness_for_skill("research-department"), "research-department")
        self.assertEqual(primary_harness_for_skill("strategy-brief"), "strategy-synthesis")
        self.assertEqual(primary_harness_for_skill("meeting-brief"), "meeting-facilitation")
        self.assertEqual(primary_harness_for_skill("feedback-triage"), "customer-insight-triage")
        self.assertEqual(primary_harness_for_skill("ops-review"), "ops-review")
        self.assertEqual(primary_harness_for_skill("operating-rhythm"), "operating-rhythm")
        self.assertEqual(primary_harness_for_skill("report-package"), "report-package")
        self.assertEqual(primary_harness_for_skill("materials-package"), "materials-package")
        self.assertEqual(primary_harness_for_skill("img-summary"), "img-summary")
        self.assertEqual(primary_harness_for_skill("source-finder"), "source-finder")
        self.assertEqual(primary_harness_for_skill("paper-learning"), "paper-learning")
        self.assertEqual(primary_harness_for_skill("reliability-review"), "reliability-review")
        self.assertEqual(primary_harness_for_skill("idea-to-deploy"), "app-delivery-loop")
        self.assertEqual(primary_harness_for_skill("cto-loop"), "app-delivery-loop")
        self.assertEqual(primary_harness_for_skill("deploy-and-monitor"), "app-delivery-loop")
        self.assertEqual(primary_harness_for_skill("loop"), "goal-loop")
        self.assertEqual(primary_harness_for_skill("ultraprocess"), "goal-execution")
        self.assertEqual(primary_harness_for_skill("best-practice-research"), "research")
        self.assertEqual(primary_harness_for_skill("autoresearch-goal"), "research")
        self.assertIn("deep-interview", retained)
        self.assertIn("web-research", retained)
        self.assertIn("ultraqa", retained)
        self.assertIn("skill", retained)
        self.assertIn("wiki", retained)
        self.assertTrue(
            {
                "research-brief",
                "research-department",
                "strategy-brief",
                "meeting-brief",
                "feedback-triage",
                "ops-review",
                "operating-rhythm",
                "report-package",
                "materials-package",
                "img-summary",
                "source-finder",
                "paper-learning",
                "reliability-review",
                "idea-to-deploy",
                "cto-loop",
                "deploy-and-monitor",
                "loop",
                "ultraprocess",
            }.issubset(catalog_intent_retained)
        )

    def test_skill_definition_canonicalizes_legacy_role_names(self) -> None:
        cases = {
            "research-lead": "researcher",
            "planning-lead": "planner",
            "retained-cognition": "planner",
            "retained-operator": "operator",
            "retained-knowledge": "memory-keeper",
            "coding-handoff": "handoff-guide",
            "runtime-handoff-guidance": "handoff-guide",
            "codex-handoff-guidance": "handoff-guide",
            "hybrid-measurement": "tracker",
            "review-gate": "reviewer",
            "hybrid-review": "reviewer",
            "hybrid-verification": "reviewer",
        }
        for legacy_role, canonical_role in cases.items():
            with self.subTest(legacy_role=legacy_role):
                definition = SkillDefinition(
                    name=f"fixture-{legacy_role}",
                    description="Fixture skill.",
                    triggers=("fixture",),
                    use_when="Testing legacy role canonicalization.",
                    category="planning" if legacy_role == "retained-cognition" else "operations",
                    hermes_role=legacy_role,
                )
                self.assertEqual(definition.hermes_role, canonical_role)

    def test_workflow_skills_refer_to_harness_discipline(self) -> None:
        skills = {skill.name: skill for skill in builtin_skill_templates()}

        self.assertIn("Harness Discipline", skills["ultragoal"].content)
        self.assertIn("Catalog Metadata", skills["ultragoal"].content)
        self.assertIn("Category: `execution`", skills["ultragoal"].content)
        self.assertIn("Phase: `durable-goals`", skills["ultragoal"].content)
        self.assertIn("Hermes role: `handoff-guide`", skills["ultragoal"].content)
        self.assertIn("Handoff policy:", skills["ultragoal"].content)
        self.assertIn("Runtime Evidence", skills["ultragoal"].content)
        self.assertIn("OMH Context Rail", skills["ultragoal"].content)
        self.assertIn("part of OMH's Hermes workflow layer", skills["ultragoal"].content)
        self.assertIn("Hermes-native workflow pack", skills["ultragoal"].content)
        self.assertIn("Completion Checklist", skills["ultragoal"].content)
        self.assertIn("Recovery Notes", skills["ultragoal"].content)
        self.assertIn("Current lane: **Intent -> plan**", skills["ultragoal"].content)
        self.assertIn("hand back to `oh-my-hermes`", skills["ultragoal"].content)
        self.assertIn("Cross-skill context", skills["ultragoal"].content)
        self.assertIn("Every generated workflow skill", skills["ultragoal"].content)
        self.assertIn("Prepared OMH routing", skills["ultragoal"].content)
        self.assertIn("Long-running or background executor milestones report observed handles", skills["ultragoal"].content)
        self.assertIn("hermes_coding_harness/v1", skills["ultragoal"].content)
        self.assertIn("builder, verifier, reviewer, docs, and PR lanes", skills["ultragoal"].content)
        self.assertIn("PR head SHA", skills["ultragoal"].content)
        self.assertIn("omh_target_topology/v1", skills["ultragoal"].content)
        self.assertIn("active_agent_count", skills["ultragoal"].content)
        self.assertIn("omh runtime record --skill ultragoal --harness goal-execution --status started", skills["ultragoal"].content)
        self.assertIn("goal_completion_gate/v1", skills["ultragoal"].content)
        self.assertIn("inspect .omh/goals", skills["ultragoal"].content)
        self.assertIn("Current lane: **Materials and visual summaries**", skills["img-summary"].content)
        self.assertIn("Current lane: **Research and company ops**", skills["web-research"].content)
        self.assertIn("loop_cycle/v1", skills["loop"].content)
        self.assertIn("permission profile", skills["loop"].content)
        self.assertIn("verification_plan", skills["loop"].content)
        self.assertIn("verification_gap", skills["loop"].content)
        self.assertIn("test as stop signal", skills["loop"].content)
        self.assertIn("queued loop ticks", skills["loop"].content)
        self.assertIn("failure_mode_summary", skills["loop"].content)
        self.assertIn("direct `loop`, `./loop`, `$loop`", skills["loop"].content)
        self.assertIn("interviewer, planner, researcher, builder, reviewer, and loop controller", skills["loop"].content)
        self.assertIn("memory/skill/wiki/failure-retrospective/automation", skills["workflow-learning"].content)
        self.assertIn("self-improvement store routing", skills["workflow-learning"].content)
        self.assertIn("project/global promotion", skills["instinct-ledger"].content)
        self.assertIn("instinct_candidate/v1", skills["instinct-ledger"].content)
        workflow_docs = workflow_reference_markdown()
        self.assertIn("self_improvement_store_routing/v1", workflow_docs)
        self.assertIn("self_improvement_store_route_record/v1", workflow_docs)
        self.assertIn("store_destination_reviewed", workflow_docs)
        self.assertIn("review_self_improvement_store_route", workflow_docs)
        self.assertIn("change_store_route_destination", workflow_docs)
        self.assertIn("When Hermes owns coding, use `hermes_coding_harness/v1` docs lane state", workflow_docs)
        self.assertIn("single-cycle-plan-to-pr", skills["ultraprocess"].content)
        self.assertIn("Do not continue into a repeated feedback loop", skills["ultraprocess"].content)
        self.assertIn("code-review gate", skills["ultraprocess"].content)
        self.assertIn("docs-specialist", skills["ultraprocess"].content)
        self.assertIn("one delivery cycle", skills["ultraprocess"].content)
        self.assertIn("lane owner, next action, and missing evidence", skills["ultraprocess"].content)
        self.assertIn("PR readiness", skills["ultraprocess"].content)
        self.assertIn("Prefer richer evidence and clearer stop conditions", skills["code-review"].content)
        self.assertIn("Findings come first", skills["code-review"].content)
        self.assertIn("independent review evidence", skills["code-review"].content)
        self.assertIn("hermes_coding_harness/v1", skills["code-review"].content)
        self.assertIn("non-disjoint", skills["ultrawork"].content)
        self.assertIn("Worker ACK", skills["ultrawork"].content)
        self.assertIn("hermes_coding_harness/v1", skills["ultrawork"].content)
        self.assertIn("Blocking issues and warnings", skills["doctor"].content)
        self.assertIn("plugin register smoke", skills["doctor"].content)

        for name, skill in skills.items():
            if name == "oh-my-hermes":
                continue
            with self.subTest(skill=name):
                self.assertIn("OMH Context Rail", skill.content)
                self.assertIn("not a standalone executor", skill.content)
                self.assertIn("Product context:", skill.content)
                self.assertIn("Cross-skill context:", skill.content)
                self.assertIn("Coverage:", skill.content)
                self.assertIn("Completion Checklist", skill.content)
                self.assertIn("Recovery Notes", skill.content)

    def test_installable_skills_expose_completion_and_recovery_guidance(self) -> None:
        for definition in installable_skill_definitions():
            with self.subTest(skill=definition.name):
                self.assertGreaterEqual(len(definition.final_checklist), 2)
                self.assertGreaterEqual(len(definition.recovery_notes), 2)
                self.assertTrue(all(item.strip() for item in definition.final_checklist))
                self.assertTrue(all(item.strip() for item in definition.recovery_notes))

    def test_default_completion_and_recovery_guidance_varies_by_lane(self) -> None:
        definitions = {definition.name: definition for definition in installable_skill_definitions()}
        completion_sets = {tuple(definition.final_checklist) for definition in definitions.values()}
        recovery_sets = {tuple(definition.recovery_notes) for definition in definitions.values()}

        self.assertGreaterEqual(len(completion_sets), 10)
        self.assertGreaterEqual(len(recovery_sets), 10)
        self.assertIn("source boundaries", " ".join(definitions["web-research"].final_checklist))
        self.assertIn("agenda", " ".join(definitions["meeting-brief"].final_checklist).lower())
        self.assertIn("selected coding or runtime owner", " ".join(definitions["ralph"].final_checklist))
        self.assertIn("managed path", " ".join(definitions["skill"].final_checklist))

    def test_coding_handoff_skills_include_executor_readiness_fallback(self) -> None:
        templates = {template.name: template.content for template in builtin_skill_templates()}
        handoff_names = {
            definition.name
            for definition in installable_skill_definitions()
            if definition.hermes_role in {"handoff-guide", "runtime-handoff-guidance"}
            or definition.quality_tier == "handoff-gated"
        }

        self.assertTrue({"ralph", "ultragoal", "ultraprocess", "team", "ultrawork", "ai-slop-cleaner"} <= handoff_names)
        for name in handoff_names:
            with self.subTest(skill=name):
                content = templates[name]
                self.assertIn("Executor readiness:", content)
                self.assertIn("executor_readiness/v1", content)
                self.assertIn("retry only after that state changes", content)
                self.assertIn("not dispatch, implementation, verification, review, CI, merge-readiness, or merge evidence", content)

    def test_harnesses_define_runtime_evidence_contract(self) -> None:
        for harness in builtin_harnesses():
            self.assertGreaterEqual(len(harness.artifact_events), 1)
            self.assertEqual(harness.privacy_default, "metadata_only")
            self.assertIn("Record", harness.delegation_expectation)
            self.assertTrue(harness.quality_tier)
            self.assertGreaterEqual(len(harness.quality_bar), 1)
            self.assertGreaterEqual(len(harness.evidence_ladder), 3)
            self.assertGreaterEqual(len(harness.wrapper_actions), 1)
            self.assertGreaterEqual(len(harness.overclaim_guards), 1)

    def test_workflow_reference_payload_exposes_quality_contracts(self) -> None:
        payload = workflow_reference_payload()

        self.assertEqual(payload["schema_version"], "workflow_catalog/v1")
        skills = {skill["name"]: skill for skill in payload["skills"]}
        harnesses = {harness["name"]: harness for harness in payload["harnesses"]}

        self.assertEqual(skills["oh-my-hermes"]["quality_tier"], "routing-gated")
        self.assertIn("Keep users command-agnostic", " ".join(skills["oh-my-hermes"]["quality_bar"]))
        self.assertIn("direct workflow selection", " ".join(skills["oh-my-hermes"]["quality_bar"]))
        self.assertIn("why_this_exists", skills["oh-my-hermes"])
        self.assertIn("do_not_use_when", skills["oh-my-hermes"])
        self.assertIn("good_example", skills["oh-my-hermes"])
        self.assertIn("bad_example", skills["oh-my-hermes"])
        self.assertIn("final_checklist", skills["oh-my-hermes"])
        self.assertIn("recovery_notes", skills["oh-my-hermes"])
        self.assertGreaterEqual(len(skills["oh-my-hermes"]["final_checklist"]), 2)
        self.assertGreaterEqual(len(skills["oh-my-hermes"]["recovery_notes"]), 2)
        self.assertIn("routing conservative", skills["oh-my-hermes"]["why_this_exists"])
        self.assertIn("Use OMH request-to-handoff", skills["oh-my-hermes"]["good_example"]["prompt"])
        loop_final = " ".join(skills["loop"]["final_checklist"])
        ultragoal_recovery = " ".join(skills["ultragoal"]["recovery_notes"])
        self.assertIn("loop_status_card/v1", loop_final)
        self.assertIn("verification_plan", loop_final)
        self.assertIn("queued loop ticks", loop_final)
        self.assertIn("inspect .omh/goals", ultragoal_recovery)
        self.assertIn("prepared_not_observed", ultragoal_recovery)
        for name, (exposure, installable) in FEATURE_SURFACE_EXPOSURES.items():
            self.assertIn(name, skills)
            self.assertEqual(skills[name]["exposure"], exposure)
            self.assertEqual(skills[name]["surface_exposure"], exposure)
            self.assertEqual(skills[name]["install_visibility"], installable)
            self.assertIn("preferred_usage", skills[name])
        self.assertEqual(harnesses["coding-handling"]["quality_tier"], "handoff-gated")
        self.assertIn("coding_delegation_prepared", harnesses["coding-handling"]["evidence_ladder"])
        self.assertIn("send_to_codex", harnesses["coding-handling"]["wrapper_actions"])
        self.assertEqual(harnesses["app-delivery-loop"]["quality_tier"], "delivery-gated")
        self.assertIn("deploy_monitor_observed_when_available", harnesses["app-delivery-loop"]["evidence_ladder"])
        self.assertIn("record_monitor_signal", harnesses["app-delivery-loop"]["wrapper_actions"])
        self.assertEqual(harnesses["goal-loop"]["quality_tier"], "loop-gated")
        self.assertIn("feedback_gate_evaluated", harnesses["goal-loop"]["evidence_ladder"])
        self.assertIn("verification_plan_attached", harnesses["goal-loop"]["evidence_ladder"])
        self.assertIn("run_loop_once", harnesses["goal-loop"]["wrapper_actions"])
        self.assertIn("choose_permission_profile", harnesses["goal-loop"]["wrapper_actions"])
        self.assertIn("prepared", " ".join(harnesses["coding-handling"]["overclaim_guards"]).lower())
        quality = harnesses["coding-handling"]["harness_quality"]
        self.assertEqual(quality, harness_quality_contract("coding-handling"))
        self.assertEqual(quality["schema_version"], "harness_quality/v1")
        self.assertEqual(validate_harness_quality(quality), [])

        for harness in payload["harnesses"]:
            self.assertIn("harness_quality", harness)
            self.assertEqual(validate_harness_quality(harness["harness_quality"]), [])

    def test_unknown_harness_quality_contract_is_safe_to_render(self) -> None:
        contract = harness_quality_contract("not-installed-harness")

        self.assertEqual(contract["schema_version"], "harness_quality/v1")
        self.assertEqual(contract["quality_tier"], "unknown")
        self.assertIn("operator_review_required", contract["evidence_ladder"])
        self.assertEqual(contract["wrapper_actions"], ["show_status"])
        self.assertIn("do not infer runtime capability", contract["overclaim_guards"][0].lower())

    def test_generated_workflow_reference_matches_catalog(self) -> None:
        reference = Path("docs/WORKFLOWS.md").read_text(encoding="utf-8")

        self.assertEqual(reference, workflow_reference_markdown())
        self.assertIn("This file is generated from `src/skills/catalog.py`", reference)
        self.assertIn("omh_target_topology/v1", reference)
        self.assertIn("Exposure is the install contract", reference)
        self.assertIn("router-only, harness-only, and agent-context surfaces stay routable references", reference)
        for definition in builtin_definitions():
            exposure = skill_exposure_payload(definition.name)
            self.assertIn(f"### {definition.name}", reference)
            self.assertIn(f"- Category: `{definition.category}`", reference)
            self.assertIn(f"- Phase: `{definition.phase}`", reference)
            self.assertIn(f"- Hermes role: `{definition.hermes_role}`", reference)
            self.assertIn(f"- Quality tier: `{definition.quality_tier}`", reference)
            self.assertIn(f"- Exposure: `{exposure['exposure']}`", reference)
            self.assertIn(f"- Install visibility: `{str(exposure['install_visibility']).lower()}`", reference)
            self.assertIn(f"- Preferred usage: {exposure['preferred_usage']}", reference)
            self.assertIn(f"- Handoff policy: {definition.handoff_policy}", reference)
            self.assertIn(f"- Why this exists: {definition.why_this_exists}", reference)
            self.assertIn("- Do not use when:", reference)
            self.assertIn("- Good example:", reference)
            self.assertIn("- Bad example:", reference)
            self.assertIn(f"  - Prompt: {definition.good_example.prompt}", reference)
            self.assertIn(f"  - Prompt: {definition.bad_example.prompt}", reference)
        for harness in builtin_harnesses():
            self.assertIn(f"### {harness.name}", reference)
            self.assertIn(f"- Quality tier: `{harness.quality_tier}`", reference)
            for event in harness.artifact_events:
                self.assertIn(f"`{event}`", reference)
            for step in harness.evidence_ladder:
                self.assertIn(f"`{step}`", reference)
        self.assertIn("coding_delegation_recorded", reference)
        self.assertIn("Evidence ladder", reference)
        self.assertIn("Overclaim guards", reference)

    def test_generated_public_content_avoids_legacy_product_branding(self) -> None:
        forbidden = ("oh-my-" + "co" + "dex",)
        combined = "\n".join(skill.content for skill in builtin_skill_templates()).lower()

        for term in forbidden:
            self.assertNotIn(term, combined)

    def test_public_project_files_avoid_legacy_product_branding(self) -> None:
        forbidden = ("oh-my-" + "co" + "dex",)
        paths = [
            Path("README.md"),
            Path("pyproject.toml"),
            Path(".gitignore"),
            Path("CONTRIBUTING.md"),
            Path("CHANGELOG.md"),
            Path("CODE_OF_CONDUCT.md"),
            Path("SECURITY.md"),
            Path("SUPPORT.md"),
            Path("install.sh"),
            *Path("src").rglob("*.py"),
            *Path("tests").rglob("*.py"),
            *Path("docs").rglob("*.md"),
            *Path("skills").rglob("*"),
            *Path("examples").rglob("*"),
            *Path("site").rglob("*"),
            *Path(".github").rglob("*.md"),
            *Path(".github").rglob("*.yml"),
        ]

        for path in paths:
            if path.is_dir():
                continue
            if path.suffix in {".png", ".jpg", ".jpeg", ".webp", ".pyc"}:
                continue
            text = path.read_text(encoding="utf-8").lower()
            for term in forbidden:
                self.assertNotIn(term, text, f"{term!r} leaked in {path}")

    def test_first_release_trust_surfaces_are_present(self) -> None:
        required_paths = [
            Path("README.md"),
            Path("AGENTS.md"),
            Path("INSTALL_FOR_AGENTS.md"),
            Path("docs/README.md"),
            Path("docs/DIRECTION.md"),
            Path("docs/HARNESS_QUALITY.md"),
            Path("docs/HERMES_AGENT_INTEGRATION_RUNBOOK.md"),
            Path("docs/INSTALLATION.md"),
            Path("docs/ROLES.md"),
            Path("docs/APPLICATION_CASES.md"),
            Path("docs/PLAYBOOKS.md"),
            Path("roles/guide.md"),
            Path("roles/researcher.md"),
            Path("roles/planner.md"),
            Path("roles/operator.md"),
            Path("roles/memory-keeper.md"),
            Path("roles/handoff-guide.md"),
            Path("roles/builder.md"),
            Path("roles/tracker.md"),
            Path("roles/reviewer.md"),
            Path("docs/RELEASE.md"),
            Path("install.sh"),
            Path("CONTRIBUTING.md"),
            Path("CHANGELOG.md"),
            Path("CODE_OF_CONDUCT.md"),
            Path("SECURITY.md"),
            Path("SUPPORT.md"),
            Path("LICENSE"),
            Path(".github/workflows/ci.yml"),
            Path(".github/workflows/pages.yml"),
            Path(".github/dependabot.yml"),
            Path(".github/pull_request_template.md"),
            Path(".github/ISSUE_TEMPLATE/bug_report.yml"),
            Path(".github/ISSUE_TEMPLATE/feature_request.yml"),
            Path(".github/ISSUE_TEMPLATE/config.yml"),
            Path("site/index.html"),
            Path("site/docs/index.html"),
            Path("site/docs/loop/index.html"),
            Path("site/docs/image-gen/index.html"),
            Path("site/docs/hermes-agent-architecture/index.html"),
            Path("site/docs/intent-to-plan/index.html"),
            Path("site/docs/product-ops/index.html"),
            Path("site/docs/executor-handoff/index.html"),
            Path("site/styles.css"),
            Path("site/assets/omh-readme-hero.png"),
            Path("site/assets/omh-img-summary-card.png"),
        ]

        for path in required_paths:
            self.assertTrue(path.exists(), f"{path} should be present")

        readme = Path("README.md").read_text(encoding="utf-8")
        docs_readme = Path("docs/README.md").read_text(encoding="utf-8")
        install_for_agents = Path("INSTALL_FOR_AGENTS.md").read_text(encoding="utf-8")
        installation = Path("docs/INSTALLATION.md").read_text(encoding="utf-8")
        ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        pages = Path(".github/workflows/pages.yml").read_text(encoding="utf-8")
        release = Path("docs/RELEASE.md").read_text(encoding="utf-8")
        pr_template = Path(".github/pull_request_template.md").read_text(encoding="utf-8")
        harness_quality = Path("docs/HARNESS_QUALITY.md").read_text(encoding="utf-8")
        runbook = Path("docs/HERMES_AGENT_INTEGRATION_RUNBOOK.md").read_text(encoding="utf-8")
        install_sh = Path("install.sh").read_text(encoding="utf-8")
        roles_doc = Path("docs/ROLES.md").read_text(encoding="utf-8")
        site = Path("site/index.html").read_text(encoding="utf-8")
        site_docs = Path("site/docs/index.html").read_text(encoding="utf-8")
        site_loop = Path("site/docs/loop/index.html").read_text(encoding="utf-8")
        site_image_gen = Path("site/docs/image-gen/index.html").read_text(encoding="utf-8")
        site_architecture_post = Path("site/docs/hermes-agent-architecture/index.html").read_text(encoding="utf-8")
        site_intent = Path("site/docs/intent-to-plan/index.html").read_text(encoding="utf-8")
        site_product_ops = Path("site/docs/product-ops/index.html").read_text(encoding="utf-8")
        site_handoff = Path("site/docs/executor-handoff/index.html").read_text(encoding="utf-8")
        site_css = Path("site/styles.css").read_text(encoding="utf-8")
        profile_map = Path("assets/omh-profile-interaction-map.svg").read_text(encoding="utf-8")

        self.assertIn("Hermes skill tap path", readme)
        self.assertIn("hermes skills tap add rlaope/oh-my-hermes", readme)
        self.assertIn("hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes", readme)
        self.assertIn("hermes skills tap add rlaope/oh-my-hermes", installation)
        self.assertIn("hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes", installation)
        self.assertIn("curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh", readme)
        self.assertIn("https://rlaope.github.io/oh-my-hermes/", readme)
        self.assertIn("[Documentation](docs/README.md)", readme)
        self.assertIn("[Installation](docs/INSTALLATION.md)", readme)
        self.assertIn("[Agent Install](INSTALL_FOR_AGENTS.md)", readme)
        self.assertIn("[Roles](docs/ROLES.md)", readme)
        self.assertIn("[Application Cases](docs/APPLICATION_CASES.md)", readme)
        self.assertIn("[GitHub Pages site](site/index.html)", readme)
        self.assertIn("**oh-my-hermes** is built for that reality", readme)
        self.assertIn("replacing your existing setup", readme)
        self.assertIn("These 7 are the representative modes", readme)
        self.assertIn("`deep-interview`", readme)
        self.assertIn("`ralplan`", readme)
        self.assertIn("`ultragoal`", readme)
        self.assertIn("`loop`", readme)
        self.assertIn("`web-research`", readme)
        self.assertIn("`idea-to-deploy`", readme)
        self.assertIn("`workflow-learning`", readme)
        self.assertIn("`instinct-ledger`", readme)
        self.assertIn("**+47** more built-in skills", readme)
        self.assertIn("Plan and decide", readme)
        self.assertIn("Learn and gather", readme)
        self.assertIn("Create materials and visuals", readme)
        self.assertIn("Delegate coding and ship", readme)
        self.assertIn("Operate and observe", readme)
        self.assertIn("## Request Flow", readme)
        self.assertIn("plain request", readme)
        self.assertIn("choose workflow lane", readme)
        self.assertIn("Request shape", readme)
        self.assertIn("Scoped handoff to Codex, Claude Code, Hermes", readme)
        self.assertIn("assets/hermes-agent-hero.png", readme)
        self.assertIn("assets/friren-agent-omh-callout.png", readme)
        self.assertIn("assets/artengine-friren-profile-card.png", readme)
        self.assertIn("assets/omh-core-workflows.png", readme)
        self.assertIn("img.shields.io/badge/github", readme)
        self.assertNotIn("### Img Summary Skill", readme)
        self.assertNotIn("assets/omh-img-summary-card.png", readme)
        self.assertNotIn("## Organization Patterns", readme)
        self.assertNotIn("assets/omh-profile-interaction-map.svg", readme)
        self.assertIn("../assets/omh-profile-interaction-map.svg", roles_doc)
        self.assertIn("OMH request-to-handoff interaction map", profile_map)
        self.assertIn("Plain request", profile_map)
        self.assertIn("Hermes Agent", profile_map)
        self.assertIn("OMH workflow layer", profile_map)
        self.assertIn("Prepared handoff", profile_map)
        self.assertIn("Observed evidence", profile_map)
        self.assertIn("Public claim rule", profile_map)
        self.assertIn("optional Hermes agent/profile packs", installation)
        self.assertIn("omh profile list", installation)
        self.assertIn("omh profile inspect cto-loop", installation)
        self.assertIn("omh setup --profile-pack cto-loop", installation)
        self.assertIn("CTO, PM, Dev, QA, Security, and Ops", installation)
        self.assertIn("not installed by default", installation)
        self.assertIn("OMH_CHANNEL=stable OMH_VERSION=<version>", installation)
        self.assertIn("v<version>", installation)
        self.assertIn("installs generated managed skills", installation)
        update_section = installation.split("## Update", 1)[1].split("\n## ", 1)[0]
        self.assertIn("```sh\nomh update\nomh doctor\n```", update_section)
        self.assertIn("Most users should run only `omh update`.", update_section)
        self.assertLess(update_section.index("omh update\nomh doctor"), update_section.index("Advanced operators"))
        self.assertNotIn("omh update --channel preview", update_section)
        self.assertIn("omh setup", readme)
        self.assertIn("omh doctor", readme)
        self.assertNotIn("## Why OMH", readme)
        self.assertLess(readme.index("## Quick Start"), readme.index("## Core Workflows"))
        quick_start = readme.split("## Quick Start", 1)[1].split("## Core Workflows", 1)[0]
        self.assertIn("curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh", quick_start)
        self.assertIn("omh setup", quick_start)
        self.assertLess(quick_start.index("omh setup"), quick_start.index("omh doctor"))
        self.assertIn("Use OMH request-to-handoff for: I want to safely add a feature to this repo.", quick_start)
        self.assertIn("First-value packs after setup", quick_start)
        for label in (
            "Frontend Rescue",
            "Repo First-Win",
            "Failure-to-Fix",
            "Visual Deliverable",
            "Toolbelt Readiness",
            "CTO/Product Loop",
        ):
            self.assertIn(label, quick_start)
        self.assertIn("not observed execution", quick_start)
        self.assertIn("hermes skills tap add", quick_start)
        self.assertNotIn("That is the normal path", quick_start)
        self.assertNotIn("name the responsible role", quick_start)
        self.assertNotIn("omh_interact", quick_start)
        self.assertNotIn("## Backend / Operator Surface", readme)
        self.assertNotIn("## Wrapper Backend Flow", readme)
        self.assertNotIn("## What Gets Recorded", readme)
        self.assertNotIn("omh docs workflows --json", readme)
        self.assertNotIn("Useful local and wrapper-debug commands", readme)
        core_workflows = readme.split("## Core Workflows", 1)[1].split("## What You Get", 1)[0]
        for label in (
            "Plan and decide",
            "Learn and gather",
            "Create materials and visuals",
            "Delegate coding and ship",
            "Operate and observe",
        ):
            self.assertIn(label, core_workflows)
        self.assertNotIn("| `deep-interview` / `ralplan`", core_workflows)
        self.assertIn("Codex, Claude Code, Hermes", core_workflows)
        self.assertIn("Install Path A: Hermes-Native Skill Tap", installation)
        self.assertIn("Agent Install Protocol", installation)
        self.assertIn("hermes_native_setup/v1", installation)
        self.assertNotIn("OMH_WITH_PLUGIN=1", installation)
        self.assertIn("omh setup --profile-pack cto-loop --profile-pack startup-delivery", installation)
        self.assertIn("omh setup --default-executor claude-code", installation)
        self.assertIn("OMH_RUN_SETUP=1 OMH_SETUP_ARGS=\"--dry-run\"", installation)
        self.assertIn("The installer also prints the installed `omh` command path", installation)
        self.assertIn("isolated OMH virtual environment", installation)
        self.assertIn("add the printed directory to", installation)
        self.assertIn("Use OMH request-to-handoff for: I want to safely add a feature to this repo.", installation)
        self.assertIn("First-value packs are the stronger first-use paths once setup is done", installation)
        self.assertIn("Frontend Rescue", installation)
        self.assertIn("Failure-to-Fix", installation)
        self.assertIn("Toolbelt Readiness", installation)
        self.assertIn("They do not", installation)
        self.assertIn("execution, visual QA, CI, deployment", installation)
        self.assertIn("omh chat native-command --source discord", installation)
        self.assertIn("omh_command_fallback_card/v1", installation)
        self.assertIn("chat_response.state.command_preview.suggestions", installation)
        self.assertIn("Open omh", installation)
        self.assertIn("`./omh`, `/omh`, `./skills`, or `/skills`", installation)
        self.assertIn("chat_response.state.skill_picker.options", installation)
        self.assertIn("chat_response.state.workflow_explanation", installation)
        self.assertIn("why/next/not-evidence card", installation)
        self.assertIn("Do not ask the", installation)
        self.assertIn("approve `omh list`", installation)
        self.assertIn("omh coding executor-readiness --executor <profile>", installation)
        self.assertIn("Readiness", installation)
        self.assertIn("name the responsible", installation)
        self.assertIn("Hermes CLI Release Smoke", installation)
        self.assertIn("all-skill awareness lane coverage", installation)
        self.assertIn("bundled role context", installation)
        self.assertIn("bounded context budgets", installation)
        self.assertIn("--hermes-home /tmp/hermes-smoke release hermes-smoke --live --install-path setup", installation)
        self.assertIn("OMH Agent Install Protocol", install_for_agents)
        self.assertIn("curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh", install_for_agents)
        self.assertIn("omh setup", install_for_agents)
        self.assertIn("omh doctor", install_for_agents)
        self.assertIn("hermes skills tap add rlaope/oh-my-hermes", install_for_agents)
        self.assertNotIn("OMH_WITH_PLUGIN=1", install_for_agents)
        self.assertIn("recommended_next_action", install_for_agents)
        self.assertIn("Use OMH request-to-handoff for: I want to safely add a feature to this repo.", install_for_agents)
        self.assertIn("omh release hermes-smoke", install_for_agents)
        self.assertIn("install, list, check, and inspect OMH", install_for_agents)
        self.assertNotIn("GITHUB_TOKEN", install_for_agents)
        self.assertNotIn("PRODUCTION_URL", install_for_agents)
        self.assertIn("Chat Wrapper Backend Flow", installation)
        self.assertIn("omh chat interact", installation)
        self.assertIn("harness_quality/v1", installation)
        self.assertIn("omh docs workflows --json", installation)
        self.assertIn("omh harness inspect planning", installation)
        self.assertIn("OMH_WITH_PLUGIN", install_sh)
        self.assertIn('OMH_RUN_SETUP="${OMH_RUN_SETUP:-0}"', install_sh)
        self.assertIn('if [ "$OMH_RUN_SETUP" = "1" ]; then', install_sh)
        self.assertIn("OMH_PROFILE_PACKS", install_sh)
        self.assertIn("OMH_LANG", install_sh)
        self.assertIn("OMH_LANGUAGE", install_sh)
        self.assertIn('--language "$OMH_LANG"', install_sh)
        self.assertIn("OMH_SOURCE_REF", install_sh)
        self.assertIn('--source-ref "$OMH_SOURCE_REF"', install_sh)
        self.assertIn("--command-package-updated", install_sh)
        self.assertIn('OMH_INSTALL_MODE="${OMH_INSTALL_MODE:-venv}"', install_sh)
        self.assertIn("step_create_venv", install_sh)
        self.assertIn("OMH_BIN_DIR", install_sh)
        self.assertIn("OMH_INSTALL_MODE=python", installation)
        self.assertIn("find_omh_command", install_sh)
        self.assertIn("Expose the omh command", install_sh)
        self.assertIn("not on PATH", install_sh)
        self.assertIn("OMH_DEFAULT_EXECUTOR", install_sh)
        self.assertIn("OMH_SETUP_PROFILES", install_sh)
        self.assertIn("OMH_SETUP_ARGS", install_sh)
        self.assertIn('if [ "$OMH_CHANNEL" = "local" ] && [ -d "$OMH_PACKAGE_URL" ]; then', install_sh)
        self.assertIn('set -- "$@" --source "$OMH_PACKAGE_URL"', install_sh)
        self.assertIn("Install OMH package", install_sh)
        self.assertIn("--disable-pip-version-check -q", install_sh)
        self.assertIn("--force-reinstall", install_sh)
        self.assertIn("wrapper_actions", harness_quality)
        self.assertIn("overclaim_guards", harness_quality)
        self.assertIn("harness_progress/v1", harness_quality)
        self.assertIn("This is an operator reference, not an `omh` command.", runbook)
        self.assertIn("Hermes-agent wrapper", runbook)
        self.assertIn("Prepared handoff is not execution evidence", runbook)
        self.assertIn("examples/wrapper-golden/hermes-agent-integration.json", runbook)
        self.assertIn("Hermes Agent Integration Runbook", docs_readme)
        self.assertIn("Hermes Agent Architecture Guide", docs_readme)
        self.assertIn("Role Surface", docs_readme)
        self.assertIn("Agent Install Protocol", docs_readme)
        self.assertIn("`deep-interview` / `ralplan` / `ultragoal` / `loop` / `ultraprocess`", docs_readme)
        self.assertIn("python -m unittest discover -s tests", ci)
        self.assertIn("python -m compileall src", ci)
        self.assertIn("docs workflows --check", ci)
        self.assertIn("Capability probe smoke", ci)
        self.assertIn("Hermes release smoke plan", ci)
        self.assertIn("Release readiness checklist", ci)
        self.assertIn("release checklist --json", ci)
        self.assertIn("release hermes-smoke", ci)
        self.assertRegex(pages, r"actions/upload-pages-artifact@v[0-9]+")
        self.assertRegex(pages, r"actions/deploy-pages@v[0-9]+")
        self.assertIn("pages: write", pages)
        self.assertIn("enablement: true", pages)
        self.assertIn("site/**", pages)
        self.assertIn("docs workflows --check", pages)
        self.assertIn("harness validate", pages)
        self.assertIn("Pinned stable install", release)
        self.assertIn("release_readiness_checklist/v1", release)
        self.assertIn("omh release checklist --version 1.0.2 --json", release)
        self.assertIn("all-skill awareness lane coverage", release)
        self.assertIn("bundled role context", release)
        self.assertIn("bounded context budgets", release)
        self.assertIn("prompt bloat", release)
        self.assertIn("Runtime evidence smoke", release)
        self.assertIn("Harness catalog validation status", release)
        self.assertIn("GitHub Pages workflow status", release)
        self.assertIn("Capability probe status", release)
        self.assertIn("Hermes CLI Install Smoke", release)
        self.assertIn("omh release hermes-smoke --live --install-path tap --target-confirmed", release)
        self.assertIn("--hermes-home /tmp/hermes-smoke release hermes-smoke --live --install-path setup", release)
        self.assertIn("hermes skills check oh-my-hermes", release)
        self.assertIn("uv build", release)
        self.assertIn("oh_my_hermes-1.0.2-py3-none-any.whl", release)
        self.assertIn("/tmp/omh-wheel-smoke/bin/omh --help", release)
        self.assertIn("OMH_VENV_DIR=/tmp/omh-installer-venv", release)
        self.assertIn("## Feature Report", pr_template)
        self.assertIn("### What Changed", pr_template)
        self.assertIn("### Why This Exists", pr_template)
        self.assertIn("### User / Operator Impact", pr_template)
        self.assertIn("### How It Works", pr_template)
        self.assertIn("### Files And Contracts Touched", pr_template)
        self.assertIn("Manual Hermes/TUI check", pr_template)
        self.assertIn("## Compatibility / Rollout", pr_template)
        self.assertIn("## Follow-Up", pr_template)
        self.assertIn("OMH", site)
        self.assertIn("Oh My Hermes", site)
        self.assertIn('src="assets/omh-readme-hero.png"', site)
        self.assertIn('href="docs/">Read the docs</a>', site)
        self.assertIn("Hermes-native workflow contracts", site)
        self.assertIn("Install once. Keep Hermes. Make the next step safe.", site)
        self.assertIn('aria-label="Top install commands"', site)
        self.assertIn("curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh", site)
        self.assertIn("omh setup", site)
        self.assertIn("hermes skills tap add rlaope/oh-my-hermes", site)
        self.assertIn("hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes", site)
        self.assertNotIn("omh doctor", site)
        self.assertNotIn("omh capabilities summary --json", site)
        self.assertNotIn("Bootstrap local operators when Hermes needs them.", site)
        self.assertIn("The README values, made visible.", site)
        self.assertIn("Modern OMH is a contract system, not a command catalog.", site)
        self.assertIn("omh_interact", site)
        self.assertIn("chat_response/v1", site)
        self.assertIn("coding_runtime_handoff/v1", site)
        self.assertIn("Install once.", site)
        self.assertIn("Keep Hermes.", site)
        self.assertIn("Choose the smallest safe move.", site)
        self.assertIn("Stay local and deterministic.", site)
        self.assertIn("Do not blur proof.", site)
        self.assertIn("Five lanes beat forty commands.", site)
        self.assertIn("Plan and decide", site)
        self.assertIn("Learn and gather", site)
        self.assertIn("Create materials and visuals", site)
        self.assertIn("Delegate coding and ship", site)
        self.assertIn("Operate and observe", site)
        self.assertIn('href="docs/product-ops/"', site)
        self.assertIn('href="docs/executor-handoff/"', site)
        self.assertIn("ultragoal", site)
        self.assertNotIn("usage-skill", site)
        self.assertIn("Hermes message", site)
        self.assertIn("I want to safely add a feature to this repo.", site)
        self.assertIn("request-to-handoff", site)
        self.assertIn("planner", site)
        self.assertIn("Prepared is not observed", site)
        self.assertIn("First-value packs", site)
        self.assertIn("Useful immediately after install.", site)
        self.assertIn("Frontend Rescue", site)
        self.assertIn("Failure-to-Fix", site)
        self.assertIn("Toolbelt Readiness", site)
        self.assertIn("prepared guidance is not observed execution", site)
        self.assertIn("Reference pages when the lane needs detail.", site)
        self.assertIn("Loop</span>", site)
        self.assertIn("Source-specific prompt cards for meetings, PRs, issues, releases, and research.", site)
        self.assertIn('href="docs/image-gen/"', site)
        self.assertIn('href="docs/hermes-agent-architecture/">Hermes Deepdive</a>', site)
        self.assertIn('href="docs/hermes-agent-architecture/"', site)
        self.assertIn("Architecture at a glance.", site)
        self.assertIn("assets/omh-img-summary-card.png", site)
        self.assertIn('href="docs/loop/"', site)
        self.assertIn('href="docs/intent-to-plan/"', site)
        self.assertIn("Hermes Agent Integration Runbook", site_docs)
        self.assertIn("Find the safe path fast.", site_docs)
        self.assertIn("Install once. Keep Hermes. Make the next step safe.", site_docs)
        self.assertIn("Core values", site_docs)
        self.assertIn("examples/wrapper-golden/hermes-agent-integration.json", site_docs)
        self.assertIn("Role surface", site_docs)
        self.assertIn("docs/ROLES.md", site_docs)
        self.assertIn("INSTALL_FOR_AGENTS.md", site_docs)
        self.assertIn("Choose a lane before a command", site_docs)
        self.assertIn("<code>loop</code> <code>workflow-learning</code>", site_docs)
        self.assertIn("request-to-handoff", site_docs)
        self.assertIn("planner", site_docs)
        self.assertIn("Routing is not plan acceptance, dispatch, or execution evidence.", site_docs)
        self.assertIn('<a class="loop-spotlight loop-spotlight--docs" href="loop/"', site_docs)
        self.assertIn('<a class="imagegen-spotlight imagegen-spotlight--docs" href="image-gen/"', site_docs)
        self.assertIn('<span class="button button--primary" aria-hidden="true">Open Loop docs</span>', site_docs)
        self.assertIn("../assets/omh-loop-engineering.png", site_docs)
        self.assertIn("../assets/omh-img-summary-card.png", site_docs)
        self.assertIn("visual_prompt_card/v1", site_docs)
        self.assertIn("visual_observation/v1", site_docs)
        self.assertIn('href="hermes-agent-architecture/">Hermes Deepdive</a>', site_docs)
        self.assertIn('href="hermes-agent-architecture/"', site_docs)
        self.assertIn("Hermes Agent explained", site_docs)
        self.assertIn('href="image-gen/"', site_docs)
        self.assertIn('href="intent-to-plan/"', site_docs)
        self.assertIn('href="product-ops/"', site_docs)
        self.assertIn('href="executor-handoff/"', site_docs)
        self.assertIn("Loop Engineering", site_loop)
        self.assertIn("In OMH, Loop Engineering is the operating surface", site_loop)
        self.assertNotIn("하네스 엔지니어링", site_loop)
        self.assertIn("../../assets/omh-loop-engineering.png", site_loop)
        self.assertIn("loop_runtime/v1", site_loop)
        self.assertIn("loop_engineering/v1", site_loop)
        self.assertIn("verification_plan", site_loop)
        self.assertIn("Inner-loop checks are cheap and frequent", site_loop)
        self.assertIn("Outer-loop checks are slower and rarer", site_loop)
        self.assertIn("failure_mode_summary", site_loop)
        self.assertIn("verification gaps, comprehension debt, and cognitive surrender", site_loop)
        self.assertIn("omh loop run-once --loop", site_loop)
        self.assertIn("created_tick", site_loop)
        self.assertIn("pending_queue_exists", site_loop)
        self.assertIn("Test as stop signal", site_loop)
        self.assertIn("Automation, worktree, skill, connector, and subagent blocks", site_loop)
        self.assertIn("fan-out, adversarial verification, tournament, and triage batch", site_loop)
        self.assertIn("Cost policy keeps reads bounded", site_loop)
        self.assertIn("A loop tick is not execution", site_loop)
        self.assertIn("Intent to plan", site_intent)
        self.assertIn("deep-interview", site_intent)
        self.assertIn("Image gen that stays source-aware.", site_image_gen)
        self.assertIn("meeting_recap_card", site_image_gen)
        self.assertIn("report_digest_card", site_image_gen)
        self.assertIn("pr_review_infographic", site_image_gen)
        self.assertIn("issue_triage_card", site_image_gen)
        self.assertIn("research_briefing_board", site_image_gen)
        self.assertIn("release_announcement_card", site_image_gen)
        self.assertIn("visual_prompt_card/v1", site_image_gen)
        self.assertIn("visual_observation/v1", site_image_gen)
        self.assertIn("image_generation_setup/v1", site_image_gen)
        self.assertIn("connected image tool", site_image_gen)
        self.assertIn("They are not generated image evidence.", site_image_gen)
        self.assertIn("Company and product ops", site_product_ops)
        self.assertIn("feedback-triage", site_product_ops)
        self.assertIn("source-specific Image gen cards", site_product_ops)
        self.assertIn('href="../image-gen/"', site_product_ops)
        self.assertIn("Executor-ready handoff", site_handoff)
        self.assertIn("Codex, Claude Code", site_handoff)
        self.assertIn("Hermes Agent Anatomy", site_architecture_post)
        self.assertIn('aria-current="page" href="./">Hermes Deepdive</a>', site_architecture_post)
        self.assertIn('href="../hermes-agent-architecture/">Hermes Deepdive</a>', site_loop)
        self.assertIn('href="../hermes-agent-architecture/">Hermes Deepdive</a>', site_image_gen)
        self.assertIn('href="../hermes-agent-architecture/">Hermes Deepdive</a>', site_intent)
        self.assertIn('href="../hermes-agent-architecture/">Hermes Deepdive</a>', site_product_ops)
        self.assertIn('href="../hermes-agent-architecture/">Hermes Deepdive</a>', site_handoff)
        self.assertIn("English", site_architecture_post)
        self.assertIn("한국어", site_architecture_post)
        self.assertIn("Hermes Agent is not just a chat box", site_architecture_post)
        self.assertIn("Hermes Agent는 단순 채팅창", site_architecture_post)
        self.assertIn("The easiest mistake is to describe Hermes as", site_architecture_post)
        self.assertIn('Hermes를 "CLI 에이전트"라고만 부르면', site_architecture_post)
        self.assertIn("Mermaid-style component map", site_architecture_post)
        self.assertIn("One user message crosses six layers before it becomes useful work.", site_architecture_post)
        self.assertIn("사용자 메시지 하나는 유용한 일이 되기 전 여섯 층을 지나갑니다.", site_architecture_post)
        self.assertIn("01 / Routing Layer", site_architecture_post)
        self.assertIn("<h2>Prompt Builder</h2>", site_architecture_post)
        self.assertIn("<h2>Agent Loop</h2>", site_architecture_post)
        self.assertIn("<h2>Memory Discipline</h2>", site_architecture_post)
        self.assertIn("06 / Extension Ports", site_architecture_post)
        self.assertIn("<h2>Tool And Plugin Ports</h2>", site_architecture_post)
        self.assertIn("<h2>Hermes Gateway</h2>", site_architecture_post)
        self.assertIn("<h2>Cron And Scheduled Work</h2>", site_architecture_post)
        self.assertIn("delivery constraints", site_architecture_post)
        self.assertIn("Hermes Agent is best understood as a layered work runtime", site_architecture_post)
        self.assertIn("<h2>Evidence Boundary</h2>", site_architecture_post)
        self.assertIn("01 / 라우팅", site_architecture_post)
        self.assertIn("<h2>프롬프트 빌더</h2>", site_architecture_post)
        self.assertIn("<h2>에이전트 루프</h2>", site_architecture_post)
        self.assertIn("<h2>메모리 규칙</h2>", site_architecture_post)
        self.assertIn("06 / 도구와 확장 포트", site_architecture_post)
        self.assertIn("<h2>도구와 플러그인 포트</h2>", site_architecture_post)
        self.assertIn("07 / 게이트웨이 표면", site_architecture_post)
        self.assertIn("<h2>크론과 예약 실행</h2>", site_architecture_post)
        self.assertIn("gateway intent card", site_architecture_post)
        self.assertIn("<h2>증거 경계</h2>", site_architecture_post)
        self.assertIn("TUI, CLI, gateway, platform adapters", site_architecture_post)
        self.assertIn("Prompt compiler", site_architecture_post)
        self.assertIn("AIAgent, model transport, tool loop, session state", site_architecture_post)
        self.assertIn("Toolsets, MCP, plugins, cron, delivery targets", site_architecture_post)
        self.assertIn("Prepared state, observed result, verification, delivery", site_architecture_post)
        self.assertIn("Telegram", site_architecture_post)
        self.assertIn("Discord", site_architecture_post)
        self.assertIn("WhatsApp", site_architecture_post)
        self.assertIn("Signal", site_architecture_post)
        expected_source_paths = (
            "README.md",
            "docs/DIRECTION.md",
            "docs/MEMORY_CONTEXT.md",
            "src/routing/recommend.py",
            "src/routing/chat.py",
            "src/wrapper/contract.py",
            "src/wrapper/sessions.py",
            "src/coding_delegation.py",
            "src/runtime/artifacts.py",
            "src/runtime/records.py",
            "src/mcp_bridge.py",
            "src/plugin_bundle/omh/tools/chat_tool.py",
            "src/plugin_bundle/omh/tools/recommend_tool.py",
            "src/hermes_ops.py",
            "src/commands/ops.py",
            "src/skills/catalog.py",
            "src/skills/render.py",
            "skills/oh-my-hermes/SKILL.md",
        )
        for source_path in expected_source_paths:
            self.assertIn(source_path, site_architecture_post)

        stale_source_paths = (
            "run_agent.py",
            "agent/prompt_builder.py",
            "agent/memory_manager.py",
            "agent/conversation_loop.py",
            "agent/tool_executor.py",
            "agent/transports/base.py",
            "agent/curator.py",
            "model_tools.py",
            "tools/mcp_tool.py",
            "gateway/session.py",
            "gateway/delivery.py",
            "gateway/platform_registry.py",
            "cron/scheduler.py",
            "cron/scheduler_provider.py",
            "skills/autonomous-ai-agents/hermes-agent/SKILL.md",
        )
        for source_path in stale_source_paths:
            self.assertNotIn(source_path, site_architecture_post)
        self.assertIn("runtime fact", site_architecture_post)
        self.assertIn("GEPA-style", site_architecture_post)
        self.assertIn("context compilation", site_architecture_post)
        self.assertIn("structured memory", site_architecture_post)
        self.assertIn("A request does not just become an answer. It becomes a route.", site_architecture_post)
        self.assertIn("요청은 그냥 답변이 되지 않습니다. route가 됩니다.", site_architecture_post)
        self.assertIn("라우팅은 별도 마케팅 기능이 아니라 첫 번째 아키텍처 압력점입니다.", site_architecture_post)
        self.assertIn("compilation에 가깝습니다.", site_architecture_post)
        self.assertIn('"Open a coding task, but do not claim execution until the executor reports back."', site_architecture_post)
        self.assertIn('"코딩 작업을 열되, executor가 보고하기 전에는 실행됐다고 말하지 마."', site_architecture_post)
        article_body = site_architecture_post.split("<main", 1)[1].split("</main>", 1)[0]
        self.assertNotIn("OMH Layer", article_body)
        self.assertNotIn("OMH 포지션", article_body)
        self.assertNotIn("Use OMH", article_body)
        self.assertNotIn("workflow lens", article_body)
        topbar = site.split('<header class="topbar"', 1)[1].split("</header>", 1)[0]
        self.assertIn('href="docs/"', topbar)
        self.assertNotIn('href="#architecture"', topbar)
        self.assertNotIn('href="#install"', topbar)
        self.assertIn('class="nav__icon"', topbar)
        self.assertIn('href="https://github.com/rlaope/oh-my-hermes"', topbar)
        self.assertNotIn(">GitHub<", topbar)
        docs_topbar = site_docs.split('<header class="topbar topbar--solid"', 1)[1].split("</header>", 1)[0]
        self.assertIn('class="nav__icon"', docs_topbar)
        self.assertIn('href="https://github.com/rlaope/oh-my-hermes"', docs_topbar)
        self.assertNotIn(">GitHub<", docs_topbar)
        top_install_command = site.split('aria-label="Top install commands"', 1)[1].split("</code>", 1)[0]
        self.assertIn("curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh", top_install_command)
        self.assertIn("omh setup", top_install_command)
        self.assertNotIn("hermes skills tap add", top_install_command)
        self.assertNotIn("hermes skills install", top_install_command)
        self.assertNotIn("omh doctor", top_install_command)
        install_command = site.split('aria-label="Install commands"', 1)[1].split("</code>", 1)[0]
        self.assertIn("curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh", install_command)
        self.assertIn("omh setup", install_command)
        self.assertIn("hermes skills tap add rlaope/oh-my-hermes", install_command)
        self.assertIn("hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes", install_command)
        self.assertNotIn("omh doctor", install_command)
        self.assertIn("assets/omh-loop-engineering.png", site)
        self.assertTrue(Path("site/assets/omh-loop-engineering.png").is_file())
        self.assertTrue(Path("site/assets/omh-img-summary-card.png").is_file())
        self.assertNotIn("github.com/rlaope/oh-my-hermes/tree/main/docs", site)
        self.assertIn("OMH Documentation", site_docs)
        self.assertIn("hermes skills tap add rlaope/oh-my-hermes", site_docs)
        self.assertIn("OMH_CHANNEL=stable OMH_VERSION=&lt;version&gt; sh", site_docs)
        self.assertIn("OMH_SOURCE_REF=main@&lt;sha&gt; sh", site_docs)
        self.assertIn("omh chat interact --source discord", site_docs)
        self.assertIn("chat_response/v1", site_docs)
        self.assertIn("harness_progress/v1", site_docs)
        self.assertIn("omh harness validate", site_docs)
        self.assertIn("harness_progress/v1", site)
        self.assertIn(".value-grid", site_css)
        self.assertIn(".docs-start-grid", site_css)
        self.assertIn(".docs-lane-map", site_css)
        self.assertIn("assets/omh-readme-hero.png", site_css)
        self.assertIn(".loop-spotlight", site_css)
        self.assertIn(".imagegen-spotlight", site_css)
        self.assertIn(".image-format-grid", site_css)
        self.assertIn(".feature-flow", site_css)
        self.assertIn(".flagship-list", site_css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", site_css)
        self.assertIn(".flagship-item--docs", site_css)
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr));", site_css)

    def test_direction_and_agent_contract_lock_product_boundary(self) -> None:
        direction = Path("docs/DIRECTION.md").read_text(encoding="utf-8")
        docs_index = Path("docs/README.md").read_text(encoding="utf-8")
        agents = Path("AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("OMH is a Hermes-native wrapper orchestration layer.", direction)
        self.assertIn("Raise the product's capability level by strengthening contracts", direction)
        self.assertIn("Hermes owns:", direction)
        self.assertIn("OMH owns:", direction)
        self.assertIn("Selected coding executors/runtimes own:", direction)
        self.assertIn("prepared_not_observed", direction)
        self.assertIn("One user goal should normally produce one PR.", direction)
        self.assertIn("Keep users command-agnostic in chat.", direction)
        self.assertIn("The goal is parity of seriousness, not parity of implementation shape.", direction)
        self.assertIn("Skill-first distribution.", direction)
        self.assertIn("This directory is the public operating map", docs_index)
        self.assertIn("prepared versus observed evidence", docs_index)
        self.assertIn("Chat users should remain command-agnostic.", docs_index)
        self.assertIn("Harness Quality Contract", docs_index)
        self.assertIn("Do not turn OMH into a hidden Hermes runtime patch", agents)
        self.assertIn("One user goal should normally produce one PR.", agents)
        self.assertIn("review feedback or small follow-up fixes", agents)
        self.assertIn("PR descriptions must read like a useful feature report", agents)
        self.assertIn("Why the change exists", agents)
        self.assertIn("What the user or operator can do after the change", agents)
        self.assertIn("evidence obvious to a reviewer reading the", agents)

    def test_application_cases_document_representative_flows(self) -> None:
        text = Path("docs/APPLICATION_CASES.md").read_text(encoding="utf-8")

        for heading in (
            "## Case 1: Coding Request Handling",
            "## Case 2: Goal, Planning, and Deep Interview Flow",
            "## Case 3: Specialist Harness Flow",
            "## Case 4: Situation Playbook Pipeline",
            "## Case 5: Company Workflows Without CLI Knowledge",
            "## Grounded UltraQA Scenario Matrix",
            "## Release Review Checklist",
        ):
            self.assertIn(heading, text)

        for section in ("### Setup", "### User Prompt Shape", "### Expected Hermes-Facing Behavior", "### Verification", "### Current Limit"):
            self.assertIn(section, text)

        for harness in (
            "coding-handling",
            "goal-execution",
            "planning",
            "research",
            "deep-interview",
            "architect",
            "critic",
            "qa-specialist",
            "docs-specialist",
            "customer-insight-triage",
            "ops-review",
            "operating-rhythm",
            "report-package",
            "materials-package",
            "reliability-review",
            "strategy-synthesis",
            "meeting-facilitation",
            "business-research",
        ):
            self.assertIn(harness, text)
        self.assertIn("quality tier", text)
        self.assertIn("evidence ladder", text)
        self.assertIn("omh playbook recommend", text)
        self.assertIn("safe-feature-change", text)
        self.assertIn("결제 실패 피드백을 모아서 회의 주제와 다음 전략을 정리해줘", text)
        self.assertIn("omh demo grounded-score", text)
        self.assertIn("omh cases demo --all --json", text)
        self.assertIn("omh_use_case_demo_card/v1", text)
        self.assertIn("examples/use-cases/g1-g10-demo-cards.json", text)
        self.assertIn("10/10", text)
        self.assertNotIn("over 28 representative messages", text)
        matrix_start = text.index("| Scenario | User message tested | Chat route | Playbook | Coding handoff behavior | Score |")
        matrix_end = text.index("\n\nUser-facing effect:", matrix_start)
        matrix_rows = [
            line
            for line in text[matrix_start:matrix_end].splitlines()
            if line.startswith("| ") and not line.startswith("| ---")
        ][1:]
        self.assertEqual(len(matrix_rows), len(GROUNDED_SCENARIOS))
        for scenario in GROUNDED_SCENARIOS:
            self.assertIn(f"| {scenario.title} |", text)
            self.assertIn(f"`{scenario.message}`", text)
        self.assertIn("$ultraprocess research the repo", text)
        self.assertIn("feedback-triage", text)
        self.assertIn("prepare weekly ops review from customer feedback and release risks", text)
        self.assertIn("쿠버네티스 장애 상황에서 Cloudy가 적절히 진단하나?", text)
        self.assertIn("prepared_not_observed", text)
        self.assertIn("omh docs workflows --json", text)
        self.assertIn("omh probe", text)

    def test_playbook_docs_are_discoverable(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        docs_index = Path("docs/README.md").read_text(encoding="utf-8")
        playbooks = Path("docs/PLAYBOOKS.md").read_text(encoding="utf-8")
        site = Path("site/index.html").read_text(encoding="utf-8")

        self.assertNotIn("omh playbook recommend", readme)
        self.assertIn("omh playbook recommend", playbooks)
        self.assertIn("Playbooks", docs_index)
        self.assertIn("request-to-handoff", playbooks)
        self.assertIn("safe-feature-change", playbooks)
        self.assertIn("source-backed-research", playbooks)
        self.assertIn("research-department", playbooks)
        self.assertIn("operating-rhythm-history", playbooks)
        self.assertIn("scheduled-ops-blueprint", playbooks)
        self.assertIn("report-package", playbooks)
        self.assertIn("reliability-incident-review", playbooks)
        self.assertIn("binary PPTX export", playbooks)
        self.assertIn("not execution evidence", playbooks)
        self.assertIn("Situation playbooks", site)
        self.assertIn("request-to-handoff", site)
        self.assertIn("Grounded operator cases", site)
        self.assertIn("Payment failures keep showing up", site)

    def test_discord_example_uses_wrapper_native_flow(self) -> None:
        text = Path("examples/discord-bot-runtime-flow.md").read_text(encoding="utf-8")

        self.assertIn("omh chat interact --source discord --event-json event.json", text)
        self.assertIn("omh chat session start", text)
        self.assertIn("omh chat session prepare-handoff", text)
        self.assertIn("omh coding lifecycle dispatch", text)
        self.assertIn("omh coding lifecycle report", text)
        self.assertIn("omh runtime show", text)
        self.assertIn("A prepared handoff is not execution evidence.", text)
        self.assertIn("normal Discord or Slack UX", text)

    def test_chat_wrapper_examples_include_grounded_operator_transcripts(self) -> None:
        text = Path("docs/CHAT_WRAPPER_EXAMPLES.md").read_text(encoding="utf-8")
        site_docs = Path("site/docs/index.html").read_text(encoding="utf-8")

        self.assertIn("## Grounded Operator Examples", text)
        self.assertIn("## Messenger-Native OMH Entry", text)
        self.assertIn("omh_native_command_surface/v1", text)
        self.assertIn("omh_native_command_render/v1", text)
        self.assertIn("chat_response.state.workflow_explanation.why_this_workflow", text)
        self.assertIn("chat_response.state.workflow_explanation.workflow_context_card", text)
        self.assertIn("first_response_shape", text)
        self.assertIn("chat_response.state.workflow_explanation.not_evidence_yet", text)
        self.assertIn("chat_response.state.workflow_explanation.recommended_reply", text)
        self.assertIn("chat_response.state.workflow_explanation.primary_action_hint", text)
        self.assertIn("web_visual_qa_package/v1", text)
        self.assertIn("message_attachment_projection/v1", text)
        self.assertIn("delivery_observed", text)
        self.assertIn("multimodal model call by OMH", text)
        self.assertIn("Telegram can register the `omh` bot command menu", text)
        self.assertIn("Startup Product Triage", text)
        self.assertIn("Real-World QA Check", text)
        self.assertIn("Product Feature Shaping", text)
        self.assertIn("Release Evidence Review", text)
        self.assertIn("No plan or execution has started.", text)
        self.assertIn('id="operator-cases"', site_docs)
        self.assertIn("Grounded operator cases", site_docs)
        self.assertIn("omh demo grounded-score", site_docs)
        self.assertIn("omh demo chat-card-coverage", text)
        self.assertIn("omh demo chat-card-coverage", site_docs)
        self.assertIn("omh demo route-hint-alignment", text)
        self.assertIn("omh demo route-hint-alignment", site_docs)
        self.assertIn("route-hint alignment", site_docs)
        self.assertIn("generic `ack`", text)
        self.assertIn("generic <code>ack</code>", site_docs)
        self.assertIn("omh cases demo --all --json", site_docs)
        self.assertIn("omh_use_case_demo_card/v1", site_docs)
        self.assertIn("10/10", site_docs)

    def test_architecture_docs_include_visual_system_view(self) -> None:
        architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
        site_home = Path("site/index.html").read_text(encoding="utf-8")
        site_docs = Path("site/docs/index.html").read_text(encoding="utf-8")

        self.assertIn("## System View", architecture)
        self.assertIn("```mermaid", architecture)
        self.assertIn("flowchart LR", architecture)
        self.assertIn("OMH local contract layer", architecture)
        self.assertIn("prepared handoff, not execution proof", architecture)
        self.assertIn('id="architecture"', site_home)
        self.assertIn("Architecture at a glance.", site_home)
        self.assertIn("architecture-map", site_home)
        self.assertLess(site_home.index('id="architecture"'), site_home.index('id="flow"'))
        self.assertIn("Architecture at a glance", site_docs)
        self.assertIn("architecture-map", site_docs)
        self.assertIn("Runtime artifacts", site_docs)


if __name__ == "__main__":
    unittest.main()
