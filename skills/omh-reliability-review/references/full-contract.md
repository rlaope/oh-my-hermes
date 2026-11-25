# Reliability Review

Load this on-demand contract after the compact `reliability-review` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user only needs a generic status report or leadership deck.
- No service, incident, SLO, metric, or reliability source boundary is available.
- The request is implementation of remediation rather than review of reliability evidence.
- The incident is still open and the user needs severity declared, a commander assigned, a running timeline, and recovery verified; use `omh-live-incident-response` and review it once it is closed.
- The ask is a go or hold verdict before launch; use `omh-production-audit`.

## Examples

Good example:

- Prompt: reliability-review 장애 포스트모템과 SLO 에러버짓 상태를 검토해줘.
- Expected behavior: Prepare a reliability artifact that separates metrics/references, assumptions, missing evidence, and remediation follow-ups.
- Why: The request is reliability evidence review with closure-sensitive claims.

Bad example:

- Prompt: reliability-review make a monthly PPT report for leadership.
- Expected behavior: Use `omh-report-package` unless the report specifically asks for reliability evidence review.
- Why: Report packaging and reliability validation are independent operations surfaces.

## Full Input, Output, and Artifact Expectations

Required inputs:

- service or incident scope
- time window
- metric/source references
- known remediation items or gaps
- for a pre-launch review: the dependency list, and the SLOs and runbooks that exist

Expected outputs:

- reliability review
- evidence and missing-evidence list
- remediation follow-up boundary

Artifact expectations:

- omh_operation_artifact/v1 reliability-review artifact when a wrapper or CLI records it
- a postmortem draft when one is asked for
