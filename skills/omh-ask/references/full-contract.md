# Ask

Load this on-demand contract after the compact `ask` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.
- The user wants typed yes/no, pick-one, or scored probabilities from Jev over supplied text; use `omh-jev-ask`.
- The user wants several perspectives to attack a proposal and a distilled constraint bundle; use `omh-adversarial-consensus`. Use this skill for one named outside advisor.

## Examples

Good example:

- Prompt: ask: ask Claude as an external advisor to critique this plugin bridge plan before implementation.
- Expected behavior: Prepare an advisor prompt, capture the response boundary, and summarize reusable critique.
- Why: The user wants outside review before committing to a direction.

Bad example:

- Prompt: ask: should I rename this variable?
- Expected behavior: Answer directly; no outside advisor would change the answer.
- Why: An outside critique is worth its cost only when it could change the decision.

## Full Input, Output, and Artifact Expectations

Required inputs:

- question
- context summary
- why external advice helps

Expected outputs:

- advisor summary
- accepted/rejected advice
- decision note

Artifact expectations:

- advisor transcript reference only when explicitly captured
