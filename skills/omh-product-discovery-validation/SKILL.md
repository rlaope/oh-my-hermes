---
name: "omh-product-discovery-validation"
description: "[omh] Unvalidated early product idea: test whether a customer problem, segment, and business hypothesis deserve product investment, ending in kill, pivot, persevere, or inconclusive before any PRD. Use when the user says: product-discovery-validation, product discovery validation, product discovery, customer discovery, customer discovery plan, zero to one validation, validate the problem before building, problem solution interview."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: product-discovery-validation
    role: planner
    quality_tier: decision-gated
    related_skills: [omh-research-brief, ulw-interview, omh-decide, omh-product-brief, omh-idea-to-deploy, omh-decision-prototype]
---

# Product Discovery Validation

Required: problem, segment/evidence, owner, learning budget, and criteria. Output: a decision frame, evidence and customer plan, test portfolio, receipt, and GTM hypothesis.

**HOLD:** Missing inputs or failed contract gates. Prepared OMH routing is not execution or approval. **Completion:** Follow the full-contract checklist.

Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

Agent/operator: `omh runtime workflow-artifact product-discovery-validation build --input <json-file-or->` builds bounded metadata only. Shared operator reference: `skill_view(name='omh-routing', file_path='references/workflow-artifacts.md')`.

Contract: `references/full-contract.md`. Procedure: `references/procedure.md`.

## Completion Checklist

- Preserve workflow intent and stop conditions; load the full contract before claiming completion.
- Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.
- Record observed delegation results; otherwise return `not_available` or `not_observed`.
- Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

## Recovery Notes

- If a required input, authority, or runtime capability is unavailable, HOLD and name the smallest safe next action; do not invent observation or approval.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `adversarial-consensus`, `codebase-onboarding`, `+9 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
