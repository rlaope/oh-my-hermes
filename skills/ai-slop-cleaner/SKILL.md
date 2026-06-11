---
name: ai-slop-cleaner
description: [omh] Hermes AI slop cleaner workflow: behavior-preserving cleanup.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, maintenance]
    category: maintenance
    phase: cleanup
    role: codex-handoff-guidance
    quality_tier: regression-gated
---

# Ai Slop Cleaner

This is a Hermes-native `ai-slop-cleaner` workflow skill.

## Why This Exists

`ai-slop-cleaner` exists to keep `maintenance` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.

## Examples

Good example:

- Prompt: ai-slop-cleaner: handle a maintenance request that needs explicit evidence boundaries and a clear stop condition.
- Expected behavior: Run `ai-slop-cleaner` only after naming the target, evidence boundary, and stop condition.
- Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.

Bad example:

- Prompt: ai-slop-cleaner: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `ai-slop-cleaner`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Use When

Use for behavior-preserving cleanup with tests before and after edits.

    Strong routing signals: `ai-slop-cleaner`, `$ai-slop-cleaner`, `cleanup`, `deslop`, `refactor`, `risky`, `safe refactor`, `risk analysis`, `refactor workflow`, `legacy refactor`, `위험한 리팩터링`, `리팩터링`, `리팩토링`, `위험 분석`, `변경 범위 제한`, `회귀 테스트`

## Catalog Metadata

Category: `maintenance`
Phase: `cleanup`
Hermes role: `codex-handoff-guidance`
Quality tier: `regression-gated`

Quality bar:

- Lock current behavior with regression checks before non-trivial cleanup.
- Prefer deletion, reuse, and boundary repair over new abstractions.
- Rerun verification after cleanup before claiming behavior is preserved.

Handoff policy:

Use Hermes to define cleanup scope and regression checks; delegate behavior-preserving edits to the selected coding executor once tests are clear.

Required inputs:

- target smell
- current behavior
- regression checks

Expected outputs:

- small cleanup diff
- before/after verification
- residual risk

Artifact expectations:

- cleanup plan and regression evidence for non-trivial work

Safety rules:

- Lock behavior with tests before risky cleanup.
- Prefer deletion and existing utilities over new layers.
- Do not add dependencies for cleanup unless explicitly requested.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `coding-handling`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill ai-slop-cleaner --harness coding-handling --status started
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
