# Legal Compliance Review

Load this on-demand contract after the compact `legal-compliance-review` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user needs a final jurisdiction-specific legal opinion, legal representation, or authoritative filing decision; prepare the issue and counsel brief instead.
- The review is about code, secrets, permissions, prompt injection, dependencies, or unsafe tool behavior; use `omh-security-safety-review`.
- The request is a plain-language rewrite without a legal-risk review objective; use `omh-content-operator`.
- The user asks to sign, accept, submit, file, publish, or change a policy or contract in an external system; use `omh-apps` only after explicit authority.
- Redact the PII in the file itself and scan it before sending it, once sharing it is cleared; use `omh-data-share-review`.

## Examples

Good example:

- Prompt: Review this vendor DPA for data-processing obligations, risky clauses, and questions for counsel.
- Expected behavior: Prepare an authority-bound issue matrix, ranked risks, and counsel questions.
- Why: The request needs a prepared review and escalation aid before a legal decision.

Bad example:

- Prompt: Audit this OAuth integration for secret and permission risks.
- Expected behavior: Route to `omh-security-safety-review`, not `legal-compliance-review`.
- Why: The target is technical security risk rather than contract or compliance analysis.

## Full Input, Output, and Artifact Expectations

Required inputs:

- jurisdiction
- document or process version
- supplied authority
- review objective

Expected outputs:

- legal_scope_authority_record/v1
- legal_issue_traceability_matrix/v1
- legal_risk_counsel_hold_register/v1
- legal_negotiation_preparation/v1 when the objective is a redline rather than an assessment
- legal_review_disposition/v1

Artifact expectations:

- prepared legal and compliance issue matrix when a wrapper captures it
- legal_negotiation_preparation/v1 with one row per contested clause: the playbook position it came from, the proposed language, the fallback, and the walk-away, plus the concession order across rows

Detailed procedure steps: `references/procedure.md`.
