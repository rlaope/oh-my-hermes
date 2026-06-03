from __future__ import annotations

from pathlib import Path
import unittest

from _local_package import load_local_package

load_local_package()
from omh.skill_pack import builtin_harnesses, builtin_skill_templates


class RouterContentTests(unittest.TestCase):
    def test_router_documents_best_effort_and_recovery(self) -> None:
        router = next(skill for skill in builtin_skill_templates() if skill.name == "oh-my-hermes")

        self.assertIn("best-effort Hermes prompt guidance", router.content)
        self.assertIn("does not override Hermes core routing", router.content)
        self.assertIn("skills_list", router.content)
        self.assertIn("skill_view", router.content)
        self.assertIn("name collides", router.content)

    def test_core_skill_set_contains_major_workflows(self) -> None:
        names = {skill.name for skill in builtin_skill_templates()}

        for expected in {
            "ralph",
            "ultragoal",
            "deep-interview",
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
        self.assertIn("Fallback:", router.content)

    def test_workflow_skills_refer_to_harness_discipline(self) -> None:
        skills = {skill.name: skill for skill in builtin_skill_templates()}

        self.assertIn("Harness Discipline", skills["ultragoal"].content)
        self.assertIn("Prefer richer evidence and clearer stop conditions", skills["code-review"].content)

    def test_generated_public_content_avoids_external_runtime_branding(self) -> None:
        forbidden = ("om" + "x", "oh-my-" + "co" + "dex", "co" + "dex")
        combined = "\n".join(skill.content for skill in builtin_skill_templates()).lower()

        for term in forbidden:
            self.assertNotIn(term, combined)

    def test_public_project_files_avoid_external_runtime_branding(self) -> None:
        forbidden = ("om" + "x", "oh-my-" + "co" + "dex", "co" + "dex")
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

        for harness in ("coding-handling", "goal-execution", "planning", "deep-interview", "architect", "critic", "qa-specialist", "docs-specialist"):
            self.assertIn(harness, text)


if __name__ == "__main__":
    unittest.main()
