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
WEB_VISUAL_QA_CHANNEL_DELIVERY_SCHEMA_VERSION: Final = "web_visual_qa_channel_delivery/v1"
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
SUPPORTED_RENDERER_TARGETS: Final = ("discord", "slack", "telegram")
SUPPORTED_COST_TIERS: Final = ("none", "low", "medium", "high", "unknown")
SUPPORTED_CONFIDENCE: Final = ("low", "medium", "high", "unknown")
SUPPORTED_RISK_LEVELS: Final = ("low", "medium", "high", "critical", "unknown")
SUPPORTED_REDACTION_STATUSES: Final = ("not_needed", "redacted", "contains_sensitive_content", "unknown")
SUPPORTED_ATTACHMENT_STATES: Final = ("eligible", "blocked", "not_requested")
SUPPORTED_CAPTURE_ORIGINS: Final = ("supplied_metadata", "imported_local_file")
OBSERVED_REVIEW_STATUSES: Final = ("observed", "prepared", "not_observed")
SUPPORTED_AUTO_ROUTES: Final = (
    "prepare_capture",
    "redact_before_message",
    "request_operator_review",
    "use_observed_multimodal_review",
    "lightweight_capture_review",
)
SUPPORTED_MULTIMODAL_STRATEGIES: Final = (
    "capture_first",
    "redact_before_multimodal_or_attachment",
    "operator_first_due_to_risk",
    "operator_review_due_to_cost_or_unresolved_criteria",
    "use_observed_host_multimodal_review",
    "operator_review_before_low_cost_multimodal",
    "prepared_review_needs_observation",
    "text_and_capture_review_without_model_call",
)
SUPPORTED_MESSAGE_DELIVERY_STATES: Final = (
    "prepare_message_card_with_attachments",
    "prepare_message_card_without_attachments",
)
SUPPORTED_ROUTING_SAFETY_FLAGS: Final = (
    "sensitive_capture_requires_redaction",
    "high_risk_requires_operator_review",
    "cost_requires_operator_or_text_only_review",
    "blocking_criteria_unresolved",
    "no_additional_safety_flag",
)
SUPPORTED_SUGGESTED_ACTIONS: Final = (
    "record_capture",
    "record_redacted_capture",
    "record_operator_review",
    "record_host_multimodal_review",
    "record_visual_qa_verdict",
)
PLUGIN_REWRITE_PATTERNS: Final = (
    {
        "id": "cost_guard_before_multimodal",
        "source_repos": ("evey-cost-guard", "evey-delegate-model"),
        "native_rule": "Treat multimodal review as host-supplied evidence and route by risk plus estimated cost before asking for it.",
    },
    {
        "id": "explicit_action_reason_for_message_delivery",
        "source_repos": ("hermes-tweet", "evey-verification"),
        "native_rule": "Prepare message cards and attachment projections locally; platform upload remains a separate observed action.",
    },
    {
        "id": "redaction_before_recall_or_attachment",
        "source_repos": ("mem9-hermes-plugin", "scope-recall-hermes"),
        "native_rule": "Never attach sensitive captures until the wrapper/user supplies redacted evidence.",
    },
    {
        "id": "normalized_visual_evidence",
        "source_repos": ("hermes-brave-search-plugin", "hermes-kagi-plugin", "yantrikdb-hermes-plugin"),
        "native_rule": "Normalize source, capture, viewport, and review metadata before generating a shareable QA card.",
    },
)
_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,120}$")
_SHA256_RE: Final = re.compile(r"^[a-f0-9]{64}$")
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
        "capture_origin": choice(text(record.get("capture_origin")), SUPPORTED_CAPTURE_ORIGINS, "supplied_metadata"),
        "byte_size": optional_non_negative_int(record.get("byte_size")),
        "sha256": text(record.get("sha256")),
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
    prepared_multimodal = [item for item in multimodal_reviews if item.get("status") == "prepared"]
    blocking_criteria_ids = [text(item.get("criterion_id")) for item in criteria if text(item.get("severity")) == "blocking"]
    results_by_criterion = {text(item.get("criterion_id")): item for item in criteria_results}
    unresolved_blocking = [
        criterion_id
        for criterion_id in blocking_criteria_ids
        if criterion_id not in results_by_criterion or results_by_criterion[criterion_id].get("status") != "pass"
    ]
    sensitive_capture_count = sum(
        1 for item in captures if text(item.get("redaction_status")) == "contains_sensitive_content"
    )
    attachment_eligible_count = sum(
        1
        for item in captures
        if text(item.get("attachment")) == "eligible"
        and text(item.get("redaction_status")) != "contains_sensitive_content"
    )
    low_cost_multimodal_possible = canonical_cost in {"none", "low"}
    suggested_actions: list[JsonValue] = []
    route = "prepare_capture"
    multimodal_strategy = "capture_first"
    if not captures:
        route = "prepare_capture"
        suggested_actions.append("record_capture")
    elif sensitive_capture_count:
        route = "redact_before_message"
        multimodal_strategy = "redact_before_multimodal_or_attachment"
        suggested_actions.append("record_redacted_capture")
    elif canonical_risk in {"high", "critical"}:
        route = "request_operator_review"
        multimodal_strategy = "operator_first_due_to_risk"
        suggested_actions.append("record_operator_review")
    elif unresolved_blocking:
        route = "request_operator_review"
        multimodal_strategy = (
            "operator_review_before_low_cost_multimodal"
            if low_cost_multimodal_possible
            else "operator_review_due_to_cost_or_unresolved_criteria"
        )
        suggested_actions.append("record_operator_review")
        if low_cost_multimodal_possible:
            suggested_actions.append("record_host_multimodal_review")
    elif observed_multimodal:
        route = "use_observed_multimodal_review"
        multimodal_strategy = "use_observed_host_multimodal_review"
        suggested_actions.append("record_visual_qa_verdict")
    elif canonical_risk in {"medium", "unknown"} and low_cost_multimodal_possible:
        route = "request_operator_review"
        multimodal_strategy = "operator_review_before_low_cost_multimodal"
        suggested_actions.extend(("record_operator_review", "record_host_multimodal_review"))
    elif prepared_multimodal:
        route = "request_operator_review"
        multimodal_strategy = "prepared_review_needs_observation"
        suggested_actions.append("record_operator_review")
    elif captures:
        route = "lightweight_capture_review"
        multimodal_strategy = "text_and_capture_review_without_model_call"
        suggested_actions.append("record_visual_qa_verdict")
    return {
        "schema_version": "web_visual_qa_auto_routing/v1",
        "route": route,
        "cost_policy": "risk_first_cost_aware_host_observed_only",
        "estimated_cost_tier": canonical_cost,
        "multimodal_strategy": multimodal_strategy,
        "message_delivery": (
            "prepare_message_card_with_attachments"
            if attachment_eligible_count and not sensitive_capture_count
            else "prepare_message_card_without_attachments"
        ),
        "suggested_actions": _unique_suggested_actions(suggested_actions),
        "decision_inputs": {
            "risk_level": canonical_risk,
            "capture_count": len(captures),
            "attachment_eligible_count": attachment_eligible_count,
            "sensitive_capture_count": sensitive_capture_count,
            "criteria_count": len(criteria),
            "blocking_unresolved_count": len(unresolved_blocking),
            "observed_multimodal_review_count": len(observed_multimodal),
            "prepared_multimodal_review_count": len(prepared_multimodal),
        },
        "routing_basis": [_plugin_rewrite_pattern(item) for item in PLUGIN_REWRITE_PATTERNS],
        "safety_flags": _safety_flags(
            captures=captures,
            canonical_risk=canonical_risk,
            canonical_cost=canonical_cost,
            unresolved_blocking=unresolved_blocking,
        ),
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
            "capture_origin": text(capture.get("capture_origin")),
            "byte_size": optional_non_negative_int(capture.get("byte_size")),
            "sha256": text(capture.get("sha256")),
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


def _safety_flags(
    *,
    captures: list[JsonObject],
    canonical_risk: str,
    canonical_cost: str,
    unresolved_blocking: list[str],
) -> list[JsonValue]:
    flags: list[JsonValue] = []
    if any(text(item.get("redaction_status")) == "contains_sensitive_content" for item in captures):
        flags.append("sensitive_capture_requires_redaction")
    if canonical_risk in {"high", "critical"}:
        flags.append("high_risk_requires_operator_review")
    if canonical_cost in {"medium", "high", "unknown"}:
        flags.append("cost_requires_operator_or_text_only_review")
    if unresolved_blocking:
        flags.append("blocking_criteria_unresolved")
    if not flags:
        flags.append("no_additional_safety_flag")
    return flags


def _plugin_rewrite_pattern(item: Mapping[str, object]) -> JsonObject:
    raw_sources = item.get("source_repos")
    sources = raw_sources if isinstance(raw_sources, (list, tuple)) else ()
    return {
        "id": text(item.get("id")),
        "source_repos": [text(value) for value in sources if text(value)],
        "native_rule": text(item.get("native_rule")),
    }


def _unique_suggested_actions(actions: list[JsonValue]) -> list[JsonValue]:
    seen: set[str] = set()
    output: list[JsonValue] = []
    for action in actions:
        action_text = text(action)
        if action_text not in SUPPORTED_SUGGESTED_ACTIONS or action_text in seen:
            continue
        seen.add(action_text)
        output.append(action_text)
    return output


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


def optional_non_negative_int(value: JsonValue | None) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


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


def valid_sha256(value: str) -> bool:
    return bool(_SHA256_RE.match(value))


def now() -> str:
    return utc_now()
