# OMH Parity Matrix

This document tracks the gap between common oh-my agent runtime capability
patterns and OMH's Hermes-native implementation. It is intentionally not a
clone list. The goal is to keep OMH competitive while preserving its core
boundary: Hermes owns conversation and workflow narration, selected executors
own observed execution, and OMH owns deterministic local contracts.

Use the live verifier for the current local install:

```sh
omh probe --parity
omh probe --parity --json
```

The JSON payload includes `omh_parity_matrix/v1`.

## Search Basis

The comparison is based on public oh-my agent runtime patterns across:

- skill and plugin installation surfaces
- native plugin/HUD/status context
- specialist role or profile systems
- bounded evidence probe tools
- team, swarm, worker, and worktree orchestration
- MCP/tool bridge setup
- loop/autopilot delivery flows
- doctor, update, uninstall, and release smoke commands

OMH should absorb the useful capability shape, not copy another project's
implementation or claim runtime behavior it did not observe.

## Current Matrix

| Capability axis | OMH status | OMH surface | Missing or intentionally delegated |
| --- | --- | --- | --- |
| Skill and plugin distribution | Available | Tap-compatible `skills/*/SKILL.md`, `omh setup`, optional `~/.hermes/plugins/omh` bridge, and `omh plugin observe-host` for host-observed plugin load/use. | Live plugin load/use must still be recorded by the host or wrapper; local install smoke is not runtime evidence. |
| Specialist role/profile system | Available | Skill catalog metadata, operating models, optional visible profile packs, wrapper role narration, plugin `omh_role`, and `[omh-role:name]` context injection. | Observed role execution still requires wrapper or runtime evidence; role context is not a hidden live agent. |
| Bounded evidence probe | Available | Plugin `omh_gather_evidence` runs shell-free allowlisted local probes such as doctor, harness validation, docs checks, unittest, compileall, and whitespace checks. | It is not a general shell, executor dispatch, PR review, CI, merge, or live Hermes plugin-load signal. |
| Team, swarm, and worker protocol | Partial | `team`, `ultrawork`, runtime handoff payloads, worker-protocol guidance, wrapper sessions, and runtime observations. | OMH does not launch hidden tmux teams, spawn workers, or manage panes by itself. |
| Worktree and project-session isolation | Available | `worktree_session_isolation/v1` plans in coding handoffs, wrapper Prepare worktree actions, `omh worktree prepare/list/bind`, executor-session status cards, loop queue metadata, and runtime observations for worktree creation. | OMH creates local Git worktrees only through the explicit opt-in backend command; binding recipes show how wrappers can open or attach host sessions but do not auto-launch executors or claim runtime evidence. |
| HUD, status, and session observability | Available | `omh hud`, plugin `omh_hud`/`omh_status`, wrapper sessions, runtime runs, and status cards. | Live host HUD rendering depends on Hermes/plugin support. |
| MCP and tool bridge | Available | `omh setup --with-mcp`, `omh mcp manifest`, `omh mcp config-recipe`, `omh mcp serve`, `omh mcp observe-host`, and `omh probe` preference/server/runtime/host-session/host-config separation. | OMH does not auto-enable host MCP config or independently inspect live host sessions; the host or wrapper must record load/session evidence. |
| Loop and autopilot workflow | Available | `loop`, `ultraprocess`, `ralplan`, `ultragoal`, loop queue ticks, verification tiers, and failure-mode cards. | Scheduling, connector I/O, worktree creation, and subagent execution remain prepared or delegated until observed. |
| Doctor, update, uninstall, and release smoke | Available | `omh setup`, `omh doctor`, `omh update`, `omh uninstall`, `omh release checklist`, `omh release install-smoke`, and `omh release hermes-smoke`. | Installer smoke can run live in an isolated temp HOME; live Hermes profile smoke still needs an explicit target Hermes profile or operator confirmation before mutation. |

## Implemented Slices

