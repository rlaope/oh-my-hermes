# Debt Dimensions and the Ledger Contract

The audit's full contract: what each dimension looks for, how findings are
graded, and how a rerun reconciles. Detection commands here are prepared
context - they count only when their output is observed.

## Orientation first

Before any dimension, establish the observed baseline:

- **Stack truth** - read the manifests (package/build/dependency files), never
  memory of the tree.
- **Churn ranking** - `git log --format= --name-only | sort | uniq -c |
  sort -rn | head -30`: the most-changed files are where debt costs the most.
- **Size ranking** - the largest source files by line count.
- **Gate inventory** - the test suites, typecheckers, linters, and CI entry
  points that already exist; debt findings that a gate already catches are
  gate-configuration findings, not new debt.

High-churn plus high-size plus low-test is the audit's priority corner.

## The nine dimensions

| Dimension | What to look for |
| --- | --- |
| Architectural decay | cyclic imports, god modules, layers bypassed, boundary leaks between packages, shallow modules (deletion test, see `references/architecture-deepening.md`) |
| Consistency rot | competing patterns for the same job - two HTTP clients, three error styles, mixed naming |
| Type and contract gaps | untyped public surfaces, `any`-equivalents, implicit schemas parsed in many places |
| Test debt | untested high-churn paths, skipped or stub tests, assertions that cannot fail |
| Dependency and configuration debt | unpinned or abandoned dependencies, drifted config copies, secrets handling by convention |
| Performance and resource debt | unbounded caches and queues, N+1 access patterns, sync work on hot paths |
| Error-handling and observability debt | swallowed exceptions, bare retries, failures invisible to logs or metrics |
| Security hygiene | credentials in the tree, injectable string building, permissive defaults |
| Documentation drift | READMEs and comments contradicting the code, dead runbooks, stale generated artifacts |

Per-stack detection commands (linters, dead-code finders, dependency and
coverage audits) are named at audit time from the manifests read in
orientation; they stay prepared_not_observed until run through the operator.

## Grading

- **Severity**: `critical` (active correctness or security risk), `high`
  (costs every change in the area), `medium` (costs some changes), `low`
  (cosmetic or contained).
- **Effort**: `S` (one bounded change), `M` (a few files, one review),
  `L` (needs `refactor-plan` phases).
- **Top fixes** rank by severity first; **quick wins** are the
  severity-at-least-medium, effort-S rows - payoff per unit of effort.
- A `critical`/`L` finding routes to `refactor-plan`; the ledger never
  recommends a rewrite.

## The ledger (`tech_debt_ledger/v1`)

One row per finding: `id`, `dimension`, `file:line`, `severity`, `effort`,
`recommendation` (bounded, actionable). Stable `id` = dimension prefix plus
path plus a short slug (`test.src-routing-chat.untested-fallback`), so reruns
can match rows without archaeology. After the table: top fixes, quick wins,
and the mandatory **looks bad but is actually fine** section - deliberate
patterns that pattern-match to debt (a generated file, an intentional
duplication, a documented workaround) stay off the ledger with their reason
recorded, so the next audit does not rediscover them.

## Rerun reconciliation

With a previous ledger present, reconcile before writing:

- **RESOLVED** - the cited evidence is gone at the cited location; name the
  commit or the observed absence.
- **CARRIED** - still present; keep the id, increment its age. A finding
  carried three audits is a prioritization finding about the ledger itself.
- **NEW** - not matched by any prior id.

Prior ids that no longer match the tree are mapped by dimension plus path
before anything is declared RESOLVED. A rerun that restarts from zero loses
the ledger's point.

## Boundary

A ledger is prepared analysis: it is not a completed cleanup, a measured
quality improvement, observed command evidence, review, CI, or merge
evidence, and every fix it recommends is separate coding work.
