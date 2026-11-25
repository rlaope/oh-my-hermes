# Github Issue Intake

Load this on-demand contract after the compact `github-issue-intake` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The report only wants classification or signal clustering; use `omh-feedback-triage` instead.
- The event concerns an already-existing issue, PR, review, or CI run; use `omh-github-event-ops` instead.
- The user wants implementation; coding stays a separate follow-up lane with its own maintainer authority.
- The report describes a security vulnerability; redirect to the private SECURITY.md path.
- The issue is already decided and the user only wants it filed or edited with the gh CLI, with no chat report to classify, question, or de-duplicate; load Hermes' bundled `github` skill instead of this one.

## Examples

Good example:

- Prompt: please file this as an issue: omh setup fails on Windows
- Expected behavior: Classify the report, run the bounded interview, search duplicates, present the direction check, and prepare github_issue_intake/v1 for confirmation-gated connector handoff.
- Why: The request is an explicit pre-creation filing ask with a classifiable report and an explicit target.

Bad example:

- Prompt: github-issue-intake prove the issue was filed and labelled.
- Expected behavior: Report that creation, labeling, and any GitHub mutation stay unobserved until an authorized connector returns read-back evidence.
- Why: A prepared package is not issue creation, label application, or any GitHub mutation evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- public report or summary
- source boundary
- explicit target repository
- desired outcome
- scope boundary
- missing evidence

Expected outputs:

- github_issue_intake/v1
- direction check
- duplicate status
- issue package or connector handoff
- read-back verification or explicit blocker

Artifact expectations:

- github_issue_intake/v1 metadata-only wrapper card when recorded
