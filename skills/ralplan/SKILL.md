---
name: ralplan
description: [omh] Hermes Ralplan workflow: consensus planning with review gates.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: reviewed-plan
    role: planner
    quality_tier: reviewed-plan-gated
---

# Ralplan

This is a Hermes-native `ralplan` workflow skill.

## Why This Exists

`ralplan` exists to make planning reviewable before execution: Hermes should gather codebase/source facts, compare options, expose risks, define acceptance criteria, and prepare a handoff without pretending implementation already happened.

## Do Not Use When

- The request is still too ambiguous to name requirements, non-goals, or acceptance criteria; use `deep-interview` first.
- The user asks for one full research-plan-implementation-review-PR cycle; use `ultraprocess` and keep ralplan as the planning stage.
- The user wants a pure source lookup, citation check, or paper explanation with no implementation plan.

## Examples

Good example:

- Prompt: $ralplan turn this risky refactor into a reviewable plan with acceptance criteria and verification commands.
- Expected behavior: Produce repo/source facts, alternatives, risk review, acceptance criteria, exact verification commands, and handoff readiness without editing code.
- Why: The request is clear enough to plan but risky enough to require consensus-style review before execution.

Bad example:

- Prompt: $ralplan implement the refactor now and open the PR.
- Expected behavior: Stop at the reviewed plan or route the full delivery cycle to `ultraprocess` after plan acceptance.
- Why: Ralplan is a planning gate, not implementation, review, CI, or PR evidence.

## Completion Checklist

- Observed repo facts and source/web evidence gaps are named.
- At least two options or one chosen option plus rejected alternatives are recorded.
- Risks, acceptance criteria, and verification commands are testable or explicitly blocked.
- The implementation handoff is prepared only after plan acceptance and remains prepared_not_observed.

## Recovery Notes

- If requirements are still fuzzy, route back to deep-interview before planning.
- If current-source evidence is missing, route a web-research step before accepting the plan.
- If the user asks for implementation, hand off through ultraprocess, ultragoal, or the selected executor path after the plan is accepted.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Intent -> plan** (`oh-my-hermes`, `deep-interview`, `plan`, `ralplan`, `codebase-onboarding`, `ultragoal`, `ultraprocess`, `loop`, `+2 more`) - clarify, plan, ship, or loop scoped goals.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match intent to a lane; name adjacent workflows; generic tool can render or execute is not a dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit/security-safety-review; verify->verification-gate; code->codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when requirements are clear enough for planning but architecture, evidence, alternatives, risks, or tests need a reviewed plan before execution.

    Strong routing signals: `ralplan`, `$ralplan`, `consensus plan`, `reviewed plan`, `issue to PR`, `acceptance criteria`, `verification command`, `reviewable PR`, `risky planning`, `dangerous`, `dangerous planning`, `unsafe`, `refactor safety`, `PR로 만들`, `PR로 만들 수 있게`, `위험한 리팩터링`, `리팩터링 위험`, `리스크 있는 리팩터링`, `검증 command`, `리뷰 가능한 단위`, `코드베이스 조사`, `웹리서치 계획`, `대안 비교`, `리스크 검토`

## Catalog Metadata

Category: `planning`
Phase: `reviewed-plan`
Hermes role: `planner`
Quality tier: `reviewed-plan-gated`

Quality bar:

- Start from observed repo facts and source/web evidence when freshness or external behavior matters.
- Include planner view, critic/risk review, alternative paths, rejected options, and a testability check before handoff.
- Produce testable acceptance criteria and exact verification commands or explain why they are not yet knowable.
- Record unresolved tradeoffs and evidence gaps instead of flattening uncertainty.
- End with a selected executor/runtime handoff shape only after the plan is accepted.
- Do not implement directly from consensus planning.

Handoff policy:

Keep consensus planning and review in Hermes; produce explicit selected executor/runtime handoff guidance only after the plan is accepted.

Required inputs:

- requirements
- codebase facts
- source or web evidence when needed
- options
- tradeoffs
- test shape

Expected outputs:

- reviewed plan
- acceptance criteria
- risk register
- verification commands
- handoff guidance

Artifact expectations:

- plan and review artifacts when a wrapper supports file-backed planning

Safety rules:

- Do not implement directly from the planning lane.
- Do not invent codebase or web evidence; label missing evidence and source gaps.
- Make acceptance criteria testable.
- Record unresolved tradeoffs explicitly.
- Keep rejected options and handoff readiness separate from accepted execution evidence.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `planning`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill ralplan --harness planning --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
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
