---
name: "omh-mobile-release"
description: "[omh] Releasing an iOS or Android app through a store: signing, the privacy manifest, a TestFlight or Play beta, a staged rollout, a hotfix; prepare each gate the store enforces, and plan the halt and the next build before the rollout starts, because a store release cannot be rolled back. Use when the user says: mobile-release, mobile release, mobile app release, ios release, android release, app store release, app store submission, submit to the app store."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: mobile-release
    role: planner
    quality_tier: store-gate-halt-planned
    related_skills: [omh-release-cut, omh-deploy-and-monitor, omh-production-audit, omh-app-debugging]
---

# Mobile Release

Required: the platforms, the app's bundle or package id, and the version and build number going out, how signing is set up today: certificates, provisioning profiles, the keystore or upload key, and who holds them, the SDKs the build ships, for the privacy manifest and the data safety form, the beta channel and testers, and what they must verify before the rollout, the crash-free and ANR figures the rollout will be judged on, observed from the consoles or crash reporting. Output: signing_plan/v1, privacy_declaration_check/v1, beta_channel_plan/v1, staged_rollout_plan/v1, hotfix_plan/v1.

## Why This Exists

`mobile-release` exists because store releases had no owner: `omh-release-cut` decides a service release that can roll back, `omh-deploy-and-monitor` watches a deploy, and `omh-production-audit` audits readiness platform-neutrally, while signing, a privacy manifest, a TestFlight beta or a Play staged rollout had nothing that knew the store's gates.

## First Steps

- Ask which platforms, which version and build number, and how signing is held today.
- Ask what halts the rollout, before planning any rollout step.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Coding handoff** - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when an iOS or Android app is being released through the App Store or Google Play: code signing and provisioning, the iOS privacy manifest or the Play data safety form, a TestFlight or Play testing-track beta, a phased or staged rollout, or a hotfix for a build already in users' hands. The output is the signing plan, the privacy declaration check, the beta plan, the staged rollout with its halt thresholds, and the hotfix plan; OMH builds, signs, uploads and submits nothing.

    Strong routing signals: `mobile-release`, `mobile release`, `mobile app release`, `ios release`, `android release`, `app store release`, `app store submission`, `submit to the app store`, `app store review`, `app store connect`, `testflight`, `play store`, `play store release`, `google play`, `play console`, `internal testing track`, `closed testing track`, `phased release`, `code signing`, `provisioning profile`, `signing certificate`, `distribution certificate`, `android keystore`, `upload keystore`, `upload key`, `play app signing`, `privacy manifest`, `privacyinfo.xcprivacy`, `required reason api`, `data safety form`, `expedited review`, `fastlane`

## Catalog Metadata

Category: `planning`
Phase: `mobile-release`
Hermes role: `planner`
Quality tier: `store-gate-halt-planned`
Reasoning demand: `standard`

Quality bar:

- Name the halt and the replacement build before any rollout step.
- Load `references/mobile-release-method.md` for the per-platform signing, privacy, beta, rollout and hotfix table instead of recalling store rules.
- Check the privacy declarations against the SDK list the build actually ships, not the one in the plan.
- Keep iOS and Android steps separate wherever the stores differ.
- Keep prepared, submitted, approved, and released as separate states for every build.

Handoff policy:

Keep the signing plan, privacy declaration check, beta plan, staged rollout, and hotfix plan in Hermes. Build numbers, review outcomes, crash-free rates and rollout percentages are recorded only from store console, crash reporting, executor, or operator observed output; OMH never builds, signs, uploads, or submits a build.

Safety rules:

- A store release cannot be rolled back; plan the halt and the next build number before the rollout starts.
- Never commit or paste a signing key, keystore, certificate, or provisioning secret; name where it lives and who holds it.
- Do not submit a build whose privacy manifest or data safety form disagrees with the SDKs it ships.
- Advance a staged rollout only on observed crash-free and ANR figures; a prepared threshold is not a passed one.
- OMH never builds, signs, uploads, or submits; every build number, review outcome, and rollout figure comes from observed output or is marked unverified.

## Completion Checklist

- Every signing asset is named with its expiry and holder, and no secret is in the plan.
- The privacy declarations match the shipped SDKs, or each mismatch is named.
- The beta channel, its testers, and its exit checks are stated.
- Every rollout step names the threshold that halts it.
- The hotfix build number and the halt are planned, and OMH submitted nothing.

## Recovery Notes

- If a signing certificate or upload key is lost or expired, recovering it is the first step; say so before any submission plan.
- If the crash figures are not observable yet, hold the rollout at its current step and mark the threshold unverified.

## Runtime Evidence

Preferred harness for this skill: `app-delivery-loop`.

```sh
omh runtime record --skill mobile-release --harness app-delivery-loop --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
