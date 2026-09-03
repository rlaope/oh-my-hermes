"""Deterministic model routing for prepared coding handoffs.

`resolve_model_route` is a pure function: same inputs, byte-identical payload,
no I/O, no clock, no environment reads. It prepares metadata only — omh never
invokes a model, never retries, and never switches models at runtime.

Reading provenance back from a persisted route MUST go through
`route_provenance` — it is the sole sanctioned accessor. Frozen fanout
contracts may carry `coding_model_route/v1` payloads whose `source` vocabulary
predates chains; that recorded value is returned verbatim, never translated
into v2 vocabulary, because restating a frozen record would make it say
something that never happened.

Effort precedence: requested effort > chain-entry effort > none.
`effort_change.requested` always holds the USER's request and the field is
absent when no effort was requested; chain-supplied efforts never appear in
`effort_change`.

Throughout this module, "profile" means a key of `EXECUTOR_MODEL_OPTIONS`.
Profiles without a catalog entry (hermes, generic, the runtime profiles) are
never matrix cells and never require chains; the executor CLI default applies.
"""

from __future__ import annotations

import re
from typing import Final, Iterable, Mapping

CODING_MODEL_ROUTE_SCHEMA_VERSION: Final[str] = "coding_model_route/v2"
# The frozen v1 identifier: referenced only for reading persisted payloads.
CODING_MODEL_ROUTE_V1_SCHEMA_VERSION: Final[str] = "coding_model_route/v1"
CODING_MODEL_ROUTE_SUPPORTED_SCHEMA_VERSIONS: Final[tuple[str, ...]] = (
    CODING_MODEL_ROUTE_SCHEMA_VERSION,
    CODING_MODEL_ROUTE_V1_SCHEMA_VERSION,
)

# Roles are the subagent shapes a fanout/handoff unit can declare. They name the
# kind of work, never a vendor, so per-role defaults stay executor-neutral.
MODEL_ROLES: Final[tuple[str, ...]] = (
    "brain",
    "implementation",
    "design_visual",
    "review",
    "docs",
    # Read-only investigation lanes. The chain default is the cheap sweep;
    # a deep multi-system investigation escalates model/effort EXPLICITLY on
    # the unit (requested values always win) — scope is the caller's dial,
    # never an inferred one.
    "research",
)

MODEL_ROUTE_STATUSES: Final[tuple[str, ...]] = (
    "routed",
    "choice_required",
    "model_unrouted",
    "no_model_catalog",
)

MODEL_ROUTE_PROVENANCES: Final[tuple[str, ...]] = (
    "request_named_model",
    "request_named_model_unavailable",
    "recommendation_chain_head",
    "category_chain_head",
    "role_chain_head",
    "role_unchained",
    "executor_default",
    "no_catalog",
)

# The frozen v1 vocabulary. Not aspirational documentation: `route_provenance`
# validates persisted v1 payloads against it, and the v1 fixture test consumes
# it. A v1 `source` outside this tuple is malformed and reads as "unknown".
_V1_MODEL_ROUTE_SOURCES: Final[tuple[str, ...]] = (
    "request_named_model",
    "role_catalog_default",
    "role_catalog_candidates",
    "executor_default",
    "no_catalog",
)

EFFORT_CHANGE_KINDS: Final[tuple[str, ...]] = (
    "unchanged",
    "legacy_alias_normalized",
    "automatic_passthrough",
    "ladder_downgrade",
    "catalog_no_authority_passthrough",
    "unknown_vocabulary_passthrough",
    "rejected_unsafe_shape",
)

# Canonical weakest-to-strongest reasoning vocabulary. Consumers may compare
# positions directly; model catalogs remain the authority on which rungs each
# exact model supports.
REASONING_EFFORT_LADDER: Final[tuple[str, ...]] = (
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)

CODING_MODEL_ROUTE_CLAIM_BOUNDARY: Final[str] = (
    "A model route is prepared metadata for a coding handoff or dispatch argv. Model availability, "
    "entitlement, pricing, and quota are provider truth omh does not observe, and a routed model is "
    "not execution, verification, review, CI, or merge evidence. Entries after the selected one are "
    "prepared next-candidate advice; omh never retries or switches models itself."
)

# Built-in default candidates per dispatchable/prompt-handoff executor profile.
# Claude Code accepts concrete model ids and stable tier aliases (`opus`
# tracks the newest Opus); Codex takes vendor model ids. Both CLIs also accept
# ids this catalog has never heard of, so requested models always pass
# through unvalidated — the catalog is a default candidate list, not an
# allowlist. The Fable-tier rows are concrete ids on purpose: the CLI's
# `fable` alias exists but cannot express the owner-ordered Claude chain
# (Fable 5.1 -> Mythos 5.1 -> Opus, 2026-09-02), which needs the two
# Fable-tier ids named exactly so Mythos sits behind Fable. Mythos 5.1
# is the same model as Fable 5.1 served only to Project Glasswing-approved
# organizations; an unapproved account gets a provider rejection and the
# chain falls through to the next entry, which is why it never heads a chain.
MODEL_CATALOG_KIND: Final[str] = "built_in_defaults"

# Closed vocabulary for a route's catalog basis. `local_inventory` marks a
# catalog derived from the user's own local configuration at observation time;
# such routes additionally carry `catalog_fingerprint` so a frozen record
# names the exact basis it was resolved from.
MODEL_CATALOG_KINDS: Final[tuple[str, ...]] = (
    "built_in_defaults",
    "local_inventory",
    "editorial_recommendations",
    # The operator's category-maestro config merged over the built-in table
    # (`~/.omh/routing/category-maestro.json`); such routes also carry the
    # config's fingerprint so a frozen record names its exact basis.
    "operator_category_config",
)

EXECUTOR_MODEL_OPTIONS: Final[dict[str, tuple[dict[str, object], ...]]] = {
    "codex": (
        {
            "model_id": "gpt-5-codex",
            "label": "Codex frontier coding model",
            "tier": "frontier",
            "recommended_roles": ("brain", "review", "design_visual"),
            "reasoning_efforts": ("off", "minimal", "low", "medium", "high", "xhigh"),
        },
        {
            "model_id": "gpt-5",
            "label": "General frontier model",
            "tier": "standard",
            "recommended_roles": ("implementation", "docs", "review", "research"),
            "reasoning_efforts": ("off", "minimal", "low", "medium", "high", "xhigh"),
        },
    ),
    "claude-code": (
        {
            "model_id": "claude-fable-5-1",
            "label": "Claude Fable 5.1 (most capable widely released tier)",
            "tier": "frontier",
            "recommended_roles": ("brain", "review", "design_visual"),
            "reasoning_efforts": ("low", "medium", "high", "xhigh", "max"),
        },
        {
            "model_id": "claude-mythos-5-1",
            "label": "Claude Mythos 5.1 (Fable 5.1 weights, Project Glasswing access only)",
            "tier": "frontier",
            "recommended_roles": ("brain", "review", "design_visual"),
            "reasoning_efforts": ("low", "medium", "high", "xhigh", "max"),
        },
        {
            "model_id": "opus",
            "label": "Claude Opus tier alias",
            "tier": "frontier",
            "recommended_roles": ("brain", "review", "design_visual"),
            "reasoning_efforts": ("low", "medium", "high", "xhigh", "max"),
        },
        {
            "model_id": "sonnet",
            "label": "Claude standard tier alias",
            "tier": "standard",
            "recommended_roles": ("implementation",),
            "reasoning_efforts": ("low", "medium", "high", "xhigh", "max"),
        },
        {
            "model_id": "haiku",
            "label": "Claude fast tier alias",
            "tier": "fast",
            "recommended_roles": ("docs", "research"),
            "reasoning_efforts": ("low", "medium", "high", "xhigh", "max"),
        },
    ),
}

