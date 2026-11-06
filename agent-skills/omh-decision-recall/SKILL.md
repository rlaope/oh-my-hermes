---
name: "omh-decision-recall"
description: "[omh] Previously rejected options to revisit: recall scoped reviewed rejected decisions without elevating them to approved memory. Use when the user says: decision-recall, rejected decision recall, rejected decisions, why was this rejected, previously rejected alternative, 거절된 결정, 기각된 대안."
license: MIT
compatibility: "Requires the omh CLI on PATH (pip install oh-my-hermes)."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, memory]
    category: memory
    phase: decision-recall
    role: memory-keeper
    quality_tier: workflow-surface-gated
---

# Decision Recall

This is an OMH `omh-decision-recall` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`omh-decision-recall` exists so Hermes users can ask for this workflow in chat and get a structured, checkable answer instead of an improvised one.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: Show rejected decisions for this project before we choose an alternative.
- Expected behavior: Produce `show_rejected_decision_recall` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: Claim the recalled rejected decision is an approved memory write or proof the replacement ran.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- The query, scope, tags, stale policy, and match limit are explicit.
- Only reviewed rejected candidates are returned; expired candidates stay excluded.
- Recall output is not presented as approved memory, source freshness, or execution evidence.

## Recovery Notes

- If the query, scope, tags, stale policy, or match limit is unspecified, no rejected-decision match stands yet; mark recall unresolved and hand back one question fixing the missing filter.
- If a candidate's reviewed-rejected status or expiry cannot be checked, retain only matches that passed those checks, mark remaining recall unresolved, and hand back rejected_decision_recall/v1 with the claim boundary and missing checks.



## When to Use

Use for scoped reviewed rejected-decision context; it is not approved memory or execution evidence.

    Strong routing signals: `decision-recall`, `rejected decision recall`, `rejected decisions`, `why was this rejected`, `previously rejected alternative`, `거절된 결정`, `기각된 대안`

## Catalog Metadata

Category: `memory`
Phase: `decision-recall`
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

- rejected_decision_recall/v1
- scoped rejected-decision matches
- claim boundary

Artifact expectations:

- rejected_decision_recall/v1 metadata-only recall result

Safety rules:

- Rejected-decision context is reviewed OMH-local context, not approved memory, Hermes memory, or execution evidence.
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
