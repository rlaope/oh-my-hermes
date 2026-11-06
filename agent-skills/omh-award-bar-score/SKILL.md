---
name: "omh-award-bar-score"
description: "[omh] Aiming for design-award quality: score a web surface against published design-award judging axes and name the binding constraint. Use when the user says: award-bar-score, award bar score, award winning, award-winning, award winning website, award-winning website, award winning design, award ready."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: award-bar-score
    role: operator
    quality_tier: design-orchestration-gated
---

# Award Bar Score

This is an OMH `award-bar-score` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`award-bar-score` gives "make it award-winning" a measurable meaning: published axes, published weights, a published threshold, and the one axis holding the surface below it — instead of a taste argument nobody can settle.

## Do Not Use When

- The request is broad premium quality across decks, PDFs, or posters; use `omh-design-quality-gate`.
- The request is frontend implementation, layout, or design-system work; use `omh-frontend`.
- The request is WCAG, keyboard, or screen-reader conformance; use `omh-accessibility-audit`.
- The request is a rendered capture or a pixel verdict; use `omh-visual-qa`.
- The award is a business, sales, or team award with no judged web surface.

## Examples

Good example:

- Prompt: score our landing page against the css design awards bar and tell me what is holding it back
- Expected behavior: Prepare award_bar_score/v1 with per-axis UI/UX/innovation scores from rendered evidence, the weighted total against the 8.0 threshold, the binding constraint, and the accessibility/performance tradeoff ledger.
- Why: The request asks for a measured comparison against a published external bar, not a general polish pass.

Bad example:

- Prompt: award-bar-score confirm this site will win website of the day
- Expected behavior: Score the axes against the published model and refuse the outcome claim; a jury scores submissions and OMH does not.
- Why: A rubric self-assessment cannot predict a jury result.

## Completion Checklist

- Each of UI, UX, and innovation carries its own score and the rendered evidence it was read from.
- The weighted total is computed from the stated weights and compared against the published threshold.
- The binding constraint names one axis and what moving it requires.
- Any innovation move that costs accessibility or performance budget is recorded as a tradeoff the user chooses.
- No award, jury, placement, or selection outcome is claimed.

## Recovery Notes

- If no rendered evidence exists, keep every axis not_observed and route the capture to visual-qa before scoring.
- If the award body publishes no weights, score the axes separately and report the total as unweighted rather than inventing a ratio.



## When to Use

Use when a web surface must be judged against an external award bar: per-axis scores for UI, UX, and innovation, the weighted total against the published threshold, and the one axis holding the score down.

    Strong routing signals: `award-bar-score`, `award bar score`, `award winning`, `award-winning`, `award winning website`, `award-winning website`, `award winning design`, `award ready`, `make it award winning`, `design award`, `design awards`, `css design awards`, `cssda`, `awwwards`, `site of the day`, `website of the day`, `wotd`, `score my site`, `어워드`, `디자인 어워드`, `어워드 수준`, `수상작 수준`, `수상 가능한 디자인`, `어워드 받을만한`, `올해의 사이트`

## Catalog Metadata

Category: `materials`
Phase: `award-bar-score`
Quality tier: `design-orchestration-gated`
Reasoning demand: `standard`

Quality bar:

- Score each axis separately with named rendered evidence, then compute the weighted total; an overall impression is not a score and hides which axis is failing.
- Reserve binding-constraint language for a total within about 0.3 of the threshold. Measured axis spread is roughly a twentieth of site spread, so further below the bar a weak axis is a symptom: report that the site needs a level change, never a one-axis fix.
- Load `references/award-judging-model.md` for the published axes, weights, and thresholds, the measured per-axis score table, and the stack table that separates entry-fee craft (fluid type, real typography) from optional spend (WebGL).
- Record what an innovation move costs on the accessibility and performance budgets before recommending it; half the sampled motion-heavy winners drop `prefers-reduced-motion`, and the two highest-scoring entries keep it, so never present the inaccessible path as the higher-scoring one.

Required inputs:

- the target URL, route, or rendered capture being judged
- the award model and its published axes, weights, and threshold
- the surface's own accessibility and performance budgets
- audience and primary user task

Expected outputs:

- award_bar_score/v1
- per-axis scores with named evidence for UI, UX, and innovation
- the weighted total and its distance from the published threshold
- the binding constraint: the axis whose gain moves the total most
- tradeoff_ledger/v1 when an innovation move costs accessibility or performance budget
- downstream route: frontend, accessibility-audit, visual-qa, or design-quality-gate

Artifact expectations:

- award_bar_score/v1 with prepared_not_observed status
- every axis score cites the rendered evidence it was read from, or stays not_observed
- the weighted total is arithmetic over the stated weights, never an impression
- no claim that a submission would win, place, or be selected

Safety rules:

- A self-assessment against a published rubric is never an award, a jury outcome, or a prediction of one; juries score submissions, and OMH does not.
- Never score an axis without rendered evidence; an unrendered page keeps every axis not_observed.
- Quote axis weights and thresholds only from the award body's published rules, and name the body and the date they were read.
- Accessibility and performance budgets outrank the innovation axis; when a move breaks one, record the tradeoff and let the user choose rather than defaulting to the score.
- Do not call a browser, network service, screenshot tool, or executor from OMH core.

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
