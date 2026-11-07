---
name: "omh-application-threat-model"
description: "[omh] Attack paths into an operated system: turn a system's components and data flows into assets, trust boundaries, attack scenarios, controls, and the security test that proves each control holds. Use when the user says: application-threat-model, application threat model, threat model, threat modeling, threat modelling, threat modeling session, threat modeling workshop, security threat model."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: application-threat-model
    role: reviewer
    quality_tier: security-safety-gated
---

# Application Threat Model

This is an OMH `application-threat-model` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`application-threat-model` exists because the nearest neighbour does not merely miss this request. `omh-security-safety-review` maps the agent's own prompt, tool, credential, and dependency surface, so an application threat-model request came back as an agent tool inventory under a near-identical name — a confident wrong artifact rather than a miss, in the one domain where that costs most.

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

## Completion Checklist

- Every asset carries a data class and one named loss; every boundary names what crosses it and what authenticates the crossing.
- Every scenario resolves to mitigate, transfer, accept, or eliminate, with an owner.
- Every mitigating control carries a security test and the observable that fails without it.
- Controls read deployed, planned, or `unverified`; none is inferred from the architecture description.
- Residual risk is listed, and the model is not offered as a scan, a penetration test, or an attestation.

## Recovery Notes

- If the architecture is not described, ask for the component map and the data flows before modeling; never substitute a generic checklist for the real system.
- If a scenario has no boundary and no asset, drop it with the reason rather than carrying an unreachable threat.
- If the user asks for exploit code, give the precondition and the detection signal instead, then hand remediation to an executor.
- If the request turns out to be about the agent's own prompts, tools, or credentials, stop and hand it to `omh-security-safety-review`.



## When to Use

Use when Hermes must model the security of an application, service, or deployed system the user operates: which assets are worth taking, where trust changes hands, how an attacker reaches each asset, which control stops them, and which security test fails when that control is removed. The subject is the modeled system, never the agent's own runtime.

    Strong routing signals: `application-threat-model`, `application threat model`, `threat model`, `threat modeling`, `threat modelling`, `threat modeling session`, `threat modeling workshop`, `security threat model`, `build a threat model`, `model the threats`, `threat scenarios`, `stride analysis`, `stride model`, `trust boundary`, `trust boundaries`, `attack scenario`, `attack scenarios`, `attack tree`, `attack trees`, `abuse case`, `abuse cases`, `security design review`, `security architecture review`, `architecture security review`, `how would an attacker`, `how could an attacker`, `what could an attacker do`, `attacker perspective`

## Catalog Metadata

Category: `review`
Phase: `application-threat-model`
Quality tier: `security-safety-gated`
Reasoning demand: `standard`

Quality bar:

- Name every component, data store, and external dependency of the real system before naming one threat; a model of a system nobody described is a checklist.
- Give each asset a data class and its primary loss: disclosure, corruption, unavailability, or fraud.
- For each trust boundary, state what crosses it, what authenticates the crossing, and what the receiver assumes without checking.
- Run all six STRIDE prompts from `omh-application-threat-model/references/threat-model-method.md` per boundary; drop an unreachable scenario with its reason instead of carrying it.
- Resolve every scenario to one decision (mitigate, transfer, accept, eliminate) with an owner, and give every mitigating control a test whose observable fails when the control is removed.
- Rank scenarios by likelihood times impact; accept only below the owner's limit.

Required inputs:

- the system under review: components, which component calls which, and where each is deployed
- data flows and data classes: what every store, queue, and message carries
- known trust boundaries: authentication points, network edges, tenant separation, third parties
- controls already deployed, and who owns each
- scope exclusions and the threat actors in scope

Expert clarification questions:
- `the system under review: components, which component calls which, and where each is deployed`
  - English: Which components make up the system, which of them call each other, and where does each one run?
  - Korean: 이 시스템은 어떤 컴포넌트로 구성되고, 서로 어떤 호출 관계이며, 각각 어디에서 실행되나요?
- `scope exclusions and the threat actors in scope`
  - English: Which attackers are in scope — external, authenticated tenant, insider, compromised dependency — and what is out of scope?
  - Korean: 어떤 공격자를 범위에 포함하나요 — 외부, 인증된 테넌트, 내부자, 침해된 의존성 — 그리고 제외 범위는 무엇인가요?

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

Safety rules:

- Never write working exploit code, a payload, or a runnable attack script; a scenario names the entry point, the path, and the precondition, not the weapon.
- Do not record a control as deployed because the architecture describes it; an unobserved control is `unverified` until configuration or a passing test says otherwise.
- Do not model the agent's own prompts, tools, credentials, or dependencies here; that surface belongs to `omh-security-safety-review`.
- Never print secrets, tokens, keys, connection strings, or live customer records pulled in as examples.
- A model is not a penetration test, a scan, or a compliance attestation; name which of the three the user still needs.

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
