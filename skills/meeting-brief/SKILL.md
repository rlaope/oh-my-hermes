---
name: meeting-brief
description: Hermes Meeting Brief workflow: agenda, prompts, decisions, and record template.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, meeting]
    category: meeting
    phase: preparation
    role: retained-cognition
    quality_tier: facilitation-gated
---

# Meeting Brief

This is a Hermes-native `meeting-brief` workflow skill.

## Use When

Use when Hermes should prepare a meeting agenda, discussion prompts, decision points, and a record template.

    Strong routing signals: `meeting-brief`, `meeting brief`, `meeting agenda`, `agenda`, `discussion prompts`, `decisions needed`, `record template`, `meeting topics`, `회의 주제`, `회의 아젠다`, `아젠다`, `회의 준비`, `논의 질문`, `결정할 것`, `기록 템플릿`

## Catalog Metadata

Category: `meeting`
Phase: `preparation`
Hermes role: `retained-cognition`
Quality tier: `facilitation-gated`

Quality bar:

- Turn context into agenda topics, prompts, decisions needed, and a record template.
- Keep prep distinct from actual meeting minutes or accepted decisions.
- Identify missing context that would change the meeting structure.

Handoff policy:

Run meeting preparation in Hermes; only create follow-up coding handoff from observed decisions or accepted plans.

Required inputs:

- meeting goal
- audience
- known context
- decision topics

Expected outputs:

- agenda
- discussion prompts
- decisions needed
- action-item template

Artifact expectations:

- meeting brief or record template when the wrapper captures it

Safety rules:

- Do not claim the meeting happened from a prepared agenda.
- Separate proposed action items from observed decisions.
- Use a later status or decision record for actual meeting outcomes.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `meeting-facilitation`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill meeting-brief --harness meeting-facilitation --status started
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
