---
name: "omh-localization-review"
description: "[omh] Translated product or content release: make a product or content release locale-ready with terminology, cultural-fit, and quality-review guidance. Use when the user says: localization review, translation QA, locale glossary, 현지화 검토, 번역 QA, 용어집."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: localization-review
    role: reviewer
    quality_tier: review-gated
---

# Localization Review

This is an OMH `localization-review` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`localization-review` makes terminology, context, cultural fit, and locale QA reviewable without treating a drafted translation as a published or visually validated release.

## Do Not Use When

- The request is a short sentence or word translation or rewrite with no product or locale QA context; answer directly or use `omh-content-operator`.
- The user needs fresh rendered UI evidence, clipping checks, or a visual PASS/REVISE/BLOCK verdict; use `omh-visual-qa`.
- The user asks to edit locale files, push a translation-management-system job, publish strings, or configure localization settings; use `omh-files` or `omh-apps` with explicit target and authority.
- The request asks for a regulatory or contractual conclusion about translated legal text; use `omh-legal-compliance-review`.

## Examples

Good example:

- Prompt: Review our Korean checkout strings for terminology consistency, cultural fit, and context gaps before launch.
- Expected behavior: Prepare the locale and source-version brief, glossary choices, issue matrix, and locale QA criteria.
- Why: The product-release context needs localization review beyond a one-off translation.

Bad example:

- Prompt: Translate 'Your trial ends tomorrow' into Korean.
- Expected behavior: Answer directly or route to `omh-content-operator`, not `localization-review`.
- Why: A one-off sentence has no product locale QA or release-review objective.

## Completion Checklist

- Findings or no-issue results are grounded in concrete file, artifact, command, or source evidence.
- Open questions, residual risk, and missing verification are named.
- Fixes or follow-up work are separate handoffs unless the user explicitly asked to implement them.
- Per string: placeholders intact, target-locale plural categories, expansion and truncation, date/number/currency formats, register, literal brand and command tokens. Blocker: wrong meaning, broken placeholder, legal or safety text; major: glossary or register miss; minor: style.

## Recovery Notes

- If the source version cannot be established, retain supplied strings and the locale/audience brief, mark terminology and cultural-fit choices tentative, and hand back the source-version question before treating the glossary as approved.
- If rendered UI evidence is missing, retain glossary choices and the string issue matrix, mark rendered validation not_observed, and hand back locale QA criteria and review owners for an accepted `omh-visual-qa` handoff.



## When to Use

Use when multiple strings, a product surface, a market release, or a locale-sensitive document needs terminology, context, consistency, cultural-fit, and QA guidance beyond one-off translation.

    Strong routing signals: `localization review`, `translation QA`, `locale glossary`, `현지화 검토`, `번역 QA`, `용어집`

## Catalog Metadata

Category: `review`
Phase: `localization-review`
Quality tier: `review-gated`
Reasoning demand: `standard`

Quality bar:

- Ground terminology and cultural-fit choices in locale, audience, context, and source version.
- Make string severity, review ownership, and rendered QA gaps explicit.

Required inputs:

- locale
- audience
- source version
- product or content context

Expert clarification questions:
- `locale`
  - English: Which target locale should this localization review cover?
  - Korean: 이 현지화 검토의 대상 로캘은 무엇인가요?

Expected outputs:

- locale/audience/context and source-version brief
- approved-term glossary and transcreation/localization choices
- string/content issue matrix with context, severity, and review owner
- locale QA acceptance criteria and handoff/observed-evidence gaps

Artifact expectations:

- prepared localization review when a wrapper captures it

Safety rules:

- Separate language guidance from rendered UI evidence and market approval.
- Do not claim locale-file changes, translation upload, publication, or rendered validation.

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
