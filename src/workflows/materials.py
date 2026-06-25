from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..local_store import atomic_write_json, ensure_dir, read_json_object, read_json_object_result, utc_now
from ..paths import OmhPaths


MATERIAL_ARTIFACT_SCHEMA_VERSION = "omh_material_artifact/v1"
MATERIALS_INDEX_SCHEMA_VERSION = "omh_materials_index/v1"
MATERIAL_KINDS = ("deck", "report", "proposal", "spreadsheet", "document", "memo", "upload-package")
MATERIAL_FORMATS = ("md", "json", "pptx", "pdf", "keynote", "docx", "xlsx", "csv", "hwp")
EXPORT_STATUSES = ("not_requested", "prepared", "handoff_prepared", "observed", "blocked")
QA_STATUSES = ("planned", "observed", "blocked", "not_applicable")
MATERIAL_SUMMARY_LIMIT = 240

DEFAULT_NOT_EVIDENCE = (
    "source_review_completion",
    "binary_export",
    "render_qa",
    "formula_recalculation",
    "stakeholder_approval",
    "presentation_delivery",
    "external_upload",
)

FORMAT_QA_LADDER = {
    "md": ("outline_schema", "heading_structure", "link_table_check"),
    "json": ("schema_validation", "required_fields", "redaction_check"),
    "pptx": ("slide_count", "render_screenshot", "overflow_or_missing_media_check"),
    "pdf": ("page_count", "render_preview", "link_or_attachment_check"),
    "keynote": ("handoff_format_check", "slide_count", "export_observation"),
    "docx": ("page_count", "section_structure", "required_clause_check"),
    "hwp": ("handoff_format_check", "locale_font_check", "export_observation"),
    "xlsx": ("sheet_schema", "formula_recalculation", "chart_table_check"),
    "csv": ("row_count", "header_schema", "encoding_check"),
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MATERIAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,159}$")


def new_material_id(kind: str, now: datetime | str | None = None) -> str:
    validate_material_kind(kind)
    return f"{_stamp(now)}-{_slugify(kind)}-{secrets.token_hex(3)}"


