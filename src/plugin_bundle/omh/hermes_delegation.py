"""Read-only observation of Hermes-native subagent delegations.

`delegate_task` children are first-class work the HUD must show live: Hermes
already records everything needed — the child session's model and reasoning
effort in `state.db` (`sessions.model_config`, with `_delegate_from` naming
the parent), token/cache/cost tallies in `session_model_usage`, background
lifecycle in `async_delegations`, and an append-only live transcript plus
`manifest.json` per delegation under `cache/delegation/live/`. This module
joins those surfaces into HUD activity rows without writing anything and
without importing Hermes code.

Everything here is observation of another product's on-disk state, so every
read degrades to "nothing observed" instead of raising: a locked SQLite file,
a torn manifest, or a missing directory must render as an idle HUD segment,
never as a widget error.

The category label is a *projection*, not an observed routing record: Hermes
does not persist which OMH mixture category (if any) chose the child's model,
so the label is derived by matching the observed model+effort against the
shipped mixture chains. A child running the parent session's own model is
labeled ``inherit`` — deliberately, so a delegation wave that never engaged
mixture routing is visible as such instead of masquerading as a routed one.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# Mirrors SHIPPED_MODEL_RECOMMENDATIONS["categories"] in
# src/coding/model_recommendations.py, projected to (model_alias,
# reasoning_effort) pairs in chain order. The plugin bundle ships standalone
# into $HERMES_HOME/plugins and cannot import src/coding, so the chains are
# embedded; tests/test_plugin_hermes_delegation.py holds the dict-parity gate.
# These are shipped editorial DEFAULTS: a user customizes chains without
# touching code by writing the mixture_chain_overrides/v1 document at
# ~/.omh/routing/model-chains.json (see effective_mixture_category_chains).
HERMES_MIXTURE_CATEGORY_CHAINS: dict[str, tuple[tuple[str, str], ...]] = {
    # GPT-6 Astra heads the GPT frontier slots (2026-09-03); Sol stays as
    # fall-through so a machine the staged rollout has not reached keeps
    # resolving to the GPT ecosystem.
    "ultrabrain": (("gpt-6-astra", "xhigh"), ("gpt-5.6-sol", "xhigh")),
    # DeepSeek closes deep's single-ecosystem exposure (the owner rule below
    # applied to a chain that sat entirely on GPT) with a reasoning-capable
    # budget candidate from a fourth provider ecosystem.
    "deep": (("gpt-5.6-terra", "high"), ("deepseek-v3.2", "high")),
    # Architecture/system-design lanes: full-depth effort across three
    # provider ecosystems. Fable and Kimi appear in other chains only at
    # low/high, so at xhigh `mixture_category_for` labels them architect;
    # Sol at xhigh stays labeled ultrabrain (its canonical head), which is
    # the honest projection when the chain falls through to it.
    # Claude vendor order (owner decision, 2026-09-02): Fable 5.1 -> Mythos
    # 5.1 -> Fable 5 fall-through. Mythos 5.1 is Fable 5.1 under Project
    # Glasswing access; an unapproved account's provider rejection falls the
    # chain through, so it never heads a chain.
    "architect": (
        ("claude-fable-5-1", "xhigh"),
        ("claude-mythos-5-1", "xhigh"),
        ("claude-fable-5", "xhigh"),
        ("gpt-6-astra", "xhigh"),
        ("gpt-5.6-sol", "xhigh"),
        ("kimi-k3", "xhigh"),
    ),
    "unspecified-high": (("kimi-k3", "medium"), ("claude-opus-5", "medium")),
    # A chain that would otherwise sit in one provider ecosystem ends with a
    # comparable-tier candidate from another (owner rule, 2026-08-19), so one
    # rejected ecosystem cannot exhaust the whole chain.
    # GLM 5.3 leads (owner decision, 2026-08-31): 5.3 heads the low-cost
    # chains and the 5.2 entries stay as fall-through so machines that only
    # serve 5.2 keep resolving to GLM instead of skipping the ecosystem.
    "unspecified-low": (
        ("glm-5.3", "low"),
        ("glm-5.2", "low"),
        ("glm-5.2-ultrafast", "low"),
        ("deepseek-v3.2", "low"),
        ("claude-opus-5", "low"),
    ),
    "quick": (
        ("glm-5.3-flash", "low"),
        ("glm-5.2-ultrafast", "low"),
        ("kimi-k3", "low"),
        ("gpt-5.6-luna", "low"),
        ("claude-fable-5-1", "low"),
        ("claude-mythos-5-1", "low"),
        ("claude-fable-5", "low"),
    ),
    "writing": (
        ("kimi-k3", "medium"),
        ("qwen3-coder", "medium"),
        ("gemini-3.1-pro", "medium"),
    ),
    "visual-engineering": (
        ("claude-fable-5-1", "high"),
        ("claude-mythos-5-1", "high"),
        ("claude-fable-5", "high"),
        ("kimi-k3", "high"),
    ),
    "artistry": (
        ("gemini-3.1-pro", "high"),
        ("claude-fable-5-1", "high"),
        ("claude-mythos-5-1", "high"),
        ("claude-fable-5", "high"),
        ("kimi-k3", "high"),
    ),
}

# User-editable chain overrides. The document replaces only the chains of the
# categories it names; the category vocabulary itself stays closed (an unknown
# category makes the document invalid). Validation is strict and atomic — an
# invalid document is ignored entirely rather than half-applied — and every
# value must be a plain identifier token so a crafted "model name" can never
# smuggle structure into config.yaml via a later omh_delegate_route write.
MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION = "mixture_chain_overrides/v1"
_CHAIN_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


def mixture_chain_overrides_path(omh_home: str | Path | None = None) -> Path:
    root = Path(omh_home).expanduser() if omh_home else Path.home() / ".omh"
    return root / "routing" / "model-chains.json"


def load_mixture_chain_overrides(
    omh_home: str | Path | None = None,
) -> tuple[dict[str, tuple[tuple[str, str], ...]], str]:
    """Read the user's chain override document.

    Returns ``(overrides, status)`` where status is ``absent``, ``applied``,
    or ``invalid: <reason>``. Overrides map category name to a full
    replacement chain; only categories the document names appear.
    """
    path = mixture_chain_overrides_path(omh_home)
    try:
        raw = _strict_json_loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "absent"
    except (OSError, UnicodeDecodeError, ValueError):
        return {}, "invalid: unreadable JSON"
    return parse_mixture_chain_overrides(raw)


def parse_mixture_chain_overrides(
    raw: object,
) -> tuple[dict[str, tuple[tuple[str, str], ...]], str]:
    """Validate one already-parsed override document.

    Split from the file loader so writers (the `omh model-chains` command)
    can validate a composed document BEFORE writing it, with exactly the
    rules the reader enforces.
    """
    if not isinstance(raw, dict):
        return {}, "invalid: document must be a JSON object"
    if raw.get("schema_version") != MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION:
        return {}, f"invalid: schema_version must be {MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION}"
    categories = raw.get("categories")
    if not isinstance(categories, dict):
        return {}, "invalid: categories must be an object"
    unknown = sorted(set(raw) - {"schema_version", "categories"})
    if unknown:
        return {}, f"invalid: unsupported fields {unknown}"
    overrides: dict[str, tuple[tuple[str, str], ...]] = {}
    for name, entries in categories.items():
        if name not in HERMES_MIXTURE_CATEGORY_CHAINS:
            return {}, f"invalid: unknown category {name!r}"
        if not isinstance(entries, list) or not entries:
            return {}, f"invalid: category {name!r} must list at least one entry"
        chain: list[tuple[str, str]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                return {}, f"invalid: category {name!r} entries must be objects"
            unknown_keys = sorted(set(entry) - {"model", "reasoning_effort"})
            if unknown_keys:
                return {}, f"invalid: category {name!r} entry fields {unknown_keys}"
            model = entry.get("model", "")
            effort = entry.get("reasoning_effort", "")
            if not isinstance(model, str) or not _CHAIN_TOKEN_RE.fullmatch(model):
                return {}, f"invalid: category {name!r} names a non-token model"
            if not isinstance(effort, str) or (
                effort and not _CHAIN_TOKEN_RE.fullmatch(effort)
            ):
                return {}, f"invalid: category {name!r} names a non-token effort"
            chain.append((model, effort))
        overrides[name] = tuple(chain)
    return overrides, "applied"


def effective_mixture_category_chains(
    omh_home: str | Path | None = None,
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Shipped chains with the user's per-category replacements applied.

    When the operator has recorded provider entitlements (`omh setup` asks;
    see `load_provider_entitlements`), every chain is additionally shaped so
    the entries no confirmed provider can serve sit behind the ones that can.
    Shaping reorders; it never drops an entry, so a wrong answer costs one
    rejected fall-through, never a missing model.
    """
    overrides, _ = load_mixture_chain_overrides(omh_home)
    chains = {
        name: overrides.get(name, chain)
        for name, chain in HERMES_MIXTURE_CATEGORY_CHAINS.items()
    }
    entitlements, _status = load_provider_entitlements(omh_home)
    if entitlements is None:
        return chains
    routes, _ = load_model_provider_routes(omh_home)
    return {
        name: entitlement_shaped_chain(chain, entitlements, routes)
        for name, chain in chains.items()
    }


