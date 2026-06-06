---
name: ultraqa
description: Hermes UltraQA workflow: adversarial QA and fix loops.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, verification]
    category: verification
    phase: qa
    role: hybrid-verification
    quality_tier: scenario-gated
---

# Ultraqa

This is a Hermes-native `ultraqa` workflow skill.

## Use When

Use when the task needs adversarial test scenarios, verification, and fix loops.

    Strong routing signals: `ultraqa`, `$ultraqa`, `adversarial qa`, `hostile scenarios`, `e2e qa`, `real-world qa`, `qa scenario`, `release qa`, `장애 상황`, `쿠버네티스 장애`, `적절히 진단`, `검증 체크리스트`, `릴리즈 전 gate`

## Catalog Metadata

Category: `verification`
Phase: `qa`
Hermes role: `hybrid-verification`
Quality tier: `scenario-gated`

Quality bar:

- Generate hostile scenarios from changed behavior and known risk areas.
- Report pass/fail evidence separately from proposed fixes.
- Delegate code mutations discovered by QA to Codex-like executors.

Handoff policy:

Hermes can design scenarios and report observed results; code fixes discovered by QA should become Codex handoffs.

Required inputs:

- changed behavior
- acceptance criteria
- known risk areas

Expected outputs:

- adversarial scenarios
- pass/fail evidence
- fix recommendations

Artifact expectations:

- QA scenario evidence
- runtime verification summary

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `qa-specialist`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill ultraqa --harness qa-specialist --status started
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
