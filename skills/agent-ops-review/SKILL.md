---
name: agent-ops-review
description: [omh] Hermes agent ops review workflow: help a manager inspect AI-agent research, coding, review, status, blockers, quality gates, and throughput levers.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operator]
    category: operator
    phase: manager-review
    role: tracker
    quality_tier: workflow-surface-gated
---

# Agent Ops Review

This is a Hermes-native `agent-ops-review` workflow skill.

## Why This Exists

`agent-ops-review` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: agent-ops-review show me quality, blockers, and throughput for AI-agent research, coding, and review work.
- Expected behavior: Produce `prepare_agent_ops_review` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: agent-ops-review claim Codex finished and CI passed because a handoff exists.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Current lane: **Automation and status** (`automation-blueprint`, `ops-observability-card`, `agent-ops-review`, `doctor`) - scheduled ops blueprints, status cards, runtime health, and release/ops review.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Normal users talk to Hermes; OMH CLI commands are backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should explain AI-agent work from a manager/operator perspective: quality gates, progress, blockers, next actions, and throughput opportunities across research, coding, review, and status.

    Strong routing signals: `agent-ops-review`, `agent ops review`, `agent productivity`, `operator productivity`, `manager view`, `quality dashboard`, `throughput review`, `agent work quality`, `coding progress quality`, `research coding review status`, `ai agent manager`, `third-party manager`, `관리자 입장`, `작업 생산량`, `처리량`, `품질 퀄리티`, `작업 품질`, `진행상황`, `리서치 코딩 리뷰`

## Catalog Metadata

Category: `operator`
Phase: `manager-review`
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

- agent-ops-review/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- agent-ops-review/v1 metadata-only runtime or wrapper card when recorded

Safety rules:

- An agent ops review card is not source retrieval, executor dispatch, coding progress, implementation, review, verification, CI, merge-readiness, merge, platform delivery, provider billing, or live runtime telemetry evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `agent-ops-review`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill agent-ops-review --harness agent-ops-review --status started
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
