# Frontend

Load this on-demand contract after the compact `frontend` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user needs a broad premium-quality gate across web, deck, PDF, poster, or publishing outputs; use `omh-design-quality-gate`.
- The user wants a disposable wireframe or mocked interaction to settle one interaction question before planning; use `omh-decision-prototype`.
- The user only needs a file, deck, PDF, spreadsheet, HWP, or attachment package; use `omh-materials-package` or `omh-deliverable-package`.
- The user only needs an image card or infographic prompt; use `omh-image-cards`.
- The user asks to mark a UI as visually passed without fresh rendered evidence; use `omh-visual-qa` and keep PASS blocked until observed.
- The user wants a standalone one-off HTML artifact or a page styled after a well-known public design system with no repo design-system contract or visual-QA handoff; load Hermes' bundled `claude-design` or `popular-web-designs` skill instead of this one.

## Examples

Good example:

- Prompt: frontend 이 대시보드가 AI 티 안 나게 레이아웃과 디자인 시스템을 잡아줘.
- Expected behavior: Prepare frontend_design_brief/v1, design_system_contract/v1, route/state matrix, implementation handoff, and visual_qa_required/v1.
- Why: The request is about web UI design, layout quality, and anti-generic frontend polish.

Bad example:

- Prompt: frontend 코드도 안 봤지만 Lighthouse랑 시각 QA 통과했다고 해줘.
- Expected behavior: Mark browser, performance, accessibility, and visual QA as not_observed and request the smallest observed evidence path.
- Why: A frontend brief is not implementation, browser, performance, or visual QA evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- target app, page, route, or component
- audience and primary user task
- existing design system or missing-system gap
- style references or quality bar
- initial generation mode or redesign mode
- DESIGN.md or design-system source of truth when available
- framework/stack when known
- routes, states, breakpoints, and locale/CJK risks
- browser-support target (default: Baseline Widely available, in every core browser for 30+ months)
- accessibility and performance constraints
- observed browser evidence for completion claims

Expected outputs:

- frontend_design_brief/v1
- frontend_initial_generation_contract/v1 when greenfield
- design_system_contract/v1
- design_reference_selection/v1
- reference_packet/v1 when supplied
- frontend_route_state_matrix/v1
- frontend_component_state_inventory/v1
- frontend_implementation_handoff/v1
- accessibility_performance_expectations/v1
- visual_qa_required/v1
- observed_browser_evidence/v1 when observed

Artifact expectations:

- frontend_design_brief/v1 when prepared
- frontend_initial_generation_contract/v1 declares DESIGN.md/design-system work, reference lane, token extraction, reusable primitives, and visual QA path before new UI code
- design_system_contract/v1 with layout, spacing, typography, color, component, motion, and responsive rules
- design_reference_selection/v1 names supplied references or the domain-fit style direction and explicitly avoids copying third-party logos, assets, or brand copy
- frontend_route_state_matrix/v1 with pages, states, viewports, CJK/locale, empty/loading/error, and interaction states, plus submitting, submit-failed, optimistic-pending, stale/refetching, and conflict (409) rows wherever the surface writes remote data
- frontend_component_state_inventory/v1 with default, hover, focus, active, disabled, loading, empty, and error states for reusable primitives, and each primitive's interface: props, events, slots, and the invariants a caller must know; a wrapper earns a row only when deleting it would push its complexity into its callers
- frontend_implementation_handoff/v1 for the selected executor/runtime
- browser screenshots, accessibility reports, Lighthouse/Core Web Vitals, and visual QA only when observed