# ONE routing rule, two model tables.
#
# Routing is expressed as semantic CATEGORIES -- what kind of thinking a unit
# needs -- and a role or scale is resolved by naming the categories that serve
# it. This is the rule the omo config already uses, and adopting it here means a
# user with an omo config and a user without one go through the SAME rule
# engine; only the category->model table differs. Previously the built-ins were
# a hand-written per-role table that had to be kept in sync with omo's semantics
# by hand, and drifted from them.
#
# The local-inventory module imports these three names rather than restating
# them, which is why the vocabulary lives here: that module already depends on
# this one (`model_family`), and the reverse direction is policy-gated -- by a
# gate that greps THIS file's source, so do not name that module here.
MODEL_CATEGORIES: Final[tuple[str, ...]] = (
    "ultrabrain",
    "deep",
    "architect",
    "unspecified-high",
    "unspecified-low",
    "quick",
    "writing",
    "visual-engineering",
    "artistry",
)

_CATEGORY_ALIASES: Final[dict[str, str]] = {
    "ultra-brain": "ultrabrain",
    "brain": "ultrabrain",
    "high": "unspecified-high",
    "low": "unspecified-low",
    "fast": "quick",
    "write": "writing",
    "writer": "writing",
    "visual": "visual-engineering",
    "creative": "artistry",
    "arch": "architect",
}
_ULW_CATEGORY_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9_-])/?ulw-([A-Za-z0-9_-]+)(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)


def canonical_model_category(value: object) -> str:
    """Normalize one explicit OMO/ULW category or return an empty sentinel."""
    normalized = str(value or "").strip().casefold().replace("_", "-")
    if normalized.startswith("/ulw-"):
        normalized = normalized[5:]
    elif normalized.startswith("ulw-"):
        normalized = normalized[4:]
    normalized = _CATEGORY_ALIASES.get(normalized, normalized)
    return normalized if normalized in MODEL_CATEGORIES else ""


def category_from_text(message: str) -> str:
    """Extract only an explicit ``ulw-*`` category marker from natural text."""
    for match in _ULW_CATEGORY_RE.finditer(str(message or "")):
        if category := canonical_model_category(match.group(1)):
            return category
    return ""

# Ordered category sources per role. Where several categories serve one role the
# order decides chain concatenation, and ties break toward the stronger-signal
# category. Review deliberately reuses the high-capability categories --
# reviewer-vs-author separation is advisory handoff text, not a catalog property.
CATEGORY_ROLE_SOURCES: Final[dict[str, tuple[str, ...]]] = {
    # `deep` first, not `ultrabrain`: the composer runs on every split, so its
    # default is the strong tier rather than the deepest one. `ultrabrain` is
    # reserved for work that DECLARES it needs that depth -- `research:deep`
    # and scale `large` -- which is what keeps a declared dial meaningful.
    # `deep` first, not `ultrabrain`: the composer runs on every split, so its
    # default is the strong tier rather than the deepest one. `ultrabrain` is
    # reserved for work that DECLARES it needs that depth -- `research:deep`
    # and scale `large` -- which is what keeps a declared dial meaningful.
    # `unspecified-low` closes the chain so the fallback names a DIFFERENT
    # model rather than repeating the head at a weaker effort.
    "brain": ("deep", "unspecified-low"),
    # `unspecified-high` is omo's name for "the default working model", not for
    # "the strongest one" -- that is `ultrabrain`. So standard implementation
    # heads on it, `small` drops to quick/unspecified-low, and `large` escalates
    # to ultrabrain/deep. All three rungs stay distinct.
    "implementation": ("unspecified-high", "unspecified-low"),
    "design_visual": ("visual-engineering", "artistry"),
    "review": ("unspecified-high", "unspecified-low"),
    "docs": ("writing", "quick"),
    # Read-only investigation lanes: standard depth is the default; the
    # shallow/deep entries resolve only when the unit DECLARES that depth.
    "research": ("unspecified-low", "quick"),
    "research:shallow": ("quick", "unspecified-low"),
    # Strongest first: the chain head is the selection, so a declared `deep`
    # must land on the deepest category rather than reach it as a fallback.
    "research:deep": ("ultrabrain", "deep"),
}

# Declared task scale over the same categories. `standard` is absent because it
# IS the role chain.
CATEGORY_SCALE_SOURCES: Final[dict[str, tuple[str, ...]]] = {
    "small": ("quick", "unspecified-low"),
    "large": ("ultrabrain", "deep", "unspecified-high"),
}

# The built-in category->model table, the fallback for a profile with no local
# inventory. Codex takes vendor model ids; Claude Code takes concrete ids for
# the Fable tier (no alias tracks it) and the `opus` alias for the Opus tier.
CLAUDE_FRONTIER_CHAIN_MODELS: Final[tuple[str, ...]] = ("claude-fable-5-1", "claude-mythos-5-1", "opus")


def _CLAUDE_FRONTIER_CHAIN(effort: str) -> tuple[dict[str, str], ...]:
    return tuple({"model_id": model_id, "reasoning_effort": effort} for model_id in CLAUDE_FRONTIER_CHAIN_MODELS)


BUILTIN_CATEGORY_MODELS: Final[dict[str, dict[str, tuple[dict[str, str], ...]]]] = {
    # Codex: gpt-5-codex is the frontier CODING model, gpt-5 the general one.
    # Every category that means "do the work well" therefore names the coding
    # model, and the light categories name the general one.
    "codex": {
        "ultrabrain": ({"model_id": "gpt-5-codex", "reasoning_effort": "xhigh"},),
        "deep": ({"model_id": "gpt-5-codex", "reasoning_effort": "high"},),
        "architect": ({"model_id": "gpt-5-codex", "reasoning_effort": "xhigh"},),
        "unspecified-high": ({"model_id": "gpt-5-codex", "reasoning_effort": ""},),
        "unspecified-low": ({"model_id": "gpt-5", "reasoning_effort": ""},),
        "quick": ({"model_id": "gpt-5", "reasoning_effort": "low"},),
        "writing": ({"model_id": "gpt-5", "reasoning_effort": ""},),
        "visual-engineering": ({"model_id": "gpt-5-codex", "reasoning_effort": ""},),
        "artistry": ({"model_id": "gpt-5", "reasoning_effort": ""},),
    },
    # Claude Code: every frontier category runs the owner-ordered Claude chain
    # (Fable 5.1 -> Mythos 5.1 -> Opus, 2026-09-02). Mythos 5.1 is Fable 5.1
    # under Project Glasswing access; where the account is not approved the
    # CLI's provider rejection falls the chain through to `opus`, so the tail
    # keeps the previous out-of-the-box behavior. The sonnet/haiku lanes are
    # cost-tier picks below the ordered chain and stay as they were.
    "claude-code": {
        "ultrabrain": _CLAUDE_FRONTIER_CHAIN("xhigh"),
        "deep": _CLAUDE_FRONTIER_CHAIN("high"),
        "architect": _CLAUDE_FRONTIER_CHAIN("xhigh"),
        "unspecified-high": _CLAUDE_FRONTIER_CHAIN(""),
        "unspecified-low": ({"model_id": "sonnet", "reasoning_effort": ""},),
        "quick": ({"model_id": "haiku", "reasoning_effort": ""},),
        "writing": ({"model_id": "haiku", "reasoning_effort": ""},),
        "visual-engineering": _CLAUDE_FRONTIER_CHAIN(""),
        "artistry": ({"model_id": "sonnet", "reasoning_effort": ""},),
    },
}


def merged_category_chain(
    category_models: Mapping[str, object],
    categories: tuple[str, ...],
) -> tuple[dict[str, str], ...]:
    """Concatenate the named categories' entries, first occurrence winning.

    Shared by the built-in table here and the locally-derived table the
    inventory side builds, so both answer a role or a scale the same way.

    Deduplicated by MODEL, not by (model, effort). A chain is next-candidate
    advice, so a second entry is only useful when it names a DIFFERENT model;
    the same model repeated at a weaker effort is noise, and because the
    strongest category is listed first, first-wins keeps the right one.
    """
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for category in categories:
        entries = category_models.get(category)
        if not isinstance(entries, (list, tuple)):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            model_id = str(entry.get("model_id", ""))
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            merged.append({"model_id": model_id, "reasoning_effort": str(entry.get("reasoning_effort", ""))})
    return tuple(merged)


