---
name: "omh-research-brief"
description: "[omh] Business research brief - turns a market, competitor, pricing, or customer question into a structured evidence-vs-inference brief; for raw link gathering use ulw-research, and for ongoing multi-role research use research-department. Use when the user says: research-brief, business-research, business research, research brief, decision brief, pricing decision brief, decision-ready brief, source-backed business research."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: business-brief
    role: researcher
    quality_tier: source-gated
---

# Research Brief

This is a Hermes-native `research-brief` workflow skill.

## Why This Exists

`research-brief` exists to keep `research` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The request is only fresh links, citations, or current facts without a business question or decision audience; use `research`.
- Sources have not yet been selected and the user wants source types, candidates, or acquisition state; use `source-finder`.

## Examples

Good example:

- Prompt: research-brief: compare three onboarding analytics vendors using customer notes and confidence gaps.
- Expected behavior: Prepare a source-backed brief with evidence, inference, confidence, and retrieval gaps separated.
- Why: The user needs business research synthesis, not recurring operations or coding.

Bad example:

- Prompt: research-brief: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `research-brief`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

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

Use when Hermes should scope a business question, gather or summarize source-backed evidence, and preserve evidence/inference boundaries before strategy or handoff.

    Strong routing signals: `research-brief`, `business-research`, `business research`, `research brief`, `decision brief`, `pricing decision brief`, `decision-ready brief`, `source-backed business research`, `customer feedback trends`, `feedback trends`, `market evidence`, `data search`, `source scan`, `자료 조사`, `데이터 서치`, `근거 조사`, `피드백 추세`, `고객 피드백 추세`

## Catalog Metadata

Category: `research`
Phase: `business-brief`
Hermes role: `researcher`
Quality tier: `source-gated`
Reasoning demand: `standard`

Quality bar:

- State the research question, source boundaries, and recency assumptions before synthesis.
- Record each material claim as a compact evidence row: claim, source, source class (upstream official, practitioner heuristic, or unattributed), source date, confidence, and unresolved conflict.
- Keep claims that lack corroboration in an explicit unresolved list instead of asserting or silently dropping them.
- Separate observed sources, source quality, source diversity, inferred trends, and unresolved uncertainty.
- Use the brief to feed strategy or meeting work without calling it execution evidence.

Handoff policy:

Keep business research in Hermes; prepare a selected executor/runtime handoff only after a later accepted plan requires code changes.

Required inputs:

- business question
- source boundary
- recency or market scope

Expected outputs:

- evidence table
- inference summary
- confidence and uncertainty

Artifact expectations:

- research brief or source ledger when the wrapper captures observed sources

Safety rules:

- Do not claim sources were fetched unless Hermes or the wrapper observed them.
- Separate evidence, inference, confidence, source diversity, and missing-source gaps.
- Route later implementation separately through an accepted plan and coding handoff.

## Runtime Evidence

Preferred harness for this skill: `business-research`.

```sh
omh runtime record --skill research-brief --harness business-research --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
