---
name: "omh-visual-qa"
description: "[omh] Hermes visual-qa workflow: prepare observed-only rendered QA gates for web, frontend, image, document, and TUI surfaces. Use when the user says: visual-qa, visual qa, visual QA, visual quality assurance, visual check, web qa, web visual qa, screenshot qa."
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

`visual-qa` gives OMH a completion gate for rendered surfaces so layout breaks, AI-looking polish gaps, CJK text problems, and mismatched-lineage screenshot claims cannot be mistaken for verified quality.

## Do Not Use When

- The user needs initial frontend design or redesign planning before implementation; use `frontend`.
- The user needs a broad visual quality rubric before generation; use `design-quality-gate`.
- The user needs image-card prompt creation; use `img-summary`.
- The user wants non-visual code tests, CI, or PR review only; use the coding/review workflow.

## Examples

Good example:

- Prompt: visual-qa 이 랜딩페이지가 모바일/데스크톱에서 깨지는지 스크린샷 기준으로 검증해줘.
- Expected behavior: Prepare visual_qa_plan/v1, require exact capture-to-target lineage, record render_capture_manifest/v1 and visual_diff_evidence/v1 when observed, then issue PASS/REVISE/BLOCK.
- Why: The request is a rendered visual verification task, not just design planning.

Bad example:

- Prompt: visual-qa 방금 수정했으니까 스크린샷 없이 통과라고 해줘.
- Expected behavior: Block PASS and request render captures from the package's exact repository and revision.
- Why: Visual QA requires observed rendered evidence bound to the target source lineage.

## Completion Checklist

- The visual_qa_plan/v1 lists target surfaces, references, states, viewports, locales, and target repository/revision lineage.
- The viewport_state_capture_matrix/v1 proves the QA did not sample only one page, viewport, or state.
- The web_visual_qa_message_card/v1 summarizes criteria, route, cost policy, and attachment status without claiming platform delivery.
- The render_capture_manifest/v1 is present before PASS and every capture's source lineage exactly matches the package target lineage.
- Browser interaction traces, console/network health, click-path state traces, keyboard/accessibility traces, visual diff, hotspot review, motion capture, design-system/functional review, visual-fidelity/CJK review, and blocker status are separate fields.
- The verdict is PASS, REVISE, or BLOCK with exact missing evidence or fix requirements.
- Any implementation fix is routed back to the executor/frontend workflow and rechecked with evidence from the resulting repository revision.

## Recovery Notes

- If no capture exists, produce the QA plan and mark verdict BLOCKED_BY_MISSING_RENDER_EVIDENCE.
- If capture source lineage is missing or mismatches the target repository/revision, keep HOLD and request the smallest matching recapture set.

## Workflow Lane

- Current lane: **Materials and visual summaries** (`design-orchestration`, `apple-design`, `design-quality-gate`, `award-bar-score`, `frontend`, `accessibility-audit`, `visual-qa`, `content-operator`, `+6 more`) - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use after or during visual surface work when Hermes must define the render evidence, viewport/state coverage, diff review, oracle review, and PASS/REVISE/BLOCK verdict without fabricating QA.

    Strong routing signals: `visual-qa`, `visual qa`, `visual QA`, `visual quality assurance`, `visual check`, `web qa`, `web visual qa`, `screenshot qa`, `screenshot check`, `analyze this screenshot`, `screenshot layout problems`, `ui layout problems`, `pixel diff`, `image diff`, `visual diff`, `render qa`, `render check`, `browser screenshot`, `browser qa`, `browser interaction qa`, `click path`, `click-path audit`, `dead link check`, `console error check`, `network failure check`, `keyboard navigation check`, `viewport check`, `responsive check`, `ui looks wrong`, `looks broken`, `layout broken`, `broken layout`, `text clipping`, `cjk clipping`, `cjk layout`, `tui check`, `terminal ui check`, `スクリーンショットで確認`, `レイアウト崩れ`, `画面崩れ`, `見た目のQA`, `비주얼 qa`, `비주얼QA`, `시각 qa`, `시각 검증`, `화면 검증`, `스크린샷 검증`, `스크린샷 ui 레이아웃`, `스크린샷 UI 레이아웃`, `스크린샷 레이아웃 문제`, `렌더 검증`, `픽셀 diff`, `픽셀 비교`, `화면 깨짐`, `레이아웃 깨짐`, `글자 잘림`, `한글 줄바꿈`, `터미널 ui`, `截图检查`, `页面错位`, `视觉验收`, `布局错乱`

