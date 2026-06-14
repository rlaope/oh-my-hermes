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
- team, swarm, worker, and worktree orchestration
- MCP/tool bridge setup
- loop/autopilot delivery flows
- doctor, update, uninstall, and release smoke commands

OMH should absorb the useful capability shape, not copy another project's
implementation or claim runtime behavior it did not observe.

## Current Matrix

| Capability axis | OMH status | OMH surface | Missing or intentionally delegated |
| --- | --- | --- | --- |
| Skill and plugin distribution | Available | Tap-compatible `skills/*/SKILL.md`, `omh setup`, and optional `~/.hermes/plugins/omh` bridge. | Observed Hermes plugin load still needs host runtime evidence. |
| Specialist role/profile system | Partial | Skill catalog metadata, operating models, optional visible profile packs, and wrapper role narration. | No hidden live specialist agents are claimed without wrapper or runtime evidence. |
| Team, swarm, and worker protocol | Partial | `team`, `ultrawork`, runtime handoff payloads, worker-protocol guidance, wrapper sessions, and runtime observations. | OMH does not launch hidden tmux teams, spawn workers, or manage panes by itself. |
| Worktree and project-session isolation | Partial | Coding runtime handoff contracts, loop queue metadata, and runtime observations for worktree creation. | OMH records and requests isolation but does not create Git worktrees in v1. |
| HUD, status, and session observability | Available | `omh hud`, plugin `omh_hud`/`omh_status`, wrapper sessions, runtime runs, and status cards. | Live host HUD rendering depends on Hermes/plugin support. |
| MCP and tool bridge preference | Partial | `omh setup --with-mcp`, setup state, and `omh probe` host-config separation. | OMH does not ship or auto-enable a real MCP server/tool bridge in v1. |
| Loop and autopilot workflow | Available | `loop`, `ultraprocess`, `ralplan`, `ultragoal`, loop queue ticks, verification tiers, and failure-mode cards. | Scheduling, connector I/O, worktree creation, and subagent execution remain prepared or delegated until observed. |
| Doctor, update, uninstall, and release smoke | Available | `omh setup`, `omh doctor`, `omh update`, `omh uninstall`, `omh release checklist`, and `omh release hermes-smoke`. | Live release smoke still needs an explicit target Hermes profile or operator confirmation before mutation. |

## Implementation Plan

This PR implements the first vertical slice:

- Add a deterministic parity catalog in `src/parity.py`.
- Add `omh probe --parity` so operators and wrappers can inspect the matrix
  beside the current local capability probe.
- Keep the default `omh probe` output unchanged unless `--parity` is passed.
- Document the comparison, non-goals, and next implementation slices.
- Add unit tests that lock the JSON schema, human summary, and conservative
  claim boundaries.

Next PR candidates:

| Next PR | Why it matters |
| --- | --- |
| Wrapper-observed role lane results | Closes more of the specialist role gap without inventing hidden Hermes agents. |
| Worktree/session isolation runbooks and smoke fixtures | Makes executor-neutral worktree guidance operational before any creator command exists. |
| Real OMH MCP bridge contract | Turns MCP preference into an installable, testable bridge when Hermes support is stable enough. |

## Acceptance Criteria

- `omh probe` remains a compact capability summary by default.
- `omh probe --parity` prints a human-readable parity section.
- `omh probe --parity --json` includes `parity_matrix.schema_version` equal to
  `omh_parity_matrix/v1`.
- Team/swarm, worktree, and MCP axes are marked `partial`, not `available`,
  until observed runtime support exists.
- The matrix never claims hidden worker launch, worktree creation, MCP tool
  calls, plugin runtime load, executor execution, review, CI, or merge
  evidence.

## Non-Goals

- No hidden tmux team launcher.
- No Git worktree creator.
- No MCP server or tool host.
- No Discord/Slack transport implementation.
- No Hermes core patch.
- No network calls, LLM calls, or executor dispatch from the parity verifier.
