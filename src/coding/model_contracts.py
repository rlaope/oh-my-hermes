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

import re
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

# The data-handling axis (issue #1560): two closed vocabularies plus prose,
# because a policy value outside a fixed set cannot be gated on.
#
# Every value here describes the VENDOR'S DOCUMENTED DEFAULT for the surface
# the contract was read from, on `sources_read`. It is never an account-level
# fact, for the same reason `rollout` is not: tier, region, and a negotiated
# agreement all move it, in both directions. An enterprise agreement can
# exclude data the default page includes, and an opted-in consumer tier can
# include data the default excludes. So the axis carries what the vendor
# publishes, the gate repeats that in its claim boundary, and neither ever
# reports what THIS account agreed to.
#
# `not_recorded` is the honest value when the contract carries no reading of
# a vendor data-usage page. It is neither permitting nor conflicting; it is
# the case the gate exists to exclude, and it says so by name rather than by
# an absent key.
TRAINING_USE_EXCLUDED: Final[str] = "excluded_by_default"
TRAINING_USE_INCLUDED: Final[str] = "included_by_default"
TRAINING_USE_NOT_RECORDED: Final[str] = "not_recorded"
DATA_HANDLING_TRAINING_USE_VALUES: Final[tuple[str, ...]] = (
    TRAINING_USE_EXCLUDED,
    TRAINING_USE_INCLUDED,
    TRAINING_USE_NOT_RECORDED,
)

RETENTION_NONE: Final[str] = "none"
RETENTION_BOUNDED: Final[str] = "bounded"
RETENTION_INDEFINITE: Final[str] = "indefinite"
RETENTION_NOT_RECORDED: Final[str] = "not_recorded"
DATA_HANDLING_RETENTION_VALUES: Final[tuple[str, ...]] = (
    RETENTION_NONE,
    RETENTION_BOUNDED,
    RETENTION_INDEFINITE,
    RETENTION_NOT_RECORDED,
)

DATA_HANDLING_ACCOUNT_SCOPE: Final[str] = (
    "vendor-documented default for the surface this contract was read from; account tier, "
    "region, and a negotiated agreement all change it in both directions, so this is not "
    "account-level evidence and never states what this account agreed to"
)

# The reading every contract that points here carries. Their `sources` are
# vendor model, pricing, and capability pages; none is a data-usage or
# retention page, so no data-handling value was read and none is invented here.
# Replacing this on a contract means reading that vendor's data-usage page,
# adding it to `sources`, and moving `sources_read`.
_DATA_HANDLING_NOT_READ: Final[dict[str, object]] = {
    "training_use": TRAINING_USE_NOT_RECORDED,
    "retention": RETENTION_NOT_RECORDED,
    "note": (
        "no data-usage or retention page is among this contract's sources, so neither value "
        "was read; add the vendor's data-usage page to `sources` before declaring one"
    ),
    "account_scope": DATA_HANDLING_ACCOUNT_SCOPE,
}

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
    "data_handling": _DATA_HANDLING_NOT_READ,
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

# GPT-6 Luna, the efficient GPT-6 tier. Unlike Astra it documents `none` as
# a rung of its own ladder, so the ladder records the vendor's spelling and
# the route sends it for both no-reasoning spellings, `none` and OMH's
# canonical `off` (a Hermes effort parser reads `none` as "disabled" and does
# not read `off` that way). Three keys join
# `model_contract/v1` here as optional keys a reader that predates them
# ignores, on the same terms `served_ids` and `limits_note` did:
# `unsupported_parameters_note` carries the condition the tuple cannot,
# `surface_notes` records surfaces whose documented ladder or limits differ
# from the API page this contract is read from, and `surface_efforts` is the
# machine-readable ladder of such a surface, for the route record to read.
_GPT_6_LUNA: Final[dict[str, object]] = {
    "schema_version": MODEL_CONTRACT_SCHEMA_VERSION,
    "model_id": "gpt-6-luna",
    "reasoning_mode": "standard",
    "service_tier": "standard",
    "family": "gpt",
    "generation": "gpt-6",
    # The Codex changelog entry date; no separate API launch date was found.
    "released": "2026-09-22",
    "rollout": (
        "rolling out in Codex to Plus, Pro, Business, Enterprise, and Edu, and to Free and Go in "
        "the desktop app; a released id is not account-level readiness evidence"
    ),
    "knowledge_cutoff": "2026-05-18",
    "context_window_tokens": 1_050_000,
    "max_input_tokens": 922_000,
    "max_output_tokens": 128_000,
    # The API page's ladder. `none` is a documented rung (the latest-model
    # guide: Astra does not support it, Sol and Luna do), so the floor is
    # `none` and there is nothing to raise a no-reasoning request to.
    # `minimal` is not in the ladder; a request for it asks for SOME
    # reasoning, so it is raised to the lowest documented rung above it
    # (`low`), never lowered to `none`.
    "reasoning_efforts": ("none", "low", "medium", "high", "xhigh", "max"),
    "effort_floor": "none",
    "effort_default": "medium",
    "unsupported_efforts": {
        "minimal": "the ladder goes from `none`, no reasoning, straight to `low`",
    },
    "tool_calling": {
        "api": "responses",
        "note": (
            "tool calling with reasoning requires the Responses API; Chat Completions serves "
            "function calling only at reasoning effort `none`"
        ),
    },
    "unsupported_parameters": ("temperature", "top_p", "top_logprobs"),
    "unsupported_parameters_note": (
        "rejected when reasoning effort is not `none`; on Chat Completions `logprobs` is rejected too"
    ),
    "surface_notes": {
        "codex": (
            "Codex documents reasoning efforts up to `max`, with no `ultra`; the Codex client's "
            "model catalog lists `low` through `max` (no `none`) and a 272K context window with "
            "an 872K maximum"
        ),
        "hermes": (
            "an installed Hermes build that predates upstream commit 79ec1f2a34 (2026-09-22) "
            "clamps `max` to `xhigh` without a notice; observed in the Hermes source, not a "
            "vendor statement"
        ),
    },
    # The Codex client's model-catalog ladder from `surface_notes.codex`.
    "surface_efforts": {
        "codex": ("low", "medium", "high", "xhigh", "max"),
    },
    # The GPT-6 family traits from the latest-model guide; the guide gives no
    # Luna-specific prompting guidance, so each is a family statement.
    "documented_traits": (
        "stated for the GPT-6 family: asks the user a question more readily",
        "stated for the GPT-6 family: follows instructions more strictly and is more sensitive to "
        "instructions contained in skills",
        "stated for the GPT-6 family: tends toward detailed, formatted responses",
        "stated for the GPT-6 family: may delegate less often than desired",
        "stated for the GPT-6 family: tends to be thorough in testing before considering a task "
        "complete",
    ),
    # OpenAI list price (developers.openai.com model and pricing pages,
    # 2026-09). The cached rate is a tenth of input, which is the
    # approximation table's default ratio.
    "pricing_usd_per_mtok": {
        "input": 0.10,
        "cached_input": 0.01,
        "cache_write": 0.125,
        "output": 0.50,
        "long_context_over_272k_input": "2x input and cache rates, 1.5x output",
        "batch_and_flex": "0.5x every standard rate",
        "fast_mode": "2x every applicable rate",
    },
    "data_handling": _DATA_HANDLING_NOT_READ,
    "sources": (
        "https://developers.openai.com/api/docs/models/gpt-6-luna",
        "https://developers.openai.com/api/docs/guides/latest-model",
        "https://developers.openai.com/api/docs/pricing",
        "https://learn.chatgpt.com/docs/models",
        "https://learn.chatgpt.com/docs/changelog",
    ),
    "sources_read": "2026-09-23",
    "claim_boundary": MODEL_CONTRACT_CLAIM_BOUNDARY,
}

# GPT-6 Sol, the mid GPT-6 tier under Astra. The same shape as Luna: `none`
# is a documented rung, so both no-reasoning spellings are sent as `none`,
# and `minimal` is raised to `low`. The Codex client's ladder differs from
# the API page in two ways, both recorded beside it rather than folded in:
# it has no `none`, and it lists a Codex-only `ultra` rung, which the API
# ladder does not document and which no OMH ladder carries.
_GPT_6_SOL: Final[dict[str, object]] = {
    "schema_version": MODEL_CONTRACT_SCHEMA_VERSION,
    "model_id": "gpt-6-sol",
    "reasoning_mode": "standard",
    "service_tier": "standard",
    "family": "gpt",
    "generation": "gpt-6",
    # The API changelog entry date ("Sep 22 ... Released GPT-6 Sol"); the
    # model page carries no release date.
    "released": "2026-09-22",
    "rollout": (
        "rolling out in Codex to Plus, Pro, Business, Enterprise, and Edu; a released id is not "
        "account-level readiness evidence"
    ),
    "knowledge_cutoff": "2026-04-20",
    "context_window_tokens": 1_050_000,
    "max_input_tokens": 922_000,
    "max_output_tokens": 128_000,
    # The API page's ladder. `none` is a documented rung (the latest-model
    # guide: Astra does not support it, Sol and Luna do). `minimal` is not in
    # the ladder; a request for it asks for SOME reasoning, so it is raised to
    # the lowest documented rung above it (`low`), never lowered to `none`.
    "reasoning_efforts": ("none", "low", "medium", "high", "xhigh", "max"),
    "effort_floor": "none",
    "effort_default": "medium",
    "unsupported_efforts": {
        "minimal": "not in the documented ladder; the migration guide says start with `low`",
    },
    "tool_calling": {
        "api": "responses",
        "note": (
            "tool calling with reasoning requires the Responses API; Chat Completions serves "
            "function calling only at reasoning effort `none`"
        ),
    },
    "unsupported_parameters": ("temperature", "top_p", "top_logprobs"),
    "unsupported_parameters_note": (
        "rejected when reasoning effort is not `none`; on Chat Completions `logprobs` is rejected too, "
        "and on Responses `message.output_text.logprobs` is removed from `include`"
    ),
    "surface_notes": {
        "codex": (
            "the Codex client's model catalog lists `low` through `max` (no `none`) plus a "
            "Codex-only `ultra` rung that no OMH ladder or chain carries, a `medium` default, and a 272K "
            "context window with an 872K maximum; the client repository's catalog also names a "
            "`priority` default service tier and a 0.155.0 minimum client version, which the "
            "served catalog does not carry"
        ),
        "hermes": (
            "an installed Hermes build that predates upstream commit 79ec1f2a34 (2026-09-22) "
            "has no price for this id and clamps `max` to `xhigh` without a notice; that commit "
            "also listed a `gpt-6-terra` tier, which 38c289c014 (2026-09-23) removed because "
            "OpenAI never published it; observed in the Hermes source, not a vendor statement"
        ),
    },
    # The Codex client's model-catalog ladder from `surface_notes.codex`,
    # without `ultra` (owner decision, 2026-09-23: no OMH ladder or chain
    # carries it).
    "surface_efforts": {
        "codex": ("low", "medium", "high", "xhigh", "max"),
    },
    # The GPT-6 family traits from the latest-model guide; the guide's
    # prompting section is written for Astra and gives no Sol-specific
    # guidance, so each is a family statement.
    "documented_traits": (
        "stated for the GPT-6 family: asks the user a question more readily",
        "stated for the GPT-6 family: follows instructions more strictly and is more sensitive to "
        "instructions contained in skills",
        "stated for the GPT-6 family: tends toward detailed, formatted responses",
        "stated for the GPT-6 family: may delegate less often than desired",
        "stated for the GPT-6 family: tends to be thorough in testing before considering a task "
        "complete",
    ),
    # OpenAI list price (developers.openai.com model and pricing pages,
    # read 2026-09-23). No promotion mark. The cached rate is a tenth of
    # input, which is the approximation table's default ratio.
    "pricing_usd_per_mtok": {
        "input": 2.0,
        "cached_input": 0.2,
        "cache_write": 2.5,
        "output": 10.0,
        "long_context_over_272k_input": "2x input and cache rates, 1.5x output, for the full request",
        "batch_and_flex": "0.5x every standard rate",
        "fast_mode": "2x every applicable rate",
        "regional_processing": "+10% where available",
    },
    "data_handling": _DATA_HANDLING_NOT_READ,
    "sources": (
        "https://developers.openai.com/api/docs/models/gpt-6-sol",
        "https://developers.openai.com/api/docs/guides/latest-model",
        "https://developers.openai.com/api/docs/guides/reasoning",
        "https://developers.openai.com/api/docs/pricing",
        "https://developers.openai.com/api/docs/changelog",
        "https://learn.chatgpt.com/docs/models",
        "https://learn.chatgpt.com/docs/changelog",
    ),
    "sources_read": "2026-09-23",
    "claim_boundary": MODEL_CONTRACT_CLAIM_BOUNDARY,
}

