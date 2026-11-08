---
name: "omh-memory-sync"
description: "[omh] Outdated or wrong Hermes memory entries: English-canonical Hermes memory-review guidance: inspect USER.md and MEMORY.md claims and prepare a native write diff without invoking, applying, or observing a native write; for a new fact use `omh-memory-new`, and for a past decision use omh_memory recall or `omh-decision-recall`. Use when the user says: memory-sync, memory curation, memory review, memory inspect, memory check, memory update, context cleanup, curate memory."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, memory]
    category: memory
    phase: curation-review
    role: memory-keeper
    quality_tier: workflow-surface-gated
    related_skills: [omh-memory-new, omh-decision-recall, omh-external-connector-readiness]
---

# Memory Sync

This is a Hermes-native `memory-sync` workflow skill.

## Why This Exists

`memory-sync` exists because Hermes' memory files are small, capped, and written by more than one hand -- the model, Hermes' own background review, and the person -- so a stale or wrong entry rides in every prompt until someone checks it: this review walks the entries with the person one claim at a time, prepares one diff they approve, and reports only the write Hermes itself returns.

## Do Not Use When

- The user states a new fact to remember; capture it with `omh-memory-new`.
- The user asks what was decided before; recall it with the omh_memory tool's recall action.
- The user asks what was rejected before; use `omh-decision-recall`.
- The user wants a memory provider enabled, switched, paused, or removed; use `omh-external-connector-readiness`, which owns the provider slot.

## Examples

Good example:

- Prompt: memory-sync inspect stale MEMORY.md claims, prepare a native write diff, and ask which claims to keep, revise, or archive.
- Expected behavior: Produce `prepare_memory_sync` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: memory-sync claim a prepared native diff changed MEMORY.md or USER.md.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Confirm the workflow target, evidence boundary, and stop condition are named.
- Report which outputs are prepared, observed, blocked, or missing.
- Name the smallest next verification or handoff instead of claiming completion from narration.

## Recovery Notes

- If entry-by-entry confirmation stops before the assembled diff is approved, retain the reviewed claim decisions, mark the diff unresolved, and hand back reviewed indexes, remaining candidates, and the next entry to resume.
- If the native memory tool is unavailable after diff approval, retain the approved before/after diff, mark the native write not_observed, and hand back that diff without editing MEMORY.md or USER.md directly.
- If a native write returns staged: true with a pending_id, retain the approved diff and pending_id, mark saving not_observed, and hand back /memory approve <id> for the person without repeating the write.

## Workflow Lane

- Current lane: **Retained knowledge** - memory, rejected alternatives, wiki notes, retrieval, and staleness.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## English-Canonical Interview Protocol

