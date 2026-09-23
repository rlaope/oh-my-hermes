"""Unit-owned Git metadata for Linux-confined fanout worktrees."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
import subprocess
from tempfile import TemporaryFile
from typing import TypedDict
from uuid import uuid4


_OBJECT_ID_LENGTH = {"sha1": 40, "sha256": 64}
_GIT_OUTPUT_LIMIT = 65_536


class GitMetadataBoundaryError(RuntimeError):
    pass


class GitMetadataReceipt(TypedDict):
    status: str
    write_root: str
    shared_git_writable: bool
    branch_ref: str
    object_format: str


def _git_environment(owned: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    if owned is not None:
        environment.update(owned)
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": os.devnull,
            "GIT_CONFIG_KEY_1": "core.fsmonitor",
            "GIT_CONFIG_VALUE_1": "false",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def _run_git_argv(
    worktree: Path,
    argv: tuple[str, ...],
    *,
    environment: Mapping[str, str] | None = None,
    input_text: str | None = None,
) -> str:
    try:
        completed = subprocess.run(
            argv,
            cwd=worktree,
            env=_git_environment(environment),
            text=True,
            input=input_text,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitMetadataBoundaryError("git metadata operation did not complete") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[:300]
        raise GitMetadataBoundaryError(detail or "git metadata operation failed")
    if len(completed.stdout.encode("utf-8")) > _GIT_OUTPUT_LIMIT or len(
        completed.stderr.encode("utf-8")
    ) > _GIT_OUTPUT_LIMIT:
        raise GitMetadataBoundaryError("git metadata operation exceeded its output limit")
    return completed.stdout.strip()


def _git_rev_parse(
    worktree: Path,
    arguments: tuple[str, ...],
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    return _run_git_argv(worktree, ("git", "rev-parse", *arguments), environment=environment)


def _git_symbolic_ref(
    worktree: Path,
    arguments: tuple[str, ...],
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    return _run_git_argv(worktree, ("git", "symbolic-ref", *arguments), environment=environment)


def _git_init(
    worktree: Path,
    arguments: tuple[str, ...],
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    return _run_git_argv(worktree, ("git", "init", *arguments), environment=environment)


def _git_config(
    worktree: Path,
    arguments: tuple[str, ...],
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    return _run_git_argv(worktree, ("git", "config", *arguments), environment=environment)


def _git_update_ref(
    worktree: Path,
    arguments: tuple[str, ...],
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    return _run_git_argv(worktree, ("git", "update-ref", *arguments), environment=environment)


def _git_read_tree(
    worktree: Path,
    arguments: tuple[str, ...],
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    return _run_git_argv(worktree, ("git", "read-tree", *arguments), environment=environment)


def _git_write_tree(
    worktree: Path,
    arguments: tuple[str, ...],
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    return _run_git_argv(worktree, ("git", "write-tree", *arguments), environment=environment)


def _git_merge_base(
    worktree: Path,
    arguments: tuple[str, ...],
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    return _run_git_argv(worktree, ("git", "merge-base", *arguments), environment=environment)


def _git_status(
    worktree: Path,
    arguments: tuple[str, ...],
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    return _run_git_argv(worktree, ("git", "status", *arguments), environment=environment)


def _import_objects(
    worktree: Path,
    source_git_dir: Path,
    target_git_dir: Path,
    head: str,
    base: str,
) -> None:
    """Import one private producer graph without fetching or updating a ref."""
    with TemporaryFile() as pack:
        try:
            packed = subprocess.run(
                ("git", "pack-objects", "--revs", "--stdout"),
                cwd=worktree,
                env=_git_environment({"GIT_DIR": str(source_git_dir)}),
                input=(f"{head}\n^{base}\n").encode("ascii"),
                stdout=pack,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            if packed.returncode != 0 or len(packed.stderr) > _GIT_OUTPUT_LIMIT:
                raise GitMetadataBoundaryError("could not pack unit-owned Git objects")
            pack.seek(0)
            imported = subprocess.run(
                ("git", "index-pack", "--stdin"),
                cwd=worktree,
                env=_git_environment({"GIT_DIR": str(target_git_dir)}),
                stdin=pack,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitMetadataBoundaryError("Git object import did not complete") from exc
    if (
        imported.returncode != 0
        or len(imported.stdout) > _GIT_OUTPUT_LIMIT
        or len(imported.stderr) > _GIT_OUTPUT_LIMIT
    ):
        raise GitMetadataBoundaryError("could not import unit-owned Git objects")


def _optional_git_config(
    worktree: Path,
    arguments: tuple[str, ...],
    *,
    environment: Mapping[str, str] | None = None,
) -> str | None:
    try:
        return _git_config(worktree, arguments, environment=environment)
    except GitMetadataBoundaryError:
        return None


def _read_regular_file(path: Path, *, limit: int) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            value = stream.read(limit + 1)
    except OSError as exc:
        raise GitMetadataBoundaryError(f"Git metadata file is unavailable: {path.name}") from exc
    if not stat.S_ISREG(metadata.st_mode) or len(value) > limit:
        raise GitMetadataBoundaryError(f"Git metadata file is invalid: {path.name}")
    return value


def _resolved_directory(path: Path, *, label: str) -> Path:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise GitMetadataBoundaryError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not resolved.is_dir():
        raise GitMetadataBoundaryError(f"{label} is invalid")
    return resolved


def _parse_gitdir(worktree: Path, git_file: bytes) -> Path:
    try:
        line = git_file.decode("utf-8").strip()
    except UnicodeError as exc:
        raise GitMetadataBoundaryError("linked worktree .git file is invalid") from exc
    if not line.startswith("gitdir: ") or "\n" in line or "\x00" in line:
        raise GitMetadataBoundaryError("linked worktree .git file is invalid")
    value = Path(line.removeprefix("gitdir: "))
    return (value if value.is_absolute() else worktree / value).resolve(strict=True)


def _valid_object_id(value: str, object_format: str) -> bool:
    length = _OBJECT_ID_LENGTH.get(object_format)
    return length is not None and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


@dataclass(frozen=True, slots=True)
class LinkedWorktreeIdentity:
    linked_git_dir: Path
    common_git_dir: Path
    branch_ref: str
    head: str
    object_format: str
    git_file: bytes


def _linked_worktree_identity(worktree: Path) -> LinkedWorktreeIdentity:
    resolved_worktree = worktree.resolve(strict=True)
    git_file_path = resolved_worktree / ".git"
    git_file = _read_regular_file(git_file_path, limit=4096)
    parsed_git_dir = _parse_gitdir(resolved_worktree, git_file)
    observed_git_dir = Path(_git_rev_parse(resolved_worktree, ("--absolute-git-dir",)))
    linked_git_dir = _resolved_directory(observed_git_dir, label="linked worktree Git directory")
    common_value = Path(_git_rev_parse(resolved_worktree, ("--git-common-dir",)))
    common_candidate = common_value if common_value.is_absolute() else resolved_worktree / common_value
    common_git_dir = _resolved_directory(common_candidate, label="shared Git directory")
    top_level = Path(_git_rev_parse(resolved_worktree, ("--show-toplevel",))).resolve(strict=True)
    branch_ref = _git_symbolic_ref(resolved_worktree, ("-q", "HEAD"))
    head = _git_rev_parse(resolved_worktree, ("--verify", "HEAD"))
    object_format = _git_rev_parse(resolved_worktree, ("--show-object-format",))
    if (
        parsed_git_dir != linked_git_dir
        or top_level != resolved_worktree
        or linked_git_dir.parent != common_git_dir / "worktrees"
        or linked_git_dir == common_git_dir
        or not branch_ref.startswith("refs/heads/")
        or not _valid_object_id(head, object_format)
    ):
        raise GitMetadataBoundaryError("linked worktree relationship is invalid")
    commondir = _read_regular_file(linked_git_dir / "commondir", limit=4096).decode("utf-8").strip()
    linked_common = (linked_git_dir / commondir).resolve(strict=True)
    backlink = Path(
        _read_regular_file(linked_git_dir / "gitdir", limit=4096).decode("utf-8").strip()
    ).resolve(strict=True)
    if linked_common != common_git_dir or backlink != git_file_path:
        raise GitMetadataBoundaryError("linked worktree metadata relationship is invalid")
    _ = _resolved_directory(common_git_dir / "objects", label="shared Git object directory")
    return LinkedWorktreeIdentity(
        linked_git_dir,
        common_git_dir,
        branch_ref,
        head,
        object_format,
        git_file,
    )


@dataclass(frozen=True, slots=True)
class FanoutGitMetadata:
    worktree: Path
    linked_git_dir: Path
    common_git_dir: Path
    private_git_dir: Path
    initial_head: str
    branch_ref: str
    object_format: str
    git_file: bytes

    def environment(self) -> dict[str, str]:
        return {
            "GIT_DIR": str(self.private_git_dir),
            "GIT_WORK_TREE": str(self.worktree),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }

    def receipt(self) -> GitMetadataReceipt:
        return {
            "status": "unit_owned",
            "write_root": str(self.private_git_dir),
            "shared_git_writable": False,
            "branch_ref": self.branch_ref,
            "object_format": self.object_format,
        }

    def promote(self) -> str:
        from .fanout_git_promotion import promote_fanout_git_metadata

        return promote_fanout_git_metadata(self)


def prepare_fanout_git_metadata(worktree: Path) -> FanoutGitMetadata | None:
    git_file = worktree / ".git"
    if not git_file.is_file():
        return None
    identity = _linked_worktree_identity(worktree)
    from .fanout_git_transaction import recover_fanout_git_promotion

    recover_fanout_git_promotion(worktree.resolve(), identity)
    identity = _linked_worktree_identity(worktree)
    private_git_dir = worktree / ".omh" / "confinement-tmp" / f"git-metadata-{uuid4().hex}"
    _git_init(
        worktree,
        ("--bare", "-q", f"--object-format={identity.object_format}", str(private_git_dir)),
    )
    environment = {
        "GIT_DIR": str(private_git_dir),
        "GIT_WORK_TREE": str(worktree.resolve()),
    }
    for key, value in (
        ("core.bare", "false"),
        ("core.worktree", str(worktree.resolve())),
        ("core.hooksPath", os.devnull),
    ):
        _git_config(worktree, (key, value), environment=environment)
    for key in ("user.name", "user.email"):
        value = _optional_git_config(
            worktree,
            ("--local", "--no-includes", "--get", key),
            environment={"GIT_DIR": str(identity.common_git_dir)},
        )
        if value is not None:
            _git_config(worktree, (key, value), environment=environment)
    alternates = private_git_dir / "objects" / "info" / "alternates"
    alternates.write_text(str(identity.common_git_dir / "objects") + "\n", encoding="utf-8")
    _git_update_ref(worktree, (identity.branch_ref, identity.head), environment=environment)
    _git_symbolic_ref(worktree, ("HEAD", identity.branch_ref), environment=environment)
    _git_read_tree(worktree, ("HEAD",), environment=environment)
    return FanoutGitMetadata(
        worktree.resolve(),
        identity.linked_git_dir,
        identity.common_git_dir,
        private_git_dir.resolve(),
        identity.head,
        identity.branch_ref,
        identity.object_format,
        identity.git_file,
    )
