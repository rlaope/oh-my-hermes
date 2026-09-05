---
name: "omh-design-quality-gate"
description: "[omh] Hermes Design Quality Gate workflow: enforce superior content, design, layout, publishing, and visual QA gates. Use when the user says: design-quality-gate, design quality gate, ui ux pro max, design pro max, frontend pro max, visual qa pro, premium design, high quality design."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: design-quality-gate
    role: operator
    quality_tier: design-pro-gated
---

# Design Quality Gate

This is a Hermes-native `design-quality-gate` workflow skill.

## Why This Exists

`design-quality-gate` makes high-stakes visual deliverables premium and trustworthy by treating taste, content, layout, accessibility, and render QA as first-class evidence.

## Do Not Use When

- Basic image prompt card only; use `img-summary`.
- Ordinary file packaging/export plan only; use `materials-package` or `deliverable-package`.
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

## Completion Checklist

- The surface, audience, source content, baseline/reference bar, and artifact type are named.
- The comparative_quality_rubric/v1 explains how the result must beat ordinary output.
- The surface_quality_matrix/v1 covers web, deck/PPT, PDF/poster, accessibility, and CJK-relevant checks as applicable.
- Prepared quality gates, generated artifacts, visual QA, export, publication, approval, and delivery remain separate states.
- The next action names whether to revise content, prepare implementation/export handoff, gather render evidence, or report blocked QA.

## Recovery Notes

- If the baseline or references are missing, prepare the gate with an explicit comparative-quality gap instead of calling the result premium.
- If render QA is unavailable, keep PASS unavailable and ask for the smallest screenshot, deck/PDF render, or operator observation that proves the target surface.

## Workflow Lane

- Current lane: **Materials and visual summaries** (`design-orchestration`, `apple-design`, `design-quality-gate`, `award-bar-score`, `frontend`, `accessibility-audit`, `visual-qa`, `content-operator`, `+6 more`) - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when web UI, decks, PDFs, posters, or visual packages must beat ordinary output on content, taste, layout, accessibility, and render QA.

    Strong routing signals: `design-quality-gate`, `design quality gate`, `ui ux pro max`, `design pro max`, `frontend pro max`, `visual qa pro`, `premium design`, `high quality design`, `beautiful website`, `frontend publishing`, `publishing quality`, `layout validation`, `ppt design quality`, `pdf design quality`, `デザイン品質ゲート`, `公開品質のデザイン`, `デザインの品質基準`, `웹사이트 디자인`, `프론트엔드 퍼블리싱`, `레이아웃 검증`, `더 뛰어나게`, `고퀄`, `设计质量门禁`, `发布级设计`, `设计质量标准`

## Catalog Metadata

Category: `materials`
Phase: `design-quality-gate`
Hermes role: `operator`
Quality tier: `design-pro-gated`
Reasoning demand: `standard`

Quality bar:

- Define superior design quality with references, audience, hierarchy, style, and measurable QA gates. The bar is named, not relative: what a senior product designer at a top-tier product company (the Linear/Stripe/Supabase class) would sign off on — technically clean but flat output fails it. Load `references/design-critique-rubric.md` and judge every axis with named evidence.
- State why the result should be better than ordinary output, including content depth, visual hierarchy, spacing, typography, and interaction or export polish.
- Review content accuracy and hierarchy before visual polish.
- Use design-system/reference rules for web, deck, PDF, and poster surfaces.
- Reject generic AI slop: weak hierarchy, cramped copy, flat templates, one-note palettes, and unverified exports.
- Require fresh visual QA for pages, slides, states, viewports, and CJK-heavy regions before PASS.

Handoff policy:

Keep the quality brief, reference selection, design rubric, content-structure review, and QA checklist in Hermes; delegate implementation or binary generation only after the surface, owner, references, and observed QA path are explicit.

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
- downstream route: frontend, materials-package, img-summary, or deliverable-package

Artifact expectations:

- design_quality_gate/v1 when prepared
- surface_quality_matrix/v1 with web: responsive viewport, deck/PPT: slide rhythm, PDF/poster: print-safe, and accessibility/CJK checks
- comparative_quality_rubric/v1 that names how this should be better than ordinary output
- visual_qa_evidence/v1 only from fresh screenshots/renders/observations
- export/publish evidence only when observed

Safety rules:

- Require references/rubric plus fresh render QA before PASS.
- Never claim PPTX, PDF, deployment, poster export, image generation, or publication without observed evidence.
- Separate content, taste, layout, accessibility, render fidelity, and delivery checks.
- Route web to frontend, binary files to materials/deliverable package, and image cards to img-summary.
- For Korean/CJK text, awkward breaks, clipped glyphs, orphan particles, or tiny copy block visual QA.
- Do not call a result high-quality unless it is compared against a named ordinary-output baseline or references.

## Runtime Evidence

Preferred harness for this skill: `design-quality-gate`.

```sh
omh runtime record --skill design-quality-gate --harness design-quality-gate --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
