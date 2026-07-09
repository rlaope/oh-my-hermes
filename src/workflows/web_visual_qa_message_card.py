from __future__ import annotations

from .web_visual_qa_contracts import (
    WEB_VISUAL_QA_CLAIM_BOUNDARY,
    WEB_VISUAL_QA_MESSAGE_CARD_DOES_NOT_PROVE,
    WEB_VISUAL_QA_MESSAGE_CARD_SCHEMA_VERSION,
    WEB_VISUAL_QA_MESSAGE_ROUTE_SCHEMA_VERSION,
    JsonObject,
    JsonValue,
    object_list,
    object_value,
    text,
)


def build_web_visual_qa_message_card(package: JsonObject) -> JsonObject:
    target = text(package.get("target"))
    verdict = text(package.get("verdict")) or "not_observed"
    route = _route_summary(object_value(package.get("routing")))
    criteria = _criteria_cards(package)
    captures = _capture_cards(package)
    attachment_projection = object_value(package.get("attachment_projection"))
    attachment_summary = _attachment_summary(attachment_projection)
    multimodal = _multimodal_summary(object_list(package.get("multimodal_reviews")))
    headline = f"Web visual QA {verdict}: {target}"
    claim_boundary = text(package.get("claim_boundary")) or WEB_VISUAL_QA_CLAIM_BOUNDARY
    return {
        "schema_version": WEB_VISUAL_QA_MESSAGE_CARD_SCHEMA_VERSION,
        "package_id": text(package.get("package_id")),
        "source": text(package.get("source")) or "generic",
        "target": target,
        "status": text(package.get("status")),
        "verdict": verdict,
        "headline": headline,
        "route": route,
        "criteria": criteria,
        "captures": captures,
        "attachment_summary": attachment_summary,
        "attachment_projection": attachment_projection,
        "multimodal_review_summary": multimodal,
        "message_blocks": _message_blocks(
            headline=headline,
            route=route,
            criteria=criteria,
            attachment_summary=attachment_summary,
            multimodal=multimodal,
            claim_boundary=claim_boundary,
        ),
        "claim_boundary": claim_boundary,
        "does_not_prove": _does_not_prove(package),
    }


def _route_summary(routing: JsonObject) -> JsonObject:
    route = text(routing.get("route")) or "prepare_capture"
    label, next_action, reason = _route_copy(route)
    decision_inputs = object_value(routing.get("decision_inputs"))
    return {
        "schema_version": WEB_VISUAL_QA_MESSAGE_ROUTE_SCHEMA_VERSION,
        "route": route,
        "label": label,
        "next_action": next_action,
        "reason": reason,
        "cost_policy": text(routing.get("cost_policy")),
        "estimated_cost_tier": text(routing.get("estimated_cost_tier")) or "unknown",
        "multimodal_strategy": text(routing.get("multimodal_strategy")),
        "message_delivery": text(routing.get("message_delivery")),
        "decision_inputs": decision_inputs,
        "safety_flags": _strings(routing.get("safety_flags")),
        "suggested_actions": _strings(routing.get("suggested_actions")),
        "routing_basis": _routing_basis_cards(routing),
    }


def _route_copy(route: str) -> tuple[str, str, str]:
    match route:
        case "prepare_capture":
            return ("Capture needed", "record_capture", "No screenshot or visual capture evidence is recorded yet.")
        case "redact_before_message":
            return (
                "Redaction required",
                "record_redacted_capture",
                "At least one capture is marked sensitive, so attachment and multimodal review must wait.",
            )
        case "request_operator_review":
            return (
                "Operator review required",
                "record_operator_review",
                "Risk, unresolved criteria, sensitivity, or cost policy requires human/host review.",
            )
        case "use_observed_multimodal_review":
            return ("Use observed multimodal review", "record_visual_qa_verdict", "A host-supplied multimodal review exists after risk and blocking gates.")
        case "lightweight_capture_review":
            return ("Lightweight capture review", "record_visual_qa_verdict", "Captured evidence is present and no higher review gate is required.")
        case _:
            return ("Unknown route", "inspect_package", "The routing value is not recognized by this OMH version.")


def _criteria_cards(package: JsonObject) -> list[JsonValue]:
    results = {text(item.get("criterion_id")): item for item in object_list(package.get("criteria_results"))}
    cards: list[JsonValue] = []
    for criterion in object_list(package.get("criteria")):
        criterion_id = text(criterion.get("criterion_id"))
        result = object_value(results.get(criterion_id))
        cards.append(
            {
                "criterion_id": criterion_id,
                "label": text(criterion.get("label")),
                "pass_rule": text(criterion.get("pass_rule")),
                "severity": text(criterion.get("severity")) or "blocking",
                "status": text(result.get("status")) or "not_observed",
                "evidence_refs": _strings(result.get("evidence_refs")),
                "summary": text(result.get("summary")),
                "blocking": bool(result.get("blocking", text(criterion.get("severity")) == "blocking")),
            }
        )
    return cards


