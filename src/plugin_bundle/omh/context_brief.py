from __future__ import annotations

import hashlib

from .awareness import (
    awareness_generic_tool_checkpoint_payload,
    awareness_primer_payload,
    awareness_route_hint,
    awareness_route_hint_context,
)

OMH_CONTEXT_BRIEF_SCHEMA_VERSION = "omh_context_brief/v1"


def build_context_brief(
    message: str = "",
    *,
    source: str = "generic",
    max_hints: int = 2,
    include_prompt_context: bool = False,
) -> dict[str, object]:
    """Build bounded Hermes-facing OMH operating context."""
    text = str(message or "")
    limit = bounded_context_hint_limit(max_hints, default=2)
    primer = awareness_primer_payload()
    route_hint = awareness_route_hint(text, max_hints=limit) if text.strip() else awareness_route_hint("", max_hints=0)
    payload: dict[str, object] = {
        "schema_version": OMH_CONTEXT_BRIEF_SCHEMA_VERSION,
        "source": source,
        "purpose": (
            "Give Hermes a compact OMH mental model before generic chat, image, file, search, or coding tools."
        ),
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


def bounded_context_hint_limit(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(parsed, 10))
