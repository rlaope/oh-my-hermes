---
name: "omh-provider-profile-posture"
description: "[omh] Provider credentials without exposure: prepare provider-profile metadata without reading secrets or calling providers. Use when the user says: provider-profile-posture, provider profile posture, provider profile readiness, secret presence confirmation, connector profile posture, 공급자 프로필 상태, 시크릿 존재 확인, 커넥터 준비 상태."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: provider-profile-posture
    role: operator
    quality_tier: workflow-surface-gated
    related_skills: [omh-external-connector-readiness, omh-toolbelt-readiness, omh-model-setup]
---

# Provider Profile Posture

This is a Hermes-native `provider-profile-posture` workflow skill.

## Why This Exists

`provider-profile-posture` exists so a profile's required secret names and capabilities are recorded as present, missing, or unknown without any secret value being read or any provider being called.

## Do Not Use When

- Choosing or adopting a connector; use `omh-external-connector-readiness`.
- Listing every tool and credential a workflow needs; use `omh-toolbelt-readiness`.
- Connecting a model provider or its login; use `omh-model-setup`.

## Examples

Good example:

- Prompt: Prepare provider profile posture for this connector using metadata-only secret presence.
- Expected behavior: Produce `prepare_provider_profile_posture` with required context, wrapper actions, and not-evidence boundaries.
- Why: The card records which key names are present, missing, or unknown, and never reads a value.

Bad example:

- Prompt: Read the secret, validate the credential, call the provider, or create a payment route.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Provider ID, profile ID, requested capabilities (chat, embedding, tool_call, image), and secret presence are explicit, and `omh ops provider-profile-posture --input <file>` made the record from JSON with `schema_version` `provider_profile_posture_input/v1`, `provider_id`, `profile_id`, `requested_capabilities`, `secret_requirements` as `{name, present: true|false|"unknown"}`, optional `host_observations`.
- No secret value, credential validation, provider call, model route, wallet, or payment action is claimed.
- Any host observation reference remains supplied metadata, not a live connector check.

## Recovery Notes

- If provider ID or profile ID is missing, retain the supplied capability requirements, mark provider_profile_posture/v1 unresolved, and hand back a request for the missing ID without reading any secret.
- If secret-presence metadata is absent, retain the named provider, profile, and requested capabilities, mark secret presence not_observed, and hand back metadata-only secret requirements plus allowed and prohibited actions.
- If only a host observation reference is supplied, retain it as metadata, mark provider connectivity not_observed, and hand back provider_profile_posture/v1 without claiming credential validation or making a provider call.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use for provider/profile capability and secret-presence preparation before connector or credential action.

    Strong routing signals: `provider-profile-posture`, `provider profile posture`, `provider profile readiness`, `secret presence confirmation`, `connector profile posture`, `공급자 프로필 상태`, `시크릿 존재 확인`, `커넥터 준비 상태`

## Catalog Metadata

Category: `operations`
Phase: `provider-profile-posture`
Hermes role: `operator`
Quality tier: `workflow-surface-gated`
Reasoning demand: `light`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- provider_profile_posture/v1
- metadata-only secret requirements
- allowed and prohibited actions

Artifact expectations:

- provider_profile_posture/v1 metadata-only preparation record

Safety rules:

- Provider/profile posture is OMH-local preparation metadata; it is not credential validation, provider connectivity, model routing, payment/wallet, or host execution evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `provider-profile-posture`.

```sh
omh runtime record --skill provider-profile-posture --harness provider-profile-posture --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
