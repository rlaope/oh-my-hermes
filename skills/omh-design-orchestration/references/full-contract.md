# Design Orchestration

Load this on-demand contract after the compact `design-orchestration` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is directly about premium multi-format quality or publishing; use `omh-design-quality-gate`.
- The request is directly about frontend implementation, layout, responsive behavior, or a design system; use `omh-frontend`.
- The request is directly about WCAG, keyboard, screen-reader, or semantic accessibility; use `omh-accessibility-audit`.
- The request is directly about screenshots, visual regression, pixel diff, rendered layout, or a verdict; use `omh-visual-qa`.

## Examples

Good example:

- Prompt: 디자인 맡겨줘. 기존 프로젝트 맥락을 먼저 보고, 방향과 구현·검증의 다음 단계를 잡아줘.
- Expected behavior: Prepare design_orchestration/v1 with opaque context references, deliberate direction, existing-lane composition, executor_selection_required, and not_observed visual evidence requirements.
- Why: The request delegates broad design ownership while leaving implementation and observed QA to the appropriate owners.

Bad example:

- Prompt: design-orchestration already rendered and visually passed the new page.
- Expected behavior: Keep rendering and visual PASS not_observed; route the required capture and verdict work to `omh-visual-qa`.
- Why: A prepared orchestration contract cannot create implementation or rendered evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- bounded target surface, audience, and primary task
- at least one opaque project, user, or Hermes context reference
- direction vocabulary and avoid-pattern selection
- executor selection and observed visual evidence remain pending

Expected outputs:

- design_orchestration/v1
- design_direction_set/v1 when the direction is still open
- design intent and opaque context-reference boundary
- prepared direction vocabulary
- downstream composition: `omh-design-quality-gate`, `omh-frontend`, `omh-accessibility-audit`, `omh-visual-qa`
- executor-neutral handoff with executor_selection_required
- visual evidence requirements with visual_verdict not_observed

Artifact expectations:

- design_orchestration/v1 with prepared_not_observed status
- design_direction_set/v1 offers two to four directions with chosen_option empty until the user picks
- a static self-contained preview file when one is written; no server, port, or browser launch
- no raw project source, prompt, asset, path, or URL retention
- no executor target, dispatch, implementation, render, QA PASS, review, CI, deployment, or merge claim
