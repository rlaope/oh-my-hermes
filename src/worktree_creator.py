from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .local_store import ensure_dir, ensure_file, read_jsonl_objects, utc_now
from .paths import OmhPaths, expand_path
from .runtime.artifacts import update_state

WORKTREE_PREPARE_SCHEMA_VERSION = "omh_worktree_prepare/v1"
WORKTREE_OBSERVATION_SCHEMA_VERSION = "omh_worktree_observation/v1"

WORKTREE_CLAIM_BOUNDARY = (
    "An OMH-created Git worktree is observed workspace-isolation evidence only. "
    "It is not executor dispatch, implementation, verification, review, CI, merge-readiness, or merge evidence."
)

RUNTIME_OBSERVATION_FOLLOWUP = {
    "schema_version": "runtime_observation_followup/v1",
    "event_type": "worktree_creation",
    "record_with": (
        "omh runtime observe --run <run-id> --runtime-profile <runtime-profile> --event worktree_creation "
        "--status observed --worktree-ref <worktree_path> --evidence-ref git-worktree:<worktree_path>"
    ),
    "when": "Only when this worktree belongs to a prepared runtime or executor session that needs ladder evidence.",
    "boundary": "The local worktree ledger is workspace-isolation evidence; runtime ladder evidence remains a separate wrapper/operator observation.",
}


def prepare_git_worktree(
    paths: OmhPaths,
    *,
    repo: str | Path,
    task: str = "",
    branch: str = "",
    worktree_path: str | Path | None = None,
    base_dir: str | Path = ".worktrees",
    from_ref: str = "HEAD",
    dry_run: bool = False,
    allow_dirty_source: bool = False,
) -> dict[str, Any]:
    repo_root = _repo_root(repo)
    status_text = _git(repo_root, "status", "--porcelain", check=True).stdout.strip()
    source_dirty = bool(status_text)
    if source_dirty and not allow_dirty_source:
        return _blocked_result(
            paths,
            repo_root=repo_root,
            task=task,
            branch=branch,
            worktree_path=worktree_path,
            base_dir=base_dir,
            from_ref=from_ref,
            reason="source_dirty",
            message="Source worktree has uncommitted changes; rerun with --allow-dirty-source if this is intentional.",
        )

    resolved_branch = _branch_name(branch, task)
    resolved_path = _worktree_path(repo_root, resolved_branch, worktree_path=worktree_path, base_dir=base_dir)
    command = ["git", "-C", str(repo_root), "worktree", "add", "-b", resolved_branch, str(resolved_path), from_ref]
    base_payload = {
        "schema_version": WORKTREE_PREPARE_SCHEMA_VERSION,
        "repo_root": str(repo_root),
        "branch": resolved_branch,
        "worktree_path": str(resolved_path),
        "from_ref": from_ref,
        "source_dirty": source_dirty,
        "command": command,
        "claim_boundary": WORKTREE_CLAIM_BOUNDARY,
        "runtime_observation_followup": RUNTIME_OBSERVATION_FOLLOWUP,
    }
    if dry_run:
        return {
            **base_payload,
            "status": "dry_run",
            "observed": False,
            "created": False,
            "evidence_refs": [],
            "next_action": "rerun_without_dry_run_to_create_worktree",
        }
    if resolved_path.exists():
        return _blocked_result(
            paths,
            repo_root=repo_root,
            task=task,
            branch=resolved_branch,
            worktree_path=resolved_path,
            base_dir=base_dir,
            from_ref=from_ref,
            reason="path_exists",
            message=f"Worktree path already exists: {resolved_path}",
        )

    completed = _git(repo_root, "worktree", "add", "-b", resolved_branch, str(resolved_path), from_ref, check=False)
    if completed.returncode != 0:
        return {
            **base_payload,
            "status": "blocked",
            "observed": False,
            "created": False,
            "reason": "git_worktree_add_failed",
            "stderr": completed.stderr.strip(),
            "stdout": completed.stdout.strip(),
            "evidence_refs": [],
            "next_action": "inspect_git_error_before_opening_executor",
        }

    evidence_refs = [f"git-worktree:{resolved_path}", f"git-branch:{resolved_branch}"]
    record = {
        **base_payload,
        "status": "created",
        "observed": True,
        "created": True,
        "evidence_refs": evidence_refs,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "recorded_at": utc_now(),
        "next_action": "open_executor_in_worktree_or_record_runtime_observation",
    }
    _append_worktree_record(paths, _observation_record(record))
    update_state(paths, {"last_worktree_prepare": record})
    return record