# Provider entitlements: what the operator said they hold, recorded once by
# the `omh setup` interview (and editable by hand). Chains stay provider-
# neutral alias lists; this document is the one place the machine's own
# accounts are described, and it only reorders the chains it is applied to.
#
#   {"schema_version": "provider_entitlements/v1",
#    "providers": {"og": "gateway", "zai": "zai"},
#    "subscription_clis": ["claude-code"]}
#
# `providers` maps a Hermes provider id (the key under `providers:` in
# config.yaml, or `model.provider`) to its KIND: one of the provider families
# the editorial catalog names for its candidates, or `gateway` for a
# multi-vendor relay that serves models of every family, or `unknown` when
# the operator declined to say (treated as a gateway, so nothing is demoted
# on a guess). `subscription_clis` lists the external coding CLIs whose
# subscription the operator confirmed and that only the Maestro lane can
# spend. Claude Code is the one such CLI today: Hermes has no way to use a
# Claude subscription, so the answer's only effect is the Claude Code
# `--model` preference. A Codex login is spent by Hermes' own openai-codex
# provider and therefore belongs under `providers`, not here.
PROVIDER_ENTITLEMENTS_SCHEMA_VERSION = "provider_entitlements/v1"
PROVIDER_KIND_GATEWAY = "gateway"
PROVIDER_KIND_UNKNOWN = "unknown"
# Mirrors the union of `preferred_provider_families` across
# SHIPPED_MODEL_RECOMMENDATIONS in src/coding/model_recommendations.py (the
# plugin bundle cannot import src/coding); the parity gate lives in
# tests/test_provider_entitlements.py (ParityTests).
PROVIDER_FAMILY_VOCABULARY: tuple[str, ...] = (
    "anthropic",
    "apitopia",
    "ccapi",
    "deepseek",
    "gemini",
    "google",
    "kimi-coding",
    "openai",
    "openai-codex",
    "opencode",
    "openrouter",
    "qwen-oauth",
    "xai",
    "zai",
)
PROVIDER_KIND_VOCABULARY: tuple[str, ...] = (
    *PROVIDER_FAMILY_VOCABULARY,
    PROVIDER_KIND_GATEWAY,
    PROVIDER_KIND_UNKNOWN,
)
# Kinds that relay every model family. `openrouter` and `opencode` are named
# families in the catalog AND multi-vendor relays, so they serve everything.
MULTI_VENDOR_PROVIDER_KINDS: frozenset[str] = frozenset(
    {"openrouter", "opencode", PROVIDER_KIND_GATEWAY, PROVIDER_KIND_UNKNOWN}
)
SUBSCRIPTION_CLI_PROFILES: tuple[str, ...] = ("claude-code",)

# Mirrors each shipped candidate's `preferred_provider_families` (parity
# gate: tests/test_provider_entitlements.py). An alias absent here is served
# by every provider — the honest default for an id the catalog has never
# described.
HERMES_MIXTURE_ALIAS_PROVIDER_FAMILIES: dict[str, tuple[str, ...]] = {
    "kimi-k3": ("apitopia", "kimi-coding", "openrouter", "opencode"),
    "claude-opus-5": ("ccapi", "anthropic", "openrouter"),
    "claude-fable-5": ("ccapi", "anthropic", "openrouter"),
    "claude-fable-5-1": ("ccapi", "anthropic", "openrouter"),
    "claude-mythos-5-1": ("ccapi", "anthropic", "openrouter"),
    "gpt-6-astra": ("openai-codex", "openai"),
    "gpt-5.6-sol": ("openai-codex", "openai"),
    "gpt-5.6-terra": ("openai-codex", "openai"),
    "gpt-5.6-luna": ("openai-codex", "openai"),
    "deepseek-v3.2": ("deepseek", "openrouter", "opencode"),
    "glm-5.2": ("zai", "openrouter", "opencode"),
    "glm-5.2-ultrafast": ("zai", "openrouter", "opencode"),
    "glm-5.3": ("zai", "openrouter", "opencode"),
    "glm-5.3-flash": ("zai", "openrouter", "opencode"),
    "grok-code-fast": ("xai", "openrouter"),
    "gemini-3.1-pro": ("google", "gemini", "openrouter"),
    "qwen3-coder": ("qwen-oauth", "openrouter", "opencode"),
}

# Standalone mirror of coding.model_contracts' exact keys. Keep this separate
# from declared aliases so a newly documented child contract stops inheriting
# stale provider/category metadata until its own rows are added here.
EXACT_MODEL_CONTRACT_ALIASES: frozenset[str] = frozenset({"gpt-6-astra"})

# Standalone mirror of coding.model_contracts' bounded declared projections.
# This plugin is copied into Hermes and cannot import the source package; the
# parity test fails if either table changes alone. Values are
# (contract/base alias, reasoning mode, service tier).
DECLARED_MODEL_ALIAS_PROJECTIONS: dict[str, tuple[str, str, str]] = {
    "gpt-6-astra-fast": ("gpt-6-astra", "standard", "fast"),
    "gpt-6-astra-flex": ("gpt-6-astra", "standard", "flex"),
    "gpt-6-astra-pro": ("gpt-6-astra", "pro", "standard"),
    "gpt-6-astra-pro-fast": ("gpt-6-astra", "pro", "fast"),
    "gpt-6-astra-pro-flex": ("gpt-6-astra", "pro", "flex"),
}


def _unqualified_model_alias(alias: object) -> str:
    key = str(alias or "").strip().casefold()
    return key.rsplit("/", 1)[-1]


def _projected_model_alias(alias: object) -> tuple[str, str]:
    """Return (declared base alias, service tier), without suffix guessing."""
    key = _unqualified_model_alias(alias)
    if key in EXACT_MODEL_CONTRACT_ALIASES:
        return key, "standard"
    projection = DECLARED_MODEL_ALIAS_PROJECTIONS.get(key)
    return (projection[0], projection[2]) if projection is not None else (key, "standard")


def is_provider_id_token(value: object) -> bool:
    """Whether ``value`` is a provider id the entitlement document accepts."""
    return isinstance(value, str) and bool(_CHAIN_TOKEN_RE.fullmatch(value))


def provider_entitlements_path(omh_home: str | Path | None = None) -> Path:
    root = Path(omh_home).expanduser() if omh_home else Path.home() / ".omh"
    return root / "routing" / "providers.json"


