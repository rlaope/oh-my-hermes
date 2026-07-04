---
name: codebase-onboarding
description: [omh] Hermes Codebase Onboarding workflow: create a repo map, reading path, glossary, risk map, and first-task runway for unfamiliar codebases.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: codebase-onboarding
    role: planner
    quality_tier: onboarding-gated
---

# Codebase Onboarding

This is a Hermes-native `codebase-onboarding` workflow skill.

## Why This Exists

`codebase-onboarding` adapts ECC's code-tour and onboarding surfaces into an OMH-native first-read workflow so unfamiliar repos become navigable before implementation pressure starts.

## Do Not Use When

- The user already named a concrete implementation task and acceptance criteria; use `ultraprocess` or `idea-to-deploy`.
- The user needs a whole-workspace capability inventory; use `workspace-audit`.
- The user wants a code diff review; use `code-review`.

## Examples

Good example:

- Prompt: codebase-onboarding 처음 보는 레포라서 구조, 주요 모듈, 테스트, 첫 작업 후보를 잡아줘.
- Expected behavior: Prepare repo_map/v1, reading_path/v1, domain_glossary/v1, risk map, and first_task_runway/v1 from observed files.
- Why: The request is repo orientation before implementation.

Bad example:

- Prompt: codebase-onboarding 파일 안 읽고 이 레포 아키텍처를 확정해줘.
- Expected behavior: Mark architecture as unobserved and inspect source evidence before making claims.
- Why: Onboarding is only useful when grounded in current repo evidence.

## Completion Checklist

- The plan names goals, non-goals, assumptions, acceptance criteria, and verification shape.
- Draft recommendations, accepted decisions, and executor handoffs are separate states.
- Rejected options or unresolved tradeoffs are recorded before handoff.

## Recovery Notes

- If acceptance criteria or verification are missing, route back to clarification before handoff.
- If assumptions materially affect the plan, keep them visible and avoid treating the plan as accepted.

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

Use when Hermes should help an operator or coding executor understand an unfamiliar repository before planning implementation.

    Strong routing signals: `codebase-onboarding`, `codebase onboarding`, `repo onboarding`, `repository onboarding`, `codebase tour`, `code tour`, `new repo orientation`, `understand this repo`, `how this repo works`, `first task runway`, `개발자 온보딩`, `레포 온보딩`, `코드베이스 온보딩`, `처음 보는 레포`, `레포 구조 설명`

## Catalog Metadata

Category: `planning`
Phase: `codebase-onboarding`
Hermes role: `planner`
Quality tier: `onboarding-gated`

Quality bar:

- Name the audience, depth, repo root, read-only boundary, and stop condition.
- Separate observed files and commands from inferred architecture and unknowns.
- Produce a practical reading path and first-task runway rather than a flat file tour.
- Route follow-up implementation to plan, ultraprocess, verification-gate, or workspace-audit as needed.

Handoff policy:

Keep codebase orientation in Hermes as prepared local context. File reads, generated maps, and first-task recommendations need observed repo evidence; code edits and executor handoffs happen only after onboarding identifies a concrete task.

Required inputs:

- repo root or supplied source context
- target audience: operator, new contributor, maintainer, or executor
- desired depth: quick map, architecture tour, first issue, or handoff pack
- known constraints such as no network, no secrets, or read-only mode

Expected outputs:

- codebase_onboarding_plan/v1
- repo_map/v1
- reading_path/v1
- domain_glossary/v1
- risk_and_unknowns_map/v1
- first_task_runway/v1
- not-evidence boundary

Artifact expectations:

- repo_map/v1 with observed directories, entrypoints, generated surfaces, tests, docs, scripts, and runtime artifacts
- reading_path/v1 ordered from product direction to architecture, core modules, tests, and operational docs
- domain_glossary/v1 with repo-specific terms, owners, artifacts, and evidence references
- first_task_runway/v1 with low-risk starter tasks, verification commands, and handoff readiness

Safety rules:

- Do not invent architecture, ownership, maturity, or runtime behavior without observed repo evidence.
- Do not mutate files, run setup, install dependencies, or dispatch an executor from onboarding alone.
- Keep onboarding findings, inferred risks, first-task suggestions, and implementation handoffs separate.
- Never expose secrets from config or environment files; record only redacted paths and risk categories.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `codebase-onboarding`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill codebase-onboarding --harness codebase-onboarding --status started
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