## Catalog Metadata

Category: `materials`
Phase: `visual-qa`
Hermes role: `operator`
Quality tier: `visual-qa-gated`
Reasoning demand: `standard`

Quality bar:

- List the exact pages, states, viewports, files, images, or TUI frames being checked.
- For TUI surfaces, bind every capture to an explicit terminal size — 80x24 and 120x40 at minimum — and treat pasted rendered output at a named size as the screenshot-equivalent; a capture without its recorded size is not visual QA evidence.
- Enumerate every page/state/viewport before capture and mark omitted surfaces as blockers rather than assumptions.
- Require exact repository and revision equality between target_lineage and every capture source_lineage.
- Combine objective capture/diff evidence, hotspot review, alpha/transparent-background checks, and human-readable visual findings.
- Capture interaction, click-path, and motion states when the UI has hover/focus/active/load/scroll transitions or buttons/forms/navigation that change state.
- Record console/network health, keyboard navigation, accessibility scan boundaries, and mutating-flow safety for live browser QA claims.
- Separate design-system consistency, functional integrity, visual fidelity, responsive behavior, accessibility visibility, and CJK/text precision.
- Return PASS, REVISE, or BLOCK with concrete evidence IDs and missing-evidence gaps.
- Score every round through `references/visual-verdict-contract.md`: one JSON object carrying an integer 0-100 score, the PASS/REVISE/BLOCK verdict, and a differences list whose every entry pairs the observed problem with the smallest suggested fix.
- Hold 90 as the pass line: under it the verdict is REVISE and the named edits, a recapture of the same pages/states/viewports, and a fresh scored round are owed; rescoring the same captures is not a new round.
- Keep implementation fixes and follow-up edits separate from the observed QA verdict.

Handoff policy:

Keep the QA plan, evidence manifest, target-lineage rule, and verdict narration in Hermes. Screenshots, TUI captures, image diffs, browser runs, OCR/CJK checks, and oracle reviews are observed evidence supplied by the wrapper, executor, or user.

Required inputs:

- surface type
- target URL, route, file, image, or TUI command when available
- intended design, baseline, or reference
- pages, states, viewports, and locales to cover
- complete page/state/viewport enumeration rather than a sample
- target repository and exact source revision
- known risk areas such as CJK, overflow, responsiveness, or accessibility
- motion and interaction states that need capture
- browser interaction paths, mutating-flow boundary, and test credentials policy when a live web UI is in scope
- console, network, accessibility, and keyboard navigation checks required for browser QA claims
- render/capture evidence bound to the target repository and revision for completion claims

Expected outputs:

- visual_qa_plan/v1
- web_visual_qa_package/v2
- viewport_state_capture_matrix/v1
- message_attachment_projection/v1 for chat attachments
- web_visual_qa_message_card/v1 for chat message summaries
- render_capture_manifest/v1 when observed
- browser_interaction_trace/v1 when observed
- console_network_health/v1 when observed
- click_path_state_trace/v1 when observed
- accessibility_keyboard_trace/v1 when observed
- visual_diff_evidence/v1 when observed
- visual_hotspot_review/v1 when observed
- motion_interaction_capture/v1 when observed
- dual_oracle_visual_review/v1 when observed
- cjk_layout_findings/v1 when applicable
- visual_qa_verdict/v1
- retry_or_blocker/v1

