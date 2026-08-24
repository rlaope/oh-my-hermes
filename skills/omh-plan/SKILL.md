---
name: omh-plan
description: [omh] Hermes Plan workflow: structured planning before execution. Use when the user says: plan, implementation plan, task breakdown, safe feature, safely add a feature, add a feature, feature request, new feature.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: plan
    role: planner
    quality_tier: acceptance-gated
---

# Plan

This is a Hermes-native `plan` workflow skill.

## Why This Exists

`plan` exists to keep `planning` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.

## Examples

Good example:

- Prompt: plan: handle a planning request that needs explicit evidence boundaries and a clear stop condition.
- Expected behavior: Run `plan` only after naming the target, evidence boundary, and stop condition.
- Why: The request matches the catalog use case and keeps observed evidence separate from prepared guidance.

Bad example:

- Prompt: plan: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `plan`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Completion Checklist

- The plan names goals, non-goals, assumptions, acceptance criteria, and verification shape.
- Draft recommendations, accepted decisions, and executor handoffs are separate states.
- Rejected options or unresolved tradeoffs are recorded before handoff.

## Recovery Notes

- If acceptance criteria or verification are missing, route back to clarification before handoff.
- If assumptions materially affect the plan, keep them visible and avoid treating the plan as accepted.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `codebase-onboarding`, `codegraph-refresh`, `+5 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use for structured planning when implementation is not ready to start safely, including feature work that needs a safe plan before handoff.

    Strong routing signals: `plan`, `$plan`, `implementation plan`, `task breakdown`, `safe feature`, `safely add a feature`, `add a feature`, `feature request`, `new feature`, `product triage`, `bug triage`, `issue triage`, `reproduction plan`, `workflow hub`, `coding handoff`, `답할 차례`, `준비할 차례`, `project template`, `재현 계획`, `요구사항 정리`, `작업 허브`, `작업 허브가 필요`, `github pr workflow`, `상태와 다음 행동`, `프로젝트별 운영`

## Catalog Metadata

Category: `planning`
Phase: `plan`
Hermes role: `planner`
Quality tier: `acceptance-gated`
Reasoning demand: `standard`

Quality bar:

- Make goals, non-goals, risks, acceptance criteria, and verification shape explicit.
- Keep draft plans unapproved until a user or wrapper accepts them.
- Only prepare coding handoff guidance after the plan is accepted.
- Plan acceptance approves the plan content, not execution: after acceptance, recommend the follow-on path that fits the work's shape — `ultrawork` durable checkpoints for progress that must survive sessions as a checkpointed ledger, `ultrawork` coordinated lanes for an accepted plan split into disjoint parallel lanes, `ultrawork` single-owner persistence for one already-scoped task with a single owner, `ultrawork` for one bounded delivery cycle, or a direct selected executor/runtime handoff for a single prepared coding change — state the fit reason in one line, and start it only after the user's explicit go-ahead.

Handoff policy:

Keep planning in Hermes; if the accepted plan requires code edits, prepare a selected executor/runtime handoff after acceptance, and start a follow-on workflow engine only after the user explicitly confirms the recommended path.

Required inputs:

- requirements
- constraints
- known facts
- non-goals

Expected outputs:

- plan
- acceptance criteria
- verification strategy

Artifact expectations:

- plan artifact when durable execution will follow

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Runtime Evidence

Preferred harness for this skill: `planning`.

```sh
omh runtime record --skill plan --harness planning --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
