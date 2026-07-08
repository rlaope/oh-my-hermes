from __future__ import annotations

import re
import secrets
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, TypeAlias
from urllib.parse import urlparse

from omh.local_store import utc_now

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

WEB_VISUAL_QA_PACKAGE_SCHEMA_VERSION: Final = "web_visual_qa_package/v1"
WEB_VISUAL_QA_PACKAGES_INDEX_SCHEMA_VERSION: Final = "omh_web_visual_qa_packages_index/v1"
MESSAGE_ATTACHMENT_PROJECTION_SCHEMA_VERSION: Final = "message_attachment_projection/v1"
WEB_VISUAL_QA_MESSAGE_CARD_SCHEMA_VERSION: Final = "web_visual_qa_message_card/v1"
WEB_VISUAL_QA_MESSAGE_ROUTE_SCHEMA_VERSION: Final = "web_visual_qa_message_route/v1"
WEB_VISUAL_QA_CLAIM_BOUNDARY: Final = (
    "OMH records supplied web visual QA evidence only; it does not capture browsers, call multimodal models, upload "
    "messages, or prove delivery."
)
WEB_VISUAL_QA_PACKAGE_DOES_NOT_PROVE: Final = (
    "browser_capture_performed_by_omh",
    "multimodal_model_called_by_omh",
    "platform_delivery_observed",
    "accessibility_pass",
    "complete_visual_correctness",
)
WEB_VISUAL_QA_MESSAGE_CARD_DOES_NOT_PROVE: Final = ("message_sent", "attachment_uploaded", "platform_delivery")
SUPPORTED_IMAGE_MIME_TYPES: Final = ("image/png", "image/jpeg", "image/webp")
SUPPORTED_VERDICTS: Final = ("pass", "hold", "fail", "not_observed")
SUPPORTED_LIFECYCLE_STATUSES: Final = ("prepared", "captures_observed", "criteria_recorded", "verdict_recorded")
SUPPORTED_RESULT_STATUSES: Final = ("pass", "hold", "fail", "not_observed")
SUPPORTED_SOURCES: Final = ("discord", "slack", "hermes", "generic")
SUPPORTED_COST_TIERS: Final = ("none", "low", "medium", "high", "unknown")
SUPPORTED_CONFIDENCE: Final = ("low", "medium", "high", "unknown")
SUPPORTED_RISK_LEVELS: Final = ("low", "medium", "high", "critical", "unknown")
SUPPORTED_REDACTION_STATUSES: Final = ("not_needed", "redacted", "contains_sensitive_content", "unknown")
SUPPORTED_ATTACHMENT_STATES: Final = ("eligible", "blocked", "not_requested")
OBSERVED_REVIEW_STATUSES: Final = ("observed", "prepared", "not_observed")
_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,120}$")
_MIME_BY_SUFFIX: Final = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def capture_record(item: Mapping[str, JsonValue], index: int, now: str) -> JsonObject:
    record = mapping(item)
    path_or_uri = text(record.get("path_or_uri"))
    capture_id = text(record.get("capture_id")) or f"capture-{index}"
    return {
        "capture_id": capture_id,
        "role": text(record.get("role")) or "current",
        "path_or_uri": path_or_uri,
        "mime_type": mime_type(path_or_uri, text(record.get("mime_type"))),
        "viewport": text(record.get("viewport")) or "unspecified",
        "captured_at": text(record.get("captured_at")) or now,
        "observer": text(record.get("observer")) or "wrapper_or_user",
        "evidence_summary": text(record.get("evidence_summary")),
        "redaction_status": choice(text(record.get("redaction_status")), SUPPORTED_REDACTION_STATUSES, "unknown"),
        "attachment": choice(text(record.get("attachment")), SUPPORTED_ATTACHMENT_STATES, "eligible"),
    }


def criterion_record(item: Mapping[str, JsonValue]) -> JsonObject:
    record = mapping(item)
    return {
        "criterion_id": text(record.get("criterion_id")),
        "label": text(record.get("label")),
        "pass_rule": text(record.get("pass_rule")),
        "severity": text(record.get("severity")) or "blocking",
    }


def criteria_result_record(item: Mapping[str, JsonValue]) -> JsonObject:
    record = mapping(item)
    return {
        "criterion_id": text(record.get("criterion_id")),
        "status": choice(text(record.get("status")), SUPPORTED_RESULT_STATUSES, "not_observed"),
        "evidence_refs": strings(record.get("evidence_refs")),
        "checked_by": text(record.get("checked_by")) or "wrapper",
        "summary": text(record.get("summary")),
        "blocking": bool_value(record.get("blocking"), default=True),
    }


def multimodal_review_record(item: Mapping[str, JsonValue]) -> JsonObject:
    record = mapping(item)
    return {
        "review_id": text(record.get("review_id")),
        "status": choice(text(record.get("status")), OBSERVED_REVIEW_STATUSES, "not_observed"),
        "reviewer": text(record.get("reviewer")) or "host_supplied",
        "cost_tier": choice(text(record.get("cost_tier")), SUPPORTED_COST_TIERS, "unknown"),
        "confidence": choice(text(record.get("confidence")), SUPPORTED_CONFIDENCE, "unknown"),
        "evidence_refs": strings(record.get("evidence_refs")),
        "summary": text(record.get("summary")),
        "does_not_prove": ["visual_qa_pass", "platform_delivery", "model_called_by_omh"],
    }


