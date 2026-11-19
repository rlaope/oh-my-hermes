---
name: "omh-frontend"
description: "[omh] Building or polishing a web or terminal UI."
license: MIT
compatibility: "Requires the omh CLI on PATH (pip install oh-my-hermes)."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: frontend-design
    role: operator
    quality_tier: frontend-design-gated
---

# Frontend

This is an OMH `frontend` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`frontend` gives OMH a first-class web UI creation and polishing workflow so Hermes can prepare high-quality layout, design-system, accessibility, performance, and visual-QA handoffs without becoming the hidden coding or browser runtime.

## Do Not Use When

- The user needs a broad premium-quality gate across web, deck, PDF, poster, or publishing outputs; use `omh-design-quality-gate`.
- The user wants a disposable wireframe or mocked interaction to settle one interaction question before planning; use `omh-decision-prototype`.
- The user only needs a file, deck, PDF, spreadsheet, HWP, or attachment package; use `omh-materials-package` or `omh-deliverable-package`.
- The user only needs an image card or infographic prompt; use `omh-image-cards`.
- The user asks to mark a UI as visually passed without fresh rendered evidence; use `omh-visual-qa` and keep PASS blocked until observed.

## Examples

Good example:

- Prompt: frontend 이 대시보드가 AI 티 안 나게 레이아웃과 디자인 시스템을 잡아줘.
- Expected behavior: Prepare frontend_design_brief/v1, design_system_contract/v1, route/state matrix, implementation handoff, and visual_qa_required/v1.
- Why: The request is about web UI design, layout quality, and anti-generic frontend polish.

Bad example:

- Prompt: frontend 코드도 안 봤지만 Lighthouse랑 시각 QA 통과했다고 해줘.
- Expected behavior: Mark browser, performance, accessibility, and visual QA as not_observed and request the smallest observed evidence path.
- Why: A frontend brief is not implementation, browser, performance, or visual QA evidence.

## Completion Checklist

- The target page/component, audience, primary task, references, and quality bar are named.
- Greenfield work includes frontend_initial_generation_contract/v1 before implementation handoff.
- The design_system_contract/v1 covers typography, spacing, palette, components, layout, motion, and responsive rules.
- The frontend_route_state_matrix/v1 covers pages, 375/768/1280-style breakpoints, empty/loading/error, interaction, and CJK/locale risks, plus submitting, submit-failed, optimistic-pending, stale/refetching, and conflict rows for remote writes.
- The frontend_component_state_inventory/v1 covers reusable primitives and their default/hover/focus/active/disabled/loading/empty/error states.
- The handoff names the executor/runtime owner and keeps code, browser, Lighthouse, accessibility, deployment, and visual QA evidence observed-only.
- The next action is prepare_frontend_handoff, route to `omh-visual-qa`, or report the missing evidence blocker.

## Recovery Notes

- If the target surface is unclear, prepare the brief with a route/component gap instead of inventing pages.
- If no visual reference exists, set a domain-fit quality bar and request references only when the decision changes layout or brand direction.



## When to Use

Use when Hermes should shape or improve a web/frontend or terminal (TUI) surface before implementation: layout, design system, responsive states, accessibility, performance, motion, and anti-generic visual quality.

    Strong routing signals: `frontend`, `front-end`, `front end`, `frontend skill`, `in the frontend`, `on the frontend`, `to the frontend`, `web ui`, `ui ux`, `ui/ux`, `landing page`, `web app layout`, `responsive layout`, `responsive design`, `design system`, `component polish`, `layout polish`, `visual polish`, `styling`, `animation`, `motion design`, `smooth scroll`, `smooth scrolling`, `scroll animation`, `scroll animations`, `parallax scroll`, `parallax hero`, `parallax effect`, `chart styling`, `chart theming`, `chart colors`, `dashboard charts`, `style the charts`, `theme the charts`, `tooltip`, `footer design`, `better footer`, `site footer`, `website footer`, `neobrutalism`, `neobrutalism style`, `neobrutalist`, `neo brutalism`, `neo-brutalism`, `logo marquee`, `marquee animation`, `scrolling marquee`, `split text animation`, `split-text animation`, `shadcn`, `component registry`, `three.js scene`, `threejs scene`, `webgl scene`, `voxel scene`, `voxel art scene`, `accessibility`, `wcag`, `lighthouse`, `core web vitals`, `make it beautiful`, `make it premium`, `make it less ai`, `ai-looking ui`, `ai slop ui`, `slop ui`, `looks like ai slop`, `look like ai slop`, `feels like ai slop`, `screams ai slop`, `generic ui`, `broken layout`, `layout broken`, `frontend qa`, `frontend layout`, `tui design`, `terminal ui design`, `tui layout`, `フロントエンド`, `ランディングページ`, `レスポンシブ対応`, `デザインシステム`, `画面のUI実装`, `スムーススクロール`, `スクロールアニメーション`, `パララックス`, `チャートのスタイル`, `チャートスタイル`, `フッターデザイン`, `ネオブルータリズム`, `ロゴマーキー`, `프론트엔드`, `웹 ui`, `웹 화면`, `랜딩페이지`, `레이아웃`, `레이아웃 깨짐`, `깨짐`, `디자인 자연스럽게`, `자연스러운 디자인`, `화려하게`, `고급스럽게`, `부드러운 스크롤`, `스크롤 부드럽게`, `스크롤 애니메이션`, `패럴랙스`, `ai 티`, `ai틱`, `ai 틱`, `반응형`, `차트 스타일`, `차트 스타일링`, `차트 테마`, `푸터 디자인`, `네오브루탈리즘`, `로고 마키`, `마키 애니메이션`, `스플릿 텍스트`, `сделай лендинг`, `одностраничный лендинг`, `свёрстай страницу`, `сделай веб страницу`, `веб интерфейс`, `анимация на сайте`, `сделай сайт`, `анимацию при скролле`, `сделать веб страницу`, `лендинга`, `на лендинге`, `вёрстку сайта`, `сверстать страницу`, `сделай лэндинг`, `前端`, `落地页`, `响应式布局`, `设计系统`, `平滑滚动`, `滚动动画`, `视差滚动`, `图表样式`, `页脚设计`, `新粗野主义`, `跑马灯`, `bangun antarmuka UI frontend`, `bantu bikin landing page`, `rapikan tampilan frontend`, `buat halaman yang responsif`, `implementasikan desain UI`, `rancang antarmuka terminal`, `tambahkan animasi scroll`, `desain ulang tampilan dashboard`, `xây dựng giao diện frontend`, `giúp tạo landing page`, `cải thiện giao diện frontend`, `tạo trang có bố cục responsive`, `thực hiện thiết kế UI`, `thiết kế giao diện terminal`, `thêm hiệu ứng scroll`, `thiết kế lại giao diện dashboard`

## Catalog Metadata

Read `references/details.md` before you act: it holds this skill's quality bar and catalog metadata, kept out of this file so the whole of it fits in one read on every host.

Toolkit setup: `skill_view(name='omh-frontend', file_path='toolkit/README.md')`.

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
