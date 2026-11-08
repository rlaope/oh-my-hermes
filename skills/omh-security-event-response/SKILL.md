---
name: "omh-security-event-response"
description: "[omh] Security event on the code already shipped -- a CVE in a dependency, a secret committed to the repo, a license question, an advisory: triage reachability and severity, contain in order, and never close a leaked secret before its rotation is observed. Use when the user says: security-event-response, security event response, exfiltrating customer data, suspected unauthorized access, account takeover, cve, triage this cve, cve in our dependency."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: security-event-response
    role: reviewer
    quality_tier: event-closure-gated
    related_skills: [omh-security-safety-review, omh-application-threat-model, omh-refactor-plan, omh-legal-compliance-review, omh-live-incident-response]
---

# Security Event Response

This is a Hermes-native `security-event-response` workflow skill.

## Why This Exists

`security-event-response` exists because an event had no owner: `omh-security-safety-review` and `omh-application-threat-model` review a design before it ships, and a CVE, a committed secret, or a license question was answered by onboarding, review, or an achievements lane with no containment order at all.

## First Steps

- Classify the event and state its exposure window before proposing any step.
- For a leaked secret, order the rotation and its observed rejection before any history rewrite.

## Do Not Use When

- Nothing has happened yet and the ask is a review of prompts, tools, or permissions before execution; use `omh-security-safety-review`, which also owns a planned rotation with no exposure.
- The subject is a design's assets, trust boundaries, and attack scenarios; use `omh-application-threat-model`.
- A dependency moves to a new version as routine maintenance with no advisory or leak attached, such as a dependabot bump; use `omh-refactor-plan`.
- The question is a contract, a privacy obligation, or legal advice beyond a dependency's declared terms; use `omh-legal-compliance-review`.
- Production is down or degraded right now and the ask is command of the incident; use `omh-live-incident-response`.

## Examples

Good example:

- Prompt: we committed a secret, what now
- Expected behavior: Record the credential type, scope, and exposure window, then prepare containment_plan/v1: revoke and replace, observe the old credential rejected, audit its use in the window, and only then rewrite history; the closure verdict stays open until the rotation is observed and the persistence list is empty.
- Why: A rewritten history does not revoke a secret that was already cloned or scraped.

Bad example:

- Prompt: just force-push the history without the key and we are done
- Expected behavior: Refuse to close: rotate first, observe the old key rejected, then rewrite, and name what is still unobserved.
- Why: Rewriting history first leaves a live credential in every clone and cache made before the push.

## Completion Checklist

- The event kind, source, and exposure window are stated.
- Every severity call cites the reachable path or its observed absence.
- A leaked secret's rotation precedes any history rewrite in the plan.
- The closure verdict is closed only when the rotation (with an empty persistence list), the fixed version, the license decision, or the ended access is observed.
- No secret value appears anywhere, and OMH scanned, contacted, or rotated nothing.

## Recovery Notes

- If the exposure window is unknown, treat the secret as exposed from its first push and say so.
- If no reachability evidence is available, keep the advisory's own severity and mark the adjustment unverified.

## Workflow Lane

- Current lane: **Coding handoff** - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when a security event has already happened to code that exists: a CVE or advisory in a dependency, a secret or credential committed or pushed, a dependency whose license may not fit the product, or an advisory that forces a major version. The output is reachability, a severity call, containment steps in order, and what must be observed before the event closes; OMH never scans, never contacts a registry, and rotates nothing.

    Strong routing signals: `security-event-response`, `security event response`, `exfiltrating customer data`, `suspected unauthorized access`, `account takeover`, `cve`, `triage this cve`, `cve in our dependency`, `cve in a dependency`, `security advisory`, `dependabot alert`, `dependabot security`, `vulnerable dependency`, `vulnerability in our dependency`, `reachability analysis`, `npm audit`, `committed a secret`, `committed an api key`, `leaked secret`, `leaked a secret`, `leaked credential`, `leaked api key`, `leaked an api key`, `leaked aws key`, `leaked an aws key`, `secret in git history`, `secret in the history`, `dependency license`, `dependency's license`, `license ok`, `license compatibility`, `license compatible`, `gpl dependency`, `agpl dependency`

## Catalog Metadata

Category: `review`
Phase: `security-event-response`
Hermes role: `reviewer`
Quality tier: `event-closure-gated`
Reasoning demand: `standard`

Quality bar:

- Classify the event first; each kind has its own containment order.
- Load `references/event-containment-order.md` for the per-event containment order, the severity adjustment, and the license obligation table instead of recalling them.
- Adjust severity by reachability: a critical advisory on a function nothing calls is not the same event as one on the request path.
- Keep prepared, observed, and closed as separate states for every containment step.
- Hand a fix that needs a planned version jump to its own upgrade plan, and keep this event open until that fix is observed.
- Leaked secret: revoke first unless every planned-rotation condition is shown by evidence. Unauthorized access: reference section 4.

Handoff policy:

Keep the event record, the reachability call, the ordered containment plan, and the closure verdict in Hermes. Scanner output, advisory text, registry metadata, rotations, revocations, and history rewrites are recorded only from executor, operator, or wrapper observed output; OMH never scans, contacts a registry, or rotates a credential.

Required inputs:

- the event kind: CVE or advisory, leaked secret, license question, an advisory that forces a major version, or suspected unauthorized access
- for a CVE: the advisory id, the affected package and version range, and the installed version from the lockfile
- for a leaked secret: the credential type and scope, where it was pushed, whether the repository is public, and when
- for a license: the package, its declared license, and how the product is distributed
- for unauthorized access: the identity or host, the first anomaly, and what it could reach
- observed evidence for any containment or closure claim

Expected outputs:

- security_event_record/v1
- reachability_analysis/v1 when a vulnerable dependency is involved
- containment_plan/v1
- license_fit_verdict/v1 when a license is asked
- event_closure_verdict/v1

Artifact expectations:

- security_event_record/v1 names the event kind, the source, the affected package, credential class, or identity and host, and the exposure window, separately from the suspected impact
- reachability_analysis/v1 names the vulnerable function or path, the repository call sites that reach it or the observed absence of any, and a severity call from the advisory score adjusted by that reachability
- containment_plan/v1 orders every step; for a leaked secret the rotation and the observed rejection of the old credential come before any history rewrite, because a rewrite does not un-publish a secret already cloned
- license_fit_verdict/v1 gives the SPDX id, the obligation it triggers for this distribution model, and fits, conflicts, or needs counsel
- event_closure_verdict/v1 reads closed only when the rotation with an empty persistence list, the fixed version, the recorded license decision, or the ended access with an empty persistence list is recorded observed; a prepared step keeps the event open and is named

Safety rules:

- A leaked-secret event cannot close while its rotation is prepared rather than observed or attacker persistence remains; `event_closure_verdict/v1` names the missing observation instead.
- Order rotation before history rewriting: revoke and replace the credential, observe the old one rejected, then rewrite history if at all.
- Never print the secret value, and never paste it into the plan, the handoff, or a search.
- OMH never runs a scanner, contacts a registry, or rotates a credential; reachability and license facts come from observed output or are marked unverified.
- Do not call a dependency safe from a version number alone: cite the reachable path or its observed absence.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
