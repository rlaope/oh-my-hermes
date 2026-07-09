from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from omh.local_store import ensure_dir
from omh.paths import OmhPaths

from .web_visual_qa import (
    build_web_visual_qa_package,
    read_web_visual_qa_package,
    save_web_visual_qa_package,
)
from .web_visual_qa_contracts import (
    SUPPORTED_IMAGE_MIME_TYPES,
    JsonObject,
    ids,
    now,
    object_list,
    text,
    valid_id,
)


@dataclass(frozen=True, slots=True)
class WebVisualQaCaptureFileImport:
    package_id: str
    capture_id: str
    source_path: Path
    role: str
    viewport: str
    summary: str
    observer: str
    redaction_status: str
    attachment: str
    mime_type: str = ""


@dataclass(frozen=True, slots=True)
class _ManagedCaptureTarget:
    package_id: str
    capture_id: str
    mime_type: str


def import_web_visual_qa_capture_file(paths: OmhPaths, request: WebVisualQaCaptureFileImport) -> JsonObject:
    current = read_web_visual_qa_package(paths, request.package_id)
    capture_id = request.capture_id.strip()
    if not valid_id(capture_id):
        raise ValueError("capture_id must contain only letters, digits, and hyphens")
    if capture_id in ids(object_list(current.get("captures")), "capture_id"):
        raise ValueError(f"web visual QA capture already exists: {capture_id}")
    source_path = request.source_path.expanduser()
    if not source_path.is_file():
        raise ValueError("--source-path must reference an existing local file")
    data = source_path.read_bytes()
    detected_mime = _capture_mime_from_bytes(data)
    if not detected_mime:
        raise ValueError("--source-path must contain PNG, JPEG, or WebP image bytes")
    supplied_mime = request.mime_type.strip().lower()
    if supplied_mime and supplied_mime not in SUPPORTED_IMAGE_MIME_TYPES:
        raise ValueError(f"--mime-type must be one of {', '.join(SUPPORTED_IMAGE_MIME_TYPES)}")
    if supplied_mime and supplied_mime != detected_mime:
        raise ValueError("--mime-type must match the detected image bytes")
    observed_at = now()
    package_id = text(current.get("package_id"))
    destination = _managed_capture_path(
        paths,
        _ManagedCaptureTarget(package_id=package_id, capture_id=capture_id, mime_type=detected_mime),
    )
    _write_capture_bytes(destination, data)
    updated = build_web_visual_qa_package(
        package_id=package_id,
        target=text(current.get("target")),
        source=text(current.get("source")) or "generic",
        risk_level=text(current.get("risk_level")) or "unknown",
        estimated_cost_tier=text(current.get("estimated_cost_tier")) or "none",
        criteria=object_list(current.get("criteria")),
        captures=object_list(current.get("captures"))
        + [
            {
                "capture_id": capture_id,
                "role": request.role.strip() or "current",
                "path_or_uri": str(destination),
                "mime_type": detected_mime,
                "viewport": request.viewport.strip() or "unspecified",
                "captured_at": observed_at,
                "evidence_summary": request.summary.strip(),
                "observer": request.observer.strip() or "wrapper_or_user",
                "redaction_status": request.redaction_status,
                "attachment": request.attachment,
                "capture_origin": "imported_local_file",
                "byte_size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        ],
        criteria_results=object_list(current.get("criteria_results")),
        multimodal_reviews=object_list(current.get("multimodal_reviews")),
        interaction_traces=object_list(current.get("interaction_traces")),
        verdict=text(current.get("verdict")) or "not_observed",
        created_at=text(current.get("created_at")),
        updated_at=observed_at,
    )
    return save_web_visual_qa_package(paths, updated)


def _managed_capture_path(paths: OmhPaths, target: _ManagedCaptureTarget) -> Path:
    extension = _capture_extension(target.mime_type)
    directory = paths.web_visual_qa_dir / "captures" / target.package_id
    destination = directory / f"{target.capture_id}{extension}"
    root = directory.resolve()
    resolved = destination.resolve()
    if resolved.parent != root:
        raise ValueError("capture_id escapes web visual QA capture storage")
    if resolved.exists():
        raise ValueError(f"managed web visual QA capture already exists: {target.capture_id}")
    return resolved


def _write_capture_bytes(path: Path, data: bytes) -> None:
    ensure_dir(path.parent, private=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.chmod(0o600)
        tmp.replace(path)
        path.chmod(0o600)
    except OSError:
        if tmp.exists():
            tmp.unlink()
        raise


def _capture_mime_from_bytes(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _capture_extension(mime_type: str) -> str:
    match mime_type:
        case "image/png":
            return ".png"
        case "image/jpeg":
            return ".jpg"
        case "image/webp":
            return ".webp"
        case _:
            raise ValueError(f"unsupported image MIME type: {mime_type}")
