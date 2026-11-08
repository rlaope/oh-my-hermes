---
name: "omh-reliability-review"
description: "[omh] Postmortem for an outage or SLO miss: postmortems, SLOs, error budgets, incident follow-ups, and service reliability evidence. Use when the user says: reliability-review, reliability review, incident review, incident postmortem, postmortem, post-mortem, slo review, slo."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, reliability]
    category: reliability
    phase: incident-and-slo-review
    role: operator
    quality_tier: reliability-gated
    related_skills: [omh-live-incident-response, omh-production-audit]
---

# Reliability Review

This is a Hermes-native `reliability-review` workflow skill.

## Why This Exists

`reliability-review` exists because a reliability claim is cheap to write and expensive to check: it holds an SLO to its arithmetic and a postmortem to its structure, and keeps remediation separate from the review.

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

## Completion Checklist

- An SLO conclusion states the SLI (good over valid events), window, target, budget consumed, and burn rate, or reads unresolved.
- A postmortem draft names impact, detection and resolution times, trigger, contributing factors (systems, not people), and action items with owner and due date.
- A pre-launch review names, per dependency, its slow, down, and wrong-answer behavior and the SLOs and runbooks that exist; remediation items read open or closed with evidence.

## Recovery Notes

- If metrics do not cover the named service and time window, retain the cited incident notes, mark SLO and error-budget conclusions unresolved, and hand back the evidence and missing-evidence list with the uncovered window.
- If remediation closure has no supporting reference, retain the source-backed reliability review, mark closure not_observed, and hand back the remediation follow-ups and missing closure evidence without claiming the fix completed.

## Workflow Lane

- Current lane: **Research and company ops** - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should review incident notes, SLOs, error budgets, or service reliability evidence while keeping remediation and closure claims observed.

    Strong routing signals: `reliability-review`, `reliability review`, `incident review`, `incident postmortem`, `postmortem`, `post-mortem`, `slo review`, `slo`, `sla`, `error budget`, `service reliability`, `reliability followup`, `remediation tracking`, `sre review`, `장애 리뷰`, `장애 회고`, `포스트모템`, `사후 분석`, `에러버짓`, `에러 버짓`, `서비스 신뢰성`, `신뢰성 검증`, `재발 방지`, `ревью надёжности`, `постмортем`, `разбор инцидента`, `почему падал сервис`, `стабильность стека`

## Catalog Metadata

Category: `reliability`
Phase: `incident-and-slo-review`
Hermes role: `operator`
Quality tier: `reliability-gated`
Reasoning demand: `standard`

Quality bar:

- Name service, incident/time window, SLO/error-budget target, source references, and missing observations.
- Separate supplied metrics, incident notes, assumptions, and remediation follow-ups.
- Keep closure and remediation status unobserved until evidence is supplied.

Handoff policy:

Keep incident/SLO/error-budget review in Hermes; prepare remediation handoffs only after an accepted fix direction exists and record closure only from observed evidence.

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

Artifact contracts:

This label denotes the machine-enforcement level, not a skill quality score and not an observed evidence state.

- contract_id: `omh_operation_artifact/v1`; enforcement_level: `shared_operation_validated`; consumer_id: `validate_operation_artifact`

Safety rules:

- Do not claim SLO pass, healthy error budget, incident closure, or remediation completion without source, metric, or reference evidence.
- Do not treat a reliability narrative as verification, review, CI, merge, or deploy evidence.
- Route code remediation through a separate accepted plan or executor handoff.

## Runtime Evidence

Preferred harness for this skill: `reliability-review`.

```sh
omh runtime record --skill reliability-review --harness reliability-review --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
