---
name: "omh-production-audit"
description: "[omh] Imminent production launch or release: evaluate release, deploy, security, observability, rollback, docs, and support readiness without claiming production access. Use when the user says: production-audit, production audit, production readiness, prod audit, prod readiness, ready for production, ready to ship, ship readiness."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: production-readiness
    role: reviewer
    quality_tier: production-readiness-gated
    related_skills: [omh-reliability-review, omh-code-review]
---

# Production Audit

Required: product, service, release, or artifact scope, target environment and release channel, known test, CI, deploy, observability, security, and support evidence, rollback owner and acceptable risk threshold. Output: production_audit_plan/v1, readiness_matrix/v1, release_gate_verdict/v1, rollback_and_monitoring_plan/v1, risk_register/v1, not-evidence boundary.

## Why This Exists

`production-audit` gives OMH a preflight release surface so operators can see production risks before launch while OMH stays out of deploy and infrastructure execution.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use before launch, deploy, release, or public delivery when Hermes should check operational readiness and expose missing production evidence.

    Strong routing signals: `production-audit`, `production audit`, `production readiness`, `prod audit`, `prod readiness`, `ready for production`, `ready to ship`, `ship readiness`, `release readiness`, `launch readiness`, `preflight audit`, `operational readiness`, `rollback readiness`, `프로덕션 준비`, `출시 준비`, `운영 준비`, `릴리즈 준비`, `롤백 준비`

## Catalog Metadata

Category: `review`
Phase: `production-readiness`
Hermes role: `reviewer`
Quality tier: `production-readiness-gated`
Reasoning demand: `standard`

Quality bar:

- Name scope, environment, release channel, owners, and acceptable risk threshold.
- Check build/test/CI, security/privacy, performance, observability, rollback, docs/support, and release communication.
- Return GO, HOLD, or BLOCK only with evidence IDs and missing evidence.
- Convert remediation into explicit follow-up workflows instead of silently patching.
- Verdict: GO only when all nine rows are observed, BLOCK when any row failed an observed check, else HOLD naming the rows lacking evidence.
- Evidence floor: rollback = command exercised, restore tested, RPO/RTO; performance = load result at peak; observability = alerts to a named on-call with a runbook; security_privacy = secrets store, least privilege, cert expiry.
- End the result with a `Not checked` list: every file, path, behavior, or environment in scope that was not examined or could not run, each with a one-line reason. Write `Not checked: none` only when coverage was complete; never leave the list out, because a report that lists only findings reads as if everything else were clean.

Handoff policy:

Keep readiness synthesis in Hermes. Code fixes, deploys, infrastructure changes, security scans, and platform actions require selected executor/runtime or operator evidence.

Artifact contracts:

This label denotes the machine-enforcement level, not a skill quality score and not an observed evidence state.

- contract_id: `readiness_matrix/v1`; enforcement_level: `executable_validated`; consumer_id: `parse_readiness_matrix`

Safety rules:

- Do not claim production deploy, security scan, live traffic, monitoring health, rollback readiness, or support readiness without observed evidence.
- Do not perform deploy, infra, credential, production, or external-platform actions from the audit lane.
- Keep readiness verdict separate from implementation, CI, incident closure, or merge evidence.

## Completion Checklist

- Each of the nine matrix rows reads observed, failed, or missing, with its evidence id, and the verdict follows the GO, BLOCK, HOLD rule.
- The rollback plan names signals, owner, threshold, and recovery path; OMH deployed and scanned nothing.
- The result ends with a `Not checked` list, one reason per entry, or `Not checked: none` when coverage was complete.

## Recovery Notes

- If build or CI evidence is missing for the target release, retain the evidenced readiness_matrix/v1 rows, mark readiness unresolved, and hand back release_gate_verdict/v1 on HOLD with the missing evidence list.
- If rollback owner, health thresholds, or recovery path is missing, retain the evidenced readiness_matrix/v1 rows, mark rollback readiness unresolved, and hand back rollback_and_monitoring_plan/v1 with the exact gaps.

## Runtime Evidence

Preferred harness for this skill: `production-audit`.

```sh
omh runtime record --skill production-audit --harness production-audit --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
