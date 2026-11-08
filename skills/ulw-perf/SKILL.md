---
name: "ulw-perf"
description: "[omh] Software slowness, memory leaks, or cost spikes: find where a system is actually slow, leaking, or expensive across runtime, memory, token cost, storage, rendering, inference, CI, and query domains, then fix one measured hot path at a time behind a regression budget. Use when the user says: ultraperf, ulw-perf, performance audit, performance bottleneck, find the bottleneck, profile the hot path, memory leak investigation, token cost hotspot."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, optimization]
    category: optimization
    phase: measured-optimization-loop
    role: tracker
    quality_tier: measurement-gated
    related_skills: [omh-code-review, omh-agent-evaluation]
---

# Ultraperf

This is a Hermes-native `ultraperf` workflow skill.

## Why This Exists

`ultraperf` exists because most performance work starts unlocalized: something is slow, leaking, or expensive and nobody knows where. It forces measurement before edits, one hypothesis at a time, executor-owned changes, and a regression budget, so an optimization loop cannot end in unverified claims.

## Do Not Use When

- The ask is to judge code quality, structure, or correctness rather than measured cost; use `omh-code-review`.
- The ask is to score model or agent output quality on a task suite; use `omh-agent-evaluation`.
- The request is a settings-only change, one bounded edit that is explicitly low-risk and has a direct owner and verification path, or one already-identified slow query or hotspot fix; handle it directly instead of opening a performance loop.

## Examples

Good example:

- Prompt: $ultraperf checkout feels slow and the worker memory keeps climbing - find where and fix it
- Expected behavior: Audit the baseline, name the evaluator command, rank hot-path hypotheses, hand the smallest reversible fix to its owner (the Hermes harness unless an external one was chosen), re-measure, and state the budget delta.
- Why: The problem is real but unlocalized across more than one domain.

Bad example:

- Prompt: $ultraperf the docstring on parse_user is wrong
- Expected behavior: Fix the docstring directly; there is no measured cost and no hot path to rank.
- Why: A wrong comment is a correctness edit, not a performance problem, so no baseline or regression budget applies.

## Completion Checklist

- Baseline, workload, environment, and evaluator command are recorded before any edit is proposed.
- Each accepted fix names the measured hot path, the reversible change, and its owner.
- Re-measured deltas cite observed evidence; unmeasured steps stay not_observed.
- The regression budget and the gate that enforces it are stated with the tolerance.

## Recovery Notes

- If no evaluator command exists, stop the loop and produce one before touching code.
- If the re-measure does not move, revert the change and re-rank hypotheses instead of stacking fixes.
- If the goal turns out to be one declared metric with a budget (for example p95 340ms to 200ms with `make bench`), skip the discovery audit: record the declared baseline and evaluator command, then fix and re-measure against the target.

## Workflow Lane

- Current lane: **Intent -> plan** - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when performance problems are suspected but not yet localized, or when several cost hotspots across domains need a measured inspect-and-fix loop.

    Strong routing signals: `ultraperf`, `$ultraperf`, `ulw-perf`, `performance audit`, `performance bottleneck`, `find the bottleneck`, `profile the hot path`, `memory leak investigation`, `token cost hotspot`, `storage footprint audit`, `rendering jank`, `model inference hotspot`, `slow ci pipeline`, `query performance audit`, `performance-goal`, `performance goal`, `latency`, `throughput`, `benchmark`, `성능 병목`, `메모리 누수`, `느려진 원인`, `성능 전반 점검`

## Catalog Metadata

Category: `optimization`
Phase: `measured-optimization-loop`
Hermes role: `tracker`
Quality tier: `measurement-gated`
Reasoning demand: `heavy`

Quality bar:

- Record a baseline and name the evaluator command before proposing any optimization edit.
- Attack only a hot path shown by a measurement or profile; never micro-optimize unmeasured code.
- Keep every fix the smallest reversible change and run its code edit in the Hermes harness, or through `ulw-maestro` when the user chose an external coding owner.
- Re-measure after each change and report deltas only from observed evidence; record the baseline as repeated runs (count and warm-up stated) with median and spread, and treat a delta smaller than the spread as no result.
- Never present a restart, cache flush, or resource bump as a leak fix; prove causation by revert-verify.
- Set the regression budget as baseline x (1 + tolerance) for a lower-is-better metric (latency, memory, cost) or baseline x (1 - tolerance) for a higher-is-better one (throughput), with a tolerance at least the observed spread, and name the CI gate that enforces it.
- A mid-run user message is an interjection, not a stop: answer it briefly and, in the same reply, continue the run — re-read the phase todo when one is active and dispatch or advance the next pending step, or name the armed wait it is waiting on -- handle, bound completion signal, deadline -- instead of re-reading status. Only the user's explicit stop or cancel, or the engine's own completion gate, ends the run; when the interjection changes scope, say so and update the declared plan or todo instead of silently abandoning it. A mid-run message is the latest steering for the active task, not automatically a replacement objective: it replaces the objective when the user says so and steers the current one otherwise.
- A follow-up that needs new authority, materially expands the scope, or changes external state not already authorized is described first and started only on the user's approval: the turn ends by naming that next action and asking whether to take it, as one question carrying the choices the user has, never by declaring what will not be done; persistence never broadens the authorized scope. A refused escalation is answered the same way, with a safer alternative inside the boundary or the authorization the boundary asks for — never a workaround or an indirect execution.
- The closing brief scales to the change: one or two sentences for a simple change. Lead with the result and validation; omit abandoned approaches unless they explain a tradeoff, and internal bookkeeping. Disclose requested-but-not-done work and material prepared/unmerged work; omit unrelated non-action footers. Required accounting stays outside this scaling. Order: result -> relevant evidence/limits -> observed accounting (when required) -> specific question (if useful). For a real unresolved user decision or a useful briefing discussion, offer one specific, content-linked question. Completed work needs no question; discussion grants no authority. Never estimate usage.

Handoff policy:

Hermes owns the audit, baseline, hypothesis, budget, and status; each optimization code edit runs in the Hermes harness (a `delegate_task` lane routed with `omh_delegate_route`) unless the user chose an external coding owner, in which case it goes through `ulw-maestro`; either way it returns as observed re-measurement.

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
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
