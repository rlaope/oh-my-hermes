# Stateful Contracts: Records, Limits, Memory

Load this reference only when the build handoff has one of these properties. An extraction, classification, summarization, or retrieval feature that never presents a record, never changes shared state, and never remembers a person stays under `references/build-rails.md` alone and does not carry these requirements.

- The feature **presents or acts on business records**: load the section on record authority and presentation receipts.
- The feature **enforces a cumulative business limit**: load the section on shared resulting-state limits.
- The feature **stores facts about a person**: load the section on user-memory lifecycle.

Everything here is a prepared handoff contract. OMH implements no record store, transaction, presentation channel, or memory backend, and observes none. Every guarantee below is enforced by the owning backend, the host that mediates the model, or the client that renders the view. Prompt text cannot supply any of them; the prompt can only be written so that a model which follows it never needs a guarantee the host does not enforce.

## 1. Record Authority And Presentation Receipts

### Provenance is not authorization

A record ID that looks valid is a lookup candidate. It is not evidence that the record exists, that this user may see it, or that this operation may touch it. The ID may have come from model output, from the user's text, from a retrieved document, or from a previous session; none of those sources establish anything.

- **The host tracks what entered scope and how.** For each record the feature may act on, the host keeps the resource ID, the read that introduced it, the principal and tenant it was read under, the version or observation time, and an expiry. Valid entry paths are an authorized direct lookup or membership in a container the user already holds. Anything else, including an ID copied from another conversation, needs a scoped read first or gets a structured refusal.
- **Authorization is checked for the current operation.** Being allowed to read a record is not being allowed to update it, and a permission that held ten minutes ago may have been revoked since. The check runs against current state at the moment of the operation, not against the fact that the record is in scope.
- **A delegate's read does not widen the parent's reach.** When a read-only sub-agent or worker surfaces a record, the parent that wants to act on it resolves the record through its own authorized read path first. Findings travel; authority does not.
- **Authoritative fields stay in the backend.** Prices, eligibility, ranking, balances, and required disclosures are computed and supplied by the owning system. The model chooses which record or which approved disclosure applies; it never recomputes the value. When exact wording is required, the host supplies the approved copy and its version. A server-owned price sitting next to a model-written explanation does not make the explanation true.
- **Descriptive fields remain untrusted.** A verified record ID does not sanitize the record's title, notes, or free-text fields. Those go through the same injection fencing as any retrieved document.

### The presentation receipt

When the model selects what the user sees, such as an ordered set of cards, a comparison, or a plan, it does so through a typed presentation tool: a component type, an ordered list of record references, and the explanatory fields it may fill. The host validates the payload, resolves each reference through the provenance record above, fills the authoritative fields, and emits a versioned view event.

What the model asked to show and what the user finally saw can differ. Records get filtered as unauthorized or stale, the host enriches, the client paginates or re-sorts. So the host returns a compact receipt to the model and retains it with the conversation:

- a presentation identity and revision, assigned by the host, never by the model;
- the component type and any parent or group structure;
- the visible record IDs and labels in their final order;
- the record and disclosure versions or observation references each item was rendered from;
- what was omitted and why;
- a status: emitted, displayed, failed, or superseded.

The client acknowledges the revision it displayed and reports any reordering that changes what "the second item" means. Stale acknowledgements are ignored. A client that cannot report its layout must preserve the emitted order exactly, and the host treats delivery as unconfirmed until something observes it.

### Follow-up references resolve against the receipt

"The second one", "the cheaper option", and "that plan" resolve against the acknowledged receipt of the view the user is looking at, not against the model's original argument order and not against a re-run of the query. When the receipt is missing, superseded, or ambiguous, the feature refreshes the view or asks which item was meant. Guessing is the failure this receipt exists to prevent.

The receipt reference survives compaction and executor handoff, rehydrated from the host rather than reconstructed from the transcript. Replaying the conversation history does not re-run a write tool.

### Provisional renders

