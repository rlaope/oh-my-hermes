from __future__ import annotations

import json
from typing import Any

from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call
from ..runtime_reader import read_omh_hud

OMH_HUD_SCHEMA = {
    "name": "omh_hud",
    "description": (
        "Read the compact OMH metadata-only HUD payload for Hermes TUI/status surfaces. "
        "Token fields are shown only when supplied by the host metadata."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "omh_home": {
                "type": "string",
                "description": "Optional OMH_HOME override. Defaults to $OMH_HOME or ~/.omh.",
            },
            "hermes_home": {
                "type": "string",
                "description": "Optional HERMES_HOME override. Defaults to $HERMES_HOME or ~/.hermes.",
            },
            "preset": {
                "type": "string",
                "enum": ["minimal", "focused", "full"],
                "description": "HUD display density.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum recent runtime runs to summarize.",
            },
            "tokens_remaining": {
                "type": "number",
                "description": "Optional host-provided token count.",
            },
            "token_budget": {
                "type": "number",
                "description": "Optional host-provided token budget.",
            },
            "input_tokens": {
                "type": "number",
                "description": "Optional host-provided input token count.",
            },
            "output_tokens": {
                "type": "number",
                "description": "Optional host-provided output token count.",
            },
            "context_remaining_percent": {
                "type": "number",
                "description": "Optional host-provided context remaining percentage.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
    },
}


def omh_hud_handler(args: dict[str, Any], **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_hud", args, kwargs)
    token_metadata = {
        key: args.get(key)
        for key in (
            "tokens_remaining",
            "token_budget",
            "input_tokens",
            "output_tokens",
            "context_remaining_percent",
        )
        if args.get(key) is not None
    }
    payload = read_omh_hud(
        omh_home=str(args.get("omh_home", "") or "") or None,
        hermes_home=str(args.get("hermes_home", "") or "") or None,
        preset=str(args.get("preset", "focused") or "focused"),
        limit=args.get("limit") or 3,
        token_metadata=token_metadata,
    )
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
