# Backend Contract Tests

Load this when a backend handoff asks for tests. The contract tables say what the surface promises; this page ties each promise to the test that proves it, so the test plan in `backend_implementation_handoff/v1` is derived from the rows rather than improvised after the code exists.

The shapes every test must have -- the seam named first, the questions before a new test, tests that guard nothing, tests coupled to internals, and fakes only at system boundaries -- live in one shared page: load `skill_view(name='omh-verification-gate', file_path='references/test-authoring.md')`. This page does not repeat them.

OMH writes no test and runs none. The plan is prepared; only an executor's observed run is evidence.

## 1. One test per contract row

| Contract row | The test | Seam |
| --- | --- | --- |
| each `auth_boundary_map/v1` row | a negative test: the caller that lacks the identity or the permission is refused with the status the row names | the HTTP or job interface |
| the object-level authorization row | always written as "caller A requests B's id", asserting the not-found or not-permitted status the error table chose | the HTTP interface |
| each `error_path_table/v1` row | status, machine code, and envelope shape asserted together, plus the retry hint on a retryable row | the HTTP interface |
| an idempotency key | the same request sent twice with one key produces one effect, read back through the interface | the HTTP interface |

A status-only assertion lets the envelope drift unseen, and a happy-path test alone proves none of the rows above. A row with no test is listed in the plan as untested with the reason, not left out.

## 2. Logic through its module interface

Logic behind a handler is tested through the interface of the module that owns it, not through private helpers and not only through HTTP. Handler tests then cover parsing, the auth check, and the mapping of results and errors to the envelope.

## 3. Stand-ins by dependency category

| Dependency | Stand-in in the test |
| --- | --- |
| Code in this service | none: it runs real |
| The database | a local instance of the same engine, at the version production runs where behaviour differs; never a different engine whose locking, types, and constraints differ |
| A service the same team owns | an in-memory adapter that implements the client interface the handler already calls |
| A third-party API (payments, email, identity) | a fake at the client seam that records what was sent; no test reaches the real vendor |
| Clock, randomness, generated ids | injected and pinned |

A repository class replaced by a mock, or an assertion that `save` was called, is a test coupled to internals: the shared page says how to rewrite it.

## 4. Writes are read back through the interface

Check a write by reading it back the way a caller would -- the read endpoint, or the module's read function -- not by querying the table. A table read passes while the read path is broken and fails when the storage layout changes without any behaviour change.

## 5. Migrations run on populated data

A migration test applies the migration to a database that already holds rows in the previous shape, including the null, empty, and boundary values the old shape allowed, never only to an empty schema. It asserts that the migration completes, that backfilled values are right, that code still running against the previous shape keeps working during the expand step, and that each step's rollback point (`references/schema-migration.md`) restores a readable state.

## 6. What the plan records

Per test: the contract row it proves, the seam, the stand-ins, and the command the executor runs. A planned test is `prepared_not_observed`; passing tests, applied migrations, and integration runs are recorded only from observed executor output.

## Attribution

One test per contract row, reading writes back through the interface, and stand-ins chosen by dependency category adapt ideas from Matt Pocock's `tdd` and `codebase-design` skills at `mattpocock/skills@d1478fcb140db0b93c0c8df17bcfd311844749d0`, MIT License, Copyright 2026 Matt Pocock. No upstream text is reproduced; the contract-row mapping and the `prepared_not_observed` boundary are OMH's own.
