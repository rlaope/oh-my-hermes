from __future__ import annotations

import json
from typing import Any

from ..delegation_routing import read_delegation_route, write_delegation_route
from ..hermes_delegation import HERMES_MIXTURE_CATEGORY_CHAINS
from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call

_EVIDENCE_BOUNDARY = (
    "Prepared route only: the delegation.* keys apply to the NEXT delegate_task "
    "dispatch (Hermes re-reads config.yaml per dispatch). Writing a route is not "
    "execution, dispatch, or completion evidence."
)

OMH_DELEGATE_ROUTE_SCHEMA = {
    "name": "omh_delegate_route",
    "description": (
        "Route the NEXT Hermes-native delegate_task dispatch onto a mixture model "
        "category (ultrabrain, deep, unspecified-high, unspecified-low, quick, writing, "
        "visual-engineering, artistry) by writing the delegation.model / "
        "delegation.reasoning_effort keys Hermes reads per dispatch. Sequence per lane: "
        "set the route, call delegate_task for that lane, then set the next lane's route "
        "or clear to restore parent inheritance. Children already running keep their model."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["set", "clear", "status"],
                "description": (
                    "set writes a route; clear removes the routable keys so children "
                    "inherit the parent again; status reads the current route."
                ),
            },
            "category": {
                "type": "string",
                "enum": sorted(HERMES_MIXTURE_CATEGORY_CHAINS),
                "description": (
                    "Mixture category to route to; resolves to the chain head "
                    "(e.g. ultrabrain -> gpt-5.6-sol xhigh). Required for set unless "
                    "an explicit model is given."
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "Explicit model id override; wins over the category's chain head. "
                    "Use for a fallback candidate when the head is unavailable."
                ),
            },
            "reasoning_effort": {
                "type": "string",
                "description": (
                    "Explicit reasoning effort override (e.g. low, medium, high, xhigh). "
                    "Defaults to the chain entry's declared effort; omitted keys inherit "
                    "the parent session's level."
                ),
            },
            "provider": {
                "type": "string",
                "description": (
                    "Optional delegation.provider override for models that live on a "
                    "different provider than the parent session. Requires that provider "
                    "to be configured in Hermes."
                ),
            },
            "hermes_home": {
                "type": "string",
                "description": "Optional HERMES_HOME override. Defaults to ~/.hermes.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
    },
}


def omh_delegate_route_handler(args: dict[str, Any], **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_delegate_route", args, kwargs)
    action = str(args.get("action", "") or "set").strip().lower()
    hermes_home = str(args.get("hermes_home", "") or "") or None

    if action == "status":
        payload: dict[str, Any] = {
            "status": "status",
            "route": read_delegation_route(hermes_home),
            "categories": {
                category: [
                    {"model": alias, "reasoning_effort": effort}
                    for alias, effort in chain
                ]
                for category, chain in HERMES_MIXTURE_CATEGORY_CHAINS.items()
            },
            "evidence_boundary": _EVIDENCE_BOUNDARY,
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)

    if action == "clear":
        result = write_delegation_route(hermes_home, clear=True)
        result["evidence_boundary"] = _EVIDENCE_BOUNDARY
        return json.dumps(attach_public_observation(result, observation), sort_keys=True)

    if action != "set":
        payload = {"status": "error", "error": f"unknown action {action!r}; use set, clear, or status"}
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)

    category = str(args.get("category", "") or "").strip()
    model = str(args.get("model", "") or "").strip()
    effort = str(args.get("reasoning_effort", "") or "").strip()
    provider = str(args.get("provider", "") or "").strip()
    if category and category not in HERMES_MIXTURE_CATEGORY_CHAINS:
        payload = {
            "status": "error",
            "error": (
                f"unknown category {category!r}; choose one of "
                + ", ".join(sorted(HERMES_MIXTURE_CATEGORY_CHAINS))
            ),
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    if not model:
        if not category:
            payload = {"status": "error", "error": "set needs a category or an explicit model"}
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        head_model, head_effort = HERMES_MIXTURE_CATEGORY_CHAINS[category][0]
        model = head_model
        if not effort:
            effort = head_effort
    result = write_delegation_route(
        hermes_home, model=model, reasoning_effort=effort, provider=provider
    )
    if result.get("status") == "routed":
        result["category"] = category
        chain = HERMES_MIXTURE_CATEGORY_CHAINS.get(category, ())
        result["fallback_candidates"] = [
            {"model": alias, "reasoning_effort": chain_effort}
            for alias, chain_effort in chain[1:]
        ]
    result["evidence_boundary"] = _EVIDENCE_BOUNDARY
    return json.dumps(attach_public_observation(result, observation), sort_keys=True)
