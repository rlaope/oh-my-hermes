from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .local_store import atomic_write_json, ensure_dir, read_json_object, read_json_object_result, utc_now
from .paths import OmhPaths


OPERATIONS_ARTIFACT_SCHEMA_VERSION = "omh_operation_artifact/v1"
OPERATIONS_INDEX_SCHEMA_VERSION = "omh_operations_index/v1"
SURFACES = ("operating-rhythm", "report-package", "reliability-review")
KINDS_BY_SURFACE = {
    "operating-rhythm": ("meeting", "scrum", "sprint-plan", "sprint-review", "retro", "decision-log"),
    "report-package": ("weekly-report", "monthly-report", "exec-brief", "ppt-outline", "status-package"),
    "reliability-review": ("postmortem", "slo-review", "error-budget", "service-review", "incident-followup"),
}
OBSERVATION_STATUSES = ("prepared", "observed", "mixed", "not_observed")
ARTIFACT_STATUSES = ("draft", "recorded", "blocked", "archived")
OPERATION_SUMMARY_LIMIT = 240
DEFAULT_NOT_EVIDENCE = {
    "operating-rhythm": (
        "meeting_held",
        "decision_acceptance",
        "action_item_acceptance",
        "sprint_completion",
    ),
    "report-package": (
        "source_review_completion",
        "stakeholder_approval",
        "presentation_delivery",
        "decision_acceptance",
        "binary_pptx_export",
    ),
    "reliability-review": (
        "slo_pass",
        "error_budget_healthy",
        "incident_closure",
        "remediation_complete",
        "verification",
    ),
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,159}$")


def new_operation_artifact_id(surface: str, kind: str, now: datetime | str | None = None) -> str:
    validate_surface_kind(surface, kind)
    stamp = _stamp(now)
    return f"{stamp}-{_slugify(surface)}-{_slugify(kind)}-{secrets.token_hex(3)}"


