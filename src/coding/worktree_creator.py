"""Worktree observation ledger helpers.

OMH does not create Git worktrees for chat-prepared handoffs. Upstream Hermes
Agent manages worktrees natively (Kanban worktree-per-task since v0.15.0,
Desktop Projects since v0.18.0), so a chat-side creation path is redundant and
can collide with the worktree Hermes is already managing for the same task.
This module retains the observation-side helpers (reading the local worktree
ledger, recording observed worktree evidence) plus one scoped exception:
`ensure_fanout_unit_worktree`, used only by the explicit opt-in
`omh coding fanout dispatch` bridge, which needs one isolated worktree per
fanout unit before spawning a local agent CLI. Worktrees are never
auto-deleted.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, Callable

from ..local_store import ensure_dir, ensure_file, file_lock, read_jsonl_objects, utc_now
from ..paths import OmhPaths, expand_path

WORKTREE_OBSERVATION_SCHEMA_VERSION = "omh_worktree_observation/v1"

WORKTREE_CLAIM_BOUNDARY = (
    "An observed Git worktree is workspace-isolation evidence only. "
    "It is not executor dispatch, implementation, verification, review, CI, merge-readiness, or merge evidence."
)


def list_worktree_records(paths: OmhPaths, *, limit: int = 20) -> tuple[list[dict[str, Any]], list[str]]:
    records, errors = read_jsonl_objects(paths.runtime_worktrees_path)
    return list(reversed(records))[:limit], errors


def latest_observed_worktree_record(paths: OmhPaths, worktree_path: str | Path) -> dict[str, Any]:
    records, _errors = read_jsonl_objects(paths.runtime_worktrees_path)
    target = str(expand_path(worktree_path))
    for record in reversed(records):
        if not isinstance(record, dict):
            continue
        if (
            str(record.get("worktree_path", "")) == target
            and record.get("observed")
            and record.get("created")
        ):
            return record
    return {}


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
    # Dispatch appends from concurrent unit threads; lock the shared ledger.
    with file_lock(paths.runtime_worktrees_path, private=True):
        with paths.runtime_worktrees_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def ensure_fanout_unit_worktree(
    paths: OmhPaths,
    *,
    repo_root: Path,
    unit_id: str,
    branch: str,
    base_sha: str,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Create the per-unit worktree for the opt-in fanout dispatch bridge.

    A pre-existing branch or worktree path is an error, never silently reused:
    building on divergent state defeats the contract's isolation guarantee.
    Completed units are skipped by dispatch before this helper is called.
    """
    worktree_path = repo_root.parent / f"{repo_root.name}-fanout-{unit_id}"
    result: dict[str, Any] = {
        "status": "failed",
        "observed": False,
        "created": False,
        "repo_root": str(repo_root),
        "branch": branch,
        "worktree_path": str(worktree_path),
        "from_ref": base_sha,
        "evidence_refs": [],
        "recorded_at": utc_now(),
    }
    if worktree_path.exists():
        result["reason"] = f"worktree path already exists: {worktree_path}; remove it or dispatch --unit selectively"
        _append_worktree_record(paths, _observation_record(result))
        return result
    try:
        completed = runner(
            ["git", "worktree", "add", str(worktree_path), "-b", branch, base_sha],
            cwd=str(repo_root),
            text=True,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["reason"] = f"git worktree add failed to run: {exc}"
        _append_worktree_record(paths, _observation_record(result))
        return result
    if int(getattr(completed, "returncode", 1)) != 0:
        stderr_tail = str(getattr(completed, "stderr", "") or "")[-300:]
        result["reason"] = f"git worktree add exited nonzero: {stderr_tail}"
        _append_worktree_record(paths, _observation_record(result))
        return result
    result.update({"status": "created", "observed": True, "created": True, "evidence_refs": [f"git-worktree:{branch}"]})
    _append_worktree_record(paths, _observation_record(result))
    return result
