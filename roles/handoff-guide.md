# Handoff Guide

This OMH role is a responsibility descriptor, not a runtime agent.

Own executor/runtime selection, prepared handoff payloads, and status narration while the chosen coding agent or runtime owns code changes.

## OMH Role Context

Use this role as OMH workflow-layer responsibility context: route the user's request to the nearest skill, name adjacent OMH workflows when the work crosses lanes, and keep status/evidence boundaries visible.

Normal users talk to Hermes; role names help Hermes explain ownership and next action without making the user learn backend OMH commands.

Role selection is prepared guidance only. It is not worker dispatch, tool execution, file generation, delivery, review, CI, merge-readiness, or merge evidence.

## Legacy Aliases

- `coding-handoff`
- `runtime-handoff-guidance`
- `codex-handoff-guidance`

## Owns

- Executor, runtime, or Hermes coding-skill choice
- Prepared coding handoff with team/swarm, worker, worktree, acceptance, and verification expectations when relevant
- Observed lifecycle status when a tested executor contract records it

## Primary Skills

- `ultragoal`
- `ultrawork`
- `ralph`
- `ai-slop-cleaner`

## Primary Harnesses

- `goal-execution`
- `parallel-delivery`
- `coding-handling`

## Wrapper Actions

- `choose_executor`
- `show_prompt_handoff`
- `show_runtime_handoff`
- `start_team`
- `start_swarm`
- `prepare_worktree`
- `send_to_executor`
- `show_status`

## Evidence Boundary

A prepared coding handoff is not executor/runtime dispatch, worker start, worktree creation, result, verification, review, CI, merge readiness, or merge evidence. Hermes/OMX/OMO/OMC runtime handoffs must record separate `runtime_observation/v1` events before the status can move from prepared to observed.
