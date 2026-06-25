from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..local_store import atomic_write_json


CODEGRAPH_SCHEMA_VERSION = "omh_codegraph/v1"
CODEGRAPH_CONTEXT_SCHEMA_VERSION = "omh_codegraph_context/v1"
CODEGRAPH_SUMMARY_SCHEMA_VERSION = "omh_codegraph_summary/v1"
CODEGRAPH_ARTIFACT_RELATIVE_PATH = Path(".omh") / "codegraph" / "codegraph.json"
CLAIM_BOUNDARY = (
    "Static local analysis is prepared context only. "
    "Static local analysis is not execution/review/CI/merge evidence. "
    "It is not review, CI, merge-readiness, merge proof, or observed executor work."
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_repo_root(repo: str | Path) -> Path:
    root = Path(repo).expanduser().resolve()
    if not root.exists():
        raise ValueError(f"repository path does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"repository path is not a directory: {root}")
    return root


def codegraph_artifact_path(repo_root: str | Path) -> Path:
    return Path(repo_root).expanduser().resolve() / CODEGRAPH_ARTIFACT_RELATIVE_PATH


def write_codegraph_artifact(graph: dict[str, Any]) -> Path:
    repo_root = str(graph.get("repo_root") or "")
    if not repo_root:
        raise ValueError("codegraph artifact is missing repo_root")
    path = codegraph_artifact_path(repo_root)
    atomic_write_json(path, graph)
    return path
