---
name: "omh-reliability-review"
description: "[omh] Postmortem for an outage or SLO miss: postmortems, SLOs, error budgets, incident follow-ups, and service reliability evidence. Use when the user says: reliability-review, reliability review, incident review, incident postmortem, postmortem, post-mortem, slo review, slo."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, reliability]
    category: reliability
    phase: incident-and-slo-review
    role: operator
    quality_tier: reliability-gated
---

# Reliability Review

This is an OMH `reliability-review` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`reliability-review` exists to make SRE-style review strict: service reliability claims must point to metrics or references, and remediation remains separate from the review narrative.

## Do Not Use When

- The user only needs a generic status report or leadership deck.
- No service, incident, SLO, metric, or reliability source boundary is available.
- The request is implementation of remediation rather than review of reliability evidence.
- The incident is still open and the user needs severity declared, a commander assigned, a running timeline, and recovery verified; use `omh-live-incident-response` and review it once it is closed.

## Examples

Good example:

- Prompt: reliability-review 장애 포스트모템과 SLO 에러버짓 상태를 검토해줘.
- Expected behavior: Prepare a reliability artifact that separates metrics/references, assumptions, missing evidence, and remediation follow-ups.
- Why: The request is reliability evidence review with closure-sensitive claims.

Bad example:

- Prompt: reliability-review make a monthly PPT report for leadership.
- Expected behavior: Use `report-package` unless the report specifically asks for reliability evidence review.
- Why: Report packaging and reliability validation are independent operations surfaces.

## Completion Checklist

- Confirm the workflow target, evidence boundary, and stop condition are named.
- Report which outputs are prepared, observed, blocked, or missing.
- Name the smallest next verification or handoff instead of claiming completion from narration.

## Recovery Notes

- If metrics do not cover the named service and time window, retain the cited incident notes, mark SLO and error-budget conclusions unresolved, and hand back the evidence and missing-evidence list with the uncovered window.
- If remediation closure has no supporting reference, retain the source-backed reliability review, mark closure not_observed, and hand back the remediation follow-ups and missing closure evidence without claiming the fix completed.



## When to Use

Use when Hermes should review incident notes, SLOs, error budgets, or service reliability evidence while keeping remediation and closure claims observed.

    Strong routing signals: `reliability-review`, `reliability review`, `incident review`, `incident postmortem`, `postmortem`, `post-mortem`, `slo review`, `slo`, `sla`, `error budget`, `service reliability`, `reliability followup`, `remediation tracking`, `sre review`, `장애 리뷰`, `장애 회고`, `포스트모템`, `사후 분석`, `에러버짓`, `에러 버짓`, `서비스 신뢰성`, `신뢰성 검증`, `재발 방지`, `ревью надёжности`, `постмортем`, `разбор инцидента`, `почему падал сервис`, `стабильность стека`

## Catalog Metadata

Category: `reliability`
Phase: `incident-and-slo-review`
Quality tier: `reliability-gated`
Reasoning demand: `standard`

Quality bar:

- Name service, incident/time window, SLO/error-budget target, source references, and missing observations.
- Separate supplied metrics, incident notes, assumptions, and remediation follow-ups.
- Keep closure and remediation status unobserved until evidence is supplied.

Required inputs:

- service or incident scope
- time window
- metric/source references
- known remediation items or gaps

Expected outputs:

- reliability review
- evidence and missing-evidence list
- remediation follow-up boundary

Artifact expectations:

- omh_operation_artifact/v1 reliability-review artifact when a wrapper or CLI records it

Artifact contracts:

This label denotes the machine-enforcement level, not a skill quality score and not an observed evidence state.

- contract_id: `omh_operation_artifact/v1`; enforcement_level: `shared_operation_validated`; consumer_id: `validate_operation_artifact`

Safety rules:

- Do not claim SLO pass, healthy error budget, incident closure, or remediation completion without source, metric, or reference evidence.
- Do not treat a reliability narrative as verification, review, CI, merge, or deploy evidence.
- Route code remediation through a separate accepted plan or executor handoff.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
