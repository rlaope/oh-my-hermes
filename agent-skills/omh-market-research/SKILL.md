---
name: "omh-market-research"
description: "[omh] Market sizing or customer/competitive analysis: investigate a scoped market with TAM/SAM/SOM sensitivity, attributed customer evidence, and comparable competitor/pricing profiles before a decision brief. Use when the user says: market-research, market sizing, tam sam som, bottom up market sizing, market size sensitivity, customer evidence analysis, jtbd evidence matrix, competitor pricing profiles."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: market-analysis
    role: researcher
    quality_tier: source-gated
---

# Market Research

This is an OMH `market-research` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`market-research` turns a broad market question into bounded sizing, customer evidence, and comparable competitive analysis that a decision owner can inspect without mistaking secondary research for validation.

## First Steps

- Confirm the decision, buyer/segment, geography, period, currency/base year, units/denominator, source cutoff, budget, and stop condition before retrieval. Mark missing inputs unknown; ask the one that changes the analysis first.
- Read `references/findings-template.md` to open the ledger, then load only the needed methods: `references/market-sizing.md`, `references/customer-evidence.md`, or `references/competitive-pricing.md`. Do not manufacture empty analysis lanes for an out-of-scope question.

## Do Not Use When

- A kill, pivot, or persevere gate before a PRD is needed; use `omh-product-discovery-validation`.
- A recurring source inbox with Scout, Analyst, and Briefer operations is needed.
- Supplied tickets need clustering and investigation priorities; use `omh-feedback-triage`.
- A supplied spreadsheet needs cleaning, descriptive statistics, or anomaly analysis; use `omh-data-analysis`.
- A supplied academic PDF needs section-by-section explanation; use `omh-paper-learning`.
- A general business question needs an audience-ready synthesis rather than a domain model; use `omh-research-brief`.

## Examples

Good example:

- Prompt: Estimate TAM SAM SOM for US independent dental clinics with sourced counts and sensitivity, not a guessed capture percentage.
- Expected behavior: Fix scope and units, build a source/assumption ledger, calculate addressable scenarios with tools, and expose confidence limits and missing inputs.
- Why: The task needs an addressable-market model, not only a narrative brief.

Bad example:

- Prompt: Approve our startup for investment because a large total market proves demand.
- Expected behavior: Keep the size estimate separate from a discovery decision; require target-customer evidence and the decision owner's gate.
- Why: Market scale is not customer validation or permission to build.

## Completion Checklist

- The scope, units, source cutoff and stop reason are explicit, and every material finding links sources or labeled assumptions.
- Requested methods include source coverage, contrary evidence and confidence limits; unrequested lanes are marked not requested, not completed.
- Calculation receipts, unresolved retrieval gaps and customer sample limitations are attached; unknowns remain unknown.
- Decision implications name verification needs and an owner, never an automatic discovery, outreach, payment, scheduling or coding action.

## Recovery Notes

- If retrieval fails, record the source ID, attempted date, failure and uncovered period; seek an allowed alternative once within budget or leave the finding unresolved.
- If sources disagree, compare definitions, geography, units and dates before choosing; preserve both ranges when they cannot be reconciled.
- If customer evidence is absent, prepare a consent-aware evidence request and leave the JTBD hypothesis unvalidated, never generate participant answers.



## When to Use

Use when the task needs market-specific analysis of addressable demand, customer jobs and pains, or comparable competitor and pricing evidence, not merely a generic brief or source list.

    Strong routing signals: `market-research`, `market sizing`, `tam sam som`, `bottom up market sizing`, `market size sensitivity`, `customer evidence analysis`, `jtbd evidence matrix`, `competitor pricing profiles`, `competitive pricing analysis`

## Catalog Metadata

Category: `research`
Phase: `market-analysis`
Quality tier: `source-gated`
Reasoning demand: `standard`

Quality bar:

- Require source IDs, dates/cutoffs, observed/vendor-asserted/inferred labels, assumptions and units on material claims.
- Keep failed retrieval, contrary evidence, sample bias, scope mismatch and confidence limits visible; a citation alone does not verify a claim.
- Load method and output templates on demand; calculations need real tool receipts, and absent evidence cannot be synthesized into certainty.

Required inputs:

- decision and audience
- buyer segment and geography
- period currency units and source cutoff
- available evidence and source boundary
- research budget and stop condition

Expert clarification questions:
- `decision and audience`
  - English: Which decision must this inform, for which audience and decision owner?
  - Korean: Which decision must this inform, for which audience and decision owner?

Expected outputs:

- market scope and source ledger
- TAM SAM SOM model and sensitivity
- customer evidence and JTBD matrix
- comparable competitor and pricing profiles
- decision-ready market findings

Artifact expectations:

- prepared market analysis with source IDs, assumptions, failed retrieval gaps, and tool calculation receipts when captured

Safety rules:

- Never invent figures or quotes, customer participants, market shares, traffic/revenue estimates, source IDs, or tool results. Label unsupported inputs unknown rather than borrowing a generic industry ratio.
- Outreach, participant recruitment, payments, and scheduling each require separate explicit approval; research approval is not permission to contact people, buy reports, run surveys, or create jobs.
- Keep contact details, raw recordings, private transcripts, and sensitive customer data outside durable artifacts; use consented bounded summaries and pseudonymous IDs with access-controlled source pointers.
- A prepared analysis is not retrieval, interviews, willingness to pay, customer validation, product-market fit, or an approved investment decision. No external tool, paid dataset, or MCP integration is mandatory.

Procedure: load `references/procedure.md`.

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
