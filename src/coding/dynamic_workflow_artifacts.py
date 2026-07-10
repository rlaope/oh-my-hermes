from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from ..system.local_store import atomic_write_json, atomic_write_text, ensure_dir
from ..system.paths import OmhPaths
from .dynamic_workflow_svg import render_dynamic_workflow_svg

_WORKFLOW_ID_RE = re.compile(r"^dynamic-[0-9a-f]{12}$")


def write_dynamic_coding_workflow(paths: OmhPaths, workflow: dict[str, object]) -> dict[str, object]:
    workflow_id = _validated_workflow_id(workflow.get("workflow_id"))
    workflow_dir = _managed_workflow_dir(paths, workflow_id)
    workflow_path = workflow_dir / "workflow.json"
    chart_path = workflow_dir / "workflow-chart.svg"
    ensure_dir(paths.dynamic_coding_workflows_dir, private=True)
    ensure_dir(workflow_dir, private=True)

    payload = deepcopy(workflow)
    _attach_artifact_paths(payload, workflow_path=str(workflow_path), chart_path=str(chart_path))
    chart_svg = render_dynamic_workflow_svg(payload)
    workflow_preexisted = workflow_path.exists() or workflow_path.is_symlink()
    atomic_write_json(workflow_path, payload, private=True)
    try:
        atomic_write_text(chart_path, chart_svg, private=True)
    except OSError:
        if not workflow_preexisted and workflow_path.exists() and not workflow_path.is_symlink():
            workflow_path.unlink()
        raise
    return payload


def _managed_workflow_dir(paths: OmhPaths, workflow_id: str) -> Path:
    root = paths.dynamic_coding_workflows_dir
    if root.is_symlink():
        raise ValueError("dynamic coding workflow storage must not be a symlink")
    root_resolved = root.resolve(strict=False)
    if not root_resolved.is_relative_to(paths.omh_home.resolve(strict=False)):
        raise ValueError("dynamic coding workflow storage must resolve under OMH home")

    workflow_dir = root / workflow_id
    if workflow_dir.is_symlink():
        raise ValueError("dynamic workflow artifact directory must not be a symlink")
    workflow_dir_resolved = workflow_dir.resolve(strict=False)
    if workflow_dir_resolved.parent != root_resolved:
        raise ValueError("workflow_id must resolve under dynamic coding workflows directory")
    return workflow_dir


def _attach_artifact_paths(payload: dict[str, object], *, workflow_path: str, chart_path: str) -> None:
    chart = payload.get("chart")
    if isinstance(chart, dict):
        chart["chart_path"] = chart_path

    projection = payload.get("message_projection")
    if isinstance(projection, dict):
        attachments = projection.get("attachments")
        if isinstance(attachments, list) and attachments and isinstance(attachments[0], dict):
            attachments[0]["path"] = chart_path

    payload["artifacts"] = {
        "workflow_path": workflow_path,
        "chart_path": chart_path,
        "chart_format": "svg",
        "privacy": "metadata_only",
    }


def _validated_workflow_id(value: object) -> str:
    workflow_id = str(value or "")
    if not _WORKFLOW_ID_RE.fullmatch(workflow_id):
        raise ValueError("workflow_id must match dynamic-<12 lowercase hex chars>")
    return workflow_id
