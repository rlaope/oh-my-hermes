# Iac Change

Load this on-demand contract after the compact `iac-change` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The ask is shipping a new version of the application and watching its health signals after the deploy; use `omh-deploy-and-monitor`.
- The ask is deciding a versioned release -- what goes in, its tag, or its canary -- rather than changing declared infrastructure; use `omh-release-cut`.
- The ask is choosing and deploying a model-serving engine; use `omh-inference-serving`.
- Production is down or degraded right now and the ask is command of the incident; use `omh-live-incident-response`.

## Examples

Good example:

- Prompt: terraform plan shows drift in the kubernetes cluster, stage the apply
- Expected behavior: Separate the drift from a refresh-only plan, read the saved plan's creates, replacements and destroys, give the cost delta or mark it unestimated, and stage the apply from staging to production with a rollout-status gate and a rollback per stage.
- Why: Applying over unresolved drift changes resources nobody meant to touch.

Bad example:

- Prompt: just run terraform apply -auto-approve in prod, the plan looked fine yesterday
- Expected behavior: Refuse the fresh apply: re-plan, save the plan, read its replacements and destroys, and apply that saved plan behind a health gate.
- Why: Yesterday's plan is not today's apply; drift and other merges change what a fresh apply does.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the tool and the unit of change: the Terraform workspace or stack, the cluster and namespace, or the Helm release
- the environments the change reaches, in promotion order
- the observed plan or diff output for the change, saved to a file where the tool allows it
- the health signal each environment already exposes: rollout status, probes, error rate, or a smoke check
- observed output for any drift, apply, health, or rollback claim

Expected outputs:

- drift_assessment/v1
- blast_radius/v1
- cost_delta/v1
- staged_apply_plan/v1
- health_gate/v1
- rollback_plan/v1

Artifact expectations:

- drift_assessment/v1 separates drift already present between state and the running infrastructure from the change being proposed, from a refresh-only plan or a live diff, and names who resolves each drifted resource before the apply
- blast_radius/v1 lists every resource the saved plan creates, updates in place, replaces, or destroys, calls out each replacement or destroy of a stateful resource, and names what depends on it
- cost_delta/v1 gives the monthly delta from an observed estimate for the saved plan, or marks the delta unestimated and names the resources that drive it
- staged_apply_plan/v1 orders the stages from the least to the most exposed environment and applies the reviewed saved plan, never a fresh one
- health_gate/v1 names, per stage, the observed signal that promotes it -- rollout status, a follow-up plan with no changes, an error rate -- and the value that stops it
- rollback_plan/v1 names, per stage, the command or revert that undoes it and what cannot be undone, such as a destroyed volume or a rotated resource id
