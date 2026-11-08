# Multi-Agent Operations

This is a wrapper and maintainer reference for running more than one
agent, wrapper process, or coding executor against the same `~/.omh` and
`~/.hermes` home directories. It complements
[Orchestration Patterns](ORCHESTRATION_PATTERNS.md), which names *which*
pattern to select; this document covers *what happens to shared state* once
more than one agent is acting concurrently.

OMH's default assumption is one active agent per home. This document names
that assumption explicitly, describes the boundary OMH can and cannot
enforce, and points concurrent multi-agent work at the coordination surfaces
that are actually built for it.

## Shared-State Ownership Model

A single `~/.omh` directory is one coordination domain. Every OMH command
that reads and writes local JSON state — run records, target topology,
memory indexes, wrapper sessions, learning traces — assumes it is the only
writer touching that file at that moment.

Concurrent wrappers or agents that need to write into the same `~/.omh` must
go through the locked update path instead of a bare read-modify-write. The
contract: an update acquires an advisory file lock scoped to the target
path, reads the current JSON object (or a supplied default if none exists),
applies a mutation, and writes the result back atomically before releasing
the lock. Callers that skip this path and write the file directly can still
race with a locked writer and lose an update. This is a description of the
contract every read-modify-write caller under `~/.omh` should use, not an
implementation walkthrough — see `src/system/local_store.py` for the actual
lock and atomic-write primitives.

One capability boundary inside the contract itself: the advisory lock is a
real OS file lock on the platforms OMH supports, taken on a `.<name>.lock`
sidecar rather than on the record. POSIX locks through `fcntl.flock`, Windows
through `msvcrt.locking` on one byte of the sidecar, and both are polled
until the caller's timeout, so mutual exclusion between concurrent processes
holds on both. Only when *neither* module is importable does the locked
update path degrade to best-effort: torn files are still prevented by the
atomic replace, but concurrent writers can interleave, so multi-agent
lost-update protection does not hold. That degradation is signaled rather
than silent — the lock primitive reports `enforced: False` with reason
`no_os_file_lock`, and `guarded_record_update()` surfaces it as
`lock_enforced=False` so a caller can say the guarantee was downgraded
instead of claiming it held. Single-agent behavior is unaffected either way.
See "What the lock actually guarantees" in
[Architecture](ARCHITECTURE.md) for the per-platform detail.

Practical implications for a wrapper or operator running more than one agent
against the same OMH home:

- Prefer one long-lived wrapper process per chat surface rather than
  multiple processes racing to update the same session or run record.
- If two agents must write concurrently (for example, two coding executors
  reporting progress on sibling tasks), route both through commands that use
  the locked update path rather than hand-rolling a parallel JSON writer.
- A lock timeout or contention error is a real signal, not a transient
  glitch to retry silently. Surface it as a blocker rather than dropping the
  update.

## Explicit Hermes Child Control

Audience: **agents, operators, and maintainers**. Normal users ask Hermes for
the outcome; they do not need to run these commands.

OMH can prepare, explicitly dispatch, inspect, and cancel one isolated local
Hermes Agent child:

```bash
omh coding hermes-child prepare \
  --model glm-5.3 --provider zai --reasoning high \
  --parent-run-id parent-1 --run-id child-1 --json < prompt.txt

omh coding hermes-child dispatch --confirm-dispatch \
  --model glm-5.3 --provider zai --reasoning high \
  --parent-run-id parent-1 --run-id child-1 --json < prompt.txt

omh coding hermes-child status --run-id child-1 --json
omh coding hermes-child cancel --run-id child-1 --json
```

`prepare` starts no process. `dispatch` is never implicit: it requires
`--confirm-dispatch`, sends the prompt over stdin, limits recursion to one
isolated child, and records `routing_observation/v1`. Status, tool count, token
usage, and cost are shown only when Hermes produced observed telemetry; OMH
does not estimate missing values. The child runs as `hermes chat --query-file -`,
the one Hermes transport that reads a prompt from stdin. Hermes writes its
`--usage-file` report for `-z` alone, so on this transport the child's tokens,
`api_calls`, model, and `estimated_cost_usd` with the `cost_status`/`cost_source`
that explain it are read after exit from the `sessions` rows of the child's own
disposable `HERMES_HOME/state.db`, the ledger Hermes fills per API call and the
`-z` report summarizes; the home is removed right after. A child that recorded
no API call, or left no readable ledger, reports no usage rather than zeros
(see Host surfaces OMH reads in `CONTEXT.md`).

