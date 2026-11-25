# Context Budget Review

Load this on-demand contract after the compact `context-budget-review` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

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

## Full Input, Output, and Artifact Expectations

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
