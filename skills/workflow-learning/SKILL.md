---
name: workflow-learning
description: [omh] Hermes workflow learning workflow: classify and review self-improvement store routes as an auxiliary review lane before durable writes, then record workflow attempts as metadata-only traces, evals, review queues, patch proposals, regression cases, audits, indexes, and exports.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, optimization]
    category: optimization
    phase: workflow-learning
    role: tracker
    quality_tier: workflow-surface-gated
---

# Workflow Learning

This is a Hermes-native `workflow-learning` workflow skill.

## Why This Exists

`workflow-learning` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: workflow-learning route this self-improvement note before deciding whether it is memory, skill, wiki, failure-retrospective, or automation material.
- Expected behavior: Produce `record_workflow_learning_trace` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: workflow-learning silently patch the skill and claim future behavior is fixed.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Confirm the workflow target, evidence boundary, and stop condition are named.
- Report which outputs are prepared, observed, blocked, or missing.
- Name the smallest next verification or handoff instead of claiming completion from narration.

## Recovery Notes

- If required context is missing, ask one blocking question or route back to the narrower workflow.
- If runtime or wrapper evidence is unavailable, keep the status as not_observed and expose the next observable action.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `automation-blueprint`, `github-event-ops`, `agent-board`, `gateway-intent-card`, `voice-operator`, `+12 more`) - schedules, status, health, and release/ops review.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match intent to a lane; name adjacent workflows; generic tool can render or execute is not a dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit/security-safety-review; verify->verification-gate; code->codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use after a Hermes/OMH workflow attempt should become inspectable, evaluable, routed to memory/skill/wiki/failure-retrospective/automation review, persisted as a metadata-only store-route decision, queued for review, audited, replayable as a regression, converted to a patch handoff, exported, repaired after index drift, or captured as a missed-route signal without raw prompts. Store-route records are an auxiliary review lane surfaced by `learning review` and `learning store-routes`; they are not canonical learning index/export records until a reviewed destination produces its own artifact.

    Strong routing signals: `workflow-learning`, `workflow learning`, `route-signal`, `self-improvement store routing`, `store route review`, `memory skill wiki routing`, `learning trace`, `learning audit`, `self improvement store routing`, `store routing`, `where should this learning go`, `audit learning`, `learning review`, `review queue`, `review-route`, `store-routes`, `learning readiness`, `learning export`, `export bundle`, `learning index`, `index rebuild`, `execution trace`, `skill improvement`, `improvement candidate`, `regression corpus`, `GEPA`, `VPRM`, `process supervision`, `why did this route`, `missed route`, `missed workflow`, `did not use OMH`, `OMH was not used`, `learn from this run`, `이번 실행 학습`, `스킬 개선`, `회귀 케이스`, `실행 기록`, `학습 기록`, `학습 점검`, `학습 준비 상태`, `학습 내보내기`, `OMH 안 썼어`, `워크플로 누락`, `라우팅 누락`

## Catalog Metadata

Category: `optimization`
Phase: `workflow-learning`
Hermes role: `tracker`
Quality tier: `workflow-surface-gated`

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

- workflow-learning/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- workflow-learning/v1 metadata-only runtime or wrapper card when recorded

Safety rules:

- A workflow learning trace, self-improvement store route, patch proposal, or export is process evidence for review. It is not automatic model training, memory mutation, skill mutation, wiki write, automation creation, execution, verification, CI, or merge evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `workflow-learning`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill workflow-learning --harness workflow-learning --status started
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
