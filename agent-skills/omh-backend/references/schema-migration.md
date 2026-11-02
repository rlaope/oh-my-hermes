# Schema and Migration Discipline

Load this when the prepared backend change touches storage. OMH writes no migration and applies none; this is the order the plan has to have before an executor runs anything.

## 1. Expand, backfill, switch, contract

A schema change that is deployed as one step is a schema change that cannot be rolled back once traffic has touched it. Split every storage change into four:

1. **Expand.** Add the new column, table, or index. Nothing reads it. Old code keeps working unchanged. This step is reversible by dropping what was added.
2. **Backfill.** Populate the new shape from the old one in bounded batches. Reversible by ignoring the new shape. Name the batch size and the pause between batches; an unbounded backfill on a live table is an outage.
3. **Switch.** Move reads, then writes, to the new shape. This is the step where a rollback means reverting code, not reverting data.
4. **Contract.** Drop the old column, table, or index -- only after the switch has been observed stable for a named period. This step is irreversible.

Each step names its own rollback point. If a step's rollback is "restore from backup", that step is a blocker until it is split further.

## 2. The blocker list

Any of these is a blocker until the plan resolves it explicitly:

- A `DROP` or destructive `ALTER` in the same deployment as the code that stops using it.
- A backfill with no batch bound, no progress measure, and no resume point.
- A rename presented as one step. A rename is expand plus backfill plus switch plus contract, always.
- A new `NOT NULL` column with no default on a populated table.
- An index creation on a large table without naming whether the engine builds it concurrently.
- A migration that must run inside the same transaction as a long backfill.
- A statement that cannot run in a transaction (`CREATE INDEX CONCURRENTLY`) inside a migration the tool wraps in one. Mark that migration non-transactional in the tool and keep the statement alone in it; dropping `CONCURRENTLY` to make the tool accept it turns an online build into a write lock.
- Two deployments that must land in a specific order with nothing enforcing the order.

## 3. Compatibility window

Between expand and contract, both shapes exist and both must work. The plan states:

- Which application versions are expected to be live at the same time.
- What the old code does when it encounters a row written by the new code, and the reverse.
- How long the window stays open, and what closes it.

A migration plan with no stated compatibility window is a plan that assumes atomic deployment, which no multi-instance service has.

## 4. What counts as evidence

| Claim | Evidence that supports it |
| --- | --- |
| The migration is written | the migration file exists in the diff |
| The migration applies | an observed run against a database, with its output |
| The backfill completed | observed row counts before and after, not the script's exit code alone |
| The switch is safe | observed reads and writes on the new shape under real traffic shape |
| The contract step is safe | an observed stable period after the switch, with the duration named |

A prepared plan supports none of these. Every row above stays `not_observed` until the executor reports the observation.
