# Award Bar Score

Load this on-demand contract after the compact `award-bar-score` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

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

## Full Input, Output, and Artifact Expectations

Required inputs:

- the target URL, route, or rendered capture being judged
- the award body (CSSDA or Awwwards) and its published axes, weights, and threshold
- the surface's own accessibility and performance budgets
- audience and primary user task

Expected outputs:

- award_bar_score/v1
- per-axis scores with named evidence for each axis the chosen body publishes (UI, UX and innovation for CSSDA)
- the weighted total and its distance from the published threshold
- the binding constraint: the axis whose gain moves the total most
- tradeoff_ledger/v1 when an innovation move costs accessibility or performance budget
- downstream route: `omh-frontend`, `omh-accessibility-audit`, `omh-visual-qa`, or `omh-design-quality-gate`

Artifact expectations:

- award_bar_score/v1 with prepared_not_observed status
- every axis score cites the rendered evidence it was read from, or stays not_observed
- the weighted total is arithmetic over the stated weights, never an impression
- no claim that a submission would win, place, or be selected
