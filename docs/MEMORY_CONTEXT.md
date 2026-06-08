# Memory Context Review

OMH memory context review helps Hermes and wrappers stop reusing stale
assumptions. It is a local, deterministic review surface for OMH-managed state
and wrapper-supplied context candidates.

It does not read, scrape, or mutate opaque Hermes internal memory.

## What It Gives Users

When a user says "check what Hermes remembers about this work", a wrapper can
show a review card instead of asking the user to manually inspect files.

The card can say:

- what context OMH found locally
- which assumptions conflict with fresher setup, target, runtime-state, or
  wrapper evidence
- which items can be kept, updated, forgotten, rescoped, or dismissed
- whether a context pack is safe to attach to an executor handoff

The important boundary is that a remembered note is not proof that execution,
review, CI, or merge happened.

## Schemas

| Schema | Purpose |
| --- | --- |
| `memory_snapshot/v1` | A wrapper-supplied or OMH-local context source. |
| `memory_inspection/v1` | Source inventory, conflict detection, review items, and preview data. |
| `memory_review_card/v1` | Wrapper-renderable review UX separate from `status_card/v1`. |
| `memory_update_batch/v1` | User-approved keep/forget/update/scope/conflict decisions. |
| `handoff_context_pack/v1` | Conflict-free metadata-only context attached to executor handoffs. |

## Wrapper Flow

```sh
omh memory inspect --fixture wrapper-memory.json
omh memory pack --fixture wrapper-memory.json --executor codex --session-id "$session_id"
omh chat session prepare-handoff "$session_id" --context-pack handoff-context.json "risky refactor"
```

The fixture is optional. Without it, OMH inspects local setup profile, target
topology, runtime state, wrapper sessions, approved `.omh/memory` context, and
catalog hints.

Apply user-approved changes:

```sh
omh memory apply --batch memory-update-batch.json --dry-run
omh memory apply --batch memory-update-batch.json
```

Approved writes stay under `.omh/memory/`. Unsafe scope refs, path traversal,
and symlink escapes are rejected.

## Handoff Behavior

Executor handoffs can include `context_pack` only when
`blocked_by_conflicts` is empty.

If conflicts remain, OMH writes `context_pack_blocked` with the conflict list
instead of attaching stale context to the executor prompt. This keeps
`prepared_not_observed` handoffs from becoming accidental memory dumps or false
evidence.

## Source Priority

OMH treats sources conservatively:

1. runtime evidence from run-ledger artifacts
2. wrapper session state
3. runtime state index
4. target topology
5. setup profile
6. approved OMH memory
7. wiki or notes
8. catalog hints
9. wrapper snapshot candidates

Higher-priority sources can block stale lower-priority assumptions from being
reused in handoffs.
