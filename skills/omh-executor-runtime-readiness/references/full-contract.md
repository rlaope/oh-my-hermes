# Executor Runtime Readiness

Load this on-demand contract after the compact `executor-runtime-readiness` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- A named plugin or API to adopt; use `omh-external-connector-readiness`.
- Which tool or credential is missing for work already chosen; use `omh-toolbelt-readiness`.

## Examples

Good example:

- Prompt: executor-runtime-readiness can this task run in Codex, Claude Code, or Hermes coding?
- Expected behavior: Produce `prepare_executor_runtime_readiness` with required context, wrapper actions, and not-evidence boundaries.
- Why: The choice depends on which CLI is on PATH and the flags it accepts.

Bad example:

- Prompt: executor-runtime-readiness claim Codex already started the session.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- executor-runtime-readiness/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- executor-runtime-readiness/v1 metadata-only runtime or wrapper card when recorded
