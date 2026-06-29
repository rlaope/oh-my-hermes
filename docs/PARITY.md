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
omh probe --roadmap
```

The JSON payload includes `omh_parity_matrix/v1`. `--parity` also includes
`omh_capability_gap_roadmap/v1`, which separates real product/setup gaps from
host or wrapper evidence gaps. This matters because a missing runtime
observation is usually not a missing OMH feature.

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
| Skill and plugin distribution | Available | Tap-compatible `skills/*/SKILL.md`, `omh setup`, managed `~/.hermes/plugins/omh` bridge, `omh plugin observe-host`, and plugin tool/hook self-observation when a host supplies bounded observation metadata. | Live plugin load/use must still be recorded or host-supplied; local install smoke is not runtime evidence. |
| Specialist role/profile system | Available | Skill catalog metadata, operating models, optional visible profile packs, wrapper role narration, plugin `omh_role`, and `[omh-role:name]` context injection. | Observed role execution still requires wrapper or runtime evidence; role context is not a hidden live agent. |
| Bounded evidence probe | Available | Plugin `omh_gather_evidence` runs shell-free allowlisted local probes such as doctor, harness validation, docs checks, unittest, compileall, and whitespace checks. | It is not a general shell, executor dispatch, PR review, CI, merge, or live Hermes plugin-load signal. |
| Team, swarm, and worker protocol | Available | `team`, `ultrawork`, `omh runtime team-readiness`, runtime handoff payloads, worker-protocol guidance, wrapper sessions, and runtime observations. | Live worker launch and pane/session management still require the selected host runtime to act and record observations. |
| Worktree and project-session isolation | Available | `worktree_session_isolation/v1` plans in coding handoffs, wrapper Prepare worktree actions, `omh worktree prepare/list/bind`, executor-session status cards, loop queue metadata, and runtime observations for worktree creation. | OMH creates local Git worktrees only through the explicit opt-in backend command; binding recipes show how wrappers can open or attach host sessions but do not auto-launch executors or claim runtime evidence. |
| HUD, status, and session observability | Available | `omh hud`, plugin `omh_interact`/`omh_recommend`/`omh_probe`/`omh_hud`/`omh_status`, wrapper sessions, runtime runs, roadmap cards, and status cards. | Live host HUD rendering depends on Hermes/plugin support; plugin chat/session output is metadata/status, not execution evidence. |
| MCP and tool bridge | Available | `omh setup --with-mcp`, `omh mcp manifest`, `omh mcp config-recipe`, `omh mcp serve`, `omh mcp observe-host`, and `omh probe` preference/server/runtime/host-session/host-config separation. | OMH does not auto-enable host MCP config or independently inspect live host sessions; the host or wrapper must record load/session evidence. |
| Loop and autopilot workflow | Available | `loop`, `ultraprocess`, `ralplan`, `ultragoal`, loop queue ticks, verification tiers, and failure-mode cards. | Scheduling, connector I/O, worktree creation, and subagent execution remain prepared or delegated until observed. |
| Doctor, update, uninstall, and release smoke | Available | `omh setup`, `omh doctor`, `omh update`, `omh uninstall`, `omh release checklist`, `omh release product-readiness`, `omh release install-smoke`, `omh release hermes-smoke`, `omh demo route-hint-alignment`, `omh demo context-brief-coverage`, `omh demo routing-precision`, and `omh demo hermes-ux-quality`. | Product readiness rolls skill content, use-case readiness, parity contracts, route-hint alignment, context-brief coverage, routing precision, Hermes UX quality, and checklist shape into one local contract card. Installer smoke can run live in an isolated temp HOME; live Hermes profile smoke still needs an explicit target Hermes profile or operator confirmation before mutation. |

## Implemented Slices

- A deterministic parity catalog in `src/quality/parity.py`.
- `omh probe --parity` so operators and wrappers can inspect the matrix beside
  the current local capability probe.
- `omh probe --roadmap`, and the roadmap section inside `omh probe --parity`,
  so operators can see whether the next step is setup or repair, optional MCP
  configuration, wrapper usage evidence, or host runtime observation.
- A plugin bridge with native role context lookup, role marker injection,
  delegate marker validation, `omh_probe` capability-roadmap status, session-end
  checkpoints, and bounded `omh_gather_evidence` probes.
- `omh_plugin_host_observation/v1` records through `omh plugin observe-host`, or
  through plugin tool/hook self-observation when a host supplies bounded
  observation metadata, so operators can distinguish local plugin
  install/import/register smoke from host-observed Hermes plugin load or use.
  Active native readiness requires the latest observed event to be
  `plugin_load`, `tool_call`, `hook_call`, or `status_query`; `session_end` and
  `plugin_unload` remain historical evidence.
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
- `omh runtime team-readiness`, which returns `omh_team_worker_readiness/v1`
  for Hermes/team/swarm worker contract readiness, installed skill visibility,
  wrapper actions, runtime templates, and observed worker ledger status without
  claiming that a worker has run. It separates `contract_status` from
  `presentation_status` so local package support is not confused with Hermes
  currently seeing the installed skill surface.
- Unit tests that lock JSON schema shape, human summaries, conservative claim
  boundaries, and wrapper-visible Prepare worktree actions.

## Acceptance Criteria

- `omh probe` remains a compact capability summary by default.
- `omh probe --parity` prints a human-readable parity section.
- `omh probe --parity --json` includes `parity_matrix.schema_version` equal to
  `omh_parity_matrix/v1`.
- `omh probe --roadmap --json` includes
  `capability_gap_roadmap.schema_version` equal to
  `omh_capability_gap_roadmap/v1`.
- The roadmap distinguishes baseline product setup gaps from evidence gaps
  such as missing wrapper metadata, MCP host-session observations, or plugin
  runtime observations.
- Roadmap `next_actions` keeps executable backend commands in `command` and
  Hermes/operator guidance in `operator_instruction`, so wrappers do not treat
  prose instructions as shell commands.
- Team/swarm worker protocol is `available` as a readiness contract, wrapper
  action set, runtime template set, and `runtime_observation/v1` ledger. Worker
  launch, pane/session management, worker results, review, CI, and merge still
  require observed host/runtime records before they are claimed. Worktree
  isolation is `available` only for explicit local Git worktree creation,
  `omh_worktree_observation/v1` records, and `worktree_executor_binding/v1`
  wrapper recipes; executor/session dispatch still needs separate runtime
  evidence. The MCP bridge axis is `available` only for the local stdio server
  and allowlisted tools; host-specific load/session use must still be recorded
  through `omh_mcp_host_session/v1` before it is claimed.
- Specialist roles are `available` only as prompt context, marker validation,
  and profile guidance. They are not hidden runtime agents.
- Plugin runtime observation is `available` only when a host or wrapper records,
  or an invoked plugin tool/hook self-records,
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
