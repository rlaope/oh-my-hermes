---
name: operating-rhythm
description: [omh] Hermes Operating Rhythm workflow: meeting minutes, scrum/sprint records, retros, decisions, and follow-up history.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: rhythm-history
    role: retained-cognition
    quality_tier: operations-gated
---

# Operating Rhythm

This is a Hermes-native `operating-rhythm` workflow skill.

## Why This Exists

`operating-rhythm` exists so recurring operating work has durable minutes, decisions, and follow-up history without pretending a meeting outcome was observed.

## Do Not Use When

- The user only needs a one-off meeting agenda before the meeting; use `meeting-brief`.
- The request is a weekly status/risk summary rather than cadence history; use `ops-review`.
- The user asks for report packaging, PPT outline, or reliability evidence review.

## Examples

Good example:

- Prompt: operating-rhythm 회의록 히스토리 관리하고 스크럼 스프린트 회고를 정리해줘.
- Expected behavior: Create a prepared operating record with cadence, decisions, action items, and not-evidence markers for missing observed notes.
- Why: The request is about recurring operating history, not a generic agenda or code handoff.

Bad example:

- Prompt: operating-rhythm implement the action items from the retro.
- Expected behavior: Route implementation to a plan or selected executor/runtime handoff after action items are accepted.
- Why: Operating records can capture follow-ups, but implementation is a separate observed work stream.

## Use When

Use when Hermes should prepare or maintain recurring operating records such as meetings, scrums, sprint plans, retrospectives, decisions, and follow-ups.

    Strong routing signals: `operating-rhythm`, `operating rhythm`, `meeting minutes`, `meeting history`, `scrum record`, `sprint planning`, `sprint review`, `sprint retrospective`, `retro history`, `decision log`, `action item history`, `회의록 관리`, `회의 히스토리`, `운영 리듬`, `스크럼`, `스프린트 회고`, `결정 기록`, `액션 아이템`

## Catalog Metadata

Category: `operations`
Phase: `rhythm-history`
Hermes role: `retained-cognition`
Quality tier: `operations-gated`

Quality bar:

- Name cadence, audience, time window, known notes, and missing evidence before producing a record.
- Separate agenda/templates from observed minutes, decisions, and action items.
- Record follow-up ownership only when supplied or explicitly mark it unknown.

Handoff policy:

Keep cadence records, minutes scaffolds, decisions, and follow-up history in Hermes; delegate implementation only from separately accepted action items.

Required inputs:

- cadence or meeting type
- audience or participants
- time window
- source notes or explicit missing-notes boundary

Expected outputs:

- operation artifact
- decision log
- action item history
- observed/prepared boundary

Artifact expectations:

- operation_artifact/v1 under .omh/operations when a wrapper or CLI records it

Safety rules:

- Do not treat a prepared record as proof that the meeting or scrum happened.
- Do not mark decisions or action items accepted without supplied notes or owner acknowledgement.
- Keep implementation follow-ups separate from operating history.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `operating-rhythm`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill operating-rhythm --harness operating-rhythm --status started
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
