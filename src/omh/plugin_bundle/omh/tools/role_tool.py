from __future__ import annotations

import json

from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call
from ..omh_roles import role_aliases, role_context_payload, role_names

OMH_ROLE_SCHEMA = {
    "name": "omh_role",
    "description": (
        "Read OMH role context for Hermes subagent or wrapper prompts. "
        "Role context is prompt guidance only, not runtime delegation evidence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "read"],
                "description": "List available roles or read one role context.",
            },
            "role": {
                "type": "string",
                "description": "Role name for action=read, such as planner, researcher, handoff-guide, or a legacy alias.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
        "required": ["action"],
    },
}


def omh_role_handler(args: dict, **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_role", args, kwargs)
    action = str(args.get("action", "list") or "list")
    if action == "list":
        payload = {
            "schema_version": "omh_role_catalog/v1",
            "roles": role_names(),
            "aliases": role_aliases(),
            "claim_boundary": "OMH role names are prompt guidance only; they are not observed runtime agents.",
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    if action != "read":
        payload = {"error": f"unknown action: {action}"}
    else:
        payload = role_context_payload(str(args.get("role", "") or ""))
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