Start with complete, validated components. If the product streams a preview, the preview uses validated and authorized fields only, is marked provisional, and is replaced under the same presentation identity when the final event arrives. Partial JSON is neither an accepted action nor a render receipt. On validation failure or cancellation, the provisional view is removed or marked and a structured result is returned. Progress text describes what has been observed so far and never claims completion. A provisional render authorizes nothing and proves no delivery.

## 2. Shared Resulting-State Limits

A business limit constrains the state that results from a write, including every prior successful write and every active reservation. A cap of four items means two requests to add three each cannot both succeed, even though each request alone is under the cap.

- **Name the limit's scope.** Decide whether each limit belongs to a resource, a person, an account, a tenant, or a time window, and write the decision down. A session-local counter cannot enforce an account-wide rule, and a lock held by one process cannot serialize writers in another process, another worker, or a human at an admin screen.
- **The atomic apply boundary is at the authoritative backend.** In one transaction, or through a conditional write at the shared resource scope, the backend reads the relevant state and version, validates the proposed resulting state against current policy, and commits the mutation together with its limit accounting. The precondition failing means a conflict or limit result and no partial write. If the backend allows a reduced amount instead, that reduction is explicit in the result and within the approved scope; it is never silently applied.
- **Staged changes carry a host-issued identity.** A proposal binds the target, the expected version, the exact diff, and the approval scope. At apply time the backend rechecks, inside the same commit boundary: current authorization, approval validity, current policy, the live target version, live limit state, and the idempotency key. When live state has changed the approved effect, the stale stage is rejected and a fresh proposal is prepared under whatever approval policy now applies. Checking new policy against old values does not detect target drift.
- **Idempotency and limits are different checks.** An idempotency key protects against one operation being delivered twice. A resulting-state check protects against two distinct, individually valid operations combining past the limit. A feature needs both.
- **Unknown outcomes are reconciled first.** A commit whose result was never observed is neither succeeded nor failed. Read the authoritative state back before retrying it, and before releasing any reservation it may have taken.

This section describes what the owning backend must enforce and what the handoff must tell the executor to build there. OMH does not implement the transaction and does not implement the store.

## 3. User-Memory Lifecycle

Persistent facts about a person are personal data under a lifecycle contract that is separate from session history and separate from reusable instructions. Persistence is optional per deployment; when it is off or unavailable, the constraints the user stated in this conversation stay in force for this conversation.

### What may be stored

- **Eligible sources only.** A stored fact comes from the user's own assertion or the user's explicit confirmation, with a reference to the evidence. Quoted material, tool results, retrieved documents, and the assistant's own guesses are not user assertions. The assistant repeating a third party's statement does not make it eligible. Filtering out tool-result messages is not sufficient provenance on its own.
- **Person and tenant are resolved by the host.** A shared account or an organization ID does not identify a person; when individual identity is unavailable, personal memory is omitted rather than attached to the account. Subject, tenant, and resource permissions are checked on every read and every write.
- **The host validates every save.** Permitted fact categories, provenance, scope, size, and retention are checked by a host validator that applies deployment policy and any required user choice. A model-emitted save request is a proposal, not an authorization.

### What the user controls

The user can inspect stored facts, correct them, delete them, see the retention that applies, and turn persistence off. A correction supersedes the older evidence. A deletion or expiry removes the fact from every future read and invalidates every profile, cache, or summary derived from it. Only the non-content metadata needed to prevent replay is retained, under an explicit retention rule. An append-only audit log, a rollback, a cache, or a retry must never bring deleted personal content back.

### Delayed extraction

An application that cannot afford extraction on the response path may run a bounded background extractor after a turn or session. It is post-MVP and optional, and it writes through the same validated path as an explicit save.

- Each extraction is identified by subject, source-event window, and an idempotency key, and it captures the fact versions it expects and the deletion generation that applied when the window was taken.
- The storage transaction checks the expected versions, the deletion generation, and current policy in the same transaction that applies the change and records the idempotency result. A generation check followed by a separate save is a deletion race.
- Deletion or expiry invalidates pending extraction and fences replay of pre-deletion evidence, including work rebuilt from an old transcript. A stale extractor cannot refresh its generation and resubmit the same evidence. A later, fresh user assertion may create a new fact.
- A version conflict is reconciled against current facts and any newer user correction. It is never a blind overwrite.
- Extraction is eventually consistent. A fact is not reported as saved before a committed result, and the next turn never waits on background completion. On timeout, failed validation, ambiguous provenance, or unavailable storage, the conversation-level constraint stays active and a bounded failure is recorded; an uncertain commit is resolved through the idempotency record before any retry.

