# Workflow Learning

Load this on-demand contract after the compact `workflow-learning` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- A lasting fact the user wants kept; capture it with `omh-memory-new`.
- Lessons seen across runs or projects to score and promote; use `omh-instinct-ledger`.
- A run that is stuck or looping right now; use `omh-agent-debug`.

## Examples

Good example:

- Prompt: workflow-learning route this self-improvement note before deciding whether it is memory, skill, wiki, failure-retrospective, or automation material.
- Expected behavior: Produce `record_workflow_learning_trace` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: workflow-learning silently patch the skill and claim future behavior is fixed.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- workflow-learning/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- workflow-learning/v1 metadata-only runtime or wrapper card when recorded
- browser_skill_promotion_approval_receipt/v1 per operation: `promotion diff` then `approve --reviewed-diff-digest --reviewer`; source `learning promotion --source-id sd-<id>` (reviewed draft) or `web-qa promotion --trace-id bwt-<id>`
