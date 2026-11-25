# Running Work Board

Load this on-demand contract after the compact `running-work-board` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user wants to start, plan, or dispatch coding work rather than observe it.
- The user wants to create or change tasks on an agent board, or to coordinate profiles; use `omh-agent-board`.
- The user wants review, CI, or merge evidence, which a status board never provides.
- The user is asking about their own application's runtime status rather than OMH coding units.

## Examples

Good example:

- Prompt: what is running right now
- Expected behavior: One line per unit: label, runtime, model, status, elapsed, tokens, with unknown printed where nothing was observed.
- Why: The request is about observed local coding activity, not about starting work.

Bad example:

- Prompt: is the deploy done and did CI pass
- Expected behavior: Route to verification or CI evidence instead of the activity board.
- Why: Observed activity is not result, review, CI, or merge evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- local coding artifacts
- on Hermes, this conversation's `omh_hud` rows

Expected outputs:

- per-unit runtime and model
- observed tokens and elapsed
- on Hermes, delegate children and kanban workers, labelled by source
- explicit unknowns

Artifact expectations:

- metadata-only status board projection from local artifacts
