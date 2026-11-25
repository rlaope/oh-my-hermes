# Deliverable Package

Load this on-demand contract after the compact `deliverable-package` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- Planning a deck, PDF, workbook, or document from source inputs before any file exists (its outline, target formats, and QA ladder); use `omh-materials-package`.
- A text-only report, executive brief, or slide outline with no file to produce; use `omh-report-package`.

## Examples

Good example:

- Prompt: deliverable-package the deck and PDF are generated; check they were rendered, get my approval of v2, and tell me whether the PDF was attached to the thread.
- Expected behavior: Produce `prepare_deliverable_package` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: deliverable-package tell the client the PDF is attached.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- deliverable-package/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- deliverable-package/v1 metadata-only runtime or wrapper card when recorded
