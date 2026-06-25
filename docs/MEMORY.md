# Project Memory

OMH project memory is a local, reviewed long-term context layer for a single
project. It stores typed summaries under `.omh/memory/` and can attach compact
recall packs to coding handoffs.

It is not Hermes global memory. OMH does not read, patch, or mutate opaque
Hermes internal memory.

## What It Stores

Project memory uses deterministic JSON files:

- `.omh/memory/candidates/*.json` for captured candidates awaiting review.
- `.omh/memory/records/*.json` for approved reviewed records.
- `.omh/memory/reviews/*.json` for approve/reject decisions.
- `.omh/memory/index.json` for local file inventory.

Generated `.omh/` files are local-only and ignored by default.

Approved records can be typed as:

- `fact`
- `decision`
- `lesson`
- `procedure`
- `episode`

Records include TTL and staleness metadata. `episode` records default to a
short TTL. Other records default to staleness review metadata so recall can
skip stale context unless an operator explicitly includes it.

## Policy

`omh setup` records a `project_memory_policy/v1` object in
`.omh/setup-profile.json`.

Modes:

- `review-first`: default. Capture candidates, require review before recall.
- `auto-safe`: auto-approve candidates that pass local safety checks; keep
  risky items in review.
- `off`: disable automatic capture and recall.

Example:

```sh
omh setup --memory-mode review-first
omh setup --memory-mode auto-safe
omh setup --memory-mode off
```

Setup only records OMH-local policy. It does not mutate Hermes memory.

## CLI Flow

Capture a candidate:

```sh
omh memory capture --type procedure --tag tests "Run unittest discovery after workflow contract changes"
```

Review pending candidates:

```sh
omh memory review
```

Approve or reject:

```sh
omh memory approve cand_1234 --approved-by user
omh memory reject cand_1234 --reason "temporary task progress"
```

Recall reviewed memory for a task:

```sh
omh memory recall --executor codex "workflow docs verification"
```

Status:

```sh
omh memory status
```

Every review and recall payload says it is prepared memory context only. It is
not execution, review, CI, merge, or Hermes internal-memory evidence.

## Safety Rules

Capture never persists raw `--content` or stdin text. It stores hashes, lengths,
typed summaries, and review metadata.

The local safety classifier blocks or requires review for:

- credential-like text
- raw logs and tracebacks
- full transcripts
- short-lived PR or commit identifiers
- temporary task progress
- unusually long raw content

Blocked candidates cannot be approved directly. Recapture them as a safe,
bounded summary or reject them.

## Handoff Behavior

When memory recall is enabled and reviewed records match a coding task, OMH
adds `memory_recall_pack/v1` to prepared coding handoffs. This applies to:

- `omh coding delegate`
- `omh coding lifecycle start`
- `omh chat interact --mode delegate`
- wrapper-session handoff preparation

Persisted lifecycle records keep only a compact recall summary. They do not
persist raw recalled summaries in status cards.

Recall packs are prepared context. They can help the selected coding owner —
Codex, Claude Code, Hermes runtime/handoff paths, or a generic executor — start
with known project facts, decisions, lessons, or procedures, but they do not
prove that any executor ran or that review/CI/merge happened.

## Future Backends

The v1 policy names `local_json` as the current backend and leaves an extension
seam for optional backends. Mem0, Graphiti, Cognee, Letta, or another memory
system could be added later as optional adapters only if dependency, privacy,
and packaging boundaries are explicit.
