---
name: "omh-research-brief"
description: "[omh] Business question on market, competitors, pricing: business research brief - turns a market, competitor, pricing, or customer question into a structured evidence-vs-inference brief; for raw link gathering use ulw-research. Use when the user says: research-brief, business-research, business research, research brief, decision brief, pricing decision brief, decision-ready brief, source-backed business research."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: business-brief
    role: researcher
    quality_tier: source-gated
---

# Research Brief

This is an OMH `research-brief` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`research-brief` exists to keep `research` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The user needs to decide whether a customer problem deserves product investment with evidence typing and customer re-entry; use `omh-product-discovery-validation`.
- The request is only fresh links, citations, or current facts without a business question or decision audience; use `ulw-research`.
- Sources have not yet been selected and the user wants source types, candidates, or acquisition state; use `omh-source-finder`.

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
- Each evidence row that cites a ledger source carries the id as `[n]` and its quote, and the citation check is reported from an observed ledger verify run that cited at least one source, or as `not_observed`.

## Recovery Notes

- If sources cannot be accessed, state the retrieval gap and use only observed local context.
- If evidence is thin or one-sided, lower confidence and ask for a narrower source boundary.



## When to Use

Use when Hermes should scope a business question, gather or summarize source-backed evidence, and preserve evidence/inference boundaries before strategy or handoff.

    Strong routing signals: `research-brief`, `business-research`, `business research`, `research brief`, `decision brief`, `pricing decision brief`, `decision-ready brief`, `source-backed business research`, `customer feedback trends`, `feedback trends`, `market evidence`, `data search`, `source scan`, `자료 조사`, `데이터 서치`, `근거 조사`, `피드백 추세`, `고객 피드백 추세`

## Catalog Metadata

Category: `research`
Phase: `business-brief`
Quality tier: `source-gated`
Reasoning demand: `standard`

Quality bar:

- State the research question, source boundaries, and recency assumptions before synthesis.
- Record each material claim as a compact evidence row: claim, source, source class (upstream official, practitioner heuristic, or unattributed), source date, confidence, and unresolved conflict.
- Keep claims that lack corroboration in an explicit unresolved list instead of asserting or silently dropping them.
- Separate observed sources, source quality, source diversity, inferred trends, and unresolved uncertainty.
- When Hermes' bundled `grounded-citations` skill is available, load it and register each source in its ledger when it is retrieved (`scripts/sources.py add`), and carry two more fields on every evidence row: the ledger id written as `[n]` - a bare number in a cell is not a citation to `verify`, so that row would go unchecked - and the verbatim quote attached with `sources.py quote <id> --text <quote> --from <page text file>`, which rejects wording that file does not contain. Keep the run's ledger in a file of its own, passed as `--ledger <path>` before the subcommand on every call: the default ledger is shared by the whole profile, and another run's reset rebinds its ids. A row whose quote could not be attached says so, and a claim that rests on model knowledge is marked `[unverified]` and listed as unresolved, never entered as evidence. Run `sources.py verify <draft> --evidence`, since every evidence row is meant to carry its quote, and report the citation check from that run, or as `not_observed`: the exit status of `sources.py verify <draft>` is the observed check - `0` is a pass and any other status is not - and `verify --evidence` also fails a draft whose cited source carries no verbatim quote. An exit `0` whose `info: stats:` line reads `0 distinct source(s) cited` checked nothing and is reported as `not_observed`; it is a citation check, not fact verification. After that verify, run `omh research receipts verify --citations <ledger> --draft <draft>` and report its fetched coverage from the run, or as `not_observed`; a receipt proves only that the page was opened in this session tree, never that it supports the claim. Without the skill, keep the source and its quoted wording in the row and report the citation check as `not_observed`.
- Use the brief to feed strategy or meeting work without calling it execution evidence.
- For a market question, fix the decision audience, buyer/segment/geography, source cutoff, period/currency/base year, units and denominator before synthesis; leave missing values unknown. Use `market-research` for scoped TAM/SAM/SOM, customer/JTBD evidence, and comparable competitor/pricing methods instead of improvising a market model inside the brief.
- Write each finding with source IDs and dates, observed, vendor-asserted, or inferred status, assumptions, decision implication, contrary evidence, confidence limit, and next verification owner. Keep failed-source coverage visible, not a claim that no evidence exists; lead with what changes the decision and attach only relevant method worksheets.
- A market brief is not customer validation or an investment approval; `product-discovery-validation` retains the kill/pivot/persevere gate, and outreach, participant recruitment, payments, or scheduling each need separate explicit approval.

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
