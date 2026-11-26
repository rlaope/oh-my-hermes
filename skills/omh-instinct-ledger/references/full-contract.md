# Instinct Ledger

Load this on-demand contract after the compact `instinct-ledger` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- A single missed route or one run's trace; use `omh-workflow-learning` first.
- Writing reviewed lessons into AGENTS guidance, prompts, or skills; use `omh-rules-distill`.
- A run that is stuck right now; use `omh-agent-debug` before drawing a lesson from it.

## Examples

Good example:

- Prompt: instinct-ledger turn these repeated OMH review lessons into project-scoped instincts and show which ones could be promoted globally.
- Expected behavior: Produce `prepare_instinct_ledger` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: instinct-ledger silently install hooks, learn from every prompt, and mutate all skills globally.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- instinct_ledger_plan/v1
- instinct_candidate/v1
- project_instinct_scope_map/v1
- instinct_promotion_review/v1
- instinct_export_review/v1 when requested

Artifact expectations:

- instinct_candidate/v1 with trigger, action, confidence, domain, scope, source evidence, non-goals, and review state
- project_instinct_scope_map/v1 separating project, global, imported, and promotion-candidate instincts
- instinct_promotion_review/v1 with repeated evidence, confidence threshold, conflicts, and approval state
- instinct_export_review/v1 with redaction, destination, import/export trust gaps, and raw-observation exclusion when requested