def build_operation_artifact(
    *,
    surface: str,
    kind: str,
    title: str,
    summary: str = "",
    status: str = "draft",
    observation_status: str = "prepared",
    source: str = "",
    inputs_summary: str = "",
    sections: list[str] | None = None,
    decisions: list[str] | None = None,
    action_items: list[str] | None = None,
    metrics: list[str] | None = None,
    references: list[str] | None = None,
    assumptions: list[str] | None = None,
    not_evidence_until_observed: list[str] | None = None,
    artifact_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    validate_surface_kind(surface, kind)
    if status not in ARTIFACT_STATUSES:
        raise ValueError(f"unsupported operation artifact status: {status}")
    if observation_status not in OBSERVATION_STATUSES:
        raise ValueError(f"unsupported operation observation_status: {observation_status}")
    created = created_at or utc_now()
    record = {
        "schema_version": OPERATIONS_ARTIFACT_SCHEMA_VERSION,
        "artifact_id": artifact_id or new_operation_artifact_id(surface, kind, created),
        "surface": surface,
        "kind": kind,
        "title": str(title).strip(),
        "status": status,
        "observation_status": observation_status,
        "created_at": created,
        "updated_at": created,
        "source": str(source).strip(),
        "summary": str(summary).strip(),
        "inputs_summary": str(inputs_summary).strip(),
        "sections": _string_list(sections),
        "decisions": _string_list(decisions),
        "action_items": _string_list(action_items),
        "metrics": _string_list(metrics),
        "references": _string_list(references),
        "assumptions": _string_list(assumptions),
        "not_evidence_until_observed": _string_list(not_evidence_until_observed)
        or list(DEFAULT_NOT_EVIDENCE[surface]),
    }
    errors = validate_operation_artifact(record)
    if errors:
        raise ValueError("; ".join(errors))
    return record


def validate_surface_kind(surface: str, kind: str) -> None:
    if surface not in SURFACES:
        raise ValueError(f"unsupported operation surface: {surface}")
    if kind not in KINDS_BY_SURFACE[surface]:
        raise ValueError(f"unsupported operation kind for {surface}: {kind}")


def validate_operation_artifact(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != OPERATIONS_ARTIFACT_SCHEMA_VERSION:
        errors.append("schema_version must be omh_operation_artifact/v1")
    surface = str(record.get("surface", ""))
    kind = str(record.get("kind", ""))
    try:
        validate_surface_kind(surface, kind)
    except ValueError as exc:
        errors.append(str(exc))
    raw_artifact_id = str(record.get("artifact_id", ""))
    if not raw_artifact_id.strip():
        errors.append("artifact_id is required")
    elif not _valid_artifact_id(raw_artifact_id):
        errors.append("artifact_id must contain only letters, digits, and hyphens, and must not contain path separators")
    if not str(record.get("title", "")).strip():
        errors.append("title is required")
    status = str(record.get("status", ""))
    if status not in ARTIFACT_STATUSES:
        errors.append(f"unsupported operation artifact status: {status}")
    observation_status = str(record.get("observation_status", ""))
    if observation_status not in OBSERVATION_STATUSES:
        errors.append(f"unsupported operation observation_status: {observation_status}")
    for key in (
        "sections",
        "decisions",
        "action_items",
        "metrics",
        "references",
        "assumptions",
        "not_evidence_until_observed",
    ):
        if not isinstance(record.get(key), list):
            errors.append(f"{key} must be a list")
    if observation_status in {"observed", "mixed"} and not _has_observed_evidence(record):
        errors.append("observed or mixed artifacts require supplied source, inputs, sections, decisions, actions, metrics, or references")
    if surface == "report-package":
        forbidden = {"slo_pass", "error_budget_healthy", "incident_closure", "remediation_complete"}
        not_evidence = set(_string_list(record.get("not_evidence_until_observed", [])))
        if forbidden & not_evidence:
            errors.append("report packages must not require reliability evidence links")
    if surface == "reliability-review" and observation_status in {"observed", "mixed"}:
        reliability_evidence = bool(str(record.get("source", "")).strip()) or bool(record.get("metrics")) or bool(record.get("references"))
        if not reliability_evidence:
            errors.append("observed reliability artifacts require source, metric, or reference evidence")
    return errors


def write_operation_artifact(paths: OmhPaths, record: dict[str, Any]) -> dict[str, Any]:
    errors = validate_operation_artifact(record)
    if errors:
        raise ValueError("; ".join(errors))
    artifact_id = str(record["artifact_id"])
    if operation_artifact_exists(paths, artifact_id):
        raise ValueError(f"operation artifact already exists: {artifact_id}")
    path = _artifact_path(paths, str(record["surface"]), artifact_id)
    atomic_write_json(path, record, private=True)
    _write_index_cache(paths)
    return record


def list_operation_artifacts(paths: OmhPaths, *, surface: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    if surface is not None and surface not in SURFACES:
        raise ValueError(f"unsupported operation surface: {surface}")
    records: list[dict[str, Any]] = []
    surfaces = (surface,) if surface else SURFACES
    for item_surface in surfaces:
        for artifact_path in sorted((paths.operations_dir / item_surface).glob("*.json")):
            record, error = read_json_object_result(artifact_path)
            if error:
                continue
            if record:
                records.append(record)
    records.sort(key=lambda item: str(item.get("created_at", "")))
    if limit is not None:
        if limit < 1:
            return []
        records = records[-limit:]
    return records


def show_operation_artifact(paths: OmhPaths, artifact_id: str) -> dict[str, Any]:
    if not _valid_artifact_id(artifact_id):
        raise FileNotFoundError(artifact_id)
    for surface in SURFACES:
        record = read_json_object(_artifact_path(paths, surface, artifact_id))
        if record:
            return record
    raise FileNotFoundError(artifact_id)


def operation_artifact_exists(paths: OmhPaths, artifact_id: str) -> bool:
    if not _valid_artifact_id(artifact_id):
        return False
    return any(_artifact_path(paths, surface, artifact_id).exists() for surface in SURFACES)


def summarize_operation_artifact(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": str(record.get("artifact_id", "")),
        "surface": str(record.get("surface", "")),
        "kind": str(record.get("kind", "")),
        "title": str(record.get("title", "")),
        "status": str(record.get("status", "")),
        "observation_status": str(record.get("observation_status", "")),
        "updated_at": str(record.get("updated_at", "")),
        "summary": _preview(str(record.get("summary", "")), limit=OPERATION_SUMMARY_LIMIT),
        "counts": {
            "sections": len(_string_list(record.get("sections", []))),
            "decisions": len(_string_list(record.get("decisions", []))),
            "action_items": len(_string_list(record.get("action_items", []))),
            "metrics": len(_string_list(record.get("metrics", []))),
            "references": len(_string_list(record.get("references", []))),
        },
    }


def validate_operations_store(paths: OmhPaths) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for surface in SURFACES:
        for artifact_path in sorted((paths.operations_dir / surface).glob("*.json")):
            record, error = read_json_object_result(artifact_path)
            if error:
                errors.append(f"{artifact_path}: {error}")
                continue
            if record:
                records.append(record)
    for record in records:
        artifact_id = str(record.get("artifact_id", ""))
        if artifact_id in seen:
            errors.append(f"duplicate artifact_id: {artifact_id}")
        seen.add(artifact_id)
        for error in validate_operation_artifact(record):
            errors.append(f"{artifact_id or '<unknown>'}: {error}")
    index = read_json_object(paths.operations_index_path)
    index_error = ""
    if index and index.get("schema_version") != OPERATIONS_INDEX_SCHEMA_VERSION:
        index_error = "operations index cache has unsupported schema_version"
    if index_error:
        errors.append(index_error)
    return {
        "schema_version": "omh_operations_validation/v1",
        "ok": not errors,
        "artifact_count": len(records),
        "errors": errors,
        "index_authority": "cache_only",
    }


def export_operation_artifact_markdown(record: dict[str, Any]) -> str:
    errors = validate_operation_artifact(record)
    if errors:
        raise ValueError("; ".join(errors))
    lines = [
        f"# {record['title']}",
        "",
        "## Metadata",
        "",
        f"- Artifact ID: `{record['artifact_id']}`",
        f"- Surface: `{record['surface']}`",
        f"- Kind: `{record['kind']}`",
        f"- Status: `{record['status']}`",
        f"- Observation: `{record['observation_status']}`",
        f"- Source: {record['source'] or 'not provided'}",
        "",
        "## Summary",
        "",
        record["summary"] or "No summary provided.",
    ]
    for key, title in (
        ("sections", "Sections"),
        ("decisions", "Decisions"),
        ("action_items", "Action Items"),
        ("metrics", "Metrics"),
        ("references", "References"),
        ("assumptions", "Assumptions"),
        ("not_evidence_until_observed", "Not Evidence Until Observed"),
    ):
        values = _string_list(record.get(key, []))
        lines.extend(["", f"## {title}", ""])
        if values:
            lines.extend(f"- {value}" for value in values)
        else:
            lines.append("- None")
    return "\n".join(lines).rstrip() + "\n"


def export_operations_bundle(
    paths: OmhPaths,
    *,
    surface: str | None = None,
    format: str = "json",
    limit: int | None = None,
) -> dict[str, Any] | str:
    records = list_operation_artifacts(paths, surface=surface, limit=limit)
    if format == "json":
        return {
            "schema_version": "omh_operations_export/v1",
            "surface": surface or "all",
            "limit": limit if limit is not None else "all",
            "artifacts": records,
            "index_authority": "cache_only",
        }
    elif format == "markdown":
        return "\n".join(export_operation_artifact_markdown(record).rstrip() for record in records).rstrip() + ("\n" if records else "")
    raise ValueError(f"unsupported operations export format: {format}")


def _artifact_path(paths: OmhPaths, surface: str, artifact_id: str) -> Path:
    if not _valid_artifact_id(artifact_id):
        raise ValueError("artifact_id must contain only letters, digits, and hyphens, and must not contain path separators")
    path = paths.operations_dir / surface / f"{artifact_id}.json"
    root = (paths.operations_dir / surface).resolve()
    resolved = path.resolve()
    if resolved.parent != root:
        raise ValueError("artifact_id escapes operations storage")
    return path


def _write_index_cache(paths: OmhPaths) -> None:
    records = list_operation_artifacts(paths)
    ensure_dir(paths.operations_dir, private=True)
    atomic_write_json(
        paths.operations_index_path,
        {
            "schema_version": OPERATIONS_INDEX_SCHEMA_VERSION,
            "updated_at": utc_now(),
            "authority": "cache_only",
            "artifacts": [
                {
                    "artifact_id": record.get("artifact_id", ""),
                    "surface": record.get("surface", ""),
                    "kind": record.get("kind", ""),
                    "title": record.get("title", ""),
                    "status": record.get("status", ""),
                    "observation_status": record.get("observation_status", ""),
                    "updated_at": record.get("updated_at", ""),
                }
                for record in records
            ],
        },
        private=True,
    )


def _stamp(value: datetime | str | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return _slugify(value)[:32] or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return _stamp(parsed)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slugify(value: str) -> str:
    return (_SLUG_RE.sub("-", value.lower()).strip("-") or "operation")[:48].strip("-")


def _valid_artifact_id(value: str) -> bool:
    return bool(_ARTIFACT_ID_RE.fullmatch(str(value)))


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        return [str(value).strip()] if str(value).strip() else []
    return [str(item).strip() for item in value if str(item).strip()]


def _preview(value: str, *, limit: int) -> str:
    clean = " ".join(str(value).split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)].rstrip() + "..."


def _has_observed_evidence(record: dict[str, Any]) -> bool:
    if str(record.get("source", "")).strip() or str(record.get("inputs_summary", "")).strip():
        return True
    return any(record.get(key) for key in ("sections", "decisions", "action_items", "metrics", "references"))
