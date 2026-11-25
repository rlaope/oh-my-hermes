# Plan

Load this on-demand contract after the compact `plan` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- The change is risky or architectural and the user wants alternatives compared, a risk review and a recorded decision; use `ulw-plan`, and keep this skill for the ordinary plan.
- Requirements are too vague to list non-goals or acceptance criteria; use `ulw-interview`.
- The direction is decided and what is missing is the phase-by-phase refactor shape; use `omh-refactor-plan`.

## Examples

Good example:

- Prompt: plan: add CSV export to the reports page; admins only, and it must stream 100k rows.
- Expected behavior: Write goals, non-goals, risks, tasks with ids, dependencies and done checks, a closing gate, and the acceptance criteria; hand back for acceptance before any handoff.
- Why: A feature with real acceptance questions needs a plan the user accepts before any code moves.

Bad example:

- Prompt: plan: fix the null check in parse_user (one line, the test already exists)
- Expected behavior: Make the edit directly and run the test; a plan adds a round trip with nothing to decide.
- Why: One bounded edit with a known check has no goals or tradeoffs to write down.

## Full Input, Output, and Artifact Expectations

Required inputs:

- requirements
- constraints
- known facts
- non-goals

Expected outputs:

- plan
- acceptance criteria
- verification strategy

Artifact expectations:

- plan artifact when durable execution will follow, via `omh hermes plan --record --plan-file <file> "<task>"`
