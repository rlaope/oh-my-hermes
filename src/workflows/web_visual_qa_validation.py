from __future__ import annotations

from .web_visual_qa_contracts import (
    MESSAGE_ATTACHMENT_PROJECTION_SCHEMA_VERSION,
    PLUGIN_REWRITE_PATTERNS,
    SUPPORTED_AUTO_ROUTES,
    SUPPORTED_ATTACHMENT_STATES,
    SUPPORTED_CAPTURE_ORIGINS,
    SUPPORTED_MESSAGE_DELIVERY_STATES,
    SUPPORTED_MULTIMODAL_STRATEGIES,
    SUPPORTED_ROUTING_SAFETY_FLAGS,
    SUPPORTED_SUGGESTED_ACTIONS,
    SUPPORTED_IMAGE_MIME_TYPES,
    SUPPORTED_LIFECYCLE_STATUSES,
    SUPPORTED_REDACTION_STATUSES,
    SUPPORTED_RESULT_STATUSES,
    SUPPORTED_VERDICTS,
    WEB_VISUAL_QA_MESSAGE_CARD_DOES_NOT_PROVE,
    WEB_VISUAL_QA_MESSAGE_CARD_SCHEMA_VERSION,
    WEB_VISUAL_QA_MESSAGE_ROUTE_SCHEMA_VERSION,
    WEB_VISUAL_QA_PACKAGE_SCHEMA_VERSION,
    JsonObject,
    JsonValue,
    ids,
    object_list,
    object_value,
    strings,
    text,
    valid_id,
    valid_path_or_uri,
    valid_sha256,
)


def validate_web_visual_qa_message_card(record: JsonObject) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != WEB_VISUAL_QA_MESSAGE_CARD_SCHEMA_VERSION:
        errors.append("schema_version must be web_visual_qa_message_card/v1")
    if not valid_id(text(record.get("package_id"))):
        errors.append("package_id must contain only letters, digits, and hyphens")
    if not text(record.get("target")):
        errors.append("target is required")
    if not text(record.get("headline")):
        errors.append("headline is required")
    _validate_message_route(record.get("route"), errors)
    _validate_card_attachment_summary(record.get("attachment_summary"), errors)
    _validate_card_attachment_projection(record.get("attachment_projection"), errors)
    _validate_message_blocks(object_list(record.get("message_blocks")), errors)
    _validate_card_does_not_prove(record, errors)
    return errors


def validate_web_visual_qa_package(record: JsonObject) -> list[str]:
    errors: list[str] = []
    _require_schema(record, errors)
    criteria_ids = ids(object_list(record.get("criteria")), "criterion_id")
    capture_ids = ids(object_list(record.get("captures")), "capture_id")
    trace_ids = ids(object_list(record.get("interaction_traces")), "trace_id")
    evidence_ids = capture_ids | trace_ids
    if not criteria_ids:
        errors.append("criteria must include at least one criterion")
    _validate_captures(object_list(record.get("captures")), errors)
    _validate_results(object_list(record.get("criteria_results")), criteria_ids, evidence_ids, errors)
    _validate_reviews(object_list(record.get("multimodal_reviews")), evidence_ids, errors)
    _validate_projection(record, errors)
    _validate_pass(record, errors)
    return errors


def _validate_captures(captures: list[JsonObject], errors: list[str]) -> None:
    seen: set[str] = set()
    for index, capture in enumerate(captures):
        capture_id = text(capture.get("capture_id"))
        if not valid_id(capture_id):
            errors.append(f"captures[{index}].capture_id must contain only letters, digits, and hyphens")
        if capture_id in seen:
            errors.append(f"captures[{index}].capture_id duplicates another capture")
        seen.add(capture_id)
        if not valid_path_or_uri(text(capture.get("path_or_uri"))):
            errors.append(f"captures[{index}].path_or_uri must be an absolute local path or URI")
        if text(capture.get("mime_type")) not in SUPPORTED_IMAGE_MIME_TYPES:
            errors.append(f"captures[{index}].mime_type must be one of {', '.join(SUPPORTED_IMAGE_MIME_TYPES)}")
        if not text(capture.get("evidence_summary")):
            errors.append(f"captures[{index}].evidence_summary is required")
        if text(capture.get("redaction_status")) not in SUPPORTED_REDACTION_STATUSES:
            errors.append(f"captures[{index}].redaction_status is unsupported")
        attachment = text(capture.get("attachment"))
        if attachment and attachment not in SUPPORTED_ATTACHMENT_STATES:
            errors.append(f"captures[{index}].attachment is unsupported")
        capture_origin = text(capture.get("capture_origin"))
        if capture_origin and capture_origin not in SUPPORTED_CAPTURE_ORIGINS:
            errors.append(f"captures[{index}].capture_origin is unsupported")
        byte_size = capture.get("byte_size")
        byte_size_is_positive_int = isinstance(byte_size, int) and not isinstance(byte_size, bool) and byte_size > 0
        if byte_size is not None and not byte_size_is_positive_int:
            errors.append(f"captures[{index}].byte_size must be a positive integer when supplied")
        sha256 = text(capture.get("sha256"))
        if sha256 and not valid_sha256(sha256):
            errors.append(f"captures[{index}].sha256 must be a lowercase SHA-256 hex digest")
        if capture_origin == "imported_local_file":
            if not byte_size_is_positive_int:
                errors.append(f"captures[{index}].byte_size is required for imported_local_file captures")
            if not valid_sha256(sha256):
                errors.append(f"captures[{index}].sha256 is required for imported_local_file captures")


