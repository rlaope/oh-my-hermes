---
name: ultrawork
description: [omh] Hermes Ultrawork compatibility workflow: bounded parallel delivery guidance.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, execution]
    category: execution
    phase: parallel-delivery
    role: runtime-handoff-guidance
    quality_tier: handoff-gated
---

# Ultrawork

This is a Hermes-native `ultrawork` workflow skill.

## Why This Exists

`ultrawork` exists to split an accepted implementation plan into independent lanes without letting parallelism blur ownership, verification, worker protocol, worktree isolation, or observed runtime evidence.

## Do Not Use When

- The work touches the same files or invariants in ways that need one owner.
- The plan is not accepted, lane boundaries are unclear, or verification commands are missing.
- The user expects Hermes to secretly execute coding lanes instead of preparing explicit selected-runtime handoffs.

## Examples

Good example:

- Prompt: $ultrawork implement docs refresh, CLI output polish, and tests as separate accepted lanes.
- Expected behavior: Create disjoint lane prompts with acceptance criteria, verification commands, and review evidence requirements.
- Why: The work can be split cleanly and benefits from parallel execution discipline.

Bad example:

- Prompt: $ultrawork refactor the central router in five agents at once.
- Expected behavior: Keep one owner or re-plan boundaries before parallelization.
- Why: Shared core logic makes parallel edits likely to conflict or hide regressions.

## Use When

Use when an accepted implementation plan can be split into independent, reviewable work lanes.

    Strong routing signals: `ultrawork`, `$ultrawork`, `parallel work`, `parallel implementation`, `high throughput`

## Catalog Metadata

Category: `execution`
Phase: `parallel-delivery`
Hermes role: `runtime-handoff-guidance`
Quality tier: `handoff-gated`

Quality bar:

- Require disjoint lane ownership before preparing multiple coding runtime handoffs.
- Attach acceptance criteria, verification commands, and review expectations to each lane.
- Keep dispatch, execution, review, CI, and merge status evidence separate.

Handoff policy:

Keep the workflow name for compatibility, but convert coding lanes into explicit selected runtime handoffs with disjoint scope, verification, review evidence, worker protocol, and worktree guidance.

Required inputs:

- accepted plan
- lane list
- disjoint file or responsibility scopes
- verification commands

Expected outputs:

- runtime handoff prompts or lane instructions
- status summary
- review/CI evidence requirements

Artifact expectations:

- prepared coding delegation record per implementation lane when wrappers can record them

Safety rules:

- Do not start parallel coding without disjoint ownership boundaries.
- Keep Hermes responsible for orchestration/status; when Hermes itself is selected for coding, still preserve runtime evidence boundaries.
- Record unobserved executor work as prepared_not_observed or not_observed.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `goal-execution`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill ultrawork --harness goal-execution --status started
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
