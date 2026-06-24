from __future__ import annotations

import hashlib
from typing import Any

from .harness_quality import build_harness_progress
from .hermes_planning import build_hermes_plan_payload
from .ingress import CHAT_SOURCES
from .routing.recommend import recommend_skills
from .wrapper.contract import build_chat_interaction_payload, build_chat_status_interaction


ORCHESTRATION_DEMO_SCHEMA_VERSION = "orchestration_demo/v1"
DEFAULT_ORCHESTRATION_MESSAGE = "I want to safely add a feature to this repo"


def build_orchestration_demo(
    message: str = DEFAULT_ORCHESTRATION_MESSAGE,
    *,
    source: str = "discord",
    limit: int = 3,
) -> dict[str, object]:
    task = message.strip()
    if not task:
        raise ValueError("demo orchestration requires a task description")
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported demo source: {source}")
    if limit < 1:
        raise ValueError("demo orchestration --limit must be at least 1")

    recommendations = recommend_skills(task, limit=limit)
    chat = build_chat_interaction_payload(task, source=source, limit=limit)
    plan = build_hermes_plan_payload(task, source=source, limit=limit)
    handoff = build_chat_interaction_payload(task, source=source, mode="delegate", limit=limit, executor_target="codex")
    status_payload = _prepared_status_from_handoff(handoff, source=source)
    status = build_chat_status_interaction(status_payload, source=source)

    return {
        "schema_version": ORCHESTRATION_DEMO_SCHEMA_VERSION,
        "scenario": "recommend_chat_plan_handoff_status",
        "source": source,
        "message_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
        "message_length": len(task),
        "redaction_policy": "metadata_only",
        "summary": "Deterministic local Hermes chat orchestration demo with routing, planning, handoff, and status contracts.",
        "steps": [
            {
                "id": "recommend",
                "title": "Recommend workflow",
                "next_action": _first_string(recommendations, "next_action"),
                "evidence_boundary": _first_string(recommendations, "evidence_boundary"),
                "payload": {"recommendations": [_public_recommendation(item) for item in recommendations]},
            },
            {
                "id": "chat",
                "title": "Render chat response",
                "next_action": chat.get("next_action", ""),
                "evidence_boundary": _claim_boundary(chat),
                "payload": {
                    "route": chat.get("route", {}),
                    "chat_response": chat.get("chat_response", {}),
                },
            },
            {
                "id": "plan",
                "title": "Draft Hermes plan",
                "next_action": _nested(plan, "wrapper_contract").get("next_action", ""),
                "evidence_boundary": "A draft Hermes plan is not accepted plan, execution, review, CI, or merge evidence.",
                "payload": _public_plan_payload(plan),
            },
            {
                "id": "handoff",
                "title": "Prepare selected executor/runtime handoff",
                "next_action": handoff.get("next_action", ""),
                "evidence_boundary": _claim_boundary(handoff),
                "payload": {
                    "delegation": _nested(_nested(handoff, "delegation"), "delegation"),
                    "executor_handoff": _nested(_nested(handoff, "delegation"), "executor_handoff"),
                    "chat_response": handoff.get("chat_response", {}),
                },
            },
            {
                "id": "status_card",
                "title": "Show wrapper status card",
                "next_action": status.get("next_action", ""),
                "evidence_boundary": _claim_boundary(status),
                "payload": {
                    "status_card": status.get("status_card", {}),
                    "chat_response": status.get("chat_response", {}),
                    "status": status_payload,
                },
            },
        ],
        "claim_boundary": [
            "Recommendation is not routing, planning, or execution evidence.",
            "Draft plan is not accepted plan or implementation evidence.",
            "Prepared executor/runtime handoff is not executor/runtime dispatch, runtime start, worker result, review, CI, merge-readiness, or merge evidence.",
        ],
        "not_observed": [
            "executor_dispatch",
            "executor_result",
            "verification",
            "review",
            "ci",
            "merge_readiness",
            "merge",
        ],
    }


