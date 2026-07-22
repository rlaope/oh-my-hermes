"""Worktree observation ledger helpers.

OMH no longer *creates* Git worktrees. Upstream Hermes Agent manages worktrees
natively (Kanban worktree-per-task since v0.15.0, Desktop Projects since
v0.18.0), so an OMH-owned creation path is redundant and can collide with the
worktree Hermes is already managing for the same task. This module retains only
the observation-side helpers: reading the local worktree ledger and recording
observed worktree evidence when a wrapper or runtime reports it. Worktree
preparation is deferred to the operator's native tooling (Hermes Kanban /
Desktop Projects, or a manual `git worktree add`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..local_store import ensure_dir, ensure_file, read_jsonl_objects, utc_now
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
    with paths.runtime_worktrees_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
