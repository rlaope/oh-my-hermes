---
name: "omh-sales-development"
description: "[omh] Prospect or account worth pursuing: turn an account or market opportunity into a focused discovery, qualification, and next-step brief. Use when the user says: sales discovery, account plan, outbound messaging, 영업 발굴, 고객사 계획, 아웃바운드 메시지."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, strategy]
    category: strategy
    phase: sales-development
    role: operator
    quality_tier: decision-gated
---

# Sales Development

This is an OMH `sales-development` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

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

- The decision, options, tradeoffs, assumptions, and rejected alternatives are named.
- Observed signals are separated from strategic inference.
- Accepted decisions and implementation follow-ups are not conflated.

## Recovery Notes

- If consent or suppression status is unknown, retain sales_opportunity_evidence_record/v1 and sales_qualification_state/v1, mark sequence eligibility unresolved with HOLD, and hand back the missing eligibility questions without drafting outreach.
- If no observed buyer response supports a commitment, retain the eligible sales_draft_sequence/v1, mark confirmation not_observed, and hand back sales_handoff_disposition/v1 with proposed actions, owners, timing, and exit criteria.



## When to Use

Use when a seller or business-development owner needs account context, buyer hypotheses, qualification questions, value narrative, partner/outreach plan, and a non-executing next-step sequence.

    Strong routing signals: `sales discovery`, `account plan`, `outbound messaging`, `영업 발굴`, `고객사 계획`, `아웃바운드 메시지`

## Catalog Metadata

Category: `strategy`
Phase: `sales-development`
Quality tier: `decision-gated`
Reasoning demand: `standard`

Quality bar:

- Separate account evidence, buyer hypotheses, qualification questions, and next-step ownership.
- Keep outreach drafts and CRM actions explicitly non-executing.

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