The same boundary has a separate, explicit loaded-skill capability probe:

```bash
omh coding hermes-child skill-load-probe --confirm-dispatch \
  --run-id load-1 --expected-skill ulw-work --json
omh coding hermes-child skill-load-status --run-id load-1 --json
```

This command implements `skill_load_observation/v1`. `probe_status` is
orthogonal to `load_state`: only a validated, fresh
`hermes_skill_inventory/v1` response bound to the generated nonce, expected-set
digest, inventory digest, and executable fingerprint can emit `observed`.
Observed inventories contain sorted expected, observed, missing, and unexpected
skill-name sets. An empty expected set becomes `not_applicable` only after that
valid response. Unsupported and failed probes omit `load_state` and every
inventory claim, retain only closed reason codes and fingerprints, and never
persist command output.

Observed on Hermes Agent v0.20.5 (upstream `5259f565`), not re-checked since:
Hermes has no such inventory command. Its
`--skills` option preloads prompt content and `hermes skills list
--enabled-only` lists configured candidates, but neither returns a nonce-bound
runtime inventory. The real host probe therefore reports
`inventory_protocol_unavailable`; child success, model self-report, static
scheduler source, and installed/enabled listings are deliberately insufficient.
The complete observed host capability remains blocked on an external Hermes
machine-inventory protocol. This OMH contract does not patch Hermes, execute a
skill body, mutate config, call a provider directly, or run by default.

Model routing preferences are also an agent/operator surface:

```bash
omh coding model-routing status --json
omh coding model-routing reset --route-family <id> --json
```

These report or clear explicit local routing preference metadata. They do not
execute a model or prove that a model is available.

## Hermes `config.yaml` Is a Capability Boundary, Not an OMH Lock

`HERMES_HOME/config.yaml` is owned by Hermes Agent, not OMH. OMH's config
adapter performs a read-modify-write when it registers the managed skill
directory, but that write has no coordination with Hermes's own writes to
the same file, and no coordination with a second OMH install pointed at the
same Hermes home.

OMH cannot make Hermes honor an OMH-side lock on `config.yaml`, and it
cannot detect that Hermes rewrote the file between an OMH read and an OMH
write. Treat concurrent mutation of `config.yaml` — by Hermes itself, by a
second OMH install, or by a human editor — as an open capability boundary:
document it, re-read before mutating, and prefer `hermes config get/set` or
`hermes config check` for verification when the operator has it available,
rather than assuming OMH's last write is still intact.

## Target Topology Is Advisory Narration, Not Enforcement

`multi_agent_targets` mode (see `src/system/targets.py`) tells a wrapper
that more than one Hermes target has recently reported activity against the
same OMH home, and narrates a recommended `skill_scope_rule` in response.
This is observation-driven narration, not coordination:

- `active_agent_count` is self-reported by whichever target last observed
  activity; it is not a live process count and it does not lock anything.
- Detecting `multi_agent_targets` mode does not pause, queue, or serialize
  other agents' writes. It only changes what the wrapper narrates to the
  user (for example, recommending skill-scope awareness).
- A wrapper should treat `multi_agent_targets` as "tell the user multiple
  agents are active here," not as "OMH is now coordinating those agents."

