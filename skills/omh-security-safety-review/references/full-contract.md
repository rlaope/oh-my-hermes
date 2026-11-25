# Security Safety Review

Load this on-demand contract after the compact `security-safety-review` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user asks for production readiness across release, rollback, and observability; use `omh-production-audit`.
- The user asks for merge verification commands; use `omh-verification-gate`.
- The user asks for a normal code review focused on bugs; use `omh-code-review`.
- The request is a vulnerability review of application code (injection, authorization, SSRF); use `omh-code-review`.
- The subject is an application or service rather than the agent's own runtime -- its assets, trust boundaries, attack scenarios, and the controls that defend them; use `omh-application-threat-model`.
- Something already happened to shipped code -- a CVE published against a dependency, a credential pushed to a repository, a license question about a package; use `omh-security-event-response`, which orders containment and closes only on an observed rotation or fix.

## Examples

Good example:

- Prompt: security-safety-review 이 자동화가 프롬프트 인젝션, 시크릿, 파괴적 명령 위험이 있는지 봐줘.
- Expected behavior: Prepare threat_surface_map/v1, permission/secret risk matrix, prompt injection review, safe action policy, and remediation handoff if needed.
- Why: The request is a safety review before agentic execution.

Bad example:

- Prompt: security-safety-review 시크릿 값을 출력하고 바로 권한을 바꿔줘.
- Expected behavior: Refuse secret disclosure and permission mutation, then prepare a redacted risk matrix and explicit remediation handoff.
- Why: Security safety review is redacted review and routing, not unsafe mutation.

## Full Input, Output, and Artifact Expectations

Required inputs:

- target workflow, code change, prompt, tool, dependency, or release surface
- available evidence: diff, config, package metadata, command plan, or runtime permissions
- risk tolerance and allowed actions
- known secrets, credentials, external services, or destructive operations to avoid

Expected outputs:

- security_safety_review_plan/v1
- threat_surface_map/v1
- permission_and_secret_risk_matrix/v1
- prompt_injection_risk_review/v1
- safe_action_policy/v1
- plugin_risk_audit/v1 for one explicitly named local plugin directory
- remediation_handoff/v1 when needed
- credential_rotation_sequence/v1 when a live credential must be replaced
- proposed_approval_deny_list/v1 when a blocked action is a terminal command
- not-evidence boundary

Artifact expectations:

- threat_surface_map/v1 with prompts, tools, files, dependencies, credentials, network, destructive actions, and external services
- permission_and_secret_risk_matrix/v1 with redacted findings, allowed actions, missing evidence, and escalation gates
- prompt_injection_risk_review/v1 with untrusted input boundaries and tool-use constraints
- safe_action_policy/v1 with allowed, confirmation-gated, blocked, and observed-only actions
- plugin_risk_audit/v1 with bounded aggregate local risk categories and no source disclosure
- credential_rotation_sequence/v1 attached to remediation_handoff/v1, ordering issue-new, deploy-new, verify-new, revoke-old, verify-revoked, with the overlap window and the operator who runs each step
- proposed_approval_deny_list/v1 with one `approvals.deny` glob per blocked terminal-command row of safe_action_policy/v1, quoted in YAML when it starts with an asterisk or holds a brace, an exclamation mark, or a colon; Hermes matches each glob case-insensitively against the terminal command and blocks a match even under yolo or `approvals.mode: off`, so each glob is checked against the commands the workflow still needs
