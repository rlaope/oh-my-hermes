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

One capability boundary inside the contract itself: the advisory lock is
POSIX `flock`-based. On platforms without `fcntl` the locked update path
degrades to plain atomic writes — torn files are still prevented, but mutual
exclusion between concurrent processes is not, so multi-agent lost-update
protection only holds on POSIX hosts. The degradation is signaled by the
lock primitive rather than silent, and single-agent behavior is unaffected.

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
board or Desktop Projects is already managing for the same task. Read
prepared isolation guidance as a recommendation to check for an existing
upstream-managed worktree before creating a new one, not as proof one does
or does not exist.

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
