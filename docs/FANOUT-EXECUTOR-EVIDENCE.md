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

## Executor sessions (`fanout_executor_session/v2`)

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
| Executor | `executor`, `protocol`, `version`, `binary_identity.launch_path`, `binary_identity.resolved_path`, `binary_identity.sha256` |
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
{"available": true, "reason": "copy_only", "argv": ["<launch codex>", "exec", "resume", "<uuid>", "-"],
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
| `reason` | `denial`, `missing_binary`, `spawn_error`, `nonzero`, `deadline`, `malformed_result`, or `internal_error`. |
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

The capacity contract accepted for implementation is deliberately narrow: only
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
