# Project Memory

OMH project memory is a local, reviewed control plane for one project. Normal
users use natural-language Hermes chat: ask Hermes to remember a bounded fact,
review existing memory, or clean up old project context. The memory commands
below are an agent, wrapper, and operator control-plane reference, not steps for
normal chat users.

OMH does not read, patch, or mutate opaque Hermes internal memory.

Reviewed records can have explicit user-global, project, or thread scope.
Storage location doesn't grant scope: a record in the user home isn't
necessarily global. See [Canonical Memory Prefetch](MEMORY-PREFETCH.md) for
scope allowlists, compatible store rollout, render budgets, and receipt privacy.
For a forgotten-preference complaint, use the
[Memory Recall Incident](MEMORY-RECALL-INCIDENT.md) workflow to distinguish
storage, eligibility, selection, rendering, delivery, and use.

## Acting-principal boundary

`project_memory_record/v3`, `omh_memory_scope/v3`, and
`project_memory_review_record/v3` add an identity block alongside scope. A
`user` scope binds an opaque `principal:v1:<sha256>` subject; a reviewed shared
project or thread record has no user subject and carries an explicit bounded
principal audience. Subject, event actor, reviewer, executor perspective, and
audience are separate fields. Profile, display name, session, thread, and
executor labels never substitute for a subject principal.

A host adapter derives a principal with the profile-local HMAC key and supplies
a fresh `memory_principal_context/v1` for capture and each shared turn. The
public `--principal-context PATH` option is an operator/wrapper-supplied local
binding, not proof that a chat platform authenticated the author. Missing,
wrong-profile, ambiguous, bot, and system contexts fail closed for personal
admission and recall. On shared surfaces, v1/v2 identity-unbound records and
unscoped memory blocks are not returned. On explicitly nonshared surfaces,
existing reviewed v2 project and thread records retain their prior behavior;
user-scoped v3 records still require a principal.

The current Hermes callback contract does not provide an authenticated author
on every shared turn. Wrappers may pass validated context through the provider
API; otherwise OMH denies personal recall. Operators must also disable Hermes'
unscoped built-in USER/MEMORY injection on shared profiles when they need this
boundary: OMH cannot isolate native memory already loaded outside its provider,
provider tenants, operating-system accounts, or platform authentication.

Migration is report-first and agent/operator-only:

```sh
omh memory principal-migration --report --json
omh memory principal-migration --plan reviewed-plan.json --apply --json
omh memory principal-migration --rollback <operation-id> --apply --json
omh memory principal-export --principal-context principal.json --json
```

The report contains bounded record identities, revisions, review IDs, and
digests, never summaries. Before apply, the wrapper/operator review adapter
records `memory_principal_assignment_review/v1` through the existing memory
operation store. That immutable record binds the verified source review and the
proposed subject, reviewer, executor perspective, and audience policy. The plan
names both reviews plus its own digest; a source review alone never authorizes
principal assignment. Apply archives the source and uses the existing operation
store; replay is idempotent. Rollback restores only
an unchanged migrated revision and refuses rather than clobbering newer data.
Legacy records are never assigned to the next active user automatically.

### Surface classes

Which surfaces are shared is decided in the provider's `initialize`, from the
`platform` and `agent_context` Hermes passes (`agent/agent_init.py`,
`_memory_provider_init_kwargs`), and for a messenger conversation from the
chat's ids, which each turn start re-checks. Anything unknown fails closed:

