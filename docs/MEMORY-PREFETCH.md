# Canonical Memory Prefetch

People ask Hermes to remember a preference or explain why it wasn't followed.
They don't need to run a recall command. This page is the agent, wrapper, and
operator reference for the OMH memory provider and its local evidence.

## One selector, different callers

With `memory.provider: omh`, `OmhMemoryProvider.render_pack` calls
`prepare_prefetch_records`, which delegates selection to
`select_memory_recall`. Handoff preparation reaches that same selector through
`build_project_memory_recall_pack`. The installed plugin uses only its bundled
modules and the standard library, not the control-plane package or a second
ranker.

The shared contract applies acting principal and reviewed audience before
scope, perspective, immutable review linkage, supersession, lifecycle, source
freshness, and archive eligibility. Unauthorized records contribute only
aggregate reason counts; their IDs and summaries never reach ranking, pins,
rendering, or receipts. Eligible
records compete in this order: privileged pins, attention tier, relevance,
decayed rank-fusion score, then record ID. Recency, saturating handoff-usage
buckets, age, admission weight, and temporal query intent feed that score.
Pins bypass no-query-overlap exclusion, not review or scope checks. Once a
record or summary-character budget is crossed, the remaining ranked suffix is
excluded as `over_budget`.

Shared selection doesn't mean every caller returns identical results. Inputs
must agree: stores, reviews, operations, policy, usage, pins, clock, scope,
perspective, query intent, and budgets. The provider uses the Hermes perspective
and a six-record limit; handoff recall defaults to five records and the selected
executor's perspective. The provider currently uses selector-default policy,
not the control plane's stored setup-profile memory policy.

## Scope is not a store path

The provider reads the nearest repository's `.omh` record store first, then
its user home. A duplicate record ID uses the project copy. Reviews and usage
also prefer the first home; pins are combined. Scope labels decide eligibility
independently of which store held the record.

The normal prefetch and handoff allowlist contains:

| Record label | Meaning |
| --- | --- |
| `user-global/default` | Explicitly reviewed cross-project context within the stores the caller reads |
| `project/<identity>` | Context for the current project label |
| `thread/<session-id>` | Context for the current session, included only when a session ID is available |

Project memory uses `project_identity/v2`, not a checkout basename. The
filesystem-only resolver prefers a valid `.omh/project-identity.json` explicit
`prj:<64 hex>` identity. Otherwise it reads Git metadata (including linked
worktree `commondir`) and hashes the normalized remote URL into
`repo:<32 hex>`. Origin wins; conflicting remotes without origin fail closed.
Git value quotes, escapes and inline comments are decoded before credentials
and transport schemes are removed. Local filesystem remotes are resolved
strictly against the checkout containing the common Git metadata directory;
the canonical endpoint URI is domain-separated and hashed, never emitted.
Missing or unsupported local endpoints fail closed. Relative, absolute and
file-URI spellings of one endpoint agree, while separate sibling upstreams
remain distinct. Local endpoint relocation changes that evidence; use an
explicit identity when endpoint-location independence is needed.
Checkout renames retain identity while their remote endpoint remains the same,
worktrees share their common remote, and distinct forks do not share memory
merely because their directories have the same name.

CLI identity, capture, automatic recall and incident diagnosis use the active
checkout, not the selected store's parent. Selecting another checkout's store
does not authorize its project records. Incident workflow callers may supply
`invocation_cwd`; otherwise the current working directory is the active context.
That transient filesystem context is not persisted in incident metadata.

Invalid explicit evidence, absent or ambiguous remotes, unreadable metadata,
and an unbound checkout produce closed diagnostics, never a basename fallback.
Resolution makes no subprocess, network, or model call and writes nothing.
This is repository scoping, not authenticated repository or user identity.
The handoff facade still reads its supplied store only; a global label does
not make it discover other stores.

### Compatibility and operator migration

Automatic recall of basename-scoped records stops until reviewed migration.
`legacy_basename` is an inspection/migration compatibility state, never a
second project ref in an automatic result. Local-only repositories need an
explicit identity initialized by the agent/operator maintenance command
`omh memory project-identity init`. Capture without a resolved project identity
refuses with that guidance; it never silently becomes user-global.

Agent/operator maintenance path:

1. `omh memory project-identity show` inspects resolution without writing.
2. `omh memory project-identity report` scans project and user stores and
   reports proposed scope changes without altering records.
3. After review, `omh memory project-identity migrate --approve <report_digest>`
   binds approval to that exact inventory and creates reviewed successor
   revisions through the existing lifecycle journal. Original revisions and
   reviews are preserved, not rewritten in place. Repeating the same completed
   migration is a no-op. Report entries retain exact source revision, source
   digest and immutable review bindings. A source or review changed between
   reporting and locked apply is skipped with `source_changed_since_report`,
   included in the receipt's `skipped` list, and requires a fresh report and
   approval. Apply never substitutes the newly read revision's digest.
4. `omh memory project-identity migrate --rollback <receipt_id>` retires those
   successors and restores original eligibility for explicit legacy inspection.
   It does not re-enable basename-based automatic recall.

