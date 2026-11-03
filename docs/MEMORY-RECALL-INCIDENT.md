# Memory Recall Incident

"Why was my saved response preference not used?" is a question about a chain
of events, not a request to apologize or to write memory again. This page
explains how the `memory-sync` workflow diagnoses one expected memory through
`memory_recall_incident/v1`, which stage it can prove, which stages it cannot,
and why the answer never turns into an automatic write.

Audience: agents running the incident branch, wrapper and host integrators, and
maintainers. People ask Hermes in natural language; the command here is an
agent reference, and it always prints JSON.

## Six separate claims

A report that memory "was not used" doesn't establish where the chain stopped.
Treat each step as its own claim with its own evidence. Proving one never
proves the next.

| Claim | Meaning | Where OMH looks |
| --- | --- | --- |
| Stored | The expected approved record exists in the inspected store; a pending candidate proves only candidate persistence | `.omh/memory/records`, `.omh/memory/candidates`, and correction history |
| Eligible | The stored record passes review state, lifecycle, scope, and perspective filters for this request | the record's review and lifecycle metadata, the request's scope lens |
| Selected | The canonical recall selector included the record in its prepared pack under the relevance, attention, and budget policy | `build_project_memory_recall_pack`, the prepared local recall selector |
| Rendered | The provider emitted the record's bounded summary projection into its prefetch section | a matching canonical record-bound prefetch receipt |
| Delivered | The host placed that rendered text in the model request | separate record-bound host evidence, unavailable to this builder |
| Used | The model's answer reflected it | separate use evidence, unavailable to this builder |

The incident names the last claim it could prove in `last_proven_stage`
(`none`, `candidate`, `stored`, `selected`, or `rendered`) and classifies the failure in
`stage`.

## Stages and remediation

| `stage` | Typical `reason_code` | `fault_domain` | Prepared `remediation.action` |
| --- | --- | --- | --- |
| `not_found` | `not_found` | `omh_control_plane` | `capture_for_review` |
| `pending_or_rejected` | `pending_review`, `rejected`, `blocked_review_required` | `omh_control_plane` | `review_candidate` |
| `invalid_or_superseded` | `superseded`, `payload_digest_mismatch`, `invalid_record`, `review_required_legacy`, `review_not_found`, `review_identity_mismatch` | `omh_control_plane` | `review_correction` |
| `scope_or_perspective_mismatch` | `scope_mismatch`, `perspective_mismatch` | `omh_control_plane` | `review_scope_lens` |
| `stale_expired_or_archived` | `review_due`, `stale_review_required`, `expired_standard`, `expired_volatile`, `expired_durable`, `archived_tier`, `retired`, `source_changed`, `source_unverifiable` | `omh_control_plane` | `review_freshness` |
| `relevance_attention_or_budget_exclusion` | `no_query_overlap`, `common_terms_only`, `attention_cut`, `over_budget` | `omh_control_plane` | `review_recall_selection` |
| `selected_not_rendered` | `selected_not_rendered` | `provider` | `inspect_provider_rendering` |
| `rendered_delivery_not_observed` | `rendered_delivery_not_observed` | `unresolved` | `inspect_host_delivery` |
| `delivered_model_use_unknown` | `delivered_model_use_unknown` | `unresolved` | `leave_model_use_unresolved` |
| `used` | `used` | `unresolved` | `no_change` |
| `unresolved` | `selected_live_evidence_unavailable`, `live_selection_excluded`, `served_this_session`, `store_unavailable`, `native_only_not_omh_reviewed`, `selection_unresolved`, `ambiguous_anchor`, `project_memory_disabled` | `unresolved` | `collect_record_bound_evidence` |

Every remediation is `state: prepared_not_applied` and lists what it
`requires`: `memory_curation_review/v1 approval` and `native_write_approval`.
`authorizes_mutation` is always `false`. The diagnosis reads; the normal
memory-sync interview decides.

`omh_correction_proposed` is `true` only for the six local stages. A failure in
the provider or the host stays provider or Hermes-core evidence unless a
separately useful OMH correction exists; the incident does not invent one.

## What the diagnosis can reach today

The builder runs the canonical selector for the request's query and scope,
scans OMH records, candidates, and correction history, and reads the native
memory inventory. It also reads the provider's persisted
`omh_memory_prefetch_receipt/v1` from the selected OMH home's
`memory/prefetch_receipt.json`.

Local selection alone yields `selected_live_evidence_unavailable`,
`stage: unresolved`, and `last_proven_stage: selected`. A matching receipt
can refine a locally selected record:

- Selected in the receipt but not rendered: `selected_not_rendered`, with
  `last_proven_stage: selected` and fault domain `provider`.
- Rendered with the expected summary digest: `rendered_delivery_not_observed`,
  with `last_proven_stage: rendered`. Delivery and use remain unknown.
- Named in the receipt's `selection.served_this_session`: `served_this_session`,
  still unresolved. The live turn left the record out because an earlier
  turn of the same conversation carried it, and that turn's receipt is gone.
