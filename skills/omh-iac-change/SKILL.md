---
name: "omh-iac-change"
description: "[omh] Infrastructure-as-code change: Terraform, OpenTofu, Pulumi, a Kubernetes manifest, a Helm chart; read the drift, the blast radius and the cost delta from the saved plan, then stage the apply behind a health gate with a rollback per stage. Use when the user says: iac-change, iac change, infrastructure as code, infrastructure-as-code, terraform plan, terraform apply, terraform state, terraform drift."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: iac-change
    role: planner
    quality_tier: staged-apply-gated
    related_skills: [omh-deploy-and-monitor, omh-release-cut, omh-inference-serving, omh-live-incident-response]
---

# Iac Change

Required: the tool and the unit of change: the Terraform workspace or stack, the cluster and namespace, or the Helm release, the environments the change reaches, in promotion order, the observed plan or diff output for the change, saved to a file where the tool allows it, the health signal each environment already exposes: rollout status, probes, error rate, or a smoke check, observed output for any drift, apply, health, or rollback claim. Output: drift_assessment/v1, blast_radius/v1, cost_delta/v1, staged_apply_plan/v1, health_gate/v1, rollback_plan/v1.

## Why This Exists

`iac-change` exists because infrastructure changes had no owner: `omh-deploy-and-monitor` watches an application release, `omh-release-cut` decides one, and `omh-inference-serving` deploys a model server, while a Terraform plan with drift, a Helm chart change, or a manifest edit reached a generic planner with no blast radius, cost delta, or staged apply at all.

## First Steps

- Ask for the saved plan or the diff output before assessing anything.
- Separate existing drift from the proposed change before ordering stages.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Coding handoff** - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when a change to declared infrastructure is about to be applied or has drifted: a Terraform, OpenTofu, Pulumi or CloudFormation plan, a Kubernetes manifest or kustomization, or a Helm chart or values change. The output is the drift between state and reality, the blast radius and cost delta read from the saved plan, and a staged apply where every stage has a health gate and a rollback; OMH applies nothing.

    Strong routing signals: `iac-change`, `iac change`, `infrastructure as code`, `infrastructure-as-code`, `terraform plan`, `terraform apply`, `terraform state`, `terraform drift`, `terraform module`, `terraform change`, `opentofu`, `tofu plan`, `pulumi`, `pulumi preview`, `pulumi up`, `cloudformation`, `cloudformation change set`, `helm upgrade`, `helm diff`, `helm chart`, `helm chart change`, `kubectl apply`, `kubectl diff`, `kustomize`, `kubernetes manifest`, `kubernetes manifests`, `k8s manifest`, `k8s manifests`, `infracost`, `drift detection`, `cost delta`, `staged apply`, `stage the apply`

## Catalog Metadata

Category: `planning`
Phase: `iac-change`
Hermes role: `planner`
Quality tier: `staged-apply-gated`
Reasoning demand: `standard`

Quality bar:

- Read the saved plan or diff before anything else; the blast radius is what the plan says, not what the change was meant to do.
- Load `references/iac-change-method.md` for the per-tool drift, plan, health and rollback commands and the replacement markers instead of recalling them.
- Resolve existing drift before the apply, so the apply changes only what the change meant to.
- Give every stage a health gate and a rollback; a stage with neither is not a stage.
- Keep prepared, applied, and verified as separate states for every stage.

Handoff policy:

Keep the drift assessment, blast radius, cost delta, staged apply plan, health gates and rollbacks in Hermes. Plan output, diffs, apply results, rollout status and cost estimates are recorded only from executor, operator, or wrapper observed output; OMH never runs terraform, tofu, pulumi, kubectl or helm, and any apply is the operator's.

Safety rules:

- Never promote a stage without its health gate observed; a prepared gate keeps the next stage blocked.
- A replacement or destroy of a stateful resource -- a database, a volume, a bucket, a load balancer address -- is a blocker for the user's explicit approval, not a line in the plan.
- Apply only the saved plan that was reviewed; a fresh apply can differ from what was read.
- Never hand-edit a state file or a live object to hide drift; import, move, or re-declare it, and say which.
- OMH never runs terraform, tofu, pulumi, kubectl, or helm, and never reads cloud credentials; every drift, cost, apply, and health fact comes from observed output or is marked unverified.

## Completion Checklist

- Existing drift is separated from the proposed change.
- Every replacement or destroy is listed, and each stateful one waits for explicit approval.
- The cost delta is observed or marked unestimated.
- Every stage names its health gate and its rollback.
- OMH ran nothing, and every fact cites observed output or is marked unverified.

## Recovery Notes

- If no saved plan exists, stop at the plan step and ask for one; do not assess from the diff of the code alone.
- If a resource cannot be rolled back, say so in its stage and ask for approval before that stage.

## Runtime Evidence

Preferred harness for this skill: `app-delivery-loop`.

```sh
omh runtime record --skill iac-change --harness app-delivery-loop --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
