---
name: "omh-support-operations"
description: "[omh] Turn a support case into a clear customer reply, severity path, and owned next step. Use when the user says: support escalation, customer support reply, ticket triage, 고객 지원 에스컬레이션, 고객 답변 초안, 지원 티켓 분류."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, triage]
    category: triage
    phase: support-operations
    role: operator
    quality_tier: triage-gated
---

# Support Operations

This is a Hermes-native `support-operations` workflow skill.

## Why This Exists

`support-operations` turns a bounded customer case into response and escalation guidance without treating drafts or recommendations as helpdesk actions.

## Do Not Use When

- The request clusters a backlog of customer signals to find product patterns or roadmap candidates; use `feedback-triage`.
- The user only needs a generic, non-support marketing or email rewrite with no case, severity, or escalation context; use `content-operator`.
- The request asks to send a reply, change ticket priority or status, issue a refund, modify an account, or update a helpdesk; use `connector-operator` with an explicit target and observed result.
- The request is an active reliability incident or postmortem rather than a support-case response; use `reliability-review`.

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

- If feedback lacks source or severity, ask for the missing signal before coding handoff.
- If the item is actually a plan or research request, route to that workflow instead of triage.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `best-practice-research`, `autoresearch-goal`, `model-optimization`, `inference-serving`, `+17 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when one or a bounded set of support contacts needs response drafting, urgency classification, incident/escalation routing, and follow-up ownership.

    Strong routing signals: `support escalation`, `customer support reply`, `ticket triage`, `고객 지원 에스컬레이션`, `고객 답변 초안`, `지원 티켓 분류`

## Catalog Metadata

Category: `triage`
Phase: `support-operations`
Hermes role: `operator`
Quality tier: `triage-gated`
Reasoning demand: `standard`

Quality bar:

- State issue, severity, impact, evidence gaps, owner, and next route.
- Draft a reply without treating it as a sent customer communication.

Handoff policy:

Keep domain framing, clarification, source/evidence synthesis, draft outputs, and next-work routing in Hermes. A prepared brief, review, reply, or plan is not an external action, approval, filing, send, publish, data mutation, implementation, review, CI, or merge claim. Prepare a connector, file, coding, or human-review handoff only when the user explicitly accepts that next step; report it only from observed evidence. Reply text is a draft, escalation is a recommendation, and no ticket state, message send, refund, account action, or customer outcome is claimed.

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

Preferred harness for this skill: `ops-review`.

```sh
omh runtime record --skill support-operations --harness ops-review --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