# GPT-6.1 Sol, the Sol tier's successor (owner decision, 2026-10-01: it takes
# every slot GPT-6 Sol held). Astra's ladder shape, not GPT-6 Sol's: the model
# page lists no `none` rung, so `off` and `minimal` are raised to the `low`
# floor on record instead of being sent as `none`. `generation` is `gpt-6.1`,
# the vendor's own versioning (the Opus 5.5 / DeepSeek V4.1 precedent): no
# code reads the field to group or route models, so it is descriptive only,
# and a value shared with GPT-6 Sol would claim a sameness the ladder denies.
# The Codex client's ladder and defaults and the Hermes-build gap are recorded
# in `surface_notes`, beside the API record rather than folded into it.
_GPT_6_1_SOL: Final[dict[str, object]] = {
    "schema_version": MODEL_CONTRACT_SCHEMA_VERSION,
    "model_id": "gpt-6.1-sol",
    "reasoning_mode": "standard",
    "service_tier": "standard",
    "family": "gpt",
    "generation": "gpt-6.1",
    # The API changelog entry date ("Sep 29 ... Released GPT-6.1 Sol").
    "released": "2026-09-29",
    "rollout": (
        "in Codex and ChatGPT Work, availability depends on plan, client, and workspace settings; "
        "not available in ChatGPT Chat; the default model of Codex CLI 0.159.1's bundled catalog; "
        "a released id is not account-level readiness evidence"
    ),
    "knowledge_cutoff": "2026-04-30",
    "context_window_tokens": 1_050_000,
    "max_input_tokens": 922_000,
    "max_output_tokens": 128_000,
    "limits_note": (
        "the model page documents a 1,050,000-token context and 128,000 max output and prints no "
        "max-input figure; 922,000 is context minus output, the figure OpenRouter's endpoint "
        "publishes, and the bound Hermes upstream probed live on 2026-09-29"
    ),
    # The API page's ladder. Unlike GPT-6 Sol there is no `none` rung, so
    # `low` is the documented floor a lower request is raised to on record.
    "reasoning_efforts": ("low", "medium", "high", "xhigh", "max"),
    "effort_floor": "low",
    "effort_default": "medium",
    "unsupported_efforts": {
        "off": "`none` is not supported (model page); the migration guide says use `low` instead",
        "minimal": "not supported (model page); the migration guide says start with `low`",
    },
    "tool_calling": {
        "api": "responses",
        "note": (
            "tool calling requires the Responses API; Chat Completions serves requests without "
            "tool calling at every effort, since there is no `none` rung"
        ),
    },
    "unsupported_parameters": ("temperature", "top_p", "top_logprobs"),
    "unsupported_parameters_note": (
        "always rejected, since every documented effort is above `none`; on Chat Completions "
        "`logprobs` is rejected too, and on Responses `message.output_text.logprobs` is removed "
        "from `include`"
    ),
    # Astra's block: the reasoning guide states the mechanism for the GPT-6
    # family, and the Codex catalog sets `supports_reasoning_effort_updates`.
    "dynamic_effort": {
        "mechanism": "configuration_update",
        "scope": "standard single-agent mode only",
        "constraints": (
            "not combinable with automatic compaction or automatic truncation",
            "two adjacent configuration_update items are rejected",
            "the original prompt prefix is preserved for prompt caching",
        ),
        "compatible_profiles": (),
        "status": "documented_not_observed",
    },
    "runtime_mechanisms": {
        "persisted_reasoning_all_turns": "documented_not_observed",
        "multi_agent_beta": "documented_not_observed",
        "async_tool_calling": "documented_not_observed",
        "mid_turn_steering": "documented_not_observed",
        "pro_reasoning_mode": "documented_not_observed",
    },
    "surface_notes": {
        "codex": (
            "the Codex client's model catalog lists `low` through `max` (no `none`) plus a "
            "Codex-only `ultra` rung that no OMH ladder or chain carries, a `low` default where "
            "the API defaults to `medium`, `low` default verbosity, `xhigh` multi-agent effort, "
            "reasoning-effort updates enabled, and a 272K context window with an 872K maximum; it "
            "names no default service tier and does not list GPT-6.1 Sol as GPT-6 Sol's upgrade"
        ),
        "hermes": (
            "an installed Hermes build without upstream `NO_DISABLE_TIER_PREFIXES` (absent at "
            "39faafb6168, 2026-09-28; present at 040b6df2c40, 2026-10-01) treats this id with the "
            "legacy `none`..`xhigh` ladder: `max` is clamped to `xhigh` without a notice, a "
            "disable sends `none`, and no price is known; a build that carries it omits the "
            "reasoning field on a disable, so the API default `medium` runs rather than `low`; "
            "observed in the Hermes source, not a vendor statement"
        ),
    },
    # The Codex client's model-catalog ladder from `surface_notes.codex`,
    # without `ultra` (owner decision, 2026-09-23: no OMH ladder or chain
    # carries it).
    "surface_efforts": {
        "codex": ("low", "medium", "high", "xhigh", "max"),
    },
    "documented_traits": (
        "stated for the GPT-6 family from behaviour observed with GPT-6 Astra: asks the user a "
        "question more readily",
        "stated for the GPT-6 family: follows instructions more strictly and is more sensitive to "
        "instructions contained in skills",
        "stated for the GPT-6 family: tends toward detailed, formatted responses",
        "stated for the GPT-6 family: may delegate less often than desired",
        "stated for the GPT-6 family: tends to be thorough in testing before considering a task "
        "complete",
        "the vendor's Codex client gives it GPT-6 Astra's base prompt plus an apology-restraint "
        "paragraph, where GPT-6 Sol keeps an older prompt",
    ),
    # OpenAI list price (developers.openai.com model and pricing pages, read
    # 2026-10-01). No promotion mark. The cached rate is 5% of input, not the
    # approximation table's default tenth, so `APPROX_CACHE_READ_RATIO`
    # carries a row for it.
    "pricing_usd_per_mtok": {
        "input": 2.0,
        "cached_input": 0.10,
        "cache_write": 2.5,
        "output": 10.0,
        "long_context_over_272k_input": "2x input and cache rates, 1.5x output, for the full request",
        "batch_and_flex": "0.5x every standard rate",
        "fast_mode": "2x every applicable rate; unavailable with EU data residency",
        "ultrafast": "not offered (the Ultrafast table lists only GPT-6 Astra)",
        "regional_processing": "+10% where available",
    },
    "data_handling": _DATA_HANDLING_NOT_READ,
    "sources": (
        "https://developers.openai.com/api/docs/models/gpt-6.1-sol",
        "https://developers.openai.com/api/docs/guides/latest-model",
        "https://developers.openai.com/api/docs/guides/reasoning",
        "https://developers.openai.com/api/docs/pricing",
        "https://developers.openai.com/api/docs/changelog",
        "https://learn.chatgpt.com/docs/models",
        "https://learn.chatgpt.com/docs/changelog",
    ),
    "sources_read": "2026-10-01",
    "claim_boundary": MODEL_CONTRACT_CLAIM_BOUNDARY,
}

