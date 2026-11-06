---
name: "omh-wiki"
description: "[omh] Scattered knowledge needing a wiki: wiki construction blueprints and retained knowledge capture with destination-aware external knowledge connection guidance. Use when the user says: wiki, project wiki, build a wiki, start a wiki, organize my notes, external knowledge store, knowledge base, Obsidian."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, knowledge]
    category: knowledge
    phase: design-and-capture
    role: memory-keeper
    quality_tier: knowledge-gated
    related_skills: [llm-wiki]
---

# Wiki

This is a Hermes-native `wiki` workflow skill.

## Why This Exists

`wiki` exists to keep `knowledge` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- The user wants the agent to ingest sources into, query, or lint an interlinked markdown knowledge base it maintains itself in the Karpathy LLM Wiki pattern; load Hermes' bundled `llm-wiki` skill instead of this one.

## Examples

Good example:

- Prompt: wiki: six of us keep re-answering the same questions in chat; help me stand up a wiki in Notion.
- Expected behavior: Ask who reads and maintains it and what knowledge repeats, then propose one model with its breaking conditions, a skeleton, and seed pages, without claiming the store was created.
- Why: The request is wiki construction for a shared audience, not a single note capture or connector execution.

Bad example:

- Prompt: wiki: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `wiki`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Completion Checklist

- Audience scale, destination, knowledge types, and maintenance owner are recorded or named as missing.
- The proposed model carries its rationale, breaking conditions, and one alternative.
- Skeleton, entry points, conventions, maintenance, and seed pages are concrete enough to start today.
- Destination-specific guidance is prepared for the named store or the unknown destination gap is explicit.
- No output claims an external write, store creation, connector run, or memory mutation without evidence.
- Separate coding or connector tasks are extracted instead of buried in notes.

## Recovery Notes

- If the audience scale is unknown, ask for it before proposing structure; it changes the model.
- If nobody owns maintenance, record 'unmaintained' and choose a model that survives it.
- If source evidence conflicts, route to memory or knowledge review before writing durable guidance.
- If the destination is unknown, record the missing facts and keep the guidance vendor-neutral.
- If the fact may be stale, record the staleness warning and next refresh action.

## Workflow Lane

- Current lane: **Retained knowledge** (`memory-new`, `memory-sync`, `decision-recall`, `wiki`) - memory, rejected alternatives, wiki notes, retrieval, and staleness.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## Design Interview

Settle structure before capture: audience scale, whether an agent reads it, the knowledge types that repeat, what someone will search for, and who maintains it. Skip answered turns, cap at five, and close with one model plus one alternative as a skeleton the user approves before anything is written. No maintainer means `unmaintained`, which rules out models needing curation.

Load `references/wiki-blueprint.md` for the interview turns and `wiki_blueprint/v1` fields, `wiki-patterns.md` for models and what breaks them, `wiki-operations.md` for solo-versus-shared rules, and `wiki-ecosystem.md` for existing skills.

## Closing A Long Piece Of Work

When work finishes, the capture for the next reader is three artifacts: a deep guide, an ELI5 pass at level `very_easy`, and a quiz that checks the guide rather than the reader. Build them from the plan record (`omh runtime todo show`, the only source that outlives the session) plus whatever verification, review, and QA output the session still holds, and record which of those you could actually read. Load `references/handover-artifacts.md` for the admissible sources and the quiz's citation rule.

## Boundary

A `wiki_blueprint/v1` is a prepared design artifact, not evidence that a store was created, written to, or migrated. OMH does not host the wiki; the user's own store does.

## When to Use

Use to design a wiki someone can start today - model, skeleton, conventions, seed pages, and maintenance sized to a personal, small-group, team, or organization audience - and to capture durable knowledge into markdown vaults, Obsidian, Notion, Google Drive/Docs, databases, or local folders.

    Strong routing signals: `wiki`, `project wiki`, `build a wiki`, `start a wiki`, `organize my notes`, `external knowledge store`, `knowledge base`, `Obsidian`, `markdown vault`, `Notion knowledge base`, `Google Drive wiki`, `옵시디언`, `마크다운 볼트`, `노션 지식베이스`, `위키`, `위키 만들`, `지식베이스`, `지식 정리 체계`

## Catalog Metadata

Category: `knowledge`
Phase: `design-and-capture`
Hermes role: `memory-keeper`
Quality tier: `knowledge-gated`
Reasoning demand: `light`

Quality bar:

- Size the structure to the audience: personal and shared wikis fail differently and get different models.
- Propose a model with its rationale, breaking conditions, and one alternative; cap seed pages at ten.
- Check existing ecosystem wiki skills before designing a bespoke structure.
- Capture durable facts with source evidence and destination-aware retrieval hints.
- Treat Obsidian as one vendor hint under a broader external knowledge connection model.
- Never present prepared wiki guidance as an observed external write, store creation, or memory mutation.
- Mark stale or uncertain knowledge instead of presenting it as permanent truth.
- Extract separate coding tasks instead of burying them in notes.

Handoff policy:

Run directly in Hermes as wiki design and retained knowledge capture; prepare connector/runtime handoff only when a separate observed external write or coding task is explicitly required.

Required inputs:

- audience scale (personal, small group, team, or organization)
- whether an agent is one of the readers
- destination or existing store
- knowledge types the wiki must hold
- maintenance owner and cadence

Expected outputs:

- wiki_blueprint/v1 with organization model, rationale, breaking conditions, and one alternative
- skeleton, entry points, conventions, maintenance routine, seed pages, and ecosystem candidates
- destination-aware note guidance with retrieval hint and staleness warning
- prepared-versus-observed external write boundary

Artifact expectations:

- wiki skeleton proposal covering sections, entry points, conventions, and maintenance
- repo-local markdown knowledge artifact or metadata-only destination guidance

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Runtime Evidence

Preferred harness for this skill: `docs-specialist`.

```sh
omh runtime record --skill wiki --harness docs-specialist --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
