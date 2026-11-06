---
name: "omh-capability-toggle"
description: "[omh] Tailoring enabled OMH families: turning one OMH capability family on or off so an install can be tailored instead of taken whole. Use when the user says: capability-toggle, capability policy, disable memory, enable memory, disable coding orchestration, disable a capability family, enable a capability family, 메모리 기능 꺼줘."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operator]
    category: operator
    phase: configuration
    role: tracker
    quality_tier: evidence-gated
---

# Capability Toggle

This is a Hermes-native `capability-toggle` workflow skill.

## Why This Exists

`capability-toggle` exists because OMH shipped one binary install lever -- 9 core skills or all of them -- so a user who wanted the coding surface but not the memory surface had to take both. It turns that into a per-family choice without uninstalling OMH.

## Do Not Use When

- The user wants to run the workflow a family owns rather than change whether that family is offered.
- The user is asking to build an on/off switch inside their own product.
- The user wants OMH removed entirely, which is the uninstall path rather than a capability policy change.
- The user wants one skill hidden on one messaging platform or everywhere; that is Hermes' own hermes skills config, an interactive command the person runs in a terminal, and OMH writes no Hermes config.

## Examples

Good example:

- Prompt: turn off memory, I already run my own memory system
- Expected behavior: Disable the retain_knowledge family, report the four memory workflows removed and the five core skills retained, and name the enable command.
- Why: The request is about which OMH surfaces are offered locally, not about capturing a memory.

Bad example:

- Prompt: add a dark mode toggle to my settings page
- Expected behavior: Route to frontend or coding delegation instead of capability policy.
- Why: That is a feature in the user's own product, not an OMH capability family.

## Completion Checklist

- The affected family is named by its canonical id, not guessed from a partial word.
- Removed workflows and retained core skills are listed separately.
- The reversing command is stated so the change never reads as permanent.
- Locally modified skill files are reported as retained exceptions rather than deleted.

## Recovery Notes

- If the family id is ambiguous, list all six and ask rather than picking the closest match.
- If a disable would remove a core skill, refuse that part and report it; core skills are the floor doctor checks for.
- If files were kept with --keep-files, say the policy changed but the files remain so the state is not misread as a full removal.

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+40 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when the user wants to turn an OMH capability family on or off -- memory, coding delegation, research, planning, materials, or operations -- rather than uninstall OMH or run the workflow that family owns.

    Strong routing signals: `capability-toggle`, `capability policy`, `disable memory`, `enable memory`, `disable coding orchestration`, `disable a capability family`, `enable a capability family`, `메모리 기능 꺼줘`, `메모리 기능 끄기`, `메모리 기능 켜줘`, `메모리 비활성화`, `메모리 관리 비활성화`, `코딩 오케스트레이션 비활성화`, `코딩 오케스트레이션 꺼줘`, `기능 비활성화`, `기능 활성화`

## Catalog Metadata

Category: `operator`
Phase: `configuration`
Hermes role: `tracker`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- Name the workflow target, constraints, validation evidence, and stop condition.
- Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.

Handoff policy:

Read and write the local capability policy directly; propose executor work only when a repository fix is required.

Required inputs:

- capability family
- requested state

Expected outputs:

- policy change summary
- what was removed versus retained
- the exact command that reverses it

Artifact expectations:

- capability policy recorded in the local setup profile

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
