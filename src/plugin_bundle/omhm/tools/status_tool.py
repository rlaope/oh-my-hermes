from __future__ import annotations

import json

from ..runtime_reader import read_omhm_status

OMHM_STATUS_SCHEMA = {
    "name": "omhm_status",
    "description": (
        "Read OMHM metadata-only runtime status. Prepared handoffs are kept separate "
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
        },
    },
}


def omhm_status_handler(args: dict, **kwargs) -> str:
    payload = read_omhm_status(
        omh_home=str(args.get("omh_home", "") or "") or None,
        limit=int(args.get("limit") or 5),
    )
    return json.dumps(payload, sort_keys=True)
