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

from . import runtime_paths
from .live_session import conversation_segments
from .provider_detection import detect_linked_providers, env_row_is_covered
from .sqlite_readonly import connect_readonly

import json
import os
import re
import sqlite3
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterable

# Mirrors SHIPPED_MODEL_RECOMMENDATIONS["categories"] in
# src/coding/model_recommendations.py, projected to (model_alias,
# reasoning_effort) pairs in chain order. The plugin bundle ships standalone
# into $HERMES_HOME/plugins and cannot import src/coding, so the chains are
# embedded; tests/test_plugin_hermes_delegation.py holds the dict-parity gate.
# These are shipped editorial DEFAULTS: a user customizes chains without
# touching code by writing the mixture_chain_overrides/v1 document at
# ~/.omh/routing/model-chains.json (see effective_mixture_category_chains).
HERMES_MIXTURE_CATEGORY_CHAINS: dict[str, tuple[tuple[str, str], ...]] = {
    # The 2026-10-13 table (owner decision), editorial and unmeasured except
    # where a comment cites a measurement. Superseded generations leave every
    # shipped chain (owner decision, 2026-09-11): on 2026-10-13 Claude Haiku
    # 4.5 left behind Haiku 5.5, and the 2025 Qwen3-Coder left with no Qwen
    # successor. A machine whose provider still serves only an older id keeps
    # it through ~/.omh/routing/model-chains.json, not through the public
    # table.
    #
    # Claude vendor order (owner decision, 2026-10-13): Opus 5.5 before Fable
    # 5.1 inside any chain, reversing the 2026-09-06 Fable -> Opus rule.
    # Claude Mythos 5.1 is Fable 5.1 under Project Glasswing access, so no
    # shipped chain names it; it stays recognized, priced, and routable for a
    # user who asks for it by name.
    #
    # Two heads collide in `mixture_category_for`, which labels a child by the
    # first category in canonical order whose head matches (model, effort).
    # The owner accepted both (2026-10-13):
    #   (claude-opus-5-5, high)   heads deep and visual-engineering -> "deep"
    #   (claude-opus-5-5, medium) heads writing and capable         -> "writing"
    # Routing is unaffected, and so is a lane routed through
    # `omh_delegate_route`: its route-provenance record overrides the
    # projection (see the reader below), so that row keeps the lane's own
    # category. Only a child with no matching record is labelled by
    # projection.
    # Non-head entries move the same way: (claude-opus-5-5, medium) projects
    # to writing, which covers unspecified-high's second entry and the
    # last_resort head; (kimi-k3.1-pro, high) from visual-engineering and
    # artistry projects to x-search since 2026-10-28 (to deep before), where
    # it sits second; (gpt-6-luna, low) and (claude-haiku-5-5, low) reached
    # through quick project to simple-work.
    "ultrabrain": (("gpt-6-astra", "xhigh"),),
    # DeepSeek V4.1 Flash left `deep`: a Flash budget model does not fit the
    # strong tier, and Opus 5.5 and Kimi K3.1 Pro now carry its cross-ecosystem
    # fallback. visual-engineering children are labelled "deep" (above).
    "deep": (("claude-opus-5-5", "high"), ("gpt-6.1-sol", "high"), ("kimi-k3.1-pro", "high")),
    # Architecture/system-design lanes: full-depth effort across three
    # provider ecosystems. Astra at xhigh stays labeled ultrabrain (its
    # canonical head), which is the honest projection when the chain falls
    # through to it.
    "architect": (
        ("claude-opus-5-5", "xhigh"),
        ("gpt-6-astra", "xhigh"),
        ("claude-fable-5-1", "xhigh"),
        ("kimi-k3.1-pro", "xhigh"),
    ),
    # The one placement here backed by a measurement, of its predecessor: on
    # benchmarks/live-model-tools/v1 (30 evaluation tasks, 2026-09-05) OMH
    # routing passed 18/30 with gpt-5.6-sol at this head and 12/30 with
    # kimi-k3-ultrafast here (the other 24 tasks routed to the quick head in
    # both arms); Kimi passed 0/6 of the six search tasks `exhaustive_search`
    # lifts here. GPT-6.1 Sol carries the GPT slot by the superseded-generation
    # rule and is itself unmeasured on that corpus.
    "unspecified-high": (
        ("gpt-6.1-sol", "medium"),
        ("claude-opus-5-5", "medium"),
        ("kimi-k3.1-pro", "medium"),
    ),
    # A chain that would otherwise sit in one provider ecosystem ends with a
    # comparable-tier candidate from another (owner rule, 2026-08-19), so one
    # rejected ecosystem cannot exhaust the whole chain. Opus 5.5 left the
    # tail: a frontier model at the end of a cheap lane inverts cost order.
    "unspecified-low": (
        ("glm-5.3", "low"),
        ("deepseek-flash", "low"),
        ("gpt-6.1-sol", "low"),
        ("claude-sonnet-5-5", "low"),
    ),
    # Fable 5.1 left the tail for the same cost-order reason; Haiku 5.5 is
    # the Claude entry at this tier.
    "quick": (
        ("glm-5.3-flash", "low"),
        ("gpt-6-luna", "low"),
        ("claude-haiku-5-5", "low"),
        ("kimi-k3.1-pro", "low"),
    ),
    # Writing keeps the (claude-opus-5-5, medium) label: it is earlier in
    # canonical order than capable, whose head is the same pair.
    "writing": (
        ("claude-opus-5-5", "medium"),
        ("claude-sonnet-5-5", "medium"),
        ("kimi-k3.1-pro", "medium"),
        ("gemini-4-argon", "medium"),
    ),
    # Labelled "deep" by projection: its head is deep's (accepted collision).
    "visual-engineering": (
        ("claude-opus-5-5", "high"),
        ("claude-fable-5-1", "high"),
        ("gemini-4-argon", "high"),
        ("kimi-k3.1-pro", "high"),
    ),
    "artistry": (
        ("gemini-4-argon", "high"),
        ("claude-opus-5-5", "high"),
        ("claude-fable-5-1", "high"),
        ("kimi-k3.1-pro", "high"),
    ),
    # The three categories below were added on 2026-09-11 and are APPENDED
    # rather than interleaved. Position is load-bearing here: `mixture_category_for`
    # resolves a head tie and a chain-position tie in canonical order, so
    # inserting a name earlier would silently move an existing model's label.
    #
    # capable: strong general work one rung under the frontier categories,
    # crossing three provider ecosystems so the owner rule above holds.
    # Labelled "writing" by projection: its head is writing's (accepted
    # collision).
    "capable": (
        ("claude-opus-5-5", "medium"),
        ("gpt-6.1-sol", "medium"),
        ("claude-fable-5-1", "medium"),
        ("kimi-k3.1-pro", "medium"),
    ),
    # simple-work: small tasks rather than fast ones. It leads with the GPT
    # small model where quick leads with the cheapest GLM tier, so a user who
    # wants GPT behavior on a trivial task can ask for it by category. Low
    # throughout, matching quick. Note this moves two labels: ("gpt-6-luna",
    # "low") sits second in quick but head-matches simple-work (the label
    # ("gpt-5.6-luna", "low") carried before it), and ("claude-haiku-5-5",
    # "low") sits third in quick but second here, the shallower slot.
    "simple-work": (
        ("gpt-6-luna", "low"),
        ("claude-haiku-5-5", "low"),
        ("deepseek-flash", "low"),
    ),
    # deep-work: a long task at frontier depth. Effort is `max` so that its
    # label survives (owner choice, 2026-10-13): at `high` the head would be
    # deep's, and because a head match resolves in canonical order deep-work
    # would be a label nothing could ever carry. `max` is a documented rung of
    # both entries' ladders.
    "deep-work": (("claude-opus-5-5", "max"), ("gpt-6.1-sol", "max")),
    # The six routing-recipe categories (owner recipe, 2026-10-28), appended
    # after deep-work for the same tie-break reason. Heads are the owner's;
    # each tail crosses into another provider ecosystem (owner rule above).
    # They are opt-in: no role or scale names them.
    #
    # Two heads collide with an earlier category's head. The owner kept
    # both heads (2026-10-28), so the earlier category keeps the label:
    #   (gpt-6-astra, xhigh)     heads ultrabrain and forensics  -> "ultrabrain"
    #   (claude-opus-5-5, xhigh) heads architect and synthesize  -> "architect"
    # Routing is unaffected, and a lane routed through `omh_delegate_route`
    # keeps its own category through the route-provenance record; only a
    # child with no matching record is labelled by projection, so forensics
    # and synthesize are labels only a routed lane carries.
    # Six projections move (diffed over every shipped (model, effort) pair):
    # (deepseek-flash, low) unspecified-low -> swarm and (gemini-4-argon,
    # medium) writing -> google-search, because each now heads a chain;
    # (gpt-6.1-sol, xhigh) and (grok-4.7, high) had no label and now head
    # review and x-search; (kimi-k3.1-pro, high) deep -> x-search and
    # (kimi-k3.1-pro, xhigh) architect -> review, because the shallower
    # chain position wins (second in x-search against third in deep; third
    # in review against fourth in architect).
    "google-search": (
        ("gemini-4-argon", "medium"),
        ("gpt-6.1-sol", "medium"),
        ("claude-opus-5-5", "medium"),
    ),
    # Grok 4.7 is a separate entry from the x_platform_data affinity, which
    # keeps Grok Build 0.1.
    "x-search": (
        ("grok-4.7", "high"),
        ("kimi-k3.1-pro", "high"),
        ("gemini-4-argon", "high"),
    ),
    # A category, not the `review` role: the role still resolves through
    # unspecified-high/unspecified-low and never reaches this chain.
    "review": (
        ("gpt-6.1-sol", "xhigh"),
        ("claude-opus-5-5", "xhigh"),
        ("kimi-k3.1-pro", "xhigh"),
    ),
    "swarm": (
        ("deepseek-flash", "low"),
        ("glm-5.3-flash", "low"),
        ("gpt-6-luna", "low"),
    ),
    # Labelled "ultrabrain" by projection: its head is ultrabrain's.
    "forensics": (
        ("gpt-6-astra", "xhigh"),
        ("claude-opus-5-5", "xhigh"),
        ("kimi-k3.1-pro", "xhigh"),
    ),
    # Labelled "architect" by projection: its head is architect's.
    "synthesize": (
        ("claude-opus-5-5", "xhigh"),
        ("gpt-6.1-sol", "xhigh"),
        ("gemini-4-argon", "high"),
    ),
}

# User-editable chain overrides. The document replaces only the chains of the
# categories it names; the category vocabulary itself stays closed (an unknown
# category makes the document invalid). Validation is strict and atomic — an
# invalid document is ignored entirely rather than half-applied — and every
# value must be a plain identifier token so a crafted "model name" can never
# smuggle structure into config.yaml via a later omh_delegate_route write.
MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION = "mixture_chain_overrides/v1"
_CHAIN_TOKEN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._/-]|:(?=[A-Za-z0-9])){0,127}$")
# A reasoning effort is a bare word (`low`, `xhigh`); the colon admitted above
# for named provider ids (`custom:cli-proxy`) and tagged model ids has no
# meaning in an effort and would make `model:effort` text ambiguous.
_EFFORT_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


def mixture_chain_overrides_path(omh_home: str | Path | None = None) -> Path:
    root = Path(omh_home).expanduser() if omh_home else runtime_paths.default_omh_home()
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
                effort and not _EFFORT_TOKEN_RE.fullmatch(effort)
            ):
                return {}, f"invalid: category {name!r} names a non-token effort"
            chain.append((model, effort))
        overrides[name] = tuple(chain)
    return overrides, "applied"


def chains_with_overrides(
    overrides: Mapping[str, tuple[tuple[str, str], ...]],
) -> dict[str, tuple[tuple[str, str], ...]]:
    """The shipped chains with ``overrides`` replacing the categories they name.

    The one derivation of the stored chains -- what `omh model-chains set`
    wrote, before entitlement shaping -- shared by the shaped reader below,
    `omh model-chains show`, and doctor, so no surface carries its own copy
    of "override or default".
    """
    return {name: overrides.get(name, chain) for name, chain in HERMES_MIXTURE_CATEGORY_CHAINS.items()}


