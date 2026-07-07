from __future__ import annotations

from .web_visual_qa_contracts import JsonObject, attachment_projection, auto_routing


def build_prepared_web_visual_qa_chat_state() -> JsonObject:
    captures: list[JsonObject] = []
    criteria = _default_criteria()
    criteria_results: list[JsonObject] = []
    multimodal_reviews: list[JsonObject] = []
    verdict = "not_observed"
    return {
        "artifact_schema": "web_visual_qa_prepared_preview/v1",
        "package_schema": "web_visual_qa_package/v1",
        "visual_qa_plan_schema": "visual_qa_plan/v1",
        "package_lifecycle_status": "prepared",
        "capture_model": "web_visual_qa_package.captures[]",
        "criteria_model": "web_visual_qa_package.criteria[]",
        "criteria_result_model": "web_visual_qa_package.criteria_results[]",
        "multimodal_review_model": "web_visual_qa_package.multimodal_reviews[]",
        "capture_count": len(captures),
        "criteria_count": len(criteria),
        "attachment_projection": attachment_projection(captures),
        "criteria_result_summary": _criteria_summary(criteria, criteria_results, verdict=verdict),
        "blocking_criteria_unresolved": [
            {
                "criterion_id": str(criterion.get("criterion_id", "")),
                "label": str(criterion.get("label", "")),
                "status": "not_observed",
            }
            for criterion in criteria
            if str(criterion.get("severity", "")) == "blocking"
        ],
        "auto_routing": auto_routing(
            risk_level="medium",
            estimated_cost_tier="none",
            captures=captures,
            criteria=criteria,
            criteria_results=criteria_results,
            multimodal_reviews=multimodal_reviews,
        ),
        "multimodal_review_policy": {
            "schema_version": "web_visual_qa_multimodal_review_policy/v1",
            "allowed_source": "host_observed_evidence",
            "cost_policy": "auto_route_by_risk_cost_and_existing_evidence",
            "omh_model_call_authorized": False,
            "does_not_authorize": ["model_call", "browser_launch", "platform_upload"],
        },
    }


def _default_criteria() -> list[JsonObject]:
    return [
        {
            "criterion_id": "viewport-captures",
            "label": "Relevant desktop and mobile captures are observed",
            "pass_rule": "Every required viewport has an observed capture before visual PASS.",
            "severity": "blocking",
        },
        {
            "criterion_id": "criteria-results",
            "label": "Visual quality criteria are checked against capture evidence",
            "pass_rule": "Blocking criteria results reference observed captures and pass before PASS.",
            "severity": "blocking",
        },
        {
            "criterion_id": "message-attachment-boundary",
            "label": "Message attachments are projected separately from delivery",
            "pass_rule": "Attachment projection can be prepared, but upload and delivery require observed platform evidence.",
            "severity": "blocking",
        },
    ]


def _criteria_summary(
    criteria: list[JsonObject],
    criteria_results: list[JsonObject],
    *,
    verdict: str,
) -> JsonObject:
    result_by_id = {str(item.get("criterion_id", "")): item for item in criteria_results}
    status_counts = {"pass": 0, "hold": 0, "fail": 0, "not_observed": 0}
    unresolved: list[JsonObject] = []
    for criterion in criteria:
        criterion_id = str(criterion.get("criterion_id", ""))
        result = result_by_id.get(criterion_id)
        status = str(result.get("status", "not_observed")) if result else "not_observed"
        if status not in status_counts:
            status = "not_observed"
        status_counts[status] += 1
        if str(criterion.get("severity", "")) == "blocking" and status != "pass":
            evidence_refs = result.get("evidence_refs", []) if result else []
            unresolved.append(
                {
                    "criterion_id": criterion_id,
                    "label": str(criterion.get("label", "")),
                    "status": status,
                    "evidence_refs": [str(ref) for ref in evidence_refs] if isinstance(evidence_refs, list) else [],
                }
            )
    return {
        "schema_version": "web_visual_qa_criteria_result_summary/v1",
        "criteria_count": len(criteria),
        "result_count": len(criteria_results),
        "pass_count": status_counts["pass"],
        "hold_count": status_counts["hold"],
        "fail_count": status_counts["fail"],
        "not_observed_count": status_counts["not_observed"],
        "blocking_unresolved_count": len(unresolved),
        "blocking_unresolved": unresolved,
        "verdict": verdict,
    }
