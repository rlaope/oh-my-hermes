---
name: ulw-plan
description: [omh] Hermes Ralplan workflow: consensus planning with review gates. Use when the user says: ralplan, consensus plan, reviewed plan, issue to PR, acceptance criteria, verification command, reviewable PR, risky planning.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: reviewed-plan
    role: planner
    quality_tier: reviewed-plan-gated
---

# Ralplan

This is a Hermes-native `ralplan` workflow skill.

## Why This Exists

`ralplan` exists to make planning reviewable before execution: Hermes should gather codebase/source facts, compare options, expose risks, define acceptance criteria, and prepare a handoff without pretending implementation already happened.

## Do Not Use When

- The request is still too ambiguous to name requirements, non-goals, or acceptance criteria; use `deep-interview` first.
- The user asks for one full research-plan-implementation-review-PR cycle; use `ultrawork` (its `delivery_boundary` capability) and keep ralplan as the planning stage.
- The change is a small local refactor or cleanup with no architectural or regression risk; use `ultrawork`, or `ai-slop-cleaner` when observable behavior must stay identical.
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

- Observed repo facts and source/web evidence gaps are named.
- At least two options or one chosen option plus rejected alternatives are recorded.
- Risks, acceptance criteria, and verification commands are testable or explicitly blocked.
- The plan exists as a recorded file-backed artifact, not only as chat narration.
- The implementation handoff is prepared only after plan acceptance and remains prepared_not_observed.
- The follow-on engine or executor path was started only after the user's explicit go-ahead in this conversation, never from plan acceptance alone.

## Recovery Notes

- If requirements are still fuzzy, route back to deep-interview before planning.
- If current-source evidence is missing, route a `research` step before accepting the plan.
- If the plan depends on unstudied reference implementations or contested external claims, route a deep research step and consume its dossier before accepting the plan.
- If the user asks for implementation after acceptance, recommend the follow-on path that fits the work's shape (`ultrawork` with the matching capability — durable checkpoint, coordinated lanes, single-owner persistence, or one delivery cycle — or a direct selected executor handoff) with a one-line fit reason, and start it only on the user's explicit go-ahead — never auto-start an engine from acceptance alone.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `codebase-onboarding`, `codegraph-refresh`, `+5 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when requirements are clear enough for planning but architecture, evidence, alternatives, risks, or tests need a reviewed plan before execution.

    Strong routing signals: `ralplan`, `$ralplan`, `consensus plan`, `reviewed plan`, `issue to PR`, `acceptance criteria`, `verification command`, `reviewable PR`, `risky planning`, `dangerous planning`, `unsafe change`, `refactor safety`, `PR로 만들`, `PR로 만들 수 있게`, `위험한 리팩터링`, `리팩터링 위험`, `리스크 있는 리팩터링`, `검증 command`, `리뷰 가능한 단위`, `코드베이스 조사`, `웹리서치 계획`, `대안 비교`, `리스크 검토`

## Catalog Metadata

Category: `planning`
Phase: `reviewed-plan`
Hermes role: `planner`
Quality tier: `reviewed-plan-gated`
Reasoning demand: `standard`

Quality bar:

- Start from observed repo facts and source/web evidence when freshness or external behavior matters.
- Include planner view, critic/risk review, alternative paths, rejected options, and a testability check before handoff.
- Produce testable acceptance criteria and exact verification commands or explain why they are not yet knowable.
- Record unresolved tradeoffs and evidence gaps instead of flattening uncertainty.
- Consume a recorded `research` dossier when one exists: plan options and rejected alternatives should cite its decision drivers and verified claims.
- End with a selected executor/runtime handoff shape only after the plan is accepted.
- Plan acceptance approves the plan content, not execution: after acceptance, recommend the follow-on path that fits the work's shape — `ultrawork` durable checkpoints for progress that must survive sessions as a checkpointed ledger, `ultrawork` coordinated lanes for an accepted plan split into disjoint parallel lanes, `ultrawork` single-owner persistence for one already-scoped task with a single owner, `ultrawork` for one bounded delivery cycle, or a direct selected executor/runtime handoff for a single prepared coding change — state the fit reason in one line, and start it only after the user's explicit go-ahead.
- Do not implement directly from consensus planning.

Handoff policy:

Keep consensus planning and review in Hermes; produce explicit selected executor/runtime handoff guidance only after the plan is accepted, and start a follow-on workflow engine only after the user explicitly confirms the recommended path.

Required inputs:

- requirements
- codebase facts
- source or web evidence when needed
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

- record the plan with `omh hermes plan --record`, which writes `<repo>/.omh/plans/<slug>.md` inside a repository and the user-scope OMH store outside one
- mark acceptance with `omh hermes plan-accept <path>` so acceptance_recorded and handoff_ready point at a real artifact

Safety rules:

- Do not implement directly from the planning lane.
- Do not invent codebase or web evidence; label missing evidence and source gaps.
- Make acceptance criteria testable.
- Record unresolved tradeoffs explicitly.
- Keep rejected options and handoff readiness separate from accepted execution evidence.
- Write plan artifacts only through the named `omh hermes plan` commands under `<repo>/.omh/plans/`; never write plans or planning state into `.omc/**` or any other wrapper's state root — `.omc/` belongs to oh-my-claudecode, a different product.

## Runtime Evidence

Preferred harness for this skill: `planning`.

```sh
omh runtime record --skill ralplan --harness planning --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
