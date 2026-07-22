# Memory Keeper

This OMH role is a responsibility descriptor, not a runtime agent.

Own durable context review, project knowledge capture, stale memory warnings, and safe memory update handoffs.

## OMH Role Context

Use this role as OMH workflow-layer responsibility context: route the user's request to the nearest skill, name adjacent OMH workflows when the work crosses lanes, and keep status/evidence boundaries visible.

Normal users talk to Hermes; role names help Hermes explain ownership and next action without making the user learn backend OMH commands.

Role selection is prepared guidance only. It is not worker dispatch, tool execution, file generation, delivery, review, CI, merge-readiness, or merge evidence.

## Legacy Aliases

- `retained-knowledge`

## Owns

- Memory and wiki context review
- Stale, duplicate, or conflicting context candidates
- Human-approved context pack preparation

## Primary Skills

- `wiki`
- `memory-sync`

## Primary Harnesses

- `knowledge`
- `memory-context-review`

## Wrapper Actions

- `ask_followup`
- `show_status`
- `prepare_handoff`

## Evidence Boundary

A memory keeper role can prepare context changes; it is not proof that Hermes internal memory, USER.md, MEMORY.md, wiki, or skill files were changed.
