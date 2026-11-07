---
name: "omh-data-analysis"
description: "[omh] Dataset or table to analyze: scope supplied data with provenance, causal-claim, and hallucination guards. Use when the user says: data-analysis, data analysis, dataset analysis, csv analysis, json analysis, log analysis, table analysis, analyze csv."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, analysis]
    category: analysis
    phase: data-task
    role: guide
    quality_tier: workflow-surface-gated
    related_skills: [omh-geospatial-analysis, omh-finance-analysis, omh-materials-package]
---

# Data Analysis

This is a Hermes-native `data-analysis` workflow skill.

## Why This Exists

`data-analysis` exists because a model that reads a table by eye returns means, trends and anomalies that look observed and are wrong, and a gap between two groups reads as a finding with no test, sample size or interval: every number here comes from a command output that can be named, and every comparison carries its evidence.

## Do Not Use When

- Polygon overlay and area computation from supplied layers; use `omh-geospatial-analysis`.
- Budget variance, cash or close analysis with accounting periods and controls; use `omh-finance-analysis`.
- The table must become a deck, workbook or exported report; use `omh-materials-package` after the analysis scope is clear.

## Examples

Good example:

- Prompt: data-analysis analyze this CSV and summarize anomalies by segment.
- Expected behavior: Produce `prepare_data_analysis_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: data-analysis is the Q3 lift significant? (two columns of five numbers each)
- Expected behavior: Compute the comparison with code and report n per group, the effect size and an interval or test with its assumptions, flagging that five per group makes the result fragile, instead of calling the gap significant or refusing for lack of data.
- Why: The data was supplied; the failure is a comparison reported without n, an effect size or an interval.

## Completion Checklist

- Dataset or corpus source, record scope, schema or extraction method, join assumptions, analysis question, method, and stop condition are explicit.
- The data was loaded with code (pandas, SQL or a spreadsheet tool) and shape, dtypes, null counts, duplicate rows and the min and max of key columns were printed before any claim; every number in the answer comes from a command output you can name. With no code tool, say so and analyse only what fits in context, labelled as read by eye.
- Numeric claims, anomalies, trends, segments, and log patterns are reported only from observed data or supplied evidence.
- Every comparison states n per group, the effect size and an interval or test (named, with its assumptions); the answer says how many segments were looked at, and the headline is checked against its major subgroups.
- Causal claims require observed identification evidence: a randomized or explicitly identified design. Otherwise report association as association.
- Source acquisition, file conversion, report generation, and code fixes are routed to the narrower workflow when stronger.

## Recovery Notes

- If the data itself is missing, ask for the smallest dataset sample, schema, or query output needed.
- If the user wants datasets found online, route to `omh-source-finder` before analysis.
- If the user wants a PPT/PDF/XLSX report generated from data, route to `omh-materials-package` or `omh-deliverable-package` after analysis scope is clear.

## Workflow Lane

- Current lane: **Research and company ops** - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should prepare supplied structured, unstructured, or mixed data analysis without unsupported numeric or causal claims.

    Strong routing signals: `data-analysis`, `data analysis`, `dataset analysis`, `csv analysis`, `json analysis`, `log analysis`, `table analysis`, `analyze csv`, `analyze this csv`, `analyze json`, `analyze logs`, `summarize anomalies`, `anomaly analysis`, `trend analysis`, `segment analysis`, `column analysis`, `schema check`, `table to chart`, `chart with an executive summary`, `spreadsheet delta analysis`, `cohort analysis`, `retention analysis`, `correlation analysis`, `causal analysis`, `causality check`, `데이터 분석`, `csv 분석`, `json 분석`, `로그 분석`, `이상치 분석`, `추세 분석`, `오류 패턴`, `컬럼 분석`, `전환율 델타`, `차트 요약`, `상관관계 분석`, `인과 분석`, `인과관계`, `проанализируй данные`, `анализ логов`, `разбери логи`, `анализ таблицы`, `посчитай метрики`, `проанализируй csv`, `анализ данных`

## Catalog Metadata

Category: `analysis`
Phase: `data-task`
Hermes role: `guide`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

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

- data_analysis_task_card/v1
- dataset_scope/v1
- analysis_method_plan/v1
- operations_data_harness/v1
- product_evidence_loop/v1
- analysis_result_summary/v1 when observed
- next action
- prepared-vs-observed boundary

Artifact expectations:

- data_analysis_task_card/v1 metadata-only wrapper card when prepared
- dataset_scope/v1 with source, row/record scope, columns or schema, filters, and stop condition
- analysis_method_plan/v1 naming summary, anomaly, trend, segment, schema, or log-pattern methods
- operations_data_harness/v1 for relationship and causal boundaries
- product_evidence_loop/v1 for prepared opaque data reference metadata
- analysis_result_summary/v1 only from observed data, calculations, query output, or supplied evidence

Safety rules:

- A data analysis card is not file extraction, query execution, chart generation, statistical proof, data correctness, hallucination-safe numeric evidence, association, or causality unless observed data and method evidence records it.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `data-analysis`.

```sh
omh runtime record --skill data-analysis --harness data-analysis --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
