from __future__ import annotations

import json

from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call
from ..runtime_reader import read_omh_status

OMH_STATUS_SCHEMA = {
    "name": "omh_status",
    "description": (
        "Read OMH metadata-only runtime status. Prepared handoffs are kept separate "
        "from observed execution, review, CI, and merge evidence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "omh_home": {
                "type": "string",
                "description": "Optional OMH_HOME override. Defaults to $OMH_HOME or ~/.omh.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum recent runtime runs to summarize.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
    },
}


def omh_status_handler(args: dict, **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_status", args, kwargs)
    payload = read_omh_status(
        omh_home=str(args.get("omh_home", "") or "") or None,
        limit=int(args.get("limit") or 5),
    )
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
