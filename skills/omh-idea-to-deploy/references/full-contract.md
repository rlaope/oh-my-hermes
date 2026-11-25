# Idea To Deploy

Load this on-demand contract after the compact `idea-to-deploy` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The task is already a concrete repo change whose stopping point is one PR-ready cycle, not product or release operations; use `ulw-work`.
- The request is a settings-only change, one bounded edit that is explicitly low-risk and has a direct owner and verification path, or a direct answer/diagnosis; handle it directly instead of opening a product delivery loop.

## Examples

Good example:

- Prompt: idea-to-deploy: turn this onboarding idea into a scoped plan, implementation handoff, QA gate, and release path.
- Expected behavior: Prepare the idea-to-release lane while keeping implementation, QA, and deploy evidence observed-only.
- Why: The request spans product shaping through deploy readiness instead of a single task.

Bad example:

- Prompt: idea-to-deploy: build the whole app and deploy it, I will check later.
- Expected behavior: Refuse the single jump: ask for the success metric and scope, then produce the stage rail with an owner per stage.
- Why: An unscoped build has no acceptance test and no rollback.

## Full Input, Output, and Artifact Expectations

Required inputs:

- product idea
- target user or customer signal
- success metric
- repo or app context

Expected outputs:

- stage rail
- decision gates
- executor handoff criteria
- verification and deploy/monitor status boundaries

Artifact expectations:

- app delivery loop status record when the wrapper captures stage acceptance or observations
