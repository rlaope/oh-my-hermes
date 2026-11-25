# Deploy And Monitor

Load this on-demand contract after the compact `deploy-and-monitor` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- An incident has already been declared and the work is commanding it -- severity, commander, running timeline, recovery verification -- rather than watching a release; use `omh-live-incident-response`.
- The ask is deciding a release before it ships -- what goes in, its version and tag, the canary stages, or which command rolls it back; use `omh-release-cut`, which writes the rollback trigger down before it is needed.
- The change is to declared infrastructure itself -- a Terraform plan, a Kubernetes manifest, a Helm chart -- and needs its drift, blast radius, and cost delta read before it is applied; use `omh-iac-change`.

## Examples

Good example:

- Prompt: deploy-and-monitor: prepare the release monitor, rollback signals, health checks, and post-deploy status card.
- Expected behavior: Create release monitoring guidance with deployment, metric, rollback, and observation boundaries.
- Why: The request is about deploy readiness and monitoring rather than code review alone.

Bad example:

- Prompt: deploy-and-monitor: ship it and tell me when it is healthy.
- Expected behavior: Refuse a health claim; name the missing baseline, signals, window, and rollback owner.
- Why: Healthy with no baseline is whatever the dashboard shows after the fact.

## Full Input, Output, and Artifact Expectations

Required inputs:

- release scope
- environment
- health signals
- rollback owner

Expected outputs:

- pre-deploy checklist
- deploy decision gate
- monitoring watchlist
- rollback criteria
- post-deploy status boundary

Artifact expectations:

- release operation status record when the wrapper captures deploy or monitor observations
- web_qa_comparison/v1 for a canary only with a trusted host_deployment_observation/v1 and a production baseline captured before it
