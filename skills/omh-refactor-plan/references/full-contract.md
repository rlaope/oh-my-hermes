# Refactor Plan

Load this on-demand contract after the compact `refactor-plan` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

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

## Full Input, Output, and Artifact Expectations

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
