from __future__ import annotations

from pathlib import Path
import unittest

from _local_package import load_local_package

load_local_package()
from omh.skill_pack import builtin_definitions, builtin_harnesses, builtin_skill_templates
from omh.skills.catalog import primary_harness_for_skill
from omh.skills.render import workflow_reference_markdown


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
        self.assertIn("Verification:", router.content)
        self.assertIn("Runtime Evidence:", router.content)
        self.assertIn("Delegation:", router.content)
        self.assertIn("Fallback:", router.content)

    def test_catalog_definitions_expose_required_metadata_fields(self) -> None:
        for definition in builtin_definitions():
            self.assertTrue(definition.category, definition.name)
            self.assertTrue(definition.phase, definition.name)
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

    def test_generated_workflow_reference_matches_catalog(self) -> None:
        reference = Path("docs/WORKFLOWS.md").read_text(encoding="utf-8")

        self.assertEqual(reference, workflow_reference_markdown())
        self.assertIn("This file is generated from `src/skills/catalog.py`", reference)
        for definition in builtin_definitions():
            self.assertIn(f"### {definition.name}", reference)
            self.assertIn(f"- Category: `{definition.category}`", reference)
            self.assertIn(f"- Phase: `{definition.phase}`", reference)
            self.assertIn(f"- Hermes role: `{definition.hermes_role}`", reference)
            self.assertIn(f"- Handoff policy: {definition.handoff_policy}", reference)
        for harness in builtin_harnesses():
            self.assertIn(f"### {harness.name}", reference)
            for event in harness.artifact_events:
                self.assertIn(f"`{event}`", reference)
        self.assertIn("coding_delegation_recorded", reference)

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
            *Path(".github").rglob("*.md"),
            *Path(".github").rglob("*.yml"),
        ]

        for path in paths:
            text = path.read_text(encoding="utf-8").lower()
            for term in forbidden:
                self.assertNotIn(term, text, f"{term!r} leaked in {path}")

    def test_first_release_trust_surfaces_are_present(self) -> None:
        required_paths = [
            Path("README.md"),
            Path("AGENTS.md"),
            Path("docs/README.md"),
            Path("docs/DIRECTION.md"),
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
            Path(".github/dependabot.yml"),
            Path(".github/pull_request_template.md"),
            Path(".github/ISSUE_TEMPLATE/bug_report.yml"),
            Path(".github/ISSUE_TEMPLATE/feature_request.yml"),
            Path(".github/ISSUE_TEMPLATE/config.yml"),
        ]

        for path in required_paths:
            self.assertTrue(path.exists(), f"{path} should be present")

        readme = Path("README.md").read_text(encoding="utf-8")
        installation = Path("docs/INSTALLATION.md").read_text(encoding="utf-8")
        ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        release = Path("docs/RELEASE.md").read_text(encoding="utf-8")

        self.assertIn("curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh", readme)
        self.assertIn("[Documentation](docs/README.md)", readme)
        self.assertIn("[Installation](docs/INSTALLATION.md)", readme)
        self.assertIn("[Application Cases](docs/APPLICATION_CASES.md)", readme)
        self.assertIn("OMH_CHANNEL=stable OMH_VERSION=0.1.0", readme)
        self.assertIn("Chat Wrapper Flow", installation)
        self.assertIn("omh chat interact", installation)
        self.assertIn("python -m unittest discover -s tests", ci)
        self.assertIn("python -m compileall src", ci)
        self.assertIn("docs workflows --check", ci)
        self.assertIn("Capability probe smoke", ci)
        self.assertIn("Pinned stable install", release)
        self.assertIn("Runtime evidence smoke", release)
        self.assertIn("Capability probe status", release)

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
