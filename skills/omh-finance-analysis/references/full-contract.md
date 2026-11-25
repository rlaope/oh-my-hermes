# Finance Analysis

Load this on-demand contract after the compact `finance-analysis` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

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

## Full Input, Output, and Artifact Expectations

Required inputs:

- period
- supplied finance source
- decision question
- calculation assumptions

Expected outputs:

- finance_scope_source_record/v1
- finance_reconciliation_analysis_schedule/v1
- finance_risk_register/v1
- finance_decision_brief/v1

Artifact expectations:

- prepared finance analysis brief when a wrapper captures it

Detailed procedure steps: `references/procedure.md`.
