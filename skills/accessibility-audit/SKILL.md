---
name: accessibility-audit
description: [omh] Hermes Accessibility Audit workflow: prepare WCAG, keyboard, focus, screen-reader, target-size, and reflow evidence gates for UI surfaces.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, accessibility]
    category: accessibility
    phase: accessibility-audit
    role: reviewer
    quality_tier: accessibility-audit-gated
---

# Accessibility Audit

This is a Hermes-native `accessibility-audit` workflow skill.

## Why This Exists

`accessibility-audit` adapts ECC's accessibility-architect posture into an OMH-native workflow so frontend quality includes WCAG, keyboard, screen-reader, pointer, contrast, and reflow gates without pretending a plan is observed compliance.

## Do Not Use When

- The user needs initial frontend design or redesign planning before accessibility-specific review; use `frontend` first.
- The user needs rendered layout, screenshot, CJK, or pixel-diff QA rather than accessibility semantics; use `visual-qa`.
- The user needs a broad premium-quality gate across web, deck, PDF, or posters; use `design-quality-gate`.
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

## Completion Checklist

- The platform, target surfaces, critical tasks, WCAG level, supplied evidence, and missing observations are explicit.
- The wcag_success_criteria_matrix/v1 separates PASS/HOLD/BLOCK and maps each issue to user impact.
- Semantic structure, focus/keyboard, screen-reader announcements, target size/pointer, contrast/reflow, and form/status behavior are separate checks.
- PASS is unavailable unless evidence is fresh after the latest UI edit and covers critical tasks.
- Remediation, frontend implementation, visual QA, browser proof, CI, release, and merge remain separate observed states.

## Recovery Notes

- If no rendered or DOM/accessibility-tree evidence exists, prepare the audit plan and mark verdict BLOCKED_BY_MISSING_ACCESSIBILITY_EVIDENCE.
- If automated scan output exists without keyboard or screen-reader evidence, keep the verdict HOLD and request the smallest focus/announcement trace.
- If the request is mostly visual layout or CJK clipping, route to visual-qa while preserving accessibility follow-up checks.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: choose skills, shape work, prepare artifacts, show status, and hand off with evidence boundaries.
- Current lane: **Materials and visual summaries** (`design-quality-gate`, `frontend`, `accessibility-audit`, `visual-qa`, `materials-package`, `img-summary`, `report-package`, `deliverable-package`) - web, accessibility, visual QA, files, and packages.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match lane, name adjacent workflows; generic tool can render or execute is not dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/accessibility-audit/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit/security-safety-review; failures->build-failure-triage; verify->verification-gate; code->codegraph-refresh/codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is setup/verification/wrapper infra.
- Boundary: Prepared OMH routing, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes must audit a UI or design system for WCAG 2.2 AA, keyboard reachability, focus flow, screen-reader semantics, target size, contrast, reflow, and accessibility evidence before claiming pass.

    Strong routing signals: `accessibility-audit`, `accessibility audit`, `a11y audit`, `a11y architect`, `wcag audit`, `wcag 2.2`, `wcag 2.2 aa`, `accessibility pass`, `accessibility check`, `screen reader`, `screenreader`, `aria audit`, `keyboard navigation`, `focus order`, `focus appearance`, `focus trap`, `tab order`, `touch target`, `target size`, `color contrast`, `contrast ratio`, `reflow`, `400% zoom`, `accessible name`, `name role value`, `접근성 감사`, `접근성 검토`, `접근성 검사`, `스크린리더`, `키보드 내비게이션`, `포커스 순서`, `포커스 표시`, `터치 타깃`, `타깃 크기`, `색 대비`, `명도 대비`, `aria`

## Catalog Metadata

Category: `accessibility`
Phase: `accessibility-audit`
Hermes role: `reviewer`
Quality tier: `accessibility-audit-gated`

Quality bar:

- Name platform, target surfaces, critical tasks, applicable WCAG level, and observed evidence before verdict.
- Map findings to concrete WCAG 2.2 criteria and user impact instead of generic accessibility advice.
- Separate semantic structure, focus/keyboard, screen-reader announcement, target-size/pointer, contrast/reflow, forms/errors, and dynamic status checks.
- Require observed keyboard and assistive-tech or accessibility-tree evidence before PASS.
- Route design-system or implementation changes back to frontend or the selected coding owner, then recheck with visual-qa/accessibility evidence.

Handoff policy:

Keep accessibility scope, WCAG mapping, focus-flow expectations, screen-reader semantics, and remediation routing in Hermes. Automated scans, browser keyboard walks, screen-reader observations, contrast measurements, and code fixes require observed wrapper, executor, or user evidence.

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
- focus_and_keyboard_trace/v1 only from observed keyboard navigation, tab order, focus appearance, skip/focus-trap checks, and critical interaction paths
- screen_reader_announcement_map/v1 only when announcements, accessible names, roles, values, hints, and dynamic updates are observed or supplied
- target_size_and_pointer_review/v1 with 24x24 CSS px / 44x44 mobile target expectations and pointer gesture alternatives
- contrast_and_reflow_review/v1 with measured contrast, zoom/reflow risk, clipping, overflow, and CJK/localized text concerns
- accessibility_audit_verdict/v1 returns PASS, HOLD, or BLOCK with missing evidence and remediation route

Safety rules:

- Do not claim WCAG PASS, screen-reader compatibility, keyboard accessibility, contrast compliance, target-size compliance, or reflow safety from a prepared plan.
- Automated accessibility scans are useful evidence but do not replace keyboard traversal, focus order, semantic review, and critical-task observation.
- Do not treat visual QA screenshots, source review, or old captures as current accessibility evidence after UI changes.
- Keep accessibility audit, remediation implementation, browser proof, visual QA, Lighthouse, CI, release, and merge evidence separate.
- For destructive or credentialed flows, require staging-safe or read-only paths before browser/accessibility walks.
- Do not call external scanners, browsers, screen readers, LLMs, or platform services from OMH core.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `accessibility-audit`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill accessibility-audit --harness accessibility-audit --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- Treat wrapper-supplied memory/context summaries as advisory local context, not proof that opaque Hermes memory was read or changed.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, `goal_continuation/v1`, or explicit checklists with named next actions,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
