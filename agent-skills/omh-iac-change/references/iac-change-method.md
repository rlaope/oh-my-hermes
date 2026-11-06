# IaC Change Method

Load this while planning an infrastructure-as-code change. OMH prepares; the operator or the executor runs every command, and each step is `prepared` until its output is observed.

## 1. Per tool

| Tool | Drift | Saved plan or diff | Health gate | Rollback |
| --- | --- | --- | --- | --- |
| Terraform / OpenTofu | `plan -refresh-only` | `plan -out=tfplan`, then `show tfplan` | a follow-up `plan` reports no changes, plus the service's own signal | revert the commit and apply the prior configuration; a destroyed resource does not come back |
| Pulumi | `pulumi refresh --preview-only` | `pulumi preview --diff` | `pulumi preview` shows no changes | revert and `pulumi up` the prior program |
| CloudFormation | drift detection on the stack | a change set, reviewed before execution | stack reaches `UPDATE_COMPLETE` | automatic rollback on failure, or a new change set to the prior template |
| Kubernetes / kustomize | `kubectl diff` against the live objects | `kubectl diff -f` or `kustomize build` output | `kubectl rollout status` within a stated timeout | `kubectl rollout undo` for a workload; re-apply the prior manifest otherwise |
| Helm | `helm diff upgrade` (plugin) or `helm get manifest` | `helm diff upgrade` or `helm template` | `--wait` with a timeout, then the release's own probes | `helm rollback <release> <revision>` |

A saved plan is a secret-bearing artifact: Terraform writes sensitive values into the plan file in cleartext even when its terminal output hides them. Keep it where the state is kept, do not attach it to a pull request or paste it into chat, and share `show` output only after checking it for sensitive values.

What the listed rollbacks cannot undo: Helm CRDs and hook-created resources, PersistentVolumeClaim contents, a destroyed Terraform volume, a CloudFormation resource with `DeletionPolicy: Delete`, and config or secrets changed in the same release. Name the retain or snapshot policy before the stage runs.

## 2. Reading the blast radius

- Count creates, in-place updates, replacements and destroys from the saved plan, not from the code diff.
- A replacement (`-/+`, "must be replaced", `replace` in a change set) destroys and recreates: a database, a volume, a bucket, an address, or anything with an identity other resources reference is a blocker for explicit approval.
- A renamed resource with no `moved` block or import is a destroy and a create.
- List what depends on each replaced or destroyed resource: DNS, security groups, IAM bindings, persistent volume claims.

## 3. Drift before the change

Resolve drift first, one resource at a time: import it, move it, re-declare it, or revert the manual change. Record which. Before any state operation take a state snapshot (`terraform state pull > backup`, stored where the state is kept, since it is as sensitive as the state), confirm no other run is in progress (the backend lock is taken per command, not held across a session), and prefer a `moved` or `import` block in code (reviewable, and part of the saved plan) over `state mv`. An apply over unresolved drift silently reverts someone's hotfix or re-creates something deliberately removed.

## 4. Cost delta

Estimate against the saved plan (Infracost or the provider's calculator) and record the monthly delta with the resources that drive it. When no estimate was run, write `unestimated` and name those resources; a missing estimate is not a zero.

## 5. Staged apply

| Stage | Promotes on | Stops on |
| --- | --- | --- |
| lowest environment | its health gate observed | any gate failure; roll back that stage |
| each next environment | the previous stage's gate and its own | a gate failure, or a plan that differs from the reviewed one |
| production | every earlier gate, and explicit approval for any stateful replacement | as above |

Re-plan per environment and apply the saved plan for that environment. A stage without a health gate or a rollback is not a stage.