| Class | Hermes inputs | Reads | Writes (`capture`, `demote`) | Pack extras |
| --- | --- | --- | --- | --- |
| `operator_console` | `platform` is `cli`, `tui` or `desktop`, primary context | nonshared: reviewed v2 records, user-global, blocks (`omh_memory` `blocks` and `read` too) | yes | system blocks, reference index, the `omh reminder:` line, the consolidation brief |
| `shared` | every gateway (`telegram`, `discord`, `slack`, `whatsapp`, ...), `api_server`, `webhook`, `relay`, `acp`, an empty platform, anything else | principal-bound only, as above; `blocks` and `read` refused (`shared_surface_reads_refused`) | refused (`shared_surface_writes_refused`) | none |
| `background` | any `agent_context` other than `primary` (Hermes passes `cron` for the scheduler) | as `shared`, with the same block refusal | refused (`writes_disabled`) | none |
| `owner_direct` | a gateway session whose ids prove a 1:1 DM with the only user Hermes authorizes on the platform (see [Messenger conversations](#messenger-conversations); never on Discord) | as `operator_console` | as `operator_console` | as `operator_console` |
| `direct` | a proven 1:1 DM with anyone else | only records bound to that person's principal; `blocks` and `read` refused | `capture` bound to that person (v3, `user` scope); `demote` refused (`demote_owner_only`) | none |
| `channel` | a proven group conversation, or any Discord conversation | only that channel's records (`channel` scope); `blocks` and `read` refused | `capture` into that channel's scope; `demote` refused | none |

An operator console is not a multi-party chat. The CLI REPL, the TUI and the
Desktop chat panel reach the agent through an OS login, a dashboard login or a
Desktop token, each of which already grants full control of the agent, so
reading the operator's memory there discloses nothing that access did not. That
holds for a remote Desktop or dashboard login too. A caller may pass
`shared_surface=True` to tighten a console to `shared`; nothing loosens a
class. The class is published in the session lens, and `omh_memory` reads it
back.

Only an operator console somebody is at raises a consolidation brief, moves
the dreaming counters (turns, compactions, observed Hermes memory writes),
retires a brief after a Hermes memory write, or records a session close for
the digest window. A brief is the profile's state in its OMH home, served on
that profile's next console turn,
so one raised by a group chat's compaction would tell the TUI that "this
conversation" lost messages it never had, and a group chat's write would
settle the operator's brief. The write journal still records Hermes memory
writes from every writing context.

A Kanban worker is a console: Hermes starts it as
`hermes -p <profile> --cli ... chat -q` (`hermes_cli/kanban_db_dispatch.py`),
which builds its agent with `platform="cli"`, so its turns keep their records.
It runs unattended, recognised by `HERMES_KANBAN_TASK` or
`HERMES_SESSION_SOURCE=kanban` in the worker's environment, read at
`initialize`. A worker gets no reminder, brief or digest, raises no brief,
moves no counter and records no session close: a question asked or a digest
served there would count as delivered to the operator, and the brief would ask
an unattended run to remove Hermes entries. A worker's default workspace is a
scratch directory outside any repository, so the outside-repository rule below
gives it user-global records, and still no project's.

One session id can have two providers. Hermes' session-hygiene agent and its
`/compress` agent load the provider as `platform="cli"` under the live gateway
session's id, though only with `compression.checkpoint_required` on, and
today Hermes then stops their compression as `checkpoint_incapable` before it
reaches OMH's (API v1) `on_pre_compress`. Each lens names the provider
instance that wrote it, and this is what that guarantees:

- A provider publishing over another instance's live lens may only tighten
  it. A looser one adopts the class it found and stays a guest under that id,
  writing nothing.
- A provider withdraws only a lens it wrote, and republishes its own when the
  lens on disk is missing or another instance's. It refreshes its lens's
  `published_at` at every turn start.
- A tightening belongs to the session id: it holds through every later read
  and through a failed lens write, and the next id (`/new`, a compression)
  starts from the class `initialize` decided.
- The provider re-reads the lens before every render and pre-compress
  hand-off, so a tighter provider arriving between turns narrows the next
  pack.
- A foreign tighter lens unrefreshed for 12 hours is presumed left by a
  process that died, and a looser provider starting under that id replaces it.
  A process probe would not do: on Windows `os.kill(pid, 0)` sends CTRL_C. If
  that owner is alive after all, its next turn start takes the lens back,
  because tightening is always allowed; until then the tool reads the looser
  lens. If that reclaim write fails, the owner removes the looser lens instead,
  so the session reads as unbound (`session_lens_unavailable`) rather than
  looser.
- A tightening is visible: the prefetch receipt and `omh memory status`
  (`last_prefetch`) carry `surface_class` and `tightened_by_foreign_lens`.

What it cannot guarantee: when the looser provider publishes first, the tool
reads its lens until the tighter one publishes, which is an ordering Hermes
decides. A lens an earlier OMH release wrote names no instance. It counts as
another instance's, so it is never widened, and only the session's own console
provider withdraws it; while an earlier-release provider is still running, it
can lose its lens that way and the tool then fails closed for that session.

A shared surface does not capture: nothing tells OMH which participant of a
group chat stated a fact.

### Messenger conversations

A gateway session is shared unless the chat's own ids prove what it is (owner
decision 2026-10-13, `memory_messenger.py`). Hermes passes `chat_type`,
`chat_id`, `chat_name`, `user_id` and `thread_id` to `initialize`, each only
when set, and `author_id` and `author_is_bot` to every `on_turn_start`
(`agent/turn_context.py`). `chat_type` alone proves nothing:
`SessionSource.chat_type` defaults to `"dm"`, the relay transport turns a
missing value into `"dm"` (`gateway/relay/ws_transport.py`), a handoff into a
home channel that opened no thread is labelled `"dm"` with
`user_id="system:handoff"` (`gateway/run_startup.py`), and Slack labels a
group DM (mpim) `"dm"`. Each covered platform has its own check on the ids,
from its adapter:

| Platform | 1:1 DM | Group conversation |
| --- | --- | --- |
| `telegram` | `chat_id == user_id`, a positive id (a private chat's id is the user's own; a channel post's author is the negative channel id) | `group` or `channel`, a negative id |
| `slack` | a `D...` IM channel (an mpim's id is not), a `U...`/`W...` author, and a named chat | `group`, a `C...` or `G...` channel |
| `discord` | none: every conversation is a channel | any conversation, by its snowflake id |
| `whatsapp` | a person's JID (`@s.whatsapp.net` or `@lid`) for both chat and author, one person by Hermes' own alias rule and lid-mapping files | `group`, an `@g.us` JID |
| `whatsapp_cloud` | `chat_id == user_id`, digits | none (the Cloud API delivers no groups) |
| `signal` | `chat_id == user_id`, a phone number or UUID | `group`, `group:<id>` |

Slack's message path always names the chat, falling back to its id
(`_resolve_channel_name`); a slash command never does
(`_handle_slash_command`), and one can be run in a DM between two people,
whose id starts with `D` too. An unnamed `D...` chat is therefore shared. A
relay connector that forwards a slash command with a name is beyond this
check.

Discord has no DM check. The relay transport keeps the platform `discord`
when it turns a missing type into `"dm"`, and the relay adapter labels every
guild-less interaction `"dm"`, user-installed app commands in group DMs
included (`gateway/relay/adapter.py`). Relayed events are authorized upstream
(`gateway/authz_mixin.py`), and nothing in the provider's kwargs says an
event was relayed. So every Discord conversation, a DM included, is a
`channel`, and Discord has no `owner_direct` or `direct` session. Memory is
per `chat_id`, except for Hermes auto-created threads as described below.

Every other platform (Matrix, Mattermost, email, SMS, Feishu, DingTalk, WeCom,
Weixin, QQ, LINE, Google Chat, Teams, IRC, BlueBubbles, SimpleX, ntfy, A2A,
Buzz, Photon, Raft, Home Assistant, `api_server`, `webhook`, `relay`) has no
check and stays shared: Matrix decides DM-ness from a member count it does not
pass on, several adapters default a missing type to `"dm"`, and email, ntfy
and IRC put many people behind `chat_id == user_id`.

A proven DM is the owner's when its partner is the only person Hermes
authorizes on the platform: `<PLATFORM>_ALLOWED_USERS` and
`GATEWAY_ALLOWED_USERS` (the process environment and the profile's `.env`)
together with the pairing store's approved users
(`platforms/pairing/<platform>-approved.json`, and the legacy `pairing/`).
A `GATEWAY_ALLOWED_USERS` entry counts for a platform only when it has that
platform's id shape, so one global list can name the owner on two platforms:
a `U...`/`W...` id for Slack, positive digits for Telegram, a number (after
dropping `+`, a device suffix and a JID domain) for either WhatsApp API, and a
`+` phone number or a UUID for Signal. No platform's user can carry another's
shape, so the filter drops nobody Hermes admits there; bare digits fit Telegram
and WhatsApp alike and count for both. OMH reads those files and never writes
them. Anything that could admit someone OMH cannot list leaves no owner: an
allow-all flag or a `*` entry, an empty set, an unreadable pairing file, an
allowlist entry that is not a user id (a username), or an authorization key in
`config.yaml` (`allow_from`, `allowed_users`, `allow_all_users`,
`allowed_roles`, or a `dm_policy` other than `pairing` or `disabled`), because
Hermes consults those when no env allowlist exists and their members cannot be
listed without a YAML parser. Without an owner every proven DM is that
person's own.

"One authorized user is the owner" is the owner decision, and it has a
consequence: whoever that one person is reads the operator's memory in their
DM. A Hermes run for someone else -- a bot an operator sets up for one client
or one family member, with only that person allowed -- hands that person the
operator's user-global records, blocks and brief. To keep the DM per-person
there, authorize a second id (the operator's own id beside theirs, in the
allowlist or by pairing), or set any `dm_policy` other than `pairing` or
`disabled` in `config.yaml`; either one leaves no owner, and every DM is then
its partner's own.

The owner's DM reads and writes like the CLI, user-global records included,
and gets the console's pack extras: blocks, the reference index, the
`omh reminder:` line, the digest and the consolidation brief, whose demote rows
quote the owner's own USER.md and MEMORY.md to the owner. Anyone else's DM gets
a principal derived like any other (`principal:v1:<hmac>` over profile,
platform and the partner's id with the profile-local key; for WhatsApp, the
shortest of the partner's aliases, as Hermes keys the DM, so a phone/LID flip
keeps the person's memory), captures there are v3 records bound to it, and
recall there returns only records that principal may read; the console never
recalls them, and no one sees the owner's identity-unbound memory or another
person's records. `confirm`, `correct` and `retire` reach a person's own v3
records: `user` scope with a `subject_only` audience. A v3 record shared with
an explicit audience stays out of the model's lifecycle actions.

A group conversation's memory is its own: a capture there is stored under a
`channel` scope whose ref is `channel:v1:<hmac>` over profile, platform and
`chat_id` (keyed, because a group's id can carry a phone number), and the
principal gate admits an identity-unbound record on a shared surface only when
its scope is exactly a channel the caller's allowlist names. `thread` already
means one Hermes conversation, keyed by a session id that rotates at `/new`,
at a compression and per participant, and `target` has its own meaning, so a
channel got a kind of its own. Threads share their channel's scope: Slack's
default `reply_in_thread` makes every top-level channel message its own thread
session, and a Slack thread or a Telegram topic is visible to everyone in its
channel, so a narrower scope protects nobody and would give each message an
empty memory. A group gets no blocks, reminder, brief, digest or demote.

Discord delivers a thread under its own channel id. A public thread Hermes
auto-created from a channel message instead shares its parent channel's memory
scope, so a fact saved there is eligible for recall in the next auto-created
thread in that channel and in the parent channel itself. The provider reads the
session's `origin_json` from Hermes' `state.db` read-only, and uses
`parent_chat_id` only for a Discord thread marked `auto_thread_created: true`
with a valid parent id distinct from its own. Other threads, including private
or manually created threads, keep their own scope. Missing or invalid origin
data also leaves the conversation's own `chat_id` in use.

Each turn is bound again at `on_turn_start`. A turn whose author is a bot, or
whose author is not the DM partner, is shared for that turn: nothing
identity-unbound, no writes. An absent author is the partner, since a proven
1:1 DM has two parties and the bot's own messages start no turn. The turn's
author is kept, so a session id that rotates inside the turn (a compression,
a turn-lease reload) is bound by the same author. The authorized set is
re-read at every turn start, and every file it comes from (`.env`,
`config.yaml`, the pairing files, WhatsApp's lid-mapping files) only when its
stat changes, so a second person paired mid-session turns the owner's DM into
that person's own DM at the next turn. A digest pending in the owner's DM
stays pending through a shared turn.

The lens carries the class and its binding: a `direct` lens without a human
principal context, or a `channel` lens without a `channel:v1:` scope, is not a
lens, and the tool reads the session as unbound. The nonce rules above hold:
`owner_direct` ranks between `operator_console` and `direct`, and `direct` and
`channel` withhold different things, so where they meet only `shared` holds.
A provider under another instance's `direct` or `channel` lens holds no
binding of its own and is `shared`; a guest -- a hygiene or `/compress` agent,
whatever its own class -- is never attended.

A coding handoff built for a chat (a wrapper session, a chat interaction, a
lifecycle start, `omh coding delegate` away from a terminal) carries only what
that chat may see, by the lens of the Hermes session it names. In process --
the `omh_interact` tool -- that is the tool's own `session_id`, which Hermes
passes every plugin tool; `HERMES_SESSION_ID` is never read there, because in
a gateway it is process-wide and belongs to whichever agent was built or
compressed last. Only a command Hermes starts (`omh coding delegate`,
`omh coding lifecycle start`, `omh chat interact`, `omh chat session start`
and `prepare-handoff`) reads `HERMES_SESSION_ID`, because Hermes builds
each command's environment from that command's own session
(`tools/environments/local.py`). The owner's DM uses the console allowlist;
another person's DM reads only records bound to that person's principal; a
group reads only its channel's scope; any other session, or none, is shared
(`shared_surface=True`, no principal), which admits no identity-unbound
record, so a repository's project records no longer travel to a chat nothing
verified. `omh_memory` stores a project-scoped capture in the user store
(`OMH_HOME`), not in `<repo>/.omh`; a handoff reads the store its caller
resolved.

## Optional Project Terms Source

A repository may have one optional `PROJECT_TERMS.md` at its root. It is a
portable, repository-reviewed human source for the words that project uses. If
it is absent, nothing happens: OMH does not create it, import it, scan for an
alternative, or treat its absence as a setup or health problem. OMH never
rewrites, commits, reverse-generates, or keeps the file synchronized.

The file and the machine store have different authority:

- `PROJECT_TERMS.md` is human-readable source material. Editing or committing it
  does not activate a mapping or change OMH behavior.
- An active, reviewed, project-scoped `domain_intelligence_profile/v1` is the
  machine-readable terminology source. It is reached only through preview,
  pending staging, separate review, and explicit approval.
- Reviewed mappings remain advisory clarification context with the claim
  boundary `routing_prior_not_override`. The ordinary router remains
  authoritative.

### Strict `omh-project-terms/v1` grammar

The parser accepts UTF-8 without a byte-order mark, no more than 65,536 exact
source bytes, and either LF throughout or CRLF throughout. The preamble,
including blank lines, is exact:

```markdown
# Project Terms

Project terminology only. This file is not agent instructions, routing rules, approval, execution, or evidence. Changes affect OMH only after explicit review.

<!-- omh-project-terms/v1 -->

## domain: delivery

- term: `dispatch packet` = `handoff`
  definition: A prepared package of coding work for one selected owner.
  say-instead: handoff
  localized[ko]: 핸드오프
  distinct-from: `dispatch` - Dispatch is observed execution, not preparation.
- workflow-hint: `ralplan`
```

After the preamble, the only accepted constructs are:

- `## domain: <domain_id>` for a unique normalized domain. Every domain must
  contain at least one term mapping.
- ``- term: `phrase` = `canonical_term` `` for at most 40 mappings per domain.
- Two-space-indented human metadata immediately below a term:
  `definition:` (at most 240 code points), repeatable `say-instead:` values (at
  most 80 each), `localized[<locale>]:` labels (at most 80 each and one per
  locale), and one ``distinct-from: `canonical_term` - note`` (note at most 240).
- ``- workflow-hint: `existing-installable-id` `` for at most 20 unique existing
  catalog workflow ids per domain.

Values are normalized and checked with the domain-vocabulary safety rules.
Unknown lines, keys, locales, or workflow ids; duplicate or conflicting domains,
mappings, or metadata; mixed line endings; unsafe values; and size/count
violations fail the whole parse before any write. Definitions, `say-instead`
guidance, localized labels, and `distinct-from` notes are retained only in the
read-only human parse view. File capture projects only phrase-to-canonical
mappings and workflow hints into the unchanged profile-v1 candidate shape. The
SHA-256 covers the exact source bytes, so accepted LF and CRLF files can have
different source digests without their bytes being rewritten.

### Reviewed lifecycle

Normal users can ask Hermes to inspect or align project terminology without
learning commands. The commands below are an agent/operator control-plane
reference. Run them from inside the repository; file mode is bound to the
canonical project root and accepts exactly the regular, non-symlink root file
named `PROJECT_TERMS.md`. Absolute paths, traversal, alternate names, and mixed
file/direct-capture arguments fail closed.

```sh
# Agent/operator only: parse and preview; writes neither the source nor the store.
omh --scope project memory domain-capture \
  --from-file PROJECT_TERMS.md --json

# Agent/operator only: atomically stage one pending candidate per file domain.
omh --scope project memory domain-capture \
  --from-file PROJECT_TERMS.md --stage --json

# Agent/operator only: inspect a pending card and derive current source freshness.
omh --scope project memory domain-review \
  --candidate <candidate-id> --source-freshness

# Agent/operator only: make the separately reviewed candidate active.
omh --scope project memory domain-approve <candidate-id>

# Agent/operator only: list active project profiles and derive source freshness.
omh --scope project memory domain-list \
  --scope-kind project --scope-ref <project-ref> --source-freshness

# Agent/operator only: retire one active profile while preserving review/history.
omh --scope project memory domain-retire \
  --scope-kind project --scope-ref <project-ref> --domain <domain-id> \
  --reason superseded
```

Preview returns `project_terms_capture/v1` in `prepared_not_observed` state with
stable profile ids, exact source SHA-256, current base revisions, capacity, and
an empty `mutation_set`. It does not invent future candidate ids. `--stage`
preflights the complete file and capacity, rechecks revisions under the store
lock, and then writes all pending candidates or none. It does not write an
active profile. Review and approval remain separate actions; approval writes
the existing active profile and immutable review record. A competing approval
or retirement makes an older candidate fail closed as `stale_candidate`.
Listing observes active profiles. Retirement records a retired revision and
preserves review and history; later activation requires another reviewed
candidate.

File-derived candidates store only bounded provenance:
`source_class="omh_local"` and `source_ref="pt_sha256:<exact-byte-sha256>"`.
With explicit `--source-freshness`, project-scoped review and list derive one of
four states against the current root file:

- `unchanged`: current exact bytes match the recorded digest.
- `changed`: current exact bytes have a different digest.
- `missing`: the tracked root file is absent.
- `untracked`: the artifact is not valid provenance for this repository's
  project-terms source.

Freshness is computed for that response only. It is not persisted and does not
stage, approve, reject, replace, retire, rewrite, or delete anything. `changed`
and `missing` are review-needed information, not synchronization and not a
claim that the active profile changed. The file remains project-only: this path
cannot import user or organization vocabulary into the repository source.

### Behavior and evidence boundaries

Neither the source prose nor a reviewed mapping routes, reranks, or dispatches a
request. Only an eligible, genuinely unresolved router-owned interaction may
receive one bounded advisory clarification from an active reviewed profile.
Explicit workflows, dispatch, status, help, file lookup, maintenance, direct
answers, task cards, and already selected routes remain protected. Workflow
hints are advisory identifiers, not instructions or dispatch authority.

Project terms do not execute work, perform code review, run tests, invoke CI,
approve a plan, establish merge readiness, or merge code. Preview, staging,
review cards, approval records, profile matches, freshness, and prepared context
packs are not evidence that Hermes, a model, provider, executor, or coding
owner read or used the terms. OMH persists neither the human definitions nor
raw prompts, transcripts, hidden reasoning, logs, or task progress through this
capture path.

The generated `ulw-context` skill is the Hermes workflow surface for direct
terminology lookup, explicitly confirmed pending-candidate capture, and
confirmed dependency-frontier interviewing before a separate planning or
handoff transition. Its catalog id is `context`; it does not make glossary prose
a routing input or change the lifecycle above. Generated name and description
metadata make it eligible for host semantic nomination, but live Hermes
semantic nomination is `not_tested`: the installed host profile used for QA did
not contain `ulw-context`, and no profile mutation was made. Explicit invocation
and deterministic lexical-proxy results are the only current selection
evidence. The lexical proxy measures metadata token competition; it is not
semantic nomination evidence.

Reviewed active project-domain profiles are now projected read-only into the
existing handoff context and role packs. Only validated, approved summaries for
the current project are included; pending, rejected, retired, malformed,
digest- or review-mismatched, and scope-mismatched artifacts are excluded. The
projection has identical semantics for Codex, Claude Code, Hermes, and generic
executor targets. It stores no exact source-file bytes. A projected summary is
prepared context only, not evidence that an executor or model received, read,
or used it, and not dispatch, execution, review, CI, merge-readiness, or merge
evidence.

The lifecycle still does not automatically place `PROJECT_TERMS.md` in
sessions, runtime records, or coding handoffs. Exact source bytes can be
included only through explicit workspace-relative file selection in
`handoff_input_manifest/v1`, subject to content hashing, safety classification,
item limits, and byte-budget checks. Manifest preparation or inclusion is
prepared context only; it is not proof of dispatch, receipt, reading, model
use, execution, review, CI, merge-readiness, or merge.

The workflow adapts dependency-frontier interviewing and the
separation of terminology from implementation decisions from Matt Pocock's
`grilling` and `domain-modeling` skills at revision
`84fdeffd12f2ee307994d1eb6feb48173b6e0502`, under the MIT License (Copyright
2026 Matt Pocock). The strict file grammar and reviewed OMH lifecycle above are
OMH-specific adaptations rather than copied upstream prose or runtime behavior.

## Reviewed Domain Intelligence

Domain intelligence is a separate reviewed vocabulary store for agents,
wrappers, and operators. It lets an operator curate bounded user,
organization, or project vocabulary without changing routing in the same
release. The store lives under `.omh/memory/domain-intelligence/` with
`candidates/`, `profiles/`, `reviews/`, `history/`, and `operations/`
subdirectories.

Every scope reference is an explicit opaque key supplied by an operator or a
wrapper identity boundary:

- `user`
- `organization`
- `project`

The stored ref is labeled `operator_or_wrapper_supplied`. It is a routing
scope key for future use, not authenticated identity evidence, and OMH v1 never
infers it from chat text, summaries, or vocabulary.

The operator lifecycle is:

```sh
# Agent/operator only: stage bounded vocabulary for manual review.
omh memory domain-capture \
  --scope-kind organization \
  --scope-ref org-acme \
  --domain sales \
  --mapping "QBR=quarterly_business_review" \
  --mapping "deal desk=deal_desk"

# Agent/operator only: inspect pending review cards.
omh memory domain-review

# Agent/operator only: approve, reject, list, or retire.
omh memory domain-approve <candidate-id>
omh memory domain-reject <candidate-id> --reason insufficient_evidence
omh memory domain-list --scope-kind organization --scope-ref org-acme
omh memory domain-retire --scope-kind organization --scope-ref org-acme --domain sales --reason superseded
```

Captured candidates are `domain_intelligence_candidate/v1` and always remain
`pending_review` until an explicit approval or rejection. Approval writes one
current `domain_intelligence_profile/v1` for the exact `(scope.kind,
scope.ref, domain_id)` key and one immutable
`domain_intelligence_review_record/v1`. The profile id is deterministic for
that key, so a public approval path cannot create duplicate current profiles.
Approvals are complete replacements: the next approved candidate increments the
revision and archives the prior profile under `history/`. Retirement writes a
reviewed retired revision and keeps review/history files; later reactivation
requires another reviewed candidate.

Candidates record `base_profile_revision`. Approval fails closed with
`stale_candidate` if another approval or retirement changed the current
revision after capture.

Profile eligibility is fail-closed. Readers exclude pending, rejected, retired,
malformed, digest-mismatched, or review-mismatched artifacts and report bounded
diagnostics instead of exposing raw content. The canonical profile digest covers
only behavior-bearing fields: schema version, profile id, revision, status,
scope, domain id, sorted vocabulary mappings, sorted workflow hints,
confidence metadata, bounded provenance metadata, and base profile revision.
It excludes candidate/review identifiers, reviewer claims, timestamps,
claim-boundary prose, and filesystem paths.

Local filesystem authorization is the trust boundary for this store. Payload
and operation digests detect accidental corruption, partial or internally
inconsistent mutation, and mismatched artifact linkage. They do not
authenticate content against a process authorized to write the store: such a
process can coordinate replacements across candidates, profiles, reviews,
history entries, and operations and recompute the ordinary SHA-256 digests.
The design has no secret key or immutable external anchor. Symlink rejection,
path-containment checks, bounded reads, and untrusted-artifact validation still
protect storage access and fail closed on unsafe or malformed input; they do
not authenticate an authorized local writer.

Domain-intelligence artifacts persist only explicit bounded vocabulary,
identifier-like workflow hints, confidence metadata, and bounded provenance.
They do not store raw prompts, transcripts, hidden reasoning, chat logs, or
Hermes internal memory. The profile claim boundary remains
`routing_prior_not_override`. Only an eligible, genuinely unresolved wrapper
interaction may consume an active reviewed profile from the current
repository's own project-local store, and only to select one catalog-owned
clarification question. The route, candidate handoff, and plan artifact's
`deep_interview_contract/v1` remain unchanged. This is clarification context,
not routing authority, plan approval, execution, review, CI, merge,
authentication, or Hermes internal-memory evidence.

For each eligible interaction, OMH derives the canonical current repository and
its unnamed project-scoped `.omh` store internally rather than accepting a
caller-supplied domain identity. User and organization profiles are not
consumed until an authenticated principal binding exists. The bounded
`domain_routing_context/v1` response context is ephemeral: it is not copied
into wrapper-session continuity, runtime records, coding handoffs, status
records, or other persisted interaction artifacts.

Replacement or retirement takes effect on the next eligible interaction. Any
unhealthy, incomplete, malformed, or conflicting profile store fails closed to
the existing generic question. Direct answers, file lookup, help, maintenance,
task cards, explicit workflows, static specialist routes, operator actions,
workflow learning, status, and every dispatch remain protected. Profiles do
not automatically learn from chat, select a route, rerank candidates, or
trigger dispatch.

This clarification-only milestone leaves broader work explicit: reviewed
activation before any routing influence; multi-round research and planning
cognition; passive missed-route review; domain-pack expansion; and optional
offline evaluation. Each requires its own reviewed authority, privacy, and
evidence contract before it can change public behavior.

If a future routing design includes malicious local writers in its threat model,
it must revisit authenticated provenance; key management or authenticated
append-only infrastructure is outside this local metadata-only foundation.

Reviewer claims and source references are safe opaque identifiers only:
ASCII letters, digits, `_`, `.`, `:`, and `-`, up to 120 characters. Review
reasons are metadata-only reason codes, not free-form text. Accepted codes are
`duplicate`, `incorrect_scope`, `insufficient_evidence`, `operator_request`,
`scope_error`, and `superseded`.

## V2 Model

New OMH-owned artifacts use versioned, replay-gated records:

- `project_memory_candidate/v2` is a bounded candidate with source class,
  canonical scope, retention choice, and safety result.
- `project_memory_record/v2`, `omh_memory_scope/v2`, and
  `omh_memory_block/v2` carry an opaque identity, positive revision, source
  class, admission, retention, and revalidation data.
- `project_memory_review_record/v2` is immutable admission evidence. Its
  states are `pending_review`, `approved_manual`, `approved_auto_safe`,
  `blocked`, and `rejected`. `approved_auto_safe` is a local policy result,
  not a human-review claim.
- `omh_memory_replay_evaluation/v1` records why an immutable revision was or
  was not eligible for a particular replay boundary. Preparation is not proof
  that a model, provider, or executor used it.

A current v2 record must pass the same deterministic evaluator before project
recall, handoff context, provider prefetch/pre-compression, block rendering, or
an explicit block read. Unsupported schema, missing review linkage, safety
failure, expiry, stale review, scope mismatch, conflict, supersession, or a
legacy v1 artifact fails closed with a reason code.

### The model-driven loop

Hermes writes into this store itself, with no operator step in the normal
loop. When the user states a lasting preference, a decision, a fact about
their setup or project, or a lesson, the model calls
`omh_remember(action="save", summary=..., record_type=..., subject=...)`.
The memory provider exposes this small, always-visible tool for `save` and
`recall` (`action="recall", query=...`). Hermes' `tool_search` can defer plugin
tools such as `omh_memory`; tools returned by a memory provider are never
deferred, so saving a fact does not require a tool search first.

The full `omh_memory(action="capture", summary=..., record_type=..., tags=...,
scope=..., retention_class=..., subject=...)` entry point remains available for
additional capture options. Both save entry points use the same session-lens
and surface gates, and call memory admission in-process (`memory_admission` in
the plugin bundle, the same path `omh memory capture` reaches through its
adapters), with duplicates skipped, and map the result to one `status`:

| `status` | Meaning |
| --- | --- |
| `remembered` | Auto-safe approval ran; `receipt_state` says how far the write was observed, `replay_ready` only when admission's own replay evaluation cleared it. |
| `pending_review` | A candidate was persisted and held; `review_reason` is `unsafe_content`, `relative_time_phrase`, `duplicate`, `derived_content`, or `policy_review_first`. |
| `already_remembered` | A live record has the same normalized summary; `duplicate_of` names it and nothing was written. |
| `refused` | Nothing was written: invalid input (including an `invalid_subject`), a session that may not write (`shared_surface_writes_refused` on a shared surface, `writes_disabled` in a background run, `session_lens_unavailable` with no provider lens; see [Surface classes](#surface-classes)), memory turned off, a project scope this session cannot resolve, or an `instruction_shaped_summary` (a second-person order or a Korean request ending, outside `procedure` records), whose `next_action` asks for the fact restated as an observation. |
| `error` | Admission raised (an unreadable store, a lock held past its 10 s wait); `reason` names the exception class and nothing is confirmed saved. |

`subject` is optional: a short slug the model chooses for what the fact is
about (`deploy-branch`, `reply-language`), in the closed shape
`[a-z0-9][a-z0-9-]{0,47}`. Anything else is refused as `invalid_subject`, never
rewritten to fit. It is stored on the candidate, shown on its review card, and
copied onto the record. Recall serves only the newest approved record per
scope and subject (see Recall Ranking and Delivery Usage).

Version skew: a record carrying `subject` is unreadable to an OMH build from
before this field. That build's record validator refuses unknown keys, so it
skips the record (reported as unreadable) until it updates; nothing is
rewritten and the record comes back on the next read by a current build.
There is no schema bump: a new record schema would make the older build skip
every new record, not only the ones that declare a subject.

A capture that goes through can carry two hints. They are read inside the
capture's own confinement, the same set the duplicate check uses: the same
scope, the same subject principal, and for a record shared with an explicit
principal audience, the same audience. Within that, a hint can only name a
record the calling session's own lens admits. The tool passes the lens the
memory provider published (the principal, scope and perspective gates
`recall` applies, with the shared-surface verdict), so on a shared surface a
record the lens refuses never comes back through a capture result, by id or
by summary. With no published lens there are no hints. A summary that
redacted to `[redacted]` never matches anything, for hints or duplicates.

- `subject_held_by` names the newest record there that already declares the
  same subject, by recall's own rule (`newest_record`).
- `similar_record_id`, `similar_summary` and `similar_wording_pct` name the
  record whose wording is closest, when the two summaries share at least
  `SIMILAR_WORDING_JACCARD_PCT` (60) percent of their distinct stemmed terms
  (token Jaccard, compared in integers).
- `recalls_now` lists which of the new record and the named one an unqueried
  prefetch under the session's lens serves after the write. It is computed by
  running the selector, so a same-second tie on a subject (approval stamps
  whole seconds, and the smaller record id wins) or a held record that is
  stale is reported as it is. The `next_action` sentence is built from it.

Neither hint holds or refuses the capture: refusing a capture that only
resembles a held record would lose the new fact whenever the resemblance is
wrong. Neither decides that two records state the same fact. A negation
shares nearly every term with what it negates, and a subject is only a label
the model chose. For a `remembered` capture, `next_action` asks the model to
call `correct` on the named record with the same summary if the new fact
replaces it. That moves the old record to history, linked to the new one (see
`correct` below). The record a correction replaces, and an exact duplicate,
are never named as hints.

Hints and recall group a subject differently on purpose. A hint names only a
live record in the capture's confinement, because its only use is a `correct`
that acts on it. Recall's collapse groups every record still in the store
that its lens admits, expired, stale and archived ones included, so an older
value cannot come back when the newest one lapses.

The subject hint does not route to supersession automatically. A slug is the
model's own label, and two different facts can land on one by accident.
Automatic supersession would move a still-true record to history on a naming
slip, while the recall-side rule already keeps the older value out of every
pack and destroys nothing. The explicit `correct` keeps the revision pin and
the lineage link.

`scope` defaults to `project` when the session's working directory resolves a
project identity, and to `user` otherwise; `user` is stored as the
`user-global` scope, which needs no acting-principal context and is delivered
beside the project scope, and on its own on a console outside any
repository. The default policy is `auto-safe`, so a safe,
absolute, non-duplicate capture goes straight to `approved_auto_safe` and then
`replay_ready`. A tool result is what the capture operation observed on local
disk; it is never evidence that a later session recalled or used the record.

The rest of the loop is the model's too, with the operator verbs below kept
for people. The tool does not decide what a session may reach; the memory
provider does, when Hermes initializes it, and publishes that decision for
the session at `.omh/memory/sessions/<session digest>.json`
(`omh_memory_session_lens/v1`):

- the record homes it reads (the repository's `.omh` first, then the OMH home);
- the project identity behind the scope allowlist (user-global, the current
  project, the current thread; outside a repository, user-global and the
  thread only);
- the principal context;
- the `surface_class` ([Surface classes](#surface-classes)) and the two flags
  it sets, `shared_surface` and `writes_enabled`. A lens written before
  `surface_class` existed is read by its flags, and one whose class
  contradicts its flags is treated as no lens at all.

The tool reads the lens back by the `session_id` Hermes passes every tool
call, and the provider removes it at `shutdown`.

Hermes reassigns the session id mid-process. Compression, `/new`, `/reset`,
`/resume` and `/branch` call `on_session_switch`, and the provider responds by
withdrawing the old lens and publishing one under the new id. A compression
(no `reset`) carries the session's seen and confirmed ids over; a genuinely
new conversation starts empty; a `rewound` switch keeps the id and the lens.
A turn-lease reload rotates the id without calling `on_session_switch`. For
that case `prefetch`, which Hermes calls with the live `session_id` every
turn, rebinds when the id it is given differs. It rebinds as a new
conversation, with empty lists: from there a reload cannot be told apart from
a `/new` racing the next turn, and carrying a finished conversation's lists
into a new one is the worse mistake. Any switch drops the principal context
bound to the old id until the next turn supplies one. The lens is withdrawn
under its own lock, so a concurrent update cannot write the old one back.

With no lens for the session (none published, unreadable, or no session id),
the tool treats the session as a shared surface with no principal and no
writes, which reaches no identity-unbound record. `recall` then says so,
refusing with `session_lens_unavailable` and `lens_state: unbound` rather
than reporting that nothing matched, and `capture` and `demote` refuse with
the same reason. A file rather than an in-process
registry, because
Hermes loads the provider and the tools as separate module copies and may run
a user provider in its own host process.

Within the lens a record must pass the selector's principal, scope, and
Hermes-perspective gates, in that order. Lifecycle state (expired, stale,
superseded) is not a lens gate: each action refuses what it cannot act on. A
record that fails the lens is refused as `record_not_in_scope`, an unknown id
as `record_not_found`, and any write in a session whose provider disabled
writes as `writes_disabled` (`session_lens_unavailable` with no lens). None of
them writes anything.

| Action | Arguments | What it does | `status` values |
| --- | --- | --- | --- |
| `recall` | `query`, optional `limit` (1-6) | Runs the prefetch selector over the lens's homes, allowlist, and principal, so the order is the order a prefetch for that query serves. Returns record ids, summaries, types, tags, approval dates, and the subject when a record declares one. Counts no use; the returned ids join the session's seen list. | `found`, `nothing_found`, `refused`, `error` |
| `confirm` | `record_id` | `omh memory confirm`'s rewrite: the review deadline moves to the record's stored cadence (else the policy default, else 90 days), an open record is answered `resolved`, and `revalidation.confirmed_by` is `hermes_model`. Then one `used` count, at most once per record per session. A record with no review deadline (a durable capture) is not refused; only the use is counted. Expired, superseded, and source-changed records are refused like the operator verb. | `confirmed`, `refused`, `error` |
| `correct` | `record_id`, `summary`, optional `tags`, optional `subject` | Admits the corrected fact through the model capture gates (instruction-shaped refusal, safety, relative-time review). The new record keeps the old record's type, scope, retention, perspective, cited source, review cadence day count, TTL day count, subject, and tags unless new tags or a new subject are given. The candidate carries `derived_from: [<old id>]`, `correction_of: <old id>`, and `correction_of_revision`, the revision the model read. Whichever approval admits it supersedes the old record inside its store lock: auto-safe at once, or an operator's `omh memory approve` later. If the old record was rewritten to another revision in between, nothing is superseded and the approval reports `revision_moved`. The old revision moves to `history/<record-id>.r<revision>.json` with `superseded_by`, leaves `records/`, and its source candidate becomes `superseded`, which approval refuses. Until then the old record stays active. When the corrected summary is already held as another record in the old record's scope and principal, which is what happens after a capture hint, that record is the replacement, if it can stand in: it must recall under the session's lens now (eligible, not archived, not itself replaced by a newer subject value), keep the fact at least as long (retention class and expiry), and not declare a different subject than the correction carries. Then the old revision moves to history with `superseded_by` naming it, under the store lock and pinned to the revision read; the correction's subject is written onto the held record when it has none; the result says `replacement: already_held`; and nothing new is captured. Otherwise nothing changes, and the result is `already_remembered` with `supersede_skipped` naming why (`held_not_recallable`, `held_retention_shorter`, `held_expires_sooner`, `subject_conflict`, `record_absent`, or a supersession skip such as `revision_moved`). | `corrected`, `pending_review`, `already_remembered`, `refused`, `error` |
| `retire` | `record_id`, `reason` (`no_longer_true`, `superseded`, `user_asked`) | `omh memory retire --apply`'s move for one record: `records/` to `archive/<record-id>.<stamp>.json`, a `retirements.jsonl` line carrying the reason, `retired_by: hermes_model`, and the `session_id`, and the source candidate flipped to `retired`. Never a delete; `omh memory restore` finds the archived revision and brings it back through review. Unlike the operator verb it may retire a record that has not expired, but only one this session was served or recalled; an unseen live record is refused as `record_not_seen_this_session`. That rule is not a defence against a model told to retire something, since a recall adds the id. What it guarantees is narrower: no blind retire of an id the conversation never saw, attribution to the session in the journal, and an archive that can always be restored. If a step after the archive move fails, the result says the record was archived. | `retired`, `refused`, `error` |

`correct` and `retire` return a suggested `display_line` (`✏️ OMH corrected:
…`, `🗄️ OMH retired: …`); the model tells the user in one short line in its
own voice and language. Writes take the same store lock capture and approval
take.

Two deliberate differences from the operator `correct`:

- The corrected fact is a new record id rather than revision N+1 of the old
  one, because it goes through capture admission.
- A correction held for review leaves the old record recallable rather than
  removing it at once, so a pending correction never makes the fact vanish.

`correction_of` is honoured only on a `hermes_model` candidate. `derived_from`
alone never supersedes anything; a rollup derives from records it must not
replace.

The policy payload discloses `mode_source`. Setup records `explicit` only when
the operator passed `--memory-mode`; anything else is `default` and follows
the current default. A profile written before `mode_source` existed that
stored `review-first` (the old default) is read as defaulted, so it becomes
`auto-safe` on the next read without re-running setup; any other stored mode
could only have been chosen and is kept as `legacy_explicit`. `off` and an
explicit `review-first` keep working.

## Admission: Remember, Refuse, or Defer

For a new fact, Hermes decides source class, target store, canonical scope,
retention class, and one of these outcomes:

- **Remember** captures one bounded **durable** candidate through
  `omh_memory(action="capture")`. Under the default `auto-safe` policy a safe
  candidate is approved in the same operation (`approved_auto_safe`, a local
  policy result, not a human review). It stays pending review only when the
  content is unsafe, carries a relative-time phrase, duplicates a live record
  outside the tool path, is derived content, or the operator chose
  `review-first`.
- **Refuse** covers secrets, raw logs, transcripts, prompt-injection-shaped
  instructions, and temporary task progress. This is lane guidance, not a
  pattern verdict: `classify_memory_admission` screens protected values, and
  the log/transcript shape is matched by the domain-vocabulary gate in
  `src/workflows/domain_intelligence_admission.py`.
- **Retrieve instead** covers past-session history. What happened in an earlier
  conversation stays in Hermes' own session store and is recalled on demand
  through its native session-search tool when that tool is available. Memory
  carries what is worth re-reading every turn, because every retained record is
  context each later turn pays for.
- **Defer** sends uncertain source, scope, target, retention, and external
  provider/vector material to review rather than retaining it.

Hermes-native and external provider/vector context is `not_omh_reviewed`. It
may nominate a candidate but never inherits OMH admission. OMH-local processing
does not promise no egress: a configured Hermes runtime may transmit rendered
OMH prefetch content in its model request.

## Retention and Replay

Retention is additive to record type:

| Class | Rule |
| --- | --- |
| `volatile` | Explicit only; admission starts its 1-7 day TTL, defaulting to seven days. It is ineligible at the exact UTC expiry boundary. |
| `standard` | Preserves current type behavior. An `episode` defaults to 30 days; other records keep explicit TTL/staleness behavior. |
| `durable` | Has no TTL. It receives a revalidation deadline only when explicitly configured. |

Expiry removes influence only; it does not move an artifact or prove any
absence. A stale revalidation deadline requires fresh review or a bounded,
identity-specific confirmation.

A reviewer can re-class a record at approval:
`omh memory approve <candidate-id> --retention-class durable` promotes a
settled decision so it does not inherit the default review clock nobody chose
for it. The override re-derives retention and a *defaulted* review deadline
with the new class's own rules — but a cadence the captor explicitly chose
(`--stale-after-days` at capture, recorded as `cadence_source: explicit`)
survives the re-class: durable makes the deadline optional, not forbidden,
and a flag about retention never silently removes a review date the reviewer
saw on the card. Supplying the class the candidate already has is a
validated no-op. Lifecycle (correction/restore) candidates keep their
reviewed class; the flag applies to plain approvals only.

### Cadence Tunables

The three memory clocks are policy tunables, not baked-in constants. A stored
setup profile's `memory_policy` block may carry, additively and optionally:

| Field | Default | Meaning |
| --- | --- | --- |
| `stale_after_days_default` | 90 | Review cadence minted for fact/decision/lesson/procedure captures without an explicit `--stale-after-days`. |
| `episode_ttl_days` | 30 | TTL minted for episode captures without an explicit `--ttl-days`. |
| `due_soon_days` | 14 | Advance-notice window recall packs warn inside, shared by review-due and expiry notices; accepted range 1–365. |
| `open_max_days` | 365 | Open ceiling for a record marked `--unresolved`: `open_since` plus this many days is `staleness.open_expires_at`, past which the question is `expired/unresolved_expired`. Durable records carry no ceiling. |
| `open_ask_days` | 14 | How often the provider may ask about the same open record after its review deadline passes; `omh memory keep-open` resets the clock. Accepted range 1–365. |

An absent or invalid value falls back to the named default, and the effective
values are always disclosed on the `project_memory_policy/v1` payload, so
`omh memory status` shows what is actually in force. A capture's cadence
(explicit or default) is stored on the record and honoured by later flagless
`omh memory confirm` runs.

### Durability Receipts

"Written" is not one event. A memory operation reports exactly which of four
receipt states it reached, and it names that state rather than implying a
later one:

| State | Meaning |
| --- | --- |
| `candidate_persisted` | The bounded candidate is on local disk under the candidate path. It is pending review and carries no replay eligibility. |
| `approved_record_persisted` | The approved record and its review linkage are on local disk under the approved path, after an OMH-local approval decision. |
| `indexes_refreshed` | The local index, link journal, and counter references that address the record agree with the persisted record. |
| `replay_ready` | The record satisfies scope, perspective, retention, and freshness gates, so a recall pack may include it. |

Each state names disk or index facts the operation itself observed, never
work it handed to something else. A queued, buffered, staged, or in-flight
write is not `candidate_persisted`, an approval decision without its record
write is not `approved_record_persisted`, and a persisted record whose index
references were not refreshed is neither `indexes_refreshed` nor
`replay_ready`. Reaching one state never asserts the states above it: a
candidate that never clears review stops at `candidate_persisted`, and an
approved record that is expired, stale, or out of scope stops short of
`replay_ready`.

`omh memory capture` prints the receipt it reached as `receipt_state`, each
step re-read from disk: the record file, then the index entry that addresses
it, then the same replay evaluator recall uses. A held candidate stops at
`candidate_persisted`; `--on-duplicate skip` and refused captures print
`null` because nothing was persisted. The `omh_memory` tool relays that value
unchanged and never upgrades it.

States are receipts, not record states. They describe what one operation
observed about persistence, so they carry no lifecycle authority: they cannot
approve, expire, retire, or revive anything, and they are not execution,
review, CI, merge, or Hermes internal-memory evidence. An operation that
cannot confirm a state says so and names the state it did reach, which is what
keeps a partial write readable as partial instead of silently reported as
durable.

## Freshness: Review-Due Dates and Source Evidence

A record's freshness is one verdict derived from four stored inputs plus the
caller's clock. Nothing is inferred from conversation, and nothing is fetched.

| Input | Field | Effect |
| --- | --- | --- |
| Retention deadline | `ttl.expires_at` | Past it, the record is `expired`. |
| Review-due date | `staleness.review_due_at` | Past it, the record is `stale` — unless it is open, then it is `open`. |
| Source digest | `source_evidence.sha256` | A changed source is `stale`; an unreadable one is `unknown`. |
| Open marker | `staleness.resolution` | `open` (set by a person) keeps the record delivered past its review deadline as `open · N days unresolved`; `resolved` is written only by confirm or correct. |
| Open ceiling | `staleness.open_expires_at` | `open_since` + `open_max_days` (default 365). Past it an open record is `expired` with reason `unresolved_expired`: a question that died unanswered, not a fact that aged out. Absent on durable records. |

`review_due_at` is the readable name for the date `staleness.stale_after`
always held; both are written, and when they disagree the earlier one wins, so
editing one spelling can never restore freshness.

The verdict is decided in this order: a passed retention TTL is `expired`;
a passed open ceiling is `expired/unresolved_expired`; a passed review
deadline on a record that is *not* open is `stale/review_due`; a changed
source is `stale/source_changed` and an unreadable one `unknown`, because
evidence that moved is not the same as an answer that has not arrived; only
then is a passed review deadline on an open record `open/unresolved`. A
record that is not open gets exactly the verdict it always got.

An open record is a marker a person sets, never a state OMH infers from
content: `omh memory capture --unresolved` starts the clock at capture and
`omh memory approve <id> --unresolved` starts it at approval; the candidate
carries `unresolved: true` and the review card shows the review deadline and
the ceiling the record will expire under. An open record always carries a
review deadline, even a durable record or an episode, which mint none on
their own: "unresolved" means "needs an answer by then", and without a
deadline the record could never reach `open`, never be asked about, and
never be answered. The default cadence is minted (marked `cadence_source:
default`) whenever the record would otherwise have none, and a durable
re-class at approval keeps the deadline the card showed. Every verdict now
also reports `resolution` (`open`,
`resolved`, or empty) and `open_days`, the whole days since `open_since`
while the record is open (0 otherwise). Nothing promotes an open record to a
settled fact on a timeout: it stays `open`, delivered with its age, until a
person answers.

Deadlines can be given as absolute dates, not only day counts:
`--stale-after YYYY-MM-DD` (review deadline) and `--expires-at YYYY-MM-DD`
(retention expiry) accept a bare date — meaning the **start** of that UTC day,
the conservative reading — or a full ISO timestamp. Each is mutually
exclusive with its day-count twin, past dates are refused at capture, and the
class rules mirror the day-count gates (volatile keeps its 1–7 day TTL;
durable cannot set `expires_at`). An absolute review date counts as an
explicit cadence, so it survives an approval-time re-class.

Relative-time **prose** is the opposite case and capture lints it: a summary
like "계약 만료는 3주 뒤" or "renew in 3 weeks" is a fact with a hidden expiry —
its anchor (the moment of writing) is not part of the stored content, so it
reads wrong once time passes. Detection is a tight deterministic pattern
(number-plus-unit or an unambiguous deictic word; bare "후/전" never match)
and only **forces review** — never blocks, never auto-rewrites — with the
candidate carrying a `time_sensitivity` verdict telling the reviewer to
restate the fact with an absolute date or set the deadline structurally. The
verdict is a capture gate, not record metadata: it rides the candidate and
the review card, and deliberately does not survive onto the approved record.

Source evidence is opt-in and local. When `--source-ref` names an absolute
path to a readable local file, capture records the file's SHA-256 alongside it.
Every later freshness check re-reads that file and compares. A ref that is not
an absolute path, a file that is gone or unreadable, and a file past the
digest budget all read as `unknown` — never as `fresh`. The freshness check
makes no network call, and never rewrites or deletes a record because its
source moved.

Both `stale` and `unknown` are ineligible for default recall, exactly like
`expired`. `omh memory recall --include-stale` surfaces them for inspection
carrying their ineligible replay evidence, which keeps the pack unattachable
as approved context. `open` is the exception by design: an open record past
its review deadline stays eligible and is delivered with `resolution: open`,
a `resolution_marker` of `open · N days unresolved`, and one
`unresolved_delivered` count per pack — never a banner per record. Ranking
is unchanged, so an old open question sinks through the age tiers but never
vanishes. `unresolved_expired` is terminal like `expired`: it leaves default
recall and `--include-stale` does not bring it back.

### Freshness Warnings

A recall pack used to drop an ineligible record silently. It now carries a
bounded `freshness_warnings` list naming every record whose freshness is not
confirmed, and a handoff pack is emitted even when the warning is all it has
to say:

```json
{
  "record_id": "mem_...",
  "state": "stale",
  "reason_code": "stale_review_required",
  "review_due_at": "2026-01-01T00:00:00Z",
  "detail": "Its revalidation deadline passed, so nobody has confirmed the record since then.",
  "delivered": false,
  "next_action": "Confirm, replace, or retire this record before it steers the plan."
}
```

`delivered` says whether the record reached the pack (`--include-stale`) or
was held back. Records excluded for reasons that are not about freshness —
`no_query_overlap`, `over_budget` on a fresh record — never warn. Wrapper
briefs and runtime artifact summaries carry the warnings through by name
rather than as a count, so a summarized handoff still says which record needs
a decision. A warning is prepared context, never execution, review, CI, or
merge evidence.

The warning also fires *before* the cliff: for the last 14 days (the
`due_soon_days` tunable) before a record's review deadline, packs still
deliver it normally but carry a `review_due_soon` warning naming the deadline;
inside the same window before a retention TTL ends, the warning is
`expires_soon` — the retention twin, pointing out that confirmation cannot
extend a TTL and the honest moves are a re-capture, a correction, or letting
it expire. The expiry window scales down to half the record's own TTL (never
below one day), so a short-lived volatile record warns near its end instead
of carrying a permanent banner from the day it was approved. Expiry outranks
review-due when both windows overlap: a passed TTL is terminal, a passed
review date is not. Only delivered records earn advance
notice — it is a statement about this pack's own content, not a store-wide
page — advisory notices never displace blocking warnings inside the bounded
list, and once a deadline actually passes, the ordinary blocking warning
covers held-back records as before.

An open record adds one advisory and one blocking reason. A delivered open
record past its review deadline warns `unresolved_open` (`state: open`,
`delivered: true`), whose `next_action` names the three answers — confirm
(resolved), keep-open (still open), retire (drop it) — and which, like every
advisory, never counts toward a wrapper's freshness-warning total. A record
past its open ceiling warns `unresolved_expired` as a held-back blocking
warning whose detail says the question died unanswered.

### Confirming, Correcting, or Retiring

These are the operator verbs. In chat the model answers through
`omh_memory(action="confirm" | "correct" | "retire")` with no operator step;
see The model-driven loop for where its semantics differ. Answering the
warning uses three verbs. `omh memory confirm <record-id>` is
the lightweight one: it states the record is still true and resets its review
deadline (default 90 days ahead, `--stale-after-days N`, or an absolute
`--stale-after YYYY-MM-DD` for a date-pinned record), rewriting only
revalidation metadata — the payload digest deliberately excludes it, so the
record's identity, admission, and immutable review record are untouched.
`omh memory confirm --all-due` confirms every record whose sole problem is a
passed deadline; each record still passes the single-record gates, so the
batch reports superseded or source-changed records as skipped with their
refusal reason and detail rather than silently re-blessing them. Expired
records never enter the batch at all — their verdict is `retention_expired`,
not `review_due`, and the fix is `omh memory retire`. Confirmation never
resurrects an expired record and never overrides the source-evidence gate —
a record whose cited source changed needs a correction, because a new
deadline would not restore its eligibility anyway.

The heavier verbs are unchanged: `omh memory correct` supersedes the record
with a reviewable replacement, `omh memory retire` archives it once expired.
Both preserve the prior revision — a correction writes
`history/<record-id>.r<revision>.json` carrying the original payload, its
admission provenance, its source evidence, and a `superseded_by` link to the
successor revision.

An open record has exactly three answers, and they are the same verbs plus
one. `omh memory confirm <record-id>` is "resolved": it resets the review
deadline as usual and writes `staleness.resolution: resolved` with a
`resolved_at`, dropping the open ceiling — and it succeeds on an open record
that carries no deadline at all (one restored from the archive, or written
before open records always minted one), resolving it without minting a clock
nobody asked for unless `--stale-after` / `--stale-after-days` states one;
the `no_review_deadline` refusal stays for records that are not open.
`omh memory correct` is the same
answer with a different fact — the replacement carries `resolved`, the
superseded history keeps `open`. `omh memory keep-open <record-id>` is
"still open": it records the answer in the local ask ledger so the provider
stops asking for another `open_ask_days`, and it writes nothing to the
record — same state, same deadline, same ceiling; it refuses `not_open` for
a record that is not marked unresolved and `unresolved_expired` for one past
its ceiling. `omh memory retire <record-id>` is "drop it": with a record id
the retire report narrows to that record and nominates an open one as
`unresolved_dropped` even before it expires, while a settled live record is
refused as `not_expired`. Without an id, the sweep nominates ceiling-expired
open records as `unresolved_expired` beside the ordinary `retention_expired`
rows, and the archive journal carries the reason. Nothing else clears the
marker: `confirm --all-due` leaves open records untouched and counts them as
`open_count`, no reminder writes a record, and no timeout resolves one.
`omh memory status` reports `counts.unresolved` and a bounded `open_records`
list (oldest first, at most 20: record id, summary, `open_days`,
`open_since`, `open_expires_at`, `review_due_at`, `state`, `last_asked_at`),
and `omh doctor` warns — never fails — when an open record has been open for
more than half of `open_max_days`.

## Recall Ranking and Delivery Usage

Recall packs order eligible records relevance-first: the relevance rank
(query-term coverage, then term frequency and length) is the primary sort key, and deterministic
reciprocal rank fusion over
relevance, recency (`approved_at`), and delivery usage orders records that
share a relevance rank. A weaker keyword match can never
displace a stronger one, including across the budget cut; without a query all
relevance ties and recency plus usage decide the order. Each included record
carries a `ranking` block with its per-signal ranks and an integer
`rrf_score_micro`, so the order is always explainable from the pack itself.
The usage signal ranks on saturating buckets (0, 1-2, 3-9, 10+ deliveries) so
delivery counts cannot compound into a permanent head start.

Relevance is computed against the eligible candidates of that one selection,
so the average summary length comes from the store being recalled from and
the same store and query always score the same. It has two keys:

- Coverage comes first. It is twice the number of distinct content terms a
  record matches in its summary or tags, plus one for each matched term that
  is one of its tags (the old overlap scorer's shape, without the record
  type). The ranking block reports `coverage`.
- Within one coverage, the score is BM25F (k1 1.2, b 0.75) without idf: how
  often the query's terms occur, saturating, in a summary normalized for
  length, with tag hits weighted up. Records whose words tie at one coverage
  share a relevance rank, and recency and usage decide them, as they did
  before this scorer.
- There is no rarity weight. Rarity is unbounded: in a store of statements,
  any chat word the lists below miss is held by one record and outweighs a
  topic word several records share. With idf inside a coverage band, the
  review's blind probes ranked "어케 해야 할지 모르면 위키를 먼저 본다" above
  every deploy record for "배포 어케 해" (both cover one term, and 어케 was
  the rarer), and the same happened in Chinese. Removing idf moved no case in
  the recall corpus or either holdout.
- The query is split into content words and listed words. The lists are
  closed and only the query is split; records keep every word:
  - English interrogatives, auxiliaries, pronouns, articles and common
    prepositions (`_QUERY_FUNCTION_WORDS`);
  - chat fillers such as remind, quick, question, anyone, tell and know, and
    hedges and intensifiers such as honestly, literally, basically, actually,
    kinda and really (`_QUERY_CHAT_FILLERS`);
  - Korean bare verb endings, colloquial and discourse fillers (어케, 어캐,
    어떡해, 혹시, 그냥, 근데, 일단), intensifiers and hedges (진짜, 정말, 완전,
    약간, 아마), and demonstratives (그거, 이게) matched as whole runs
    (`_QUERY_FUNCTION_RUNS`);
  - any Korean run that starts with an interrogative (언제, 어떻게, 누가, 누구,
    어디, 뭐, 무슨, 몇, 왜) or with the stem of "tell me" or "teach me" (알려,
    가르쳐; `_QUERY_FUNCTION_RUN_PREFIXES`), so 언제쯤이야, 누가요 and
    알려주세요 go too;
  - the particles and request or verb endings a Korean run ends in (은, 는,
    이, 가, 으로, 에서, 이면, 인지 ...; 해, 해줘, 주세요, 해야, 하면, 돼, 됨 ...;
    `_QUERY_KOREAN_SUFFIXES`). The longest listed suffix comes off, again
    and again, while at least two syllables stay, and the query scores the
    stem: 자동으로 as 자동, 확인해주세요 as 확인, while 경로 and 평가 stay
    whole. A run that is one of them whole (해주세요, or 에서 in "main에서")
    leaves nothing, and a stem that is itself a filler goes too (진짜로). The
    stem's bigrams are a subset of the run's, so within the run the strip
    adds no match: it moves the inflected run, the bigram that crosses into
    the suffix and the suffix's own bigrams from coverage to ordering. The
    suffixes are spelled, not parsed, so a noun of three or more syllables
    that ends in a listed syllable is cut too (재시도 scores as 재시, 게이트웨이
    as 게이트웨, 응답속도 as 응답속, each losing its last bigram and its whole
    run to ordering), and a run that reduces to a stem which is itself a
    listed suffix leaves nothing (인지도, like 해야돼; 인지 alone goes the
    same way);
  - Japanese and Chinese interrogatives, request fillers and wrappers (どう,
    何, いつ, 誰, すれば, ですか, いい, 教えて, ください, って, なってる, 怎么, 什么,
    什么时候, 谁, 请问, 一下, 怎么弄, 搞, 一般, 通常 ...; `_QUERY_FUNCTION_CJK`),
    cut out of a run before it is split into bigrams, so
    "デプロイってどうすればいいですか" adds no coverage from its request words.

  Listed words never make a record match and never add coverage: "how do we
  deploy?" once ranked "How expenses are filed ..." above every deploy record.
  They do order records of equal coverage, so "is there a quick start?",
  whose only content word is "start", serves "Quick start guide ..." above
  "Standups start at 9:30". A listed word is content again when the raw query
  writes it all in capitals or capitalized mid-sentence ("WHO?", "ask Will",
  "CAN logger"; the check reads the raw string before lowercasing), and every
  listed word is content when no content word longer than two Latin letters is
  left: "what is it?" is scored on "what", and "where do thanks go?" on
  "thanks" as well as "go". A two-character CJK word counts as a word there,
  and so does a two-letter word written in capitals (PR, CI, DB, but not the
  interjections OK, HI, PS), which the same case rule reads as a name: "what
  about CI" is scored on CI. The Korean suffix strip never causes the
  fallback: when the stripped content collapses, the content without the
  strip is tried first, so "pr 어떻게 해야돼" keeps 해야돼 as content, as
  before the strip, and 어떻게 stays listed.
  A word not listed is content, and that is what coverage and the missing idf
  are for.
- How the pieces were chosen, by measurement against the old scorer on the
  pre-registered corpus, both holdouts and the review's blind set with its
  tie-flip twin:
  - Coverage first was chosen on holdout-2: with the earlier lists, coverage
    alone fixed the English cases but not the Korean, Japanese or Chinese
    ones, and with the lists and no coverage the Japanese case still put
    "どうやるのか分からない時は..." above the deploy record.
  - Dropping idf inside the band is what holds the blind set without the
    Korean and the Japanese/Chinese additions above: with idf back in the band
    and those additions removed, four blind cases rank a distractor strictly
    first where the old scorer tied; without idf and without the additions,
    none does.
  - Listed words ordering within a band is what serves the quick start guide;
    without it, standups and the guide tie and the record id decides.
  - The Korean suffixes, the colloquial fillers in all four languages and the
    Japanese and Chinese wrappers were measured against the scorer before
    them on the pre-registered corpus and on the round-3 and round-4 blind
    sets with their tie-flip twins. The pre-registered corpus served the same
    packs; round 3 kept every verdict (one pack stopped serving a distractor
    that matched only "basically"); round 4 gained five cases and its
    tie-flip twin four; no case in those sets lost. Those sets were seen
    while writing the change. Two later rounds were frozen by a writer who
    never saw the code (24 owner-style cases each): 2 wins, 21 ties, 1 loss,
    and 2 wins, 22 ties, 0 losses. The loss is a query whose topic record
    shared the particle form (모델로) that now only orders records. Two
    round-4 cases stay wrong: 피알 for PR is a transliteration no list covers,
    and a request verb (확인) is a word, so "확인좀 해주세요 PR" ties the PR
    record with a record about 확인 and the record id decides.
- There are three fields. A summary hit is the unit and a tag hit weighs 2;
  the weighted counts saturate together, so a word in both the summary and a
  tag outranks a tag-only hit, which outranks a summary-only hit. The record
  type weighs like one summary word, but only in a record that also has a
  summary or tag hit: a type is a category, so "any facts about deploys?"
  does not pull in every fact record.
- Summary length is counted in whole multiples of the candidates' average,
  never below one, rather than as a continuous ratio. Two near-average records
  that cover the same query terms therefore tie, and recency and usage still
  decide them. A record at least twice the average is discounted, so a long
  checklist that mentions a word once ranks below the short record about it.
  The step is a cliff: a record at 1.99 times the average is not discounted,
  and adding short records lowers the average and can push a long record
  across it. CJK summaries count their runs and bigrams, so they read longer
  than English ones of the same meaning. Both effects only reorder records
  whose other evidence ties.
- Each term's contribution is rounded to integer millionths before it is
  added and the score is stored as integer thousandths, so ties are exact and
  the total cannot depend on summation order, the hash seed or the host's
  float rounding.
- A temporal query (see Recall signal refinements) ranks relevance in four
  bands below the best score of the same coverage instead of on raw scores,
  so records within a quarter of the best compete on recency (weighted up for
  that query). Score
  thousandths are nearly a total order, and without the bands "what did we
  decide recently about deploy windows" served the older decision first
  because it repeated "deploy".

Tokens are the same ASCII words, two-letter terms, CJK runs with character
bigrams, and accent-folded Latin words as before. Each all-ASCII-letter token
of four or more letters is then lightly stemmed, the same way for the query
and the records: one plural rule, at most one of -ment, -ing, -ion, -ed and
-ly, then a final e. Deploy, deploys, deployed, deploying and deployment all
meet, as do cache, caches and caching. A suffix comes off only when it leaves
a stem with a vowel and a minimum length, which keeps string, thing, apply,
reply and region whole. CJK runs, accented words, numbers, paths, and
hyphenated or underscored compounds are never stemmed. It is a stemmer, not a
dictionary: state, stats, station and statement all read as "stat", likely as
like, evening as even, news as new.

So a match made only by stemming is weaker evidence. It counts as overlap
only when some live candidate in the same selection also shares an unstemmed
query token in its summary or tags. When none does, the query met the store
only through a suffix rule, and it falls back to the active tier exactly as a
query that matches nothing does. The stemmed matches keep their scores, so
they lead that fallback pack, and `query_fallback` is set. "stats location?"
therefore serves every active record with "State is kept in a Redux store"
first, rather than serving it alone. When some record does share an unstemmed
word, stemmed matches count normally: "new hire onboarding" still serves the
release-news record after "New hires ...", and the recall suite pins that
cost. A relevance score of 0 means no content term matched, or only
store-common ones did (below), and any other match scores at least 1.

A query term that most of the records the pack could serve hold is
store-common, and it never makes a record match on its own. Those records are
the selection's eligible candidates minus the values a subject's current
record replaced (below) and the stale records `--include-stale` surfaces only
for inspection, with records whose summaries are equal after normalization
counted once, since the pack keeps one of them; a subject's history or copies
of one record never make their own words common. A term is common when more
than half of those records hold it in their summary or tags, counted in the
same index terms the ranker matches on (stemmed words and CJK bigrams), and
only when there are at least five of them. Exactly half is not common, and
below five the rule is off. In a store about one project, the project's name
is in most records, and a task that named the project matched every one of
them on that word alone, so the tie-breaks decided which of them filled the
pack. A common term is scored like a listed word: it makes no match and adds
no coverage, but it still orders records of equal coverage. Two exceptions
keep it:

- A record that carries the term as a tag still matches on it, because a tag
  is the captor's label for the topic.
- When every content term of the query is common, nothing is demoted: a store
  whose records all say "release" still answers "release" with them.

The second exception reads the closed lists, so it depends on the query's
other words. In a store where most records name the project 탈리, "탈리 알려줘"
keeps them, because 알려줘 is a listed request word and 탈리 is the only
content term; "탈리에 대해" serves none of them, because 대해 is not listed,
so 탈리 is common beside it. A question whose other words are not on the
closed lists therefore gets none of the records it meets only on the
project's name; a record that carries the name as a tag still matches.

A record whose only matches are common terms is excluded as
`common_terms_only`, unless it is a subject's current value and an older
value matched another query word (below). It keeps its unstemmed flag for the
stemmed-only rule above, so in a store where most records name the team, "team
backup" still reaches "Backups rotate weekly" through stemming: the team
records share the query's unstemmed word even though they cannot match on it.
This is not idf. No term gains weight for being rare; a majority term only
loses the power to match by itself. Like `no_query_overlap`,
`common_terms_only` is a relevance cut and not an eligibility one, so the
`omh reminder:` line still asks about an open record held back that way.

A record can declare a `subject` (see The model-driven loop). Two records in
one scope that declare the same subject are two values of one thing. The
newest `approved_at` among every record still in the store that the lens
admits is current (the smaller record id on an equal stamp, `newest_record`).
That includes expired, stale and archived records, so an older value cannot
come back when the newest one lapses: the subject still says it was replaced,
and the topic simply has no servable value until it is confirmed, corrected
or restored. Each other eligible record is excluded as
`superseded_by_subject`, with `superseded_by` naming the current record and
`subject` naming the slug. The prefetch receipt lists those id pairs under
`selection.subject_superseded` (at most 16; the count in
`exclusion_reason_counts` is never cut).

The current record takes the best coverage and relevance score in its group
only when it shares a query term itself, a store-common one included. A query
worded like the old value still finds a current value that shares some of its
words, and that current value is then a match, not `common_terms_only`. A
current value that matches nothing is never pulled in on another record's
words, because two different facts given one slug by mistake must not serve
the unrelated one. The collapse reads two structured fields and never the
summaries. A record with no subject never joins a group, different scopes
never merge, and a pin does not hold an older value in place.

A query that matches nothing does not empty the pack. When a query has
indexable tokens and no eligible record overlaps it, not even on a
store-common term, and no pin applies, every `active`-tier record that was held
out as `no_query_overlap` is served the way an unqueried pack serves it —
relevance ties, recency and usage decide the order, and the normal budget cut
applies — and the pack carries
`query_fallback: {"mode": "active_tier", "reason": "no_query_overlap",
"readmitted_count": N}` (the key is absent when the fallback did not fire; the
prefetch receipt records it as `selection.query_fallback`, null otherwise).
Reference records stay keyword-gated and archived records stay explicit, so
they remain `no_query_overlap` / `archived_tier` exclusions. A partial match
never falls back. Overlap only on store-common terms is not a match, and it
does not fall back either: the records that met the query that way stay
`common_terms_only`, the rest stay `no_query_overlap`, and none is readmitted.
The query did meet the store, and the fallback would serve the records that do
not even share the common word. That needs some record the pack could serve to
share an unstemmed query token: when none does ("teams backup" against records
that say "team"), the common-word hits are stemmed-only as well, and the query
falls back under the stemmed-only rule, with the common-only records still held
back. Two eligible records whose summaries are equal after NFC, lowercasing
and whitespace collapse — the same normalization capture uses for
`duplicate_of` — take one slot: the pinned one, else the newest
`approved_at`, else the smaller record id stays, and the other is excluded as
`duplicate_record` with `duplicate_of` naming the record kept. The collapse
runs after eligibility and before ranking, so a duplicate never spends budget.

Two per-record counters exist, and only one of them is a ranking input:

| Counter | File | Counts | Read by the ranking |
| --- | --- | --- | --- |
| `used` (`times_recalled`) | `.omh/memory/usage.json` (`omh_memory_recall_usage/v1`) | A recall pack actually attached to a prepared handoff payload, and an `omh_memory(action="confirm")` by the model, at most once per record per session, in the store that holds the record | Yes, through the saturating usage buckets |
| `served` (`times_served`) | `.omh/memory/served.json` (`omh_memory_served/v1`), in the store that holds the record | A provider prefetch that returned a pack to Hermes: one count per record the pack rendered, once per render | Never |

`used` stays narrow on purpose. Building a pack is speculative, so a
delegation that ends without a handoff, or rejects the pack, counts nothing;
a CLI `omh memory recall` and the tool's `recall` action are inspections and
count nothing. In chat, `confirm` is how a record earns use: the model calls
it when a record proved true or useful. `served` is kept apart because the
ranking reading it would feed itself — a served record would rank higher and
be served again. A queued re-render that no prefetch returns is not a serve,
and one render returned to several API calls in a turn is one serve.

A missing or corrupt counter file reads as empty and never blocks recall;
both writers take the file's own lock for at most a second and drop the count
rather than wait longer, and a rewrite keeps any key in an entry it does not
own. Usage is a ranking hint plus a retirement-report annotation, never an
eligibility input. `omh memory status` reports both under `recall_usage`
(`used` and `served`, each with a record count, a total, and the ten highest
counts) with `ranking_reads: "used"` and `store`, the one store whose counters
it read: a project store and the user store each report their own.
Retirement reports annotate each expired or expiring row with `recall_usage`
so an operator can see whether a record was ever delivered before archiving
it. Lifecycle receipts list `recall_usage_counters` under their exclusions: a
prune deletes the manifest targets, not the delivery counters.

This ranking design is a deterministic reinterpretation of the hybrid-search
rank fusion and per-observation usage tracking popularized by memory servers
such as Honcho; OMH keeps the bookkeeping and drops the model calls.

## Recall Anchors, Age Tiers, and Duplicate Detection

Three bookkeeping ideas ported from Mnemosyne, deterministically:

**Pins** — mark an approved record as a recall anchor (at most 12 pins;
a pin never overrides expiry, scope, perspective, or review eligibility):

```sh
# Agent/operator only: anchor one reviewed record in every recall pack.
omh memory pin <record-id>

# Agent/operator only: remove the anchor marker.
omh memory unpin <record-id>
```

Pinned eligible records lead the pack and skip only the `no_query_overlap`
cut. Pins take priority within the recall budget rather than expanding it,
and at most `limit - 1` pinned slots (minimum one) lead a pack — further
pins compete as normal records, so a fully-used pin budget can never blank
query-driven recall. Pin markers live in `.omh/memory/pins.json`
(`omh_memory_pins/v1`), outside record payloads, so digests and review
linkage are untouched; retirement reports annotate rows with `pinned`,
lifecycle receipts list `pin_markers` under exclusions, and each ranking
block carries `pinned`.

**Age tiers** — the ranking's `decayed_score_micro` degrades with record
age (0-30 days full weight, 30-180 days half, older a quarter), reported as
`age_tier`; `rrf_score_micro` stays pure rank fusion so fusion quality
remains comparable across records. Relevance still leads the sort, so a
stale strong keyword match beats a fresh weak one; tiers only reorder
records of equal relevance.

**Duplicate detection** — capture compares the normalized summary (NFC,
lowercase, collapsed whitespace) against active records and stamps an exact
match as `duplicate_of` on the candidate and its review card. Review-first:
nothing is silently merged, the reviewer decides — but a duplicate never
auto-approves, even under the auto-safe policy. Wording that is only similar
is a hint on the capture result (`similar_record_id`), never a duplicate: see
The model-driven loop.

**Episode rollup** — additive consolidation without a model:

```sh
# Agent/operator only: report which records one episode would roll up.
omh memory rollup --tag deploy

# Agent/operator only: stage the reviewable episode candidate.
omh memory rollup --tag deploy --apply
```

The rollup selects up to 8 non-expired, non-episode records matching a tag
and/or scope (oldest first), and proposes one `episode` candidate whose
summary is a per-member-budgeted mechanical join — every member is
represented — and whose `derived_from` names every member; synthesis stays
Hermes' job. The episode inherits its members' confinement, strictest
wins: mixed scopes or mixed perspectives refuse (`mixed_scope` /
`mixed_perspective`), a shared perspective or scope carries onto the
episode, and any volatile member makes the episode volatile with the
smallest member TTL. Originals are never modified or retired by a rollup;
the candidate always lands in review (a derived aggregate never
auto-approves, even under the auto-safe policy), a re-run while an
identical candidate is pending reports `already_staged` instead of staging
twins, and `omh memory lineage` on the approved episode walks back to all
members.

**Recall signal refinements** — the ranking block reports
`veracity_weight_pct` (an `approved_manual` record weighs 100, an
`approved_auto_safe` record 90 in the decayed score — both classes stay
fully eligible), and packs echo `query_intent`: a query carrying an
unambiguous English time cue — the tokens `yesterday`, `today`, `recent`,
`recently`, `ago`, or a phrase such as `most recent` / `last week` — is
classified `temporal` and doubles the recency weight inside rank fusion.
Ambiguous engineering adjectives (`current`, `latest`, `now`, `newest`)
deliberately do not fire as bare tokens. Relevance stays the primary sort
key in both cases, so neither signal can change which keyword matches win —
only how peers of equal relevance order.

## Attention Tiers: Active, Reference, Archive

Approved memory grows, and an old but still-true record can crowd out the few
facts that should steer the current conversation. Every approved record
therefore carries an explicit attention tier saying how much of the working
context it may occupy. The tier says nothing about whether the record is true,
approved, or fresh — expiry, scope, perspective, and review eligibility are
unchanged by it.

| Tier | Effect on recall |
| --- | --- |
| `active` | Leads the working context. The default for every approved record. |
| `reference` | Stays recallable, but yields to active peers inside the same budget. |
| `archive` | Leaves default recall. The record stays in the store and answers an explicit archived query. |

The tier enters the one existing ranking ladder, which now reads: pinned
anchors, then attention tier, then relevance rank, then the decayed fused
score, then record id. A reference record therefore ranks below every active
record of the same pin status, and there is no second ordering mechanism to
keep in sync. Each included record reports its `attention_tier`, and its
`ranking` block reports the integer `attention_rank` used for the sort. The
fused score itself is untouched, so a tier change reorders a pack without
rewriting the relevance evidence that explains it.

Every pack carries an `attention` block disclosing what it is made of:

```json
{
  "active_included": 2,
  "reference_included": 1,
  "archived_included": 0,
  "archived_excluded": 1,
  "include_archived": false,
  "detail": "2 active record(s) lead this working context. 1 reference-tier record(s) are included behind them. 1 archived record(s) stayed out of the working context; they remain in the store and are listed as archived_tier exclusions."
}
```

A tier change is previewed before it is applied, and the preview writes
nothing:

```sh
# Agent/operator only: preview what the tier change does to the working context.
omh memory attention <record-id> --tier reference

# Agent/operator only: apply the previewed change and journal the prior tier.
omh memory attention <record-id> --tier archive --reason "superseded by the canary policy" --apply

# Agent/operator only: query the archive explicitly.
omh memory recall "deploys" --include-archived
```

The preview projects the working context twice — as it stands, and with the
requested tier substituted — through the same recall builder, so
`working_context_after` is the pack the operator actually gets rather than a
description of one. It also names `leaving_working_context` and
`entering_working_context` by record id. Pass `--query` to preview against the
task text the change is meant to affect. A change that would be a no-op is
refused as `tier_unchanged`, so every journal line is a real move, and a
missing record is refused as `record_not_found` with a readable reason.

Applied changes write `attention` on the record (tier, bounded reason, prior
tier, change timestamp) and append one `omh_memory_attention_journal/v1` line
to `.omh/memory/attention.jsonl`. The prior tier is recorded in both places, so
an archive is always reversible from local evidence alone. The tier lives
outside the reviewed payload digest, so changing it never breaks a record's
immutable review linkage — and corrections and restores carry the tier onto the
successor revision instead of silently returning an archived record to the
active set.

**Archive the tier is not retirement the lifecycle verb.** Archiving moves no
file: the record stays in `records/`, stays readable, stays valid, and is
listed in every pack as an `archived_tier` exclusion rather than vanishing from
it. Retirement moves an expired revision into `.omh/memory/archive/` and writes
a tombstone. The tier is also not an exemption: an expired archive-tier record
still retires on the normal schedule. Neither operation is a deletion.

This is Letta's context hierarchy read deterministically: OMH keeps the
explicit tiers and the disclosure, and drops the model-side judgement about
what deserves attention.

## Provenance and Lineage

A capture may declare which approved records a new fact was derived from:

```sh
# Agent/operator only: capture a conclusion with explicit provenance links.
omh memory capture "Always purge cache before deploy" --derived-from <record-id>

# Agent/operator only: trace where a record came from and what built on it.
omh memory lineage <record-id>
omh memory lineage <record-id> --depth 5
```

`--derived-from` is repeatable (at most 8 refs) and every ref must name an
existing approved record at capture time. The lineage report
(`omh_memory_lineage/v1`) walks ancestors and descendants breadth-first up to
`--depth` hops (clamped to 1-10), cuts cycles, and marks deeper unexplored
links as `truncated`. A parent that was later retired or pruned appears under
`unresolved_refs` rather than failing the report. Recall items expose each
record's `derived_from` list so an executor can ask for lineage when a
summary alone is not enough. Lineage is prepared-context traversal only; it
never claims the derivation itself was re-verified.

### Origin pointer

OMH stores one bounded summary line per memory and no transcript. Hermes
already keeps every message verbatim in `<HERMES_HOME>/state.db`. So a
model capture through `omh_memory(action="capture")` records only the session
it was made in, as `source_ref = "hermes-session:<session_id>"`; an unusable
session id leaves `source_ref` empty. Correcting a record keeps its ref.

When `omh_memory recall` returns such a record on a surface that admitted it
(operator console, owner direct message, bound direct message or channel),
the row carries `origin = {"session_id", "around_message_id"}`: the newest
user message of that session stamped no later than the capture. The model can
open it with `session_search(session_id, around_message_id)` to quote the
person's own words, and `next_action` says so. A shared or background lens
gets no origin. The lookup is a read-only open of `state.db` with a short busy
timeout and one `SELECT` of an id; a missing, corrupt or locked store gives no
origin and recall still succeeds. No message text is read into OMH.

## Source Recovery: Which Records Came From One Source

Lineage answers "where did this record come from". The reverse question --
"which records came from this source" -- is what recovery from a poisoned,
wrong, or no-longer-trusted source starts with, because `lineage`, `retire`,
`prune`, and `correct` all take a record id that must already be known.

```sh
# Agent/operator only: every source label in the store, with record counts.
omh memory sources

# Agent/operator only: the records admitted from one source.
omh memory sources --source wiki-scrape
```

The report (`memory_source_index/v1`) is a read: it quarantines, retires, and
deletes nothing. Two record fields are source axes and one record can carry
both -- `source`, the admission channel recorded at capture, and `source_ref`,
the document, ticket, or URL the memory was taken from. A record is indexed
under every label it carries, so a record admitted from two sources appears
under both, and one whose two axes name the same value reports both axes under
`matched_axes` rather than only the first. `source_class` is deliberately not
an axis: it is a four-value governance classification and every directly
captured record is `omh_local`, so indexing it would produce one label matching
most of the store.

A record that recorded no source at all is listed under `indeterminate` with
reason `source_not_recorded`, never quietly excluded -- this selector cannot
call it clean. A record file that would not parse is listed beside it. An empty
selection carries its reason in `selected.outcome`, because the three ways to
match nothing are three different answers: `empty_store`,
`source_never_recorded` (records exist and none recorded a source, so nothing
can be excluded), and `no_records_for_source` (sources are recorded and this
one is not among them -- the only outcome meaning the source contributed
nothing).

Recovery from the enumerated set uses the primitives above, in order:
`omh memory lineage <record-id>` to widen through descendants, then
`omh memory retire <record-id> --apply` to quarantine into the local archive
(reversible, and the default), then `omh memory prune <record-id> --revision
<n> --apply --confirm-hard-delete-local` only as an explicit second step.
Completion evidence is a recall report over this store showing the records
absent -- `omh memory recall "<the claim those records answered>"`, or `omh
memory recall-incident --record-id <id>` for one record's stored/eligible/
selected stages. The retire command's exit code is not: a sweep that archived
nothing also exits `0`. Neither is `omh memory recall-suite`, which seeds its
own fixture corpus in a temporary store (see Retrieval Regression Suite) and
proves the recall engine did not regress, never that this store's records left
recall.

## Perspectives (Observer / Observed)

A record may optionally carry a perspective: which actor's view it is
(`observer`, defaulting to `hermes`) and which actor it is about
(`observed`). This is Honcho's peer paradigm reinterpreted deterministically:
no theory-of-mind inference, just bookkeeping that keeps one actor's lessons
out of another actor's context. An `observed` label that should reach
handoffs must be an executor target id (`EXECUTOR_PROFILES` in
`src/coding/executors.py`); other labels such as
`operator` are inspection-only lenses that no handoff ever selects.

```sh
# Agent/operator only: capture a fact about one executor.
omh memory capture "codex needs the full test command spelled out" --observed codex

# Agent/operator only: recall through a lens; unscoped records always pass.
omh memory recall "test command" --observed codex

# Agent/operator only: list observer/observed pairs with record counts.
omh memory perspectives
```

Lens semantics: an unscoped record (no perspective) behaves exactly as
before and passes every lens. A scoped record surfaces only through a
matching lens; lens labels normalize like capture labels (lowercased,
trimmed). Handoff recall packs and handoff context packs automatically use
the selected executor target as their `observed` lens, so a record captured
about `codex` reaches codex handoffs — and never a `claude-code` or
`generic` handoff. While the executor target is still unresolved
(`choose`), handoffs carry unscoped records only. A plain recall with no
lens is an inspection surface and hides nothing. Recall packs echo the
active lens under `perspective`, each included record carries its own
`perspective` block, and context packs exclude mismatched records with
reason `perspective_mismatch`.

Thread records travel with their own session only. A handoff context pack
includes a `thread` record when its ref is the pack's `--session-id` (or the
pack is that thread's own scope) and lists any other session's thread record
under `excluded_context` as `scope_mismatch` — the recall pack's reason,
listed per record id here where recall reports a count; a record under
another project scope — including the unbound `project/default` label once
the home's identity has resolved — is listed the same way. An explicit
`--scope-kind thread --scope-ref <session>` or
`--scope-kind project --scope-ref <identity>` matches reviewed records on the
scope each was captured under. Naming the resolved project identity gives the
default project pack under its own name — no scope filter applies, so the
same snapshots, the same conflicts and the same exclusions; naming another
identity gives only the records captured under it.

## Legacy Migration and Reactivation

Legacy v1 files remain readable in status and review surfaces as
`review_required_legacy`; they do not replay. The first operator step is always
a report:

```sh
# Agent/operator only: dry-run, source-by-source counts and review-required notice.
omh memory inventory

# Agent/operator only: persist the bounded inventory ledger when requested.
omh memory inventory --write-ledger

# Agent/operator only: re-scan and reactivate exactly one reviewed artifact.
omh memory reactivate <record-id> --revision <n> --apply
```

Inventory reports deterministic counts for active records, scope items, blocks,
archive/history, candidates/reviews, index references, declared-link journals,
corrupt or unknown artifacts, and external exclusions. It does not emit raw
values or content hashes. Reactivation is per artifact/revision, report-first,
under the store lock, and creates v2 review evidence. It never mass-promotes
legacy memory or silently grants replay eligibility.

## Exact Lifecycle Vocabulary

- **expire** removes influence only.
- **retire** archives a readable local revision recoverably.
- **restore** creates a new pending revision linked to the archived revision
  while preserving that archive. A newer live conflict remains review-blocked.
- **prune** hard-deletes only the manifest-declared OMH-local target set for an
  expired volatile revision, after report and explicit confirmation.

The `archive` attention tier is not one of these verbs. It changes only how
much of the working context a live record may occupy; it moves no file and
writes no tombstone. See Attention Tiers above.

Restore and prune are report-first operator actions:

```sh
# Agent/operator only: inspect first, then apply a recoverable archive move.
omh memory retire
omh memory retire --apply

# Agent/operator only: inspect archive targets; a restore remains pending review.
omh memory restore <record-id> --revision <n>
omh memory restore <record-id> --revision <n> --apply

# Agent/operator only: inspect the local manifest, then explicitly hard-delete it.
omh memory prune <record-id> --revision <n>
omh memory prune <record-id> --revision <n> --apply --confirm-hard-delete-local
```

A prune receipt names attempted, observed, absent, unresolved, and excluded
local targets. It does not cover backups, filesystem snapshots, trash, synced
copies, Hermes-native memory, providers, vector stores, executors, or unlinked
artifacts. A tombstone blocks restore/retry of that exact opaque identity; it
does not block a newly captured fact.

## Batch Context Updates

Direct batch mutation is not a trust path. Agents and operators use a staged
sequence:

```sh
# Agent/operator only: validate into review-only candidates.
omh memory batch-stage --batch memory-update-batch.json

# Agent/operator only: create immutable review evidence for the staged set.
omh memory batch-review <batch-id>

# Agent/operator only: apply only the linked approved set under the store lock.
omh memory batch-apply <batch-id> --apply
```

Each stage is separate from replay eligibility. The compatibility
`omh memory apply --batch` path reports `review_required` rather than directly
writing unreviewed updates.

## Provider Prefetch and the Recall Line

The Hermes memory provider (`memory.provider: omh`) is the lane through which
reviewed memory reaches a Hermes turn without being asked for. Before every
model call Hermes takes the provider's prefetch text; OMH serves one pack,
rendered off the hot path and re-ranked after each turn:

1. system-tier memory blocks in full, under the block render budget;
2. reference-tier blocks as a label index (values stay behind `omh_memory
   read`);
3. `<memory_records>`: reviewed `project_memory_record/v2` records selected by
   the same canonical eligibility and ranking contract as handoff recall.
   The provider applies the explicit user-global/current-project/current-thread
   allowlist and the Hermes perspective. Privileged pins lead, then attention,
   relevance, decayed rank fusion, and record ID. Selection keeps at most six
   records. Rendering keeps a prefix under a separate 2,400-character section
   budget, including tags, escaping, separators, and omission reports.
   `over_budget` counts selector cuts; `render_budget_exhausted` counts selected
   records that didn't fit the rendering. Neither cut silently substitutes a
   lower-ranked record. A budget too small for the omission report returns no
   section and a zero record count.

Blocks and the reference index go to an operator console only, and the
`omh reminder:` line and the consolidation brief to an attended one, not a
Kanban worker ([Surface classes](#surface-classes)); a shared surface or a
background run gets the records its lens admits and the digest, nothing else. Outside any repository a console's allowlist is
user-global and the current thread: with no project identity, no project record
is admitted at all, and what is left is a subset of what the same session reads
inside any repository (owner decision 2026-10-13; before it, the allowlist was
empty there, so a capture made outside a repository was stored and never
recalled). A shared surface outside a repository still reads nothing.

### The recall query

The pack is ranked against a query built from the person's turn, and that
turn reaches the provider exactly as Hermes built it. Before ranking,
`memory_query_sanitizer.sanitize_memory_query` reduces it in two steps.

First it separates the person's own words from host framing, each rule
anchored to the exact string Hermes writes at the start of a line: an
out-of-band steer wrapper, a context summary handoff, a gateway origin
preamble, a triggering-message note, a reply pointer (`[Replying to: "..."]`),
Discord channel backfill (the `[Recent channel messages]`, `[Context around
the replied-to message]` or unverified-sender header through the last
`[New message]` line), and a single speaker's `[name] ` prefix. A slash-skill
or auto-loaded skill turn gives only the instruction the person typed, by
the same markers and first/last rule as Hermes' own
`extract_user_instruction_from_skill_message`; a bare invocation gives an
empty query. A host notice (a background-process, delegation-completion or
gateway-provenance notice) ends the person's words at the line where it
starts, and a turn that is only a notice gives an empty query. A turn that
only mentions one of these phrases mid-sentence keeps it, backfill with no
`[New message]` boundary is kept whole, and a relay with two or more
distinct speakers keeps its prefixes.

Then own words of at most 250 characters are used as they are. Longer ones,
such as a question next to a pasted log or document, are cut to one segment,
skipping log, timestamp and fenced code lines: the last question of the final
paragraph, else the first question of the first paragraph (asked first, pasted
after), else the last question; failing that the last plain sentence; failing
that the tail cut at a word boundary.

Last, two kinds of context the person chose are appended after their own
words. The first is the quoted message of a reply, because "answer this"
means the quote is the topic. The second applies when the new message is
shorter than 40 characters: the same speaker's earlier backfill lines, newest
first. Another speaker's backfill line never enters the query, and a new
message without a speaker prefix appends no backfill. No query is longer
than 250 characters (`QUERY_MAX_CHARS`), cut at a word boundary with the
person's own words kept first, and sanitizing a sanitized query changes
nothing.

This applies only to the chat-turn query the provider builds in
`on_turn_start`, `prefetch` and `queue_prefetch`. CLI recall, `omh_memory
recall` and coding-handoff recall packs keep their raw task text, because
every sentence of a task matters. The prefetch receipt records which method
applied (`passthrough`, `framing_only`, `question_extraction`,
`tail_sentence`, `tail_truncation` or `empty`) and the original and clean
lengths in `lens`, never the text. The paste reduction is reimplemented from
MemPalace's query sanitizer (`MemPalace/mempalace`, MIT); the framing rules
are OMH's own.

### The pack budget

Hermes keeps only the first and last 500 characters of a provider's prefetch
result longer than 10,000 characters (`DEFAULT_MAX_CHARS`,
`tools/hook_output_spill.py`) and spills the rest to a file, so records in the
middle of an oversized pack never reach the model while the receipt and
`served.json` still count them. The section caps alone summed past that. The
whole pack now fits `PACK_BUDGET_CHARS` (9,000):

- the records, the reminder, the digest and the brief render at their own caps;
- the reference index stops at 600 characters with one `<omitted count="N" />`
  line for the rest;
- system blocks take what is left, at most their 6,000-character cap, with
  their wrapper and omission lines counted.

When that is not enough, lowest-ranked system blocks give first (each is still
listed by `omh_memory(action="blocks")` and readable with `read`, both on a
console) down to a 3,000-character floor, then index lines, then the brief's
demote rows, then system blocks below the floor. The records section, the
brief's `<do>` lines and every closing tag are never cut, by the pack or by the
brief's own 1,600-character cap, under which the reason and headroom lines give
way after the demote rows. The reminder and the digest are whole or absent; a
digest left out stays pending for the next render, and a reminder left out is
not recorded as asked. The receipt's `rendering` names only what the returned
text carries and adds `pack_chars`, the text's length.

Two limits on that guarantee:

- It holds for Hermes' default cap. An operator who sets
  `hooks.output_spill.max_chars` below 9,000 in Hermes' config brings the spill
  back for the largest packs.
- The copied 10,000 is checked against Hermes' `tools/hook_output_spill.py`
  only where a Hermes checkout exists (`$HERMES_AGENT_ROOT` or
  `~/.hermes/hermes-agent`). CI installs none, so there the check is skipped
  and says so.

Records are read from the project store (`<repository>/.omh/memory/records/`
for the nearest `.git` above the working directory) and then the user store
(`~/.omh` by default); a record id present in both is read from the project.
The snapshot reader retains reviewed superseded, expired, and stale revisions
so the selector can classify exclusions at its own clock rather than losing
those reasons to a wall-clock prefilter. Legacy v1 and records without a
resolvable review don't enter that snapshot. Pending, rejected, superseded,
expired, stale, foreign-scope, and foreign-perspective records never render.
The provider's prefetch is not a handoff attachment and doesn't move the
`used` counter the ranking reads; a prefetch that returns a pack counts
`served` instead (see Recall Ranking and Delivery Usage).

A `user-global/default` record is eligible across projects only within the
stores the caller reads. Existing `project/default` records stay project
records; inside a differently named repository they don't match the current
project lens. There is no automatic relabeling or schema migration. Capture,
recall, and incident commands now accept `--scope-kind user-global`; changing
an old fact's audience still requires normal reviewed capture and approval.
See [store rollout](MEMORY-PREFETCH.md#store-rollout) before changing labels.

When the served pack is non-empty Hermes prints its deterministic recall line
through its status channel, so it appears on every surface Hermes speaks
through (CLI, TUI, and each gateway platform) whether or not the model mentions
memory:

```text
🧠 OMH — recalled 2 memories
```

The count is rendered full blocks plus rendered record elements in the last
pack returned by `prefetch`, not the number selected for a queued pack. Record
summaries are bounded projections, not a promise of full source content. A
reference-only block index reports content without a discrete count.
Initialization, a newly served empty pack, and shutdown don't retain an old
served count.

The provider also writes a bounded `omh_memory_prefetch_receipt/v1` with
selected IDs, rendered IDs and summary digests, exclusions, truncation, and
session/store/configuration identity. It supports local preparation and return
claims, not host delivery or model use. The recall line is aggregate status,
not record-bound evidence that a memory entered a model request. Receipt
integrity checks detect inconsistent edits but don't authenticate the sender.
See [receipt privacy and identity](MEMORY-PREFETCH.md#receipt-privacy-and-identity).

### The `omh reminder:` line

An open record should not wait for someone to run a command; the provider
asks. After the records section the pack may carry exactly one line:

```text
omh reminder: "<summary>" (<record_id>) has been unresolved for <N> days — resolved, still open, or drop it? Answer with omh memory confirm <id> · omh memory keep-open <id> · omh memory retire <id>
```

Hermes relays it as a question in its reply; the answer maps to the three
verbs above. The summary is the same bounded, redacted projection a record
element carries. Cadence: a record is asked about once its review deadline
has passed (an open record still inside its deadline is delivered with its
marker but not asked about), then at most every `open_ask_days` (default 14)
per record; "still open" resets that clock. Never more than one line per
pack — the rest queue by age, oldest `open_since` first — and only for
records the pack itself was willing to deliver: inside its scope allowlist
and admitted by its eligibility evaluation (delivered, or held back only for
no query overlap, overlap only on store-common terms, or the budget cut). A
superseded, archived, or otherwise refused record is never asked about,
because two of the three answers would refuse it; the reminder is
eligibility-bound, not query-bound. Principal-bound
(`project_memory_record/v3`) records are asked about on the same terms: the
pack's own principal and audience rules decide whether they are eligible, and
the reminder never reads them more loosely than the pack does. Only an
operator console is asked: a shared surface (a group chat) is never asked to
settle the operator's question, and a background run has nobody to answer.

Boundary: the reminder only asks. Serving the pack writes one line to the
local ask ledger `<omh_home>/memory/open_reminders.json`
(`{"schema_version": "omh_memory_open_reminders/v1", "records": {"<record_id>":
{"asked_at": ..., "asked_count": n}}}`) through the same best-effort path as
the receipt; a queued re-render that is never served records nothing, and
the same pack served to several API calls inside one turn is one ask. No
reminder path writes a record — every state change still goes through
confirm / correct / retire. The line never moves the recall count. Hermes'
`RecallStatus` has no field for it, so the ask is disclosed in the prefetch
receipt (`reminder: {record_id, open_days}`, no summary) and through the
provider's `latest_open_reminder()` accessor.

### The `<memory_digest>` section

What OMH memory did between sessions used to be invisible: each capture,
demotion, correction or retirement was announced once, in the turn that made
it, and the next conversation opened with nothing. The first pack a prefetch
serves in a new session may now carry one section:

```text
<memory_digest since="2026-10-11T08:12:40Z" remembered="2" hermes_entries_freed="1" retired="1">
OMH memory changes in this OMH home since your last session. If they bear on the user's message, mention them in one short line at most; otherwise leave them out.
</memory_digest>
```

A new session is one Hermes starts: `initialize`, or Hermes' own
`on_session_switch(reset=True)` (`/new`, `/reset`). That switch arrives from
Hermes' worker after `on_session_end`, often after the next turn's prefetch
already adopted the new id, and it still starts the digest. Four things are not
a new session and get none:

- a compression (a switch without `reset`);
- a turn-lease reload, which rotates the id to the compression child of the
  same conversation without any switch call, so the prefetch only moves the
  lens;
- a gateway rebuilding its agent for a conversation already under way, which
  shows as an `initialize` whose id is the session the last served pack went
  to;
- a cron or subagent context, which has no user to tell.

The section rides every render until a prefetch serves one, so a first turn
Hermes skips (a bare greeting) does not use it up. After that it never appears
again in that session.

The window ends at this session's start, floored to its second. Record and
journal stamps are whole seconds, so nothing this session writes is ever
counted. It starts at the later of two marks in this OMH home's
`memory/session_close.json` (`omh_memory_session_close/v1`, written atomically
under the state lock):

- `last_session_closed_at`, the last recorded close. An attended operator
  console records it at `shutdown`, at `on_session_end` and at Hermes' `reset`
  switch, in this session or any other; a gateway session, a background run
  and a Kanban worker record none. Hermes calls `on_session_end` at every
  compression (CLI included) as well as at a real end, so a console records a
  close at each of them too. The stamp keeps microseconds, so every write made
  before a close sorts before it.
- `reported_through`, the end of the last digest served. It is recorded when a
  non-shared digest is served, so a row already reported never comes back
  after a session that was killed or ran alongside, while what that session
  wrote afterwards still counts. A shared surface's confined digest records
  nothing, and neither does a digest with nothing to say. A session that
  started earlier but serves later reads the mark again at render time, so it
  does not repeat rows another session reported in between. Only this mark is
  read again: a newer close would also hide rows no digest showed.

"Served" means `prefetch` returned the pack to Hermes (`returned_to_host`), not
that the model read it. Hermes drops an external prefetch that takes longer
than 8 seconds (`_EXTERNAL_PREFETCH_TIMEOUT_S`, `agent/memory_manager.py`) and
spills a result over 10,000 characters to a file, keeping its first and last
500 in the prompt (`DEFAULT_MAX_CHARS`, `tools/hook_output_spill.py`). So a
mark can be recorded for a digest the model never saw. That errs toward
reporting less, never toward repeating.

The mark is one per OMH home. The counts cover the current repository's
project store plus the user store, so a digest served in one repository marks
the window reported for every repository.

Both marks only move forward, so a clock stepped back or a `~/.omh` shared by
two machines cannot widen the window. A mark more than five minutes ahead of
the clock (`MARK_FUTURE_SKEW_SECONDS`) is ignored, as if absent, and the next
write replaces it. One wrong clock therefore cannot silence digests until its
date, at the cost that a clock stepped back further than that no longer holds
the old marks. With no close ever recorded, the last
served pack (the prefetch receipt's `served_at`, whole seconds, so a write in
that same second is counted) stands in for the close. The window never starts
more than seven days back. A marks file or receipt that exists but cannot be
read means no digest at all, never the seven-day window. The receipt is read
raw (`state`, `served_at`, `session_id`), so one written by an earlier OMH
release still counts. Each count comes from a structured field:

| Attribute | Counted from |
| --- | --- |
| `remembered` | admitted records whose `created_at` is in the window, other than the two kinds below |
| `hermes_entries_copied` | records with `source: hermes_demotion` whose `source_ref` digest matches the record's own summary (an intact copy; an altered one is not counted) |
| `hermes_entries_freed` | write-journal `remove` lines with `removed_entry_demoted: true` |
| `corrected` | `hermes_model` records with a non-empty `derived_from`, which only `omh_memory` correct writes |
| `retired` | `retirements.jsonl` lines whose `retired_at` is in the window, whoever retired the record |

Only live records are read: a record created and then corrected or retired
inside the window counts as the correction or the retirement, not also as
remembered. Only nonzero counts are named, and a session with every count at
zero gets no section. The section carries counts and the fixed sentence, never
record text, and asks for nothing: it gives no language or voice direction and
no forced announcement. It is a status, not memory, so it never moves the
recall count; a pack that carries only the digest prints no recall line. A
write journal at its retention cap has dropped its oldest lines, so the section
then names `journal_at_cap="true"` and `hermes_entries_freed` is a floor.

On a shared surface (every gateway, see [Surface classes](#surface-classes)),
the digest is confined rather than suppressed:

- It counts only records the session's own recall lens admits. That lens is
  prefetch's and `omh_memory` recall's: principal, then scope, then
  perspective.
- It takes none of `hermes_entries_copied`, `hermes_entries_freed` or
  `retired`, because a write-journal or retirement line carries no scope a lens
  could judge.
- It names no `since`, and uses its own sentence ("Changes since the last
  session to OMH memory this conversation can recall").

That lens admits no identity-unbound record on a shared surface today, so until
Hermes supplies an authenticated principal those surfaces see no digest in
practice. The same is true of their recall.

What the window guarantees, exactly:

- This session's own writes are never counted.
- A row a non-shared digest already reported is not counted again, unless the
  mark write failed (counted in the next receipt's write failures as
  `session_marks`). Then the rows that digest showed can repeat.
- A previous session's writes are counted only when that session recorded no
  close after them: a killed process, or a close write that failed (counted
  as `session_close`). The window then starts at the later of the close
  before them and the last digest's end, or at the last served pack.
- Any close moves the start later, so the digest can leave out activity that
  happened before it. That includes a console's compression, in this session
  or another.
- Counts cover the user store and the current repository's project store,
  except on a shared surface as above. The marks are home-wide.
- A corrupt stamp (a 400-digit number, a date past the platform's range) is not
  a stamp. Any fault reading the stores costs only the digest, recorded as a
  `session_digest` write failure, and never fails `initialize`, a switch or a
  render.

`omh quality-evidence memory` imports the digest's stamp parser and its freeing
rule, so the two read stamps and frees identically. A parity test holds the
record and journal counts together across the user and project stores.

### Backups

The provider's `backup_paths()` hands `<omh_home>/memory` to `hermes backup`
when it exists as a real directory (not a symlink); it never creates or
changes it. A restore can leave `principal.key` with the restoring process's
umask mode; OMH re-tightens it to 0600 on its next read.

## Dreaming

Dreaming has only `off` and `reminder` modes. The reminder scheduler runs
automatically at five points:

| hook | trigger | purpose |
| --- | --- | --- |
| `on_turn_start` | `turn` | Evaluate when the interval is due (five turns by default). |
| `on_pre_compress` | `compaction` | Preserve a reminder before compression discards messages. |
| `on_session_end` | `session_end` | Review what a productive session may have made worth keeping. |
| `shutdown` | `shutdown` | Take the final opportunity before the process exits. |
| `initialize` | `session_start_recovery` | Recover when the prior session ended without consolidation. |

Only an attended operator console evaluates at these points
([Surface classes](#surface-classes)); a shared surface, a background run and a
Kanban worker raise no brief and move no counter.

### Per-profile dreaming state and the mode setting

The counters and the brief belong to one Hermes profile, not to the OMH home.
Each profile keeps them in its own directory,
`<omh_home>/memory/profiles/<slot>/dreaming.json` and `consolidation.json`,
where the slot is the sha256 of the profile's resolved Hermes home (the key the
group-activity status already uses). Several profiles can bind one store, for
example every profile of a gateway running `gateway.multiplex_profiles: true`
that names `~/.omh`. In that case each profile counts only its own turns and
compactions, raises headroom reasons only from its own `MEMORY.md` and
`USER.md`, and is served only its own brief. The pack, the chat card notice,
`omh_memory(action="consolidation")` and `omh doctor` each read the brief of the
Hermes home they are bound to, and `omh memory dream` reports that home's
counters.
The metadata-only journal `memory/consolidation.jsonl` stays home-wide: it is
history for evidence reports, never served, and each line names the session
that raised it. `omh memory retire --apply` archives the home's records, so it
retires an expiring-only brief in every profile's directory.

A profile chooses its mode in its own `config.yaml`:

```yaml
plugins:
  entries:
    omh:
      settings:
        dreaming_mode: off   # or: reminder (the default)
```

`off` means no brief is raised, served or reported for that profile, including
a brief written before it chose `off`. The pack carries none, and neither do
the chat notice, `omh_memory`, or `omh doctor`. The counters keep counting, so
switching back to `reminder` starts from what happened in the meantime. Written
bare, `off` is a YAML false, and `hermes config set` stores it as `false`.
`off`, `false` and `no` all mean `off`. An unset key keeps the default
`reminder`, so memory keeps running with no step for a person to take. Any
other value (`disabled`, `0`, `on`, a typo), or a config this reader cannot
follow, also keeps `reminder`, and says so: `omh memory dream` reports the mode
in force as `mode` and how the setting read as `mode_setting`, which carries
`issue: mode_setting_unrecognized` with the value as written (at most 64
printable characters) and a `reason` of `unknown_value` or
`config_unreadable`. `omh doctor` prints the same as a `mode_setting_unrecognized`
advice line, which never changes the doctor status.
The setting is read from the profile's own file once per evaluation and once
per pack render, so a change applies from the next turn without a restart. The
same block-style scan the standalone lane uses for `omh_home` reads it, and the
managed overlay is not consulted. Profiles that share a store can choose
differently, and no managed OMH file is edited.

On the first attended session start after the upgrade from an earlier release,
which kept one `memory/dreaming.json` and `memory/consolidation.json` for the
whole home:

- A profile that is not routed claims them by moving them into its own
  directory. Not routed means a process serving its launch profile alone. On a
  single-profile host the files are that profile's own, so a pending brief and
  its counters survive the upgrade. Where separate processes for different
  profiles share one store, the first to start claims them, one at a time
  under a single lock, so the two files never split between profiles. A file
  the profile already has is never replaced, so if `omh memory dream
  --evaluate` wrote the profile's own files before that first session start,
  the old ones stay unread.
- A routed profile leaves them where they are and never reads them. That is
  every profile of a multiplexed process, including a host that runs a single
  profile with `gateway.multiplex_profiles: true`, or a profile other than the
  launch one. Nothing records which profile raised them, so a stale shared brief stops
  reaching every profile instead of being handed to one at random. A standing
  condition such as low headroom is raised again from the profile's own state
  at its next evaluation.

The brief nominates duplicate clusters, records at or near their deadline,
and working-context headroom below the configured floor. Standing reasons also
include `stale_review_required` and `expired_volatile_records`. An unchanged
standing condition is suppressed until its value changes, rather than being
restated every time the scheduler runs. A record OMH cannot source is never an
eviction candidate: absence of provenance is not evidence that the record is
wrong.

The ranking inputs do not expand eligibility or establish truth:

- Pins guarantee inclusion among eligible records; they never override
  expiry, scope, perspective, or review eligibility.
- Attention tiers control how much working context a record may occupy, not
  whether it is true.
- `approved_manual` carries 100% veracity weight and `approved_auto_safe`
  carries 90%; an unknown approval mode fails closed to the lower weight.
- Age tiers only degrade old records within an equal relevance rank.
- Delivery usage uses saturating buckets, so repeated use cannot compound into
  a permanent head start.

Dreaming prepares a reminder and metadata-only evidence. It never invokes a
model or performs consolidation, retirement, restore, or prune; whatever is
consolidated, the model does through its own tool calls in a later turn.

For agents and operators, `omh_memory(action="consolidation")` reads the latest
recorded brief and scheduler counters without starting a provider session or
evaluating triggers. It returns `evaluated: false`; `due` and the brief's other
fields are present only when a readable brief exists. No brief is not evidence
that nothing is due. Repeated status queries leave counters, suppression state,
and the pending brief unchanged. `omh memory dream` is likewise read-only;
explicit `omh memory dream --evaluate` evaluates once under the `manual` trigger
and may write a reminder. Provider lifecycle hooks retain their scheduled
evaluation behavior.

### How a brief reaches the model and the user

A brief on disk consolidates nothing by itself. While the newest brief is
`due`, the provider serves it inside its prefetch pack as a bounded
`<memory_consolidation>` section (trigger, reasons, Hermes memory headroom
and duplicate-cluster counts, and what is requested), so the next
non-trivial turn on an operator console (CLI, TUI or Desktop) carries the
request to the model. A shared surface and a background run never carry it:
its demote rows quote the operator's USER.md and MEMORY.md. The
section asks the model for three things: move durable facts, preferences, and
decisions from the session into OMH with `omh_memory(action="capture")`, one
bounded line each; when Hermes memory is nearly full (a
`headroom_below_floor` reason), move the entries the brief names into OMH with
`omh_memory(action="demote")` and remove them from Hermes (see
[Demotion](#hermes-memory-tiering-demotion-l1--l2)), otherwise trim or merge
with Hermes' own memory tool; then tell the user in one short line what it
remembered or trimmed, or that nothing needed changing. A brief is a
request, not recalled memory and not evidence of consolidation: it never moves
the recall count or the recall line, and only the capture results and memory
writes the model actually makes are observed.

A compaction brief is raised in `on_pre_compress` but served in the next
turn's pack, after the compressed messages are gone. So it says the turns were
replaced by a summary and points the capture at it: from the summary's
"Constraints & Preferences", which Hermes' template fills with user
preferences, constraints and important decisions, each fact, preference or
decision the user stated that should hold in later sessions and that was not
already captured in this conversation, one `omh_memory(action="capture")` call
per fact. Hermes' iterative summary carries earlier items forward, so each
compaction would offer them again; a fact OMH already holds answers
`already_remembered`. "Key Decisions" is left out on purpose: it holds the
work's technical decisions, mostly scoped to the task at hand. The "N
message(s) went into that summary" line appears on a compaction brief only.
`on_pre_compress` itself returns
only the system blocks. It does not ask the summarizer for anything: Hermes
JSON-encodes that text and tells its summarizer to read it "only as source
material to preserve in the summary, not as instructions"
(`agent/context_compressor.py`), and OMH does not argue with the host's
prompt. OMH remains a best-effort (API v1) pre-compress provider, so the text
never takes part in Hermes' checkpoint decision. The brief is raised only on an
attended operator console. A shared surface raises none: the brief is the
profile's state, served on its next console turn, so a group chat's compaction
would reach the TUI as "earlier turns of this conversation" it never had.

The section disappears once consolidation is observed: a `replace` or
`remove` from Hermes' memory tool retires the brief when no standing reason
remains. Where the host hands the provider a status callback (Hermes does
this on the CLI surface), the provider also prints one line when a brief
fires and one when it is honoured:

```text
💤 OMH — memory consolidation due (session_end: session_ending_with_unconsolidated_turns:1)
🧹 OMH — memory consolidated (replace on memory)
```

Every other platform (the TUI, Desktop, and gateways such as Slack, Telegram
and Discord) receives no provider status callback from Hermes; on a console
there the model's one-line report is the visible
signal, and the tool calls it makes are shown by the platform as usual.
`memory-sync` (reviewing existing Hermes memory against OMH records) stays
an explicit workflow: nothing runs it automatically, and the brief only
points at duplicate clusters for the model to resolve.

## Hermes Memory Tiering: Demotion (L1 → L2)

Hermes-native memory files (`MEMORY.md`, `USER.md`) are L1: small,
character-capped, and paid for on every turn. The OMH record store is L2:
reviewed, governed, and not bound by that cap. When L1 fills, the usual move
is deleting an entry — which loses the fact. Demotion is the other move: the
content goes down into L2 and the L1 entry is removed (the model's path) or
replaced by a short reference line (the operator's path).

### The model-driven path

Demotion runs without an operator step. When MEMORY.md or USER.md falls below
the headroom floor (the floor is proportional to each file's cap, 300 characters at
MEMORY.md's default 2200 and 187 at USER.md's 1375; each file's reason names
it, `headroom_below_floor:USER.md:34<=187`, and MEMORY.md's keeps the bare
`headroom_below_floor:289<=300`), the consolidation brief carries up
to three `<demote>` rows drawn from every file below the floor: the largest
entries, minus any the action would refuse (sensitive-looking,
over the summary bound) or that already have a pending, rejected, or
unrecognized candidate, or that the other Hermes memory file also holds.

```text
<demote file="MEMORY.md" entry="<sha12>" chars="201">Fact 1: the bravo cluster rotates its bu…</demote>
```

When a row comes from USER.md the brief adds one instruction: keep entries about
who the user is, how to address them, and reply language or voice, and demote
only the others. That is the model's judgement; OMH does not read the entries.

On disk the brief names rows by file, sha256 prefix, and length only — the
brief file and its journal never carry entry text. The preview is read from
the live Hermes file when the section renders, and a row whose entry is gone
is dropped. The brief offers no row the model may remove without calling the
action: for each row the model calls
`omh_memory(action="demote", entry_sha256=<sha12>)`, which decides live.

The action reads the entry from the Hermes file itself (never the model's
paraphrase), parsed the way Hermes parses it — split on the full `\n§\n`
delimiter, BOM stripped — and refuses one that is not a whole Hermes entry.
It checks any candidate already filed for exactly this entry first, then
applies the same guards as `--stage` below, and captures the entry as a
`user-global`, `durable` fact with `source="hermes_demotion"` and the same
`source_ref` the operator path writes, so the two paths see each other's
candidates. Hermes memory belongs to one Hermes home, not to a project, which
is why the scope is user-global. Results:

| `status` | Meaning |
| --- | --- |
| `demoted` | Auto-safe approved an intact copy; `remove_from_hermes` and `display_line` are present. |
| `already_covered` | An approved, replay-eligible record already holds the entry exactly: the record captured under this entry's `source_ref` with the same text, or a durable user-global record with exactly the same text. `remove_from_hermes` and `display_line` are present. |
| `pending_review` | A copy waits for review (new, or from an earlier call); keep the Hermes entry. |
| `refused` | Nothing removable: `shared_surface_writes_refused`, `writes_disabled` or `session_lens_unavailable` outside an operator console ([Surface classes](#surface-classes)), `entry_not_found`, `entry_in_both_files`, `entry_ambiguous`, `entry_sha256_invalid`, `entry_not_whole`, `previously_rejected`, `candidate_status_unknown`, `redacted_cannot_demote`, `summary_bound_exceeded`, `content_not_intact`, `held_record_not_removable`, or an admission refusal. |
| `error` | The store raised; nothing is confirmed moved. |

Token similarity never authorizes a removal: a negation of the same fact
shares nearly every token, and a project-scoped or volatile record does not
come back wherever the Hermes entry would. An entry that is only similar to a
record is captured as its own durable copy instead.

Only `demoted` and `already_covered` carry
`remove_from_hermes: {"target": "memory" | "user", "old_text": ...}`, and the
model then removes the entry with Hermes' own `memory` tool (`action="remove"`)
and confirms that the entry Hermes reports removed is the demoted one.
`old_text` is the entry itself when it is at most 60 characters, else the
first window of at most 60 characters that no other entry contains, and the
whole entry only when no such window exists (an entry wholly inside another);
it selects only that entry under Hermes' matching. It is the model's own
memory, already in its system prompt, and is the one place the tool returns
Hermes entry text. On this path the entry is removed, not replaced by a
reference line: the line costs about 70 characters per entry, which is the
space the move exists to free, and recall brings the fact back from OMH when a
turn needs it. Hermes may stage or gate the removal itself; OMH never writes
Hermes files. When Hermes reports the removed entry, the write journal records
`removed_entry_demoted` — whether OMH holds that exact entry under its demotion
`source_ref`. A Hermes `remove` retires the brief once no standing reason
remains. Capture and demote results carry a `display_line`
(`📌 OMH remembered: …`, `📦 OMH moved to long-term memory: …`, or
`📦 OMH already holds: …` when nothing new was stored) as suggested wording;
the model tells the user in one short line what was kept.

### The operator path

```sh
# Agent/operator only: plan which entries to move, biggest savings first.
omh memory demote [--file MEMORY.md] [--max 5]

# Capture the planned entries as review-first OMH candidates.
omh memory demote --stage
```

The plan selects entries no approved OMH record already explains, ranked by
size; an entry an approved record covers is reported separately as deletable
rather than copied down twice, and each planned row carries its
`staging_status` (`unstaged`, `already_staged`, `previously_rejected`) so the
plan advertises exactly the work `--stage` would do. Each row carries a
prepared reference line — `[omh#<sha12>] <first 60 chars…>` — keyed by the
sha256 of the entry's exact bytes, the one identifier both stores can
compute, so the line survives the candidate → record lifecycle it points
into.

Demotion moves content intact or it refuses; it never quietly damages it.
An entry the 240-char summary bound would truncate is refused as
`summary_bound_exceeded` (split it to demote it), and one the
sensitive-content redactor would collapse is refused as
`redacted_cannot_demote` — both stay in L1, because the next documented step
deletes the L1 original and that must never happen to a copy that is not
intact. Staging is idempotent (`already_staged` / `previously_rejected`,
never a duplicate candidate), cleanly staged candidates go through the
ordinary review gates, and the payload counts `captured_count` vs
`refused_count`. Note the plan output prints entry text verbatim — it is the
operator's own local Hermes memory content, but treat the plan like that
content when capturing terminal transcripts.

The L1 half stays with Hermes: OMH reads Hermes memory and cannot change it.
After approving the staged candidates, ask Hermes to replace each original
entry with its reference line through Hermes's own memory tool. Everything on
this surface is `prepared_not_observed` until that happens. The reverse move
— promoting an approved OMH record up into L1 — remains the memory bridge's
`promotable` surface (`omh memory status`).

### Measuring memory on your machine

`omh quality-evidence memory` counts what OMH memory did over a window, from
local records only:

```sh
omh quality-evidence memory [--days 7 | --since 2026-10-01T00:00:00Z] [--json]
omh --hermes-home ~/.hermes/profiles/<name> quality-evidence memory --json
```

It reads Hermes' `state.db` read-only (`omh_memory` calls per action and
result status, native `memory` calls per action and outcome, sessions with an
OMH memory write), the OMH store (admitted records per `source` and admission
state -- a candidate awaiting review is not a record -- records created in the
window, the last prefetch receipt, consolidation briefs per reason family, the
write journal's `removed_entry_demoted` counts), and Hermes memory headroom per
file. The headline lines are computed from those counts: facts remembered,
Hermes entries OMH stored a verified copy of (a demote alone removes nothing
from Hermes memory), and native entries freed after a demotion. Each names its
window and the home its count came from. Every count comes from a structured
field, never message text. A profile has its own `state.db` and OMH
home; the payload's `homes` names the pair that was read. A source that could
not be read exits 3 and its headline says "not observed" rather than zero. The
counts are local records: they do not show that a recalled memory improved an
answer. [Harness Quality](HARNESS_QUALITY.md#memory-evidence) has the counting
rules.

## Retrieval Regression Suite

Record validity and retrieval quality are different questions. `omh memory
evaluate` answers the first: admission, lifecycle, replay, and store
compaction against a generated corpus. A change to relevance ranking, pins,
age decay, attention tiers, the scope or perspective lens, budget cuts, or
stale-record handling can leave every one of those verdicts green and still
hand the executor the wrong context. `omh memory recall-suite` answers the
second.

```sh
# Agent/operator only: deterministic local retrieval and prefetch regression check.
omh memory recall-suite --revision "$(git rev-parse HEAD)"
```

The command runs a retained fixture corpus through
`build_project_memory_recall_pack`, the same builder handoff preparation uses,
and compares expected record IDs, order, and production reason codes. It also
checks canonical selection against the actual local prefetch adapter and
provider lifecycle. A retained-expectation failure or parity divergence makes
the case and report fail, with a nonzero CLI exit. Add `--output` to keep the
JSON report; no ranking, eligibility, or budget logic is copied into a second
selector.

Each case has two parity arms over its seeded store and frozen clock:

- `prefetch_adapter` reads the plugin snapshot, selects, renders, and builds a
  receipt using the case's record and summary-character budgets.
- `provider_session` runs `initialize`, `queue_prefetch`, `prefetch`, receipt
  retrieval, and `shutdown` at the provider's six-record limit with no selector
  summary-character cap. Canonical selection is compared at that same budget.

Both parity arms use delivery mode with `user-global/default`,
`project/default`, `thread/session-fixture`, and the Hermes perspective.
Retained inspection expectations still use each fixture's own lens and flags;
`--include-stale` and `--include-archived` aren't carried into live parity.
The comparison checks included IDs and order, exclusion reason counts,
truncation, configuration identity, scope/perspective, enabled state, clock,
and selector/pack schema. It also validates receipts and requires rendered
IDs to be a prefix of canonical selection, not equal in count when rendering
cuts that prefix. Missing or malformed receipts fail rather than skip.

Per-case `parity` lists both arms, their budgets, projections, and divergences.
`summary.parity_divergence_count` and `summary.parity_failed_cases` distinguish
adapter drift from retained ranking failures. These are local provider-class
executions on fixtures, not native Hermes sessions, host delivery, or model-use
observations.

Each fixture declares its own records, pins, delivery counters, query, scope
and perspective lens, record and character budgets, and the expected
disposition of every record: included in this order, excluded for this named
reason, or absent because a lens filtered it before the pack could name it.
The corpus covers exact and partial relevance, no-match behavior, same-topic
disagreement, correction and supersession, expiry, stale review and the
`--include-stale` inspection path, scope and perspective isolation, pin and
attention interactions, age ties, both archive directions, and record and
character budget truncation. It also covers inflected query words (deployment,
migration, caching), tag-only matches, a long record that mentions a word in
passing beside a short record about it, Korean, Chinese, Japanese and
mixed-language queries, common words that must not outrank a rare match, and
same-subject supersession in one scope and across scopes. The stores and
queries the review of #2091 used against the first BM25 revision are copied
in verbatim: question words that must not lead, stemmed-only matches that
must fall back, a temporal query that must keep recency, a plural record-type
word that must not flood the pack, and a superseded subject value that must
not come back when the newest expires or is archived. The re-review's
question-shaped stores are copied the same way: Japanese, Chinese, Korean
and English questions whose wrapping words must not outrank the deploy
records, and "WHO?", "ask Will" and "CAN logger", where a listed word in
capitals names something. Cases whose answer is a known cost say so in their
intent: the light stemmer reads "news" as "new"
when another record matches "new" exactly, "caching" alone falls back
because its only match is stemmed, and a current subject value that shares no
query word arrives only through the fallback.

The clock is part of the fixture. Every timestamp is absolute and the corpus
declares its own `now`, so a case that turns on expiry, review deadlines, or
age tiers reads the same on any host on any day, and no fixture goes red
because a day passed. Records are written straight into a per-case temporary
store rather than captured and approved, because approval stamps the real
clock and mints a random record id.

The report separates what broke. Ordering failures, missing expected hits, and
unexpected inclusions are counted apart from budget violations, so a pack that
returns the right records but overruns its budget is never reported as a
relevance miss. A record that a lens, a deadline, or a tier was supposed to
keep out carries a contamination class, and an unexpected inclusion increments
that class's own counter — `foreign_scope_contamination`,
`foreign_perspective_contamination`, `stale_contamination`,
`expired_contamination`, `archived_contamination` — so a leak is reported
under its own name. Every finding names the fixture, the record id, the
expected disposition, the observed disposition, and the production reason code
when the pack carried one.

Two reports are comparable only when their identities match. The report binds
itself to the fixture digest, the evaluator version, the corpus version, a
digest of the effective retrieval configuration
(`effective_recall_configuration` reads the live ranking constants, so
retuning a weight moves the digest), the fixture clock, and the target
revision passed to `--revision`. `compare_retrieval_reports` refuses a
comparison whose identities differ and names the mismatched fields, rather
than attributing a corpus edit or a weight change to a retrieval regression.

Reports retain `schema_version: omh_memory_retrieval_evaluation/v1` with
additive parity fields and `evaluator_version: omh-memory-retrieval-evaluator/v2`.
A v1-evaluator report isn't comparable to v2, even though the report schema is
unchanged. This remains a sibling of `omh_memory_evaluation/v1`; readers dispatch
on schema and check evaluator identity before comparing results. Neither runner
makes a model call, hosted-provider call, network request, or credential read.
The retrieval suite does execute the local OMH provider class inside its own
temporary stores, which are removed after the run. A model-judge or external memory-provider result may enter
only through a separate observed-evidence contract; this suite never produces
one.

## Prepared Context Boundary

A prepared recall or handoff pack is OMH-local context, not proof that an
executor ran, a provider received content, a model used it, or review/CI/merge
happened. Keep source class, admission mode, retention class, revision, and
replay reason with the bounded preparation evidence.
