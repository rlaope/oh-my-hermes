## Catalog Metadata

Category: `materials`
Phase: `visual-qa`
Quality tier: `visual-qa-gated`
Reasoning demand: `standard`

Quality bar:

- List the exact pages, states, viewports, files, images, or TUI frames being checked.
- For TUI surfaces, bind every capture to an explicit terminal size (80x24 and 120x40 at minimum); pasted rendered output at a named size is the screenshot-equivalent, and a capture without its size is not evidence.
- When a product surface is composed into a larger frame (promo, poster, slide, end card), measure it against the frame: a look-alike of a UI that exists, in place of its real renderer's output, is BLOCK, while an unbuilt UI labeled concept or a brief-requested stylised treatment labeled as such is not; with no subtitles a product-led shot is full-bleed, the full frame minus a 46 px edge inset (at least about 988 px tall at 1080p) with platform-UI zones still clear, and with subtitles it fills at least 90% of the width and height of the body safe area with the subtitle band clear; text rows are at least 2% of the frame's shorter side; a logo or identity mark keeps at least one of its own text rows from the frame and window edges, intentional crops excepted; meta text the product does not render (window title, dimension label, invented path) is removed; every count agrees with its noun in each plural category of the content locale. Each miss is one `differences` entry.
- Combine objective capture/diff evidence, hotspot review, alpha/transparent-background checks, and human-readable visual findings.
- Capture interaction, click-path, and motion states when the UI has transitions or controls that change state.
- For a 3D or canvas scene, capture the first frame exactly as booted, each camera preset, and every time of day the scene advertises; a claim in its own title or HUD that its first frame does not show, a small animated object that does not read as what it is, and flat light are each one `differences` entry (`omh-frontend/references/rendered-scene-craft.md`).
- A game or interactive scene passes only when captures show it boots (first frame neither blank nor one flat colour), answers its declared input (the frame after a key, click or touch differs from the frame before it where the input should move something), keeps running (frames seconds apart differ while idle, background-only animation not counting) and logs zero console errors across boot and input; a missing capture is BLOCK, reading code never passes it, and a run without a WebGL context is recorded as `environment: no_webgl`, not judged blank (`references/playable-check.md`).
- Separate design-system consistency, functional integrity, visual fidelity, responsive behavior, accessibility visibility, and CJK/text precision.
- Score every round through `references/visual-verdict-contract.md`: integer 0-100 score, PASS/REVISE/BLOCK, and a differences list pairing each observed problem with the smallest fix.
- Hold 90 as the pass line: under it the verdict is REVISE and the named edits, a recapture of the same pages/states/viewports, and a fresh scored round are owed; rescoring the same captures is not a new round.
- A host-collected sub-90 baseline needs a changed revision, next round ordinal, and newer same-condition capture; plan caps only tighten.
- Bind each capture to its screenshot path, URL, the viewport width the page reported, and the target revision; an entry missing any of the four is not evidence.
- Score a round from the captured image itself, never from another model's text description of it.
- Set a viewport only through a tool that can, and read the width back before the capture; a width that reads back other than the one requested is not that viewport, and a width nothing could set is a named blocker unless a capture of it is supplied.
- For animated or simulated output, verify motion continuity through `references/motion-continuity.md`: check entry/spawn position against the declared origin, per-frame displacement against the declared speed, force direction against observed motion (knockback sign), monotonic HP/resource bars, and re-run the full deploy/travel/engage flow in an independent simulation/replay with frames sampled per phase — never infer flow from cost/clear numbers, and record frame indices/timestamps as evidence; a technical pass (build/tests/metrics) is never visual approval.
- Read the browser console after every navigation and every interaction in scope; a clean console read is console evidence only, never network, accessibility, or visual evidence.
- For a phone-viewport capture, record in render_capture_manifest/v1 whether touch and mobile user-agent emulation was on; a width-only capture is named as width-only and does not show `(hover: none)`, `(pointer: coarse)` or user-agent branches. Phone-used surfaces also go through `omh-frontend/references/mobile-density-gate.md`.

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
- Operator-supplied blocking criteria (CJK clipping, broken wrapping, overlapping UI, invisible text, unusable controls, offscreen critical content) block PASS until each has a passing evidence ref in the package, which `omh web-qa` validation checks.
- Do not launch, poll, or watch browsers, image tools, LLMs, or external services from OMH core; the selected host or executor adapter does that work.
- A host receipt is observation, not permission: a missing channel keeps BLOCK, unequal condition digests are not_comparable, and a completed run is reused, not recollected.

