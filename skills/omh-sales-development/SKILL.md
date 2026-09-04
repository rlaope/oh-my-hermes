---
name: "omh-sales-development"
description: "[omh] Turn an account or market opportunity into a focused discovery, qualification, and next-step brief. Use when the user says: sales discovery, account plan, outbound messaging, 영업 발굴, 고객사 계획, 아웃바운드 메시지."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, strategy]
    category: strategy
    phase: sales-development
    role: operator
    quality_tier: decision-gated
---

# Sales Development

This is a Hermes-native `sales-development` workflow skill.

## Why This Exists

`sales-development` prepares evidence-bounded discovery and qualification guidance without claiming sales execution.

## Do Not Use When

- The user needs a company-level positioning, market-entry, or strategic-options decision rather than account-level discovery; use `strategy-brief`.
- The user only wants a polished social post, newsletter, or one-off outbound-copy rewrite; use `content-operator`.
- The user asks to send outreach, update Salesforce or HubSpot, create an opportunity, or book a meeting; use `connector-operator` with explicit recipient, object, and authority.
- The request asks for current competitor or company evidence but supplies no source material; begin with `research` before presenting claims as observed.

## Examples

Good example:

- Prompt: Build a discovery plan and qualification questions for a mid-market prospect considering our support platform.
- Expected behavior: Prepare account evidence gaps, discovery and qualification questions, value hypotheses, and an owned next-step plan.
- Why: The request is account-level sales discovery, not outreach execution or company strategy.

Bad example:

- Prompt: Write a LinkedIn launch post for our new feature.
- Expected behavior: Route to `content-operator`, not `sales-development`.
- Why: A one-off social post has no account qualification or discovery objective.

## Completion Checklist

- The decision, options, tradeoffs, assumptions, and rejected alternatives are named.
- Observed signals are separated from strategic inference.
- Accepted decisions and implementation follow-ups are not conflated.

## Recovery Notes

- If evidence is mostly assumption, label it and recommend a research or feedback-triage pass.
- If the decision owner is missing, keep the output as options rather than accepted strategy.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `best-practice-research`, `autoresearch-goal`, `model-optimization`, `inference-serving`, `+17 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

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

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
