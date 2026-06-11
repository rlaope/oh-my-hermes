---
name: ops-review
description: [omh] Hermes Ops Review workflow: status, risks, blockers, priorities, and follow-ups.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: status-review
    role: retained-cognition
    quality_tier: status-gated
---

# Ops Review

This is a Hermes-native `ops-review` workflow skill.

## Why This Exists

`ops-review` exists to keep `operations` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.

## Examples

Good example:

- Prompt: ops-review: handle a operations request that needs explicit evidence boundaries and a clear stop condition.
- Expected behavior: Run `ops-review` only after naming the target, evidence boundary, and stop condition.
- Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.

Bad example:

- Prompt: ops-review: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `ops-review`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Use When

Use when Hermes should summarize observed status, risks, blockers, priorities, and follow-up actions for recurring operating work.

    Strong routing signals: `ops-review`, `ops review`, `weekly ops review`, `status review`, `operating review`, `release risks`, `risks and blockers`, `priorities`, `weekly status`, `운영 리뷰`, `주간 운영`, `상태 리뷰`, `리스크`, `블로커`, `우선순위`, `릴리즈 리스크`

## Catalog Metadata

Category: `operations`
Phase: `status-review`
Hermes role: `retained-cognition`
Quality tier: `status-gated`

Quality bar:

- Tie every status claim to observed evidence or mark it as unknown.
- Separate risks, blockers, priorities, and follow-up owners.
- Keep code fixes as explicit follow-up handoffs, not implicit ops-review output.

Handoff policy:

Keep operating review and status narration in Hermes; delegate code fixes only from explicit accepted follow-up items.

Required inputs:

- status evidence
- scope
- time window
- known risks

Expected outputs:

- status summary
- risks
- blockers
- priorities
- follow-up actions

Artifact expectations:

- ops review record or status artifact when a wrapper captures it

Safety rules:

- Do not infer status from missing evidence.
- Separate observed facts, risks, blockers, decisions, and follow-up actions.
- Do not report review, CI, release, or merge readiness from an ops summary alone.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `ops-review`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill ops-review --harness ops-review --status started
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
