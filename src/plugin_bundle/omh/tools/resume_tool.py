from __future__ import annotations

from .. import runtime_paths

import json
from typing import Any

from ..host_observation import (
    attach_public_observation,
    host_session_id,
    observe_plugin_tool_call,
)
from ..work_resume import DEFAULT_LIMIT, MAX_LIMIT, WORK_RESUME_CLAIM_BOUNDARY, WORK_RESUME_SCHEMA, read_work_resume

OMH_RESUME_SCHEMA = {
    "name": "omh_resume",
    "description": (
        "Read this person's work in other sessions. These are their other Hermes sessions of this profile "
        "(TUI, Desktop, CLI, or the same chat-platform user): recent OMH plans with item states "
        "and completion checkpoints. Call it when they ask to continue or pick up earlier work, "
        "and relay `text`. Done items are that session's declarations, not observed results."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_LIMIT,
                "description": f"Most recent sessions to include (default {DEFAULT_LIMIT}).",
            },
        },
    },
}


def omh_resume_handler(args: dict[str, Any], **kwargs: Any) -> str:
    # The session comes from the host dispatch, never from `args`: the model
    # must not be able to name another person's session to read its work.
    if error := runtime_paths.tool_home_error(args):
        return json.dumps(error, sort_keys=True)
    observation = observe_plugin_tool_call("omh_resume", args, kwargs)
    limit = args.get("limit")
    if not isinstance(limit, int) or isinstance(limit, bool):
        limit = DEFAULT_LIMIT
    try:
        omh_home, hermes_home = runtime_paths.resolve_homes()
    except runtime_paths.RuntimeBindingError:
        payload = {
            "schema_version": WORK_RESUME_SCHEMA,
            "claim_boundary": WORK_RESUME_CLAIM_BOUNDARY,
            "status": "store_unavailable",
            "work": [],
            "text": "This profile's OMH home is not bound, so no earlier work is shown.",
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    payload = read_work_resume(omh_home, hermes_home, host_session_id(kwargs), limit=limit)
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
