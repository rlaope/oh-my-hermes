---
name: loop
description: Hermes Loop workflow: ambitious goal interview, research, planning, runtime ticks, handoff, feedback, and resume cycles.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, goal-loop]
    category: goal-loop
    phase: continuous-goal-loop
    role: retained-cognition
    quality_tier: loop-gated
---

# Loop

This is a Hermes-native `loop` workflow skill.

## Use When

Use when the user explicitly starts a high-level, long-horizon goal loop that should refine the goal, separate implementable work from external waiting, and keep cycling through task discovery, distribution, execution, verification, next-task decisions, runtime tick queueing, handoff, feedback, and status until the authority envelope or evidence gate stops it.

    Strong routing signals: `loop`, `./loop`, `$loop`, `goal loop`, `long horizon goal`, `never stop`, `research plan ultragoal feedback`, `token exhaustion resume`, `permission profile`, `star 10k`, `10k star`, `loop engineering`, `루프`, `목표 루프`, `장기 목표`, `끝까지`, `토큰 고갈`, `피드백 루프`

## Catalog Metadata

Category: `goal-loop`
Phase: `continuous-goal-loop`
Hermes role: `retained-cognition`
Quality tier: `loop-gated`

Quality bar:

- Start with direct user intent such as `./loop` or an explicit ambitious goal loop request.
- Reframe the north-star goal into implementable internal work without shrinking its ambition.
- Separate task discovery, distribution, execution, verification, next-task decision, runtime tick queueing, ultragoal/handoff, feedback, waiting, and resume decisions.
- Expose a permission profile before executor dispatch, repository mutation, PR, merge, or external publishing.
- Expose the automation, worktree, skill, connector, and subagent building-block states without treating planned blocks as observed work.
- Choose workflow patterns such as single-step, fan-out-and-synthesize, adversarial verification, tournament, or triage batch as orchestration metadata only.
- Keep repeated scaffold shape stable, summarize within bounded budgets, and add verifier lanes only when risk or evidence warrants them.
- Keep prepared worktree/subagent/connector plans, observed executor work, linked goal completion, and external waiting as distinct evidence states.

Handoff policy:

Keep loop orchestration, interviews, research, planning, runtime ticks with deterministic queue shapes, loop_engineering/v1 pipeline and building-block status, feedback evaluation, status, and permission-envelope narration in Hermes; prepare selected executor/worktree/connector handoffs only when the loop produces concrete work and record completion only from linked goal/runtime evidence.

Required inputs:

- north-star goal summary
- goal reframe
- success criteria
- permission profile
- feedback or wait signal

Expected outputs:

- loop_start_card/v1 setup prompt
- loop_cycle/v1 state
- loop_engineering/v1 pipeline/building-block snapshot
- loop cost_policy for bounded reads and verifier restraint
- loop_status_card/v1 next action
- loop_runtime/v1 queued tick with loop policy refs
- loop_queue_handoff/v1 only when permitted
- executor-neutral handoff only when permitted
- external-wait or checkpoint boundary

Artifact expectations:

- metadata-only .omh/loops loop_cycle/v1 artifact
- loop_engineering/v1 status over automation, worktree, skill, connector, and subagent blocks
- loop_runtime/v1 queue entries with context_policy_ref and cost_policy_ref
- loop_subagent_result_contract/v1 for prepared subagent handoffs
- loop_status_card/v1 wrapper payload
- loop_start_card/v1 wrapper setup card
- linked goal_ledger/v1 only when completion evidence is required

Safety rules:

- Do not treat loop persistence as permission to bypass the selected permission profile.
- Do not treat a runtime tick as worktree creation, subagent dispatch, connector I/O, implementation, review, CI, merge, publication, or completion evidence.
- Do not claim goal completion from loop state; require linked goal_ledger/v1 completion evidence.
- When context or token budget runs out, checkpoint or rely on resumable state instead of pretending the loop is complete.
- External results such as market response, stars, or adoption are waiting states unless observed evidence is supplied.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `goal-loop`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill loop --harness goal-loop --status started
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
