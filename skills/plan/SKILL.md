---
name: plan
description: Hermes Plan workflow: structured planning before execution.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: plan
    role: retained-cognition
    quality_tier: acceptance-gated
---

# Plan

This is a Hermes-native `plan` workflow skill.

## Use When

Use for structured planning when implementation is not ready to start safely, including feature work that needs a safe plan before handoff.

    Strong routing signals: `plan`, `$plan`, `implementation plan`, `strategy`, `task breakdown`, `safe feature`, `safely add a feature`, `add a feature`, `feature request`, `new feature`, `product triage`, `bug triage`, `issue triage`, `reproduction plan`, `workflow hub`, `coding handoff`, `답할 차례`, `준비할 차례`, `project template`, `결제 실패`, `결제 실패 이슈`, `재현 계획`, `고객 피드백`, `기능 요청`, `요구사항 정리`, `작업 허브`, `작업 허브가 필요`, `github pr workflow`, `상태와 다음 행동`, `프로젝트별 운영`

## Catalog Metadata

Category: `planning`
Phase: `plan`
Hermes role: `retained-cognition`
Quality tier: `acceptance-gated`

Quality bar:

- Make goals, non-goals, risks, acceptance criteria, and verification shape explicit.
- Keep draft plans unapproved until a user or wrapper accepts them.
- Only prepare coding handoff guidance after the plan is accepted.

Handoff policy:

Keep planning in Hermes; if the accepted plan requires code edits, prepare a Codex handoff after acceptance.

Required inputs:

- requirements
- constraints
- known facts
- non-goals

Expected outputs:

- plan
- acceptance criteria
- verification strategy

Artifact expectations:

- plan artifact when durable execution will follow

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `planning`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill plan --harness planning --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers or explicit checklists,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
