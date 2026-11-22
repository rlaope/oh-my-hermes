# Fanout executor evidence: sessions, failure diagnostics, capacity

Agent/operator reference. Normal users ask Hermes what happened to a coding
run; Hermes reads these records. This page names the exact evidence the fanout
dispatcher persists for issues #1421 (resumable executor sessions), #1423
(bounded failure diagnostics), and #1422 (capacity-aware fanout), and where
each record stops being evidence. The dispatch bridge itself is described in
[`docs/FANOUT.md`](FANOUT.md).

Three rules apply to every record below:

- Executor output is untrusted metadata. Identity comes from the dispatcher's
  own unit, attempt, worktree, and revision lineage, never from text the
  executor printed.
- Nothing here launches, resumes, retries, or merges anything. Records are
  read-only projections of what one explicit `dispatch` invocation observed.
- Raw prompts, transcripts, reasoning, event bodies, and secret-shaped text
  are never persisted under `.omh`. Complete executor event streams are not
  retained.

## Executor sessions (`fanout_executor_session/v1`)

### What is observed

When the resolved executor binary negotiates a supported structured-output
protocol (Codex `exec` JSON lines or Claude Code stream JSON), the dispatcher
decodes stdout frames through a fresh decoder for each attempt and accepts
exactly one canonical session identifier from a supported root event. Stderr
supplies no identity. Nested, duplicate, conflicting, or malformed identifiers,
an unknown protocol, a generic executor, or a truncated capture leave the
receipt `not_observed` or `not_available` with a closed reason. A loose legacy
`session_ref` in an older artifact stays display-only.

Each receipt is bound to the attempt that produced it:

| Field group | Fields |
| --- | --- |
| State | `state` (`observed`, `not_observed`, `not_available`), `reason`, `reference_kind`, `reference`, `event_ref` |
| Executor | `executor`, `protocol`, `version`, `binary_identity.resolved_path`, `binary_identity.sha256` |
| Lineage | `fanout_id`, `unit_id`, `run_ref`, `attempt_id`, `predecessor_attempt_id`, `contract_digest` |
| Workspace | `worktree_path`, `worktree_incarnation` (`incarnation_id`, `common_dir`, `branch`, `device`, `inode`), `base_sha`, `launch_head`, `end_head` |

Every real attempt gets a unique dispatcher invocation ID and attempt ID. A
retry is a new attempt with a `predecessor_attempt_id`; it never inherits the
earlier attempt's session reference. Held receipts from unselected units are
preserved untouched by a partial rerun.

### Where it shows

- `omh coding fanout status --fanout-id <id> --unit <unit> --json` selects one
  observed unit and projects its `executor_session` and `resume` block.
- Unit results, the fanout journal, and the observation journal carry the same
  validated receipt. Old artifacts that lack the field read as
  `legacy_missing`; unknown versions read as unavailable. Nothing rewrites an
  old artifact.
- The wrapper follow-up projection (`build_fanout_session_followup`) exposes
  the selected unit's receipt and resume block to chat with
  `execution_policy: copy_only`. The wrapper status projection
  (`build_fanout_status_interaction`, below) reads the same canonical roster.

### Resume is copy-only

The `resume` block is a projection, not a launch:

```json
{"available": true, "reason": "copy_only", "argv": ["<resolved codex>", "exec", "resume", "<uuid>", "-"],
 "cwd": "<worktree>", "shell_command": "cd -- <worktree> && ...",
 "execution_policy": "copy_only", "required_input": "follow_up_prompt_on_stdin",
 "native_resume_state": "not_tested"}
```

