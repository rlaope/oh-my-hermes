# Run Efficiency

Load this on-demand contract after the compact `run-efficiency` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user asks only what this Hermes conversation has used or cost so far; Hermes' /usage shows this session's tokens and context, /insights estimates cost across recent sessions, and the omh_run_summary tool relays this conversation's recorded tokens and cost.
- The user wants service latency, uptime, error rates, or supplied metric-provider figures; use `omh-ops-observability-card`.
- The user wants a provider invoice or quota truth; no OMH report observes either, so name the provider's own console as the source.

## Examples

Good example:

- Prompt: Show the local run efficiency report from this run's supplied context budget and timings.
- Expected behavior: Produce `show_run_efficiency_report` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: Claim this report proves provider billing, host load, or cron execution without observations.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- run_efficiency_report/v1
- context utilization
- host_usage: Hermes' recorded usage for a named session, or not_observed
- not_observed provider and billing gaps

Artifact expectations:

- run_efficiency_report/v1 metadata-only report, built with `omh runtime efficiency-report --input <run_efficiency_input/v1 file> [--hermes-session <id>] [--write]`; the input is JSON with exactly `schema_version` (`run_efficiency_input/v1`), `run_id`, `context_budget` (`schema_version` `omh_run_context_budget/v1`, `run_id`, `budget_bytes`, `emitted_bytes`, `remaining_bytes` equal to the difference, and `surfaces` mapping a surface name to a count) and `observations` (at most 20 entries of `metric`, one of `wall_clock_duration_ms`, `tool_duration_ms`, `context_bytes`, an integer `value` and a `source_ref`); with no input file you ask for the timings and never write estimates into it
- supplied `session_activity_receipt/v1` when available; unavailable metrics stay unavailable, never zero
- `host_usage` from the Hermes-accounted part of the cost receipt `omh_run_summary` returns (the session, its delegated children, and its kanban workers; `--hermes-session`, and a local Hermes terminal holds the id in `$HERMES_SESSION_ID`): observed only when Hermes recorded tokens for it; no session row or no tokens stays not_observed, never zero
