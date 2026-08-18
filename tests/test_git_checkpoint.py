from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.coding.git_checkpoint import (  # noqa: E402
    build_git_checkpoint,
    collect_git_maintenance_evidence,
    verify_git_checkpoint,
)


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=path, text=True, capture_output=True, check=True)
    return result.stdout.strip()


class GitCheckpointTests(unittest.TestCase):
    def _repo(self) -> Path:
        path = Path(self.tmp.name)
        _git(path, "init", "-q", "-b", "main")
        _git(path, "config", "user.email", "test@example.invalid")
        _git(path, "config", "user.name", "test")
        (path / "README.md").write_text("initial\n", encoding="utf-8")
        _git(path, "add", "README.md")
        _git(path, "commit", "-qm", "initial")
        return path

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_checkpoint_captures_dirty_state_and_verify_detects_head_drift(self) -> None:
        repo = self._repo()
        _git(repo, "checkout", "-qb", "feature/ubuntu-test-checkpoint")
        (repo / "README.md").write_text("changed\n", encoding="utf-8")
        checkpoint = build_git_checkpoint(repo, seed="ubuntu-test", base_sha="main", validation=["pytest"])
        self.assertEqual(checkpoint["branch"], "feature/ubuntu-test-checkpoint")
        self.assertEqual(checkpoint["base_sha"], _git(repo, "rev-parse", "main"))
        self.assertTrue(checkpoint["dirty_state"]["dirty"])
        self.assertEqual(checkpoint["validation"], ["pytest"])
        self.assertTrue(verify_git_checkpoint(checkpoint, repo)["ok"], verify_git_checkpoint(checkpoint, repo))
        _git(repo, "add", "README.md")
        _git(repo, "commit", "-qm", "change")
        verified = verify_git_checkpoint(checkpoint, repo)
        self.assertFalse(verified["ok"])
        self.assertTrue(any("head_sha changed" in item for item in verified["mismatches"]))

    def test_maintenance_is_observation_only_and_reports_worktrees(self) -> None:
        repo = self._repo()
        evidence = collect_git_maintenance_evidence(repo)
        self.assertEqual(evidence["schema_version"], "git_maintenance_evidence/v1")
        self.assertFalse(evidence["mutated"])
        self.assertTrue(evidence["worktrees"]["ok"])
        self.assertTrue(evidence["prune_dry_run"]["ok"])

    def test_verify_refuses_branch_drift_even_when_head_is_unchanged(self) -> None:
        repo = self._repo()
        checkpoint = build_git_checkpoint(repo)
        _git(repo, "checkout", "-qb", "feature/ubuntu-test-drift")
        verified = verify_git_checkpoint(checkpoint, repo)
        self.assertFalse(verified["ok"])
        self.assertTrue(any("branch changed" in item for item in verified["mismatches"]))

    def test_checkpoint_payload_is_json_serializable(self) -> None:
        repo = self._repo()
        self.assertIsInstance(json.dumps(build_git_checkpoint(repo)), str)


if __name__ == "__main__":
    unittest.main()
