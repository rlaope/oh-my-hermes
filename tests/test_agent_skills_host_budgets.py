"""The installed Agent Skills packs fit each host's listing budget and single-read cap.

Host facts come from SkillEvaluator 1.0.1's harness profiles (Apache-2.0),
verified 2026-11-01 against Claude Code 2.1.316, Codex 0.166.0 and OpenClaw
2026.10.9:
- Claude Code lists descriptions inside 1% of the context window, 8,000
  characters when the window is unknown; Codex inside 2%, 8,000 if unknown.
- OpenClaw cuts every description to 220 characters and leaves skills out of
  the list once a folder holds more than 150 skills or 18,000 description
  characters.
- OpenClaw returns a SKILL.md read only up to 16,000 weighted characters under
  a 100K-token context, counting each CJK character as 4 or more.
"""
from __future__ import annotations

import json
import unittest

LISTING_BUDGET_CHARS = 8_000  # Claude Code and Codex, context window unknown.
LISTING_MAX_SKILLS = 150  # OpenClaw.
DESCRIPTION_MAX_CHARS = 220  # OpenClaw's compact cut.
READ_CAP_CHARS = 15_000  # OpenClaw's 16,000 less room for its read wrapper.


def _description(content: str) -> str:
    line = next(line for line in content.splitlines() if line.startswith("description: "))
    return json.loads(line.removeprefix("description: "))


def _skill_files(files: dict[str, str]) -> dict[str, str]:
    return {path: content for path, content in files.items() if path.count("/") == 1 and path.endswith("/SKILL.md")}


class ListingBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from omh.install.agent_skills_projection import agent_skill_files, claude_skill_files

        portable = agent_skill_files()
        cls.packs = {".agents/skills": portable, ".claude/skills": claude_skill_files(portable)}

    def test_each_pack_fits_the_listing_budget(self):
        for root, files in self.packs.items():
            skills = _skill_files(files)
            descriptions = [_description(content) for content in skills.values()]
            with self.subTest(root=root):
                self.assertLessEqual(len(skills), LISTING_MAX_SKILLS)
                self.assertLessEqual(sum(map(len, descriptions)), LISTING_BUDGET_CHARS)
                for path, text in zip(skills, descriptions):
                    self.assertLessEqual(len(text), DESCRIPTION_MAX_CHARS, path)

    def test_every_description_is_the_whole_situation_clause(self):
        from omh.skills.catalog import builtin_definitions, omh_skill_display_name
        from omh.skills.catalog_types import omh_description

        portable = self.packs[".agents/skills"]
        for definition in builtin_definitions():
            path = f"{omh_skill_display_name(definition.name)}/SKILL.md"
            if path not in portable:
                continue
            clause = omh_description(definition.description).partition(": ")[0].rstrip(" .,;:-")
            with self.subTest(skill=path):
                self.assertTrue(_description(portable[path]).startswith(clause + "."), _description(portable[path]))

    def test_descriptions_stay_distinct(self):
        for root, files in self.packs.items():
            descriptions = [_description(content).casefold() for content in _skill_files(files).values()]
            self.assertEqual(len(descriptions), len(set(descriptions)), root)


class ReadCapTests(unittest.TestCase):
    def test_every_portable_skill_md_fits_one_read(self):
        from omh.install.agent_skills_projection import agent_skill_files
        from omh.skills.render import openclaw_read_chars

        for path, content in _skill_files(agent_skill_files()).items():
            self.assertLessEqual(openclaw_read_chars(content), READ_CAP_CHARS, path)

    def test_cjk_counts_four_per_character(self):
        from omh.skills.render import openclaw_read_chars

        self.assertEqual(openclaw_read_chars("ab"), 2)
        self.assertEqual(openclaw_read_chars("한국"), 8)
        self.assertEqual(openclaw_read_chars("漢字"), 8)
        self.assertEqual(openclaw_read_chars("é"), 1)

    def test_split_preserves_every_byte_of_the_full_body(self):
        from omh.install.agent_skills_projection import agent_skill_files
        from omh.skills.catalog import builtin_definitions, omh_skill_display_name
        from omh.skills.render import (
            PORTABLE_DETAILS_PATH, PORTABLE_DETAILS_POINTER, SkillTemplate, workflow_skill_from_definition,
        )

        files = agent_skill_files()
        split = []
        for definition in builtin_definitions():
            name = omh_skill_display_name(definition.name)
            if f"{name}/SKILL.md" not in files:
                continue
            rendered = workflow_skill_from_definition(definition, definition.name, target="agent-skills").content
            full = SkillTemplate(name, rendered).content
            details = files.get(f"{name}/{PORTABLE_DETAILS_PATH}")
            with self.subTest(skill=name):
                if details is None:
                    self.assertEqual(files[f"{name}/SKILL.md"], full)
                    continue
                split.append(name)
                self.assertEqual(files[f"{name}/SKILL.md"].count(PORTABLE_DETAILS_POINTER), 1)
                self.assertEqual(files[f"{name}/SKILL.md"].replace(PORTABLE_DETAILS_POINTER, details), full)
        # The seven bodies over the cap when the split landed; a new one must be split, not dropped.
        self.assertTrue({
            "omh-external-connector-readiness", "omh-frontend", "omh-llm-app-dev", "omh-visual-qa",
            "ulw-loop", "ulw-research", "ulw-work",
        } <= set(split), split)

    def test_split_rules(self):
        from omh.skills.render import PORTABLE_DETAILS_POINTER, PORTABLE_READ_CAP, split_for_read_cap

        small = "---\nname: x\n---\n\n# X\n\n## Catalog Metadata\n\nbar\n"
        self.assertEqual(split_for_read_cap(small), (small, None))
        meta = "## Catalog Metadata\n\n" + "- rule\n" * (PORTABLE_READ_CAP // 7)
        big = "# X\n\n## When to Use\n\nnow\n\n" + meta + "\n## Runtime Evidence\n\ntail\n"
        head, details = split_for_read_cap(big)
        self.assertEqual(details, meta + "\n")
        self.assertIn(PORTABLE_DETAILS_POINTER, head)
        self.assertTrue(head.endswith("## Runtime Evidence\n\ntail\n"))
        self.assertEqual(head.replace(PORTABLE_DETAILS_POINTER, details), big)
        with self.assertRaises(ValueError):
            split_for_read_cap("# X\n" + "word " * PORTABLE_READ_CAP)


class HermesBodiesUnchangedTests(unittest.TestCase):
    def test_hermes_skills_are_not_split(self):
        from omh.skills.packaging import builtin_skill_reference_templates

        self.assertFalse([t for t in builtin_skill_reference_templates() if t.relative_path == "references/details.md"])


if __name__ == "__main__":
    unittest.main()
