from __future__ import annotations

from collections.abc import Callable

from .catalog_types import HERMES_USAGE_SURFACES_CLAUSE


def native_capability_skill_definitions(feature_surface_skill: Callable[..., object]) -> tuple[object, ...]:
    return (
        feature_surface_skill(
            "decision-recall",
            "[omh] Previously rejected options to revisit: recall scoped reviewed rejected decisions without elevating them to approved memory.",
            (
                "decision-recall",
                "rejected decision recall",
                "rejected decisions",
                "why was this rejected",
                "previously rejected alternative",
            ),
            "Use for scoped reviewed rejected-decision context; it is not approved memory or execution evidence.",
            category="memory",
            phase="decision-recall",
            next_action="show_rejected_decision_recall",
            boundary="Rejected-decision context is reviewed OMH-local context, not approved memory, Hermes memory, or execution evidence.",
            good_prompt="Show rejected decisions for this project before we choose an alternative.",
            bad_prompt="Claim the recalled rejected decision is an approved memory write or proof the replacement ran.",
            expected_outputs=("rejected_decision_recall/v1", "scoped rejected-decision matches", "claim boundary"),
            artifact_expectations=("rejected_decision_recall/v1 metadata-only recall result",),
            final_checklist=(
                "The query, scope, tags, stale policy, and match limit are explicit.",
                "Only reviewed rejected candidates are returned; expired candidates stay excluded.",
                "Recall output is not presented as approved memory, source freshness, or execution evidence.",
            ),
            situations=(
                "what did we rule out",
                "why did we drop this",
                "alternatives we rejected before",
                "was this idea turned down already",
                "options we decided against",
                "why an approach was dismissed",
            ),
            recovery_notes=(
                "If the query, scope, tags, stale policy, or match limit is unspecified, no rejected-decision match stands yet; mark recall unresolved and hand back one question fixing the missing filter.",
                "If a candidate's reviewed-rejected status or expiry cannot be checked, retain only matches that passed those checks, mark remaining recall unresolved, and hand back rejected_decision_recall/v1 with the claim boundary and missing checks.",
            ),
        ),
        feature_surface_skill(
            "run-efficiency",
            "[omh] Run efficiency and context usage report: report supplied local run efficiency while provider data stays unobserved.",
            (
                "run-efficiency",
                "run efficiency report",
                "local run efficiency",
                "context utilization",
                "tool duration report",
            ),
            "Use for a bounded local efficiency report from supplied metadata with provider gaps explicit.",
            category="observability",
            phase="run-efficiency",
            next_action="show_run_efficiency_report",
            boundary=(
                "Run efficiency is supplied OMH-local metadata plus, for a named Hermes session, Hermes' own "
                "recorded usage; it is not provider billing, cron, or host-load evidence."
            ),
            good_prompt="Show the local run efficiency report from this run's supplied context budget and timings.",
            bad_prompt="Claim this report proves provider billing, host load, or cron execution without observations.",
            expected_outputs=(
                "run_efficiency_report/v1",
                "context utilization",
                "host_usage: Hermes' recorded usage for a named session, or not_observed",
                "not_observed provider and billing gaps",
            ),
            artifact_expectations=(
                "run_efficiency_report/v1 metadata-only report",
                "supplied `session_activity_receipt/v1` when available; unavailable metrics stay unavailable, never zero",
                "`host_usage` from the Hermes-accounted part of the cost receipt `omh_run_summary` returns (the "
                "session, its delegated children, and its kanban workers; `--hermes-session`, and a local Hermes "
                "terminal holds the id in `$HERMES_SESSION_ID`): observed only when Hermes recorded tokens for it; "
                "no session row or no tokens stays not_observed, never zero",
            ),
            final_checklist=(
                "The run ID, context budget, surfaces, and supplied observations are explicit.",
                "Host usage is Hermes' recorded accounting for the named session, observed only when it recorded "
                "tokens; provider billing and cron stay not_observed.",
                "The report does not intercept, route, or execute provider or host work.",
            ),
            why_this_exists=(
                "`run-efficiency` exists so a question about how a run spent its time, tools, and context gets the "
                "supplied timings and context budget, plus what Hermes itself recorded for a named session's tokens "
                "and cost, instead of figures a model guesses."
            ),
            do_not_use_when=(
                "The user asks only what this Hermes conversation has used or cost so far; "
                f"{HERMES_USAGE_SURFACES_CLAUSE}.",
                "The user wants service latency, uptime, error rates, or supplied metric-provider figures; use "
                "`ops-observability-card`.",
                "The user wants a provider invoice or quota truth; no OMH report observes either, so name the "
                "provider's own console as the source.",
            ),
            situations=(
                "how efficient was the last run",
                "which tools were slow",
                "run timing breakdown",
                "time spent per tool in this run",
                "wasted steps in this session",
            ),
            recovery_notes=(
                "If the named Hermes session has no row or recorded tokens, retain supplied timings and context data in run_efficiency_report/v1, mark host_usage not_observed, and hand back the session ID for a recorded-usage check.",
                "If session_activity_receipt/v1 omits tool durations or context-budget metrics, retain its available observations, mark the missing metrics not_observed rather than zero, and hand back the exact missing measurements.",
            ),
        ),
        feature_surface_skill(
            "provider-profile-posture",
            "[omh] Provider credentials without exposure: prepare provider-profile metadata without reading secrets or calling providers.",
            (
                "provider-profile-posture",
                "provider profile posture",
                "provider profile readiness",
                "secret presence confirmation",
                "connector profile posture",
            ),
            "Use for provider/profile capability and secret-presence preparation before connector or credential action.",
            category="operations",
            phase="provider-profile-posture",
            next_action="prepare_provider_profile_posture",
            boundary="Provider/profile posture is OMH-local preparation metadata; it is not credential validation, provider connectivity, model routing, payment/wallet, or host execution evidence.",
            good_why="The card records which key names are present, missing, or unknown, and never reads a value.",
            good_prompt="Prepare provider profile posture for this connector using metadata-only secret presence.",
            why_this_exists=(
                "`provider-profile-posture` exists so a profile's required secret names and capabilities are recorded as present, "
                "missing, or unknown without any secret value being read or any provider being called."
            ),
            do_not_use_when=(
                "Choosing or adopting a connector; use `external-connector-readiness`.",
                "Listing every tool and credential a workflow needs; use `toolbelt-readiness`.",
                "Connecting a model provider or its login; use `model-setup`.",
            ),
            bad_prompt="Read the secret, validate the credential, call the provider, or create a payment route.",
            expected_outputs=("provider_profile_posture/v1", "metadata-only secret requirements", "allowed and prohibited actions"),
            artifact_expectations=("provider_profile_posture/v1 metadata-only preparation record",),
            final_checklist=(
                "Provider ID, profile ID, requested capabilities (chat, embedding, tool_call, image), and secret-presence metadata are explicit, and `omh ops provider-profile-posture --input <file>` produced the record from JSON with `provider_profile_posture_input/v1`, `provider_id`, `profile_id`, `requested_capabilities`, `secret_requirements` as `{name, present}`, optional `host_observations`.",
                "No secret value, credential validation, provider call, model route, wallet, or payment action is claimed.",
                "Any host observation reference remains supplied metadata, not a live connector check.",
            ),
            situations=(
                "is the api key present without showing it",
                "provider profile setup",
                "which secrets does this connector need",
                "check credentials exist safely",
                "capabilities of a provider profile",
            ),
            recovery_notes=(
                "If provider ID or profile ID is missing, retain the supplied capability requirements, mark provider_profile_posture/v1 unresolved, and hand back a request for the missing ID without reading any secret.",
                "If secret-presence metadata is absent, retain the named provider, profile, and requested capabilities, mark secret presence not_observed, and hand back metadata-only secret requirements plus allowed and prohibited actions.",
                "If only a host observation reference is supplied, retain it as metadata, mark provider connectivity not_observed, and hand back provider_profile_posture/v1 without claiming credential validation or making a provider call.",
            ),
        ),
    )


