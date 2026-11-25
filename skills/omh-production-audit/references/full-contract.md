# Production Audit

Load this on-demand contract after the compact `production-audit` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user wants to implement a feature or fix; prepare a coding handoff first.
- The user wants incident/SLO analysis after production behavior; use `omh-reliability-review`.
- The user wants a narrow code diff review; use `omh-code-review`.

## Examples

Good example:

- Prompt: production-audit 이 릴리즈가 운영에 나가도 되는지 테스트, CI, 롤백, 모니터링 기준으로 봐줘.
- Expected behavior: Prepare readiness_matrix/v1, release_gate_verdict/v1, rollback_and_monitoring_plan/v1, and missing-evidence list.
- Why: The request is release-readiness review, not implementation or deploy execution.

Bad example:

- Prompt: production-audit 지금 바로 prod 배포하고 정상이라고 말해줘.
- Expected behavior: Block deploy/health claims without observed operator evidence and route deploy to an explicit authorized workflow.
- Why: Production audit can assess readiness, but it cannot secretly deploy or observe live health.

## Full Input, Output, and Artifact Expectations

Required inputs:

- product, service, release, or artifact scope
- target environment and release channel
- known test, CI, deploy, observability, security, and support evidence
- rollback owner and acceptable risk threshold

Expected outputs:

- production_audit_plan/v1
- readiness_matrix/v1
- release_gate_verdict/v1
- rollback_and_monitoring_plan/v1
- risk_register/v1
- not-evidence boundary

Artifact expectations:

- readiness_matrix/v1 covering build, tests, CI, security/privacy, performance, observability, rollback, docs/support, and release communication
- release_gate_verdict/v1 with GO, HOLD, or BLOCK plus missing evidence
- rollback_and_monitoring_plan/v1 with health signals, owner, threshold, and recovery path
