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

Required: capability family, requested state. Output: policy change summary, what was withheld versus retained, the exact command that reverses it.

## Why This Exists

`capability-toggle` exists because OMH shipped one binary install lever -- the small core set or all installable skills -- so a user who wanted the coding surface but not the memory surface had to take both. It turns that into a per-family choice without uninstalling OMH.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
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

Change the local capability policy with `omh capability-policy`; propose executor work only when a repository fix is required.

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Completion Checklist

- The affected family is named by its canonical id, not guessed from a partial word.
- Withheld workflows and retained core skills are listed separately.
- The report says what the disable does: `retain_knowledge` turns memory off; any other family is only withheld from the offered list (`omh capability-policy status`), routing is unchanged.
- The change uses `omh capability-policy disable|enable <family>` (`--dry-run` previews, `status` lists), never a hand edit, and the printed reversing command is stated.

## Recovery Notes

- If the family id is ambiguous, list all six and ask rather than picking the closest match.
- The policy never deletes skill files.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
