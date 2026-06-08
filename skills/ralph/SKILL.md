---
name: ralph
description: Hermes Ralph workflow: persistent execution with verification and review.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, execution]
    category: execution
    phase: completion
    role: codex-handoff-guidance
    quality_tier: handoff-gated
---

# Ralph

This is a Hermes-native `ralph` workflow skill.

## Use When

Use after scope is concrete and the user wants one owner to continue through implementation and verification.

    Strong routing signals: `ralph`, `$ralph`, `finish until done`, `persistent execution`, `self-referential loop`

## Catalog Metadata

Category: `execution`
Phase: `completion`
Hermes role: `codex-handoff-guidance`
Quality tier: `handoff-gated`

Quality bar:

- Do not enter a finish-until-done loop until scope, acceptance criteria, and verification commands are concrete.
- For coding edits, prepare and track selected executor evidence instead of implying Hermes implemented the changes.
- Report completion only from observed execution and verification evidence.

Handoff policy:

Keep as compatibility guidance; for implementation, ask the wrapper to prepare/track the selected executor path instead of making Hermes the hidden coder.

Required inputs:

- concrete scope
- acceptance criteria
- verification commands

Expected outputs:

- completed work summary
- verification evidence
- remaining risks

Artifact expectations:

- goal-execution run record
- checkpoint or final evidence when available

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
omh runtime record --skill ralph --harness goal-execution --status started
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
  - goal tools -> `.omh/goals/` ledgers or explicit checklists,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
