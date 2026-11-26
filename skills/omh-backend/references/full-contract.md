# Backend

Load this on-demand contract after the compact `backend` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The work is the database itself -- a slow query and the index that fixes it, DDL that locks a live table, N+1 queries, or when to partition or shard; use `omh-relational-db`, which owns the lock behaviour and rollback of each statement.
- The request is about web UI, layout, or a design system; use `omh-frontend`.
- The request is a security posture or threat review rather than a service design; use `omh-security-safety-review`.
- The request is to run or judge the verification of an already-built service; use `omh-verification-gate`.
- The request is a Rust-language change whose risk is compiler, ownership, or `unsafe` discipline; use `omh-rust`.
- The work is a batch or streaming job's rerun, backfill, duplicate rows, or a warehouse table's downstream readers; use `omh-data-pipelines`.

## Examples

Good example:

- Prompt: Design a REST API with a Postgres schema and migrations for the billing service.
- Expected behavior: Prepare backend_service_contract/v1, auth_boundary_map/v1, error_path_table/v1, response_shape_contract/v1, and schema_migration_plan/v1, then hand off with the per-stack reference named.
- Why: The request is server-side design across an endpoint surface and its storage, before any code exists.

Bad example:

- Prompt: The migration is written, so mark the schema as migrated and the API as live.
- Expected behavior: Mark migration application, integration runs, and deployment as not_observed and name the smallest observed proof for each.
- Why: A prepared migration plan is not an applied migration, and a contract is not a running service.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the service, endpoint, or data surface being changed
- callers and their trust level (public, partner, internal, machine)
- language, framework, and datastore when known
- authentication and authorization model in force
- existing schema and migration tooling
- backward-compatibility and rollout constraints
- observed integration or load evidence for completion claims

Expected outputs:

- backend_service_contract/v1
- auth_boundary_map/v1
- error_path_table/v1
- response_shape_contract/v1
- schema_migration_plan/v1 when the change touches storage
- consumer_impact_and_sunset/v1 when an existing contract changes
- backend_implementation_handoff/v1
- observed_integration_evidence/v1 when observed

Artifact expectations:

- backend_service_contract/v1 names each endpoint or job, its caller class, request and response shapes, its idempotency and pagination rules, and its expected rate, latency target, and payload bound (or `unknown`)
- auth_boundary_map/v1 states where an untrusted caller becomes a trusted one, and which check runs on each path
- error_path_table/v1 pairs every failure mode with its status/code, body shape, retryability, and log/redaction rule
- response_shape_contract/v1 keeps success and error envelopes consistent across the surface instead of per-endpoint improvisation
- schema_migration_plan/v1 orders expand, backfill, switch, and contract steps with the rollback point for each
- consumer_impact_and_sunset/v1 lists each identified consumer with what breaks for it, then the compatibility window, the migration path, and the sunset date; a consumer set that could not be enumerated is reported as `consumers_not_enumerable` with the reason, never as zero breakage
- integration runs, applied migrations, load numbers, and deployment only when observed