- A deterministic parity catalog in `src/parity.py`.
- `omh probe --parity` so operators and wrappers can inspect the matrix beside
  the current local capability probe.
- A plugin bridge with native role context lookup, role marker injection,
  delegate marker validation, session-end checkpoints, and bounded
  `omh_gather_evidence` probes.
- `omh_plugin_host_observation/v1` records through `omh plugin observe-host`, so
  operators can distinguish local plugin install/import/register smoke from
  host-observed Hermes plugin load or use. Active native readiness requires the
  latest observed event to be `plugin_load`, `tool_call`, `hook_call`, or
  `status_query`; `session_end` and `plugin_unload` remain historical evidence.
- `worktree_session_isolation/v1`, which gives coding handoffs and wrapper
  status cards a concrete same-workspace/worktree-recommended/worktree-required
  contract before any executor is opened.
- `omh worktree prepare` and `omh worktree list`, which let wrappers or
  operators explicitly create a local Git worktree and record
  `omh_worktree_observation/v1` workspace-isolation evidence. That evidence is
  still not executor dispatch, implementation, review, CI, merge-readiness, or
  merge evidence.
- `omh worktree bind`, which returns `worktree_executor_binding/v1` so wrappers
  can render Open in Codex, Open in Claude Code, Attach session, and runtime
  observation record actions for a prepared worktree without launching the
  executor or treating a terminal command as evidence.
- A dependency-free stdio MCP bridge with allowlisted local `omh_status`,
  `omh_recommend`, and `omh_probe` tools plus manifest and probe evidence.
- `omh mcp config-recipe --host ...`, which prints copy-paste config snippets
  for Claude Code, Codex, OpenCode, Cursor, and generic MCP hosts without
  mutating host files or claiming host load.
- `omh_mcp_host_session/v1` records for host/wrapper-observed MCP bridge load
  or session use, kept separate from local bridge tool-call evidence and host
  config file probes.
- Unit tests that lock JSON schema shape, human summaries, conservative claim
  boundaries, and wrapper-visible Prepare worktree actions.

## Acceptance Criteria

- `omh probe` remains a compact capability summary by default.
- `omh probe --parity` prints a human-readable parity section.
- `omh probe --parity --json` includes `parity_matrix.schema_version` equal to
  `omh_parity_matrix/v1`.
- Team/swarm worker launch remains `partial` until observed runtime support
  exists. Worktree isolation is `available` only for explicit local Git
  worktree creation, `omh_worktree_observation/v1` records, and
  `worktree_executor_binding/v1` wrapper recipes; executor/session dispatch
  still needs separate runtime evidence. The MCP bridge axis is `available`
  only for the local stdio server and allowlisted tools; host-specific
  load/session use must still be recorded through `omh_mcp_host_session/v1`
  before it is claimed.
- Specialist roles are `available` only as prompt context, marker validation,
  and profile guidance. They are not hidden runtime agents.
- Plugin runtime observation is `available` only when a host or wrapper records
  `omh_plugin_host_observation/v1` with an evidence reference. It is not coding
  dispatch, implementation, review, CI, merge, or proof of unrecorded tool/hook
  calls. `native_integration_claim_ready` is narrower than historical runtime
  observation and requires an active plugin event.
- Bounded evidence probes are `available` only as explicit allowlisted local
  command results. They are not executor dispatch, implementation, review, CI,
  merge, or plugin-load evidence.
- The matrix never claims hidden worker launch, automatic worktree creation,
  unrecorded MCP host load, plugin runtime load, executor execution, review, CI,
  or merge evidence.

## Non-Goals

- No hidden tmux team launcher.
- No automatic Git worktree creator.
- No executor launch from the worktree creator or binder.
- No arbitrary MCP shell, connector runner, or auto-enabled host config.
- No Discord/Slack transport implementation.
- No Hermes core patch.
- No network calls, LLM calls, or executor dispatch from the parity verifier.
- No arbitrary shell or connector command runner from the plugin bridge.