Artifact expectations:

- visual_qa_plan/v1 with pages, states, viewports, references, and exact target repository/revision lineage
- web_visual_qa_package/v2 with target_lineage, unique required_viewports, capture source_lineage, blocking_violations, criteria, reviews, auto routing, and observed-only cost policy
- viewport_state_capture_matrix/v1 enumerates every route/page, 375/768/1280-style viewport, scroll position, modal/tab state, and CJK-heavy region to capture
- message_attachment_projection/v1 maps eligible observed captures to chat attachment candidates without claiming upload or delivery
- web_visual_qa_message_card/v1 projects recorded criteria, captures, routing, cost policy, and attachment hints into Discord/Slack/hosted-chat safe copy
- render_capture_manifest/v1 only from screenshots, file renders, images, or terminal captures whose source lineage matches the target package
- browser_interaction_trace/v1 only from observed navigation, form, auth, search, modal, and critical journey runs with read-only or staging-safe boundaries recorded
- console_network_health/v1 records observed critical console errors, failed requests, status codes, and ignored third-party noise before browser QA can pass
- click_path_state_trace/v1 maps each user-facing button/touchpoint to its handler, ordered state reads/writes, final UI state, and undo/race/stale-closure risks when interaction behavior is in scope
- accessibility_keyboard_trace/v1 records observed focus order, keyboard reachability, and automated accessibility scan boundaries; automated scans alone are not enough for an accessibility PASS
- visual_diff_evidence/v1 only when the wrapper/executor records objective diff output such as dimensionsMatch, diffRatio, similarityScore, alphaChannelIntact, and hotspots
- motion_interaction_capture/v1 only when hover/focus/active/load/scroll motion frames are observed before, during, and after transition
- visual_hotspot_review/v1 maps diff hotspots, TUI overflow lines, or screenshot regions to concrete visual causes
- dual_oracle_visual_review/v1 only when independent read-only review evidence exists
- visual_qa_verdict/v1 carries the scored round: an integer 0-100 score, PASS/REVISE/BLOCK, and difference/suggestion pairs, with the sub-90 rerun requirement stated rather than narrated away
- PASS unavailable until capture repository/revision lineage exactly matches the package target, every required viewport is captured, and all supplied blocking findings are resolved

Safety rules:

- Never claim PASS without rendered evidence whose repository and revision exactly match the package target lineage.
- Do not treat source review, captures with missing or mismatched source lineage, generated plans, or unobserved browser commands as visual QA evidence.
- Do not sample only one good page, viewport, or state when the surface has more; missed pages, modals, scroll states, or CJK-heavy regions keep PASS unavailable.
- Do not run destructive browser journeys such as checkout, payment, delete, or mass-update on production URLs; require staging or explicit safe test boundaries and redact credentials/PII from captures.
- Do not claim browser interaction PASS without observed click-path/state-transition traces for the touchpoints in scope.
- Do not claim accessibility from automated scan output alone; keyboard navigation and focus-order evidence remain separate observed checks.
- Objective diffs are evidence, not verdicts; review visual hierarchy, layout, CJK text, state coverage, and product intent separately.
- Pixel diff localizes hotspots only; it never produces the round score or the verdict, and a low diff ratio is not evidence that the rubric axes pass.
- Do not excuse diff hotspots as animation; capture settled frames and motion frames separately.
- Run or request two read-only review perspectives when claiming high confidence: design-system/functional integrity and visual fidelity/CJK precision.
- Recorded operator-supplied blocking criteria for CJK clipping, broken wrapping, overlapping UI, invisible text, unusable controls, or offscreen critical content block PASS until `_validate_pass` sees passing evidence refs.
- Do not call browsers, image tools, LLMs, or external services from OMH core.

## Runtime Evidence

Preferred harness for this skill: `visual-qa`.

```sh
omh runtime record --skill visual-qa --harness visual-qa --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
