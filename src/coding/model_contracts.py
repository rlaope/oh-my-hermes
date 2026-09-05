"""Exact-model contracts and bounded declared inheritance.

A contract is prepared metadata — the vendor's published effort vocabulary,
limits, tool-calling surface, pricing, and runtime mechanisms for one exact
model id, each with the page it was read from. It is consulted by the route
resolver (to keep a documented-unsupported effort from reaching a provider
silently) and printed by `omh coding model-contract`. It never proves that a
provider serves the model to this account, that a runtime implements any of
the mechanisms named here, or that a route ran.

Contracts are keyed by exact model id after the provider prefix is stripped.
Provider catalogs may expose a bounded set of declared mode/service-tier aliases
for one contract. Those aliases resolve only through the explicit projection
table below; arbitrary suffix stripping is forbidden. A model without an exact
or declared contract gets `None`, never a guess.
"""

from __future__ import annotations

from typing import Final, Mapping

MODEL_CONTRACT_SCHEMA_VERSION: Final[str] = "model_contract/v1"
MODEL_CONTRACT_PROJECTION_SCHEMA_VERSION: Final[str] = "model_contract_projection/v1"

MODEL_CONTRACT_CLAIM_BOUNDARY: Final[str] = (
    "A model contract is the vendor's documented interface for one model id, read from the cited "
    "pages on the cited date. It is not evidence that any provider serves the model to this "
    "account, that a runtime implements the named mechanisms, or that a route ran; observed "
    "behavior comes only from the runtime that actually ran the model."
)

MODEL_CONTRACT_PROJECTION_CLAIM_BOUNDARY: Final[str] = (
    "A model contract projection records how OMH interprets one explicitly declared catalog id. "
    "It is not evidence that a provider advertises or serves the requested id, that an account is "
    "entitled to it, or that execution occurred. The host/runtime owns any wire translation."
)

# Compatibility outcomes a contract can hand the route resolver.
EFFORT_FLOOR_KIND: Final[str] = "floor_raised"

_GPT_6_ASTRA: Final[dict[str, object]] = {
    "schema_version": MODEL_CONTRACT_SCHEMA_VERSION,
    "model_id": "gpt-6-astra",
    "reasoning_mode": "standard",
    "service_tier": "standard",
    "family": "gpt",
    "generation": "gpt-6",
    "released": "2026-09-03",
    "rollout": "staged; a released id is not account-level readiness evidence",
    "knowledge_cutoff": "2026-04-30",
    "context_window_tokens": 1_050_000,
    "max_input_tokens": 922_000,
    "max_output_tokens": 128_000,
    # The documented ladder. `none` returns HTTP 400 and the migration guide
    # sends `none`/`minimal` callers to `low`, so `low` is the documented
    # floor OMH raises a lower request to — explicitly, in the route record.
    "reasoning_efforts": ("low", "medium", "high", "xhigh", "max"),
    "effort_floor": "low",
    "effort_default": "",
    "unsupported_efforts": {
        "off": "`none` returns HTTP 400; migrate to `low`",
        "minimal": "not in the documented ladder; migrate to `low`",
    },
    "tool_calling": {
        "api": "responses",
        "note": "tool calling requires the Responses API; Chat Completions serves text only",
    },
    "unsupported_parameters": ("temperature", "top_p", "top_logprobs"),
    "dynamic_effort": {
        "mechanism": "configuration_update",
        "scope": "standard single-agent mode only",
        "constraints": (
            "not combinable with automatic compaction or automatic truncation",
            "two adjacent configuration_update items are rejected",
            "the original prompt prefix is preserved for prompt caching",
        ),
        # No executor profile OMH prepares for has been observed to expose
        # this mechanism; the guidance that depends on it is emitted only for
        # a profile named here, so today it is emitted nowhere.
        "compatible_profiles": (),
        "status": "documented_not_observed",
    },
    "runtime_mechanisms": {
        "async_tool_calling": "documented_not_observed",
        "mid_turn_steering": "documented_not_observed",
    },
    "documented_traits": (
        "asks a clarifying question more readily when more input could materially change the result",
        "follows instructions more strictly and may pause on unclear or conflicting skill-file guidance",
        "may delegate less often than a harness expects",
        "may write broader tests than the change requires",
    ),
    # OpenAI list price (developers.openai.com model reference, 2026-09).
    # The approximation table carries input/output only; cache writes and
    # the >272K long-context multiplier are documented here, not flattened.
    "pricing_usd_per_mtok": {
        "input": 10.0,
        "cached_input": 1.0,
        "cache_write": 12.5,
        "output": 50.0,
        "long_context_over_272k_input": "2x input and cache rates, 1.5x output",
    },
    "sources": (
        "https://openai.com/index/gpt-6-astra/",
        "https://developers.openai.com/api/docs/models/gpt-6-astra",
        "https://developers.openai.com/api/docs/guides/latest-model",
        "https://developers.openai.com/api/docs/guides/reasoning",
        "https://developers.openai.com/api/docs/guides/async-tool-calling",
        "https://developers.openai.com/api/docs/guides/steering",
    ),
    "sources_read": "2026-09-04",
    "claim_boundary": MODEL_CONTRACT_CLAIM_BOUNDARY,
}

