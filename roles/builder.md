# Builder

This OMH role is a responsibility descriptor, not a runtime agent.

Name the implementation responsibility inside a prepared Hermes-facing playbook while the selected executor/runtime remains the actual work owner.

## OMH Role Context

Use this role as OMH workflow-layer responsibility context: route the user's request to the nearest skill, name adjacent OMH workflows when the work crosses lanes, and keep status/evidence boundaries visible.

Normal users talk to Hermes; role names help Hermes explain ownership and next action without making the user learn backend OMH commands.

Role selection is prepared guidance only. It is not worker dispatch, tool execution, file generation, delivery, review, CI, merge-readiness, or merge evidence.

## Legacy Aliases

- `implementation-owner`

## Owns

- Presentation-layer implementation step in the prepared playbook
- selected executor/runtime ownership narration
- Expected implementation artifact boundary before observed evidence exists

## Primary Skills

- `ultragoal`
- `ultrawork`
- `ralph`

## Primary Harnesses

- `goal-execution`
- `coding-handling`

## Wrapper Actions

- `choose_executor`
- `show_prompt_handoff`
- `show_runtime_handoff`
- `send_to_executor`
- `show_status`

## Evidence Boundary

A builder role label is not hidden coding execution, executor/runtime dispatch, worker start, implementation result, verification, review, CI, merge readiness, or merge evidence. The selected executor/runtime owns implementation only after observed evidence exists.
