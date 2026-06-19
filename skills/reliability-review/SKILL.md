---
name: reliability-review
description: [omh] Hermes Reliability Review workflow: postmortems, SLOs, error budgets, incident follow-ups, and service reliability evidence.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, reliability]
    category: reliability
    phase: incident-and-slo-review
    role: operator
    quality_tier: reliability-gated
---

# Reliability Review

This is a Hermes-native `reliability-review` workflow skill.

## Why This Exists

`reliability-review` exists to make SRE-style review strict: service reliability claims must point to metrics or references, and remediation remains separate from the review narrative.

## Do Not Use When

- The user only needs a generic status report or leadership deck.
- No service, incident, SLO, metric, or reliability source boundary is available.
- The request is implementation of remediation rather than review of reliability evidence.

## Examples

Good example:

- Prompt: reliability-review 장애 포스트모템과 SLO 에러버짓 상태를 검토해줘.
- Expected behavior: Prepare a reliability artifact that separates metrics/references, assumptions, missing evidence, and remediation follow-ups.
- Why: The request is reliability evidence review with closure-sensitive claims.

Bad example:

- Prompt: reliability-review make a monthly PPT report for leadership.
- Expected behavior: Use `report-package` unless the report specifically asks for reliability evidence review.
- Why: Report packaging and reliability validation are independent operations surfaces.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, surface status, and hand off to tools or coding agents without hiding unobserved execution.
- Current lane: **Research and company ops** (`web-research`, `best-practice-research`, `autoresearch-goal`, `research-brief`, `strategy-brief`, `feedback-triage`, `research-department`, `meeting-brief`, `operating-rhythm`, `ops-review`, `reliability-review`) - source-backed research, customer signals, product operations, and briefing workflows.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: Carry this context across every OMH skill, not only image or coding skills: match the user's intent to the nearest workflow lane, name adjacent OMH workflows when the request crosses lanes, and keep the next action clear.
- Coverage: Every generated workflow skill carries an OMH Context Rail derived from this awareness payload.
- Normal users talk to Hermes; OMH CLI commands are backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should review incident notes, SLOs, error budgets, or service reliability evidence while keeping remediation and closure claims observed.

    Strong routing signals: `reliability-review`, `reliability review`, `incident review`, `incident postmortem`, `postmortem`, `post-mortem`, `slo review`, `slo`, `sla`, `error budget`, `service reliability`, `reliability followup`, `remediation tracking`, `sre review`, `장애 리뷰`, `장애 회고`, `포스트모템`, `사후 분석`, `에러버짓`, `에러 버짓`, `서비스 신뢰성`, `신뢰성 검증`, `재발 방지`

## Catalog Metadata

Category: `reliability`
Phase: `incident-and-slo-review`
Hermes role: `operator`
Quality tier: `reliability-gated`

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

Expected outputs:

- reliability review
- evidence and missing-evidence list
- remediation follow-up boundary

Artifact expectations:

- operation_artifact/v1 reliability-review artifact when a wrapper or CLI records it

Safety rules:

- Do not claim SLO pass, healthy error budget, incident closure, or remediation completion without source, metric, or reference evidence.
- Do not treat a reliability narrative as verification, review, CI, merge, or deploy evidence.
- Route code remediation through a separate accepted plan or executor handoff.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `reliability-review`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill reliability-review --harness reliability-review --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- Treat wrapper-supplied memory/context summaries as advisory local context, not proof that opaque Hermes memory was read or changed.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, `goal_continuation/v1`, or explicit checklists with named next actions,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
