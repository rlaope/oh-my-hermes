from __future__ import annotations

import json
from typing import Any

from ..delegation_routing import read_delegation_route, write_delegation_route
from ..hermes_delegation import (
    HERMES_MIXTURE_CATEGORY_CHAINS,
    chain_alias_for,
    load_mixture_chain_overrides,
    load_model_provider_routes,
    mixture_chain_overrides_path,
    model_provider_routes_path,
    resolve_provider_model,
)
from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call

_EVIDENCE_BOUNDARY = (
    "Prepared route only: the delegation.* keys apply to the NEXT delegate_task "
    "dispatch (Hermes re-reads config.yaml per dispatch). Writing a route is not "
    "execution, dispatch, or completion evidence."
)

def _chain_entry(
    alias: str,
    effort: str,
    routes: dict[str, tuple[str, str]],
) -> dict[str, str]:
    """Render one chain position.

    The public shape always carries alias, provider, executable model, and
    effort; unresolved aliases report an empty provider explicitly.
    """
    entry = {
        "alias": alias,
        "provider": "",
        "model": alias,
        "reasoning_effort": effort,
    }
    wire_model, provider = resolve_provider_model(alias, routes=routes)
    if provider:
        entry["provider"] = provider
        entry["model"] = wire_model
    return entry


OMH_DELEGATE_ROUTE_SCHEMA = {
    "name": "omh_delegate_route",
    "description": (
        "Route the NEXT Hermes-native delegate_task dispatch onto a mixture model "
        "category (ultrabrain, deep, architect, unspecified-high, unspecified-low, quick, "
        "writing, visual-engineering, artistry) by writing the delegation.model / "
        "delegation.reasoning_effort keys Hermes reads per dispatch. Sequence per lane: "
        "set the route, call delegate_task for that lane, then set the next lane's route "
        "or clear to restore parent inheritance. Children already running keep their model. "
        "Hermes has NO provider-side fallback: a child whose model the billing account "
        "cannot serve dies on an HTTP 400 yet its delegation still reports completed with "
        "the error text as the result — a completed child with no recorded model usage "
        "means exactly this. When that happens call action=fallback with the category "
        "returned by set to advance the route and re-dispatch; shared routes fail "
        "closed without that origin. An exhausted chain "
        "clears the route so the next dispatch inherits the parent's working model."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["set", "clear", "status", "fallback"],
                "description": (
                    "set writes a route; clear removes the routable keys so children "
                    "inherit the parent again; status reads the current route; fallback "
                    "advances the current route to the next candidate in its category "
                    "chain (clearing to parent inheritance once the chain is exhausted). "
                    "Reuse the category returned by set; ambiguous origins fail closed."
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
                    "Use for a fallback candidate when the head is unavailable, or to pin "
                    "a model the user named for the run (e.g. 'use fable'): keep the "
                    "fitting category for the lane label and pass the user's model (plus "
                    "reasoning_effort) here on every lane of that run."
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
                    "Hermes provider override. Supply it together with model so the "
                    "provider/wire identity remains atomic."
                ),
            },
            "hermes_home": {
                "type": "string",
                "description": "Optional HERMES_HOME override. Defaults to ~/.hermes.",
            },
            "omh_home": {
                "type": "string",
                "description": (
                    "Optional OMH home override for model-chains.json and "
                    "model-providers.json. Defaults to ~/.omh."
                ),
            },
            "observation": OBSERVATION_SCHEMA,
        },
    },
}


