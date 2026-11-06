# Recovering From One Wrong Memory Source

When a source turns out to be poisoned, wrong, or no longer trusted, recovery is not a record-by-record review. It starts with the one question the per-record commands cannot answer -- which records came from it -- and it closes on a recall report over this store, not on an exit code.

## Sequence

1. **Enumerate.** `omh memory sources` lists every source label in the store with its record count and the axes it appears on; `omh memory sources --source <label>` returns that source's records. It is a read: it quarantines, retires, and deletes nothing.
2. **Widen.** `omh memory lineage <record-id>` for each returned record. A record derived from a poisoned one carries the claim forward, and this selector does not follow provenance on its own.
3. **Quarantine.** `omh memory attention <record-id> --tier archive` previews, then add `--apply`: the record leaves default recall and stays stored (reversible; `omh memory recall --include-archived` still finds it). `omh memory retire <record-id> --apply` moves only expired or open records and reports `skipped: not_expired` for a live one with exit 0, so read its `moved` list, never its exit code. To archive the revision itself, recall the record in the session and call `omh_memory` with `action="retire"` and `reason: no_longer_true`.
4. **Delete only then.** `omh memory prune <record-id> --revision <n> --apply --confirm-hard-delete-local` hard-deletes the manifest-declared OMH-local target set, but accepts only an expired approved volatile record (`prune_requires_expired_approved_volatile` otherwise). For a live record there is no hard-delete path here: say so and leave it archived. Irreversible; an explicit second step, never folded into the quarantine.
5. **Prove it.** `omh memory recall "<the claim those records answered>"` over this store, or `omh memory recall-incident --record-id <id>` for one record's stored/eligible/selected stages. A recall report showing the records absent is the completion evidence. The retire command's exit code is not: a sweep that archived nothing also exits 0. Neither is `omh memory recall-suite`, which seeds its own fixture corpus in a temporary store -- it proves the recall engine did not regress while you worked, never that this store's records left recall.

## What the selector matches

Two axes carry a record's origin and one record can carry both: `source`, the admission channel recorded at capture, and `source_ref`, the document, ticket, or URL the memory was taken from. A record is listed under every label it carries, so a record admitted from two sources appears under both, and one whose two axes name the same value reports both axes rather than the first.

`source_class` is not an axis. It is a four-value governance classification and every directly captured record is `omh_local`, so indexing it would produce one label matching most of the store and say nothing about where a record came from.

## What it cannot tell you

A record that recorded no source at all is listed under `indeterminate`, never quietly excluded. This selector cannot call it clean and neither can this report; those records stay yours to judge. An unreadable record file is the same answer for a different reason and is listed beside them.

## Reading an empty result

`selected.outcome` separates the three ways to match nothing, because they are three different answers:

- `empty_store` -- nothing readable in the store.
- `source_never_recorded` -- records exist and none of them recorded a source. The selector can exclude nothing here; the whole store is indeterminate.
- `no_records_for_source` -- sources are recorded and this one is not among them. This is the only outcome that means the source contributed nothing.

## Boundaries

The report is `memory_source_index/v1`: OMH-local prepared context, never execution, review, CI, merge, or Hermes internal-memory evidence. Retire archives and prune deletes only the OMH-local target set each one names; neither proves anything about Hermes' own memory files or an external provider's store.
