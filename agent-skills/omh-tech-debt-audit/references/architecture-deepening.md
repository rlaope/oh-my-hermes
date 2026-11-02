# Architecture Deepening

The audit's second reading. Instead of debt in general, it looks for places
where a small interface could hide much more behaviour. Its output is still
`tech_debt_ledger/v1` rows in the architectural-decay dimension, graded,
ranked, and reconciled like every other finding. It stops before any
interface is proposed.

## Terms

Defined here for this reading only; "boundary" keeps its OMH meaning
(evidence boundary, scope boundary) everywhere.

- **Module** - anything with an interface and an implementation, at any
  scale: a function, a class, a package, a slice across tiers.
- **Interface** - everything a caller must know to use the module correctly:
  the signature, plus invariants, ordering, error modes, required
  configuration, and cost.
- **Depth** - behaviour a caller or test reaches per unit of interface it has
  to learn. Deep: much behaviour behind a small interface. Shallow: the
  interface is nearly as large as what it hides.
- **Seam** - where the interface sits; behaviour can be swapped there without
  editing the callers.
- **Adapter** - a concrete thing that fills a seam.
- **Locality** - change, bugs, and verification concentrate in one place.
- **Leverage** - one implementation pays back across many callers and tests.

## Where to look

Scope before scanning. A direction the user named (a module, a subsystem, a
pain point) is the scope. Otherwise the orientation's churn ranking picks it:
deepening pays off where code keeps changing, so the most-changed files come
first.

Questions that surface candidates:

- Does understanding one concept mean hopping across several small modules?
- Is a module's interface nearly as large as its body?
- Was a pure helper extracted only so it could be tested, while the bugs live
  in how callers combine it?
- Do callers reach across a seam into another module's internals?
- Can a behaviour be tested only by going past the current interface?

## The deletion test

A shallow claim needs this evidence; size and line counts never substitute
for it. Imagine deleting the module and inlining it into its callers. If the
complexity vanishes - it only forwarded, renamed, or re-wrapped - the module
was a pass-through and is a candidate. If the same complexity reappears
across its callers, the module earns its keep, whatever its size or caller
count. Record which way the test went and name the callers it was run
against.

## Dependency category

The category of a candidate's dependencies decides how the deepened module
will be tested:

| Category | How the deepened module is tested |
| --- | --- |
| In-process (pure computation, in-memory state) | merge the modules and test through the new interface directly |
| Local stand-in exists (a local instance of the same engine, an in-memory filesystem) | run the stand-in in the suite; the seam stays internal |
| Owned remote (the team's own service across a network) | a port at the seam with a production adapter and an in-memory adapter |
| Third-party (a service the team does not control) | an injected port with a test adapter |

One adapter makes a hypothetical seam; two make a real one. A port that only
one adapter will ever fill is indirection, not a win.

## Recorded decisions

Before listing, read the decision records for the area (`docs/adr/`, or
`decision-recall` where it is installed). A candidate that contradicts a
recorded decision is listed only when its friction is strong enough to reopen
the decision, and the row names the record. Otherwise it goes on the
looks-bad-but-is-actually-fine list with the record as its reason.

## Candidate rows

Each candidate is a `tech_debt_ledger/v1` row in the architectural-decay
dimension: `id`, `dimension`, `file:line`, `severity`, and `effort` as usual,
and the **deepening** - one sentence on what moves behind which interface -
fills `recommendation`. These columns are added to the row:

- **files** - the modules involved;
- **friction** - one sentence on what the current shape costs;
- **wins** - stated as locality, leverage, or test surface, never "cleaner";
- **dependency category** - from the table above;
- **strength** - `strong`, `worth exploring`, or `speculative`.

Candidates rank by severity, then strength. The top pick is the first
candidate in that order and sits in the ledger's top fixes; a deepening is
rarely effort `S`, and one that is appears among the quick wins as well.

The before-picture of a candidate is derived, never drawn. For a Python
candidate where the `omh` CLI is installed (its codegraph reads Python
sources only), `omh codegraph uml --focus <candidate path>` renders the
current structure with its omissions legend (`codebase-uml`); otherwise the
cited files stand in for it. The after-shape stays the one-sentence
deepening. A future structure has no tree to derive a picture from, and a
hand-drawn one would present a guess as structure.

## Stop rule

The audit ends at the ranked candidates and one named top pick with its
reason. It proposes no interface. When the user picks a candidate, its
interface is shaped in `refactor-plan`
(`omh-refactor-plan/references/interface-shaping.md`), and that plan keeps
its own approval gate.

## Attribution

The deep-module vocabulary, the deletion test, the dependency categories, and
the candidate fields adapt ideas from Matt Pocock's
`improve-codebase-architecture` and `codebase-design` skills at
`mattpocock/skills@7739eaed7f8f3915437a8def198a6d0d7206dbc7`, MIT License, Copyright 2026 Matt Pocock. OMH keeps
candidates in its debt ledger and plans them behind one approval gate.
