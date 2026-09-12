from __future__ import annotations

from .. import runtime_paths

import json
from collections.abc import Callable

from ..group_activity_status import group_activity_status
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
                "description": "Standalone operator override only. Native Hermes calls reject this field; omit it to use the active profile.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum recent runtime runs to summarize.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
    },
}


def omh_status_handler(args: dict, *, group_activity_enabled: bool = False,
                       group_activity_observer: Callable[[], dict[str, str | int]] | None = None, **kwargs) -> str:
    if error := runtime_paths.tool_home_error(args):
        return json.dumps(error, sort_keys=True)
    observation = observe_plugin_tool_call("omh_status", args, kwargs)
    payload = read_omh_status(
        omh_home=runtime_paths.plugin_home(args.get("omh_home")),
        limit=int(args.get("limit") or 5),
    )
    payload["group_chat_activity"] = (group_activity_observer() if group_activity_observer is not None
                                      else group_activity_status(group_activity_enabled))
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