def effective_mixture_category_chains(
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Shipped chains with the user's per-category replacements applied.

    When this machine holds providers -- linked to Hermes, or recorded by
    the `omh setup` interview; see `effective_provider_entitlements` --
    every chain is additionally shaped so the entries no such provider can
    serve sit behind the ones one can. Shaping reorders; it never drops an
    entry, so a wrong answer costs one rejected fall-through, never a
    missing model.
    """
    overrides, _ = load_mixture_chain_overrides(omh_home)
    chains = chains_with_overrides(overrides)
    entitlements, _status, _providers = effective_provider_entitlements(omh_home, hermes_home)
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
# tests/test_provider_entitlements.py (ParityTests). Two families are retained
# past their last catalog member: `qwen-oauth`, whose only member qwen3-coder
# left every shipped chain on 2026-10-13, and `apitopia`, whose only member
# kimi-k3 left them on 2026-10-24 (nobody observed Apitopia serving K3.1
# Pro). The entitlement parser is strict and atomic, so dropping a kind would
# invalidate as a whole every providers.json that recorded it, and
# recognition-only qwen3-coder and kimi-k3 still name them; the parity gate
# lists the exceptions by name. A side effect: the setup interview offers
# every vocabulary family, so both stay selectable there although no
# shipped chain uses them.
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
    # Families are the ones observed serving each id on 2026-10-24: Moonshot's
    # own API (`kimi-coding` in Hermes) for both, OpenRouter
    # (`moonshotai/kimi-k3.1-pro`) and OpenCode Go for the base model only.
    # No family is claimed for a relay nobody observed serving it.
    "kimi-k3.1-pro": ("kimi-coding", "openrouter", "opencode"),
    "claude-opus-5-5": ("ccapi", "anthropic", "openrouter"),
    "claude-fable-5-1": ("ccapi", "anthropic", "openrouter"),
    "claude-sonnet-5-5": ("ccapi", "anthropic", "openrouter"),
    "claude-haiku-5-5": ("ccapi", "anthropic", "openrouter"),
    # Recognition-only: no shipped chain names Claude Mythos 5.1, but a user
    # who asks for it still deserves "which of my providers serves this"
    # answered rather than unknown. The parity gate lists it explicitly.
    "claude-mythos-5-1": ("ccapi", "anthropic", "openrouter"),
    # Recognition-only: no shipped chain names the Highspeed tier. Moonshot's
    # own API (`kimi-coding` in Hermes) is the one family observed serving it
    # (2026-10-24); OpenRouter and OpenCode list only the base id.
    "kimi-k3.1-pro-highspeed": ("kimi-coding",),
    # Recognition-only, retired 2026-10-24 behind kimi-k3.1-pro.
    "kimi-k3": ("apitopia", "kimi-coding", "openrouter", "opencode"),
    "gpt-6-astra": ("openai-codex", "openai"),
    "gpt-6.1-sol": ("openai-codex", "openai"),
    # Recognition-only until an owner places it (released 2026-10-26).
    # Families observed serving the exact id on 2026-10-27: the Codex
    # subscription route (a live one-shot on this maintainer host), the
    # OpenAI API catalog, and OpenRouter (`openai/gpt-6.1-terra`).
    "gpt-6.1-terra": ("openai-codex", "openai", "openrouter"),
    "gpt-6-luna": ("openai-codex", "openai"),
    "deepseek-flash": ("deepseek", "openrouter", "opencode"),
    # Recognition-only: the versioned spelling of the Flash pointer above
    # (the gateway id `deepseek/deepseek-v4.1-flash` arrives this way).
    "deepseek-v4.1-flash": ("deepseek", "openrouter", "opencode"),
    # Recognition-only, in no shipped chain (catalog sync, 2026-10-28):
    # DeepSeek's pricing page lists the served id and OpenRouter lists
    # `deepseek/deepseek-v4-pro`; no OpenCode serving was observed.
    "deepseek-v4-pro": ("deepseek", "openrouter"),
    # Recognition-only, retired generations (left the shipped chains on
    # 2026-09-11): a machine-level chain override may still name them, and
    # that operator deserves "which of my providers serves this" answered.
    "claude-fable-5": ("ccapi", "anthropic", "openrouter"),
    "deepseek-v3.2": ("deepseek", "openrouter", "opencode"),
    "glm-5.2": ("zai", "openrouter", "opencode"),
    "glm-5.2-ultrafast": ("zai", "openrouter", "opencode"),
    # Retired on 2026-09-23 under the same rule (superseded by
    # claude-opus-5-5, gpt-6-luna, and gpt-6-sol for both GPT-5.6 Sol and
    # GPT-5.6 Terra).
    "claude-opus-5": ("ccapi", "anthropic", "openrouter"),
    "gpt-5.6-luna": ("openai-codex", "openai"),
    "gpt-5.6-sol": ("openai-codex", "openai"),
    "gpt-5.6-terra": ("openai-codex", "openai"),
    "glm-5.3": ("zai", "openrouter", "opencode"),
    "glm-5.3-flash": ("zai", "openrouter", "opencode"),
    # Recognition-only, in no shipped chain (catalog sync, 2026-10-28): Z.ai's
    # pricing page lists it and OpenRouter lists `z-ai/glm-5.3-flashx`; no
    # OpenCode serving was observed.
    "glm-5.3-flashx": ("zai", "openrouter"),
    "grok-build-0.1": ("xai", "openrouter"),
    # Retired on 2026-10-01: xAI lists it as an alias of grok-build-0.1.
    "grok-code-fast": ("xai", "openrouter"),
    # Each has its own docs.x.ai model page and an OpenRouter `x-ai/<id>`
    # listing (catalog sync, 2026-10-28). Grok 4.7 heads x-search since the
    # routing recipe of the same day; the older three stay recognition-only.
    "grok-4.7": ("xai", "openrouter"),
    "grok-4.6": ("xai", "openrouter"),
    "grok-4.5": ("xai", "openrouter"),
    "grok-4.3": ("xai", "openrouter"),
    # Retired on 2026-10-01 under the same rule (superseded by gpt-6.1-sol).
    "gpt-6-sol": ("openai-codex", "openai"),
    # Gemini 4 Argon holds every former Gemini 3.1 Pro slot since 2026-10-28.
    # Google's own API serves it (`google` / `gemini` in Hermes), and
    # OpenRouter lists `google/gemini-4-argon` (catalog snapshot, 2026-10-28).
    "gemini-4-argon": ("google", "gemini", "openrouter"),
    # Retired on 2026-10-28 under the same rule (superseded by gemini-4-argon).
    "gemini-3.1-pro": ("google", "gemini", "openrouter"),
    # Recognition-only, in no shipped chain (catalog sync, 2026-10-28): the
    # Gemini API pricing page lists each id and OpenRouter lists
    # `google/<id>`. Gemini 3.7 Flash and 3.5 Flash were deprecated on
    # 2026-10-08 and route to 3.8 Flash and 3.6 Flash; they get no row.
    "gemini-3.8-flash": ("google", "gemini", "openrouter"),
    "gemini-3.6-flash": ("google", "gemini", "openrouter"),
    "gemini-3.5-flash-lite": ("google", "gemini", "openrouter"),
    # Retired on 2026-10-13 under the same rule: Claude Haiku 4.5 behind
    # claude-haiku-5-5, and the 2025 Qwen3-Coder with no Qwen successor.
    "claude-haiku-4-5": ("ccapi", "anthropic", "openrouter"),
    "qwen3-coder": ("qwen-oauth", "openrouter", "opencode"),
}

# Standalone mirror of coding.model_contracts' exact keys. Keep this separate
# from declared aliases so a newly documented child contract stops inheriting
# stale provider/category metadata until its own rows are added here.
EXACT_MODEL_CONTRACT_ALIASES: frozenset[str] = frozenset(
    {
        "gpt-6-astra", "gpt-6-sol", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-luna", "claude-opus-5-5",
        "claude-sonnet-5-5", "claude-haiku-5-5", "deepseek-v4.1-flash", "kimi-k3.1-pro",
        "kimi-k3.1-pro-highspeed", "gemini-4-argon", "jev-1.13.0",
    }
)

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
    # GPT-6.1 Sol's pro reasoning mode; no `-fast` / `-flex` row.
    "gpt-6.1-sol-pro": ("gpt-6.1-sol", "pro", "standard"),
    # GPT-6.1 Terra's pro reasoning mode, on the same terms.
    "gpt-6.1-terra-pro": ("gpt-6.1-terra", "pro", "standard"),
    # DeepSeek's first-party API names the current Flash generation
    # `deepseek-flash` (api-docs.deepseek.com, 2026-09-10); today that is
    # DeepSeek-V4.1-Flash. The pointer moves with the next Flash release, so
    # it is a declared projection with a read date, not an exact contract.
    "deepseek-flash": ("deepseek-v4.1-flash", "thinking", "standard"),
    # Claude Opus 5.5's Bedrock id (the contract's `served_ids.bedrock`) and
    # its dotted gateway spelling (OpenRouter's live listing, 2026-09-23):
    # second spellings of the same model at the contract's mode and tier.
    "anthropic.claude-opus-5-5": ("claude-opus-5-5", "thinking", "standard"),
    "claude-opus-5.5": ("claude-opus-5-5", "thinking", "standard"),
    "anthropic.claude-sonnet-5-5": ("claude-sonnet-5-5", "thinking", "standard"),
    "claude-sonnet-5.5": ("claude-sonnet-5-5", "thinking", "standard"),
    "anthropic.claude-haiku-5-5": ("claude-haiku-5-5", "thinking", "standard"),
    "claude-haiku-5.5": ("claude-haiku-5-5", "thinking", "standard"),
    # TypeSafe publishes two aliases for Jev (docs.typesafe.ai/models,
    # 2026-09-21); both point at `jev-1.13.0` today and both move on the next
    # release, so each is a declared projection with a read date.
    "jev-latest": ("jev-1.13.0", "none", "standard"),
    "jev-preview": ("jev-1.13.0", "none", "standard"),
}

# Standalone mirror of coding.model_contracts.EXACT_CONTRACT_POINTER_ALIASES:
# the declared aliases that are the same model at the contract's own mode
# and tier (a vendor's second spelling). Only these project in reverse — an
# exact id never inherits a `-pro` / `-fast` / `-flex` chain entry's label.
EXACT_CONTRACT_POINTER_ALIASES: dict[str, tuple[str, ...]] = {
    "deepseek-v4.1-flash": ("deepseek-flash",),
}


def _unqualified_model_alias(alias: object) -> str:
    key = str(alias or "").strip().casefold()
    return key.rsplit("/", 1)[-1]


# Standalone mirror of coding.model_contracts.dated_snapshot_base: a vendor's
# `<base>-YYYY-MM-DD` snapshot id (`gpt-5.6-terra-2026-07-09`) is the base
# model pinned to a release date, the same model at the same mode and tier.
# Shape only; every caller checks that the base is an alias it already knows
# (a contract, a declared row, a priced or provider-mapped alias, a chain
# entry). The parity test pins this pattern against the source copy.
_DATED_SNAPSHOT_SUFFIX = re.compile(
    r"^(?P<base>.+)-(?P<date>\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))$"
)


def _dated_snapshot_base(alias: object) -> str:
    match = _DATED_SNAPSHOT_SUFFIX.match(_unqualified_model_alias(alias))
    return match.group("base") if match else ""


def _catalog_knows_alias(alias: str) -> bool:
    """Whether the plugin's own tables describe ``alias`` (never a guess)."""
    return (
        alias in EXACT_MODEL_CONTRACT_ALIASES
        or alias in DECLARED_MODEL_ALIAS_PROJECTIONS
        or alias in HERMES_MIXTURE_ALIAS_PROVIDER_FAMILIES
        or alias in APPROX_PRICE_PER_MTOK
    )


def _projected_model_alias(alias: object) -> tuple[str, str]:
    """Return (declared base alias, service tier), without suffix guessing.

    The one shape that projects without a declared row is a dated snapshot of
    an alias the tables already describe; it inherits that base's projection.
    """
    key = _unqualified_model_alias(alias)
    if key in EXACT_MODEL_CONTRACT_ALIASES:
        return key, "standard"
    projection = DECLARED_MODEL_ALIAS_PROJECTIONS.get(key)
    if projection is not None:
        return projection[0], projection[2]
    snapshot_base = _dated_snapshot_base(key)
    if snapshot_base and _catalog_knows_alias(snapshot_base):
        return _projected_model_alias(snapshot_base)
    return key, "standard"


def is_provider_id_token(value: object) -> bool:
    """Whether ``value`` is a provider id the entitlement document accepts."""
    return isinstance(value, str) and bool(_CHAIN_TOKEN_RE.fullmatch(value))


def provider_entitlements_path(omh_home: str | Path | None = None) -> Path:
    root = Path(omh_home).expanduser() if omh_home else runtime_paths.default_omh_home()
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
    unknown = sorted(set(raw) - {"schema_version", "providers", "subscription_clis", "excluded_providers"})
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
    # Optional, written only when the operator cleared a row detection had
    # ticked: the ids here are linked to Hermes but must not count. Absent
    # from every document written before detection existed, so the
    # serialized shape of those documents is unchanged.
    excluded = raw.get("excluded_providers", [])
    if not isinstance(excluded, list):
        return None, "invalid: excluded_providers must be a list"
    normalized_excluded: list[str] = []
    for provider_id in excluded:
        if not isinstance(provider_id, str) or not _CHAIN_TOKEN_RE.fullmatch(provider_id):
            return None, f"invalid: excluded provider id {provider_id!r} is not a plain identifier"
        if provider_id in normalized_providers:
            return None, f"invalid: provider {provider_id!r} is both recorded and excluded"
        if provider_id not in normalized_excluded:
            normalized_excluded.append(provider_id)
    return {
        "providers": normalized_providers,
        "subscription_clis": normalized_clis,
        "excluded_providers": normalized_excluded,
    }, "applied"


PROVIDER_ENTITLEMENT_SOURCE_RECORDED = "recorded"
# Display order for the providers a surface lists: the operator's own word
# first, then a login, a config key, a variable name.
_PROVIDER_SOURCE_RANK: dict[str, int] = {
    PROVIDER_ENTITLEMENT_SOURCE_RECORDED: 0,
    "login": 1,
    "config": 2,
    "env": 3,
}


def effective_provider_entitlements(
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> tuple[dict[str, Any] | None, str, tuple[dict[str, str], ...]]:
    """The providers this machine holds: what Hermes is linked to, plus the record.

    Returns ``(entitlements, document_status, providers)``. ``entitlements``
    has the parsed document's shape and is ``None`` only when nothing is
    recorded AND nothing is linked, so every consumer keeps its no-shaping
    branch. ``document_status`` is `load_provider_entitlements`' own status,
    unchanged, so a surface can still say whether the operator answered.
    ``providers`` lists every provider counted, one row per id, with the
    `source` it came from (`recorded`, `login`, `config`, `env`) and the
    `evidence` (the document, a section of `auth.json`, a config key, a
    variable NAME).

    Detection (`provider_detection`) is the baseline: a provider Hermes can
    already use counts the moment it is linked, without a second interview.
    The recorded document is the operator's word on top of it -- its kind
    wins for an id both name (they said `og` is a gateway; a config key only
    guessed), its `excluded_providers` are the linked ids the operator
    cleared in the interview and are dropped from the baseline (the one way
    a linked provider stops counting short of unlinking it from Hermes),
    and it is the only source of `subscription_clis`, because nothing on
    disk says a CLI subscription is held. Beyond that neither side removes
    the other's providers: the serving rule only ever moves a served entry
    forward, so more evidence can promote, never demote.
    """
    recorded, status = load_provider_entitlements(omh_home)
    excluded = set(recorded.get("excluded_providers", [])) if recorded is not None else set()
    recorded_providers: dict[str, str] = dict(recorded["providers"]) if recorded is not None else {}
    rows: dict[str, dict[str, str]] = {
        row["id"]: {"id": row["id"], "kind": row["kind"], "source": row["source"], "evidence": row["evidence"]}
        for row in detect_linked_providers(hermes_home)
        if row["id"] not in excluded and not env_row_is_covered(row, recorded_providers)
    }
    clis: list[str] = []
    if recorded is not None:
        for provider_id, kind in recorded["providers"].items():
            rows[provider_id] = {
                "id": provider_id,
                "kind": kind,
                "source": PROVIDER_ENTITLEMENT_SOURCE_RECORDED,
                "evidence": "providers.json",
            }
        clis = list(recorded["subscription_clis"])
    if recorded is None and not rows:
        return None, status, ()
    ordered = tuple(sorted(rows.values(), key=lambda row: (_PROVIDER_SOURCE_RANK.get(row["source"], 9), row["id"])))
    entitlements = {"providers": {row["id"]: row["kind"] for row in ordered}, "subscription_clis": clis}
    return entitlements, status, ordered


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
    route_key = _route_key_for(alias, routes)
    if routes and route_key is not None:
        return routes[route_key][0] in providers
    kinds = set(str(kind) for kind in providers.values())
    if kinds & MULTI_VENDOR_PROVIDER_KINDS:
        return True
    projected_key, _tier = _projected_model_alias(_unqualified_model_alias(alias))
    families = HERMES_MIXTURE_ALIAS_PROVIDER_FAMILIES.get(projected_key)
    if families is None:
        return True
    return bool(kinds & set(families))


def _route_key_for(alias: object, routes: Mapping[str, tuple[str, str]] | None) -> str | None:
    """The key under which ``routes`` answers for ``alias``, or None.

    The one lookup the serving rule and every surface reporting on it
    share: the alias casefolded, then unqualified (`vendor/model` ->
    `model`), then verbatim. A key none of those spellings reach -- a
    capitalized or vendor-prefixed key when the chain names the plain
    alias -- is not a route for that alias, whatever it looks like.
    """
    if not routes:
        return None
    requested_key = str(alias or "").strip().casefold()
    canonical_key = _unqualified_model_alias(alias)
    for key in (requested_key, canonical_key, alias):
        if isinstance(key, str) and key in routes:
            return key
    return None


# What a route to a provider this machine does not hold does, per row of
# `routes_to_unknown_providers`: `chain` demotes an alias a chain names;
# `dispatch` reaches no chain and only ever resolves a pinned dispatch.
UNKNOWN_ROUTE_EFFECT_CHAIN = "chain"
UNKNOWN_ROUTE_EFFECT_DISPATCH = "dispatch"


def routes_to_unknown_providers(
    routes: Mapping[str, tuple[str, str]],
    entitlements: Mapping[str, Any] | None,
    chains: Mapping[str, tuple[tuple[str, str], ...]] | None = None,
) -> tuple[dict[str, str], ...]:
    """Routes naming a provider this machine does not hold, each with its effect.

    Rows are ``{"alias", "route", "provider", "effect"}``, chain rows first.
    A route decides `alias_is_served` before anything else, so one that
    names a provider neither recorded nor linked has one of two effects,
    and they are not the same sentence:

    * ``chain`` -- the route is the one the serving rule finds for an alias
      some chain names (``chains``: the effective chains; the shipped ones
      when not given), looked up exactly as the rule looks it up
      (`_route_key_for`). That alias is unserved and sorts behind the
      served entries of every chain naming it. ``alias`` is the chain's
      spelling, ``route`` the key as written.
    * ``dispatch`` -- no chain alias reaches the key, so nothing is
      reordered. The route still resolves, verbatim, when a dispatch pins
      that alias (`resolve_provider_model`), and it resolves unchecked: a
      route that names a provider skips the inheritance guard, so the
      child asks Hermes for a provider it is not linked to. ``alias`` is
      the key itself.

    Empty when nothing is recorded or linked: with no providers to judge
    against every alias counts as served and every route is left alone.
    """
    providers = (entitlements or {}).get("providers", {})
    if not isinstance(providers, Mapping) or not providers:
        return ()
    effective_chains = chains if chains is not None else HERMES_MIXTURE_CATEGORY_CHAINS
    chain_aliases = sorted({model for chain in effective_chains.values() for model, _effort in chain})
    reached: dict[str, list[str]] = {}
    for alias in chain_aliases:
        key = _route_key_for(alias, routes)
        if key is not None:
            reached.setdefault(key, []).append(alias)
    rows: list[dict[str, str]] = []
    for key, (provider, _model) in routes.items():
        if provider in providers:
            continue
        for alias in reached.get(key, []):
            rows.append({"alias": alias, "route": key, "provider": provider, "effect": UNKNOWN_ROUTE_EFFECT_CHAIN})
        if key not in reached:
            rows.append({"alias": key, "route": key, "provider": provider, "effect": UNKNOWN_ROUTE_EFFECT_DISPATCH})
    return tuple(
        sorted(rows, key=lambda row: (row["effect"] != UNKNOWN_ROUTE_EFFECT_CHAIN, row["alias"], row["route"]))
    )


# How many unknown-provider routes a doctor or show line names before
# folding the rest into "… and K more": thirty stale gateway routes are one
# finding, not thirty lines.
UNKNOWN_ROUTE_NAMED_LIMIT = 5


def split_unknown_routes(
    rows: Iterable[Mapping[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """``(chain rows, dispatch rows)`` of `routes_to_unknown_providers`.

    Both effects are matched by equality; a row carrying any other value
    raises rather than falling into the dispatch sentence, so a new effect
    has to be given its own wording before a surface can print it.
    """
    chain_rows: list[dict[str, str]] = []
    dispatch_rows: list[dict[str, str]] = []
    for row in rows:
        effect = row.get("effect")
        if effect == UNKNOWN_ROUTE_EFFECT_CHAIN:
            chain_rows.append(dict(row))
        elif effect == UNKNOWN_ROUTE_EFFECT_DISPATCH:
            dispatch_rows.append(dict(row))
        else:
            raise ValueError(f"unknown route effect {effect!r}")
    return chain_rows, dispatch_rows


def unknown_route_label(row: Mapping[str, str]) -> str:
    """``<route key> -> <provider>``, plus the chain's spelling when it differs.

    The key is what the operator's document contains and what a repair
    edits, so it is always named; the chain alias is the entry that moves,
    named only when the chain spells it differently (`zai/glm-5.3` reached
    by the key `glm-5.3`), or the repair would hunt for a key that is not
    there.
    """
    route = str(row.get("route") or row.get("alias") or "")
    alias = str(row.get("alias") or "")
    if alias and alias != route:
        return f"{route} (chain alias {alias}) -> {row['provider']}"
    return f"{route} -> {row['provider']}"


def unknown_route_labels(rows: Iterable[Mapping[str, str]], limit: int = UNKNOWN_ROUTE_NAMED_LIMIT) -> str:
    """Up to ``limit`` route labels, comma-joined, then ``… and K more``."""
    labels = [unknown_route_label(row) for row in rows]
    if len(labels) <= limit:
        return ", ".join(labels)
    return ", ".join(labels[:limit]) + f" … and {len(labels) - limit} more"


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
        # Hermes names a `providers.<name>` block `custom:<name>` at runtime
        # (`model.provider: custom:cliproxy`), while detection and the setup
        # interview record the bare block name. Both spellings are one
        # provider, so each is looked up under the other too; without this a
        # session on `custom:<name>` read as a provider nothing records.
        for spelling in _provider_id_spellings(key):
            recorded = providers.get(spelling)
            if isinstance(recorded, str) and recorded:
                return recorded
    return key if key in PROVIDER_FAMILY_VOCABULARY else ""


def _provider_id_spellings(provider_id: str) -> tuple[str, ...]:
    """``provider_id`` first, then its other `custom:` spelling, if it has one."""
    if provider_id.startswith("custom:") and len(provider_id) > len("custom:"):
        return (provider_id, provider_id[len("custom:"):])
    if provider_id and ":" not in provider_id:
        return (provider_id, f"custom:{provider_id}")
    return (provider_id,)


def provider_block_name(provider_id: str) -> str:
    """The `providers.<name>` key a provider id runs from: `custom:<name>` -> `<name>`."""
    key = str(provider_id or "").strip()
    return key[len("custom:"):] if key.startswith("custom:") else key


def providers_known_to_serve_alias(
    alias: str,
    entitlements: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """The operator's provider ids whose vendor family the catalog says serves ``alias``.

    Narrower than `providers_serving_alias`: a multi-vendor relay is left
    out, because "a relay serves everything" is a fail-open default, not
    evidence. This is the set a route may pin on its own when the provider a
    child would inherit cannot serve the model -- a known server, never a
    guess.
    """
    providers = (entitlements or {}).get("providers", {})
    if not isinstance(providers, Mapping):
        return ()
    projected_key, _tier = _projected_model_alias(alias)
    families = HERMES_MIXTURE_ALIAS_PROVIDER_FAMILIES.get(projected_key)
    if not families:
        return ()
    return tuple(
        sorted(
            provider_id
            for provider_id, kind in providers.items()
            if isinstance(provider_id, str)
            and isinstance(kind, str)
            and kind not in MULTI_VENDOR_PROVIDER_KINDS
            and kind in families
        )
    )


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
    root = Path(omh_home).expanduser() if omh_home else runtime_paths.default_omh_home()
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
# route, an exhausted chain as `category(model inherit)`, and a lane routed
# to the model the parent session itself runs as that lane's own category
# — the category names the lane and never changes — instead of plain
# inherit. The record is preparation evidence only: a label upgrade for an
# observed child whose wire identity matches, never execution evidence and
# never a routing input.
#
# Each record also names the session that prepared the route, so a
# session-scoped reader can keep its own conversation's records instead of
# discarding the history whole. It stays a route record: identity, model,
# category, timestamp and owner — never anything about what was said.
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
    root = Path(omh_home).expanduser() if omh_home else runtime_paths.default_omh_home()
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
    # `identity`/`identity_digest` name the `omh_identity_profiles/v1` profile
    # and identities.json digest a route was prepared under — additive-optional
    # like `session_id`: old records carry neither, and a reader that predates
    # the fields keeps only the bounded strings it knows. `identity_digest`
    # never holds prompt text; it is the document's own sha256 prefix.
    for field in ("identity", "identity_digest"):
        value = record.get(field, "")
        if not isinstance(value, str) or len(value) > 160:
            return None
        if value:
            cleaned[field] = value
    # `session_id` names the Hermes session that prepared this route, and is
    # additive-optional inside `delegation_route_provenance/v1`: the key is
    # kept only when non-empty, so a writer that cannot name its session
    # produces exactly the record this function produced before the field
    # existed. A malformed owner refuses the record the same way every other
    # malformed field does, which the loader turns into "no provenance".
    owner = record.get("session_id", "")
    if not isinstance(owner, str) or len(owner) > 160:
        return None
    if owner:
        cleaned["session_id"] = owner
    return cleaned


def load_delegation_route_provenance(
    omh_home: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Read prepared-route records, oldest first; absent or invalid is empty.

    Provenance upgrades a HUD label, and it also gates two routing answers:
    `fallback` takes a conversation's chain position and category from it
    (`delegate_route_tool._fallback_position`), and the leftover check asks it
    whether the keys in the file are OMH's
    (`delegation_route_restore.leftover_verdict`). Every failure mode reads as
    "no provenance" rather than an error, and both answers then take the safe
    side: a fallback has no position, and the keys in the file are kept as
    the person's (`person_provenance_unavailable`).
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
    """Mirror the projection's inherit test: child alias == parent model.

    The projection routes the model it resolved, so this reads the same
    resolved model; testing the raw `sessions.model` made the two disagree
    on a child whose model is only recorded in its usage rows.
    """
    parent_model = _text(parent_models.get(child.get("parent_id", ""), ""))
    if not parent_model:
        return False
    alias, _ = configured_route_for_wire(_observed_wire_model(child), provider_routes)
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
        # A child on the parent session's own model may still have been
        # ROUTED there: the owner's `deep` chain heads on the model the
        # session itself runs, so every deep lane looked unrouted and the
        # category the tool prepared was thrown away. The chain projection
        # alone still says inherit (it cannot tell the two apart); a fresh
        # record whose identity matches is what tells them apart, and the
        # caller keeps the lane's category on the row. It also marks the row
        # `same_as_parent` for the payload; the TUI renders no token for it.
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
    # OpenAI published price (developers.openai.com/api/docs/models/gpt-5.6-sol
    # and /api/docs/pricing, read 2026-09-23): 4/20, cached input 0.40. The
    # page labels it promotional, "available at least through November 21,
    # 2026", and names no later price; re-read the page after that date. The
    # earlier 1.25/10 matched neither page. The id left the shipped chains
    # on 2026-09-23 and stays priced for overrides.
    "gpt-5.6-sol": (4.0, 20.0),
    # OpenAI list price (developers.openai.com/api/docs/models/gpt-6-astra,
    # 2026-09): 10/50; cached input 1 (the default tenth). The $12.5 cache
    # write and the 2x/1.5x multiplier above 272K input have no column in
    # this table and stay documented in `src/coding/model_contracts.py`.
    "gpt-6-astra": (10.0, 50.0),
    # OpenAI list price (developers.openai.com/api/docs/models/gpt-5.6-terra,
    # read 2026-09-23): 2/12, cached input 0.20. The earlier 1.25/10 did not
    # match the page. The id left the shipped chains on 2026-09-23 and stays
    # priced for overrides.
    "gpt-5.6-terra": (2.0, 12.0),
    # OpenAI list price (developers.openai.com/api/docs/models/gpt-5.6-luna,
    # 2026-09): 0.20/1.20. The earlier 0.25/2.0 did not match the page. The
    # id left the shipped chains on 2026-09-23 and stays priced for overrides.
    "gpt-5.6-luna": (0.20, 1.20),
    # OpenAI list price (developers.openai.com/api/docs/models/gpt-6-luna and
    # openai.com/api/pricing, 2026-09): 0.10/0.50; cached input 0.01 (the
    # default tenth). Cache write, long-context, and service-tier rates stay
    # documented in `src/coding/model_contracts.py`.
    "gpt-6-luna": (0.10, 0.50),
    # OpenAI list price (developers.openai.com/api/docs/models/gpt-6-sol and
    # /api/docs/pricing, read 2026-09-23): 2/10, no promotion mark; cached
    # input 0.20 (the default tenth). Cache write, long-context, and
    # service-tier rates stay documented in `src/coding/model_contracts.py`.
    # The id left the shipped chains on 2026-10-01 and stays priced for
    # overrides.
    "gpt-6-sol": (2.0, 10.0),
    # OpenAI list price (developers.openai.com/api/docs/models/gpt-6.1-sol and
    # /api/docs/pricing, read 2026-10-01): 2/10, no promotion mark; cached
    # input 0.10 is 5% of input, not the default tenth (APPROX_CACHE_READ_RATIO).
    # Cache write, long-context, and service-tier rates stay documented in
    # `src/coding/model_contracts.py`. `gpt-6.1-sol-pro` has no row: it
    # inherits this one through its declared projection (pro mode bills at
    # the selected model's standard rates).
    "gpt-6.1-sol": (2.0, 10.0),
    # OpenAI list price (developers.openai.com/api/docs/models/gpt-6.1-terra
    # and /api/docs/pricing, read 2026-10-27): 1/5, no promotion mark; cached
    # input 0.05 is 5% of input (APPROX_CACHE_READ_RATIO). Cache write,
    # long-context, and service-tier rates stay documented in
    # `src/coding/model_contracts.py`. GPT-5.6 Terra keeps its own 2/12 row.
    "gpt-6.1-terra": (1.0, 5.0),
    # Anthropic first-party list prices (docs.claude.com pricing, 2026-09):
    # Opus 5 5/25, Sonnet 5 2/10, Fable 5 and 5.1 10/50; Mythos 5.1 shares
    # Fable 5.1's per-token price. Earlier entries here were stale.
    "claude-opus-5": (5.0, 25.0),
    # Anthropic list price (platform.claude.com pricing, 2026-09): Opus 5.5
    # 4/20; cache read 0.05x input (APPROX_CACHE_READ_RATIO below). Cache
    # write, Batch, and fast-mode rates stay in `model_contracts.py`.
    "claude-opus-5-5": (4.0, 20.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-fable-5-1": (10.0, 50.0),
    "claude-mythos-5-1": (10.0, 50.0),
    "claude-sonnet-5": (2.0, 10.0),
    # Anthropic list price (platform.claude.com pricing, read 2026-10-01):
    # Sonnet 5.5 2/10. The same page says Sonnet 5's 2/10 launch price is now
    # its standard price and the scheduled move to 3/15 will not occur, so the
    # row above stands. Cache read is 0.10, 0.05x input rather than the default
    # tenth (APPROX_CACHE_READ_RATIO): Anthropic lowered it from 0.20 on
    # 2026-10-07 (the Haiku 5.5 launch post and the pricing page, read
    # 2026-10-13).
    "claude-sonnet-5-5": (2.0, 10.0),
    # Anthropic list price (platform.claude.com pricing, read 2026-10-13):
    # Haiku 5.5 0.10/0.50 for a prompt up to 100,000 tokens, cache read 0.01
    # (the default tenth). A longer prompt is billed 0.50/2.50 on its own
    # card; like the Gemini 3.1 Pro and Grok Build 0.1 rows, this table
    # carries the lower card, so a run with prompts over 100K is
    # under-reported fivefold. The higher card stays in `model_contracts.py`.
    "claude-haiku-5-5": (0.10, 0.50),
    # Anthropic list price (platform.claude.com pricing, read 2026-10-13):
    # 1/5 at any prompt length. The id left the shipped chains on 2026-10-13
    # and stays priced for overrides.
    "claude-haiku-4-5": (1.0, 5.0),
    # Moonshot AI list price (platform.kimi.ai/docs/pricing/chat, read
    # 2026-10-01, re-read 2026-10-24): 3/15, cache-hit input 0.30 (the
    # default tenth). The earlier 0.6/2.5 was the K2-era rate and
    # under-reported K3 input fivefold and output sixfold. Cache write (3.00
    # at a 5-minute TTL, 6.00 at 1 hour, the same page) has no column here.
    "kimi-k3": (3.0, 15.0),
    # Moonshot AI list price (platform.kimi.ai/docs/pricing/chat, read
    # 2026-10-24): K3.1 Pro 2/10 with cached input 0.20 (the default tenth);
    # Highspeed has its own card, 4/20 with cached input still 0.20 (the 0.05
    # ratio below). Cache writes (2.00/4.00 and 4.00/8.00 at 5 minutes / 1
    # hour) stay on the contracts.
    "kimi-k3.1-pro": (2.0, 10.0),
    "kimi-k3.1-pro-highspeed": (4.0, 20.0),
    # Z.ai list price (docs.z.ai/guides/overview/pricing, read 2026-10-28):
    # GLM-5.2 1.4/4.4, cached input 0.26 (APPROX_CACHE_READ_RATIO). The
    # earlier 0.6/2.2 was the GLM-4.7/4.6/4.5 rate on the same page and
    # under-reported GLM-5.2 input 2.3x and output 2x.
    "glm-5.2": (1.4, 4.4),
    # Z.ai list price for the 5.3 generation (docs.z.ai pricing, 2026-08).
    # 5.3 always reasons and bills the reasoning inside output tokens, so the
    # output side dominates real spend; still an approximation, not billing.
    "glm-5.3": (1.4, 4.4),
    "glm-5.3-flash": (0.15, 0.5),
    # Z.ai list price (docs.z.ai/guides/overview/pricing, read 2026-10-28):
    # GLM-5.3-FlashX 0.37/1.25, cached input 0.075 (APPROX_CACHE_READ_RATIO).
    # The id is listed on the glm-5.3-flash model page (it has no page of its
    # own): 1M context, 128K output, thinking `enabled` only. Recognition-only,
    # in no shipped chain.
    "glm-5.3-flashx": (0.37, 1.25),
    # Z.ai publishes no separate rate for the 5.3-generation Ultrafast serving
    # (observed 2026-09-24), so this row carries the generation's own
    # documented list price (docs.z.ai pricing, 2026-08) rather than the
    # halved ballpark the older speed tiers use: a run on the tier reports the
    # base model's rate instead of a discount nobody published, and instead of
    # no cost at all. Approximate and editable, not billing evidence.
    #
    # The tier deliberately has no provider-family row either (same as
    # `kimi-k3-ultrafast`): it was observed on a gateway, and OpenRouter's own
    # catalog serves no `-ultrafast` id at all, so naming a family here would
    # claim a serving path nobody observed. Absent means "served by every
    # provider", the honest default for an id the catalog has not described.
    "glm-5.3-ultrafast": (1.4, 4.4),
    # DeepSeek publishes no separate rate for the OpenGateway Ultrafast serving
    # of V4.1 Flash either (observed 2026-09-24), so this row mirrors the
    # contract's documented peak list price (api-docs.deepseek.com pricing,
    # 2026-09) and the cache-hit ratio below: the tier reports the model's
    # published rate rather than no cost at all. It is deliberately NOT a
    # declared contract row -- a different serving tier is not the contract's
    # second spelling, so the exact id keeps its own label and this row owns
    # the rate -- and, like the GLM tier above, it gets no provider-family row:
    # the tier was observed on a gateway and no vendor catalog lists it.
    "deepseek-v4.1-flash-ultrafast": (0.30, 1.20),
    # DeepSeek list price (api-docs.deepseek.com/quick_start/pricing, 2026-09,
    # re-read 2026-10-28): peak-hour cache-miss input 0.30 / output 1.20;
    # cache-hit input 0.006 (the 0.02 ratio below); every rate halves
    # off-peak. Peak is 01:00-04:00 and 06:00-10:00 UTC, Monday-Friday,
    # excluding Chinese public holidays; every other hour, weekends, and
    # those holidays are off-peak. Peak is the honest approximation because a
    # fanout wave has no off-peak guarantee. Since 2026-10-17 the
    # `deepseek-flash` pointer serves DeepSeek-V4.1-Flash-1017 at unchanged
    # prices.
    "deepseek-v4.1-flash": (0.30, 1.20),
    # DeepSeek list price (api-docs.deepseek.com/quick_start/pricing, read
    # 2026-10-28): peak cache-miss input 1.32 / output 3.96, cache-hit input
    # 0.044 (APPROX_CACHE_READ_RATIO); every rate halves off-peak under the
    # V4.1 Flash rule above. The served id carries no `-0813` suffix: that is
    # the version name (DeepSeek-V4-Pro-0813, GA 2026-08-13). 1M context and
    # 384K output (the page's shared limits cell); effort `low`/`high`/`max`
    # (default `high`) with V4.1 Flash's mapping. No V4.1 Pro exists.
    # Recognition-only, in no shipped chain.
    "deepseek-v4-pro": (1.32, 3.96),
    # DeepSeek list price (api-docs.deepseek.com pricing, 2026-08); the id
    # left the shipped chains on 2026-09-11 but a machine-level override may
    # still route it, so the row stays.
    "deepseek-v3.2": (0.28, 0.42),
    # Z.ai publishes no separate rate for the GLM-5.2 Ultrafast serving, so
    # this row carries the base model's documented list price
    # (docs.z.ai/guides/overview/pricing, read 2026-10-28) -- the
    # `glm-5.3-ultrafast` shape. It moved on 2026-10-28 from a halved
    # ballpark (0.3/1.2) of the stale 0.6/2.2 base, together with the
    # corrected base row, as `kimi-k3-ultrafast` did on 2026-10-01.
    "glm-5.2-ultrafast": (1.4, 4.4),
    # The Ultrafast serving of K3 (a gateway tier, not a Moonshot product)
    # publishes no tier rate, so
    # this row carries the base model's documented list price
    # (platform.kimi.ai/docs/pricing/chat, read 2026-10-01) -- the
    # `glm-5.3-ultrafast` shape -- instead of the halved ballpark it carried
    # before, which halved a base rate that was itself stale.
    "kimi-k3-ultrafast": (3.0, 15.0),
    # Google list price (ai.google.dev/gemini-api/docs/pricing, read
    # 2026-10-01): Gemini 3.1 Pro Preview 2/12 up to 200K prompt tokens, 4/18
    # above. The earlier 1.25/10 was Gemini 2.5 Pro's rate on the same page.
    # The id left the shipped chains on 2026-10-28 and stays priced for
    # overrides.
    "gemini-3.1-pro": (2.0, 12.0),
    # Google list price (ai.google.dev/gemini-api/docs/pricing, read
    # 2026-10-28), Standard paid tier, no prompt-size tier: Gemini 4 Argon
    # 2/10 through 2026-11-30, cached input 0.10 (APPROX_CACHE_READ_RATIO).
    # From 2026-12-01 the card is 4/20 (cache 0.20, the same 0.05 ratio), so
    # re-read the page after that date. Batch is half. GA 2026-10-13;
    # 1,048,576-token unified context, 65,536 output per synchronous request.
    # Thinking `low`/`medium`/`high` (default `medium`), never off.
    "gemini-4-argon": (2.0, 10.0),
    # Google list price (ai.google.dev/gemini-api/docs/pricing, read
    # 2026-10-28), paid tier, no prompt-size tier: Gemini 3.8 Flash and 3.6
    # Flash 0.75/3.75, cached input 0.075 (the default tenth). Both are an
    # introductory price through 2026-12-31; from 2027-01-01 they are
    # 1.50/7.50 (cache 0.15), so re-read the page after that date. 3.8 Flash
    # went GA 2026-09-02 and 3.6 Flash 2026-07-21; both take 1,048,576 input
    # and 65,536 output tokens. Thinking levels: 3.8 Flash `low`/`medium`/
    # `high` (default `medium`, `minimal` errors), 3.6 Flash `minimal` to
    # `high` (default `medium`). Gemini 3.7 Flash and 3.5 Flash were
    # deprecated on 2026-10-08 and route to 3.8 Flash and 3.6 Flash; neither
    # has a price on the page, so neither has a row. Recognition-only, in no
    # shipped chain.
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    # Google list price (the same page, read 2026-10-28): Gemini 3.5
    # Flash-Lite 0.30/2.50, cached input 0.03 (the default tenth), no
    # introductory mark. GA 2026-07-21; thinking `minimal` to `high`, default
    # `minimal`. Recognition-only, in no shipped chain.
    "gemini-3.5-flash-lite": (0.30, 2.50),
    # Alibaba Cloud Model Studio list price (alibabacloud.com pricing, 2026-08).
    # The id left the shipped chains on 2026-10-13 and stays priced for
    # overrides.
    "qwen3-coder": (0.4, 1.6),
    # Alibaba Cloud Model Studio list price
    # (alibabacloud.com/help/en/model-studio/model-pricing, Singapore region,
    # read 2026-10-28): Qwen3.8-Max 2/6 and Qwen3.8-Flash 0.15/0.47, one tier
    # up to 1M input tokens. The page publishes no per-model cache-hit rate,
    # so the default tenth applies and is unverified; Alibaba's general
    # context-cache rule bills an explicit hit at 10% of input and an
    # implicit hit at 20%, so the tenth may under-report implicit hits.
    # China and global deployments bill 1.65/4.951 (Max) and 0.113/0.382
    # (Flash). Alibaba also serves the snapshot `qwen3.8-max-0902` (MMDD),
    # which this row does not cover: only `-YYYY-MM-DD` snapshots project
    # onto a base. No provider row: the vocabulary holds no first-party
    # family observed serving either id (`qwen-oauth`'s served list is
    # undocumented). OpenRouter lists `qwen/qwen3.8-flash`, but a relay-only
    # row would claim that every first-party provider does not serve it.
    # Recognition-only, in no shipped chain.
    "qwen3.8-max": (2.0, 6.0),
    "qwen3.8-flash": (0.15, 0.47),
    # Upstage list price (upstage.ai pricing, 2026-08): every Solar Pro 2
    # version reaches end of service on 2026-10-30 KST, and Upstage
    # recommends Solar Pro 4 (upstage.ai/pricing and
    # console.upstage.ai/docs/models/solar-pro-2, read 2026-10-28). The row
    # stays because a machine-level override may still name the id.
    "solar-pro2": (0.15, 0.60),
    # Upstage list price (upstage.ai/pricing and
    # console.upstage.ai/docs/models/solar-pro-4, read 2026-10-28): 0.30/1.20,
    # cached input 0.06 (APPROX_CACHE_READ_RATIO), excluding VAT. The pricing
    # page also shows a time-limited promotional rate; this is the standard
    # one. `solar-pro4` is the served alias of `solar-pro4-260806`; 512K
    # context, 128K output. No provider row: the vocabulary has no Upstage
    # family (the `solar-pro2` precedent). OpenRouter lists
    # `upstage/solar-pro4`, but a relay-only row would claim that every
    # first-party provider does not serve it. Recognition-only, in no shipped
    # chain.
    "solar-pro4": (0.30, 1.20),
    # MiniMax list price (platform.minimax.io/docs/guides/pricing-paygo, read
    # 2026-10-28), standard tier: MiniMax-M3 0.30/1.20 with cache read 0.06
    # (APPROX_CACHE_READ_RATIO) up to 512K input tokens; above that the card
    # is 0.60/2.40 (cache 0.12), and the priority tier bills 1.5x. Like the
    # Gemini 3.1 Pro row, this table carries the lower card. MiniMax-M3.1-Flash
    # (released 2026-10-19, platform.minimax.io/docs/release-notes/models) is
    # 0.15/0.60, cache read 0.015 (the default tenth), one tier; reasoning is
    # always on, effort `low` to `max` (default `max`), and `none` is a 400.
    # The vendor serves them as `MiniMax-M3` and `MiniMax-M3.1-Flash`; cost
    # lookup casefolds the id first, so the lower-case keys match. No provider
    # row: the vocabulary has no MiniMax family. OpenRouter lists both ids,
    # but a relay-only row would claim that every first-party provider does
    # not serve them. Recognition-only, in no shipped chain.
    "minimax-m3": (0.30, 1.20),
    "minimax-m3.1-flash": (0.15, 0.60),
    # xAI list price (docs.x.ai/developers/models/grok-build-0.1, read
    # 2026-10-01): 1/2 below 200K prompt tokens, 2/4 at or above; cached input
    # 0.20, a fifth of input (APPROX_CACHE_READ_RATIO below). The page's
    # alias list is `grok-code-fast-1`, `grok-code-fast`, and
    # `grok-code-fast-1-0825`; xAI retired Grok Code Fast on 2026-05-15, so
    # a run on the old spelling against xAI's API is billed at this rate and
    # its earlier 0.2/1.5 (the retired model's) under-reported it. Other
    # routes may map the old id elsewhere: the Hermes retirement map sends
    # `grok-code-fast-1` to `grok-4.3` (observed in the Hermes source).
    "grok-build-0.1": (1.0, 2.0),
    "grok-code-fast": (1.0, 2.0),
    # xAI list price (docs.x.ai/developers/models/grok-4.7, /grok-4.6,
    # /grok-4.5, and /grok-4.3, read 2026-10-28), below 200K prompt tokens.
    # A request whose prompt reaches 200K is billed at the higher card for
    # ALL its tokens, not only the excess: Grok 4.7/4.6/4.5 4/12, Grok 4.3
    # 2.50/5.00. This table carries the lower card, so a long-prompt run is
    # under-reported twofold. Cached input (APPROX_CACHE_READ_RATIO): 0.50 on
    # 4.7 and 4.6, 0.30 on 4.5, 0.20 on 4.3 (doubled above 200K). Context
    # 500K (1M on 4.3). Effort: 4.7 and 4.6 `low`/`medium`/`high` (default)/
    # `xhigh`; 4.5's model page lists the same, but its July release note
    # says no `xhigh`; 4.3 `none`/`low` (default)/`medium`/`high`/`xhigh`.
    # Release notes date 4.7 to September, 4.6 to August, and 4.5 to July
    # 2026 (month only). Aliases: `grok-4.5-latest` and `grok-build-latest`
    # for 4.5, `grok-4.3-latest` for 4.3 (see the Grok Build 0.1 row for the
    # Hermes retirement map). Recognition-only, in no shipped chain.
    "grok-4.7": (2.0, 6.0),
    "grok-4.6": (2.0, 6.0),
    "grok-4.5": (2.0, 6.0),
    "grok-4.3": (1.25, 2.50),
    # TypeSafe list price (docs.typesafe.ai/models, 2026-09): input $0.042
    # per Mtok, output free. The zero is the published rate, not a missing
    # one -- this model is never a chain member, but a machine-level override
    # can still name it and a run on it must not report no cost at all.
    "jev-1.13.0": (0.042, 0.0),
}


# Cache-read price as a fraction of input price, per model, where the vendor
# documents a rate other than the tenth above. Fable 5.1 lists cache reads at
# $0.25/MTok against $10 input (docs.claude.com pricing, 2026-09); Mythos 5.1
# shares Fable 5.1's per-token price and its cache-read rate was open at
# launch, so its entry is the Fable figure, still an approximation.
APPROX_CACHE_READ_RATIO: dict[str, float] = {
    # Opus 5.5 cache read is "0.05x the base input price" (platform.claude.com
    # pricing, 2026-09). Sonnet 5.5 joined it on 2026-10-07, when Anthropic
    # lowered its cache reads from $0.20 to $0.10 (the Haiku 5.5 launch post
    # and the pricing page, read 2026-10-13).
    "claude-opus-5-5": 0.05,
    "claude-sonnet-5-5": 0.05,
    "claude-fable-5-1": 0.025,
    "claude-mythos-5-1": 0.025,
    # DeepSeek V4.1 Flash cache hit 0.006 vs cache miss 0.30 per MTok input
    # (api-docs.deepseek.com/quick_start/pricing, 2026-09); the Ultrafast
    # serving of the same model carries the same cache-hit ratio, or a run on
    # the tier would price cached input at the generic tenth.
    "deepseek-v4.1-flash": 0.02,
    "deepseek-v4.1-flash-ultrafast": 0.02,
    # DeepSeek V4 Pro cache hit 0.044 vs cache miss 1.32 per MTok input
    # (api-docs.deepseek.com/quick_start/pricing, read 2026-10-28).
    "deepseek-v4-pro": 0.0333,
    # Gemini 4 Argon cached input 0.10 against 2.00 input through 2026-11-30,
    # and 0.20 against 4.00 from 2026-12-01 (ai.google.dev/gemini-api/docs/
    # pricing, read 2026-10-28).
    "gemini-4-argon": 0.05,
    # Kimi K3.1 Pro Highspeed cached input 0.20 against 4.00 input
    # (platform.kimi.ai/docs/pricing/chat, read 2026-10-24); the base model's
    # 0.20 against 2.00 is the default tenth and needs no row.
    "kimi-k3.1-pro-highspeed": 0.05,
    # Grok Build 0.1 cached input 0.20 against 1.00 input below 200K, and
    # 0.40 against 2.00 above (docs.x.ai/developers/models/grok-build-0.1,
    # read 2026-10-01); the retired alias bills at the same rate.
    "grok-build-0.1": 0.2,
    "grok-code-fast": 0.2,
    # Grok 4.7 and 4.6 cached input 0.50, Grok 4.5 0.30, against 2.00 input;
    # Grok 4.3 0.20 against 1.25 (docs.x.ai/developers/models/<id>, read
    # 2026-10-28). The ratio holds on the card above 200K too.
    "grok-4.7": 0.25,
    "grok-4.6": 0.25,
    "grok-4.5": 0.15,
    "grok-4.3": 0.16,
    # Z.ai lists GLM-5.3 cached input at $0.26 against $1.4 input, and
    # GLM-5.3-Flash cached input at $0.03 against $0.15 input (docs.z.ai
    # pricing, read 2026-09-24). The Ultrafast serving of GLM-5.3 carries the
    # same ratio as the base generation -- same reasoning as the DeepSeek row
    # above, or a run on the tier would price cached input at the generic
    # tenth.
    "glm-5.3": 0.186,
    "glm-5.3-flash": 0.2,
    "glm-5.3-ultrafast": 0.186,
    # The same page, read 2026-10-28: GLM-5.2 cached input $0.26 against $1.4
    # (its Ultrafast serving carries the base ratio, as above), and
    # GLM-5.3-FlashX $0.075 against $0.37.
    "glm-5.2": 0.186,
    "glm-5.2-ultrafast": 0.186,
    "glm-5.3-flashx": 0.203,
    # Solar Pro 4 cached input 0.06 against 0.30 (upstage.ai/pricing, read
    # 2026-10-28), and MiniMax-M3 cache read 0.06 against 0.30 on both of its
    # cards (platform.minimax.io/docs/guides/pricing-paygo, read 2026-10-28).
    "solar-pro4": 0.2,
    "minimax-m3": 0.2,
    # GPT-6.1 Sol: "Cached input tokens are priced at 5% of the uncached input
    # token rate" (developers.openai.com model page, read 2026-10-01).
    "gpt-6.1-sol": 0.05,
    # GPT-6.1 Terra: the same 5% wording on its model page (read 2026-10-27).
    "gpt-6.1-terra": 0.05,
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
    root = Path(omh_home).expanduser() if omh_home else runtime_paths.default_omh_home()
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
# How many delegate children one state.db read selects, newest first.
_CHILD_SELECT_LIMIT = 32


def _text(value: Any, limit: int = 80) -> str:
    return str(value or "").strip()[:limit]


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value == value and abs(value) != float("inf"):
        return float(value)
    return None


def _model_alias_candidates(observed_model: str) -> list[str]:
    """Every alias spelling that names the same served model as ``observed_model``.

    Specific first: the observed spelling, then the aliases the declared
    tables say are the same model. Two readers share this list — the mixture
    category label and the served-model attestation — so a new pointer alias
    or dated snapshot moves both without a second copy to update.

    Some explicitly declared catalog aliases represent a model contract plus
    a reasoning mode/service tier. Project only those rows onto the contract
    alias before retaining the older generic speed-tier behavior. Unknown
    suffixes therefore do not gain an Astra contract merely because their
    spelling looks similar. A dated snapshot (`gpt-5.6-terra-2026-07-09`) is
    the exception with its own bound: the base becomes a candidate, and it
    names a model only when a caller's own table names that base — an unknown
    base with a date matches nothing.

    ``observed_model`` is already unqualified and casefolded by
    `_unqualified_model_alias`; a raw wire spelling passed straight in would
    match nothing.
    """
    candidates = [observed_model]
    projected_model, _service_tier = _projected_model_alias(observed_model)
    snapshot_base = _dated_snapshot_base(observed_model)
    for alias in (projected_model, snapshot_base):
        if alias and alias not in candidates:
            candidates.append(alias)
    # The reverse direction: a chain may name the vendor's served pointer
    # (`deepseek-flash`) while the child ran under the exact contract id
    # (`deepseek/deepseek-v4.1-flash` on a gateway). Only a pointer — the
    # same model at the same mode and tier — projects this way; a `-pro` /
    # `-fast` / `-flex` entry is a different mode or price and never labels
    # the base id. A dated snapshot of the exact id reaches the pointer
    # through its snapshot base; a mode or tier variant's projected base is
    # deliberately not a root here, or `-fast` would reach the pointer.
    for root in (observed_model, snapshot_base):
        candidates.extend(
            alias
            for alias in EXACT_CONTRACT_POINTER_ALIASES.get(root, ())
            if root and alias not in candidates
        )
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
    return candidates


def mixture_category_for(
    model: str,
    effort: str,
    *,
    parent_model: str = "",
    chains: dict[str, tuple[tuple[str, str], ...]] | None = None,
) -> str:
    """Project an observed child model+effort onto a mixture category label.

    ``inherit`` wins over any chain match: a child on the parent session's own
    model looks unrouted, whatever chain its model also appears in — the
    projection cannot tell "routed to the model the parent also runs" from
    "not routed"; a fresh matching provenance record can, and the reader
    upgrades the row from it (`same_as_parent`). Otherwise
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
    # A child on a dated snapshot of the parent's model is on the parent's
    # model; the parent's own id is the base this reader knows. One direction
    # only, like the resolver's explicit match: a child on the unpinned base
    # of a date-pinned parent, or on a different date, is not the same run.
    if parent_key and parent_key in (observed_model, _dated_snapshot_base(observed_model)):
        return "inherit"

    # The alias spellings this model may also be named by; a chain entry
    # labels a category only when it names one of them. The list is shared
    # with the served-model attestation, so both move on one declaration.
    candidates = _model_alias_candidates(observed_model)
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


def _conversation_session_ids(connection: sqlite3.Connection, session_ref: str) -> set[str]:
    """Exact durable identity plus the segments Hermes' compaction links join to it.

    A transport id is not a durable id. Never substitute the latest session
    or normalize an invalid reference. The lineage is
    `live_session.conversation_segments`, which decides each link with the
    same predicates as the route restore's liveness and `omh_team`'s returns:
    within its row bound, every segment of a conversation gets the same set
    here, and the segments those walkers resolve from it are in that set. A
    branch, a delegate child, a reset and a `tool` row are forks, never this
    conversation; a stale sibling Hermes left beside a continuation, under
    any segment, is included. Older schemas can still answer exact ownership
    without answering lineage.
    """
    if not isinstance(session_ref, str) or not (1 <= len(session_ref) <= 160) or any(
        not (char.isalnum() or char in "_.:@-") for char in session_ref
    ):
        return set()
    if not connection.execute("SELECT 1 FROM sessions WHERE id = ?", (session_ref,)).fetchone():
        return set()
    return conversation_segments(connection, session_ref)


def _informative_cost_row_sql(columns: set[str]) -> str:
    """One SQL predicate: does this usage row say anything about cost?

    OMH still does not enumerate a host's BILLING words -- "included",
    "billed_zero" and the rest stay unknown to this reader, and any of them
    vouches for the zero it annotates. The one word named here is not a
    billing word at all: `unknown` is the host's own NO-FIGURE status, the
    one `usage_pricing._unknown_cost` stamps whenever it produced no amount
    (`agent/usage_pricing.py:549`, returning `amount_usd=None`), whether the
    route had no pricing entry at all (`:565`, paired with source `none`) or
    only a partial rate (`:583`, which pairs it with an informative source).
    The status is what carries the "no figure" meaning, so the source is not
    part of the test. `agent/turn_usage.py:236,257` is what persists the pair
    into `session_model_usage`; `agent/agent_init.py:2140` only seeds the
    session attribute default.

    Treating that status as provenance is what made every child on a custom
    gateway provider render `$0.0000 (unknown)` -- a stated zero the host
    never claimed. Evaluating it PER ROW instead of reducing with MAX is what
    keeps a MIXED group safe: one row carrying a real billing word is enough
    to stop the approximation, exactly as before.
    """
    status = "COALESCE(cost_status, '')" if "cost_status" in columns else "''"
    source = "COALESCE(cost_source, '')" if "cost_source" in columns else "''"
    return f"({status} <> '' OR {source} <> '') AND {status} <> 'unknown'"


def _preferred_provenance_sql(column: str, informative: str, columns: set[str]) -> str:
    """Read one provenance column from an informative row when the group has one.

    `MAX` over a mixed group answers alphabetically, so a session with one
    `included` row beside one `unknown` row reported `unknown` and rendered a
    vouched zero as `$0.0000 (unknown)`. Prefer the informative rows; with
    none, the host's no-figure status is the honest answer and `MAX` supplies
    it unchanged.
    """
    if column not in columns:
        return "NULL"
    return f"COALESCE(MAX(CASE WHEN {informative} THEN {column} END), MAX({column}))"


def _sole_distinct_value(value: Any, *, limit: int = 80) -> str:
    """The single value a `GROUP_CONCAT(DISTINCT ...)` returned, else "".

    `GROUP_CONCAT` joins distinct values with a comma, so more than one
    arrives as a list this reader cannot resolve into a single row field. The
    comma test runs on the WHOLE string: truncating first could cut the list
    down to its first element and pass it off as the only one.
    """
    text = str(value or "").strip()
    if not text or "," in text:
        return ""
    return text[:limit]


def _distinct_value_count(value: Any) -> int:
    """How many distinct values a `GROUP_CONCAT(DISTINCT ...)` returned.

    `_sole_distinct_value` spells "no rows at all" and "more than one value"
    with the same empty string, which is the right answer for a row field but
    loses the difference a verdict has to state: nothing observed versus an
    observation this reader cannot resolve. Counting the joined list keeps
    both, and is only ever read when that empty string arrives.
    """
    text = str(value or "").strip()
    if not text:
        return 0
    return len([part for part in text.split(",") if part.strip()])


def _observed_wire_model(child: Mapping[str, Any]) -> str:
    """The model a child ran: recorded on the session, else observed in usage.

    Hermes leaves `sessions.model` empty on a child whose session row was
    created before the model was known, and the label then had nothing to
    print. `session_model_usage.model` is written per call from the model
    that actually answered, so one distinct value there names it. Two
    distinct values (a child that switched models) or none leave the row
    exactly as recorded -- this reads an observation, it never infers one.
    """
    recorded = _text(child.get("model"))
    if recorded:
        return recorded
    return _text((child.get("usage") or {}).get("model"))


# What the verdict covers, stated where the verdict is read rather than left
# for the reader to assume. `_query_state_db` only ever selects delegation
# children (`model_config LIKE '%_delegate_from%'`), and only a child's usage
# rows are grouped per session here, so a main session is named by
# `sessions.model` alone and has nothing to attest against.
ATTESTATION_COVERAGE = "delegation_child"
ATTESTATION_COVERAGE_CLAIM = (
    "Served-model attestation covers delegation children only: the verdict "
    "compares the model a child was routed to against the model its "
    "session_model_usage rows say answered. A main session is named by "
    "sessions.model alone, with no per-call answering model to attest "
    "against, so it carries no verdict rather than an agreeing one."
)


def _shared_model_aliases(requested_key: str, answering_key: str) -> list[str]:
    """Every alias both sides resolve to, most specific first; empty is two models.

    Resolution is `_model_alias_candidates`, the same list the mixture
    category label matches chains against, so a newly declared pointer alias
    or a dated snapshot changes this verdict through that one table.
    """
    answering_candidates = set(_model_alias_candidates(answering_key))
    return [
        alias
        for alias in _model_alias_candidates(requested_key)
        if alias in answering_candidates
    ]


# Hermes ends every system prompt it builds with an identity trailer
# (`agent/system_prompt._timestamp_line`): one paragraph of `Label: value`
# lines, `Model: <agent.model>` among them, followed only by the renderer's
# own runtime block when there is one. Hermes reads it back with
# `agent/surface_switch.identity_line_value`, and these constants are the
# boundary that function splits on (`agent/prompt_builder.py`).
_RUNTIME_ENVIRONMENT_HEADING = "# Hermes runtime environment"
_RUNTIME_ENVIRONMENT_END = "<!-- End Hermes runtime environment -->"
_PROMPT_IDENTITY_LABEL = "Model:"
# Every line `_timestamp_line` can write. A last paragraph with any other line
# in it is not the trailer (memory or plugin prose when no trailer was
# written), and names no request.
_PROMPT_TRAILER_LABELS = (
    "Conversation started:",
    "Today's date (as of the last context rebuild):",
    "Timezone:",
    "Session ID:",
    "Model:",
    "Provider:",
    "Platform:",
)
# The trailer sits within the last few hundred characters of a stored prompt,
# so the read takes only this much of each one. A tail that does not hold the
# whole trailer paragraph reads as no identity, never as a partial one.
_PROMPT_IDENTITY_TAIL_CHARS = 8192
# The unknown basis for a row whose stored prompt Hermes may have rewritten
# after the first call: see `_attach_prompt_identity_models`.
PROMPT_MAY_BE_REBUILT_BASIS = "requested_model_prompt_may_be_rebuilt"


def _prompt_identity_model(prompt_tail: str) -> str:
    """The `Model:` value of a stored prompt's identity trailer, else "".

    Read the way Hermes' `identity_line_value` reads it, and stricter: drop the
    runtime block at its LAST heading when the prompt ends in its end marker
    (memory or context prose may quote the heading), take the last paragraph
    of what remains, and require every line in it to be one `_timestamp_line`
    writes. Memory, context files and plugin prose sit in earlier paragraphs,
    and a last paragraph that is prose is not a trailer, so a `Model:` line of
    theirs is never read. A tail with no paragraph break before the trailer is
    not known to hold the whole paragraph and reads as "".
    """
    identity = prompt_tail
    if prompt_tail.endswith(_RUNTIME_ENVIRONMENT_END):
        # A heading outside the tail leaves nothing before it, which the
        # paragraph rule below reads as "".
        identity = prompt_tail.rpartition(f"\n\n{_RUNTIME_ENVIRONMENT_HEADING}\n\n")[0]
    _earlier, paragraph_break, trailer = identity.rpartition("\n\n")
    if not paragraph_break:
        return ""
    lines = trailer.splitlines()
    if not lines or not all(line.startswith(_PROMPT_TRAILER_LABELS) for line in lines):
        return ""
    values = [
        line[len(_PROMPT_IDENTITY_LABEL):].strip()
        for line in lines
        if line.startswith(_PROMPT_IDENTITY_LABEL)
    ]
    return _text(values[-1]) if values else ""


def _attach_prompt_identity_models(
    connection: sqlite3.Connection,
    children: list[dict[str, Any]],
    session_columns: set[str],
) -> None:
    """The model each child's first system prompt names, as its attested request.

    Hermes builds a child's system prompt at the start of its first turn, from
    the model the child was built with, and creates the session row with it
    before the first model call (`agent/turn_context.build_turn_context`). A
    fallback during the turn swaps the running model and rewrites only the
    in-memory prompt (`rewrite_prompt_model_identity`: "Not persisted"), and
    the first accounted call can rewrite `sessions.model`, not the prompt.

    Hermes does rewrite the STORED prompt from the running model, which after
    a fallback is the fallback, in two places:
    - an in-place compaction (`compression.in_place`, on by default) archives
      the compacted rows (`messages.active = 0`), then writes a prompt rebuilt
      for the running model to the same row (`update_system_prompt`);
    - a later turn whose stored identity differs from the running model
      rebuilds and stores the prompt at its start (a child's output-schema
      retry is a second turn).
    So a stored prompt is read as the request only when the row cannot have
    passed either: a first segment, with no archived message and at most one
    user message. Any other first segment with a stored prompt is marked
    `prompt_may_be_rebuilt`, and an agreement there reads `unknown`.

    Not covered: a row `_ensure_db_session` creates late carries the
    in-memory prompt, which may already name a fallback, and nothing in the
    row marks it. That is a retry after the create at turn start failed
    transiently, or a re-create after the row disappeared mid-run.

    A first segment names the delegating session as `parent_session_id`, the
    same id as `_delegate_from`. A compression continuation names the
    previous segment and rebuilds its prompt from the running model, so it is
    never read. A schema without `parent_session_id` or `messages.active`
    cannot show the shape and attests nothing.

    The prompt is in `system_prompts`, keyed by `sessions.system_prompt_hash`,
    or inline in `sessions.system_prompt` on rows that predate the table.
    Best-effort like the other enrichments: any read fault leaves the request
    unattested, which withholds an agreement rather than inventing one.
    """
    if not children or "parent_session_id" not in session_columns:
        return
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

        def columns_of(table: str) -> set[str]:
            if table not in tables:
                return set()
            return {
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            }

        if not {"session_id", "role", "active"} <= columns_of("messages"):
            return
        tail = _PROMPT_IDENTITY_TAIL_CHARS
        sources: list[str] = []
        join = ""
        if "system_prompt_hash" in session_columns and {"hash", "prompt"} <= columns_of("system_prompts"):
            sources.append(f"substr(p.prompt, -{tail})")
            join = " LEFT JOIN system_prompts p ON p.hash = s.system_prompt_hash"
        if "system_prompt" in session_columns:
            sources.append(f"substr(s.system_prompt, -{tail})")
        if not sources:
            return
        prompt_tail = sources[0] if len(sources) == 1 else f"COALESCE({', '.join(sources)})"
        placeholders = ",".join("?" for _ in children)
        cursor = connection.execute(
            f"SELECT s.id, s.parent_session_id, {prompt_tail}, "
            "EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id AND m.active = 0), "
            "(SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id AND m.role = 'user') "
            f"FROM sessions s{join} WHERE s.id IN ({placeholders})",
            tuple(child["session_id"] for child in children),
        )
        rows = cursor.fetchall()
    except sqlite3.Error:
        return
    by_id = {child["session_id"]: child for child in children}
    for session_id, parent_session_id, prompt, archived, user_rows in rows:
        child = by_id.get(_text(session_id))
        if child is None or _text(parent_session_id) != child["parent_id"]:
            continue
        if not isinstance(prompt, str):
            continue
        if archived or int(user_rows or 0) > 1:
            child["prompt_may_be_rebuilt"] = True
            continue
        child["prompt_model"] = _prompt_identity_model(prompt)


def served_model_attestation(
    requested: str,
    answering: str,
    *,
    requested_source: str = "",
    request_attested: bool = False,
    unattested_basis: str = "requested_model_not_attested",
    answering_observations: int = 0,
) -> dict[str, Any]:
    """Compare the model a run was routed to against the model that answered.

    `session_model_usage.model` is written per call from the model that
    actually answered. The requested side is the caller's: the reader passes
    the model a child's first stored system prompt names when there is one
    (`_attach_prompt_identity_models`), else `sessions.model` with
    ``request_attested=False``. Nothing compared the two before, and
    `_observed_wire_model` prefers the recorded value — which hides the
    difference in exactly the case it exists.

    `sessions.model` is not a record of the request. Hermes'
    `update_token_counts` fills a NULL one from any accounted call, and on a
    session's first accounted call that names a billing provider it
    overwrites a different value with that call's model
    (`first_accounted_route`, there for a fallback route). So an unattested
    request that agrees with the answer may be the answer itself, and the
    verdict is `unknown` (`requested_model_not_attested`), never agreement.
    One that disagrees still reads as disagreement: those writes copy the
    model of an accounted call, so a value that differs from the sole model
    the usage rows name was not copied from any call that left a usage row.

    Both sides resolve through `_model_alias_candidates`, so a vendor pointer
    (`deepseek-flash`) answered by its exact contract id, or a base answered
    by a dated snapshot of itself, is agreement rather than a false alarm.

    `unknown` is a first-class verdict, never a failure and never a silent
    agreement. It is what a caller gets when no usage row named an answering
    model (`no_usage_observation`), when the usage rows named more than one so
    no single model answered the run (`multiple_usage_models` — the mid-run
    switch, which `_sole_distinct_value` hands over as an empty string that
    must not read as a match), when nothing recorded what was requested
    (`no_requested_model`), or when only an unattested request agrees
    (``unattested_basis``: `requested_model_not_attested`, or
    `requested_model_prompt_may_be_rebuilt` when the reader withheld a stored
    prompt Hermes may have rewritten).

    ``answering_observations`` is the distinct-model count behind ``answering``
    and is consulted only when ``answering`` is empty, to tell those first two
    apart. ``requested_source`` names where the requested side came from. The
    requested side is reported only when it is attested, or when it is the
    disagreeing value; an unattested value is never named `requested` beside
    a verdict that could not use it. ``request_attested`` defaults to False,
    so a caller that does not say where its request came from gets no
    agreement out of it.
    """
    requested_key = _unqualified_model_alias(requested)
    answering_key = _unqualified_model_alias(answering)
    resolved_requested = _projected_model_alias(requested_key)[0] if requested_key else ""
    resolved_answering = _projected_model_alias(answering_key)[0] if answering_key else ""
    shared_aliases: list[str] = []
    # The answering side is judged first: it is the observation the verdict
    # exists to report, and its absence is the structural case. A caller that
    # knows neither side hears about the missing observation first.
    if not answering_key:
        verdict = "unknown"
        basis = (
            "multiple_usage_models"
            if answering_observations > 1
            else "no_usage_observation"
        )
    elif not requested_key:
        verdict = "unknown"
        basis = "no_requested_model"
    else:
        shared_aliases = _shared_model_aliases(requested_key, answering_key)
        if shared_aliases and not request_attested:
            verdict = "unknown"
            basis = unattested_basis
            shared_aliases = []
        else:
            verdict = "agreement" if shared_aliases else "disagreement"
            basis = "resolved_match" if shared_aliases else "resolved_mismatch"
    attestation: dict[str, Any] = {"verdict": verdict, "basis": basis}
    if resolved_requested and (request_attested or verdict == "disagreement"):
        attestation["requested"] = resolved_requested
        if requested_source:
            attestation["requested_source"] = requested_source
    if resolved_answering:
        attestation["answering"] = resolved_answering
    # Named only when it says something the two sides do not: an `-ultrafast`
    # route answered by a `-fast` one agrees on a model neither side spells.
    # When either side already reports a shared alias, that spelling IS the
    # shared identity and a third name would only muddy it.
    if (
        shared_aliases
        and resolved_requested not in shared_aliases
        and resolved_answering not in shared_aliases
    ):
        attestation["resolved"] = shared_aliases[0]
    attestation["coverage"] = ATTESTATION_COVERAGE
    return attestation


def _attach_opening_goals(connection: sqlite3.Connection, children: list[dict[str, Any]]) -> None:
    """The dispatch prompt each child was opened with, as its own row's label.

    The HUD already renders a goal sentence -- `action` is the manifest task's
    `goal`, which IS the text the dispatcher wrote -- so this adds no new class
    of content to the screen. What it adds is OWNERSHIP. A manifest names no
    session, so in session scope it cannot be attributed and is dropped, and
    the row loses its label; a child's own first user message is in that
    child's session row, so the attribution is a primary key rather than a
    timestamp guess. That is why this is read here and the manifest is not.

    Rendered and never written anywhere: the reader persists nothing, and the
    awareness ledger's rule about never recording what was said is untouched
    by a label the HUD draws and forgets.

    The limit here bounds what the READER holds, not what renders -- the row
    applies `_ACTION_LIMIT` again on its way to `action`, so a first message
    that is a 100 KB paste never becomes 32 of those in memory. One number,
    two jobs; only the render one is observable from a row, so only that one
    is pinned by a test.

    Best-effort like every other enrichment here. A missing table, an older
    schema, or a child whose first row is not a user message leaves the label
    empty, which is what the row showed before.
    """
    pending = [child for child in children if not child.get("opening_goal")]
    if not pending:
        return
    placeholders = ",".join("?" for _ in pending)
    try:
        cursor = connection.execute(
            "SELECT session_id, content FROM messages WHERE rowid IN ("
            f"SELECT MIN(rowid) FROM messages WHERE session_id IN ({placeholders}) "
            "AND role = 'user' GROUP BY session_id)",
            tuple(child["session_id"] for child in pending),
        )
        opened = {str(row[0]): _text(row[1], limit=_ACTION_LIMIT) for row in cursor.fetchall()}
    except sqlite3.Error:
        return
    for child in pending:
        child["opening_goal"] = opened.get(child["session_id"], "")


def _query_state_db(
    state_db: Path, *, now: float, session_ref: str | None = None, owned_only: bool = False
) -> dict[str, Any]:
    """Read child sessions, usage tallies, and delegation states, read-only.

    `owners` is the conversation the rows were selected for, and is empty in
    global scope. It is reported rather than kept private because ownership
    of a child and ownership of the route prepared for it are the same
    question, answered once here. With `owned_only`, a `session_ref` that
    maps to no conversation selects no children, in session scope, instead
    of the global fallback.
    """
    result: dict[str, Any] = {
        "children": [],
        "delegation_states": {},
        "parent_models": {},
        "owners": frozenset(),
        "scope": "global",
        # How the read went, so a caller that lists children can say a read
        # failed instead of rendering it as no children: `absent` (no file),
        # `unreadable` (the child query never answered), `partial` (children
        # were read and a later query failed), else `read`.
        "read_status": "read",
        # True when the child query reached `_CHILD_SELECT_LIMIT`: more
        # children may exist than were read, so a count over them is a floor.
        "selection_capped": False,
    }
    if not state_db.is_file():
        result["read_status"] = "absent"
        return result
    try:
        connection = connect_readonly(state_db, timeout=0.25)
    except sqlite3.Error:
        result["read_status"] = "unreadable"
        return result
    children_read = False
    try:
        owner_filter = ""
        parameters: list[Any] = [now - _SESSION_WINDOW_SECONDS]
        if session_ref is not None:
            owners = _conversation_session_ids(connection, session_ref)
            if not owners and owned_only:
                result["scope"] = "session"
                return result
            if owners:
                result["scope"] = "session"
                result["owners"] = frozenset(owners)
                placeholders = ",".join("?" for _ in owners)
                owner_filter = (
                    " AND CASE WHEN json_valid(model_config) THEN "
                    f"json_extract(model_config, '$._delegate_from') IN ({placeholders}) ELSE 0 END"
                )
                parameters.extend(sorted(owners))
        # `ended_at` is what Hermes' `end_session` stamps when the child's
        # agent closes; a state.db from before the column reads every child
        # as unended, which leaves the age rule below to decide.
        session_columns = {
            str(row[1]) for row in connection.execute('PRAGMA table_info("sessions")').fetchall()
        }
        ended_at_column = "ended_at" if "ended_at" in session_columns else "NULL"
        cursor = connection.execute(
            f"SELECT id, model, model_config, started_at, {ended_at_column} FROM sessions "
            "WHERE model_config LIKE '%_delegate_from%' AND started_at >= ?"
            + owner_filter + f" ORDER BY started_at DESC LIMIT {_CHILD_SELECT_LIMIT + 1}",
            parameters,
        )
        # One row past the bound says the bound cut the selection; it is
        # dropped, so the children read are the same `_CHILD_SELECT_LIMIT`.
        rows = cursor.fetchall()
        result["selection_capped"] = len(rows) > _CHILD_SELECT_LIMIT
        rows = rows[:_CHILD_SELECT_LIMIT]
        parents_needed: set[str] = set()
        children: list[dict[str, Any]] = []
        for session_id, model, model_config, started_at, ended_at in rows:
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
                    "ended_at": _finite(ended_at),
                }
            )
        result["children"] = children
        children_read = True

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
            informative = _informative_cost_row_sql(columns)
            cost_status = _preferred_provenance_sql("cost_status", informative, columns)
            cost_source = _preferred_provenance_sql("cost_source", informative, columns)
            # One distinct value, or nothing. `billing_provider` is part of
            # the table's primary key, so a session that reached two
            # providers has two rows and no single answer to give a row.
            # `NULLIF` drops the column's own empty default first: a real
            # provider beside an unattributed row is still one provider.
            billing_provider = (
                "GROUP_CONCAT(DISTINCT NULLIF(billing_provider, ''))"
                if "billing_provider" in columns
                else "NULL"
            )
            # Hermes records each auxiliary call (compression, vision, web
            # extraction, ...) in this table under its task name and the aux
            # route's model (`record_auxiliary_usage`); the child's own turns
            # write an empty task. Those calls are real spend, so the sums
            # keep them, and so does the model that prices a child whose
            # only calls were auxiliary. They do not say which model answered
            # the child.
            every_model = "GROUP_CONCAT(DISTINCT NULLIF(model, ''))"
            answering_model = (
                "GROUP_CONCAT(DISTINCT CASE WHEN COALESCE(task, '') = '' THEN NULLIF(model, '') END)"
                if "task" in columns
                else every_model
            )
            cursor = connection.execute(
                f"""
                SELECT session_id, SUM(api_call_count), SUM(input_tokens),
                       SUM(output_tokens), SUM(cache_read_tokens),
                       SUM(actual_cost_usd), SUM(estimated_cost_usd),
                       {cost_status}, {cost_source},
                       MIN(first_seen), MAX(last_seen),
                       SUM(CASE WHEN {informative} THEN 1 ELSE 0 END),
                       {billing_provider},
                       {answering_model}, {every_model}
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
                    "informative_cost_rows": int(_finite(row[11]) or 0.0),
                    "billing_provider": _sole_distinct_value(row[12]),
                    "model": _sole_distinct_value(row[13]),
                    # Kept beside the resolved value, not derived from it: a
                    # child that switched models mid-run and a child with no
                    # usage row at all both leave `model` empty, and the
                    # attestation verdict has to tell them apart.
                    "model_count": _distinct_value_count(row[13]),
                    # The one model every row names, auxiliary calls
                    # included: what prices a child with no answering model.
                    "spend_model": _sole_distinct_value(row[14]),
                }
            for child in children:
                child["usage"] = usage.get(child["session_id"], {})
            _attach_opening_goals(connection, children)
            _attach_prompt_identity_models(connection, children, session_columns)

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
        result["read_status"] = "partial" if children_read else "unreadable"
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


def _observed_routes_reader(omh_home: str | Path | None) -> Any:
    """``parent session -> {child session: observed route}`` from OMH's delegation ledger, read once per parent.

    The ledger holds the ``route`` Hermes' own `delegate_task` result reported
    for a backend-routed child (`delegation_ledger.observe_delegate_call`). No
    OMH home, or an unreadable ledger, reports none.
    """
    cache: dict[str, dict[str, dict[str, Any]]] = {}

    def routes_of(parent_id: str) -> dict[str, dict[str, Any]]:
        if omh_home is None or not parent_id:
            return {}
        if parent_id not in cache:
            ledger = _delegation_ledger.read_ledger(Path(omh_home).expanduser(), parent_id) or {}
            cache[parent_id] = {
                child["child_session_id"]: child["observed_route"]
                for child in ledger.get("children", [])
                if child.get("observed_route")
            }
        return cache[parent_id]

    return routes_of


def read_hermes_native_subagents(
    hermes_home: str | Path | None = None,
    *,
    now: float | None = None,
    limit: int = _ROW_LIMIT,
    omh_home: str | Path | None = None,
    session_ref: str | None = None,
    owned_only: bool = False,
) -> dict[str, Any]:
    """Project owned native children, or explicitly global fallback activity.

    `owned_only` drops the fallback: a reference that maps to no conversation
    owns no children (see `_query_state_db`).
    """
    current = float(now) if now is not None else time.time()
    home = Path(hermes_home).expanduser() if hermes_home else runtime_paths.default_hermes_home()
    # Category labels honor the user's ~/.omh/routing/model-chains.json
    # overrides so a customized chain labels its children like a shipped one.
    active_chains = effective_mixture_category_chains(omh_home, home)
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
    state = _query_state_db(home / "state.db", now=current, session_ref=session_ref, owned_only=owned_only)
    payload["scope"] = state["scope"]
    payload["read_status"] = state["read_status"]
    payload["selection_capped"] = state["selection_capped"]
    children = state.get("children", [])
    if not children:
        return payload
    observed_routes = _observed_routes_reader(omh_home)
    # The host manifests carry neither parent nor child session identity.
    # Timestamp/task-order matching cannot establish ownership when dispatches
    # overlap. Keep legacy global context, but never borrow it for a session.
    manifests = (
        _read_manifests(home / "cache" / "delegation" / "live", now=current)
        if payload["scope"] == "global" else []
    )
    if payload["scope"] == "session":
        # A prepared route belongs to the session that wrote it, and that
        # session is the same identity the child filter above selected on,
        # so the history is filtered rather than discarded. Discarding it
        # was why the upgrade never once fired in the HUD: the widget reads
        # session-scoped, and every record went out with the bathwater.
        #
        # A record with no owner is not this conversation's by default. It
        # predates the field or came from a writer that could not name its
        # session, and unknown ownership is exactly what must not be
        # borrowed — which is also what those records did before, so no
        # install gets a worse label than it has today.
        owners = state.get("owners") or frozenset()
        route_provenance = [
            record for record in route_provenance if record.get("session_id") in owners
        ]
    payload["attestation_coverage"] = ATTESTATION_COVERAGE_CLAIM

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
        ended_at = child.get("ended_at")
        last_activity = max(
            child["started_at"],
            usage.get("last_seen") or 0.0,
            task.get("log_mtime") or 0.0,
            ended_at or 0.0,
        )
        age = current - last_activity
        if age > COMPLETED_LINGER_SECONDS:
            continue
        if delegation_state in {"completed", "failed", "cancelled"}:
            row_state = "failed" if delegation_state == "failed" else "done"
        elif ended_at is not None:
            # The child's session was ended, so it is not running whatever
            # its age; the session-scoped path has no manifest state to say
            # so, and without this an ended child spun for the whole recent
            # window. Hermes ends a child with `agent_close` whether it
            # succeeded or not, so the end reason says nothing about failure;
            # the no-usage rule below still does.
            row_state = "done"
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

        # An empty `sessions.model` is filled from the one model the child's
        # usage rows observed, never from a guess; see `_observed_wire_model`.
        wire_model = _observed_wire_model(child)
        # What was asked for, compared with what answered (the usage model).
        # The request comes from the child's own records and nothing else:
        # the model its first stored system prompt names, read only from a
        # row that shows neither way Hermes rebuilds a stored prompt
        # (`_attach_prompt_identity_models`, which names the late-created row
        # it cannot see), else its `sessions.model`,
        # which Hermes can rewrite to the answering model and so cannot
        # attest an agreement (see `served_model_attestation`). A child with
        # neither is `unknown` (`no_requested_model`). Today's
        # `delegation.model` is not a record of a past request: OMH rewrites
        # it per dispatch and restores it at turn end, so reading it here
        # made a finished child's verdict change when the config did.
        prompt_model = _text(child.get("prompt_model"))
        attestation = served_model_attestation(
            prompt_model or _text(child.get("model")),
            _text(usage.get("model")),
            requested_source="prompt_identity" if prompt_model else "session_model",
            request_attested=bool(prompt_model),
            unattested_basis=(
                PROMPT_MAY_BE_REBUILT_BASIS
                if child.get("prompt_may_be_rebuilt")
                else "requested_model_not_attested"
            ),
            answering_observations=int(usage.get("model_count") or 0),
        )

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
        #
        # The single exception is the host's own no-figure status, tested per
        # usage row by `_informative_cost_row_sql`: `unknown` is what Hermes
        # stamps when its pricing produced no amount at all, so it says the
        # host has no figure rather than naming a billing outcome.
        # `informative_cost_rows` is therefore the count of rows carrying
        # provenance that IS a claim about cost; zero means every row either
        # recorded nothing or recorded that it knows nothing.
        cost_provenance = cost_status or cost_source
        informative_cost_rows = int(usage.get("informative_cost_rows") or 0)
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
        # approximation therefore fires on a zero that no usage row made an
        # informative claim about -- none recorded, or every one of them the
        # host's no-figure status.
        # What must NOT happen is the third case: no recorded cost, no
        # provenance, AND no price for the model (`_approximate_cost_usd`
        # returns None for an unpriced model, and for a run with no tokens).
        # That left `cost` at 0.0 with no approximate flag, so the row
        # claimed the run was free. An unknown cost is unknown: send None and
        # let the surface say nothing rather than state a zero it cannot
        # support. A no-figure row is the one place the bare zero stays: the
        # host wrote a word for it, so the surface can still render
        # `$0.0000 (unknown)` instead of falling silent.
        cost_approximate = False
        # A figure derived from the operator's own rate and one derived from
        # our shipped ballpark are both approximations, but they are not
        # equally arguable: only the first is a number the operator chose.
        # The row says which, so a surface can tell them apart.
        #
        # The tokens priced here include auxiliary calls. A child whose only
        # calls were auxiliary has no answering model, so those tokens are
        # priced at the one model they ran on.
        priced_model = wire_model or _text(usage.get("spend_model"))
        cost_override = bool(_model_price_override_key(priced_model, price_overrides))
        if not cost and not informative_cost_rows:
            approx = _approximate_cost_usd(
                priced_model, input_tokens, output_tokens, cache_read, price_overrides
            )
            if approx is not None:
                cost = approx
                cost_approximate = True
            elif cost_provenance is None:
                cost = None

        parent_model = state.get("parent_models", {}).get(child["parent_id"], "")
        route_alias, route_provider = configured_route_for_wire(
            wire_model,
            provider_routes,
        )
        session_tail = child["session_id"].rsplit("_", 1)[-1][:8]
        # A finished child's elapsed is frozen at its end, else its last
        # activity: a done task should not keep aging, and a byte-stable
        # lingering row is what lets the widget skip repaints so the dock
        # stays drag-copyable.
        if ended_at is not None:
            elapsed_until = ended_at
        else:
            elapsed_until = last_activity if row_state != "running" else current
        row: dict[str, Any] = {
            "scope": payload["scope"],
            "state": row_state,
            "task_id": session_tail,
            "role": "hermes-native",
            # The manifest task's goal when one could be attributed, else the
            # prompt the child itself was opened with. Same sentence, and the
            # fallback is the one with provable ownership -- see
            # `_attach_opening_goals`.
            "action": _text(task.get("goal", ""), limit=_ACTION_LIMIT)
            or _text(child.get("opening_goal", ""), limit=_ACTION_LIMIT),
            "alias": route_alias,
            "provider": route_provider,
            "model": wire_model,
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
            "model_attestation": attestation,
        }
        if route_provider:
            row["provider_source"] = "model_provider_routes"
        elif usage.get("billing_provider"):
            # No `model-providers.json` row names this wire model, so OMH has
            # no configured provider of its own -- but the host recorded which
            # provider it billed the calls under, which answers the same
            # question. This fills the payload field for the `read_omh_hud`
            # JSON payload; the TUI widget renders the model, not the
            # provider, so nothing on screen changes. The source marker keeps
            # an observed billing fact distinguishable from OMH's own
            # configuration.
            row["provider"] = usage["billing_provider"]
            row["provider_source"] = "hermes_billing_provider"
        # Prepared-route provenance is a best-effort label upgrade, never
        # row identity: when the child's identity matches the newest route
        # prepared before its dispatch, a fallback lane says so and an
        # exhausted chain keeps its category with an `inherit` model token
        # (`category(model inherit)`), and a lane routed to the parent's own
        # model keeps its category with a `=parent` token, instead of
        # converging into plain inherit. The upgrade carries its own source
        # marker. The model that matches here is the same observed wire
        # model the alias and category above were derived from, so the three
        # stay one identity; a child whose model the host never recorded and
        # never used matches nothing, which is the safe degradation.
        provenance = _provenance_for_dispatch(
            route_provenance,
            started_at=child["started_at"],
            wire_model=wire_model,
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
                    if row["category"] == "inherit":
                        # Routed to the model the parent also runs: the
                        # category is the lane's, and the payload records
                        # that the model is the parent's own for a caller
                        # holding both. The TUI row spends no token on it —
                        # the row names the model that ran, and the
                        # comparison is against a model it never shows.
                        # Gated on the record carrying a category by
                        # decision: an explicit bare-model route (`set` with
                        # a model and no category) onto the parent's model
                        # has no lane to name, so it stays the plain
                        # `inherit(model)`.
                        row["same_as_parent"] = True
                    row["category"] = provenance["category"]
                    row["category_source"] = "route_provenance"
                if provenance["origin"] == "fallback":
                    row["route_origin"] = "fallback"
        if failure_hint:
            row["failure_hint"] = failure_hint
        reported = observed_routes(child["parent_id"]).get(child["session_id"])
        if reported:
            # Where Hermes' delegation backend (0.22.5+) reports it ran this child. The model shown is the observed
            # wire model above; the option name (`label`) is the user's own, and it outranks no OMH category.
            row["route_backend"] = reported["backend"]
            if reported.get("label"):
                row["route_label"] = reported["label"]
            if reported.get("fallback_activated"):
                row["route_origin"] = "fallback"
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


# Module scope, not call time: Hermes can evict the bundle from sys.modules
# while its callbacks stay live (#1979). Last, because the ledger imports this
# module: the cycle then finds every name defined here.
from . import delegation_ledger as _delegation_ledger  # noqa: E402
