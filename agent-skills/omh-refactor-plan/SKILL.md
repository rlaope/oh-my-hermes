---
name: "omh-refactor-plan"
description: "[omh] Decided cross-module refactor to phase: refactor planning - turn a decided boundary-changing refactor into a phased plan - reconnaissance, contracts-first phase order, per-phase verification and rollback, a files table, and an explicit approval gate before any edit. Use when the user says: refactor-plan, refactor plan, plan this refactor, plan the refactor, refactor planning, refactor phases, phased refactor, refactor in phases."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: refactor-plan
    role: planner
    quality_tier: plan-gated
---

# Refactor Plan

This is an OMH `refactor-plan` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`refactor-plan` exists because boundary-changing refactors bounced between goal planning and behavior-preserving cleanup with neither owning the execution shape: the phase order, the per-phase rollback, and the files table that make a large refactor reviewable and abortable.

## Do Not Use When

- The refactor's direction is still contested or the goal itself needs consensus planning; use `ulw-plan`.
- The work is deletion-first cleanup with no boundary changes; use `omh-ai-slop-cleaner`.
- The plan is done and the claim is that work is complete; use `omh-verification-gate` for the evidence close.
- The version bump carries a security advisory, a CVE, or a leaked secret; use `omh-security-event-response`, which owns containment and closure.

## Examples

Good example:

- Prompt: We decided to split the billing module out of orders - plan the refactor so each step is shippable.
- Expected behavior: Map affected files and consumers from the import graph, name hidden coupling and blast radius, order the five phases with per-phase verification and rollback, ship the files table, and stop at the approval gate.
- Why: The direction is decided and the need is a phased, abortable execution shape - exactly this workflow's territory.

Bad example:

- Prompt: Should we even split billing out of orders?
- Expected behavior: Route to `ulw-plan`: the direction is not decided, so consensus planning comes before phase planning.
- Why: A phase plan for a contested direction launders a decision through logistics.

## Completion Checklist

- Reconnaissance names affected files, boundaries, coupling, and blast radius from observed evidence.
- Every phase carries its verification command and its rollback point, and ends at a shippable commit.
- The files table covers every touched file with action, phase, and dependencies.
- For an upgrade, every breaking change row names its call sites or an observed empty search, and every stage names its rollback.
- The plan stopped at the approval gate; no implementation began without the user's go.

## Recovery Notes

- If the import graph is unavailable, build the codegraph first or reduce the plan's confidence and say which files are unverified.
- If a phase cannot be made independently green, split it further; two half-phases beat one unabortable one.
- If reconnaissance finds the direction itself is unsettled, route back to `ulw-plan` before ordering phases.
- If the module to deepen is chosen but its interface is not, shape it under contrasting constraints and recommend one design before phase 1; that is not a contested direction.



## When to Use

Use when a refactor that crosses module boundaries is already decided and needs its execution shaped: which files move in which phase, what verifies each phase, and where each phase rolls back to - before anything is edited.

    Strong routing signals: `refactor-plan`, `refactor plan`, `plan this refactor`, `plan the refactor`, `refactor planning`, `refactor phases`, `phased refactor`, `refactor in phases`, `refactor rollback plan`, `blast radius`, `module restructure plan`, `restructure plan`, `dependency upgrade`, `major version upgrade`, `framework upgrade`, `upgrade to the next major`, `breaking change upgrade`, `lockfile`, `리팩터링 계획`, `리팩토링 계획`, `리팩터링 단계`, `단계별 리팩터링`, `리팩터링 계획 세워줘`, `리팩터링 롤백 계획`, `спланируй рефакторинг`, `план рефакторинга`, `рефакторинг по фазам`, `поэтапный рефакторинг`, `рефакторинг по шагам`

## Catalog Metadata

Category: `planning`
Phase: `refactor-plan`
Quality tier: `plan-gated`
Reasoning demand: `standard`

Quality bar:

- Reconnaissance first: affected files, ownership boundaries, hidden coupling, and blast radius are mapped before any phase is ordered; the full contract is `omh-refactor-plan/references/refactor-phases.md`.
- Order phases contracts-first: types and interfaces, then implementations, then callers in reviewable groups, then tests, then cleanup - and name what verifies each phase and where it rolls back to.
- Ship the files table with the plan: one row per file with action, phase, and blocks/blocked-by; a row without a phase is unplanned work.
- Size verification to the blast radius, not to optimism: a phase touching public surfaces or persisted shapes carries the full gate, not the fast one.
- For a dependency or framework upgrade, read four inputs before ordering phases — advisory and end-of-life intake, the licence delta at the target version, the upstream migration guide item by item against this codebase, and lockfile handling in the same commit as the manifest; a breaking change nobody checked is a gap, not a pass. The full contract is `omh-refactor-plan/references/dependency-upgrade.md`.
- Stop at the approval gate and hand the user the go/no-go, whole plan or first phase.

Required inputs:

- the decided target shape (what moves where), or a pointer to the accepted plan that decided it; for a chosen deepening candidate whose interface is still open, shape it first per `omh-refactor-plan/references/interface-shaping.md`
- the affected-file evidence: import graph, codegraph handoff, or an observed file inventory
- the regression gates that exist today (test suite, typecheck, generated-artifact checks)

Expected outputs:

- reconnaissance: affected files, ownership boundaries, hidden coupling, blast radius — and for an upgrade, the advisory, licence, migration-guide, and lockfile intake
- phase plan in the fixed order - types/interfaces, implementations, callers, tests, cleanup - each with verification and rollback
- files table: path, action, phase, blocks/blocked-by
- for an upgrade, the call-site readiness gate: every breaking change between the two versions against this repository's call sites or an observed empty search, and every stage's rollback
- the approval gate: the plan stops and waits for the user's go

Artifact expectations:

- metadata-only runtime record when a wrapper or shell is available

Safety rules:

- The plan comes from observed repo evidence, never from memory of the tree.
- An upgrade plan is not ready while any breaking change lacks its call sites or an observed empty search, or any stage lacks its rollback; name the open rows instead of calling the bump safe to merge.
- Every phase ends at a commit that could ship; a phase that cannot end green is split further.
- Nothing is deleted before the cleanup phase, and cleanup starts from a tagged rollback point.
- Do not begin implementing any phase without the user's explicit approval of the plan.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
