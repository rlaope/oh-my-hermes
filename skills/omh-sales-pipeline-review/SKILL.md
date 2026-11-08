---
name: "omh-sales-pipeline-review"
description: "[omh] CRM pipeline or sales forecast to review: turn a supplied CRM export or pipeline snapshot into an evidence-bound pipeline health, forecast, and follow-up review. Aliases: pipeline-review, forecast-review, deal-review. Use when the user says: sales-pipeline-review, sales pipeline review, pipeline review, pipeline health, pipeline coverage, deal review, deal health, sales forecast review."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: sales-pipeline-review
    role: operator
    quality_tier: decision-gated
    related_skills: [omh-sales-development, omh-ops-review, omh-finance-analysis, omh-data-analysis, omh-feedback-triage, omh-apps]
---

# Sales Pipeline Review

Required: supplied snapshot and as-of time, definitions, prior outcomes, and owner. Output: scope, health, forecast, supported annexes, and follow-up handoff.

**HOLD:** Missing inputs or failed contract gates. Prepared OMH routing is not execution or approval. **Completion:** Follow the full-contract checklist.

Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

Agent/operator: `omh runtime workflow-artifact sales-pipeline-review prepare --input <json-file-or->` prepares bounded metadata only. Shared operator reference: `skill_view(name='omh-routing', file_path='references/workflow-artifacts.md')`.

Contract: `references/full-contract.md`. Procedure: `references/procedure.md`.

## Completion Checklist

- Preserve workflow intent and stop conditions; load the full contract before claiming completion.
- Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.
- Record observed delegation results; otherwise return `not_available` or `not_observed`.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
- Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

## Recovery Notes

- If a required input, authority, or runtime capability is unavailable, HOLD and name the smallest safe next action; do not invent observation or approval.

## Workflow Lane

- Current lane: **Research and company ops** - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
