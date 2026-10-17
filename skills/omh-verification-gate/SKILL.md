---
name: "omh-verification-gate"
description: "[omh] Proof a change is done before merge: define and record build, lint, typecheck, test, security, docs, generated-output, and CI evidence before completion or merge. Use when the user says: verification-gate, verification gate, quality gate, release gate, test gate, build lint test, lint typecheck tests, verify before merge."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, verification]
    category: verification
    phase: verification-gate
    role: reviewer
    quality_tier: verification-gated
    related_skills: [omh-visual-qa, omh-production-audit, omh-code-review]
---

# Verification Gate

This is a Hermes-native `verification-gate` workflow skill.

## Why This Exists

`verification-gate` gives OMH a deterministic evidence surface before done/merge claims, inspired by ECC-style gates but rebuilt around OMH's prepared-versus-observed contract.

## Do Not Use When

- The user asks for visual render QA; use `omh-visual-qa`.
- The user asks for production release readiness beyond verification commands; use `omh-production-audit`.
- The user wants a bug-first code review of a diff; use `omh-code-review`.

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

## Workflow Lane

- Current lane: **Coding handoff** (`idea-to-deploy`, `llm-app-dev`, `cto-loop`, `deploy-and-monitor`, `code-review`, `build-failure-triage`, `verification-gate`, `security-safety-review`, `+28 more`) - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes must turn a change, PR, release, or claim into a concrete evidence checklist and PASS/HOLD/BLOCK verdict.

    Strong routing signals: `verification-gate`, `verification gate`, `quality gate`, `release gate`, `test gate`, `build lint test`, `lint typecheck tests`, `verify before merge`, `merge readiness gate`, `generated file`, `generated artifact`, `generated output`, `source of truth`, `regenerate instead of editing`, `検証ゲート`, `品質ゲート`, `マージ前の検証`, `リリース前チェック`, `검증 게이트`, `품질 게이트`, `테스트 게이트`, `머지 전 검증`, `빌드 린트 테스트`, `验证门禁`, `质量门禁`, `合并前验证`, `发布前检查`, `verifikasi sebelum merge`, `buktikan perubahan ini sudah selesai`, `cek bukti build lint dan tes`, `pastikan semua pemeriksaan lulus sebelum merge`, `tolong validasi hasil implementasi ini`

## Catalog Metadata

Category: `verification`
Phase: `verification-gate`
Hermes role: `reviewer`
Quality tier: `verification-gated`
Reasoning demand: `standard`

Quality bar:

- Tie every completion claim to the smallest check that proves it, then broaden for shared surfaces.
- When a diff touches a declared generated path, name its source of truth and regeneration command before the edit rather than after a byte gate rejects it; a diff touching a generator and its output together is the correct shape, not a violation — load `references/generated-artifact-provenance.md` for the declaration and reporting rules.
- Record every field the `observed_check_results/v1` artifact expectation below names, for each observed result (`origin` on a failing check only); a field left out is a gap in the record, not a shorter record.
- For native `omh_todo` checkpoints, load the todo-checklist closing recipe; `record` then `recall` this verification declaration. Stored declarations are not proof.
- When the change answers to a written spec, plan, or issue, load `references/requirement-coverage-map.md` and map requirement to task to evidence under stable ids before claiming coverage.
- Give each failing check an `origin`: `introduced` when the same command passes at the merge-base or the failure points at a line the diff added or changed; `pre_existing` only when an observed run of the same command fails the same way at the merge-base in a clean detached worktree (`git worktree add --detach <dir> <merge-base>`, removed afterwards), never by stashing or checking out the tree the user is working in; otherwise `unknown`. An observed merge-base run outranks a diff-line reading: a check that fails the same way at the merge-base is `pre_existing` even when its failure points at a line the diff changed. Name the proof beside the origin: a merge-base run is an observation, a diff-line reading is an inference.
- Return PASS only when required checks pass and stale or missing evidence is resolved; PASS never stands beside a failing required check, whatever its origin. A required check that fails `pre_existing` is HOLD worded as not charged to the change, naming the merge-base run that proves it, and only when the failing run's scope still covered the change: a failure that stopped the check before it exercised the change, such as a collection or import error, leaves that check as missing evidence. `unknown` is HOLD with the merge-base run named as the missing evidence.
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
- generated_artifact_provenance/v1 when the change touches a path the repository declares generated
- observed_check_results/v1 when observed
- claim_verdict/v1
- rerun_or_blocker/v1
- not-evidence boundary

Artifact expectations:

- verification_matrix/v1 covering build, lint, typecheck, unit/integration/e2e tests, generated docs, static/security checks, diff hygiene, and CI/DCO when applicable
- observed_check_results/v1 with command (verbatim, not a description of it), source (this checkout, a CI job, or an operator report), exit status, summary (what the output said), scope (what that run covered, since a narrower run proves less), freshness (when it ran, and whether the tree has moved since), and origin (for a failing check: introduced, pre_existing, or unknown)
- claim_verdict/v1 with PASS, HOLD, or BLOCK and exact missing or failed checks, each failed one with its origin
- generated_artifact_provenance/v1 with one row per touched generated path: the source of truth that produces it, the regeneration command, and the drift gate that catches it, or the single state `map_not_declared` when the repository declares no generated-artifact map

Safety rules:

- Do not treat a planned command, stale output, green local check, or prepared handoff as fresh verification evidence.
- Read generated paths from a map the repository declares; where none exists report `map_not_declared` and never infer one from filename patterns, directory names, or a generated-file header, because a false positive redirects correct work while the miss it prevents only costs a rerun.
- Do not collapse build, lint, tests, security, generated docs, review, CI, DCO, merge-readiness, or merge into one claim.
- Failed or unavailable checks must produce HOLD/BLOCK with a rerun or remediation path.
- A change touching an authentication, secrets/config, schema/migration, or payment/crypto path escalates to the thorough verification lane regardless of diff size.
- Refuse completion, do not merely report it, when the claim carries an unlinked TODO/FIXME/stub marker in changed code, a suppressed test with no linked reason, placeholder or self-referential evidence ('TBD', 'works as expected'), or a proof word ('fixed', 'verified', 'passing') with no observed evidence naming a command; each refusal names its category, the offending excerpt, and the remedy.
- Before a diff deletes a validation/refusal/sanitization/permission/allowlist check at a trust boundary, or a negative test named for it ('refuses', 'rejects', 'denies', 'blocks', 'invalid'), require a named adversarial or regression case proving the boundary still refuses what it should; a guard that only moves elsewhere in the same diff is not a deletion, but a deletion with no negative case behind it -- in the diff or named in evidence -- earns no completion claim.

## Runtime Evidence

Preferred harness for this skill: `verification-gate`.

```sh
omh runtime record --skill verification-gate --harness verification-gate --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a stop condition or a decision the user owns ends the turn, offer the next action as a question rather than declaring what will not be done.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
