---
name: "omh-running-work-board"
description: "[omh] Live view of running coding units: showing which coding units are running right now, on which runtime and model, with observed tokens and elapsed time. Use when the user says: running-work-board, running work board, which units are running, what models are running, 지금 뭐 돌고 있어, 뭐가 돌고 있어, 어떤 모델로 돌고 있어, 실행 중인 작업 보여줘."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operator]
    category: operator
    phase: observability
    role: tracker
    quality_tier: evidence-gated
    related_skills: [omh-agent-board]
---

# Running Work Board

This is a Hermes-native `running-work-board` workflow skill.

## Why This Exists

`running-work-board` exists because multi-session coding work was invisible: the runtime was tracked but the model was dropped, token counts had no write site at all, and a blocking dispatch could not report that it was still running. The board answers which model on which runtime, or says unknown.

## Do Not Use When

- The user wants to start, plan, or dispatch coding work rather than observe it.
- The user wants to create or change tasks on an agent board, or to coordinate profiles; use `omh-agent-board`.
- The user wants review, CI, or merge evidence, which a status board never provides.
- The user is asking about their own application's runtime status rather than OMH coding units.

## Examples

Good example:

- Prompt: what is running right now
- Expected behavior: One line per unit: label, runtime, model, status, elapsed, tokens, with unknown printed where nothing was observed.
- Why: The request is about observed local coding activity, not about starting work.

Bad example:

- Prompt: is the deploy done and did CI pass
- Expected behavior: Route to verification or CI evidence instead of the activity board.
- Why: Observed activity is not result, review, CI, or merge evidence.

## Completion Checklist

- The board is rendered with `omh coding status-board --json` (read-only: local dispatch and progress artifacts; on Hermes it also reads delegate children and workers from Hermes' own records), not recalled.
- Runtime and model are named per unit, or explicitly reported as unknown.
- Token counts and session references are observed values or the literal unknown, never estimates.
- Elapsed time for an unfinished unit comes from its start marker, which cannot prove the unit is still alive.
- The board is labelled observed activity, not result, verification, review, CI, or merge evidence.
- On Hermes, `delegate_task` children and kanban workers of this conversation come from `omh_hud` (its `subagents` rows and `kanban` block, read from Hermes' own records) beside the OMH units, each labelled by source; `/agents` is the person's own Hermes list of running agents and tasks in Hermes' own terminal; the OMH TUI refuses `/agents`, and its agent list (Down on an empty composer while subagents show) shows the subagents of the running turn.

## Recovery Notes

- If no units are found, say so plainly rather than implying nothing ever ran.
- If `omh_hud` is not available, say delegate children and kanban workers were not read rather than implying none are running.
- If a marker is stale because a process died, report it as observed-start-without-end instead of claiming the unit is running.
- If tokens are unknown for a runtime with no structured output, say the runtime does not report them.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when the user asks what coding work is running right now -- which unit, which runtime, which model, how long, how many tokens -- rather than asking to start, plan, or review work.

    Strong routing signals: `running-work-board`, `running work board`, `which units are running`, `what models are running`, `지금 뭐 돌고 있어`, `뭐가 돌고 있어`, `어떤 모델로 돌고 있어`, `실행 중인 작업 보여줘`, `что делают агенты`, `покажи что запущено`, `чем заняты агенты`, `что запущено сейчас`

## Catalog Metadata

Category: `operator`
Phase: `observability`
Hermes role: `tracker`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- Name the workflow target, constraints, validation evidence, and stop condition.
- Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.

Handoff policy:

Read local dispatch and progress artifacts and, on Hermes, `omh_hud`'s delegate and kanban rows, and render the board; never dispatch, stop, or modify a unit from this workflow.

Required inputs:

- local coding artifacts
- on Hermes, this conversation's `omh_hud` rows

Expected outputs:

- per-unit runtime and model
- observed tokens and elapsed
- on Hermes, delegate children and kanban workers, labelled by source
- explicit unknowns

Artifact expectations:

- metadata-only status board projection from local artifacts

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. Finished work ends with no question and no offer; when a decision only the user can make remains, end with one specific question about that decision, not a list of questions, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