- Absent from the receipt's selected IDs otherwise: `live_selection_excluded`,
  still unresolved. Aggregate exclusion counts don't prove a reason for that
  record.

A local lifecycle or scope exclusion remains a local verdict even when a bound
receipt carries a matching aggregate reason. The incident never reranks the
provider's result or turns an aggregate count into per-record evidence.

When a correction removes the prior current record, its scoped history can
establish `superseded`. A matching current record takes precedence over its
older history. Unreadable history is reported as unavailable, not as proof
that a claim never existed.

Receipt acceptance checks schema and body integrity, `returned_to_host`
state, an explicitly supplied matching session, store-path digest, canonical
selection configuration, and membership of the requested scope in the receipt's
allowlist. Configuration is recomputed through the selector using the receipt's
lens and query intent, the current profile policy, and the diagnosis budgets.
For a rendered anchor, its full stored-summary digest must also match.

The receipt records a query digest and clock, but diagnosis doesn't require its
query or time to equal the receipt's. This is a comparison of local inspection
with a cited provider preparation, not proof about an arbitrary later turn.
The on-disk file holds only the last persisted receipt. Use the right session
and inspect its preparation time; file recency alone isn't identity evidence.

`delivered_model_use_unknown` and `used` remain synthetic stage-model cases,
labelled `evidence_basis: synthetic`, not outcomes the incident builder can
observe. A bound receipt proves local preparation and return, not a hosted
provider call, host delivery, or model adherence.

## Evidence surfaces

`evidence_surfaces` names every surface the builder considered and one of three
statuses:

- `observed`: OMH read it. `canonical_recall_pack`, `omh_approved_records`,
  `omh_candidates`, `omh_history`.
- `unavailable`: OMH could not read it, or no record-bound observation exists.
  a missing or unreadable `live_prefetch_receipt`, `host_delivery`, `model_use`,
  `provider_availability`, and a store that was partly unreadable.
- `not_authoritative`: something was supplied, but it cannot settle the
  question. `native_inventory` is native material outside OMH review;
  `provider_recall_status` appears when the caller passes
  `--provider-served-count`, which is an aggregate ("recalled 2 memories") and
  never says which record was served.

For `live_prefetch_receipt`, a bound receipt is `observed` with basis
`canonical_1452_receipt_bound`. No file gives `no_receipt_persisted`;
unreadable, oversized, invalid UTF-8, invalid JSON, or decoder-recursion failures
give `receipt_unreadable`. If decoding succeeds, a structurally incompatible receipt is
`not_authoritative` with `incompatible_receipt:<field>`. Identity refusals
include `receipt_session_unbound`, `receipt_session_mismatch`,
`receipt_store_mismatch`, `receipt_configuration_mismatch`,
`receipt_scope_mismatch`, and `receipt_record_digest_mismatch`.

The rule that matters: an absent receipt is `unavailable`, not evidence of
non-delivery. `delivery_observed` and `model_use_observed` are `null` in every
incident this tree can produce, and the text of an incident should say
"delivery was not observed", never "the memory was not delivered".

## Privacy and scope

The persisted artifact carries identifiers and digests only. The anchor is a
record id, candidate id, or SHA-256 of the claim; the query, the session id,
the OMH home path, the recall policy, and the selection inputs appear as
digests under `configuration_identity`. No summary text, query text, prompt,
transcript, provider payload, or credential is written, and records from other
profiles or projects are neither listed nor counted. `redaction_policy` is
`metadata_only` on every incident.

The incident cites validated `receipt_id` and `receipt_configuration_id`
without copying the receipt's selected/rendered lists or unrelated IDs. The
receipt itself retains session and scope labels, unlike the incident's hashed
configuration identifiers. Both are sensitive correlation metadata.

Ordinary SHA-256 detects inconsistent body edits; it doesn't authenticate the
sender. A local writer can replace a receipt and recompute its digest.
`receipt_id` excludes the mutable `state` and `served_at` fields. Those fields
are lifecycle metadata, not authenticated return evidence. Store access remains
the trust boundary. See [Memory Prefetch](MEMORY-PREFETCH.md) for the producer
contract and its limits.

A digest anchor is matched only inside the requested scope, so a claim stored
under another project cannot be revealed by guessing its hash. An explicit
record id may still explain a scope or perspective mismatch, because you
already hold the id.

## Command

```sh
omh memory recall-incident --record-id <mem_or_cand_id> [--query <text>] [--session-id <id>]
omh memory recall-incident --claim-digest <sha256-of-exact-claim> [--query <text>] [--session-id <id>]
```

Exactly one anchor is required. Optional flags:
`--scope-kind channel|project|run|target|thread|user|user-global`,
`--scope-ref`, `--observer`, `--observed`, `--limit`, `--max-chars`,
`--provider-served-count`, and `--write`, which saves the incident under
`.omh/memory/incidents/<incident_id>.json`. Without `--write` nothing is
persisted. The command prints JSON only; there is no text mode and no receipt
flag.