- **Inventory (목록)** - Call `omh_memory` with `action="status"` for the entry inventory: per-file counts, per-entry index and size, headroom, and entries with no OMH record. It returns counts and hashes, never entry text.
- **Pending writes (대기)** - Also list the memory writes Hermes is holding for approval: one JSON record per write under `pending/memory/` in the active profile's Hermes home, carrying `id`, `action`, `summary`, `origin`, and `created_at`. `/memory pending` shows the same list and tags `[auto]` a write whose `origin` is `background_review`, one Hermes' own background review proposed. Read the directory whatever `memory.write_approval` says now, since a record stays there until the person decides it. A pending write is not in `MEMORY.md` or `USER.md` yet: review it as a proposal, never as a remembered claim, and leave approving or rejecting it to the person (`/memory approve <id>` or `/memory reject <id>`).
- **Claim extraction (추출)** - Break the `USER.md` and `MEMORY.md` material into claims; quote only observed claims and never invent provenance.
- **Provenance (출처)** - Ask for the source class and distinguish Hermes-native, provider, and vector material as `not_omh_reviewed`. A provider posture's `input_fidelity_summary.readiness` is literal: only `complete_observed` rests on an observed complete receipt (`docs/MEMORY-SYNC-FIDELITY.md`).
- **Target (대상)** - Review existing native-memory claims only; route a new project/product fact to `omh-memory-new`.
- **Candidate selection (후보)** - Open records first (see Open Records below); then a short interview, not a census: pick about five candidates per pass and say why. Rank by dreaming reminders (duplicate clusters, deadline, `stale_review_required`), status-bridge similarity rows, and claims that look stale, conflicting, or overgeneralized. Walk the full inventory only on request.
- **Per-entry confirmation (확인)** - One candidate at a time: quote it back from your own memory file, say what you take it to mean, then ask the user to keep, revise, or archive it before moving on. A review the user cannot correct entry by entry is not a review.
- **Cursor (이어하기)** - Close every pass with reviewed entry indexes, remaining candidates, and the next entry a resumed review starts from. The resume point lives only in the conversation; name it.
- **Incident (진단)** - A recall complaint ("my saved preference was not used") is a diagnosis, never an apology or automatic write. Anchor one expected claim and run `omh memory recall-incident --record-id <id> | --claim-digest <sha256> --session-id <session>` (agent reference; JSON only). Explain its `memory_recall_incident/v1` stage, evidence surfaces, and remediation: stored, eligible, selected, rendered, delivered, and used are separate claims; diagnosis today stops at `selected`; a missing receipt is `unavailable`, never non-delivery. Mutation waits for this interview's approvals. Contract: `docs/MEMORY-RECALL-INCIDENT.md`.
- **Source recovery (출처 회수)** - A whole wrong source is not a record-by-record review. Enumerate it with `omh memory sources --source <label>` (a read; it quarantines nothing), then follow `references/source-recovery.md`.
- **Review (검토)** - Prioritize stale, conflicting, duplicate, and overgeneralized claims. Offer keep, revise, or archive; never call an archive a removal.
- **Attention (주의)** - For a reviewed OMH-local record, keep/archive is an attention tier: `active` leads the working context, `reference` stays recallable behind it, `archive` leaves default recall. Preview with `omh memory attention <record-id> --tier <tier>`, name which records stay in or leave the working context, then add `--apply` only after the user agrees. The preview writes nothing.
- **Diff (차이)** - Prepare one concise native write diff with before/after claims and counts. Caps: use each file's `cap` and `cap_source` from the inventory; Hermes reads them from `memory.memory_char_limit` and `memory.user_char_limit` and falls back to 2,200 characters for MEMORY.md and 1,375 characters for USER.md.
- **Move to OMH** - A durable entry the user agrees belongs in OMH, you capture yourself with `omh_memory` and `action="capture"` (one bounded summary per fact; never hand the user a CLI step), and the diff shrinks its Hermes entry to a short pointer line. The capture result is OMH-local evidence only; the Hermes side changes only through the native write below. Hermes' `write_approval` gates only Hermes' own memory and skill writes, never this capture: OMH's own policy approves a safe capture at once (`approved_auto_safe`), and a capture waits for review only when its result names a `review_reason`.
- **Native-write boundary (쓰기)** - OMH prepares guidance and a native write diff only; no OMH surface invokes, applies, or observes a `MEMORY.md`/`USER.md` write.
- **Apply after approval (적용)** - Per-entry answers feed the diff without approving it. Ask for one explicit approval of the assembled diff, then apply the approved entries yourself through the Hermes-native memory tool that owns these files and report what the write observably changed; an approved diff left unapplied while the tool is available fails the interview. Without the tool, report the approved diff and stop; never edit the files directly. When the native write returns `staged: true` with a `pending_id`, nothing was saved even though `success` is true: Hermes' own write approval, the user's setting, is holding it, so report it as staged and waiting for the person's `/memory approve <id>`, never as an applied write, and do not repeat the write. When Hermes asks the person before the write and they decline, the error result saved nothing: report that entry as declined and do not retry it. The OMH artifact stays `memory_curation_review/v1` metadata either way; the native write is Hermes's own act and never becomes OMH mutation evidence.

## Open Records

An open record is one the person marked unresolved: `staleness.resolution: "open"`. Recall delivers it as `open · N days unresolved`; past its review deadline its freshness state is `open` (reason `unresolved`), never `stale`, and it never becomes a verdict by timeout. Two clocks can still expire it: a retention TTL, which outranks everything, and the hard ceiling `open_max_days` (default 365; durable records exempt), with reason `unresolved_expired`.

When the user asks to tidy, review, or clean up memory, list open records first, before the stale, duplicate, and conflict review. Run `omh memory status` and read `counts.unresolved` and the bounded `open_records` list (oldest first). Show each record with its `summary`, `open_days`, `review_due_at`, `state`, and `last_asked_at`, then offer the same three answers the reminder offers:

- **Resolved** - `omh memory confirm <record-id>` writes `resolution: resolved` and resets the review deadline. A correction (`omh memory correct`) also resolves, by superseding.
- **Still open** - `omh memory keep-open <record-id>` resets only the reminder's ask clock; the record, its state, and its deadline do not change.
- **Drop it** - `omh memory retire <record-id>` prepares the retirement; `--apply` archives it. Nothing is deleted.

Without a shell that runs `omh`: `confirm` and `retire` (reason `user_asked`) exist as `omh_memory` actions and apply at once, so call them only after the person's answer (recall the record first: a record not served this session is refused as `record_not_seen_this_session`); the open-record listing and `keep-open` have no tool form, so say they need a terminal and stop.

The person answers per record; never resolve, keep open, or retire on your own judgment. A record with no answer stays open: say so, and do not default it to keep-open. Between reviews the provider prefetch asks on its own, with at most one `omh reminder: "<summary>" (<record_id>) has been unresolved for N days — resolved, still open, or drop it?` line per turn: once when the review deadline passes, then at most every `open_ask_days` (default 14) per record, and "still open" resets that clock. The reminder only asks and writes no record, so an answer given in chat still goes through one of the three commands above.

## Memory Boundaries

The prepared artifact is `memory_curation_review/v1`, not native-memory mutation evidence. Hermes-native and external provider/vector context is `not_omh_reviewed`: it can nominate an OMH candidate but never inherits OMH approval. A configured Hermes runtime may send rendered OMH prefetch content in a model request.

