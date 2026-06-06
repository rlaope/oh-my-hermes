from __future__ import annotations

from pathlib import Path
import unittest

from _local_package import load_local_package

load_local_package()
from omh.skill_pack import builtin_definitions, builtin_harnesses, builtin_skill_templates
from omh.runtime.records import validate_harness_quality
from omh.skills.catalog import harness_quality_contract, primary_harness_for_skill
from omh.skills.render import workflow_reference_markdown, workflow_reference_payload


class RouterContentTests(unittest.TestCase):
    def test_router_documents_best_effort_and_recovery(self) -> None:
        router = next(skill for skill in builtin_skill_templates() if skill.name == "oh-my-hermes")

        self.assertIn("best-effort Hermes prompt guidance", router.content)
        self.assertIn("does not override Hermes core routing", router.content)
        self.assertIn("omh chat route", router.content)
        self.assertIn("omh coding delegate", router.content)
        self.assertIn("deterministic wrapper-side decision layer", router.content)
        self.assertIn("Skill Role Classification", router.content)
        self.assertIn("advisory wrapper guidance", router.content)
        self.assertIn("This role metadata is advisory", router.content)
        self.assertIn("Hermes should retain routing, web/source research, deep interview, planning, status, and evidence narration", router.content)
        self.assertIn("prepare a Codex handoff", router.content)
        self.assertIn("prepared_not_observed", router.content)
        self.assertIn("skills_list", router.content)
        self.assertIn("skill_view", router.content)
        self.assertIn("name collides", router.content)

    def test_core_skill_set_contains_major_workflows(self) -> None:
        names = {skill.name for skill in builtin_skill_templates()}

        for expected in {
            "ralph",
            "ultragoal",
            "ultrawork",
            "deep-interview",
            "web-research",
            "team",
            "ultraqa",
            "plan",
            "ralplan",
            "code-review",
        }:
            self.assertIn(expected, names)

    def test_router_renders_representative_harness_registry(self) -> None:
        router = next(skill for skill in builtin_skill_templates() if skill.name == "oh-my-hermes")
        harnesses = {harness.name for harness in builtin_harnesses()}

        self.assertEqual(
            {
                "coding-handling",
                "goal-execution",
                "planning",
                "research",
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
        self.assertIn("Inputs:", router.content)
        self.assertIn("Outputs:", router.content)
        self.assertIn("Quality tier:", router.content)
        self.assertIn("Quality Bar:", router.content)
        self.assertIn("Evidence Ladder:", router.content)
        self.assertIn("Wrapper Actions:", router.content)
        self.assertIn("Overclaim Guards:", router.content)
        self.assertIn("Verification:", router.content)
        self.assertIn("Runtime Evidence:", router.content)
        self.assertIn("Delegation:", router.content)
        self.assertIn("Fallback:", router.content)

    def test_catalog_definitions_expose_required_metadata_fields(self) -> None:
        for definition in builtin_definitions():
            self.assertTrue(definition.category, definition.name)
            self.assertTrue(definition.phase, definition.name)
            self.assertTrue(definition.quality_tier, definition.name)
            self.assertGreaterEqual(len(definition.quality_bar), 1, definition.name)
            self.assertGreaterEqual(len(definition.required_inputs), 1, definition.name)
            self.assertGreaterEqual(len(definition.expected_outputs), 1, definition.name)
            self.assertGreaterEqual(len(definition.artifact_expectations), 1, definition.name)
            self.assertGreaterEqual(len(definition.safety_rules), 1, definition.name)
            self.assertTrue(definition.hermes_role, definition.name)
            self.assertTrue(definition.handoff_policy, definition.name)

    def test_catalog_marks_retained_and_codex_handoff_skills(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}

        self.assertEqual(definitions["deep-interview"].hermes_role, "retained-cognition")
        self.assertEqual(definitions["web-research"].hermes_role, "retained-cognition")
        self.assertEqual(definitions["ralplan"].hermes_role, "retained-cognition")
        self.assertEqual(definitions["ultrawork"].hermes_role, "codex-handoff-guidance")
        self.assertEqual(definitions["ai-slop-cleaner"].hermes_role, "codex-handoff-guidance")
        self.assertIn("Codex", definitions["ultrawork"].handoff_policy)
        self.assertEqual(primary_harness_for_skill("web-research"), "research")
        self.assertEqual(primary_harness_for_skill("best-practice-research"), "research")
        self.assertEqual(primary_harness_for_skill("autoresearch-goal"), "research")

    def test_workflow_skills_refer_to_harness_discipline(self) -> None:
        skills = {skill.name: skill for skill in builtin_skill_templates()}

        self.assertIn("Harness Discipline", skills["ultragoal"].content)
        self.assertIn("Catalog Metadata", skills["ultragoal"].content)
        self.assertIn("Category: `execution`", skills["ultragoal"].content)
        self.assertIn("Phase: `durable-goals`", skills["ultragoal"].content)
        self.assertIn("Hermes role: `codex-handoff-guidance`", skills["ultragoal"].content)
        self.assertIn("Handoff policy:", skills["ultragoal"].content)
        self.assertIn("Runtime Evidence", skills["ultragoal"].content)
        self.assertIn("omh runtime record --skill ultragoal --harness goal-execution --status started", skills["ultragoal"].content)
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
        self.assertEqual(harnesses["coding-handling"]["quality_tier"], "handoff-gated")
        self.assertIn("coding_delegation_prepared", harnesses["coding-handling"]["evidence_ladder"])
        self.assertIn("send_to_codex", harnesses["coding-handling"]["wrapper_actions"])
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
        for definition in builtin_definitions():
            self.assertIn(f"### {definition.name}", reference)
            self.assertIn(f"- Category: `{definition.category}`", reference)
            self.assertIn(f"- Phase: `{definition.phase}`", reference)
            self.assertIn(f"- Hermes role: `{definition.hermes_role}`", reference)
            self.assertIn(f"- Quality tier: `{definition.quality_tier}`", reference)
            self.assertIn(f"- Handoff policy: {definition.handoff_policy}", reference)
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

    def test_generated_public_content_avoids_external_runtime_branding(self) -> None:
        forbidden = ("om" + "x", "oh-my-" + "co" + "dex")
        combined = "\n".join(skill.content for skill in builtin_skill_templates()).lower()

        for term in forbidden:
            self.assertNotIn(term, combined)

    def test_public_project_files_avoid_external_runtime_branding(self) -> None:
        forbidden = ("om" + "x", "oh-my-" + "co" + "dex")
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
            *Path("examples").rglob("*"),
            *Path("site").rglob("*"),
            *Path(".github").rglob("*.md"),
            *Path(".github").rglob("*.yml"),
        ]

        for path in paths:
            if path.is_dir():
                continue
            if path.suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            text = path.read_text(encoding="utf-8").lower()
            for term in forbidden:
                self.assertNotIn(term, text, f"{term!r} leaked in {path}")

    def test_first_release_trust_surfaces_are_present(self) -> None:
        required_paths = [
            Path("README.md"),
            Path("AGENTS.md"),
            Path("docs/README.md"),
            Path("docs/DIRECTION.md"),
            Path("docs/HARNESS_QUALITY.md"),
            Path("docs/INSTALLATION.md"),
            Path("docs/APPLICATION_CASES.md"),
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
            Path("site/styles.css"),
            Path("site/assets/hermes-agent-hero.png"),
        ]

        for path in required_paths:
            self.assertTrue(path.exists(), f"{path} should be present")

        readme = Path("README.md").read_text(encoding="utf-8")
        installation = Path("docs/INSTALLATION.md").read_text(encoding="utf-8")
        ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        pages = Path(".github/workflows/pages.yml").read_text(encoding="utf-8")
        release = Path("docs/RELEASE.md").read_text(encoding="utf-8")
        harness_quality = Path("docs/HARNESS_QUALITY.md").read_text(encoding="utf-8")
        site = Path("site/index.html").read_text(encoding="utf-8")
        site_css = Path("site/styles.css").read_text(encoding="utf-8")

        self.assertIn("curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh", readme)
        self.assertIn("https://rlaope.github.io/oh-my-hermes-agent/", readme)
        self.assertIn("[Documentation](docs/README.md)", readme)
        self.assertIn("[Installation](docs/INSTALLATION.md)", readme)
        self.assertIn("[Application Cases](docs/APPLICATION_CASES.md)", readme)
        self.assertIn("[GitHub Pages site](site/index.html)", readme)
        self.assertIn("OMH_CHANNEL=stable OMH_VERSION=<version>", readme)
        self.assertIn("v<version>", readme)
        self.assertIn("Most users should start with one health check", readme)
        self.assertIn("## Command Surface", readme)
        self.assertIn("omh docs workflows --json", readme)
        self.assertIn("omh harness validate", readme)
        self.assertIn("Root README intentionally shows the small public surface", readme)
        self.assertNotIn("Useful local and wrapper-debug commands", readme)
        self.assertIn("Chat Wrapper Flow", installation)
        self.assertIn("omh chat interact", installation)
        self.assertIn("harness_quality/v1", installation)
        self.assertIn("omh docs workflows --json", installation)
        self.assertIn("omh harness inspect planning", installation)
        self.assertIn("wrapper_actions", harness_quality)
        self.assertIn("overclaim_guards", harness_quality)
        self.assertIn("harness_progress/v1", harness_quality)
        self.assertIn("python -m unittest discover -s tests", ci)
        self.assertIn("python -m compileall src", ci)
        self.assertIn("docs workflows --check", ci)
        self.assertIn("Capability probe smoke", ci)
        self.assertIn("actions/upload-pages-artifact@v4", pages)
        self.assertIn("actions/deploy-pages@v4", pages)
        self.assertIn("site/**", pages)
        self.assertIn("docs workflows --check", pages)
        self.assertIn("harness validate", pages)
        self.assertIn("Pinned stable install", release)
        self.assertIn("Runtime evidence smoke", release)
        self.assertIn("Harness catalog validation status", release)
        self.assertIn("GitHub Pages workflow status", release)
        self.assertIn("Capability probe status", release)
        self.assertIn("OMH", site)
        self.assertIn("harness_progress/v1", site)
        self.assertIn("assets/hermes-agent-hero.png", site_css)

    def test_direction_and_agent_contract_lock_product_boundary(self) -> None:
        direction = Path("docs/DIRECTION.md").read_text(encoding="utf-8")
        docs_index = Path("docs/README.md").read_text(encoding="utf-8")
        agents = Path("AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("OMHM is a Hermes-native wrapper orchestration layer.", direction)
        self.assertIn("Raise the product's capability level by strengthening contracts", direction)
        self.assertIn("Hermes owns:", direction)
        self.assertIn("OMH owns:", direction)
        self.assertIn("Codex-like executors own:", direction)
        self.assertIn("prepared_not_observed", direction)
        self.assertIn("One user goal should normally produce one PR.", direction)
        self.assertIn("Keep users command-agnostic in chat.", direction)
        self.assertIn("The goal is parity of seriousness, not parity of implementation shape.", direction)
        self.assertIn("This directory is the public operating map", docs_index)
        self.assertIn("prepared versus observed evidence", docs_index)
        self.assertIn("Chat users should remain command-agnostic.", docs_index)
        self.assertIn("Harness Quality Contract", docs_index)
        self.assertIn("Do not turn OMHM into a hidden Hermes runtime patch", agents)
        self.assertIn("One user goal should normally produce one PR.", agents)
        self.assertIn("review feedback or small follow-up fixes", agents)

    def test_application_cases_document_representative_flows(self) -> None:
        text = Path("docs/APPLICATION_CASES.md").read_text(encoding="utf-8")

        for heading in (
            "## Case 1: Coding Request Handling",
            "## Case 2: Goal, Planning, and Deep Interview Flow",
            "## Case 3: Specialist Harness Flow",
            "## Release Review Checklist",
        ):
            self.assertIn(heading, text)

        for section in ("### Setup", "### User Prompt Shape", "### Expected Hermes-Facing Behavior", "### Verification", "### Current Limit"):
            self.assertIn(section, text)

        for harness in ("coding-handling", "goal-execution", "planning", "research", "deep-interview", "architect", "critic", "qa-specialist", "docs-specialist"):
            self.assertIn(harness, text)
        self.assertIn("quality tier", text)
        self.assertIn("evidence ladder", text)
        self.assertIn("omh docs workflows --json", text)
        self.assertIn("omh probe", text)

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


if __name__ == "__main__":
    unittest.main()