def build_material_artifact(
    *,
    kind: str,
    title: str,
    target_formats: list[str] | None = None,
    summary: str = "",
    audience: str = "",
    source_inputs: list[str] | None = None,
    outline_sections: list[str] | None = None,
    assumptions: list[str] | None = None,
    missing_inputs: list[str] | None = None,
    export_status: str = "prepared",
    handoff_target: str = "",
    observed_files: list[str] | None = None,
    qa_checks: list[dict[str, str]] | None = None,
    approvals: list[str] | None = None,
    not_evidence_until_observed: list[str] | None = None,
    material_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    validate_material_kind(kind)
    formats = _formats(target_formats or ["md"])
    if export_status not in EXPORT_STATUSES:
        raise ValueError(f"unsupported material export_status: {export_status}")
    created = created_at or utc_now()
    record = {
        "schema_version": MATERIAL_ARTIFACT_SCHEMA_VERSION,
        "material_id": material_id or new_material_id(kind, created),
        "kind": kind,
        "title": str(title).strip(),
        "summary": str(summary).strip(),
        "audience": str(audience).strip(),
        "target_formats": formats,
        "source_inputs": _string_list(source_inputs),
        "outline_sections": _string_list(outline_sections),
        "assumptions": _string_list(assumptions),
        "missing_inputs": _string_list(missing_inputs),
        "export_status": export_status,
        "handoff_target": str(handoff_target).strip(),
        "observed_files": _string_list(observed_files),
        "qa_checks": _qa_checks(qa_checks, formats),
        "approvals": _string_list(approvals),
        "not_evidence_until_observed": _string_list(not_evidence_until_observed) or list(DEFAULT_NOT_EVIDENCE),
        "created_at": created,
        "updated_at": created,
    }
    errors = validate_material_artifact(record)
    if errors:
        raise ValueError("; ".join(errors))
    return record


def validate_material_kind(kind: str) -> None:
    if kind not in MATERIAL_KINDS:
        raise ValueError(f"unsupported material kind: {kind}")


def validate_material_artifact(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != MATERIAL_ARTIFACT_SCHEMA_VERSION:
        errors.append("schema_version must be omh_material_artifact/v1")
    raw_id = str(record.get("material_id", ""))
    if not raw_id.strip():
        errors.append("material_id is required")
    elif not _valid_material_id(raw_id):
        errors.append("material_id must contain only letters, digits, and hyphens, and must not contain path separators")
    kind = str(record.get("kind", ""))
    try:
        validate_material_kind(kind)
    except ValueError as exc:
        errors.append(str(exc))
    if not str(record.get("title", "")).strip():
        errors.append("title is required")
    export_status = str(record.get("export_status", ""))
    if export_status not in EXPORT_STATUSES:
        errors.append(f"unsupported material export_status: {export_status}")
    for key in (
        "target_formats",
        "source_inputs",
        "outline_sections",
        "assumptions",
        "missing_inputs",
        "observed_files",
        "qa_checks",
        "approvals",
        "not_evidence_until_observed",
    ):
        if not isinstance(record.get(key), list):
            errors.append(f"{key} must be a list")
    formats = _string_list(record.get("target_formats", []))
    for item in formats:
        if item not in MATERIAL_FORMATS:
            errors.append(f"unsupported material target format: {item}")
    if export_status == "observed" and not _string_list(record.get("observed_files", [])):
        errors.append("observed material export requires observed_files")
    qa_checks = record.get("qa_checks", [])
    if isinstance(qa_checks, list):
        for index, check in enumerate(qa_checks, start=1):
            if not isinstance(check, dict):
                errors.append(f"qa_checks[{index}] must be an object")
                continue
            status = str(check.get("status", ""))
            if status not in QA_STATUSES:
                errors.append(f"qa_checks[{index}].status must be one of {', '.join(QA_STATUSES)}")
            if not str(check.get("check", "")).strip():
                errors.append(f"qa_checks[{index}].check is required")
            if str(check.get("format", "")) not in MATERIAL_FORMATS:
                errors.append(f"qa_checks[{index}].format must be one of {', '.join(MATERIAL_FORMATS)}")
            if status == "observed" and not str(check.get("evidence", "")).strip():
                errors.append(f"qa_checks[{index}].observed requires evidence")
    if export_status == "observed" and not _has_observed_qa(record):
        errors.append("observed material export requires at least one observed QA check")
    return errors


def write_material_artifact(paths: OmhPaths, record: dict[str, Any]) -> dict[str, Any]:
    errors = validate_material_artifact(record)
    if errors:
        raise ValueError("; ".join(errors))
    material_id = str(record["material_id"])
    if material_artifact_exists(paths, material_id):
        raise ValueError(f"material artifact already exists: {material_id}")
    atomic_write_json(_material_path(paths, material_id), record, private=True)
    _write_index_cache(paths)
    return record


def list_material_artifacts(paths: OmhPaths, *, kind: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    if kind is not None:
        validate_material_kind(kind)
    records: list[dict[str, Any]] = []
    for material_path in sorted(paths.materials_dir.glob("*.json")):
        if material_path.name == "index.json":
            continue
        record, error = read_json_object_result(material_path)
        if error or not record:
            continue
        if kind and record.get("kind") != kind:
            continue
        records.append(record)
    records.sort(key=lambda item: str(item.get("created_at", "")))
    if limit is not None:
        if limit < 1:
            return []
        records = records[-limit:]
    return records


def show_material_artifact(paths: OmhPaths, material_id: str) -> dict[str, Any]:
    if not _valid_material_id(material_id):
        raise FileNotFoundError(material_id)
    record = read_json_object(_material_path(paths, material_id))
    if not record:
        raise FileNotFoundError(material_id)
    return record


def material_artifact_exists(paths: OmhPaths, material_id: str) -> bool:
    if not _valid_material_id(material_id):
        return False
    return _material_path(paths, material_id).exists()


def summarize_material_artifact(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "material_id": str(record.get("material_id", "")),
        "kind": str(record.get("kind", "")),
        "title": str(record.get("title", "")),
        "target_formats": _string_list(record.get("target_formats", [])),
        "export_status": str(record.get("export_status", "")),
        "updated_at": str(record.get("updated_at", "")),
        "summary": _preview(str(record.get("summary", "")), limit=MATERIAL_SUMMARY_LIMIT),
        "counts": {
            "source_inputs": len(_string_list(record.get("source_inputs", []))),
            "outline_sections": len(_string_list(record.get("outline_sections", []))),
            "missing_inputs": len(_string_list(record.get("missing_inputs", []))),
            "observed_files": len(_string_list(record.get("observed_files", []))),
            "qa_checks": len(record.get("qa_checks", []) if isinstance(record.get("qa_checks"), list) else []),
        },
    }


def validate_materials_store(paths: OmhPaths) -> dict[str, Any]:
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for material_path in sorted(paths.materials_dir.glob("*.json")):
        if material_path.name == "index.json":
            continue
        record, error = read_json_object_result(material_path)
        if error:
            errors.append(f"{material_path}: {error}")
            continue
        if record:
            records.append(record)
    for record in records:
        material_id = str(record.get("material_id", ""))
        if material_id in seen:
            errors.append(f"duplicate material_id: {material_id}")
        seen.add(material_id)
        for error in validate_material_artifact(record):
            errors.append(f"{material_id or '<unknown>'}: {error}")
    index = read_json_object(paths.materials_index_path)
    if index and index.get("schema_version") != MATERIALS_INDEX_SCHEMA_VERSION:
        errors.append("materials index cache has unsupported schema_version")
    return {
        "schema_version": "omh_materials_validation/v1",
        "ok": not errors,
        "artifact_count": len(records),
        "errors": errors,
        "index_authority": "cache_only",
    }


def export_material_artifact_markdown(record: dict[str, Any]) -> str:
    errors = validate_material_artifact(record)
    if errors:
        raise ValueError("; ".join(errors))
    lines = [
        f"# {record['title']}",
        "",
        "## Metadata",
        "",
        f"- Material ID: `{record['material_id']}`",
        f"- Kind: `{record['kind']}`",
        f"- Target formats: {', '.join(record['target_formats']) or 'not provided'}",
        f"- Export status: `{record['export_status']}`",
        f"- Handoff target: {record['handoff_target'] or 'not selected'}",
        "",
        "## Summary",
        "",
        record["summary"] or "No summary provided.",
    ]
    for key, title in (
        ("source_inputs", "Source Inputs"),
        ("outline_sections", "Outline Sections"),
        ("assumptions", "Assumptions"),
        ("missing_inputs", "Missing Inputs"),
        ("observed_files", "Observed Files"),
        ("approvals", "Approvals"),
        ("not_evidence_until_observed", "Not Evidence Until Observed"),
    ):
        lines.extend(["", f"## {title}", ""])
        values = _string_list(record.get(key, []))
        lines.extend(f"- {value}" for value in values) if values else lines.append("- None")
    lines.extend(["", "## QA Checks", ""])
    qa_checks = record.get("qa_checks", [])
    if qa_checks:
        for check in qa_checks:
            evidence = f" evidence={check.get('evidence')}" if check.get("evidence") else ""
            lines.append(f"- {check.get('format')}: {check.get('check')} [{check.get('status')}]{evidence}")
    else:
        lines.append("- None")
    return "\n".join(lines).rstrip() + "\n"


def export_materials_bundle(
    paths: OmhPaths,
    *,
    kind: str | None = None,
    format: str = "json",
    limit: int | None = None,
) -> dict[str, Any] | str:
    records = list_material_artifacts(paths, kind=kind, limit=limit)
    if format == "json":
        return {
            "schema_version": "omh_materials_export/v1",
            "kind": kind or "all",
            "limit": limit if limit is not None else "all",
            "artifacts": records,
            "index_authority": "cache_only",
        }
    if format == "markdown":
        return "\n".join(export_material_artifact_markdown(record).rstrip() for record in records).rstrip() + ("\n" if records else "")
    raise ValueError(f"unsupported materials export format: {format}")


def material_qa_ladder(formats: list[str] | None = None) -> dict[str, Any]:
    selected = _formats(formats or list(MATERIAL_FORMATS))
    return {
        "schema_version": "omh_material_qa_ladder/v1",
        "formats": {
            item: {
                "checks": list(FORMAT_QA_LADDER[item]),
                "boundary": "planned checks are not observed QA evidence until a wrapper or operator records evidence",
            }
            for item in selected
        },
    }


def _material_path(paths: OmhPaths, material_id: str) -> Path:
    if not _valid_material_id(material_id):
        raise ValueError("material_id must contain only letters, digits, and hyphens, and must not contain path separators")
    path = paths.materials_dir / f"{material_id}.json"
    root = paths.materials_dir.resolve()
    resolved = path.resolve()
    if resolved.parent != root:
        raise ValueError("material_id escapes materials storage")
    return path


def _write_index_cache(paths: OmhPaths) -> None:
    records = list_material_artifacts(paths)
    ensure_dir(paths.materials_dir, private=True)
    atomic_write_json(
        paths.materials_index_path,
        {
            "schema_version": MATERIALS_INDEX_SCHEMA_VERSION,
            "updated_at": utc_now(),
            "authority": "cache_only",
            "artifacts": [summarize_material_artifact(record) for record in records],
        },
        private=True,
    )


def _qa_checks(values: list[dict[str, str]] | None, formats: list[str]) -> list[dict[str, str]]:
    if values:
        return [
            {
                "format": str(item.get("format", "")).strip(),
                "check": str(item.get("check", "")).strip(),
                "status": str(item.get("status", "planned")).strip() or "planned",
                "evidence": str(item.get("evidence", "")).strip(),
            }
            for item in values
        ]
    checks: list[dict[str, str]] = []
    for material_format in formats:
        for check in FORMAT_QA_LADDER[material_format]:
            checks.append({"format": material_format, "check": check, "status": "planned", "evidence": ""})
    return checks


def _formats(values: list[str]) -> list[str]:
    normalized = []
    for value in values:
        item = str(value).strip().lower()
        if item == "key":
            item = "keynote"
        if item and item not in normalized:
            normalized.append(item)
    if not normalized:
        normalized = ["md"]
    for item in normalized:
        if item not in MATERIAL_FORMATS:
            raise ValueError(f"unsupported material target format: {item}")
    return normalized


def _string_list(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    return [str(value).strip() for value in values if str(value).strip()]


def _has_observed_qa(record: dict[str, Any]) -> bool:
    checks = record.get("qa_checks", [])
    return any(isinstance(check, dict) and check.get("status") == "observed" for check in checks)


def _valid_material_id(value: str) -> bool:
    return bool(_MATERIAL_ID_RE.match(value)) and "/" not in value and "\\" not in value and ".." not in value


def _preview(value: str, *, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


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
    return (_SLUG_RE.sub("-", value.lower()).strip("-") or "material")[:48].strip("-")
