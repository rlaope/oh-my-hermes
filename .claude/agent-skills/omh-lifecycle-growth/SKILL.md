---
name: "omh-lifecycle-growth"
description: "[omh] Churn or weak activation among users: turn an observed onboarding, activation, retention, re-engagement, referral, or monetization problem into one consent-safe in-app journey or growth experiment plan with a bounded readout and an explicit decision. Use when the user says: lifecycle-growth, lifecycle growth, lifecycle marketing, lifecycle messaging, in-app journey, in-app message campaign, onboarding journey, onboarding nudge."
disable-model-invocation: true
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, strategy]
    category: strategy
    phase: lifecycle-growth
    role: operator
    quality_tier: decision-gated
---

# Lifecycle Growth

This is an OMH `lifecycle-growth` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`lifecycle-growth` exists so audience eligibility, consent and frequency safety, sticky exposure, causal measurement, and the stop decision travel together in one plan instead of being assembled ad hoc from analysis, copy, scheduling, and connector work.

## Do Not Use When

- The user only wants a one-off message, email, banner, or push copy rewrite with no audience, experiment, or decision; use `omh-content-operator`.
- The user wants generic exploration or calculation over a supplied cohort, retention, conversion, or segment table with no journey or experiment to design; use `omh-data-analysis`.
- The user wants a recurring schedule, cron, or digest cadence for an already-decided operation rather than a lifecycle intervention.
- The user asks to send a message, change a feature flag, create a segment, or start an experiment in a provider now; use `omh-apps` with explicit authorization and observed results.
- The user needs a PRD, prioritization frame, or roadmap for a product change rather than a journey or experiment; use `omh-product-brief`.

## Examples

Good example:

- Prompt: Our day-7 retention dropped for new workspace admins; design an in-app onboarding journey and a holdout experiment so we know whether it works.
- Expected behavior: Prepare the brief, audience trigger policy, safety policy, experiment plan with sticky assignment and actual exposure, a readout scaffold, and an approval-gated handoff disposition.
- Why: The request spans lifecycle stage, audience, treatment, and causal measurement, which is the whole lifecycle-growth loop rather than one sibling's slice.

Bad example:

- Prompt: Send the re-engagement push to every inactive user tonight.
- Expected behavior: Route to `omh-apps` with explicit authorization, or return HOLD if consent, suppression, and frequency eligibility are unknown.
- Why: An immediate external send is a connector action, and lifecycle-growth never sends or claims delivery.

## Completion Checklist

- The target behavior, baseline, eligible audience, safety policy, experiment design, readout, and decision owner are named or marked HOLD.
- Prepared plan, human approval, observed delivery or display, observed user action, observed outcome, and causal claim are reported as separate states.
- The readout disposition is exactly `ship`, `rollback`, `review`, or `insufficient_data`, and every proposed handoff names its owning workflow, approver, and stop conditions.

## Recovery Notes

- If consent, suppression, identity, event semantics, denominator, or the decision owner is unknown, return HOLD with the missing fields and ask for the one input that unblocks the smallest next step.
- If provider or data evidence for delivery, display, action, or outcome is unavailable, keep every readout stage not_observed and set the disposition to `insufficient_data` or `review` rather than `ship`.
- If a readout is missing, ask for the analysis run state and its observation time before concluding anything: a queued or long-running analysis holds for reconciliation, while failed, canceled, and never-started runs each need a different next step.



## When to Use

Use when a product or growth owner wants to improve a lifecycle stage and needs the target behavior, eligible audience, safety policy, experiment design, launch/rollback gates, measurement readout, and ship/rollback/review/insufficient_data decision assembled as one evidence-bounded plan.

    Strong routing signals: `lifecycle-growth`, `lifecycle growth`, `lifecycle marketing`, `lifecycle messaging`, `in-app journey`, `in-app message campaign`, `onboarding journey`, `onboarding nudge`, `activation campaign`, `activation experiment`, `retention campaign`, `retention experiment`, `re-engagement campaign`, `win-back campaign`, `referral experiment`, `monetization experiment`, `growth experiment`, `holdout experiment`, `product-led growth loop`, `라이프사이클 마케팅`, `온보딩 여정`, `그로스 실험`