# GPT-6.1 Terra, the Terra tier's first GPT-6-generation release (the API
# changelog's "Oct 26 ... Released GPT-6.1 Terra"). GPT-6 Luna's ladder shape,
# not GPT-6.1 Sol's: the model page and the latest-model guide both list
# `none` ("GPT-6.1 Terra, GPT-6 Sol, and GPT-6 Luna support `none`"), so a
# no-reasoning request is sent as `none` and only `minimal` is raised. OMH's
# 2026-09-23 note that no GPT-6 Terra exists still holds: OpenAI skipped 6.0
# for this tier. Recognized, priced, and provider-mapped, but in no shipped
# chain: GPT-5.6 Terra's slots went to GPT-6 Sol on 2026-09-23, so there is
# no Terra slot for it to inherit, and placement is an owner decision.
_GPT_6_1_TERRA: Final[dict[str, object]] = {
    "schema_version": MODEL_CONTRACT_SCHEMA_VERSION,
    "model_id": "gpt-6.1-terra",
    "reasoning_mode": "standard",
    "service_tier": "standard",
    "family": "gpt",
    "generation": "gpt-6.1",
    # The API changelog entry date ("Oct 26 ... Released GPT-6.1 Terra").
    "released": "2026-10-26",
    "rollout": (
        "in Codex and ChatGPT Work for Plus, Pro, Enterprise, and Edu, and in the API; Codex CLI "
        "needs 0.159.0 or later (vendor launch coverage); a released id is not account-level "
        "readiness evidence"
    ),
    "knowledge_cutoff": "2026-06-01",
    "context_window_tokens": 1_050_000,
    "max_input_tokens": 922_000,
    "max_output_tokens": 128_000,
    "limits_note": (
        "the model page documents a 1,050,000-token context, 922,000 maximum input tokens, and "
        "128,000 max output"
    ),
    # The API page's ladder. `none` is a documented rung, so the floor is
    # `none` and a no-reasoning request has nothing to be raised to; `minimal`
    # asks for SOME reasoning and goes up to `low`, never down to `none`.
    "reasoning_efforts": ("none", "low", "medium", "high", "xhigh", "max"),
    "effort_floor": "none",
    "effort_default": "medium",
    "unsupported_efforts": {
        "minimal": "not in the documented ladder; the migration guide says start with `low`",
    },
    "tool_calling": {
        "api": "responses",
        "note": (
            "tool calling requires the Responses API (the model page and the migration guide); "
            "Chat Completions is supported for requests without tools"
        ),
    },
    "unsupported_parameters": ("temperature", "top_p", "top_logprobs"),
    "unsupported_parameters_note": (
        "rejected when reasoning effort is not `none`; on Chat Completions `logprobs` is rejected too, "
        "and on Responses `message.output_text.logprobs` is removed from `include`"
    ),
    # The reasoning guide states the mechanism for the GPT-6 family, and the
    # Codex catalog sets `supports_reasoning_effort_updates` for this id.
    "dynamic_effort": {
        "mechanism": "configuration_update",
        "scope": "standard single-agent mode only",
        "constraints": (
            "not combinable with automatic compaction or automatic truncation",
            "two adjacent configuration_update items are rejected",
            "the original prompt prefix is preserved for prompt caching",
        ),
        "compatible_profiles": (),
        "status": "documented_not_observed",
    },
    "runtime_mechanisms": {
        "persisted_reasoning_all_turns": "documented_not_observed",
        "async_tool_calling": "documented_not_observed",
        "mid_turn_steering": "documented_not_observed",
        "pro_reasoning_mode": "documented_not_observed",
    },
    "surface_notes": {
        "codex": (
            "the Codex client's model catalog (openai/codex models-manager, read 2026-10-27) lists "
            "`low` through `max` (no `none`) plus a Codex-only `ultra` rung that no OMH ladder or "
            "chain carries, a `low` default where the API defaults to `medium`, `low` default "
            "verbosity, `xhigh` multi-agent effort, reasoning-effort updates enabled, and a 500K "
            "context window with an 872K maximum; it gives the id the same base instructions as "
            "GPT-6 Astra and GPT-6.1 Sol and names no upgrade from GPT-5.6 Terra"
        ),
        "hermes": (
            "Hermes v0.22.5 and origin/main a382af23f4 (2026-10-26) match this id to no GPT-6 "
            "effort prefix, so the Codex route clamps `max` to `xhigh` without a notice; neither "
            "carries a price row, and the Codex route falls back to a 256K context while "
            "OpenRouter resolves 1.05M; observed in the Hermes source, not a vendor statement"
        ),
    },
    # The Codex client's model-catalog ladder from `surface_notes.codex`,
    # without `ultra` (owner decision, 2026-09-23: no OMH ladder or chain
    # carries it).
    "surface_efforts": {
        "codex": ("low", "medium", "high", "xhigh", "max"),
    },
    "documented_traits": (
        "stated for the GPT-6 family from behaviour observed with GPT-6 Astra: asks the user a "
        "question more readily",
        "stated for the GPT-6 family: follows instructions more strictly and is more sensitive to "
        "instructions contained in skills",
        "stated for the GPT-6 family: tends toward detailed, formatted responses",
        "stated for the GPT-6 family: may delegate less often than desired",
        "stated for the GPT-6 family: tends to be thorough in testing before considering a task "
        "complete",
        "the model page positions it for visual reasoning, precise computer use, and clear, "
        "natural writing; the vendor still points the most complex coding at GPT-6.1 Sol or "
        "GPT-6 Astra (launch coverage)",
    ),
    # OpenAI list price (developers.openai.com model and pricing pages, read
    # 2026-10-27). No promotion mark. The cached rate is 5% of input, as on
    # GPT-6.1 Sol, so `APPROX_CACHE_READ_RATIO` carries a row for it.
    "pricing_usd_per_mtok": {
        "input": 1.0,
        "cached_input": 0.05,
        "cache_write": 1.25,
        "cache_write_12h": 2.5,
        "output": 5.0,
        "long_context_over_272k_input": "2x input and cache rates, 1.5x output, for the full request",
        "batch_and_flex": "0.5x every standard rate",
        "fast_mode": "2x every applicable rate",
        "ultrafast": "not offered (the Ultrafast guide names only GPT-6 Astra and GPT-6.1 Sol)",
        "regional_processing": "+10% where available",
    },
    "data_handling": _DATA_HANDLING_NOT_READ,
    "sources": (
        "https://developers.openai.com/api/docs/models/gpt-6.1-terra",
        "https://developers.openai.com/api/docs/guides/latest-model",
        "https://developers.openai.com/api/docs/guides/reasoning",
        "https://developers.openai.com/api/docs/pricing",
        "https://developers.openai.com/api/docs/changelog",
    ),
    "sources_read": "2026-10-27",
    "claim_boundary": MODEL_CONTRACT_CLAIM_BOUNDARY,
}

# GPT-6 Cyber (2026-11-05), an access-gated sibling kept out of every chain
# on the Mythos 5.1 terms, with no executor option row, as for GPT-6.1 Terra:
# the system card calls it "a cyber-specialized variant of GPT-6 Astra", and
# the model page serves it only to organizations with "Daybreak Red access and
# approval". Recognized, priced, and provider-mapped so a user who names it
# gets a contract, a cost, and Astra's calibration, but in no shipped chain:
# most accounts cannot call it and its scope is authorized security work.
# The model page lists "Reasoning token support" and no effort values, so the
# ladder below is GPT-6 Astra's, inherited on the system card's statement and
# labeled as such; a rung Astra rejects is raised on record here too. Only
# the ladder is inherited: limits, endpoints, and price are this model's own
# page, and Astra's unsupported parameters are not copied, because the Cyber
# page names none.
_GPT_6_CYBER: Final[dict[str, object]] = {
    "schema_version": MODEL_CONTRACT_SCHEMA_VERSION,
    "model_id": "gpt-6-cyber",
    "reasoning_mode": "standard",
    "service_tier": "standard",
    "family": "gpt",
    "generation": "gpt-6",
    # The API changelog entry date ("Nov 5 ... Model: gpt-6-cyber").
    "released": "2026-11-05",
    "rollout": (
        "only for organizations with Daybreak Red access and approval (model page), through the "
        "API and the Codex app (the system card recommends Codex's sandboxing \"when accessing "
        "GPT-6 Cyber through the Codex app\"), though the Codex models page "
        "(learn.chatgpt.com/docs/models, read 2026-11-06) does not list it; the OpenAI Codex "
        "subscription route on this "
        "maintainer host returned HTTP 400 on 2026-11-06 with the same wording an unknown id gets, "
        "so the probe cannot tell gated from absent; a released id is not account-level readiness "
        "evidence"
    ),
    "access": (
        "gated: \"Your organization needs Daybreak Red access and approval to use GPT-6-Cyber\" "
        "(model page); the system card rates it Critical in Cybersecurity under OpenAI's "
        "Preparedness Framework, the same designations as GPT-6 Astra, and scopes it to "
        "authorized security work"
    ),
    "served_ids": {
        "first_party": "gpt-6-cyber",
    },
    "knowledge_cutoff": "",
    "context_window_tokens": 1_050_000,
    "max_input_tokens": 922_000,
    "max_output_tokens": 128_000,
    "limits_note": (
        "the model page documents a 1,050,000-token context, 922,000 maximum input tokens, and "
        "128,000 max output; it states no knowledge cutoff and lists one snapshot, `gpt-6-cyber`"
    ),
    # GPT-6 Astra's ladder, inherited: the model page lists no effort values.
    "reasoning_efforts": ("low", "medium", "high", "xhigh", "max"),
    "effort_floor": "low",
    "effort_default": "",
    "unsupported_efforts": {
        "off": "the model page documents no effort values; GPT-6 Astra, its base, returns HTTP 400 for `none`",
        "minimal": "the model page documents no effort values; not in GPT-6 Astra's ladder",
    },
    "effort_ladder_source": (
        "inherited from GPT-6 Astra on the system card's statement that GPT-6 Cyber is a variant "
        "of it; the model page says only \"Reasoning token support\""
    ),
    "tool_calling": {
        "api": "responses",
        "note": (
            "the model page lists Chat Completions and Responses as supported endpoints and every "
            "other endpoint, Batch included, as not supported; it states no tool-calling "
            "restriction of its own (GPT-6 Astra's tool calling requires Responses), so `responses` "
            "here is OMH's choice, not a vendor restriction"
        ),
    },
    "unsupported_parameters": (),
    "runtime_mechanisms": {},
    "surface_notes": {
        "hermes": (
            "Hermes v0.22.5 (bf0203a794) and origin/main 44ec783afd (2026-11-06) carry no "
            "`gpt-6-cyber` id, price, or context row; origin/main's Daybreak switch (60f5029394, "
            "2026-11-02) sends `access_programs.cyber: daybreak_blue` for models the account's "
            "Codex catalog lists, which is Daybreak Blue on existing models, not this Daybreak Red "
            "model; observed in the Hermes source, not a vendor statement"
        ),
    },
    "documented_traits": (
        "the system card: a cyber-specialized variant of GPT-6 Astra for authorized security work, "
        "including vulnerability discovery, exploit development, and web pentesting",
        "the changelog: investigates vulnerabilities, reproduces them in an authorized test "
        "environment, and verifies fixes",
        "its model page, changelog entry, and system card give no prompting guidance; GPT-6 Astra's "
        "documented traits are the nearest record",
    ),
    # OpenAI list price (developers.openai.com model page and pricing page,
    # "Cyber models" table, read 2026-11-06). Only a short-context rate is
    # published: the long-context columns are "-" and the page names no
    # Batch, Flex, or priority row. Cached input is a tenth of input.
    "pricing_usd_per_mtok": {
        "input": 20.0,
        "cached_input": 2.0,
        "cache_write": 25.0,
        "cache_write_12h": 50.0,
        "output": 100.0,
        "long_context_over_272k_input": "not published",
    },
    "data_handling": _DATA_HANDLING_NOT_READ,
    "sources": (
        "https://developers.openai.com/api/docs/models/gpt-6-cyber",
        "https://developers.openai.com/api/docs/pricing",
        "https://developers.openai.com/api/docs/changelog",
        "https://deploymentsafety.openai.com/gpt-6-cyber",
        "https://learn.chatgpt.com/docs/models",
    ),
    "sources_read": "2026-11-06",
    "claim_boundary": MODEL_CONTRACT_CLAIM_BOUNDARY,
}

