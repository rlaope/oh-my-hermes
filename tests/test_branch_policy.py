from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from omh.coding.branch_policy import (
    check_feature_branch,
    create_feature_worktree,
    feature_branch_name,
    verify_repository_branch,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


class BranchPolicyTests(unittest.TestCase):
    def test_branch_name_is_stable_and_seed_bound(self) -> None:
        branch = feature_branch_name("ubuntu-ab12", "Memory router / v2")
        self.assertEqual(branch, "feature/ubuntu-ab12-memory-router-v2")
        self.assertTrue(check_feature_branch(branch, seed_id="ubuntu-ab12").allowed)

    def test_protected_and_non_feature_branches_are_refused(self) -> None:
        self.assertEqual(check_feature_branch("main").reason_code, "protected_branch")
        self.assertEqual(check_feature_branch("bugfix/ubuntu-ab12-thing").reason_code, "feature_branch_required")
        self.assertEqual(check_feature_branch("feature/other-thing", seed_id="ubuntu-ab12").reason_code, "seed_missing_from_branch")

    def test_create_feature_worktree_records_branch_and_head(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw) / "repo"
            root.mkdir()
            _git(root, "init", "-q", "-b", "main")
            _git(root, "config", "user.name", "test")
            _git(root, "config", "user.email", "test@example.invalid")
            (root / "README.md").write_text("seed\n", encoding="utf-8")
            _git(root, "add", "README.md")
            _git(root, "commit", "-q", "-m", "init")
            target = Path(raw) / "worktree"

            payload = create_feature_worktree(root, seed_id="ubuntu-ab12", feature="branch-policy", worktree_path=target)

            self.assertEqual(payload["status"], "created")
            self.assertEqual(payload["branch"], "feature/ubuntu-ab12-branch-policy")
            self.assertTrue(target.is_dir())
            self.assertEqual(_git(target, "branch", "--show-current"), payload["branch"])
            self.assertTrue(payload["head_sha"])
            self.assertEqual(verify_repository_branch(target, seed_id="ubuntu-ab12")["status"], "allowed")

    def test_verify_refuses_protected_branch(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            _git(root, "init", "-q", "-b", "main")
            _git(root, "config", "user.name", "test")
            _git(root, "config", "user.email", "test@example.invalid")
            (root / "README.md").write_text("seed\n", encoding="utf-8")
            _git(root, "add", "README.md")
            _git(root, "commit", "-q", "-m", "init")

            payload = verify_repository_branch(root)

            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["branch_check"]["reason_code"], "protected_branch")
