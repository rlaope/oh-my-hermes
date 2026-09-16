---
name: "omh-refactor-plan"
description: "[omh] Hermes refactor planning workflow: turn a decided boundary-changing refactor into a phased plan - reconnaissance, contracts-first phase order, per-phase verification and rollback, a files table, and an explicit approval gate before any edit. Use when the user says: refactor-plan, refactor plan, plan this refactor, plan the refactor, refactor planning, refactor phases, phased refactor, refactor in phases."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: refactor-plan
    role: planner
    quality_tier: plan-gated
---

# Refactor Plan

This is a Hermes-native `refactor-plan` workflow skill.

## Why This Exists

`refactor-plan` exists because boundary-changing refactors bounced between goal planning and behavior-preserving cleanup with neither owning the execution shape: the phase order, the per-phase rollback, and the files table that make a large refactor reviewable and abortable.

## Do Not Use When

- The refactor's direction is still contested or the goal itself needs consensus planning; use `ralplan`.
- The work is deletion-first cleanup with no boundary changes; use `ai-slop-cleaner`.
- The plan is done and the claim is that work is complete; use `verification-gate` for the evidence close.

## Examples

Good example:

- Prompt: We decided to split the billing module out of orders - plan the refactor so each step is shippable.
- Expected behavior: Map affected files and consumers from the import graph, name hidden coupling and blast radius, order the five phases with per-phase verification and rollback, ship the files table, and stop at the approval gate.
- Why: The direction is decided and the need is a phased, abortable execution shape - exactly this workflow's territory.

Bad example:

- Prompt: Should we even split billing out of orders?
- Expected behavior: Route to `ralplan`: the direction is not decided, so consensus planning comes before phase planning.
- Why: A phase plan for a contested direction launders a decision through logistics.

## Completion Checklist

- Reconnaissance names affected files, boundaries, coupling, and blast radius from observed evidence.
- Every phase carries its verification command and its rollback point, and ends at a shippable commit.
- The files table covers every touched file with action, phase, and dependencies.
- The plan stopped at the approval gate; no implementation began without the user's go.

## Recovery Notes

- If the import graph is unavailable, build the codegraph first or reduce the plan's confidence and say which files are unverified.
- If a phase cannot be made independently green, split it further; two half-phases beat one unabortable one.
- If reconnaissance finds the direction itself is unsettled, route back to `ralplan` before ordering phases.

## Workflow Lane

- Current lane: **Intent -> plan** (`oh-my-hermes`, `meta-router`, `deep-interview`, `context`, `plan`, `ralplan`, `adversarial-consensus`, `codebase-onboarding`, `+9 more`) - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when a refactor that crosses module boundaries is already decided and needs its execution shaped: which files move in which phase, what verifies each phase, and where each phase rolls back to - before anything is edited.

    Strong routing signals: `refactor-plan`, `refactor plan`, `plan this refactor`, `plan the refactor`, `refactor planning`, `refactor phases`, `phased refactor`, `refactor in phases`, `refactor rollback plan`, `blast radius`, `module restructure plan`, `restructure plan`, `dependency upgrade`, `major version upgrade`, `framework upgrade`, `upgrade to the next major`, `breaking change upgrade`, `lockfile`, `리팩터링 계획`, `리팩토링 계획`, `리팩터링 단계`, `단계별 리팩터링`, `리팩터링 계획 세워줘`, `리팩터링 롤백 계획`

## Catalog Metadata

Category: `planning`
Phase: `refactor-plan`
Hermes role: `planner`
Quality tier: `plan-gated`
Reasoning demand: `standard`

Quality bar:

- Reconnaissance first: affected files, ownership boundaries, hidden coupling, and blast radius are mapped before any phase is ordered; the full contract is `omh-refactor-plan/references/refactor-phases.md`.
- Order phases contracts-first: types and interfaces, then implementations, then callers in reviewable groups, then tests, then cleanup - and name what verifies each phase and where it rolls back to.
- Ship the files table with the plan: one row per file with action, phase, and blocks/blocked-by; a row without a phase is unplanned work.
- Size verification to the blast radius, not to optimism: a phase touching public surfaces or persisted shapes carries the full gate, not the fast one.
- For a dependency or framework upgrade, read four inputs before ordering phases — advisory and end-of-life intake, the licence delta at the target version, the upstream migration guide item by item against this codebase, and lockfile handling in the same commit as the manifest; a breaking change nobody checked is a gap, not a pass. The full contract is `omh-refactor-plan/references/dependency-upgrade.md`.
- Stop at the approval gate and hand the user the go/no-go, whole plan or first phase.

Handoff policy:

Hermes owns reconnaissance and the phased plan; implementation of any approved phase is coding work for the selected executor lane under its own evidence rules. An approved plan is approval of the order, not evidence any phase ran.

Required inputs:

- the decided target shape (what moves where), or a pointer to the accepted plan that decided it
- the affected-file evidence: import graph, codegraph handoff, or an observed file inventory
- the regression gates that exist today (test suite, typecheck, generated-artifact checks)

Expected outputs:

- reconnaissance: affected files, ownership boundaries, hidden coupling, blast radius — and for an upgrade, the advisory, licence, migration-guide, and lockfile intake
- phase plan in the fixed order - types/interfaces, implementations, callers, tests, cleanup - each with verification and rollback
- files table: path, action, phase, blocks/blocked-by
- the approval gate: the plan stops and waits for the user's go

Artifact expectations:

- metadata-only runtime record when a wrapper or shell is available

Safety rules:

- The plan comes from observed repo evidence, never from memory of the tree.
- Every phase ends at a commit that could ship; a phase that cannot end green is split further.
- Nothing is deleted before the cleanup phase, and cleanup starts from a tagged rollback point.
- Do not begin implementing any phase without the user's explicit approval of the plan.

## Runtime Evidence

Preferred harness for this skill: `coding-handling`.

```sh
omh runtime record --skill refactor-plan --harness coding-handling --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
