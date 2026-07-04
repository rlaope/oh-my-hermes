---
name: failure-signal-audit
description: [omh] Failure Signal Audit workflow: find swallowed errors, unsafe fallbacks, hidden UI/runtime failures, and missing propagation before they become false green status.
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

`failure-signal-audit` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.

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
- If the user wants live service SLO or incident review, route to reliability-review.
- If the user wants rendered browser proof, route frontend visual evidence to visual-qa before PASS.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: choose skills, shape work, prepare artifacts, show status, and hand off with evidence boundaries.
- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `automation-blueprint`, `github-event-ops`, `agent-board`, `gateway-intent-card`, `voice-operator`, `+18 more`) - schedules, status, health, and ops review.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match lane, name adjacent workflows; generic tool can render or execute is not dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/accessibility-audit/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit/security-safety-review; verify->verification-gate; code->codegraph-refresh/codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is setup/verification/wrapper infra.
- Boundary: Prepared OMH routing, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should audit code, frontend/browser behavior, agent traces, or runtime reports for failures that were swallowed, downgraded, hidden by fallbacks, or reported as green without enough evidence.

    Strong routing signals: `failure-signal-audit`, `failure signal audit`, `silent failure`, `silent failures`, `silent failure hunter`, `swallowed error`, `swallowed errors`, `empty catch`, `ignored exception`, `hidden failure`, `hidden failures`, `dangerous fallback`, `bad fallback`, `fallback hides errors`, `missing error propagation`, `error propagation`, `console errors ignored`, `network failures ignored`, `false green`, `false pass`, `무음 실패`, `조용한 실패`, `숨은 실패`, `삼킨 에러`, `에러 삼킴`, `위험한 fallback`, `위험한 폴백`, `폴백이 에러 숨김`, `실패 신호 감사`, `실패 신호`

## Catalog Metadata

Category: `review`
Phase: `failure-signal-audit`
Hermes role: `reviewer`
Quality tier: `workflow-surface-gated`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

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

Safety rules:

- A failure signal audit is not remediation, code modification, runtime repair, console/network pass, incident closure, verification, review, CI, merge-readiness, merge, or proof that hidden failures no longer exist.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `failure-signal-audit`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill failure-signal-audit --harness failure-signal-audit --status started
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
