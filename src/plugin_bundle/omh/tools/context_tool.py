from __future__ import annotations

import hashlib
import json

from ..context_brief import bounded_context_hint_limit, build_context_brief as build_plugin_context_brief
from ..degradation import safe_error_type as _safe_error_type
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
    except (ImportError, ModuleNotFoundError):
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
    except Exception as exc:
        # The package imported successfully but the delegated call raised. This is a
        # package runtime failure, not a genuine missing-package fallback, so it must
        # not be mislabeled as `standalone_plugin_bundle_fallback`.
        return _package_context_error(message, source=source, error_type=type(exc).__name__), "package_context_error"


def _package_context_error(message: str, *, source: str, error_type: str) -> dict[str, object]:
    text = str(message or "")
    return {
        "schema_version": "omh_context_brief_error/v1",
        "status": "error",
        "error": "package_backend_error",
        "error_type": _safe_error_type(error_type),
        "source": source,
        "message": {
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
            "length": len(text),
            "raw_prompt_stored": False,
            "raw_prompt_echoed": False,
        },
        "degraded": True,
        "claim_boundary": (
            "The installed OMH package raised while building this context brief. This response carries no "
            "lanes, route hints, or capability context; it is neither a normal package-backed brief nor a "
            "genuine missing-package standalone fallback."
        ),
    }
