# Adversarial Consensus

Load this on-demand contract after the compact `adversarial-consensus` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user wants the plan itself, with options, acceptance criteria, and verification commands; use `ulw-plan`, which this workflow feeds.
- The request is still too ambiguous to state the proposal being attacked; use `ulw-interview` first.
- The user wants completed code reviewed for defects rather than a proposal attacked before it is built; use `omh-code-review`.
- The user wants hostile runtime scenarios against a built change; use `ulw-qa`.
- One perspective would do: a small local change with no contested decision does not earn three rounds.

## Examples

Good example:

- Prompt: $adversarial-consensus we plan to move session state into Redis before the launch — attack it from every angle before I write the plan.
- Expected behavior: Name the roster and their distinct angles, take blind findings from each, run one attack-only round, resolve each objection to defend/refine/concede, distill only into the four buckets, and hand the bundle to `ulw-plan` as planning input.
- Why: The decision is contested and pre-plan, which is exactly where independent objections are worth more than one planner's confidence.

Bad example:

- Prompt: $adversarial-consensus give me the migration plan with the steps and the rollout order.
- Expected behavior: Produce the distilled bundle and hand it to `ulw-plan`; the steps and rollout order are the planner's output, not this workflow's.
- Why: The bundle is INPUT to planning. Emitting a plan here skips the reviewed-plan gate and turns the buckets into a task list.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the proposal, plan draft, or direction under review
- the decision the review must inform
- known constraints and non-negotiables
- the perspective roster and why each angle is distinct

Expected outputs:

- per-perspective independent findings
- cross-attack objections attributed to their author
- defend, refine, or concede verdict per objection
- distilled bundle in the fixed buckets Hard Constraints, Decisions, Risks, Open Questions
- mandatory planner handoff naming the follow-on planning workflow

Artifact expectations:

- record the distilled bundle with `omh hermes plan --record --plan-file <bundle.md> --input-bundle "<proposal>"`, which writes it as `hermes_plan_input/v1` (planning input, marked INPUT TO PLANNING, NOT A PLAN) beside the plans, and which `omh hermes plan-accept` refuses; never record it without `--input-bundle`, because that stores a draft plan scaffold with canned goals and options