def _derived_role_chains() -> dict[str, dict[str, tuple[dict[str, str], ...]]]:
    return {
        profile: {
            role: chain
            for role, categories in CATEGORY_ROLE_SOURCES.items()
            if ":" not in role and (chain := merged_category_chain(category_models, categories))
        }
        for profile, category_models in BUILTIN_CATEGORY_MODELS.items()
    }


# Ordered per-role chains: head is the deterministic selection, later entries
# are prepared next-candidate advice. An entry's reasoning_effort applies only
# when the user requested none (requested > chain-entry > none). Derived from
# the category table above rather than hand-written, so a category change moves
# every role that names it.
ROLE_MODEL_CHAINS: Final[dict[str, dict[str, tuple[dict[str, str], ...]]]] = _derived_role_chains()

# Explicit research-depth dial (surveyed autorouting consensus: depth is a
# DECLARED dial, never inferred from text; standard is the default, shallow
# is the declared saving, deep is the declared escalation). `standard` has
# no entry here on purpose: it IS the role chain above.
RESEARCH_DEPTHS: Final[tuple[str, ...]] = ("shallow", "standard", "deep")

def _derived_depth_chains() -> dict[str, dict[str, tuple[dict[str, str], ...]]]:
    return {
        profile: {
            depth: chain
            for depth in ("shallow", "deep")
            if (chain := merged_category_chain(category_models, CATEGORY_ROLE_SOURCES[f"research:{depth}"]))
        }
        for profile, category_models in BUILTIN_CATEGORY_MODELS.items()
    }


RESEARCH_DEPTH_CHAINS: Final[dict[str, dict[str, tuple[dict[str, str], ...]]]] = _derived_depth_chains()

# Declared task-scale dial. Role says WHAT the unit does; scale says HOW MUCH
# of it there is, and the two are independent -- a one-line fix and a forty-file
# migration are both `implementation`, and routing them to the same model wastes
# a frontier model on the first and starves the second.
#
# Same contract as the research-depth dial above and for the same reason: scale
# is DECLARED by the unit, never inferred from the request text. Inferring
# "large" from words like "refactor everything" would make model cost depend on
# phrasing, which is exactly the unpredictability the depth dial was written to
# avoid. `standard` has no entry here on purpose: it IS the role chain.
#
# Scale covers every role EXCEPT `research`, which already has `depth`. A unit
# that declares both keeps depth for research and records scale as skipped.
TASK_SCALES: Final[tuple[str, ...]] = ("small", "standard", "large")

def _derived_scale_chains() -> dict[str, dict[str, tuple[dict[str, str], ...]]]:
    return {
        profile: {
            scale: chain
            for scale, categories in CATEGORY_SCALE_SOURCES.items()
            if (chain := merged_category_chain(category_models, categories))
        }
        for profile, category_models in BUILTIN_CATEGORY_MODELS.items()
    }


TASK_SCALE_CHAINS: Final[dict[str, dict[str, tuple[dict[str, str], ...]]]] = _derived_scale_chains()

# Model-family prefixes mirror the dynamic-workflow target classifier so both
# surfaces name families the same way; bare Claude tier aliases fold into the
# claude family because the claude CLI resolves them to concrete claude models,
# and the bare Fable-tier names (`fable`, `mythos`) fold the same way because
# users name the run that way in chat ("use fable") and the family-level
# calibration must attach to it rather than the generic fallback.
_MODEL_FAMILY_PREFIXES: Final[tuple[tuple[str, str], ...]] = (
    ("gpt-", "gpt"),
    ("glm-", "glm"),
    ("claude-", "claude"),
    ("gemini-", "gemini"),
    ("grok-", "grok"),
    ("qwen-", "qwen"),
    ("kimi-", "kimi"),
    ("mistral-", "mistral"),
    ("minimax-", "minimax"),
    ("llama-", "llama"),
    ("deepseek-", "deepseek"),
    ("codestral-", "codestral"),
    ("solar-", "solar"),
)
_MODEL_FAMILY_ALIASES: Final[tuple[tuple[str, str], ...]] = (
    ("openai-gpt-", "gpt"),
    ("anthropic-claude-", "claude"),
    ("qwen3-", "qwen"),
)
_MODEL_FAMILY_ALIAS_EXCLUSIONS: Final[tuple[str, ...]] = ("openai-gpt-image-",)
_CLAUDE_TIER_ALIASES: Final[frozenset[str]] = frozenset({"opus", "sonnet", "haiku", "fable", "mythos"})


def model_family(model_id: str) -> str:
    normalized = str(model_id or "").strip().casefold()
    if not normalized:
        return ""
    # Provider-prefixed ids (`opencode/kimi-k3`, `anthropic/claude-opus-5`)
    # classify by the model segment: the provider names where it runs, the
    # family names what it is.
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[1]
    if normalized in _CLAUDE_TIER_ALIASES:
        return "claude"
    if normalized.startswith(_MODEL_FAMILY_ALIAS_EXCLUSIONS):
        return "unknown"
    for prefix, family in _MODEL_FAMILY_ALIASES:
        if normalized.startswith(prefix):
            return family
    for prefix, family in _MODEL_FAMILY_PREFIXES:
        if normalized.startswith(prefix):
            return family
    return "unknown"


