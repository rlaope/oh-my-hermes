---
name: "omh-visual-qa"
description: "[omh] Rendered UI needing a visual verdict: prepare observed-only rendered QA gates for web, frontend, image, document, and TUI surfaces. Use when the user says: visual-qa, visual qa, visual QA, visual quality assurance, visual check, web qa, web visual qa, screenshot qa."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: visual-qa
    role: operator
    quality_tier: visual-qa-gated
    related_skills: [omh-frontend, omh-design-quality-gate, omh-image-cards, dogfood]
---

# Visual Qa

This is a Hermes-native `visual-qa` workflow skill.

## Why This Exists

`visual-qa` gives OMH a completion gate for rendered surfaces so layout breaks, AI-looking polish gaps, CJK text problems, and mismatched-lineage screenshot claims cannot be mistaken for verified quality.

## Do Not Use When

- The user needs initial frontend design or redesign planning before implementation; use `omh-frontend`.
- The user needs a broad visual quality rubric before generation; use `omh-design-quality-gate`.
- The user needs image-card prompt creation; use `omh-image-cards`.
- The user wants non-visual code tests, CI, or PR review only; use the coding/review workflow.
- Open-ended bug-hunting across a web app with no page, state, and viewport matrix or target revision to judge; on Hermes, use the bundled `dogfood` skill when it is available.

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

- Interaction, console/network, click-path, keyboard/accessibility, diff, hotspot, motion, dual-review evidence, and blocker status are separate fields.
- The verdict is PASS, REVISE, or BLOCK with concrete evidence IDs and exact missing evidence or fix requirements.
- Implementation fixes stay separate from the observed verdict, routed back to the executor/frontend workflow and rechecked against the resulting revision.

## Recovery Notes

- If no capture exists, produce the QA plan and mark verdict BLOCKED_BY_MISSING_RENDER_EVIDENCE.
- If capture lineage is missing or mismatched, keep HOLD and request the smallest matching recapture set.

## Workflow Lane

- Current lane: **Materials and visual summaries** (`design-orchestration`, `apple-design`, `design-quality-gate`, `award-bar-score`, `frontend`, `accessibility-audit`, `visual-qa`, `content-operator`, `+6 more`) - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use after or during visual surface work when Hermes must define the render evidence, viewport/state coverage, diff review, oracle review, and PASS/REVISE/BLOCK verdict without fabricating QA.

    Strong routing signals: `visual-qa`, `visual qa`, `visual QA`, `visual quality assurance`, `visual check`, `web qa`, `web visual qa`, `screenshot qa`, `screenshot check`, `analyze this screenshot`, `screenshot layout problems`, `ui layout problems`, `pixel diff`, `image diff`, `visual diff`, `render qa`, `render check`, `browser screenshot`, `browser qa`, `browser interaction qa`, `click path`, `click-path audit`, `dead link check`, `console error check`, `network failure check`, `keyboard navigation check`, `viewport check`, `responsive check`, `ui looks wrong`, `looks broken`, `layout broken`, `broken layout`, `text clipping`, `cjk clipping`, `cjk layout`, `tui check`, `terminal ui check`, `スクリーンショットで確認`, `レイアウト崩れ`, `画面崩れ`, `見た目のQA`, `비주얼 qa`, `비주얼QA`, `시각 qa`, `시각 검증`, `화면 검증`, `스크린샷 검증`, `스크린샷 ui 레이아웃`, `스크린샷 UI 레이아웃`, `스크린샷 레이아웃 문제`, `렌더 검증`, `픽셀 diff`, `픽셀 비교`, `화면 깨짐`, `레이아웃 깨짐`, `글자 잘림`, `한글 줄바꿈`, `터미널 ui`, `截图检查`, `页面错位`, `视觉验收`, `布局错乱`, `cek tampilan dari screenshot`, `tolong periksa layout yang berantakan`, `uji visual halaman yang sudah dirender`, `cek elemen yang terpotong di layar`, `tinjau hasil render antarmuka`, `bantu periksa tata letak dari tangkapan layar`

## Catalog Metadata

Category: `materials`
Phase: `visual-qa`
Hermes role: `operator`
Quality tier: `visual-qa-gated`
Reasoning demand: `standard`

Quality bar:

