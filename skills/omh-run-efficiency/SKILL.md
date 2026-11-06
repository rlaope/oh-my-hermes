---
name: "omh-run-efficiency"
description: "[omh] Run efficiency and context usage report: report supplied local run efficiency while provider data stays unobserved. Use when the user says: run-efficiency, run efficiency report, local run efficiency, context utilization, tool duration report, 실행 효율 리포트, 컨텍스트 사용량, 도구 지연 시간."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, observability]
    category: observability
    phase: run-efficiency
    role: tracker
    quality_tier: workflow-surface-gated
    related_skills: [omh-ops-observability-card]
---

# Run Efficiency

This is a Hermes-native `run-efficiency` workflow skill.

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

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+40 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use for a bounded local efficiency report from supplied metadata with provider gaps explicit.

    Strong routing signals: `run-efficiency`, `run efficiency report`, `local run efficiency`, `context utilization`, `tool duration report`, `실행 효율 리포트`, `컨텍스트 사용량`, `도구 지연 시간`

## Catalog Metadata

Category: `observability`
Phase: `run-efficiency`
Hermes role: `tracker`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

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

- run_efficiency_report/v1 metadata-only report, built with `omh runtime efficiency-report --input <run_efficiency_input/v1 file> [--hermes-session <id>] [--write]`; the input carries the supplied run id, context budget, surfaces and tool durations, and with no input file you ask for the timings and never write estimates into it
- supplied `session_activity_receipt/v1` when available; unavailable metrics stay unavailable, never zero
- `host_usage` from the Hermes-accounted part of the cost receipt `omh_run_summary` returns (the session, its delegated children, and its kanban workers; `--hermes-session`, and a local Hermes terminal holds the id in `$HERMES_SESSION_ID`): observed only when Hermes recorded tokens for it; no session row or no tokens stays not_observed, never zero

Safety rules:

- Run efficiency is supplied OMH-local metadata plus, for a named Hermes session, Hermes' own recorded usage; it is not provider billing, cron, or host-load evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `run-efficiency`.

```sh
omh runtime record --skill run-efficiency --harness run-efficiency --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
