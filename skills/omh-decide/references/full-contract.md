# Strategy Brief

Load this on-demand contract after the compact `strategy-brief` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- A technical choice one cheap experiment can settle; use `omh-decision-prototype`. A technical choice inside a plan being written; use `omh-plan`. A technical choice the user wants attacked; use `omh-adversarial-consensus`. Use this skill for the decision note and ADR once the options are known.
- The strategic question is whether an early idea's customer problem and segment are real, and no validated discovery receipt exists yet; use `omh-product-discovery-validation`.
- The question is how to run a hiring process — scorecards, interview loops, candidate comparison — rather than whether to hire at all; use `omh-people-ops`.
- The user wants Jev's typed probabilities for a yes/no, pick-one, or scored question over supplied text rather than tradeoffs and a recommendation; use `omh-jev-ask`.

## Examples

Good example:

- Prompt: strategy-brief: decide whether our onboarding should prioritize solo founders or enterprise buyers.
- Expected behavior: Frame options, tradeoffs, assumptions, rejected paths, and the decision evidence needed.
- Why: The request is strategy-shaped and should not jump directly into implementation.

Bad example:

- Prompt: strategy-brief: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `strategy-brief`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Full Input, Output, and Artifact Expectations

Required inputs:

- goal
- known evidence
- constraints
- decision owner

Expected outputs:

- options
- tradeoffs
- recommended direction
- decision note

Artifact expectations:

- strategy brief or decision note when a wrapper captures it
