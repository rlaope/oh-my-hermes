---
name: "omh-design-quality-gate"
description: "[omh] Deliverable demands premium polish: enforce superior content, design, layout, publishing, and visual QA gates. Use when the user says: design-quality-gate, design quality gate, ui ux pro max, design pro max, frontend pro max, visual qa pro, premium design, high quality design."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: design-quality-gate
    role: operator
    quality_tier: design-pro-gated
    related_skills: [omh-image-cards, omh-decision-prototype, omh-materials-package, omh-deliverable-package]
---

# Design Quality Gate

This is a Hermes-native `design-quality-gate` workflow skill.

## Why This Exists

`design-quality-gate` makes high-stakes visual deliverables premium and trustworthy by treating taste, content, layout, accessibility, and render QA as first-class evidence.

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

- Current lane: **Materials and visual summaries** - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when web UI, decks, PDFs, posters, or visual packages must beat ordinary output on content, taste, layout, accessibility, and render QA.

    Strong routing signals: `design-quality-gate`, `design quality gate`, `ui ux pro max`, `design pro max`, `frontend pro max`, `visual qa pro`, `premium design`, `high quality design`, `beautiful website`, `frontend publishing`, `publishing quality`, `layout validation`, `ppt design quality`, `pdf design quality`, `デザイン品質ゲート`, `公開品質のデザイン`, `デザインの品質基準`, `웹사이트 디자인`, `프론트엔드 퍼블리싱`, `레이아웃 검증`, `더 뛰어나게`, `고퀄`, `премиальный дизайн сайта`, `полировка дизайна`, `设计质量门禁`, `发布级设计`, `设计质量标准`, `pastikan desain memenuhi standar premium`, `tingkatkan kualitas desain sebelum publikasi`, `tolong poles desain sampai siap dipublikasikan`, `cek standar kualitas desain ini`, `rapikan konten dan tata letak agar layak terbit`, `đảm bảo thiết kế đạt tiêu chuẩn chất lượng cao`, `nâng cao chất lượng thiết kế trước khi xuất bản`, `hãy tinh chỉnh thiết kế cho sẵn sàng xuất bản`, `kiểm tra tiêu chuẩn chất lượng của thiết kế này`, `chỉnh sửa nội dung và bố cục cho đạt mức xuất bản`

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
- For a composed frame (promo, poster, slide, end card), run the color-harmony pass before render: list every hue family on screen with its hex values and where it appears; the surrounding composition adds at most one accent family beyond the captured product or brand palette; neutrals, semantic-state colors and data-series palettes are listed but not counted; text contrast is at least 4.5:1, or 3:1 for large type, on its actual background. A composed frame that fails is REVISE before render; details in `references/design-critique-rubric.md`.
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
- downstream route: `omh-frontend`, `omh-materials-package`, `omh-image-cards`, or `omh-deliverable-package`

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
- Route web to `omh-frontend`, binary files to `omh-materials-package` or `omh-deliverable-package`, and image cards to `omh-image-cards`.
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
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. Finished work ends with no question and no offer; when a decision only the user can make remains, end with one specific question about that decision, not a list of questions, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
