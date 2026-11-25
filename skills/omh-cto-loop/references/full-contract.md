# Cto Loop

Load this on-demand contract after the compact `cto-loop` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is a settings-only change, one bounded edit that is explicitly low-risk and has a direct owner and verification path, or a direct answer/diagnosis; handle it directly or use `omh-decide` for a decision brief instead of starting a leadership operating loop.
- A launch-readiness audit of one named service or release with deploy, security, observability and rollback evidence; use `omh-production-audit`. Prioritisation and risk ranking across workstreams stays here.
- An accepted plan is ready for build; use `ulw-work` or `omh-idea-to-deploy`.

## Examples

Good example:

- Prompt: cto-loop: run the PM, dev, QA, security, and ops loop for this risky billing launch.
- Expected behavior: Prepare the CTO operating model with role responsibilities, gates, blockers, and status boundaries.
- Why: The request needs a leadership operating loop, not just a generic plan.

Bad example:

- Prompt: Tell me whether we should rewrite the billing service in Rust.
- Expected behavior: Route to `omh-decide`, not `cto-loop`: one decision between options is a decision brief.
- Why: A single decision with options does not need a multi-function leadership operating loop.

## Full Input, Output, and Artifact Expectations

Required inputs:

- operating signals
- roadmap or release scope
- known risks
- decision owner

Expected outputs:

- priority frame
- architecture tradeoffs
- delivery risks
- decision note
- follow-up handoff candidates

Artifact expectations:

- leadership loop record or status summary when a wrapper captures decisions and follow-ups
