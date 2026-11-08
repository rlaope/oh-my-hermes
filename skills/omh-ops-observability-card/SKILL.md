---
name: "omh-ops-observability-card"
description: "[omh] Tracking cost, tokens, latency, or service health: prepare an operations command-board for wrapper-safe token, cost, latency, run history, queue, failure-mode, external metric-provider, and service-quality evidence boundaries. Use when the user says: ops-observability-card, observability card, operations command board, ops command board, service quality board, service quality, external metric provider, metric provider."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, observability]
    category: observability
    phase: telemetry-card
    role: tracker
    quality_tier: workflow-surface-gated
    related_skills: [omh-run-efficiency]
---

# Ops Observability Card

This is a Hermes-native `ops-observability-card` workflow skill.

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

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when automation, loops, gateway work, executor handoffs, or service operations need a safe command-board for cost, latency, token, history, failure-mode, supplied metric-provider, and service-quality visibility.

    Strong routing signals: `ops-observability-card`, `observability card`, `operations command board`, `ops command board`, `service quality board`, `service quality`, `external metric provider`, `metric provider`, `prometheus metrics`, `grafana metrics`, `cost telemetry`, `latency telemetry`, `token telemetry`, `run history`, `loop telemetry`, `failure mode`, `monitor tokens`, `service health`, `slo dashboard`, `지연시간`, `관측성`, `운영 지휘판`, `서비스 품질`, `메트릭`, `프로메테우스`, `그라파나`

## Catalog Metadata

Category: `observability`
Phase: `telemetry-card`
Hermes role: `tracker`
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

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

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

Preferred harness for this skill: `ops-observability-card`.

```sh
omh runtime record --skill ops-observability-card --harness ops-observability-card --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
