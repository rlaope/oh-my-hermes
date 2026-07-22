from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REMOVED_PATHS = (
    "aside-live-1440.png",
    "omh-before-1440.png",
    "omh-qa-docs-mobile-live.png",
    "omh-qa-home-mobile-live.png",
    "omh-qa-docs-mobile-snapshot.md",
    "omh-qa-home-mobile-snapshot.md",
    ".playwright-mcp",
    "docs/SKILL_QUALITY_COMPARISON.md",
)

QA_LEFTOVER_SAMPLES = (
    ".playwright-mcp/console-example.log",
    "omh-qa-docs-mobile-live.png",
    "omh-qa-home-mobile-snapshot.md",
    "aside-live-1440.png",
)


class RepoHygieneTests(unittest.TestCase):
    def test_removed_qa_scratch_paths_are_absent(self) -> None:
        for relative_path in REMOVED_PATHS:
            with self.subTest(relative_path=relative_path):
                self.assertFalse(
                    (REPO_ROOT / relative_path).exists(),
                    f"{relative_path} should have been deleted from the repo",
                )

    def test_gitignore_covers_qa_leftovers(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git executable unavailable")

        for relative_path in QA_LEFTOVER_SAMPLES:
            with self.subTest(relative_path=relative_path):
                result = subprocess.run(
                    ["git", "check-ignore", "-v", relative_path],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    f"expected .gitignore to cover {relative_path!r}, got: {result.stdout}{result.stderr}",
                )

    def test_no_remaining_references_to_removed_skill_quality_doc(self) -> None:
        needle = "SKILL_QUALITY_COMPARISON"
        search_roots = [REPO_ROOT / "docs", REPO_ROOT / "src"]
        search_roots.extend(REPO_ROOT.glob("README*"))
        search_roots.append(REPO_ROOT / "AGENTS.md")

        offenders: list[str] = []
        for root in search_roots:
            if not root.exists():
                continue
            candidates = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
            for path in candidates:
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if needle in text:
                    offenders.append(str(path.relative_to(REPO_ROOT)))

        self.assertEqual(offenders, [], f"unexpected references to {needle}: {offenders}")


if __name__ == "__main__":
    unittest.main()
