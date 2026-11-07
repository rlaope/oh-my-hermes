---
name: "omh-verification-gate"
description: "[omh] Proof a change is done before merge: define and record build, lint, typecheck, test, security, docs, generated-output, and CI evidence before completion or merge. Use when the user says: verification-gate, verification gate, quality gate, run the release gate, release gate check, test gate, build lint test, lint typecheck tests."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, verification]
    category: verification
    phase: verification-gate
    role: reviewer
    quality_tier: verification-gated
---

# Verification Gate

This is an OMH `verification-gate` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`verification-gate` gives OMH a deterministic evidence surface before done/merge claims: every claim maps to a check that was observed, with its scope and freshness; the gate shape is inspired by ECC and rebuilt around the prepared-versus-observed contract.

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
- Missing or failed verification routes back to `omh-plan`, fix, or a narrower test.

## Recovery Notes

- If a required check fails with an unknown origin, keep the other fresh results, mark the claim unresolved on HOLD, and hand back the same check rerun at the merge base as the missing evidence.
- If a fix test has only a fresh green result, retain that result within its scope, mark the claim unresolved on HOLD with regression_witness_missing, and hand back the required pre-fix red witness and its source.
- If a declared generated path has no known regeneration command, retain verification_matrix/v1, mark generated-output verification unresolved, and hand back generated_artifact_provenance/v1 with the command gap.



## When to Use

Use when Hermes must turn a change, PR, release, or claim into a concrete evidence checklist and PASS/HOLD/BLOCK verdict.

    Strong routing signals: `verification-gate`, `verification gate`, `quality gate`, `run the release gate`, `release gate check`, `test gate`, `build lint test`, `lint typecheck tests`, `verify before merge`, `merge readiness gate`, `generated file`, `generated artifact`, `generated output`, `source of truth`, `regenerate instead of editing`, `検証ゲート`, `品質ゲート`, `マージ前の検証`, `リリース前チェック`, `검증 게이트`, `품질 게이트`, `테스트 게이트`, `머지 전 검증`, `빌드 린트 테스트`, `перед мерджем проверь`, `проверь перед пушем`, `гейт проверки`, `проверь перед мерджем`, `докажи что тесты проходят`, `验证门禁`, `质量门禁`, `合并前验证`, `发布前检查`, `verifikasi sebelum merge`, `buktikan perubahan ini sudah selesai`, `cek bukti build lint dan tes`, `pastikan semua pemeriksaan lulus sebelum merge`, `tolong validasi hasil implementasi ini`, `xác minh trước khi gộp`, `xác minh trước khi merge`, `chứng minh thay đổi này đã hoàn thành`, `kiểm tra bằng chứng build lint và kiểm thử`, `đảm bảo mọi kiểm tra đều đạt trước khi gộp`, `đảm bảo tất cả kiểm tra đạt trước khi merge`, `hãy xác thực kết quả thực hiện này`

## Catalog Metadata

Category: `verification`
Phase: `verification-gate`
Quality tier: `verification-gated`
Reasoning demand: `standard`

Quality bar:

