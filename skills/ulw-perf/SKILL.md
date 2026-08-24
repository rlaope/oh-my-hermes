---
name: ulw-perf
description: [omh] Ultraperf - find where a system is actually slow, leaking, or expensive across runtime, memory, token cost, storage, rendering, inference, CI, and query domains, then fix one measured hot path at a time behind a regression budget. Use when the user says: ultraperf, ulw-perf, performance audit, performance bottleneck, find the bottleneck, profile the hot path, memory leak investigation, token cost hotspot.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, optimization]
    category: optimization
    phase: measured-optimization-loop
    role: tracker
    quality_tier: measurement-gated
---

# Ultraperf

This is a Hermes-native `ultraperf` workflow skill.

## Why This Exists

`ultraperf` exists because most performance work starts unlocalized: something is slow, leaking, or expensive and nobody knows where. It forces measurement before edits, one hypothesis at a time, executor-owned changes, and a regression budget, so an optimization loop cannot end in unverified claims.

## Do Not Use When

- Metric, baseline, budget, and benchmark command are already declared for one measurable goal; use `performance-goal`.
- The ask is to judge code quality, structure, or correctness rather than measured cost; use `code-review`.
- The ask is to score model or agent output quality on a task suite; use `agent-evaluation`.
- The request is a settings-only change, one bounded edit that is explicitly low-risk and has a direct owner and verification path, or one already-identified slow query or hotspot fix; handle it directly instead of opening a performance loop.

## Examples

Good example:

- Prompt: $ultraperf checkout feels slow and the worker memory keeps climbing - find where and fix it
- Expected behavior: Audit the baseline, name the evaluator command, rank hot-path hypotheses, hand the smallest reversible fix to the selected executor, re-measure, and state the budget delta.
- Why: The problem is real but unlocalized across more than one domain.

Bad example:

- Prompt: $ultraperf make the recommender p95 under 200ms; baseline 340ms, benchmark is 'make bench'
- Expected behavior: Route to `performance-goal`, which owns a declared metric/baseline/budget/benchmark goal.
- Why: A single declared measurable goal does not need a discovery loop.

## Completion Checklist

- Baseline, workload, environment, and evaluator command are recorded before any edit is proposed.
- Each accepted fix names the measured hot path, the reversible change, and its owner.
- Re-measured deltas cite observed evidence; unmeasured steps stay not_observed.
- The regression budget and the gate that enforces it are stated with the tolerance.

## Recovery Notes

- If no evaluator command exists, stop the loop and produce one before touching code.
- If the re-measure does not move, revert the change and re-rank hypotheses instead of stacking fixes.
- If the goal turns out to be one declared metric with a budget, hand off to `performance-goal`.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `codebase-onboarding`, `codegraph-refresh`, `+5 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when performance problems are suspected but not yet localized, or when several cost hotspots across domains need a measured inspect-and-fix loop.

    Strong routing signals: `ultraperf`, `$ultraperf`, `ulw-perf`, `performance audit`, `performance bottleneck`, `find the bottleneck`, `profile the hot path`, `memory leak investigation`, `token cost hotspot`, `storage footprint audit`, `rendering jank`, `model inference hotspot`, `slow ci pipeline`, `query performance audit`, `성능 병목`, `메모리 누수`, `느려진 원인`, `성능 전반 점검`

## Catalog Metadata

Category: `optimization`
Phase: `measured-optimization-loop`
Hermes role: `tracker`
Quality tier: `measurement-gated`
Reasoning demand: `heavy`

Quality bar:

- Record a baseline and name the evaluator command before proposing any optimization edit.
- Attack only a hot path shown by a measurement or profile; never micro-optimize unmeasured code.
- Keep every fix the smallest reversible change and route code edits to the selected executor.
- Re-measure after each change and report deltas only from observed evidence.
- Never present a restart, cache flush, or resource bump as a leak fix; prove causation by revert-verify.
- Set the regression budget as baseline x (1 + tolerance) and name the CI gate that enforces it.
- A mid-run user message is an interjection, not a stop: answer it briefly and, in the same reply, continue the run — re-read the phase todo when one is active and dispatch or advance the next pending step, or state exactly what the run is waiting on (for example, lanes still in flight that resume when their results return). Only the user's explicit stop or cancel, or the engine's own completion gate, ends the run; when the interjection changes scope, say so and update the declared plan or todo instead of silently abandoning it.

Handoff policy:

Hermes owns the audit, baseline, hypothesis, budget, and status; every optimization code edit becomes a selected executor/runtime handoff and returns as observed re-measurement.

Required inputs:

- symptom or suspected slow surface
- workload or reproduction
- runnable evaluator or measurement command
- acceptable tolerance

Expected outputs:

- baseline record
- ranked hot-path hypotheses
- smallest reversible fix handoff
- re-measured delta
- regression budget and gate

Artifact expectations:

- baseline measurement record
- final profile or benchmark evidence
- budget delta with tolerance

Safety rules:

- Do not claim a profile, benchmark, measurement, or CI budget gate ran without observed evidence.
- Do not begin optimization edits before an evaluator command and its pass/fail contract exist.
- Ask for the workload, environment, and acceptable tolerance before declaring a budget.

## Runtime Evidence

Preferred harness for this skill: `goal-execution`.

```sh
omh runtime record --skill ultraperf --harness goal-execution --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
