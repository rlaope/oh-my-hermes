---
name: "omh-context-budget-review"
description: "[omh] Hermes Context Budget Review workflow: plan compact context, token/cost budgets, summarization checkpoints, and overflow recovery before long agent work. Use when the user says: context-budget-review, context budget review, context budget, token budget review, token budget, prompt budget, prompt caching, prompt cache."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, observability]
    category: observability
    phase: context-budget-review
    role: tracker
    quality_tier: context-budget-gated
---

# Context Budget Review

This is a Hermes-native `context-budget-review` workflow skill.

## Why This Exists

`context-budget-review` ports ECC's context-budget and token-budget instincts into OMH as a compactness gate that protects long-running work without redefining success around a smaller task.

## Do Not Use When

- The user asks for live token/cost telemetry; use `ops-observability-card`.
- The user asks to continue a loopable goal; use `loop` unless budget planning is the explicit blocker.
- The task is a short one-step answer with no meaningful context risk.

## Examples

Good example:

- Prompt: context-budget-review 이 장기 PR 작업에서 어떤 맥락을 꼭 유지하고 언제 요약해야 하는지 잡아줘.
- Expected behavior: Prepare context_budget_plan/v1, must_keep_context_pack/v1, checkpoint plan, risk register, and overflow recovery route.
- Why: The request is about preserving context quality during long-running agent work.

Bad example:

- Prompt: context-budget-review 토큰 아끼려고 원래 목표를 더 작은 목표로 바꿔줘.
- Expected behavior: Reject goal shrinking and instead compact context while preserving the full objective and evidence gaps.
- Why: Budget review optimizes context handling, not the user's requested end state.

## Completion Checklist

- The run or workflow scope, metric window, failure modes, and cost/latency boundary are named.
- Local telemetry, provider truth, billing truth, and completion evidence are separate states.
- Warnings name the next measurement or operator review action.

## Recovery Notes

- If provider metrics are unavailable, report only local metadata and mark provider truth not_observed.
- If cost or latency looks risky, surface a warning plus the next measurement rather than a completion claim.

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+36 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use before long-running research, coding, review, or multi-agent work when context, token, cost, or summary drift could break quality.

    Strong routing signals: `context-budget-review`, `context budget review`, `context budget`, `token budget review`, `token budget`, `prompt budget`, `prompt caching`, `prompt cache`, `cache hygiene`, `context compaction`, `compact context`, `too much context`, `context window`, `running out of context`, `hand off to a new session`, `summarization checkpoint`, `budget this task`, `컨텍스트 예산`, `토큰 예산`, `컨텍스트 압축`, `요약 체크포인트`

## Catalog Metadata

Category: `observability`
Phase: `context-budget-review`
Hermes role: `tracker`
Quality tier: `context-budget-gated`
Reasoning demand: `standard`

Quality bar:

- Name must-keep context before summarizing or delegating long work.
- Separate durable requirements, volatile status, file refs, verification evidence, and open blockers.
- Define checkpoint cadence, overflow recovery, and continuity verification.
- Use bounded copy while preserving the full objective and evidence gaps.
- Count the must-keep pack by item class, so a replaced pack reports which class lost entries instead of only that a digest moved; a pack that recorded no classes reports the comparison unavailable and never reports zero items.
- Keep prompt-prefix placement cache-stable: fixed section order, volatile bytes never above the fold, mid-run changes as appended messages never system-prompt mutations — load `references/cache-placement.md` for the placement rules.

Handoff policy:

Keep budget design and status narration in Hermes. Provider billing, exact token usage, runtime compaction, and executor cost evidence require observed wrapper, runtime, or provider data.

Route binding:

- Bind the plan to the session's published `context_budget_plan/v1` (agent/operator: `omh context budget-plan prepare|rebind|status --session-ref <session>`). Unpublished capacity holds as `capacity_unknown_hold` and inherits nothing; a hold or checkpoint action is a prepared obligation, not compaction, usage, or billing evidence. Rules: `references/route-capacity.md`.

Required inputs:

- task or workflow scope
- expected duration, artifacts, and handoff surfaces
- available context sources and must-keep facts
- token, cost, latency, or message-size constraints when known

Expected outputs:

- context_budget_plan/v1
- must_keep_context_pack/v1
- must_keep_item_class_delta/v1 when a pack replaces an earlier one
- summarization_checkpoint_plan/v1
- budget_risk_register/v1
- overflow_recovery_route/v1
- not-evidence boundary

Artifact expectations:

- context_budget_plan/v1 with scope, max visible context, source priority, discard rules, and checkpoint cadence
- must_keep_context_pack/v1 with durable facts, file refs, decisions, PR/CI state, and blocked assumptions
- must_keep_item_class_delta/v1 naming the item class that lost entries rather than reporting a digest difference, over the closed vocabulary prohibitions, decisions, open_questions, requirements, paths, pr_state, verification_gaps
- summarization_checkpoint_plan/v1 with when to compact, what to preserve, and how to verify continuity
- budget_risk_register/v1 separating estimated cost/token/latency risk from provider-observed truth

Safety rules:

- Do not claim provider billing, exact token counts, or runtime compaction occurred without observed evidence.
- Do not drop user requirements, file paths, PR state, verification gaps, or explicit constraints during compaction.
- Keep estimated budget risk, observed usage, checkpoint summaries, and completion evidence separate.
- Do not use budget pressure as a reason to shrink the user's requested end state.

## Runtime Evidence

Preferred harness for this skill: `context-budget-review`.

```sh
omh runtime record --skill context-budget-review --harness context-budget-review --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
