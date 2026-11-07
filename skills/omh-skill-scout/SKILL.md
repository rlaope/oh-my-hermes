---
name: "omh-skill-scout"
description: "[omh] Existing skills to reuse before authoring: prepare a metadata-only search-before-creation report for local, marketplace, GitHub, and web skill candidates with risk review and adoption options. Use when the user says: skill-scout, skill scout, skill candidate, skill candidate search, skill discovery, find a skill, find skills, top skills."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: skill-scout
    role: operator
    quality_tier: workflow-surface-gated
    related_skills: [omh-doctor, omh-skill-health, omh-skill]
---

# Skill Scout

This is a Hermes-native `skill-scout` workflow skill.

## Why This Exists

`skill-scout` exists because writing a skill that already exists, or adopting a public one on its popularity, both cost more than a search: it compares installed, bundled, and public candidates first, keeps each source's trust level and any scan verdict beside it, and recommends using, extending, or creating one without installing, copying, or trusting anything.

## Do Not Use When

- Repairing an OMH install or a skill that does not load; use `omh-doctor`.
- A health overview of the skills already installed; use `omh-skill-health`.
- Writing or changing a skill once the scout decision is made; use `omh-skill`.

## Examples

Good example:

- Prompt: skill-scout find existing skill candidates before we create a release-note workflow skill.
- Expected behavior: Produce `prepare_skill_scout` with required context, wrapper actions, and not-evidence boundaries.
- Why: Reuse is judged by candidate and source trust; the scout installs nothing.

Bad example:

- Prompt: skill-scout install the best GitHub skill and copy it into the marketplace without review.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Intent, keywords, source scope, and stop condition are explicit.
- Local and external search evidence is separated from planned search.
- No install, copy, write, credential, or trust claim is made without observed review or implementation.
- On Hermes, fill the external candidates from `hermes skills search <query>` and `hermes skills inspect <identifier>`, whose hub requests are Hermes' own, not OMH's. Keep the trust each shows (`official` for an official-source row, otherwise `builtin`, `trusted`, or `community`, highest first) beside the candidate as its source's standing, never as a review of its content, and record a scan verdict (`safe`, `caution`, or `dangerous`) only from install or `hermes skills audit` output that was seen, so a candidate nobody installed has none.

## Recovery Notes

- If the request is about setup or installed skill repair, route to `omh-doctor`.
- If the request is a portfolio health dashboard, route to `omh-skill-health`.
- If the request is an approved skill mutation or creation task, route to `omh-skill` or implementation after the scout decision.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use before creating or adapting a skill so OMH can compare existing local, marketplace, GitHub, or web candidates without installing, copying, or trusting them by default.

    Strong routing signals: `skill-scout`, `skill scout`, `skill candidate`, `skill candidate search`, `skill discovery`, `find a skill`, `find skills`, `top skills`, `popular skills`, `famous hermes skills`, `useful hermes skills`, `hermes skills/plugin`, `skills/plugin`, `agentskills.io top skills`, `is there a skill`, `existing skill`, `fork a skill`, `extend a skill`, `create skill after search`, `new skill search`, `skill adoption`, `스킬 스카우트`, `스킬 후보`, `스킬 찾기`, `스킬 검색`, `스킬 만들기 전`, `유명한 hermes skills`, `유명한 hermes skill`, `유용한 hermes skills`, `스킬 플러그인 후보`, `플러그인 찾아`, `플러그인 비교`, `없는 것 설치할지 비교`, `기존 스킬`, `найди скилл`, `какие есть скиллы`, `есть ли скилл`, `подбери скилл`, `поищи скиллы`, `есть скилл для`, `какие скиллы есть`, `найти скилл`

## Catalog Metadata

Category: `operations`
Phase: `skill-scout`
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

- skill_scout_query/v1
- local_skill_candidate_inventory/v1 when observed
- external_skill_candidate_risk_review/v1 when observed
- awesome_hermes_agent_coverage/v1 for upstream ecosystem comparison when requested
- skill_adoption_decision_matrix/v1
- skill_scout_recommendation/v1

Artifact expectations:

- skill_scout_query/v1 with intended workflow, triggers, domains/tools, and search keywords
- local_skill_candidate_inventory/v1 separating installed, bundled, marketplace, and repo-local matches when observed
- awesome_hermes_agent_coverage/v1 mapping upstream ecosystem entries to OMH covered, partial, or missing_candidate coverage statuses, matched OMH surfaces, rule_set_version, and matched_rule_id
- skill_adoption_decision_matrix/v1 ranking use existing, fork or extend, and create fresh options with trust gaps

Safety rules:

- A skill scout report is not skill installation, external source trust, marketplace mutation, file copy, network retrieval, credential use, implementation, review, CI, or proof that a candidate is safe to adopt.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `skill-scout`.

```sh
omh runtime record --skill skill-scout --harness skill-scout --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
