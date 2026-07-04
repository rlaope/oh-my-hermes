---
name: design-quality-gate
description: [omh] Hermes Design Quality Gate workflow: enforce superior content, design, layout, publishing, and visual QA gates.
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

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Materials and visual summaries** (`design-quality-gate`, `frontend`, `visual-qa`, `materials-package`, `img-summary`, `report-package`, `deliverable-package`) - web, visual QA, files, image cards, and packages.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match lane, name adjacent workflows; generic tool can render or execute is not dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit/security-safety-review; verify->verification-gate; code->codegraph-refresh/codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend/setup/verification/wrapper infra.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when web UI, decks, PDFs, posters, or visual packages must beat ordinary output on content, taste, layout, accessibility, and render QA.

    Strong routing signals: `design-quality-gate`, `design quality gate`, `ui ux pro max`, `design pro max`, `frontend pro max`, `visual qa pro`, `premium design`, `high quality design`, `beautiful website`, `frontend publishing`, `publishing quality`, `layout validation`, `ppt design quality`, `pdf design quality`, `웹사이트 디자인`, `프론트엔드 퍼블리싱`, `레이아웃 검증`, `더 뛰어나게`, `고퀄`

## Catalog Metadata

Category: `materials`
Phase: `design-quality-gate`
Hermes role: `operator`
Quality tier: `design-pro-gated`

Quality bar:

- Define superior design quality with references, audience, hierarchy, style, and measurable QA gates.
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

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `design-quality-gate`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill design-quality-gate --harness design-quality-gate --status started
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
