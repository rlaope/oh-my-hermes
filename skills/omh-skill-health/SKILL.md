---
name: "omh-skill-health"
description: "[omh] OMH skill portfolio health overview: prepare a metadata-only OMH skill portfolio dashboard with stale surfaces, observed failure signals, pending amendments, and top actions. Use when the user says: skill-health, skill health, skill portfolio health, skill dashboard, skill health dashboard, skill failure pattern dashboard, skill failure patterns, pending skill amendments."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: skill-health
    role: operator
    quality_tier: workflow-surface-gated
    related_skills: [omh-doctor, omh-workflow-learning, omh-skill-scout]
---

# Skill Health

This is a Hermes-native `skill-health` workflow skill.

## Why This Exists

`skill-health` exists because a skill portfolio drifts in ways no single run shows -- a managed skill changed in place, an authoring finding nobody fixed, an update waiting on its hub -- and use counts measure none of that: it gathers the observed signals into one card with an owner lane and a safe next action for each, and changes nothing itself.

## Do Not Use When

- OMH setup, install, or a skill that does not load; use `omh-doctor`.
- One run that missed a route or went wrong; use `omh-workflow-learning`.
- Finding a new skill to adopt; use `omh-skill-scout`.

## Examples

Good example:

- Prompt: skill-health show the OMH skill portfolio dashboard with stale surfaces, failure patterns, pending amendments, and top improvement actions.
- Expected behavior: Produce `prepare_skill_health` with required context, wrapper actions, and not-evidence boundaries.
- Why: Drift comes from `lint_warnings` and, on Hermes, the curator ledger, not use counts.

Bad example:

- Prompt: skill-health claim every skill is working and patch the failures automatically without observed signals or review.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Dashboard scope, source surfaces, stale/duplicate criteria, and stop condition are explicit.
- Install/setup health is routed to `omh-doctor`; catalog operations are routed to `omh-skill`; failure retrospectives are routed to `omh-workflow-learning`.
- No skill, prompt, doc, memory, or model behavior is claimed changed until a reviewed implementation records evidence.
- Never present use, view, or load counts, `.usage.json` included, as a health, prune, archive, or retire signal: a rarely used skill is not an unhealthy one, and no health card recommends removing, archiving, or pruning a skill for being used little.
- On Hermes, read the skill audit ledger read-only (that skill's entries in `skills/.curator_ledger.jsonl` under the active profile's Hermes home, or `hermes curator ledger --skill <name> --limit <n>`, which lists only the 20 newest entries by default): an entry against an OMH-managed skill means Hermes changed that managed copy outside OMH, so it may no longer match its generated body; report it as drift with the entry's `action` and `actor` (`agent`, `user`, or `curator`, which covers Hermes' curator and its background review). An OMH-managed skill is one OMH installed, under a label OMH's catalog renders such as `omh-plan` or `ulw-work`; a companion skill the person or an agent created is theirs, whatever its name. An empty ledger is unknown, not clean, because `skills.ledger: false` turns it off.
- On Hermes, record an authoring finding only from the `lint_warnings` a `skill_manage` write returned, which are advisory and never proof a skill works; only some writes return them (an `edit` never does), so a write without them is not a clean lint. Record an available update for a hub-installed skill only from `hermes skills check` output that was seen; that hub request is Hermes' own, not OMH's.

## Recovery Notes

- If the request is about OMH setup, install, stale package paths, or command availability, route to `omh-doctor`.
- If the request is a missed-route or self-improvement trace, route to `omh-workflow-learning` before adding health actions.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when operators need portfolio-level skill health without treating it as install repair, live execution success, or automatic skill mutation.

    Strong routing signals: `skill-health`, `skill health`, `skill portfolio health`, `skill dashboard`, `skill health dashboard`, `skill failure pattern dashboard`, `skill failure patterns`, `pending skill amendments`, `skill amendments`, `스킬 헬스`, `스킬 상태`, `스킬 대시보드`, `스킬 실패 패턴`, `스킬 개선 후보`, `스킬 보류 수정`

## Catalog Metadata

Category: `operations`
Phase: `skill-health`
Hermes role: `operator`
Quality tier: `workflow-surface-gated`
Reasoning demand: `light`

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

- catalog, generated, reference, harness, and capability-surface status
- observed failure signals, or an explicit statement that none were supplied
- pending amendment review slots and top safe actions with owner lane and verification path

Artifact expectations:

- skill_health_card/v1 metadata-only wrapper card recording surface status, observed-only failure signals, pending amendments, and the non-mutation boundary

Safety rules:

- A skill health dashboard is not install/setup health, live skill execution success, automatic skill mutation, model training, verification, review, CI, or proof that future routing is fixed.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `skill-health`.

```sh
omh runtime record --skill skill-health --harness skill-health --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
