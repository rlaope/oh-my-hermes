---
name: "omh-data-pipelines"
description: "[omh] Data pipeline work -- an ETL or streaming job, a backfill or replay, duplicate events, a schema change downstream, a lineage question."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: data-pipelines
    role: planner
    quality_tier: idempotent-replay-gated
---

# Data Pipelines

This is an OMH `data-pipelines` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`data-pipelines` exists because pipeline work had no owner: `omh-backend` owns a service's schema migration, `omh-data-analysis` analyzes data it is handed, and `omh-relational-db` owns a database's locks and indexes, while a backfill that duplicated events or a schema change with unknown readers reached memory and event lanes with no idempotency contract or replay bound at all.

## First Steps

- Ask what makes a row unique at the sink before planning any rerun.
- Bound the window and the targets before ordering any replay or backfill step.

## Do Not Use When

- The ask is a service's own database migration, API, or queue design; use `omh-backend`.
- The ask is analyzing, charting, or summarizing a dataset that was handed over; use `omh-data-analysis`.
- The ask is a slow query, an index, or DDL locking a live table; use `omh-relational-db`.
- The ask is remembering or syncing what the assistant knows about the user.

## Examples

Good example:

- Prompt: our airflow etl backfill is producing duplicate events
- Expected behavior: Find the sink's unique key, name the append that duplicated rows, write the idempotency contract (event-id dedupe or partition overwrite), then bound the backfill window and gate it on key uniqueness and row count against the prior window.
- Why: Rerunning an appending backfill doubles the duplicates it was meant to fix.

Bad example:

- Prompt: just delete the duplicates and rerun the whole history
- Expected behavior: Refuse the unbounded rerun: fix the write to be idempotent first, then backfill a bounded window behind a quality gate.
- Why: Deleting duplicates without fixing the write guarantees the next rerun duplicates again.

## Completion Checklist

- The sink's unique key and the idempotency contract are stated.
- Every replay or backfill is bounded by window and target.
- Every downstream reader of a schema change is named with its impact.
- Every load names its data-quality gate and the value that stops it.
- OMH ran nothing, and every count cites observed output or is marked unverified.

## Recovery Notes

- If no unique key exists at the sink, the first step is defining one; say so before any rerun.
- If lineage is unavailable, list readers found by search and mark the map incomplete.



## When to Use

Use when a batch or streaming data pipeline needs planning or repair: an ETL, ELT, Airflow, dbt, Spark or Kafka job; a backfill or a replay of past events; duplicate or missing rows; a schema change whose downstream readers are unknown; a lineage question; or a data-quality regression. The output is the lineage, the schema change's downstream impact, an idempotency contract, a bounded replay or backfill plan, and the data-quality gate each load must pass; OMH runs no job and reads no warehouse.

    Strong routing signals: `data-pipelines`, `data pipeline`, `data pipelines`, `etl`, `elt`, `etl pipeline`, `etl job`, `etl backfill`, `airflow dag`, `airflow etl`, `airflow backfill`, `dagster`, `dbt model`, `dbt run`, `spark job`, `kafka topic`, `kafka events`, `kafka consumer`, `backfill`, `data backfill`, `replay events`, `replay the events`, `event replay`, `idempotent`, `idempotency`, `exactly once`, `exactly-once`, `duplicate events`, `lineage`, `data lineage`, `data quality`, `data quality check`, `schema evolution`, `late arriving data`, `dead letter queue`, `batch job`

## Catalog Metadata

Category: `planning`
Phase: `data-pipelines`
Quality tier: `idempotent-replay-gated`
Reasoning demand: `standard`

Quality bar:

- Find what makes a row unique at the sink before proposing any rerun.
- Load `references/pipeline-method.md` for the idempotency patterns, the schema compatibility table, the replay and backfill procedure, and the quality checks instead of recalling them.
- Map lineage from the orchestrator's graph first and mark anything found only by search.
- Treat duplicates as an idempotency defect, not a cleanup task: fix the write, then repair the rows.
- Keep prepared, run, and verified as separate states for every load and check.

Required inputs:

- the pipeline: its orchestrator, its sources, its sinks, and its schedule or trigger
- the unit of the problem: the table, topic, or model, and the time window affected
- what makes a row unique at the sink: the natural key, the event id, or the partition
- the downstream readers already known: models, dashboards, exports, services
- observed counts, job logs, or check results for any claim about what was loaded

Expected outputs:

- lineage_map/v1
- schema_change_impact/v1
- idempotency_contract/v1
- replay_backfill_plan/v1
- data_quality_gate/v1

Artifact expectations:

- lineage_map/v1 names each upstream source and each downstream reader of the affected table, topic, or model, from the orchestrator's graph or a lineage record, and marks readers found by search rather than by the graph
- schema_change_impact/v1 classifies the change as additive, widening, or breaking for each downstream reader, and names the reader that breaks and the order that avoids it
- idempotency_contract/v1 names the key that makes a rerun safe -- a natural key upsert, an event-id dedupe window, or a partition overwrite -- and what happens to a row written twice
- replay_backfill_plan/v1 bounds the window, names the target partitions or offsets, pauses or isolates downstream readers, and writes through the idempotency contract so a second run changes nothing
- data_quality_gate/v1 names the observed checks each load must pass before readers see it -- row count against the prior window, key uniqueness, null rate, freshness -- and the value that stops the load

Safety rules:

- Never plan a replay or backfill without an idempotency contract; a rerun that appends is how the duplicates got there.
- Bound every replay and backfill by window and target; an unbounded rerun rewrites history nobody asked about.
- A breaking schema change waits until every downstream reader in the lineage map is adapted or named as accepting the break.
- Do not publish a load to readers before its data-quality gate is observed; a prepared check is not a passed one.
- OMH never runs a job, triggers a backfill, or queries a warehouse; every count and check comes from observed output or is marked unverified.

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
