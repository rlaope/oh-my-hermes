from __future__ import annotations

import json
from typing import Any

from ..context_brief import bounded_context_hint_limit, build_context_brief as build_plugin_context_brief
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
    limit = bounded_context_hint_limit(args.get("limit"), default=2)
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
        from omh.context import build_context_brief as build_package_context_brief
    except Exception:
        return build_plugin_context_brief(
            message,
            source=source,
            max_hints=max_hints,
            include_prompt_context=include_prompt_context,
        ), "standalone_plugin_bundle_fallback"
    try:
        return build_package_context_brief(
            message,
            source=source,
            max_hints=max_hints,
            include_prompt_context=include_prompt_context,
        ), "package_context"
    except Exception:
        return build_plugin_context_brief(
            message,
            source=source,
            max_hints=max_hints,
            include_prompt_context=include_prompt_context,
        ), "standalone_plugin_bundle_fallback"
