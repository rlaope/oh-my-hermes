from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli
from omh.catalogs.roles import roles_reference_markdown
from omh.routing import recommend as recommend_module
from omh.skill_pack import (
    CORE_PROFILE_SKILLS,
    CORE_SKILLS,
    builtin_definitions,
    builtin_skill_templates,
)
from omh.skills.catalog import installable_skill_names
from omh.wrapper.contract import VISIBLE_ACTIONS


def _definition(name: str):
    for definition in builtin_definitions():
        if definition.name == name:
            return definition
    raise AssertionError(f"skill definition not found: {name}")


def _template_content(name: str) -> str:
    for template in builtin_skill_templates():
        if template.name == name:
            return template.content
    raise AssertionError(f"skill template not found: {name}")


class MemorySyncSkillTests(unittest.TestCase):
    def test_memory_sync_skill_registered(self) -> None:
        self.assertIn("memory-sync", installable_skill_names())
        definition = _definition("memory-sync")
        self.assertEqual(definition.category, "memory")
        self.assertEqual(definition.hermes_role, "memory-keeper")
        self.assertEqual(
            recommend_module._SKILL_POLICIES["memory-sync"].next_action,
            "prepare_memory_sync",
        )
        required_triggers = {
            "memory-sync",
            "기억 정리",
            "메모리 정리",
            "메모리 점검",
            "기억 점검",
            "MEMORY.md",
            "USER.md",
        }
        self.assertTrue(
            required_triggers.issubset(set(definition.triggers)),
            required_triggers.difference(set(definition.triggers)),
        )

    def test_memory_curation_review_removed(self) -> None:
        self.assertNotIn("memory-curation-review", installable_skill_names())
        self.assertFalse(Path("skills/memory-curation-review").exists())
        self.assertNotIn("prepare_memory_curation_review", VISIBLE_ACTIONS)

    def test_memory_sync_skill_golden_strings(self) -> None:
        content = _template_content("memory-sync")
        for anchor in (
            "원문 그대로 인용",
            "출처를 추정하거나 지어내지",
            "승인 전에는 어떤 파일도",
            "2,200자",
            "1,375자",
        ):
            self.assertIn(anchor, content, anchor)

    def test_memory_sync_skill_context_rail_markers(self) -> None:
        markers = ("OMH Context Rail", "not a standalone executor", "Prepared OMH routing")
        template_content = _template_content("memory-sync")
        on_disk = Path("skills/memory-sync/SKILL.md").read_text(encoding="utf-8")
        for marker in markers:
            self.assertIn(marker, template_content, marker)
            self.assertIn(marker, on_disk, marker)

    def test_memory_sync_full_only(self) -> None:
        self.assertNotIn("memory-sync", CORE_PROFILE_SKILLS)
        self.assertEqual(len(CORE_SKILLS), 5)
        self.assertEqual(len(CORE_PROFILE_SKILLS), 9)


class DocsRolesCommandTests(unittest.TestCase):
    def test_docs_roles_command_check(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "ROLES.md"

            status, stdout, stderr = run_cli(["docs", "roles", "--output", str(output)])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertTrue(output.exists())
            self.assertIn("written", stdout)
            self.assertEqual(output.read_text(encoding="utf-8"), roles_reference_markdown())

            status, _stdout, stderr = run_cli(["docs", "roles", "--output", str(output), "--check"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)

            output.write_text(output.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
            status, _stdout, stderr = run_cli(["docs", "roles", "--output", str(output), "--check"])
            self.assertEqual(status, 2)
            self.assertIn("role docs are stale", stderr)


class ResidualIdentifierScanTests(unittest.TestCase):
    def test_no_residual_memory_curation_review_identifier(self) -> None:
        # Build the forbidden identifiers by concatenation so this test file's own
        # source does not self-match. The exempt layer-3 spellings (memory_curation,
        # memory_curation_review/v1, ...) use underscores and cannot match these
        # hyphenated needles.
        skill_needle = "memory-" + "curation-" + "review"
        action_needle = "prepare_" + skill_needle

        repo_root = Path(__file__).resolve().parents[1]
        # Enumerate the committed repo tree via git; this naturally excludes .git,
        # gitignored operational state (.omc, .omx), build artifacts (build/),
        # node_modules, __pycache__, and *.pyc.
        listing = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
        tracked = [rel for rel in listing.stdout.decode("utf-8").split("\0") if rel]

        # test_memory_curation_review_removed legitimately references the literal
        # identifier to assert its absence, so exclude this test file itself.
        self_rel = str(Path(__file__).resolve().relative_to(repo_root))

        offenders: list[str] = []
        for rel in tracked:
            if rel == self_rel:
                continue
            path = repo_root / rel
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if skill_needle in text or action_needle in text:
                offenders.append(rel)

        self.assertEqual(offenders, [], f"residual identifiers found in: {offenders}")


if __name__ == "__main__":
    unittest.main()
