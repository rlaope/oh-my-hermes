---
name: "omh-award-bar-score"
description: "[omh] Aiming for design-award quality: score a web surface against published design-award judging axes and name the binding constraint. Use when the user says: award-bar-score, award bar score, award winning, award-winning, award winning website, award-winning website, award winning design, award ready."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: award-bar-score
    role: operator
    quality_tier: design-orchestration-gated
    related_skills: [omh-design-quality-gate, omh-frontend, omh-accessibility-audit, omh-visual-qa]
---

# Award Bar Score

Required: the target URL, route, or rendered capture being judged, the award body (CSSDA or Awwwards) and its published axes, weights, and threshold, the surface's own accessibility and performance budgets, audience and primary user task. Output: award_bar_score/v1, per-axis scores with named evidence for each axis the chosen body publishes (UI, UX and innovation for CSSDA), the weighted total and its distance from the published threshold, the binding constraint: the axis whose gain moves the total most, tradeoff_ledger/v1 when an innovation move costs accessibility or performance budget, downstream route: `omh-frontend`, `omh-accessibility-audit`, `omh-visual-qa`, or `omh-design-quality-gate`.

## Why This Exists

`award-bar-score` gives "make it award-winning" a measurable meaning: published axes, published weights, a published threshold, and the one axis holding the surface below it — instead of a taste argument nobody can settle.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Materials and visual summaries** - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when a web surface must be judged against an external award bar: per-axis scores for the axes the chosen award body publishes, the weighted total against the published threshold, and the one axis holding the score down.

    Strong routing signals: `award-bar-score`, `award bar score`, `award winning`, `award-winning`, `award winning website`, `award-winning website`, `award winning design`, `award ready`, `make it award winning`, `design award`, `design awards`, `css design awards`, `cssda`, `awwwards`, `site of the day`, `website of the day`, `wotd`, `score my site`, `어워드`, `디자인 어워드`, `어워드 수준`, `수상작 수준`, `수상 가능한 디자인`, `어워드 받을만한`, `올해의 사이트`

## Catalog Metadata

Category: `materials`
Phase: `award-bar-score`
Hermes role: `operator`
Quality tier: `design-orchestration-gated`
Reasoning demand: `standard`

Quality bar:

- Score each axis separately with named rendered evidence, then compute the weighted total; an overall impression is not a score and hides which axis is failing.
- For CSSDA, reserve binding-constraint language for a total within about 0.3 of the threshold. Measured axis spread is roughly a twentieth of site spread, so further below the bar a weak axis is a symptom: report that the site needs a level change, never a one-axis fix.
- Load `references/award-judging-model.md` for the published axes, weights, and thresholds, the measured per-axis score table, and the stack table that separates entry-fee craft (fluid type, real typography) from optional spend (WebGL).
- Record what an innovation move costs on the accessibility and performance budgets before recommending it; half the sampled motion-heavy winners drop `prefers-reduced-motion`, and the two highest-scoring entries keep it, so never present the inaccessible path as the higher-scoring one.

Handoff policy:

Keep axis scoring, the weighted total, the binding-constraint call, and the tradeoff ledger in Hermes. Route implementation to `omh-frontend`, WCAG evidence to `omh-accessibility-audit`, and rendered captures to `omh-visual-qa`; never score an axis from a description of a page instead of the page.

Safety rules:

- A self-assessment against a published rubric is never an award, a jury outcome, or a prediction of one; juries score submissions, and OMH does not.
- Never score an axis without rendered evidence; an unrendered page keeps every axis not_observed.
- Quote axis weights and thresholds only from the award body's published rules, and name the body and the date they were read.
- Accessibility and performance budgets outrank the innovation axis; when a move breaks one, record the tradeoff and let the user choose rather than defaulting to the score.
- Do not call a browser, network service, screenshot tool, or executor from OMH core.

## Completion Checklist

- Each axis the chosen body publishes carries its own score and the rendered evidence it was read from.
- The weighted total is computed from the stated weights and compared against the published threshold.
- The binding constraint names one axis and what moving it requires.
- Any innovation move that costs accessibility or performance budget is recorded as a tradeoff the user chooses.
- No award, jury, placement, or selection outcome is claimed.

## Recovery Notes

- If no rendered evidence exists, keep every axis not_observed and route the capture to `omh-visual-qa` before scoring.
- If the body is neither CSSDA nor Awwwards, ask for its published rules URL and score only the axes it publishes.
- If the award body publishes no weights, score the axes separately and report the total as unweighted rather than inventing a ratio.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