def omh_delegate_route_handler(args: dict[str, Any], **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_delegate_route", args, kwargs)
    action = str(args.get("action", "") or "set").strip().lower()
    hermes_home = str(args.get("hermes_home", "") or "") or None
    omh_home = str(args.get("omh_home", "") or "") or None
    # Every chain read below honors the user's routing/model-chains.json
    # overrides; the category vocabulary itself stays the shipped closed set.
    overrides, override_status = load_mixture_chain_overrides(omh_home)
    chains = {
        name: overrides.get(name, chain)
        for name, chain in HERMES_MIXTURE_CATEGORY_CHAINS.items()
    }
    # Chains name models the way a person says them. A host that reaches
    # models through a provider needs a provider id and that provider's own
    # (often namespaced) model string; routing/model-providers.json supplies
    # that mapping. With no document every alias dispatches unchanged.
    provider_routes, provider_route_status = load_model_provider_routes(omh_home)

    if action == "status":
        route = read_delegation_route(hermes_home)
        if route.get("model"):
            route.setdefault("provider", "")
            route["alias"] = chain_alias_for(
                str(route["model"]),
                str(route["provider"]),
                provider_routes,
            )
        payload: dict[str, Any] = {
            "status": "status",
            "route": route,
            "categories": {
                category: [
                    _chain_entry(alias, effort, provider_routes)
                    for alias, effort in chain
                ]
                for category, chain in chains.items()
            },
            "chain_overrides": override_status,
            "chain_overrides_path": str(mixture_chain_overrides_path(omh_home)),
            "provider_routes": provider_route_status,
            "provider_routes_path": str(model_provider_routes_path(omh_home)),
            "evidence_boundary": _EVIDENCE_BOUNDARY,
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)

    if action == "clear":
        result = write_delegation_route(hermes_home, clear=True)
        result["evidence_boundary"] = _EVIDENCE_BOUNDARY
        return json.dumps(attach_public_observation(result, observation), sort_keys=True)

    if action == "fallback":
        if override_status.startswith("invalid:"):
            payload = {"status": "error", "error": override_status}
            return json.dumps(
                attach_public_observation(payload, observation),
                sort_keys=True,
            )
        if provider_route_status.startswith("invalid:"):
            payload = {"status": "error", "error": provider_route_status}
            return json.dumps(
                attach_public_observation(payload, observation),
                sort_keys=True,
            )
        route = read_delegation_route(hermes_home)
        current_model = str(route.get("model", ""))
        current_provider = str(route.get("provider", ""))
        # The live route holds whatever was dispatched, which is the provider's
        # wire model when a route applied. Chain positions are keyed by alias,
        # so translate back before any chain lookup below -- otherwise a routed
        # model reads as absent from the very chain it came from.
        current_alias = chain_alias_for(
            current_model,
            current_provider,
            provider_routes,
        )
        if not current_model:
            payload = {
                "status": "error",
                "error": "no active route to fall back from; use set with a category first",
            }
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        category = str(args.get("category", "") or "").strip()
        if category and category not in chains:
            payload = {
                "status": "error",
                "error": (
                    f"unknown category {category!r}; choose one of "
                    + ", ".join(sorted(chains))
                ),
            }
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        if not current_provider and "/" in current_model:
            payload = {
                "status": "error",
                "error": f"current route {current_model!r} requires an explicit provider",
            }
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        matches = [
            (name, index)
            for name, chain in chains.items()
            for index, (alias, _) in enumerate(chain)
            if alias == current_alias and (not category or name == category)
        ]
        if not matches:
            payload = {
                "status": "error",
                "error": (
                    f"current route model {current_model!r} does not match "
                    + (
                        f"category {category!r}"
                        if category
                        else "any mixture chain; pass category explicitly"
                    )
                ),
            }
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        if len(matches) > 1:
            origins = ", ".join(sorted({name for name, _ in matches}))
            payload = {
                "status": "error",
                "error": (
                    f"current route model {current_model!r} has ambiguous origins "
                    f"across {origins}; pass category explicitly"
                ),
            }
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        category, index = matches[0]
        chain = chains[category]
        if index + 1 >= len(chain):
            # Chain exhausted: restore inheritance so the next dispatch runs on
            # the parent's known-working model instead of one more rejection.
            result = write_delegation_route(
                hermes_home,
                clear=True,
                expected_previous=route,
            )
            if result.get("status") == "cleared":
                result["status"] = "exhausted_to_inherit"
            result["category"] = category
            result["from"] = current_model
            result["evidence_boundary"] = _EVIDENCE_BOUNDARY
            return json.dumps(attach_public_observation(result, observation), sort_keys=True)
        next_model, next_effort = chain[index + 1]
        wire_model, next_provider = resolve_provider_model(
            next_model, routes=provider_routes
        )
        if "/" in wire_model and not next_provider:
            payload = {
                "status": "error",
                "error": (
                    f"next route {next_model!r} has no provider-aware wire model; "
                    "fallback refused without mutation"
                ),
            }
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        result = write_delegation_route(
            hermes_home,
            model=wire_model,
            reasoning_effort=next_effort,
            provider=next_provider,
            expected_previous=route,
        )
        if result.get("status") == "routed":
            result["status"] = "fell_back"
            result["applied"]["alias"] = next_model
            result["category"] = category
            result["from"] = current_model
            result["fallback_candidates"] = [
                _chain_entry(alias, chain_effort, provider_routes)
                for alias, chain_effort in chain[index + 2 :]
            ]
        result["evidence_boundary"] = _EVIDENCE_BOUNDARY
        return json.dumps(attach_public_observation(result, observation), sort_keys=True)

    if action != "set":
        payload = {
            "status": "error",
            "error": f"unknown action {action!r}; use set, clear, status, or fallback",
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)

    if override_status.startswith("invalid:"):
        payload = {"status": "error", "error": override_status}
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    if provider_route_status.startswith("invalid:"):
        payload = {"status": "error", "error": provider_route_status}
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    category = str(args.get("category", "") or "").strip()
    model = str(args.get("model", "") or "").strip()
    effort = str(args.get("reasoning_effort", "") or "").strip()
    provider = str(args.get("provider", "") or "").strip()
    if category and category not in chains:
        payload = {
            "status": "error",
            "error": (
                f"unknown category {category!r}; choose one of "
                + ", ".join(sorted(chains))
            ),
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    if provider and not model:
        payload = {
            "status": "error",
            "error": "provider and model overrides must appear together",
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    if not model and not category:
        payload = {"status": "error", "error": "set needs a category or an explicit model"}
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    alias = model
    if category and not model:
        alias, head_effort = chains[category][0]
        if not effort:
            effort = head_effort
    if provider:
        wire_model = model
    else:
        wire_model, provider = resolve_provider_model(alias, routes=provider_routes)
    if "/" in wire_model and not provider:
        payload = {
            "status": "error",
            "error": "a wire-shaped model requires an explicit provider",
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    result = write_delegation_route(
        hermes_home,
        model=wire_model,
        reasoning_effort=effort,
        provider=provider,
    )
    if result.get("status") == "routed":
        result["applied"]["alias"] = alias
        result["category"] = category
        chain = chains.get(category, ())
        result["fallback_candidates"] = [
            _chain_entry(alias, chain_effort, provider_routes)
            for alias, chain_effort in chain[1:]
        ]
    result["evidence_boundary"] = _EVIDENCE_BOUNDARY
    return json.dumps(attach_public_observation(result, observation), sort_keys=True)
