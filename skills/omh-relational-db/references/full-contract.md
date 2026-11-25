# Relational Db

Load this on-demand contract after the compact `relational-db` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is a service or API change whose storage part is one section of the contract; use `omh-backend`, which owns schema_migration_plan/v1.
- The request is an end-to-end performance goal across the whole system rather than one database; use `ulw-perf`.
- The request is analysis of the data itself -- trends, metrics, a report; use `omh-data-analysis`.
- The request is watching a release roll out with its health signals and rollback criteria; use `omh-deploy-and-monitor`.

## Examples

Good example:

- Prompt: write an online migration for a 200M row table
- Expected behavior: Ask for the engine and version, then prepare online_migration_plan/v1: expand, batched backfill, switch, and contract, each step with the lock it takes, its `lock_timeout`, and its rollback, and a readiness verdict.
- Why: At 200M rows the lock each statement takes decides whether the deploy is an outage.

Bad example:

- Prompt: just add the index, it will be fine
- Expected behavior: Size the index, cite the plan it changes, build it with the non-blocking method, and name what is unverified.
- Why: An index built with a blocking statement on a large table locks writes for the whole build.

## Full Input, Output, and Artifact Expectations

Required inputs:

- engine and version, and whether it is managed or self-hosted
- the table sizes involved, in rows and bytes, and the write rate
- the query, its observed plan (`EXPLAIN (ANALYZE, BUFFERS)` or the engine's equivalent), and its latency
- for a migration: the statements, the deploy mechanism, and the longest lock the service tolerates
- observed evidence for any readiness or completion claim

Expected outputs:

- db_problem_statement/v1
- query_plan_evidence/v1 when a query is involved
- index_proposal/v1 when an index is proposed
- online_migration_plan/v1 when a table changes shape
- n_plus_one_finding/v1 when an endpoint issues per-row queries
- capacity_projection/v1 when partitioning or sharding is asked
- migration_readiness_verdict/v1

Artifact expectations:

- db_problem_statement/v1 names the engine, the version, the table sizes, and the observed symptom separately from the suspected cause
- index_proposal/v1 gives the columns in order, the index type, the estimated size, the write cost, and the non-blocking build method
- online_migration_plan/v1 gives every step its statement, the lock mode it takes and for how long, the `lock_timeout` guarding it, the backfill batch size, and its rollback
- migration_readiness_verdict/v1 reads ready only when every step states lock behaviour and a rollback; otherwise it names the steps that do not
- capacity_projection/v1 projects rows, bytes, and write rate against the single-node limit before recommending a partition or a shard
