# Memory Context Review

Memory context review is OMH's local, deterministic review surface for
OMH-managed state and wrapper-supplied candidates. Normal users stay in
natural-language Hermes chat. The CLI examples below are agent/operator
control-plane references, not normal-user setup.

It does not read, scrape, invoke, apply, or observe opaque Hermes internal
memory changes.

## V2 Context Model

OMH-owned records, scope items, and blocks use v2 admission and replay data:
opaque identity plus revision, canonical scope, source class, immutable review
linkage, retention, and revalidation. `pending_review`, `blocked`, `rejected`,
legacy v1, stale, expired, malformed, conflicting, superseded, or tombstoned
artifacts are review-visible but cannot influence a recall pack or handoff.

`memory_snapshot/v1`, `memory_inspection/v1`, `memory_review_card/v1`, and
`handoff_context_pack/v1` remain compact review/preparation surfaces. Their
presence is not evidence that a model, provider, or executor used context.

## Source Boundary

Hermes-native and external provider/vector context is `not_omh_reviewed`. It
may nominate one bounded OMH candidate, but it never grants OMH admission or
replay eligibility. A configured Hermes runtime may transmit rendered OMH
prefetch content in its model request; local OMH storage and computation do
not promise no egress.

## Existing Native Memory Review

`memory-sync` is English-canonical prompt guidance. Korean routing triggers
remain supported, with concise Korean help labels such as `추출` (extract),
`출처` (source), `대상` (target), `검토` (review), and `차이` (diff).

It may ask Hermes to inspect supplied claims and prepare a native `MEMORY.md`
or `USER.md` write diff. It never invokes, applies, or observes that native
write. The review states that a prepared diff is not native mutation evidence.
New facts belong in the remember/refuse/defer candidate flow instead.

## Migration and Review-Required Notice

v1 artifacts are fail-closed and display as `review_required_legacy`. Run a
report first; its deterministic counts cover records, scope items, blocks,
archive/history, candidates/reviews, indexes, declared-link journals, corrupt
or unknown artifacts, and exclusions:

```sh
# Agent/operator only.
omh memory inventory
omh memory inventory --write-ledger

# Agent/operator only: reactivate one reviewed v1 artifact, never a bulk trust grant.
omh memory reactivate <record-id> --revision <n> --apply
```

Reactivation performs a current-policy rescan, links a new immutable v2 review
record, and leaves an unsafe or failed artifact review-only.

## Batch Review and Apply

Context changes are staged before review and application:

```sh
# Agent/operator only.
omh memory batch-stage --batch memory-update-batch.json
omh memory batch-review <batch-id>
omh memory batch-apply <batch-id> --apply
```

The final step verifies the staged identities and their immutable review links
under one store lock. A direct compatibility batch reports `review_required`;
it does not make context prompt-eligible.

## Lifecycle and Dreaming

Use literal lifecycle terms: expire removes influence only; retire archives
recoverably; restore preserves the archive and creates a new pending revision;
prune hard-deletes only the manifest-declared OMH-local target set after a
report and explicit confirmation. No result extends beyond the named local
target set. Restore conflicts with newer live revisions remain review-blocked.

Dreaming remains `off` or `reminder`. It prepares reminders only, including
`stale_review_required` and `expired_volatile_records`; it never performs
consolidation, retirement, restore, or prune.

## Handoff Behavior

A handoff may contain only evaluator-eligible, conflict-free OMH context. It
records exclusions with stable reasons instead of silently reusing stale or
unreviewed material. Prepared handoff context remains preparation evidence,
not execution, model-use, provider-use, review, CI, or merge evidence.

## Role Context Packs

Every prepared coding handoff also names one `role_context_pack/v1`: the
reviewed guidance that travels with that handoff, addressed by the sha256 of
its own content. The handoff carries the pin as `role_context_pack_hash` and
the pack itself as `role_context_pack`, and a pin that does not recompute from
the pack it names is a validation error rather than a warning.

What the pack contains, and what it deliberately does not:

- One ordered record per piece of guidance already approved for the handoff —
  the `handoff_context_pack/v1` items and the `project_memory_recall_pack/v1`
  records that passed their own eligibility gates. Nothing else composes a
  pack.
- Per record: its id, a short label, the sha256 of the guidance it stands for,
  its origin surface, and the reason it was included, rendered from the reason
  code that surface already emitted. No parallel reason vocabulary exists.
- No guidance text. The pack is a manifest of what shaped the handoff; the
  summaries stay in the surface they came from, bound to the pack by the
  per-record hash.
- No owner field. Codex, Claude Code, Hermes, and generic executor profiles
  consume the identical contract, and identical guidance produces the identical
  hash for all four. Owner-specific selection happens earlier, through the
  perspective lens the recall and context builders already apply.

Record order is part of the identity. The recall builder's ordering carries
precedence, so the same records in a different order are a different pack.

Packs are immutable by construction rather than by convention. The store lives
at `.omh/memory/role-context-packs/<pack-hash>.json`, the writer derives that
path from the content, and no update, patch, or delete entry point exists.
Adjusting guidance before acceptance — dropping a record, or the guidance
changing underneath — mints the next pack and leaves the accepted one
byte-identical, so a handoff pinned to the earlier hash keeps resolving to the
guidance it was accepted with. `diff_role_context_packs` renders the
additions, removals, reorders, and stale records between two packs so the
change can be shown before it is accepted.

An empty pack is a real pack. A handoff that travels with no reviewed guidance
still names a hash, and that hash is distinguishable from carrying no pack at
all.

A pack is prepared context. It is not execution, review, CI, merge, or Hermes
internal-memory evidence.
