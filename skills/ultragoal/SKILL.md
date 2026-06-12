---
name: ultragoal
description: [omh] Hermes Ultragoal workflow: file-backed durable goal ledgers.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, execution]
    category: execution
    phase: durable-goals
    role: runtime-handoff-guidance
    quality_tier: checkpoint-gated
---

# Ultragoal

This is a Hermes-native `ultragoal` workflow skill.

## Why This Exists

`ultragoal` exists for work that can outlive one chat turn: it turns ambition into durable stories, checkpoints, and completion gates so progress can resume without pretending a summary is evidence.

## Do Not Use When

- The request is a single-turn answer, quick diagnosis, or small edit that does not need a durable ledger.
- Acceptance criteria, current checkpoint, and final gate expectations are too vague to make a goal inspectable.
- The user expects hidden Hermes code execution rather than explicit executor handoff and observed verification evidence.

## Examples

Good example:

- Prompt: $ultragoal add per-skill quality rubrics, regenerate skills, test, and open a PR.
- Expected behavior: Create or update a goal ledger, split the story into verifiable checkpoints, and close only after generated docs, skills, and tests match.
- Why: The task has multiple milestones and a final quality gate that should be inspectable across interruptions.

Bad example:

- Prompt: $ultragoal what does this one error mean?
- Expected behavior: Route to diagnosis or a direct answer instead of creating a durable goal.
- Why: A narrow explanation does not need checkpointed long-running state.

## Use When

Use when work needs durable goal artifacts, checkpointed progress, and final quality gates.

    Strong routing signals: `ultragoal`, `$ultragoal`, `durable goal`, `multi-goal`, `goal ledger`

## Catalog Metadata

Category: `execution`
Phase: `durable-goals`
Hermes role: `runtime-handoff-guidance`
Quality tier: `checkpoint-gated`

Quality bar:

- Keep goal state durable, inspectable, and separate from chat narration.
- Checkpoint every success, blocker, and final quality gate with fresh evidence.
- Reject completion with a summary-only goal_completion_gate/v1 result until required criteria, blockers, and explicitly linked runtime runs are satisfied.
- Tell the user the next action through goal_status_card/v1 or goal_continuation/v1 instead of ending with vague follow-up copy.
- For coding milestones, use prepared runtime handoffs and observed runtime evidence rather than hidden execution claims.

Handoff policy:

Use Hermes to maintain .omh/goals goal_ledger/v1 state, show goal_status_card/v1 / goal_continuation/v1 next actions, and route coding milestones to the selected runtime profile with only observed runtime evidence.

Required inputs:

- goal statement
- acceptance criteria
- current checkpoint or missing criteria

Expected outputs:

- goal_ledger/v1 updates
- checkpoint evidence
- goal_completion_gate/v1 result
- completion or blocker summary

Artifact expectations:

- metadata-only .omh/goals ledger
- goal_status_card/v1 or goal_continuation/v1 wrapper payload
- runtime run record only for explicitly linked coding milestones

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `goal-execution`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill ultragoal --harness goal-execution --status started
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