def _validate_results(
    results: list[JsonObject],
    criteria_ids: set[str],
    evidence_ids: set[str],
    errors: list[str],
) -> None:
    for index, result in enumerate(results):
        if text(result.get("criterion_id")) not in criteria_ids:
            errors.append(f"criteria_results[{index}].criterion_id must reference criteria[].criterion_id")
        if text(result.get("status")) not in SUPPORTED_RESULT_STATUSES:
            errors.append(f"criteria_results[{index}].status is unsupported")
        if not text(result.get("summary")):
            errors.append(f"criteria_results[{index}].summary is required")
        for ref in strings(result.get("evidence_refs")):
            if ref not in evidence_ids:
                errors.append(f"criteria_results[{index}].evidence_refs contains unknown package evidence ref: {ref}")


def _validate_reviews(reviews: list[JsonObject], evidence_ids: set[str], errors: list[str]) -> None:
    for index, review in enumerate(reviews):
        if not valid_id(text(review.get("review_id"))):
            errors.append(f"multimodal_reviews[{index}].review_id must contain only letters, digits, and hyphens")
        if not text(review.get("summary")):
            errors.append(f"multimodal_reviews[{index}].summary is required")
        for ref in strings(review.get("evidence_refs")):
            if ref not in evidence_ids:
                errors.append(f"multimodal_reviews[{index}].evidence_refs contains unknown package evidence ref: {ref}")


def _validate_projection(record: JsonObject, errors: list[str]) -> None:
    projection = record.get("attachment_projection")
    if not isinstance(projection, dict):
        errors.append("attachment_projection must be an object")
        return
    if projection.get("schema_version") != MESSAGE_ATTACHMENT_PROJECTION_SCHEMA_VERSION:
        errors.append("attachment_projection.schema_version must be message_attachment_projection/v1")
    if projection.get("delivery_observed") is not False:
        errors.append("attachment_projection.delivery_observed must remain false until wrapper evidence exists")
    eligible_capture_ids = {
        text(capture.get("capture_id"))
        for capture in object_list(record.get("captures"))
        if text(capture.get("attachment")) == "eligible" and text(capture.get("redaction_status")) != "contains_sensitive_content"
    }
    for index, item in enumerate(object_list(projection.get("items"))):
        if text(item.get("capture_id")) not in eligible_capture_ids:
            errors.append(f"attachment_projection.items[{index}].capture_id must reference an attachment-eligible capture")


def _validate_pass(record: JsonObject, errors: list[str]) -> None:
    if record.get("verdict") != "pass":
        return
    if not object_list(record.get("captures")):
        errors.append("PASS requires at least one observed capture")
    blocking_criteria_ids = [
        text(item.get("criterion_id")) for item in object_list(record.get("criteria")) if text(item.get("severity")) == "blocking"
    ]
    results_by_criterion = {text(item.get("criterion_id")): item for item in object_list(record.get("criteria_results"))}
    missing_or_not_passing = [
        criterion_id
        for criterion_id in blocking_criteria_ids
        if criterion_id not in results_by_criterion or results_by_criterion[criterion_id].get("status") != "pass"
    ]
    if not blocking_criteria_ids or missing_or_not_passing:
        errors.append("PASS requires every blocking criterion result to pass")
    if any(not strings(results_by_criterion[criterion_id].get("evidence_refs")) for criterion_id in blocking_criteria_ids if criterion_id in results_by_criterion):
        errors.append("PASS requires every blocking criterion result to reference observed package evidence")


def _require_schema(record: JsonObject, errors: list[str]) -> None:
    if record.get("schema_version") != WEB_VISUAL_QA_PACKAGE_SCHEMA_VERSION:
        errors.append("schema_version must be web_visual_qa_package/v1")
    if not valid_id(text(record.get("package_id"))):
        errors.append("package_id must contain only letters, digits, and hyphens")
    if text(record.get("status")) not in SUPPORTED_LIFECYCLE_STATUSES:
        errors.append(f"status must be one of {', '.join(SUPPORTED_LIFECYCLE_STATUSES)}")
    if text(record.get("verdict")) not in SUPPORTED_VERDICTS:
        errors.append(f"verdict must be one of {', '.join(SUPPORTED_VERDICTS)}")
    if not text(record.get("target")):
        errors.append("target is required")


