from __future__ import annotations

import json

from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call
from ..omh_roles import role_aliases, role_context_payload, role_names
from ..omh_identities import identity_context_payload, identity_definitions
from .. import runtime_paths

OMH_ROLE_SCHEMA = {
    "name": "omh_role",
    "description": (
        "List the common built-in/custom identity directory or read a qualified identity; legacy role reads work. "
        "Read OMH role context for Hermes subagent or wrapper prompts. "
        "Role context is prompt guidance only, not runtime delegation evidence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "read"],
                "description": "List identities and legacy roles or read one definition.",
            },
            "role": {
                "type": "string",
                "description": "Role name for action=read, such as planner, researcher, handoff-guide, or a legacy alias.",
            },
            "identity": {"type": "string", "description": "Qualified builtin:name or custom:name for action=read."},
            "observation": OBSERVATION_SCHEMA,
        },
        "required": ["action"],
    },
}


def omh_role_handler(args: dict, **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_role", args, kwargs)
    action = str(args.get("action", "list") or "list")
    home = runtime_paths.plugin_home(kwargs.get("omh_home"))
    if action == "list":
        definitions = identity_definitions(home)
        names = sorted(definitions)
        shown = names[:64]
        payload = {
            "schema_version": "omh_role_catalog/v1",
            "roles": role_names(),
            "aliases": role_aliases(),
            "identities": [{key: value for key, value in definitions[name].items() if key != "prompt"}
                           for name in shown],
            "omitted": len(names) - len(shown),
            "directory_note": "Bounded directory; read any qualified reference with action=read identity=REFERENCE.",
            "claim_boundary": "OMH role names are prompt guidance only; they are not observed runtime agents.",
        }
        return json.dumps(attach_public_observation(payload, observation), ensure_ascii=False, sort_keys=True)
    if action != "read":
        payload = {"error": f"unknown action: {action}"}
    elif args.get("identity") or ":" in str(args.get("role", "")):
        payload = identity_context_payload(str(args.get("identity") or args.get("role")), omh_home=home)
    else:
        payload = role_context_payload(str(args.get("role", "") or ""))
    return json.dumps(attach_public_observation(payload, observation), ensure_ascii=False, sort_keys=True)
