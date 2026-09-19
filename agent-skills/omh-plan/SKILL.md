---
name: "omh-plan"
description: "[omh] Hermes Plan workflow: structured planning before execution. Use when the user says: plan, implementation plan, make a plan, write a plan, write the plan, task breakdown, safe feature, safely add a feature."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: plan
    role: planner
    quality_tier: acceptance-gated
---

# Plan

This is an OMH `plan` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

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



## Use When

Use for structured planning when implementation is not ready to start safely, including feature work that needs a safe plan before handoff.

    Strong routing signals: `plan`, `$plan`, `implementation plan`, `make a plan`, `write a plan`, `write the plan`, `task breakdown`, `safe feature`, `safely add a feature`, `add a feature`, `feature request`, `new feature`, `product triage`, `bug triage`, `issue triage`, `reproduction plan`, `workflow hub`, `coding handoff`, `project template`, `github pr workflow`, `実装計画`, `タスク分解`, `安全に機能追加`, `機能追加の計画`, `답할 차례`, `준비할 차례`, `재현 계획`, `요구사항 정리`, `작업 허브`, `작업 허브가 필요`, `상태와 다음 행동`, `프로젝트별 운영`, `实现计划`, `任务拆解`, `安全地新增功能`, `新增功能计划`

## Catalog Metadata

Category: `planning`
Phase: `plan`
Quality tier: `acceptance-gated`
Reasoning demand: `standard`

Quality bar:

- Make goals, non-goals, risks, acceptance criteria, and verification shape explicit.
- Where the repository declares non-negotiable principles, load `references/project-constitution.md` and record the check: a plan conflicting with a MUST is resolved by changing the plan, never by reinterpreting the principle.
- Keep draft plans unapproved until a user or wrapper accepts them.
- Only prepare coding handoff guidance after the plan is accepted.
- Plan acceptance approves the plan content, not execution: after acceptance, recommend the follow-on path that fits the work's shape — `ultrawork` durable checkpoints for progress that must survive sessions as a checkpointed ledger, `ultrawork` coordinated lanes for an accepted plan split into disjoint parallel lanes, `ultrawork` single-owner persistence for one already-scoped task with a single owner, `ultrawork` for one bounded delivery cycle, or a direct selected executor/runtime handoff for a single prepared coding change — state the fit reason in one line, and start it only after the user's explicit go-ahead.

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

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Report actual tool results or
`not_observed` / `not_available`; never invent dispatch or host accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