`argv` and `cwd` are exact and shell-quoted for POSIX; Codex requires the
follow-up prompt on stdin, and Claude Code's `--resume=<uuid>` opens an
interactive session. Availability requires an `observed` receipt whose binding
matches the selected unit, a unique reference, an observed `end_head`, and a
fresh workspace observation with the same path, incarnation, and head. A dirty
worktree is actionable only when the dispatcher's recorded recovery digest
matches the current one. Otherwise `reason` names the gap:
`binding_mismatch`, `duplicate_reference`, `end_revision_not_observed`,
`stale_workspace`, or `recovery_snapshot_mismatch`. `native_resume_state` is
always `not_tested`: OMH has not verified that the native session store still
holds that conversation, and repeated status reads launch nothing.

## Executor sessions for user executors

Session receipts for these executors use `fanout_executor_session/v2`. An
executor declared in `<omh_home>/routing/executors.toml`, or a preset, that
declares `session.export` (see [**Your own harness** in `FANOUT.md`](FANOUT.md#your-own-harness))
cannot be decoded frame by frame, so its session evidence is a file receipt.
Only Devin's preset declares an export today, and it is unvalidated until a live
dispatch: the shipped tests use a fake CLI that writes a small JSON object with a
root `session_id`, not a real Devin export. Built-in codex and Claude Code
receipts stay `fanout_executor_session/v1`, byte for byte.

### What is observed

For each attempt the dispatcher creates a private scratch directory inside the
unit's worktree (`.omh-executor-tmp-<attempt id>/`, mode 0700, self-ignoring),
passes the CLI the path of `session.json` in it through the declared export
fragment, and after the process exits observes that one file. The file counts only
if it is a regular, single-link file of at most 1 MiB, opened without following a
link, whose size and timestamps did not change while it was read. It must be
UTF-8 JSON with an object at the root, no duplicate keys, and nesting no deeper
than 32. The dispatcher hashes the bytes and reads one thing from the object: a
root `session_id`, accepted only as a canonical lowercase UUID or `devin-` plus 32
lowercase hex digits. Stderr, stdout, nested fields and earlier attempts' exports
supply nothing.

| Outcome | Receipt |
| --- | --- |
| Valid file with an accepted `session_id` | `state: observed`, `reason: export_digest_observed`, `reference_kind: session_id`, `reference` is the id, `export_sha256` is the file hash |
| Valid file with no `session_id` | `observed`, `reference_kind: export_file`, no `reference`. A hash only, so nothing can be resumed from it |
| No usable file | `state: not_observed`, no `reference`, no `export_sha256`, and a closed `reason`: `export_missing`, `export_unsafe`, `export_unreadable`, `export_not_object`, `export_duplicate_keys`, `export_oversized`, `export_invalid_utf8`, `export_invalid_json`, `export_too_deep`, `export_changing` or `export_invalid_id` (a `session_id` of any other shape voids the whole file) |

A receipt is written for failed and timed-out attempts too, so a missing export
shows as `not_observed` instead of as nothing. It is also recorded before the
post-run Git gates return. Those gates require that `HEAD` descends from the
frozen base and that no commit between the base and `HEAD` touches a scratch
path, even if a later commit removes it. A unit refused with `executor_history_unverified` or
`executor_scratch_committed` still carries `executor_session` and
`executor_session_status` and the same receipt is in the journal. The receipt
describes the export file only; the refusal still fails the unit. It carries the same lineage and
workspace fields as v1 (executor, `fanout_id`, `unit_id`, `run_ref`,
`attempt_id`, `predecessor_attempt_id`, `contract_digest`, `worktree_path`,
`worktree_incarnation`, `base_sha`, `launch_head`, `end_head`,
`binary_identity`, `version`), `protocol: user_export_json`, and these:

| Field | Meaning |
| --- | --- |
| `export_ref` | The export's base name, `session.json`. Never the absolute path. |
| `export_sha256` | SHA-256 of the export file's bytes, or null when `not_observed`. |
| `resume_reason` | Why this attempt did or did not continue a session (below). |

There is no `event_ref` in v2. The `export_ref` is a historical name, not a
promise the file is still readable: when the attempt ends the dispatcher empties
the scratch directory and removes it. Cleanup works through the directory handle
opened when the scratch was created, never through the absolute path. If the
directory was renamed, the original directory is still emptied but stays under its
new name; if a different entry (such as a symlink) now sits at the original path,
it is neither followed nor removed. A tool that moved the scratch directory can
therefore leave an empty directory or its own replacement behind.

### What is never stored

- The export file's contents. Only its hash and its `session_id` are kept. A
  transcript sentinel written into a fixture export is absent from every file
  under the OMH home after a dispatch (`tests/test_user_executor_sessions.py`).
- The export file itself, the absolute path to it, or the prompt. The prompt file
  is removed with the scratch directory too.
- Any argv fragment. A receipt holds no `--export` or `-r` token, and a stored
  receipt is never turned back into argv.
- Account, login or provider identity. The export is read for one id field and
  nothing else.

### Resume is repair-only

The `resume` block for a v2 receipt is always `available: false`, `reason:
repair_only`, with no `argv` and no `shell_command`. `fanout status` renders no
vendor command and launches nothing, whether or not the workspace still matches.

The one place a session is re-entered is a budgeted repair, inside the
dispatcher, for an executor that declares `session.resume`. The repair passes
the declared resume tokens with the id only if the immediately preceding attempt's
receipt is a v2 `observed` receipt with an id, and still matches this unit's
owner, frozen contract, fanout, unit, run and base, the same worktree incarnation
at the head the receipt ended on, the same CLI binary bytes, and a recovery state
the dispatcher re-observed, and no other unit claims the same id. The repair gets
a new attempt id and a new export file; it inherits no observation. Otherwise it
starts a fresh session and its receipt's `resume_reason` says why. The id is
spent at the first launch of a repair, so a transient retry starts fresh.

| `resume_reason` | Meaning |
| --- | --- |
| `same_session` | The repair re-entered the preceding attempt's session. |
| `not_a_repair` | An ordinary first attempt. |
| `no_resume_declared` | The entry declares no `session.resume`. |
| `no_prior_receipt`, `not_user_export` | There was no v2 receipt to continue. |
| `no_id` | The previous export had no usable `session_id`. |
| `binding_changed`, `binary_changed` | The unit, contract, base or CLI binary no longer matches. |
| `stale_workspace`, `recovery_snapshot_mismatch`, `end_revision_not_observed` | The worktree is not the one the receipt ended on. |
| `duplicate_reference` | Another unit claims the same id. |
| `fresh_retry` | A transient retry after the id was spent. |

A session id in a receipt is the CLI's own claim about its own export. It does not
show the CLI was logged in, that the session still exists on the vendor side, or
that the work passed; the git result and the unit's postconditions decide that.

## Failure diagnostics (`fanout_failure_diagnostic/v1`)

### What is captured

Worker and verification processes are drained incrementally on separate binary
pipes; the dispatcher keeps no full raw buffer. When a phase fails, the
diagnostic records exact provenance and a bounded, sanitized view of each
stream:

| Field | Meaning |
| --- | --- |
| `fanout_id`, `unit_id`, `run_ref`, `owner`, `attempt_id`, `worktree_ref`, `base_sha`, `observed_revision` | Dispatcher-owned identity of the failed attempt. |
| `phase` | `preflight`, `worktree`, `launch`, `worker`, `timeout`, `unit_result`, `verification`, or `dispatcher`. |
| `reason` | `denial`, `missing_binary`, `spawn_error`, `nonzero`, `deadline`, `malformed_result`, `internal_error`, `executor_sandbox_read_only`, or `executor_sandbox_start_failed` (the executor's own sandbox refused writes or never started; see [child-environment policy](CHILD-ENVIRONMENT-POLICY.md#codex-on-native-windows)). |
| `returncode`, `exit_code_source` | The observed exit and whether it came from the `process`, was `synthetic`, or was `not_observed` (for example a missing binary). |
| `streams[]` | One entry per stream: `state`, `reason`, `text`, `limit_bytes` (2000), `limit_lines` (20), `original_bytes`, `original_lines`, `kept_bytes`, `kept_lines`, `truncated`, `truncation_reason`, `digest`, `digest_basis: sanitized_utf8`. |

Stream text is retained only when it matches a closed set of safe template
lines. Sensitive markers (authorization headers, bearer tokens, API keys,
passwords, private-key blocks, well-known token prefixes) are screened before
truncation, with overlap across chunk boundaries, and yield `redacted`.
Invalid UTF-8, terminal control sequences, protocol frames, and any other
unknown output are `withheld`; an incomplete capture is `withheld` with
`incomplete_capture`. Original sizes are reported only when the capture was
complete. The digest covers the sanitized text, so it can confirm a repeat
without exposing the original.

Successful phases produce no diagnostic and gain no extra raw retention.
Both streams are kept as separate entries; OMH does not invent a cross-stream
chronology or merge structured events.

### Where it shows

`failure_diagnostic` is the optional field on observed journal events, unit
results, fanout status, and the status board brief. Readers admit it only
through `read_failure_diagnostic` under the current fanout, unit, and attempt
identity: a rerun never borrows an older attempt's failure, a later sidecar
event never hides the relevant one, and old records stay readable without
following any raw spill path. The existing failure-kind and retry ladders are
unchanged; a diagnostic never turns a failure into success or asserts an
execution that was not observed.

Worktree creation failures pass through the same builder before any worktree
record or cleanup journal is written, so a secret in a Git error is screened
before it is sliced or stored.

## Capacity-aware admission (#1422)

The capacity contract is deliberately narrow: only
a source-qualified fresh Codex `exec` JSON-lines initial-turn queue rejection,
observed on the attempt's own process with a complete capture and exact
terminal framing, may trip that executor's launch gate for the rest of the
invocation. Prose, HTTP 429, quota or auth messages, nested tool failures, and
unknown framing are ordinary failures. The classification is process-local; it
is not provider quota truth and does not assert that startup had no side
effects.

### The launch gate

Every agent process a dispatch invocation starts crosses one
`OwnerLaunchGate` immediately around its `Popen`, after owner wait, stagger,
and backoff: initial starts, retries, retargets, and the Hermes-child recovery
chain (`dispatch_unit_via_hermes_child` and `dispatch_hermes_child` accept the
same `launch` seam and keep their confirm-dispatch, stdin-only prompt,
depth-one, and safe-tool semantics). A source-qualified rejection trips the
gate for that executor before any retry, recovery, or slot release, and the
lock never spans a child's lifetime. Work that already started keeps its own
result; unrelated owners keep launching; cancellation stays distinct from
capacity.

By default, `dispatch_fanout(..., capacity_sources=None)` resolves the attempt's
negotiated executable SHA-256 and exact version against the shipped reviewed
build registry, binding the result to the actual resolved executable path.
Only the official Codex 0.154.0 Darwin ARM64 and Linux ARM64/musl binaries in
[the compact provenance reference](FANOUT-CODEX-BUILD-PROVENANCE.md) qualify.
This is not an executor version requirement or release floor. Unknown builds,
including different bytes reporting the same version, remain ordinary failures.
The resolver is local and read-only: no network, operator attestation, or new
client dependency. An explicit `capacity_sources=()` disables recognition;
a supplied sequence remains the path-bound integration/fixture seam.

Recognized launches receive `RUST_LIB_BACKTRACE=0`; exact framing and complete
capture checks are unchanged. The executable identity is checked again after
the process exits. Summary `native_support` reflects only recognized,
postflight-checked launches in this invocation: `source_qualified_build` for a
reviewed native association, `fixture_only` for fixture-only observations, or
`unsupported_without_source_qualified_build` otherwise. A recognized build can
still have an ordinary failure; support is not a rejection or quota observation.
Fixtures carry `evidence_kind: fixture`; reviewed build associations carry
`source_verified`. Neither is vendor saturation evidence.

### What is recorded (`fanout_capacity_unit/v1`)

A capacity record appears only on the attempt that observed or was refused by
the trip. It is the optional `capacity` field of the unit result, the
`capacity_admission_observed` journal event, and the status roster:

| Field | Meaning |
| --- | --- |
| `status` | `executor_capacity_rejected` (the attempt whose process was rejected), `not_started_capacity_blocked` (a later unit the closed gate refused before `Popen`), or `blocked_by_capacity_dependency` (a dependent whose prerequisite was capacity-blocked). |
| `owner`, `fanout_id`, `unit_id`, `run_ref`, `attempt_id`, `invocation_id` | Dispatcher-owned identity of this attempt; a fresh attempt and invocation ID per real start, never a retry index. |
| `process_started` | Whether a process existed for this attempt. |
| `trigger_unit`, `trigger_owner`, `trigger_attempt_id`, `trip_sequence` | The attempt whose rejection closed the gate and its order. |
| `adapter`, `protocol`, `evidence_kind` | `codex_fresh_initial_request_queue`, `codex_exec_json`, and `fixture` or `source_verified`. |
| `definition_revision` | Original classifier definition pin `b83105710695b70b6d96a64d1e4612bdf68d5f92`; not a claim that the released executable was built from that commit. |
| `source_revision` | Associated build source: the definition pin for original fixtures, or reviewed release commit `6b9826e3aa83b1a5947db50f4332cb9c65f1b340`. Legacy v1 records missing this field remain readable without inventing a source association. |
| `scope`, `quota_observed`, `next_action` | Always `process_local`, `false`, and `explicit_bounded_redispatch_after_capacity_change`. |

A companion `capacity_lineage` keeps the blocked unit's owner, base SHA,
planned worktree path, branch, contract digest, and observed worktree
incarnation so a later explicit dispatch can resume exactly that unit. Readers
(`read_capacity_fields`) reject any capacity record whose identity disagrees
with the surrounding unit or whose fields are malformed or foreign; an
otherwise valid legacy record without the field still reads normally.

### Where it shows

- The dispatch summary carries `capacity` (`fanout_capacity/v1`):
  `requested_concurrency`, `effective_concurrency`, `affected_units`,
  `closed_owners`, `native_support`, `quota_observed: false`, and
  `next_action`. Dependents blocked only by capacity are listed with their
  own reason; an implementation failure or a completed prerequisite keeps its
  original evidence.
- `omh coding fanout status` and the status board brief show each affected
  unit's capacity status and next action next to its lifecycle state.
- Resuming a capacity-blocked unit requires an explicit, finite `--unit`
  selection against the prior journal. Reuse of the planned worktree is
  allowed only when the creation ledger, incarnation, base, and clean state
  match and no result artifact exists; dirty, foreign, unknown, or occupied
  state is held, not deleted. No read, status call, or wrapper action
  redispatches anything.

## Wrapper status surface

`build_fanout_status_interaction(paths, fanout_id=..., unit_id=None, source=...)`
in `omh.wrapper.contract` renders the canonical roster for chat. Its
`refresh_status` action carries the read-only `omh coding fanout status`
argv. Only when a unit is explicitly selected and its canonical `resume` block
is available does a `copy_fanout_resume` action appear, with the same
`argv`, `cwd`, `required_input`, and `execution_policy: copy_only` fields.
Capacity and diagnostic metadata pass through unchanged; session refusal
reasons are shown as data. The agent-board chat card's `show_status` action
points at this reader (`docs/AGENT-BOARD.md`).

## Boundaries and QA attribution

- Fixture executors in the test suite are real local processes that emit the
  protocol framing under test. They are labeled as fixtures in every result
  and prove decoding, binding, refusal, persistence, and cleanup behavior.
  They are not native vendor execution.
- Native probes are recorded separately with their own provenance. An
  unavailable binary or credential is reported as unavailable, never turned
  into a native success.
- None of the records above is review, CI, merge-readiness, or merge evidence.