# Claude Opus 5.5, the first Claude contract. Thinking is always on: a
# thinking-disabled request or a manual budget returns HTTP 400, so a
# no-thinking rung is raised to `low` on record. One optional key joins
# `model_contract/v1` here on the `served_ids` / `limits_note` terms:
# `retirement`, the vendor's published not-before date.
_CLAUDE_OPUS_5_5: Final[dict[str, object]] = {
    "schema_version": MODEL_CONTRACT_SCHEMA_VERSION,
    "model_id": "claude-opus-5-5",
    "reasoning_mode": "thinking",
    "service_tier": "standard",
    "family": "claude",
    "generation": "claude-opus-5.5",
    "released": "2026-09-22",
    "rollout": (
        "available on the Claude API, Amazon Bedrock, Google Cloud, Microsoft Foundry, and Claude "
        "Platform on AWS; a released id is not account-level readiness evidence"
    ),
    # A fixed id with no date suffix: the dateless id is the pinned snapshot.
    "served_ids": {
        "first_party": "claude-opus-5-5",
        "bedrock": "anthropic.claude-opus-5-5",
    },
    "retirement": "not sooner than 2027-09-22",
    "knowledge_cutoff": "2026-06",
    "context_window_tokens": 1_000_000,
    "max_input_tokens": 1_000_000,
    "max_output_tokens": 128_000,
    "limits_note": (
        "1M context and 128K max output are documented; Message Batches allow up to 300K output "
        "with the `output-300k-2026-03-24` beta header; no separate max-input figure is published"
    ),
    "reasoning_efforts": ("low", "medium", "high", "xhigh", "max"),
    "effort_floor": "low",
    # The API default when a request omits effort. Opus 5 defaulted to
    # `high`, so an effort-less request runs one level lower than it did.
    "effort_default": "medium",
    "unsupported_efforts": {
        "off": (
            "thinking is always on; `thinking.type=disabled` or a manual `budget_tokens` returns "
            "HTTP 400"
        ),
        "minimal": "not in the documented ladder",
    },
    "tool_calling": {
        "api": "messages",
        "note": (
            "forced `tool_choice` of type `any` or `tool` returns HTTP 400, on count_tokens as "
            "well; use `auto` and say in the prompt when a tool applies"
        ),
    },
    "unsupported_parameters": ("thinking.budget_tokens",),
    "runtime_mechanisms": {
        "preserved_thinking_blocks": "documented_not_observed",
        "fast_mode": "documented_not_observed",
    },
    "documented_traits": (
        "thinking is always on and adaptive; a request that disables it returns HTTP 400",
        "`medium` is the API default, where Opus 5 defaulted to `high`",
        "thinks more per turn than Opus 5 at the same effort level, especially at `xhigh` and "
        "`max`",
        "text between tool calls arrives in `thinking` blocks whose text is empty at the default "
        "display setting",
        "on long multi-part tasks some progress updates end the turn with text rather than a tool "
        "call",
        "thinking blocks are tied to the model and conversation that produced them",
    ),
    # Anthropic list price (platform.claude.com pricing, 2026-09). Cache
    # reads are 0.05x input on this model, not the tenth the approximation
    # table assumes by default.
    "pricing_usd_per_mtok": {
        "input": 4.0,
        "cached_input": 0.20,
        "cache_write_5m": 5.0,
        "cache_write_1h": 8.0,
        "output": 20.0,
        "batch": "input 2.00, output 10.00 on Message Batches",
        "fast_mode": "input 8.00, output 40.00; Claude API (first-party) only, beta",
        "long_context": "no premium: the full 1M window is billed at standard rates",
    },
    "data_handling": _DATA_HANDLING_NOT_READ,
    "sources": (
        "https://platform.claude.com/docs/en/about-claude/models/overview.md",
        "https://platform.claude.com/docs/en/about-claude/pricing.md",
        "https://platform.claude.com/docs/en/models/opus-5-5/migration-guide",
        "https://platform.claude.com/docs/en/models/opus-5-5/whats-new-opus-5-5",
        "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5",
        "https://platform.claude.com/docs/en/build-with-claude/effort",
        "https://www.anthropic.com/claude-opus-5-5",
    ),
    "sources_read": "2026-09-23",
    "claim_boundary": MODEL_CONTRACT_CLAIM_BOUNDARY,
}

# Claude Sonnet 5.5, the Opus 5.5 shape one tier down. Adaptive thinking is
# on by default and `disabled` or a manual budget returns HTTP 400. The API
# documents one thinking-off mode, `thinking.type=between_tools` at effort
# `high` or below, but neither the installed Hermes build nor Claude Code
# sends it, so a no-thinking rung is raised to `low` on record -- the
# vendor's own first migration step.
_CLAUDE_SONNET_5_5: Final[dict[str, object]] = {
    "schema_version": MODEL_CONTRACT_SCHEMA_VERSION,
    "model_id": "claude-sonnet-5-5",
    "reasoning_mode": "thinking",
    "service_tier": "standard",
    "family": "claude",
    "generation": "claude-sonnet-5.5",
    "released": "2026-09-28",
    "rollout": (
        "available on the Claude API, Amazon Bedrock, Google Cloud, Microsoft Foundry (Azure-hosted, "
        "Global Standard only), and Claude Platform on AWS; a released id is not account-level "
        "readiness evidence"
    ),
    # A fixed id with no date suffix: the dateless id is the pinned snapshot.
    "served_ids": {
        "first_party": "claude-sonnet-5-5",
        "bedrock": "anthropic.claude-sonnet-5-5",
    },
    "retirement": "not sooner than 2027-09-28",
    "knowledge_cutoff": "2026-06",
    "context_window_tokens": 1_000_000,
    "max_input_tokens": 1_000_000,
    "max_output_tokens": 128_000,
    "limits_note": (
        "1M context and 128K max output are documented; Message Batches allow up to 300K output "
        "with the `output-300k-2026-03-24` beta header; no separate max-input figure is published"
    ),
    "reasoning_efforts": ("low", "medium", "high", "xhigh", "max"),
    "effort_floor": "low",
    # The API default when a request omits effort, unchanged from Sonnet 5,
    # but the levels are recalibrated: a rung does not buy the thinking it
    # bought on Sonnet 5.
    "effort_default": "high",
    "unsupported_efforts": {
        "off": (
            "`thinking.type=disabled` or a manual `budget_tokens` returns HTTP 400; the documented "
            "thinking-off mode is `thinking.type=between_tools` at effort `high` or below, which no "
            "OMH route emits"
        ),
        "minimal": "not in the documented ladder",
    },
    "tool_calling": {
        "api": "messages",
        "note": (
            "forced `tool_choice` of type `any` or `tool` returns HTTP 400, on count_tokens as "
            "well; use `auto` and say in the prompt when a tool applies"
        ),
    },
    "unsupported_parameters": ("thinking.budget_tokens",),
    "runtime_mechanisms": {
        "preserved_thinking_blocks": "documented_not_observed",
        "between_tools_thinking": "documented_not_observed",
    },
    "surface_notes": {
        "claude_code": (
            "the `sonnet` alias resolves to Sonnet 5.5 on the Anthropic API from Claude Code "
            "v2.1.284, to Sonnet 4.6 on Claude Platform on AWS, and to Sonnet 4.5 on Bedrock, "
            "Google Cloud, and Foundry; the client defaults Sonnet 5.5 to `medium` effort and "
            "offers no thinking-off setting"
        ),
        "hermes": (
            "Hermes origin/main 040b6df2c40 (2026-10-01) has no price row for this id, sends "
            "`thinking.type=disabled` when reasoning is off (HTTP 400 here), and never sends "
            "`between_tools`; context and output limits resolve through the `claude-sonnet-5` "
            "substring rows; observed in the Hermes source, not a vendor statement"
        ),
    },
    "documented_traits": (
        "adaptive thinking is on by default; a request that disables it returns HTTP 400, and "
        "`between_tools` is the lowest setting",
        "effort levels are recalibrated from Sonnet 5; `high` stays the API default",
        "a prompt asking it to think less has little effect; lowering effort does",
        "at `low` and `medium`, on long agentic tasks, more likely to stop and check in before "
        "finishing; at `low` it can report a change done without running a check that exercises it",
        "adds tests, documentation, and small supporting files nobody asked for, at every effort "
        "level and more at higher effort",
        "at `xhigh` and `max` it can start its own review and verification rounds, including "
        "reviewer subagents",
        "thinking blocks are tied to the model and conversation that produced them",
    ),
    # Anthropic list price (platform.claude.com pricing, read 2026-10-01).
    # Anthropic lowered the cache-read rate on 2026-10-07: the Haiku 5.5
    # launch post says "Cache reads now cost 50% less: $0.10 per million
    # tokens rather than $0.20", and the pricing page now prices cache hits on
    # Opus 5.5 and Sonnet 5.5 at 0.05x input (both read 2026-10-13). The
    # 0.20 recorded on 2026-10-01 was the rate then, not a misreading.
    "pricing_usd_per_mtok": {
        "input": 2.0,
        "cached_input": 0.10,
        "cache_write_5m": 2.50,
        "cache_write_1h": 4.0,
        "output": 10.0,
        "batch": "input 1.00, output 5.00 on Message Batches",
        "long_context": "no premium: the full 1M window is billed at standard rates",
    },
    "data_handling": _DATA_HANDLING_NOT_READ,
    "sources": (
        "https://platform.claude.com/docs/en/about-claude/models/overview.md",
        "https://platform.claude.com/docs/en/about-claude/pricing.md",
        "https://platform.claude.com/docs/en/about-claude/model-deprecations",
        "https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide",
        "https://platform.claude.com/docs/en/models/sonnet-5-5/whats-new-sonnet-5-5",
        "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5",
        "https://code.claude.com/docs/en/model-config",
        # The 2026-10-07 cache-read price cut (read 2026-10-13).
        "https://www.anthropic.com/claude-haiku-5-5",
    ),
    "sources_read": "2026-10-01",
    "claim_boundary": MODEL_CONTRACT_CLAIM_BOUNDARY,
}

