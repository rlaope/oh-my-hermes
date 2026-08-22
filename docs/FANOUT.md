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
   (for example `(gpt-5-codex xhigh)`), status, elapsed seconds, token
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
  surfaces keep their prompt-only semantics for prompt-only profiles; the
  bridge is an operator-invoked command on a different surface.
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
  means the argv stays byte-identical to the base template and the executor
  CLI default model applies. Model availability and entitlement are provider
  truth; a routed model that the CLI rejects surfaces as a normal observed
  exit failure. `omh coding model-route` previews a single route;
  `omh coding model-route --explain` renders the full profile × role
  resolution matrix with chains and provenance. Contracts frozen before the
  v2 bump may embed `coding_model_route/v1` routes — they are read verbatim
  (the brief annotates them `[schema v1]`), never rewritten.
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
  [--repo-root .] [--base-ref HEAD] [--concurrency 2] [--timeout 1800] \
  [--unit <id> ...] [--dry-run] [--run-verification]
omh coding model-route [--executor <profile>] [--role <role>] [--model <id>] [--effort <level>] [--domain <name>] [--explain] [--from-inventory] [--json]
omh coding model-inventory [--json]
omh coding composition-guide [--model <id>] [--json]
```

`--units` and `--goal-file` accept `-` for stdin. `--dry-run` resolves
readiness, planned argv, and worktree paths without spawning anything or
creating any runs. `--run-verification` is off unless typed; it runs only the
`verification_commands` a unit's own contract declares.
