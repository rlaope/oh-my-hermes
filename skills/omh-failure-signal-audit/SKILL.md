---
name: "omh-failure-signal-audit"
description: "[omh] Hidden or swallowed errors suspected: find swallowed errors, unsafe fallbacks, hidden UI/runtime failures, and missing propagation before they become false green status. Use when the user says: failure-signal-audit, failure signal audit, silent failure, silent failures, silent failure hunter, swallowed error, swallowed errors, empty catch."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: failure-signal-audit
    role: reviewer
    quality_tier: workflow-surface-gated
---

# Failure Signal Audit

This is a Hermes-native `failure-signal-audit` workflow skill.

## Why This Exists

`failure-signal-audit` exists so Hermes users can ask for this workflow in chat and get a structured, checkable answer instead of an improvised one.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: failure-signal-audit check this frontend and agent trace for swallowed errors, false green status, and dangerous fallbacks.
- Expected behavior: Produce `prepare_failure_signal_audit` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: failure-signal-audit silently patch every catch block and claim the system is reliable now.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Audit scope, source surfaces, and evidence types are named.
- Swallowed errors, dangerous fallbacks, propagation gaps, and false-green claims are reported as separate finding types.
- Each finding names location or evidence ref, severity, user/operator impact, and a smallest safe remediation route.
- No remediation, runtime repair, verification, CI, merge, or future reliability claim is made without observed follow-up evidence.

## Recovery Notes

- If no code/trace/runtime evidence is supplied, prepare the audit plan and request the smallest source surface to inspect.
- If the user wants live service SLO or incident review, route to the `omh-reliability-review` workflow.
- If the user wants rendered browser proof, route frontend visual evidence to the `omh-visual-qa` workflow before any PASS is claimed.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should audit code, frontend/browser behavior, agent traces, or runtime reports for failures that were swallowed, downgraded, hidden by fallbacks, or reported as green without enough evidence.

    Strong routing signals: `failure-signal-audit`, `failure signal audit`, `silent failure`, `silent failures`, `silent failure hunter`, `swallowed error`, `swallowed errors`, `empty catch`, `ignored exception`, `hidden failure`, `hidden failures`, `dangerous fallback`, `bad fallback`, `fallback hides errors`, `missing error propagation`, `error propagation`, `console errors ignored`, `network failures ignored`, `false green`, `false pass`, `무음 실패`, `조용한 실패`, `숨은 실패`, `삼킨 에러`, `에러 삼킴`, `위험한 fallback`, `위험한 폴백`, `폴백이 에러 숨김`, `실패 신호 감사`, `실패 신호`

## Catalog Metadata

Category: `review`
Phase: `failure-signal-audit`
Hermes role: `reviewer`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.
- Hold masked-failure and intended-fallback as competing hypotheses for each suspect site, each with observed evidence for and against, until one reading is discriminated.
- Order evidence probes cheapest-discriminating-first: read the handler and its callers, then logs and traces, before demanding expensive reruns or instrumentation.
- When a check went green without an observed fix, bisect from the last run that surfaced the failure to the first that swallowed it before naming the masking change.
- Attribute a masked failure to a specific handler or fallback only with revert-verify evidence (the signal observed reappearing without it), or mark causation unproven.
- Route remediation only against a reproduced failing signal; a remediation handoff without a reproduced failure first is a guess.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- failure_signal_audit_plan/v1
- silent_failure_finding/v1 when observed
- fallback_risk_matrix/v1
- propagation_gap_map/v1
- false_green_status_review/v1
- remediation_handoff/v1 when needed

Artifact expectations:

- failure_signal_audit_plan/v1 with source boundary, surfaces, evidence types, and stop condition
- silent_failure_finding/v1 only from observed code, trace, console, network, test, or runtime evidence
- fallback_risk_matrix/v1 separating safe fallback, user-visible degraded mode, masked failure, and destructive fallback
- propagation_gap_map/v1 for missing context, lost stack, ignored async rejection, empty catch, null/empty default, or log-only handling
- false_green_status_review/v1 comparing PASS/green claims against observed checks and missing signals
- remediation_handoff/v1 only after findings are accepted and the selected owner is explicit

Artifact contracts:

This label denotes the machine-enforcement level, not a skill quality score and not an observed evidence state.

- contract_id: `failure_signal_audit_plan/v1`; enforcement_level: `guidance_only`; consumer_id: `none`

Safety rules:

- A failure signal audit is not remediation, code modification, runtime repair, console/network pass, incident closure, verification, review, CI, merge-readiness, merge, or proof that hidden failures no longer exist.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `failure-signal-audit`.

```sh
omh runtime record --skill failure-signal-audit --harness failure-signal-audit --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
