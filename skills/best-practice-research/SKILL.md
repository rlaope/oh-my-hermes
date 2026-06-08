---
name: best-practice-research
description: Hermes adaptation for bounded official/upstream best-practice research.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: evidence
    role: retained-cognition
    quality_tier: source-gated
---

# Best Practice Research

This is a Hermes-native `best-practice-research` workflow skill.

## Use When

Use when correctness depends on current official or upstream guidance.

    Strong routing signals: `best-practice-research`, `best practice`, `official docs`, `upstream guidance`

## Catalog Metadata

Category: `research`
Phase: `evidence`
Hermes role: `retained-cognition`
Quality tier: `source-gated`

Quality bar:

- Use official or upstream sources first and name the version/environment assumptions.
- Map applicability to the user's local context before recommending action.
- Preserve residual uncertainty instead of overstating best practice.

Handoff policy:

Run as Hermes-side evidence gathering; hand coding to the selected executor only after source-backed guidance is summarized.

Required inputs:

- chosen technology
- question
- version or environment constraints

Expected outputs:

- source-backed guidance
- applicability notes
- residual uncertainty

Artifact expectations:

- research notes or citations when the wrapper captures them

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `research`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill best-practice-research --harness research --status started
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
