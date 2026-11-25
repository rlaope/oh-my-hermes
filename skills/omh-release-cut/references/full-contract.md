# Release Cut

Load this on-demand contract after the compact `release-cut` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The rollout is already running and the ask is watching its health signals and post-deploy status; use `omh-deploy-and-monitor`.
- Production is down or degraded and the work is commanding the incident; use `omh-live-incident-response`.
- The ask is a readiness audit across observability, security, and operations before launch; use `omh-production-audit`.
- The ask is drafting the commit message or the pull request description for a change; use `omh-commit-pr-authoring`.
- The app ships through the App Store or Google Play -- signing, a TestFlight or Play testing-track beta, a phased release, a store hotfix; use `omh-mobile-release`.

## Examples

Good example:

- Prompt: cut a release and tag it
- Expected behavior: List what goes in and what is held, derive the version, and prepare release_plan/v1: freeze, bump every file that carries the version, tag, run the release workflow, pass its approval, publish, and curate notes, with rollback_trigger/v1 naming the signal, the threshold, and the exact command.
- Why: A release whose rollback is decided during the outage is a release with no rollback.

Bad example:

- Prompt: ship it, we will figure out rollback if something breaks
- Expected behavior: Keep the plan not ready, name the missing rollback trigger and command, and ask who runs it.
- Why: The rollback decision made under pressure is the one most likely to be wrong.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the changes since the last release, and the current version and versioning scheme
- how a release is cut here: the workflow or command, the approval gates, and every file that carries the version it bumps
- the deploy target, the traffic split available, and the health signals with their normal range
- the rollback mechanism: redeploy of the previous artifact, a flag, or a revert, and who may run it
- observed evidence for any published, promoted, or rolled-back claim

Expected outputs:

- release_scope/v1
- release_plan/v1
- rollout_stages/v1 when the release is staged
- rollback_trigger/v1
- release_readiness_verdict/v1

Artifact expectations:

- release_scope/v1 lists what goes in and what is held back, and derives the version from the change classes: a breaking change, a feature, or a fix
- release_plan/v1 orders the cut: freeze the release branch, bump every file that carries the version, tag, run the release workflow, pass its approval gate, publish, and curate the notes
- rollout_stages/v1 gives each stage its traffic share, its bake time, and the promotion criterion read from a named health signal
- rollback_trigger/v1 names the signal and threshold that trigger the rollback, the exact command that performs it, and who runs it
- release_readiness_verdict/v1 reads ready only when a named rollback trigger and its exact command are stated; otherwise it names what is missing
