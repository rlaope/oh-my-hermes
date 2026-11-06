---
name: "omh-running-work-board"
description: "[omh] Live view of running coding units: showing which coding units are running right now, on which runtime and model, with observed tokens and elapsed time. Use when the user says: running-work-board, running work board, which units are running, what models are running, 지금 뭐 돌고 있어, 뭐가 돌고 있어, 어떤 모델로 돌고 있어, 실행 중인 작업 보여줘."
license: MIT
compatibility: "Requires the omh CLI on PATH (pip install oh-my-hermes)."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operator]
    category: operator
    phase: observability
    role: tracker
    quality_tier: evidence-gated
---

# Running Work Board

This is an OMH `running-work-board` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`running-work-board` exists because multi-session coding work was invisible: the runtime was tracked but the model was dropped, token counts had no write site at all, and a blocking dispatch could not report that it was still running. The board answers which model on which runtime, or says unknown.

## Do Not Use When

- The user wants to start, plan, or dispatch coding work rather than observe it.
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



## When to Use

Use when the user asks what coding work is running right now -- which unit, which runtime, which model, how long, how many tokens -- rather than asking to start, plan, or review work.

    Strong routing signals: `running-work-board`, `running work board`, `which units are running`, `what models are running`, `지금 뭐 돌고 있어`, `뭐가 돌고 있어`, `어떤 모델로 돌고 있어`, `실행 중인 작업 보여줘`, `что делают агенты`, `покажи что запущено`, `чем заняты агенты`, `что запущено сейчас`

## Catalog Metadata

Category: `operator`
Phase: `observability`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- Name the workflow target, constraints, validation evidence, and stop condition.
- Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.

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

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