Lifecycle words are literal: expire removes influence only; retire archives recoverably; restore creates a new pending revision and keeps the archive; prune hard-deletes only the manifest-declared OMH-local target set. Report restore and prune first; no lifecycle result proves anything outside that target set.

An attention tier is not a lifecycle state; the two uses of "archive" differ: the `archive` tier only removes a record from the default working context, leaving it stored and answerable by `omh memory recall --include-archived`; `retire` moves an expired revision to the local archive directory. Neither is deletion.

Legacy v1 material is migration/review-required: show `memory inventory` counts and the report-first `memory reactivate ... --apply` path; neither silently grants replay eligibility.

Dreaming runs in reminder mode at five scheduler points: `turn` on the due interval (default five turns), `compaction` before compression discards messages, `session_end`, `shutdown`, and `session_start_recovery` after an unconsolidated end. It flags duplicate clusters, records near deadline, headroom below the floor, `stale_review_required`, and `expired_volatile_records`, suppressing an unchanged condition until its value changes; a reminder OMH cannot source is no candidate. Dreaming never invokes a model or performs consolidation, retirement, restore, or prune.

Ranking limits: pins guarantee inclusion but never override expiry, scope, perspective, or review eligibility; attention tiers control working-context occupancy, not truth; `approved_manual` weighs 100%, `approved_auto_safe` 90%, and an unknown approval mode fails closed to 90%; age only breaks ties within an equal relevance rank; usage buckets saturate, so repeated delivery cannot compound into a permanent lead.

Normal users talk to Hermes in natural language; `omh memory ...` commands are agent/operator references.

## When to Use

Use when existing Hermes USER.md, MEMORY.md, or accumulated skill memories need an English-canonical, claim-by-claim review. It prepares native write guidance only; no OMH surface invokes, applies, or observes a native write — a user-approved diff is applied by Hermes's own native memory tool. Do not use for new project or product candidates.

    Strong routing signals: `memory-sync`, `memory curation`, `memory review`, `memory inspect`, `memory check`, `memory update`, `context cleanup`, `curate memory`, `stale memory`, `hermes remembers`, `conflicting memory`, `duplicate skill`, `MEMORY.md`, `USER.md`, `what you remember about me`, `your memory about me`, `your memories`, `memory interview`, `memories still true`, `기억하고 있는`, `기억하고 있는 프로젝트 맥락`, `기억하는 맥락`, `현재 hermes가 기억하는 맥락`, `현재 헤르메스가 기억하는 맥락`, `헤르메스가 기억하는 맥락`, `오래된 맥락`, `오래된 기억`, `기억 점검`, `기억 정리`, `메모리 업데이트`, `메모리 검사`, `메모리 점검`, `메모리 정리`, `맥락 점검`, `맥락 정리`, `맥락 피드백`, `등록된 맥락`, `헤르메스 기억`, `중복 스킬`, `나에 대해 잘못 알고`, `저장된 내 정보`, `너한테 저장된`, `저장된 프로필`, `기억 바로잡`, `메모리 인터뷰`, `기억 인터뷰`, `что у тебя в памяти`, `что ты помнишь про меня`, `память устарела`, `старые записи в памяти`

## Catalog Metadata

Category: `memory`
Phase: `curation-review`
Hermes role: `memory-keeper`
Quality tier: `workflow-surface-gated`
Reasoning demand: `light`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.
- State that Hermes-native and external provider/vector context is not_omh_reviewed, can nominate a candidate only, and may receive rendered OMH prefetch content through a configured Hermes runtime model request.
- Send memory-provider lifecycle questions -- enabling, switching, pausing, retention, deletion, export, or failed synchronization -- to `omh-external-connector-readiness`, which owns the provider posture this review cannot establish.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- memory-sync/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- memory-sync/v1 metadata-only runtime or wrapper card when recorded

Safety rules:

- A memory-sync review is prompt guidance only: no OMH surface invokes, applies, or observes a MEMORY.md or USER.md write. Applying a user-approved diff is Hermes's own act through its native memory tool — report it as an observed native write, never as OMH mutation evidence. Hermes-native and external provider/vector context is not_omh_reviewed and never inherits OMH approval.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.
- Keep English as the canonical protocol; Korean routing triggers and concise Korean help labels remain available.
- Quote claims only when observed, do not invent provenance, and keep the prepared native diff separate from any native write.
- A memory_provider_posture/v1 block arrives as not_omh_reviewed context and a next-action handoff; it imports no provider record into OMH review and authorizes no native-memory mutation.
- A write Hermes holds in `pending/memory/` is the person's to decide: OMH never approves, rejects, edits, or deletes one, and never proposes turning `memory.write_approval` on or off.

## Runtime Evidence

Preferred harness for this skill: `memory-sync`.

```sh
omh runtime record --skill memory-sync --harness memory-sync --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. Finished work ends with no question and no offer; when a decision only the user can make remains, end with one specific question about that decision, not a list of questions, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
