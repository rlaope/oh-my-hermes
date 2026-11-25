# Support Operations

Load this on-demand contract after the compact `support-operations` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request clusters a backlog of customer signals to find product patterns or roadmap candidates; use `omh-feedback-triage`.
- The user only needs a generic, non-support marketing or email rewrite with no case, severity, or escalation context; use `omh-content-operator`.
- The request asks to send a reply, change ticket priority or status, issue a refund, modify an account, or update a helpdesk; use `omh-apps` with an explicit target and observed result.
- The request is an incident that is still open, needing severity declared, a commander assigned, and a running timeline rather than a support-case response; use `omh-live-incident-response`.
- The request is a closed incident's postmortem or reliability evidence rather than a support-case response; use `omh-reliability-review`.

## Examples

Good example:

- Prompt: Draft a calm reply for this login-outage customer and tell me whether it needs an engineering escalation.
- Expected behavior: Prepare a customer-safe reply, severity matrix, engineering escalation recommendation, and owner handoff.
- Why: The request is one support case with reply and escalation decisions, not a feedback backlog or ticket mutation.

Bad example:

- Prompt: Cluster last quarter's support feedback into roadmap opportunities.
- Expected behavior: Route to `omh-feedback-triage`, not `support-operations`.
- Why: A historical signal backlog needs product-pattern triage rather than case-level support guidance.

## Full Input, Output, and Artifact Expectations

Required inputs:

- support case
- known facts
- customer impact, support tier or SLA, and arrival time
- available ownership or escalation path

Expected outputs:

- customer-safe reply draft with stated facts, unknowns, and tone
- issue/severity/impact/escalation matrix
- internal next-step and owner handoff brief
- missing repro, account, entitlement, or approval evidence list

Artifact expectations:

- prepared support case brief when a wrapper captures it
