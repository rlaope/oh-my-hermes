---
name: "omh-legal-compliance-review"
description: "[omh] Surface contract and compliance risks, questions, and escalation points before a legal decision or action. Use when the user says: contract review, contract liability clause, regulatory analysis, compliance review, 계약서 검토, 규제 분석, 컴플라이언스 검토."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: legal-compliance-review
    role: reviewer
    quality_tier: review-gated
---

# Legal Compliance Review

This is a Hermes-native `legal-compliance-review` workflow skill.

## Why This Exists

`legal-compliance-review` prepares scoped issues for human legal review without claiming counsel or filing authority.

## Do Not Use When

- The user needs a final jurisdiction-specific legal opinion, legal representation, or authoritative filing decision; prepare the issue and counsel brief instead.
- The review is about code, secrets, permissions, prompt injection, dependencies, or unsafe tool behavior; use `security-safety-review`.
- The request is a plain-language rewrite without a legal-risk review objective; use `content-operator`.
- The user asks to sign, accept, submit, file, publish, or change a policy or contract in an external system; use `connector-operator` only after explicit authority.

## Examples

Good example:

- Prompt: Review this vendor DPA for data-processing obligations, risky clauses, and questions for counsel.
- Expected behavior: Prepare an authority-bound issue matrix, ranked risks, and counsel questions.
- Why: The request needs a prepared review and escalation aid before a legal decision.

Bad example:

- Prompt: Audit this OAuth integration for secret and permission risks.
- Expected behavior: Route to `security-safety-review`, not `legal-compliance-review`.
- Why: The target is technical security risk rather than contract or compliance analysis.

## Completion Checklist

- Findings or no-issue results are grounded in concrete file, artifact, command, or source evidence.
- Open questions, residual risk, and missing verification are named.
- Fixes or follow-up work are separate handoffs unless the user explicitly asked to implement them.

## Recovery Notes

- If the reviewed target is missing, inspect the requested artifact or ask one target question.
- If independent verification is unavailable, report the gap and avoid an approval-style claim.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `best-practice-research`, `autoresearch-goal`, `model-optimization`, `inference-serving`, `+17 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when supplied contract, policy, product, process, or regulatory context needs a scoped issue matrix, assumptions, and counsel/escalation brief.

    Strong routing signals: `contract review`, `contract liability clause`, `regulatory analysis`, `compliance review`, `계약서 검토`, `규제 분석`, `컴플라이언스 검토`

## Catalog Metadata

Category: `review`
Phase: `legal-compliance-review`
Hermes role: `reviewer`
Quality tier: `review-gated`
Reasoning demand: `standard`

Quality bar:

- Name jurisdiction, authority, document version, and unresolved questions.
- Rank issues and preserve the counsel-escalation boundary.

Handoff policy:

Keep domain framing, clarification, source/evidence synthesis, draft outputs, and next-work routing in Hermes. A prepared brief, review, reply, or plan is not an external action, approval, filing, send, publish, data mutation, implementation, review, CI, or merge claim. Prepare a connector, file, coding, or human-review handoff only when the user explicitly accepts that next step; report it only from observed evidence. The result is a prepared review and escalation aid, not legal advice, counsel sign-off, compliance certification, contract execution, filing, or regulator communication.

Required inputs:

- jurisdiction
- document or process version
- supplied authority
- review objective

Expert clarification questions:
- `jurisdiction`
  - English: Which parties, actor or data roles, operative facts, governing law and forum, and separately applicable regulatory jurisdictions are supplied?
  - Korean: 어떤 당사자, 행위자 또는 데이터 역할, 주요 사실, 준거법과 관할, 별도 적용 규제 관할권이 제공되었나요?

Expected outputs:

- legal_scope_authority_record/v1
- legal_issue_traceability_matrix/v1
- legal_risk_counsel_hold_register/v1
- legal_review_disposition/v1

Artifact expectations:

- prepared legal and compliance issue matrix when a wrapper captures it

Safety rules:

- Distinguish supplied authority from legal interpretation and final advice.
- Do not claim sign-off, certification, filing, execution, or regulator communication.

Procedure: load `references/procedure.md`.

## Runtime Evidence

Preferred harness for this skill: `critic`.

```sh
omh runtime record --skill legal-compliance-review --harness critic --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
