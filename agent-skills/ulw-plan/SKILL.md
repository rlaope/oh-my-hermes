---
name: "ulw-plan"
description: "[omh] Hermes Ralplan workflow: consensus planning with review gates. Use when the user says: ralplan, consensus plan, reviewed plan, issue to PR, acceptance criteria, verification command, reviewable PR, risky planning."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: reviewed-plan
    role: planner
    quality_tier: reviewed-plan-gated
---

# Ralplan

This is an OMH `ralplan` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`ralplan` exists to make planning reviewable before execution: the host should gather codebase/source facts, compare options, expose risks, define acceptance criteria, and prepare a handoff without pretending implementation already happened.

## First Steps

- Use the host task list or a durable checklist for repo facts, evidence gaps, options, risks, verification, and plan acceptance; keep one item active and insert research when evidence is missing. Checklist states are declarations, not execution evidence.

## Do Not Use When

- The request is still too ambiguous to name requirements, non-goals, or acceptance criteria; use `deep-interview` first.
- The user asks for one full research-plan-implementation-review-PR cycle; use `ultrawork` (its `delivery_boundary` capability) and keep ralplan as the planning stage.
- The change is a small local refactor or cleanup with no architectural or regression risk; use `ultrawork`, or `ai-slop-cleaner` when observable behavior must stay identical.
- The refactor's direction is already decided and what is missing is its execution shape - which files move in which phase, what verifies each phase, where each phase rolls back to; use `refactor-plan`.
- One plan-blocking choice still needs behavior evidence rather than argument; run `decision-prototype` first and consume its decision receipt without transcript replay.
- The user wants a pure source lookup, citation check, or paper explanation with no implementation plan.
- The unresolved work is repository terminology alignment or a project-language decision frontier; use `context` before planning.

## Examples

Good example:

- Prompt: $ralplan turn this risky refactor into a reviewable plan with acceptance criteria and verification commands.
- Expected behavior: Produce repo/source facts, alternatives, risk review, acceptance criteria, exact verification commands, and handoff readiness without editing code.
- Why: The request is clear enough to plan but risky enough to require consensus-style review before execution.

Bad example:

- Prompt: $ralplan implement the refactor now and open the PR.
- Expected behavior: Stop at the reviewed plan or route the full delivery cycle to `ultrawork` after plan acceptance.
- Why: Ralplan is a planning gate, not implementation, review, CI, or PR evidence.

## Completion Checklist

- The plan todo was declared before the first planning step and every stage reached a terminal state; a plan produced without one, or with stages still pending, is not finished.
- Observed repo facts and source/web evidence gaps are named.
- At least two options or one chosen option plus rejected alternatives are recorded.
- Risks, acceptance criteria, and verification commands are testable or explicitly blocked.
- The plan exists as a recorded file-backed artifact, not only as chat narration.
- The implementation handoff is prepared only after plan acceptance and remains prepared_not_observed.
- The follow-on engine or executor path was started only after the user's explicit go-ahead in this conversation, never from plan acceptance alone.

## Recovery Notes

- If requirements are still fuzzy, route back to deep-interview before planning.
- If current-source evidence is missing, route a `research` step before accepting the plan.
- If the user asks for implementation after acceptance, recommend the follow-on path that fits the work's shape (`ultrawork` with the matching capability — durable checkpoint, coordinated lanes, single-owner persistence, or one delivery cycle — or a direct selected executor handoff) with a one-line fit reason, and start it only on the user's explicit go-ahead — never auto-start an engine from acceptance alone.



## Use When

Use when requirements are clear enough for planning but architecture, evidence, alternatives, risks, or tests need a reviewed plan before execution.

    Strong routing signals: `ralplan`, `$ralplan`, `consensus plan`, `reviewed plan`, `issue to PR`, `acceptance criteria`, `verification command`, `reviewable PR`, `risky planning`, `dangerous planning`, `unsafe change`, `refactor safety`, `PR로 만들`, `PR로 만들 수 있게`, `위험한 리팩터링`, `리팩터링 위험`, `리스크 있는 리팩터링`, `검증 command`, `리뷰 가능한 단위`, `코드베이스 조사`, `웹리서치 계획`, `대안 비교`, `리스크 검토`

## Catalog Metadata

Category: `planning`
Phase: `reviewed-plan`
Quality tier: `reviewed-plan-gated`
Reasoning demand: `standard`

Quality bar:

- Start from observed repo facts and source/web evidence when freshness or external behavior matters.
- Include planner view, critic/risk review, alternative paths, rejected options, and a testability check before handoff.
- Produce testable acceptance criteria and exact verification commands or explain why they are not yet knowable.
- Record unresolved tradeoffs and evidence gaps instead of flattening uncertainty.
- When plan-shaping evidence is missing — current external behavior, contested claims, or unstudied reference implementations — run the `research` workflow as a bounded in-plan stage (not an exhaustive deep-research run) before comparing options, record its dossier the way the `research` artifact contract requires, and consume it instead of planning on assumptions.
- Consume a recorded `research` dossier when one exists: plan options and rejected alternatives should cite its decision drivers and verified claims.
- End with a selected executor/runtime handoff shape only after the plan is accepted.
- Plan acceptance approves the plan content, not execution: after acceptance, recommend the follow-on path that fits the work's shape — `ultrawork` durable checkpoints for progress that must survive sessions as a checkpointed ledger, `ultrawork` coordinated lanes for an accepted plan split into disjoint parallel lanes, `ultrawork` single-owner persistence for one already-scoped task with a single owner, `ultrawork` for one bounded delivery cycle, or a direct selected executor/runtime handoff for a single prepared coding change — state the fit reason in one line, and start it only after the user's explicit go-ahead.
- Do not implement directly from consensus planning.

Required inputs:

- requirements
- codebase facts
- source or web evidence when needed, or an in-plan research stage to obtain it
- options
- tradeoffs
- test shape

Expected outputs:

- reviewed plan
- acceptance criteria
- risk register
- verification commands
- handoff guidance

Artifact expectations:

- Record the plan as a durable file/ledger the host can resume, with goals, options, risks, acceptance criteria, and exact verification commands.
- Record the user acceptance against that exact artifact; acceptance is not permission to start implementation.

Safety rules:

- Do not implement directly from the planning lane.
- Do not invent codebase or web evidence; label missing evidence and source gaps.
- Make acceptance criteria testable.
- Record unresolved tradeoffs explicitly.
- Keep rejected options and handoff readiness separate from accepted execution evidence.
- Write plans only to an explicitly chosen repository or host-owned planning path; never write another product's state root.

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
