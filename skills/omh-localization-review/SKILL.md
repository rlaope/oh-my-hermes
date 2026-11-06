---
name: "omh-localization-review"
description: "[omh] Translated product or content release: make a product or content release locale-ready with terminology, cultural-fit, and quality-review guidance. Use when the user says: localization review, translation QA, locale glossary, 현지화 검토, 번역 QA, 용어집."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: localization-review
    role: reviewer
    quality_tier: review-gated
    related_skills: [omh-content-operator, omh-visual-qa, omh-files, omh-apps, omh-legal-compliance-review]
---

# Localization Review

This is a Hermes-native `localization-review` workflow skill.

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

## Recovery Notes

- If the source version cannot be established, retain supplied strings and the locale/audience brief, mark terminology and cultural-fit choices tentative, and hand back the source-version question before treating the glossary as approved.
- If rendered UI evidence is missing, retain glossary choices and the string issue matrix, mark rendered validation not_observed, and hand back locale QA criteria and review owners for an accepted `omh-visual-qa` handoff.

## Workflow Lane

- Current lane: **Materials and visual summaries** (`show-reel`, `sprite-forge`, `design-orchestration`, `apple-design`, `design-quality-gate`, `award-bar-score`, `frontend`, `accessibility-audit`, `+8 more`) - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when multiple strings, a product surface, a market release, or a locale-sensitive document needs terminology, context, consistency, cultural-fit, and QA guidance beyond one-off translation.

    Strong routing signals: `localization review`, `translation QA`, `locale glossary`, `현지화 검토`, `번역 QA`, `용어집`

## Catalog Metadata

Category: `review`
Phase: `localization-review`
Hermes role: `reviewer`
Quality tier: `review-gated`
Reasoning demand: `standard`

Quality bar:

- Ground terminology and cultural-fit choices in locale, audience, context, and source version.
- Make string severity, review ownership, and rendered QA gaps explicit.

Handoff policy:

Keep domain framing, clarification, source/evidence synthesis, draft outputs, and next-work routing in Hermes. A prepared brief, review, reply, or plan is not an external action, approval, filing, send, publish, data mutation, implementation, review, CI, or merge claim. Prepare a connector, file, coding, or human-review handoff only when the user explicitly accepts that next step; report it only from observed evidence. Hermes may draft and review language guidance; it does not alter locale files, upload strings, publish translations, validate a rendered build, or claim market approval.

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

Preferred harness for this skill: `critic`.

```sh
omh runtime record --skill localization-review --harness critic --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
