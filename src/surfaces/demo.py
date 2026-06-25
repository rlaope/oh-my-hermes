from __future__ import annotations

import hashlib
from typing import Any

from ..coding_delegation import CODING_EXECUTOR_TARGETS
from ..executors import executor_label
from ..harness_quality import build_harness_progress
from ..hermes_planning import build_hermes_plan_payload
from ..ingress import CHAT_SOURCES
from ..routing.recommend import recommend_skills
from ..wrapper.contract import build_chat_interaction_payload, build_chat_status_interaction


ORCHESTRATION_DEMO_SCHEMA_VERSION = "orchestration_demo/v1"
DEFAULT_ORCHESTRATION_MESSAGE = "I want to safely add a feature to this repo"


def build_orchestration_demo(
    message: str = DEFAULT_ORCHESTRATION_MESSAGE,
    *,
    source: str = "discord",
    limit: int = 3,
    executor_target: str = "choose",
) -> dict[str, object]:
    task = message.strip()
    if not task:
        raise ValueError("demo orchestration requires a task description")
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported demo source: {source}")
    if limit < 1:
        raise ValueError("demo orchestration --limit must be at least 1")
    if executor_target not in CODING_EXECUTOR_TARGETS:
        raise ValueError(f"unsupported demo orchestration executor: {executor_target}")

    recommendations = recommend_skills(task, limit=limit)
    chat = build_chat_interaction_payload(task, source=source, limit=limit)
    plan = build_hermes_plan_payload(task, source=source, limit=limit)
    handoff = build_chat_interaction_payload(task, source=source, mode="delegate", limit=limit, executor_target=executor_target)
    status_payload = _prepared_status_from_handoff(handoff, source=source)
    status = build_chat_status_interaction(status_payload, source=source)

    return {
        "schema_version": ORCHESTRATION_DEMO_SCHEMA_VERSION,
        "scenario": "recommend_chat_plan_handoff_status",
        "source": source,
        "executor_target": executor_target,
        "message_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
        "message_length": len(task),
        "redaction_policy": "metadata_only",
        "summary": _demo_summary(executor_target),
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
    runtime_handoff = _nested(delegation_payload, "runtime_handoff")
    prompt_handoff = _nested(delegation_payload, "prompt_handoff")
    selected_handoff = executor_handoff or runtime_handoff or prompt_handoff
    selected_executor = str(
        selected_handoff.get("selected_executor_profile")
        or selected_handoff.get("executor_target")
        or delegation_payload.get("selected_executor_profile")
        or _nested(handoff, "executor_resolution").get("resolved_executor_target")
        or "choose"
    )
    choice_required = bool(_nested(delegation_payload, "executor_selection").get("choice_required", False))
    harness_quality = _nested(delegation_payload, "harness_quality")
    ladder = [str(step) for step in harness_quality.get("evidence_ladder", []) if isinstance(step, str)]
    progress = build_harness_progress(harness_quality, {ladder[0]: "complete"} if ladder else {})
    review_required = bool(delegation.get("review_required", False))
    review_status = "not_observed" if review_required else "not_required"
    next_action = _status_next_action_from_handoff(
        handoff,
        selected_handoff=bool(selected_handoff),
        choice_required=choice_required,
    )
    return {
        "schema_version": "delegated_coding_status/v1",
        "run_id": _demo_run_id(selected_executor),
        "source": source,
        "source_metadata": {},
        "prepared": {
            "available": bool(selected_handoff),
            "handoff_available": bool(selected_handoff),
            "choice_required": choice_required,
            "executor_target": selected_executor,
            "selected_executor_profile": selected_handoff.get("selected_executor_profile", selected_executor)
            if selected_handoff
            else "",
            "handoff_schema_version": selected_handoff.get("schema_version", "") if selected_handoff else "",
            "status": selected_handoff.get("status", "prepared_not_observed") if selected_handoff else "not_available",
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
        "next_action": next_action,
        "safe_summary": _safe_status_summary(
            selected_executor,
            selected_handoff=bool(selected_handoff),
            choice_required=choice_required,
        ),
        "overclaim_guard": [
            "Prepared coding delegation is not execution evidence.",
            "Hermes should not claim it implemented code from this demo artifact.",
            "Review, verification, CI, and merge status require separate observed evidence.",
        ],
    }


def _demo_summary(executor_target: str) -> str:
    if executor_target == "choose":
        return (
            "Deterministic local Hermes chat orchestration demo with routing, planning, executor choice, "
            "handoff, and status contracts."
        )
    return (
        "Deterministic local Hermes chat orchestration demo with routing, planning, selected executor/runtime "
        f"handoff for {executor_label(executor_target)}, and status contracts."
    )


def _demo_run_id(executor_target: str) -> str:
    normalized = executor_target.strip() or "choose"
    if normalized == "choose":
        return "demo-prepared-executor-choice"
    return f"demo-prepared-{normalized}-handoff"


def _status_next_action_from_handoff(
    handoff: dict[str, object],
    *,
    selected_handoff: bool,
    choice_required: bool,
) -> str:
    if choice_required:
        return "choose_executor"
    chat_next_action = str(handoff.get("next_action", ""))
    if chat_next_action == "send_to_executor":
        return "dispatch_to_executor"
    if chat_next_action in {"show_prompt_handoff", "show_runtime_handoff"}:
        return chat_next_action
    return "dispatch_to_executor" if selected_handoff else "route_coding_request"


def _safe_status_summary(executor_target: str, *, selected_handoff: bool, choice_required: bool) -> str:
    if choice_required:
        return "A coding handoff path is not selected yet; no executor/runtime dispatch is observed."
    if selected_handoff:
        label = executor_label(executor_target)
        return f"A {label} handoff is prepared, but wrapper dispatch or runtime start is not observed yet."
    return "No coding executor/runtime handoff is prepared or observed yet."


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
