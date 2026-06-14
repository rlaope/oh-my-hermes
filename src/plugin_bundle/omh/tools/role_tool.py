from __future__ import annotations

import json

from ..omh_roles import role_context_payload, role_names

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
                "description": "Role name for action=read, such as planning-lead or coding-handoff.",
            },
        },
        "required": ["action"],
    },
}


def omh_role_handler(args: dict, **kwargs) -> str:
    action = str(args.get("action", "list") or "list")
    if action == "list":
        return json.dumps(
            {
                "schema_version": "omh_role_catalog/v1",
                "roles": role_names(),
                "claim_boundary": "OMH role names are prompt guidance only; they are not observed runtime agents.",
            },
            sort_keys=True,
        )
    if action != "read":
        return json.dumps({"error": f"unknown action: {action}"}, sort_keys=True)
    return json.dumps(role_context_payload(str(args.get("role", "") or "")), sort_keys=True)
