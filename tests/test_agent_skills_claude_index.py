"""The Claude Code copy lists a few skills and indexes the rest; other packs keep their bytes."""
from __future__ import annotations

from contextlib import chdir
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from _cli_harness import run_cli

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/claude_context/base-pack-empty-config.md"


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def description(content: str) -> str:
    line = next(line for line in content.splitlines() if line.startswith("description: "))
    return json.loads(line.removeprefix("description: "))


def frontmatter(content: str) -> list[str]:
    return content.split("\n---\n", 1)[0].splitlines()


class ClaudeIndexProducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from omh.install.agent_skills_projection import agent_skill_files, claude_skill_files

        cls.portable = agent_skill_files()
        cls.claude = claude_skill_files(cls.portable)

    def test_direct_set_is_portable_and_keeps_long_descriptions(self):
        from omh.skills.catalog_portable import CLAUDE_DIRECT_SKILLS

        self.assertEqual(len(CLAUDE_DIRECT_SKILLS), 10)
        for name in sorted(CLAUDE_DIRECT_SKILLS):
            with self.subTest(name=name):
                content = self.claude[f"{name}/SKILL.md"]
                self.assertEqual(content, self.portable[f"{name}/SKILL.md"])
                self.assertNotIn("disable-model-invocation: true", frontmatter(content))
                # Over 60 characters, so a `< 20` row in /context can only mean dropped.
                self.assertGreater(len(description(content)), 60)

    def test_every_other_skill_is_flagged_and_indexed_once(self):
        from omh.install.agent_skills_projection import CLAUDE_INDEX_SKILL
        from omh.skills.catalog_portable import CLAUDE_DIRECT_SKILLS

        index = self.claude[f"{CLAUDE_INDEX_SKILL}/SKILL.md"]
        names = sorted({path.split("/")[0] for path in self.portable} - CLAUDE_DIRECT_SKILLS)
        self.assertEqual(len(names), len({path.split("/")[0] for path in self.portable}) - 10)
        rows = re.findall(r"^- `([^`]+)`: (.*)\n  file: \.\./([^/]+)/SKILL\.md$", index, re.M)
        self.assertEqual([row[0] for row in rows], names)
        for name, text, folder in rows:
            with self.subTest(name=name):
                lines = frontmatter(self.claude[f"{name}/SKILL.md"])
                self.assertEqual(lines.count("disable-model-invocation: true"), 1)
                # Only the flag line is added; the body and the rest of the frontmatter are untouched.
                self.assertEqual(self.claude[f"{name}/SKILL.md"].replace("disable-model-invocation: true\n", "", 1),
                                 self.portable[f"{name}/SKILL.md"])
                self.assertEqual(text, description(self.portable[f"{name}/SKILL.md"]))
                self.assertEqual(folder, name)
        self.assertIn(f"Index of {len(names)} more OMH workflows", index)

    def test_index_description_is_one_bounded_sentence(self):
        text = description(self.claude["omh-index/SKILL.md"])
        self.assertTrue(100 <= len(text) <= 160, len(text))
        self.assertNotIn("disable-model-invocation", self.claude["omh-index/SKILL.md"])

    def test_only_skill_bodies_differ_and_one_index_is_added(self):
        self.assertEqual(self.claude.keys() - self.portable.keys(), {"omh-index/SKILL.md"})
        self.assertEqual(self.portable.keys() - self.claude.keys(), set())
        for relative, content in self.portable.items():
            if not relative.endswith("/SKILL.md") or relative.count("/") != 1:
                self.assertEqual(self.claude[relative], content, relative)

    def test_index_name_collision_and_frontmatterless_files_fail_or_pass_closed(self):
        from omh.install.agent_skills_projection import claude_skill_files

        with self.assertRaisesRegex(ValueError, "already holds omh-index"):
            claude_skill_files({"omh-index/SKILL.md": '---\ndescription: "x"\n---\n',
                                "omh-a/SKILL.md": '---\nname: "omh-a"\ndescription: "a"\n---\nbody\n'})
        self.assertEqual(claude_skill_files({"omh-a/SKILL.md": "no frontmatter\n"}),
                         {"omh-a/SKILL.md": "no frontmatter\n"})


class CommittedPackTests(unittest.TestCase):
    def test_committed_claude_pack_is_the_generated_copy_and_agent_skills_is_unflagged(self):
        from omh.install.agent_skills_projection import MANIFEST_NAME, agent_skills_manifest, claude_skill_files

        committed = tree(ROOT / ".claude/agent-skills")
        files = claude_skill_files()
        receipt = committed.pop(MANIFEST_NAME)
        self.assertEqual(committed, {relative: content.encode() for relative, content in files.items()})
        self.assertEqual(json.loads(receipt), agent_skills_manifest(files))
        for path in (ROOT / "agent-skills").glob("*/SKILL.md"):
            self.assertNotIn(b"disable-model-invocation", path.read_bytes(), path)
        manifest = json.loads((ROOT / ".claude/manifest.json").read_bytes())
        self.assertEqual(manifest["source"], ".claude/agent-skills")
        self.assertIn("omh-index", manifest["skills"])
        self.assertEqual(json.loads((ROOT / ".codex/manifest.json").read_bytes())["source"], "agent-skills")

    def test_gate_catches_a_stale_missing_or_extra_claude_pack_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = ["docs", "agent-skills", "--output", str(root / "agent-skills")]
            self.assertEqual(run_cli(command)[0], 0)
            self.assertEqual(run_cli(command + ["--check"])[0], 0)
            pack = root / ".claude/agent-skills"
            (pack / "omh-ask/SKILL.md").write_bytes(b"stale")
            (pack / "omh-index/SKILL.md").unlink()
            (pack / "extra.md").write_bytes(b"extra")
            code, output, error = run_cli(command + ["--check"])
            self.assertEqual(code, 1, error)
            payload = json.loads(output)
            self.assertEqual(payload["host_pack_stale"], [".claude/agent-skills/omh-ask/SKILL.md"])
            self.assertEqual(payload["host_pack_missing"], [".claude/agent-skills/omh-index/SKILL.md"])
            self.assertEqual(payload["host_pack_extra"], [".claude/agent-skills/extra.md"])


