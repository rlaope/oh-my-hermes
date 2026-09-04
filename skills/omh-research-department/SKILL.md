---
name: "omh-research-department"
description: "[omh] Research operations department - coordinate Scout, Analyst, and Briefer work with source-inbox and status boundaries; for one decision brief use research-brief, and for typed candidates before research starts use source-finder. Use when the user says: research-department, research department, research ops department, research operations department, scout analyst briefer, scout analyst brief, daily research department, competitor research department."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: research-department
    role: researcher
    quality_tier: research-ops-gated
---

# Research Department

This is a Hermes-native `research-department` workflow skill.

## Why This Exists

`research-department` exists so Hermes users can start complex research-ops patterns without manually designing profiles, cron, knowledge storage, synthesis tooling, and delivery glue, while OMH keeps every runtime claim observed-only.

## Do Not Use When

- The user only needs a one-off current-source lookup; use `research`.
- The user only needs a one-off business synthesis; use `research-brief`.
- The request is pure scheduling with no source collection or synthesis; use `automation-blueprint`.
- The user asks for coding implementation; prepare a selected executor/runtime handoff after the research plan is accepted.

## Examples

Good example:

- Prompt: Set up a Scout, Analyst, and Briefer research flow for daily competitor and market changes.
- Expected behavior: Prepare research_department_plan/v1 with Scout/Analyst/Briefer lanes, source inbox buckets, briefing status, knowledge-store and synthesis-tool readiness, and observed-only evidence requirements.
- Why: The request is recurring, source-backed, and operational; a single research brief would miss the ongoing workflow/status boundary.

Bad example:

- Prompt: research-department prove the synthesis tool queried the knowledge base and posted the Slack brief.
- Expected behavior: Ask for observed synthesis-tool and gateway delivery evidence or mark those states as not_observed.
- Why: The workflow pack can prepare the operating pattern, but it cannot prove external tool execution or delivery.

## Completion Checklist

- The research question, source boundaries, recency assumptions, and confidence level are named.
- Observed sources, inference, synthesis, and unresolved retrieval gaps are separated.
- Follow-up planning or handoff uses the research summary without calling it execution evidence.

## Recovery Notes

- If sources cannot be accessed, state the retrieval gap and use only observed local context.
- If evidence is thin or one-sided, lower confidence and ask for a narrower source boundary.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `best-practice-research`, `autoresearch-goal`, `model-optimization`, `inference-serving`, `+17 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when Hermes should turn an ongoing or recurring research request into a prepared Scout -> Analyst -> Briefer workflow with source inbox, knowledge-store and synthesis-tool readiness, and briefing status without claiming research execution.

    Strong routing signals: `research-department`, `research department`, `research ops department`, `research operations department`, `scout analyst briefer`, `scout analyst brief`, `daily research department`, `competitor research department`, `market research department`, `paper review`, `weekly paper review`, `research paper review`, `paper research`, `notebooklm research`, `obsidian research vault`, `knowledge store`, `knowledge storage`, `synthesis tool`, `knowledge summarizer`, `research inbox`, `source inbox`, `briefing status`, `리서치 부서`, `리서치 조직`, `리서치 운영`, `수집 합성 브리핑`, `지식 저장소`, `요약 도구`, `경쟁사 리서치 부서`

## Catalog Metadata

Category: `research`
Phase: `research-department`
Hermes role: `researcher`
Quality tier: `research-ops-gated`
Reasoning demand: `standard`

Quality bar:

- Name topic, source boundaries, cadence, delivery target, knowledge-store destination, and synthesis-tool readiness.
- Map Scout, Analyst, and Briefer lanes to concrete OMH skills and source inbox buckets.
- Expose collected, synthesized, briefed, conflict, and verification counts as status, not execution proof.
- List required evidence before claiming retrieval, synthesis, storage, delivery, or verification.

Handoff policy:

Keep the research operating model in Hermes. Map Scout to `research`/`autoresearch-goal`, Analyst to `research-brief`/`best-practice-research`, and Briefer to `report-package` or meeting/report workflows. Record retrieval, synthesis-tool output, knowledge-store writes, delivery, and verification only from observed evidence.

Required inputs:

- topic or watch area
- source boundaries
- cadence
- delivery target
- knowledge-store preference
- synthesis-tool preference

Expected outputs:

- research_department_plan/v1
- source_inbox/v1
- briefing_status/v1
- not-evidence boundary

Artifact expectations:

- research_department_plan/v1 under .omh/research-department/plans when a wrapper or CLI records it

Safety rules:

- Do not claim web retrieval, synthesis-tool query, knowledge-store write, cron creation, gateway delivery, or verification from a prepared plan.
- Keep raw findings, processed notes, briefs, conflicts, and verification needs in separate source inbox buckets.
- Treat vendor-specific tool names as optional aliases for synthesis-tool and knowledge-store readiness unless observed evidence exists.

## Runtime Evidence

Preferred harness for this skill: `research-department`.

```sh
omh runtime record --skill research-department --harness research-department --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
