---
name: instinct-ledger
description: [omh] Instinct Ledger workflow: turn repeated project or cross-project lessons into atomic, confidence-scored instinct candidates with scoped promotion and export boundaries.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, optimization]
    category: optimization
    phase: instinct-ledger
    role: tracker
    quality_tier: workflow-surface-gated
---

# Instinct Ledger

This is a Hermes-native `instinct-ledger` workflow skill.

## Why This Exists

`instinct-ledger` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: instinct-ledger turn these repeated OMH review lessons into project-scoped instincts and show which ones could be promoted globally.
- Expected behavior: Produce `prepare_instinct_ledger` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: instinct-ledger silently install hooks, learn from every prompt, and mutate all skills globally.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Each instinct is atomic: one trigger, one action, one scope, confidence, evidence refs, and review state.
- Project-specific conventions, global practices, project/global promotion candidates, imports, and exports are separated.
- No hooks, memory writes, skill edits, global promotion, import/export, or behavior-change claims are made without observed approval and implementation evidence.

## Recovery Notes

- If the request is a single missed route or run trace, route to workflow-learning first.
- If the request is to mutate durable rules, prompts, skills, or AGENTS guidance, route to rules-distill or implementation after review approval.
- If evidence comes from a stuck run, use agent-debug before converting lessons into instincts.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: choose skills, shape work, prepare artifacts, show status, and hand off with evidence boundaries.
- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `automation-blueprint`, `github-event-ops`, `agent-board`, `gateway-intent-card`, `voice-operator`, `+30 more`) - schedules, status, health, and ops review.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: every OMH skill: match lane; generic tool can render or execute.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/a11y/visual-qa; paper->paper-learning; content->content-operator; media->media-input-operator; file->materials-package; search->web-research; live->live-info-operator; audit->workspace/production/security; failures->build-failure; verify->verification-gate; code->codegraph/onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is infra.
- Boundary: Prepared OMH routing, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should review repeated observations, user corrections, workflow lessons, or failure patterns as atomic project-scoped or global instinct candidates with confidence, evidence, promotion, import, or export decisions.

    Strong routing signals: `instinct-ledger`, `instinct ledger`, `project instincts`, `project-scoped instincts`, `project scoped instincts`, `global instincts`, `instinct review`, `instinct candidate`, `instinct candidates`, `instinct promotion`, `promote instinct`, `promote learning`, `confidence scored learning`, `confidence-scored learning`, `project learning patterns`, `cross-project learning`, `export instincts`, `import instincts`, `학습 본능`, `프로젝트별 학습`, `프로젝트 스코프 학습`, `전역 학습 승격`, `학습 승격`, `학습 패턴 승격`

## Catalog Metadata

Category: `optimization`
Phase: `instinct-ledger`
Hermes role: `tracker`
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

- instinct_ledger_plan/v1
- instinct_candidate/v1
- project_instinct_scope_map/v1
- instinct_promotion_review/v1
- instinct_export_review/v1 when requested

Artifact expectations:

- instinct_candidate/v1 with trigger, action, confidence, domain, scope, source evidence, non-goals, and review state
- project_instinct_scope_map/v1 separating project, global, imported, and promotion-candidate instincts
- instinct_promotion_review/v1 with repeated evidence, confidence threshold, conflicts, and approval state
- instinct_export_review/v1 with redaction, destination, import/export trust gaps, and raw-observation exclusion when requested

Safety rules:

- An instinct ledger is not hook installation, automatic observation, model training, hidden memory mutation, skill mutation, prompt mutation, global rule promotion, import, export, or proof that future behavior changed. Record only reviewed candidate instincts, confidence, scope, promotion state, and evidence gaps.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `instinct-ledger`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill instinct-ledger --harness instinct-ledger --status started
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
