---
name: "omh-systematic-review"
description: "[omh] Literature screening against frozen criteria: two blind reviewers, a deterministic merge, open conflicts and agreement for systematic, scoping or rapid reviews. Use when the user says: systematic-review, systematic review, systematic literature review, scoping review, rapid review, prisma screening, title and abstract screening, inclusion and exclusion criteria screening."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: literature-screening
    role: researcher
    quality_tier: evidence-gated
    related_skills: [omh-source-finder, omh-paper-learning, omh-repro-audit]
---

# Systematic Review

This is a Hermes-native `systematic-review` workflow skill.

## Why This Exists

Two reviewers screening the same records only count as dual review when neither sees the other's answers and the merge is mechanical. This workflow freezes the criteria first, keeps each reviewer blind, and never turns a missing answer into an exclusion.

## First Steps

- Records must be deduplicated across databases first (DOI or PMID, else normalized title plus year); record the identified, duplicate-removed and screened counts, because the PRISMA flow needs them and this workflow does not deduplicate.
- Agree the inclusion and exclusion criteria and the ordered exclusion codes with the person before any record is read; nothing is frozen until they say the criteria are final. To pilot the criteria, freeze a throwaway DIR, prepare it on 25 to 50 records, review the conflicts, then freeze the real DIR.
- Call `omh research screening freeze --criteria FILE --codes FILE --out DIR`. The protocol is write-once: a criteria change after freeze means a new DIR, never an edited protocol.json.
- Call `omh research screening prepare --dir DIR --records FILE --seed N`, then read DIR/manifest.json for the batch list.
- When `delegate_task` is in your tool list or tool_search finds it, dispatch two children, A and B: give each only its own `DIR/tasks/<A|B>/` files and tell it to write answer lines to `DIR/answers/<A|B>/`. Never pass one child the other's tasks, answers or name; without the tool, ask the person to run the two reviewers separately. By default a child runs on the session's model (or the `delegation.model` pin) and `delegate_task` takes no per-child model, so A and B are then recorded as the same model: pass the real model for both and report `broken_independence`. Where the host routes each delegated task to a different model (a delegation backend or `omh_delegate_route`), give B another route and record the model it reports; otherwise ask the person to run reviewer B in a session on another model. Never write a model name you did not observe.
- Call `omh research screening merge --dir DIR --answers-a DIR/answers/A --answers-b DIR/answers/B --reviewer-models A=<model>,B=<model> --json`. Exit 1 means conflicts or pending records remain; exit 2 is an input error to fix, not a result.
- Show the conflict and pending ids to the person, or give a third child only the conflict records and the frozen criteria; pass its lines with `--adjudication` and merge again.

## Do Not Use When

- Finding candidate papers, datasets or repositories on a topic belongs to `omh-source-finder`.
- Explaining one supplied paper section by section belongs to `omh-paper-learning`.
- Checking a HellaSwag log against the paper's reported conditions belongs to `omh-repro-audit`.
- Full-text screening, search-string building, risk-of-bias and data extraction are not covered; this skill screens title and abstract only.
- Drafting the manuscript itself is paper writing: load Hermes' optional research-paper-writing skill when it is installed.

## Examples

Good example:

- Prompt: Screen these 400 abstracts for my systematic review of statin trials with two reviewers.
- Expected behavior: Freeze the agreed criteria, prepare blind batches, dispatch reviewers A and B, merge, and report conflicts, pending records and agreement with the independence label.
- Why: The person has records and a review protocol, and needs dual screening.

Bad example:

- Prompt: Do a systematic code review of this PR.
- Expected behavior: Route to code review; nothing here screens literature.
- Why: Systematic describes the review style, not a literature screening protocol.

## Completion Checklist

- protocol.json was frozen before any reviewer saw a record.
- Each reviewer received only its own task files.
- The report gives included, excluded by code, conflicts, adjudicated and pending counts, agreement and the independence label from the observed merge output.

## Recovery Notes

- If freeze refuses because protocol.json exists, choose a new DIR; never delete or edit the frozen protocol.
- If merge reports pending records, send the missing ids back to that reviewer only, then merge again.

## Workflow Lane

- Current lane: **Research and company ops** - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when records for a systematic, scoping or rapid review must be screened against the person's inclusion and exclusion criteria by two independent reviewers, with every conflict and missing decision kept visible.

    Strong routing signals: `systematic-review`, `systematic review`, `systematic literature review`, `scoping review`, `rapid review`, `prisma screening`, `title and abstract screening`, `inclusion and exclusion criteria screening`, `dual reviewer screening`, `체계적 문헌고찰 스크리닝`, `초록 선별`, `두 명이 선별`

## Catalog Metadata

Category: `research`
Phase: `literature-screening`
Hermes role: `researcher`
Quality tier: `evidence-gated`
Reasoning demand: `standard`

Quality bar:

- Counts in the report equal the merge payload's counts, with conflicts and pending reported separately from included and excluded.
- The report names the protocol_sha256, the seed and the reviewer models it ran with.

Handoff policy:

Hermes owns the protocol conversation, the two reviewer children and the report. `omh research screening` only freezes, prepares and merges local files; it makes no model or network call and never decides a record itself.

Required inputs:

- inclusion and exclusion criteria the person approved
- ordered exclusion codes (E1, E2, ...)
- records JSONL with id, title and abstract
- new screening directory and an integer seed

Expected outputs:

- DIR/protocol.json (screening_protocol/v1, write-once)
- DIR/tasks/A and DIR/tasks/B blind batches plus DIR/manifest.json (screening_manifest/v1)
- screening_merge/v1 with counts, conflict and pending ids, agreement_stats/v1 and reviewer_independence

Artifact expectations:

- Keep protocol.json, manifest.json, every task file and every answer file under DIR; the merge payload carries ids and codes only, never titles, abstracts or answer text.

Safety rules:

- A record with no answer line, two different lines or an unknown code is pending for that reviewer; never read it as an exclusion.
- Same-model reviewers are not independent: report `reviewer_independence` as the merge prints it, and keep the `broken_independence` warning in the report.
- Agreement (kappa, PABAK) is agreement between two reviewers, not accuracy; never call it correctness against a human gold set.
- AI screening decisions are decision support; the review team verifies them before any PRISMA count is published.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
