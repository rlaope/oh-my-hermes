---
name: "omh-docs"
description: "[omh] Explaining OMH itself: current-source-first documentation for OMH itself: product identity, public capability catalog, model routing, local state, and long-term memory. Use when the user says: product-docs, OMH documentation, oh-my-hermes documentation, what is OMH, what is oh-my-hermes, how does OMH work, OMH capability catalog, OMH skill catalog."
license: MIT
compatibility: "Requires the omh CLI on PATH (pip install oh-my-hermes)."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: product-documentation
    role: researcher
    quality_tier: source-gated
---

# Product Docs

This is an OMH `product-docs` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`omh-docs` gives Hermes one bounded, source-first way to explain OMH itself without turning product questions into generic workflow routing or silently changing the user's installation.

## Do Not Use When

- The user wants generic documentation writing, editing, or summarization unrelated to OMH.
- The question is about OpenAI or Hermes Agent rather than OMH; use that product's official documentation skill.
- The user wants setup or repair.
- The user wants to install, update, remove, or edit catalog skills.
- The user wants model or provider settings changed.

## Examples

Good example:

- Prompt: How does OMH model routing work, and which local settings can I inspect safely?
- Expected behavior: Separate current public behavior from this installation, retrieve official sources plus passive local metadata, disclose refs or versions, and answer without changing settings.
- Why: The request asks for current OMH self-knowledge and local-state explanation, not a configuration change.

Bad example:

- Prompt: Rewrite my library's API documentation and publish it.
- Expected behavior: Do not select omh-docs; this is generic documentation authoring plus an external mutation.
- Why: The skill explains OMH itself and does not author or publish unrelated documentation.

## Completion Checklist

- Every mutable public claim cites an official current source and ref, version, or commit.
- Local facts name the passive command, disclosed diagnostic, or metadata path and remain separate from public-product facts.
- No prohibited secret, raw-log, or unrelated-content source was read or printed.
- Any requested mutation was routed to a specialized workflow and not performed without separate authorization.

## Recovery Notes

- If official sources conflict, show the conflict with exact refs and lower confidence.
- If network retrieval is unavailable, use a clean local checkout or installed package only with its commit or version and an explicit freshness caveat.
- If a documented local path is absent, report that the install or profile does not expose it instead of treating absence as corruption.



## When to Use

Use for current, source-backed questions about OMH itself, including its product identity, public skill catalog, model routing, local installation state, and long-term memory.

    Strong routing signals: `product-docs`, `OMH documentation`, `oh-my-hermes documentation`, `what is OMH`, `what is oh-my-hermes`, `how does OMH work`, `OMH capability catalog`, `OMH skill catalog`, `OMH model routing`, `OMH memory system`, `where does OMH store local state`

## Catalog Metadata

Category: `research`
Phase: `product-documentation`
Quality tier: `source-gated`
Reasoning demand: `standard`

Quality bar:

- Classify each claim as public-product or current-local-install before retrieval.
- Retrieve only the sources needed for the question and stop when the answer is supported.
- Prefer live repository metadata and current main sources for mutable public facts; never answer a current-facts question from model recall.
- Query the current catalog for skill counts instead of hard-coding a mutable number.
- If official sources disagree or freshness cannot be established, name the exact source boundary instead of flattening the conflict.

Required inputs:

- OMH documentation question
- public-product or current-local-install scope
- freshness, version, or ref requirement when material

Expected outputs:

- source-backed answer
- public-product and local-install facts kept separate
- source URL or local command/path plus ref, version, or commit
- named freshness or source-boundary gap

Artifact expectations:

- one-shot answer by default; durable documentation artifact only when the user requests one

Safety rules:

- Use official `rlaope/oh-my-hermes` sources for current public facts and disclose the source plus ref, version, or commit.
- Use passive CLI output or narrowly scoped metadata for local-install facts; disclose diagnostic state writes and say that path presence varies by resolved home, scope, install, and profile.
- Never read or print credentials, tokens, auth files, `.env` values, provider secrets, raw private logs, or unrelated user content.
- Do not treat a local checkout or installed package as current public truth without recording its commit or version and disclosing possible staleness.
- Do not mutate setup, installation, updates, settings, memory, routing, or repository files while answering a documentation question.

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
