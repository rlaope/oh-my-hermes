from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from omh.local_store import atomic_write_json, ensure_dir, read_json_object_result
from omh.paths import OmhPaths

from .web_visual_qa_contracts import (
    SUPPORTED_COST_TIERS,
    SUPPORTED_RISK_LEVELS,
    SUPPORTED_SOURCES,
    SUPPORTED_VERDICTS,
    WEB_VISUAL_QA_PACKAGES_INDEX_SCHEMA_VERSION,
    WEB_VISUAL_QA_PACKAGE_SCHEMA_VERSION,
    JsonObject,
    JsonValue,
    attachment_projection,
    auto_routing,
    capture_record,
    choice,
    criteria_result_record,
    criterion_record,
    item_list,
    lifecycle_status,
    messenger_summary,
    multimodal_review_record,
    now,
    object_list,
    object_value,
    package_id_or_default,
    text,
    valid_id,
    viewport,
)
from .web_visual_qa_validation import validate_web_visual_qa_package


def build_web_visual_qa_package(
    *,
    package_id: str = "",
    target: str,
    criteria: Sequence[Mapping[str, JsonValue]],
    source: str = "generic",
    risk_level: str = "unknown",
    estimated_cost_tier: str = "none",
    captures: Sequence[Mapping[str, JsonValue]] = (),
    criteria_results: Sequence[Mapping[str, JsonValue]] = (),
    multimodal_reviews: Sequence[Mapping[str, JsonValue]] = (),
    interaction_traces: Sequence[Mapping[str, JsonValue]] = (),
    verdict: str = "not_observed",
    created_at: str = "",
    updated_at: str = "",
) -> JsonObject:
    created = created_at.strip() or now()
    updated = updated_at.strip() or created
    capture_records = [capture_record(item, index, created) for index, item in enumerate(captures, start=1)]
    criteria_records = [criterion_record(item) for item in criteria]
    result_records = [criteria_result_record(item) for item in criteria_results]
    trace_records = [dict(item) for item in interaction_traces]
    review_records = [multimodal_review_record(item) for item in multimodal_reviews]
    attachments = attachment_projection(capture_records)
    canonical_verdict = choice(verdict, SUPPORTED_VERDICTS, "not_observed")
    routing = auto_routing(
        risk_level=risk_level,
        estimated_cost_tier=estimated_cost_tier,
        captures=capture_records,
        criteria=criteria_records,
        criteria_results=result_records,
        multimodal_reviews=review_records,
    )
    return {
        "schema_version": WEB_VISUAL_QA_PACKAGE_SCHEMA_VERSION,
        "package_id": package_id_or_default(package_id, target),
        "status": lifecycle_status(capture_records, result_records, canonical_verdict),
        "source": choice(source, SUPPORTED_SOURCES, "generic"),
        "target": target.strip(),
        "created_at": created,
        "updated_at": updated,
        "risk_level": choice(risk_level, SUPPORTED_RISK_LEVELS, "unknown"),
        "estimated_cost_tier": choice(estimated_cost_tier, SUPPORTED_COST_TIERS, "none"),
        "criteria": criteria_records,
        "criteria_results": result_records,
        "viewport_matrix": [viewport(item) for item in capture_records],
        "captures": capture_records,
        "interaction_traces": trace_records,
        "multimodal_reviews": review_records,
        "verdict": canonical_verdict,
        "attachment_hints": item_list(attachments.get("items")),
        "attachment_projection": attachments,
        "messenger_summary": messenger_summary(result_records, canonical_verdict),
        "routing": routing,
        "claim_boundary": "OMH records supplied web visual QA evidence only; it does not capture browsers, call multimodal models, upload messages, or prove delivery.",
        "does_not_prove": [
            "browser_capture_performed_by_omh",
            "multimodal_model_called_by_omh",
            "platform_delivery_observed",
            "accessibility_pass",
            "complete_visual_correctness",
        ],
    }


def write_web_visual_qa_package(paths: OmhPaths, record: JsonObject) -> JsonObject:
    package_id = text(record.get("package_id"))
    path = _package_path(paths, package_id)
    if path.exists():
        raise ValueError(f"web visual QA package already exists: {package_id}")
    return save_web_visual_qa_package(paths, record)


def save_web_visual_qa_package(paths: OmhPaths, record: JsonObject) -> JsonObject:
    errors = validate_web_visual_qa_package(record)
    if errors:
        raise ValueError("; ".join(errors))
    package_id = text(record.get("package_id"))
    path = _package_path(paths, package_id)
    atomic_write_json(path, record, private=True)
    _write_packages_index(paths)
    return record


def read_web_visual_qa_package(paths: OmhPaths, package_id: str) -> JsonObject:
    path = _package_path(paths, package_id)
    record, error = read_json_object_result(path)
    if error:
        raise ValueError(error)
    if record is None:
        raise ValueError(f"web visual QA package not found: {package_id}")
    return record


def list_web_visual_qa_packages(paths: OmhPaths) -> list[JsonObject]:
    records: list[JsonObject] = []
    for package_path in sorted(paths.web_visual_qa_packages_dir.glob("*.json")):
        if package_path.name == "index.json":
            continue
        record, error = read_json_object_result(package_path)
        if error or record is None:
            continue
        records.append(record)
    records.sort(key=lambda item: text(item.get("created_at")))
    return records


def _write_packages_index(paths: OmhPaths) -> None:
    records = list_web_visual_qa_packages(paths)
    ensure_dir(paths.web_visual_qa_packages_dir, private=True)
    atomic_write_json(
        paths.web_visual_qa_packages_index_path,
        {
            "schema_version": WEB_VISUAL_QA_PACKAGES_INDEX_SCHEMA_VERSION,
            "updated_at": now(),
            "authority": "cache_only",
            "packages": [_summary(record) for record in records],
        },
        private=True,
    )


def _summary(record: JsonObject) -> JsonObject:
    return {
        "package_id": text(record.get("package_id")),
        "target": text(record.get("target")),
        "status": text(record.get("status")),
        "verdict": text(record.get("verdict")),
        "capture_count": len(object_list(record.get("captures"))),
        "routing_route": text(object_value(record.get("routing")).get("route")),
    }


def _package_path(paths: OmhPaths, package_id: str) -> Path:
    if not valid_id(package_id):
        raise ValueError("web visual QA package id must contain only letters, digits, and hyphens")
    path = paths.web_visual_qa_packages_dir / f"{package_id}.json"
    root = paths.web_visual_qa_packages_dir.resolve()
    resolved = path.resolve()
    if resolved.parent != root:
        raise ValueError("package_id escapes web visual QA package storage")
    return path
