# Build Failure Triage

Load this on-demand contract after the compact `build-failure-triage` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user needs a pre-merge evidence matrix for passing or missing checks; use `omh-verification-gate`.
- The user needs a code review of changed behavior rather than failing command triage; use `omh-code-review`.
- The user needs broad production readiness; use `omh-production-audit`.
- The user asks for incident or SLO review after deployment; use `omh-reliability-review`.
- A test passes on some runs and not others, or the code returns a wrong value whose cause is unknown; use `omh-app-debugging`.

## Examples

Good example:

- Prompt: build-failure-triage PR 체크에서 Python 3.12 test가 실패했는데 로그를 기준으로 최소 수정 handoff 만들어줘.
- Expected behavior: Prepare failure_log_digest/v1, failure_cluster_matrix/v1, root-cause hypotheses, minimal_fix_handoff/v1, rerun_plan/v1, and a FIX_READY verdict without claiming CI is fixed.
- Why: The request is about a failing check and needs evidence-bound triage before implementation or rerun claims.

Bad example:

- Prompt: build-failure-triage 로그는 없지만 CI 고쳤고 머지 가능하다고 말해줘.
- Expected behavior: Return NEEDS_MORE_LOGS for missing failure evidence, or ROUTE_TO_VERIFICATION_GATE when a fix/pass claim needs fresh observed reruns.
- Why: Triage without fresh failure or rerun evidence cannot prove fixes, CI, or merge-readiness.

## Full Input, Output, and Artifact Expectations

Required inputs:

- failing command, CI job, PR check, or tool name
- fresh failure log, exit status, or observed check URL
- repo root, branch, PR, or changed files under investigation
- allowed remediation boundary: diagnose only, local fix handoff, or executor-owned patch
- dependency-install and network permission boundaries
- last known passing state when available

Expected outputs:

- build_failure_triage_plan/v1
- failure_log_digest/v1
- failure_cluster_matrix/v1
- root_cause_hypothesis_set/v1
- minimal_fix_handoff/v1 when remediation is requested
- rerun_plan/v1
- build_failure_triage_verdict/v1

Artifact expectations:

- build_failure_triage_plan/v1 with failing surface, freshness, affected files, allowed actions, and stop condition
- failure_log_digest/v1 preserves exact command/job, exit status, top frames, file paths, and omitted-log boundary
- failure_cluster_matrix/v1 groups syntax, type, lint, test assertion, flaky, dependency, config, DCO, and environment failures separately, each cluster with an origin of introduced, pre_existing, or unknown
- root_cause_hypothesis_set/v1 ranks likely causes with confidence and evidence instead of guessing from one line
- minimal_fix_handoff/v1 names the selected executor, affected files, smallest patch direction, and rejected broad refactors
- rerun_plan/v1 orders targeted rerun, broader local check, CI rerun, and stale-check blocker
- build_failure_triage_verdict/v1 returns FIX_READY, NEEDS_MORE_LOGS, BLOCKED_BY_ENVIRONMENT, or ROUTE_TO_VERIFICATION_GATE