def _capture_cards(package: JsonObject) -> list[JsonValue]:
    return [
        {
            "capture_id": text(capture.get("capture_id")),
            "role": text(capture.get("role")),
            "viewport": text(capture.get("viewport")),
            "path_or_uri": text(capture.get("path_or_uri")),
            "mime_type": text(capture.get("mime_type")),
            "evidence_summary": text(capture.get("evidence_summary")),
            "redaction_status": text(capture.get("redaction_status")),
            "attachment": text(capture.get("attachment")),
            "capture_origin": text(capture.get("capture_origin")),
            "byte_size": capture.get("byte_size"),
            "sha256": text(capture.get("sha256")),
        }
        for capture in object_list(package.get("captures"))
    ]


def _attachment_summary(projection: JsonObject) -> JsonObject:
    return {
        "eligible_count": len(object_list(projection.get("items"))),
        "blocked_count": len(object_list(projection.get("blocked_items"))),
        "delivery_observed": bool(projection.get("delivery_observed")),
        "schema_version": text(projection.get("schema_version")),
    }


def _multimodal_summary(reviews: list[JsonObject]) -> JsonObject:
    observed = [review for review in reviews if text(review.get("status")) == "observed"]
    return {
        "review_count": len(reviews),
        "observed_count": len(observed),
        "reviews": [
            {
                "review_id": text(review.get("review_id")),
                "status": text(review.get("status")),
                "reviewer": text(review.get("reviewer")),
                "cost_tier": text(review.get("cost_tier")),
                "confidence": text(review.get("confidence")),
                "summary": text(review.get("summary")),
            }
            for review in reviews
        ],
    }


def _message_blocks(
    *,
    headline: str,
    route: JsonObject,
    criteria: list[JsonValue],
    attachment_summary: JsonObject,
    multimodal: JsonObject,
    claim_boundary: str,
) -> list[JsonValue]:
    blocks: list[JsonValue] = [
        {"type": "header", "text": headline},
        {"type": "section", "text": f"Route: {text(route.get('label'))}. Next action: {text(route.get('next_action'))}."},
        {"type": "section", "text": _route_detail_text(route)},
        {"type": "section", "text": _criteria_text(criteria)},
        {"type": "section", "text": _attachment_text(attachment_summary)},
        {"type": "section", "text": _multimodal_text(multimodal)},
    ]
    if claim_boundary:
        blocks.append({"type": "context", "text": f"Boundary: {claim_boundary}"})
    return blocks


def _criteria_text(criteria: list[JsonValue]) -> str:
    lines = ["Criteria:"]
    for item in criteria:
        criterion = object_value(item)
        label = text(criterion.get("label")) or text(criterion.get("criterion_id")) or "criterion"
        status = text(criterion.get("status")) or "not_observed"
        summary = text(criterion.get("summary")) or "No result summary recorded."
        lines.append(f"- {label}: {status} - {summary}")
    return "\n".join(lines)


def _attachment_text(summary: JsonObject) -> str:
    delivery = "observed" if summary.get("delivery_observed") is True else "not observed"
    return f"Attachments: {summary['eligible_count']} eligible, {summary['blocked_count']} blocked; delivery {delivery}"


def _multimodal_text(summary: JsonObject) -> str:
    return f"Multimodal review: {summary['observed_count']} observed of {summary['review_count']} recorded"


def _route_detail_text(route: JsonObject) -> str:
    details = [
        f"Reason: {text(route.get('reason'))}",
        f"Multimodal strategy: {text(route.get('multimodal_strategy')) or 'not specified'}",
        f"Message delivery: {text(route.get('message_delivery')) or 'not specified'}",
    ]
    safety_flags = _strings(route.get("safety_flags"))
    if safety_flags:
        details.append(f"Safety flags: {', '.join(safety_flags)}")
    suggested_actions = _strings(route.get("suggested_actions"))
    if suggested_actions:
        details.append(f"Suggested actions: {', '.join(suggested_actions)}")
    basis = object_list(route.get("routing_basis"))
    if basis:
        basis_ids = [text(item.get("id")) for item in basis[:4] if text(item.get("id"))]
        if basis_ids:
            details.append(f"Native rewrite basis: {', '.join(basis_ids)}")
    return "\n".join(details)


def _routing_basis_cards(routing: JsonObject) -> list[JsonValue]:
    cards: list[JsonValue] = []
    for item in object_list(routing.get("routing_basis")):
        cards.append(
            {
                "id": text(item.get("id")),
                "source_repos": _strings(item.get("source_repos")),
                "native_rule": text(item.get("native_rule")),
            }
        )
    return cards


def _does_not_prove(package: JsonObject) -> list[JsonValue]:
    return _unique(
        [
            *[text(item) for item in _json_list(package.get("does_not_prove"))],
            *WEB_VISUAL_QA_MESSAGE_CARD_DOES_NOT_PROVE,
        ]
    )


def _json_list(value: JsonValue | None) -> list[JsonValue]:
    return list(value) if isinstance(value, list) else []


def _strings(value: JsonValue | None) -> list[JsonValue]:
    return [str(item).strip() for item in _json_list(value) if str(item).strip()]


def _unique(values: list[str]) -> list[JsonValue]:
    seen: set[str] = set()
    output: list[JsonValue] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
