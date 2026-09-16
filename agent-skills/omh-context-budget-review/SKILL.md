---
name: "omh-context-budget-review"
description: "[omh] Hermes Context Budget Review workflow: plan compact context, token/cost budgets, summarization checkpoints, and overflow recovery before long agent work. Use when the user says: context-budget-review, context budget review, context budget, token budget review, token budget, prompt budget, prompt caching, prompt cache."
compatibility: "Requires the omh CLI on PATH (pip install oh-my-hermes)."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, observability]
    category: observability
    phase: context-budget-review
    role: tracker
    quality_tier: context-budget-gated
---

# Context Budget Review

This is an OMH `context-budget-review` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

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



## Use When

Use before long-running research, coding, review, or multi-agent work when context, token, cost, or summary drift could break quality.

    Strong routing signals: `context-budget-review`, `context budget review`, `context budget`, `token budget review`, `token budget`, `prompt budget`, `prompt caching`, `prompt cache`, `cache hygiene`, `context compaction`, `compact context`, `too much context`, `context window`, `running out of context`, `hand off to a new session`, `summarization checkpoint`, `budget this task`, `컨텍스트 예산`, `토큰 예산`, `컨텍스트 압축`, `요약 체크포인트`

## Catalog Metadata

Category: `observability`
Phase: `context-budget-review`
Quality tier: `context-budget-gated`
Reasoning demand: `standard`

Quality bar:

- Name must-keep context before summarizing or delegating long work.
- Separate durable requirements, volatile status, file refs, verification evidence, and open blockers.
- Define checkpoint cadence, overflow recovery, and continuity verification.
- Use bounded copy while preserving the full objective and evidence gaps.
- Count the must-keep pack by item class, so a replaced pack reports which class lost entries instead of only that a digest moved; a pack that recorded no classes reports the comparison unavailable and never reports zero items.
- Keep prompt-prefix placement cache-stable: fixed section order, volatile bytes never above the fold, mid-run changes as appended messages never system-prompt mutations — load `references/cache-placement.md` for the placement rules.

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

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Report actual tool results or
`not_observed` / `not_available`; never invent dispatch or host accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
