---
name: "omh-finance-analysis"
description: "[omh] Company budget overrun, cash risk, or close issue: turn finance and accounting inputs into a decision-ready variance, cash, and close-risk brief. Use when the user says: finance analysis, budget variance, budget vs actual, month-end close, 재무 분석, 예산 대비 실적, 월마감."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: finance-analysis
    role: operator
    quality_tier: evidence-gated
    related_skills: [omh-live-info, omh-data-analysis, omh-apps, omh-sales-pipeline-review, omh-decide, omh-internal-audit]
---

# Finance Analysis

Required: period, supplied finance source, decision question, calculation assumptions. Output: finance_scope_source_record/v1, finance_reconciliation_analysis_schedule/v1, finance_risk_register/v1, finance_decision_brief/v1.

## Why This Exists

`finance-analysis` prepares a source-bounded decision brief without claiming an authoritative financial action.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details). Procedure: `references/procedure.md`.

## Workflow Lane

- Current lane: **Research and company ops** - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

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

Expert clarification questions:
- `period`
  - English: What period, cutoff, reporting entity/perimeter, currency/units, accounting basis, comparator version, and close status apply?
  - Korean: 어떤 기간, 마감 기준일, 보고 법인과 범위, 통화와 단위, 회계 기준, 비교 버전, 마감 상태를 적용해야 하나요?

Safety rules:

- State source and calculation assumptions before presenting a variance.
- Do not imply an ERP, bank, ledger, tax, payment, or filing action occurred.

Procedure: load `references/procedure.md`.

## Completion Checklist

- finance_scope_source_record/v1 names entity, period, cutoff, currency and units, accounting basis and comparator version.
- Totals tie to the source, or the unreconciled gap is listed; the brief is not called reconciled otherwise.
- Every formula and policy is supplied or marked an unapproved assumption.
- Recalculation ran with a tool and its result is quoted; the disposition is PASS or HOLD with an escalation owner.

## Recovery Notes

- If period, currency, basis, or comparator version conflicts, retain the supplied source provenance, mark comparability unresolved, and hand back finance_scope_source_record/v1 with the conflicting attributes.
- If totals or account mappings do not tie out, retain the confirmed scope and source record, mark reconciliation unresolved, and hand back finance_reconciliation_analysis_schedule/v1 with unreconciled gaps.
- If recalculation fails at brief validation, retain supported calculations and finance_risk_register/v1, mark finance_decision_brief/v1 unresolved with HOLD, and hand back the failed calculation and escalation owner.

## Runtime Evidence

Preferred harness for this skill: `ops-review`.

```sh
omh runtime record --skill finance-analysis --harness ops-review --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
