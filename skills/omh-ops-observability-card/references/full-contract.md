# Ops Observability Card

Load this on-demand contract after the compact `ops-observability-card` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

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

## Full Input, Output, and Artifact Expectations

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
