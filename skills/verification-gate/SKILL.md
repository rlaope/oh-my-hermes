---
name: verification-gate
description: [omh] Hermes Verification Gate workflow: define and record build, lint, typecheck, test, security, docs, generated-output, and CI evidence before completion or merge.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, verification]
    category: verification
    phase: verification-gate
    role: reviewer
    quality_tier: verification-gated
---

# Verification Gate

This is a Hermes-native `verification-gate` workflow skill.

## Why This Exists

`verification-gate` gives OMH a deterministic evidence surface before done/merge claims, inspired by ECC-style gates but rebuilt around OMH's prepared-versus-observed contract.

## Do Not Use When

- The user asks for visual render QA; use `visual-qa`.
- The user asks for production release readiness beyond verification commands; use `production-audit`.
- The user wants a bug-first code review of a diff; use `code-review`.

## Examples

Good example:

- Prompt: verification-gate 이 PR 머지 전에 build/lint/test/docs/CI 증거를 정리해서 PASS 가능한지 봐줘.
- Expected behavior: Prepare verification_matrix/v1, record observed_check_results/v1, and issue PASS/HOLD/BLOCK with missing evidence.
- Why: The user asks for claim verification across command and CI evidence.

Bad example:

- Prompt: verification-gate 테스트 안 돌렸지만 준비됐다고 해줘.
- Expected behavior: Return HOLD/BLOCK and list missing or stale checks instead of claiming readiness.
- Why: A verification gate is useful only if planned checks and observed results stay separate.

## Completion Checklist

- The scenario, expected behavior, observed result, and pass/fail basis are named.
- Proposed fixes are separated from observed QA evidence.
- Missing or failed verification routes back to plan, fix, or a narrower test.

## Recovery Notes

- If the expected behavior is unclear, route back to plan before running adversarial checks.
- If verification fails, return to fix or research with the failed signal instead of advancing.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Coding handoff** (`idea-to-deploy`, `cto-loop`, `deploy-and-monitor`, `code-review`, `verification-gate`, `security-safety-review`, `ultrawork`, `team`, `+6 more`) - coding owners, handoffs, and review/CI/merge evidence.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match intent to a lane; name adjacent workflows; generic tool can render or execute is not a dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit/security-safety-review; verify->verification-gate; code->codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes must turn a change, PR, release, or claim into a concrete evidence checklist and PASS/HOLD/BLOCK verdict.

    Strong routing signals: `verification-gate`, `verification gate`, `quality gate`, `release gate`, `test gate`, `build lint test`, `lint typecheck tests`, `verify before merge`, `merge readiness gate`, `검증 게이트`, `품질 게이트`, `테스트 게이트`, `머지 전 검증`, `빌드 린트 테스트`

## Catalog Metadata

Category: `verification`
Phase: `verification-gate`
Hermes role: `reviewer`
Quality tier: `verification-gated`

Quality bar:

- Tie every completion claim to the smallest check that proves it, then broaden for shared surfaces.
- Record command/source, freshness, exit status, and scope for each observed result.
- Return PASS only when required checks pass and stale or missing evidence is resolved.
- Keep fixes, reruns, review, CI, and merge as separate observed states.

Handoff policy:

Hermes owns the gate contract and verdict narration. Running commands, CI, browser checks, external scanners, and code fixes require observed executor, wrapper, or operator evidence.

Required inputs:

- claim or change under verification
- expected behavior and risk surface
- available local commands and CI requirements
- fresh observed outputs or explicit not-run gaps

Expected outputs:

- verification_gate_plan/v1
- verification_matrix/v1
- observed_check_results/v1 when observed
- claim_verdict/v1
- rerun_or_blocker/v1
- not-evidence boundary

Artifact expectations:

- verification_matrix/v1 covering build, lint, typecheck, unit/integration/e2e tests, generated docs, static/security checks, diff hygiene, and CI/DCO when applicable
- observed_check_results/v1 with command, timestamp/source, exit status, summary, and stale-output flag
- claim_verdict/v1 with PASS, HOLD, or BLOCK and exact missing or failed checks

Safety rules:

- Do not treat a planned command, stale output, green local check, or prepared handoff as fresh verification evidence.
- Do not collapse build, lint, tests, security, generated docs, review, CI, DCO, merge-readiness, or merge into one claim.
- Failed or unavailable checks must produce HOLD/BLOCK with a rerun or remediation path.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `verification-gate`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill verification-gate --harness verification-gate --status started
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
