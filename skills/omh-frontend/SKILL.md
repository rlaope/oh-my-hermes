---
name: "omh-frontend"
description: "[omh] Hermes frontend workflow: prepare design-system-driven web and terminal (TUI) UI creation, redesign, polish, accessibility, performance, and visual QA handoffs. Use when the user says: frontend, front-end, front end, frontend skill, web ui, ui ux, landing page, web app layout."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: frontend-design
    role: operator
    quality_tier: frontend-design-gated
---

# Frontend

This is a Hermes-native `frontend` workflow skill.

## Why This Exists

`frontend` gives OMH a first-class web UI creation and polishing workflow so Hermes can prepare high-quality layout, design-system, accessibility, performance, and visual-QA handoffs without becoming the hidden coding or browser runtime.

## Do Not Use When

- The user needs a broad premium-quality gate across web, deck, PDF, poster, or publishing outputs; use `design-quality-gate`.
- The user only needs a file, deck, PDF, spreadsheet, HWP, or attachment package; use `materials-package` or `deliverable-package`.
- The user only needs an image card or infographic prompt; use `img-summary`.
- The user asks to mark a UI as visually passed without fresh rendered evidence; use `visual-qa` and keep PASS blocked until observed.

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
- The frontend_route_state_matrix/v1 covers pages, 375/768/1280-style breakpoints, empty/loading/error, interaction, and CJK/locale risks.
- The frontend_component_state_inventory/v1 covers reusable primitives and their default/hover/focus/active/disabled/loading/empty/error states.
- The handoff names the executor/runtime owner and keeps code, browser, Lighthouse, accessibility, deployment, and visual QA evidence observed-only.
- The next action is prepare_frontend_handoff, route to visual-qa, or report the missing evidence blocker.

## Recovery Notes

- If the target surface is unclear, prepare the brief with a route/component gap instead of inventing pages.
- If no visual reference exists, set a domain-fit quality bar and request references only when the decision changes layout or brand direction.

## Workflow Lane

- Current lane: **Materials and visual summaries** (`design-orchestration`, `apple-design`, `design-quality-gate`, `award-bar-score`, `frontend`, `accessibility-audit`, `visual-qa`, `content-operator`, `+6 more`) - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when Hermes should shape or improve a web/frontend or terminal (TUI) surface before implementation: layout, design system, responsive states, accessibility, performance, motion, and anti-generic visual quality.

    Strong routing signals: `frontend`, `front-end`, `front end`, `frontend skill`, `web ui`, `ui ux`, `ui/ux`, `landing page`, `web app layout`, `responsive layout`, `responsive design`, `design system`, `component polish`, `layout polish`, `visual polish`, `styling`, `animation`, `motion design`, `accessibility`, `wcag`, `lighthouse`, `core web vitals`, `make it beautiful`, `make it premium`, `make it less ai`, `ai-looking ui`, `ai slop ui`, `generic ui`, `broken layout`, `layout broken`, `frontend qa`, `frontend layout`, `tui design`, `terminal ui design`, `tui layout`, `フロントエンド`, `ランディングページ`, `レスポンシブ対応`, `デザインシステム`, `画面のUI実装`, `프론트엔드`, `웹 ui`, `웹 화면`, `랜딩페이지`, `레이아웃`, `레이아웃 깨짐`, `깨짐`, `디자인 자연스럽게`, `자연스러운 디자인`, `화려하게`, `고급스럽게`, `ai 티`, `ai틱`, `ai 틱`, `반응형`, `접근성`, `前端`, `落地页`, `响应式布局`, `设计系统`

## Catalog Metadata

Category: `materials`
Phase: `frontend-design`
Hermes role: `operator`
Quality tier: `frontend-design-gated`
Reasoning demand: `standard`

Quality bar:

