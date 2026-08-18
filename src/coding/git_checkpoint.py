"""Observable Git checkpoint and maintenance evidence for agent handoffs."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

GIT_CHECKPOINT_SCHEMA_VERSION = "git_checkpoint/v1"
GIT_MAINTENANCE_SCHEMA_VERSION = "git_maintenance_evidence/v1"
GIT_RANGE_DIFF_SCHEMA_VERSION = "git_range_diff_evidence/v1"

CLAIM_BOUNDARY = (
    "Git checkpoint evidence binds a handoff to observed repository state. It does not prove implementation, "
    "tests, review, CI, merge-readiness, or merge. Maintenance and range-diff results are observations only."
)

Runner = Callable[..., subprocess.CompletedProcess[str]]


class GitCheckpointError(ValueError):
    """Raised when required Git checkpoint state cannot be observed."""


def _run(repo_root: Path, argv: list[str], runner: Runner) -> tuple[int, str, str]:
    try:
        result = runner(argv, cwd=str(repo_root), text=True, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)
    return int(result.returncode), result.stdout or "", result.stderr or ""


def _required(repo_root: Path, argv: list[str], runner: Runner, label: str) -> str:
    code, stdout, stderr = _run(repo_root, argv, runner)
    if code != 0 or not stdout.strip():
        detail = stderr.strip()[-240:]
        raise GitCheckpointError(f"could not observe Git {label}: {detail or f'exit {code}'}")
    return stdout.strip()


def _status(repo_root: Path, runner: Runner) -> dict[str, Any]:
    code, stdout, stderr = _run(repo_root, ["git", "status", "--porcelain=v1"], runner)
    if code != 0:
        raise GitCheckpointError(f"could not observe Git dirty state: {stderr.strip()[-240:] or f'exit {code}'}")
    entries = [line for line in stdout.splitlines() if line]
    staged = sum(1 for line in entries if line[:1] not in {" ", "?"})
    untracked = sum(1 for line in entries if line.startswith("??"))
    unstaged = sum(1 for line in entries if line[:2] not in {"??", "  "} and line[1:2] not in {" ", "?"})
    return {
        "dirty": bool(entries),
        "entry_count": len(entries),
        "staged_count": staged,
        "unstaged_count": unstaged,
        "untracked_count": untracked,
        "entries": entries[:100],
        "entries_truncated": len(entries) > 100,
    }


def build_git_checkpoint(
    repo_root: str | Path = ".",
    *,
    seed: str = "",
    base_sha: str = "",
    validation: list[str] | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Capture the immutable and dirty-state fields needed for a resumable handoff."""
    root = Path(repo_root).expanduser().resolve()
    observed_root = Path(_required(root, ["git", "rev-parse", "--show-toplevel"], runner, "repository root")).resolve()
    branch = _required(root, ["git", "branch", "--show-current"], runner, "branch")
    head_sha = _required(root, ["git", "rev-parse", "HEAD"], runner, "HEAD")
    remote_code, remote, _ = _run(root, ["git", "config", "--get", "remote.origin.url"], runner)
    status = _status(root, runner)
    resolved_base = base_sha.strip()
    if resolved_base:
        resolved_base = _required(root, ["git", "rev-parse", "--verify", f"{resolved_base}^{{commit}}"], runner, "base SHA")
    return {
        "schema_version": GIT_CHECKPOINT_SCHEMA_VERSION,
        "repo_root": str(observed_root),
        "remote": remote.strip() if remote_code == 0 else "",
        "branch": branch,
        "detached": not bool(branch),
        "head_sha": head_sha,
        "base_sha": resolved_base,
        "worktree": str(root),
        "seed": seed,
        "dirty_state": status,
        "validation": list(validation or []),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def verify_git_checkpoint(
    checkpoint: dict[str, Any],
    repo_root: str | Path = ".",
    *,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Compare a recorded checkpoint with current Git state without mutating it."""
    try:
        current = build_git_checkpoint(repo_root, base_sha=str(checkpoint.get("base_sha", "")), runner=runner)
    except GitCheckpointError as exc:
        return {"schema_version": GIT_CHECKPOINT_SCHEMA_VERSION, "ok": False, "mismatches": [str(exc)], "current": None}
    mismatches: list[str] = []
    for field in ("repo_root", "remote", "branch", "head_sha", "base_sha", "worktree"):
        if str(checkpoint.get(field, "")) != str(current.get(field, "")):
            mismatches.append(f"{field} changed: recorded={checkpoint.get(field)!r} current={current.get(field)!r}")
    recorded_dirty = checkpoint.get("dirty_state", {})
    if bool(recorded_dirty.get("dirty")) != bool(current["dirty_state"]["dirty"]):
        mismatches.append("dirty state changed")
    return {
        "schema_version": GIT_CHECKPOINT_SCHEMA_VERSION,
        "ok": not mismatches,
        "mismatches": mismatches,
        "recorded": checkpoint,
        "current": current,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def collect_git_maintenance_evidence(repo_root: str | Path = ".", *, runner: Runner = subprocess.run) -> dict[str, Any]:
    """Report maintenance configuration and safe worktree-prune candidates."""
    root = Path(repo_root).expanduser().resolve()
    strategy_code, strategy, _ = _run(root, ["git", "config", "--get", "maintenance.strategy"], runner)
    auto_code, auto, _ = _run(root, ["git", "config", "--get", "maintenance.auto"], runner)
    list_code, worktrees, list_error = _run(root, ["git", "worktree", "list", "--porcelain"], runner)
    prune_code, prune, prune_error = _run(root, ["git", "worktree", "prune", "--dry-run"], runner)
    return {
        "schema_version": GIT_MAINTENANCE_SCHEMA_VERSION,
        "repo_root": str(root),
        "maintenance": {
            "strategy": strategy.strip() if strategy_code == 0 else "",
            "auto": auto.strip() if auto_code == 0 else "",
            "configured": strategy_code == 0 or auto_code == 0,
        },
        "worktrees": {
            "ok": list_code == 0,
            "porcelain": worktrees.splitlines(),
            "error": list_error.strip(),
        },
        "prune_dry_run": {
            "ok": prune_code == 0,
            "candidates": prune.splitlines(),
            "error": prune_error.strip(),
        },
        "mutated": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def collect_range_diff_evidence(
    repo_root: str | Path,
    old_range: str,
    new_range: str,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Capture whether a rebased patch preserves its old-vs-new intent."""
    root = Path(repo_root).expanduser().resolve()
    code, stdout, stderr = _run(root, ["git", "range-diff", "--no-dual-color", old_range, new_range], runner)
    return {
        "schema_version": GIT_RANGE_DIFF_SCHEMA_VERSION,
        "repo_root": str(root),
        "old_range": old_range,
        "new_range": new_range,
        "ok": code == 0,
        "exit_code": code,
        "output": stdout[-20000:],
        "error": stderr.strip()[-1000:],
        "claim_boundary": CLAIM_BOUNDARY,
    }
