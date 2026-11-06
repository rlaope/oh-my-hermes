---
name: "omh-relational-db"
description: "[omh] Database work on a relational store -- a slow query, an index to size, a migration on a big table, a lock taken during deploy, N+1 queries: plan it with the checks that prove it safe, and never call a migration ready without its lock behaviour and rollback. Use when the user says: relational-db, relational database, online migration, migration for a large table, lock-safe ddl, alter table, took a lock, table lock."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: relational-db
    role: planner
    quality_tier: db-lock-and-rollback-gated
---

# Relational Db

This is an OMH `relational-db` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`relational-db` exists because the database work itself had no owner: `omh-backend` owns `schema_migration_plan/v1` for a service change, and an index question, a lock taken during deploy, or an N+1 finding was answered by a data, deploy, or interview lane with no lock model at all.

## First Steps

- Ask for the engine, the version, and the table sizes before proposing any statement.
- For a migration, give every step its lock behaviour and its rollback before calling the plan ready.

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

## Completion Checklist

- Engine, version, and table sizes are stated.
- Every proposed index cites an observed plan or is marked unverified.
- Every migration step states its lock mode, its duration bound, and its rollback.
- The readiness verdict is ready only when no step lacks lock behaviour or rollback.
- Nothing was connected to, run, or applied by OMH.

## Recovery Notes

- If the engine or version is unknown, plan for the most restrictive lock behaviour and say so.
- If no query plan is available, ask for the observed plan before proposing an index, and mark any proposal unverified.



## When to Use

Use when the work is the database itself on a relational engine such as Postgres or MySQL: a slow query and the index that fixes it, an online migration on a large table, DDL that took or would take a lock during deploy, N+1 queries from an endpoint, or when to partition or shard. The output is a plan plus the checks that prove it safe to run; OMH never connects to a database.

    Strong routing signals: `relational-db`, `relational database`, `online migration`, `migration for a large table`, `lock-safe ddl`, `alter table`, `took a lock`, `table lock`, `lock during deploy`, `create index concurrently`, `which index`, `what index`, `missing index`, `index size`, `seq scan`, `seq-scans`, `sequential scan`, `explain analyze`, `query plan`, `n+1`, `n+1 query`, `n+1 queries`, `need to shard`, `shard the database`, `database sharding`, `table partitioning`, `partition the table`, `index bloat`, `postgres lock`, `mysql online ddl`

## Catalog Metadata

Category: `planning`
Phase: `relational-db`
Quality tier: `db-lock-and-rollback-gated`
Reasoning demand: `standard`

Quality bar:

- State the engine and version first; lock behaviour differs by engine and by version.
- Load `references/engine-lock-tables.md` for the per-engine lock modes, the online DDL rules, and index-type selection instead of recalling them.
- Size an index before proposing it: rows, key width, and the write amplification it adds.
- Order an online migration as expand, backfill in batches, switch, contract, with the rollback for each step.
- For a read-modify-write, an upsert, a queue table, or a deadlock, use the concurrency section of the lock tables: name the isolation level, the row lock and its order, and which error codes retry the whole transaction.
- Give non-transactional DDL such as `CREATE INDEX CONCURRENTLY` its own migration marked non-transactional; never drop `CONCURRENTLY` to satisfy the migration tool.
- Keep planned, observed, and applied as separate states for every statement.

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

Safety rules:

- A migration plan cannot be ready while any step lacks a stated lock behaviour or a rollback; `migration_readiness_verdict/v1` names each such step instead.
- Never recommend an index from a guess: cite the observed plan it changes, or mark the proposal unverified until the plan is observed.
- Build indexes on live tables with the engine's non-blocking method (`CREATE INDEX CONCURRENTLY`, online DDL `LOCK=NONE`), and state what that method cannot do.
- OMH never connects to a database, and does not claim a plan, a row count, a lock wait, or an applied migration it did not observe.
- Never put connection strings, credentials, or customer rows into the plan or the handoff.

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