- Name the product goal, audience, target surfaces, routes, states, and visual quality bar.
- Hold the named bar: what a senior product designer at a top-tier product company (the Linear/Stripe/Supabase class) would sign off on — technically clean but flat output fails it. Load `references/taste-foundations.md`, name one primary taste direction, and reject the anti-slop patterns it lists.
- Name the model's own default aesthetic before inheriting it — the editorial prior of cream grounds, serif display faces, and muted terracotta accents suits editorial, portfolio, and hospitality briefs and is a failure mode on dashboards, developer tools, fintech, and data-dense UIs. Treat a generic negation ("don't make it look AI", "make it minimal") as unactionable: an override counts only when it carries concrete tokens, a hex palette and a typeface stack recorded in DESIGN.md. Run the review prompts in `references/taste-foundations.md` over framework blue, glass and gradient surfaces, default UI typefaces, bounce easing, blanket shadows, eyebrow/title/description stuffing, uniform column grids, and CJK body under the 14px Korean floor.
- When the target surface is a terminal UI (TUI), load `references/tui-craft.md` and hold the same bar there: default widgets are scaffolding, not finished UI; borders spent sparingly with spacing and a muted-color ladder doing the hierarchy; one named terminal aesthetic; verification rendered at 80x24 and 120x40 minimum with the pasted output as the screenshot-equivalent.
- Use references and domain fit to avoid generic AI-looking frontend output; when the user supplies a visual reference, load `references/reference-token-extraction.md` and extract tokens into the contract instead of eyeballing.
- Prepare a concrete design-system contract before implementation handoff: load `references/design-system-contract.md` and write DESIGN.md before the first component — no component code before the contract exists.
- Query the local design reference data before fixing tokens: `omh design data --kind palette|font|ux --context <product context>` returns curated palettes, font stacks with CJK notes, and UX guidelines offline. Those rows inform DESIGN.md; the contract, not the query, still gates the code.
- For first-time UI creation, name the initial generation branch, reference direction, reusable primitives, state coverage, and required visual QA path.
- Cover responsive layout, empty/loading/error states, hover/focus/active states, CJK text, accessibility, and performance expectations.
- State performance as a budget, not an adjective: load `references/web-vitals-budgets.md`, name one metric with its published bar (LCP, INP, CLS), the device and network class it is judged on, the route and load shape, and the baseline captured under that same profile - before the change. A budget chosen after seeing the result describes what happened instead of gating it.
- Attribute before optimizing: name the LCP element and its dominant phase, the interaction that produced the worst INP and where the time went, or the node that shifted and what moved above it. A list of optimizations with no attribution is folklore, and a change that improved a different element than the one attributed did not fix the metric.
- Keep field and lab apart: a p75 claim needs field data, a lab audit is a diagnostic sample on one device profile, and a lab pass is never a statement about real users.
- After implementation lands on a web surface, load `references/screenshot-loop.md` and require the screenshot iteration loop live-environment-first: capture the running UI at 1440/768/375px, compare against the supplied target or DESIGN.md, list every difference triaged Blocker/High/Medium/Nit with its capture attached, fix, and recapture until the difference list is empty.
- Prefer native UI controls, stable dimensions, and realistic content over decorative cards, blobs, and placeholder-heavy screens.
- Keep implementation, browser verification, accessibility/performance checks, visual QA, and deployment as observed-only evidence.

Handoff policy:

Keep product framing, reference selection, design-system contract, viewport/state matrix, and implementation brief in Hermes. Record code changes, browser screenshots, Lighthouse/Core Web Vitals, accessibility scans, and visual QA only from executor or wrapper observed evidence.

Required inputs:

- target app, page, route, or component
- audience and primary user task
- existing design system or missing-system gap
- style references or quality bar
- initial generation mode or redesign mode
- DESIGN.md or design-system source of truth when available
- framework/stack when known
- routes, states, breakpoints, and locale/CJK risks
- accessibility and performance constraints
- observed browser evidence for completion claims

Expected outputs:

- frontend_design_brief/v1
- frontend_initial_generation_contract/v1 when greenfield
- design_system_contract/v1
- design_reference_selection/v1
- reference_packet/v1 when supplied
- frontend_route_state_matrix/v1
- frontend_component_state_inventory/v1
- frontend_implementation_handoff/v1
- accessibility_performance_expectations/v1
- visual_qa_required/v1
- observed_browser_evidence/v1 when observed

Artifact expectations:

- frontend_design_brief/v1 when prepared
- frontend_initial_generation_contract/v1 declares DESIGN.md/design-system work, reference lane, token extraction, reusable primitives, and visual QA path before new UI code
- design_system_contract/v1 with layout, spacing, typography, color, component, motion, and responsive rules
- design_reference_selection/v1 names supplied references or the domain-fit style direction and explicitly avoids copying third-party logos, assets, or brand copy
- frontend_route_state_matrix/v1 with pages, states, viewports, CJK/locale, empty/loading/error, and interaction states
- frontend_component_state_inventory/v1 with default, hover, focus, active, disabled, loading, empty, and error states for reusable primitives
- frontend_implementation_handoff/v1 for the selected executor/runtime
- browser screenshots, accessibility reports, Lighthouse/Core Web Vitals, and visual QA only when observed

Safety rules:

- Do not claim implementation, browser verification, deployment, Lighthouse, accessibility pass, or visual QA from a prepared frontend brief.
- Reject generic AI-looking UI: one-note palettes, weak hierarchy, cramped cards, ungrounded gradients, decorative filler, and placeholder-heavy copy.
- Require a design-system contract before broad visual changes.
- For greenfield UI, require an initial generation contract before implementation handoff so the first generated screen has tokens, references, primitives, states, and QA expectations.
- Require fresh rendered evidence after the last UI edit before PASS.
- Do not report a Core Web Vitals number without the device class, route, and load shape it was measured under; a figure from a different profile than the baseline is not a comparison.
- For Korean/CJK text, clipped glyphs, awkward line breaks, orphan particles, tiny copy, and overflow block visual QA.
- Do not call external design, image, browser, LLM, or network services from OMH core.

## Runtime Evidence

Preferred harness for this skill: `frontend`.

```sh
omh runtime record --skill frontend --harness frontend --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
