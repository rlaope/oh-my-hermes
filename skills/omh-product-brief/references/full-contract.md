# Product Brief

Load this on-demand contract after the compact `product-brief` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The input is unprocessed feedback, bug reports, or feature asks that first need clustering and evidence boundaries; use `omh-feedback-triage`.
- The product evidence is unvalidated, synthetic, or a founder belief rather than external-human or behavioral-data evidence from the target segment (usage data, support contacts and interviews count); use `omh-product-discovery-validation` before a PRD.
- The input is a growth hypothesis that still needs an experiment and readout before it becomes a product requirement; use `omh-lifecycle-growth`.
- The user needs a company or product strategy decision across high-level options rather than a requirements or roadmap artifact; use `omh-decide`.
- The request is an accepted, code-ready change with repository constraints and verification needs; use `ulw-plan` or `ulw-work` rather than recreating a PRD.
- The user asks to create or update Jira, Linear, Aha!, or a roadmap system directly; use `omh-apps` with explicit target, approval, and observed evidence.

## Examples

Good example:

- Prompt: Create a PRD and prioritization options for reducing first-time user drop-off in onboarding.
- Expected behavior: Prepare the product problem, user and metric brief, PRD, roadmap options, tradeoffs, and downstream prerequisites.
- Why: The request needs a decision-ready requirements and prioritization artifact before delivery planning.

Bad example:

- Prompt: Implement the accepted onboarding PRD and open a PR.
- Expected behavior: Route to `ulw-work` or `ulw-plan`, not `product-brief`.
- Why: Accepted implementation work should move into planning or delivery rather than recreate a PRD.

## Full Input, Output, and Artifact Expectations

Required inputs:

- product evidence
- problem and user
- goal, non-goals, and success metric with baseline
- decision owner
- capacity or effort constraints

Expected outputs:

- problem, user, evidence, metric, goal, and non-goal brief
- PRD with requirements, open questions, risks, dependencies, and acceptance shape
- prioritization/roadmap options with tradeoffs and decision owner
- explicit downstream route to `ulw-plan`, `omh-decide`, or `ulw-work` only when its prerequisite is satisfied

Artifact expectations:

- prepared product brief or PRD when a wrapper captures it
