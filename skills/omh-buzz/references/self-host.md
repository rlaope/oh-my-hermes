# Self-hosted Buzz Relay

Use this lane to inspect or guide a Buzz relay deployed with the official
Compose topology (the Compose file in the relay's own repository; if it cannot
be opened, mark the topology `not_observed` and ask for the file). Guide, don't drive: present state-changing commands and let
the user approve and run them unless execution was explicitly requested.

## Read-only Failure Tree

Inspect the stack in this order:

1. Compose resolution and exact image/component versions.
2. Relay process state and logs.
3. Postgres connectivity and migration state.
4. Redis connectivity.
5. MinIO/S3 reachability, bucket policy, and upload path.
6. Persistent disk availability and ownership.
7. Relay readiness endpoint.
8. External client and Hermes connectivity.

A green relay readiness response does not prove MinIO, upload, or disk health.
Name those blind spots instead of collapsing the stack into one boolean.

## Safety Gates

- Treat non-loopback database, cache, object-store admin, or management binds
  as a blocking exposure unless an accepted network policy proves otherwise.
- Resolve Compose overlays before judging the effective bind or environment.
- Never print secret values or copy an entire dotenv into a diagnostic child.
- Do not recommend plaintext backups for private keys or owner-attestation
  material.
- Record exact component versions before migrations, upgrades, or restores.

## Mutating Operations

For start, stop, upgrade, membership change, backup, or restore:

1. Name the exact target and expected state transition.
2. Capture the version and persistence layout.
3. Require the user's approval.
4. Name rollback and data-loss boundaries.
5. Run one bounded operation.
6. Re-observe every affected layer; do not infer recovery from command exit.

Target-deployment auth, route, media, backup, and restore remain unverified
until executed against that deployment. Static Compose inspection is not E2E
evidence.
