---
name: "omh-legal-compliance-review"
description: "[omh] Surface contract and compliance risks, questions, and escalation points before a legal decision or action. Use when the user says: contract review, contract liability clause, regulatory analysis, compliance review, contract redline, redline the contract, negotiation preparation, negotiation strategy."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: legal-compliance-review
    role: reviewer
    quality_tier: review-gated
---

# Legal Compliance Review

This is an OMH `legal-compliance-review` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

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



## Use When

Use when supplied contract, policy, product, process, or regulatory context needs a scoped issue matrix, assumptions, and counsel/escalation brief.

    Strong routing signals: `contract review`, `contract liability clause`, `regulatory analysis`, `compliance review`, `contract redline`, `redline the contract`, `negotiation preparation`, `negotiation strategy`, `clause language`, `counterparty position`, `계약서 검토`, `규제 분석`, `컴플라이언스 검토`

## Catalog Metadata

Category: `review`
Phase: `legal-compliance-review`
Quality tier: `review-gated`
Reasoning demand: `standard`

Quality bar:

- Name jurisdiction, authority, document version, and unresolved questions.
- Rank issues and preserve the counsel-escalation boundary.
- For a redline objective, tie every proposed clause to the playbook position it came from and carry its fallback and walk-away, so the negotiator sees what is being traded; an open counsel hold on a clause blocks its row rather than producing a proposal — load `references/negotiation-preparation.md` for the row shape and the concession-order rules.

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
- legal_negotiation_preparation/v1 when the objective is a redline rather than an assessment
- legal_review_disposition/v1

Artifact expectations:

- prepared legal and compliance issue matrix when a wrapper captures it
- legal_negotiation_preparation/v1 with one row per contested clause: the playbook position it came from, the proposed language, the fallback, and the walk-away, plus the concession order across rows

Safety rules:

- Distinguish supplied authority from legal interpretation and final advice.
- Do not claim sign-off, certification, filing, execution, or regulator communication.
- Proposed clause language is preparation material for the person who will negotiate, never advice about whether to accept it; a row whose playbook position cannot be cited is a counsel question, not a proposal.

Procedure: load `references/procedure.md`.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Report actual tool results or
`not_observed` / `not_available`; never invent dispatch or host accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
