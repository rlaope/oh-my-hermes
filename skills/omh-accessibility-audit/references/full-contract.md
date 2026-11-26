# Accessibility Audit

Load this on-demand contract after the compact `accessibility-audit` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user needs initial frontend design or redesign planning before accessibility-specific review; use `omh-frontend` first.
- The user needs rendered layout, screenshot, CJK, or pixel-diff QA rather than accessibility semantics; use `omh-visual-qa`.
- The user needs a broad premium-quality gate across web, deck, PDF, or posters; use `omh-design-quality-gate`.
- The user asks to implement accessibility fixes directly; prepare a selected executor/runtime handoff after the audit or use the coding workflow.

## Examples

Good example:

- Prompt: accessibility-audit 이 checkout flow가 WCAG 2.2 AA, 키보드 포커스, 스크린리더, 터치 타깃 기준으로 통과 가능한지 봐줘.
- Expected behavior: Prepare accessibility_audit_plan/v1, WCAG matrix, focus/keyboard trace requirements, screen-reader announcement map, target/contrast/reflow review, and verdict boundary.
- Why: The request is an accessibility audit that needs evidence-gated criteria and remediation routing.

Bad example:

- Prompt: accessibility-audit 스크린리더나 키보드 확인 없이 접근성 통과라고 말해줘.
- Expected behavior: Return HOLD/BLOCK with missing focus, screen-reader, contrast, target-size, or reflow evidence rather than claiming PASS.
- Why: A prepared accessibility plan is not observed WCAG or assistive-technology evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- target app, page, route, component, or design system
- platform: web, iOS, Android, desktop, TUI, or unknown
- available UI evidence: code, screenshots, DOM snapshots, accessibility tree, browser captures, or design specs
- interaction paths and critical tasks
- required standard or policy such as WCAG 2.2 AA
- known risk areas: keyboard traps, missing labels, low contrast, small targets, reflow, live regions, or CJK/localization
- observed accessibility evidence for PASS claims

Expected outputs:

- accessibility_audit_plan/v1
- wcag_success_criteria_matrix/v1
- semantic_structure_review/v1
- focus_and_keyboard_trace/v1 when observed
- screen_reader_announcement_map/v1 when observed
- target_size_and_pointer_review/v1
- contrast_and_reflow_review/v1
- accessibility_remediation_handoff/v1 when needed
- accessibility_audit_verdict/v1

Artifact expectations:

- accessibility_audit_plan/v1 with platform, surfaces, critical tasks, standard level, supplied evidence, and missing observations
- wcag_success_criteria_matrix/v1 covering perceivable, operable, understandable, robust requirements with PASS/HOLD/BLOCK per criterion
- semantic_structure_review/v1 with labels, roles, names, headings, landmarks, form errors, live regions, and state semantics
- focus_and_keyboard_trace/v1 only from observed keyboard navigation, tab order, focus indicator (2.4.7; 2.4.13 appearance is AAA, advisory), skip/focus-trap checks, and critical interaction paths
- screen_reader_announcement_map/v1 only when announcements, accessible names, roles, values, hints, and dynamic updates are observed or supplied
- target_size_and_pointer_review/v1 with 24x24 CSS px as the WCAG 2.2 AA criterion (2.5.8), 44x44 as AAA (2.5.5) or platform guidance reported as advisory, and pointer gesture alternatives
- contrast_and_reflow_review/v1 with measured contrast, zoom/reflow risk, clipping, overflow, and CJK/localized text concerns
- accessibility_audit_verdict/v1 returns PASS, HOLD, or BLOCK with missing evidence and remediation route