def load_provider_entitlements(
    omh_home: str | Path | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Read the operator's provider-entitlement document.

    Returns ``(entitlements, status)`` where status is ``absent``,
    ``applied``, or ``invalid: <reason>``; an absent or invalid document
    yields ``None`` so callers apply no shaping rather than half a document.
    """
    path = provider_entitlements_path(omh_home)
    try:
        raw = _strict_json_loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "absent"
    except (OSError, UnicodeDecodeError, ValueError):
        return None, "invalid: unreadable JSON"
    return parse_provider_entitlements(raw)


def parse_provider_entitlements(raw: object) -> tuple[dict[str, Any] | None, str]:
    """Validate one already-parsed entitlement document (strict, atomic)."""
    if not isinstance(raw, dict):
        return None, "invalid: document must be a JSON object"
    if raw.get("schema_version") != PROVIDER_ENTITLEMENTS_SCHEMA_VERSION:
        return None, f"invalid: schema_version must be {PROVIDER_ENTITLEMENTS_SCHEMA_VERSION}"
    unknown = sorted(set(raw) - {"schema_version", "providers", "subscription_clis"})
    if unknown:
        return None, f"invalid: unsupported fields {unknown}"
    providers = raw.get("providers", {})
    if not isinstance(providers, dict):
        return None, "invalid: providers must be an object"
    normalized_providers: dict[str, str] = {}
    for provider_id, kind in providers.items():
        if not isinstance(provider_id, str) or not _CHAIN_TOKEN_RE.fullmatch(provider_id):
            return None, f"invalid: provider id {provider_id!r} is not a plain identifier"
        if not isinstance(kind, str) or kind not in PROVIDER_KIND_VOCABULARY:
            return None, (
                f"invalid: provider {provider_id!r} kind must be one of "
                + ", ".join(PROVIDER_KIND_VOCABULARY)
            )
        normalized_providers[provider_id] = kind
    clis = raw.get("subscription_clis", [])
    if not isinstance(clis, list):
        return None, "invalid: subscription_clis must be a list"
    normalized_clis: list[str] = []
    for profile in clis:
        if not isinstance(profile, str) or profile not in SUBSCRIPTION_CLI_PROFILES:
            return None, (
                f"invalid: subscription_clis entry {profile!r} must be one of "
                + ", ".join(SUBSCRIPTION_CLI_PROFILES)
            )
        if profile not in normalized_clis:
            normalized_clis.append(profile)
    return {"providers": normalized_providers, "subscription_clis": normalized_clis}, "applied"


def alias_is_served(
    alias: str,
    entitlements: Mapping[str, Any],
    routes: Mapping[str, tuple[str, str]] | None = None,
) -> bool:
    """Whether a confirmed provider can serve ``alias``. Fails open.

    An explicit route in model-providers.json decides first: the alias is
    served when its provider is one the operator confirmed, and unserved when
    the route names a provider they did not. Without a route, a multi-vendor
    provider serves every alias, a vendor provider serves the aliases whose
    catalog families name it, and an alias the catalog never described (or a
    machine with no providers recorded at all) is served — nothing is
    demoted on a guess.
    """
    providers = entitlements.get("providers", {})
    if not isinstance(providers, Mapping) or not providers:
        return True
    requested_key = str(alias or "").strip().casefold()
    canonical_key = _unqualified_model_alias(alias)
    if routes:
        route = routes.get(requested_key) or routes.get(canonical_key) or routes.get(alias)
        if route:
            return route[0] in providers
    kinds = set(str(kind) for kind in providers.values())
    if kinds & MULTI_VENDOR_PROVIDER_KINDS:
        return True
    projected_key, _tier = _projected_model_alias(canonical_key)
    families = HERMES_MIXTURE_ALIAS_PROVIDER_FAMILIES.get(projected_key)
    if families is None:
        return True
    return bool(kinds & set(families))


def provider_family_for(provider_id: str, entitlements: Mapping[str, Any] | None) -> str:
    """The family a provider id belongs to, or "" when nothing records it.

    The operator's own document decides first, because a provider id is
    theirs to name -- `og`, `work-gateway`, anything. A id that is itself a
    catalog family name (`anthropic`, `openai-codex`) resolves without a
    document, which is what an install with no entitlements recorded has.
    """
    key = str(provider_id or "").strip()
    if not key:
        return ""
    providers = (entitlements or {}).get("providers", {})
    if isinstance(providers, Mapping):
        recorded = providers.get(key)
        if isinstance(recorded, str) and recorded:
            return recorded
    return key if key in PROVIDER_FAMILY_VOCABULARY else ""


def provider_serves_alias(
    alias: str,
    provider_id: str,
    entitlements: Mapping[str, Any] | None = None,
) -> bool | None:
    """Whether ONE named provider can serve ``alias``. None means unknown.

    Distinct from `alias_is_served`, which asks whether ANY confirmed
    provider could. That question cannot catch the failure this one exists
    for: a dispatch that inherits its provider goes to whatever the session
    runs on, and a multi-vendor account elsewhere in the document does not
    make the inherited one able to serve the model.

    Unknown -- not False -- whenever the provider has no recorded family, the
    catalog never described the alias, or the family is multi-vendor and so
    serves everything. Nothing is refused on a guess.
    """
    family = provider_family_for(provider_id, entitlements)
    if not family or family in MULTI_VENDOR_PROVIDER_KINDS:
        return None
    projected_key, _tier = _projected_model_alias(alias)
    families = HERMES_MIXTURE_ALIAS_PROVIDER_FAMILIES.get(projected_key)
    if families is None:
        return None
    return family in families


def providers_serving_alias(
    alias: str,
    entitlements: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """The operator's own provider ids that could serve ``alias``.

    The direction half of the guard: refusing a dispatch is only useful
    beside the answer, and the answer can only come from what the operator
    recorded holding.
    """
    providers = (entitlements or {}).get("providers", {})
    if not isinstance(providers, Mapping):
        return ()
    projected_key, _tier = _projected_model_alias(alias)
    families = HERMES_MIXTURE_ALIAS_PROVIDER_FAMILIES.get(projected_key)
    candidates = []
    for provider_id, kind in providers.items():
        if not isinstance(provider_id, str) or not isinstance(kind, str):
            continue
        if kind in MULTI_VENDOR_PROVIDER_KINDS or (families and kind in families):
            candidates.append(provider_id)
    return tuple(sorted(candidates))


def entitlement_shaped_chain(
    chain: tuple[tuple[str, str], ...],
    entitlements: Mapping[str, Any],
    routes: Mapping[str, tuple[str, str]] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Stable-partition ``chain``: served entries first, unserved behind them."""
    served = tuple(entry for entry in chain if alias_is_served(entry[0], entitlements, routes))
    unserved = tuple(entry for entry in chain if not alias_is_served(entry[0], entitlements, routes))
    return served + unserved


# User-editable alias -> (provider, wire model) routes.
#
# A chain names a model the way a person says it (`glm-5.2`, `kimi-k3`), but a
# host that reaches models through a provider usually needs two different
# values: a provider id and that provider's own model string, which is often
# namespaced (`vendor/model`). Which provider serves which model, and under
# what name, is a property of one person's account -- so OMH ships NO routes
# and hardcodes no provider. Absent this document every alias dispatches
# unchanged, which is the behavior every host without a provider indirection
# wants.
#
# Validation mirrors the chain-override contract exactly: strict, atomic, and
# token-only, so a crafted value can never smuggle structure into config.yaml
# through a later omh_delegate_route write.
MODEL_PROVIDER_ROUTES_SCHEMA_VERSION = "model_provider_routes/v1"


def model_provider_routes_path(omh_home: str | Path | None = None) -> Path:
    root = Path(omh_home).expanduser() if omh_home else Path.home() / ".omh"
    return root / "routing" / "model-providers.json"


def load_model_provider_routes(
    omh_home: str | Path | None = None,
) -> tuple[dict[str, tuple[str, str]], str]:
    """Read the user's alias -> (provider, model) document.

    Returns ``(routes, status)`` where status is ``absent``, ``applied``, or
    ``invalid: <reason>``, matching `load_mixture_chain_overrides`.
    """
    path = model_provider_routes_path(omh_home)
    try:
        raw = _strict_json_loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "absent"
    except (OSError, UnicodeDecodeError, ValueError):
        return {}, "invalid: unreadable JSON"
    return parse_model_provider_routes(raw)


def parse_model_provider_routes(
    raw: object,
) -> tuple[dict[str, tuple[str, str]], str]:
    """Validate one already-parsed provider-route document."""
    if not isinstance(raw, dict):
        return {}, "invalid: document must be a JSON object"
    if raw.get("schema_version") != MODEL_PROVIDER_ROUTES_SCHEMA_VERSION:
        return {}, f"invalid: schema_version must be {MODEL_PROVIDER_ROUTES_SCHEMA_VERSION}"
    models = raw.get("models")
    if not isinstance(models, dict):
        return {}, "invalid: models must be an object"
    unknown = sorted(set(raw) - {"schema_version", "models"})
    if unknown:
        return {}, f"invalid: unsupported fields {unknown}"
    routes: dict[str, tuple[str, str]] = {}
    for alias, entry in models.items():
        if not isinstance(alias, str) or not _CHAIN_TOKEN_RE.fullmatch(alias):
            return {}, f"invalid: alias {alias!r} is not a token"
        if not isinstance(entry, dict):
            return {}, f"invalid: alias {alias!r} must map to an object"
        unknown_keys = sorted(set(entry) - {"provider", "model"})
        if unknown_keys:
            return {}, f"invalid: alias {alias!r} entry fields {unknown_keys}"
        provider = entry.get("provider", "")
        model = entry.get("model", "")
        if not isinstance(provider, str) or not _CHAIN_TOKEN_RE.fullmatch(provider):
            return {}, f"invalid: alias {alias!r} names a non-token provider"
        if not isinstance(model, str) or not _CHAIN_TOKEN_RE.fullmatch(model):
            return {}, f"invalid: alias {alias!r} names a non-token model"
        routes[alias] = (provider, model)
    return routes, "applied"


def resolve_provider_model(
    model: str,
    provider: str = "",
    routes: Mapping[str, tuple[str, str]] | None = None,
) -> tuple[str, str]:
    """Expand one alias into ``(wire model, provider)``.

    A caller that pinned a provider is answered verbatim: an explicit choice
    outranks a stored route. An alias with no route is returned unchanged with
    no provider, which is what a direct-billing host needs.
    """
    if provider:
        return model, provider
    resolved = (routes or {}).get(model)
    if resolved is None:
        return model, ""
    resolved_provider, wire_model = resolved
    return wire_model, resolved_provider


def chain_alias_for(
    model: str,
    provider: str = "",
    routes: Mapping[str, tuple[str, str]] | None = None,
) -> str:
    """Map a wire model back to the alias its chain uses.

    Chain positions are matched by alias, so a route that was written as a
    wire model has to be translated back before any chain lookup; otherwise a
    routed model looks absent from the chain it came from.
    """
    if not provider:
        return model
    aliases = {
        alias
        for alias, (route_provider, wire_model) in (routes or {}).items()
        if provider == route_provider and model == wire_model
    }
    return next(iter(aliases)) if len(aliases) == 1 else model


def configured_route_for_wire(
    model: str,
    routes: Mapping[str, tuple[str, str]] | None = None,
) -> tuple[str, str]:
    """Return one uniquely configured alias/provider for an observed wire model."""
    matches = {
        (alias, provider)
        for alias, (provider, wire_model) in (routes or {}).items()
        if model == wire_model
    }
    return next(iter(matches)) if len(matches) == 1 else (model, "")


# Prepared-route provenance. Hermes persists which model a child ran, but not
# WHY that model was chosen — chain head, fallback after a dead candidate, or
# chain exhaustion clearing back to parent inheritance. omh_delegate_route
# records each successful route write here so the HUD can label a fallback
# lane as a fallback instead of rendering it indistinguishable from a head
# route (and an exhausted chain as `category(model inherit)` — the category
# names the lane and never changes — instead of plain inherit). The record is preparation evidence only: a label upgrade for an
# observed child whose wire identity matches, never execution evidence and
# never a routing input.
DELEGATION_ROUTE_PROVENANCE_SCHEMA_VERSION = "delegation_route_provenance/v1"
_PROVENANCE_RECORD_LIMIT = 32
# A route write immediately precedes its dispatch (the tool contract is
# set → dispatch per lane). A record this much older than a child's start
# no longer describes that dispatch, so it stops upgrading labels.
_PROVENANCE_FRESHNESS_SECONDS = 900.0
# An exhaustion record describes only the immediate re-dispatch after the
# chain cleared — the agent retries within seconds, and every inherit child
# beyond this window is an ordinary unrouted lane, so the claim window is
# much tighter than the routed one.
_EXHAUSTION_FRESHNESS_SECONDS = 120.0
_PROVENANCE_ORIGINS = (
    "head",
    "explicit",
    "fallback",
    "exhausted_to_inherit",
    "cleared",
)


def delegation_route_provenance_path(omh_home: str | Path | None = None) -> Path:
    root = Path(omh_home).expanduser() if omh_home else Path.home() / ".omh"
    return root / "routing" / "route-provenance.json"


def _valid_provenance_record(record: object) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    origin = record.get("origin")
    if origin not in _PROVENANCE_ORIGINS:
        return None
    written_at = record.get("written_at")
    if (
        isinstance(written_at, bool)
        or not isinstance(written_at, (int, float))
        or not written_at == written_at
    ):
        return None
    cleaned: dict[str, Any] = {"origin": origin, "written_at": float(written_at)}
    for field in ("category", "alias", "wire_model", "provider", "reasoning_effort", "from_alias"):
        value = record.get(field, "")
        if not isinstance(value, str) or len(value) > 160:
            return None
        cleaned[field] = value
    return cleaned


def load_delegation_route_provenance(
    omh_home: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Read prepared-route records, oldest first; absent or invalid is empty.

    Provenance only ever upgrades a HUD label — it never gates routing — so
    every failure mode reads as "no provenance" rather than an error.
    """
    path = delegation_route_provenance_path(omh_home)
    try:
        raw = _strict_json_loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError, ValueError):
        return []
    if not isinstance(raw, dict):
        return []
    if raw.get("schema_version") != DELEGATION_ROUTE_PROVENANCE_SCHEMA_VERSION:
        return []
    records = raw.get("records")
    if not isinstance(records, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for record in records:
        valid = _valid_provenance_record(record)
        if valid is None:
            return []
        cleaned.append(valid)
    return cleaned


def append_delegation_route_provenance(
    record: dict[str, Any],
    omh_home: str | Path | None = None,
) -> str:
    """Append one prepared-route record; returns ``recorded`` or ``unrecorded: <reason>``."""
    valid = _valid_provenance_record(record)
    if valid is None:
        return "unrecorded: invalid record"
    records = load_delegation_route_provenance(omh_home)
    records.append(valid)
    records = records[-_PROVENANCE_RECORD_LIMIT:]
    payload = {
        "schema_version": DELEGATION_ROUTE_PROVENANCE_SCHEMA_VERSION,
        "records": records,
    }
    payload["claim_boundary"] = (
        "Prepared routes only: each record says what omh_delegate_route wrote "
        "into delegation.* before a dispatch, not that any dispatch ran, "
        "which model a child actually used, or that the lane completed. The "
        "history is read-modify-write without a lock; concurrent appends may "
        "drop a record, which degrades to a missing HUD label."
    )
    path = delegation_route_provenance_path(omh_home)
    temp_name = ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=".omh-route-provenance-", dir=str(path.parent)
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
        os.replace(temp_name, path)
    except OSError:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        return "unrecorded: provenance write failed"
    return "recorded"


def _child_is_inherit(
    child: Mapping[str, Any],
    parent_models: Mapping[str, str],
    provider_routes: Mapping[str, tuple[str, str]],
) -> bool:
    """Mirror the projection's inherit test: child alias == parent model."""
    parent_model = _text(parent_models.get(child.get("parent_id", ""), ""))
    if not parent_model:
        return False
    alias, _ = configured_route_for_wire(child["model"], provider_routes)
    return _text(alias).casefold() == parent_model.casefold()


def _provenance_for_dispatch(
    records: list[dict[str, Any]],
    *,
    started_at: float,
    wire_model: str,
    alias: str,
    is_inherit: bool,
    session_id: str = "",
    exhaustion_claims: Mapping[int, str] | None = None,
) -> dict[str, Any] | None:
    """Best-effort pairing of a child with the route prepared before it.

    Like the manifest/task pairing above, this is best-effort context, never
    row identity: only the newest record written before the child's start is
    considered (later writes replaced it for later lanes), the child must
    still match the record's identity, and every ambiguity degrades to "no
    record" — a missing label is acceptable, a wrong one is not.
    """
    for index in range(len(records) - 1, -1, -1):
        record = records[index]
        # written_at and the child's started_at come from the same machine
        # clock, and the tool contract writes the route BEFORE dispatching
        # the lane, so a record stamped after the child started cannot be
        # the route that dispatch read.
        if record["written_at"] > started_at:
            continue
        if started_at - record["written_at"] > _PROVENANCE_FRESHNESS_SECONDS:
            return None
        if record["origin"] == "cleared":
            # The route was explicitly cleared before this dispatch: the
            # child inherited on purpose, and no older record describes it.
            return None
        if record["origin"] == "exhausted_to_inherit":
            # An exhaustion record describes exactly one dispatch — the
            # next inherit child after the chain cleared. The caller
            # precomputes that claim, the window is tight, and every other
            # inherit child is an ordinary unrouted lane.
            if not is_inherit:
                return None
            if started_at - record["written_at"] > _EXHAUSTION_FRESHNESS_SECONDS:
                return None
            claimed = (exhaustion_claims or {}).get(index, "")
            return record if session_id and session_id == claimed else None
        if is_inherit:
            # `inherit` wins over any chain match (the projection's
            # documented invariant): a child on the parent session's own
            # model was not routed, whatever the prepared route said.
            return None
        matched = (wire_model and wire_model == record["wire_model"]) or (
            alias and alias == record["alias"]
        )
        return record if matched else None
    return None


def _strict_json_loads(text: str) -> object:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=unique_object)

# Rough USD-per-million-token list prices used ONLY when the host recorded no
# cost (subscription billing bills nothing per call; the owner asked for an
# approximation there instead of a blank). These are editable ballpark figures,
# not billing evidence — every cost derived from them is flagged approximate
# and rendered with a `~`. Cache reads are charged at a tenth of input unless
# APPROX_CACHE_READ_RATIO names the model.
APPROX_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    # Every rate below carries the vendor page it came from and the month it
    # was read. A number without that is unauditable -- a reader cannot tell
    # a current price from one that drifted, which is how the Claude rows
    # went stale before anyone noticed.
    # OpenAI list prices (openai.com/api/pricing, 2026-08):
    "gpt-5.6-sol": (1.25, 10.0),
    # OpenAI list price (developers.openai.com/api/docs/models/gpt-6-astra,
    # 2026-09): 10/50; cached input 1 (the default tenth). The $12.5 cache
    # write and the 2x/1.5x multiplier above 272K input have no column in
    # this table and stay documented in `src/coding/model_contracts.py`.
    "gpt-6-astra": (10.0, 50.0),
    "gpt-5.6-terra": (1.25, 10.0),
    "gpt-5.6-luna": (0.25, 2.0),
    # Anthropic first-party list prices (docs.claude.com pricing, 2026-09):
    # Opus 5 5/25, Sonnet 5 2/10, Fable 5 and 5.1 10/50; Mythos 5.1 shares
    # Fable 5.1's per-token price. Earlier entries here were stale.
    "claude-opus-5": (5.0, 25.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-fable-5-1": (10.0, 50.0),
    "claude-mythos-5-1": (10.0, 50.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    # Moonshot AI list price (platform.moonshot.cn pricing, 2026-08):
    "kimi-k3": (0.6, 2.5),
    # Zhipu AI list price (docs.z.ai pricing, 2026-08):
    "glm-5.2": (0.6, 2.2),
    # Z.ai list price for the 5.3 generation (docs.z.ai pricing, 2026-08).
    # 5.3 always reasons and bills the reasoning inside output tokens, so the
    # output side dominates real spend; still an approximation, not billing.
    "glm-5.3": (1.4, 4.4),
    "glm-5.3-flash": (0.15, 0.5),
    # DeepSeek list price (api-docs.deepseek.com pricing, 2026-08):
    "deepseek-v3.2": (0.28, 0.42),
    # Zhipu AI speed-tier ballpark (docs.z.ai pricing, 2026-08):
    "glm-5.2-ultrafast": (0.3, 1.2),
    # Speed-tier ballpark mirrors the glm pattern (roughly half the base
    # model's list price); editable approximation, not billing evidence.
    "kimi-k3-ultrafast": (0.3, 1.25),
    # Google AI Studio list price (ai.google.dev/pricing, 2026-08):
    "gemini-3.1-pro": (1.25, 10.0),
    # Alibaba Cloud Model Studio list price (alibabacloud.com pricing, 2026-08):
    "qwen3-coder": (0.4, 1.6),
    # Upstage list price (upstage.ai pricing, 2026-08):
    "solar-pro2": (0.15, 0.60),
    # xAI list price (docs.x.ai pricing, 2026-08). The catalog shipped
    # this model with a provider family and no rate, so every run on it
    # reported no cost at all.
    "grok-code-fast": (0.2, 1.5),
}


# Cache-read price as a fraction of input price, per model, where the vendor
# documents a rate other than the tenth above. Fable 5.1 lists cache reads at
# $0.25/MTok against $10 input (docs.claude.com pricing, 2026-09); Mythos 5.1
# shares Fable 5.1's per-token price and its cache-read rate was open at
# launch, so its entry is the Fable figure, still an approximation.
APPROX_CACHE_READ_RATIO: dict[str, float] = {
    "claude-fable-5-1": 0.025,
    "claude-mythos-5-1": 0.025,
}
_DEFAULT_CACHE_READ_RATIO = 0.1


# Token prices differ per user and drift over time: a gateway applies its own
# markup, an enterprise contract is not the list price, a free tier bills
# nothing, and vendors reprice. The shipped table below is a ballpark, so the
# rates a user actually pays belong in their own document rather than in our
# source -- the same rule `model-chains.json` and `providers.json` already
# follow ("Chain customization is a config edit, not a source edit").
#
#   {"schema_version": "model_price_overrides/v1",
#    "models": {"claude-fable-5-1": {"input_per_mtok": 8.0,
#                                    "output_per_mtok": 40.0,
#                                    "cache_read_ratio": 0.025}}}
#
# `cache_read_ratio` is optional and defaults to the shipped ratio for that
# model. A model the shipped table never priced can be priced here, which is
# how a user reaches a model OMH ships no rate for at all.
MODEL_PRICE_OVERRIDES_SCHEMA_VERSION = "model_price_overrides/v1"


def model_price_overrides_path(omh_home: str | Path | None = None) -> Path:
    root = Path(omh_home).expanduser() if omh_home else Path.home() / ".omh"
    return root / "routing" / "model-prices.json"


def load_model_price_overrides(
    omh_home: str | Path | None = None,
) -> tuple[dict[str, tuple[float, float, float | None]], str]:
    """Read the user's price override document.

    Returns ``(overrides, status)`` where status is ``absent``, ``applied``,
    or ``invalid: <reason>``, matching `load_mixture_chain_overrides`. An
    invalid document is ignored entirely rather than half-applied.
    """
    path = model_price_overrides_path(omh_home)
    try:
        raw = _strict_json_loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "absent"
    except (OSError, UnicodeDecodeError, ValueError):
        return {}, "invalid: unreadable JSON"
    return parse_model_price_overrides(raw)


def parse_model_price_overrides(
    raw: object,
) -> tuple[dict[str, tuple[float, float, float | None]], str]:
    """Validate one already-parsed price document (strict, atomic)."""
    if not isinstance(raw, dict):
        return {}, "invalid: document must be a JSON object"
    if raw.get("schema_version") != MODEL_PRICE_OVERRIDES_SCHEMA_VERSION:
        return {}, f"invalid: schema_version must be {MODEL_PRICE_OVERRIDES_SCHEMA_VERSION}"
    unknown = sorted(set(raw) - {"schema_version", "models"})
    if unknown:
        return {}, f"invalid: unsupported fields {unknown}"
    models = raw.get("models")
    if not isinstance(models, dict):
        return {}, "invalid: models must be an object"
    overrides: dict[str, tuple[float, float, float | None]] = {}
    for name, entry in models.items():
        if not isinstance(name, str) or not _CHAIN_TOKEN_RE.fullmatch(name):
            return {}, f"invalid: model {name!r} is not a plain model token"
        if not isinstance(entry, dict):
            return {}, f"invalid: model {name!r} must be an object"
        entry_unknown = sorted(set(entry) - {"input_per_mtok", "output_per_mtok", "cache_read_ratio"})
        if entry_unknown:
            return {}, f"invalid: model {name!r} fields {entry_unknown}"
        rates: list[float] = []
        for field in ("input_per_mtok", "output_per_mtok"):
            value = entry.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return {}, f"invalid: model {name!r} {field} must be a number"
            if value != value or value < 0 or value == float("inf"):
                return {}, f"invalid: model {name!r} {field} must be zero or more"
            rates.append(float(value))
        ratio = entry.get("cache_read_ratio")
        if ratio is None:
            cache_ratio: float | None = None
        elif isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
            return {}, f"invalid: model {name!r} cache_read_ratio must be a number"
        elif ratio != ratio or ratio < 0 or ratio > 1:
            return {}, f"invalid: model {name!r} cache_read_ratio must be between 0 and 1"
        else:
            cache_ratio = float(ratio)
        overrides[name.casefold()] = (rates[0], rates[1], cache_ratio)
    return overrides, "applied"


def _approximate_cost_usd(
    model: str,
    input_tokens: float,
    output_tokens: float,
    cache_read_tokens: float,
    overrides: Mapping[str, tuple[float, float, float | None]] | None = None,
) -> float | None:
    if (input_tokens + output_tokens) <= 0:
        return None
    requested_key = _text(model).casefold()
    canonical_key = _unqualified_model_alias(requested_key)
    base_key, service_tier = _projected_model_alias(canonical_key)
    provider, separator, _model = requested_key.rpartition("/")
    provider_base_key = f"{provider}/{base_key}" if separator else ""
    override_key = _model_price_override_key(requested_key, overrides)
    if override_key:
        override = (overrides or {})[override_key]
        input_price, output_price, override_ratio = override
        cache_ratio = (
            override_ratio
            if override_ratio is not None
            else APPROX_CACHE_READ_RATIO.get(
                canonical_key,
                APPROX_CACHE_READ_RATIO.get(base_key, _DEFAULT_CACHE_READ_RATIO),
            )
        )
        multiplier = (
            _service_tier_price_multiplier(service_tier)
            if override_key in {provider_base_key, base_key} and canonical_key != base_key
            else 1.0
        )
        return multiplier * (
            input_tokens * input_price
            + cache_read_tokens * input_price * cache_ratio
            + output_tokens * output_price
        ) / 1_000_000
    price_key = canonical_key if canonical_key in APPROX_PRICE_PER_MTOK else base_key
    prices = APPROX_PRICE_PER_MTOK.get(price_key)
    if not prices:
        return None
    input_price, output_price = prices
    cache_ratio = APPROX_CACHE_READ_RATIO.get(
        canonical_key,
        APPROX_CACHE_READ_RATIO.get(base_key, _DEFAULT_CACHE_READ_RATIO),
    )
    multiplier = (
        _service_tier_price_multiplier(service_tier)
        if price_key == base_key and canonical_key != base_key
        else 1.0
    )
    return multiplier * (
        input_tokens * input_price
        + cache_read_tokens * input_price * cache_ratio
        + output_tokens * output_price
    ) / 1_000_000


def _model_price_override_key(
    model: str,
    overrides: Mapping[str, tuple[float, float, float | None]] | None,
) -> str:
    """Return the exact or inherited override key cost resolution will use."""
    requested_key = _text(model).casefold()
    canonical_key = _unqualified_model_alias(requested_key)
    base_key, _service_tier = _projected_model_alias(canonical_key)
    provider, separator, _model = requested_key.rpartition("/")
    provider_base_key = f"{provider}/{base_key}" if separator else ""
    return next(
        (
            key
            for key in dict.fromkeys(
                (requested_key, canonical_key, provider_base_key, base_key)
            )
            if key and (overrides or {}).get(key) is not None
        ),
        "",
    )


def _service_tier_price_multiplier(service_tier: str) -> float:
    # OpenAI documents Fast at 2x and Flex/Batch at 0.5x. Pro is a reasoning
    # mode, not a price tier, so it deliberately has no multiplier.
    return {"fast": 2.0, "flex": 0.5}.get(service_tier, 1.0)


# A child is "running" while its newest observable signal (live transcript
# mtime, usage last_seen, session start) is at most this old. The live log
# streams one line per child event, so an actively working child refreshes
# well inside this window; a child that stalls longer than this reads as done
# rather than spinning forever.
RECENT_ACTIVITY_SECONDS = 150
# Finished children linger as "done" rows for this long so the operator sees
# what just completed — same shape as the todo panel's finished-plan linger.
COMPLETED_LINGER_SECONDS = 15 * 60
# Children older than this are history, not HUD material, regardless of state.
_SESSION_WINDOW_SECONDS = 6 * 3600
_ACTION_LIMIT = 140
_ROW_LIMIT = 8


def _text(value: Any, limit: int = 80) -> str:
    return str(value or "").strip()[:limit]


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value == value and abs(value) != float("inf"):
        return float(value)
    return None


def mixture_category_for(
    model: str,
    effort: str,
    *,
    parent_model: str = "",
    chains: dict[str, tuple[tuple[str, str], ...]] | None = None,
) -> str:
    """Project an observed child model+effort onto a mixture category label.

    ``inherit`` wins over any chain match: a child on the parent session's own
    model was not routed, whatever chain its model also appears in. Otherwise
    the first category (canonical chain order) whose head matches wins, then
    the category where the model sits earliest in its chain (a shallow
    fall-through entry is a likelier route than a deep one; canonical order
    breaks position ties); a chain entry that declares a reasoning effort
    only matches that effort.
    """
    observed_model = _unqualified_model_alias(_text(model))
    observed_effort = _text(effort, limit=40).casefold()
    if not observed_model:
        return ""
    parent_key = _unqualified_model_alias(_text(parent_model))
    if parent_key and observed_model == parent_key:
        return "inherit"

    # Some explicitly declared catalog aliases represent a model contract plus
    # a reasoning mode/service tier. Project only those rows onto the contract
    # alias before retaining the older generic speed-tier category behavior.
    # Unknown suffixes therefore do not gain an Astra contract/category merely
    # because their spelling looks similar.
    candidates = [observed_model]
    projected_model, _service_tier = _projected_model_alias(observed_model)
    if projected_model != observed_model:
        candidates.append(projected_model)
    if observed_model not in EXACT_MODEL_CONTRACT_ALIASES:
        for speed_suffix in ("-ultrafast", "-highspeed", "-fast"):
            if observed_model.endswith(speed_suffix):
                speed_base = observed_model[: -len(speed_suffix)]
                if (
                    speed_base in EXACT_MODEL_CONTRACT_ALIASES
                    or speed_base in DECLARED_MODEL_ALIAS_PROJECTIONS
                ) and observed_model not in DECLARED_MODEL_ALIAS_PROJECTIONS:
                    break
                if speed_base not in candidates:
                    candidates.append(speed_base)
                break
    active_chains = HERMES_MIXTURE_CATEGORY_CHAINS if chains is None else chains

    def _entry_matches(entry: tuple[str, str], model: str) -> bool:
        alias, chain_effort = entry
        if alias.casefold() != model:
            return False
        return not chain_effort or chain_effort.casefold() == observed_effort

    for model in candidates:
        for category, chain in active_chains.items():
            if chain and _entry_matches(chain[0], model):
                return category
        best_category = ""
        best_position = -1
        for category, chain in active_chains.items():
            for position, entry in enumerate(chain):
                if _entry_matches(entry, model):
                    if best_position < 0 or position < best_position:
                        best_category = category
                        best_position = position
                    break
        if best_category:
            return best_category
    return ""


def _read_manifests(live_root: Path, *, now: float) -> list[dict[str, Any]]:
    """Load recent delegation manifests plus each task log's mtime."""
    manifests: list[dict[str, Any]] = []
    try:
        candidates = sorted(
            (path for path in live_root.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:_ROW_LIMIT]
    except OSError:
        return []
    for directory in candidates:
        manifest_path = directory / "manifest.json"
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        started = _parse_local_timestamp(str(raw.get("started", "")))
        tasks_raw = raw.get("tasks", [])
        tasks: list[dict[str, Any]] = []
        newest_log_mtime = 0.0
        for task in tasks_raw if isinstance(tasks_raw, list) else []:
            if not isinstance(task, dict):
                continue
            log_mtime = 0.0
            log_path = _text(task.get("log", ""), limit=512)
            if log_path:
                try:
                    log_mtime = Path(log_path).stat().st_mtime
                except OSError:
                    log_mtime = 0.0
            newest_log_mtime = max(newest_log_mtime, log_mtime)
            tasks.append(
                {
                    "goal": _text(task.get("goal", ""), limit=_ACTION_LIMIT),
                    "log_mtime": log_mtime,
                }
            )
        if started and now - max(started, newest_log_mtime) > _SESSION_WINDOW_SECONDS:
            continue
        manifests.append(
            {
                "delegation_id": _text(raw.get("delegation_id", directory.name)),
                "started": started,
                "tasks": tasks,
            }
        )
    return manifests


def _parse_local_timestamp(value: str) -> float:
    # Manifest `started` is "YYYY-MM-DD HH:MM:SS" in local time (written by
    # delegation_live_log with time.strftime).
    try:
        return time.mktime(time.strptime(value.strip(), "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return 0.0


def _query_state_db(state_db: Path, *, now: float) -> dict[str, Any]:
    """Read child sessions, usage tallies, and delegation states, read-only."""
    result: dict[str, Any] = {"children": [], "delegation_states": {}, "parent_models": {}}
    try:
        connection = sqlite3.connect(
            f"file:{state_db}?mode=ro", uri=True, timeout=0.25
        )
    except sqlite3.Error:
        return result
    try:
        cursor = connection.execute(
            """
            SELECT id, model, model_config, started_at
            FROM sessions
            WHERE model_config LIKE '%_delegate_from%' AND started_at >= ?
            ORDER BY started_at DESC LIMIT 32
            """,
            (now - _SESSION_WINDOW_SECONDS,),
        )
        rows = cursor.fetchall()
        parents_needed: set[str] = set()
        children: list[dict[str, Any]] = []
        for session_id, model, model_config, started_at in rows:
            config: dict[str, Any] = {}
            try:
                parsed = json.loads(model_config or "{}")
                if isinstance(parsed, dict):
                    config = parsed
            except (ValueError, TypeError):
                config = {}
            parent_id = _text(config.get("_delegate_from", ""))
            if not parent_id:
                continue
            reasoning = config.get("reasoning_config", {})
            effort = ""
            if isinstance(reasoning, dict) and reasoning.get("enabled"):
                effort = _text(reasoning.get("effort", ""), limit=40)
            parents_needed.add(parent_id)
            children.append(
                {
                    "session_id": _text(session_id),
                    "parent_id": parent_id,
                    "model": _text(model),
                    "effort": effort,
                    "started_at": _finite(started_at) or 0.0,
                }
            )
        result["children"] = children

        for parent_id in parents_needed:
            cursor = connection.execute(
                "SELECT model FROM sessions WHERE id = ?", (parent_id,)
            )
            row = cursor.fetchone()
            if row:
                result["parent_models"][parent_id] = _text(row[0])

        if children:
            placeholders = ",".join("?" for _ in children)
            columns = {
                str(row[1])
                for row in connection.execute(
                    'PRAGMA table_info("session_model_usage")'
                ).fetchall()
            }
            cost_status = "MAX(cost_status)" if "cost_status" in columns else "NULL"
            cost_source = "MAX(cost_source)" if "cost_source" in columns else "NULL"
            cursor = connection.execute(
                f"""
                SELECT session_id, SUM(api_call_count), SUM(input_tokens),
                       SUM(output_tokens), SUM(cache_read_tokens),
                       SUM(actual_cost_usd), SUM(estimated_cost_usd),
                       {cost_status}, {cost_source},
                       MIN(first_seen), MAX(last_seen)
                FROM session_model_usage
                WHERE session_id IN ({placeholders})
                GROUP BY session_id
                """,
                tuple(child["session_id"] for child in children),
            )
            usage: dict[str, dict[str, Any]] = {}
            for row in cursor.fetchall():
                usage[str(row[0])] = {
                    "api_calls": _finite(row[1]),
                    "input_tokens": _finite(row[2]),
                    "output_tokens": _finite(row[3]),
                    "cache_read_tokens": _finite(row[4]),
                    "actual_cost_usd": _finite(row[5]),
                    "estimated_cost_usd": _finite(row[6]),
                    "cost_status": _text(row[7]) or None,
                    "cost_source": _text(row[8]) or None,
                    "first_seen": _finite(row[9]),
                    "last_seen": _finite(row[10]),
                }
            for child in children:
                child["usage"] = usage.get(child["session_id"], {})

        cursor = connection.execute(
            "SELECT delegation_id, state FROM async_delegations WHERE dispatched_at >= ?",
            (now - _SESSION_WINDOW_SECONDS,),
        )
        result["delegation_states"] = {
            str(row[0]): _text(row[1], limit=40) for row in cursor.fetchall()
        }
    except sqlite3.Error:
        # A schema Hermes has since changed, a lock we lost the race for: the
        # partial result still distinguishes "observed nothing" from success.
        pass
    finally:
        try:
            connection.close()
        except sqlite3.Error:
            pass
    return result


def _iso_utc(epoch: float) -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))
    except (ValueError, OverflowError, OSError):
        return ""


def read_hermes_native_subagents(
    hermes_home: str | Path | None = None,
    *,
    now: float | None = None,
    limit: int = _ROW_LIMIT,
    omh_home: str | Path | None = None,
) -> dict[str, Any]:
    """Project live Hermes-native delegation children into HUD activity rows."""
    current = float(now) if now is not None else time.time()
    home = Path(hermes_home).expanduser() if hermes_home else Path.home() / ".hermes"
    # Category labels honor the user's ~/.omh/routing/model-chains.json
    # overrides so a customized chain labels its children like a shipped one.
    active_chains = effective_mixture_category_chains(omh_home)
    provider_routes, _ = load_model_provider_routes(omh_home)
    price_overrides, _price_status = load_model_price_overrides(omh_home)
    route_provenance = load_delegation_route_provenance(omh_home)
    payload: dict[str, Any] = {
        "status": "idle",
        "rows": [],
        "active": 0,
        "running": 0,
        "blocked": 0,
        "completed": 0,
    }
    state = _query_state_db(home / "state.db", now=current)
    children = state.get("children", [])
    if not children:
        return payload
    manifests = _read_manifests(home / "cache" / "delegation" / "live", now=current)

    # Children of one manifest, oldest-first, pair with the manifest's tasks
    # by dispatch order; the pairing is best-effort context (goal text and
    # log mtime), never row identity — the child session id is the identity.
    matched_tasks: dict[str, dict[str, Any]] = {}
    matched_delegations: dict[str, str] = {}
    for manifest in manifests:
        window_children = sorted(
            (
                child
                for child in children
                if child["started_at"] >= manifest["started"] - 5
                and (
                    child["session_id"] not in matched_delegations
                )
            ),
            key=lambda child: child["started_at"],
        )[: len(manifest["tasks"])]
        for task, child in zip(manifest["tasks"], window_children):
            matched_tasks[child["session_id"]] = task
            matched_delegations[child["session_id"]] = manifest["delegation_id"]

    # One-shot exhaustion claims: an exhaustion record describes exactly the
    # next dispatch after its chain cleared, so only the EARLIEST inherit
    # child started after the record may carry its label (best-effort
    # pairing, never row identity — same discipline as the manifest match).
    parent_models = state.get("parent_models", {})
    exhaustion_claims: dict[int, str] = {}
    for index, record in enumerate(route_provenance):
        if record["origin"] != "exhausted_to_inherit":
            continue
        candidates = [
            child
            for child in children
            if 0.0
            <= child["started_at"] - record["written_at"]
            <= _EXHAUSTION_FRESHNESS_SECONDS
            and _child_is_inherit(child, parent_models, provider_routes)
        ]
        if candidates:
            claimed = min(candidates, key=lambda item: item["started_at"])
            exhaustion_claims[index] = claimed["session_id"]

    rows: list[dict[str, Any]] = []
    running = 0
    blocked = 0
    completed = 0
    for child in sorted(children, key=lambda item: item["started_at"], reverse=True):
        usage = child.get("usage", {})
        task = matched_tasks.get(child["session_id"], {})
        delegation_id = matched_delegations.get(child["session_id"], "")
        delegation_state = state.get("delegation_states", {}).get(delegation_id, "")
        last_activity = max(
            child["started_at"],
            usage.get("last_seen") or 0.0,
            task.get("log_mtime") or 0.0,
        )
        age = current - last_activity
        if age > COMPLETED_LINGER_SECONDS:
            continue
        if delegation_state in {"completed", "failed", "cancelled"}:
            row_state = "failed" if delegation_state == "failed" else "done"
        elif age <= RECENT_ACTIVITY_SECONDS:
            row_state = "running"
        else:
            row_state = "done"
        # A terminal child with NO recorded model usage never completed a
        # single API call, yet Hermes still marks the delegation "completed"
        # and delivers the provider error text as a normal result (observed
        # live: HTTP 400 "model is not supported when using Codex with a
        # ChatGPT account" rendering as a ✓ done row). No usage means no
        # work happened: project the row as failed, never done.
        failure_hint = ""
        if row_state == "done" and not usage:
            row_state = "failed"
            failure_hint = "no model usage observed"

        input_tokens = usage.get("input_tokens") or 0.0
        output_tokens = usage.get("output_tokens") or 0.0
        cache_read = usage.get("cache_read_tokens") or 0.0
        tokens_total = int(input_tokens + output_tokens)
        first_seen = usage.get("first_seen")
        last_seen = usage.get("last_seen")
        tokens_per_second = None
        if output_tokens and first_seen and last_seen and last_seen > first_seen:
            tokens_per_second = output_tokens / (last_seen - first_seen)
        cache_hit = None
        if cache_read and (cache_read + input_tokens) > 0:
            cache_hit = round(100.0 * cache_read / (cache_read + input_tokens), 1)
        cost_status = usage.get("cost_status")
        cost_source = usage.get("cost_source")
        # Provenance is host-vocabulary-neutral: OMH does not enumerate the
        # status strings a host may write ("included", "billed_zero", ...).
        # ANY recorded status or source vouches for the recorded figure,
        # zero included, so the split below is "some provenance" versus
        # "none" -- never a match on one host's word. Matching on a word is
        # what let a mixed group (billed $12.50 rows beside included zero
        # rows) collapse to a fake zero when MAX(cost_status) surfaced the
        # hardcoded word, and let a host's confirmed billed-zero get
        # approximated over because its status was not that word.
        cost_provenance = cost_status or cost_source
        # A positive observed aggregate always stands as recorded; only a
        # zero consults provenance at all.
        cost = usage.get("actual_cost_usd") or usage.get("estimated_cost_usd")
        # Hosts that record no per-call cost (subscription billing bills
        # nothing per call) reach here as a zero; the owner asked for an
        # approximation there rather than a blank. Token-derived, and flagged
        # approximate so the widget can render it as `~$…`.
        #
        # `session_model_usage` declares both cost columns NOT NULL DEFAULT 0,
        # so a host that billed zero and a host that recorded nothing reach
        # this line as the same 0.0 -- cost_status/cost_source are the only
        # fields that tell them apart, and they are nullable, so unlike the
        # summed costs they CAN distinguish "recorded" from "absent". The
        # approximation therefore fires only on a zero with NO provenance.
        # What must NOT happen is the third case: no recorded cost, no
        # provenance, AND no price for the model (`_approximate_cost_usd`
        # returns None for an unpriced model, and for a run with no tokens).
        # That left `cost` at 0.0 with no approximate flag, so the row
        # claimed the run was free. An unknown cost is unknown: send None and
        # let the surface say nothing rather than state a zero it cannot
        # support.
        cost_approximate = False
        # A figure derived from the operator's own rate and one derived from
        # our shipped ballpark are both approximations, but they are not
        # equally arguable: only the first is a number the operator chose.
        # The row says which, so a surface can tell them apart.
        cost_override = bool(_model_price_override_key(child["model"], price_overrides))
        if not cost and cost_provenance is None:
            approx = _approximate_cost_usd(
                child["model"], input_tokens, output_tokens, cache_read, price_overrides
            )
            if approx is not None:
                cost = approx
                cost_approximate = True
            else:
                cost = None

        parent_model = state.get("parent_models", {}).get(child["parent_id"], "")
        route_alias, route_provider = configured_route_for_wire(
            child["model"],
            provider_routes,
        )
        session_tail = child["session_id"].rsplit("_", 1)[-1][:8]
        # A finished child's elapsed is frozen at its last activity: a done
        # task should not keep aging, and a byte-stable lingering row is what
        # lets the widget skip repaints so the dock stays drag-copyable.
        elapsed_until = last_activity if row_state != "running" else current
        row: dict[str, Any] = {
            "state": row_state,
            "task_id": session_tail,
            "role": "hermes-native",
            "action": _text(task.get("goal", ""), limit=_ACTION_LIMIT),
            "alias": route_alias,
            "provider": route_provider,
            "model": child["model"],
            "effort": child["effort"],
            # A terminal row's zero is observed, not missing: the failure
            # hint above is derived from this same absence, so sending `None`
            # here made the HUD render `--` on a row the reader had just
            # labelled failed for having no usage. Only a still-running child
            # that has not reported yet is honestly unknown.
            "tokens": tokens_total if tokens_total or row_state != "running" else None,
            "elapsed_seconds": max(0.0, elapsed_until - child["started_at"]),
            "observed_at": _iso_utc(last_activity),
            "category": mixture_category_for(
                route_alias,
                child["effort"],
                parent_model=parent_model,
                chains=active_chains,
            ),
            "delegation_id": delegation_id,
        }
        if route_provider:
            row["provider_source"] = "model_provider_routes"
        # Prepared-route provenance is a best-effort label upgrade, never
        # row identity: when the child's identity matches the newest route
        # prepared before its dispatch, a fallback lane says so and an
        # exhausted chain keeps its category with an `inherit` model token
        # (`category(model inherit)`) instead of converging into plain
        # inherit. The upgrade carries its own source marker.
        provenance = _provenance_for_dispatch(
            route_provenance,
            started_at=child["started_at"],
            wire_model=child["model"],
            alias=route_alias,
            is_inherit=row["category"] == "inherit",
            session_id=child["session_id"],
            exhaustion_claims=exhaustion_claims,
        )
        if provenance is not None:
            if provenance["origin"] == "exhausted_to_inherit":
                if provenance["category"]:
                    row["route_origin"] = "exhausted_to_inherit"
                    row["route_category"] = provenance["category"]
                    row["category_source"] = "route_provenance"
            else:
                if provenance["category"]:
                    row["category"] = provenance["category"]
                    row["category_source"] = "route_provenance"
                if provenance["origin"] == "fallback":
                    row["route_origin"] = "fallback"
        if failure_hint:
            row["failure_hint"] = failure_hint
        api_calls = usage.get("api_calls")
        if api_calls is not None:
            row["turn_count"] = int(api_calls)
        if cost_status is not None:
            row["cost_status"] = cost_status
        if cost_source is not None:
            row["cost_source"] = cost_source
        if cost is not None:
            row["cost_usd"] = cost
            if cost_approximate:
                row["cost_approximate"] = True
                if cost_override:
                    row["cost_override"] = True
        if tokens_per_second is not None:
            row["tokens_per_second"] = tokens_per_second
        if cache_hit is not None:
            row["cache_hit_percentage"] = cache_hit
        rows.append(row)
        if row_state == "running":
            running += 1
        elif row_state == "failed":
            blocked += 1
        elif row_state == "done":
            completed += 1

    # The per-source bound is disclosed, not silent: the HUD merge adds this
    # to its own drop count so the widget's `+N more` line stays honest.
    payload["hidden"] = max(0, len(rows) - max(1, int(limit)))
    rows = rows[: max(1, int(limit))]
    payload["rows"] = rows
    payload["running"] = running
    payload["blocked"] = blocked
    payload["completed"] = completed
    payload["active"] = running + blocked
    payload["status"] = "observed" if rows else "idle"
    return payload
