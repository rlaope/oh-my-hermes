"""Sanitized, recoverable promotion of confined fanout Git commits."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING
from uuid import uuid4

from .fanout_git_metadata import (
    GitMetadataBoundaryError,
    _git_config,
    _git_init,
    _git_merge_base,
    _git_read_tree,
    _git_rev_parse,
    _git_status,
    _git_symbolic_ref,
    _git_update_ref,
    _import_objects,
    _linked_worktree_identity,
    _read_regular_file,
    _resolved_directory,
    _valid_object_id,
)
from .fanout_git_transaction import (
    PromotionTransaction,
    copy_regular_file as _copy_regular_file,
    fsync_directory as _fsync_directory,
    index_matches_head as _index_matches_head,
    install_index as _install_index,
    recover_fanout_git_promotion,
    write_transaction as _write_transaction,
)

if TYPE_CHECKING:
    from .fanout_git_metadata import FanoutGitMetadata


def _private_head(boundary: FanoutGitMetadata) -> str:
    private_git_dir = _resolved_directory(
        boundary.private_git_dir,
        label="unit-owned Git directory",
    )
    if private_git_dir != boundary.private_git_dir:
        raise GitMetadataBoundaryError("unit-owned Git directory changed during dispatch")
    objects = _resolved_directory(
        boundary.private_git_dir / "objects",
        label="unit-owned Git object directory",
    )
    if objects != boundary.private_git_dir / "objects":
        raise GitMetadataBoundaryError("unit-owned Git object directory changed during dispatch")
    expected_head = f"ref: {boundary.branch_ref}\n".encode()
    if _read_regular_file(boundary.private_git_dir / "HEAD", limit=4096) != expected_head:
        raise GitMetadataBoundaryError("unit-owned Git branch changed during dispatch")
    loose_ref = boundary.private_git_dir.joinpath(*boundary.branch_ref.split("/"))
    if not loose_ref.parent.resolve(strict=True).is_relative_to(boundary.private_git_dir):
        raise GitMetadataBoundaryError("unit-owned Git ref path changed during dispatch")
    value = _read_regular_file(loose_ref, limit=256).decode("ascii").strip()
    if not _valid_object_id(value, boundary.object_format):
        raise GitMetadataBoundaryError("unit-owned Git HEAD is invalid")
    return value


def _safe_private_view(boundary: FanoutGitMetadata, head: str) -> Path:
    safe_git_dir = boundary.linked_git_dir / f"omh-promotion-{uuid4().hex}"
    _git_init(
        boundary.worktree,
        ("--bare", "-q", f"--object-format={boundary.object_format}", str(safe_git_dir)),
    )
    try:
        environment = {"GIT_DIR": str(safe_git_dir), "GIT_WORK_TREE": str(boundary.worktree)}
        for key, value in (
            ("core.bare", "false"),
            ("core.worktree", str(boundary.worktree)),
            ("core.hooksPath", os.devnull),
            ("core.fsmonitor", "false"),
        ):
            _git_config(boundary.worktree, (key, value), environment=environment)
        alternates = safe_git_dir / "objects" / "info" / "alternates"
        alternate_paths = (
            (boundary.private_git_dir / "objects").as_posix(),
            (boundary.common_git_dir / "objects").as_posix(),
        )
        alternates.write_bytes(("\n".join(alternate_paths) + "\n").encode("utf-8"))
        _git_update_ref(boundary.worktree, (boundary.branch_ref, head), environment=environment)
        _git_symbolic_ref(boundary.worktree, ("HEAD", boundary.branch_ref), environment=environment)
        _copy_regular_file(boundary.private_git_dir / "index", safe_git_dir / "index")
        if _git_status(
            boundary.worktree,
            ("--porcelain", "--untracked-files=all"),
            environment={**environment, "GIT_OPTIONAL_LOCKS": "0"},
        ):
            raise GitMetadataBoundaryError("unit-owned Git worktree is not clean")
        return safe_git_dir
    except (GitMetadataBoundaryError, OSError):
        shutil.rmtree(safe_git_dir, ignore_errors=True)
        raise


def _validate_linked_identity(boundary: FanoutGitMetadata) -> None:
    observed = _linked_worktree_identity(boundary.worktree)
    if (
        observed.git_file != boundary.git_file
        or observed.linked_git_dir != boundary.linked_git_dir
        or observed.common_git_dir != boundary.common_git_dir
        or observed.branch_ref != boundary.branch_ref
        or observed.object_format != boundary.object_format
    ):
        raise GitMetadataBoundaryError("linked worktree branch changed during dispatch")
    if observed.head != boundary.initial_head:
        raise GitMetadataBoundaryError("linked worktree HEAD changed during dispatch")


def _update_explicit_ref(boundary: FanoutGitMetadata, head: str) -> None:
    try:
        _git_update_ref(
            boundary.worktree,
            (boundary.branch_ref, head, boundary.initial_head),
            environment={"GIT_DIR": str(boundary.linked_git_dir)},
        )
    except GitMetadataBoundaryError:
        observed = _git_rev_parse(
            boundary.worktree,
            ("--verify", boundary.branch_ref),
            environment={"GIT_DIR": str(boundary.linked_git_dir)},
        )
        if observed != head:
            raise


def promote_fanout_git_metadata(boundary: FanoutGitMetadata) -> str:
    _validate_linked_identity(boundary)
    head = _private_head(boundary)
    safe_git_dir = _safe_private_view(boundary, head)
    index = boundary.linked_git_dir / "index"
    temporary_index = boundary.linked_git_dir / f"index.omh-{uuid4().hex}"
    backup = boundary.linked_git_dir / f"index.omh-previous-{uuid4().hex}"
    marker: Path | None = None
    try:
        try:
            _git_merge_base(
                boundary.worktree,
                ("--is-ancestor", boundary.initial_head, head),
                environment={"GIT_DIR": str(safe_git_dir)},
            )
        except GitMetadataBoundaryError as exc:
            raise GitMetadataBoundaryError("unit-owned Git HEAD is not a descendant of the frozen base") from exc
        _import_objects(
            boundary.worktree,
            safe_git_dir,
            boundary.linked_git_dir,
            head,
            boundary.initial_head,
        )
        _git_read_tree(
            boundary.worktree,
            (head,),
            environment={
                "GIT_DIR": str(boundary.linked_git_dir),
                "GIT_WORK_TREE": str(boundary.worktree),
                "GIT_INDEX_FILE": str(temporary_index),
            },
        )
        _copy_regular_file(index, backup)
        marker = _write_transaction(
            boundary.linked_git_dir,
            PromotionTransaction(
                boundary.branch_ref,
                boundary.initial_head,
                head,
                backup.name,
            ),
        )
        _install_index(temporary_index, index)
        _validate_linked_identity(boundary)
        _update_explicit_ref(boundary, head)
        if not _index_matches_head(boundary.worktree, boundary.linked_git_dir, index, head):
            raise GitMetadataBoundaryError("promoted Git index does not match the unit commit")
        marker.unlink()
        marker = None
        _fsync_directory(boundary.linked_git_dir)
        backup.unlink(missing_ok=True)
        return head
    except (Exception, KeyboardInterrupt, SystemExit) as exc:
        if marker is not None:
            try:
                identity = _linked_worktree_identity(boundary.worktree)
                recover_fanout_git_promotion(boundary.worktree, identity)
                marker = None
            except GitMetadataBoundaryError as recovery_error:
                raise recovery_error from exc
        if isinstance(exc, (GitMetadataBoundaryError, KeyboardInterrupt, SystemExit)):
            raise
        raise GitMetadataBoundaryError("Git metadata promotion failed") from exc
    finally:
        temporary_index.unlink(missing_ok=True)
        shutil.rmtree(safe_git_dir, ignore_errors=True)
