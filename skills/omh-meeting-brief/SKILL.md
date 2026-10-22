---
name: "omh-meeting-brief"
description: "[omh] Upcoming work meeting that lacks an agenda: agenda, prompts, decisions, and record template. Use when the user says: meeting-brief, meeting brief, meeting agenda, agenda, discussion prompts, decisions needed, record template, meeting topics."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, meeting]
    category: meeting
    phase: preparation
    role: operator
    quality_tier: facilitation-gated
    related_skills: [meeting-action-items]
---

# Meeting Brief

This is a Hermes-native `meeting-brief` workflow skill.

## Why This Exists

`meeting-brief` exists to turn scattered context into a focused agenda, discussion prompts, decision points, and a record template without pretending the meeting already happened.

## Do Not Use When

- The user needs observed meeting minutes, decisions, or action items but has not provided notes.
- The request is strategy synthesis without a meeting audience, agenda, or decision ceremony.
- The follow-up is implementation work that already has accepted requirements and should become a plan or handoff.
- The meeting already happened, its notes or transcript are in hand, and the user wants decisions, owners, follow-ups, or tickets drawn from them; load Hermes' bundled `meeting-action-items` skill instead of this one.

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

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `model-optimization`, `inference-serving`, `model-finetuning`, `research-brief`, `+26 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

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
- Give the record template's action-item rows outcome, owner, due date, dependency, acceptance condition, and source columns, each marked unknown until the meeting record fills it.

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
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
