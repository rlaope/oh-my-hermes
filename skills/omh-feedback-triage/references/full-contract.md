# Feedback Triage

Load this on-demand contract after the compact `feedback-triage` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request already contains an accepted product decision and asks for implementation.
- There are no feedback items, source boundary, or product area to classify.
- The user wants current market research rather than triage of supplied signals.
- The triage result asks for a retention or activation intervention rather than another cluster; use `omh-lifecycle-growth`.
- The supplied material is opportunity records and the request is portfolio health or forecast review; use `omh-sales-pipeline-review`.
- The request is one reproducible bug with a fix asked for, not a set of reports to cluster; use the coding handoff.

## Examples

Good example:

- Prompt: Cluster these customer payment failure reports and feature requests before we plan fixes.
- Expected behavior: Cluster bug signals and feature asks, rank severity or opportunity, and recommend research, planning, or coding as a next workflow.
- Why: The input is mixed feedback that needs classification before delivery decisions.

Bad example:

- Prompt: feedback-triage implement the accepted billing fix now.
- Expected behavior: Route to planning or coding handoff instead of re-triaging.
- Why: The decision is already accepted, so triage would add delay without improving evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- feedback items or summary
- source boundary
- product area

Expected outputs:

- clusters
- severity or opportunity ranking
- next workflow recommendation
- product_evidence_loop/v1

Artifact expectations:

- feedback triage record when a wrapper captures it
