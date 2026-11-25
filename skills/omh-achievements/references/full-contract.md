# Achievements

Load this on-demand contract after the compact `achievements` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: achievements show my unlocked badges and what is closest to the next tier.
- Expected behavior: Produce `show_achievements_summary` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: achievements recompute my session history and grant the missing badges.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- hermes_achievements_observation/v1 summary or badge list
- recent unlocks and progress hints
- next action
- prepared-vs-observed boundary

Artifact expectations:

- hermes_achievements_observation/v1 metadata-only payload from `omh achievements` when recorded
- supplied `session_activity_receipt/v1` when available; unavailable metrics stay unavailable, never zero