def _prepared_status_from_handoff(handoff: dict[str, object], *, source: str) -> dict[str, object]:
    delegation_payload = _nested(handoff, "delegation")
    delegation = _nested(delegation_payload, "delegation")
    executor_handoff = _nested(delegation_payload, "executor_handoff")
    harness_quality = _nested(delegation_payload, "harness_quality")
    ladder = [str(step) for step in harness_quality.get("evidence_ladder", []) if isinstance(step, str)]
    progress = build_harness_progress(harness_quality, {ladder[0]: "complete"} if ladder else {})
    review_required = bool(delegation.get("review_required", False))
    review_status = "not_observed" if review_required else "not_required"
    return {
        "schema_version": "delegated_coding_status/v1",
        "run_id": "demo-prepared-codex-handoff",
        "source": source,
        "source_metadata": {},
        "prepared": {
            "available": bool(executor_handoff),
            "handoff_available": bool(executor_handoff),
            "executor_target": executor_handoff.get("executor_target", "codex") if executor_handoff else "codex",
            "handoff_schema_version": executor_handoff.get("schema_version", "") if executor_handoff else "",
            "status": executor_handoff.get("status", "prepared_not_observed") if executor_handoff else "not_available",
            "action": delegation.get("action", "fallback"),
            "workflow": delegation.get("recommended_workflow", "oh-my-hermes"),
            "harness": delegation.get("recommended_harness", "coding-handling"),
        },
        "execution": {"observed": False, "status": "not_observed", "participants": [], "evidence_refs": []},
        "verification": {"observed": False, "expected": delegation.get("verification", [])},
        "review": {
            "required": review_required,
            "observed": False,
            "workflow": delegation.get("review_workflow"),
            "evidence_refs": [],
            "satisfied": not review_required,
        },
        "ci": {"required": False, "observed": True, "status": "not_required", "checks": [], "evidence_refs": [], "satisfied": True},
        "merge_readiness": {"required": False, "observed": True, "status": "not_required", "evidence_refs": []},
        "merge": {"required": False, "observed": True, "status": "not_required", "merged": False, "evidence_refs": []},
        "wrapper": {
            "prompt_dispatched": False,
            "hermes_response_observed": True,
            "verification_observed": False,
            "completion_status": "unknown",
            "unobserved_gaps": [],
        },
        "harness_quality": harness_quality,
        "harness_progress": progress,
        "integrity": {"ok": True, "warnings": []},
        "next_action": "dispatch_to_executor" if executor_handoff else "route_coding_request",
        "safe_summary": "A selected executor/runtime handoff is prepared, but wrapper dispatch is not observed yet.",
        "overclaim_guard": [
            "Prepared coding delegation is not execution evidence.",
            "Hermes should not claim it implemented code from this demo artifact.",
            "Review, verification, CI, and merge status require separate observed evidence.",
        ],
    }


def _public_recommendation(item: dict[str, object]) -> dict[str, object]:
    return {
        "skill": item.get("skill", ""),
        "score": item.get("score", 0),
        "confidence": item.get("confidence", "low"),
        "why": item.get("why", ""),
        "next_action": item.get("next_action", ""),
        "evidence_boundary": item.get("evidence_boundary", ""),
        "wrapper_guidance": item.get("wrapper_guidance", ""),
        "matched": item.get("matched", []),
    }


def _public_plan_payload(plan: dict[str, object]) -> dict[str, object]:
    public = dict(plan)
    plan_body = dict(_nested(public, "plan"))
    if plan_body.get("task_statement"):
        plan_body["task_statement"] = "{message}"
    public["plan"] = plan_body
    return public


def _claim_boundary(payload: dict[str, object]) -> str:
    response = _nested(payload, "chat_response")
    return str(response.get("claim_boundary", "Only observed evidence can support completion claims."))


def _first_string(items: list[dict[str, object]], key: str) -> str:
    if not items:
        return ""
    return str(items[0].get(key, ""))


def _nested(payload: dict[str, object], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}