- When adapting an existing capability, read `../omh-verification-gate/references/adaptation-quality.md` before accepting a plan, dispatching work, or claiming completion; carry its criteria and comparisons into tasks and evidence.
- Tie every completion claim to the smallest check that proves it, then broaden for shared surfaces.
- When a diff touches a declared generated path, name its source of truth and regeneration command before the edit rather than after a byte gate rejects it; a diff touching a generator and its output together is the correct shape, not a violation — load `references/generated-artifact-provenance.md` for the declaration and reporting rules.
- Record every field the `observed_check_results/v1` artifact expectation below names, for each observed result (`origin` on a failing check only); a field left out is a gap in the record, not a shorter record.
- On Hermes, for native `omh_todo` checkpoints, `record` then `recall` this verification declaration. Stored declarations are not proof.
- When the change answers to a written spec, plan, or issue, load `references/requirement-coverage-map.md` and map requirement to task to evidence under stable ids before claiming coverage.
- Give each failing check an `origin`: `introduced` when the same command passes at the merge-base or the failure points at a line the diff added or changed; `pre_existing` only when an observed run of the same command fails the same way at the merge-base in a clean detached worktree (`git worktree add --detach <dir> <merge-base>`, removed afterwards), never by stashing or checking out the tree the user is working in; otherwise `unknown`. An observed merge-base run outranks a diff-line reading: a check that fails the same way at the merge-base is `pre_existing` even when its failure points at a line the diff changed. Name the proof beside the origin: a merge-base run is an observation, a diff-line reading is an inference. A failing test is `introduced` only after one rerun at head fails again; with no rerun, or a green one, its origin stays `unknown` and the missing evidence is the failure rate, measured at head and at the merge-base with the same command and the same N. A head rate near the merge-base rate is `pre_existing`; a higher head rate is `introduced`, with the two rates as its proof, and its remediation is a root-cause investigation (`omh-app-debugging`), not a one-line fix.
- A fix claim whose evidence is a new or changed test needs a regression witness: an observed red of that test, for the bug's reason, on the pre-fix tree (the fix commit's parent, or the merge-base when the fix is the whole change), recorded with its source -- a run in a clean detached worktree at that tree, a CI job on a commit that adds only the test, or the debugging session's run before the fix. A collection or import error there is not a witness. For an intermittent fault the witness is the failure rate over N runs before beside 0/N at the same N after, with N sized from the pre-fix rate p as N >= ln(0.05) / ln(1 - p), about 3 / p. When the test calls a seam the fix added, force the red by reverting only the behavioural lines, keep the seam, and show that diff. When the fix changes only test code, the witness is the old test's measured failure rate on the pre-fix tree beside the new test's 0/N at the same N. A fix test only ever observed green is HOLD with `regression_witness_missing`. A fix recorded with `regression_seam: none_correct` and its reason has no fix test; its evidence is the reproduction loop observed red before and green after (for an intermittent fault, its rate over N runs before beside 0/N after), and the test witness rule does not apply.
- Take the required set from the repository, not from what happened to run: branch protection or ruleset required status checks (a repository that uses rulesets has none: `gh api repos/{owner}/{repo}/branches/{base}/protection/required_status_checks` answers 404 there; read `gh api repos/{owner}/{repo}/rules/branches/{base}` and take the contexts of its `required_status_checks` rule), the CI workflow, and the contributor docs; name which source defined required. Then compare those contexts with the results (`gh pr view <n> --json statusCheckRollup`): a required context with no result is missing evidence, not a pass. `gh pr checks --required` lists only checks that already exist, so it can read green while a required check has not started.
- Return PASS only when required checks pass and stale or missing evidence is resolved; PASS never stands beside a failing required check, whatever its origin. A required check that fails `pre_existing` is HOLD worded as not charged to the change, naming the merge-base run that proves it, and only when the failing run's scope still covered the change: a failure that stopped the check before it exercised the change, such as a collection or import error, leaves that check as missing evidence. `unknown` is HOLD with the merge-base run named as the missing evidence (for a failing test, the failure rate at head and at the merge-base).
- Keep fixes, reruns, review, CI, and merge as separate observed states.

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

Safety rules:

- Do not treat a planned command, stale output, green local check, or prepared handoff as fresh verification evidence.
- Read generated paths from a map the repository declares; where none exists report `map_not_declared` and never infer one from filename patterns, directory names, or a generated-file header, because a false positive redirects correct work while the miss it prevents only costs a rerun.
- Do not collapse build, lint, tests, security, generated docs, review, CI, DCO, merge-readiness, or merge into one claim.
- Failed or unavailable checks must produce HOLD/BLOCK with a rerun or remediation path.
- A change touching an authentication, secrets/config, schema/migration, or payment/crypto path escalates to the thorough verification lane regardless of diff size: add a negative test that fails if the guard is removed, a migration run up and down on a copy, a secrets scan of the diff, and a second reader (`omh-code-review`); the verdict stays HOLD until each is observed or listed as missing.
- Refuse completion, do not merely report it, when the claim carries an unlinked TODO/FIXME/stub marker in changed code, a suppressed test with no linked reason, placeholder or self-referential evidence ('TBD', 'works as expected'), or a proof word ('fixed', 'verified', 'passing') with no observed evidence naming a command; each refusal names its category, the offending excerpt, and the remedy.
- Before a diff deletes a validation/refusal/sanitization/permission/allowlist check at a trust boundary, or a negative test named for it ('refuses', 'rejects', 'denies', 'blocks', 'invalid'), require a named adversarial or regression case proving the boundary still refuses what it should; a guard that only moves elsewhere in the same diff is not a deletion, but a deletion with no negative case behind it -- in the diff or named in evidence -- earns no completion claim.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
