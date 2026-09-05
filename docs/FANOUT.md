# Fanout: Parallel Split, Dispatch Bridge, and Merge Contract

Audience: operators, wrappers, and coding agents. Normal users describe the
goal to Hermes in chat; these commands are the backend surface.

## Lifecycle

1. **Propose** — Hermes (the LLM) proposes the unit split in chat: unit ids,
   titles, owners, file boundaries, dependencies.
2. **Freeze** — `omh coding fanout prepare --goal <words> --units units.json
   --record` validates the split deterministically (boundary overlaps without
   a `depends_on` edge are hard errors; dependency cycles are hard errors; a
   split wider than four units with no spawn plan is a hard error, see
   **Spawn plan** below) and freezes it as `fanout_contract/v2` with one
   deterministic capability snapshot per assigned owner under
   `~/.omh/coding/fanout/<id>/`. The goal is stored as a digest only.
3. **Dispatch (opt-in bridge)** — `omh coding fanout dispatch <id>
   --goal-file goal.txt` spawns each spawnable unit's local agent CLI in an
   isolated per-unit worktree, dependency-aware, with bounded concurrency.
4. **Observe** — `omh coding fanout show <id>` joins the frozen contract with
   per-unit run records; unit status is `not_observed` until real evidence
   exists. The board reads a bounded tail (last 20 events) of each unit's run
   history, so repeated checks cost the same context instead of growing with
   the run. `--limit N` changes the tail; `--full` reads everything and is
   expensive for agent context.
   For user-facing briefings, `omh coding fanout brief <id>` renders one
   line per unit in merge-plan order — unit, owner, `(model effort)` label
   (for example `(gpt-5.6-sol xhigh)`), status, elapsed seconds, token
   count, session ref, last observed summary — as plain text by default
   with `--json` for the `fanout_briefing/v1` payload. It joins the
   contract, the persisted dispatch summary, and a one-event journal tail;
   unknown fields stay the literal `unknown` rather than being inferred,
   and never-dispatched units keep `prepared_not_observed`. Without an id
   it lists known fanouts. Session refs and token counts are `unknown`
   until a structured-output dispatch contract lands (deliberate deferral
   — the current templates keep executor stdout as opaque bounded text);
   executor-progress bindings for `omh runtime progress-status` are
   deferred with that same follow-up.
5. **Merge (human/agent-gated)** — dispatch never merges. The summary lists
   merge-ready units in the contract's `merge_order`; merging and the final
   integration gate remain the operator's or reviewing agent's job.

## Single-run entry (`omh coding run`)

