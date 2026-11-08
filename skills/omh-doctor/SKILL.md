---
name: "omh-doctor"
description: "[omh] OMH install misbehaving: diagnosing oh-my-hermes installation health. Use when the user says: doctor, diagnose omh, installation health."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operator]
    category: operator
    phase: diagnostics
    role: tracker
    quality_tier: evidence-gated
---

# Doctor

This is a Hermes-native `doctor` workflow skill.

## Why This Exists

`doctor` exists to turn confusing install/setup states into grouped, local health evidence and the next repair action without treating a check as a fix.

## Do Not Use When

- The user is asking for a general product explanation rather than local health diagnostics.
- The requested change is a repository bug fix, not an installed-environment check.
- The wrapper wants to claim Hermes reload, skill execution, or plugin behavior that was not observed.

## Examples

Good example:

- Prompt: doctor after omh update says setup is next but Hermes skills still look stale.
- Expected behavior: Inspect managed skills, Hermes registration, runtime state, and next repair action with explicit proof boundaries.
- Why: The issue is local installation health and needs grouped diagnostic evidence.

Bad example:

- Prompt: doctor implement a new uninstall command UX.
- Expected behavior: Route to planning or implementation instead of health diagnostics.
- Why: That is product development work, not a local health check.

## Completion Checklist

- Command availability, managed skills, Hermes registration, runtime state, and optional surfaces are grouped separately.
- Blocking issues and warnings are separated, with one next repair action named for each blocking area.
- Plugin install, plugin import/register smoke, and Hermes runtime load are not collapsed into one claim.
- The final status says whether setup/update/doctor repaired anything or only observed health.
- `omh doctor --json` was run (`--no-state-write` writes nothing, `--no-personal-files` skips SOUL.md and memory files) and `recommended_next_action` is quoted.

## Recovery Notes

- If managed skills are stale, recommend omh update or omh setup depending on whether registration also needs repair.
- If skills.external_dirs or Hermes config is missing, route to setup repair rather than editing hidden runtime state.
- If plugin register smoke fails, reinstall the plugin bundle with `omh setup --force` before claiming plugin readiness.
- If omh is missing from PATH, use the installer-reported absolute command path and then re-run doctor.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use to diagnose OMH installation and Hermes config registration.

    Strong routing signals: `doctor`, `$doctor`, `diagnose omh`, `installation health`

## Catalog Metadata

Category: `operator`
Phase: `diagnostics`
Hermes role: `tracker`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- Name the workflow target, constraints, validation evidence, and stop condition.
- Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.

Handoff policy:

Run directly as local health inspection; propose executor work only when a repo fix is required.

Required inputs:

- omh home
- Hermes home
- observed issue

Expected outputs:

- health checks
- fix guidance
- known proof boundary

Artifact expectations:

- doctor state summary when runtime artifacts are writable

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Runtime Evidence

Preferred harness for this skill: `qa-specialist`.

```sh
omh runtime record --skill doctor --harness qa-specialist --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. Finished work ends with no question and no offer; when a decision only the user can make remains, end with one specific question about that decision, not a list of questions, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
