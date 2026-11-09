---
name: "omh-agent-ops-review"
description: "[omh] AI agent progress for managers: help managers inspect AI-agent progress, blockers, quality gates, and throughput levers. Use when the user says: agent-ops-review, agent ops review, tracing audit, telemetry audit, instrumentation audit, agent productivity, operator productivity, manager view."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operator]
    category: operator
    phase: manager-review
    role: tracker
    quality_tier: workflow-surface-gated
---

# Agent Ops Review

This is a Hermes-native `agent-ops-review` workflow skill.

## Why This Exists

`agent-ops-review` exists so Hermes users can ask for this workflow in chat and get a structured, checkable answer instead of an improvised one.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: agent-ops-review show quality, blockers, and throughput for AI-agent work.
- Expected behavior: Produce `prepare_agent_ops_review` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: agent-ops-review claim Codex finished and CI passed because a handoff exists.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Each run is listed as prepared, observed, or not_observed, with the evidence behind observed.
- Blockers and failed quality gates carry an owner or next action.
- Throughput claims cite a measurement or say none exists.
- An instrumentation audit gives every ladder row PASS, FAIL, or PARTIAL with its location.

## Recovery Notes

- If only a prepared handoff exists, mark coding progress not_observed; hand back the missing stage.
- If P0 capture fails its audit, keep the tier checks, mark readiness unresolved; hand back quick wins.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should explain AI-agent work: quality gates, progress, blockers, next actions, and throughput.

    Strong routing signals: `agent-ops-review`, `agent ops review`, `tracing audit`, `telemetry audit`, `instrumentation audit`, `agent productivity`, `operator productivity`, `manager view`, `quality dashboard`, `throughput review`, `agent work quality`, `coding progress quality`, `coding progress`, `where is codex`, `what's going on`, `status update please`, `what are you doing`, `what are you working on`, `where are we`, `今何してる`, `现在在做什么`, `qué está pasando`, `qu'est-ce qui se passe`, `was ist los`, `ai agent manager`, `관리자 입장`, `Codex 작업`, `Codex 작업이 어디까지`, `코덱스 작업`, `작업이 어디까지`, `진행됐는지`, `진행되었는지`, `처리량`, `작업 품질`, `진행상황`, `무슨일이노`, `뭔일임`, `무슨 일이야`, `뭐해`, `지금 뭐 하고 있어`, `작업상황 브리핑`, `어디까지 됐어`, `리서치 코딩 리뷰`, `что сделали агенты`, `прогресс агентов`, `как там делегированное`, `статус работы агентов`

## Catalog Metadata

Category: `operator`
Phase: `manager-review`
Hermes role: `tracker`
Quality tier: `workflow-surface-gated`
Reasoning demand: `light`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.
- For instrumentation-audit requests, grade against the tier ladder in `omh-agent-ops-review/references/instrumentation-ladder.md`: T0 foundation through T5 advanced, with every verdict PASS, FAIL, or PARTIAL and a file or config location attached.
- Audit coverage in priority order - P0 (telemetry init, LLM-call capture, tool-call capture, error capture) before P1 (tokens, cost attribution, agent identity, multi-agent links) before P2 (memory/RAG spans, human-in-the-loop, evaluation runs) - and rank remediation as quick win (under an hour), medium, or larger.
- Check the audited setup against the anti-pattern checklist in the same reference; an anti-pattern hit is a finding with its location and fix, never a style remark.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- agent-ops-review/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- agent-ops-review/v1 metadata-only runtime or wrapper card when recorded

Artifact contracts:

This label denotes the machine-enforcement level, not a skill quality score and not an observed evidence state.

- contract_id: `agent_operator_productivity/v1`; enforcement_level: `executable_validated`; consumer_id: `validate_agent_operator_productivity_card`

Safety rules:

- An agent ops review card is not source retrieval, executor dispatch, coding progress, implementation, review, verification, CI, merge, platform delivery, provider billing, or live runtime telemetry evidence. If Hermes is the coding owner, summarize `hermes_coding_harness/v1` stage, lane owner, next action, and missing evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `agent-ops-review`.

```sh
omh runtime record --skill agent-ops-review --harness agent-ops-review --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
