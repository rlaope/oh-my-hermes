# Sales Pipeline Review

Load this on-demand contract after the compact `sales-pipeline-review` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

## Why This Exists

`sales-pipeline-review` prepares evidence-bounded portfolio pipeline, forecast, and follow-up reviews from supplied CRM snapshots without replacing a CRM, mutating records, or claiming revenue.

## Do Not Use When

- The request is single-account discovery, qualification, buyer hypotheses, outreach drafting, or one opportunity's next step; use `omh-sales-development`.
- The user wants a weekly status, release-risk, or operating review with no sales stages, forecast categories, or deal records; use `omh-ops-review`.
- The user needs authoritative revenue, bookings, budget-variance, or close reporting rather than a pipeline scenario; use `omh-finance-analysis`.
- The user wants generic exploration or calculation on a supplied table with no stage, forecast, or deal-health semantics; use `omh-data-analysis`.
- The supplied material is qualitative customer feedback, call notes, or survey text rather than opportunity records; use `omh-feedback-triage`.
- The user asks to update Salesforce or HubSpot, store or sync CRM data, send alerts or outreach, or change an opportunity; use `omh-apps` with explicit object, field, and authority.

## Examples

Good example:

- Prompt: Here is this week's pipeline export as of Monday 09:00; review deal health, slipped close dates, and whether the commit forecast holds up against last quarter's calls.
- Expected behavior: Validate as-of time, currency, amount and stage semantics first, then prepare health, forecast-state, and calibration findings with owned follow-ups and proposed CRM corrections.
- Why: The request is portfolio-level pipeline and forecast review over a supplied snapshot with a stated as-of time.

Bad example:

- Prompt: Write discovery questions for the Northwind opportunity and draft the follow-up email.
- Expected behavior: Route to `omh-sales-development`, not `sales-pipeline-review`.
- Why: A single account's discovery, qualification, and outreach draft has no portfolio, aging, or forecast-calibration objective.

## Completion Checklist

- The scope disposition is recorded before any figure: `HOLD` names the blocking gap, otherwise freshness, currency basis, amount and stage semantics, duplicates, and owners are confirmed from supplied data.
- Health, forecast, and annex outputs cite supplied record references, keep stage, seller forecast, scenario, and observed commitment separate, and mark calibration or an annex `unavailable` or `unsupported` instead of filling it.
- The handoff lists owner, due date, exit criterion, and evidence per follow-up, keeps every CRM correction proposed with an approval state, and reports mutation, storage, sync, alerts, and outreach as `not_observed` unless a connector result was observed.

## Recovery Notes

- If the snapshot fails scope validation, return `HOLD` naming the exact missing definition, conversion basis, owner, or duplicate set and ask for it; do not rank or total partial data.
- If prior forecasts or outcomes are absent, keep calibration `unavailable`; if an annex has no supporting evidence, emit it as `unsupported` with the gap named rather than omitting it.
- If a connector is unavailable, keep every CRM correction proposed and every alert or message unsent, and name the connector boundary as the next observable step.

## When to Use

Use when a sales leader or business owner supplies a bounded CRM export or pipeline snapshot and needs recurring portfolio review: evidence scope and freshness, stage and forecast definitions, movement and aging, stale or slipped deals, exit-criteria gaps, next-step quality, concentration, forecast scenarios and prior-forecast calibration, optional won/lost or renewal-risk learning, and an owned follow-up handoff.

Routing signals: `sales-pipeline-review`, `sales pipeline review`, `pipeline review`, `pipeline health`, `pipeline coverage`, `deal review`, `deal health`, `sales forecast review`, `forecast call`, `forecast calibration`, `seller forecast`, `stale deals`, `slipped deals`, `renewal risk review`, `win loss review`, `파이프라인 리뷰`, `영업 예측 보정`, `딜 리뷰`

## Workflow Contract

Category: `operations`
Phase: `sales-pipeline-review`
Hermes role: `operator`
Quality tier: `decision-gated`
Reasoning demand: `standard`

Quality bar:

- Separate stage, seller forecast, model-derived scenario, and observed buyer commitment in every forecast statement.
- Cite the supplied record reference behind every exception, slip, stall, concentration, and proposed correction.
- Emit calibration only from matched prior snapshots and observed outcomes; otherwise state that it is unavailable.

Handoff policy:

Keep domain framing, clarification, source/evidence synthesis, draft outputs, and next-work routing in Hermes. A prepared brief, review, reply, or plan is not an external action, approval, filing, send, publish, data mutation, implementation, review, CI, or merge claim. Prepare a connector, file, coding, or human-review handoff only when the user explicitly accepts that next step; report it only from observed evidence. Hermes reviews supplied records; it does not replace a CRM, store or sync CRM data, mutate opportunities, create dashboards or alerts, send outreach, book revenue, or claim seller or buyer commitments that were not observed.

Required inputs:

- pipeline snapshot
- as-of time and review horizon
- currency, amount, stage, and forecast definitions
- prior forecast and actuals
- decision owner

Expected outputs:

- sales_pipeline_scope/v1
- sales_pipeline_health/v1
- sales_forecast_assessment/v1
- sales_outcome_learning_annex/v1
- sales_renewal_risk_annex/v1
- sales_pipeline_handoff/v1

Artifact expectations:

- prepared sales pipeline review brief when a wrapper captures it
- durable artifacts hold bounded aggregates, opaque source references, and only the account identifiers an approved handoff needs; raw export rows and message content are not persisted by default

Safety rules:

- Treat a missing or stale as-of time, undefined stage or forecast semantics, mixed currencies without an observed conversion basis, unknown amount meaning, duplicate opportunities, or missing owners as `HOLD`, never as an input to a calculation.
- Do not claim CRM storage, sync, mutation, dashboards, alerts, outreach, booked revenue, or seller or buyer commitments; a proposed correction is not a change and a scenario is not a promise.
- Consume the organization's supplied stage, category, probability, amount, and close-date definitions; never impose a vendor schema or a default probability table.
- Persist bounded aggregates and opaque source references only; raw CRM exports and message content stay out of durable artifacts unless the user explicitly approves a scoped exception.

Detailed procedure steps: `references/procedure.md`.
