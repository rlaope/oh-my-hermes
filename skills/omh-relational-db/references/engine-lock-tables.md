# Engine Lock Tables

Load this while planning database work. OMH never connects to a database: every statement, plan, and lock wait below is something the executor or operator runs and reports back. Lock behaviour differs by engine and by version, so state both before reading a row here, and when the version is unknown plan for the most restrictive row.

## 1. PostgreSQL lock modes by statement

| Statement | Lock taken | Blocks | Online alternative |
| --- | --- | --- | --- |
| `CREATE INDEX` | `SHARE` | writes for the whole build | `CREATE INDEX CONCURRENTLY` (`SHARE UPDATE EXCLUSIVE`; no transaction block; an invalid index is left behind on failure and must be dropped) |
| `DROP INDEX` | `ACCESS EXCLUSIVE` | reads and writes | `DROP INDEX CONCURRENTLY` |
| `ALTER TABLE ... ADD COLUMN` (nullable, or constant default on 11+) | `ACCESS EXCLUSIVE`, brief | everything, while queued behind long transactions | set `lock_timeout` and retry |
| `ALTER TABLE ... ADD COLUMN ... DEFAULT volatile()` | `ACCESS EXCLUSIVE` + table rewrite | everything for the rewrite | add nullable, backfill in batches, then set the default |
| `ALTER TABLE ... SET NOT NULL` | `ACCESS EXCLUSIVE` + full scan | everything for the scan | `ADD CONSTRAINT ... CHECK (col IS NOT NULL) NOT VALID`, `VALIDATE CONSTRAINT`, then `SET NOT NULL` (12+ skips the scan) |
| `ALTER TABLE ... ADD FOREIGN KEY` | `SHARE ROW EXCLUSIVE` on both tables + scan | writes | `ADD CONSTRAINT ... NOT VALID`, then `VALIDATE CONSTRAINT` |
| `ALTER TABLE ... ALTER COLUMN TYPE` | `ACCESS EXCLUSIVE` + rewrite (most types) | everything | new column, dual write, backfill, switch, drop |
| `VACUUM FULL`, `CLUSTER` | `ACCESS EXCLUSIVE` + rewrite | everything | `pg_repack` or plain `VACUUM` |

Every DDL statement on a live table runs under `SET lock_timeout = '2s'` (or the service's tolerance) with a retry. Without it, a statement queued behind one long transaction blocks every query that arrives after it, which is how a sub-second `ALTER` becomes an outage.

## 2. MySQL (InnoDB) online DDL

| Operation | `ALGORITHM` | `LOCK` | Note |
| --- | --- | --- | --- |
| Add a secondary index | `INPLACE` | `NONE` | concurrent DML allowed; brief metadata lock at start and end |
| Add a column (8.0.12+, last position) | `INSTANT` | none | no rebuild |
| Add a column elsewhere, or before 8.0.12 | `INPLACE` with rebuild | `NONE` | rebuilds the table |
| Change a column type | `COPY` | `SHARED` | blocks writes; use `gh-ost` or `pt-online-schema-change` |
| Drop the primary key | `COPY` | `SHARED` | blocks writes |

State `ALGORITHM=... , LOCK=...` explicitly in the statement so the server refuses instead of silently falling back to a blocking copy. Every DDL still waits for a metadata lock; a long transaction holds it up and queues everything behind it, so bound it with `lock_wait_timeout`.

## 3. Online migration order

1. **Expand**: add the new column, table, or index without breaking current code.
2. **Backfill** in batches keyed on the primary key: a bounded row count per batch, a pause between batches, progress recorded, restartable.
3. **Switch**: deploy code that reads the new shape; dual-write while both exist.
4. **Contract**: drop the old shape only after the switch is observed in production.

Every step carries its statement, the lock it takes and for how long, its timeout, and its rollback. A plan with any step missing lock behaviour or rollback is not ready.

- **Non-transactional DDL gets its own migration.** Most migration tools wrap each migration in a transaction, and `CREATE INDEX CONCURRENTLY` (and `DROP INDEX CONCURRENTLY`) refuses to run inside one. Mark that migration non-transactional in the project's tool and keep the statement alone in it. Removing `CONCURRENTLY` to get past the error turns an online build into a write lock.
- **Each backfill batch runs under a `statement_timeout`** sized to the batch, beside the `lock_timeout`, so a batch that hits a slow plan fails fast and resumes instead of holding locks.
- **Read the SQL that will run.** When an ORM or migration tool generates the statement, plan against the SQL it emits (its statement log or its to-SQL output), not against the call that produced it.

## 4. Index selection and sizing

| Need | Index type |
| --- | --- |
| Equality and range on scalar columns | B-tree, most selective equality column first, range column last |
| Array, JSONB containment, full-text | GIN |
| Geometric, range overlap, nearest neighbour | GiST |
| Huge append-only table ordered by time | BRIN |
| Query touches a known subset | partial index with that `WHERE` |
| Query reads few columns | covering index (`INCLUDE`) for an index-only scan |
| Keyset (cursor) pagination: `WHERE (sort_col, id) > ($1, $2) ORDER BY sort_col, id LIMIT n` | B-tree on the equality-filter columns first, then the sort columns in sort direction, then the unique tie-breaker; the plan shows an index scan with no sort step. Mixed sort directions need the index to match them and the predicate written as `OR` terms, because a row comparison assumes one direction. On MySQL write the expanded `OR` form even for a single direction, because an equality prefix followed by a row comparison uses only the prefix columns of the index; check that the plan's `key_len` and range cover the sort columns, not only that there is no filesort |

Size before proposing: rows times (key width plus about 20 bytes of per-entry overhead), plus fill-factor slack. Every index adds a write per insert and per update of its columns; name that cost next to the read it saves. Cite the observed plan the index changes (`EXPLAIN (ANALYZE, BUFFERS)`), and re-read the plan after the build.

## 5. N+1 queries

The symptom is one query for the list and one more per row, and the count scales with page size. Confirm it from the query log or the ORM's statement counter, not from reading the code. Fix it with an eager load (`JOIN`, `IN (...)` batch, or the ORM's preload) and pin it with a test that asserts the statement count for a page of N rows.

