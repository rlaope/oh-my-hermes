# Ops Review

Load this on-demand contract after the compact `ops-review` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The review is over sales stages, forecast categories, deal aging, or seller forecast rather than generic operating status; use `omh-sales-pipeline-review`.
- The primary output is durable cadence history, minutes, a decision log, or action history; use `omh-operating-rhythm`.
- The user wants a recurring personal or calendar weekly reset across tasks and inbox rather than a team operating-status brief; load Hermes' bundled `weekly-review-planning` skill instead of this one.

## Examples

Good example:

- Prompt: ops-review: summarize this week’s support queue, release blockers, owner status, and next operating risks.
- Expected behavior: Create an operations status review with owners, blockers, evidence gaps, and next actions.
- Why: The request is an operating review rather than a one-off plan or coding handoff.

Bad example:

- Prompt: ops-review: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `ops-review`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Full Input, Output, and Artifact Expectations

Required inputs:

- status evidence
- scope
- time window
- known risks

Expected outputs:

- status summary
- risks
- blockers
- priorities
- follow-up actions

Artifact expectations:

- ops review record or status artifact when a wrapper captures it