Prefetch receipts are `omh_memory_prefetch_receipt/v3`. Configuration
identity includes both resolver version and project identity. Older v2 receipts
remain structurally readable, but cannot establish current repository-bound
recall evidence; identity/version mismatches are rejected.

Delivery requires an explicit nonempty allowlist, with a valid project entry
whenever a project identity resolved. A missing required kind, invalid scope,
or blank ref yields `scope_status: unresolved`, an empty disabled record pack,
and `scope_unresolved`. It never falls back to all records. With no project
identity (outside any repository, or a repository whose identity does not
resolve), an operator console's allowlist is user-global plus the current
thread and requires no project entry (owner decision 2026-10-13): no project
record is admitted there, and a capture made outside a repository, which
defaults to user scope, is recalled where it was stated. A shared surface
gets an empty allowlist there, as before, unless it names a principal (a
person's messenger DM, or a wrapper's principal context) or a messenger
channel: those labels admit only records bound to that principal or scoped to
that channel, so they need no repository. A `channel` scope admits its
identity-unbound records on a shared surface only when the allowlist names
that exact channel (see
[Messenger conversations](MEMORY.md#messenger-conversations)). This is a
record-selection boundary;
separately governed blocks and a consolidation reminder aren't selected by
this record allowlist, and reach an operator console only (see
[Surface classes](MEMORY.md#surface-classes)).

Scope and perspective mismatches disclose only aggregate exclusion counts,
not foreign IDs or summaries. Records without a perspective pass each actor
lens. The live provider selects `observed: hermes`; handoffs select their
executor, including Codex, Claude Code, Hermes, and generic targets. An
unresolved executor doesn't inherit another actor's perspective.

Agent/operator `omh memory recall` without scope flags uses the current stable
project allowlist; the coding handoff's recall pack uses the project its store
belongs to. With no project resolved, operator recall follows the live turn's
console rule (user-global and the thread, no project entry required). A
handoff follows the rule of the surface it came from: a wrapper's chat-sourced
handoff (every `CHAT_SOURCES` name) or one whose caller states no surface
carries what the chat's own Hermes session may see by its published lens --
the session the caller names: the `omh_interact` tool's own `session_id` in
process, and `HERMES_SESSION_ID` only in a command Hermes started (`omh coding
delegate`, `omh coding lifecycle start`, `omh chat interact`, `omh chat session
start` and `prepare-handoff`). The owner's messenger DM reads like
a console, another person's DM reads only that person's records, a group only
its channel's, and
anything else is shared (`shared_surface=True`), admitting no
identity-unbound record, because the pack can travel back to that chat. `omh
coding delegate` typed at a terminal (both stdin and stdout TTYs) is an
operator console, unless `HERMES_SESSION_PLATFORM` names a non-console
platform: Hermes sets it in every child of a gateway session. `omh memory recall-incident` recomputes a receipt's configuration under
the same rule, so a console receipt made outside a repository is
authoritative. Explicit scope flags remain available for legacy inspection
within the selected store. Supplying only half a scope fails closed.
`--include-stale` is inspection-only and carries ineligible replay evidence;
it can't turn stale records into approved handoff context. Inspection isn't
what the live provider delivers.

## Store rollout

The store layout stays compatible while newly principal-bound records use
`project_memory_record/v3`, `omh_memory_scope/v3`, and
`project_memory_review_record/v3`. Existing v2 `project`, `target`, `thread`, and
`run` labels remain readable on explicitly nonshared surfaces. `user-global`
remains a legacy profile-local scope, not a human identity; it is excluded on a
shared surface. Upgrade and recall never silently rewrite or assign old records.
Use the report-first principal migration described in [Project Memory](MEMORY.md).

A record in the user home is not automatically global. In particular, old
`project/default` records do not match a resolved stable repository identity.
They stay stored and explicitly inspectable until reviewed migration. `target`
and `run` records likewise are not implicitly added to the normal allowlist.

For a rollout, inspect the existing store and intended audience first. Keep
correct project/thread labels. If an old fact really belongs across projects,
stage an explicitly scoped candidate and complete normal review and approval;
don't relabel JSON in place or bulk-promote old records. Select the user store
when the preference should be available to prefetch across repositories.
Legacy v1 records remain `review_required_legacy` in inspection and require
explicit reviewed reactivation before replay.

Agent/operator examples, not a user quick start:

```sh
# Stage a cross-project preference in the user store. Approval is separate.
omh --scope user memory capture "Prefer concise responses" \
  --scope-kind user-global --scope-ref default

# Inspect just that lens in the user store.
omh --scope user memory recall "responses" \
  --scope-kind user-global --scope-ref default

# Stage a project fact from inside the release-tools repository.
omh --scope project memory capture "Release checks include the CLI suite" \
  --scope-kind project --scope-ref release-tools
```

`--scope` selects storage; `--scope-kind` and `--scope-ref` label the record.
The capture, recall, and recall-incident CLI paths accept `user-global`; this
isn't a claim that every other memory subcommand supports that label.

## Selection, rendering, and served status

The provider initializes with an empty query. `queue_prefetch` rerenders for
the next turn using the queued query, which the host supplies after a completed
turn. `prefetch` returns the already prepared pack; its query argument doesn't
rerank that pack on the hot path.

The pack contains system-tier blocks, a reference-block label index, the record
section, and any current consolidation reminder, all within a 9,000-character
whole-pack budget under Hermes' 10,000-character prefetch spill cap (see
[The pack budget](MEMORY.md#the-pack-budget)). Record rendering preserves a
prefix of the canonical selection. Its separate 2,400-character section budget
includes XML tags, escaping, separators, and aggregate omission reports. Each
summary projection is capped at 500 characters. A record that doesn't fit
ends the prefix; a smaller later record can't jump ahead. Record IDs and types
aren't shortened to fit. A budget too small for the omission report returns
no section.

When the selection carries `query_fallback` (the message matched no stored
record; see [Recall Ranking and Delivery Usage](MEMORY.md#recall-ranking-and-delivery-usage)),
the provider withholds the readmitted records: no summary, no name, no line,
and no section at all when nothing else is shown. Records captured in this
conversation (by `source_ref`, for this session or its compaction ancestors)
still render in full. The model reads a withheld record with `omh_remember`
recall. CLI recall, `omh_memory` recall and coding handoffs don't withhold.

Selection cuts are `over_budget`; selected records lost to section rendering
are `render_budget_exhausted`. These are different events. The receipt names
selected IDs and rendered IDs separately, including selected-but-not-rendered
records, and lists withheld records as `rendering.indexed_records`. Its
content digest covers the full stored summary, not the potentially shorter
escaped projection.

`recall_status()` reports the last pack actually returned by `prefetch`, not a
queued replacement. Its count is rendered full blocks plus rendered record
elements, never selected records or consolidation reminders. A reference-only
index is memory content without a discrete count. Initialization and shutdown
clear in-memory served status and receipts. A newly served empty pack replaces
the old state. The status line alone doesn't name records or prove host delivery
or model use. It reports nothing on a platform the profile's `recall_line`
excludes (by default every one but `cli`, `tui` and `desktop`), while the pack
and its receipt stay the same; see
[Turning the recall line or recall off](MEMORY.md#turning-the-recall-line-or-recall-off).

## Receipt privacy and identity

`build_prefetch_receipt` creates `omh_memory_prefetch_receipt/v3` in `prepared`
state. It binds resolver version and project identity, with resolution state
and closed diagnostics in the lens, alongside opaque principal binding state,
actor kind, shared-surface flag, aggregate allow/deny reasons, and audience-policy
digest. Existing v1/v2 receipts remain readable; they cannot establish the new
repository-identity binding, and v1 establishes no principal-isolation claim. `prefetch`
marks the current receipt `returned_to_host`, exposes it through
`latest_prefetch_receipt()`, and attempts to persist it at
`<provider-user-home>/memory/prefetch_receipt.json`. A write `OSError` doesn't
fail the turn or produce a separate failure receipt, so disk may still hold an
older receipt. The file holds the last persisted receipt, not a per-turn
history, and survives shutdown for session-bound diagnosis.

The producer emits record IDs, summary digests, selected/rendered counts,
exclusion counts, truncation, scope and perspective lenses, query digest and
intent, session ID, clock, store-path digests, selector configuration identity,
and render-budget identity. It includes no summaries, raw query, prompts,
transcripts, block values, rendered text, or consolidation text. IDs, digests,
and session/scope labels still allow correlation, so protect the receipt like
other local memory metadata. Redaction isn't anonymity.

The reader caps input at 64 KiB, contains decoder-recursion failures, and rejects
malformed, oversized, foreign-schema, internally inconsistent, or digest-mismatched receipts.
Validation checks that rendered IDs form a prefix of the selected IDs with
indexed IDs removed, that no indexed ID is reported as selected-but-not-rendered,
and that
`delivery_observed` and `model_use_observed` remain `null`.

`receipt_id` is an ordinary SHA-256 over the preparation body, excluding
`receipt_id`, `state`, and `served_at`. It detects inconsistent edits; it isn't
a signature or sender authentication. An authorized local writer can replace
the body and recompute the digest. Lifecycle state and served time aren't
covered by that digest. Configuration and store digests bind local inputs,
not an authenticated provider, user, or host.

A receipt supports a claim about local provider preparation and return. It
cannot prove that Hermes put the section in a model request or that the model
followed it. Missing evidence is unknown, never proof of nondelivery. The
[recall incident workflow](MEMORY-RECALL-INCIDENT.md) checks the receipt's
session, store, configuration, scope, and rendered anchor digest before using
it, without copying unrelated record metadata into the incident.

Local preparation makes no model or network call. A configured Hermes host
may later send rendered content to its model provider; receipt privacy isn't
a no-egress promise for that content. Host execution, billing, delivery, and
model use need their own observations.

Related: [Project Memory](MEMORY.md), especially the retained retrieval suite
and its canonical-versus-provider parity checks.
