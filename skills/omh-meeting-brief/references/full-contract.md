# Meeting Brief

Load this on-demand contract after the compact `meeting-brief` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user needs observed meeting minutes, decisions, or action items but has not provided notes.
- The request is strategy synthesis without a meeting audience, agenda, or decision ceremony.
- The follow-up is implementation work that already has accepted requirements and should become a plan or handoff.
- The user wants minutes, scrum history or a decision log for a recurring meeting; use `omh-operating-rhythm`.
- The meeting already happened, its notes or transcript are in hand, and the user wants decisions, owners, follow-ups, or tickets drawn from them; load Hermes' bundled `meeting-action-items` skill instead of this one.

## Examples

Good example:

- Prompt: Prepare a meeting agenda for a leadership sync on setup UX, plugin bridge defaults, and release risk.
- Expected behavior: Prepare agenda topics, prompts, decisions needed, and a record template with unknowns marked.
- Why: The request is preparation for a meeting and should separate prep from observed outcomes.

Bad example:

- Prompt: meeting-brief summarize what the team decided yesterday.
- Expected behavior: Ask for meeting notes or route to an ops/status summary with explicit evidence gaps.
- Why: A prepared agenda cannot be treated as observed minutes or decisions.

## Full Input, Output, and Artifact Expectations

Required inputs:

- meeting goal, date and length
- audience
- known context
- decision topics and who decides

Expected outputs:

- agenda
- discussion prompts
- decisions needed
- action-item template

Artifact expectations:

- meeting brief or record template when the wrapper captures it
