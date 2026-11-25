# Verification Gate

Load this on-demand contract after the compact `verification-gate` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user asks for visual render QA; use `omh-visual-qa`.
- The user asks for production release readiness beyond verification commands; use `omh-production-audit`.
- The user wants a bug-first code review of a diff; use `omh-code-review`.
- The task is solely writing unit tests first in a single RED-GREEN-REFACTOR coding loop with no pre-merge verification-gate verdict or failure-origin split; load Hermes' bundled `test-driven-development` skill instead of this one.

## Examples

Good example:

- Prompt: verification-gate 이 PR 머지 전에 build/lint/test/docs/CI 증거를 정리해서 PASS 가능한지 봐줘.
- Expected behavior: Prepare verification_matrix/v1, record observed_check_results/v1, and issue PASS/HOLD/BLOCK with missing evidence.
- Why: The user asks for claim verification across command and CI evidence.

Bad example:

- Prompt: verification-gate 테스트 안 돌렸지만 준비됐다고 해줘.
- Expected behavior: Return HOLD/BLOCK and list missing or stale checks instead of claiming readiness.
- Why: A verification gate is useful only if planned checks and observed results stay separate.

## Full Input, Output, and Artifact Expectations

Required inputs:

- claim or change under verification
- expected behavior and risk surface
- available local commands and CI requirements
- fresh observed outputs or explicit not-run gaps

Expected outputs:

- verification_gate_plan/v1
- verification_matrix/v1
- generated_artifact_provenance/v1 when the change touches a path the repository declares generated
- observed_check_results/v1 when observed
- claim_verdict/v1
- rerun_or_blocker/v1
- not-evidence boundary

Artifact expectations:

- verification_matrix/v1 covering build, lint, typecheck, unit/integration/e2e tests, generated docs, static/security checks, diff hygiene, and CI/DCO when applicable
- observed_check_results/v1 with command (verbatim, not a description of it), source (this checkout, a CI job, or an operator report), exit status, summary (what the output said), scope (what that run covered, since a narrower run proves less), freshness (when it ran, and whether the tree has moved since), and origin (for a failing check: introduced, pre_existing, or unknown)
- claim_verdict/v1 with PASS, HOLD, or BLOCK, a HOLD reason of `regression_witness_missing` when a fix test has no observed pre-fix red, and exact missing or failed checks, each failed one with its origin
- generated_artifact_provenance/v1 with one row per touched generated path: the source of truth that produces it, the regeneration command, and the drift gate that catches it, or the single state `map_not_declared` when the repository declares no generated-artifact map
