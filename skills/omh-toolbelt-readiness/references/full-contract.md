# Toolbelt Readiness

Load this on-demand contract after the compact `toolbelt-readiness` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- One named integration needs assessing end to end before adoption; use `omh-external-connector-readiness`.
- The question is which coding owner should run the work; use `omh-executor-runtime-readiness`.
- The user wants a tool installed, a credential validated, or a connector called now; the card names that step and who runs it, and performs none of them.

## Examples

Good example:

- Prompt: toolbelt-readiness what MCP or CLI tools do I need for weekly Linear and GitHub triage?
- Expected behavior: Produce `prepare_toolbelt_readiness` with required context, wrapper actions, and not-evidence boundaries.
- Why: Linear and GitHub triage needs two read credentials and matching MCP servers or CLIs, listed before the first run.

Bad example:

- Prompt: toolbelt-readiness claim Gmail access works without an observed credential check.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- toolbelt-readiness/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- toolbelt-readiness/v1 metadata-only runtime or wrapper card when recorded
