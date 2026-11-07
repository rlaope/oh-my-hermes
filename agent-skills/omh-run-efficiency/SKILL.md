---
name: "omh-run-efficiency"
description: "[omh] Run efficiency and context usage report: report supplied local run efficiency while provider data stays unobserved. Use when the user says: run-efficiency, run efficiency report, local run efficiency, context utilization, tool duration report, 실행 효율 리포트, 컨텍스트 사용량, 도구 지연 시간."
license: MIT
compatibility: "Requires the omh CLI on PATH (pip install oh-my-hermes)."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, observability]
    category: observability
    phase: run-efficiency
    role: tracker
    quality_tier: workflow-surface-gated
---

# Run Efficiency

This is an OMH `run-efficiency` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`run-efficiency` exists so a question about how a run spent its time, tools, and context gets the supplied timings and context budget, plus what Hermes itself recorded for a named session's tokens and cost, instead of figures a model guesses.

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

## Completion Checklist

- The run ID, context budget, surfaces, and supplied observations are explicit.
- Host usage is Hermes' recorded accounting for the named session, observed only when it recorded tokens; provider billing and cron stay not_observed.
- The report does not intercept, route, or execute provider or host work.

## Recovery Notes

- If the named Hermes session has no row or recorded tokens, retain supplied timings and context data in run_efficiency_report/v1, mark host_usage not_observed, and hand back the session ID for a recorded-usage check.
- If session_activity_receipt/v1 omits tool durations or context-budget metrics, retain its available observations, mark the missing metrics not_observed rather than zero, and hand back the exact missing measurements.



## When to Use

Use for a bounded local efficiency report from supplied metadata with provider gaps explicit.

    Strong routing signals: `run-efficiency`, `run efficiency report`, `local run efficiency`, `context utilization`, `tool duration report`, `실행 효율 리포트`, `컨텍스트 사용량`, `도구 지연 시간`

## Catalog Metadata

Category: `observability`
Phase: `run-efficiency`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

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

Safety rules:

- Run efficiency is supplied OMH-local metadata plus, for a named Hermes session, Hermes' own recorded usage; it is not provider billing, cron, or host-load evidence.
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