## 6. When to partition or shard

Project rows, bytes, and write rate for 12 to 24 months. Partition when one table's maintenance (vacuum, index builds, retention deletes) outgrows its window; partitioning keeps one node. Shard only when a single primary cannot hold the write rate or the working set after vertical scaling, read replicas, and partitioning; name the shard key, the cross-shard queries it breaks, and the rebalancing plan.

## 7. Concurrency

Sections 1 and 2 cover the locks DDL takes. These rules cover two transactions writing the same rows.

| | PostgreSQL | MySQL (InnoDB) |
| --- | --- | --- |
| Default isolation | `READ COMMITTED` | `REPEATABLE READ` |
| Serialization failure | SQLSTATE `40001`, at `REPEATABLE READ` and `SERIALIZABLE` | not raised at the default level; a plain `SELECT` reads an old snapshot while `UPDATE` sees the latest row |
| Rollback scope after an error | any error aborts the whole transaction; only a savepoint taken before the statement lets the transaction continue | depends on the error; see the two rows below |
| Deadlock | SQLSTATE `40P01` | error 1213 (SQLSTATE `40001`); the whole transaction is rolled back |
| Lock wait timeout | `lock_timeout` raises SQLSTATE `55P03`; the transaction is aborted | error 1205; by default only the statement is rolled back, so either retry that statement or `ROLLBACK` before retrying the whole transaction |
| Upsert | `INSERT ... ON CONFLICT (cols) DO UPDATE` / `DO NOTHING`, with a unique index matching the conflict target | `INSERT ... ON DUPLICATE KEY UPDATE`, which fires on any unique key; with more than one unique key the row it updates is ambiguous |
| Queue table | `SELECT ... FOR UPDATE SKIP LOCKED` (9.5+) | `SELECT ... FOR UPDATE SKIP LOCKED` (8.0+) |

- **Read-modify-write takes the row lock first.** Read with `SELECT ... FOR UPDATE`, or move the arithmetic into the `UPDATE` itself (`SET qty = qty - $1 WHERE id = $2 AND qty >= $1`) and check the affected row count. A version column compared in the `WHERE` clause works without holding a lock across the read.
- **A check-then-insert is a race.** Insert under the unique constraint and handle the violation, or use the upsert row above. Never select first and insert if absent.
- **Lock rows in one order.** Two transactions that lock the same rows in different orders deadlock. Lock in a fixed order, for example `ORDER BY id` in the `FOR UPDATE` query, and lock parents before children everywhere.
- **Retry the whole transaction, with a bound.** A serialization failure or a deadlock is retried by re-running the transaction from its start, with backoff and a maximum attempt count; retrying the failed statement alone runs it without the locks and effects of the statements before it, which the rollback already undid. On PostgreSQL every error aborts the transaction, so a whole-transaction retry always starts with `ROLLBACK`; a savepoint only lets you handle other errors inside the transaction, never `40001`/`40P01`. A MySQL lock wait timeout (1205) leaves the transaction open: retry that statement, or `ROLLBACK` first and retry the whole transaction, never resume as if nothing failed. Name the error codes that are retried; every other error is not.
- **Keep the transaction short.** No network call, user wait, or model call happens while a transaction holds row locks.
