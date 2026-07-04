---
name: visual-qa
description: [omh] Hermes visual-qa workflow: prepare observed-only rendered QA gates for web, frontend, image, document, and TUI surfaces.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: visual-qa
    role: operator
    quality_tier: visual-qa-gated
---

# Visual Qa

This is a Hermes-native `visual-qa` workflow skill.

## Why This Exists

`visual-qa` gives OMH a completion gate for rendered surfaces so layout breaks, AI-looking polish gaps, CJK text problems, and stale screenshot claims cannot be mistaken for verified quality.

## Do Not Use When

- The user needs initial frontend design or redesign planning before implementation; use `frontend`.
- The user needs a broad visual quality rubric before generation; use `design-quality-gate`.
- The user needs image-card prompt creation; use `img-summary`.
- The user wants non-visual code tests, CI, or PR review only; use the coding/review workflow.

## Examples

Good example:

- Prompt: visual-qa 이 랜딩페이지가 모바일/데스크톱에서 깨지는지 스크린샷 기준으로 검증해줘.
- Expected behavior: Prepare visual_qa_plan/v1, require fresh captures, record render_capture_manifest/v1 and visual_diff_evidence/v1 when observed, then issue PASS/REVISE/BLOCK.
- Why: The request is a rendered visual verification task, not just design planning.

Bad example:

- Prompt: visual-qa 방금 수정했으니까 스크린샷 없이 통과라고 해줘.
- Expected behavior: Block PASS and request fresh render capture after the latest edit.
- Why: Visual QA requires observed rendered evidence newer than the last UI change.

## Completion Checklist

- The visual_qa_plan/v1 lists target surfaces, references, states, viewports, locales, and freshness criteria.
- The render_capture_manifest/v1 is present before PASS and is newer than the last relevant edit.
- Visual diff, design-system/functional review, visual-fidelity/CJK review, and blocker status are separate fields.
- The verdict is PASS, REVISE, or BLOCK with exact missing evidence or fix requirements.
- Any implementation fix is routed back to the executor/frontend workflow and rechecked with fresh evidence.

## Recovery Notes

- If no capture exists, produce the QA plan and mark verdict BLOCKED_BY_MISSING_RENDER_EVIDENCE.
- If a capture exists but predates the latest edit, mark it stale and request the smallest fresh recapture set.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Materials and visual summaries** (`design-quality-gate`, `frontend`, `visual-qa`, `materials-package`, `img-summary`, `report-package`, `deliverable-package`) - premium web/frontends, visual QA, docs/decks/PDFs, image cards, and packages.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match intent to a lane; name adjacent workflows; generic tool can render or execute is not a dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit; verify->verification-gate; code->ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use after or during visual surface work when Hermes must define the render evidence, viewport/state coverage, diff review, oracle review, and PASS/REVISE/BLOCK verdict without fabricating QA.

    Strong routing signals: `visual-qa`, `visual qa`, `visual QA`, `visual quality assurance`, `visual check`, `screenshot qa`, `screenshot check`, `pixel diff`, `image diff`, `visual diff`, `render qa`, `render check`, `browser screenshot`, `viewport check`, `responsive check`, `ui looks wrong`, `looks broken`, `layout broken`, `broken layout`, `text clipping`, `cjk clipping`, `cjk layout`, `tui check`, `terminal ui check`, `비주얼 qa`, `비주얼QA`, `시각 qa`, `시각 검증`, `화면 검증`, `스크린샷 검증`, `렌더 검증`, `픽셀 diff`, `픽셀 비교`, `화면 깨짐`, `레이아웃 깨짐`, `글자 잘림`, `한글 줄바꿈`, `터미널 ui`

## Catalog Metadata

Category: `materials`
Phase: `visual-qa`
Hermes role: `operator`
Quality tier: `visual-qa-gated`

Quality bar:

- List the exact pages, states, viewports, files, images, or TUI frames being checked.
- Require evidence freshness after the last visual edit.
- Combine objective capture/diff evidence with human-readable visual findings.
- Separate design-system consistency, functional integrity, visual fidelity, responsive behavior, accessibility visibility, and CJK/text precision.
- Return PASS, REVISE, or BLOCK with concrete evidence IDs and missing-evidence gaps.
- Keep implementation fixes and follow-up edits separate from the observed QA verdict.

Handoff policy:

Keep the QA plan, evidence manifest, freshness rule, and verdict narration in Hermes. Screenshots, TUI captures, image diffs, browser runs, OCR/CJK checks, and oracle reviews are observed evidence supplied by the wrapper, executor, or user.

Required inputs:

- surface type
- target URL, route, file, image, or TUI command when available
- intended design, baseline, or reference
- pages, states, viewports, and locales to cover
- latest edit or source revision
- known risk areas such as CJK, overflow, responsiveness, or accessibility
- fresh render/capture evidence for completion claims

Expected outputs:

- visual_qa_plan/v1
- render_capture_manifest/v1 when observed
- visual_diff_evidence/v1 when observed
- dual_oracle_visual_review/v1 when observed
- cjk_layout_findings/v1 when applicable
- visual_qa_verdict/v1
- retry_or_blocker/v1

Artifact expectations:

- visual_qa_plan/v1 with pages, states, viewports, references, and freshness rule
- render_capture_manifest/v1 only from fresh screenshots, file renders, images, or terminal captures
- visual_diff_evidence/v1 only when the wrapper/executor records objective diff output
- dual_oracle_visual_review/v1 only when independent read-only review evidence exists
- PASS unavailable until captures are newer than the last visual edit and all blocking findings are resolved

Safety rules:

- Never claim PASS without fresh rendered evidence captured after the last relevant edit.
- Do not treat source review, screenshots from an older run, generated plans, or unobserved browser commands as visual QA evidence.
- Objective diffs are evidence, not verdicts; review visual hierarchy, layout, CJK text, state coverage, and product intent separately.
- Run or request two read-only review perspectives when claiming high confidence: design-system/functional integrity and visual fidelity/CJK precision.
- CJK clipping, broken wrapping, overlapping UI, invisible text, unusable controls, or offscreen critical content block PASS.
- Do not call browsers, image tools, LLMs, or external services from OMH core.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `visual-qa`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill visual-qa --harness visual-qa --status started
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
