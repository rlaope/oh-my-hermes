---
name: "omh-support-operations"
description: "[omh] Support ticket your team must answer or escalate: turn a support case into a clear customer reply, severity path, and owned next step. Use when the user says: support escalation, customer support reply, ticket triage, 고객 지원 에스컬레이션, 고객 답변 초안, 지원 티켓 분류."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, triage]
    category: triage
    phase: support-operations
    role: operator
    quality_tier: triage-gated
---

# Support Operations

This is an OMH `support-operations` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`support-operations` turns a bounded customer case into response and escalation guidance without treating drafts or recommendations as helpdesk actions.

## Do Not Use When

- The request clusters a backlog of customer signals to find product patterns or roadmap candidates; use `omh-feedback-triage`.
- The user only needs a generic, non-support marketing or email rewrite with no case, severity, or escalation context; use `omh-content-operator`.
- The request asks to send a reply, change ticket priority or status, issue a refund, modify an account, or update a helpdesk; use `omh-apps` with an explicit target and observed result.
- The request is an incident that is still open, needing severity declared, a commander assigned, and a running timeline rather than a support-case response; use `omh-live-incident-response`.
- The request is a closed incident's postmortem or reliability evidence rather than a support-case response; use `omh-reliability-review`.

## Examples

Good example:

- Prompt: Draft a calm reply for this login-outage customer and tell me whether it needs an engineering escalation.
- Expected behavior: Prepare a customer-safe reply, severity matrix, engineering escalation recommendation, and owner handoff.
- Why: The request is one support case with reply and escalation decisions, not a feedback backlog or ticket mutation.

Bad example:

- Prompt: Cluster last quarter's support feedback into roadmap opportunities.
- Expected behavior: Route to `feedback-triage`, not `support-operations`.
- Why: A historical signal backlog needs product-pattern triage rather than case-level support guidance.

## Completion Checklist

- The source boundary, signal clusters, severity, and follow-up lane are named.
- Bug, feature, research, strategy, and coding handoff outcomes stay separate.
- The next workflow is recommended before any implementation claim.

## Recovery Notes

- If customer impact or reproduction evidence is missing, retain the stated case facts, mark severity tentative, and hand back the reply draft and missing repro, account, or entitlement evidence list.
- If no escalation owner or path is available, retain the issue/severity/impact/escalation matrix, mark ownership unresolved, and hand back the internal next-step and owner handoff brief with the owner question.



## When to Use

Use when one or a bounded set of support contacts needs response drafting, urgency classification, incident/escalation routing, and follow-up ownership.

    Strong routing signals: `support escalation`, `customer support reply`, `ticket triage`, `고객 지원 에스컬레이션`, `고객 답변 초안`, `지원 티켓 분류`

## Catalog Metadata

Category: `triage`
Phase: `support-operations`
Quality tier: `triage-gated`
Reasoning demand: `standard`

Quality bar:

- State issue, severity, impact, evidence gaps, owner, and next route.
- Draft a reply without treating it as a sent customer communication.

Required inputs:

- support case
- known facts
- customer impact
- available ownership or escalation path

Expert clarification questions:
- `support case`
  - English: Which support case should we examine first?
  - Korean: 어떤 지원 사례를 먼저 살펴봐야 하나요?

Expected outputs:

- customer-safe reply draft with stated facts, unknowns, and tone
- issue/severity/impact/escalation matrix
- internal next-step and owner handoff brief
- missing repro, account, entitlement, or approval evidence list

Artifact expectations:

- prepared support case brief when a wrapper captures it

Artifact contracts:

This label denotes the machine-enforcement level, not a skill quality score and not an observed evidence state.

- contract_id: `support-operations`; enforcement_level: `guidance_only`; consumer_id: `none`

Safety rules:

- Keep customer-safe facts, unknowns, and escalation recommendations distinct.
- Do not claim ticket mutation, message send, refund, account action, or case outcome.

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
