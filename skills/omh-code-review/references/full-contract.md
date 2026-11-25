# Code Review

Load this on-demand contract after the compact `code-review` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user asks to implement the fix rather than review existing code or claims.
- There is no diff, file set, claim, artifact, or expected behavior to review.
- The request is broad product critique, strategy, or planning rather than code or evidence review.
- The user wants build, lint, test, and CI results collected into a PASS/HOLD/BLOCK evidence matrix before merge; use `omh-verification-gate`. This skill supplies findings that matrix may cite.
- A kanban review worker needs its card's transition decided: Hermes' bundled `sdlc-review` owns approve, request-changes, and escalate there, and this skill only supplies the findings that decision cites.
- The user wants their own uncommitted changes checked before a commit or push, with a security scan, quality gates, and fixes applied in place; load Hermes' bundled `requesting-code-review` skill for that pre-commit pass instead of this one.

## Examples

Good example:

- Prompt: $code-review review this PR for install/update UX regressions and missing tests.
- Expected behavior: Lead with ranked findings, cite concrete evidence, then list open questions and test gaps.
- Why: The task is explicitly review-shaped and has a behavioral risk surface.

Bad example:

- Prompt: $code-review add the missing setup flag and commit it.
- Expected behavior: Route implementation to a selected executor/runtime after review findings are established.
- Why: Review can identify the issue, but code mutation is a separate execution step.

## Full Input, Output, and Artifact Expectations

Required inputs:

- diff or files
- expected behavior
- test evidence
- the dispatch Claim and Requirements pointer (issue, plan, or spec section) when intent is reviewable

Expected outputs:

- ranked findings per axis
- spec-axis verdict or a named not-assessed reason
- open questions
- test gaps
- checked-and-clean and could-not-assess lists

Artifact expectations:

- critic run record when review evidence is captured