def resolve_model_route(
    executor_profile: str,
    *,
    requested_model: str = "",
    requested_effort: str = "",
    role: str = "",
    requested_domain: str = "",
    requested_depth: str = "",
    requested_scale: str = "",
    requested_category: str = "",
    chains: Mapping[str, Mapping[str, tuple[Mapping[str, str], ...]]] | None = None,
    category_config: Mapping[str, object] | None = None,
    local_catalog: Mapping[str, object] | None = None,
    active_models: Iterable[str | Mapping[str, object]] | None = None,
    recommendation_overrides: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return the deterministic prepared model route for one executor profile.

    Four stages, each recorded in `attempted[]`: an explicitly requested model
    always wins (passthrough, never rejected); otherwise a declared role routes
    to its chain head; a role whose chain is missing is an explicit choice;
    no data leaves the executor CLI default in place as a named outcome.

    Injection precedence — the injected sources never apply to the same
    profile: `chains` (tests only) overrides role chains for profiles WITH a
    built-in catalog and wins over `category_config`; `category_config` (the
    validated `omh_category_maestro/v1` payload read by the caller — I/O stays
    in the caller) merges the operator's per-category chains over the built-in
    table for built-in-catalog profiles only, feeding every path that consults
    that table (explicit category, role, research depth, task scale) and
    recording `catalog_kind: "operator_category_config"` plus the config
    fingerprint — the kind names which TABLE was consulted for this profile,
    not that the override changed the outcome: a route whose chain happens to
    match the built-in one, or that a requested model won over, still records
    the operator basis because that is the table that would have adjudicated;
    `local_catalog` (a `local_model_catalog/v1` payload derived by
    the caller from an observed inventory — I/O stays in the caller, this
    function remains pure) is consulted ONLY when the profile has no built-in
    catalog and the payload names this profile. A route resolved from a local
    catalog records `catalog_kind: "local_inventory"` plus the catalog's
    `fingerprint` so the frozen record names its exact basis, and a local
    catalog never gains effort authority — observed config variants are
    evidence of use, not of a model's effort vocabulary. An absent
    `catalog_fingerprint` on any route means "no local basis was consulted",
    never "unknown basis" — v1 routes and built-in-catalog routes correctly
    carry none.

    `requested_domain` is explicit unit data (never inferred from text). When
    a locally-derived chain resolves and the catalog's affinity vocabulary
    knows the domain, chain entries from affine families are stably reordered
    to the front — an advisory reorder recorded in `attempted[]`, never a
    veto: every entry stays in the chain and a requested model still wins.
    Outside a local catalog the domain is recorded and explicitly skipped.

    `requested_depth` is the research-lane dial (shallow|standard|deep) —
    explicit unit data, never inferred. It applies only to `role="research"`:
    shallow/deep swap in their declared depth chain, standard (or no depth)
    keeps the role chain. On other roles or unknown vocabulary the depth is
    recorded and explicitly skipped.
    """
    profile = str(executor_profile or "").strip().casefold()
    raw_role = str(role or "").strip()
    normalized_role = _normalized_role(raw_role)
    role_reasons: list[str] = []
    if raw_role and not normalized_role:
        # A declared role that fails to normalize must be named, not erased:
        # this reason lands in frozen contracts, so "no role was requested"
        # would be a false statement about the request.
        role_reasons.append(
            f"Role {raw_role!r} is not a known role ({', '.join(MODEL_ROLES)}); it was ignored."
        )
    model = str(requested_model or "").strip()
    effort = str(requested_effort or "").strip().casefold()
    domain = str(requested_domain or "").strip().casefold().replace("-", "_")
    depth = str(requested_depth or "").strip().casefold()
    scale = str(requested_scale or "").strip().casefold()
    raw_category = str(requested_category or "").strip()
    category = canonical_model_category(raw_category)
    if raw_category and not category:
        raise ValueError(
            f"unsupported model category {raw_category!r}; expected one of {', '.join(MODEL_CATEGORIES)}"
        )
    if profile == "hermes" and active_models is not None:
        return _resolve_hermes_recommendation_route(
            role=normalized_role,
            requested_model=model,
            requested_effort="off" if effort == "none" else effort,
            requested_domain=domain,
            requested_depth=depth,
            requested_scale=scale,
            requested_category=category,
            active_models=active_models,
            recommendation_overrides=recommendation_overrides,
            role_reasons=role_reasons,
        )
    options = EXECUTOR_MODEL_OPTIONS.get(profile, ())
    catalog_kind = MODEL_CATALOG_KIND
    catalog_fingerprint: dict[str, object] | None = None
    effort_authoritative = True
    local_chains: Mapping[str, tuple[Mapping[str, str], ...]] = {}
    if not options and _local_catalog_applies(profile, local_catalog):
        raw_options = local_catalog.get("options", []) if isinstance(local_catalog, Mapping) else []
        resolved_options = tuple(option for option in raw_options if isinstance(option, Mapping))
        if resolved_options:
            # The local basis is claimed only once it demonstrably exists: an
            # empty or corrupt payload must fall through to the executor
            # default WITHOUT a fingerprint, or the frozen record would name
            # a basis that never adjudicated anything.
            options = resolved_options
            raw_chains = local_catalog.get("chains", {}) if isinstance(local_catalog, Mapping) else {}
            local_chains = raw_chains if isinstance(raw_chains, Mapping) else {}
            raw_fingerprint = local_catalog.get("fingerprint") if isinstance(local_catalog, Mapping) else None
            catalog_fingerprint = dict(raw_fingerprint) if isinstance(raw_fingerprint, Mapping) else None
            catalog_kind = "local_inventory"
            effort_authoritative = False
        else:
            role_reasons.append(
                "A local model catalog was offered but carried no usable options; it was not consulted."
            )
    # The operator's category-maestro config applies only to profiles WITH a
    # built-in category table (the dispatchable CLIs); catalogless profiles
    # keep the local-inventory path as their single override source. `chains`
    # stays the tests-only injection and wins over the operator table.
    operator_categories: Mapping[str, object] | None = None
    if (
        category_config is not None
        and chains is None
        and catalog_kind == MODEL_CATALOG_KIND
        and profile in BUILTIN_CATEGORY_MODELS
    ):
        config_profiles = category_config.get("profiles") if isinstance(category_config, Mapping) else None
        raw_operator = config_profiles.get(profile) if isinstance(config_profiles, Mapping) else None
        if isinstance(raw_operator, Mapping) and raw_operator:
            operator_categories = raw_operator
            catalog_kind = "operator_category_config"
            raw_config_fingerprint = category_config.get("fingerprint")
            if isinstance(raw_config_fingerprint, Mapping):
                catalog_fingerprint = dict(raw_config_fingerprint)
    effective_categories: Mapping[str, object] = (
        {**BUILTIN_CATEGORY_MODELS.get(profile, {}), **dict(operator_categories)}
        if operator_categories is not None
        else BUILTIN_CATEGORY_MODELS.get(profile, {})
    )
    candidates = [dict(option) for option in options]
    if catalog_kind == "local_inventory":
        role_chain = tuple(local_chains.get(normalized_role, ())) if normalized_role else ()
    elif operator_categories is not None:
        role_chain = (
            merged_category_chain(effective_categories, CATEGORY_ROLE_SOURCES.get(normalized_role, ()))
            if normalized_role
            else ()
        )
    else:
        chain_table = ROLE_MODEL_CHAINS if chains is None else chains
        role_chain = tuple(chain_table.get(profile, {}).get(normalized_role, ())) if normalized_role else ()
    attempted: list[dict[str, str]] = []
    if operator_categories is not None:
        attempted.append(
            {
                "stage": "category_config",
                "outcome": "applied",
                "reason": (
                    "operator category-maestro config overrides categories "
                    f"({', '.join(sorted(str(name) for name in operator_categories))}) for `{profile}`"
                ),
            }
        )
    if category:
        if catalog_kind == "local_inventory":
            raw_categories = local_catalog.get("categories", {}) if isinstance(local_catalog, Mapping) else {}
            category_chain = raw_categories.get(category, ()) if isinstance(raw_categories, Mapping) else ()
        else:
            category_chain = effective_categories.get(category, ())
        role_chain = tuple(entry for entry in category_chain if isinstance(entry, Mapping))
        attempted.append(
            {
                "stage": "category_chain",
                "outcome": "applied" if role_chain else "unavailable",
                "reason": f"explicit category `{category}` selects its chain independently of role `{normalized_role or 'none'}`",
            }
        )
    operator_table = effective_categories if operator_categories is not None else None
    if depth and not category:
        role_chain = _depth_selected_chain(
            depth,
            normalized_role,
            profile,
            role_chain,
            local_chains if catalog_kind == "local_inventory" else None,
            attempted,
            operator_table=operator_table,
        )
    if scale and not category:
        role_chain = _scale_selected_chain(
            scale,
            normalized_role,
            profile,
            role_chain,
            local_chains if catalog_kind == "local_inventory" else None,
            depth,
            attempted,
            operator_table=operator_table,
        )
    if domain:
        role_chain = _domain_ordered_chain(
            domain,
            role_chain,
            local_catalog if catalog_kind == "local_inventory" else None,
            attempted,
        )

    if model:
        attempted.append(
            {"stage": "requested_model", "outcome": "selected", "reason": f"request names `{model}`"}
        )
        selected_effort, effort_change = _selected_effort(
            options, effort, "", model, authoritative=effort_authoritative
        )
        return _route_payload(
            profile,
            status="routed",
            provenance="request_named_model",
            role=normalized_role,
            selected_model=model,
            selected_reasoning_effort=selected_effort,
            effort_change=effort_change,
            catalog_kind=catalog_kind,
            catalog_fingerprint=catalog_fingerprint,
            domain=domain,
            depth=depth,
            category=category,
            chain=_chain_payload(options, role_chain, selected_model=""),
            attempted=attempted,
            candidates=candidates,
            reasons=role_reasons + [f"The request names `{model}` directly, so the catalog is advisory only."],
        )
    attempted.append({"stage": "requested_model", "outcome": "skipped", "reason": "no model requested"})

    if not options:
        attempted.append(
            {"stage": "role_chain", "outcome": "skipped", "reason": "profile has no model catalog"}
        )
        attempted.append(
            {"stage": "executor_default", "outcome": "selected", "reason": "no catalog; executor CLI default applies"}
        )
        selected_effort, effort_change = _selected_effort(
            options, effort, "", "", authoritative=effort_authoritative
        )
        return _route_payload(
            profile,
            status="no_model_catalog",
            provenance="no_catalog",
            role=normalized_role,
            selected_reasoning_effort=selected_effort,
            effort_change=effort_change,
            catalog_kind=catalog_kind,
            catalog_fingerprint=catalog_fingerprint,
            domain=domain,
            depth=depth,
            category=category,
            chain=[],
            attempted=attempted,
            candidates=[],
            reasons=role_reasons
            + [
                f"No built-in model catalog exists for `{profile or 'unknown'}`; the executor CLI default applies.",
            ],
        )

    if normalized_role or category:
        if role_chain:
            head = role_chain[0]
            selected = str(head.get("model_id", ""))
            selected_stage = "category_chain" if category else "role_chain"
            attempted.append(
                {
                    "stage": selected_stage,
                    "outcome": "selected",
                    "reason": (
                        f"chain head `{selected}` for category `{category}`"
                        if category
                        else f"chain head `{selected}` for role `{normalized_role}`"
                    ),
                }
            )
            selected_effort, effort_change = _selected_effort(
                options, effort, str(head.get("reasoning_effort", "") or ""), selected,
                authoritative=effort_authoritative,
            )
            return _route_payload(
                profile,
                status="routed",
                provenance="category_chain_head" if category else "role_chain_head",
                role=normalized_role,
                selected_model=selected,
                selected_reasoning_effort=selected_effort,
                effort_change=effort_change,
                catalog_kind=catalog_kind,
                catalog_fingerprint=catalog_fingerprint,
                domain=domain,
                depth=depth,
                category=category,
                chain=_chain_payload(options, role_chain, selected_model=selected),
                attempted=attempted,
                candidates=candidates,
                reasons=role_reasons
                + [
                    (
                        f"Category `{category}` routes to its ordered chain head for `{profile}`; "
                        f"role `{normalized_role or 'none'}` remains independent metadata."
                        if category
                        else f"Role `{normalized_role}` routes to its ordered chain head for `{profile}`."
                    ),
                ],
            )
        # Unreachable-by-construction under the bidirectional parity gate
        # (every catalog profile carries a chain for every role); kept as a
        # structural net so a future catalog edit fails loudly instead of
        # guessing. Tested via a constructed chain-gap dict.
        attempted.append(
            {"stage": "role_chain", "outcome": "unavailable", "reason": f"no chain declared for role `{normalized_role}`"}
        )
        selected_effort, effort_change = _selected_effort(
            options, effort, "", "", authoritative=effort_authoritative
        )
        return _route_payload(
            profile,
            status="choice_required",
            provenance="role_unchained",
            role=normalized_role,
            selected_reasoning_effort=selected_effort,
            effort_change=effort_change,
            catalog_kind=catalog_kind,
            catalog_fingerprint=catalog_fingerprint,
            domain=domain,
            depth=depth,
            category=category,
            chain=[],
            attempted=attempted,
            candidates=candidates,
            reasons=role_reasons
            + [
                f"Role `{normalized_role}` has no declared chain for `{profile}`; "
                f"pick one of the {len(candidates)} catalog options or name a model.",
            ],
        )
    attempted.append({"stage": "role_chain", "outcome": "skipped", "reason": "no role declared"})

    attempted.append(
        {"stage": "executor_default", "outcome": "selected", "reason": "no model or role; executor CLI default applies"}
    )
    unrouted_reason = (
        "No model or role was requested, so the executor CLI default model applies."
        if not raw_role
        else "No usable model or role remained, so the executor CLI default model applies."
    )
    selected_effort, effort_change = _selected_effort(
        options, effort, "", "", authoritative=effort_authoritative
    )
    return _route_payload(
        profile,
        status="model_unrouted",
        provenance="executor_default",
        role=normalized_role,
        selected_reasoning_effort=selected_effort,
        effort_change=effort_change,
        catalog_kind=catalog_kind,
        catalog_fingerprint=catalog_fingerprint,
        domain=domain,
        depth=depth,
        category=category,
        chain=[],
        attempted=attempted,
        candidates=candidates,
        reasons=role_reasons + [unrouted_reason],
    )


def model_route_for_unit(
    unit: Mapping[str, object],
    executor_target: str,
    local_catalog: Mapping[str, object] | None = None,
    category_config: Mapping[str, object] | None = None,
) -> dict[str, object] | None:
    """Return the prepared model route for a fanout unit, or None when unrouted.

    `local_catalog` and `category_config` are passed through verbatim; this
    function stays pure and the resolver's precedence rules decide whether
    either applies.
    """
    model = str(unit.get("model", "") or "").strip()
    effort = str(unit.get("reasoning_effort", "") or "").strip()
    role = str(unit.get("role", "") or "").strip()
    category = str(unit.get("category", unit.get("model_category", "")) or "").strip()
    if not model and not effort and not role and not category:
        # A declared domain alone never triggers routing: it advises chain
        # order, it does not request a model.
        return None
    return resolve_model_route(
        executor_target,
        requested_model=model,
        requested_effort=effort,
        role=role,
        requested_domain=str(unit.get("domain", "") or "").strip(),
        requested_depth=str(unit.get("depth", "") or "").strip(),
        requested_scale=str(unit.get("scale", "") or "").strip(),
        requested_category=category,
        category_config=category_config,
        local_catalog=local_catalog,
    )


def _resolve_hermes_recommendation_route(
    *,
    role: str,
    requested_model: str,
    requested_effort: str,
    requested_domain: str,
    requested_depth: str,
    requested_scale: str,
    requested_category: str,
    active_models: Iterable[str | Mapping[str, object]],
    recommendation_overrides: Mapping[str, object] | None,
    role_reasons: list[str],
) -> dict[str, object]:
    """Resolve Hermes against editorial policy and confirmed active models.

    Hermes owns native provider bindings rather than an OMO executor catalog.
    Recommendation resolution therefore consumes only the caller-confirmed
    active set. The local OMO catalog is intentionally absent from this path.
    """
    from .model_recommendations import resolve_model_recommendation

    attempted: list[dict[str, str]] = []
    active = tuple(active_models)
    category = requested_category or _recommendation_category(role, requested_depth, requested_scale)
    selector = {"category": category}

    if requested_model:
        explicit = resolve_model_recommendation(
            owner="hermes",
            active_models=active,
            explicit_model=requested_model,
            **selector,
        )
        if explicit["status"] != "resolved":
            attempted.append(
                {
                    "stage": "requested_model",
                    "outcome": "unavailable",
                    "reason": (
                        f"explicit model `{requested_model}` is not confirmed active for Hermes; "
                        "recommendation fallthrough is frozen"
                    ),
                }
            )
            payload = _route_payload(
                "hermes",
                status="choice_required",
                provenance="request_named_model_unavailable",
                role=role,
                selected_reasoning_effort=requested_effort,
                catalog_kind="editorial_recommendations",
                domain=requested_domain,
                depth=requested_depth,
                category=category,
                chain=[],
                attempted=attempted,
                candidates=[],
                reasons=role_reasons
                + [
                    f"The explicit Hermes model `{requested_model}` is unavailable; "
                    "no recommendation was substituted."
                ],
            )
            payload["requested_model"] = requested_model
            payload["recommendation"] = explicit
            return payload
        selected = _recommendation_binding(explicit)
        attempted.append(
            {
                "stage": "requested_model",
                "outcome": "selected",
                "reason": f"request names confirmed-active Hermes model `{selected}`",
            }
        )
        payload = _route_payload(
            "hermes",
            status="routed",
            provenance="request_named_model",
            role=role,
            selected_model=selected,
            selected_reasoning_effort=requested_effort,
            catalog_kind="editorial_recommendations",
            domain=requested_domain,
            depth=requested_depth,
            category=category,
            chain=_recommendation_chain(explicit, selected_model=selected),
            attempted=attempted,
            candidates=[],
            reasons=role_reasons + ["The explicit confirmed-active Hermes model wins over recommendation policy."],
        )
        payload["recommendation"] = explicit
        return payload

    attempted.append({"stage": "requested_model", "outcome": "skipped", "reason": "no model requested"})
    recommendation = resolve_model_recommendation(
        owner="hermes",
        active_models=active,
        overrides=recommendation_overrides,
        **selector,
    )
    chain = (
        _hermes_recommendation_chain(recommendation, active_models=active)
        if recommendation["status"] == "resolved"
        else []
    )
    if requested_domain:
        chain, recommendation = _stable_domain_recommendation_chain(
            requested_domain,
            chain,
            attempted,
            base_resolution=recommendation,
            active_models=active,
            recommendation_overrides=recommendation_overrides,
        )
    if not chain:
        attempted.append(
            {
                "stage": "recommendation_chain",
                "outcome": "owner_default",
                "reason": "no editorial candidate is confirmed active for Hermes",
            }
        )
        attempted.append(
            {
                "stage": "executor_default",
                "outcome": "selected",
                "reason": "no confirmed recommendation; Hermes default model applies",
            }
        )
        payload = _route_payload(
            "hermes",
            status="model_unrouted",
            provenance="executor_default",
            role=role,
            selected_reasoning_effort=requested_effort,
            catalog_kind="editorial_recommendations",
            domain=requested_domain,
            depth=requested_depth,
            category=category,
            chain=[],
            attempted=attempted,
            candidates=[],
            reasons=role_reasons
            + [
                "No confirmed-active Hermes recommendation could be resolved, "
                "so the Hermes default model remains in effect."
            ],
        )
        payload["recommendation"] = recommendation
        return payload

    selected = str(chain[0]["model_id"])
    selected_effort = requested_effort or str(chain[0].get("reasoning_effort", ""))
    last_resort = str(recommendation.get("source", "")) == "last_resort_chain"
    attempted.append(
        {
            "stage": "recommendation_chain",
            "outcome": "last_resort" if last_resort else "selected",
            "reason": (
                "no confirmed-active candidate in the selected recommendation chains; "
                f"shared last-resort head `{selected}` selected"
                if last_resort
                else f"confirmed-active recommendation chain head `{selected}` selected"
            ),
        }
    )
    payload = _route_payload(
        "hermes",
        status="routed",
        provenance="recommendation_chain_head",
        role=role,
        selected_model=selected,
        selected_reasoning_effort=selected_effort,
        catalog_kind="editorial_recommendations",
        domain=requested_domain,
        depth=requested_depth,
        category=category,
        chain=[
            dict(entry, position=position, selected=position == 0)
            for position, entry in enumerate(chain)
        ],
        attempted=attempted,
        candidates=[],
        reasons=role_reasons
        + ["Hermes used editable editorial order filtered to caller-confirmed active models."],
    )
    payload["recommendation"] = recommendation
    return payload


def _recommendation_category(role: str, depth: str, scale: str) -> str:
    if role == "research" and depth == "deep":
        return "ultrabrain"
    if scale == "large":
        return "ultrabrain"
    if scale == "small":
        return "unspecified-low"
    sources = CATEGORY_ROLE_SOURCES.get(role, ("unspecified-high",))
    return sources[0]


def _recommendation_binding(resolution: Mapping[str, object]) -> str:
    selected = resolution.get("selected")
    if not isinstance(selected, Mapping):
        return ""
    provider = str(selected.get("provider", ""))
    model_id = str(selected.get("model_id", ""))
    return model_id if "/" in model_id or not provider else f"{provider}/{model_id}"


def _recommendation_chain(
    resolution: Mapping[str, object],
    *,
    selected_model: str = "",
) -> list[dict[str, object]]:
    projection = resolution.get("projection")
    if not isinstance(projection, Mapping):
        return []
    raw_chain = projection.get("chain")
    if not isinstance(raw_chain, list):
        binding = _recommendation_binding(resolution)
        selected = resolution.get("selected")
        if not binding or not isinstance(selected, Mapping):
            return []
        raw_chain = [selected]
    chain: list[dict[str, object]] = []
    for position, entry in enumerate(raw_chain):
        if not isinstance(entry, Mapping):
            continue
        provider = str(entry.get("provider", ""))
        model_id = str(entry.get("model_id", ""))
        binding = model_id if "/" in model_id or not provider else f"{provider}/{model_id}"
        chain.append(
            {
                "position": position,
                "model_id": binding,
                "reasoning_effort": str(entry.get("reasoning_effort", "")),
                "tier": "",
                "label": str(entry.get("model_alias", "")),
                "selected": bool(selected_model) and binding == selected_model and position == 0,
            }
        )
    return chain


def _hermes_recommendation_chain(
    resolution: Mapping[str, object],
    *,
    active_models: Iterable[str | Mapping[str, object]],
) -> list[dict[str, object]]:
    """Expand a Hermes binding projection into its eligible editorial order."""
    from .model_recommendations import resolve_model_recommendation

    active = tuple(active_models)
    available = resolution.get("available_chain")
    if not isinstance(available, list):
        return _recommendation_chain(resolution)
    selected = resolution.get("selected")
    chain: list[dict[str, object]] = []
    for alias in available:
        candidate = (
            resolution
            if isinstance(selected, Mapping) and str(selected.get("model_alias", "")) == str(alias)
            else resolve_model_recommendation(
                owner="hermes",
                active_models=active,
                explicit_model=str(alias),
            )
        )
        chain.extend(_recommendation_chain(candidate))
    return chain


def _stable_domain_recommendation_chain(
    domain: str,
    base_chain: list[dict[str, object]],
    attempted: list[dict[str, str]],
    *,
    base_resolution: dict[str, object],
    active_models: Iterable[str | Mapping[str, object]],
    recommendation_overrides: Mapping[str, object] | None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    from .model_recommendations import resolve_model_recommendation

    domain_resolution = resolve_model_recommendation(
        owner="hermes",
        active_models=active_models,
        domain=domain,
        overrides=recommendation_overrides,
    )
    promoted = _hermes_recommendation_chain(
        domain_resolution,
        active_models=active_models,
    )
    if not promoted:
        attempted.append(
            {
                "stage": "domain_affinity",
                "outcome": "no_affine_candidate",
                "reason": f"domain `{domain}` has no confirmed-active editorial candidate; role chain kept",
            }
        )
        return base_chain, base_resolution

    if str(domain_resolution.get("source", "")) == "last_resort_chain" and base_chain:
        base_is_last_resort = str(base_resolution.get("source", "")) == "last_resort_chain"
        attempted.append(
            {
                "stage": "domain_affinity",
                "outcome": (
                    "shared_last_resort_already_selected"
                    if base_is_last_resort
                    else "last_resort_deferred"
                ),
                "reason": (
                    f"domain `{domain}` exhausted its affine chain; the shared last resort "
                    "cannot outrank an already resolved category or role chain"
                ),
            }
        )
        return base_chain, base_resolution

    seen = {str(entry["model_id"]) for entry in promoted}
    reordered = promoted + [entry for entry in base_chain if str(entry["model_id"]) not in seen]
    attempted.append(
        {
            "stage": "domain_affinity",
            "outcome": "reordered" if reordered != base_chain else "already_ordered",
            "reason": (
                f"domain `{domain}` promoted its confirmed-active editorial chain in stable order; "
                "no entry removed"
            ),
        }
    )
    return reordered, domain_resolution


def route_provenance(route: Mapping[str, object] | object) -> tuple[str, str]:
    """Return (value, vocabulary) for a route of any schema version.

    The sole sanctioned accessor for reading provenance back from a route —
    including v1 payloads embedded in frozen fanout contracts. A v1 `source`
    is returned verbatim (never translated into v2 chain vocabulary: the
    record must keep saying exactly what was written). vocabulary is one of
    "v1" | "v2" | "unknown"; anything malformed reads ("unknown", "unknown").
    """
    if not isinstance(route, Mapping):
        return ("unknown", "unknown")
    version = str(route.get("schema_version", "") or "")
    if version == CODING_MODEL_ROUTE_SCHEMA_VERSION:
        value = str(route.get("provenance", "") or "")
        if value in MODEL_ROUTE_PROVENANCES:
            return (value, "v2")
        return ("unknown", "unknown")
    if version == CODING_MODEL_ROUTE_V1_SCHEMA_VERSION:
        value = str(route.get("source", "") or "")
        if value in _V1_MODEL_ROUTE_SOURCES:
            return (value, "v1")
        return ("unknown", "unknown")
    return ("unknown", "unknown")


def _normalized_role(role: str) -> str:
    normalized = str(role or "").strip().casefold().replace("-", "_")
    return normalized if normalized in MODEL_ROLES else ""


def _scale_selected_chain(
    scale: str,
    normalized_role: str,
    profile: str,
    role_chain: tuple[Mapping[str, str], ...],
    local_chains: Mapping[str, object] | None,
    depth: str,
    attempted: list[dict[str, str]],
    *,
    operator_table: Mapping[str, object] | None = None,
) -> tuple[Mapping[str, str], ...]:
    """Swap in the declared task-scale chain, recording the outcome.

    Mirrors `_depth_selected_chain` deliberately: scale never infers, unknown
    vocabulary keeps the chain untouched with a named skip, and `standard` is
    the role chain by definition. The research role is excluded because it
    already has `depth`; a unit declaring both keeps depth and is told so
    rather than having one dial silently overwrite the other.
    """
    if normalized_role == "research":
        attempted.append(
            {
                "stage": "task_scale",
                "outcome": "skipped",
                "reason": (
                    f"scale `{scale}` recorded; the research role uses the depth dial"
                    + (f" (`{depth}` declared)" if depth else "")
                ),
            }
        )
        return role_chain
    if scale not in TASK_SCALES:
        attempted.append(
            {
                "stage": "task_scale",
                "outcome": "unknown_scale",
                "reason": f"scale `{scale}` is not in ({', '.join(TASK_SCALES)}); role chain kept",
            }
        )
        return role_chain
    if scale == "standard":
        attempted.append(
            {"stage": "task_scale", "outcome": "standard", "reason": "standard is the role chain"}
        )
        return role_chain
    if local_chains is not None:
        scale_chain = local_chains.get(f"{normalized_role}:{scale}")
        if isinstance(scale_chain, (list, tuple)) and scale_chain:
            attempted.append(
                {
                    "stage": "task_scale",
                    "outcome": "applied",
                    "reason": f"declared `{scale}` task scale uses its locally-derived chain",
                }
            )
            return tuple(entry for entry in scale_chain if isinstance(entry, Mapping))
        attempted.append(
            {
                "stage": "task_scale",
                "outcome": "no_scale_chain",
                "reason": f"the local catalog derives no `{scale}` chain for `{normalized_role}`; role chain kept",
            }
        )
        return role_chain
    if operator_table is not None:
        scale_chain = merged_category_chain(operator_table, CATEGORY_SCALE_SOURCES.get(scale, ()))
    else:
        scale_chain = TASK_SCALE_CHAINS.get(profile, {}).get(scale, ())
    if scale_chain:
        attempted.append(
            {
                "stage": "task_scale",
                "outcome": "applied",
                "reason": f"declared `{scale}` task scale uses its declared chain",
            }
        )
        return tuple(scale_chain)
    attempted.append(
        {
            "stage": "task_scale",
            "outcome": "no_scale_chain",
            "reason": f"no `{scale}` scale chain is declared for `{profile}`; role chain kept",
        }
    )
    return role_chain


def _depth_selected_chain(
    depth: str,
    normalized_role: str,
    profile: str,
    role_chain: tuple[Mapping[str, str], ...],
    local_chains: Mapping[str, object] | None,
    attempted: list[dict[str, str]],
    *,
    operator_table: Mapping[str, object] | None = None,
) -> tuple[Mapping[str, str], ...]:
    """Swap in the declared research-depth chain, recording the outcome.

    Depth never infers: unknown vocabulary and non-research roles keep the
    chain untouched with a named skip, and `standard` is the role chain by
    definition.
    """
    if normalized_role != "research":
        attempted.append(
            {
                "stage": "research_depth",
                "outcome": "skipped",
                "reason": f"depth `{depth}` recorded; the depth dial applies to the research role only",
            }
        )
        return role_chain
    if depth not in RESEARCH_DEPTHS:
        attempted.append(
            {
                "stage": "research_depth",
                "outcome": "unknown_depth",
                "reason": f"depth `{depth}` is not in ({', '.join(RESEARCH_DEPTHS)}); standard chain kept",
            }
        )
        return role_chain
    if depth == "standard":
        attempted.append(
            {"stage": "research_depth", "outcome": "standard", "reason": "standard is the role chain"}
        )
        return role_chain
    if local_chains is not None:
        depth_chain = local_chains.get(f"research:{depth}")
        if isinstance(depth_chain, (list, tuple)) and depth_chain:
            attempted.append(
                {
                    "stage": "research_depth",
                    "outcome": "applied",
                    "reason": f"declared `{depth}` research depth uses its locally-derived chain",
                }
            )
            return tuple(entry for entry in depth_chain if isinstance(entry, Mapping))
        attempted.append(
            {
                "stage": "research_depth",
                "outcome": "no_depth_chain",
                "reason": f"the local catalog derives no `{depth}` research chain; standard chain kept",
            }
        )
        return role_chain
    if operator_table is not None:
        depth_chain = merged_category_chain(operator_table, CATEGORY_ROLE_SOURCES.get(f"research:{depth}", ()))
    else:
        depth_chain = RESEARCH_DEPTH_CHAINS.get(profile, {}).get(depth, ())
    if depth_chain:
        attempted.append(
            {
                "stage": "research_depth",
                "outcome": "applied",
                "reason": f"declared `{depth}` research depth uses its declared chain",
            }
        )
        return tuple(depth_chain)
    attempted.append(
        {
            "stage": "research_depth",
            "outcome": "no_depth_chain",
            "reason": f"no `{depth}` research chain is declared for `{profile}`; standard chain kept",
        }
    )
    return role_chain


def _domain_ordered_chain(
    domain: str,
    role_chain: tuple[Mapping[str, str], ...],
    local_catalog: Mapping[str, object] | None,
    attempted: list[dict[str, str]],
) -> tuple[Mapping[str, str], ...]:
    """Stably move affine-family chain entries to the front for a declared domain.

    Advisory only: every entry stays in the chain, the reorder (or the reason
    none happened) is recorded in `attempted[]`, and outside a locally-derived
    catalog the domain is explicitly skipped — built-in chains stay curated.
    """
    if local_catalog is None:
        attempted.append(
            {
                "stage": "domain_affinity",
                "outcome": "skipped",
                "reason": f"domain `{domain}` recorded; affinity reordering applies to locally-derived chains only",
            }
        )
        return role_chain
    affinities = local_catalog.get("domain_affinities", {})
    affine = (
        tuple(str(family) for family in affinities.get(domain, ()))
        if isinstance(affinities, Mapping)
        else ()
    )
    if not affine:
        attempted.append(
            {
                "stage": "domain_affinity",
                "outcome": "unknown_domain",
                "reason": f"domain `{domain}` is not in the catalog's affinity vocabulary; chain order unchanged",
            }
        )
        return role_chain
    if not role_chain:
        attempted.append(
            {"stage": "domain_affinity", "outcome": "skipped", "reason": "no chain to reorder"}
        )
        return role_chain
    front = tuple(entry for entry in role_chain if model_family(str(entry.get("model_id", ""))) in affine)
    rest = tuple(entry for entry in role_chain if model_family(str(entry.get("model_id", ""))) not in affine)
    if not front:
        attempted.append(
            {
                "stage": "domain_affinity",
                "outcome": "no_affine_candidate",
                "reason": f"no chain entry belongs to an affine family ({', '.join(affine)}) for domain `{domain}`",
            }
        )
        return role_chain
    reordered = front + rest
    if reordered == role_chain:
        attempted.append(
            {
                "stage": "domain_affinity",
                "outcome": "already_ordered",
                "reason": f"affine families ({', '.join(affine)}) already lead the chain for domain `{domain}`",
            }
        )
        return role_chain
    attempted.append(
        {
            "stage": "domain_affinity",
            "outcome": "reordered",
            "reason": f"affine families ({', '.join(affine)}) moved ahead for domain `{domain}`; no entry removed",
        }
    )
    return reordered


def _local_catalog_applies(profile: str, local_catalog: Mapping[str, object] | None) -> bool:
    """A local catalog applies only to the profile it names — never to a
    profile with a built-in catalog (the caller gate) and never to a payload
    resolved for some other executor."""
    if not isinstance(local_catalog, Mapping):
        return False
    return str(local_catalog.get("executor_profile", "") or "").strip().casefold() == profile


def _supported_efforts(
    options: tuple[Mapping[str, object], ...], model_id: str
) -> tuple[tuple[str, ...], str]:
    """Return (efforts, authority) with authority "exact_model" | "profile_union".

    Only an exact catalog match grants the catalog authority over a model's
    effort vocabulary. The union fallback exists so a requested effort is never
    silently dropped for a model the catalog has not met — the catalog
    disclaims authority there, so its answer is advisory, never adjudicating.
    An empty options tuple returns ((), "profile_union").
    """
    for option in options:
        if str(option.get("model_id", "")).casefold() == str(model_id or "").casefold():
            return tuple(str(value) for value in option.get("reasoning_efforts", ())), "exact_model"
    union: list[str] = []
    for option in options:
        for value in option.get("reasoning_efforts", ()):
            if str(value) not in union:
                union.append(str(value))
    return tuple(union), "profile_union"


# Efforts are a closed vocabulary shape, unlike model ids: an effort value is
# embedded into a codex `--config key=value` composite, so free text here would
# lean on the third-party TOML parser for containment. Off-catalog efforts are
# accepted only in this shape; anything else falls back to the CLI default.
_EFFORT_SHAPE_CHARSET: Final[frozenset[str]] = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


def _selected_effort(
    options: tuple[Mapping[str, object], ...],
    requested_effort: str,
    chain_effort: str,
    model_id: str,
    *,
    authoritative: bool = True,
) -> tuple[str, dict[str, str] | None]:
    """Resolve the effort and its typed change record.

    Precedence: requested > chain-entry > none. The change record exists only
    when the user requested an effort; chain-supplied efforts never appear in
    it. The ladder downgrades only under exact-model catalog authority — the
    catalog never adjudicates a model it has not met, and a non-authoritative
    catalog (local inventory) never adjudicates at all.
    """
    if requested_effort:
        normalized_effort = "off" if requested_effort == "none" else requested_effort
        supported, authority = _supported_efforts(options, model_id)
        supported = tuple("off" if value == "none" else value for value in supported)
        if not authoritative:
            authority = "profile_union"
        if normalized_effort == "auto":
            return normalized_effort, _effort_change(
                requested_effort,
                normalized_effort,
                "automatic_passthrough",
                "`auto` delegates effort selection to the executor contract",
            )
        if normalized_effort in supported:
            kind = "legacy_alias_normalized" if normalized_effort != requested_effort else "unchanged"
            reason = (
                "legacy `none` normalized to canonical `off`"
                if kind == "legacy_alias_normalized"
                else "supported as requested"
            )
            return normalized_effort, _effort_change(
                requested_effort, normalized_effort, kind, reason
            )
        if normalized_effort in REASONING_EFFORT_LADDER and authority == "exact_model":
            requested_index = REASONING_EFFORT_LADDER.index(normalized_effort)
            for rung in reversed(REASONING_EFFORT_LADDER[: requested_index + 1]):
                if rung in supported:
                    return rung, _effort_change(
                        requested_effort,
                        rung,
                        "ladder_downgrade",
                        f"`{normalized_effort}` is not supported by `{model_id}`; stepped down to `{rung}`",
                    )
            return "", _effort_change(
                requested_effort,
                "",
                "ladder_downgrade",
                f"no supported rung at or below `{normalized_effort}`",
            )
        if normalized_effort in REASONING_EFFORT_LADDER:
            kind = (
                "legacy_alias_normalized"
                if normalized_effort != requested_effort
                else "catalog_no_authority_passthrough"
            )
            reason = (
                "legacy `none` normalized to canonical `off`; the catalog has no exact-model authority"
                if kind == "legacy_alias_normalized"
                else "the catalog has no exact entry for this model, so it does not adjudicate the effort"
            )
            return normalized_effort, _effort_change(
                requested_effort, normalized_effort, kind, reason
            )
        if set(normalized_effort) <= _EFFORT_SHAPE_CHARSET:
            # Unknown-but-effort-shaped values still pass through so a newer
            # CLI vocabulary is not blocked by a stale catalog.
            return normalized_effort, _effort_change(
                requested_effort,
                normalized_effort,
                "unknown_vocabulary_passthrough",
                "effort-shaped but off-vocabulary",
            )
        return "", _effort_change(
            requested_effort, "", "rejected_unsafe_shape", "not an effort-shaped value; CLI default applies"
        )
    if chain_effort:
        return chain_effort, None
    return "", None


def _effort_change(requested: str, selected: str, kind: str, reason: str) -> dict[str, str]:
    return {"requested": requested, "selected": selected, "kind": kind, "reason": reason}


def _chain_payload(
    options: tuple[Mapping[str, object], ...],
    role_chain: tuple[Mapping[str, str], ...],
    *,
    selected_model: str,
) -> list[dict[str, object]]:
    by_model: dict[str, Mapping[str, object]] = {
        str(option.get("model_id", "")): option for option in options
    }
    payload: list[dict[str, object]] = []
    for position, entry in enumerate(role_chain):
        model_id = str(entry.get("model_id", ""))
        option = by_model.get(model_id, {})
        payload.append(
            {
                "position": position,
                "model_id": model_id,
                "reasoning_effort": str(entry.get("reasoning_effort", "") or ""),
                "tier": str(option.get("tier", "")),
                "label": str(option.get("label", "")),
                "selected": bool(selected_model) and model_id == selected_model and position == 0,
            }
        )
    return payload


def _route_payload(
    profile: str,
    *,
    status: str,
    provenance: str,
    role: str,
    chain: list[dict[str, object]],
    attempted: list[dict[str, str]],
    candidates: list[dict[str, object]],
    reasons: list[str],
    selected_model: str = "",
    selected_reasoning_effort: str = "",
    effort_change: dict[str, str] | None = None,
    catalog_kind: str = MODEL_CATALOG_KIND,
    catalog_fingerprint: dict[str, object] | None = None,
    domain: str = "",
    depth: str = "",
    category: str = "",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": CODING_MODEL_ROUTE_SCHEMA_VERSION,
        "executor_profile": profile,
        "status": status,
        "provenance": provenance,
        "role": role,
        "selected_model": selected_model,
        "selected_reasoning_effort": selected_reasoning_effort,
        "model_family": model_family(selected_model),
        "chain": chain,
        "attempted": list(attempted),
        "candidates": [
            {
                "model_id": str(option.get("model_id", "")),
                "label": str(option.get("label", "")),
                "tier": str(option.get("tier", "")),
                "recommended_roles": list(option.get("recommended_roles", ())),
                "reasoning_efforts": list(option.get("reasoning_efforts", ())),
            }
            for option in candidates
        ],
        "catalog_kind": catalog_kind,
        "reasons": list(reasons),
        "claim_boundary": CODING_MODEL_ROUTE_CLAIM_BOUNDARY,
    }
    if category:
        payload["category"] = category
    if domain:
        # Present only when the unit declared a domain: existing payloads
        # stay byte-identical.
        payload["domain"] = domain
    if depth:
        payload["depth"] = depth
    if catalog_fingerprint is not None:
        payload["catalog_fingerprint"] = catalog_fingerprint
    if effort_change is not None:
        payload["effort_change"] = effort_change
    return payload
