"""Feature-branch policy and Git worktree creation primitives.

This module is intentionally small and subprocess-based. It is the policy seam
used by CLI and future hook integrations; it does not infer merge or CI proof.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
import subprocess
from typing import Any, Callable


BRANCH_POLICY_SCHEMA_VERSION = "omh_branch_policy/v1"
FEATURE_BRANCH_PREFIX = "feature"
PROTECTED_BRANCHES = frozenset({"main", "master", "develop", "development", "trunk"})
_SAFE_PART = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class BranchCheck:
    allowed: bool
    branch: str
    reason_code: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": BRANCH_POLICY_SCHEMA_VERSION,
            "allowed": self.allowed,
            "branch": self.branch,
            "reason_code": self.reason_code,
            "reason": self.reason,
        }


def feature_branch_name(seed_id: str, feature: str) -> str:
    seed = _slug(seed_id, fallback="task")
    name = _slug(feature, fallback="feature")
    return f"{FEATURE_BRANCH_PREFIX}/{seed}-{name}"


def check_feature_branch(branch: str, *, seed_id: str = "") -> BranchCheck:
    normalized = str(branch or "").strip()
    if not normalized:
        return BranchCheck(False, normalized, "branch_missing", "a feature branch name is required")
    short = normalized.removeprefix("refs/heads/")
    if short in PROTECTED_BRANCHES:
        return BranchCheck(False, short, "protected_branch", f"direct work on protected branch {short!r} is refused")
    if not short.startswith(f"{FEATURE_BRANCH_PREFIX}/"):
        return BranchCheck(False, short, "feature_branch_required", "work must be performed on a feature/<seed>-<name> branch")
    if seed_id and _slug(seed_id, fallback="task") not in short:
        return BranchCheck(False, short, "seed_missing_from_branch", f"branch must contain seed id {seed_id!r}")
    return BranchCheck(True, short, "allowed", "feature branch policy satisfied")


def _run_git(runner: Callable[..., Any], repo_root: Path, args: list[str]) -> tuple[int, str, str]:
    try:
        result = runner(["git", *args], cwd=str(repo_root), text=True, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)
    return int(getattr(result, "returncode", 1)), str(getattr(result, "stdout", "") or ""), str(getattr(result, "stderr", "") or "")


def current_branch(repo_root: Path, *, runner: Callable[..., Any] = subprocess.run) -> str:
    code, stdout, _stderr = _run_git(runner, repo_root, ["branch", "--show-current"])
    return stdout.strip() if code == 0 else ""


def verify_repository_branch(
    repo_root: Path,
    *,
    seed_id: str = "",
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, object]:
    branch = current_branch(repo_root, runner=runner)
    check = check_feature_branch(branch, seed_id=seed_id)
    code, sha, stderr = _run_git(runner, repo_root, ["rev-parse", "HEAD"])
    return {
        "schema_version": BRANCH_POLICY_SCHEMA_VERSION,
        "repository": str(repo_root.resolve()),
        "branch": check.branch,
        "head_sha": sha.strip() if code == 0 else "",
        "branch_check": check.as_dict(),
        "status": "allowed" if check.allowed and code == 0 else "blocked",
        "error": stderr.strip() if code != 0 else "",
    }


def create_feature_worktree(
    repo_root: Path,
    *,
    seed_id: str,
    feature: str,
    worktree_path: Path | None = None,
    base_ref: str = "HEAD",
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, object]:
    branch = feature_branch_name(seed_id, feature)
    check = check_feature_branch(branch, seed_id=seed_id)
    if not check.allowed:
        return {"schema_version": BRANCH_POLICY_SCHEMA_VERSION, "status": "blocked", "branch_check": check.as_dict()}
    target = worktree_path or (repo_root / ".worktrees" / branch.replace("/", "-"))
    if target.exists():
        return {
            "schema_version": BRANCH_POLICY_SCHEMA_VERSION,
            "status": "blocked",
            "reason_code": "worktree_path_exists",
            "reason": f"worktree path already exists: {target}",
            "branch": branch,
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    code, stdout, stderr = _run_git(runner, repo_root, ["worktree", "add", "-b", branch, str(target), base_ref])
    if code != 0:
        return {
            "schema_version": BRANCH_POLICY_SCHEMA_VERSION,
            "status": "blocked",
            "reason_code": "git_worktree_add_failed",
            "reason": stderr.strip() or "git worktree add failed",
            "branch": branch,
            "worktree_path": str(target),
        }
    verify = verify_repository_branch(target, seed_id=seed_id, runner=runner)
    return {
        "schema_version": BRANCH_POLICY_SCHEMA_VERSION,
        "status": "created" if verify["status"] == "allowed" else "blocked",
        "branch": branch,
        "worktree_path": str(target.resolve()),
        "base_ref": base_ref,
        "head_sha": verify["head_sha"],
        "creation_stdout": stdout.strip(),
        "branch_check": verify["branch_check"],
    }


def _slug(value: str, *, fallback: str) -> str:
    cleaned = _SAFE_PART.sub("-", str(value or "").strip().lower()).strip("-")
    return cleaned[:72] or fallback
