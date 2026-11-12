---
name: "omh-production-audit"
description: "[omh] Imminent production launch or release: evaluate release, deploy, security, observability, rollback, docs…"
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: production-readiness
    role: reviewer
    quality_tier: production-readiness-gated
---

# Production Audit

This is an OMH `production-audit` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`production-audit` gives OMH a preflight release surface so operators can see production risks before launch while OMH stays out of deploy and infrastructure execution.

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

## Completion Checklist

- Each of the nine matrix rows reads observed, failed, or missing, with its evidence id, and the verdict follows the GO, BLOCK, HOLD rule.
- The rollback plan names signals, owner, threshold, and recovery path; OMH deployed and scanned nothing.

## Recovery Notes

- If build or CI evidence is missing for the target release, retain the evidenced readiness_matrix/v1 rows, mark readiness unresolved, and hand back release_gate_verdict/v1 on HOLD with the missing evidence list.
- If rollback owner, health thresholds, or recovery path is missing, retain the evidenced readiness_matrix/v1 rows, mark rollback readiness unresolved, and hand back rollback_and_monitoring_plan/v1 with the exact gaps.



## When to Use

Use before launch, deploy, release, or public delivery when Hermes should check operational readiness and expose missing production evidence.

    Strong routing signals: `production-audit`, `production audit`, `production readiness`, `prod audit`, `prod readiness`, `ready for production`, `ready to ship`, `ship readiness`, `release readiness`, `launch readiness`, `preflight audit`, `operational readiness`, `rollback readiness`, `프로덕션 준비`, `출시 준비`, `운영 준비`, `릴리즈 준비`, `롤백 준비`

## Catalog Metadata

Category: `review`
Phase: `production-readiness`
Quality tier: `production-readiness-gated`
Reasoning demand: `standard`

Quality bar:

- Name scope, environment, release channel, owners, and acceptable risk threshold.
- Check build/test/CI, security/privacy, performance, observability, rollback, docs/support, and release communication.
- Return GO, HOLD, or BLOCK only with evidence IDs and missing evidence.
- Convert remediation into explicit follow-up workflows instead of silently patching.
- Verdict: GO only when all nine rows are observed, BLOCK when any row failed an observed check, else HOLD naming the rows lacking evidence.
- Evidence floor: rollback = command exercised, restore tested, RPO/RTO; performance = load result at peak; observability = alerts to a named on-call with a runbook; security_privacy = secrets store, least privilege, cert expiry.

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

Artifact contracts:

This label denotes the machine-enforcement level, not a skill quality score and not an observed evidence state.

- contract_id: `readiness_matrix/v1`; enforcement_level: `executable_validated`; consumer_id: `parse_readiness_matrix`

Safety rules:

- Do not claim production deploy, security scan, live traffic, monitoring health, rollback readiness, or support readiness without observed evidence.
- Do not perform deploy, infra, credential, production, or external-platform actions from the audit lane.
- Keep readiness verdict separate from implementation, CI, incident closure, or merge evidence.

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
