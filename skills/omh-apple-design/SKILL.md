---
name: "omh-apple-design"
description: "[omh] Hermes Apple design workflow: prepare native Apple UI or Apple marketing product-visual direction, review, and improvement briefs with evidence-backed remediation handoffs. Use when the user says: apple-design, apple design, apple ui design, apple hig, human interface guidelines, ios design guidelines, macos app design, apple-inspired web."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: apple-design
    role: operator
    quality_tier: apple-design-gated
---

# Apple Design

This is a Hermes-native `apple-design` workflow skill.

## Why This Exists

`apple-design` turns Apple UI design, review, and improvement requests into a platform-aware brief that respects native and web differences while preserving OMH's existing implementation and evidence owners.

## Do Not Use When

- The request is generic frontend design, accessibility, screenshot QA, image-card work, or material guidance without an Apple-specific phrase or explicit `apple-design` invocation; use the existing specialist lane.
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

## Completion Checklist

- Target, convention, state, and evidence are explicit.
- Each direction or finding names evidence, source applicability, owner, and missing verification; product visuals name original art direction.
- Implementation remains with the selected coding owner; accessibility and visual completion remain not_observed until their existing lanes record evidence.

## Recovery Notes

- If the platform/version, convention, or target state is missing, ask for it before treating a guideline as applicable.
- If no supplied screen or code exists, prepare the brief and mark visual status not_observed rather than inferring a rendered result.

## Workflow Lane

- Current lane: **Materials and visual summaries** (`design-orchestration`, `apple-design`, `design-quality-gate`, `award-bar-score`, `frontend`, `accessibility-audit`, `visual-qa`, `content-operator`, `+6 more`) - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when an iOS, iPadOS, macOS, Apple-inspired web surface, or explicit Apple-style product visual needs an Apple-aware direction, evidence-backed review, or improvement brief before implementation or visual verification.

    Strong routing signals: `apple-design`, `apple design`, `apple ui design`, `apple hig`, `human interface guidelines`, `ios design guidelines`, `macos app design`, `apple-inspired web`, `liquid glass review`, `liquid glass design`, `apple 3d hero`, `apple-style 3d`, `apple product render`, `apple product visual`, `apple studio lighting`, `apple-style landing visual`, `apple product page`

## Catalog Metadata

Category: `materials`
Phase: `apple-design`
Hermes role: `operator`
Quality tier: `apple-design-gated`
Reasoning demand: `standard`

Quality bar:

- Start with mode, target, convention, and available evidence; choose directions before visuals when open.
- Load `references/platform-foundations.md`, `references/materials-and-accessibility.md`, `references/product-visual-production.md`, `references/web-production-libraries.md`, and `references/review-playbook.md` for their named boundaries.
- For product work, use reference -> actual production -> same-subject comparison -> revision. Motion needs frames, video, or browser evidence and a reduced-motion alternative; do not award an Apple score.
- Findings name evidence, impact, source/applicability, fix, owner, and missing check; route implementation to the selected owner and proof to accessibility-audit or visual-qa.

Handoff policy:

Hermes directs; selected owners implement and existing lanes observe.

Required inputs:

- mode: design, review, or improve
- visual target: Apple marketing/product visual, native Apple application, or Apple-inspired web UI
- target, surface/state, supplied evidence, and available execution constraints

Expected outputs:

- apple_design_brief/v1
- apple_visual_direction/v1
- apple_design_finding/v1 with severity, location/evidence, impact, source/applicability, fix, owner, and missing checks
- two to four design directions before visual work when direction is open
- composed remediation route to frontend, design-quality-gate, accessibility-audit, visual-qa, or award-bar-score

Artifact expectations:

- prepared Apple design brief with observations and hypotheses distinguished
- prepared product-visual handoff when no authorized execution path exists
- visual status not_observed when no supplied screen, capture, or rendered surface exists
- no Apple certification, accessibility PASS, visual PASS, or implementation claim from a prepared brief

Safety rules:

- Choose one target: marketing/product visual, native Apple application, or Apple-inspired web UI; do not substitute marketing or web effects for native controls/Liquid Glass.
- For native targets use current HIG/system controls and platform foundations; macOS has no Dynamic Type. For web, use semantic responsive UI with reduced-motion/transparency and opaque fallback.
- Product visuals use original geometry, camera, material, light, palette, scale, copy-safe space, and no Apple assets; see the production reference for renderer choices.
- Only call a result generated, rendered, or animated with matching actual evidence. Without an authorized execution path, prepare a handoff and name the missing boundary.
- Load the web-library reference only for explicit Apple product work; confirm existing-project compatibility and license posture. Do not install, vendor, fetch, or call it native Apple; generic GSAP/logo work stays in its existing lane.
- Review supplied evidence; prepared guidance is not implementation, accessibility/visual PASS, or certification.
- Before output and before approval, classify native, web, or marketing intent; use `apple-design` only for the explicit specialist request.
- If current source guidance applies, keep its conditional 35% bright-background note; it is not universal. When no renderer is available, do not claim a result; while work is prepared, it is not observed.
- Never treat web glass as native, never substitute a still for motion, and use only actual evidence after production; without it, the result is not PASS.
- While evidence is missing, use only a prepared handoff; it is not execution and not a PASS.

## Runtime Evidence

Preferred harness for this skill: `apple-design`.

```sh
omh runtime record --skill apple-design --harness apple-design --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
