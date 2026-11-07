from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from omh.codegraph.scanner import build_codegraph

ROOT = Path(__file__).resolve().parent.parent


def _text(skill: str) -> str:
    return (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")


class CodegraphIsPythonOnlyTests(unittest.TestCase):
    """The codegraph skills say the generator reads Python only; hold the claim to the scanner."""

    def test_a_non_python_repository_scans_to_zero_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.ts").write_text("export const x = 1;\n", encoding="utf-8")
            (root / "main.go").write_text("package main\n", encoding="utf-8")
            stats = build_codegraph(root)["stats"]
        self.assertEqual(stats["file_count"], 0)

    def test_the_skills_state_the_stop(self):
        for skill in ("omh-codebase-uml", "omh-codegraph-refresh"):
            with self.subTest(skill=skill):
                self.assertIn("Python files only", _text(skill))


class DebuggingReferencesTests(unittest.TestCase):
    def test_native_debugging_names_the_instruments(self):
        text = (ROOT / "skills/omh-native-debugging/references/native-debug-loop.md").read_text(encoding="utf-8")
        for needle in ("-fsanitize=address", "Valgrind", "rr record", "core file", "lldb --batch", "gdb -batch"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_bisect_exit_codes_are_stated(self):
        text = (ROOT / "skills/omh-git-workflow/references/git-repair-method.md").read_text(encoding="utf-8")
        self.assertIn("a build failure exits 125", text)
        self.assertIn("rerere.enabled", text)


if __name__ == "__main__":
    unittest.main()
