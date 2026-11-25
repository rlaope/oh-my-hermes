---
name: "omh-support-operations"
description: "[omh] Support ticket your team must answer or escalate: turn a support case into a clear customer reply, severity path, and owned next step. Use when the user says: support escalation, customer support reply, ticket triage, 고객 지원 에스컬레이션, 고객 답변 초안, 지원 티켓 분류."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, triage]
    category: triage
    phase: support-operations
    role: operator
    quality_tier: triage-gated
    related_skills: [omh-feedback-triage, omh-content-operator, omh-apps, omh-live-incident-response, omh-reliability-review]
---

# Support Operations

Required: support case, known facts, customer impact, support tier or SLA, and arrival time, available ownership or escalation path. Output: customer-safe reply draft with stated facts, unknowns, and tone, issue/severity/impact/escalation matrix, internal next-step and owner handoff brief, missing repro, account, entitlement, or approval evidence list.

## Why This Exists

`support-operations` turns a bounded customer case into response and escalation guidance without treating drafts or recommendations as helpdesk actions.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Research and company ops** - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

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

Expert clarification questions:
- `support case`
  - English: Which support case should we examine first?
  - Korean: 어떤 지원 사례를 먼저 살펴봐야 하나요?

Artifact contracts:

This label denotes the machine-enforcement level, not a skill quality score and not an observed evidence state.

- contract_id: `support-operations`; enforcement_level: `guidance_only`; consumer_id: `none`

Safety rules:

- Keep customer-safe facts, unknowns, and escalation recommendations distinct.
- Do not claim ticket mutation, message send, refund, account action, or case outcome.

## Completion Checklist

- The reply states only case facts and unknowns and promises no timing, refund or fix the user did not authorize.
- Severity and priority are separate, with SLA time left when supplied; account takeover, exposed personal data, legal or regulator contact, payment disputes and safety go to their owner, not a product escalation.

## Recovery Notes

- If customer impact or reproduction evidence is missing, retain the stated case facts, mark severity tentative, and hand back the reply draft and missing repro, account, or entitlement evidence list.
- If no escalation owner or path is available, retain the issue/severity/impact/escalation matrix, mark ownership unresolved, and hand back the internal next-step and owner handoff brief with the owner question.

## Runtime Evidence

Preferred harness for this skill: `ops-review`.

```sh
omh runtime record --skill support-operations --harness ops-review --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