# Claude Haiku 5.5, Claude Haiku 4.5's successor and the first Haiku-class
# model with an effort ladder. Unlike Opus 5.5 and Sonnet 5.5 it accepts
# `thinking.type=disabled`, but only at effort `high` or below, so `off` is
# neither raised nor listed as unsupported: a disable carries no effort rung,
# and the route passes it through on record. `minimal` is not a rung and is
# raised to `low`. Two prices, chosen by prompt length: the approximation
# table carries the up-to-100K card, the Gemini 3.1 Pro / Grok Build 0.1 shape
# for a tiered price; the higher card is recorded here and not flattened.
_CLAUDE_HAIKU_5_5: Final[dict[str, object]] = {
    "schema_version": MODEL_CONTRACT_SCHEMA_VERSION,
    "model_id": "claude-haiku-5-5",
    "reasoning_mode": "thinking",
    "service_tier": "standard",
    "family": "claude",
    "generation": "claude-haiku-5.5",
    # The launch post and the system card are dated October 7, 2026.
    "released": "2026-10-07",
    "rollout": (
        "available on the Claude API, Amazon Bedrock, Google Cloud, Microsoft Foundry, and Claude "
        "Platform on AWS; a released id is not account-level readiness evidence"
    ),
    # A fixed id with no date suffix: the dateless id is the pinned snapshot.
    "served_ids": {
        "first_party": "claude-haiku-5-5",
        "bedrock": "anthropic.claude-haiku-5-5",
    },
    "retirement": "not sooner than 2027-10-07",
    "knowledge_cutoff": "2026-06",
    "context_window_tokens": 1_000_000,
    "max_input_tokens": 1_000_000,
    "max_output_tokens": 128_000,
    "limits_note": (
        "1M context and 128K max output are documented; Message Batches allow up to 300K output "
        "with the `output-300k-2026-03-24` beta header; no separate max-input figure is published, "
        "and a prompt over 100,000 tokens is billed on the higher price card"
    ),
    "reasoning_efforts": ("low", "medium", "high", "xhigh", "max"),
    "effort_floor": "low",
    # The API default when a request omits effort, as on Opus 5.5.
    "effort_default": "medium",
    "unsupported_efforts": {
        "minimal": "not in the documented ladder",
    },
    "tool_calling": {
        "api": "messages",
        "note": (
            "forced `tool_choice` of type `any` or `tool` is accepted, but the response then starts "
            "with the tool call and carries no `thinking` block; use `auto` and say in the prompt "
            "when a tool applies to keep thinking before the call"
        ),
    },
    "unsupported_parameters": ("thinking.budget_tokens", "top_k"),
    "unsupported_parameters_note": (
        "`temperature` must be 1 and `top_p` must be 0.99 when sent, and sending both is rejected; "
        "every `top_k` value, a manual thinking budget, and an assistant prefill return HTTP 400; "
        "`thinking.type=disabled` returns HTTP 400 at `xhigh` and `max`, and `between_tools` is "
        "documented for Sonnet 5.5 only"
    ),
    "runtime_mechanisms": {
        "preserved_thinking_blocks": "documented_not_observed",
        "per_message_effort": "documented_not_observed",
    },
    "surface_notes": {
        "claude_code": (
            "the `haiku` alias resolves to Haiku 5.5 on the Anthropic API from Claude Code v2.1.293 "
            "and to Haiku 4.5 on Claude Platform on AWS, Bedrock, Google Cloud, and Foundry; the "
            "client runs it at `medium` effort with adaptive reasoning and offers no thinking-off "
            "setting"
        ),
        "hermes": (
            "on Hermes' Anthropic route, builds through v0.21.6 (2026-10-08), the 0.21.1 floor "
            "included, treat every `haiku` id as pre-thinking and send neither thinking nor effort, "
            "so a requested rung is not on the wire and the API default `medium` runs; v0.21.7 "
            "(2026-10-12; fix 8ed7d31b20 of 2026-10-11 UTC) and origin/main 63d0b941200 exempt only "
            "Haiku below 5.5 and send adaptive "
            "thinking plus `output_config.effort`; neither has a price row for this id, and context "
            "resolves through the 200K `claude` catch-all row; observed in the Hermes source, not a "
            "vendor statement"
        ),
    },
    "documented_traits": (
        "adaptive thinking is on by default; `thinking.type=disabled` is accepted at `high` or "
        "below and returns HTTP 400 at `xhigh` and `max`",
        "the first Haiku-class model with effort levels; `medium` is the API default",
        "a prompt asking it to answer directly does not stop it thinking; lowering effort does",
        "at `low`, in a long agent prompt, it sometimes stops early and hands the task back",
        "at `low` and `medium` it sometimes reports a code change as done without running a check",
        "at `xhigh` in multi-turn chats it sometimes writes its whole answer in thinking and ends "
        "the turn with no visible text",
        "the same text counts as about 30% more tokens than on Claude Haiku 4.5",
        "thinking blocks are tied to the account and conversation that produced them",
    ),
    # Anthropic list price (platform.claude.com pricing, read 2026-10-13).
    # Cache reads are the standard tenth of input on both cards.
    "pricing_usd_per_mtok": {
        "input": 0.10,
        "cached_input": 0.01,
        "cache_write_5m": 0.125,
        "cache_write_1h": 0.20,
        "output": 0.50,
        "long_context_over_100k_prompt": (
            "input 0.50, cached input 0.05, cache write 0.625 (5m) and 1.00 (1h), output 2.50 for a "
            "request whose prompt, counting cache reads and writes, exceeds 100,000 tokens"
        ),
        "batch": "input 0.05, output 0.25 up to 100K; input 0.25, output 1.25 above",
    },
    "data_handling": _DATA_HANDLING_NOT_READ,
    "sources": (
        "https://platform.claude.com/docs/en/about-claude/models/overview.md",
        "https://platform.claude.com/docs/en/about-claude/pricing.md",
        "https://platform.claude.com/docs/en/about-claude/model-deprecations",
        "https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide",
        "https://platform.claude.com/docs/en/models/haiku-5-5/whats-new-haiku-5-5",
        "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5",
        "https://platform.claude.com/docs/en/build-with-claude/effort",
        "https://www.anthropic.com/claude-haiku-5-5",
        "https://code.claude.com/docs/en/model-config",
    ),
    "sources_read": "2026-10-13",
    "claim_boundary": MODEL_CONTRACT_CLAIM_BOUNDARY,
}

# DeepSeek V4.1 Flash. OMH's alias is the versioned gateway spelling; the
# first-party API names the current Flash generation `deepseek-flash` and
# that pointer is a declared projection below, not a second contract.
_DEEPSEEK_V41_FLASH: Final[dict[str, object]] = {
    "schema_version": MODEL_CONTRACT_SCHEMA_VERSION,
    "model_id": "deepseek-v4.1-flash",
    "reasoning_mode": "thinking",
    "service_tier": "standard",
    "family": "deepseek",
    "generation": "deepseek-v4.1",
    "released": "2026-09-10",
    "rollout": (
        "generally available on the first-party API as `deepseek-flash`; `deepseek-v4-flash` and "
        "`deepseek-v4-flash-vision-exp` are routed to it; `deepseek-v4-pro` stays a separately "
        "priced model (pricing page re-read 2026-10-28); since 2026-10-17 the pointer serves "
        "DeepSeek-V4.1-Flash-1017, an upgrade of this model with \"The API calling method and "
        "pricing remain unchanged\" (change log and pricing page re-read 2026-11-06; the pricing "
        "page names the snapshot only as the MODEL VERSION, never as a model name); a released "
        "id is not account-level readiness evidence"
    ),
    "served_ids": {
        "first_party": "deepseek-flash",
        "openrouter": "deepseek/deepseek-v4.1-flash",
        "openrouter_snapshot_1017": "deepseek/deepseek-v4.1-flash-1017",
        "huggingface": "deepseek-ai/DeepSeek-V4.1-Flash",
    },
    "knowledge_cutoff": "",
    # The vendor documents the window and the max output literally (1M
    # context, 384K max output) and publishes no separate max-input figure;
    # the output is produced inside the window, so input plus output is not
    # additive here the way it is in the Astra record.
    "context_window_tokens": 1_000_000,
    "max_input_tokens": 1_000_000,
    "max_output_tokens": 384_000,
    "limits_note": "1M context and 384K max output are documented literally; no separate max-input figure is published",
    # The documented ladder is three rungs with thinking on by default at
    # `high`. Nothing returns an error: the thinking-mode guide publishes a
    # mapping table for every other rung (below), so there is no floor to
    # raise to and `unsupported_efforts` stays empty — OMH keeps the
    # requested rung in the route record and the table says what it bought.
    "reasoning_efforts": ("low", "high", "max"),
    "effort_floor": "low",
    "effort_default": "high",
    "unsupported_efforts": {},
    "effort_mapping": {
        "minimal": "low",
        "medium": "high",
        "xhigh": "high",
        "ultra": "max",
        "note": (
            "documented in the thinking-mode guide; no value returns an error. Thinking is "
            "disabled through `thinking.type=disabled` (OpenAI format) or `reasoning.effort=none` "
            "(Anthropic format), not through the effort ladder"
        ),
    },
    "tool_calling": {
        "api": "chat_completions",
        "note": (
            "tool calls are served on Chat Completions, the Responses API, and the "
            "Anthropic-compatible endpoint; on every request that carries the `tools` parameter "
            "the `reasoning_content` of every earlier turn must be sent back — including turns "
            "where the model made no tool call — and is concatenated into the context (HTTP 400 "
            "otherwise); on a request without `tools` it is ignored"
        ),
    },
    # Accepted without error but without effect in thinking mode; `top_p`
    # has a documented floor of 0.95 there.
    "unsupported_parameters": ("temperature", "presence_penalty", "frequency_penalty"),
    "runtime_mechanisms": {
        "reasoning_content_passback": "documented_not_observed",
        "prefix_cache_hit_pricing": "documented_not_observed",
        "native_image_input": "documented_not_observed",
        "json_output": "documented_not_observed",
    },
    "documented_traits": (
        "thinking is on by default at `high`; the ladder is `low`, `high`, `max`, and the guide "
        "maps every other rung (`minimal` to `low`, `medium` and `xhigh` to `high`, `ultra` to "
        "`max`) without an error",
        "on every request carrying `tools` the reasoning_content of every earlier turn is sent "
        "back, so earlier reasoning is already in the context of every later tool step",
        "post-trained on large-scale synthesized agent tasks and evaluated by the vendor at its "
        "maximum reasoning setting with a 1M-token context and max_tokens of at least 256K",
        "cache-hit input is priced at a fiftieth of cache-miss input, so a changed prompt prefix "
        "is billing-visible on every later turn",
        "temperature, presence_penalty, and frequency_penalty have no effect in thinking mode",
    ),
    # DeepSeek list price (api-docs.deepseek.com/quick_start/pricing, 2026-09):
    # peak-hour rates; every rate halves off-peak. The approximation table
    # carries peak input/output; the cache-hit rate is its 0.02 ratio row.
    "pricing_usd_per_mtok": {
        "input": 0.30,
        "cached_input": 0.006,
        "output": 1.20,
        "off_peak": (
            "half of every peak rate (cache hit 0.003, cache miss 0.15, output 0.6) outside "
            "01:00-04:00 and 06:00-10:00 UTC, Monday through Friday"
        ),
    },
    "data_handling": _DATA_HANDLING_NOT_READ,
    "sources": (
        "https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash",
        "https://api-docs.deepseek.com/updates/",
        "https://api-docs.deepseek.com/quick_start/pricing",
        "https://api-docs.deepseek.com/guides/thinking_mode",
    ),
    "sources_read": "2026-09-11",
    "claim_boundary": MODEL_CONTRACT_CLAIM_BOUNDARY,
}

