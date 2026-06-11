from __future__ import annotations

import inspect
from pathlib import Path
import unittest

from _local_package import load_local_package

load_local_package()
from omh.routing import recommend as recommend_module
from omh.roles import role_definitions, role_file_markdown, roles_reference_markdown
from omh.skill_pack import builtin_definitions, builtin_harnesses, builtin_skill_templates
from omh.runtime.records import validate_harness_quality
from omh.skills.catalog import (
    SkillDefinition,
    catalog_intent_delegation_skill_names,
    harness_quality_contract,
    primary_harness_for_skill,
    retained_delegation_skill_names,
)
from omh.skills.render import workflow_reference_markdown, workflow_reference_payload


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


class RouterContentTests(unittest.TestCase):
    def test_router_documents_best_effort_and_recovery(self) -> None:
        router = next(skill for skill in builtin_skill_templates() if skill.name == "oh-my-hermes")

        self.assertIn("best-effort Hermes prompt guidance", router.content)
        self.assertIn("does not override Hermes core routing", router.content)
        self.assertIn("omh chat route", router.content)
        self.assertIn("omh coding delegate", router.content)
        self.assertIn("deterministic wrapper-side decision layer", router.content)
        self.assertIn("Normal users should talk to Hermes Agent", router.content)
        self.assertIn("Hermes-native install paths should converge", router.content)
        self.assertIn("skills.external_dirs", router.content)
        self.assertIn("Skill Role Classification", router.content)
        self.assertIn("advisory wrapper guidance", router.content)
        self.assertIn("This role metadata is advisory", router.content)
        self.assertIn("Responsibility Roles", router.content)
        self.assertIn("Responsibility role details are generated in `docs/WORKFLOWS.md`", router.content)
        self.assertIn("Full per-skill handoff policies live in generated workflow skills", router.content)
        self.assertIn("Hermes should retain routing, web/source research, deep interview, planning, status, and evidence narration", router.content)
        self.assertIn("selected executor profile", router.content)
        self.assertIn("prepared_not_observed", router.content)
        self.assertIn("Multi-Agent Target Awareness", router.content)
        self.assertIn("omh_target_topology/v1", router.content)
        self.assertIn("single_to_multi", router.content)
        self.assertIn("skills_list", router.content)
        self.assertIn("skill_view", router.content)
        self.assertIn("name collides", router.content)

    def test_role_surface_docs_match_catalog_and_avoid_runtime_claims(self) -> None:
        roles_doc = Path("docs/ROLES.md").read_text(encoding="utf-8")

        self.assertEqual(roles_doc, roles_reference_markdown())
        self.assertIn("request-to-handoff", roles_doc)
        self.assertIn("roles are responsibility descriptors, not runtime agents", roles_doc.lower())
        for role in role_definitions():
            role_file = Path("roles") / f"{role.id}.md"
            text = role_file.read_text(encoding="utf-8")
            self.assertEqual(text, role_file_markdown(role))
            self.assertIn("responsibility descriptor, not a runtime agent", text)
            self.assertIn(role.evidence_boundary, text)
            self.assertNotIn("secretly", text.lower())
            if role.id == "coding-handoff":
                self.assertIn("not executor dispatch", text)

    def test_core_skill_set_contains_major_workflows(self) -> None:
        names = {skill.name for skill in builtin_skill_templates()}

        for expected in {
            "ralph",
            "ultragoal",
            "ultrawork",
            "deep-interview",
            "web-research",
            "research-brief",
            "strategy-brief",
            "meeting-brief",
            "feedback-triage",
            "ops-review",
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
        }:
            self.assertIn(expected, names)

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
            "goal-loop": "start_goal_loop",
            "process": "start_ultraprocess",
        }

        for category, next_action in expected.items():
            with self.subTest(category=category):
                self.assertEqual(recommend_module._CATEGORY_POLICIES[category].next_action, next_action)

        self.assertEqual(recommend_module._SKILL_POLICIES["cancel"].next_action, "cancel")

        for helper in (
            recommend_module._next_action,
            recommend_module._evidence_boundary,
            recommend_module._wrapper_guidance,
        ):
            source = inspect.getsource(helper)
            self.assertIn("_policy_for", source)
            self.assertNotIn("if definition.category", source)

    def test_repo_root_tap_skills_match_generated_templates(self) -> None:
        templates = {template.name: template for template in builtin_skill_templates()}

        for name, template in templates.items():
            path = Path("skills") / name / "SKILL.md"
            self.assertTrue(path.exists(), f"{path} should be present for Hermes skill taps")
            self.assertEqual(path.read_text(encoding="utf-8"), template.content)

        self.assertEqual({path.parent.name for path in Path("skills").glob("*/SKILL.md")}, set(templates))

    def test_router_renders_representative_harness_registry(self) -> None:
        router = next(skill for skill in builtin_skill_templates() if skill.name == "oh-my-hermes")
        harnesses = {harness.name for harness in builtin_harnesses()}

        self.assertEqual(
            {
                "coding-handling",
                "goal-execution",
                "planning",
                "research",
                "business-research",
                "strategy-synthesis",
                "meeting-facilitation",
                "customer-insight-triage",
                "ops-review",
                "app-delivery-loop",
                "goal-loop",
                "deep-interview",
                "architect",
                "critic",
                "qa-specialist",
                "docs-specialist",
            },
            harnesses,
        )
        self.assertIn("Representative Harness Registry", router.content)
        self.assertIn("quality lanes, not proof that a separate runtime role exists", router.content)
        for harness in harnesses:
            self.assertIn(f"`{harness}`", router.content)
        self.assertIn("Tier `", router.content)
        self.assertIn("Ladder:", router.content)
        self.assertIn("Actions:", router.content)
        self.assertIn("Privacy `metadata_only`", router.content)
        self.assertNotIn("Inputs:", router.content)
        self.assertNotIn("Quality Bar:", router.content)

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

        self.assertEqual(definitions["deep-interview"].hermes_role, "retained-cognition")
        self.assertEqual(definitions["web-research"].hermes_role, "retained-cognition")
        self.assertEqual(definitions["ralplan"].hermes_role, "retained-cognition")
        self.assertEqual(definitions["ultraprocess"].hermes_role, "retained-cognition")
        self.assertEqual(
            definitions["ultraprocess"].description,
            "[omh] Ultra Process - Research - Ralplan - Ultragoal - Code Review - Sync Circle: one PR-ready delivery cycle.",
        )
        self.assertEqual(definitions["ultrawork"].hermes_role, "codex-handoff-guidance")
        self.assertEqual(definitions["ai-slop-cleaner"].hermes_role, "codex-handoff-guidance")
        self.assertIn("selected executor", definitions["ultrawork"].handoff_policy)
        self.assertIn("selected executor handoff", definitions["ultraprocess"].handoff_policy)
        self.assertEqual(primary_harness_for_skill("web-research"), "research")
        self.assertEqual(primary_harness_for_skill("research-brief"), "business-research")
        self.assertEqual(primary_harness_for_skill("strategy-brief"), "strategy-synthesis")
        self.assertEqual(primary_harness_for_skill("meeting-brief"), "meeting-facilitation")
        self.assertEqual(primary_harness_for_skill("feedback-triage"), "customer-insight-triage")
        self.assertEqual(primary_harness_for_skill("ops-review"), "ops-review")
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
                "strategy-brief",
                "meeting-brief",
                "feedback-triage",
                "ops-review",
                "idea-to-deploy",
                "cto-loop",
                "deploy-and-monitor",
                "loop",
                "ultraprocess",
            }.issubset(catalog_intent_retained)
        )

    def test_workflow_skills_refer_to_harness_discipline(self) -> None:
        skills = {skill.name: skill for skill in builtin_skill_templates()}

        self.assertIn("Harness Discipline", skills["ultragoal"].content)
        self.assertIn("Catalog Metadata", skills["ultragoal"].content)
        self.assertIn("Category: `execution`", skills["ultragoal"].content)
        self.assertIn("Phase: `durable-goals`", skills["ultragoal"].content)
        self.assertIn("Hermes role: `codex-handoff-guidance`", skills["ultragoal"].content)
        self.assertIn("Handoff policy:", skills["ultragoal"].content)
        self.assertIn("Runtime Evidence", skills["ultragoal"].content)
        self.assertIn("omh_target_topology/v1", skills["ultragoal"].content)
        self.assertIn("active_agent_count", skills["ultragoal"].content)
        self.assertIn("omh runtime record --skill ultragoal --harness goal-execution --status started", skills["ultragoal"].content)
        self.assertIn("loop_cycle/v1", skills["loop"].content)
        self.assertIn("permission profile", skills["loop"].content)
        self.assertIn("single-cycle-plan-to-pr", skills["ultraprocess"].content)
        self.assertIn("Do not continue into a repeated feedback loop", skills["ultraprocess"].content)
        self.assertIn("code-review gate", skills["ultraprocess"].content)
        self.assertIn("docs-specialist", skills["ultraprocess"].content)
        self.assertIn("Prefer richer evidence and clearer stop conditions", skills["code-review"].content)

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
        self.assertIn("why_this_exists", skills["oh-my-hermes"])
        self.assertIn("do_not_use_when", skills["oh-my-hermes"])
        self.assertIn("good_example", skills["oh-my-hermes"])
        self.assertIn("bad_example", skills["oh-my-hermes"])
        self.assertIn("routing conservative", skills["oh-my-hermes"]["why_this_exists"])
        self.assertIn("Use OMH request-to-handoff", skills["oh-my-hermes"]["good_example"]["prompt"])
        self.assertEqual(harnesses["coding-handling"]["quality_tier"], "handoff-gated")
        self.assertIn("coding_delegation_prepared", harnesses["coding-handling"]["evidence_ladder"])
        self.assertIn("send_to_codex", harnesses["coding-handling"]["wrapper_actions"])
        self.assertEqual(harnesses["app-delivery-loop"]["quality_tier"], "delivery-gated")
        self.assertIn("deploy_monitor_observed_when_available", harnesses["app-delivery-loop"]["evidence_ladder"])
        self.assertIn("record_monitor_signal", harnesses["app-delivery-loop"]["wrapper_actions"])
        self.assertEqual(harnesses["goal-loop"]["quality_tier"], "loop-gated")
        self.assertIn("feedback_gate_evaluated", harnesses["goal-loop"]["evidence_ladder"])
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
        for definition in builtin_definitions():
            self.assertIn(f"### {definition.name}", reference)
            self.assertIn(f"- Category: `{definition.category}`", reference)
            self.assertIn(f"- Phase: `{definition.phase}`", reference)
            self.assertIn(f"- Hermes role: `{definition.hermes_role}`", reference)
            self.assertIn(f"- Quality tier: `{definition.quality_tier}`", reference)
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
            Path("roles/research-lead.md"),
            Path("roles/planning-lead.md"),
            Path("roles/review-gate.md"),
            Path("roles/coding-handoff.md"),
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
            Path("site/docs/intent-to-plan/index.html"),
            Path("site/docs/product-ops/index.html"),
            Path("site/docs/executor-handoff/index.html"),
            Path("site/styles.css"),
            Path("site/assets/hermes-agent-hero.png"),
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
        site = Path("site/index.html").read_text(encoding="utf-8")
        site_docs = Path("site/docs/index.html").read_text(encoding="utf-8")
        site_loop = Path("site/docs/loop/index.html").read_text(encoding="utf-8")
        site_intent = Path("site/docs/intent-to-plan/index.html").read_text(encoding="utf-8")
        site_product_ops = Path("site/docs/product-ops/index.html").read_text(encoding="utf-8")
        site_handoff = Path("site/docs/executor-handoff/index.html").read_text(encoding="utf-8")
        site_css = Path("site/styles.css").read_text(encoding="utf-8")

        self.assertIn("hermes skills tap add rlaope/oh-my-hermes", readme)
        self.assertIn("hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes", readme)
        self.assertIn("curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh", readme)
        self.assertIn("https://rlaope.github.io/oh-my-hermes/", readme)
        self.assertIn("[Documentation](docs/README.md)", readme)
        self.assertIn("[Installation](docs/INSTALLATION.md)", readme)
        self.assertIn("[Agent Install](INSTALL_FOR_AGENTS.md)", readme)
        self.assertIn("[Roles](docs/ROLES.md)", readme)
        self.assertIn("[Application Cases](docs/APPLICATION_CASES.md)", readme)
        self.assertIn("[GitHub Pages site](site/index.html)", readme)
        self.assertIn("Have you ever felt that Hermes Agent is powerful", readme)
        self.assertIn("ready-to-use workflows such as", readme)
        self.assertIn("`web-research`, `doctor`, `idea-to-deploy`, `ultragoal`, `loop`, and", readme)
        self.assertIn("`ultraprocess`", readme)
        self.assertIn("Optional team profile packs", readme)
        self.assertIn("omh profile list", readme)
        self.assertIn("omh profile inspect cto-loop", readme)
        self.assertIn("omh setup --profile-pack cto-loop", readme)
        self.assertIn("CTO, PM, Dev, QA, Security, and Ops", readme)
        self.assertIn("not installed by default", readme)
        self.assertIn("OMH_CHANNEL=stable OMH_VERSION=<version>", readme)
        self.assertIn("v<version>", readme)
        self.assertIn("`omh setup` installs generated skills", readme)
        self.assertIn("omh setup", readme)
        self.assertIn("omh doctor", readme)
        self.assertLess(readme.index("## Quick Start"), readme.index("## Why OMH"))
        quick_start = readme.split("## Quick Start", 1)[1].split("## Why OMH", 1)[0]
        self.assertIn("curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh", quick_start)
        self.assertIn("omh setup", quick_start)
        self.assertIn("Use OMH request-to-handoff for: I want to safely add a feature to this repo.", quick_start)
        self.assertIn("name the responsible role", quick_start)
        self.assertLess(quick_start.index("curl -fsSL"), quick_start.index("hermes skills tap add"))
        self.assertNotIn("## Backend / Operator Surface", readme)
        self.assertNotIn("## Wrapper Backend Flow", readme)
        self.assertNotIn("## What Gets Recorded", readme)
        self.assertNotIn("omh docs workflows --json", readme)
        self.assertNotIn("Useful local and wrapper-debug commands", readme)
        self.assertIn("Install Path A: Hermes-Native Skill Tap", installation)
        self.assertIn("Agent Install Protocol", installation)
        self.assertIn("hermes_native_setup/v1", installation)
        self.assertNotIn("OMH_WITH_PLUGIN=1", installation)
        self.assertIn("OMH_PROFILE_PACKS=cto-loop,startup-delivery", installation)
        self.assertIn("OMH_DEFAULT_EXECUTOR=claude-code", installation)
        self.assertIn("OMH_SETUP_ARGS=\"--dry-run\"", installation)
        self.assertIn("The installer also prints the installed `omh` command path", installation)
        self.assertIn("isolated OMH virtual environment", installation)
        self.assertIn("add the printed directory to", installation)
        self.assertIn("Use OMH request-to-handoff for: I want to safely add a feature to this repo.", installation)
        self.assertIn("name the responsible", installation)
        self.assertIn("Hermes CLI Release Smoke", installation)
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
        self.assertIn("Role Surface", docs_readme)
        self.assertIn("Agent Install Protocol", docs_readme)
        self.assertIn("python -m unittest discover -s tests", ci)
        self.assertIn("python -m compileall src", ci)
        self.assertIn("docs workflows --check", ci)
        self.assertIn("Capability probe smoke", ci)
        self.assertIn("Hermes release smoke plan", ci)
        self.assertIn("release hermes-smoke", ci)
        self.assertRegex(pages, r"actions/upload-pages-artifact@v[0-9]+")
        self.assertRegex(pages, r"actions/deploy-pages@v[0-9]+")
        self.assertIn("pages: write", pages)
        self.assertIn("enablement: true", pages)
        self.assertIn("site/**", pages)
        self.assertIn("docs workflows --check", pages)
        self.assertIn("harness validate", pages)
        self.assertIn("Pinned stable install", release)
        self.assertIn("Runtime evidence smoke", release)
        self.assertIn("Harness catalog validation status", release)
        self.assertIn("GitHub Pages workflow status", release)
        self.assertIn("Capability probe status", release)
        self.assertIn("Hermes CLI Install Smoke", release)
        self.assertIn("omh release hermes-smoke --live --install-path tap --target-confirmed", release)
        self.assertIn("--hermes-home /tmp/hermes-smoke release hermes-smoke --live --install-path setup", release)
        self.assertIn("hermes skills check oh-my-hermes", release)
        self.assertIn("uv build", release)
        self.assertIn("oh_my_hermes-1.0.0-py3-none-any.whl", release)
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
        self.assertIn('href="docs/">Read docs</a>', site)
        self.assertIn('id="real-use"', site)
        self.assertIn("From install to real use", site)
        self.assertIn("high barrier to entry", site)
        self.assertIn("web-research", site)
        self.assertIn("doctor", site)
        self.assertIn("idea-to-deploy", site)
        self.assertIn("ultragoal", site)
        self.assertNotIn("usage-skill", site)
        self.assertIn("First Hermes prompt", site)
        self.assertIn("Use OMH request-to-handoff for: I want to safely add a feature to this repo.", site)
        self.assertIn("request-to-handoff", site)
        self.assertIn("planning-lead", site)
        self.assertIn("Prepared is not observed", site)
        self.assertIn("Routing is not plan acceptance, dispatch, or execution evidence.", site)
        self.assertIn("Loop is now a flagship OMH lane.", site)
        self.assertIn("<h3>Loop!</h3>", site)
        self.assertIn('<a class="loop-spotlight" href="docs/loop/"', site)
        self.assertIn('href="docs/loop/"', site)
        self.assertIn('href="docs/intent-to-plan/"', site)
        self.assertIn('href="docs/product-ops/"', site)
        self.assertIn('href="docs/executor-handoff/"', site)
        self.assertIn("Hermes Agent Integration Runbook", site_docs)
        self.assertIn("examples/wrapper-golden/hermes-agent-integration.json", site_docs)
        self.assertIn("Role surface", site_docs)
        self.assertIn("docs/ROLES.md", site_docs)
        self.assertIn("INSTALL_FOR_AGENTS.md", site_docs)
        self.assertIn("request-to-handoff", site_docs)
        self.assertIn("planning-lead", site_docs)
        self.assertIn("Routing is not plan acceptance, dispatch, or execution evidence.", site_docs)
        self.assertIn('<a class="loop-spotlight loop-spotlight--docs" href="loop/"', site_docs)
        self.assertIn('<span class="button button--primary" aria-hidden="true">Open Loop docs</span>', site_docs)
        self.assertIn("../assets/omh-loop-engineering.png", site_docs)
        self.assertIn('href="intent-to-plan/"', site_docs)
        self.assertIn('href="product-ops/"', site_docs)
        self.assertIn('href="executor-handoff/"', site_docs)
        self.assertIn("Loop Engineering", site_loop)
        self.assertIn("After harness engineering, Loop Engineering becomes the next", site_loop)
        self.assertNotIn("하네스 엔지니어링", site_loop)
        self.assertIn("../../assets/omh-loop-engineering.png", site_loop)
        self.assertIn("loop_runtime/v1", site_loop)
        self.assertIn("loop_engineering/v1", site_loop)
        self.assertIn("Automation, worktree, skill, connector, and subagent blocks", site_loop)
        self.assertIn("fan-out, adversarial verification, tournament, and triage batch", site_loop)
        self.assertIn("Cost policy keeps reads bounded", site_loop)
        self.assertIn("A loop tick is not execution", site_loop)
        self.assertIn("Intent to plan", site_intent)
        self.assertIn("deep-interview", site_intent)
        self.assertIn("Company and product ops", site_product_ops)
        self.assertIn("feedback-triage", site_product_ops)
        self.assertIn("Executor-ready handoff", site_handoff)
        self.assertIn("Codex, Claude Code", site_handoff)
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
        hero_command = site.split('aria-label="OMH quick start commands"', 1)[1].split("</code>", 1)[0]
        self.assertIn("curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh", hero_command)
        self.assertIn("omh setup", hero_command)
        self.assertNotIn("omh doctor", hero_command)
        self.assertIn("assets/omh-loop-engineering.png", site)
        self.assertTrue(Path("site/assets/omh-loop-engineering.png").is_file())
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
        self.assertIn("assets/hermes-agent-hero.png", site_css)
        self.assertIn(".loop-spotlight", site_css)
        self.assertIn(".feature-flow", site_css)

    def test_direction_and_agent_contract_lock_product_boundary(self) -> None:
        direction = Path("docs/DIRECTION.md").read_text(encoding="utf-8")
        docs_index = Path("docs/README.md").read_text(encoding="utf-8")
        agents = Path("AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("OMH is a Hermes-native wrapper orchestration layer.", direction)
        self.assertIn("Raise the product's capability level by strengthening contracts", direction)
        self.assertIn("Hermes owns:", direction)
        self.assertIn("OMH owns:", direction)
        self.assertIn("Selected coding executors own:", direction)
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
        self.assertIn("Startup Product Triage", text)
        self.assertIn("Real-World QA Check", text)
        self.assertIn("Product Feature Shaping", text)
        self.assertIn("Release Evidence Review", text)
        self.assertIn("No plan or execution has started.", text)
        self.assertIn('id="operator-cases"', site_docs)
        self.assertIn("Grounded operator cases", site_docs)

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