def native_capability_harnesses(feature_surface_harness: Callable[..., object]) -> tuple[object, ...]:
    return (
        feature_surface_harness(
            "decision-recall",
            "Prepare a scope-limited recall of reviewed rejected decisions.",
            "Use when an operator needs past rejected alternatives before a new decision.",
            ("query", "scope", "optional tags", "stale policy", "result limit"),
            ("rejected_decision_recall/v1", "ranked rejected candidates", "claim boundary"),
            quality_tier="workflow-surface-gated",
            evidence_ladder=("query_scoped", "rejected_candidates_matched", "recall_rendered"),
            wrapper_actions=("show_rejected_decision_recall",),
            overclaim_guard="A rejected-decision recall is not approved memory, Hermes memory, source freshness, or execution evidence.",
        ),
        feature_surface_harness(
            "run-efficiency",
            "Render a deterministic report from supplied local run metadata.",
            "Use when an operator has run/context-budget metadata and needs a bounded latency or context report.",
            ("run ID", "context budget", "surface counts", "supplied observations", "optional Hermes session id"),
            ("run_efficiency_report/v1", "context utilization", "not_observed gaps"),
            quality_tier="workflow-surface-gated",
            evidence_ladder=("input_validated", "local_report_prepared", "not_observed_gaps_rendered"),
            wrapper_actions=("show_run_efficiency_report",),
            overclaim_guard=(
                "A run efficiency report is not provider billing, cron, host-load, or performance proof beyond "
                "supplied local metadata and Hermes' recorded usage for a named session."
            ),
        ),
        feature_surface_harness(
            "provider-profile-posture",
            "Prepare a provider/profile posture card without accessing a provider or secret value.",
            "Use before adopting a connector profile when capability and secret-presence requirements need a safe review boundary.",
            ("provider ID", "profile ID", "requested capabilities", "secret-presence metadata"),
            ("provider_profile_posture/v1", "allowed actions", "prohibited actions"),
            quality_tier="workflow-surface-gated",
            evidence_ladder=("profile_scoped", "secret_presence_declared", "posture_prepared"),
            wrapper_actions=("prepare_provider_profile_posture",),
            overclaim_guard="A provider/profile posture is not secret access, credential validation, provider connectivity, model routing, payment, wallet, or host execution evidence.",
        ),
    )


def native_capability_surface_exposures(surface_exposure: Callable[..., object]) -> tuple[object, ...]:
    projections = ("routable", "installable", "playbook", "harness", "workflow_reference", "capability")
    return (
        surface_exposure(
            "decision-recall",
            "workflow_skill",
            projections,
            True,
            "primary_workflow_skill",
            "Use as an installed Hermes workflow skill to recall scoped rejected alternatives without promoting them to approved memory or execution evidence.",
        ),
        surface_exposure(
            "run-efficiency",
            "workflow_skill",
            projections,
            True,
            "primary_workflow_skill",
            "Use as an installed Hermes workflow skill to render bounded local run efficiency from supplied metadata, with Hermes' recorded usage for a named session, and keep provider and billing gaps visible.",
        ),
        surface_exposure(
            "provider-profile-posture",
            "workflow_skill",
            projections,
            True,
            "primary_workflow_skill",
            "Use as an installed Hermes workflow skill to prepare provider/profile metadata without reading secrets, calling providers, or routing models.",
        ),
    )
