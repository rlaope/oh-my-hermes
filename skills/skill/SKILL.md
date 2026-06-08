---
name: skill
description: Hermes adaptation for managing local skills.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operator]
    category: operator
    phase: skill-management
    role: retained-operator
    quality_tier: evidence-gated
---

# Skill

This is a Hermes-native `skill` workflow skill.

## Use When

Use for local skill listing, search, add, remove, or edit tasks.

    Strong routing signals: `skill`, `$skill`, `skills`, `manage skills`

## Catalog Metadata

Category: `operator`
Phase: `skill-management`
Hermes role: `retained-operator`
Quality tier: `evidence-gated`

Quality bar:

- Name the workflow target, constraints, validation evidence, and stop condition.
- Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.

Handoff policy:

Use Hermes for inventory and guidance; delegate only repository code changes to the selected coding executor.

Required inputs:

- skill action
- target skill name or directory

Expected outputs:

- skill inventory or mutation result
- verification note

Artifact expectations:

- manifest update when managed skills change

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `docs-specialist`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill skill --harness docs-specialist --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
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