@unittest.skipUnless(shutil.which("sh"), "POSIX shell unavailable")
class InstallTests(unittest.TestCase):
    def test_claude_installer_writes_the_index_and_codex_keeps_portable_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp).resolve()
            for host in ("claude", "codex"):
                result = subprocess.run(["sh", str(ROOT / f".{host}/install.sh")], cwd=repo,
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(tree(repo / ".claude/skills"), tree(ROOT / ".claude/agent-skills"))
            self.assertEqual(tree(repo / ".agents/skills"), tree(ROOT / "agent-skills"))
            # The index's relative paths resolve inside the installed copy.
            index = (repo / ".claude/skills/omh-index/SKILL.md").read_text(encoding="utf-8")
            for relative in re.findall(r"^  file: (\S+)$", index, re.M):
                self.assertTrue((repo / ".claude/skills/omh-index" / relative).resolve().is_file(), relative)

    def test_unselected_install_mirrors_the_claude_copy_and_status_stays_truthful(self):
        from omh.install.agent_skills_projection import (
            MANIFEST_NAME, agent_skill_files, agent_skills_status, claude_skill_files, install_agent_skills,
        )

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            target, mirror = home / ".agents/skills", home / ".claude/skills"
            # A mirror written before this change holds the portable bytes: stale, clean drift.
            old = install_agent_skills(target, mirror=None)
            self.assertEqual(old["projection"], "fresh")
            shutil.copytree(target, mirror)
            receipt = json.loads((target / MANIFEST_NAME).read_text())
            receipt["target_dirs"] = [str(target), str(mirror)]
            for root in (target, mirror):
                (root / MANIFEST_NAME).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
            status = agent_skills_status(target, mirror=mirror)
            self.assertEqual((status["primary"], status["mirror"], status["drift"]), ("fresh", "stale", "clean"))
            # Reinstall: each root gets its own bytes and its own receipt.
            status = install_agent_skills(target, mirror=mirror)
            self.assertEqual((status["projection"], status["drift"]), ("fresh", "clean"))
            self.assertEqual(tree(target).keys() - {MANIFEST_NAME}, agent_skill_files().keys())
            self.assertEqual({k: v.decode() for k, v in tree(mirror).items() if k != MANIFEST_NAME}, claude_skill_files())
            receipts = [json.loads((root / MANIFEST_NAME).read_text()) for root in (target, mirror)]
            self.assertEqual(receipts[0]["target_dirs"], receipts[1]["target_dirs"])
            self.assertNotEqual(receipts[0]["files"], receipts[1]["files"])
            # Mirror drift is still named per file.
            (mirror / "omh-index/SKILL.md").write_bytes(b"edited")
            status = agent_skills_status(target, mirror=mirror)
            self.assertEqual(status["locally_modified"], ["mirror:omh-index/SKILL.md"])

    def test_cli_host_install_and_clone_script_write_the_same_claude_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            cli, script, home = root / "cli", root / "script", root / "home"
            for path in (cli, script, home):
                path.mkdir()
            with chdir(cli), patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                code, output, error = run_cli(["install", "--target", "agents", "--host", "claude", "--json"])
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["projection"], "fresh")
            result = subprocess.run(["sh", str(ROOT / ".claude/install.sh")], cwd=script,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(tree(cli / ".claude/skills"), tree(script / ".claude/skills"))


class ContextParserTests(unittest.TestCase):
    def load(self):
        path = ROOT / "tools/claude_context_skills.py"
        spec = importlib.util.spec_from_file_location("claude_context_skills", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_saved_base_pack_context_counts(self):
        # Saved 2026-11-12, Claude Code 2.1.322, claude-opus-5-5, empty CLAUDE_CONFIG_DIR, base-commit pack
        # (trailing spaces stripped for `git diff --check`).
        payload = self.load().parse_context(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(payload["skills_listing_tokens"], "9.9k")
        project = payload["sources"]["Project"]
        self.assertEqual((project["listed"], project["with_description"], project["name_only"]), (123, 61, 62))
        self.assertIn("omh-plan", project["name_only_skills"])
        self.assertEqual(payload["sources"]["Built-in"]["listed"], 13)

    def test_output_without_a_skills_section_is_an_error(self):
        module = self.load()
        with self.assertRaises(ValueError):
            module.parse_context("## Context Usage\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "context.md"
            path.write_text("nothing\n", encoding="utf-8")
            self.assertEqual(module.main([str(path)]), 2)


if __name__ == "__main__":
    unittest.main()
