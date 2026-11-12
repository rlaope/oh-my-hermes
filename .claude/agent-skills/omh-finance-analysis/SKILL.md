---
name: "omh-finance-analysis"
description: "[omh] Company budget overrun, cash risk, or close issue: turn finance and accounting inputs into a decision-ready variance, cash, and close-risk brief."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: finance-analysis
    role: operator
    quality_tier: evidence-gated
---

# Finance Analysis

This is an OMH `finance-analysis` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`finance-analysis` prepares a source-bounded decision brief without claiming an authoritative financial action.

## Do Not Use When

- The request is for a current quote, exchange rate, crypto price, or other live market lookup; use `omh-live-info`.
- The user wants generic exploration of a supplied CSV or table without accounting periods, controls, or finance decision framing; use `omh-data-analysis`.
- The user asks to post journal entries, reconcile accounts, approve payments, submit tax filings, or configure an accounting system; use `omh-apps` for an explicit observed action path.
- The user wants pipeline coverage, deal health, or a seller forecast scenario rather than authoritative revenue or close reporting; use `omh-sales-pipeline-review`.
- The user needs an enterprise or product direction decision after analysis; route that decision to `omh-decide`.
- The ask is testing whether an internal control operated -- a SOX or ICFR sample, re-performance, or a deficiency's severity; use `omh-internal-audit`.
- The ask is a valuation, DCF, multiples or a stock comparison from published statements; this procedure does not cover it. A host valuation skill does, when installed (Hermes ships optional finance skills); otherwise compute ratios with code from the supplied statements, state the formulas, give no recommendation, and stop at facts.

## Examples

Good example:

- Prompt: Compare Q2 actuals against budget, explain the biggest expense variances, and flag cash risks for the CFO.
- Expected behavior: Prepare the period boundary, actual-versus-plan narrative, cash-risk register, and decision questions.
- Why: The supplied finance framing needs a bounded decision brief rather than an external accounting action.

Bad example:

- Prompt: What is the USD/KRW exchange rate right now?
- Expected behavior: Route to `omh-live-info`, not `finance-analysis`.
- Why: A live exchange rate needs observed provider data rather than a finance analysis brief.

## Completion Checklist

- finance_scope_source_record/v1 names entity, period, cutoff, currency and units, accounting basis and comparator version.
- Totals tie to the source, or the unreconciled gap is listed; the brief is not called reconciled otherwise.
- Every formula and policy is supplied or marked an unapproved assumption.
- Recalculation ran with a tool and its result is quoted; the disposition is PASS or HOLD with an escalation owner.

## Recovery Notes

- If period, currency, basis, or comparator version conflicts, retain the supplied source provenance, mark comparability unresolved, and hand back finance_scope_source_record/v1 with the conflicting attributes.
- If totals or account mappings do not tie out, retain the confirmed scope and source record, mark reconciliation unresolved, and hand back finance_reconciliation_analysis_schedule/v1 with unreconciled gaps.
- If recalculation fails at brief validation, retain supported calculations and finance_risk_register/v1, mark finance_decision_brief/v1 unresolved with HOLD, and hand back the failed calculation and escalation owner.



## When to Use

Use when supplied ledger, budget, forecast, revenue, expense, cash-flow, or close context needs a bounded analysis and decision brief.

    Strong routing signals: `finance analysis`, `budget variance`, `budget vs actual`, `month-end close`, `재무 분석`, `예산 대비 실적`, `월마감`

## Catalog Metadata

Category: `operations`
Phase: `finance-analysis`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- Separate supplied numbers, assumptions, and missing finance evidence.
- Keep decision and escalation questions explicit.

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
