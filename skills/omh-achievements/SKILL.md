---
name: "omh-achievements"
description: "[omh] Hermes badges unlocked and achievement progress: achievements observation: summarize hermes-achievements badges, tiers, recent unlocks, and progress from local plugin artifacts. Use when the user says: achievements, achievement, badges, badge, my badges, show achievements, achievement summary, unlocked badges."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, observability]
    category: observability
    phase: telemetry-card
    role: tracker
    quality_tier: workflow-surface-gated
---

# Achievements

This is a Hermes-native `achievements` workflow skill.

## Why This Exists

`achievements` exists so Hermes users can ask for this workflow in chat and get a structured, checkable answer instead of an improvised one.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: achievements show my unlocked badges and what is closest to the next tier.
- Expected behavior: Produce `show_achievements_summary` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: achievements recompute my session history and grant the missing badges.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- The summary states the snapshot's `generated_at` and whether it is older than 120 seconds, the plugin's own rescan rule.
- Unlocked, discovered, and secret badges are listed from the files read, and nothing is recomputed from session history.
- Missing plugin files give not_observed with the way to produce a snapshot, not an empty list.

## Recovery Notes

- If no snapshot exists, the plugin has not scanned yet: it writes one when its dashboard Achievements tab asks (`hermes dashboard`), so a gateway-only person has none until they open it; read with `omh achievements summary`.
- If neither active-profile nor legacy hermes-achievements files are available, no badge result stands; mark the summary not_observed and hand back the missing local-file evidence needed for hermes_achievements_observation/v1.
- If the snapshot is older than the plugin's rescan window, retain its badge list as of generated_at, mark current progress tentative, and hand back the timestamp and stale-snapshot warning.
- If supplied session_activity_receipt/v1 lacks a metric, retain the available badge and activity metadata, mark that metric not_observed, and hand back the gap without replacing it with zero.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when the user asks which achievements or badges they unlocked, badge progress or tiers, recent unlocks, or wants an achievements section prepared for a report.

    Strong routing signals: `achievements`, `achievement`, `badges`, `badge`, `my badges`, `show achievements`, `achievement summary`, `unlocked badges`, `badge progress`, `achievement tier`, `recent unlocks`, `badge share card`, `実績`, `バッジ`, `成就`, `徽章`, `업적`, `배지`, `뱃지`, `도전과제`, `업적 요약`

## Catalog Metadata

Category: `observability`
Phase: `telemetry-card`
Hermes role: `tracker`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- hermes_achievements_observation/v1 summary or badge list
- recent unlocks and progress hints
- next action
- prepared-vs-observed boundary

Artifact expectations:

- hermes_achievements_observation/v1 metadata-only payload from `omh achievements` when recorded
- supplied `session_activity_receipt/v1` when available; unavailable metrics stay unavailable, never zero

Safety rules:

- An achievements card reflects only the hermes-achievements plugin's local files, read from `plugin-data/hermes-achievements/` under the active profile's Hermes home first and the legacy `plugins/hermes-achievements/` second, as of the snapshot's `generated_at` and stale once older than the plugin's rescan window; it is not a session-history rescan, badge recomputation, unlock proof beyond those files, or productivity evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
