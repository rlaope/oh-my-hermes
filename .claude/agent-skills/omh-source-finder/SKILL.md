---
name: "omh-source-finder"
description: "[omh] Gathering candidate papers, datasets, or repos: source candidate inventory - prepare typed source candidates and acquisition status before downstream work; use ulw-research to fetch and cite them, or `omh-research-brief` to turn them into a decision-ready brief. Use when the user says: source-finder, source finder, source acquisition, source intake, find papers and datasets, find datasets and repos, find papers, find arxiv link."
disable-model-invocation: true
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: source-acquisition
    role: researcher
    quality_tier: source-acquisition-gated
---

# Source Finder

This is an OMH `source-finder` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`source-finder` exists so Hermes can turn vague source discovery requests into typed candidates, acquisition status, and downstream workflow choice without pretending OMH searched, downloaded, or verified the material.

## First Steps

- Discover the current search/read tools and authorized scope, then follow `references/search-method.md`: plan -> actual host search/read -> merge -> assess -> bounded retry. Use `omh_search` only when available; otherwise report the skill-only fallback. Keep direct file lookups direct.

## Do Not Use When

- The requested output is factual findings, comparison, or a summary rather than a typed candidate inventory and acquisition status; use `ulw-research`.
- The user needs a business decision brief with evidence-versus-inference treatment; use `omh-research-brief`.
- The user asks for a cited answer to a current-facts question; use `omh-web-research`, and for a reference-implementation study with a depth budget use `ulw-research`.
- The user supplies a paper/PDF/arXiv/DOI/excerpt and wants explanation; use `omh-paper-learning`.
- The user asks for recurring monitoring, source inbox, or Scout/Analyst/Briefer operations.
- The user asks to export, convert, render, package, or attach a file; use `omh-materials-package` or `omh-deliverable-package`.
- The user asks for an image card or visual summary; use `omh-image-cards`.

## Examples

Good example:

- Prompt: source-finder find papers, datasets, and GitHub repos for evaluating browser agent benchmarks.
- Expected behavior: Prepare source_finder_plan/v1 with typed candidates, acquisition states, missing observed evidence, and downstream choices.
- Why: The user needs source candidates before deciding whether to learn, research, package, or implement.

Bad example:

- Prompt: source-finder find current citations and summarize what the sources say.
- Expected behavior: Route to `ulw-research` because the user asks for current evidence and synthesis, not candidate acquisition status.
- Why: Source-finder prepares acquisition lifecycle metadata; research owns current evidence synthesis.

## Completion Checklist

- Source kinds, source boundaries, and downstream intent are named.
- Each candidate has a source_candidate/v1 shape and acquisition state.
- Observed states include provenance before being treated as evidence.
- The next downstream workflow is recommended without claiming it ran.
- Search, download, clone, extraction, hash, license, verification, and downstream processing gaps are explicit.

## Recovery Notes

- If the user asks for facts or citations, route to `ulw-research`.
- If a candidate lacks a link or file reference, keep it candidate_prepared and ask for the next observable source step.
- If the user wants to process a selected source, route to the downstream workflow instead of continuing source acquisition.



## When to Use

Use when the requested output is a typed source candidate inventory and acquisition status across papers, web links, datasets, GitHub repositories, public presentations, docs/specs, or unknown source material before choosing `omh-paper-learning`, `ulw-research`, `omh-research-brief`, `omh-materials-package`, or `ulw-work` for a delivery cycle.

    Strong routing signals: `source-finder`, `source finder`, `source acquisition`, `source intake`, `find papers and datasets`, `find datasets and repos`, `find papers`, `find arxiv link`, `find arxiv paper`, `find datasets`, `find github repos`, `find oss repos`, `find presentations`, `find public slides`, `find docs and specs`, `find source candidates`, `download candidate`, `source candidate`, `acquisition status`, `자료 후보`, `출처 후보`, `arxiv 링크`, `arxiv 링크 찾아`, `논문 데이터셋 찾아`, `깃허브 저장소 찾아`, `공개 발표자료 찾아`, `문서 스펙 찾아`

## Catalog Metadata

Category: `research`
Phase: `source-acquisition`
Quality tier: `source-acquisition-gated`
Reasoning demand: `standard`

Quality bar:

- Name source kinds from: paper, web_link, dataset, github_repo, presentation, docs_spec, unknown.
- Record acquisition state from: candidate_prepared, link_observed, download_link_prepared, download_observed, file_hash_recorded, text_extraction_observed, license_checked, verification_observed, downstream_selected.
- Separate candidate preparation, observed link, observed download, file hash, text extraction, license check, verification, and downstream selection.
- Attach observation provenance before treating any acquisition state as evidence.
- For `paper` candidates, when Hermes' bundled `arxiv` skill is available, search through it - by topic, author, category, or paper id - and record each entry it returns as `link_observed` with `hermes_tool` provenance. A search result is an observed link and nothing more: download, text extraction, and verification stay unclaimed until their own run is observed. Without the skill, a paper candidate stays `candidate_prepared` until a link is observed another way.
- Vary search angles across official docs, academic work, implementations, datasets, and criticism within the plan's budget (3 queries, 10 external attempts and one follow-up for an explore search), and name the source kinds still without candidates when the budget ends.
- Recommend the next downstream workflow without pretending that downstream work already ran.

Required inputs:

- source target or topic
- desired source kinds
- source boundaries or exclusion criteria
- downstream intent when known

Expected outputs:

- source_finder_plan/v1
- source_candidate/v1
- source_candidate_set/v1
- source_acquisition_status/v1
- downstream workflow recommendation
- not-evidence boundary

Artifact expectations:

- source_finder_plan/v1 under .omh/source-finder when a wrapper or CLI records it

Safety rules:

- Do not claim web search, download, repository clone, file extraction, file hash verification, license verification, or source correctness from a prepared candidate.
- Do not define a source inbox; source-finder owns source_candidate_set/v1 and source_acquisition_status/v1 only.
- Route current citations and source-backed synthesis to `ulw-research`, supplied-paper explanation to `omh-paper-learning`, file export to `omh-materials-package`, and image cards to `omh-image-cards`.

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
