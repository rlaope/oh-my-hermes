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

Required: surface type, target URL, route, file, image, or TUI command when available, intended design, baseline, or reference, pages, states, viewports, and locales to cover, complete page/state/viewport enumeration rather than a sample, target repository and exact source revision, known risk areas such as CJK, overflow, responsiveness, or accessibility, motion and interaction states that need capture, browser interaction paths, mutating-flow boundary, and test credentials policy when a live web UI is in scope, console, network, accessibility, and keyboard navigation checks required for browser QA claims, render/capture evidence bound to the target repository and revision for completion claims. Output: visual_qa_plan/v1, web_visual_qa_package/v2, viewport_state_capture_matrix/v1, message_attachment_projection/v1 for chat attachments, web_visual_qa_message_card/v1 for chat message summaries, render_capture_manifest/v1 when observed, browser_interaction_trace/v1 when observed, console_network_health/v1 when observed, click_path_state_trace/v1 when observed, accessibility_keyboard_trace/v1 when observed, visual_diff_evidence/v1 when observed, visual_hotspot_review/v1 when observed, motion_interaction_capture/v1 when observed, dual_oracle_visual_review/v1 when observed, cjk_layout_findings/v1 when applicable, visual_qa_verdict/v1, retry_or_blocker/v1.

**Do Not Use When:** Open-ended bug-hunting across a web app with no page, state, and viewport matrix or target revision to judge; on Hermes, use the bundled `dogfood` skill when it is available.

## Why This Exists

`visual-qa` gives OMH a completion gate for rendered surfaces so layout breaks, AI-looking polish gaps, CJK text problems, and mismatched-lineage screenshot claims cannot be mistaken for verified quality.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Materials and visual summaries** - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use after or during visual surface work when Hermes must define the render evidence, viewport/state coverage, diff review, oracle review, and PASS/REVISE/BLOCK verdict without fabricating QA.

    Strong routing signals: `visual-qa`, `visual qa`, `visual QA`, `visual quality assurance`, `visual check`, `web qa`, `web visual qa`, `screenshot qa`, `screenshot check`, `analyze this screenshot`, `screenshot layout problems`, `ui layout problems`, `pixel diff`, `image diff`, `visual diff`, `render qa`, `render check`, `browser screenshot`, `browser qa`, `browser interaction qa`, `click path`, `click-path audit`, `dead link check`, `console error check`, `network failure check`, `keyboard navigation check`, `viewport check`, `responsive check`, `ui looks wrong`, `looks broken`, `layout broken`, `broken layout`, `text clipping`, `cjk clipping`, `cjk layout`, `tui check`, `terminal ui check`, `スクリーンショットで確認`, `レイアウト崩れ`, `画面崩れ`, `見た目のQA`, `비주얼 qa`, `비주얼QA`, `시각 qa`, `시각 검증`, `화면 검증`, `스크린샷 검증`, `스크린샷 ui 레이아웃`, `스크린샷 UI 레이아웃`, `스크린샷 레이아웃 문제`, `렌더 검증`, `픽셀 diff`, `픽셀 비교`, `화면 깨짐`, `레이아웃 깨짐`, `글자 잘림`, `한글 줄바꿈`, `터미널 ui`, `вёрстка съехала`, `не сломалась ли вёрстка`, `截图检查`, `页面错位`, `视觉验收`, `布局错乱`, `cek tampilan dari screenshot`, `tolong periksa layout yang berantakan`, `uji visual halaman yang sudah dirender`, `cek elemen yang terpotong di layar`, `tinjau hasil render antarmuka`, `bantu periksa tata letak dari tangkapan layar`, `kiểm tra giao diện từ ảnh chụp màn hình`, `hãy kiểm tra bố cục bị lỗi`, `kiểm tra trực quan trang đã render`, `kiểm tra các thành phần bị cắt trên màn hình`, `rà soát kết quả render của giao diện`, `giúp kiểm tra bố cục từ ảnh chụp`

## Catalog Metadata

Category: `materials`
Phase: `visual-qa`
Hermes role: `operator`
Quality tier: `visual-qa-gated`
Reasoning demand: `standard`

Quality bar:

