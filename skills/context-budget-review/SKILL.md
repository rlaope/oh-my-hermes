---
name: context-budget-review
description: [omh] Hermes Context Budget Review workflow: plan compact context, token/cost budgets, summarization checkpoints, and overflow recovery before long agent work.
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

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `automation-blueprint`, `github-event-ops`, `agent-board`, `gateway-intent-card`, `voice-operator`, `+14 more`) - schedules, status, health, and release/ops review.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match intent to a lane; name adjacent workflows; generic tool can render or execute is not a dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit/security-safety-review; verify->verification-gate; code->codegraph-refresh/codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use before long-running research, coding, review, or multi-agent work when context, token, cost, or summary drift could break quality.

    Strong routing signals: `context-budget-review`, `context budget review`, `context budget`, `token budget review`, `token budget`, `prompt budget`, `context compaction`, `compact context`, `too much context`, `summarization checkpoint`, `budget this task`, `컨텍스트 예산`, `토큰 예산`, `컨텍스트 압축`, `요약 체크포인트`

## Catalog Metadata

Category: `observability`
Phase: `context-budget-review`
Hermes role: `tracker`
Quality tier: `context-budget-gated`

Quality bar:

- Name must-keep context before summarizing or delegating long work.
- Separate durable requirements, volatile status, file refs, verification evidence, and open blockers.
- Define checkpoint cadence, overflow recovery, and continuity verification.
- Use bounded copy while preserving the full objective and evidence gaps.

Handoff policy:

Keep budget design and status narration in Hermes. Provider billing, exact token usage, runtime compaction, and executor cost evidence require observed wrapper, runtime, or provider data.

Required inputs:

- task or workflow scope
- expected duration, artifacts, and handoff surfaces
- available context sources and must-keep facts
- token, cost, latency, or message-size constraints when known

Expected outputs:

- context_budget_plan/v1
- must_keep_context_pack/v1
- summarization_checkpoint_plan/v1
- budget_risk_register/v1
- overflow_recovery_route/v1
- not-evidence boundary

Artifact expectations:

- context_budget_plan/v1 with scope, max visible context, source priority, discard rules, and checkpoint cadence
- must_keep_context_pack/v1 with durable facts, file refs, decisions, PR/CI state, and blocked assumptions
- summarization_checkpoint_plan/v1 with when to compact, what to preserve, and how to verify continuity
- budget_risk_register/v1 separating estimated cost/token/latency risk from provider-observed truth

Safety rules:

- Do not claim provider billing, exact token counts, or runtime compaction occurred without observed evidence.
- Do not drop user requirements, file paths, PR state, verification gaps, or explicit constraints during compaction.
- Keep estimated budget risk, observed usage, checkpoint summaries, and completion evidence separate.
- Do not use budget pressure as a reason to shrink the user's requested end state.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `context-budget-review`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill context-budget-review --harness context-budget-review --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- Treat wrapper-supplied memory/context summaries as advisory local context, not proof that opaque Hermes memory was read or changed.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, `goal_continuation/v1`, or explicit checklists with named next actions,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
