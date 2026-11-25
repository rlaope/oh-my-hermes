# Decision Recall

Load this on-demand contract after the compact `decision-recall` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user asks what was decided or why an approved decision was made; recall it with the omh_memory tool's recall action, because only decisions a person rejected are stored here.

## Examples

Good example:

- Prompt: Show rejected decisions for this project before we choose an alternative.
- Expected behavior: Produce `show_rejected_decision_recall` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: Claim the recalled rejected decision is an approved memory write or proof the replacement ran.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- rejected_decision_recall/v1
- scoped rejected-decision matches
- claim boundary

Artifact expectations:

- rejected_decision_recall/v1 metadata-only recall result