def auto_routing(
    *,
    risk_level: str,
    estimated_cost_tier: str,
    captures: list[JsonObject],
    criteria: list[JsonObject],
    criteria_results: list[JsonObject],
    multimodal_reviews: list[JsonObject],
) -> JsonObject:
    canonical_risk = choice(risk_level, SUPPORTED_RISK_LEVELS, "unknown")
    canonical_cost = choice(estimated_cost_tier, SUPPORTED_COST_TIERS, "none")
    observed_multimodal = [item for item in multimodal_reviews if item.get("status") == "observed"]
    blocking_criteria_ids = [text(item.get("criterion_id")) for item in criteria if text(item.get("severity")) == "blocking"]
    results_by_criterion = {text(item.get("criterion_id")): item for item in criteria_results}
    unresolved_blocking = [
        criterion_id
        for criterion_id in blocking_criteria_ids
        if criterion_id not in results_by_criterion or results_by_criterion[criterion_id].get("status") != "pass"
    ]
    route = "prepare_capture"
    if not captures:
        route = "prepare_capture"
    elif canonical_risk in {"high", "critical"}:
        route = "request_operator_review"
    elif unresolved_blocking:
        route = "request_operator_review"
    elif observed_multimodal:
        route = "use_observed_multimodal_review"
    elif canonical_risk in {"medium", "unknown"} and canonical_cost in {"none", "low"}:
        route = "request_operator_review"
    elif captures:
        route = "lightweight_capture_review"
    return {
        "schema_version": "web_visual_qa_auto_routing/v1",
        "route": route,
        "cost_policy": "risk_first_cost_aware_host_observed_only",
        "estimated_cost_tier": canonical_cost,
        "decision_inputs": {
            "risk_level": canonical_risk,
            "capture_count": len(captures),
            "criteria_count": len(criteria),
            "blocking_unresolved_count": len(unresolved_blocking),
            "observed_multimodal_review_count": len(observed_multimodal),
        },
        "does_not_authorize": ["model_call", "browser_launch", "platform_upload"],
    }


def attachment_projection(captures: list[JsonObject]) -> JsonObject:
    items: list[JsonValue] = []
    blocked_items: list[JsonValue] = []
    for index, capture in enumerate(captures, start=1):
        capture_id = text(capture.get("capture_id"))
        role = text(capture.get("role"))
        attachment_state = text(capture.get("attachment"))
        redaction_status = text(capture.get("redaction_status"))
        if attachment_state != "eligible" or redaction_status == "contains_sensitive_content":
            blocked_items.append({
                "capture_id": capture_id,
                "role": role,
                "attachment": attachment_state,
                "redaction_status": redaction_status,
                "reason": "capture_not_attachment_eligible",
            })
            continue
        items.append({
            "id": f"attachment-{capture_id}",
            "capture_id": capture_id,
            "path_or_uri": text(capture.get("path_or_uri")),
            "mime_type": text(capture.get("mime_type")),
            "caption": f"{role or 'capture'} web QA capture",
            "alt_text": text(capture.get("evidence_summary")) or f"{role or 'web'} capture",
            "role": role,
            "display_order": index,
            "platform_upload_observed": False,
        })
    return {
        "schema_version": MESSAGE_ATTACHMENT_PROJECTION_SCHEMA_VERSION,
        "delivery_observed": False,
        "items": items,
        "blocked_items": blocked_items,
        "does_not_prove": ["platform_upload", "platform_delivery"],
    }


def lifecycle_status(captures: list[JsonObject], criteria_results: list[JsonObject], verdict: str) -> str:
    if verdict != "not_observed":
        return "verdict_recorded"
    if criteria_results:
        return "criteria_recorded"
    if captures:
        return "captures_observed"
    return "prepared"


def package_id_or_default(package_id: str, target: str) -> str:
    supplied = package_id.strip()
    if supplied:
        return supplied
    slug = re.sub(r"[^A-Za-z0-9]+", "-", target.strip()).strip("-").lower() or "web-qa"
    return f"{slug[:72]}-{secrets.token_hex(3)}"


def messenger_summary(results: list[JsonObject], verdict: str) -> str:
    return f"Web visual QA {verdict}: {len(results)} criteria result(s), screenshots and delivery only count when observed."


def viewport(capture: JsonObject) -> JsonObject:
    return {"capture_id": text(capture.get("capture_id")), "viewport": text(capture.get("viewport")), "role": text(capture.get("role"))}


def mapping(value: Mapping[str, JsonValue]) -> JsonObject:
    return {str(key): item for key, item in value.items()}


def object_value(value: JsonValue | None) -> JsonObject:
    return value if isinstance(value, dict) else {}


def object_list(value: JsonValue | None) -> list[JsonObject]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def item_list(value: JsonValue | None) -> list[JsonValue]:
    return list(value) if isinstance(value, list) else []


def ids(records: list[JsonObject], key: str) -> set[str]:
    return {text(record.get(key)) for record in records if text(record.get(key))}


def strings(value: JsonValue | None) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []


def text(value: JsonValue | None) -> str:
    return str(value).strip() if value is not None else ""


def bool_value(value: JsonValue | None, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def choice(value: str, choices: Sequence[str], fallback: str) -> str:
    return value if value in choices else fallback


def mime_type(path_or_uri: str, supplied_mime_type: str) -> str:
    if supplied_mime_type:
        return supplied_mime_type.lower()
    suffix = Path(urlparse(path_or_uri).path).suffix.lower()
    return _MIME_BY_SUFFIX.get(suffix, "")


def valid_path_or_uri(value: str) -> bool:
    if not value or "\x00" in value:
        return False
    parsed = urlparse(value)
    if parsed.scheme:
        if parsed.scheme == "file":
            return Path(parsed.path).is_absolute()
        return bool(parsed.netloc)
    return Path(value).expanduser().is_absolute()


def valid_id(value: str) -> bool:
    return bool(_ID_RE.match(value)) and "/" not in value and "\\" not in value and ".." not in value


def now() -> str:
    return utc_now()
