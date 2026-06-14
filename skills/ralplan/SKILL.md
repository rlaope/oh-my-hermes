---
name: ralplan
description: [omh] Hermes Ralplan workflow: consensus planning with review gates.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: reviewed-plan
    role: retained-cognition
    quality_tier: reviewed-plan-gated
---

# Ralplan

This is a Hermes-native `ralplan` workflow skill.

## Why This Exists

`ralplan` exists to keep `planning` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.

## Examples

Good example:

- Prompt: ralplan: handle a planning request that needs explicit evidence boundaries and a clear stop condition.
- Expected behavior: Run `ralplan` only after naming the target, evidence boundary, and stop condition.
- Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.

Bad example:

- Prompt: ralplan: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `ralplan`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Use When

Use when requirements are clear enough for planning but architecture, risks, or tests need review.

    Strong routing signals: `ralplan`, `$ralplan`, `consensus plan`, `reviewed plan`, `issue to PR`, `acceptance criteria`, `verification command`, `reviewable PR`, `risky planning`, `dangerous`, `dangerous planning`, `unsafe`, `refactor safety`, `PR로 만들`, `PR로 만들 수 있게`, `위험한 리팩터링`, `리팩터링 위험`, `리스크 있는 리팩터링`, `검증 command`, `리뷰 가능한 단위`

## Catalog Metadata

Category: `planning`
Phase: `reviewed-plan`
Hermes role: `retained-cognition`
Quality tier: `reviewed-plan-gated`

Quality bar:

- Include a planner view, risk review, and testability check before handoff.
- Record unresolved tradeoffs and rejected options instead of flattening uncertainty.
- Do not implement directly from consensus planning.

Handoff policy:

Keep consensus planning and review in Hermes; produce explicit selected executor/runtime handoff guidance only after the plan is accepted.

Required inputs:

- requirements
- options
- tradeoffs
- test shape

Expected outputs:

- approved plan
- risk review
- handoff guidance

Artifact expectations:

- plan and review artifacts when a wrapper supports file-backed planning

Safety rules:

- Do not implement directly from the planning lane.
- Make acceptance criteria testable.
- Record unresolved tradeoffs explicitly.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `planning`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill ralplan --harness planning --status started
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
