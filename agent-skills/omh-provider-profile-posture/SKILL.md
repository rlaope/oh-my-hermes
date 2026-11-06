---
name: "omh-provider-profile-posture"
description: "[omh] Provider credentials without exposure: prepare provider-profile metadata without reading secrets or calling providers. Use when the user says: provider-profile-posture, provider profile posture, provider profile readiness, secret presence confirmation, connector profile posture, 공급자 프로필 상태, 시크릿 존재 확인, 커넥터 준비 상태."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: provider-profile-posture
    role: operator
    quality_tier: workflow-surface-gated
---

# Provider Profile Posture

This is an OMH `omh-provider-profile-posture` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`omh-provider-profile-posture` exists so Hermes users can ask for this workflow in chat and get a structured, checkable answer instead of an improvised one.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: Prepare provider profile posture for this connector using metadata-only secret presence.
- Expected behavior: Produce `prepare_provider_profile_posture` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: Read the secret, validate the credential, call the provider, or create a payment route.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Provider ID, profile ID, requested capabilities, and secret-presence metadata are explicit.
- No secret value, credential validation, provider call, model route, wallet, or payment action is claimed.
- Any host observation reference remains supplied metadata, not a live connector check.

## Recovery Notes

- If provider ID or profile ID is missing, retain the supplied capability requirements, mark provider_profile_posture/v1 unresolved, and hand back a request for the missing ID without reading any secret.
- If secret-presence metadata is absent, retain the named provider, profile, and requested capabilities, mark secret presence not_observed, and hand back metadata-only secret requirements plus allowed and prohibited actions.
- If only a host observation reference is supplied, retain it as metadata, mark provider connectivity not_observed, and hand back provider_profile_posture/v1 without claiming credential validation or making a provider call.



## When to Use

Use for provider/profile capability and secret-presence preparation before connector or credential action.

    Strong routing signals: `provider-profile-posture`, `provider profile posture`, `provider profile readiness`, `secret presence confirmation`, `connector profile posture`, `공급자 프로필 상태`, `시크릿 존재 확인`, `커넥터 준비 상태`

## Catalog Metadata

Category: `operations`
Phase: `provider-profile-posture`
Quality tier: `workflow-surface-gated`
Reasoning demand: `light`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

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

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
