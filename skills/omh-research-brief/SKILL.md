---
name: "omh-research-brief"
description: "[omh] Business question on market, competitors, pricing: business research brief - turns a market, competitor, pricing, or customer question into a structured evidence-vs-inference brief. Use when the user says: research-brief, business-research, business research, research brief, decision brief, pricing decision brief, decision-ready brief, source-backed business research."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: business-brief
    role: researcher
    quality_tier: source-gated
    related_skills: [omh-product-discovery-validation, omh-web-research, ulw-research, omh-source-finder, omh-market-research, omh-research-department]
---

# Research Brief

This is a Hermes-native `research-brief` workflow skill.

## Why This Exists

`research-brief` exists because a decision brief goes wrong when a vendor claim, a source's date and the analyst's inference share one sentence: it keeps each evidence row typed observed, vendor-asserted or inferred, with its source date, so the decision owner can see what would change the answer.

## Do Not Use When

- The user needs to decide whether a customer problem deserves product investment with evidence typing and customer re-entry; use `omh-product-discovery-validation`.
- The request is only fresh links, citations, or current facts without a business question or decision audience; use `omh-web-research` for one cited lookup, or `ulw-research` for a depth-budget study.
- Sources have not yet been selected and the user wants source types, candidates, or acquisition state; use `omh-source-finder`.
- A scoped TAM/SAM/SOM model, customer-evidence matrix, or comparable competitor or pricing profile is the deliverable; use `omh-market-research`, then return here for the audience synthesis.
- The research is recurring and run by several roles; use `omh-research-department`.

## Examples

Good example:

- Prompt: research-brief: compare three onboarding analytics vendors using customer notes and confidence gaps.
- Expected behavior: Prepare a source-backed brief with evidence, inference, confidence, and retrieval gaps separated.
- Why: The user needs business research synthesis, not recurring operations or coding.

Bad example:

- Prompt: research-brief: how big is the dental-clinic software market, TAM, SAM and SOM?
- Expected behavior: Hand the sizing to `omh-market-research`; return here only for the audience synthesis.
- Why: Sizing is a model with units and calculation receipts, not a brief.

## Completion Checklist

- The research question, source boundaries, recency assumptions, and confidence level are named.
- Observed sources, inference, synthesis, and unresolved retrieval gaps are separated.
- Follow-up planning or handoff uses the research summary without calling it execution evidence.
- Each evidence row that cites a ledger source carries the id as `[n]` and its quote, and the citation check is reported from an observed ledger verify run that cited at least one source, or as `not_observed`.

## Recovery Notes

- If ledger verification cites zero distinct sources, retain the source ledger and evidence table, mark the citation check not_observed, and hand back the draft with the missing [n] source IDs for correction.
- If an evidence row's quote cannot be attached from the page text, retain the retrieved source and other supported rows, mark that claim unresolved, and hand back the unmatched wording and source for correction.
- If a pricing comparison mixes periods, currencies, or denominators, retain its dated source rows, mark the comparison tentative, and hand back the missing common basis before drawing a decision implication.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `model-optimization`, `inference-serving`, `model-finetuning`, `research-brief`, `+28 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

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
- When Hermes' bundled `grounded-citations` skill is available, load it and register each source in its ledger when it is retrieved (`scripts/sources.py add`), and carry two more fields on every evidence row: the ledger id written as `[n]` - a bare number in a cell is not a citation to `verify`, so that row would go unchecked - and the verbatim quote attached with `sources.py quote <id> --text <quote> --from <page text file>`, which rejects wording that file does not contain. Keep the run's ledger in a file of its own, passed as `--ledger <path>` before the subcommand on every call: the default ledger is shared by the whole profile, and another run's reset rebinds its ids. A row whose quote could not be attached says so, and a claim that rests on model knowledge is marked `[unverified]` and listed as unresolved, never entered as evidence. Run `sources.py verify <draft> --evidence`, since every evidence row is meant to carry its quote, and report the citation check from that run, or as `not_observed`: the exit status of `sources.py verify <draft>` is the observed check - `0` is a pass and any other status is not - and `verify --evidence` also fails a draft whose cited source carries no verbatim quote. An exit `0` whose `info: stats:` line reads `0 distinct source(s) cited` checked nothing and is reported as `not_observed`; it is a citation check, not fact verification. After that verify, run `omh research receipts verify --citations <ledger> --draft <draft>` and report its fetched coverage from the run, or as `not_observed`; a receipt proves only that the page was opened in this session tree, never that it supports the claim. Without the skill, keep the source and its quoted wording in the row and report the citation check as `not_observed`.
- Use the brief to feed strategy or meeting work without calling it execution evidence.
- For a market question, fix the decision audience, buyer/segment/geography, source cutoff, period/currency/base year, units and denominator before synthesis; leave missing values unknown. Use `omh-market-research` for scoped TAM/SAM/SOM, customer/JTBD evidence, and comparable competitor/pricing methods instead of improvising a market model inside the brief.
- Write each finding with source IDs and dates, observed, vendor-asserted, or inferred status, assumptions, decision implication, contrary evidence, confidence limit, and next verification owner. Keep failed-source coverage visible, not a claim that no evidence exists; lead with what changes the decision and attach only relevant method worksheets.
- A market brief is not customer validation or an investment approval; `omh-product-discovery-validation` retains the kill/pivot/persevere gate, and outreach, participant recruitment, payments, or scheduling each need separate explicit approval.

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
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
