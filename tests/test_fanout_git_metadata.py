from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from omh.coding.fanout_git_metadata import GitMetadataBoundaryError, prepare_fanout_git_metadata
from omh.coding.fanout_dispatch import _observed_clean_producer_head
from omh.coding.fanout_unit_results import validate_unit_result
from omh.coding.local_diagnostic_engine import GitRevisionReader


def _git(worktree: Path, *arguments: str, environment: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=worktree,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def _linked_worktree(root: Path, *, object_format: str | None = None) -> Path:
    repository = root / "repository"
    worktree = root / "unit"
    repository.mkdir()
    init_arguments = ("init", "-q") if object_format is None else (
        "init",
        "-q",
        f"--object-format={object_format}",
    )
    _git(repository, *init_arguments)
    _git(repository, "config", "user.name", "Test User")
    _git(repository, "config", "user.email", "test@example.test")
    (repository / "tracked").write_text("base\n", encoding="utf-8")
    (repository / ".gitignore").write_text(".omh/\n", encoding="utf-8")
    _git(repository, "add", "tracked", ".gitignore")
    _git(repository, "commit", "-qm", "base")
    _git(repository, "worktree", "add", "-qb", "unit/test", str(worktree))
    return worktree


def _supports_sha256() -> bool:
    with TemporaryDirectory() as temporary:
        completed = subprocess.run(
            ("git", "init", "--bare", "-q", "--object-format=sha256", temporary),
            text=True,
            capture_output=True,
            check=False,
        )
        return completed.returncode == 0


class FanoutGitMetadataTests(unittest.TestCase):
    def test_promotion_never_executes_child_controlled_fsmonitor(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree = _linked_worktree(root)
            boundary = prepare_fanout_git_metadata(worktree)
            self.assertIsNotNone(boundary)
            assert boundary is not None
            environment = {**os.environ, **boundary.environment()}
            (worktree / "change").write_text("unit\n", encoding="utf-8")
            _git(worktree, "add", "change", environment=environment)
            _git(worktree, "commit", "-qm", "unit change", environment=environment)
            marker = root / "host-command-ran"
            fsmonitor = root / "fsmonitor"
            fsmonitor.write_text(
                f"#!/bin/sh\nprintf escaped > {marker}\nexit 0\n",
                encoding="utf-8",
            )
            fsmonitor.chmod(0o755)
            _git(worktree, "config", "core.fsmonitor", str(fsmonitor), environment=environment)

            boundary.promote()

            self.assertFalse(marker.exists())

    def test_preparation_ignores_ambient_git_repository_routing(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree = _linked_worktree(root)
            unrelated = root / "unrelated"
            unrelated.mkdir()
            _git(unrelated, "init", "-q")
            _git(unrelated, "config", "user.name", "Other User")
            _git(unrelated, "config", "user.email", "other@example.test")
            (unrelated / "other").write_text("other\n", encoding="utf-8")
            _git(unrelated, "add", "other")
            _git(unrelated, "commit", "-qm", "other")
            expected_git_dir = Path(_git(worktree, "rev-parse", "--absolute-git-dir"))

            with mock.patch.dict(
                os.environ,
                {
                    "GIT_DIR": str(unrelated / ".git"),
                    "GIT_WORK_TREE": str(unrelated),
                    "GIT_INDEX_FILE": str(unrelated / ".git" / "index"),
                },
            ):
                boundary = prepare_fanout_git_metadata(worktree)

            self.assertIsNotNone(boundary)
            assert boundary is not None
            self.assertEqual(boundary.linked_git_dir, expected_git_dir.resolve())

    def test_private_alternates_uses_git_portable_lf_bytes(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = _linked_worktree(Path(temporary))

            boundary = prepare_fanout_git_metadata(worktree)

            self.assertIsNotNone(boundary)
            assert boundary is not None
            alternates = (boundary.private_git_dir / "objects" / "info" / "alternates").read_bytes()
            self.assertTrue(alternates.endswith(b"\n"))
            self.assertNotIn(b"\r", alternates)

    def test_preparation_rejects_git_file_redirect_to_the_common_repository(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree = _linked_worktree(root)
            git_file = worktree / ".git"
            os.chmod(git_file, stat.S_IREAD | stat.S_IWRITE)
            git_file.unlink()
            git_file.write_text(
                f"gitdir: {root / 'repository' / '.git'}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(GitMetadataBoundaryError, "relationship"):
                prepare_fanout_git_metadata(worktree)

    def test_promotion_refuses_branch_drift_without_advancing_either_branch(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree = _linked_worktree(root)
            boundary = prepare_fanout_git_metadata(worktree)
            self.assertIsNotNone(boundary)
            assert boundary is not None
            environment = {**os.environ, **boundary.environment()}
            _git(worktree, "commit", "--allow-empty", "-qm", "unit change", environment=environment)
            _git(worktree, "switch", "-qc", "other", boundary.initial_head)

            with self.assertRaisesRegex(GitMetadataBoundaryError, "branch changed"):
                boundary.promote()

            self.assertEqual(_git(worktree, "rev-parse", "refs/heads/unit/test"), boundary.initial_head)
            self.assertEqual(_git(worktree, "rev-parse", "refs/heads/other"), boundary.initial_head)

    @unittest.skipUnless(_supports_sha256(), "local Git does not support SHA-256 repositories")
    def test_sha256_linked_worktree_uses_matching_private_object_format(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree = _linked_worktree(Path(temporary), object_format="sha256")

            boundary = prepare_fanout_git_metadata(worktree)

            self.assertIsNotNone(boundary)
            assert boundary is not None
            self.assertEqual(
                _git(boundary.private_git_dir, "rev-parse", "--show-object-format"),
                "sha256",
            )
            environment = {**os.environ, **boundary.environment()}
            (worktree / "tracked").write_text("sha256\n", encoding="utf-8")
            _git(worktree, "add", "tracked", environment=environment)
            _git(worktree, "commit", "-qm", "sha256 unit", environment=environment)

            producer_head = boundary.promote()

            self.assertEqual(len(producer_head), 64)
            self.assertEqual(_git(worktree, "rev-parse", "HEAD"), producer_head)
            self.assertEqual(_observed_clean_producer_head(subprocess.run, worktree), producer_head)
            self.assertEqual(GitRevisionReader().read(str(worktree), producer_head), producer_head)
            validated = validate_unit_result(
                {
                    "schema_version": "fanout_unit_result/v1",
                    "unit_id": "unit",
                    "run_id": "run-sha256",
                    "fanout_id": "fanout-0123456789ab",
                    "base_sha": boundary.initial_head,
                    "head_sha": producer_head,
                    "process_status": "process_succeeded",
                    "changed_paths": ["tracked"],
                    "checks": [],
                    "findings": [],
                }
            )
            self.assertEqual(validated["head_sha"], producer_head)

if __name__ == "__main__":
    unittest.main()
