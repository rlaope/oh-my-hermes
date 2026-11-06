---
name: "omh-ops-review"
description: "[omh] Recurring operating status and blockers: status, risks, blockers, priorities, and follow-ups. Use when the user says: ops-review, ops review, weekly ops review, status review, operating review, release risks, risks and blockers, priorities."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: status-review
    role: operator
    quality_tier: status-gated
---

# Ops Review

This is an OMH `ops-review` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

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

- If status evidence covers only part of the requested time window, retain the dated observations in the status summary, mark uncovered status not_observed, and hand back the missing periods and affected priorities.
- If a blocker needs a code fix but no follow-up is accepted, retain the observed blocker and risk, mark remediation unresolved, and hand back the follow-up action for acceptance before delegation.



## When to Use

Use when Hermes should summarize observed status, risks, blockers, priorities, and follow-up actions for recurring operating work.

    Strong routing signals: `ops-review`, `ops review`, `weekly ops review`, `status review`, `operating review`, `release risks`, `risks and blockers`, `priorities`, `weekly status`, `운영 리뷰`, `주간 운영`, `상태 리뷰`, `리스크`, `블로커`, `우선순위`, `릴리즈 리스크`

## Catalog Metadata

Category: `operations`
Phase: `status-review`
Quality tier: `status-gated`
Reasoning demand: `light`

Quality bar:

- Tie every status claim to observed evidence or mark it as unknown.
- Separate risks, blockers, priorities, and follow-up owners.
- Keep code fixes as explicit follow-up handoffs, not implicit ops-review output.

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
