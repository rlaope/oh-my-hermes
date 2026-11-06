---
name: "omh-context-budget-review"
description: "[omh] Context window or token budget at risk: plan compact context, token/cost budgets, summarization checkpoints, and overflow recovery before long agent work. Use when the user says: context-budget-review, context budget review, context budget, token budget review, token budget, prompt budget, prompt caching, prompt cache."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, observability]
    category: observability
    phase: context-budget-review
    role: tracker
    quality_tier: context-budget-gated
    related_skills: [ulw-loop]
---

# Context Budget Review

This is a Hermes-native `context-budget-review` workflow skill.

## Why This Exists

`context-budget-review` ports ECC's context-budget and token-budget instincts into OMH as a compactness gate that protects long-running work without redefining success around a smaller task.

## Do Not Use When

- The user asks only what this Hermes session has used or cost so far; Hermes' /usage shows this session's tokens and context, /insights estimates cost across recent sessions, and the omh_run_summary tool relays this conversation's recorded tokens and cost.
- The user asks to continue a loopable goal; use `ulw-loop` unless budget planning is the explicit blocker.
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

- If the previous must-keep pack has no item classes, retain its recorded contents, mark the class delta unresolved, and hand back must_keep_item_class_delta/v1 as comparison unavailable, never as zero items.
- If a checkpoint is due but no Hermes /compress reply is observed, retain the must-keep context pack and checkpoint plan, mark compaction not_observed, and hand back /compress <focus> with the reply needed to verify continuity.
- If the session has no published context_budget_plan/v1, retain the proposed budget plan, mark inherited capacity unresolved, and hand back the capacity_unknown_hold and session reference for publication or rebinding.

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+40 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use before long-running research, coding, review, or multi-agent work when context, token, cost, or summary drift could break quality.

    Strong routing signals: `context-budget-review`, `context budget review`, `context budget`, `token budget review`, `token budget`, `prompt budget`, `prompt caching`, `prompt cache`, `cache hygiene`, `context compaction`, `compact context`, `too much context`, `context window`, `running out of context`, `hand off to a new session`, `summarization checkpoint`, `budget this task`, `컨텍스트 예산`, `토큰 예산`, `컨텍스트 압축`, `요약 체크포인트`, `что жрёт токены`, `бюджет токенов`, `контекст переполнен`, `сколько уходит токенов`, `на что уходят токены`, `на что тратятся токены`

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
- On Hermes, bind the summarization checkpoint to Hermes' own compaction: render the must-keep classes as one short focus topic and hand the person `/compress <focus>` to run when the checkpoint is due. OMH never compresses, and a compaction is observed only from Hermes' own reply to that command.
- On Hermes, offer `/compress --preview <focus>` only in the classic CLI or on a messaging platform, never when the surface is unknown, and count it as a preview only when the reply says `Preview — no changes made.`: a modern TUI whose `/compress` does not parse the flag compresses for real with the flag in its focus. Context occupancy is the person's `/usage` reading when shared, otherwise an estimate.

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
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
