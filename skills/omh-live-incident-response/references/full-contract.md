# Live Incident Response

Load this on-demand contract after the compact `live-incident-response` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The incident is over and the request is the postmortem, the SLO or error-budget consequence, or remediation follow-up; use `omh-reliability-review`.
- The request is one customer's support case needing a reply, a severity opinion, and an escalation path, with no incident declared; use `omh-support-operations`.
- The request is a release being rolled out and watched -- deploy checklist, health signals, rollback criteria -- and nothing has been declared broken; use `omh-deploy-and-monitor`.
- The request is to send the page, publish the status-page update, or deliver the customer notice; use `omh-apps`, which records a send as observed only on a returned result.
- The request asks whether a release is ready across rollout, rollback, and observability, before anything broke; use `omh-production-audit`.

## Examples

Good example:

- Prompt: we have a production outage right now, declare severity and assign an incident commander
- Expected behavior: Prepare live_incident_record/v1: ask for the user-visible symptom and blast radius, declare the severity with the observation that set it, name the commander and the remaining roles, open the append-only timeline, and state which signal decides recovery.
- Why: The incident is open, so severity and command are live state rather than findings to review later.

Bad example:

- Prompt: live-incident-response write up the postmortem for last week's outage and what it cost the error budget
- Expected behavior: Route to `omh-reliability-review`: a closed incident is reviewed, never commanded.
- Why: Severity, roles, and a running timeline have no subject once the incident is over.

## Full Input, Output, and Artifact Expectations

Required inputs:

- what is broken right now, and the user-visible behavior that shows it
- blast radius: which customers, tenants, or regions, and since when
- who is available for commander, operations, communications, and scribe
- the signal that decides recovery, and the value that counts as healthy
- mitigation state so far: nothing tried, tried and failed, or in place

Expected outputs:

- live_incident_record/v1
- declared severity: the level, the observation that set it, and when it last changed
- role assignment naming a person per role, or recording the role unfilled
- append-only timeline: one entry per observation, action, or decision, each timestamped and attributed
- mitigation entries marked temporary or permanent, each with what removes it
- recovery verification: the signal, its healthy value, the observed value, and who observed it
- customer notice draft plus the prepared paging and status-page requests, kept apart from observed sends

Artifact expectations:

- live_incident_record/v1 with severity, roles, timeline, mitigations, recovery verification, and a communication ledger
- every communication entry reads prepared or observed and never both; a correction appends an entry and never edits one
