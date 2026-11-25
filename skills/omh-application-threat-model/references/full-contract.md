# Application Threat Model

Load this on-demand contract after the compact `application-threat-model` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The subject is the agent's own prompts, tools, files, credentials, dependencies, or destructive actions; use `omh-security-safety-review`, which maps that runtime surface.
- The user wants defects found in a diff or a file; use `omh-code-review`.
- The user asks whether a release is ready across rollout, rollback, and observability; use `omh-production-audit`.
- The user asks which commands prove a merge is safe; use `omh-verification-gate`.
- The user asks for a contractual or regulatory obligation rather than an attacker; use `omh-legal-compliance-review`.

## Examples

Good example:

- Prompt: build a threat model for our payment service architecture
- Expected behavior: Prepare application_threat_model/v1: ask for the component map and data flows, register card data and settlement records as assets, mark the merchant API edge and the PSP callback as trust boundaries, derive scenarios per boundary, decide a control for each, and name the test that fails when the control is removed.
- Why: The subject is an application the user operates, and the goal needs assets, boundaries, scenarios, controls, and tests.

Bad example:

- Prompt: application-threat-model check whether this agent can be prompt-injected through its file tool
- Expected behavior: Route to `omh-security-safety-review`: prompts, tools, and credentials are the agent's runtime surface, not an application this workflow models.
- Why: The two surfaces share vocabulary and nothing else; modeling the agent's runtime here is how the artifacts get confused.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the system under review: components, which component calls which, and where each is deployed
- data flows and data classes: what every store, queue, and message carries
- known trust boundaries: authentication points, network edges, tenant separation, third parties
- controls already deployed, and who owns each
- scope exclusions and the threat actors in scope

Expected outputs:

- application_threat_model/v1
- asset register: data class plus the loss that makes each asset worth defending
- trust boundaries: what crosses, what authenticates the crossing, what the receiver assumes unchecked
- attack scenarios: entry point, path, precondition, impact
- one decision per scenario (mitigate, transfer, accept, eliminate) with an owner
- per-control security test naming the observable that fails without it, plus residual risk

Artifact expectations:

- application_threat_model/v1 with asset register, trust boundaries, attack scenarios, control decisions, and per-control tests
- every control marked deployed, planned, or unverified; a scenario with no boundary and no asset is dropped, never carried
