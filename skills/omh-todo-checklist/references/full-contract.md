# Todo Checklist

Load this on-demand contract after the compact `todo-checklist` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The work is one step, already finished, or answerable in this turn; a checklist that never advances is a panel of noise.
- The user wants an accepted implementation plan split into parallel lanes with owners and verification commands; use `ulw-work`.
- The user wants the planning content itself -- options, risks, acceptance criteria before execution; use `ulw-plan`.
- The user is asking what coding work is running right now rather than what the plan says; use `omh-running-work-board`.

## Examples

Good example:

- Prompt: declare a plan checklist for this migration so I can see where you are
- Expected behavior: Declare numbered phases in delivery order with one task per observable outcome, exactly one active, and update states as work completes.
- Why: The user wants the HUD checklist itself, for work that spans turns, without starting a delivery engine.

Bad example:

- Prompt: add a TODO comment above this function
- Expected behavior: Edit the code; the plan todo panel has nothing to do with a source comment.
- Why: `todo` is an everyday word in a coding session and this use of it is not a plan checklist.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the work to be tracked

Expected outputs:

- a declared checklist with exactly one active item
- explicit states as work completes

Artifact expectations:

- metadata-only `omh_todo/v1` plan todo owned by the declaring session
