# Security Event Response

Load this on-demand contract after the compact `security-event-response` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

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

## Full Input, Output, and Artifact Expectations

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
