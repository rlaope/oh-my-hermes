from __future__ import annotations

import hashlib
import json
from typing import Any

from ..awareness import (
    awareness_generic_tool_checkpoint_payload,
    awareness_primer_payload,
    awareness_route_hint,
    awareness_route_hint_context,
)
from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call

OMH_CONTEXT_SCHEMA = {
    "name": "omh_context",
    "description": (
        "Return compact OMH operating context for Hermes before generic chat, image, file, search, or coding tools. "
        "The payload is metadata-only and does not store or echo the raw user request."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Optional current user request. The response returns hash/length metadata instead of echoing it.",
            },
            "source": {
                "type": "string",
                "default": "hermes-agent",
                "description": "Host or wrapper source label.",
            },
            "limit": {
                "type": "integer",
                "minimum": 0,
                "maximum": 10,
                "default": 2,
                "description": "Maximum route hints to include.",
            },
            "include_prompt_context": {
                "type": "boolean",
                "default": False,
                "description": "Include compact prompt-context text for hook-style injection.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
    },
}


def omh_context_handler(args: dict, **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_context", args, kwargs)
    message = str(args.get("message") or "")
    source = str(args.get("source") or "hermes-agent")
    limit = _bounded_limit(args.get("limit"), default=2)
    include_prompt_context = bool(args.get("include_prompt_context", False))
    payload, backend = _context_brief(
        message,
        source=source,
        max_hints=limit,
        include_prompt_context=include_prompt_context,
    )
    payload["plugin_tool"] = "omh_context"
    payload["source_backend"] = backend
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)


def _context_brief(
    message: str,
    *,
    source: str,
    max_hints: int,
    include_prompt_context: bool,
) -> tuple[dict[str, object], str]:
    try:
        from omh.context import build_context_brief
    except Exception:
        return _standalone_context_brief(
            message,
            source=source,
            max_hints=max_hints,
            include_prompt_context=include_prompt_context,
        ), "standalone_plugin_bundle_fallback"
    try:
        return build_context_brief(
            message,
            source=source,
            max_hints=max_hints,
            include_prompt_context=include_prompt_context,
        ), "package_context"
    except Exception:
        return _standalone_context_brief(
            message,
            source=source,
            max_hints=max_hints,
            include_prompt_context=include_prompt_context,
        ), "standalone_plugin_bundle_fallback"


def _standalone_context_brief(
    message: str,
    *,
    source: str,
    max_hints: int,
    include_prompt_context: bool,
) -> dict[str, object]:
    text = str(message or "")
    limit = _bounded_limit(max_hints, default=2)
    primer = awareness_primer_payload()
    route_hint = awareness_route_hint(text, max_hints=limit) if text.strip() else awareness_route_hint("", max_hints=0)
    payload: dict[str, object] = {
        "schema_version": "omh_context_brief/v1",
        "source": source,
        "purpose": "Give Hermes a compact OMH mental model before generic chat, image, file, search, or coding tools.",
        "message": {
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
            "length": len(text),
            "raw_prompt_stored": False,
            "raw_prompt_echoed": False,
        },
        "chat_rule": primer["chat_rule"],
        "first_turn_rule": primer["first_turn_rule"],
        "all_skill_context_rule": primer["all_skill_context_rule"],
        "lanes": primer["lanes"],
        "workflow_context_cards": primer["workflow_context_cards"],
        "workflow_cues": primer["workflow_cues"],
        "generic_tool_checkpoint": awareness_generic_tool_checkpoint_payload(),
        "route_hint": route_hint,
        "tool_hints": primer["tool_hints"],
        "fallback_rule": primer["fallback_rule"],
        "evidence_boundary": primer["evidence_boundary"],
        "normal_response_contract": {
            "schema_version": "omh_context_response_contract/v1",
            "when_user_asks_capabilities": "Summarize lanes and offer the workflow picker instead of requesting shell approval.",
            "when_request_matches_lane": "Name the OMH workflow, the reason, the next action, and what is not evidence yet.",
            "when_generic_tool_is_available": (
                "Do not skip OMH merely because a generic tool can render, search, edit files, or run code."
            ),
            "when_missing_connector_or_executor": (
                "Offer setup or selection fallback instead of claiming generation, delivery, dispatch, or execution."
            ),
        },
        "privacy": {
            "mode": "metadata_only",
            "raw_prompt_stored": False,
            "raw_prompt_echoed": False,
            "stored_fields": ["message hash", "message length", "matched cue labels", "workflow hint"],
        },
        "claim_boundary": (
            "OMH context is advisory routing and status context only. It is not workflow execution, image generation, "
            "file export, source retrieval, executor dispatch, implementation, verification, review, CI, merge, "
            "delivery, or proof that live Hermes selected the workflow."
        ),
    }
    if include_prompt_context:
        payload["prompt_context"] = awareness_route_hint_context(text, max_hints=limit) if text.strip() else ""
        payload["prompt_context_boundary"] = (
            "Prompt context is for Hermes routing guidance only; it is not workflow execution or observed evidence."
        )
    return payload


def _bounded_limit(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(parsed, 10))
