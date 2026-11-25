---
name: "omh-legal-compliance-review"
description: "[omh] Business contract, NDA, or policy with legal risk: surface contract and compliance risks, questions, and escalation points before a legal decision or action. Use when the user says: contract review, contract liability clause, regulatory analysis, compliance review, contract redline, redline the contract, negotiation preparation, negotiation strategy."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: legal-compliance-review
    role: reviewer
    quality_tier: review-gated
    related_skills: [omh-security-safety-review, omh-content-operator, omh-apps, omh-data-share-review]
---

# Legal Compliance Review

Required: jurisdiction, document or process version, supplied authority, review objective. Output: legal_scope_authority_record/v1, legal_issue_traceability_matrix/v1, legal_risk_counsel_hold_register/v1, legal_negotiation_preparation/v1 when the objective is a redline rather than an assessment, legal_review_disposition/v1.

## Why This Exists

`legal-compliance-review` prepares scoped issues for human legal review without claiming counsel or filing authority.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details). Procedure: `references/procedure.md`.

## Workflow Lane

- Current lane: **Research and company ops** - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when supplied contract, policy, product, process, or regulatory context needs a scoped issue matrix, assumptions, and counsel/escalation brief.

    Strong routing signals: `contract review`, `contract liability clause`, `regulatory analysis`, `compliance review`, `contract redline`, `redline the contract`, `negotiation preparation`, `negotiation strategy`, `clause language`, `counterparty position`, `계약서 검토`, `규제 분석`, `컴플라이언스 검토`

## Catalog Metadata

Category: `review`
Phase: `legal-compliance-review`
Hermes role: `reviewer`
Quality tier: `review-gated`
Reasoning demand: `standard`

Quality bar:

- Name jurisdiction, authority, document version, and unresolved questions.
- Rank issues and preserve the counsel-escalation boundary.
- For a redline objective, tie every proposed clause to the playbook position it came from and carry its fallback and walk-away, so the negotiator sees what is being traded; an open counsel hold on a clause blocks its row rather than producing a proposal — load `references/negotiation-preparation.md` for the row shape and the concession-order rules.

Handoff policy:

Keep domain framing, clarification, source/evidence synthesis, draft outputs, and next-work routing in Hermes. A prepared brief, review, reply, or plan is not an external action, approval, filing, send, publish, data mutation, implementation, review, CI, or merge claim. Prepare a connector, file, coding, or human-review handoff only when the user explicitly accepts that next step; report it only from observed evidence. The result is a prepared review and escalation aid, not legal advice, counsel sign-off, compliance certification, contract execution, filing, or regulator communication.

Expert clarification questions:
- `jurisdiction`
  - English: Which parties, actor or data roles, operative facts, governing law and forum, and separately applicable regulatory jurisdictions are supplied?
  - Korean: 어떤 당사자, 행위자 또는 데이터 역할, 주요 사실, 준거법과 관할, 별도 적용 규제 관할권이 제공되었나요?

Safety rules:

- Distinguish supplied authority from legal interpretation and final advice.
- Do not claim sign-off, certification, filing, execution, or regulator communication.
- Proposed clause language is preparation material for the person who will negotiate, never advice about whether to accept it; a row whose playbook position cannot be cited is a counsel question, not a proposal.

Procedure: load `references/procedure.md`.

## Completion Checklist

- Every authority-dependent statement has an exact locator and effective status or is marked unverified.
- Every mandatory hold trigger is evaluated and each open one has a counsel owner and a question; the disposition is PASS, REVISE or HOLD.
- The documents and versions that were not supplied are listed; no sign-off, filing or advice is claimed.

## Recovery Notes

- If an authority's pinpoint or effective status cannot be verified, retain the established document scope, mark authority-dependent issues unresolved, and hand back legal_scope_authority_record/v1 with the missing citations for counsel.
- If a contested clause has an open counsel hold or no cited playbook position, retain its issue row, mark that redline row unresolved, and hand back the counsel question rather than proposed language.
- If mandatory counsel triggers remain open at final review, retain the issue matrix and hold register, mark legal_review_disposition/v1 unresolved with HOLD, and hand back the exact triggers and counsel owner without a final determination.

## Runtime Evidence

Preferred harness for this skill: `critic`.

```sh
omh runtime record --skill legal-compliance-review --harness critic --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
