---
name: "omh-ops-observability-card"
description: "[omh] Tracking cost, tokens, latency, or service health: prepare an operations command-board for wrapper-safe token, cost, latency, run history, queue, failure-mode, external metric-provider, and service-quality evidence boundaries. Use when the user says: ops-observability-card, observability card, operations command board, ops command board, service quality board, service quality, external metric provider, metric provider."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, observability]
    category: observability
    phase: telemetry-card
    role: tracker
    quality_tier: workflow-surface-gated
---

# Ops Observability Card

This is an OMH `ops-observability-card` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`ops-observability-card` exists so service, loop, and automation operations get one board where each cost, latency, token, failure-mode, and metric-provider figure is marked observed or prepared, instead of an improvised dashboard.

## Do Not Use When

- The user asks what their own Hermes conversation has used or cost; Hermes' /usage shows this session's tokens and context, /insights estimates cost across recent sessions, and the omh_run_summary tool relays this conversation's recorded tokens and cost.
- The user wants one run's timing and context-budget report; use `omh-run-efficiency`.
- The user asks OMH to sign in to a metric provider, billing console, or dashboard and pull live figures; the card reads only supplied payloads and Hermes' own records.

## Examples

Good example:

- Prompt: ops-observability-card show token, cost, latency, supplied Prometheus/Grafana metrics, and missing service-quality evidence for this loop.
- Expected behavior: Produce `prepare_ops_observability_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: ops-observability-card claim exact provider billing, healthy SLO, incident closure, or remediation completion from local estimates.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- The run or workflow scope, metric window, failure modes, and cost/latency boundary are named.
- Local telemetry, provider truth, billing truth, and completion evidence are separate states.
- Warnings name the next measurement or operator review action.

## Recovery Notes

- If the metric window is missing, keep supplied payloads, mark quality unresolved; hand back the next measure.
- If a budget threshold is missing, keep the observed cost, mark advice tentative; hand back the gaps.



## When to Use

Use when automation, loops, gateway work, executor handoffs, or service operations need a safe command-board for cost, latency, token, history, failure-mode, supplied metric-provider, and service-quality visibility.

    Strong routing signals: `ops-observability-card`, `observability card`, `operations command board`, `ops command board`, `service quality board`, `service quality`, `external metric provider`, `metric provider`, `prometheus metrics`, `grafana metrics`, `cost telemetry`, `latency telemetry`, `token telemetry`, `run history`, `loop telemetry`, `failure mode`, `monitor tokens`, `service health`, `slo dashboard`, `지연시간`, `관측성`, `운영 지휘판`, `서비스 품질`, `메트릭`, `프로메테우스`, `그라파나`

## Catalog Metadata

Category: `observability`
Phase: `telemetry-card`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.
- When advising what to record per model call, require the five answers - which model, how long, how many tokens in and out, whether it succeeded, and why it failed - with streaming calls adding time-to-first-token; the attribute tiers live in `omh-agent-ops-review/references/instrumentation-ladder.md`.
- Aggregate cost at the four levels - per call, per agent run, per session, per user - and name the budget threshold each level checks against before recommending any optimization signal.
- Never recommend logging raw prompts, responses, or secret values into telemetry; counts, lengths, hashes, and key-set booleans carry the signal without the leak.
- On Hermes, a conversation's token and cost figures come from the cost receipt `omh_run_summary` returns, which keeps Hermes' own accounting apart from executor-reported fanout units and names each cost's basis, and the person's `/insights` gives Hermes' estimated cost across recent sessions. A conversation with no recorded tokens is not_observed, never zero, and provider billing stays not_observed.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- ops-observability-card/v1 card or guidance
- external_metric_provider/v1 payload contract
- external_metric_provider_adapter/v1 adapter contract
- ops_service_quality_board/v1 service-quality board
- typed service-quality downgrade gaps
- next action
- prepared-vs-observed boundary

Artifact expectations:

- ops-observability-card/v1 metadata-only runtime or wrapper card when recorded
- external_metric_provider/v1 supplied metric payload when available
- external_metric_provider_adapter/v1 connector-ready adapter metadata when available
- ops_service_quality_board/v1 evidence-gated service-quality board

Artifact contracts:

This label denotes the machine-enforcement level, not a skill quality score and not an observed evidence state.

- contract_id: `ops_service_quality_board/v1`; enforcement_level: `executable_validated`; consumer_id: `validate_ops_service_quality_board`

Safety rules:

- An ops observability card is not billing truth, provider quota truth, live metric-provider access, complete tracing, SLO pass, incident closure, root-cause proof, remediation completion, performance proof, or successful workflow completion evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

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