- List the exact pages, states, viewports, files, images, or TUI frames being checked.
- For TUI surfaces, bind every capture to an explicit terminal size (80x24 and 120x40 at minimum); pasted rendered output at a named size is the screenshot-equivalent, and a capture without its size is not evidence.
- Combine objective capture/diff evidence, hotspot review, alpha/transparent-background checks, and human-readable visual findings.
- Capture interaction, click-path, and motion states when the UI has transitions or controls that change state.
- Separate design-system consistency, functional integrity, visual fidelity, responsive behavior, accessibility visibility, and CJK/text precision.
- Score every round through `references/visual-verdict-contract.md`: integer 0-100 score, PASS/REVISE/BLOCK, and a differences list pairing each observed problem with the smallest fix.
- Hold 90 as the pass line: under it the verdict is REVISE and the named edits, a recapture of the same pages/states/viewports, and a fresh scored round are owed; rescoring the same captures is not a new round.
- A host-collected sub-90 baseline needs a changed revision, next round ordinal, and newer same-condition capture; plan caps only tighten.
- On Hermes, when `browser_vision` is in your tool list or tool_search finds it, the session can take its own captures: each such render_capture_manifest/v1 entry records the `screenshot_path` it returned, the URL, the viewport width the page reported, and the target revision, and an entry missing any of the four is not evidence; captures from the wrapper, executor, or user still count.
- Score a round from the captured image itself, never from an auxiliary model's `analysis` text, which is what the capture tool returns when the session has no native vision.
- On Hermes, for the session's own captures, set each required viewport with `browser_cdp` `Emulation.setDeviceMetricsOverride` when `browser_cdp` is in your tool list or tool_search finds it (Hermes offers it only with a CDP endpoint the user configured), then read the width back through `browser_console` (`window.innerWidth`) before the capture: each `browser_cdp` call opens its own connection, so the override may not hold, and a width that reads back other than the one requested is not that viewport. Without that tool, a width the browser does not already report is a named blocker for the session's own captures, and a capture of that width from the wrapper, executor, or user still counts.
- On Hermes, when `browser_console` is in your tool list or tool_search finds it, read it after every navigation and every interaction in scope and record its errors in console_network_health/v1; a clean console read is console evidence only, never network, accessibility, or visual evidence.
- Exploratory bug-hunting goes to Hermes' bundled `dogfood` skill when it is available: its issues and screenshots enter this verdict only as observed findings bound to the target lineage, and a report with no issues is not a PASS.

Handoff policy:

Keep the QA plan, evidence manifest, target-lineage rule, and verdict narration in Hermes. Screenshots, TUI captures, image diffs, browser runs, OCR/CJK checks, and oracle reviews are observed evidence supplied by the wrapper, executor, or user, or taken by the session's own browser tools.

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
- message_attachment_projection/v1 maps eligible observed captures to attachment candidates without claiming delivery
- web_visual_qa_message_card/v1 projects recorded criteria, captures, routing, cost policy, and attachment hints into chat-safe copy
- render_capture_manifest/v1 only from captures whose source lineage matches the target package
- browser_interaction_trace/v1 only from observed journey runs with read-only or staging-safe boundaries recorded
- console_network_health/v1 records observed console errors, failed requests, status codes, and ignored third-party noise
- click_path_state_trace/v1 maps each touchpoint to its handler, state reads/writes, final UI state, and undo/race/stale-closure risks
- accessibility_keyboard_trace/v1 records observed focus order, keyboard reachability, and automated scan boundaries
- visual_diff_evidence/v1 only when the wrapper/executor records objective diff output such as dimensionsMatch, diffRatio, similarityScore, alphaChannelIntact, and hotspots
- motion_interaction_capture/v1 only when motion frames are observed before, during, and after transition
- visual_hotspot_review/v1 maps diff hotspots, TUI overflow lines, or screenshot regions to visual causes
- dual_oracle_visual_review/v1 only when independent read-only review evidence exists
- visual_qa_verdict/v1 with the integer 0-100 score, PASS/REVISE/BLOCK, and difference/suggestion pairs
- PASS unavailable until capture repository/revision lineage exactly matches the package target, every required viewport is captured, and all supplied blocking findings are resolved
- web_qa_observation_run/v1 and web_qa_comparison/v1 only from a host_web_qa_adapter_receipt/v1 imported through `omh web-qa observation`: seven independently observed channels or a named blocker per cell

Safety rules:

- Never claim PASS without rendered evidence whose repository and revision exactly match the package target lineage.
- Source review, mismatched-lineage captures, generated plans, and unobserved browser commands are not visual QA evidence.
- Do not sample only one good page, viewport, or state when the surface has more; missed pages, modals, scroll states, or CJK-heavy regions keep PASS unavailable.
- Do not run destructive browser journeys such as checkout, payment, delete, or mass-update on production URLs; require staging or explicit safe test boundaries and redact credentials/PII from captures.
- Do not claim browser interaction PASS without observed click-path/state-transition traces for the touchpoints in scope.
- Do not claim accessibility from automated scan output alone; keyboard and focus-order evidence are separate observed checks.
- Pixel diff localizes hotspots only; it never produces the score or verdict, and objective diffs are evidence, not verdicts: review visual hierarchy, layout, CJK text, state coverage, and product intent separately.
- Do not excuse diff hotspots as animation; capture settled frames and motion frames separately.
- Claim high confidence only with two read-only reviews: design-system/functional integrity and visual fidelity/CJK precision.
- Operator-supplied blocking criteria (CJK clipping, broken wrapping, overlapping UI, invisible text, unusable controls, offscreen critical content) block PASS until `_validate_pass` sees passing evidence refs.
- Do not launch, poll, or watch browsers, image tools, LLMs, or external services from OMH core; the selected host or executor adapter does that work.
- A host receipt is observation, not permission: a missing channel keeps BLOCK, unequal condition digests are not_comparable, and a completed run is reused, not recollected.

## Runtime Evidence

Preferred harness for this skill: `visual-qa`.

```sh
omh runtime record --skill visual-qa --harness visual-qa --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a stop condition or a decision the user owns ends the turn, offer the next action as a question rather than declaring what will not be done.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
