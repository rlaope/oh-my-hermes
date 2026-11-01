"""Deterministic local model inventory (`model_inventory/v1`).

Reporting-only observation of which coding models the user has locally
activated: agent CLIs on PATH, models named by the pi-family runtime
config, opencode provider config, and opencode auth provider names. The
inventory answers "what does this user actually have?" before any delegation
or routing decision is proposed.

Boundaries, in order of importance:

- Reporting only. Nothing here enters a model route payload, a frozen fanout
  contract, or persisted state — the inventory is a read-time observation and
  routing stays pure (`model_routing` never imports this module; a test pins
  that direction).
- Metadata only. Model ids, provider names, and variant labels are read;
  secret values never are. Every identifier passes
  `require_opaque_metadata_ref` before it may appear in the payload; anything
  rejected is counted, never echoed. Unreadable sources report a status, not
  a path or an error text.
- Local-file evidence only. Presence in the inventory is configuration
  evidence, not entitlement, quota, or login truth — the provider owns those
  and adjudicates at execution time.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Callable, Final, Mapping

from ..system.local_store import utc_now
from ..system.metadata_safety import require_opaque_metadata_ref
from .pi_family_interop import (
    OPENCODE_RUNTIME_CONFIG_RELATIVE,
    PI_DISTRIBUTION_HOME,
    PI_DISTRIBUTION_HOST,
)
from .executor_auth_signals import executor_auth_signals
from .model_discovery import discover_local_models
from .model_routing import (
    CATEGORY_ROLE_SOURCES,
    CATEGORY_SCALE_SOURCES,
    MODEL_CATEGORIES,
    merged_category_chain,
    model_family,
)

MODEL_INVENTORY_SCHEMA_VERSION: Final[str] = "model_inventory/v1"

MODEL_INVENTORY_CLAIM_BOUNDARY: Final[str] = (
    "A model inventory is a read-time observation of local configuration files and PATH presence. "
    "It is reporting-only advisory context: not entitlement, quota, or login truth, not a route, "
    "and never dispatch, execution, review, CI, or merge evidence."
)

MODEL_INVENTORY_SOURCE_STATUSES: Final[tuple[str, ...]] = ("present", "absent", "unreadable")

# Fixed probe table: agent CLI command names checked for PATH presence only.
# Presence of a wrapper CLI (opencode) is how provider-hosted models
# (gemini/grok/kimi/glm-style) become locally runnable without their own CLI.
CLI_PRESENCE_COMMANDS: Final[tuple[str, ...]] = (
    "codex",
    "claude",
    "opencode",
    "pi",
    PI_DISTRIBUTION_HOST,
    "gemini",
    "grok",
    "qwen",
)

# Static advisory notes mapping work domains to model families with a known
# edge there (for example X/Twitter platform data belongs to the grok family's
# home platform). Closed vocabulary, report-only: these notes never rank,
# reorder, or route — they exist so a wrapper proposing a split can mention
# which locally-present family fits a domain. Deliberately NOT named
# "capability": `KNOWN_CAPABILITY_NAMES` (executor runtime capabilities) and
# `capabilities/families.py` (skill families) are different vocabularies.
MODEL_DOMAIN_AFFINITIES: Final[dict[str, tuple[str, ...]]] = {
    "x_platform_data": ("grok",),
    "multimodal_vision": ("gemini", "gpt", "claude"),
}

MODEL_DOMAIN_AFFINITY_CLAIM_BOUNDARY: Final[str] = (
    "Domain affinity notes are static editorial defaults, not observed, benchmarked, or measured "
    "capability — OMH never evaluates a model. When a unit explicitly declares a domain, they may "
    "advisorily reorder a locally-derived chain with the reorder recorded in the route's attempted "
    "trail; they are never a veto, never remove an option, and the user's explicit model choice "
    "always wins."
)

# The executor profile a locally-derived catalog belongs to: the pi-family
# runtime ships either as an extension of a pi-family host CLI (pi, or its
# distribution host) or
# as an opencode plugin — both layouts are first-class hosts (see
# PI_FAMILY_HOST_CANDIDATES in fanout_dispatch). Models named by its config
# run under the pi-family runtime surface, never under codex/claude-code (whose
# catalogs stay built-in). Catalog compatibility boundary: the legacy
# route-authoritative model list is still read ONLY from the opencode config
# path (`OPENCODE_RUNTIME_CONFIG_RELATIVE`). The separate reporting-only
# discovery payload observes the runtime's canonical home config
# (`RUNTIME_HOME` / `RUNTIME_CONFIG_FILES`, `RUNTIME_MODELS_FILE`) metadata, but never promotes those observations
# into this catalog. Unknown `~/.omp` layouts remain explicitly unverified.
MODEL_INVENTORY_CATALOG_PROFILE: Final[str] = "pi-family-runtime"

LOCAL_MODEL_CATALOG_SCHEMA_VERSION: Final[str] = "local_model_catalog/v1"

# The routing rule is ONE rule, defined in `model_routing` and imported here so
# a locally-derived catalog and the built-in table cannot drift apart.

_RUNTIME_AGENT_CONFIG_RELATIVE: Final[str] = OPENCODE_RUNTIME_CONFIG_RELATIVE
_OPENCODE_CONFIG_RELATIVE: Final[str] = ".config/opencode/opencode.json"
_OPENCODE_AUTH_RELATIVE: Final[str] = ".local/share/opencode/auth.json"
_PI_AUTH_RELATIVE: Final[str] = ".pi/agent/auth.json"
_PI_DISTRIBUTION_AUTH_RELATIVE: Final[str] = f"{PI_DISTRIBUTION_HOME}/agent/auth.json"

# Narrow by design (mirrors `_claude_marker`): a failure to read or parse a
# config marks the source `unreadable` and nothing else — no broad except.
_READ_ERRORS = (OSError, UnicodeDecodeError, json.JSONDecodeError)


def local_model_inventory(
    home: Path | None = None,
    *,
    discovery_limits: Mapping[str, object] | None = None,
    discovery_clock: Callable[[], float] | None = None,
) -> dict[str, object]:
    """Return the metadata-only inventory of locally-activated coding models."""
    base = home if home is not None else Path.home()
    cli_presence = {command: shutil.which(command) is not None for command in CLI_PRESENCE_COMMANDS}
    runtime_source, runtime_models, category_chains = _runtime_agent_config_source(base / _RUNTIME_AGENT_CONFIG_RELATIVE)
    provider_source = _top_level_key_source(base / _OPENCODE_CONFIG_RELATIVE, section="provider")
    auth_source = _top_level_key_source(base / _OPENCODE_AUTH_RELATIVE, section="")
    pi_distribution_auth_source = _top_level_key_source(base / _PI_DISTRIBUTION_AUTH_RELATIVE, section="")
    pi_auth_source = _top_level_key_source(base / _PI_AUTH_RELATIVE, section="")
    auth_signals = executor_auth_signals(base)
    signal_profiles = auth_signals.get("profiles", {})
    login_markers = {
        profile: str(entry.get("login_marker", "unknown"))
        for profile, entry in signal_profiles.items()
        if isinstance(entry, Mapping)
    }
    available_models = _aggregated_models(runtime_models)
    families = sorted({str(entry["family"]) for entry in available_models if entry["family"]})
    discovery = (
        discover_local_models(base, limits=discovery_limits, clock=discovery_clock)
        if discovery_clock is not None
        else discover_local_models(base, limits=discovery_limits)
    )
    return {
        "schema_version": MODEL_INVENTORY_SCHEMA_VERSION,
        "observed_at": utc_now(),
        "sources": {
            "cli_presence": {
                "status": "present" if any(cli_presence.values()) else "absent",
                "commands": cli_presence,
            },
            "runtime_agent_config": runtime_source,
            "opencode_config_providers": provider_source,
            "opencode_auth_providers": auth_source,
            "pi_auth_providers": pi_auth_source,
            "pi_distribution_auth_providers": pi_distribution_auth_source,
            "executor_auth_signals": {"status": "present", "login_markers": login_markers},
        },
        "available_models": available_models,
        "families_present": families,
        "runtime_category_chains": {name: list(chain) for name, chain in sorted(category_chains.items())},
        "domain_affinity_notes": [
            {
                "domain": domain,
                "affine_families": list(affine),
                "locally_present": sorted(set(affine) & set(families)),
            }
            for domain, affine in sorted(MODEL_DOMAIN_AFFINITIES.items())
        ],
        "domain_affinity_claim_boundary": MODEL_DOMAIN_AFFINITY_CLAIM_BOUNDARY,
        "model_discovery": discovery,
        "claim_boundary": MODEL_INVENTORY_CLAIM_BOUNDARY,
    }


def _runtime_agent_config_source(
    path: Path,
) -> tuple[dict[str, object], list[tuple[str, str, str]], dict[str, list[dict[str, str]]]]:
    """Read (source payload, model entries, per-category ordered chains).

    Model entries are `(provider, model_id, variant)` tuples from both agents
    and categories. Category chains keep the config's own primary-then-
    fallback order per category name so a local catalog can derive role
    chains from them deterministically.
    """
    parsed = _read_json(path)
    if parsed is None:
        return (
            {"status": "absent" if not path.is_file() else "unreadable", "model_count": 0, "rejected": 0},
            [],
            {},
        )
    entries: list[tuple[str, str, str]] = []
    category_chains: dict[str, list[dict[str, str]]] = {}
    rejected = 0
    for section in ("agents", "categories"):
        table = parsed.get(section)
        if not isinstance(table, Mapping):
            continue
        for name, spec in table.items():
            if not isinstance(spec, Mapping):
                continue
            candidates = [spec]
            fallbacks = spec.get("fallback_models")
            if isinstance(fallbacks, list):
                candidates.extend(entry for entry in fallbacks if isinstance(entry, Mapping))
            accepted_chain: list[dict[str, str]] = []
            for candidate in candidates:
                if "model" not in candidate:
                    continue
                accepted = _accepted_model_entry(candidate)
                if accepted is None:
                    # Present but shape-rejected data is counted, never echoed.
                    rejected += 1
                else:
                    entries.append(accepted)
                    provider, model_id, variant = accepted
                    accepted_chain.append(
                        {"model_id": f"{provider}/{model_id}", "reasoning_effort": variant}
                    )
            if section == "categories" and accepted_chain:
                try:
                    category = require_opaque_metadata_ref(name, field="category")
                except ValueError:
                    rejected += 1
                    continue
                category_chains[category] = accepted_chain
    return {"status": "present", "model_count": len(entries), "rejected": rejected}, entries, category_chains


def _accepted_model_entry(candidate: Mapping[str, object]) -> tuple[str, str, str] | None:
    """Validate one `{model, variant?}` config entry into (provider, model_id, variant)."""
    raw_model = candidate.get("model")
    raw_variant = candidate.get("variant", "")
    try:
        reference = require_opaque_metadata_ref(raw_model, field="model")
        variant = require_opaque_metadata_ref(raw_variant, field="variant") if raw_variant else ""
    except ValueError:
        return None
    provider, separator, model_id = reference.partition("/")
    if not separator or not provider or not model_id or "/" in model_id:
        return None
    return provider, model_id, variant


def _top_level_key_source(path: Path, *, section: str) -> dict[str, object]:
    """Report top-level key NAMES of a JSON object (or of one nested section).

    Values are never read: providers are identified by key name alone, which
    is what keeps auth files presence-only.
    """
    parsed = _read_json(path)
    if parsed is None:
        return {"status": "absent" if not path.is_file() else "unreadable", "providers": [], "rejected": 0}
    table = parsed.get(section) if section else parsed
    if not isinstance(table, Mapping):
        return {"status": "present", "providers": [], "rejected": 0}
    providers: list[str] = []
    rejected = 0
    for key in table:
        try:
            providers.append(require_opaque_metadata_ref(key, field="provider"))
        except ValueError:
            rejected += 1
    return {"status": "present", "providers": sorted(providers), "rejected": rejected}


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        if not path.is_file():
            return None
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except _READ_ERRORS:
        return None
    return parsed if isinstance(parsed, dict) else None


def inventory_model_catalog(inventory: Mapping[str, object]) -> dict[str, object] | None:
    """Derive the local model catalog for the pi-family runtime from an inventory payload.

    Pure data transform (no I/O): callers observe the inventory once and pass
    it in, so the route resolver stays free of filesystem reads. Returns None
    when the inventory names no models — a missing catalog must read as
    "nothing configured", never as an empty-but-authoritative catalog.

    The fingerprint is the reproducibility anchor for any route frozen from
    this catalog: digest of the sorted model ids plus per-source statuses and
    the observation time. `reasoning_efforts` stays empty on every option —
    observed config variants are evidence of use, not of a model's effort
    vocabulary, so this catalog never gains effort authority.
    """
    models = inventory.get("available_models", [])
    if not isinstance(models, list) or not models:
        return None
    option_ids: list[str] = []
    options: list[dict[str, object]] = []
    for entry in models:
        if not isinstance(entry, Mapping):
            continue
        model_id = f"{entry.get('provider')}/{entry.get('model_id')}"
        option_ids.append(model_id)
        options.append(
            {
                "model_id": model_id,
                "label": f"{entry.get('family') or 'unknown'} family via {entry.get('provider')}",
                "tier": "",
                "recommended_roles": (),
                "reasoning_efforts": (),
            }
        )
    category_chains = inventory.get("runtime_category_chains", {})
    chains: dict[str, tuple[dict[str, str], ...]] = {}
    category_catalog: dict[str, tuple[dict[str, str], ...]] = {}
    if isinstance(category_chains, Mapping):
        for category in MODEL_CATEGORIES:
            merged = merged_category_chain(category_chains, (category,))
            if merged:
                category_catalog[category] = tuple(merged)
        for role, source_categories in CATEGORY_ROLE_SOURCES.items():
            merged = merged_category_chain(category_chains, source_categories)
            if merged:
                chains[role] = tuple(merged)
        # `{role}:{scale}` chains, keyed exactly like the `research:{depth}`
        # entries the resolver already looks up, so the local path and the
        # built-in path answer the same question the same way.
        for role in CATEGORY_ROLE_SOURCES:
            # `research` is excluded because the resolver skips the scale dial
            # for it in favour of depth; deriving `research:small` would be a
            # chain nothing can ever look up.
            if ":" in role or role == "research":
                continue
            for scale, source_categories in CATEGORY_SCALE_SOURCES.items():
                merged = merged_category_chain(category_chains, source_categories)
                if merged:
                    chains[f"{role}:{scale}"] = tuple(merged)
    sources = inventory.get("sources", {})
    source_statuses = (
        {name: str(entry.get("status", "unknown")) for name, entry in sources.items() if isinstance(entry, Mapping)}
        if isinstance(sources, Mapping)
        else {}
    )
    # The digest anchors the derived ARTIFACT, not just the input model set:
    # reassigning a category (and with it a role chain) to an already-present
    # model is exactly the drift the fingerprint exists to make visible, so
    # the chains participate in the digest alongside the option ids.
    canonical = json.dumps(
        {
            "options": sorted(option_ids),
            "chains": {
                role: [[entry["model_id"], entry["reasoning_effort"]] for entry in chain]
                for role, chain in sorted(chains.items())
            },
            "categories": {
                category: [[entry["model_id"], entry["reasoning_effort"]] for entry in chain]
                for category, chain in sorted(category_catalog.items())
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return {
        "schema_version": LOCAL_MODEL_CATALOG_SCHEMA_VERSION,
        "executor_profile": MODEL_INVENTORY_CATALOG_PROFILE,
        "catalog_kind": "local_inventory",
        "options": options,
        "chains": chains,
        "categories": category_catalog,
        # The affinity vocabulary rides the catalog payload so the resolver
        # consumes it as data — routing never imports this module, and the
        # reorder scope stays exactly the locally-derived chains.
        "domain_affinities": {domain: affine for domain, affine in sorted(MODEL_DOMAIN_AFFINITIES.items())},
        "fingerprint": {
            "digest": digest,
            "sources": source_statuses,
            "observed_at": str(inventory.get("observed_at", "")),
        },
    }


def catalog_fingerprint_note(
    model_route: Mapping[str, object] | None, current_digest: str
) -> dict[str, object] | None:
    """Advisory prepare-vs-dispatch skew record for a frozen route.

    A route resolved from a local catalog froze that catalog's fingerprint;
    the local config may have changed between prepare and dispatch. The note
    names both digests and whether they match — advisory only: a mismatch
    never blocks dispatch (the frozen contract stays the explicit instruction
    and provider truth adjudicates the model), it only makes the skew visible.
    Returns None for routes without a fingerprint — and for fingerprints that
    name a different source (`identities.json`, `category-maestro.json`),
    whose digest can only be compared against that same source's current
    read; those take `_config_fingerprint_note`'s path instead of reporting
    permanent false skew against the inventory digest.
    """
    if not isinstance(model_route, Mapping):
        return None
    fingerprint = model_route.get("catalog_fingerprint")
    if not isinstance(fingerprint, Mapping) or fingerprint.get("source") is not None:
        return None
    frozen = str(fingerprint.get("digest", "") or "")
    current = str(current_digest or "")
    return {
        "frozen_digest": frozen,
        "current_digest": current,
        "match": bool(frozen) and frozen == current,
    }


def _aggregated_models(entries: list[tuple[str, str, str]]) -> list[dict[str, object]]:
    variants_by_model: dict[tuple[str, str], set[str]] = {}
    for provider, model_id, variant in entries:
        variants = variants_by_model.setdefault((provider, model_id), set())
        if variant:
            variants.add(variant)
    return [
        {
            "provider": provider,
            "model_id": model_id,
            "variants": sorted(variants),
            "family": model_family(model_id),
        }
        for (provider, model_id), variants in sorted(variants_by_model.items())
    ]
