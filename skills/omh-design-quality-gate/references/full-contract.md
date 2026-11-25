# Design Quality Gate

Load this on-demand contract after the compact `design-quality-gate` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- Basic image prompt card only; use `omh-image-cards`.
- The artifact is a throwaway probe whose quality is irrelevant to the decision it answers; use `omh-decision-prototype`.
- Ordinary file packaging/export plan only; use `omh-materials-package` or `omh-deliverable-package`.
- Pure backend, CLI, data, or text-only research with no visual surface.
- The user asks to claim deployment, export, publication, or visual QA without evidence.

## Examples

Good example:

- Prompt: design-quality-gate make this landing page and deck premium and verified.
- Expected behavior: Prepare design_quality_gate/v1 with references, comparative_quality_rubric/v1, surface_quality_matrix/v1, hierarchy, layout plan, visual QA checklist, route, and evidence boundaries.
- Why: The request asks for superior visual quality and publishing readiness.

Bad example:

- Prompt: design-quality-gate say the PDF and website look amazing because the plan says so.
- Expected behavior: Require rendered PDF/page screenshots or mark visual QA as not_observed.
- Why: A quality brief is not render, visual QA, export, deployment, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- surface/channel
- audience and purpose
- source content or gaps
- style references
- ordinary-output baseline or competitor/reference quality bar
- viewport/page/export constraints
- observed render QA for completion claims

Expected outputs:

- design_quality_gate/v1
- content_quality_review/v1
- surface_quality_matrix/v1
- comparative_quality_rubric/v1
- layout_validation_plan/v1
- visual_qa_evidence/v1 when observed
- publishing_readiness/v1
- downstream route: `omh-frontend`, `omh-materials-package`, `omh-image-cards`, or `omh-deliverable-package`

Artifact expectations:

- design_quality_gate/v1 when prepared
- surface_quality_matrix/v1 with web: responsive viewport, deck/PPT: slide rhythm, PDF/poster: print-safe, and accessibility/CJK checks
- comparative_quality_rubric/v1 that names how this should be better than ordinary output
- visual_qa_evidence/v1 only from fresh screenshots/renders/observations
- export/publish evidence only when observed
