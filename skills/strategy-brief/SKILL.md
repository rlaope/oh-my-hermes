---
name: strategy-brief
description: [omh] Hermes Strategy Brief workflow: options, tradeoffs, recommendation, and decision notes.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, strategy]
    category: strategy
    phase: brief
    role: retained-cognition
    quality_tier: decision-gated
---

# Strategy Brief

This is a Hermes-native `strategy-brief` workflow skill.

## Why This Exists

`strategy-brief` exists to keep `strategy` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.

## Examples

Good example:

- Prompt: strategy-brief: handle a strategy request that needs explicit evidence boundaries and a clear stop condition.
- Expected behavior: Run `strategy-brief` only after naming the target, evidence boundary, and stop condition.
- Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.

Bad example:

- Prompt: strategy-brief: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `strategy-brief`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Use When

Use when Hermes should turn goals and evidence into options, tradeoffs, recommendations, and a decision-ready brief.

    Strong routing signals: `strategy-brief`, `strategy brief`, `strategy memo`, `product strategy`, `strategic options`, `decision note`, `leadership strategy`, `next strategy`, `다음 전략`, `전략 정리`, `전략 메모`, `전략 옵션`, `의사결정`, `리더십 회의`

## Catalog Metadata

Category: `strategy`
Phase: `brief`
Hermes role: `retained-cognition`
Quality tier: `decision-gated`

Quality bar:

- Name the decision, constraints, options, tradeoffs, and rejected alternatives.
- Tie recommendations to observed evidence or mark them as assumptions.
- Keep coding handoff disabled until strategy is accepted and code work is explicit.

Handoff policy:

Keep strategy synthesis in Hermes; do not create implementation handoff until a decision is accepted and code work is explicit.

Required inputs:

- goal
- known evidence
- constraints
- decision owner

Expected outputs:

- options
- tradeoffs
- recommended direction
- decision note

Artifact expectations:

- strategy brief or decision note when a wrapper captures it

Safety rules:

- Do not treat a draft recommendation as an accepted decision.
- Keep unresolved assumptions visible.
- Separate strategy from implementation planning unless the user asks for execution.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `strategy-synthesis`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill strategy-brief --harness strategy-synthesis --status started
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