def list_worktree_records(paths: OmhPaths, *, limit: int = 20) -> tuple[list[dict[str, Any]], list[str]]:
    records, errors = read_jsonl_objects(paths.runtime_worktrees_path)
    return list(reversed(records))[:limit], errors


def _blocked_result(
    paths: OmhPaths,
    *,
    repo_root: Path,
    task: str,
    branch: str,
    worktree_path: str | Path | None,
    base_dir: str | Path,
    from_ref: str,
    reason: str,
    message: str,
) -> dict[str, Any]:
    resolved_branch = _branch_name(branch, task)
    resolved_path = _worktree_path(repo_root, resolved_branch, worktree_path=worktree_path, base_dir=base_dir)
    record = {
        "schema_version": WORKTREE_PREPARE_SCHEMA_VERSION,
        "status": "blocked",
        "observed": False,
        "created": False,
        "repo_root": str(repo_root),
        "branch": resolved_branch,
        "worktree_path": str(resolved_path),
        "from_ref": from_ref,
        "reason": reason,
        "message": message,
        "evidence_refs": [],
        "recorded_at": utc_now(),
        "claim_boundary": WORKTREE_CLAIM_BOUNDARY,
        "runtime_observation_followup": RUNTIME_OBSERVATION_FOLLOWUP,
        "next_action": "resolve_blocker_before_opening_executor",
    }
    _append_worktree_record(paths, _observation_record(record))
    update_state(paths, {"last_worktree_prepare": record})
    return record


def _observation_record(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": WORKTREE_OBSERVATION_SCHEMA_VERSION,
        "status": result["status"],
        "observed": result["observed"],
        "created": result["created"],
        "repo_root": result["repo_root"],
        "branch": result["branch"],
        "worktree_path": result["worktree_path"],
        "from_ref": result["from_ref"],
        "evidence_refs": result["evidence_refs"],
        "reason": result.get("reason", ""),
        "message": result.get("message", ""),
        "recorded_at": result.get("recorded_at", utc_now()),
        "claim_boundary": WORKTREE_CLAIM_BOUNDARY,
    }


def _append_worktree_record(paths: OmhPaths, record: dict[str, Any]) -> None:
    ensure_dir(paths.runtime_dir, private=True)
    ensure_file(paths.runtime_worktrees_path, private=True)
    with paths.runtime_worktrees_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _repo_root(repo: str | Path) -> Path:
    repo_path = expand_path(repo)
    completed = _git(repo_path, "rev-parse", "--show-toplevel", check=False)
    if completed.returncode != 0:
        raise ValueError(f"not a Git worktree: {repo_path}")
    return expand_path(completed.stdout.strip())


def _branch_name(branch: str, task: str) -> str:
    if branch.strip():
        return branch.strip()
    slug = re.sub(r"[^a-z0-9]+", "-", task.lower()).strip("-")[:42].strip("-")
    stamp = utc_now().replace(":", "").replace("-", "").lower()
    return f"omh/{slug or 'worktree'}-{stamp}"


def _worktree_path(repo_root: Path, branch: str, *, worktree_path: str | Path | None, base_dir: str | Path) -> Path:
    if worktree_path:
        return expand_path(worktree_path)
    base = Path(base_dir)
    if not base.is_absolute():
        base = repo_root / base
    safe_branch = re.sub(r"[^a-zA-Z0-9._-]+", "-", branch).strip("-") or "worktree"
    return expand_path(base / safe_branch)


def _git(cwd: Path, *args: str, check: bool) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and completed.returncode != 0:
        raise ValueError(completed.stderr.strip() or completed.stdout.strip() or "git command failed")
    return completed