# Kimi K3.1 Pro (Moonshot AI, 2026-10-23), the first K3.1-series model: a
# post-trained Kimi K3 served under the K3 parameter contract ("`kimi-k3.1-pro`
# and `kimi-k3.1-pro-highspeed` also have the same parameter constraints as
# `kimi-k3`", models-overview, read 2026-10-24). Kimi K3 itself has no exact
# contract; this one is read from the K3.1 pages, which restate the K3 rules.
#
# The ladder is three rungs and the API accepts only those values, so every
# other rung is recorded as unsupported and raised on record: `off` and
# `minimal` to the floor `low` (thinking is always on and the `thinking`
# parameter is not supported), `medium` to `high` and `xhigh` to `max`, the
# lowest documented rung above each. Those two raises are the same mapping the
# installed Hermes Agent applies on its kimi-coding route
# (`KIMI_K3_OVERRIDES`), so the route record now says what the wire carries.
_KIMI_K3_1_PRO: Final[dict[str, object]] = {
    "schema_version": MODEL_CONTRACT_SCHEMA_VERSION,
    "model_id": "kimi-k3.1-pro",
    "reasoning_mode": "thinking",
    "service_tier": "standard",
    "family": "kimi",
    "generation": "kimi-k3.1",
    # The launch post on X is dated October 23, 2026.
    "released": "2026-10-23",
    "rollout": (
        "available on the Kimi API, Kimi Code, Kimi Work, and the Kimi apps; off by default for "
        "Kimi Enterprise organizations until an administrator enables it; open weights are "
        "promised by 2026-11-04; a released id is not account-level readiness evidence"
    ),
    "served_ids": {
        "first_party": "kimi-k3.1-pro",
        "openrouter": "moonshotai/kimi-k3.1-pro",
    },
    "knowledge_cutoff": "",
    "context_window_tokens": 1_048_576,
    "max_input_tokens": 1_048_576,
    "max_output_tokens": 1_048_576,
    "limits_note": (
        "every K3-series model has a 1,048,576-token context window; `max_completion_tokens` "
        "defaults to 131,072 and can be set up to 1,048,576; no separate max-input figure is "
        "published, and billing is flat across the window (no long-context tier)"
    ),
    "reasoning_efforts": ("low", "high", "max"),
    "effort_floor": "low",
    "effort_default": "max",
    "unsupported_efforts": {
        "off": "thinking is always on and the `thinking` parameter is not supported",
        "minimal": "not an accepted `reasoning_effort` value",
        "medium": "not an accepted `reasoning_effort` value",
        "xhigh": "not an accepted `reasoning_effort` value",
    },
    "tool_calling": {
        "api": "chat_completions",
        "note": (
            "`tool_choice` accepts `auto`, `none`, and `required`; forcing one named function "
            "returns HTTP 400 while thinking is on, and thinking is always on; the complete "
            "assistant message, `reasoning_content` and `tool_calls` included, is returned "
            "unchanged on every later turn"
        ),
    },
    "unsupported_parameters": ("thinking", "temperature", "top_p", "n", "presence_penalty", "frequency_penalty"),
    "unsupported_parameters_note": (
        "`temperature` 1.0, `top_p` 0.95, `n` 1, and both penalties 0 are fixed and any other "
        "value returns an error, so none is sent; `thinking` is a K2.x-only parameter"
    ),
    "runtime_mechanisms": {
        "preserved_thinking": "documented_not_observed",
        "prefix_cache_ttl_tiers": "documented_not_observed",
        "dynamic_tool_loading": "documented_not_observed",
        "native_image_and_video_input": "documented_not_observed",
    },
    "surface_notes": {
        "hermes": (
            "the installed Hermes Agent (0.22.2) and origin/main 5894e750c3 send every model on "
            "the kimi-coding route through the K3 ladder (`low`/`high`/`max`, `medium` raised to "
            "`high`, `xhigh` to `max`), resolve the 1,048,576-token window through the `kimi-k3` "
            "context row by longest match, and carry no price row for this id; observed in the "
            "Hermes source, not a vendor statement"
        ),
        "kimi_code": (
            "the Kimi Code plan lists the model under the bare slug `k3.1-pro` (models.dev, read "
            "2026-10-24; community), which classifies `unknown` here, like the bare `k3` slug"
        ),
    },
    "documented_traits": (
        "a post-trained Kimi K3 with substantially larger post-training compute and joint "
        "reinforcement learning across hundreds of domains; the served parameter contract is "
        "K3's",
        "always reasons; `reasoning_effort` accepts `low`, `high`, and `max`, and `max` is the "
        "default when a request omits it",
        "switching the effort level invalidates prefix-cache hits, so the vendor advises "
        "fixing it before a conversation starts",
        "Preserved Thinking is always on: earlier `reasoning_content` is sent back and the model "
        "continues its earlier reasoning",
        "forcing a specific tool returns HTTP 400 because thinking cannot be turned off",
        "vision input takes base64 or `ms://` file ids, not public image URLs",
    ),
    # Moonshot AI list price (platform.kimi.ai/docs/pricing/chat, read
    # 2026-10-24). Cached input is the default tenth of input.
    "pricing_usd_per_mtok": {
        "input": 2.0,
        "cached_input": 0.20,
        "cache_write_5m": 2.0,
        "cache_write_1h": 4.0,
        "output": 10.0,
    },
    "data_handling": _DATA_HANDLING_NOT_READ,
    "sources": (
        "https://platform.kimi.ai/docs/guide/kimi-k3-1-pro-quickstart",
        "https://platform.kimi.ai/docs/pricing/chat",
        "https://platform.kimi.ai/docs/guide/use-reasoning-effort",
        "https://platform.kimi.ai/docs/guide/use-thinking-models",
        "https://platform.kimi.ai/docs/guide/use-tool-choice",
        "https://platform.kimi.ai/docs/api/models-overview",
    ),
    "sources_read": "2026-10-24",
    "claim_boundary": MODEL_CONTRACT_CLAIM_BOUNDARY,
}

# Kimi K3.1 Pro Highspeed: the same model served faster ("same intelligence
# and 1M-token context window at roughly 3x the speed", platform.kimi.ai; the
# launch post says 2-3x). It is an exact contract rather than a declared
# projection because Moonshot publishes a full rate card of its own: input,
# output, and cache writes are double the base card but cached input is the
# same 0.20, which no single service-tier multiplier reproduces. Being exact,
# it projects onto no base chain entry; a chain that wants it names it.
_KIMI_K3_1_PRO_HIGHSPEED: Final[dict[str, object]] = {
    **_KIMI_K3_1_PRO,
    "model_id": "kimi-k3.1-pro-highspeed",
    "service_tier": "highspeed",
    "served_ids": {"first_party": "kimi-k3.1-pro-highspeed"},
    "surface_notes": {
        "hermes": _KIMI_K3_1_PRO["surface_notes"]["hermes"],  # type: ignore[index]
        "kimi_code": (
            "the Kimi Code plan lists the model under the bare slug `k3.1-pro-highspeed` "
            "(models.dev, read 2026-10-24; community) and documents about twice the quota usage "
            "of `k3.1-pro`; OpenRouter's live listing (read 2026-10-24) serves no Highspeed id"
        ),
    },
    "documented_traits": (
        "the same model as `kimi-k3.1-pro` served at 2-3x the speed, with the same parameter "
        "contract and context window",
        *_KIMI_K3_1_PRO["documented_traits"][1:],  # type: ignore[index]
    ),
    # Moonshot AI list price (platform.kimi.ai/docs/pricing/chat, read
    # 2026-10-24): double the base card except cached input.
    "pricing_usd_per_mtok": {
        "input": 4.0,
        "cached_input": 0.20,
        "cache_write_5m": 4.0,
        "cache_write_1h": 8.0,
        "output": 20.0,
    },
}

# Gemini 4 Argon (Google, GA 2026-10-13), the first Gemini exact contract and
# the successor of Gemini 3.1 Pro in every shipped chain. The ladder is
# `low`/`medium`/`high` with `medium` the default, and thinking cannot be
# turned off, so `off` and `minimal` are raised to the floor `low` on record.
# Rungs above `high` (`xhigh`, `max`, `ultra`) are deliberately NOT listed as
# unsupported: the raise rule picks the lowest documented rung above the
# request and there is none, so listing them would lower `xhigh` to the
# floor. Google documents no value for them; they pass through on record,
# and the Hermes surface note says what that build sends instead.
_GEMINI_4_ARGON: Final[dict[str, object]] = {
    "schema_version": MODEL_CONTRACT_SCHEMA_VERSION,
    "model_id": "gemini-4-argon",
    "reasoning_mode": "thinking",
    "service_tier": "standard",
    "family": "gemini",
    "generation": "gemini-4",
    # The Gemini API changelog entry is dated October 13, 2026.
    "released": "2026-10-13",
    "rollout": (
        "generally available on the Gemini API; not on the free tier; a released id is not "
        "account-level readiness evidence"
    ),
    # The model page lists one stable id and no preview, latest, or dated
    # variant.
    "served_ids": {
        "first_party": "gemini-4-argon",
        "openrouter": "google/gemini-4-argon",
    },
    "knowledge_cutoff": "",
    "context_window_tokens": 1_048_576,
    "max_input_tokens": 1_048_576,
    "max_output_tokens": 65_536,
    "limits_note": (
        "1,048,576 tokens is a unified input and output limit; a synchronous request returns up to "
        "65,536 output tokens, and long decode (`background: true` with `max_output_tokens` above "
        "65,536) raises that to 1,048,576; `max_output_tokens` is a hard stop on thinking and "
        "output together, and the migration guide recommends at least 32,768 because the model "
        "can spend more of the limit on thinking"
    ),
    "reasoning_efforts": ("low", "medium", "high"),
    "effort_floor": "low",
    "effort_default": "medium",
    "unsupported_efforts": {
        "off": "thinking cannot be turned off; the thinking table lists the default as `On (medium)`",
        "minimal": "not a documented `thinking_level`",
    },
    "tool_calling": {
        "api": "generate_content",
        "note": (
            "function calling is supported; send the full history back, thought signatures "
            "included, on every multi-turn and function-calling request"
        ),
    },
    "unsupported_parameters": ("temperature", "top_p", "top_k"),
    "unsupported_parameters_note": (
        "`temperature`, `top_p`, and `top_k` are ignored when sent; explicit caching "
        "(`cachedContents`) is not supported, only implicit caching"
    ),
    "runtime_mechanisms": {
        "thought_signature_passback": "documented_not_observed",
        "long_decode": "documented_not_observed",
        "implicit_caching": "documented_not_observed",
    },
    "surface_notes": {
        "hermes": (
            "the installed Hermes Agent (v0.22.5 bf0203a794) sends `thinkingLevel` only, maps "
            "`none`/`minimal` to `low` and `xhigh`/`max`/`ultra` to `high`, and on direct Google "
            "endpoints only adds a long-decode output budget (262,144 at `xhigh`, 1,048,576 at "
            "`max` and `ultra`); observed in the Hermes source, not a vendor statement"
        ),
        "thinking_budget": (
            "Google's guides disagree: AI Studio maps `thinking_budget` to the nearest level with "
            "a warning, Vertex AI returns HTTP 400 for it and for `MINIMAL`; send `thinkingLevel` "
            "only; official"
        ),
        "gemini_cli": (
            "gemini-cli main (b8fa817, 2026-10-28) has no Argon id or alias and its README says "
            "it is \"Not optimized for Gemini 4+\"; official-client"
        ),
        "openrouter": (
            "no `-preview` spelling is listed anywhere; OpenRouter's floating "
            "`~google/gemini-pro-latest` now points at `google/gemini-4-argon` (read 2026-10-28); "
            "community"
        ),
    },
    "documented_traits": (
        "thinking is always on; `thinking_level` accepts `low`, `medium`, and `high`, and "
        "`medium` is the default and the level recommended for complex code and agentic work",
        "it can spend more of `max_output_tokens` on thinking than earlier models",
        "hard prompts can take several minutes, so client timeouts need room",
    ),
    # Google list price (ai.google.dev/gemini-api/docs/pricing, read
    # 2026-10-28), Standard paid tier, no prompt-size tier. The rates step up
    # on 2026-12-01; the cache-read ratio is 0.05 in both periods.
    "pricing_usd_per_mtok": {
        "input": 2.0,
        "cached_input": 0.10,
        "output": 10.0,
        "from_2026_12_01": "input 4.00, cached input 0.20, output 20.00",
        "batch": "half of the standard rates",
    },
    "data_handling": _DATA_HANDLING_NOT_READ,
    "sources": (
        "https://ai.google.dev/gemini-api/docs/models/gemini-4-argon",
        "https://ai.google.dev/gemini-api/docs/thinking",
        "https://ai.google.dev/gemini-api/docs/pricing",
        "https://ai.google.dev/gemini-api/docs/changelog",
        "https://ai.google.dev/gemini-api/docs/latest-model",
    ),
    "sources_read": "2026-10-28",
    "claim_boundary": MODEL_CONTRACT_CLAIM_BOUNDARY,
}

