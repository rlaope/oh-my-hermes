"""The Claude Code copy shortens every description; other packs keep their bytes."""
from __future__ import annotations

from contextlib import chdir
import importlib.util
import json
import os
from pathlib import Path
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


FUNCTION_WORDS = {"a", "an", "the", "and", "or", "of", "to", "for", "with", "in", "on", "instead of",
                  "before", "after", "that", "which", "when"}


class ClaudeDescriptionProducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from omh.install.agent_skills_projection import agent_skill_files, claude_skill_files

        cls.portable = agent_skill_files()
        cls.claude = claude_skill_files(cls.portable)
        cls.skills = sorted(path for path in cls.portable if path.endswith("/SKILL.md") and path.count("/") == 1)

    def test_no_flag_and_no_index_anywhere_in_the_claude_pack(self):
        for relative, content in self.claude.items():
            self.assertNotIn("disable-model-invocation", content, relative)
        self.assertNotIn("omh-index/SKILL.md", self.claude)

    def test_no_skill_added_or_removed_and_only_skill_files_differ(self):
        self.assertEqual(self.claude.keys(), self.portable.keys())
        self.assertEqual(len(self.skills), 123)
        for relative, content in self.portable.items():
            if relative not in self.skills:
                self.assertEqual(self.claude[relative], content, relative)

    def test_only_the_description_line_differs_and_the_prefix_stays(self):
        for relative in self.skills:
            with self.subTest(relative=relative):
                before, after = self.portable[relative].split("\n"), self.claude[relative].split("\n")
                self.assertEqual(len(before), len(after))
                changed = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
                self.assertEqual(len(changed), 1)
                self.assertTrue(before[changed[0]].startswith("description: "))
                self.assertTrue(description(self.claude[relative]).startswith("[omh] "))

    def test_every_description_is_short_whole_and_ends_cleanly(self):
        from omh.install.agent_skills_projection import CLAUDE_DESCRIPTION_CAP

        for relative in self.skills:
            text = description(self.claude[relative])
            with self.subTest(relative=relative):
                self.assertLessEqual(len(text), CLAUDE_DESCRIPTION_CAP)
                self.assertGreaterEqual(len(text), 40)
                self.assertNotIn("Use when the user says", text)
                lead = description(self.portable[relative]).partition(" Use when the user says:")[0].strip()
                if len(lead) <= CLAUDE_DESCRIPTION_CAP:
                    # Nothing was cut, so nothing is reworded: a lead that ends "act on." keeps its last word.
                    self.assertEqual(text, lead.rstrip(" .,;:-") + ".")
                    continue
                # A cut says it is one, and is a prefix of the lead it was cut from.
                self.assertTrue(text.endswith("…"), text)
                self.assertTrue(lead.startswith(text[:-1]), text)
                words = text[:-1].rstrip(" ,;:-").split()
                self.assertNotIn(words[-1].lower(), FUNCTION_WORDS, text)
                self.assertNotIn(" ".join(words[-2:]).lower(), FUNCTION_WORDS, text)

    def test_every_portable_description_has_the_trigger_marker(self):
        from omh.install.agent_skills_projection import CLAUDE_TRIGGER_MARKER

        for relative in self.skills:
            self.assertIn(CLAUDE_TRIGGER_MARKER, description(self.portable[relative]), relative)

    def test_shorten_description_rules(self):
        from omh.install.agent_skills_projection import shorten_description

        self.assertEqual(shorten_description("[omh] Short lead. Use when the user says: a, b."), "[omh] Short lead.")
        self.assertEqual(shorten_description("No marker at all"), "No marker at all.")
        self.assertEqual(
            shorten_description("[omh] A decision note you can act on. Use when the user says: decide."),
            "[omh] A decision note you can act on.",
        )
        long = "[omh] " + "Check the build output and report every failure, " + "then fix the cause of it for the team and the rest of us"
        cut = shorten_description(long, 80)
        self.assertLessEqual(len(cut), 80)
        self.assertEqual(cut, "[omh] Check the build output and report every failure…")
        tail = shorten_description("[omh] " + "word " * 12 + "and the", 40)
        self.assertTrue(tail.endswith("word…"), tail)


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
        self.assertNotIn("omh-index", manifest["skills"])
        self.assertEqual(json.loads((ROOT / ".codex/manifest.json").read_bytes())["source"], "agent-skills")

    def test_gate_catches_a_stale_missing_or_extra_claude_pack_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = ["docs", "agent-skills", "--output", str(root / "agent-skills")]
            self.assertEqual(run_cli(command)[0], 0)
            self.assertEqual(run_cli(command + ["--check"])[0], 0)
            pack = root / ".claude/agent-skills"
            (pack / "omh-ask/SKILL.md").write_bytes(b"stale")
            (pack / "omh-plan/SKILL.md").unlink()
            (pack / "extra.md").write_bytes(b"extra")
            code, output, error = run_cli(command + ["--check"])
            self.assertEqual(code, 1, error)
            payload = json.loads(output)
            self.assertEqual(payload["host_pack_stale"], [".claude/agent-skills/omh-ask/SKILL.md"])
            self.assertEqual(payload["host_pack_missing"], [".claude/agent-skills/omh-plan/SKILL.md"])
            self.assertEqual(payload["host_pack_extra"], [".claude/agent-skills/extra.md"])


@unittest.skipUnless(shutil.which("sh"), "POSIX shell unavailable")
class InstallTests(unittest.TestCase):
    def test_claude_installer_writes_the_short_descriptions_and_codex_keeps_portable_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp).resolve()
            for host in ("claude", "codex"):
                result = subprocess.run(["sh", str(ROOT / f".{host}/install.sh")], cwd=repo,
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(tree(repo / ".claude/skills"), tree(ROOT / ".claude/agent-skills"))
            self.assertEqual(tree(repo / ".agents/skills"), tree(ROOT / "agent-skills"))

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
            (mirror / "omh-plan/SKILL.md").write_bytes(b"edited")
            status = agent_skills_status(target, mirror=mirror)
            self.assertEqual(status["locally_modified"], ["mirror:omh-plan/SKILL.md"])

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
