---
name: "omh-design-orchestration"
description: "[omh] Entire product design problem to delegate: prepare a bounded design direction, existing-lane composition, and executor-neutral handoff. Use when the user says: design-orchestration, design orchestration, design ownership, handle this product design, take on the design, デザインを任せる, デザイン全体を任せ, プロダクトデザインを任せ."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: design-orchestration
    role: operator
    quality_tier: design-orchestration-gated
---

# Design Orchestration

This is an OMH `design-orchestration` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`design-orchestration` lets Hermes users say that they want design handled without making them manually compose four specialist lanes or confusing preparation with completed visual work.

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
- Expected behavior: Keep rendering and visual PASS not_observed; route the required capture and verdict work to visual-qa.
- Why: A prepared orchestration contract cannot create implementation or rendered evidence.

## Completion Checklist

- The bounded intent, opaque context references, direction vocabulary, and avoid patterns are explicit.
- The four downstream lanes retain their direct ownership and the executor is still selection-required.
- The visual evidence contract keeps visual_verdict not_observed until fresh captures are recorded by the visual-QA owner.

## Recovery Notes

- If only a raw brief exists, let Hermes retain it in chat and create an opaque user-supplied reference instead of storing the brief.
- If the request narrows to implementation, accessibility, or rendered QA, route to the existing specialist rather than expanding this orchestration surface.



## When to Use

Use when Hermes should take broad ownership of a design problem before a narrower quality, frontend, accessibility, or visual-QA lane is known.

    Strong routing signals: `design-orchestration`, `design orchestration`, `design ownership`, `handle this product design`, `take on the design`, `デザインを任せる`, `デザイン全体を任せ`, `プロダクトデザインを任せ`, `디자인 맡겨`, `디자인 맡겨줘`, `디자인 전체 맡겨`, `프로덕트 디자인 맡겨`, `设计交给你`, `整体设计交给你`, `产品设计交给你`, `tangani desain produk ini secara menyeluruh`, `koordinasikan seluruh proses desain`, `bantu urus desain produk dari awal`, `siapkan arahan desain untuk tim eksekusi`, `susun handoff desain produk`

## Catalog Metadata

Category: `materials`
Phase: `design-orchestration`
Quality tier: `design-orchestration-gated`
Reasoning demand: `standard`

Quality bar:

- Make the design job, context boundary, direction, downstream lane ownership, and visual evidence requirements readable before handoff.
- Reject generic default drift by naming hierarchy, palette, typography, layout, signature element, and avoid patterns deliberately — the direction vocabulary and anti-slop patterns live in the frontend skill's `omh-frontend/references/taste-foundations.md`; prepared directions inherit its named bar (technically clean but flat fails).
- Require the selected executor and fresh visual evidence separately before any implementation or quality completion claim.

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
- downstream composition: design-quality-gate, frontend, accessibility-audit, visual-qa
- executor-neutral handoff with executor_selection_required
- visual evidence requirements with visual_verdict not_observed

Artifact expectations:

- design_orchestration/v1 with prepared_not_observed status
- design_direction_set/v1 offers two to four directions with chosen_option empty until the user picks
- a static self-contained preview file when one is written; no server, port, or browser launch
- no raw project source, prompt, asset, path, or URL retention
- no executor target, dispatch, implementation, render, QA PASS, review, CI, deployment, or merge claim

Safety rules:

- Preserve the existing direct owners: design-quality-gate for premium multi-format quality, frontend for web implementation/design-system work, accessibility-audit for semantic access review, and visual-qa for fresh rendered verdicts.
- Do not use a prepared direction to claim code, screenshots, browser QA, accessibility PASS, review, CI, deployment, or merge.
- Keep free-form briefs in Hermes conversation context; persist only closed vocabulary and opaque reference metadata in the deterministic artifact.
- Do not call Claude Design, Figma, Open Design, an image provider, browser, network service, daemon, or executor from OMH core.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a stop condition or a decision the user owns ends the turn,
offer the next action as a question rather than declaring what will not be done.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
