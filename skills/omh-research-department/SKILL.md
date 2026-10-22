---
name: "omh-research-department"
description: "[omh] Recurring market or topic research: research operations department - coordinate Scout, Analyst, and Briefer work with source-inbox and status boundaries; for one decision brief use research-brief, and for typed candidates before research starts use source-finder. Use when the user says: research-department, research department, research ops department, research operations department, scout analyst briefer, scout analyst brief, daily research department, competitor research department."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: research-department
    role: researcher
    quality_tier: research-ops-gated
    related_skills: [ulw-research, omh-research-brief, omh-automation-blueprint, competitor-news-monitor, arxiv]
---

# Research Department

This is a Hermes-native `research-department` workflow skill.

## Why This Exists

`research-department` exists so Hermes users can start complex research-ops patterns without manually designing profiles, cron, knowledge storage, synthesis tooling, and delivery glue, while OMH keeps every runtime claim observed-only.

## Do Not Use When

- The user only needs a one-off current-source lookup; use `ulw-research`.
- The user only needs a one-off business synthesis; use `omh-research-brief`.
- The request is pure scheduling with no source collection or synthesis; use `omh-automation-blueprint`.
- The user asks for coding implementation; prepare a selected executor/runtime handoff after the research plan is accepted.
- The request is one news watch over named companies, or a scheduled run of a watch that already exists, with no knowledge store, synthesis tool, or briefing lanes to set up, and Hermes' bundled `competitor-news-monitor` skill is available; load that skill.
- The user wants a one-off paper search by topic, author, category, or paper id rather than a recurring paper review, and Hermes' bundled `arxiv` skill is available; load that skill.

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

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `model-optimization`, `inference-serving`, `model-finetuning`, `research-brief`, `+26 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

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
- Inside the Scout lane, when the watch area is a set of named companies and Hermes' bundled `competitor-news-monitor` skill is available, run the watch through that skill; when the user names no knowledge store and the bundled `llm-wiki` skill is available, offer it as the store.
- A schedule stays a prepared job description in the plan and OMH creates no job. In a Hermes session the job is created with the `cronjob_manage` tool, and it counts as created only from that tool's observed result or a cron listing.
- For a recurring watch, write the watchlist and the materiality threshold down once, before the first run, and reuse them unchanged: what is watched and what is worth reporting change only by a recorded edit, so one candidate is accepted or rejected the same way on every run.
- Report coverage source by source on every run. A source the run could not read is unknown coverage for that period and is named as a gap; it is never reported as a quiet period or as nothing new.
- Keep one cutoff per source and move it only for a source the run covered. A source that failed keeps its earlier cutoff, so the next run reads the missed window instead of skipping it.
- Count by the underlying event, not by article or URL: reprints, rewrites, and link variants of one announcement are one finding, and an independent second source stays attached to it as corroboration.
- For market watches, keep a dated competitor/pricing snapshot per covered entity with source IDs, observation/effective dates, original packaging and normalized comparison units. Reuse a stable period, currency, units, source cutoff, and materiality threshold; record scope changes and distinguish a real change from changed source coverage.
- Classify market findings as observed, vendor-asserted, or inferred and preserve contrary evidence. When coverage fails, retain the failed source's previous cutoff and name the uncovered window; do not turn a failed read into unchanged pricing or no new activity.
- When a material event needs sizing, customer/JTBD, or comparable pricing work, hand the bounded analysis to `market-research` with snapshot IDs, source dates, cutoff, gaps and budget; return findings to `research-brief` before Briefer delivery. A prepared handoff does not prove any analysis ran.
- Outreach, paid sources, and schedule creation require separate explicit approval; research-operation setup is not permission to contact customers, buy data, schedule a watch, or approve a product investment.

Handoff policy:

Keep the research operating model in Hermes. Map Scout to `ulw-research`/`omh-web-research`, Analyst to `omh-research-brief`/`omh-web-research`, and Briefer to `omh-report-package` or meeting/report workflows. Record retrieval, synthesis-tool output, knowledge-store writes, delivery, and verification only from observed evidence.

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
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