- List the exact pages, states, viewports, files, images, or TUI frames being checked.
- For TUI surfaces, bind every capture to an explicit terminal size (80x24 and 120x40 at minimum); pasted rendered output at a named size is the screenshot-equivalent, and a capture without its size is not evidence.
- When a product surface is composed into a larger frame (promo, poster, slide, end card), measure it against the frame: a look-alike of a UI that exists, in place of its real renderer's output, is BLOCK, while an unbuilt UI labeled concept or a brief-requested stylised treatment labeled as such is not; with no subtitles a product-led shot is full-bleed, the full frame minus a 46 px edge inset (at least about 988 px tall at 1080p) with platform-UI zones still clear, and with subtitles it fills at least 90% of the width and height of the body safe area with the subtitle band clear; text rows are at least 2% of the frame's shorter side; a logo or identity mark keeps at least one of its own text rows from the frame and window edges, intentional crops excepted; meta text the product does not render (window title, dimension label, invented path) is removed; every count agrees with its noun in each plural category of the content locale. Each miss is one `differences` entry.
- Combine objective capture/diff evidence, hotspot review, alpha/transparent-background checks, and human-readable visual findings.
- Capture interaction, click-path, and motion states when the UI has transitions or controls that change state.
- Compare against the reference at the size and density people will see it: the real viewport, the real icon or toolbar size (a 24 px toolbar slot), the real slide or card dimensions, not only an enlarged render, where detail that reads at large size can vanish. An interactive result is exercised with the actions it supports (click, type, scroll, key) before any verdict.
- For a 3D or canvas scene, capture the first frame exactly as booted, each camera preset, and every time of day the scene advertises; a claim in its own title or HUD that its first frame does not show, a small animated object that does not read as what it is, and flat light are each one `differences` entry (`omh-frontend/references/rendered-scene-craft.md`).
- A game or interactive scene passes only when captures show it boots (first frame neither blank nor one flat colour), answers its declared input (the frame after a key, click or touch differs from the frame before it where the input should move something), keeps running (frames seconds apart differ while idle, background-only animation not counting) and logs zero console errors across boot and input; a missing capture is BLOCK, reading code never passes it, and a run without a WebGL context is recorded as `environment: no_webgl`, not judged blank (`references/playable-check.md`).
- Separate design-system consistency, functional integrity, visual fidelity, responsive behavior, accessibility visibility, and CJK/text precision.
- Score every round through `references/visual-verdict-contract.md`: integer 0-100 score, PASS/REVISE/BLOCK, and a differences list pairing each observed problem with the smallest fix.
- For animated or simulated output, verify motion continuity through `references/motion-continuity.md`: check entry/spawn position against the declared origin, per-frame displacement against the declared speed, force direction against observed motion (knockback sign), monotonic HP/resource bars, and re-run the full deploy/travel/engage flow in an independent simulation/replay with frames sampled per phase — never infer flow from cost/clear numbers, and record frame indices/timestamps as evidence; a technical pass (build/tests/metrics) is never visual approval.
- Hold 90 as the pass line: under it the verdict is REVISE and the named edits, a recapture of the same pages/states/viewports, and a fresh scored round are owed; rescoring the same captures is not a new round.
- A host-collected sub-90 baseline needs a changed revision, next round ordinal, and newer same-condition capture; plan caps only tighten.
- On Hermes, when `browser_vision` is in your tool list or tool_search finds it, the session can take its own captures: each such render_capture_manifest/v1 entry records the `screenshot_path` it returned, the URL, the viewport width the page reported, and the target revision, and an entry missing any of the four is not evidence; captures from the wrapper, executor, or user still count.
- Score a round from the captured image itself, never from an auxiliary model's `analysis` text, which is what the capture tool returns when the session has no native vision.
- On Hermes, for the session's own captures, set each required viewport with `browser_cdp` `Emulation.setDeviceMetricsOverride` when `browser_cdp` is in your tool list or tool_search finds it (Hermes offers it only with a CDP endpoint the user configured), then read the width back through `browser_console` (`window.innerWidth`) before the capture: each `browser_cdp` call opens its own connection, so the override may not hold, and a width that reads back other than the one requested is not that viewport. Without that tool, a width the browser does not already report is a named blocker for the session's own captures, and a capture of that width from the wrapper, executor, or user still counts.
- On Hermes, when `browser_console` is in your tool list or tool_search finds it, read it after every navigation and every interaction in scope and record its errors in console_network_health/v1; a clean console read is console evidence only, never network, accessibility, or visual evidence.
- For a phone-viewport capture, record in render_capture_manifest/v1 whether touch and mobile user-agent emulation was on; a width-only capture is named as width-only and does not show `(hover: none)`, `(pointer: coarse)` or user-agent branches. Phone-used surfaces also go through the `omh-frontend` skill's `references/mobile-density-gate.md`.
- Exploratory bug-hunting goes to Hermes' bundled `dogfood` skill when it is available: its issues and screenshots enter this verdict only as observed findings bound to the target lineage, and a report with no issues is not a PASS.

Handoff policy:

Keep the QA plan, evidence manifest, target-lineage rule, and verdict narration in Hermes. Screenshots, TUI captures, image diffs, browser runs, OCR/CJK checks, and oracle reviews are observed evidence supplied by the wrapper, executor, or user, or taken by the session's own browser tools.

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
- Operator-supplied blocking criteria (CJK clipping, broken wrapping, overlapping UI, invisible text, unusable controls, offscreen critical content) block PASS until each has a passing evidence ref in the package, which `omh web-qa` validation checks.
- Do not launch, poll, or watch browsers, image tools, LLMs, or external services from OMH core; the selected host or executor adapter does that work.
- A host receipt is observation, not permission: a missing channel keeps BLOCK, unequal condition digests are not_comparable, and a completed run is reused, not recollected.

## Completion Checklist

- Interaction, console/network, click-path, keyboard/accessibility, diff, hotspot, motion, dual-review evidence, and blocker status are separate fields.
- The verdict is PASS, REVISE, or BLOCK with concrete evidence IDs and exact missing evidence or fix requirements.
- Implementation fixes stay separate from the observed verdict, routed back to the executor/frontend workflow and rechecked against the resulting revision.

## Recovery Notes

- If no capture exists, produce the QA plan and return verdict BLOCK with blocker `missing_render_evidence`.
- If capture lineage is missing or mismatched, return BLOCK with blocker `lineage_mismatch` and request the smallest matching recapture set.

## Runtime Evidence

Preferred harness for this skill: `visual-qa`.

```sh
omh runtime record --skill visual-qa --harness visual-qa --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
