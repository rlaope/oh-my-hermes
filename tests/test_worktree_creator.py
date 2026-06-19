from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli


class WorktreeCreatorTests(unittest.TestCase):
    def test_worktree_prepare_dry_run_does_not_create_path(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _init_repo(root / "repo")
            target = root / "worktrees" / "dry"

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(root / ".omh"),
                    "worktree",
                    "prepare",
                    "--repo",
                    str(repo),
                    "--task",
                    "risky refactor",
                    "--path",
                    str(target),
                    "--dry-run",
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)["worktree"]
            self.assertEqual(payload["schema_version"], "omh_worktree_prepare/v1")
            self.assertEqual(payload["status"], "dry_run")
            self.assertFalse(payload["observed"])
            self.assertFalse(target.exists())
            self.assertIn("git", payload["command"][0])
            self.assertEqual(payload["runtime_observation_followup"]["event_type"], "worktree_creation")

    def test_worktree_prepare_creates_git_worktree_and_records_ledger(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _init_repo(root / "repo")
            target = root / "worktrees" / "risky"
            home = root / ".omh"

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(home),
                    "worktree",
                    "prepare",
                    "--repo",
                    str(repo),
                    "--task",
                    "risky refactor",
                    "--branch",
                    "omh/risky-refactor-test",
                    "--path",
                    str(target),
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0, stdout)
            payload = json.loads(stdout)["worktree"]
            self.assertEqual(payload["status"], "created")
            self.assertTrue(payload["observed"])
            self.assertTrue(payload["created"])
            self.assertTrue((target / ".git").exists() or (target / ".git").is_file())
            self.assertIn(f"git-worktree:{target.resolve()}", payload["evidence_refs"])
            self.assertIn("not executor dispatch", payload["claim_boundary"])
            self.assertIn("omh runtime observe", payload["runtime_observation_followup"]["record_with"])
            worktree_list = _git(repo, "worktree", "list", "--porcelain")
            self.assertIn(str(target), worktree_list.stdout)

            status, stdout, stderr = run_cli(["--omh-home", str(home), "worktree", "list", "--limit", "1"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            records = json.loads(stdout)["records"]
            self.assertEqual(records[0]["schema_version"], "omh_worktree_observation/v1")
            self.assertTrue(records[0]["created"])

    def test_worktree_prepare_blocks_dirty_source_by_default(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _init_repo(root / "repo")
            (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(root / ".omh"),
                    "worktree",
                    "prepare",
                    "--repo",
                    str(repo),
                    "--task",
                    "risky refactor",
                    "--path",
                    str(root / "worktrees" / "blocked"),
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            payload = json.loads(stdout)["worktree"]
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["reason"], "source_dirty")
            self.assertFalse(payload["created"])


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init")
    (path / "README.md").write_text("# temp\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "-c", "user.name=OMH Test", "-c", "user.email=omh@example.com", "commit", "-m", "init")
    return path


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return completed


if __name__ == "__main__":
    unittest.main()
