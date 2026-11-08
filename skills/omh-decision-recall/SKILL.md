---
name: "omh-decision-recall"
description: "[omh] Previously rejected options to revisit: recall scoped reviewed rejected decisions without elevating them to approved memory. Use when the user says: decision-recall, rejected decision recall, rejected decisions, why was this rejected, previously rejected alternative, 거절된 결정, 기각된 대안."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, memory]
    category: memory
    phase: decision-recall
    role: memory-keeper
    quality_tier: workflow-surface-gated
---

# Decision Recall

This is a Hermes-native `decision-recall` workflow skill.

## Why This Exists

`decision-recall` exists so Hermes users can ask for this workflow in chat and get a structured, checkable answer instead of an improvised one.

## Do Not Use When

- The user asks what was decided or why an approved decision was made; recall it with the omh_memory tool's recall action, because only decisions a person rejected are stored here.

## Examples

Good example:

- Prompt: Show rejected decisions for this project before we choose an alternative.
- Expected behavior: Produce `show_rejected_decision_recall` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: Claim the recalled rejected decision is an approved memory write or proof the replacement ran.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- The query and scope are explicit, and any tags, stale policy, or match limit that were set are stated.
- Only reviewed rejected candidates are returned; expired candidates stay excluded.
- Recall output is not presented as approved memory, source freshness, or execution evidence.

## Recovery Notes

- Run `omh memory rejected-recall --scope-kind project --scope-ref <id> [--tag <tag>] [--include-stale] [--limit <n>] <query words>`; `--scope-kind` and `--scope-ref` are required. Get the `prj:` id yourself from `omh memory project-identity show`, and ask the user only for a missing query, never for the scope.
- An empty result on a default install is expected: memory is approved on capture, so rejected decisions exist only after a person rejected a staged candidate. Say "no reviewed rejection is on record for this project", not "nothing was rejected", and offer to recall alternatives that were only discussed or captured as ordinary memory.
- If `omh memory project-identity show` reports `state: unresolved` (no project identity exists, for example a git repository with no remote that was never initialised), there is no project to look in from here: say so and do not run the recall with an empty scope ref.
- If the query is missing, no rejected-decision match stands yet; mark recall unresolved and hand back one question for the query. The scope comes from the project identity, and tags, stale policy, and match limit default when unset.
- If a candidate's reviewed-rejected status or expiry cannot be checked, retain only matches that passed those checks, mark remaining recall unresolved, and hand back rejected_decision_recall/v1 with the claim boundary and missing checks.

## Workflow Lane

- Current lane: **Retained knowledge** - memory, rejected alternatives, wiki notes, retrieval, and staleness.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use for scoped reviewed rejected-decision context; it is not approved memory or execution evidence.

    Strong routing signals: `decision-recall`, `rejected decision recall`, `rejected decisions`, `why was this rejected`, `previously rejected alternative`, `거절된 결정`, `기각된 대안`

## Catalog Metadata

Category: `memory`
Phase: `decision-recall`
Hermes role: `memory-keeper`
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

- rejected_decision_recall/v1
- scoped rejected-decision matches
- claim boundary

Artifact expectations:

- rejected_decision_recall/v1 metadata-only recall result

Safety rules:

- Rejected-decision context is reviewed OMH-local context, not approved memory, Hermes memory, or execution evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `decision-recall`.

```sh
omh runtime record --skill decision-recall --harness decision-recall --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. Finished work ends with no question and no offer; when a decision only the user can make remains, end with one specific question about that decision, not a list of questions, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
