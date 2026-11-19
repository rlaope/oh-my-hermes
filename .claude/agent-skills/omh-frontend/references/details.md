## Catalog Metadata

Category: `materials`
Phase: `frontend-design`
Quality tier: `frontend-design-gated`
Reasoning demand: `standard`

Quality bar:

- Name the product goal, audience, target surfaces, routes, states, and visual quality bar.
- Hold the named bar: what a senior product designer at a top-tier product company (the Linear/Stripe/Supabase class) would sign off on — technically clean but flat output fails it. Load `references/taste-foundations.md`, name one primary taste direction, and reject the anti-slop patterns it lists.
- Name the model's own default aesthetic before inheriting it — the editorial prior of cream grounds, serif display faces, and muted terracotta accents suits editorial, portfolio, and hospitality briefs and is a failure mode on dashboards, developer tools, fintech, and data-dense UIs. Treat a generic negation ("don't make it look AI", "make it minimal") as unactionable: an override counts only when it carries concrete tokens, a hex palette and a typeface stack recorded in DESIGN.md. Run the review prompts in `references/taste-foundations.md` over framework blue, glass and gradient surfaces, default UI typefaces, bounce easing, blanket shadows, eyebrow/title/description stuffing, uniform column grids, and CJK body under the 14px Korean floor.
- When the target surface is a terminal UI (TUI), load `references/tui-craft.md` and hold the same bar there: default widgets are scaffolding, not finished UI; borders spent sparingly with spacing and a muted-color ladder doing the hierarchy; one named terminal aesthetic; verification rendered at 80x24 and 120x40 minimum with the pasted output as the screenshot-equivalent.
- Use references and domain fit to avoid generic AI-looking frontend output; when the user supplies a visual reference, load `references/reference-token-extraction.md` and extract tokens into the contract instead of eyeballing.
- Prepare a concrete design-system contract before implementation handoff: load `references/design-system-contract.md` and write DESIGN.md before the first component — no component code before the contract exists. A new DESIGN.md is Google's DESIGN.md format (YAML token front matter, its sections in its order) plus OMH's own sections; a file in OMH's earlier numbered layout stays valid and is converted only when the user asks. When Hermes' bundled `design-md` skill is available, author, lint, diff, or export a file in the format through it, never a file in the earlier layout; lint is evidence only from a run that executed, otherwise `not_observed`.
- Query the local design reference data before fixing tokens: `omh design data --kind palette|font|ux --context <product context>` returns curated palettes, font stacks with CJK notes, and UX guidelines offline. Those rows inform DESIGN.md; the contract, not the query, still gates the code.
- Scroll-driven motion is a decision with a bill: load `references/scroll-motion-libraries.md`, take the native path (CSS `scroll-behavior`, scroll-driven animations, `IntersectionObserver`, scroll-snap) unless one interpolated scroll position feeds several consumers, and when a library is chosen (Lenis is the reviewed record) name its reduced-motion branch, anchors, nested scroll, teardown, and INP budget in the contract.
- Copied component source is the project's to fix: before adopting from a shadcn-style registry, load `references/component-registry-adoption.md` (license, dependencies, reduced motion, ARIA, keyboard/touch, token mapping, one hero effect per view). Theme charts through tokens, not config literals: load `references/chart-styling.md`.
- A 3D or canvas scene (WebGL, a three.js-style engine, a voxel world) is judged on its first frame: load `references/rendered-scene-craft.md`, boot on the view the scene's own title and copy promise, light it with a warm-or-cool key, a sky fill, explicit tone mapping, shadows, and fog, and make every small animated object read as what it is. A clean console is not a finished scene.
- For first-time UI creation, name the initial generation branch, reference direction, reusable primitives, state coverage, and required visual QA path.
- Cover responsive layout, empty/loading/error states, hover/focus/active states, CJK text, accessibility, and performance expectations.
- For a new page or a redesign, load `references/editorial-layout.md` before choosing the layout.
- For a surface people use on a phone, load `references/mobile-density-gate.md`; measure with `toolkit/scripts/phone_check.py` (setup in `toolkit/README.md`: `skill_view(name='omh-frontend', file_path='toolkit/README.md')`) when a browser is available, otherwise the measurement is `not_observed`.
- When the surface reads or writes remote data, load the `omh-frontend-refactor` skill's `omh-frontend-refactor/references/state-discipline.md` (sections 1 and 4-6) before writing the component: server state lives in a query cache, each mutation names the query keys it invalidates, and an optimistic write ships with its rollback.
- When the surface has a form, a text composer, or a dialog, load `references/forms-and-input.md` before writing it: labelled controls, errors shown after the user commits a value, server field errors mapped onto their fields, one submit in flight, an Enter-to-send that waits for IME composition, and focus returned when a dialog closes.
- Check the browser-support target before using a newer platform feature: a feature newer than the target (by default, anything only Baseline Newly available) needs feature detection plus a fallback, or a deliberate target change; suggest recording the target in the repository's agent instruction file (`omh-agent-instructions` owns that file).
- State performance as a budget, not an adjective: load `references/web-vitals-budgets.md`, name one metric with its published bar (LCP, INP, CLS), the device and network class it is judged on, the route and load shape, and the baseline captured under that same profile - before the change. A budget chosen after seeing the result describes what happened instead of gating it.
- Attribute before optimizing: name the LCP element and its dominant phase, the interaction that produced the worst INP and where the time went, or the node that shifted and what moved above it. A list of optimizations with no attribution is folklore, and a change that improved a different element than the one attributed did not fix the metric.
- Keep field and lab apart: a p75 claim needs field data, a lab audit is a diagnostic sample on one device profile, and a lab pass is never a statement about real users.
- While building, look at each change that affects what renders: after it, capture the affected surface and read the capture before the next change, for a 3D or canvas scene the default camera and each declared preset; a change not looked at is not done (`references/screenshot-loop.md`, section `During implementation`).
- After implementation lands on a web surface, load `references/screenshot-loop.md` and require the screenshot iteration loop live-environment-first: capture the running UI at 1440/768/375px, compare against the supplied target or DESIGN.md, list every difference triaged Blocker/High/Medium/Nit with its capture attached, fix, and recapture until the difference list is empty.
- Prefer native UI controls, stable dimensions, and realistic content over decorative cards, blobs, and placeholder-heavy screens.
- When the handoff asks for component or interaction tests, read `../omh-verification-gate/references/test-authoring.md` and name the seam each test drives: assert through what a user perceives (role, accessible name, visible text) across the frontend_component_state_inventory/v1 states, never class names or component-internal state, and fake only at the boundaries the shared page lists (network, clock, randomness).
- Keep implementation, browser verification, accessibility/performance checks, visual QA, and deployment as observed-only evidence.

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
- frontend_route_state_matrix/v1 with pages, states, viewports, CJK/locale, empty/loading/error, and interaction states, plus submitting, submit-failed, optimistic-pending, stale/refetching, and conflict (409) rows wherever the surface writes remote data
- frontend_component_state_inventory/v1 with default, hover, focus, active, disabled, loading, empty, and error states for reusable primitives, and each primitive's interface: props, events, slots, and the invariants a caller must know; a wrapper earns a row only when deleting it would push its complexity into its callers
- frontend_implementation_handoff/v1 for the selected executor/runtime
- browser screenshots, accessibility reports, Lighthouse/Core Web Vitals, and visual QA only when observed

Safety rules:

- Do not claim implementation, browser verification, deployment, Lighthouse, accessibility pass, or visual QA from a prepared frontend brief.
- Reject generic AI-looking UI: one-note palettes, weak hierarchy, cramped cards, ungrounded gradients, decorative filler, and placeholder-heavy copy.
- Require a design-system contract before broad visual changes.
- For greenfield UI, require an initial generation contract before implementation handoff so the first generated screen has tokens, references, primitives, states, and QA expectations.
- Require fresh rendered evidence after the last UI edit before PASS.
- Do not hand off a smooth-scroll integration without its reduced-motion branch, keyboard/anchor/nested-scroll behavior, and teardown named; a `respectReducedMotion` option covers the library own scroll, never the animations the project wrote.
- Do not hand off a copied registry component or text effect without its license read at the source and its reduced-motion branch; decorative duplicates and split characters are `aria-hidden`, and a marquee gets a pause reachable by keyboard and touch.
- Do not report a Core Web Vitals number without the device class, route, and load shape it was measured under; a figure from a different profile than the baseline is not a comparison.
- For Korean/CJK text, clipped glyphs, awkward line breaks, orphan particles, tiny copy, and overflow block visual QA.
- Do not call external design, image, browser, LLM, or network services from OMH core.

