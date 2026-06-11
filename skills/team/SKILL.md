---
name: team
description: [omh] Hermes Team workflow: coordinated parallel or sequential work lanes.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, execution]
    category: execution
    phase: coordination
    role: codex-handoff-guidance
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

## Use When

Use when multiple independent lanes materially improve throughput or verification.

    Strong routing signals: `team`, `$team`, `swarm`, `parallel agents`, `coordinated workers`

## Catalog Metadata

Category: `execution`
Phase: `coordination`
Hermes role: `codex-handoff-guidance`
Quality tier: `coordination-gated`

Quality bar:

- Split only independent lanes with explicit ownership and verification boundaries.
- Keep Hermes as coordinator and status narrator while coding lanes become executor handoffs.
- Integrate lane evidence before reporting combined progress.

Handoff policy:

Use Hermes for lane framing and status; implementation lanes should become selected executor handoff tasks unless they are research, interview, planning, or status-only.

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
