from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from omh.coding import fanout_git_promotion, fanout_git_transaction
from omh.coding.fanout_git_metadata import (
    FanoutGitMetadata,
    GitMetadataBoundaryError,
    prepare_fanout_git_metadata,
)

from test_fanout_git_metadata import _git, _linked_worktree


class FanoutGitTransactionTests(unittest.TestCase):
    def _boundary(
        self, temporary: str
    ) -> tuple[Path, FanoutGitMetadata, dict[str, str]]:
        worktree = _linked_worktree(Path(temporary))
        boundary = prepare_fanout_git_metadata(worktree)
        self.assertIsNotNone(boundary)
        assert boundary is not None
        return worktree, boundary, {**os.environ, **boundary.environment()}

    def test_index_install_failure_occurs_before_any_ref_update(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree, boundary, environment = self._boundary(temporary)
            _git(worktree, "commit", "--allow-empty", "-qm", "unit change", environment=environment)
            with (
                mock.patch.object(
                    fanout_git_promotion,
                    "_install_index",
                    side_effect=GitMetadataBoundaryError("injected index install failure"),
                ),
                mock.patch.object(
                    fanout_git_promotion,
                    "_update_explicit_ref",
                    side_effect=AssertionError("ref update must follow index installation"),
                ),
                self.assertRaises(GitMetadataBoundaryError),
            ):
                boundary.promote()
            self.assertEqual(_git(worktree, "rev-parse", boundary.branch_ref), boundary.initial_head)

    def test_ref_update_failure_restores_the_original_index(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree, boundary, environment = self._boundary(temporary)
            _git(worktree, "commit", "--allow-empty", "-qm", "unit change", environment=environment)
            index = boundary.linked_git_dir / "index"
            original_index = index.read_bytes()
            with (
                mock.patch.object(
                    fanout_git_promotion,
                    "_update_explicit_ref",
                    side_effect=GitMetadataBoundaryError("injected ref update failure"),
                ),
                self.assertRaises(GitMetadataBoundaryError),
            ):
                boundary.promote()
            self.assertEqual(index.read_bytes(), original_index)
            self.assertEqual(_git(worktree, "rev-parse", boundary.branch_ref), boundary.initial_head)

    def test_interruption_after_index_install_is_recovered_before_reuse(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree, boundary, environment = self._boundary(temporary)
            (worktree / "change").write_text("unit\n", encoding="utf-8")
            _git(worktree, "add", "change", environment=environment)
            _git(worktree, "commit", "-qm", "unit change", environment=environment)
            original_index = (boundary.linked_git_dir / "index").read_bytes()
            with (
                mock.patch.object(fanout_git_promotion, "_update_explicit_ref", side_effect=KeyboardInterrupt),
                mock.patch.object(
                    fanout_git_promotion,
                    "recover_fanout_git_promotion",
                    side_effect=KeyboardInterrupt,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                boundary.promote()
            recovered = prepare_fanout_git_metadata(worktree)
            self.assertIsNotNone(recovered)
            self.assertEqual((boundary.linked_git_dir / "index").read_bytes(), original_index)
            self.assertEqual(_git(worktree, "rev-parse", boundary.branch_ref), boundary.initial_head)
            self.assertFalse(tuple(boundary.linked_git_dir.glob("omh-promotion-transaction*")))

    @unittest.skipUnless(os.name == "posix", "Git hook probe requires a POSIX shell")
    def test_crash_recovery_never_runs_repository_reference_transaction_hook(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree, boundary, environment = self._boundary(temporary)
            (worktree / "change").write_text("unit\n", encoding="utf-8")
            _git(worktree, "add", "change", environment=environment)
            _git(worktree, "commit", "-qm", "unit change", environment=environment)
            original_update = fanout_git_promotion._update_explicit_ref

            def interrupt_after_ref_update(target: FanoutGitMetadata, head: str) -> None:
                original_update(target, head)
                raise KeyboardInterrupt

            with (
                mock.patch.object(
                    fanout_git_promotion,
                    "_update_explicit_ref",
                    side_effect=interrupt_after_ref_update,
                ),
                mock.patch.object(
                    fanout_git_promotion,
                    "recover_fanout_git_promotion",
                    side_effect=KeyboardInterrupt,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                boundary.promote()

            backup = next(boundary.linked_git_dir.glob("index.omh-previous-*"))
            (boundary.linked_git_dir / "index").write_bytes(backup.read_bytes())
            marker = Path(temporary) / "reference-transaction-executed"
            hooks = Path(temporary) / "hostile-hooks"
            hooks.mkdir()
            hook = hooks / "reference-transaction"
            hook.write_text(
                "#!/bin/sh\nprintf executed > " + shlex.quote(str(marker)) + "\n",
                encoding="utf-8",
            )
            hook.chmod(0o755)
            _git(worktree, "config", "core.hooksPath", str(hooks))

            recovered = prepare_fanout_git_metadata(worktree)

            self.assertIsNotNone(recovered)
            self.assertFalse(marker.exists())
            self.assertEqual(_git(worktree, "rev-parse", boundary.branch_ref), boundary.initial_head)

    def test_promotion_refuses_a_non_descendant_private_head(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree, boundary, environment = self._boundary(temporary)
            tree = _git(worktree, "write-tree", environment=environment)
            created = subprocess.run(
                ("git", "commit-tree", tree),
                cwd=worktree,
                env=environment,
                input="unrelated root\n",
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            _git(worktree, "update-ref", boundary.branch_ref, created, environment=environment)
            with self.assertRaisesRegex(GitMetadataBoundaryError, "descendant"):
                boundary.promote()
            self.assertEqual(_git(worktree, "rev-parse", boundary.branch_ref), boundary.initial_head)

    def test_ref_update_with_lost_success_response_keeps_the_matching_index(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree, boundary, environment = self._boundary(temporary)
            _git(worktree, "commit", "--allow-empty", "-qm", "unit change", environment=environment)
            producer_head = _git(worktree, "rev-parse", "HEAD", environment=environment)
            original_update_ref = fanout_git_promotion._git_update_ref
            injected = False

            def lose_success_response(
                target_worktree: Path,
                arguments: tuple[str, ...],
                *,
                environment: dict[str, str] | None = None,
            ) -> str:
                nonlocal injected
                result = original_update_ref(target_worktree, arguments, environment=environment)
                if (
                    environment is not None
                    and environment.get("GIT_DIR") == str(boundary.linked_git_dir)
                    and boundary.branch_ref in arguments
                    and not injected
                ):
                    injected = True
                    raise GitMetadataBoundaryError("injected lost update-ref response")
                return result

            with mock.patch.object(
                fanout_git_promotion,
                "_git_update_ref",
                side_effect=lose_success_response,
            ):
                promoted = boundary.promote()
            self.assertEqual(promoted, producer_head)
            self.assertEqual(_git(worktree, "rev-parse", boundary.branch_ref), producer_head)
            self.assertEqual(_git(worktree, "status", "--porcelain"), "")

    def test_failed_index_rollback_retains_recovery_backup_and_restores_ref(self) -> None:
        with TemporaryDirectory() as temporary:
            worktree, boundary, environment = self._boundary(temporary)
            _git(worktree, "commit", "--allow-empty", "-qm", "unit change", environment=environment)
            with (
                mock.patch.object(
                    fanout_git_promotion,
                    "_update_explicit_ref",
                    side_effect=GitMetadataBoundaryError("injected ref update failure"),
                ),
                mock.patch.object(
                    fanout_git_transaction,
                    "restore_index",
                    side_effect=GitMetadataBoundaryError("injected rollback failure"),
                ),
                self.assertRaises(GitMetadataBoundaryError),
            ):
                boundary.promote()
            self.assertEqual(_git(worktree, "rev-parse", boundary.branch_ref), boundary.initial_head)
            self.assertTrue((boundary.linked_git_dir / "index").is_file())
            self.assertTrue(tuple(boundary.linked_git_dir.glob("index.omh-previous-*")))


if __name__ == "__main__":
    unittest.main()
