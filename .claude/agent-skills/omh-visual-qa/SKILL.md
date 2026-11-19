---
name: "omh-visual-qa"
description: "[omh] Rendered UI needing a visual verdict."
license: MIT
compatibility: "Requires the omh CLI on PATH (pip install oh-my-hermes)."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: visual-qa
    role: operator
    quality_tier: visual-qa-gated
---

# Visual Qa

This is an OMH `visual-qa` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`visual-qa` gives OMH a completion gate for rendered surfaces so layout breaks, AI-looking polish gaps, CJK text problems, and mismatched-lineage screenshot claims cannot be mistaken for verified quality.

## Do Not Use When

- The user needs initial frontend design or redesign planning before implementation; use `omh-frontend`.
- The user needs a broad visual quality rubric before generation; use `omh-design-quality-gate`.
- The user needs image-card prompt creation; use `omh-image-cards`.
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

- Interaction, console/network, click-path, keyboard/accessibility, diff, hotspot, motion, dual-review evidence, and blocker status are separate fields.
- The verdict is PASS, REVISE, or BLOCK with concrete evidence IDs and exact missing evidence or fix requirements.
- Implementation fixes stay separate from the observed verdict, routed back to the executor/frontend workflow and rechecked against the resulting revision.

## Recovery Notes

- If no capture exists, produce the QA plan and return verdict BLOCK with blocker `missing_render_evidence`.
- If capture lineage is missing or mismatched, return BLOCK with blocker `lineage_mismatch` and request the smallest matching recapture set.



## When to Use

Use after or during visual surface work when Hermes must define the render evidence, viewport/state coverage, diff review, oracle review, and PASS/REVISE/BLOCK verdict without fabricating QA.

    Strong routing signals: `visual-qa`, `visual qa`, `visual QA`, `visual quality assurance`, `visual check`, `web qa`, `web visual qa`, `screenshot qa`, `screenshot check`, `analyze this screenshot`, `screenshot layout problems`, `ui layout problems`, `pixel diff`, `image diff`, `visual diff`, `render qa`, `render check`, `browser screenshot`, `browser qa`, `browser interaction qa`, `click path`, `click-path audit`, `dead link check`, `console error check`, `network failure check`, `keyboard navigation check`, `viewport check`, `responsive check`, `ui looks wrong`, `looks broken`, `layout broken`, `broken layout`, `text clipping`, `cjk clipping`, `cjk layout`, `tui check`, `terminal ui check`, `スクリーンショットで確認`, `レイアウト崩れ`, `画面崩れ`, `見た目のQA`, `비주얼 qa`, `비주얼QA`, `시각 qa`, `시각 검증`, `화면 검증`, `스크린샷 검증`, `스크린샷 ui 레이아웃`, `스크린샷 UI 레이아웃`, `스크린샷 레이아웃 문제`, `렌더 검증`, `픽셀 diff`, `픽셀 비교`, `화면 깨짐`, `레이아웃 깨짐`, `글자 잘림`, `한글 줄바꿈`, `터미널 ui`, `вёрстка съехала`, `не сломалась ли вёрстка`, `截图检查`, `页面错位`, `视觉验收`, `布局错乱`, `cek tampilan dari screenshot`, `tolong periksa layout yang berantakan`, `uji visual halaman yang sudah dirender`, `cek elemen yang terpotong di layar`, `tinjau hasil render antarmuka`, `bantu periksa tata letak dari tangkapan layar`, `kiểm tra giao diện từ ảnh chụp màn hình`, `hãy kiểm tra bố cục bị lỗi`, `kiểm tra trực quan trang đã render`, `kiểm tra các thành phần bị cắt trên màn hình`, `rà soát kết quả render của giao diện`, `giúp kiểm tra bố cục từ ảnh chụp`

## Catalog Metadata

Read `references/details.md` before you act: it holds this skill's quality bar and catalog metadata, kept out of this file so the whole of it fits in one read on every host.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
