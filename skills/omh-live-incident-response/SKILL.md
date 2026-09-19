---
name: "omh-live-incident-response"
description: "[omh] Live incident response workflow: command an incident that is still open -- severity as declared live state, commander and roles, an append-only timeline, a recorded temporary mitigation, verified recovery, and the customer notice. Use when the user says: live-incident-response, live incident response, incident response, active incident, ongoing incident, open incident, incident open, incident commander."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, reliability]
    category: reliability
    phase: live-incident-command
    role: operator
    quality_tier: incident-command-gated
---

# Live Incident Response

This is a Hermes-native `live-incident-response` workflow skill.

## Why This Exists

`live-incident-response` exists because an incident that is still open had no owner. `support-operations` sent an active incident to `reliability-review`, and `reliability-review` reviews incident notes after the fact, so the one skill that saw the request handed it to a postmortem while the outage was still running.

## Do Not Use When

- The incident is over and the request is the postmortem, the SLO or error-budget consequence, or remediation follow-up; use `reliability-review`.
- The request is one customer's support case needing a reply, a severity opinion, and an escalation path, with no incident declared; use `support-operations`.
- The request is a release being rolled out and watched -- deploy checklist, health signals, rollback criteria -- and nothing has been declared broken; use `deploy-and-monitor`.
- The request is to send the page, publish the status-page update, or deliver the customer notice; use `connector-operator`, which records a send as observed only on a returned result.
- The request asks whether a release is ready across rollout, rollback, and observability, before anything broke; use `production-audit`.

## Examples

Good example:

- Prompt: we have a production outage right now, declare severity and assign an incident commander
- Expected behavior: Prepare live_incident_record/v1: ask for the user-visible symptom and blast radius, declare the severity with the observation that set it, name the commander and the remaining roles, open the append-only timeline, and state which signal decides recovery.
- Why: The incident is open, so severity and command are live state rather than findings to review later.

Bad example:

- Prompt: live-incident-response write up the postmortem for last week's outage and what it cost the error budget
- Expected behavior: Route to `reliability-review`: a closed incident is reviewed, never commanded.
- Why: Severity, roles, and a running timeline have no subject once the incident is over.

## Completion Checklist

- Severity is declared, carries the observation that set it, and every change appended rather than overwrote the previous level.
- One commander is named; operations, communications, and scribe each name a person or read unfilled.
- Every timeline entry is timestamped, attributed, and typed, and no earlier entry was edited.
- Each mitigation reads temporary or permanent, and a temporary one names what removes it.
- Recovery cites the named signal, its healthy value, the observed value, and the observer, never the mitigation alone.
- Paging, status-page, and customer-send entries read prepared unless a connector result was observed.

## Recovery Notes

- If nobody is named commander, ask for one before anything else; an incident without a commander produces opinions instead of decisions.
- If the recovery signal is not stated, ask which signal and which value counts as healthy before calling anything recovered.
- If the incident turns out to be closed, hand the postmortem to `reliability-review` and leave this record as the timeline it reads.
- If a connector call fails or returns nothing, keep the send prepared and name the channel that is unconfirmed instead of assuming delivery.

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+37 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when an incident is open right now and the user needs it commanded: severity declared as live state, a commander and the other roles assigned, an append-only timeline kept, a temporary mitigation recorded as temporary, recovery verified against a named signal, and the customer notice drafted. The incident is still running; once it is closed the work is a review.

    Strong routing signals: `live-incident-response`, `live incident response`, `incident response`, `active incident`, `ongoing incident`, `open incident`, `incident open`, `incident commander`, `incident command`, `incident bridge`, `incident channel`, `incident timeline`, `incident roles`, `declare severity`, `declare an incident`, `declare the incident`, `sev1`, `sev2`, `sev3`, `production outage`, `production is down`, `the site is down`, `service is down`, `we have an outage`, `outage right now`, `war room`, `stop the bleeding`, `temporary mitigation`, `page the on-call`, `page on-call`, `who is the incident commander`, `assign an incident commander`, `verify recovery`

## Catalog Metadata

Category: `reliability`
Phase: `live-incident-command`
Hermes role: `operator`
Quality tier: `incident-command-gated`
Reasoning demand: `standard`

Quality bar:

- Declare severity from the observed blast radius and record the observation that set it; an undeclared severity is not a severity, and a changed one appends rather than replaces.
- Name one commander before anything else, then name or mark unfilled each of operations, communications, and scribe.
- Give every timeline entry a timestamp, an actor, and a type -- observation, action, or decision -- per `omh-live-incident-response/references/incident-command-method.md`.
- Separate a mitigation from a fix: say what was changed, whether it is temporary, and what removes it.
- Verify recovery against the named signal at its healthy value; when that signal is unavailable the incident stays open and says so.
- Keep paging, status-page updates, and customer sends listed as prepared until a connector result is observed.

Handoff policy:

Keep severity, role assignment, the timeline, mitigation records, and recovery verification in Hermes. Paging, status-page updates, and customer sends are `connector-operator` requests recorded as observed only when the connector returns a result; rollbacks, code changes, and infrastructure operations are executor or operator work and reach the timeline as observations, never as claims.

Required inputs:

- what is broken right now, and the user-visible behavior that shows it
- blast radius: which customers, tenants, or regions, and since when
- who is available for commander, operations, communications, and scribe
- the signal that decides recovery, and the value that counts as healthy
- mitigation state so far: nothing tried, tried and failed, or in place

Expert clarification questions:
- `who is available for commander, operations, communications, and scribe`
  - English: Who is the incident commander right now, and who else is available to take operations, communications, and scribe?
  - Korean: 지금 인시던트 커맨더는 누구이고, 운영·커뮤니케이션·기록 역할을 맡을 수 있는 사람은 누구인가요?
- `the signal that decides recovery, and the value that counts as healthy`
  - English: Which signal decides that this is recovered, and what value does it have to reach?
  - Korean: 어떤 신호로 복구를 판정하며, 그 값이 얼마가 되어야 정상인가요?

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

Safety rules:

- Never rewrite or delete a timeline entry. A correction is a new entry naming the entry it corrects, because the timeline is what the review reads afterwards.
- Do not claim a page was sent, a status page was updated, or a customer was notified; those are `connector-operator` requests, observed only when the connector returns a result.
- Do not call the incident recovered because a mitigation was applied; recovery needs the named signal observed at its healthy value, with the observer recorded.
- Never leave a temporary mitigation unmarked; record what it changed and what removes it, or it becomes permanent because nobody wrote it down.
- Never print customer records, credentials, tokens, or connection strings pulled into the timeline as evidence.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
