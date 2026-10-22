---
name: "omh-ops-review"
description: "[omh] Recurring operating status and blockers: status, risks, blockers, priorities, and follow-ups. Use when the user says: ops-review, ops review, weekly ops review, status review, operating review, release risks, risks and blockers, priorities."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: status-review
    role: operator
    quality_tier: status-gated
    related_skills: [omh-sales-pipeline-review, omh-operating-rhythm]
---

# Ops Review

This is a Hermes-native `ops-review` workflow skill.

## Why This Exists

`ops-review` exists to keep `operations` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The review is over sales stages, forecast categories, deal aging, or seller forecast rather than generic operating status; use `omh-sales-pipeline-review`.
- The primary output is durable cadence history, minutes, a decision log, or action history; use `omh-operating-rhythm`.

## Examples

Good example:

- Prompt: ops-review: summarize this week’s support queue, release blockers, owner status, and next operating risks.
- Expected behavior: Create an operations status review with owners, blockers, evidence gaps, and next actions.
- Why: The request is an operating review rather than a one-off plan or coding handoff.

Bad example:

- Prompt: ops-review: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `ops-review`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Completion Checklist

- Confirm the workflow target, evidence boundary, and stop condition are named.
- Report which outputs are prepared, observed, blocked, or missing.
- Name the smallest next verification or handoff instead of claiming completion from narration.

## Recovery Notes

- If required context is missing, ask one blocking question or route back to the narrower workflow.
- If runtime or wrapper evidence is unavailable, keep the status as not_observed and expose the next observable action.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `model-optimization`, `inference-serving`, `model-finetuning`, `research-brief`, `+26 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should summarize observed status, risks, blockers, priorities, and follow-up actions for recurring operating work.

    Strong routing signals: `ops-review`, `ops review`, `weekly ops review`, `status review`, `operating review`, `release risks`, `risks and blockers`, `priorities`, `weekly status`, `운영 리뷰`, `주간 운영`, `상태 리뷰`, `리스크`, `블로커`, `우선순위`, `릴리즈 리스크`

## Catalog Metadata

Category: `operations`
Phase: `status-review`
Hermes role: `operator`
Quality tier: `status-gated`
Reasoning demand: `light`

Quality bar:

- Tie every status claim to observed evidence or mark it as unknown.
- Separate risks, blockers, priorities, and follow-up owners.
- Keep code fixes as explicit follow-up handoffs, not implicit ops-review output.

Handoff policy:

Keep operating review and status narration in Hermes; delegate code fixes only from explicit accepted follow-up items.

Required inputs:

- status evidence
- scope
- time window
- known risks

Expected outputs:

- status summary
- risks
- blockers
- priorities
- follow-up actions

Artifact expectations:

- ops review record or status artifact when a wrapper captures it

Artifact contracts:

This label denotes the machine-enforcement level, not a skill quality score and not an observed evidence state.

- contract_id: `ops-review`; enforcement_level: `guidance_only`; consumer_id: `none`

Safety rules:

- Do not infer status from missing evidence.
- Separate observed facts, risks, blockers, decisions, and follow-up actions.
- Do not report review, CI, release, or merge readiness from an ops summary alone.

## Runtime Evidence

Preferred harness for this skill: `ops-review`.

```sh
omh runtime record --skill ops-review --harness ops-review --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
