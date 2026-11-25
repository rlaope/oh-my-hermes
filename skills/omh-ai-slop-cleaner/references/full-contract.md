# Ai Slop Cleaner

Load this on-demand contract after the compact `ai-slop-cleaner` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The goal is new or changed behavior rather than removing existing code; a plain refactor, feature, or fix request belongs to `ulw-work`.
- The cleanup would change architecture or module boundaries and needs its execution shaped into phases first; use `omh-refactor-plan`, or `ulw-plan` when the direction itself is still contested.
- The user wants code judged for bugs or merge readiness with no drafted slop removal to inspect; use `omh-code-review` for a bug-first review and `omh-failure-signal-audit` for swallowed failures.
- The user asks to simplify their own recent changes, a commit, or the staged diff with a reuse, quality, and efficiency pass rather than a behavior-locked removal of existing code; load Hermes' bundled `simplify-code` skill for that instead of this one.

## Examples

Good example:

- Prompt: $ai-slop-cleaner remove duplicated router branches and lock behavior with regression tests before refactoring.
- Expected behavior: Plan cleanup, preserve behavior, delete or simplify code, and prove it with targeted tests.
- Why: The request is maintenance cleanup with regression risk.

Bad example:

- Prompt: ai-slop-cleaner: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `ai-slop-cleaner`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Full Input, Output, and Artifact Expectations

Required inputs:

- target smell, or a scoped file list when the user has not named one
- current behavior
- regression checks

Expected outputs:

- smell inventory naming each finding's category before any edit
- small cleanup diff, one pass at a time
- before/after verification
- closing report: changed files, simplifications, behavior lock, remaining risks

Artifact expectations:

- cleanup plan and regression evidence for non-trivial work
