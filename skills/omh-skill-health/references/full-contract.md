# Skill Health

Load this on-demand contract after the compact `skill-health` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- OMH setup, install, or a skill that does not load; use `omh-doctor`.
- One run that missed a route or went wrong; use `omh-workflow-learning`.
- Finding a new skill to adopt; use `omh-skill-scout`.

## Examples

Good example:

- Prompt: skill-health show the OMH skill portfolio dashboard with stale surfaces, failure patterns, pending amendments, and top improvement actions.
- Expected behavior: Produce `prepare_skill_health` with required context, wrapper actions, and not-evidence boundaries.
- Why: Drift comes from `lint_warnings` and, on Hermes, the curator ledger, not use counts.

Bad example:

- Prompt: skill-health claim every skill is working and patch the failures automatically without observed signals or review.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- catalog, generated, reference, harness, and capability-surface status
- observed failure signals, or an explicit statement that none were supplied
- pending amendment review slots and top safe actions with owner lane and verification path

Artifact expectations:

- skill_health_card/v1 metadata-only wrapper card recording surface status, observed-only failure signals, pending amendments, and the non-mutation boundary