# TypeSafe Jev 1.13, the first `non_generative` contract: a model whose
# documented output is a typed answer over options the caller supplies, not
# text. Four keys exist only on this class and carry their reason here rather
# than in a schema bump, on the same terms `served_ids` and `limits_note`
# joined `model_contract/v1` — an optional key a reader that predates it
# ignores. `model_class` is the class itself (the route resolver refuses a
# `non_generative` model by name); `question_types` and `max_choice_options`
# are the answer surface that replaces an effort ladder; `rate_limits` is
# published per-model here and nowhere else in the record.
_JEV_1_13: Final[dict[str, object]] = {
    "schema_version": MODEL_CONTRACT_SCHEMA_VERSION,
    "model_id": "jev-1.13.0",
    # No reasoning ladder is documented for this model and none is inferred:
    # a question is answered at one setting, so there is no mode to name.
    "reasoning_mode": "none",
    "service_tier": "standard",
    "family": "jev",
    "generation": "jev-1.13",
    # The vendor's model page publishes no release date for 1.13. `GET
    # /v1/models` returns a `release_date` per alias and OMH never calls it,
    # so the field stays empty rather than carrying a press figure the cited
    # pages do not support.
    "released": "",
    "rollout": (
        "generally available on `POST /v1/systemone`; `jev-latest` and `jev-preview` both resolve "
        "to `jev-1.13.0` today and both move on the next release; a served alias is not "
        "account-level readiness evidence"
    ),
    "served_ids": {
        "first_party": "jev-1.13.0",
        "first_party_latest_alias": "jev-latest",
        "first_party_preview_alias": "jev-preview",
    },
    "knowledge_cutoff": "",
    # The 64k budget covers `state` plus every question in the request; the
    # 32k figure is `state` plus the single longest question, which is what a
    # caller actually has to fit, so it is the max-input side.
    "context_window_tokens": 64_000,
    "max_input_tokens": 32_000,
    # An int, not an absence: the model returns typed answers, they are
    # billed at zero, and the record has to say that rather than leave the
    # field blank and let a reader guess whether it was never read.
    "max_output_tokens": 0,
    "limits_note": (
        "64k covers `state` plus all questions combined and 32k covers `state` plus the single "
        "longest question; output is typed answers billed at zero, not generated text, so the "
        "output limit is 0 rather than unread"
    ),
    "rate_limits": {
        "tokens_per_second": 250_000,
        "requests_per_minute": 1_200,
        "note": (
            "the vendor warns these are adjusting dynamically and can change without notice; a "
            "request over either limit returns 429 and 529 means overloaded, both retried with "
            "backoff by the vendor's own SDKs"
        ),
    },
    # No effort ladder exists to be raised to or stepped down from. Empty is
    # the documented reading, not an unread one: the request carries a
    # `state` and typed questions and no effort parameter at all.
    "reasoning_efforts": (),
    "effort_floor": "",
    "effort_default": "",
    "unsupported_efforts": {},
    "model_class": "non_generative",
    "question_types": ("choice", "score", "noul"),
    "max_choice_options": 255,
    "tool_calling": {
        "api": "systemone",
        "note": (
            "none: the endpoint takes a `state` plus a map of typed questions and returns their "
            "answers, so there is no tool-call surface to serve"
        ),
    },
    "unsupported_parameters": (),
    "runtime_mechanisms": {
        "parallel_question_fan_out": "documented_not_observed",
    },
    "documented_traits": (
        "is not trained to generate text; when the answer space is bounded the vendor's guidance "
        "is to turn extraction into a Choice over the options rather than asking for the value",
        "answers the question as written rather than as meant: scoping words, negations, and "
        "implied conditions are read at face value",
        "does not count, convert numeric representations, or compare dates reliably; the vendor "
        "directs every arithmetic and ordering step into code",
        "loses accuracy with each hop of indirection and with state that carries detail the "
        "question does not need",
        "treats state as data rather than as hostile, so adversarial content in state can move "
        "the answer",
        "degrades when the instructions and the criteria of one question ask for different things",
        "guarantees no structural invariant across separate questions: a Choice over options is "
        "relative and settles which option, while each Noul is absolute and can be low for all "
        "of them, so a threshold tuned on one does not carry to the other",
        "is trained primarily on English; the vendor states other languages including CJK "
        "scripts are handled but not equally well",
        "accepts natural-language text only, as a string, JSON object, or array of text values; "
        "images, audio, video, and binaries must be turned into text or structured fields before "
        "they can be sent as `state`",
    ),
    # TypeSafe list price (docs.typesafe.ai/models, 2026-09): $0.042 per Mtok
    # of input, charged per input token, with output tokens free. Zero is the
    # published price, not a missing one.
    "pricing_usd_per_mtok": {
        "input": 0.042,
        "output": 0.0,
    },
    # Read from the vendor's own data-handling section and legal index. The
    # training answer is published in words ("Jev is not trained on customer
    # requests or responses"); no retention window is, and zero data
    # retention is named as an enterprise offer, which makes it explicitly
    # not the default. So the retention rung stays `not_recorded`.
    "data_handling": {
        "training_use": TRAINING_USE_EXCLUDED,
        "retention": RETENTION_NOT_RECORDED,
        "note": (
            "the models page states Jev is not trained on customer requests or responses and that "
            "it is not fine-tuned or LoRA-adapted with customer data; the legal index points at a "
            "DPA and privacy policy for retention and offers zero data retention to enterprise "
            "customers, so no default retention window was published and none is invented here"
        ),
        "account_scope": DATA_HANDLING_ACCOUNT_SCOPE,
    },
    "sources": (
        "https://docs.typesafe.ai/models",
        "https://docs.typesafe.ai/api",
        "https://docs.typesafe.ai/model-jaggedness/jev-1.13",
        "https://docs.typesafe.ai/confidence",
        "https://docs.typesafe.ai/primitives/choice",
        "https://docs.typesafe.ai/legal",
    ),
    "sources_read": "2026-09-21",
    "claim_boundary": MODEL_CONTRACT_CLAIM_BOUNDARY,
}

MODEL_CONTRACTS: Final[dict[str, Mapping[str, object]]] = {
    "gpt-6-astra": _GPT_6_ASTRA,
    "gpt-6-sol": _GPT_6_SOL,
    "gpt-6.1-sol": _GPT_6_1_SOL,
    "gpt-6.1-terra": _GPT_6_1_TERRA,
    "gpt-6-cyber": _GPT_6_CYBER,
    "gpt-6-luna": _GPT_6_LUNA,
    "claude-opus-5-5": _CLAUDE_OPUS_5_5,
    "claude-sonnet-5-5": _CLAUDE_SONNET_5_5,
    "claude-haiku-5-5": _CLAUDE_HAIKU_5_5,
    "deepseek-v4.1-flash": _DEEPSEEK_V41_FLASH,
    "kimi-k3.1-pro": _KIMI_K3_1_PRO,
    "kimi-k3.1-pro-highspeed": _KIMI_K3_1_PRO_HIGHSPEED,
    "gemini-4-argon": _GEMINI_4_ARGON,
    "jev-1.13.0": _JEV_1_13,
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
    # GPT-6.1 Sol's pro reasoning mode (the reasoning guide, read 2026-10-01:
    # `"model": "gpt-6.1-sol", "reasoning": {"mode": "pro"}`, billed at the
    # selected model's standard rates). No `-fast` / `-flex` row: no host
    # catalog declares either spelling.
    "gpt-6.1-sol-pro": {
        "contract_model_id": "gpt-6.1-sol",
        "reasoning_mode": "pro",
        "service_tier": "standard",
    },
    # GPT-6.1 Terra's pro reasoning mode, on the Sol terms above: the
    # reasoning guide gives `pro` to GPT-6 models at the selected model's
    # standard rates, and OpenRouter lists `openai/gpt-6.1-terra-pro` at the
    # base 1/5 card (read 2026-10-27). No `-fast` / `-flex` row.
    "gpt-6.1-terra-pro": {
        "contract_model_id": "gpt-6.1-terra",
        "reasoning_mode": "pro",
        "service_tier": "standard",
    },
    # The first-party API's moving pointer to the current Flash generation
    # (api-docs.deepseek.com, read 2026-09-11: DeepSeek-V4.1-Flash). The next
    # Flash release moves it, which is exactly why it is a declared row with
    # a read date and not a second exact contract.
    "deepseek-flash": {
        "contract_model_id": "deepseek-v4.1-flash",
        "reasoning_mode": "thinking",
        "service_tier": "standard",
    },
    # DeepSeek-V4.1-Flash-1017, the 2026-10-17 upgrade the pointer above now
    # serves ("The API calling method and pricing remain unchanged",
    # api-docs.deepseek.com/updates, read 2026-11-06). DeepSeek accepts no
    # such model name; the spelling is a relay's (Hermes' static OpenRouter
    # catalog lists `deepseek/deepseek-v4.1-flash-1017`, "dated snapshot of
    # v4.1-flash"), so a child observed under it keeps the V4.1 Flash
    # contract, price, and calibration. Its row equals the pointer's, so the
    # plugin also labels it with the pointer's category; it is not a pointer
    # itself. The MMDD suffix is not the `-YYYY-MM-DD` shape and never
    # projects on its own.
    "deepseek-v4.1-flash-1017": {
        "contract_model_id": "deepseek-v4.1-flash",
        "reasoning_mode": "thinking",
        "service_tier": "standard",
    },
    # Claude Opus 5.5's second spellings, the same model at the contract's
    # own mode and tier. The Bedrock id is the contract's own
    # `served_ids.bedrock` (platform.claude.com models overview, read
    # 2026-09-23); the dotted form is the gateway spelling OpenRouter's live
    # model listing returned on 2026-09-23 (`anthropic/claude-opus-5.5`; the
    # provider prefix is stripped before this lookup). Bedrock's regional
    # inference-profile ids (`us.anthropic.claude-opus-5-5` and siblings) are
    # not declared: no vendor page listing them was read.
    "anthropic.claude-opus-5-5": {
        "contract_model_id": "claude-opus-5-5",
        "reasoning_mode": "thinking",
        "service_tier": "standard",
    },
    "claude-opus-5.5": {
        "contract_model_id": "claude-opus-5-5",
        "reasoning_mode": "thinking",
        "service_tier": "standard",
    },
    # Claude Sonnet 5.5's second spellings, on the Opus 5.5 terms above: the
    # Bedrock id is the contract's own `served_ids.bedrock`; the dotted form
    # is OpenRouter's (`anthropic/claude-sonnet-5.5`, listed in the Hermes
    # OpenRouter catalog read 2026-10-01).
    "anthropic.claude-sonnet-5-5": {
        "contract_model_id": "claude-sonnet-5-5",
        "reasoning_mode": "thinking",
        "service_tier": "standard",
    },
    "claude-sonnet-5.5": {
        "contract_model_id": "claude-sonnet-5-5",
        "reasoning_mode": "thinking",
        "service_tier": "standard",
    },
    # Claude Haiku 5.5's second spellings, on the same terms: the Bedrock id is
    # the contract's own `served_ids.bedrock` (platform.claude.com models
    # overview, read 2026-10-13); the dotted form is OpenRouter's
    # (`anthropic/claude-haiku-5.5`, listed in the Hermes static model catalog
    # at origin/main 63d0b941200, read 2026-10-13).
    "anthropic.claude-haiku-5-5": {
        "contract_model_id": "claude-haiku-5-5",
        "reasoning_mode": "thinking",
        "service_tier": "standard",
    },
    "claude-haiku-5.5": {
        "contract_model_id": "claude-haiku-5-5",
        "reasoning_mode": "thinking",
        "service_tier": "standard",
    },
    # TypeSafe's two published aliases (docs.typesafe.ai/models, read
    # 2026-09-21). Both resolve to `jev-1.13.0` today and both MOVE on the
    # next release -- `jev-preview` first, whenever a preview build exists --
    # which is why each is a declared row with a read date rather than a
    # second contract. The bare word `jev` is deliberately absent: a gateway
    # spells it `typesafe/jev` but no vendor page describes it, so family
    # recognition covers it and no contract is inherited on a guess.
    "jev-latest": {
        "contract_model_id": "jev-1.13.0",
        "reasoning_mode": "none",
        "service_tier": "standard",
    },
    "jev-preview": {
        "contract_model_id": "jev-1.13.0",
        "reasoning_mode": "none",
        "service_tier": "standard",
    },
}

