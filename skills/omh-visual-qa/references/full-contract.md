# Visual Qa

Load this on-demand contract after the compact `visual-qa` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

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

## Full Input, Output, and Artifact Expectations

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
