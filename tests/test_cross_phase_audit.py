from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.coding.cross_phase_audit import audit_memory_retrieval, run_cross_phase_audit  # noqa: E402
from omh.coding.git_checkpoint import build_git_checkpoint  # noqa: E402


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=path, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


class CrossPhaseAuditTests(unittest.TestCase):
    def _repo(self) -> Path:
        self.tmp = TemporaryDirectory()
        path = Path(self.tmp.name)
        _git(path, "init", "-q", "-b", "main")
        _git(path, "config", "user.email", "test@example.invalid")
        _git(path, "config", "user.name", "test")
        (path / "README.md").write_text("initial\n", encoding="utf-8")
        _git(path, "add", "README.md")
        _git(path, "commit", "-qm", "initial")
        _git(path, "checkout", "-qb", "feature/seeds-f1b1-cross-phase-audit")
        return path

    def tearDown(self) -> None:
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def test_memory_failure_paths_are_explicit(self) -> None:
        valid = {
            "freshness_warnings": [],
            "retrieval_observation": {
                "schema_version": "memory_retrieval_observation/v1",
                "selected_records": 2,
                "excluded_records": 1,
                "selected_token_estimate": 100,
            },
        }
        self.assertTrue(audit_memory_retrieval(valid)["ok"])
        self.assertEqual(
            audit_memory_retrieval({})["reason"], "missing_retrieval_observation"
        )
        self.assertEqual(
            audit_memory_retrieval(
                {"retrieval_observation": {"schema_version": "other"}}
            )["reason"],
            "conflicting_observation_schema",
        )
        self.assertEqual(
            audit_memory_retrieval(
                {
                    "retrieval_observation": {
                        "schema_version": "memory_retrieval_observation/v1"
                    },
                    "freshness_warnings": ["old"],
                }
            )["reason"],
            "stale_recall_evidence",
        )
        self.assertEqual(
            audit_memory_retrieval(
                {
                    "retrieval_observation": {
                        "schema_version": "memory_retrieval_observation/v1",
                        "selected_token_estimate": 9,
                    }
                },
                token_budget=8,
            )["reason"],
            "retrieval_over_budget",
        )

    def test_cross_phase_audit_passes_and_refuses_checkpoint_drift(self) -> None:
        repo = self._repo()
        checkpoint = build_git_checkpoint(repo, seed="seeds-f1b1", base_sha="main")
        memory = {
            "freshness_warnings": [],
            "retrieval_observation": {
                "schema_version": "memory_retrieval_observation/v1",
                "selected_token_estimate": 1,
            },
        }
        passed = run_cross_phase_audit(
            repo, seed_id="seeds-f1b1", checkpoint=checkpoint, memory_pack=memory
        )
        self.assertTrue(passed["ok"], passed)
        _git(repo, "checkout", "main")
        drifted = run_cross_phase_audit(
            repo, seed_id="seeds-f1b1", checkpoint=checkpoint, memory_pack=memory
        )
        self.assertFalse(drifted["ok"])
        reasons = {check["reason"] for check in drifted["checks"]}
        self.assertIn("feature_branch_policy_refused", reasons)
        self.assertIn("checkpoint_continuity_refused", reasons)

    def test_cross_phase_audit_refuses_dirty_state_drift(self) -> None:
        repo = self._repo()
        checkpoint = build_git_checkpoint(repo, seed="seeds-f1b1", base_sha="main")
        memory = {
            "freshness_warnings": [],
            "retrieval_observation": {
                "schema_version": "memory_retrieval_observation/v1",
                "selected_token_estimate": 1,
            },
        }
        (repo / "README.md").write_text("changed\n", encoding="utf-8")
        audited = run_cross_phase_audit(
            repo, seed_id="seeds-f1b1", checkpoint=checkpoint, memory_pack=memory
        )
        self.assertFalse(audited["ok"])
        checkpoint_check = next(
            check for check in audited["checks"] if check["name"] == "git_checkpoint"
        )
        self.assertEqual(checkpoint_check["reason"], "checkpoint_continuity_refused")
        self.assertIn(
            "dirty state changed",
            checkpoint_check["evidence"]["verification"]["mismatches"],
        )


if __name__ == "__main__":
    unittest.main()
