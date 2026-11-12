---
name: "omh-data-analysis"
description: "[omh] Dataset or table to analyze: scope supplied data with provenance, causal-claim, and hallucination guards."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, analysis]
    category: analysis
    phase: data-task
    role: guide
    quality_tier: workflow-surface-gated
---

# Data Analysis

This is an OMH `data-analysis` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

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



## When to Use

Use when Hermes should prepare supplied structured, unstructured, or mixed data analysis without unsupported numeric or causal claims.

    Strong routing signals: `data-analysis`, `data analysis`, `dataset analysis`, `csv analysis`, `json analysis`, `log analysis`, `table analysis`, `analyze csv`, `analyze this csv`, `analyze json`, `analyze logs`, `summarize anomalies`, `anomaly analysis`, `trend analysis`, `segment analysis`, `column analysis`, `schema check`, `table to chart`, `chart with an executive summary`, `spreadsheet delta analysis`, `cohort analysis`, `retention analysis`, `correlation analysis`, `causal analysis`, `causality check`, `데이터 분석`, `csv 분석`, `json 분석`, `로그 분석`, `이상치 분석`, `추세 분석`, `오류 패턴`, `컬럼 분석`, `전환율 델타`, `차트 요약`, `상관관계 분석`, `인과 분석`, `인과관계`, `проанализируй данные`, `анализ логов`, `разбери логи`, `анализ таблицы`, `посчитай метрики`, `проанализируй csv`, `анализ данных`

## Catalog Metadata

Category: `analysis`
Phase: `data-task`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

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
