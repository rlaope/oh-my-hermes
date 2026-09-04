---
name: "omh-operating-rhythm"
description: "[omh] Hermes Operating Rhythm workflow: meeting minutes, scrum/sprint records, retros, decisions, and follow-up history. Use when the user says: operating-rhythm, operating rhythm, meeting minutes, meeting history, scrum record, sprint planning, sprint review, sprint retrospective."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: rhythm-history
    role: operator
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

## Completion Checklist

- Confirm the workflow target, evidence boundary, and stop condition are named.
- Report which outputs are prepared, observed, blocked, or missing.
- Name the smallest next verification or handoff instead of claiming completion from narration.

## Recovery Notes

- If required context is missing, ask one blocking question or route back to the narrower workflow.
- If runtime or wrapper evidence is unavailable, keep the status as not_observed and expose the next observable action.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `best-practice-research`, `autoresearch-goal`, `model-optimization`, `inference-serving`, `+17 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when Hermes should prepare or maintain recurring operating records such as meetings, scrums, sprint plans, retrospectives, decisions, and follow-ups.

    Strong routing signals: `operating-rhythm`, `operating rhythm`, `meeting minutes`, `meeting history`, `scrum record`, `sprint planning`, `sprint review`, `sprint retrospective`, `retro history`, `decision log`, `action item history`, `회의록 관리`, `회의 히스토리`, `운영 리듬`, `스크럼`, `스프린트 회고`, `결정 기록`, `액션 아이템`

## Catalog Metadata

Category: `operations`
Phase: `rhythm-history`
Hermes role: `operator`
Quality tier: `operations-gated`
Reasoning demand: `light`

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

## Runtime Evidence

Preferred harness for this skill: `operating-rhythm`.

```sh
omh runtime record --skill operating-rhythm --harness operating-rhythm --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
