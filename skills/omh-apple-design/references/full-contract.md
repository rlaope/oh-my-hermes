# Apple Design

Load this on-demand contract after the compact `apple-design` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is generic frontend design, accessibility, screenshot QA, image-card work, or material guidance without an Apple-specific phrase or explicit `omh-apple-design` invocation; use the existing specialist lane.
- The message concerns Apple fruit, stock, support, a glass database, material science, or unrelated Swift/macOS discussion.
- The user needs a conformance, accessibility PASS, or visual PASS claim without supplied and observed evidence.

## Examples

Good example:

- Prompt: Review this iPad checkout against Apple HIG and hand the concrete fixes to the frontend and accessibility owners.
- Expected behavior: Prepare apple_design_brief/v1 with applicable evidence, findings, platform-aware remediation, and the existing owner routes.
- Why: The request specifies an Apple platform and asks for a review plus downstream remediation without treating the brief as implementation or a verdict.

Bad example:

- Prompt: Call our generic WCAG screenshot check Apple-certified.
- Expected behavior: Keep the Apple-specific verdict unavailable and route generic accessibility or rendered evidence to the existing specialist.
- Why: A generic check without applicable Apple evidence cannot establish platform compliance or certification.

## Full Input, Output, and Artifact Expectations

Required inputs:

- mode: design, review, or improve
- visual target: Apple marketing/product visual, native Apple application, or Apple-inspired web UI
- target, surface/state, supplied evidence, and available execution constraints

Expected outputs:

- apple_design_brief/v1
- apple_visual_direction/v1
- apple_design_finding/v1 with severity, location/evidence, impact, source/applicability, fix, owner, and missing checks
- two to four design directions before visual work when direction is open
- composed remediation route to `omh-frontend`, `omh-design-quality-gate`, `omh-accessibility-audit`, `omh-visual-qa`, or `omh-award-bar-score`

Artifact expectations:

- prepared Apple design brief with observations and hypotheses distinguished
- prepared product-visual handoff when no authorized execution path exists
- visual status not_observed when no supplied screen, capture, or rendered surface exists
- no Apple certification, accessibility PASS, visual PASS, or implementation claim from a prepared brief
