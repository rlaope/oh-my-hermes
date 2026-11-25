---
name: "omh-design-orchestration"
description: "[omh] Entire product design problem to delegate: prepare a bounded design direction, existing-lane composition, and executor-neutral handoff. Use when the user says: design-orchestration, design orchestration, design ownership, handle this product design, take on the design, デザインを任せる, デザイン全体を任せ, プロダクトデザインを任せ."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: design-orchestration
    role: operator
    quality_tier: design-orchestration-gated
    related_skills: [omh-design-quality-gate, omh-frontend, omh-accessibility-audit, omh-visual-qa]
---

# Design Orchestration

Required: bounded target surface, audience, and primary task, at least one opaque project, user, or Hermes context reference, direction vocabulary and avoid-pattern selection, executor selection and observed visual evidence remain pending. Output: design_orchestration/v1, design_direction_set/v1 when the direction is still open, design intent and opaque context-reference boundary, prepared direction vocabulary, downstream composition: `omh-design-quality-gate`, `omh-frontend`, `omh-accessibility-audit`, `omh-visual-qa`, executor-neutral handoff with executor_selection_required, visual evidence requirements with visual_verdict not_observed.

## Why This Exists

`design-orchestration` lets Hermes users say that they want design handled without making them manually compose four specialist lanes or confusing preparation with completed visual work.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Materials and visual summaries** - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should take broad ownership of a design problem before a narrower quality, frontend, accessibility, or visual-QA lane is known.

    Strong routing signals: `design-orchestration`, `design orchestration`, `design ownership`, `handle this product design`, `take on the design`, `デザインを任せる`, `デザイン全体を任せ`, `プロダクトデザインを任せ`, `디자인 맡겨`, `디자인 맡겨줘`, `디자인 전체 맡겨`, `프로덕트 디자인 맡겨`, `设计交给你`, `整体设计交给你`, `产品设计交给你`, `tangani desain produk ini secara menyeluruh`, `koordinasikan seluruh proses desain`, `bantu urus desain produk dari awal`, `siapkan arahan desain untuk tim eksekusi`, `susun handoff desain produk`, `xử lý thiết kế sản phẩm này toàn diện`, `phối hợp toàn bộ quy trình thiết kế`, `giúp phụ trách thiết kế sản phẩm từ đầu`, `chuẩn bị chỉ đạo thiết kế cho đội thực thi`, `lập bàn giao thiết kế sản phẩm`

## Catalog Metadata

Category: `materials`
Phase: `design-orchestration`
Hermes role: `operator`
Quality tier: `design-orchestration-gated`
Reasoning demand: `standard`

Quality bar:

- Make the design job, context boundary, direction, downstream lane ownership, and visual evidence requirements readable before handoff.
- Reject generic default drift by naming hierarchy, palette, typography, layout, signature element, and avoid patterns deliberately — the direction vocabulary and anti-slop patterns live in the frontend skill's `omh-frontend/references/taste-foundations.md`; prepared directions inherit its named bar (technically clean but flat fails).
- Require the selected executor and fresh visual evidence separately before any implementation or quality completion claim.
- The options in `design_direction_set/v1` are shown as rendered images; an option described only in words is not yet an option.
- Running to the end without asking is for runs nobody can answer (scheduled, batch) or when the user handed the choice over.

Handoff policy:

Keep design intent, opaque project context references, deliberate direction, and existing-lane composition in Hermes; prepare an executor-neutral handoff only. The selected executor owns implementation, while existing visual-QA and web-QA paths own observed rendered evidence.

Safety rules:

- Preserve the existing direct owners: `omh-design-quality-gate` for premium multi-format quality, `omh-frontend` for web implementation/design-system work, `omh-accessibility-audit` for semantic access review, and `omh-visual-qa` for fresh rendered verdicts.
- Do not use a prepared direction to claim code, screenshots, browser QA, accessibility PASS, review, CI, deployment, or merge.
- Keep free-form briefs in Hermes conversation context; persist only closed vocabulary and opaque reference metadata in the deterministic artifact.
- Do not call Claude Design, Figma, Open Design, an image provider, browser, network service, daemon, or executor from OMH core.

## Completion Checklist

- The bounded intent, opaque context references, direction vocabulary, and avoid patterns are explicit.
- The four downstream lanes retain their direct ownership and the executor is still selection-required.
- The visual evidence contract keeps visual_verdict not_observed until fresh captures are recorded by the visual-QA owner.

## Recovery Notes

- If only a raw brief exists, let Hermes retain it in chat and create an opaque user-supplied reference instead of storing the brief.
- If the request narrows to implementation, accessibility, or rendered QA, route to the existing specialist rather than expanding this orchestration surface.

## Runtime Evidence

Preferred harness for this skill: `design-orchestration`.

```sh
omh runtime record --skill design-orchestration --harness design-orchestration --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
