---
name: "omh-workflow-learning"
description: "[omh] Missed route or run lessons to record: classify and review self-improvement store routes as an auxiliary review lane before durable writes, then record workflow attempts as metadata-only traces, evals, review queues, patch proposals, regression cases, audits, indexes, and exports. Use when the user says: workflow-learning, workflow learning, route-signal, self-improvement store routing, store route review, memory skill wiki routing, learning trace, learning audit."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, optimization]
    category: optimization
    phase: workflow-learning
    role: tracker
    quality_tier: workflow-surface-gated
    related_skills: [omh-memory-new, omh-instinct-ledger, omh-agent-debug]
---

# Workflow Learning

This is a Hermes-native `workflow-learning` workflow skill.

## Why This Exists

`workflow-learning` exists because a lesson from a run can land in the wrong store or in none, and Hermes' own background review can write skills and memory after a turn with no OMH review: it routes each lesson to memory, skill, wiki, failure-retrospective, or automation review as metadata-only records, and checks what Hermes wrote on its own against what was reviewed.

## Do Not Use When

- A lasting fact the user wants kept; capture it with `omh-memory-new`.
- Lessons seen across runs or projects to score and promote; use `omh-instinct-ledger`.
- A run that is stuck or looping right now; use `omh-agent-debug`.

## Examples

Good example:

- Prompt: workflow-learning route this self-improvement note before deciding whether it is memory, skill, wiki, failure-retrospective, or automation material.
- Expected behavior: Produce `record_workflow_learning_trace` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: workflow-learning silently patch the skill and claim future behavior is fixed.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Read Hermes' skill audit ledger read-only (`skills/.curator_ledger.jsonl` under the active profile's Hermes home, or `hermes curator ledger --limit <n>`, which lists only the 20 newest entries by default) and report each entry whose `actor` is `agent` or `curator` (Hermes' curator or its background review) that no store-route record (`omh learning store-routes`) or approved `skill_update_candidate` accounts for as `unreviewed_native_write`, which means OMH holds no record of that write, not that nobody reviewed it. An empty ledger is unknown, not clean, because `skills.ledger: false` turns it off.
- Mark an approved `skill_update_candidate` landed only from a `skill_manage` result for that skill that succeeded without `staged: true`, or from a ledger entry that is dated after the approval, has `actor` `agent` or `user` and `action` `create`, `edit`, `patch`, or `write_file`, and lists the approved target file in its `after` manifest. An entry by `curator`, or one that deletes, archives, rolls back, or purges, never marks it landed, and a staged result waits in `/skills pending` for the person and has not landed.
- The ledger records skill writes only: a memory write by Hermes' background review is visible only when Hermes staged it under `pending/memory/` with `origin: background_review`, and is `not_observed` otherwise.
- Point the user to `/journey` in the Hermes CLI for Hermes' own view of what it learned; reading the ledger or the journey changes nothing, and undoing an entry (`hermes curator rollback <id>`) is the person's own step, never OMH's.

## Recovery Notes

- If required context is missing, ask one blocking question or route back to the narrower workflow.
- If runtime or wrapper evidence is unavailable, keep the status as not_observed and expose the next observable action.
- Native write policy `required` stops promotion as unsupported and `not_required` is not an approval; drift unlinks only the managed SKILL.md and keeps generations and receipts, and an incomplete promotion resumes only via explicit `retry --receipt-id`.

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+40 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use after a Hermes/OMH workflow attempt should become inspectable, evaluable, routed to memory/skill/wiki/failure-retrospective/automation review, persisted as a metadata-only store-route decision, queued for review, audited, replayable as a regression, converted to a patch handoff, exported, repaired after index drift, or captured as a missed-route signal without raw prompts. Store-route records are an auxiliary review lane surfaced by `learning review` and `learning store-routes`; they are not canonical learning index/export records until a reviewed destination produces its own artifact.

    Strong routing signals: `workflow-learning`, `workflow learning`, `route-signal`, `self-improvement store routing`, `store route review`, `memory skill wiki routing`, `learning trace`, `learning audit`, `self improvement store routing`, `store routing`, `where should this learning go`, `audit learning`, `learning review`, `review queue`, `review-route`, `store-routes`, `learning readiness`, `learning export`, `export bundle`, `learning index`, `index rebuild`, `execution trace`, `skill improvement`, `improvement candidate`, `regression corpus`, `GEPA`, `VPRM`, `process supervision`, `why did this route`, `missed route`, `missed workflow`, `did not use OMH`, `OMH was not used`, `learn from this run`, `이번 실행 학습`, `스킬 개선`, `회귀 케이스`, `실행 기록`, `학습 기록`, `학습 점검`, `학습 준비 상태`, `학습 내보내기`, `OMH 안 썼어`, `워크플로 누락`, `라우팅 누락`

## Catalog Metadata

Category: `optimization`
Phase: `workflow-learning`
Hermes role: `tracker`
Quality tier: `workflow-surface-gated`
Reasoning demand: `heavy`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- workflow-learning/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- workflow-learning/v1 metadata-only runtime or wrapper card when recorded
- browser_skill_promotion_approval_receipt/v1 per operation: `promotion diff` then `approve --reviewed-diff-digest --reviewer`; source `learning promotion --source-id sd-<id>` (reviewed draft) or `web-qa promotion --trace-id bwt-<id>`

Safety rules:

- A workflow learning trace, self-improvement store route, patch proposal, or export is process evidence for review. It is not automatic model training, memory mutation, skill mutation, wiki write, automation creation, execution, verification, CI, or merge evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `workflow-learning`.

```sh
omh runtime record --skill workflow-learning --harness workflow-learning --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
