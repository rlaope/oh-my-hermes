---
name: design-orchestration
description: [omh] Hermes design orchestration workflow: prepare a bounded design direction, existing-lane composition, and executor-neutral handoff.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: design-orchestration
    role: operator
    quality_tier: design-orchestration-gated
---

# Design Orchestration

This is a Hermes-native `design-orchestration` workflow skill.

## Why This Exists

`design-orchestration` lets Hermes users say that they want design handled without making them manually compose four specialist lanes or confusing preparation with completed visual work.

## Do Not Use When

- The request is directly about premium multi-format quality or publishing; use `design-quality-gate`.
- The request is directly about frontend implementation, layout, responsive behavior, or a design system; use `frontend`.
- The request is directly about WCAG, keyboard, screen-reader, or semantic accessibility; use `accessibility-audit`.
- The request is directly about screenshots, visual regression, pixel diff, rendered layout, or a verdict; use `visual-qa`.

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

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: choose skills, shape work, prepare artifacts, show status, and hand off with evidence boundaries.
- Current lane: **Materials and visual summaries** (`design-orchestration`, `design-quality-gate`, `frontend`, `accessibility-audit`, `visual-qa`, `content-operator`, `media-input-operator`, `materials-package`, `+3 more`) - web, accessibility, visual QA, files, and packages.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: every OMH skill: match lane; generic tool can render or execute.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/a11y/visual-qa; paper->paper-learning; content->content-operator; media->media-input-operator; file->materials-package; search->web-research; live->live-info-operator; audit->workspace/production/security; failures->build-failure; verify->verification-gate; code->codegraph/onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is infra.
- Boundary: Prepared OMH routing, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should take broad ownership of a design problem before a narrower quality, frontend, accessibility, or visual-QA lane is known.

    Strong routing signals: `design-orchestration`, `design orchestration`, `design ownership`, `handle this product design`, `take on the design`, `디자인 맡겨`, `디자인 맡겨줘`, `디자인 전체 맡겨`, `프로덕트 디자인 맡겨`

## Catalog Metadata

Category: `materials`
Phase: `design-orchestration`
Hermes role: `operator`
Quality tier: `design-orchestration-gated`

Quality bar:

- Make the design job, context boundary, direction, downstream lane ownership, and visual evidence requirements readable before handoff.
- Reject generic default drift by naming hierarchy, palette, typography, layout, signature element, and avoid patterns deliberately.
- Require the selected executor and fresh visual evidence separately before any implementation or quality completion claim.

Handoff policy:

Keep design intent, opaque project context references, deliberate direction, and existing-lane composition in Hermes; prepare an executor-neutral handoff only. The selected executor owns implementation, while existing visual-QA and web-QA paths own observed rendered evidence.

Required inputs:

- bounded target surface, audience, and primary task
- at least one opaque project, user, or Hermes context reference
- direction vocabulary and avoid-pattern selection
- executor selection and observed visual evidence remain pending

Expected outputs:

- design_orchestration/v1
- design intent and opaque context-reference boundary
- prepared direction vocabulary
- downstream composition: design-quality-gate, frontend, accessibility-audit, visual-qa
- executor-neutral handoff with executor_selection_required
- visual evidence requirements with visual_verdict not_observed

Artifact expectations:

- design_orchestration/v1 with prepared_not_observed status
- no raw project source, prompt, asset, path, or URL retention
- no executor target, dispatch, implementation, render, QA PASS, review, CI, deployment, or merge claim

Safety rules:

- Preserve the existing direct owners: design-quality-gate for premium multi-format quality, frontend for web implementation/design-system work, accessibility-audit for semantic access review, and visual-qa for fresh rendered verdicts.
- Do not use a prepared direction to claim code, screenshots, browser QA, accessibility PASS, review, CI, deployment, or merge.
- Keep free-form briefs in Hermes conversation context; persist only closed vocabulary and opaque reference metadata in the deterministic artifact.
- Do not call Claude Design, Figma, Open Design, an image provider, browser, network service, daemon, or executor from OMH core.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `design-orchestration`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill design-orchestration --harness design-orchestration --status started
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