MODEL_CONTRACTS: Final[dict[str, Mapping[str, object]]] = {
    "gpt-6-astra": _GPT_6_ASTRA,
}

# Catalog aliases whose relationship to an exact contract is explicitly
# declared. The spelling and composition order are part of the contract: a
# future suffix does not inherit until it gets its own row and evidence.
DECLARED_MODEL_CONTRACT_PROJECTIONS: Final[dict[str, Mapping[str, str]]] = {
    "gpt-6-astra-fast": {
        "contract_model_id": "gpt-6-astra",
        "reasoning_mode": "standard",
        "service_tier": "fast",
    },
    "gpt-6-astra-flex": {
        "contract_model_id": "gpt-6-astra",
        "reasoning_mode": "standard",
        "service_tier": "flex",
    },
    "gpt-6-astra-pro": {
        "contract_model_id": "gpt-6-astra",
        "reasoning_mode": "pro",
        "service_tier": "standard",
    },
    "gpt-6-astra-pro-fast": {
        "contract_model_id": "gpt-6-astra",
        "reasoning_mode": "pro",
        "service_tier": "fast",
    },
    "gpt-6-astra-pro-flex": {
        "contract_model_id": "gpt-6-astra",
        "reasoning_mode": "pro",
        "service_tier": "flex",
    },
}


def _unqualified_model_id(model_id: str) -> str:
    normalized = str(model_id or "").strip().casefold()
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[1]
    return normalized


def model_contract_projection(model_id: str) -> dict[str, str] | None:
    """Resolve an exact or explicitly inherited contract without guessing."""
    requested = str(model_id or "").strip()
    canonical = _unqualified_model_id(requested)
    if not canonical:
        return None
    contract = MODEL_CONTRACTS.get(canonical)
    declared = DECLARED_MODEL_CONTRACT_PROJECTIONS.get(canonical)
    if contract is not None:
        contract_id = canonical
        reasoning_mode = str(contract.get("reasoning_mode", "standard"))
        service_tier = str(contract.get("service_tier", "standard"))
        provenance = "exact"
    elif declared is not None:
        contract_id = str(declared["contract_model_id"])
        if contract_id not in MODEL_CONTRACTS:
            return None
        reasoning_mode = str(declared["reasoning_mode"])
        service_tier = str(declared["service_tier"])
        provenance = "declared_inheritance"
    else:
        return None
    return {
        "schema_version": MODEL_CONTRACT_PROJECTION_SCHEMA_VERSION,
        "requested_model": requested,
        "canonical_model_id": canonical,
        "contract_model_id": contract_id,
        "reasoning_mode": reasoning_mode,
        "service_tier": service_tier,
        "provenance": provenance,
        "claim_boundary": MODEL_CONTRACT_PROJECTION_CLAIM_BOUNDARY,
    }


def contract_model_id(model_id: str) -> str:
    """Return the exact/declared contract key, or the normalized unknown id."""
    projection = model_contract_projection(model_id)
    return str(projection["contract_model_id"]) if projection is not None else _unqualified_model_id(model_id)


