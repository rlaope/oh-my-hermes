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

## When to Use

Use when Hermes should shape or improve a web/frontend or terminal (TUI) surface before implementation: layout, design system, responsive states, accessibility, performance, motion, and anti-generic visual quality.

    Strong routing signals: `frontend`, `front-end`, `front end`, `frontend skill`, `in the frontend`, `on the frontend`, `to the frontend`, `web ui`, `ui ux`, `ui/ux`, `landing page`, `web app layout`, `responsive layout`, `responsive design`, `design system`, `component polish`, `layout polish`, `visual polish`, `styling`, `animation`, `motion design`, `smooth scroll`, `smooth scrolling`, `scroll animation`, `scroll animations`, `parallax scroll`, `parallax hero`, `parallax effect`, `chart styling`, `chart theming`, `chart colors`, `dashboard charts`, `style the charts`, `theme the charts`, `tooltip`, `footer design`, `better footer`, `site footer`, `website footer`, `neobrutalism`, `neobrutalism style`, `neobrutalist`, `neo brutalism`, `neo-brutalism`, `logo marquee`, `marquee animation`, `scrolling marquee`, `split text animation`, `split-text animation`, `shadcn`, `component registry`, `three.js scene`, `threejs scene`, `webgl scene`, `voxel scene`, `voxel art scene`, `accessibility`, `wcag`, `lighthouse`, `core web vitals`, `make it beautiful`, `make it premium`, `make it less ai`, `ai-looking ui`, `ai slop ui`, `slop ui`, `looks like ai slop`, `look like ai slop`, `feels like ai slop`, `screams ai slop`, `generic ui`, `broken layout`, `layout broken`, `frontend qa`, `frontend layout`, `tui design`, `terminal ui design`, `tui layout`, `フロントエンド`, `ランディングページ`, `レスポンシブ対応`, `デザインシステム`, `画面のUI実装`, `スムーススクロール`, `スクロールアニメーション`, `パララックス`, `チャートのスタイル`, `チャートスタイル`, `フッターデザイン`, `ネオブルータリズム`, `ロゴマーキー`, `프론트엔드`, `웹 ui`, `웹 화면`, `랜딩페이지`, `레이아웃`, `레이아웃 깨짐`, `깨짐`, `디자인 자연스럽게`, `자연스러운 디자인`, `화려하게`, `고급스럽게`, `부드러운 스크롤`, `스크롤 부드럽게`, `스크롤 애니메이션`, `패럴랙스`, `ai 티`, `ai틱`, `ai 틱`, `반응형`, `차트 스타일`, `차트 스타일링`, `차트 테마`, `푸터 디자인`, `네오브루탈리즘`, `로고 마키`, `마키 애니메이션`, `스플릿 텍스트`, `сделай лендинг`, `одностраничный лендинг`, `свёрстай страницу`, `сделай веб страницу`, `веб интерфейс`, `анимация на сайте`, `сделай сайт`, `анимацию при скролле`, `сделать веб страницу`, `лендинга`, `на лендинге`, `вёрстку сайта`, `сверстать страницу`, `сделай лэндинг`, `前端`, `落地页`, `响应式布局`, `设计系统`, `平滑滚动`, `滚动动画`, `视差滚动`, `图表样式`, `页脚设计`, `新粗野主义`, `跑马灯`, `bangun antarmuka UI frontend`, `bantu bikin landing page`, `rapikan tampilan frontend`, `buat halaman yang responsif`, `implementasikan desain UI`, `rancang antarmuka terminal`, `tambahkan animasi scroll`, `desain ulang tampilan dashboard`, `xây dựng giao diện frontend`, `giúp tạo landing page`, `cải thiện giao diện frontend`, `tạo trang có bố cục responsive`, `thực hiện thiết kế UI`, `thiết kế giao diện terminal`, `thêm hiệu ứng scroll`, `thiết kế lại giao diện dashboard`

Required inputs:

- target app, page, route, or component
- audience and primary user task
- existing design system or missing-system gap
- style references or quality bar
- initial generation mode or redesign mode
- DESIGN.md or design-system source of truth when available
- framework/stack when known
- routes, states, breakpoints, and locale/CJK risks
- browser-support target (default: Baseline Widely available, in every core browser for 30+ months)
- accessibility and performance constraints
- observed browser evidence for completion claims

Artifact expectations:

- frontend_design_brief/v1 when prepared
- frontend_initial_generation_contract/v1 declares DESIGN.md/design-system work, reference lane, token extraction, reusable primitives, and visual QA path before new UI code
- design_system_contract/v1 with layout, spacing, typography, color, component, motion, and responsive rules
- design_reference_selection/v1 names supplied references or the domain-fit style direction and explicitly avoids copying third-party logos, assets, or brand copy
- frontend_route_state_matrix/v1 with pages, states, viewports, CJK/locale, empty/loading/error, and interaction states, plus submitting, submit-failed, optimistic-pending, stale/refetching, and conflict (409) rows wherever the surface writes remote data
- frontend_component_state_inventory/v1 with default, hover, focus, active, disabled, loading, empty, and error states for reusable primitives, and each primitive's interface: props, events, slots, and the invariants a caller must know; a wrapper earns a row only when deleting it would push its complexity into its callers
- frontend_implementation_handoff/v1 for the selected executor/runtime
- browser screenshots, accessibility reports, Lighthouse/Core Web Vitals, and visual QA only when observed
