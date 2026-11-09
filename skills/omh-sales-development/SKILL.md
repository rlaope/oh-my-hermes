---
name: "omh-sales-development"
description: "[omh] Prospect or account worth pursuing: turn an account or market opportunity into a focused discovery, qualification, and next-step brief. Use when the user says: sales discovery, account plan, outbound messaging, 영업 발굴, 고객사 계획, 아웃바운드 메시지."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, strategy]
    category: strategy
    phase: sales-development
    role: operator
    quality_tier: decision-gated
    related_skills: [omh-decide, omh-sales-pipeline-review, omh-content-operator, omh-apps, ulw-research]
---

# Sales Development

This is a Hermes-native `sales-development` workflow skill.

## Why This Exists

`sales-development` prepares evidence-bounded discovery and qualification guidance without claiming sales execution.

## Do Not Use When

- The user needs a company-level positioning, market-entry, or strategic-options decision rather than account-level discovery; use `omh-decide`.
- The user supplies a CRM export or pipeline snapshot and needs portfolio health, aging, slipped deals, forecast calibration, or renewal-risk review; use `omh-sales-pipeline-review`.
- The user only wants a polished social post, newsletter, or one-off outbound-copy rewrite; use `omh-content-operator`.
- The user asks to send outreach, update Salesforce or HubSpot, create an opportunity, or book a meeting; use `omh-apps` with explicit recipient, object, and authority.
- The request asks for current competitor or company evidence but supplies no source material; begin with `ulw-research` before presenting claims as observed.

## Examples

Good example:

- Prompt: Build a discovery plan and qualification questions for a mid-market prospect considering our support platform.
- Expected behavior: Prepare account evidence gaps, discovery and qualification questions, value hypotheses, and an owned next-step plan.
- Why: The request is account-level sales discovery, not outreach execution or company strategy.

Bad example:

- Prompt: Write a LinkedIn launch post for our new feature.
- Expected behavior: Route to `omh-content-operator`, not `sales-development`.
- Why: A one-off social post has no account qualification or discovery objective.

## Completion Checklist

- Each claim is tagged observed, asserted, hypothesis or unknown, with a source for observed ones; sequence rows are unsent drafts and exist only with supplied consent, suppression and channel eligibility.
- The disposition is ADVANCE, HOLD or DISQUALIFY with its deciding evidence; a next step is confirmed only from an observed buyer response; CRM changes stay proposals.

## Recovery Notes

- If consent or suppression status is unknown, retain sales_opportunity_evidence_record/v1 and sales_qualification_state/v1, mark sequence eligibility unresolved with HOLD, and hand back the missing eligibility questions without drafting outreach.
- If no observed buyer response supports a commitment, retain the eligible sales_draft_sequence/v1, mark confirmation not_observed, and hand back sales_handoff_disposition/v1 with proposed actions, owners, timing, and exit criteria.

## Workflow Lane

- Current lane: **Research and company ops** - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when a seller or business-development owner needs account context, buyer hypotheses, qualification questions, value narrative, partner/outreach plan, and a non-executing next-step sequence.

    Strong routing signals: `sales discovery`, `account plan`, `outbound messaging`, `영업 발굴`, `고객사 계획`, `아웃바운드 메시지`

## Catalog Metadata

Category: `strategy`
Phase: `sales-development`
Hermes role: `operator`
Quality tier: `decision-gated`
Reasoning demand: `standard`

Quality bar:

- Separate account evidence, buyer hypotheses, qualification questions, and next-step ownership.
- Keep outreach drafts and CRM actions explicitly non-executing.

Handoff policy:

Keep domain framing, clarification, source/evidence synthesis, draft outputs, and next-work routing in Hermes. A prepared brief, review, reply, or plan is not an external action, approval, filing, send, publish, data mutation, implementation, review, CI, or merge claim. Prepare a connector, file, coding, or human-review handoff only when the user explicitly accepts that next step; report it only from observed evidence. Hermes prepares research, discovery, and message guidance; it does not research unobserved facts as facts, contact prospects, create opportunities, change CRM data, book meetings, or claim revenue or progress.

Required inputs:

- account or segment
- available evidence
- buyer hypothesis
- sales objective

Expert clarification questions:
- `account or segment`
  - English: Which fit criteria and disqualifiers, offer or use case, stage and owner, geography, and evidenced stakeholders and roles define the account or segment?
  - Korean: 어떤 적합 기준과 제외 기준, 제안 또는 사용 사례, 단계와 책임자, 지역, 근거가 있는 이해관계자와 역할이 계정 또는 세그먼트를 정의하나요?

Expected outputs:

- sales_opportunity_evidence_record/v1
- sales_qualification_state/v1
- sales_draft_sequence/v1
- sales_handoff_disposition/v1

Artifact expectations:

- prepared sales development brief when a wrapper captures it

Safety rules:

- Treat unsupported company and competitor information as evidence gaps, not facts.
- Do not claim prospect contact, CRM mutation, meeting booking, opportunity creation, revenue, or progress.

Procedure: load `references/procedure.md`.

## Runtime Evidence

Preferred harness for this skill: `ops-review`.

```sh
omh runtime record --skill sales-development --harness ops-review --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
