# Data Pipelines

Load this on-demand contract after the compact `data-pipelines` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The ask is a service's own database migration, API, or queue design; use `omh-backend`.
- The ask is analyzing, charting, or summarizing a dataset that was handed over; use `omh-data-analysis`.
- The ask is a slow query, an index, or DDL locking a live table; use `omh-relational-db`.
- The ask is remembering or syncing what the assistant knows about the user; use `omh-memory-sync`.

## Examples

Good example:

- Prompt: our airflow etl backfill is producing duplicate events
- Expected behavior: Find the sink's unique key, name the append that duplicated rows, write the idempotency contract (event-id dedupe or partition overwrite), then bound the backfill window and gate it on key uniqueness and row count against the prior window.
- Why: Rerunning an appending backfill doubles the duplicates it was meant to fix.

Bad example:

- Prompt: just delete the duplicates and rerun the whole history
- Expected behavior: Refuse the unbounded rerun: fix the write to be idempotent first, then backfill a bounded window behind a quality gate.
- Why: Deleting duplicates without fixing the write guarantees the next rerun duplicates again.

## Full Input, Output, and Artifact Expectations

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
