---
name: "omh-operating-rhythm"
description: "[omh] Team minutes, retros, and decision history to keep: meeting minutes, scrum/sprint records, retros, decisions, and follow-up history. Use when the user says: operating-rhythm, operating rhythm, meeting minutes, meeting history, scrum record, sprint planning, sprint review, sprint retrospective."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: rhythm-history
    role: operator
    quality_tier: operations-gated
---

# Operating Rhythm

This is an OMH `operating-rhythm` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`operating-rhythm` exists so recurring operating work has durable minutes, decisions, and follow-up history without pretending a meeting outcome was observed.

## Do Not Use When

- The user only needs a one-off meeting agenda before the meeting; use `omh-meeting-brief`.
- The request is a weekly status/risk summary rather than cadence history; use `omh-ops-review`.
- Report packaging or reliability evidence review; use `omh-report-package` or `omh-reliability-review`.

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

- Each decision names who decided and its source; an undecided proposal stays out of the log.
- Each action item has outcome, owner, due date and source, unknown where the notes are silent; last meeting's actions carry their status.

## Recovery Notes

- If source notes are missing, retain the cadence, audience, and time-window scaffold, mark minutes and decisions not_observed, and hand back operation_artifact/v1 with the explicit missing-notes boundary.
- If notes leave an action item's owner or due date unstated, retain its source-linked outcome and dependencies, mark follow-up readiness unresolved, and hand back the action item history with unknown fields for confirmation.
- If a retro proposal has no decision or owner acknowledgement, retain the source notes, mark acceptance unresolved, and hand back the proposal outside the decision log for explicit confirmation before an implementation handoff.



## When to Use

Use when Hermes should prepare or maintain recurring operating records such as meetings, scrums, sprint plans, retrospectives, decisions, and follow-ups.

    Strong routing signals: `operating-rhythm`, `operating rhythm`, `meeting minutes`, `meeting history`, `scrum record`, `sprint planning`, `sprint review`, `sprint retrospective`, `retro history`, `decision log`, `action item history`, `회의록 관리`, `회의 히스토리`, `운영 리듬`, `스크럼`, `스프린트 회고`, `결정 기록`, `액션 아이템`

## Catalog Metadata

Category: `operations`
Phase: `rhythm-history`
Quality tier: `operations-gated`
Reasoning demand: `light`

Quality bar:

- Name cadence, audience, time window, known notes, and missing evidence before producing a record.
- Separate agenda/templates from observed minutes, decisions, and action items.
- Record follow-up ownership only when supplied or explicitly mark it unknown.
- Record each action item with its outcome, owner, due date, dependency, acceptance condition, and source reference, marking an owner or date the notes do not state as unknown, and keep a proposal that was discussed but not decided out of the decision log.
- On Hermes, when the bundled `meeting-action-items` skill is available, it may pull decisions, owners, and actions out of the supplied notes; its list is a reading of those notes, so every item keeps its source reference and stays unaccepted until the notes or the owner confirm it, and a ticket or message it drafts is reported as published only after the user approved it and it was read back.

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
