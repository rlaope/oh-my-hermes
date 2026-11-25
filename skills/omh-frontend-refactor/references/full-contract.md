# Frontend Refactor

Load this on-demand contract after the compact `frontend-refactor` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The target is not UI code, or the smell is generic slop, duplication, or dead code outside a component tree; use `omh-ai-slop-cleaner`.
- The user wants new UI built or redesigned rather than restructured; use `omh-frontend`.
- The user wants findings and a verdict without changing the code; use `omh-code-review`.
- The restructuring crosses module boundaries or changes architecture beyond the component tree; use `omh-refactor-plan` for the phased execution shape, or `ulw-plan` first when the direction itself is still contested.

## Examples

Good example:

- Prompt: This dashboard component is 800 lines and has six useState booleans - refactor it without changing behavior.
- Expected behavior: Preview first: characterization-test gate, then a plan that folds the booleans into one state union, extracts along change reasons found by the scroll test, and lists per-change line refs with safety reasons; apply only as the explicit second step.
- Why: Oversized component plus flag-cluster state is exactly the impact-ordered, behavior-locked restructuring this workflow owns.

Bad example:

- Prompt: Refactor and also add the dark-mode feature while you are in there.
- Expected behavior: Split the request: the behavior-preserving refactor runs under this workflow, and the dark-mode feature goes to `omh-frontend` as separate planned work.
- Why: A refactor that changes behavior cannot claim behavior preservation; mixing the two hides the feature from review.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the target files or component, and the framework in use
- current behavior evidence: tests, or the characterization checks to write first
- the diff budget: micro pass only, one macro tier, or full ladder

Expected outputs:

- preview change plan with per-change line refs, before/after, safety reason, and category counts
- impact-ordered pass selection naming what is deferred and why
- characterization-test gate verdict before any macro change
- apply-step handoff with the unsafe-in-isolation changes listed under notes, never half-applied

Artifact expectations:

- metadata-only runtime record when a wrapper or shell is available
