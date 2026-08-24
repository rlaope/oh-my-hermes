---
name: omh-performance-goal
description: [omh] Hermes adaptation for measurable performance-goal execution. Use when the user says: performance-goal, performance goal, latency, throughput, benchmark.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, optimization]
    category: optimization
    phase: measurement
    role: tracker
    quality_tier: measurement-gated
---

# Performance Goal

This is a Hermes-native `performance-goal` workflow skill.

## Why This Exists

`performance-goal` exists to keep `optimization` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The ask is to find where performance problems are, or to fix multiple unscoped hotspots across domains; use `ultraperf`.

## Examples

Good example:

- Prompt: performance-goal: benchmark recommendation latency, optimize hot paths safely, and prove no regressions.
- Expected behavior: Create a measurement-led optimization loop with baseline, change, verification, and regression evidence.
- Why: The request is performance optimization and needs measured before/after proof.

Bad example:

- Prompt: performance-goal: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `performance-goal`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Completion Checklist

- Confirm the workflow target, evidence boundary, and stop condition are named.
- Report which outputs are prepared, observed, blocked, or missing.
- Name the smallest next verification or handoff instead of claiming completion from narration.

## Recovery Notes

- If required context is missing, ask one blocking question or route back to the narrower workflow.
- If runtime or wrapper evidence is unavailable, keep the status as not_observed and expose the next observable action.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `codebase-onboarding`, `codegraph-refresh`, `+5 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when the goal is measurable performance improvement with evaluator evidence.

    Strong routing signals: `performance-goal`, `performance goal`, `latency`, `throughput`, `benchmark`

## Catalog Metadata

Category: `optimization`
Phase: `measurement`
Hermes role: `tracker`
Quality tier: `measurement-gated`
Reasoning demand: `heavy`

Quality bar:

- Name the metric, baseline, budget, and benchmark command before optimizing.
- Treat code-level optimization as executor work when edits are required.
- Report deltas only from observed benchmark evidence.

Handoff policy:

Hermes can own baselines, benchmark plans, and status; optimization code changes should be selected executor/runtime handoffs.

Required inputs:

- metric
- baseline
- budget
- benchmark command

Expected outputs:

- measurement delta
- implementation summary
- benchmark evidence

Artifact expectations:

- baseline and final benchmark evidence

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Runtime Evidence

Preferred harness for this skill: `goal-execution`.

```sh
omh runtime record --skill performance-goal --harness goal-execution --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
