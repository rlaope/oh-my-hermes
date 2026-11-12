# Interface Shaping

For a chosen deepening candidate whose interface is not decided yet. This is
the step between "deepen this module" and the phase plan: it produces the
target shape that phase 1 (types and interfaces) introduces. The approval
gate does not move.

## Frame the problem first

Before any design, write down:

- the constraints every new interface must meet - the callers that must keep
  working, the invariants they rely on, the error modes they handle;
- the dependencies behind the module and their category (in-process, local
  stand-in, owned remote, third-party; see
  `omh-tech-debt-audit/references/architecture-deepening.md`);
- how one caller uses the module today, as a short sketch that makes the
  constraints concrete. It illustrates; it does not propose.

## Design under contrasting constraints

Produce at least three interfaces, each under a different forcing
constraint. "Three options" without a constraint returns three near-copies;
a constraint forces them apart.

1. **Smallest surface** - one to three entry points, the most leverage per
   entry point.
2. **Common caller first** - the most frequent caller's case is trivial;
   rarer cases may cost more.
3. **Ports at the seams** - cross-seam dependencies are injected, and the
   adapters are named.
4. Optionally, **most flexible** - many use cases and extension points,
   mostly useful as the contrast that shows what the others gave up.

Each design states:

- the interface: entry points and parameters, plus invariants, ordering, and
  error modes;
- one caller example;
- what the implementation hides behind the seam;
- the dependency strategy and its adapters - a seam with one adapter is
  hypothetical and must name what the second will be;
- where its leverage is thin.

The designs are separate lanes - parallel delegation where the host has it,
otherwise sequential. Each lane starts from the same written brief, never from another
lane's draft, so one design does not anchor the next.

## Compare, then recommend one

Compare the designs on **depth** (behaviour per unit of interface),
**locality** (where future change and bugs land), and **seam placement**
(what varies across the seam, and whether something real does). Recommend
one design, or a named hybrid that says which part comes from which design.
Do not hand back a menu.

The recommended interface becomes the plan's target shape: phase 1 adds it
beside the old one, and the tests phase moves coverage onto it
(`references/refactor-phases.md`).

## Boundary

The designs and the comparison are prepared context. A recommendation is not
approval: the plan still stops at its approval gate, and no design is
implemented before the user's go.

## Attribution

Designing under contrasting constraints and comparing on depth, locality, and
seam placement adapt ideas from Matt Pocock's `codebase-design` skill at
`mattpocock/skills@7739eaed7f8f3915437a8def198a6d0d7206dbc7`, MIT License, Copyright 2026 Matt Pocock, which
builds on John Ousterhout's "design it twice". OMH keeps one approval gate in
place of a question loop.