### Read paths

Three read paths share one permission and freshness filter:

| Path | What it carries |
| --- | --- |
| Always present | A small set of permitted, current facts that almost every request needs. |
| Preloaded for this turn | Facts selected before the model call from an observed task or entry-point signal. |
| Explicit lookup | Everything else, fetched only when the task needs it. |

Each path drops deleted, expired, and inaccessible facts. An uncertain or stale fact is omitted, and the feature asks for the current value when the task depends on it. Personal context is kept out of the shared cacheable prompt prefix. Retrieval volume is not a success metric; memory behavior is measured through the fixtures in `references/eval-harness.md`.

## 4. Predictive Skill Loading

A host may load an already-reviewed skill before the first model call when an observed signal, such as the entry page or the classified task type, predicts that the skill will be needed. This is an optimization, and it is optional.

- **A signal selects context. It grants nothing.** Preloading a skill does not grant a tool permission, does not introduce an instruction that was not already reviewed, and does not make any policy conditional on the skill having loaded. Mandatory policy is present whether or not a skill was preloaded.
- **Bounded, versioned, logged.** The selection is limited in size, the signal and the loaded skill version are recorded, and the loaded body is placed in scoped context or tool-result history so the shared prompt prefix is not rewritten on every request.
- **Uncertain matches fall back.** When the signal does not clearly predict a skill, ordinary on-demand loading applies. No universal traffic threshold decides the placement.
- **Measured, not assumed.** Always-loaded, preloaded, and on-demand placement are compared on representative tasks and near misses by task frequency, quality, context cost, and turns saved. A placement without that comparison is a guess.

The same entry signal may drive memory preloading only after the memory read path's own permission and freshness checks have run.

## Evidence Boundary

A provenance design, a receipt shape, a limit scope, a memory policy, and a preloading plan are prepared work. None of them is a record store, a transaction, a rendered view, a deletion, or an observed eval. A fixture that proves any of these contracts is a fixture until a harness run emits its result; until then the outcome is absent, not passing, and the handoff stays `prepared_not_observed`.

## Anti-Patterns

| Pattern | Why it fails |
| --- | --- |
| Acting on an ID because the model produced it | A well-formed ID proves nothing about existence, scope, or permission. |
| Resolving "the second one" from the tool arguments | The client filtered or re-sorted; the user is looking at a different second item. |
| Treating a provisional render as delivered | Nothing observed the final view; the partial view authorized nothing. |
| Validating each request under the cap | Two valid requests exceed the cap together; only the resulting state can be checked. |
| A session lock guarding an account-wide limit | Other sessions, workers, and admin screens share the state and never saw the lock. |
| Rechecking policy against the staged values | The target moved; the stage is stale even if the policy still allows the old numbers. |
| Storing what the assistant repeated | The assistant is not the user; a repeated third-party claim is not a user assertion. |
| Checking the deletion generation, then saving | The deletion landed between the two steps and the fact came back. |
| Preloading a skill and skipping its permission check | A prediction chose context; it never chose authority. |

## Attribution

Concept lineage only. The separation of record provenance from authorization,
the final-order presentation receipt, the resulting-state limit with an atomic
apply boundary, the user-memory lifecycle with a deletion generation checked in
the same transaction, and bounded permission-neutral predictive loading are
adapted from `DenisSergeevitch/agents-best-practices` at revision
`8ae085045bd6cddfab22c740c95dd2d764117ffc` (MIT License, Copyright 2026 Denis
Shiryaev). No upstream text is reproduced. The wording, the conditional
activation rule, and the `prepared_not_observed` claim boundary are OMH's own,
and the upstream commerce-agent example is treated as evidence for the
contracts, not as a portable runtime result: its demo authentication,
process-local locking, and partial operator isolation are the weaknesses these
contracts exist to rule out.
