---
name: "omh-data-pipelines"
description: "[omh] Data pipeline work on an ETL or streaming job: a backfill or replay, duplicate events, a schema change downstream, a lineage question, a data-quality regression; make every rerun idempotent, bound every replay, and gate each load on observed checks. Use when the user says: data-pipelines, data pipeline, data pipelines, etl, elt, etl pipeline, etl job, etl backfill."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: data-pipelines
    role: planner
    quality_tier: idempotent-replay-gated
    related_skills: [omh-backend, omh-data-analysis, omh-relational-db, omh-memory-sync]
---

# Data Pipelines

Required: the pipeline: its orchestrator, its sources, its sinks, and its schedule or trigger, the unit of the problem: the table, topic, or model, and the time window affected, what makes a row unique at the sink: the natural key, the event id, or the partition, the downstream readers already known: models, dashboards, exports, services, observed counts, job logs, or check results for any claim about what was loaded. Output: lineage_map/v1, schema_change_impact/v1, idempotency_contract/v1, replay_backfill_plan/v1, data_quality_gate/v1.

## Why This Exists

`data-pipelines` exists because pipeline work had no owner: `omh-backend` owns a service's schema migration, `omh-data-analysis` analyzes data it is handed, and `omh-relational-db` owns a database's locks and indexes, while a backfill that duplicated events or a schema change with unknown readers reached memory and event lanes with no idempotency contract or replay bound at all.

## First Steps

- Ask what makes a row unique at the sink before planning any rerun.
- Bound the window and the targets before ordering any replay or backfill step.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Coding handoff** - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when a batch or streaming data pipeline needs planning or repair: an ETL, ELT, Airflow, dbt, Spark or Kafka job; a backfill or a replay of past events; duplicate or missing rows; a schema change whose downstream readers are unknown; a lineage question; or a data-quality regression. The output is the lineage, the schema change's downstream impact, an idempotency contract, a bounded replay or backfill plan, and the data-quality gate each load must pass; OMH runs no job and reads no warehouse.

    Strong routing signals: `data-pipelines`, `data pipeline`, `data pipelines`, `etl`, `elt`, `etl pipeline`, `etl job`, `etl backfill`, `airflow dag`, `airflow etl`, `airflow backfill`, `dagster`, `dbt model`, `dbt run`, `spark job`, `kafka topic`, `kafka events`, `kafka consumer`, `backfill`, `data backfill`, `replay events`, `replay the events`, `event replay`, `idempotent`, `idempotency`, `exactly once`, `exactly-once`, `duplicate events`, `lineage`, `data lineage`, `data quality`, `data quality check`, `schema evolution`, `late arriving data`, `dead letter queue`, `batch job`

## Catalog Metadata

Category: `planning`
Phase: `data-pipelines`
Hermes role: `planner`
Quality tier: `idempotent-replay-gated`
Reasoning demand: `standard`

Quality bar:

- Find what makes a row unique at the sink before proposing any rerun.
- Load `references/pipeline-method.md` for the idempotency patterns, the schema compatibility table, the replay and backfill procedure, and the quality checks instead of recalling them.
- Map lineage from the orchestrator's graph first and mark anything found only by search.
- Treat duplicates as an idempotency defect, not a cleanup task: fix the write, then repair the rows.
- Keep prepared, run, and verified as separate states for every load and check.

Handoff policy:

Keep the lineage map, schema impact, idempotency contract, replay or backfill plan, and quality gates in Hermes. Row counts, job runs, query results and check outcomes are recorded only from executor, operator, or wrapper observed output; OMH never runs a pipeline, triggers a backfill, or queries a warehouse.

Safety rules:

- Never plan a replay or backfill without an idempotency contract; a rerun that appends is how the duplicates got there.
- Bound every replay and backfill by window and target; an unbounded rerun rewrites history nobody asked about.
- A breaking schema change waits until every downstream reader in the lineage map is adapted or named as accepting the break.
- Do not publish a load to readers before its data-quality gate is observed; a prepared check is not a passed one.
- OMH never runs a job, triggers a backfill, or queries a warehouse; every count and check comes from observed output or is marked unverified.

## Completion Checklist

- The sink's unique key and the idempotency contract are stated.
- Every replay or backfill is bounded by window and target.
- Every downstream reader of a schema change is named with its impact.
- Every load names its data-quality gate and the value that stops it.
- OMH ran nothing, and every count cites observed output or is marked unverified.

## Recovery Notes

- If no unique key exists at the sink, the first step is defining one; say so before any rerun.
- If lineage is unavailable, list readers found by search and mark the map incomplete.

## Runtime Evidence

Preferred harness for this skill: `coding-handling`.

```sh
omh runtime record --skill data-pipelines --harness coding-handling --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