The four-step ceremony above is built for a proposed multi-unit split; one
already-chosen owner running one prepared task never needed it.
`omh coding run --owner <profile> --goal <words...>` (or `--goal-file`)
builds a one-unit `fanout_contract/v2` and calls the same `dispatch_fanout`
engine in a single call — propose/freeze/dispatch collapse into one
invocation, never a parallel spawn implementation. Everything above still
applies unchanged at unit count one: an isolated per-unit worktree
(`<repo>-fanout-<unit-id>`, branch `agent/<unit-id>`; a single run is never
defaulted to the repo's own worktree, so its claim boundary stays exactly as
narrow as a multi-unit fanout's), the executor-progress binding that drives
the `(<executor>/maestro <model>)` HUD row, model routing and the
dispatch-model-preference fallback, session/thread id capture, unit result
intake, and the run summary. The contract is written under
`~/.omh/coding/fanout/<id>/` exactly like `fanout prepare --record`, so
`omh coding fanout show/brief/reap` all work against it afterward.

`--model`/`--effort` set this one run's own model choice, unvalidated
passthrough to the spawned CLI; precedence is `--model` flag > routed
handoff model > `dispatch-models.json` preference > the executor CLI's own
default, and the value the flag resolves to is what the HUD row and the
recorded unit result both show.

Dispatch stays explicit per invocation and never merges: running this
command against an explicitly-named owner IS the opt-in — there is no
separate confirmation step to add on top of an operator (or an agent acting
on the operator's own owner-naming message) typing the command.

```sh
omh coding run --owner claude-code --goal "Research pricing approaches and write a summary." \
  [--goal-file prompt.md] [--unit-id run] [--file-scope . ] [--repo-root .] [--base-ref HEAD] \
  [--timeout 1800] [--dry-run] [--run-verification] [--model opus] [--effort high]
```

The claude-code dispatch template's `--allowedTools "Bash(git add:*),Bash(git
commit:*)"` (see **Spawnability is data** below) is unchanged by this entry
point: it was scoped to the git verbs a coding unit's prompt asks for, so a
non-coding single run (a pure research brief, for example) may complete with
no git side effects, or may need a Bash call the template does not grant —
the host's own `--permission-mode` is what actually governs the spawned CLI,
and a tighter or looser tool policy is a separate, explicit decision on that
template, not something this entry point silently widens.

## Spawn plan

A split into more than four units has to say why. Up to four, the shape is
small enough to read at a glance; past that the contract stops recording an
obvious decomposition and starts recording a guess, and the cost of a wrong
guess is N worktrees of thin work nobody can merge.

The plan rides in the units payload's object form rather than behind its own
flag, so the justification and the split it justifies live in one file:

```json
{
  "units": [ ... ],
  "spawn_plan": {
    "why_parallel": "Five disjoint subsystems each own their own test lane.",
    "why_not_single_unit": "One executor would serialize five unrelated verification loops.",
    "independence": "No unit reads or writes another unit's file_scope.",
    "expected_evidence_shape": "Per-unit run record plus the unit's own focused test command."
  }
}
```

Rules:

- All four fields must be strings. Each is collapsed to a single line and
  bounded at 280 characters. A list, number, or boolean is refused rather
  than coerced — its Python repr would pass the blank check while being
  exactly the answer nobody wrote.
- A plan supplied at all must be complete, at any width. A half-filled plan
  reads as an answer nobody wrote, so it is refused rather than frozen —
  below the threshold the fix is to complete it or drop the key entirely.
- The gate runs **last**, after the boundary-overlap and dependency-cycle
  checks. A split that can never be frozen fails on its structure, so the
  operator is not asked to justify a decomposition they will have to rewrite.
- A key that is `spawn_plan` with different punctuation or case (`spawnPlan`,
  `spawn-plan`) is a hard error naming the intended key, not a silent drop.
- An accepted plan is frozen into the contract as an optional top-level
  `spawn_plan` key carrying the four answers, the observed `unit_count`, the
  `threshold` in force, and a claim boundary. A split that needed no plan
  gains no key, so contracts frozen before this gate existed keep their exact
  shape.
- A spawn plan is prepared operator justification. It is not evidence that
  the split is correct, that the units are independent, that the named
  evidence shape was produced, or that any unit ran.
- `omh coding fanout validate` runs the same checks in the same order and
  reports `unit_count` and `spawn_plan_required` on both its success and its
  error payload, so a wrapper can ask for a plan before `prepare` refuses the
  freeze, and can always parse the answer as JSON.

## Dispatch bridge semantics

- **Concurrency is fixed by default and adaptive only when requested.** The dispatch pool width comes from
  the setup profile's `parallelism` block — `default_concurrency` (5) sized
  against a `global_concurrency` ceiling (8), the same defaults OMO's task
  engine ships. A fresh `omh setup` writes the block into the profile so it
  is visible and editable; an explicit `--concurrency` flag still wins,
  clamped to the ceiling. Without another flag, scheduling remains fixed-width.
  `--adaptive-concurrency` makes that resolved concurrency the ceiling, starts
  the admission window at 2 (capped by the ceiling), grows it by one after an
  observed clean completion, and halves it with a floor of 1 after observed
  provider-limit pressure. Pressure includes a final `limit_shaped` result or
  a `transient_provider_limit` retry decision even when the retry recovered;
  auth, timeout, missing-binary, crash, terminal test/code, and ordinary
  transport failures do not reduce the window. Ready dependency-frontier units
  are submitted only while they fit the current window; a reduction does not
  cancel units already running.

  The dispatch summary's `concurrency` block records the requested and applied
  ceiling plus its source. Adaptive mode additionally emits a bounded,
  metadata-only `adaptive_admission` (`fanout_admission/v1`) receipt with the
  initial, ceiling, final, and minimum windows and unit-id/status-class
  adjustments. It includes no raw output and is not provider quota,
  verification, review, CI, or merge evidence. A dry run reports
  `not_observed_dry_run`, zero observed completions and pressure, and no
  adjustments; planned units are not successful execution. `per_owner`
  maps an executor owner (for example `codex: 2`) to its own lane width so
  one rate-limited provider is not hammered by the whole pool; owners not
  named there are governed by the global pool alone. A gated owner's units
  hold pool slots while they wait for a lane, so many same-owner units
  queued ahead can delay another owner's ready units — size
  `per_owner` with that trade in mind. An install written before this
  block existed resolves to the same defaults without showing the block;
  re-running `omh setup` writes it out, and rewrites the whole profile
  while doing so. `lane_budget_default` is advisory context for
  Hermes-native lanes — OMH never enforces a lane count inside Hermes.
- **Dispatch does not nest, and one run has a total spawn budget.** Every
  child this command starts — the agent CLI and any declared verification
  command — is stamped with `OMH_FANOUT_DEPTH` and `OMH_FANOUT_LINEAGE`. A
  dispatch that starts inside such a child reads its inherited depth and
  refuses before any subprocess exists, returning a dispatch summary carrying
  `refused: true`, `refusal_reason: "fanout_depth_exceeded"`, and a
  `spawn_guard` block naming the depth, the cap, and the lineage it came down;
  the CLI exits 1. Separately, one run may only ever START
  `run_spawn_ceiling` agent processes (default 60, OMO's own
  `DEFAULT_FANOUT_LIMIT`); a unit that arrives after the budget is spent
  returns `spawn_ceiling_reached` before its worktree is created, so nothing
  is left behind to clean up. Both are `parallelism` block tunables
  (`max_depth`, default 1) read with the same validated-override-plus-
  disclosure shape as the widths, and both are recorded in the summary's
  `spawn_guard` block alongside how much of the budget the run used. Neither
  is verification, review, or merge evidence — a run inside its bounds is not
  thereby correct.
- **Retries are classified, and never replayed over observed work.** A failed
  unit is retried only when both answers come back yes, in this order. First,
  is the failure transient? A provider rate limit, an overload, an HTTP 5xx, a
  socket reset or hang-up is the executor's transport failing; a real non-zero
  exit from a test or verification run is the unit's own answer and is
  **terminal**, never retried. A timeout and a missing executable get their own
  terminal classes. Second, is the unit replay-safe? Only a unit that has
  produced **no observed side effect** may be re-dispatched: the recovery probe
  measures the worktree, and `recovery_available` (files written) or
  `capture_failed` (unmeasurable) both block the replay — "I could not tell"
  fails closed. A result sidecar on disk blocks it too. A transient failure
  that is not replay-safe is surfaced through the existing
  `recovery_available` path as work to **continue**, with
  `retry_blocked_by_side_effects` on the unit entry, rather than silently
  re-run from base — which would destroy exactly the work the failure left
  behind. Backoff is `min(2s * 2^(attempt-1), 30s)` scaled by 75–100% jitter,
  bounded at two retries, so a fanout of N units that all hit one rate limit
  does not retry in lockstep and re-trigger it. Every attempt spends the
  `run_spawn_ceiling` budget like any other spawn. The unit entry's `retry`
  block records the attempts and the reason trying stopped — `terminal`,
  `retries_exhausted`, `surfaced_for_continuation`, `spawn_ceiling_reached`,
  or `interrupted`; a unit that succeeded first try carries no block at all. A
  retry is another attempt, not evidence: a unit that passed on attempt three
  is no more verified than one that passed on attempt one.
- **Admission is dependency-frontier, not wave-barrier.** A unit starts the
  moment every unit it depends on has completed and a pool slot is free —
  never because a wave boundary was reached — so an unrelated slow sibling
  cannot starve ready dependents (OMO's DAG scheduler discipline). The
  wave grouping in `merge_order` is informational; merge order itself is
  unchanged. A seeded chaos bench (`tests/test_fanout_chaos.py`, replay
  with `SEED=<n>`) drives random DAGs, outcomes, pool widths, and owner
  lanes through the real engine and holds the scheduler invariants.
- **Units are process groups; interrupts are honest.** The default runner
  spawns each unit as its own session/process group and records the leader
  pid in the unit's inflight marker. A timeout kills the whole group (no
  surviving grandchildren against the worktree). Ctrl-C stops admitting
  work, terminates every live group, marks never-started units
  `interrupted`, prints the summary with `"interrupted": true`, and exits
  130. SIGTERM writes the same summary FILE but prints nothing: the
  original termination is re-raised after the write so a supervisor
  observes the death it asked for, and the process exits 143. If the
  dispatcher dies without cleanup, `omh coding fanout reap` terminates the
  marker-named groups — liveness is judged at the GROUP level (a dead
  leader with live grandchildren stays reapable), a live pid no longer
  leading its own group is refused as recycled, and a pid the markers do
  not name is refused whatever its process name. The reaper does not check
  that the dispatcher is dead — verify that first; a live dispatcher's
  running units are equally marker-named.
- **Each spawned unit opens an executor-progress row.** Before the spawn,
  dispatch opens an `omh_executor_progress_binding/v1` on the unit's run
  (`target_type: run, target_id: <run_ref>`) tagged `delivery.source:
  fanout_dispatch`, reports an `executor_dispatched` event carrying the
  unit's title and its routed (or preference-filled) model, and updates the
  binding's pid once the real spawn hands one back — the same seam the
  inflight marker above uses. On exit it reports `executor_completed` or
  `executor_failed`, carrying whatever tokens/cost the spawned CLI's own
  stdout reported (`unit_telemetry`, never estimated) and closing the
  binding, which is what stops the row — a closed binding drops out of the
  HUD's active-executor projection on the next read. The HUD reader labels
  these rows `(<executor>/maestro <model>)`, alongside Hermes-native
  delegate_task rows, because a fanout unit IS the Maestro lane spawning an
  external CLI directly, and derives the row's `elapsed_seconds` from the
  binding's own opened timestamp against wall-clock now so a live row shows
  real running time instead of the widget's snapshot-age fallback. Cost is
  NOT a live figure for this lane: the spawned CLI reports it only in its
  terminal result object, so `cost_usd` never has a value until the unit's
  binding closes on exit, and a closed binding drops out of the active-row
  projection before the next read — a finished unit's cost still surfaces
  wherever closed rows are reported (the dispatch summary, `omh coding
  fanout brief`), just never on a still-running row. Every write here is
  best-effort: an `ExecutorProgressError` or `OSError` never blocks or fails
  the dispatch, the same rule the inflight marker already holds; the binding
  now opens and closes inside the same `try`/`finally` so a Ctrl-C or other
  interruption during the spawn cannot orphan a live row with no closer.
- **Spawnability is data.** `DISPATCH_COMMAND_TEMPLATES` in
  `src/coding/fanout_dispatch.py` maps profiles with a local headless CLI to
  fixed argv templates — currently codex (`codex exec`), claude-code
  (`claude -p`), and omo-runtime. The omo runtime's host CLI is DETECTED at
  dispatch/readiness time in a fixed order (`pi`, then its `senpi`
  distribution, then `opencode`) — first on PATH wins, no personal stack is
  hardcoded, and the selected host is visible in the planned argv and the
  probed command. The pi-family surface was validated in a live bridge
  dispatch; the opencode template is prepared from its verified flags and
  validates on first live dispatch (claude-template precedent).
  Profiles without a template (hermes, omx/omc runtimes, generic,
  unassigned) are reported `unsupported_for_local_dispatch` with the unit
  handoff as a prepared-prompt fallback — no profile is privileged.
- **Bridge dispatch is a separate axis from chat prompt-handoff.** Chat
  surfaces keep their prompt-only semantics for prompt-only profiles (a
  `coding_prompt_handoff/v1` record stays `dispatchable: false` no matter
  what the bridge can do); the bridge — `omh coding fanout dispatch` for a
  multi-unit split, `omh coding run` for one unit — is an operator-invoked
  command on a different surface, and it is what actually spawns
  claude-code, not the chat-prepared record.
- **Goal integrity.** `--goal-file` must hash to the digest frozen in the
  contract; a diverged goal is refused.
- **Safety-profile integrity.** The contract also freezes the
  `safety_profile_revision` it was prepared under. Dispatch re-checks it beside
  the goal digest, before discovery, readiness probing, any spawn, and any
  write; a drifted or unprovable profile is refused and the contract must be
  re-prepared. Legacy v1 migration preserves an absent revision as "not gated"
  in the resulting v2 contract; v1 itself never dispatches.
- **Owner-readiness integrity.** Each unit's owner is rechecked immediately
  before its handoff. A stored readiness observation counts only while it is
  still fresh and still bound to the same profile, tool, permission profile,
  and workspace; a decision that no longer describes this machine reads
  `stale`, never `ready`. The unit then comes back `executor_not_ready`
  carrying `pre_handoff_repair_card/v1`, which names the prerequisite that
  moved and the commands that confirm it. Dispatch never re-probes on its own:
  `omh coding executor-readiness --executor <profile> --force` is the only
  thing that replaces a stale observation.
- **Worktrees.** One per unit at `<repo>-fanout-<unit>` on branch
  `agent/<unit>`, all branched from one SHA resolved at dispatch start
  (`--base-ref`, default HEAD). Pre-existing paths or branches are errors,
  never silently reused. Worktrees are never auto-deleted; reconcile with
  `git worktree list`.
- **Evidence.** Each dispatched unit gets a run named by its `run_ref`;
  spawn and exit are recorded as journal observations
  (`worker_dispatch`/`worker_result`, canonicalized to
  `executor_dispatch_observed`/`executor_result_observed`).
- **Executable verification (opt-in).** A unit may declare
  `verification_commands: [...]` beside its prose `integration_checks`. The
  field is optional and additive — a unit that declares none carries no key and
  its contract stays byte-identical to one frozen before the field existed. At
  freeze time each command is bounded (at most 8 per unit, 240 chars each), may
  not be blank, and is split with `shlex` so a command no dispatcher could run
  is refused while the operator is still holding it. Leading `NAME=VALUE`
  tokens become environment overrides (this repo's own gate is spelled
  `PYTHONPATH=tests uv run ...`); everything after them is an argv run with
  `shell=False`, so pipes and redirections are argument text, not operators.
  `omh coding fanout dispatch --run-verification` — explicit, never on by
  default — runs those commands with `cwd` set to the unit's own worktree,
  after that unit's process exited 0 *and* its sidecar validated, with a
  10-minute ceiling per command. Each command becomes a check row omh both
  reported and observed (`reported_by`/`observed_by: dispatcher`,
  `observation_source: dispatch_verification`), validated through the same
  `fanout_unit_result/v1` gate every executor-written row goes through. Only
  when every command passes does dispatch append the unit's
  `unit_verification_observed` journal event, which is what flips that rung of
  the ladder — the semantics are unchanged, the observation is simply one omh
  made itself instead of one a human recorded with `omh runtime observe`. Any
  failure appends nothing, leaves the unit short of `integration_ready`, and is
  reported in `verification_failures` with the exit code and a bounded output
  tail. A command that cannot start is a failed check, never a failed dispatch.
  Under `--dry-run` the flag only names the commands in
  `planned_verification_commands`. This runs inside the same sanctioned
  dispatch bridge as the unit spawns themselves: still operator-invoked, still
  local, still no merge and no network from omh.
- **Verification plans, tiers, and receipts (opt-in).** Beside bare
  `verification_commands`, a unit may declare `verification_checks` — the
  additive, structured sibling (declare one or the other, never both; the
  command list is then derived from the checks). Each check names its
  `command` plus optional `id`, `tier` (`unit` default, or `integration`),
  `safety` (`stateful` default, or `read_only`), `resource_class`
  (a validated lowercase resource name such as `local_cpu`, `shared_repo`, or
  `postgres-acceptance`; equal stateful names serialize),
  `claim_scope` (closed and tier-bound: `unit_verification` or
  `integrated_verification`), `depends_on` (sibling check ids; unknown, self,
  or cyclic references are refused at freeze), and `timeout` (an integer that
  may only narrow the 600s ceiling). Declared
  checks compile to a `verification_plan/v1`: typed nodes with stable ids,
  executor-neutral, identical in every lane. At dispatch, read-only
  unit-tier checks run as a bounded parallel wave whose width is the same
  policy-resolved concurrency the unit pool runs with — never a new
  unbounded pool. One dispatch-scoped execution gate is shared by every unit
  plan and the post-integration wave, so concurrent units cannot multiply that
  width; `stateful` checks serialize on their resource class even across plans,
  and a check starts only after every check it depends on has passed. A failed
  check blocks its dependents (recorded `skipped`, never run) while unrelated
  checks finish. Integration-tier checks hold until every selected and actually
  produced lane has passed unit-tier verification (or intentionally declared
  none) **and** the caller supplies one clean, exact integrated checkout with
  `--integration-worktree <path> --integration-revision <HEAD^{tree}>`.
  After each executor exits, dispatch itself proves the producer worktree is
  clean, resolves canonical `git rev-parse HEAD`, and requires exact full-SHA
  equality with the sidecar before recording producer evidence. It ancestry
  checks that dispatcher-observed SHA against the integrated checkout; a
  forged base sidecar, a dirty producer, or a clean base that omits a producer
  commit stays HOLD. Unselected lanes never participate in partial-dispatch
  fan-in. Fan-in alone never claims integration. The full gate then runs once
  against that supplied tree, never a producer worktree. This is an explicit
  two-stage flow: producer checks first in their own worktrees, then one broad
  gate in the caller-supplied integrated checkout. Every executed check files an immutable
  `verification_receipt/v1` under `~/.omh/coding/verification-receipts/`,
  keyed by repository/worktree identity + exact revision (the worktree's
  tree hash) + normalized argv + toolchain/config digest (executable bytes,
  the exact structured-check execution environment, and relevant lock/config
  files) + claim scope. Structured checks inherit only a closed non-secret
  runtime/platform/temp/CI/fanout-lineage environment; any additional value
  must be declared explicitly. A secret-shaped declared override
  (`*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `*_KEY`, `*_PIN`, credential, or auth
  name) still reaches that check but disables receipt reuse entirely: the
  check runs fresh and files no receipt, so no persisted key supports offline
  value guessing. Metadata-free legacy commands keep their historical full
  environment. Non-secret environment values remain exact invalidators. Receipt filenames accept only
  64 lowercase hexadecimal characters and every load, store, and lock proves
  the non-symlink destination remains beneath the receipt directory. Dirty or
  untracked worktrees produce no reusable revision evidence. Any key
  component changing — a new revision, one argv token, an env override, a
  lockfile, claim scope, tier, dependency edge, safety, resource class, or
  timeout — is a different receipt, never a mutation:
  cached evidence cannot cross revisions and cannot be silently upgraded to
  a broader claim. Two consumers resolving the same key share one process
  and one receipt; the second consumer's row carries `reused: true` and a
  `verification_receipt:<key>` ref. Receipts retain metadata only (key,
  check id, timestamps, duration, status, revision, dependency ids, claim
  scope) — never command text, env values, or command output; failure detail
  stays behind the bounded-tail-plus-spill path. A missing, stale, or
  scope-insufficient receipt is treated as missing evidence: the aggregate
  appends `unit_verification_observed` only when every check holds fresh or
  reused in-scope passing evidence, exactly the HOLD semantics a failure has
  always had. **Migration:** contracts without `verification_checks` are
  untouched — they freeze byte-identically, run the legacy serial loop in
  declared order, and produce the same rows and journal event as before.
- **Dependency bar.** A satisfied dependency means only that the owner agent
  process exited 0. It is not verified, reviewed, or correct work. Failed
  units block their dependents, never their independents.
- **Frozen capability evidence.** Newly prepared assigned-owner handoffs carry
  `fanout_contract/v2` plus
  `executor_capability_snapshot_policy: frozen_required`. Dispatch validates
  `unit.owner`, `handoff.executor_target`, and the snapshot executor before
  readiness or spawn. Missing, malformed, or mismatched evidence returns
  `capability_snapshot_invalid`; that status blocks dependent units and is
  projected as blocked work on the coordination board. Legacy contracts
  under `fanout_contract/v1` must first be upgraded with the operator command
  `omh coding fanout migrate-legacy <fanout-id>`. Migration resolves and
  freezes one capability snapshot per assigned owner, writes v2 plus closed
  provenance, and only then permits dispatch; v1 never dispatches directly.
  If the pre-upgrade artifact has no provenance sidecar, the first migration
  call is a dry preview that prints its exact SHA-256 and a confirmation
  command. Existing sidecars are validated before migration, so a drifted
  legacy payload is never silently re-blessed.
- **Local trust boundary.** Contract provenance detects accidental or partial
  local drift. It is not authentication against a process or operator that can
  rewrite both the contract and its provenance under OMH home; such a writer
  already controls this local execution surface. No OMH claim relies on the
  digest as a secret, signature, or remote attestation.
- **Blocked-by-design cascades.** An `unsupported_for_local_dispatch`,
  `executor_not_ready`, `capability_snapshot_invalid`, or
  `model_choice_required` dependency (a frozen
  route that reserves the model choice is never dispatched on the silent
  executor default — re-prepare the unit with a declared model or a
  resolvable role) also blocks its dependents — dependents must
  never build on an unstarted base. Recovery: complete that unit manually (or
  via its owner's own tooling), record its observed result on the unit's
  `run_ref` run, then re-run `dispatch --unit <dependent>`; completed units
  satisfy dependencies even when not re-selected. Blocked entries carry a
  `blocked_on` list naming the offending units.
- **First-use validation note.** `codex exec` has in-repo precedent. The
  claude template was validated in a live dispatch (2026-07): `acceptEdits`
  alone let the agent create files but blocked the requested `git commit`,
  so the template additionally grants `--allowedTools
  "Bash(git add:*),Bash(git commit:*)"` — exactly those two git verbs,
  nothing broader. The pi-family template was validated in a live bridge
  dispatch (2026-07, senpi distribution): a routed unit spawned non-interactively via
  `--print --no-session`, the `workspace` permission preset allowed file
  creation plus the exact `git add`/`git commit` the unit prompt asks for
  (the unit completed with a real commit inside its isolated worktree, no
  interactive prompt), and a missing provider key and an inactive plan each
  surfaced as a clean exit-1 failure with bounded output (feeding the usual
  limit-signal path). Template drift
  in any CLI surfaces as a clean readiness or exit-code failure recorded as
  observed evidence, and the fix is a one-line data edit in
  `DISPATCH_COMMAND_TEMPLATES`.
- **Model routing.** A unit may declare `model`, `reasoning_effort`, and/or
  `role` (brain, implementation, design_visual, review, docs, research —
  research is the read-only investigation lane). Research units may also
  declare `depth` (shallow | standard | deep) — an explicit dial, never
  inferred from text, matching the surveyed autorouting consensus:
  standard is the default chain, shallow swaps in the declared fast-tier
  sweep, deep swaps in the declared frontier-tier chain (locally-derived
  catalogs source these from the user's own quick and deep/ultrabrain
  categories), and the swap (or the reason none happened) is recorded in
  `attempted[]`. Requested model/effort still always win. Prepare embeds
  the resolved `coding_model_route/v2` in the unit handoff, and dispatch
  turns it into argv fragments (`codex --model … --config
  model_reasoning_effort=…`; `claude --model … --effort …`). Resolution is a
  four-stage pure pipeline — requested model > role chain head > chain gap
  (explicit choice) > executor default — and every route records its
  `provenance` plus a per-stage `attempted[]` trail. Roles resolve against
  ordered per-profile chains (`ROLE_MODEL_CHAINS`); entries after the
  selected head are prepared next-candidate advice — omh never retries or
  switches models itself. A requested reasoning effort that a catalog-known
  model does not support steps down an ordered effort ladder with a typed
  `effort_change` record; for models the catalog has not met the request
  passes through untouched (the catalog is a default candidate list, not an
  allowlist, and it never adjudicates a model it does not know). No route
  means the argv stays byte-identical to the base template *unless* the
  operator's dispatch-model preference fills the gap (below); with neither, the
  executor CLI default model applies. Model availability and entitlement are
  provider truth; a routed model that the CLI rejects surfaces as a normal
  observed exit failure. `omh coding model-route` previews a single route;
  `omh coding model-route --explain` renders the full profile × role
  resolution matrix with chains and provenance. Contracts frozen before the
  v2 bump may embed `coding_model_route/v1` routes — they are read verbatim
  (the brief annotates them `[schema v1]`), never rewritten.
- **Dispatch-model preference (fallback only).** `<omh_home>/routing/dispatch-models.json`
  (`omh_dispatch_model_preferences/v1`, `{"schema_version": ..., "profiles": {"codex": "...", "claude-code": "..."}}`)
  names a per-owner `--model` value dispatch uses only when a unit's prepared
  handoff routed no model at all — it never overrides a resolved
  `coding_model_route/v2`/`v1`, and a frozen `choice_required` route still
  fails closed before this is ever read. Full precedence for `omh coding
  run`: its own `--model` flag > a routed handoff model > this preference
  file > the executor CLI's own default. Editing the JSON file directly is
  the supported surface; there is no dedicated CLI editor. No profile ships a
  default: a model an account is not entitled to is an observed exit failure
  with no fallback walk, so an unset entry — meaning the spawned CLI's own
  default — is the out-of-the-box behavior for every profile, including
  `claude-code`. **Recommended**, not shipped: an operator who wants the
  strongest claude-code tier and knows their account carries it can set
  `"claude-code": "opus"` themselves (this codebase's own model-family alias
  set, `_CLAUDE_TIER_ALIASES` in `src/coding/model_routing.py`, recognizes
  `opus` as a claude-family model id; whether `claude --help` documents it as
  a `--model` alias on a given install is unverified here). `codex` has no
  recommended value either (no local `codex` CLI in this repo to confirm its
  `--model` value space against). An operator profile entry, including an
  explicit empty string, always overrides an unset default.
- **Category-maestro (operator category chains).** The Hermes-native
  delegation lane routes per work category through an editable mixture
  (`omh model-chains`); `<omh_home>/routing/category-maestro.json`
  (`omh_category_maestro/v1`) is the same dial for the Maestro lane. It
  overrides individual categories of the built-in category → model table for
  the dispatchable profiles (`codex`, `claude-code`); unmentioned categories
  keep the built-in chain, and the merged table feeds every path that
  consults categories — a unit's explicit `category` (ulw-\* aliases
  accepted), role chains, the research `depth` dial, and the task `scale`
  dial. A route resolved against the merged table records
  `catalog_kind: "operator_category_config"` plus the config's fingerprint,
  so a frozen contract names the exact basis it was resolved from; the
  file's presence is the opt-in, and codex/claude-only contracts stay
  byte-identical across machines that have not created it. Edit it with
  `omh coding category-maestro set <profile> <category> <model[:effort]>...`
  (the tail after the last colon is the effort only when it is a known level
  — off/minimal/low/medium/high/xhigh/max/auto — so colon-tagged model ids
  like `qwen2.5-coder:7b` stay intact) or walk it guided with
  `omh coding category-maestro interview` (also offered by the interactive
  `omh setup` maestro step; non-terminal callers get the scriptable path
  named instead of a hanging prompt), inspect the effective table with
  `omh coding category-maestro show` (operator overrides are marked, invalid
  config pieces are named, a broken file reads as absent and never blocks a
  dispatch), and restore a built-in chain with
  `omh coding category-maestro clear <profile> <category>`. `omh coding run
  --category <category>` routes one run through the same table; an explicit
  `--model` still wins (requested > chain head). Catalogless profiles are
  deliberately not configurable here — the local-inventory catalog remains
  their single override source, so "which basis resolved this route" always
  has one answer.
- **Request complexity (advisory).** `omh coding complexity "<request>"`
  scores a request deterministically — no model, no network — and returns a
  tier (`light` / `standard` / `deep`) with every contributing signal named,
  weighted, and carrying its own evidence. The score is exactly the sum of the
  listed signals, so a tier is always explainable from the payload alone.
  Signals: `architecture_keywords` (+3), `impact_system_wide` (+3),
  `subtasks_many` (+4), `exhaustive_search` (+4: "find every reference / all
  usages / every occurrence" reaches `standard` on its own, because recall is
  the whole task and the 2026-09-05 `live-model-tools` run showed the `quick`
  head tying the flagship on every class except that one), `risk_keywords`
  (+2), `debugging_keywords` (+2), `fanout_intent` (+2), `cross_file` (+2),
  `message_length` (+1/+2), `routed_skill_class` (+1/+2), and
  `simple_request` (−2, the only signal that subtracts). The tier names a model *class* — a `MODEL_CATEGORIES` member —
  which resolves through the user's own
  `<omh-home>/routing/model-chains.json` chains, so no model id is ever
  hardcoded; a class the user's chains do not cover is named as
  `class_not_in_chains` rather than substituted. `--model` / `--effort` record
  an explicit choice, which supersedes the recommendation (still printed, so
  what was set aside stays visible). The same two blocks
  (`request_complexity/v1` and `complexity_model_recommendation/v1`) ride every
  prepared handoff from `omh coding delegate`. This is a recommendation, never
  a route: the declared `role` / `depth` / `category` / `scale` dials that
  `resolve_model_route` reads stay declared by the caller, never inferred from
  phrasing.
- **Model inventory (reporting-only).** `omh coding model-inventory` reports
  which coding models the user has locally activated before any split or
  delegation is proposed: agent CLIs on PATH (codex, claude, opencode,
  gemini, grok, qwen), models named by the oh-my-openagent config
  (`~/.config/opencode/oh-my-openagent.json` — model/variant/fallback ids
  only), opencode provider-config and auth provider key NAMES
  (presence-only, values never read), and the existing executor login
  markers. Every identifier passes the opaque-metadata shape gate; rejects
  are counted, never echoed, and unreadable sources report a status without
  a path. The payload aggregates models with their `model_family()` and
  ships static domain-affinity notes (for example X-platform data work
  favors the grok family) under their own claim boundary: editorial
  defaults, not observed capability, no routing effect. The inventory never
  enters a model route, a frozen contract, or persisted state — it is
  read-time advisory context for the operator or wrapper proposing a split.
  A compact hint (families present, model count, the full-report command)
  rides the choose-executor context automatically, so Hermes proposes owners
  from what the user actually has instead of asking blind.
- **Inventory-derived routing (fingerprint-recorded).** For profiles without
  a built-in model catalog, the command layer derives a
  `local_model_catalog/v1` from the observed inventory — today that means
  the OMO runtime, whose role chains come from the user's own omo category
  config (ordered category→role sources declared as data). Built-in
  catalogs always win; the derived catalog applies only to the profile it
  names; and it never gains effort authority (observed config variants are
  evidence of use, not of a model's effort vocabulary, so requested ladder
  efforts pass through untouched). A route resolved this way records
  `catalog_kind: "local_inventory"` plus a `catalog_fingerprint` (model-set
  digest, per-source statuses, observation time) so the frozen contract
  names the exact basis it was resolved from. At dispatch, units carrying a
  fingerprint gain an advisory `inventory_fingerprint` note comparing the
  frozen digest against the current one — a mismatch never blocks (the
  frozen contract stays the instruction; provider truth adjudicates), it
  only makes prepare-vs-dispatch skew visible. `omh coding model-route
  --from-inventory` previews these routes; fanout prepare consults the
  derived catalog automatically. A unit may additionally declare an explicit
  work `domain` (closed vocabulary riding the catalog payload — for example
  `x_platform_data`, whose affine family is grok): affine-family entries are
  stably moved to the front of the locally-derived chain, the reorder (or
  the reason none happened) is recorded in the route's `attempted[]` trail,
  and the declared domain rides the frozen route. Never a veto: every entry
  stays in the chain, built-in chains are never reordered (a domain there is
  recorded and explicitly skipped), a requested model still wins, and no
  text matching ever infers a domain.
- **Composer calibration.** The MAIN agent composing the split runs on
  whatever model the user configured (a claude-family fable/opus, a
  gpt-family sol/terra, a gemini, a kimi, ...), and each family fails
  composition differently. `omh coding composition-guide --model <id>`
  returns the discipline that agent applies to ITSELF while writing the
  split, the unit prompts, and the briefings — same family key set as the
  subagent calibrations (parity-gated), generic fallback for unmet
  families, selected by the composer's own model id (provider prefixes
  welcome).
- **Unit prompt protocol.** Every dispatched unit prompt carries a fixed
  verification discipline (`src/coding/unit_prompt_protocol.py`): the
  subagent first echoes the goal, its deliverable, and the numbered
  completion criteria back before any tool use (and stops to report a
  conflict instead of guessing); "done" is pre-declared as numbered
  criteria derived from the frozen contract (boundary confinement, the
  unit's integration checks, committed work); and verification is
  mandatory-but-bounded — exactly one full pass is the floor, a finding
  blocks only when it violates a stated criterion, passing criteria are
  never re-verified, and a still-failing criterion is reported after two
  fix-and-verify cycles instead of looping. Review-role units add
  criterion-bound review with a two-round re-review cap. High-effort
  routes (high/xhigh/max) append a per-family calibration block countering
  over-verification inertia; unknown families get the generic block so no
  vendor carries richer guidance than another. Prompts are subprocess
  argv, so the assembled worst case is policy-gated under
  `UNIT_PROMPT_MAX_BYTES` in tests rather than trimmed at runtime.
- **Telemetry.** Each dispatched unit records `started_at`, `finished_at`,
  and `duration_seconds`, and the full dispatch summary persists to
  `~/.omh/coding/fanout/<id>/dispatch_summary.json` (latest wins,
  metadata only, skipped on `--dry-run`).
- **Run journal and resume.** Alongside the summary, every non-dry-run
  dispatch writes `~/.omh/coding/fanout/<id>/run_journal.json`
  (`fanout_run_journal/v1`): one row per unit holding the terminal state it
  reached (`succeeded`, `failed`, `skipped_by_dependency`, `not_attempted`),
  the failure class read off the retry decision, the replay-safety verdict,
  and what it was blocked on. The write is temp-then-rename, so a dispatch
  interrupted mid-write leaves the previous journal intact rather than a
  truncated document. Passing it back as `omh coding fanout dispatch
  <id> --resume-journal <path>` re-dispatches only what is eligible: a unit
  that already succeeded is never re-run and still clears its dependents; a
  failure with no observed side effect is re-run; a failure that left changes
  in its worktree, wrote a result artifact, or could not be measured is
  **held**, with the reason named, and continued through the recovery record
  instead; and a dependent skipped behind a blocker is un-skipped exactly when
  that blocker is being attempted again. The plan is reported under the
  summary's `resume` key and per unit under `resume`, and a journal that
  cannot be read as this schema is refused with a `reason_code`
  (`journal_corrupt`, `journal_schema_unsupported`, `journal_fanout_mismatch`)
  rather than treated as an empty prior run. The resume decides eligibility
  only — it does not remove anything, so a unit whose earlier attempt left its
  worktree in place still meets the existing `worktree_path_already_exists`
  refusal until that worktree and branch are cleared by hand.
- **Failed-unit recovery.** A unit that exits non-zero — including a
  timeout — still owns its worktree, and whatever it wrote is the only
  thing between the operator and redoing the work. Before the summary
  reports the failure, dispatch measures that worktree against the
  dispatch base and attaches a `recovery` record to the unit result:
  `outcome` (`recovery_available`, `no_changes`, or `capture_failed`),
  the changed path count and names (capped, with `paths_truncated`),
  `lines_changed`, `diff_bytes`, `diff_sha256`, `recovery_ref`, and a
  `recover_with` command. Units whose outcome is `recovery_available` are
  rolled up in the summary's `recovery_available_units`, the counterpart
  to `integration_ready_units`, and `omh coding fanout brief` carries a compact
  `recovery` line per unit so the signal survives after the dispatch JSON
  scrolls past. The record also persists to
  `~/.omh/coding/fanout/<id>/recovery/<unit>.json`, byte-for-byte the same
  keys as the summary's copy.
  The probe runs `git add -N` in that unit's worktree first so files the
  unit *created* are measured too, and so the printed `recover_with`
  command produces a complete patch; it stages no content and makes no
  commit, and a `rev-parse --show-toplevel` check first proves the probe
  is standing in the unit's own worktree. If `add -N` fails, the outcome
  is `capture_failed` with `tracked_paths_seen` — never
  `recovery_available`, because a patch missing the created files is not
  the complete one the record advertises. Paths and the patch are both
  read as raw bytes, so a non-ASCII filename is recorded as written
  rather than mangled through the host locale. The record is metadata
  only — the diff is hashed for size and digest, then dropped, and never
  leaves the worktree.
  Lifecycle: any stored record is cleared before a unit re-runs, so one
  cannot outlive the worktree it points at; a unit that re-runs and
  succeeds ends with no record and drops out of the rollup; and a unit
  that could not re-run at all (`worktree_failed`) keeps the earlier
  record, because failing to start says nothing about what the last
  attempt left behind. Successful units are never probed: their work is
  reached by merging their branch, not by salvage. A failed probe
  degrades to `capture_failed` and never changes the unit's own result.
- **Limit signals.** A failed spawn whose bounded output matches a fixed,
  context-anchored limit-shape pattern (rate limit, usage limit, quota
  exceeded, HTTP 429, credits) is flagged `limit_shaped` with a pattern
  label; the last such failure per executor persists to
  `~/.omh/runtime/executor-limit-signals.json` (plus its transient `.lock`
  sibling) and surfaces as an advisory — with read-time `age_seconds` and
  a 6-hour `stale` marker — in `omh coding executor-readiness` and the
  choose-executor context, where candidates rank logged-in/no-fresh-limit
  first without ever removing an option. A later successful dispatch to
  the same executor clears its signal. Only the boolean and label persist
  — never the matched text, and stderr is matched in memory only.
- **Data boundary.** The #801 limits split three ways and this lane sits on
  the honest side of the split. `workspace_root_claim`,
  `prohibited_data_class`, and `declared_destination` are
  `refused_before_handoff`: omh declines to prepare the artifact at all, so
  they hold identically on every host and a dispatched unit can never be handed
  a target, a data class, or a destination that was refused upstream.
  `runtime_filesystem_confinement` and `runtime_network_confinement` are
  `host_confinement`, and dispatch does **not** provide them — the
  cross-harness adapter lane builds an OS confinement sandbox (`sandbox-exec`
  on macOS, a trusted `bwrap` on Linux) and no dispatched unit runs under it,
  which is the blocker those two rows now name in words.
  `executor_honours_declared_targets` is advisory everywhere: a unit's
  file boundary is frozen in the contract and checked for overlaps at prepare
  time, but nothing constrains the spawned CLI to it at runtime.
  `quality/safety_preflight.py::data_boundary_enforcement_facts` reports which
  of these the current host *could* enforce, and the six rows ride on
  `handoff_safety_contract/v1` as `data_*` boundaries so the answer is a fact
  about this machine rather than a promise.
- **Resume.** Re-running dispatch skips units whose runs already carry an
  observed successful result. `--unit <id>` selects subsets.
- **Never**: auto-merge, default-on execution, network calls by omh itself,
  raw-prompt persistence under `.omh`, Hermes-inline coding (coding-shaped
  work that cannot resolve an executor becomes an explicit user choice, not
  retained Hermes implementation).

## Failure recovery

A spawned agent CLI that dies because the provider quota is spent or the stored
credential is rejected is recoverable, and the two are not recoverable the same
way. This section is what dispatch does about that. It applies identically to
`omh coding fanout dispatch` and to the `omh coding run` single-run entry, which
funnel into the same engine.

- **`failure_kind` is a closed enum on every failed unit envelope**:
  `auth_shaped`, `limit_shaped`, `timeout`, `binary_missing`, or `crash` as the
  fallback. Precedence is fixed and deterministic. The dispatcher's own
  synthetic exit codes classify first — 127 is `binary_missing`, 124 is
  `timeout` — because they are observations of the process rather than text the
  provider wrote. Text then classifies as `auth_shaped` **before**
  `limit_shaped`: the two pattern sets overlap in practice (a 401 body routinely
  also mentions a rate limit for unauthenticated callers), and an invalid
  credential must be repaired before any attempt can succeed while a limit
  clears on its own — filing an overlapping failure into the wait-it-out lane
  would put it where waiting can never clear it. The auth patterns are
  multi-word and anchored to credential context for the same reason the limit
  patterns are: a bare `401`, `token`, or `auth` matches ordinary CLI narration.
  Only the boolean and the matched label are ever persisted, never the matched
  text. The existing `limit_shaped` / `limit_pattern` fields are unchanged.
- **Auth-failure signals persist per owner**, in
  `~/.omh/runtime/executor-auth-failure-signals.json`
  (`executor_auth_failure_signals/v1`), a sibling of the limit signals rather
  than another key inside them — the limit record's own field is
  `last_limit_shaped_at`, and writing a credential rejection under that name
  would make every reader report a quota problem that never happened. Records
  gain read-time `age_seconds` and a `stale` marker, and the owner's next exit-0
  clears them, exactly like limit signals. These are **not** the presence
  markers in `executor_auth_signals`: a marker is absent for every legitimate
  API-key install and never vetoes anything.
- **Repair cards** ride every `auth_shaped` and `limit_shaped` unit entry
  (`dispatch_failure_repair_card/v1`). An auth card names re-authentication then
  re-dispatch, with the owner's own login command where this repo has verified
  one and a neutral "re-authenticate the `<owner>` CLI" instruction where it has
  not — no CLI is the implied default. A limit card names the wait and the
  remaining cooldown window.
- **A fresh observed signal is a spawn cooldown.** At spawn time, an owner
  carrying a non-stale auth or limit signal does not spawn: the unit finishes as
  `executor_auth_invalid` or `executor_limit_cooldown`, before the readiness
  probe and before its worktree exists, so nothing is left behind. This is the
  one place an observed signal becomes a veto rather than a ranking hint, and it
  does not contradict the advisory-marker principle: the input is a runtime
  failure omh observed from a real spawn of that owner, not the absence of a
  local login file. A record whose observation time cannot be read never vetoes
  — it cannot be *shown* to be inside the window. `--ignore-limit-signal`
  overrides both and re-observes the provider's answer directly. A vetoed unit
  blocks its dependents and journals as `not_attempted`, so a later resume
  re-attempts it.
- **The recovery interview offers three actions, and never picks one.** After
  the run, each unit that failed as `auth_shaped` or `limit_shaped` gets a
  numbered choice: **[1] retarget** to another coding owner, ranked from
  `executor_choice_context` with the failed owner excluded; **[2] Hermes
  subagent**, re-running the unit through the `omh coding hermes-child dispatch`
  boundary, which carries separate auth and a separate quota; **[3] wait**,
  marking the unit for retry later. An option this environment cannot carry out
  is still listed, with `available: false` and the reason. Every decision —
  including "none" — is recorded in the summary's `failure_recovery` block
  (`fanout_failure_recovery/v1`). **No coding owner is ever switched without an
  explicit choice recorded there.**
  - **Retarget** re-dispatches under a derived unit id
    (`<unit-id>-retarget-<owner>`), which gives it its own worktree and branch.
    The failed unit's worktree is neither reused nor deleted — this engine
    refuses a pre-existing worktree path and never removes an operator's
    directory. The frozen model route is dropped rather than carried across: a
    model id belongs to the CLI it was resolved for. Retargeting to the owner
    that just failed is refused.
  - **Hermes** runs the unit in its OWN worktree or not at all; pointing the
    child at the dispatch repo root would let a recovery attempt edit the main
    checkout. Selecting it is the explicit dispatch consent the Hermes child
    boundary requires — equivalent to `--confirm-dispatch` — and it is recorded
    as such. The lane is offered only when `--hermes-model`,
    `--hermes-provider`, and `--hermes-reasoning` are supplied.
  - **Wait** marks the unit `awaiting_retry` in the run journal with its
    failure kind. The next `--resume-journal` run re-dispatches exactly those
    units under the `rerun_awaiting_retry` action; units whose success was
    observed stay skipped, and a deferred unit that is replay-unsafe is still
    held with its side effect named — deferring is a reason to re-attempt, never
    a licence to rebuild a worktree over work a failure left behind.
- **`--on-failure=report|retarget:<owner>|hermes|wait`** is the non-interactive
  degradation. `report` is the default and today's behavior: the notice, the
  repair card, and the options are printed to stderr and nothing changes. The
  interview runs only when the mode is `report`, `--no-interactive` was not
  passed, and stdin is a real terminal — a named mode is the operator answering
  on the command line, and a pipe or a CI job never blocks on a prompt nobody
  can see. The prompt-reading seam is injected, so the interview is exercised
  without a terminal anywhere in the test suite.
- **Not evidence.** A recovery decision records what was chosen and what the
  attempt observed. Choosing an action is not a claim it succeeded, and a
  retargeted or Hermes-lane unit that exits 0 is no more verified than any other
  unit that exits 0.

## Installed-skill discovery

Before building unit prompts, dispatch probes fixed executor-specific
locations once per distinct spawnable owner and embeds the declared skills in
the prompt. Probing is read-only observation of what is installed, never proof
that a skill resolves at run time — the executor stays the authority. Each
probed source reports a status: `present`, `absent`, `unreadable`, or
`unsupported`.

- **claude-code** probes three sources: personal skills at `~/.claude/skills`
  (invoked `/<name>`), plugin skills under `~/.claude/plugins` (invoked
  `/<plugin>:<name>`), and — because dispatch passes the target repo as
  `project_root` — repo-local `.claude/skills` in the dispatch target. Plugin
  probing prefers the installed-cache layout
  (`cache/<marketplace>/<plugin>/<version>/skills/`) and falls back to
  marketplace clones (`marketplaces/<dir>/plugins/<plugin>/skills/`, plus the
  legacy `marketplaces/<dir>/.claude/skills` shape). The namespace prefix is
  the plugin's own manifest `name` (`.claude-plugin/plugin.json` or
  `plugin.json`, first parseable wins) when readable, with the directory name
  only as a fallback: a cache directory `ui-ux-pro-max-skill` holding a
  plugin named `ui-ux-pro-max` emits `/ui-ux-pro-max:design`, not a prefix no
  registry knows.
- **codex** probes custom prompts at `~/.codex/prompts` (addressed by file
  stem, invoked `/<name>`) and OMX-style skill directories at
  `~/.codex/skills` (invoked `$<name>`).
- **omo-runtime** reports one explicit `unsupported` source with a reason
  instead of silence: its host CLIs (pi/senpi/opencode) declare no skill
  layout this repo can verify, so nothing is scanned — a dry run then shows
  WHY no skills are sequenced rather than an empty payload with no trace.
- **Dry-run surface.** Each planned unit carries `skill_sequence_source`:
  `declared` / `declared_none` when the unit already answered,
  `auto_recommended` plus a `skill_selection` question card when the
  environment offers a genuine arrangement choice, `auto` plus the concrete
  `skill_sequence` invocations that will ride the prompt, or `none`. Live
  dispatch never blocks on the card — unanswered means option 1.

## Command reference

```sh
# units.json is either a JSON list of units, or an object:
#   {"units": [...], "spawn_plan": {...}}   <- spawn_plan required above 4 units
omh coding fanout prepare --goal <words...> --units units.json [--record] [--source discord]
omh coding fanout validate --units units.json   # also reports spawn_plan_required
omh coding fanout show <fanout-id> [--limit 20] [--full]
omh coding fanout brief [<fanout-id>] [--json]
omh coding fanout status --fanout-id <fanout-id> [--json]
omh coding fanout migrate-legacy <fanout-id> \
  [--confirm-contract-sha256 <digest>]  # operator/maintenance only
omh coding fanout dispatch <fanout-id> --goal-file goal.txt \
  [--repo-root .] [--base-ref HEAD] [--concurrency N] [--timeout 1800] \
  [--unit <id> ...] [--dry-run] [--run-verification] \
  [--resume-journal ~/.omh/coding/fanout/<fanout-id>/run_journal.json]
omh coding run --owner <profile> (--goal <words...> | --goal-file goal.txt) \
  [--unit-id run] [--file-scope <path> ...] [--repo-root .] [--base-ref HEAD] \
  [--timeout 1800] [--dry-run] [--run-verification] [--source discord] \
  [--model <id>] [--effort <level>] [--category <category>]
  # single-invocation: builds and dispatches a one-unit fanout_contract/v2 through
  # the same engine as `fanout dispatch`; see "Single-run entry" above
omh coding fanout reap <fanout-id> [--pid N ...]  # terminate marker-named
  # unit process groups (verify the dispatcher is dead first); refuses any
  # pid the inflight markers do not name — never kills by process name
omh coding model-route [--executor <profile>] [--role <role>] [--model <id>] [--effort <level>] [--domain <name>] [--explain] [--from-inventory] [--json]
omh coding category-maestro show [--json]      # effective category table, operator overrides marked
omh coding category-maestro set <profile> <category> <model[:effort]>...
omh coding category-maestro clear <profile> <category>
omh coding category-maestro interview          # guided per-profile walk (terminal only)
omh coding model-inventory [--json]
omh coding complexity <request> [--skill <workflow>] [--model <id>] [--effort <level>] [--json]
omh coding composition-guide [--model <id>] [--executor <profile>] [--json]
omh coding model-contract --model <id> [--executor <profile>] [--json]
```

`--units` and `--goal-file` accept `-` for stdin. `--dry-run` resolves
readiness, planned argv, and worktree paths without spawning anything or
creating any runs. `--run-verification` is off unless typed; it runs only the
`verification_commands` a unit's own contract declares.
