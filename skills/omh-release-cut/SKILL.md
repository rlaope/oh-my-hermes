---
name: "omh-release-cut"
description: "[omh] Shipping a versioned release -- tag it, stage it behind a canary, or roll back the last deploy: decide what goes in, the version, the rollout stages, and a rollback with its trigger and exact command before it is needed. Use when the user says: release-cut, release cut, cut a release, cut the release, cut a new release, tag a release, tag the release, release candidate."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: release-cut
    role: planner
    quality_tier: rollback-trigger-gated
    related_skills: [omh-deploy-and-monitor, omh-live-incident-response, omh-production-audit, omh-commit-pr-authoring, omh-mobile-release]
---

# Release Cut

This is a Hermes-native `release-cut` workflow skill.

## Why This Exists

`release-cut` exists because nothing owned deciding a release: `omh-deploy-and-monitor` watches a rollout that is already happening, and a cut, a canary, or a rollback decision reached an image card or a watch lane with no rollback trigger at all.

## First Steps

- State what goes in, what is held back, and the version before proposing the cut.
- Name the rollback trigger and its exact command before the first stage ships.

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

## Completion Checklist

- The contents, the held items, and the version are stated.
- Every rollout stage has a traffic share, a bake time, and a promotion criterion.
- The rollback trigger names a signal, a threshold, and the exact command.
- The readiness verdict is ready only when the trigger and the command are named.
- Nothing was tagged, published, deployed, or rolled back by OMH.

## Recovery Notes

- If the release mechanism is unknown, ask for the workflow or command and every file that carries the version it bumps before proposing a cut.
- If there is no traffic split, stage by environment or by cohort and say that the canary is coarse.

## Workflow Lane

- Current lane: **Coding handoff** - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when a release is being decided or undone: what goes into it, its version, how it is tagged and published, how it rolls out in stages behind a canary, or rolling back a deploy that already shipped. The output is a release plan whose rollback has a named trigger and the exact command that performs it; OMH prepares, and the host or CI executes.

    Strong routing signals: `release-cut`, `release cut`, `cut a release`, `cut the release`, `cut a new release`, `tag a release`, `tag the release`, `release candidate`, `what goes in the release`, `version the release`, `semver bump`, `roll back the last deploy`, `roll back the deploy`, `roll back the release`, `roll back to the previous version`, `rollback trigger`, `rollback command`, `canary`, `canary release`, `canary deploy`, `set up a canary`, `staged rollout`, `progressive rollout`, `percentage rollout`

## Catalog Metadata

Category: `planning`
Phase: `release-cut`
Hermes role: `planner`
Quality tier: `rollback-trigger-gated`
Reasoning demand: `standard`

Quality bar:

- Derive the version from the change classes, not from a feeling about size.
- Load `references/release-and-rollback-method.md` for the cut sequence, the rollout stage table, and rollback by mechanism instead of recalling them.
- Give every rollout stage a promotion criterion read from a signal, not a clock alone.
- Name the rollback trigger as a signal, a threshold, and a window, and the command as the literal command line.
- Keep prepared, dispatched, observed, and published as separate states for every step.

Handoff policy:

Keep the release contents, the version decision, the rollout stages, the rollback trigger and command, and the readiness verdict in Hermes. Tags, workflow runs, approvals, published artifacts, canary metrics, and every rollback are recorded only from executor, operator, CI, or wrapper observed output; OMH prepares and never publishes, tags, or deploys.

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

Safety rules:

- A release plan cannot be ready without a named rollback trigger and the exact command that performs it; `release_readiness_verdict/v1` names what is missing instead.
- Decide the rollback before the release: the trigger, the threshold, the command, and the person who runs it are written down before the first stage ships.
- Nothing merges to the release branch between starting a cut and its tag push; a merge in that window breaks the atomic push of the bump and the tag.
- OMH never tags, publishes, deploys, approves, or rolls back; a prepared plan is never a cut release or a performed rollback.
- A rollback that crosses a database migration or a published package names what cannot be undone and how it is contained.

## Runtime Evidence

Preferred harness for this skill: `app-delivery-loop`.

```sh
omh runtime record --skill release-cut --harness app-delivery-loop --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