# Declared aliases that are the SAME model at the contract's own reasoning
# mode and service tier — a vendor's second spelling, nothing more. A shipped
# chain may name the pointer instead of the exact id (DeepSeek serves
# `deepseek-flash` and rejects `deepseek-v4.1-flash`), so a child observed
# under the exact id must still label the category that names its pointer.
# Mode and tier variants (`gpt-6-astra-pro`, `-fast`, `-flex`) are NOT
# pointers: the forward projection is honest for them, the reverse is not.
# Mirrored in the plugin bundle; the parity test pins both tables and that
# every entry here is a declared row at the contract's own mode and tier.
EXACT_CONTRACT_POINTER_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "deepseek-v4.1-flash": ("deepseek-flash",),
}


def _unqualified_model_id(model_id: str) -> str:
    normalized = str(model_id or "").strip().casefold()
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[1]
    return normalized


# A vendor's dated snapshot id (OpenAI's `<model>-YYYY-MM-DD`, e.g.
# `gpt-5.6-terra-2026-07-09`) is the base model pinned to a release date: the
# same contract at the same reasoning mode and service tier. Some providers
# serve only the dated form, so a user who confirms it must still be
# recognized as running the base. This is the one suffix rule the catalog
# applies without a declared row, and it is bounded twice: only this exact
# trailing shape matches, and it projects only onto a base the caller already
# knows (a contract, a declared row, a chain alias). An unknown base with a
# date stays unknown. Mirrored in the plugin bundle; the parity test pins the
# pattern.
_DATED_SNAPSHOT_SUFFIX: Final = re.compile(
    r"^(?P<base>.+)-(?P<date>\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))$"
)


def dated_snapshot_base(model_id: str) -> str:
    """Return the base alias of a ``<base>-YYYY-MM-DD`` snapshot id, else ''.

    Shape only: the caller decides whether the base is one it knows.
    """
    match = _DATED_SNAPSHOT_SUFFIX.match(_unqualified_model_id(model_id))
    return match.group("base") if match else ""


def _dated_snapshot_projection(canonical: str) -> tuple[str, str, str] | None:
    """Project a dated snapshot onto the contract its base already resolves to."""
    base = dated_snapshot_base(canonical)
    # One date only: a snapshot of a snapshot is not a shape the vendor ships.
    if not base or dated_snapshot_base(base):
        return None
    projection = model_contract_projection(base)
    if projection is None:
        return None
    return (
        projection["contract_model_id"],
        projection["reasoning_mode"],
        projection["service_tier"],
    )


def model_contract_projection(model_id: str) -> dict[str, str] | None:
    """Resolve an exact, explicitly inherited, or dated-snapshot contract without guessing."""
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
        snapshot = _dated_snapshot_projection(canonical)
        if snapshot is None:
            return None
        contract_id, reasoning_mode, service_tier = snapshot
        provenance = "dated_snapshot"
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


def _contract_projection_provenance(projection: Mapping[str, str]) -> str:
    """Recover the contract projection origin without reading route metadata."""
    canonical = str(projection["canonical_model_id"])
    contract_id = str(projection["contract_model_id"])
    if canonical == contract_id:
        return "exact"
    if dated_snapshot_base(canonical):
        return "dated_snapshot"
    return "declared_inheritance"


def contract_model_id(model_id: str) -> str:
    """Return the exact/declared contract key, or the normalized unknown id."""
    projection = model_contract_projection(model_id)
    return str(projection["contract_model_id"]) if projection is not None else _unqualified_model_id(model_id)


def model_contract(model_id: str) -> Mapping[str, object] | None:
    """Return the exact or explicitly inherited documented contract, or None."""
    projection = model_contract_projection(model_id)
    return MODEL_CONTRACTS.get(str(projection["contract_model_id"])) if projection is not None else None


def contract_documents_effort(model_id: str, effort: str) -> bool:
    """Whether the model's contract lists ``effort`` verbatim as a ladder rung."""
    contract = model_contract(model_id)
    if contract is None:
        return False
    normalized = str(effort or "").strip().casefold()
    return bool(normalized) and normalized in tuple(str(value) for value in contract.get("reasoning_efforts", ()))


def contract_surface_efforts(model_id: str, surface: str) -> tuple[str, ...] | None:
    """The ladder the contract records for one executor surface, or None.

    None means the contract records no surface-specific ladder, so the API
    page's ladder is the only one on record.
    """
    contract = model_contract(model_id)
    ladders = contract.get("surface_efforts") if contract is not None else None
    if not isinstance(ladders, Mapping):
        return None
    ladder = ladders.get(str(surface or "").strip().casefold())
    return tuple(str(rung) for rung in ladder) if ladder is not None else None


def _raise_target(supported: tuple[str, ...], requested: str, floor: str) -> str:
    """The lowest documented rung above ``requested`` on the canonical ladder.

    A contract's ladder is ordered weakest first. The floor is the answer
    whenever it sits above the request (Astra: `off` and `minimal` both go to
    `low`); when the floor is the no-reasoning rung (`none`) a request for
    some reasoning is raised past it rather than lowered onto it.
    """
    # Imported here: model_routing imports this module at load time.
    from .model_routing import REASONING_EFFORT_LADDER

    def position(rung: str) -> int:
        canonical = "off" if rung == "none" else rung
        return REASONING_EFFORT_LADDER.index(canonical) if canonical in REASONING_EFFORT_LADDER else -1

    requested_position = position(requested)
    for rung in supported:
        if position(rung) > requested_position:
            return rung
    return floor


def contract_effort_floor(model_id: str, effort: str) -> tuple[str, str] | None:
    """Return (rung, reason) when ``effort`` is a documented-unsupported rung.

    The rung is the documented floor, or — when the floor is `none` and so
    sits below the request — the lowest documented rung above the request.
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
    target = _raise_target(supported, normalized, floor)
    if target == floor:
        return floor, (
            f"`{normalized}` is below `{contract['model_id']}`'s documented effort ladder "
            f"({detail}); raised to the documented floor `{floor}`"
        )
    return target, (
        f"`{normalized}` is not a rung of `{contract['model_id']}`'s documented effort ladder "
        f"({detail}); raised to `{target}`, the lowest documented rung above it, rather than "
        f"lowered to the floor `{floor}`"
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


def _selectable_effort_vocabulary() -> tuple[str, ...]:
    """The picker's vocabulary, derived from the canonical ladder.

    `off` is OMH's older spelling of the no-thinking rung; the Hermes
    boundary (and the picker) spell it `none`. Imported lazily because
    `model_routing` imports this module at load time.
    """
    from .model_routing import REASONING_EFFORT_LADDER

    return tuple("none" if rung == "off" else rung for rung in REASONING_EFFORT_LADDER)


def contract_effort_option(model_id: str, *, surface: str = "hermes") -> dict[str, object] | None:
    """The built-in selectable effort ladder for one model id, or None.

    The list is the contract's documented `reasoning_efforts` (or the
    contract's `surface_efforts` for ``surface`` when one is recorded), in
    canonical vocabulary order. None means the contract table has no
    authority for the id — never "every rung": an unknown model stays
    unconfigured in the picker.

    `none` is added only for a documented disable capability: an explicit
    rung, Haiku 5.5's documented_traits, or DeepSeek V4.1 Flash's
    effort_mapping.note. Absence from unsupported_efforts is not evidence
    of support. The latter two facts are named explicitly rather than
    inferred by parsing English prose or widening the contract schema.
    """
    projection = model_contract_projection(model_id)
    if projection is None:
        return None
    contract_id = str(projection["contract_model_id"])
    contract = MODEL_CONTRACTS.get(contract_id)
    if contract is None:
        return None
    surface_ladder = contract_surface_efforts(model_id, surface) if surface else None
    raw_rungs = surface_ladder if surface_ladder is not None else contract.get("reasoning_efforts")
    if not isinstance(raw_rungs, (list, tuple)) or not raw_rungs:
        # No documented ladder (the non-generative contract) is no authority,
        # not an explicit empty choice.
        return None
    vocabulary = _selectable_effort_vocabulary()
    rungs = tuple(str(rung) for rung in raw_rungs)
    unknown = [rung for rung in rungs if rung not in vocabulary]
    if unknown:
        raise ValueError(
            f"contract {contract_id!r} declares efforts outside the selectable vocabulary: {unknown}"
        )
    efforts = tuple(rung for rung in vocabulary if rung in set(rungs))
    thinking_disable = "none" in rungs or (
        surface_ladder is None and contract_id in {"claude-haiku-5-5", "deepseek-v4.1-flash"}
    )
    if thinking_disable and "none" not in efforts:
        efforts = ("none",) + efforts
    return {
        "efforts": efforts,
        "source": "contract",
        "model_id": contract_id,
        "provenance": _contract_projection_provenance(projection),
        "thinking_disable": thinking_disable,
    }


__all__ = [
    "DATA_HANDLING_ACCOUNT_SCOPE",
    "DATA_HANDLING_RETENTION_VALUES",
    "DATA_HANDLING_TRAINING_USE_VALUES",
    "DECLARED_MODEL_CONTRACT_PROJECTIONS",
    "EFFORT_FLOOR_KIND",
    "EXACT_CONTRACT_POINTER_ALIASES",
    "MODEL_CONTRACTS",
    "RETENTION_BOUNDED",
    "RETENTION_INDEFINITE",
    "RETENTION_NONE",
    "RETENTION_NOT_RECORDED",
    "TRAINING_USE_EXCLUDED",
    "TRAINING_USE_INCLUDED",
    "TRAINING_USE_NOT_RECORDED",
    "MODEL_CONTRACT_CLAIM_BOUNDARY",
    "MODEL_CONTRACT_PROJECTION_CLAIM_BOUNDARY",
    "MODEL_CONTRACT_PROJECTION_SCHEMA_VERSION",
    "MODEL_CONTRACT_SCHEMA_VERSION",
    "contract_documents_effort",
    "contract_effort_floor",
    "contract_effort_option",
    "contract_model_id",
    "contract_surface_efforts",
    "dynamic_effort_guidance",
    "model_contract",
    "model_contract_projection",
]