Store selection and record scope are separate. `--scope user` or
`--scope project` before `memory` selects a store; `--scope-kind` and
`--scope-ref` identify a record lens. Capture and diagnosis default to
`project/default`, not the current repository name. For a repository-specific
record, pass its actual scope ref. To inspect a user-global preference, use
`--scope-kind user-global --scope-ref default`.

The provider writes its receipt in its user home, even when it also reads
project records. Diagnosis reads records and receipts from the one selected
home; it doesn't merge the provider's two stores or accept a separate receipt
path. A project-home diagnosis normally has no provider receipt. Don't copy
receipts between homes to bypass this boundary.

## Worked example

Produced against a temporary OMH home: one candidate captured with
`omh memory capture`, then diagnosed by its claim digest with a caller-supplied
aggregate count.

```sh
omh memory recall-incident --claim-digest 129e9e6fabeba13b3dbae876326b1971a8703596e65d2ad2df82485f8839ece4 --query "answer style" --session-id session-a --provider-served-count 2
```

```json
{
  "schema_version": "memory_recall_incident/v1",
  "incident_id": "incident_5ce9c07a605b74f081a8b4d1",
  "stage": "pending_or_rejected",
  "reason_code": "pending_review",
  "evidence_basis": "local_inspection",
  "fault_domain": "omh_control_plane",
  "omh_correction_proposed": true,
  "remediation": {
    "action": "review_candidate",
    "state": "prepared_not_applied",
    "requires": ["memory_curation_review/v1 approval", "native_write_approval"]
  },
  "authorizes_mutation": false,
  "anchor": {
    "candidate_id": "cand_470d50f348384559",
    "requested_digest": "129e9e6fabeba13b3dbae876326b1971a8703596e65d2ad2df82485f8839ece4"
  },
  "configuration_identity": {
    "home_digest": "9c2adf9f68c2d18f73dbeb2bf0d92d1ef1613bd7bef64f092cfa3d9942330569",
    "session_digest": "fa57a52dbf08190218529730a3e99db6946c6c29220fb6e0551e21598b0b05db",
    "policy_digest": "7d8485ee4f0cb76a029dcb5aa8a7f30fc2e6dd795bfd793c048675d07194460b",
    "selection_digest": "264a9a1cdfc11926fb17a01747474eed989179468904e00bed7a7e38beafef49"
  },
  "evidence_surfaces": {
    "canonical_recall_pack": {"status": "observed", "basis": "prepared_local_selection"},
    "omh_approved_records": {"status": "observed", "basis": "local_store"},
    "omh_candidates": {"status": "observed", "basis": "local_store"},
    "omh_history": {"status": "observed", "basis": "local_store"},
    "native_inventory": {"status": "not_authoritative", "basis": "native_inventory_not_omh_reviewed"},
    "provider_recall_status": {"status": "not_authoritative", "basis": "caller_supplied_aggregate_count"},
    "live_prefetch_receipt": {"status": "unavailable", "basis": "no_receipt_persisted"},
    "host_delivery": {"status": "unavailable", "basis": "no_record_bound_observation"},
    "model_use": {"status": "unavailable", "basis": "no_record_bound_observation"},
    "provider_availability": {"status": "unavailable", "basis": "runtime_not_inspected"}
  },
  "last_proven_stage": "candidate",
  "delivery_observed": null,
  "model_use_observed": null,
  "external_review_status": "not_omh_reviewed",
  "redaction_policy": "metadata_only",
  "claim_boundary": "Local diagnosis and prepared remediation only; not live rendering, delivery, model use, dispatch, execution, review, CI, merge, or native-write evidence."
}
```

Read it as: the claim exists as a candidate that was never approved, so this
candidate was not eligible for OMH recall. That does not establish whether
another memory path rendered or delivered the same claim. The prepared
remediation is to review the candidate in the memory-sync interview. The
provider count of 2 changed nothing, because it does not name records.

In Hermes, the same result should sound like: "That preference is still a
pending candidate, so it was never eligible for recall. I can walk you through
reviewing it now; nothing is written until you approve."

## How the complaint reaches this branch

Natural-language recall complaints ("why was my saved preference not used",
"memory was not used") route to `memory-sync`, not to a generic apology, an
automatic write, or an agent-debug workflow. Quoted phrases in a translation
request and a plain apology request stay where they were; the routing corpus
carries both the positive cases and those controls.

## Boundaries

- No model call, provider search, network egress, background agent, or
  automatic write. Diagnosis is read-only.
- Hosted provider behavior, host delivery, and model adherence may remain
  unknown; the artifact says so instead of naming a cause.
- Record ids and digests are correlation metadata scoped to the active profile
  and project.
- Canonical prefetch receipts can establish record rendering and local return.
  They cannot establish host delivery or model use. Neither a recall count nor
  a model's explanation closes those gaps.

Related: [Project Memory](MEMORY.md), [Memory Context Review](MEMORY_CONTEXT.md),
[Memory Sync Fidelity](MEMORY-SYNC-FIDELITY.md).