def _validate_message_route(raw_route: JsonValue | None, errors: list[str]) -> None:
    if not isinstance(raw_route, dict):
        errors.append("route must be an object")
        return
    route = object_value(raw_route)
    if route.get("schema_version") != WEB_VISUAL_QA_MESSAGE_ROUTE_SCHEMA_VERSION:
        errors.append("route.schema_version must be web_visual_qa_message_route/v1")
    if text(route.get("route")) not in SUPPORTED_AUTO_ROUTES:
        errors.append("route.route is unsupported")
    if not text(route.get("label")):
        errors.append("route.label is required")
    if not text(route.get("next_action")):
        errors.append("route.next_action is required")
    if not text(route.get("reason")):
        errors.append("route.reason is required")
    if text(route.get("multimodal_strategy")) not in SUPPORTED_MULTIMODAL_STRATEGIES:
        errors.append("route.multimodal_strategy is unsupported")
    if text(route.get("message_delivery")) not in SUPPORTED_MESSAGE_DELIVERY_STATES:
        errors.append("route.message_delivery is unsupported")
    for index, flag in enumerate(strings(route.get("safety_flags"))):
        if flag not in SUPPORTED_ROUTING_SAFETY_FLAGS:
            errors.append(f"route.safety_flags[{index}] is unsupported")
    for index, action in enumerate(strings(route.get("suggested_actions"))):
        if action not in SUPPORTED_SUGGESTED_ACTIONS:
            errors.append(f"route.suggested_actions[{index}] is unsupported")
    _validate_routing_basis(object_list(route.get("routing_basis")), errors)


def _validate_routing_basis(items: list[JsonObject], errors: list[str]) -> None:
    allowed_ids = {text(item.get("id")) for item in PLUGIN_REWRITE_PATTERNS}
    for index, item in enumerate(items):
        item_id = text(item.get("id"))
        if item_id not in allowed_ids:
            errors.append(f"route.routing_basis[{index}].id is unsupported")
        if not strings(item.get("source_repos")):
            errors.append(f"route.routing_basis[{index}].source_repos must list source repo ids")
        if not text(item.get("native_rule")):
            errors.append(f"route.routing_basis[{index}].native_rule is required")


def _validate_card_attachment_summary(raw_summary: JsonValue | None, errors: list[str]) -> None:
    if not isinstance(raw_summary, dict):
        errors.append("attachment_summary must be an object")
        return
    summary = object_value(raw_summary)
    if not _non_negative_int(summary.get("eligible_count")):
        errors.append("attachment_summary.eligible_count must be a non-negative integer")
    if not _non_negative_int(summary.get("blocked_count")):
        errors.append("attachment_summary.blocked_count must be a non-negative integer")
    if summary.get("delivery_observed") is not False:
        errors.append("attachment_summary.delivery_observed must remain false until wrapper evidence exists")
    if summary.get("schema_version") != MESSAGE_ATTACHMENT_PROJECTION_SCHEMA_VERSION:
        errors.append("attachment_summary.schema_version must be message_attachment_projection/v1")


def _validate_card_attachment_projection(raw_projection: JsonValue | None, errors: list[str]) -> None:
    if not isinstance(raw_projection, dict):
        errors.append("attachment_projection must be an object")
        return
    projection = object_value(raw_projection)
    if projection.get("schema_version") != MESSAGE_ATTACHMENT_PROJECTION_SCHEMA_VERSION:
        errors.append("attachment_projection.schema_version must be message_attachment_projection/v1")
    if projection.get("delivery_observed") is not False:
        errors.append("attachment_projection.delivery_observed must remain false until wrapper evidence exists")


def _validate_message_blocks(blocks: list[JsonObject], errors: list[str]) -> None:
    if not blocks:
        errors.append("message_blocks must include at least one block")
        return
    for index, block in enumerate(blocks):
        if not text(block.get("type")):
            errors.append(f"message_blocks[{index}].type is required")
        if not text(block.get("text")):
            errors.append(f"message_blocks[{index}].text is required")


def _validate_card_does_not_prove(record: JsonObject, errors: list[str]) -> None:
    non_proofs = set(strings(record.get("does_not_prove")))
    for required in WEB_VISUAL_QA_MESSAGE_CARD_DOES_NOT_PROVE:
        if required not in non_proofs:
            errors.append(f"does_not_prove must include {required}")


def _non_negative_int(value: JsonValue | None) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
