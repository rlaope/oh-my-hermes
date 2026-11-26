# Web Research

Load this on-demand contract after the compact `web-research` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The decision needs reference-implementation study, a declared depth budget, or a decision-grounding dossier; use `ulw-research`.
- The output is a typed candidate inventory and acquisition status rather than an answer; use `omh-source-finder`.
- The ask is a market, competitor, pricing, or customer decision brief; use `omh-research-brief`.
- Market sizing, a customer-evidence matrix, or a competitor or pricing profile is the deliverable; use `omh-market-research`.
- The user wants recurring monitoring, a source inbox, or Scout/Analyst/Briefer operations; use `omh-research-department`.
- The user wants to configure or cheapen web search itself, such as a provider API key or a search or extract backend or tier; use `omh-websearch-setup`.
- The study target is this repository rather than the open web; use `omh-codebase-onboarding`.
- The request is only citation bookkeeping on a draft that already exists - renumbering, rebuilding the Sources block, or checking cited ids against the ledger - with nothing new to retrieve, and Hermes' bundled `grounded-citations` skill is available; load that skill.
- The answer is an arXiv paper list or one paper's entry - a search by topic, author, category, or paper id - and Hermes' bundled `arxiv` skill is available; load that skill.
- The task is solely recovering one blocked URL (HTTP 403, HTTP 429, paywall, or WAF wall) with no broader multi-source research question; load Hermes' bundled `blocked-page-recovery` skill instead of this one.

## Examples

Good example:

- Prompt: 이번 주 기준으로 그 API 요금제 어떻게 바뀌었는지 웹서치해서 알려줘.
- Expected behavior: Retrieve current pricing from the vendor's own page, cite it with the retrieval date, and name what the page does not state.
- Why: A current-facts question that one cited retrieval round settles.

Bad example:

- Prompt: 스펙 잡기 전에 오픈소스 구현들 깊게 보고 근거 만들어줘.
- Expected behavior: Route to `ulw-research`, which declares a depth budget and studies reference implementations with pinned refs.
- Why: Pre-spec grounding needs the engine's dossier rather than a single lookup.

## Full Input, Output, and Artifact Expectations

Required inputs:

- question
- freshness or version constraints
- source boundaries when the topic is contested
- requested as-of date or interval when the question is point-in-time

Expected outputs:

- cited answer
- retrieval date per time-sensitive fact
- source-quality notes
- named retrieval gaps
- web_research_brief/v1
- temporal_source_receipt/v1 per historical claim and temporal_evidence_surfaces/v1 when the question is point-in-time

Artifact expectations:

- research notes with source URLs and retrieval dates when the wrapper captures them
