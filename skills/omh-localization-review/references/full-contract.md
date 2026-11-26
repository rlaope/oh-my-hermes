# Localization Review

Load this on-demand contract after the compact `localization-review` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is a short sentence or word translation or rewrite with no product or locale QA context; answer directly or use `omh-content-operator`.
- The user needs fresh rendered UI evidence, clipping checks, or a visual PASS/REVISE/BLOCK verdict; use `omh-visual-qa`.
- The user asks to edit locale files, push a translation-management-system job, publish strings, or configure localization settings; use `omh-files` or `omh-apps` with explicit target and authority.
- The request asks for a regulatory or contractual conclusion about translated legal text; use `omh-legal-compliance-review`.

## Examples

Good example:

- Prompt: Review our Korean checkout strings for terminology consistency, cultural fit, and context gaps before launch.
- Expected behavior: Prepare the locale and source-version brief, glossary choices, issue matrix, and locale QA criteria.
- Why: The product-release context needs localization review beyond a one-off translation.

Bad example:

- Prompt: Translate 'Your trial ends tomorrow' into Korean.
- Expected behavior: Answer directly or route to `omh-content-operator`, not `localization-review`.
- Why: A one-off sentence has no product locale QA or release-review objective.

## Full Input, Output, and Artifact Expectations

Required inputs:

- locale
- audience
- source version
- product or content context

Expected outputs:

- locale/audience/context and source-version brief
- approved-term glossary and transcreation/localization choices
- string/content issue matrix with context, severity, and review owner
- locale QA acceptance criteria and handoff/observed-evidence gaps

Artifact expectations:

- prepared localization review when a wrapper captures it
