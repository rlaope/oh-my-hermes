---
name: "omh-meeting-brief"
description: "[omh] Hermes Meeting Brief workflow: agenda, prompts, decisions, and record template. Use when the user says: meeting-brief, meeting brief, meeting agenda, agenda, discussion prompts, decisions needed, record template, meeting topics."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, meeting]
    category: meeting
    phase: preparation
    role: operator
    quality_tier: facilitation-gated
---

# Meeting Brief

This is a Hermes-native `meeting-brief` workflow skill.

## Why This Exists

`meeting-brief` exists to turn scattered context into a focused agenda, discussion prompts, decision points, and a record template without pretending the meeting already happened.

## Do Not Use When

- The user needs observed meeting minutes, decisions, or action items but has not provided notes.
- The request is strategy synthesis without a meeting audience, agenda, or decision ceremony.
- The follow-up is implementation work that already has accepted requirements and should become a plan or handoff.

## Examples

Good example:

- Prompt: Prepare a meeting agenda for a leadership sync on setup UX, plugin bridge defaults, and release risk.
- Expected behavior: Prepare agenda topics, prompts, decisions needed, and a record template with unknowns marked.
- Why: The request is preparation for a meeting and should separate prep from observed outcomes.

Bad example:

- Prompt: meeting-brief summarize what the team decided yesterday.
- Expected behavior: Ask for meeting notes or route to an ops/status summary with explicit evidence gaps.
- Why: A prepared agenda cannot be treated as observed minutes or decisions.

## Completion Checklist

- The agenda, participants or audience, decisions needed, and record template are named.
- Meeting prep, observed minutes, accepted decisions, and action ownership are separate states.
- Missing context that would change the meeting structure is surfaced.

## Recovery Notes

- If participants, purpose, or decision owner are missing, ask for the one field that changes the agenda.
- If minutes or decisions were not observed, keep the output as prep rather than record.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `best-practice-research`, `autoresearch-goal`, `model-optimization`, `inference-serving`, `+17 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when Hermes should prepare a meeting agenda, discussion prompts, decision points, and a record template.

    Strong routing signals: `meeting-brief`, `meeting brief`, `meeting agenda`, `agenda`, `discussion prompts`, `decisions needed`, `record template`, `meeting topics`, `회의 주제`, `회의 아젠다`, `아젠다`, `회의 준비`, `논의 질문`, `결정할 것`, `기록 템플릿`

## Catalog Metadata

Category: `meeting`
Phase: `preparation`
Hermes role: `operator`
Quality tier: `facilitation-gated`
Reasoning demand: `light`

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

## Runtime Evidence

Preferred harness for this skill: `meeting-facilitation`.

```sh
omh runtime record --skill meeting-brief --harness meeting-facilitation --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
