# Refactor Phases

The phase contract for a boundary-changing refactor whose direction is already
decided. The plan is the deliverable; implementation starts only after the
user approves it, phase by phase if they choose.

## Reconnaissance before phases

Map the territory before ordering the work:

- **Affected files** - every file the change touches, from the actual import
  graph (a codegraph handoff is the prepared input when available), not from
  memory. Each file enters the plan's table as modify, create, or delete.
- **Ownership boundaries** - which modules own the symbols that move, and who
  else imports them. A consumer outside the mapped set found later is a plan
  defect, not a surprise.
- **Hidden coupling** - shared mutable state, import cycles, reflection or
  string-keyed lookups, test fixtures that reach into internals. Each one is
  named in the plan with the phase that unwinds it.
- **Blast radius** - the observable surfaces that could change if a phase goes
  wrong: public APIs, CLI output, generated artifacts, persisted schemas.
  The radius decides the verification depth, not optimism.
- **Regression gates** - the tests, typecheck, and generated-artifact checks
  that cover the affected files today. Where none cover them, the plan opens
  with a Phase 0 of characterization tests for the blast-radius surfaces, and
  every later phase's verification is that suite. If the user declines them,
  say each phase is unverified and stop at the approval gate.

## The phase order

Contracts precede implementations, implementations precede callers, callers
precede tests, tests precede cleanup:

1. **Types and interfaces** - introduce the target contracts beside the old
   ones; nothing calls them yet. Verification: the build and typecheck gate.
   Rollback: delete the additions.
2. **Implementations** - fill the new contracts, old paths still live.
   Verification: new-path unit tests plus the untouched existing suite.
   Rollback: revert this phase alone; callers never moved.
3. **Callers** - move call sites in reviewable groups; both paths stay green
   until the last group lands. Verification: the full suite per group.
   Rollback: revert the group, not the phase.
4. **Tests** - retarget tests that asserted the old shape; add the boundary
   locks the new shape needs. A test that reaches past the new interface is
   rewritten through it, or deleted once an interface-level test observes the
   same behaviour; keeping both layers makes every later internal change edit
   two suites. Name each deleted test and the interface test that covers it.
   Verification: the full suite, plus a check that coverage did not silently
   narrow.
5. **Cleanup** - delete the old contracts and their shims; this is the first
   phase that removes production code (phase 4 deletes only tests that an
   interface-level test now covers). Verification: the full suite plus a
   dead-code sweep. Rollback: restore from the tag cut before cleanup.

Every phase ends at a commit that could ship. A phase that cannot end green
is split further or its plan is wrong.

A phase that changes a persisted or wire shape (a table, a stored format, a
queue payload, a config shape) follows expand, migrate or dual-write, switch
reads, then contract; each step runs with the code of the step before it,
because old and new code meet during a rolling deploy. A code revert does not
undo data already written in the new shape. For each phase say whether its
rollback is a code revert or a data restore, and name the point after which
only a restore works.

## The plan's table

One row per file: path, action (modify/create/delete), phase, blocks /
blocked-by. A row without a phase is unplanned work; a phase without rollback
is a bet, not a plan.

## The approval gate

The plan stops here. State the phases, the table, the blast radius, and the
per-phase verification, then wait for the user's go - whole plan or first
phase. Implementation, however approved, is executor work under the coding
lane's own evidence rules.

## Boundary

A refactor plan is prepared context: it is not implementation, migration,
verification, review, CI, or merge evidence, and an approved plan does not
make its phases' verification claims true in advance.
