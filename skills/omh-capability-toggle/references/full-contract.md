# Capability Toggle

Load this on-demand contract after the compact `capability-toggle` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user wants to run the workflow a family owns rather than change whether that family is offered.
- The user is asking to build an on/off switch inside their own product.
- The user wants OMH removed entirely, which is the uninstall path rather than a capability policy change.
- The user wants one skill hidden on one messaging platform or everywhere; that is Hermes' own hermes skills config, an interactive command the person runs in a terminal, and OMH writes no Hermes config.

## Examples

Good example:

- Prompt: turn off memory, I already run my own memory system
- Expected behavior: Run `omh capability-policy disable retain_knowledge`; report the four memory workflows withheld, memory off, the five core skills retained, and the enable command.
- Why: The request is about which OMH surfaces are offered locally, not about capturing a memory.

Bad example:

- Prompt: add a dark mode toggle to my settings page
- Expected behavior: Route to `omh-frontend` or coding delegation instead of capability policy.
- Why: That is a feature in the user's own product, not an OMH capability family.

## Full Input, Output, and Artifact Expectations

Required inputs:

- capability family
- requested state

Expected outputs:

- policy change summary
- what was withheld versus retained
- the exact command that reverses it

Artifact expectations:

- capability policy recorded in the local setup profile
