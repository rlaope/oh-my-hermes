# Reviewer

This OMH role is a responsibility descriptor, not a runtime agent.

Own claim checking, review findings, QA framing, release/readiness review, and evidence requirements.

## OMH Role Context

Use this role as OMH workflow-layer responsibility context: route the user's request to the nearest skill, name adjacent OMH workflows when the work crosses lanes, and keep status/evidence boundaries visible.

Normal users talk to Hermes; role names help Hermes explain ownership and next action without making the user learn backend OMH commands.

Role selection is prepared guidance only. It is not worker dispatch, tool execution, file generation, delivery, review, CI, merge-readiness, or merge evidence.

## Legacy Aliases

- `review-gate`
- `hybrid-review`
- `hybrid-verification`

## Owns

- Findings and risks
- Verification, CI, and release-readiness status
- Follow-up handoff only when fixes are accepted

## Primary Skills

- `code-review`
- `ultraqa`
- `ask`

## Primary Harnesses

- `code-review`
- `qa`
- `ops-review`

## Wrapper Actions

- `show_findings`
- `prepare_fix_handoff`
- `refresh_status`

## Evidence Boundary

Review findings are not fix evidence; merge-ready is not merged.