The same boundary applies to worktree isolation guidance: `build_isolation_plan`
(`src/coding/isolation.py`) returns `prepared_not_observed` guidance that
*recommends* a worktree for risky or parallel work. It cannot detect or
prevent two agents editing the same workspace, and — per the
[Upstream Basis](HERMES_AGENT_INTEGRATION_RUNBOOK.md#upstream-basis) note in
the integration runbook — it can collide with a worktree Hermes's own Kanban
board or Desktop Projects is already managing for the same task. Because of that
collision risk, OMH no longer creates worktrees: worktree preparation is
deferred to native tooling (Hermes Kanban worktree-per-task since v0.15.0,
Desktop Projects since v0.18.0, or a manual `git worktree add`). OMH only
*observes* an existing worktree (`omh worktree list`) and binds a coding handoff
to it (`omh worktree bind`). Read prepared isolation guidance as a recommendation
to reuse or create a worktree with upstream-native tooling, not as proof one
does or does not exist.

## Prefer Upstream-Native Coordination Primitives

For actual multi-agent work distribution — not narration, but agents
picking up and completing units of work — prefer the coordination surfaces
Hermes Agent already ships over building a competing one inside OMH:

- **Kanban board** (`HERMES_HOME/kanban.db`, `kanban_*` toolset): a durable,
  multi-profile work queue with orchestrator auto-decomposition, swarm
  topology, worktree-per-task, and per-task model overrides. This is the
  preferred target for "hand this queue of tasks to multiple agents,"
  rather than a parallel OMH-side task queue.
- **`delegate_task` subagents**: background-by-default delegated work with
  handles and live transcripts. Prefer this for a single agent fanning out
  bounded sub-work, as distinct from the durable, cross-session Kanban
  queue.
- **Profiles**: concurrent Hermes profiles (desktop or gateway-routed) are
  the native mechanism for more than one persistent agent identity sharing
  one Hermes install.

OMH's role with respect to these primitives is to prepare handoffs and
evidence, not to reimplement them. A handoff prepared for Kanban or
`delegate_task` is still `prepared_not_observed` until a
`runtime_observation/v1` event records that Hermes actually created the
Kanban task, dispatched the subagent, or that a worktree exists. The same
prepared-vs-observed boundary that governs every other OMH contract applies
here: naming a coordination primitive is not proof it ran.

## Model Routing Across Multiple Agents

Model identity does not change the shared-state rules. Keep these owners
separate when several agents are active:

- Hermes owns `HERMES_HOME/config.yaml`, native aliases, provider bindings,
  skills, Kanban model pins, and `delegate_task` execution. Guided model setup
  must preview and digest-bind every alias change; a concurrent Hermes config
  write invalidates that preview and must be re-inspected rather than retried
  blindly.
- Maestro coordinates prepared external Codex, Claude Code, pi-family
  runtime, OMC, OMX, and generic handoffs. It is not an executor, does not own
  Hermes-native work, and cannot turn one agent's prepared route into another
  agent's observed run.
- The pi-family runtime's host CLIs are hosts of that runtime, not
  additional owners. Their metadata observations do not select a model for
  another agent.
- Recommendation categories and aliases are editable user policy. A missing
  Kimi, GPT, or Claude recommendation can fall through to a confirmed compatible
  GLM, DeepSeek, Gemini, Grok, or other model without blocking setup. An explicitly
  requested unavailable model instead requires a new choice.
- Grok's `x_platform_data` placement is editorial X-platform affinity, not a
  measured capability or a reason to override a user's model choice. CCAPI for
  Claude is likewise preferred provider-family metadata only; it is not a
  bundled or probed integration and is considered only when the user declares
  the corresponding local route active. Credentials remain with the native
  owner.

The agent/maintainer `omh coding model-routing status` report can compare local
observations, Hermes aliases, Maestro chains, and stored owner-choice metadata (which selects no owner). It is
an offline advisory snapshot, not a cross-process lock or provider/runtime
observation. `omh coding model-routing reset --route-family <id>` changes only
OMH owner-preference metadata and must not be used as a substitute for
coordinating a live agent or editing Hermes aliases.

## Executor-Neutral Throughout

Everything above applies regardless of which coding executor is behind a
handoff — Codex, Claude Code, Hermes's own coding runtime, or another
selected executor. None of them is the implicit default, and none of them
changes the shared-state ownership model described here.

## Related Reading

- [Orchestration Patterns](ORCHESTRATION_PATTERNS.md) — which pattern to
  select for a given shape of work.
- [Hermes Agent Integration Runbook](HERMES_AGENT_INTEGRATION_RUNBOOK.md) —
  upstream basis and wrapper contract surfaces.
- [Delegation-First Completeness](DELEGATION_FIRST_COMPLETENESS.md) — single
  vs. multi-executor handoff limitations.
