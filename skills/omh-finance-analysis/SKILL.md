---
name: "omh-finance-analysis"
description: "[omh] Turn finance and accounting inputs into a decision-ready variance, cash, and close-risk brief. Use when the user says: finance analysis, budget variance, budget vs actual, month-end close, 재무 분석, 예산 대비 실적, 월마감."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: finance-analysis
    role: operator
    quality_tier: evidence-gated
---

# Finance Analysis

This is a Hermes-native `finance-analysis` workflow skill.

## Why This Exists

`finance-analysis` prepares a source-bounded decision brief without claiming an authoritative financial action.

## Do Not Use When

- The request is for a current quote, exchange rate, crypto price, or other live market lookup; use `live-info-operator`.
- The user wants generic exploration of a supplied CSV or table without accounting periods, controls, or finance decision framing; use `data-analysis`.
- The user asks to post journal entries, reconcile accounts, approve payments, submit tax filings, or configure an accounting system; use `connector-operator` for an explicit observed action path.
- The user needs an enterprise or product direction decision after analysis; route that decision to `strategy-brief`.

## Examples

Good example:

- Prompt: Compare Q2 actuals against budget, explain the biggest expense variances, and flag cash risks for the CFO.
- Expected behavior: Prepare the period boundary, actual-versus-plan narrative, cash-risk register, and decision questions.
- Why: The supplied finance framing needs a bounded decision brief rather than an external accounting action.

Bad example:

- Prompt: What is the USD/KRW exchange rate right now?
- Expected behavior: Route to `live-info-operator`, not `finance-analysis`.
- Why: A live exchange rate needs observed provider data rather than a finance analysis brief.

## Completion Checklist

- Confirm the workflow target, evidence boundary, and stop condition are named.
- Report which outputs are prepared, observed, blocked, or missing.
- Name the smallest next verification or handoff instead of claiming completion from narration.

## Recovery Notes

- If required context is missing, ask one blocking question or route back to the narrower workflow.
- If runtime or wrapper evidence is unavailable, keep the status as not_observed and expose the next observable action.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `best-practice-research`, `autoresearch-goal`, `model-optimization`, `inference-serving`, `+17 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when supplied ledger, budget, forecast, revenue, expense, cash-flow, or close context needs a bounded analysis and decision brief.

    Strong routing signals: `finance analysis`, `budget variance`, `budget vs actual`, `month-end close`, `재무 분석`, `예산 대비 실적`, `월마감`

## Catalog Metadata

Category: `operations`
Phase: `finance-analysis`
Hermes role: `operator`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- Separate supplied numbers, assumptions, and missing finance evidence.
- Keep decision and escalation questions explicit.

Handoff policy:

Keep domain framing, clarification, source/evidence synthesis, draft outputs, and next-work routing in Hermes. A prepared brief, review, reply, or plan is not an external action, approval, filing, send, publish, data mutation, implementation, review, CI, or merge claim. Prepare a connector, file, coding, or human-review handoff only when the user explicitly accepts that next step; report it only from observed evidence. Calculations are only as authoritative as supplied or observed sources and methods; no ERP, bank, ledger, tax, payment, or filing action is implied.

Required inputs:

- period
- supplied finance source
- decision question
- calculation assumptions

Expert clarification questions:
- `period`
  - English: What period, cutoff, reporting entity/perimeter, currency/units, accounting basis, comparator version, and close status apply?
  - Korean: 어떤 기간, 마감 기준일, 보고 법인과 범위, 통화와 단위, 회계 기준, 비교 버전, 마감 상태를 적용해야 하나요?

Expected outputs:

- finance_scope_source_record/v1
- finance_reconciliation_analysis_schedule/v1
- finance_risk_register/v1
- finance_decision_brief/v1

Artifact expectations:

- prepared finance analysis brief when a wrapper captures it

Safety rules:

- State source and calculation assumptions before presenting a variance.
- Do not imply an ERP, bank, ledger, tax, payment, or filing action occurred.

Procedure: load `references/procedure.md`.

## Runtime Evidence

Preferred harness for this skill: `ops-review`.

```sh
omh runtime record --skill finance-analysis --harness ops-review --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
