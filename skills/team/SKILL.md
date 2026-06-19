---
name: team
description: [omh] Hermes Team workflow: coordinated parallel or sequential work lanes.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, execution]
    category: execution
    phase: coordination
    role: handoff-guide
    quality_tier: coordination-gated
---

# Team

This is a Hermes-native `team` workflow skill.

## Why This Exists

`team` exists to keep `execution` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.

## Examples

Good example:

- Prompt: team: handle a execution request that needs explicit evidence boundaries and a clear stop condition.
- Expected behavior: Run `team` only after naming the target, evidence boundary, and stop condition.
- Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.

Bad example:

- Prompt: team: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `team`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, surface status, and hand off to tools or coding agents without hiding unobserved execution.
- Current lane: **Coding handoff** (`idea-to-deploy`, `cto-loop`, `deploy-and-monitor`, `code-review`, `ultrawork`, `team`, `ultraqa`, `ai-slop-cleaner`, `request-to-handoff`, `executor selection`, `coding runtime handoff`) - Codex, Claude Code, Hermes coding, or oh-my runtime paths with observed evidence tracking.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: Carry this context across every OMH skill, not only image or coding skills: match the user's intent to the nearest workflow lane, name adjacent OMH workflows when the request crosses lanes, and keep the next action clear.
- Coverage: Every generated workflow skill carries an OMH Context Rail derived from this awareness payload.
- Normal users talk to Hermes; OMH CLI commands are backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when multiple independent lanes materially improve throughput or verification.

    Strong routing signals: `team`, `$team`, `swarm`, `parallel agents`, `coordinated workers`

## Catalog Metadata

Category: `execution`
Phase: `coordination`
Hermes role: `handoff-guide`
Quality tier: `coordination-gated`

Quality bar:

- Split only independent lanes with explicit ownership and verification boundaries.
- Keep Hermes as coordinator and status narrator while coding lanes become runtime handoffs with explicit ownership.
- Integrate lane evidence before reporting combined progress.

Handoff policy:

Use Hermes for lane framing and status; implementation lanes should become selected runtime handoff tasks, including Hermes-owned coding when the user chooses that runtime.

Executor readiness:

- When accepted work mutates code, check `executor_readiness/v1` for the selected Codex, Claude Code, Hermes, or oh-my runtime path before first dispatch.
- If readiness is `missing` or `blocked`, ask the user to choose another coding agent, configure PATH, continue in Hermes, or keep a prompt/runtime handoff; retry only after that state changes.
- A readiness probe is not dispatch, implementation, verification, review, CI, merge-readiness, or merge evidence.

Required inputs:

- bounded lane definitions
- ownership boundaries
- verification target

Expected outputs:

- lane results
- integration summary
- combined verification evidence

Artifact expectations:

- delegation record only when separate participants are observed

Safety rules:

- Use parallel lanes only when work is independent.
- Keep shared-file edits under one owner.
- Record unobserved delegation as not_observed.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `goal-execution`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill team --harness goal-execution --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
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
