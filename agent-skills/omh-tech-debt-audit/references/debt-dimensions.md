# Debt Dimensions and the Ledger Contract

The audit's full contract: what each dimension looks for, how findings are
graded, and how a rerun reconciles. Detection commands here are prepared
context - they count only when their output is observed.

## Orientation first

Before any dimension, establish the observed baseline:

- **Stack truth** - read the manifests (package/build/dependency files), never
  memory of the tree.
- **Churn ranking** - the most-changed files are where debt costs the most, but
  an all-history count is led by changelogs, lockfiles, and generated docs. Use a
  window, skip merges, drop those paths, keep only files that still exist, keep
  the count, and run it from the repository top level (paths are relative to it).
  Also drop every path the repository declares generated:

  ```sh
  cd "$(git rev-parse --show-toplevel)"
  git -c core.quotePath=false log --since=12.months --no-merges --format= --name-only \
    | grep -v -E '(^|/)(CHANGELOG[^/]*|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.lock|poetry\.lock|uv\.lock)$|\.snap$|\.min\.' \
    | sort | uniq -c | sort -rn \
    | while read -r n f; do [ -e "$f" ] && echo "$n $f"; done | head -30
  ```
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
| Security hygiene | injectable string building, permissive defaults; a live-looking credential in the tree is not a ledger row (see below) |
| Documentation drift | READMEs and comments contradicting the code, dead runbooks, stale generated artifacts |

Per-stack detection commands (linters, dead-code finders, dependency and
coverage audits) are named at audit time from the manifests read in
orientation; they stay prepared_not_observed until run through the operator.

## Grading

- **Severity**: `critical` (active correctness or security risk), `high`
  (costs every change in the area), `medium` (costs some changes), `low`
  (cosmetic or contained).
- **Effort**: `S` (one bounded change), `M` (a few files, one review),
  `L` (needs `omh-refactor-plan` phases).
- **Top fixes** rank by severity first; **quick wins** are the
  severity-at-least-medium, effort-S rows - payoff per unit of effort.
- A `critical`/`L` finding routes to `omh-refactor-plan`; the ledger never
  recommends a rewrite.

A live-looking credential found in the tree stops the ledger. Cite path and
line only, never the value; route to `omh-security-event-response` (rotate, then
clean history). Placeholders and test fixtures go on the looks-bad-but-fine
list with the reason.

## The ledger (`tech_debt_ledger/v1`)

One row per finding: `id`, `dimension`, `file:line`, `severity`, `effort`,
`recommendation` (bounded, actionable). Stable `id` = dimension prefix plus
path plus a short slug (`test.src-routing-chat.untested-fallback`), so reruns
can match rows without archaeology. After the table: top fixes, quick wins,
and the mandatory **looks bad but is actually fine** section - deliberate
patterns that pattern-match to debt (a generated file, an intentional
duplication, a documented workaround) stay off the ledger with their reason
recorded, so the next audit does not rediscover them.

Write the ledger to a file the user names (default `docs/tech-debt-ledger.md`)
as a Markdown table carrying the stable ids, and end the reply with its path.
On a rerun with no path given, look for that file; when none exists, say this
is a first audit.

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
