---
name: "omh-lifecycle-growth"
description: "[omh] Churn or weak activation among users: turn an observed onboarding, activation, retention, re-engagement, referral, or monetization problem into one consent-safe in-app journey or growth experiment plan with a bounded readout and an explicit decision. Use when the user says: lifecycle-growth, lifecycle growth, lifecycle marketing, lifecycle messaging, in-app journey, in-app message campaign, onboarding journey, onboarding nudge."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, strategy]
    category: strategy
    phase: lifecycle-growth
    role: operator
    quality_tier: decision-gated
    related_skills: [omh-content-operator, omh-data-analysis, omh-automation-blueprint, omh-apps, omh-product-brief]
---

# Lifecycle Growth

Required: lifecycle objective, audience/events, consent, budget, and owner. Output: a brief, audience/safety policy, experiment, readout, and handoff.

**HOLD:** Missing inputs or failed contract gates. Prepared OMH routing is not execution or approval. **Completion:** Follow the full-contract checklist.

Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

Agent/operator: `omh runtime workflow-artifact lifecycle-growth build --input <json-file-or->` builds bounded metadata only. Shared operator reference: `skill_view(name='omh-routing', file_path='references/workflow-artifacts.md')`.

Contract: `references/full-contract.md`. Procedure: `references/procedure.md`.

## Completion Checklist

- Preserve workflow intent and stop conditions; load the full contract before claiming completion.
- Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.
- Record observed delegation results; otherwise return `not_available` or `not_observed`.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
- Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

## Recovery Notes

- If a required input, authority, or runtime capability is unavailable, HOLD and name the smallest safe next action; do not invent observation or approval.

## Workflow Lane

- Current lane: **Research and company ops** - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
