from __future__ import annotations

import hashlib
import json
from typing import Any

from ..awareness import awareness_primer_payload, awareness_route_hint
from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call

OMH_RECOMMEND_SCHEMA = {
    "name": "omh_recommend",
    "description": (
        "Recommend OMH workflows for a natural-language Hermes request without shell catalog approval. "
        "The returned payload redacts the raw request and remains routing guidance, not execution evidence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Current user request to route. The plugin returns hash/length metadata instead of echoing it.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "default": 5,
                "description": "Maximum recommendations to return.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
        "required": ["message"],
    },
}

_FALLBACK_RECOMMENDATIONS = (
    {
        "skill": "oh-my-hermes",
        "description": "Use the OMH router when the request crosses workflow lanes or needs a safe first step.",
        "category": "router",
        "phase": "route",
        "hermes_role": "guide",
        "handoff_policy": "hermes_retained",
        "next_action": "clarify_or_route",
        "wrapper_guidance": "Show the nearest OMH workflow lane, one safe next action, and what is not evidence yet.",
    },
    {
        "skill": "deep-interview",
        "description": "Clarify ambiguous goals before planning or implementation.",
        "category": "clarification",
        "phase": "clarify",
        "hermes_role": "guide",
        "handoff_policy": "hermes_retained",
        "next_action": "ask_clarification",
        "wrapper_guidance": "Ask one focused question before choosing a workflow when the request is unclear.",
    },
    {
        "skill": "ralplan",
        "description": "Create a reviewed implementation or operations plan before handoff.",
        "category": "planning",
        "phase": "plan",
        "hermes_role": "planner",
        "handoff_policy": "hermes_retained",
        "next_action": "present_plan",
        "wrapper_guidance": "Prepare a plan with acceptance criteria and keep execution disabled until accepted.",
    },
)


def omh_recommend_handler(args: dict, **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_recommend", args, kwargs)
    message = str(args.get("message") or "").strip()
    limit = _bounded_limit(args.get("limit"), default=5)
    if not message:
        payload = {
            "schema_version": "omh_recommend_result/v1",
            "status": "error",
            "error": "omh_recommend.message is required",
            "recommendations": [],
            "claim_boundary": _claim_boundary(),
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)

    recommendations, source = _recommendations(message, limit)
    payload = {
        "schema_version": "omh_recommend_result/v1",
        "status": "recommended" if recommendations else "no_match",
        "source": source,
        "message": {
            "sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
            "length": len(message),
            "raw_prompt_stored": False,
            "raw_prompt_echoed": False,
        },
        "recommendations": recommendations[:limit],
        "tool_guidance": (
            "Use this tool when Hermes needs the nearest OMH workflow without asking the user to approve "
            "`omh recommend` or `omh list` shell commands."
        ),
        "claim_boundary": _claim_boundary(),
    }
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)


def _recommendations(message: str, limit: int) -> tuple[list[dict[str, Any]], str]:
    try:
        from omh.routing.recommend import recommend_skills
    except Exception:
        return _fallback_recommendations(message, limit), "standalone_plugin_bundle_fallback"
    try:
        return [_redacted_recommendation(item) for item in recommend_skills(message, limit=limit)], "package_recommend"
    except Exception:
        return _fallback_recommendations(message, limit), "standalone_plugin_bundle_fallback"


def _redacted_recommendation(item: dict[str, Any]) -> dict[str, Any]:
    skill = str(item.get("skill") or "")
    redacted = dict(item)
    if skill:
        redacted["suggested_prompt"] = f"Use {skill} for: <current user request>"
    redacted["raw_prompt_echoed"] = False
    return redacted


def _fallback_recommendations(message: str, limit: int) -> list[dict[str, Any]]:
    route_hint = awareness_route_hint(message, max_hints=limit)
    hints = route_hint.get("hints", [])
    if isinstance(hints, list) and hints:
        return [_recommendation_from_hint(hint, route_hint) for hint in hints if isinstance(hint, dict)]
    return [_static_fallback_recommendation(item) for item in _FALLBACK_RECOMMENDATIONS[:limit]]


def _recommendation_from_hint(hint: dict[str, Any], route_hint: dict[str, Any]) -> dict[str, Any]:
    workflow = str(hint.get("workflow") or "oh-my-hermes")
    context_card = hint.get("workflow_context_card") if isinstance(hint.get("workflow_context_card"), dict) else {}
    matched = [str(item) for item in hint.get("matched_cues", []) if str(item)]
    return {
        "skill": workflow,
        "description": str(hint.get("reason") or context_card.get("omh_pattern") or "OMH workflow route hint."),
        "category": str(hint.get("lane") or context_card.get("id") or "router"),
        "phase": "route",
        "hermes_role": _role_for_lane(str(hint.get("lane") or "")),
        "handoff_policy": "hermes_retained",
        "score": 8 if matched else 4,
        "confidence": "medium" if matched else "low",
        "matched": matched,
        "why": str(hint.get("reason") or "Matched OMH awareness route hint metadata."),
        "next_action": str(hint.get("next_action") or "show_workflow_guidance"),
        "evidence_boundary": str(route_hint.get("claim_boundary") or _claim_boundary()),
        "wrapper_guidance": str(
            context_card.get("first_response_shape")
            or "Name the OMH workflow, show one safe next action, and keep observed evidence separate."
        ),
        "suggested_prompt": f"Use {workflow} for: <current user request>",
        "raw_prompt_echoed": False,
    }


def _static_fallback_recommendation(item: dict[str, Any]) -> dict[str, Any]:
    skill = str(item["skill"])
    return {
        **item,
        "score": 0,
        "confidence": "low",
        "matched": [],
        "why": "No strong plugin route hint matched; start with general OMH routing guidance.",
        "evidence_boundary": _claim_boundary(),
        "suggested_prompt": f"Use {skill} for: <current user request>",
        "raw_prompt_echoed": False,
    }


def _role_for_lane(lane: str) -> str:
    return {
        "intent_to_plan": "planner",
        "research_and_ops": "researcher",
        "materials_and_visuals": "operator",
        "automation_and_status": "tracker",
        "coding_handoff": "handoff-guide",
    }.get(lane, "guide")


def _bounded_limit(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, 10))


def _claim_boundary() -> str:
    primer = awareness_primer_payload()
    return str(
        primer.get("evidence_boundary")
        or "OMH recommendations are routing guidance only, not workflow execution evidence."
    )