def model_contract(model_id: str) -> Mapping[str, object] | None:
    """Return the exact or explicitly inherited documented contract, or None."""
    projection = model_contract_projection(model_id)
    return MODEL_CONTRACTS.get(str(projection["contract_model_id"])) if projection is not None else None


def contract_effort_floor(model_id: str, effort: str) -> tuple[str, str] | None:
    """Return (floor, reason) when ``effort`` sits below the model's documented ladder.

    ``None`` means the contract has nothing to say: no contract, no floor, an
    effort the ladder supports, or a value that is not a documented-unsupported
    rung. The caller records the raise as an explicit effort change; nothing is
    changed silently.
    """
    contract = model_contract(model_id)
    if contract is None:
        return None
    floor = str(contract.get("effort_floor", "") or "")
    supported = tuple(str(value) for value in contract.get("reasoning_efforts", ()))
    normalized = str(effort or "").strip().casefold()
    if not floor or not normalized or normalized in supported:
        return None
    unsupported = contract.get("unsupported_efforts", {})
    if not isinstance(unsupported, Mapping) or normalized not in unsupported:
        return None
    detail = str(unsupported[normalized])
    return floor, (
        f"`{normalized}` is below `{contract['model_id']}`'s documented effort ladder "
        f"({detail}); raised to the documented floor `{floor}`"
    )


def dynamic_effort_guidance(model_id: str, executor_profile: str) -> dict[str, object] | None:
    """Return the effort-policy record for a model with a documented dynamic-effort mechanism.

    The mid-conversation mechanism is described only when ``executor_profile``
    is one the contract names as compatible; every other profile gets the
    per-turn policy, so no prepared text implies a runtime mutation that the
    runtime cannot perform.
    """
    contract = model_contract(model_id)
    if contract is None:
        return None
    dynamic = contract.get("dynamic_effort")
    if not isinstance(dynamic, Mapping):
        return None
    profile = str(executor_profile or "").strip().casefold()
    compatible = tuple(str(value) for value in dynamic.get("compatible_profiles", ()))
    floor = str(contract.get("effort_floor", "") or "")
    policy: dict[str, object] = {
        "model_id": str(contract["model_id"]),
        "effort_floor": floor,
        "escalate_while": (
            "an active criterion still holds unresolved hard reasoning, a new failure, or "
            "contradictory evidence"
        ),
        "reduce_when": "the decisive evidence is in hand and the remaining work is routine follow-up",
        "stop_when": (
            "every predeclared criterion is done, the single verification pass succeeded, no "
            "contradictory result remains, and the TODO is reconciled; a passed criterion is not "
            "reopened for reassurance"
        ),
        "status": str(dynamic.get("status", "documented_not_observed")),
    }
    if profile and profile in compatible:
        policy["mode"] = "mid_conversation"
        policy["mechanism"] = str(dynamic.get("mechanism", ""))
        policy["scope"] = str(dynamic.get("scope", ""))
        policy["constraints"] = list(dynamic.get("constraints", ()))
    else:
        policy["mode"] = "per_turn"
        policy["mechanism"] = "prepare the next unit or turn at the new effort"
        policy["note"] = (
            f"`{profile or 'this'}` executor profile is not documented as exposing "
            f"{dynamic.get('mechanism', 'a mid-conversation effort update')}; effort is set "
            "explicitly per prepared turn and no mid-conversation change is claimed"
        )
    return policy


__all__ = [
    "DECLARED_MODEL_CONTRACT_PROJECTIONS",
    "EFFORT_FLOOR_KIND",
    "MODEL_CONTRACTS",
    "MODEL_CONTRACT_CLAIM_BOUNDARY",
    "MODEL_CONTRACT_PROJECTION_CLAIM_BOUNDARY",
    "MODEL_CONTRACT_PROJECTION_SCHEMA_VERSION",
    "MODEL_CONTRACT_SCHEMA_VERSION",
    "contract_effort_floor",
    "contract_model_id",
    "dynamic_effort_guidance",
    "model_contract",
    "model_contract_projection",
]