## Catalog Metadata

Category: `strategy`
Phase: `lifecycle-growth`
Quality tier: `decision-gated`
Reasoning demand: `standard`

Quality bar:

- Define the value-bearing behavior and its baseline before any campaign or treatment is proposed.
- Separate assignment from actual exposure, and eligible, attempted, delivered, displayed, acted, and outcome stages from one another.
- Keep copy, supplied-data calculation, recurring scheduling, external sends, and PRD work with their owning workflows.
- Require a named human approval before any launch handoff and observed evidence before any delivery or outcome claim.

Required inputs:

- lifecycle objective and stage
- target segment
- event schema and baseline
- channels or product surfaces
- consent and policy constraints
- experiment budget
- decision owner

Expert clarification questions:
- `lifecycle objective and stage`
  - English: Which lifecycle stage (onboarding, activation, retention, re-engagement, referral, monetization) and which value-bearing user behavior should improve, from what baseline?
  - Korean: 어떤 라이프사이클 단계(온보딩, 활성화, 리텐션, 재참여, 추천, 수익화)에서 어떤 가치 있는 사용자 행동을 어느 기준선에서 개선해야 하나요?

Expected outputs:

- lifecycle_growth_brief/v1
- audience_trigger_policy/v1
- lifecycle_safety_policy/v1
- growth_experiment_plan/v1
- growth_measurement_readout/v1
- growth_handoff_disposition/v1

Artifact expectations:

- prepared lifecycle-growth plan and readout, as metadata-only records with safe references, when a wrapper captures them

Safety rules:

- Fail closed: unknown consent, suppression, frequency eligibility, event semantics, identity, denominator, or decision owner returns HOLD and blocks a launch-ready handoff.
- Consent and suppression come only from supplied records; product usage or the absence of an opt-out never implies either.
- Do not claim a message was sent, a flag was changed, a treatment was displayed, a user acted, an outcome moved, or an experiment succeeded without observed provider, runtime, or data evidence.
- Delivery and click counts are not product or revenue impact; a causal claim needs a valid observed experiment or another named identification method.
- Retain bounded metadata and safe references only; never store user identity, event payloads, message bodies, consent records, or transcripts in durable artifacts.
- Treat small samples, novelty effects, seasonality, concurrent interventions, and inconsistent event semantics as blockers or stated uncertainty, not as results.
- A throttle window is identified by its configured key or expression plus the resolved value, scoped to a recipient or tenant; a resolved value is never re-read as a second key, a missing static value stays ungrouped, and an empty dynamic value falls back to the default window.
- Per-step matched and skipped outcomes carry a reason and status but never evaluated values or secrets; a step trace is best-effort diagnostics, not delivery evidence, and its absence must not block or fail a send.
- Production or published workflow content is view-only in prepared guidance; mutations go to a development or draft copy, then an explicit promotion decision, and only an observed provider result proves the promotion happened.
- A missing analysis result is not proof that no analysis is running; name the run state and the time it was observed, and never report a queued or running analysis as failed, canceled, absent, or complete.
- Elapsed time is a delay warning measured against a supplied service expectation, never evidence about a run; no fixed staleness cutoff may overwrite an observed in-flight state, and analysis-job runtime, experiment minimum runtime, and source-data freshness stay three separate questions.
- While the latest observed run is queued or running, do not start or recommend another analysis; reconcile the existing work first, and select the newest in-flight run rather than the newest run of any kind.
- A cancellation or status-reconciliation handoff is prepared, never performed: it names the exact run and scope, stays `prepared_not_observed`, and only an observed provider result may record acceptance or a terminal cancellation.

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
