"""Durable index/ref recovery for confined fanout Git promotion."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import stat
from typing import assert_never, Literal

from .fanout_git_metadata import (
    GitMetadataBoundaryError,
    LinkedWorktreeIdentity,
    _git_rev_parse,
    _git_update_ref,
    _git_write_tree,
    _read_regular_file,
    _valid_object_id,
)


TRANSACTION_NAME = "omh-promotion-transaction.json"


@dataclass(frozen=True, slots=True)
class PromotionTransaction:
    branch_ref: str
    old_head: str
    new_head: str
    backup_name: str


def copy_regular_file(source: Path, destination: Path) -> None:
    try:
        source_descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(source_descriptor, "rb") as source_stream:
            metadata = os.fstat(source_stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise GitMetadataBoundaryError(f"Git metadata file is invalid: {source.name}")
            destination_descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(destination_descriptor, "wb") as destination_stream:
                shutil.copyfileobj(source_stream, destination_stream)
                destination_stream.flush()
                os.fsync(destination_stream.fileno())
        fsync_directory(destination.parent)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise GitMetadataBoundaryError(f"could not copy Git metadata file: {source.name}") from exc


def install_index(source: Path, index: Path) -> None:
    lock = index.with_name("index.lock")
    copy_regular_file(source, lock)
    try:
        lock.replace(index)
    except OSError as exc:
        lock.unlink(missing_ok=True)
        raise GitMetadataBoundaryError("could not install the promoted unit index") from exc


def restore_index(backup: Path, index: Path) -> None:
    lock = index.with_name("index.lock")
    lock.unlink(missing_ok=True)
    copy_regular_file(backup, lock)
    try:
        lock.replace(index)
    except OSError as exc:
        lock.unlink(missing_ok=True)
        raise GitMetadataBoundaryError(f"index recovery backup retained at {backup}") from exc


def fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        # Windows does not expose POSIX directory descriptors for fsync.
        # File contents are flushed before this boundary; the atomic replace
        # remains the platform's durability primitive for directory entries.
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_transaction(linked_git_dir: Path, transaction: PromotionTransaction) -> Path:
    marker = linked_git_dir / TRANSACTION_NAME
    payload = json.dumps(
        {
            "backup_name": transaction.backup_name,
            "branch_ref": transaction.branch_ref,
            "new_head": transaction.new_head,
            "old_head": transaction.old_head,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        descriptor = os.open(
            marker,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        fsync_directory(linked_git_dir)
    except OSError as exc:
        marker.unlink(missing_ok=True)
        raise GitMetadataBoundaryError("could not persist Git promotion transaction") from exc
    return marker


def _read_transaction(linked_git_dir: Path) -> PromotionTransaction | None:
    marker = linked_git_dir / TRANSACTION_NAME
    if not marker.exists():
        return None
    try:
        payload = json.loads(_read_regular_file(marker, limit=4096))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise GitMetadataBoundaryError("Git promotion transaction is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "backup_name", "branch_ref", "new_head", "old_head",
    }:
        raise GitMetadataBoundaryError("Git promotion transaction is invalid")
    values = tuple(payload[key] for key in ("branch_ref", "old_head", "new_head", "backup_name"))
    if not all(isinstance(value, str) for value in values):
        raise GitMetadataBoundaryError("Git promotion transaction is invalid")
    return PromotionTransaction(*values)


def index_matches_head(worktree: Path, linked_git_dir: Path, index: Path, head: str) -> bool:
    expected_tree = _git_rev_parse(
        worktree,
        (f"{head}^{{tree}}",),
        environment={"GIT_DIR": str(linked_git_dir)},
    )
    observed_tree = _git_write_tree(
        worktree,
        (),
        environment={"GIT_DIR": str(linked_git_dir), "GIT_INDEX_FILE": str(index)},
    )
    return observed_tree == expected_tree


def _transaction_state(
    observed_ref: str, transaction: PromotionTransaction
) -> Literal["old", "new", "drift"]:
    if observed_ref == transaction.old_head:
        return "old"
    if observed_ref == transaction.new_head:
        return "new"
    return "drift"


def recover_fanout_git_promotion(worktree: Path, identity: LinkedWorktreeIdentity) -> None:
    transaction = _read_transaction(identity.linked_git_dir)
    if transaction is None:
        return
    if (
        transaction.branch_ref != identity.branch_ref
        or not _valid_object_id(transaction.old_head, identity.object_format)
        or not _valid_object_id(transaction.new_head, identity.object_format)
        or re.fullmatch(r"index\.omh-previous-[0-9a-f]{32}", transaction.backup_name) is None
    ):
        raise GitMetadataBoundaryError("Git promotion transaction does not match the linked worktree")
    backup = identity.linked_git_dir / transaction.backup_name
    index = identity.linked_git_dir / "index"
    observed_ref = _git_rev_parse(
        worktree,
        ("--verify", transaction.branch_ref),
        environment={"GIT_DIR": str(identity.linked_git_dir)},
    )
    state = _transaction_state(observed_ref, transaction)
    match state:
        case "old":
            restore_index(backup, index)
        case "new":
            if not index_matches_head(worktree, identity.linked_git_dir, index, transaction.new_head):
                _git_update_ref(
                    worktree,
                    (transaction.branch_ref, transaction.old_head, transaction.new_head),
                    environment={"GIT_DIR": str(identity.linked_git_dir)},
                )
                restore_index(backup, index)
        case "drift":
            raise GitMetadataBoundaryError("Git promotion state drifted; recovery backup retained")
        case unreachable:
            assert_never(unreachable)
    marker = identity.linked_git_dir / TRANSACTION_NAME
    marker.unlink()
    fsync_directory(identity.linked_git_dir)
    backup.unlink(missing_ok=True)
