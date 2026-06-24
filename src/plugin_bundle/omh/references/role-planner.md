# Planner

This OMH role is a responsibility descriptor, not a runtime agent.

Own clarification, non-goals, acceptance criteria, tradeoffs, loopability, and verification strategy.

## OMH Role Context

Use this role as OMH workflow-layer responsibility context: route the user's request to the nearest skill, name adjacent OMH workflows when the work crosses lanes, and keep status/evidence boundaries visible.

Normal users talk to Hermes; role names help Hermes explain ownership and next action without making the user learn backend OMH commands.

Role selection is prepared guidance only. It is not worker dispatch, tool execution, file generation, delivery, review, CI, merge-readiness, or merge evidence.

## Legacy Aliases

- `planning-lead`

## Owns

- One-question clarification when scope is ambiguous
- Plan artifact with goals, non-goals, risks, and verification
- Decision gate before handoff or execution

## Primary Skills

- `deep-interview`
- `plan`
- `ralplan`
- `loop`

## Primary Harnesses

- `deep-interview`
- `planning`
- `strategy-synthesis`
- `goal-loop`

## Wrapper Actions

- `ask_followup`
- `accept_plan`
- `revise_plan`
- `show_status`

## Evidence Boundary

A planner role can make work reviewable; it is not proof that the work was accepted or executed.
