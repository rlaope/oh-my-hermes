# Release And Rollback Method

Load this while deciding a release or a rollback. OMH prepares; the host, CI, or an operator tags, publishes, deploys, and rolls back, and each step is `prepared` until its output is observed.

## 1. Scope and version

- List the changes since the last tag and sort them into breaking changes, features, and fixes.
- Semantic versioning: any breaking change is a major, otherwise any feature is a minor, otherwise a patch. A pre-1.0 project states its own rule.
- Hold back what is not ready behind a flag or out of the branch, and say which.

## 2. The cut sequence

| Order | Step | Failure it prevents |
| --- | --- | --- |
| 1 | Land the prep change: changelog entry, and any version surface that gained a check | a bump that leaves a surface behind and turns the release branch red |
| 2 | Freeze the release branch: nothing merges until the tag is pushed | a merge in the window breaks the atomic push of the bump commit and the tag |
| 3 | Run the cut (a release workflow or command) that bumps every version surface, runs the suite on the bumped tree, and pushes the bump commit and the tag atomically | a tag that points at a tree nobody tested |
| 4 | Pass the approval gate (a protected environment or a manual approval) | an unreviewed publish |
| 5 | Publish, then check each channel moved: package registry, container registry, installers, site | a release visible on one channel and missing on another |
| 6 | Curate the notes on top of the generated change list | a list of titles nobody can act on |

Wait for the release branch's own CI on its last merge before starting the cut. After the cut, compare every version surface against the tag.

## 3. Rollout stages

| Stage | Traffic | Bake time | Promote when |
| --- | --- | --- | --- |
| Canary | 1-5% or one instance | long enough to cover one traffic peak | error rate, latency, and saturation stay inside the stated range against the baseline |
| Partial | 25-50% | one more peak | the same signals hold with more load |
| Full | 100% | until the rollback window closes | the previous artifact may be retired |

Promotion reads a named signal against a threshold. A clock alone is not a promotion criterion. A stage also states the minimum number of requests it must serve before the signal is read: zero failures in 300 requests only bounds the true failure rate below about 1% at 95% confidence. When traffic cannot reach that count inside the bake time, call the canary coarse and widen the stage or extend the bake.

## 4. Rollback trigger and command

A rollback trigger is a signal, a threshold, and a window: "5xx rate above 1% for 5 minutes against the canary cohort". The command is the literal line that performs it, and it names who may run it.

| Mechanism | Command shape | Cannot undo |
| --- | --- | --- |
| Redeploy the previous artifact | `kubectl rollout undo deployment/<name>`, or redeploy the previous image tag | data the new version already wrote, and config or secrets changed in the same release (roll those back with the same trigger) |
| Traffic shift | set the canary weight to 0 | nothing, while the old version still runs |
| Feature flag | turn the flag off | side effects already emitted |
| Revert and re-release | revert the merge, then cut a patch | a published package: yank or deprecate it, never delete and reuse the version |

A rollback that crosses a schema migration needs the migration to be backward compatible (expand before contract), or the rollback is a restore, and the plan says which.
