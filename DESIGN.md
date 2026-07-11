# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-07-11
- Primary product surfaces: GitHub Pages homepage, documentation index, workflow detail pages, README-linked public assets.
- Evidence reviewed: `site/index.html`, `site/styles.css`, every `site/docs/*/index.html`, `README.md`, `docs/DIRECTION.md`, `docs/CAPABILITIES.md`, `src/capabilities/families.py`, `src/quality/capability_impact.py`, the live `https://aside.com/` page, and the local Aside reference digest.
- Reference intent: borrow Aside's bright product-app density, compact type, hairline bands, neutral controls, and browser-frame focal object. Do not copy its logo, product imagery, copy, or proprietary assets.

## Brand
- Personality: precise, capable, calm, inspectable, and operator-grade.
- Trust signals: deterministic routing contracts, local artifacts, six capability families, prepared-versus-observed evidence, executor-neutral handoffs, and explicit verification boundaries.
- Avoid: dark launch-poster composition, oversized type, stacked marketing cards, decorative gradients, hidden-agent claims, executor favoritism, and command-catalog sprawl.

## Product goals
- Goals: explain OMH in one viewport, show the product through a real contract workbench, make the six capability families scannable, expose the evidence boundary, and keep installation and deeper docs obvious.
- Non-goals: do not reposition OMH as a standalone bot, Hermes core patch, network service, LLM router, or hidden coding executor.
- Success signals: a new visitor can answer what OMH adds, what it can prepare, what still needs observed proof, and where to start in under one minute.

## Personas and jobs
- Primary personas: existing Hermes users, maintainers, wrapper builders, coding-agent operators, and teams evaluating Hermes-native orchestration.
- User jobs: understand the value before installing, route a plain-language request, choose the right capability family, prepare executor-ready work, inspect proof boundaries, and find deeper contracts.
- Key contexts of use: GitHub README, GitHub Pages, wrapper integration planning, technical evaluation, and release review.

## Information architecture
- Primary navigation: Product, Capabilities, Evidence, Docs, GitHub.
- Homepage sequence: compact hero; contract workbench; proof rail; capability-family bands; coding handoff; knowledge and operations; evidence model; install.
- Documentation sequence: start paths; capability families; runtime and wrapper contracts; quality and evidence; deep references.
- Detail pages: keep existing routes and content ownership, but render them through the shared compact page shell.

## Design principles
- Product before promises: the first viewport contains a working-looking OMH contract surface, not decorative art.
- Quiet confidence: use medium weight, compact scale, white space, and thin dividers instead of oversized headings or glow.
- Dense where useful: capability and evidence modules should resemble operator UI, with short labels and structured values.
- One claim, one proof boundary: every capability statement names whether it is prepared, registered, locally checked, or observed.
- Original composition: Aside is a layout and token reference only; OMH content and product surfaces remain original.

## Visual language
- Color: `canvas` #ffffff; `soft` #f5f5f2; `soft-blue` #eef7fa; `ink` #090b0c; `muted` #62686f; `quiet` #6b7177; `line` rgba(9, 11, 12, 0.09); `accent` #147c70; `accent-soft` #e7f5f1; `observed` #2563eb; `warning` #94540f.
- Typography: local system sans for body/UI with `Arial`, `Helvetica Neue`, and platform fallbacks; Georgia for selected display claims; system monospace for contracts. No remote font dependency.
- Type scale: display 52/56; page title 44/48; section 38/44; subsection 26/32; card title 18/24; body 16/24; small body 14/21; label 12/16. Mobile steps down to 38/42, 34/40, and 30/36 without viewport-based scaling.
- Spacing: 4px base unit; page gutter 24px mobile, 40px tablet, 56px desktop; sections 72px desktop and 48px mobile; compact UI uses 8px, 12px, 16px, and 24px rhythm.
- Shape: 999px only for trust pills and primary hero actions; 8px for product frames and repeated cards; 6px for controls; structural bands stay square.
- Elevation: hairline borders first; one restrained neutral frame shadow; no colored glow or stacked decorative shadows.
- Motion: 150-180ms color, background, border, opacity, and transform transitions tied to real links or controls. No decorative looping animation.
- Imagery: use existing workflow posters only in secondary reference modules. The hero focal object is a live DOM contract workbench.

## Components
- Site shell: compact sticky topbar, max-width content frame, full-width section bands, simple footer.
- Buttons: neutral primary, quiet secondary, text link; default, hover, active, focus-visible, disabled states.
- Trust pill: one provenance signal near the hero claim; no chip clouds.
- Product workbench: browser-like frame with sidebar, message intake, route contract, capability family, selected executor state, and evidence ladder.
- Proof rail: compact facts separated by hairlines, not floating cards.
- Capability rows: full-width bands with claim, explanation, and product specimen.
- Route and evidence primitives: state dot, key/value row, compact status label, boundary note, and command block.
- Docs primitives: sticky local navigation, start-path rows, reference list, callout, feature hero, prose measure, and code block.
- Showcase harness: `site/design-system.html` renders core primitives and states at mobile, tablet, and desktop widths before product-page QA.

## Accessibility
- Target standard: WCAG 2.1 AA, with Lighthouse accessibility 100 as a verification target.
- Keyboard: skip link first, visible focus ring, logical source order, and no interactive-looking non-interactive element.
- Contrast: ink and muted text must pass on canvas and soft surfaces; accent is a signal, never the only carrier of state.
- Semantics: one H1 per page, ordered headings, landmark elements, descriptive link text, explicit image dimensions, and useful alt text.
- Motion: honor `prefers-reduced-motion`; product understanding must not depend on animation.
- Cognitive accessibility: short paragraphs, stable labels, consistent state vocabulary, and no command knowledge required to understand the public story.

## Responsive behavior
- Supported viewports: 360px mobile, 768px tablet, 1280px desktop, and 1440px wide desktop.
- Desktop: full navigation, two-column hero, complete workbench, side-by-side capability specimens.
- Tablet: simplified navigation spacing, stacked hero copy and workbench, two-column proof and reference modules.
- Mobile: product frame keeps a stable crop, sidebar becomes a horizontal rail, dense rows wrap without horizontal page overflow, and docs navigation becomes a compact scrollable row after the hero.
- Touch: controls remain at least 40px high; hover is an enhancement only.

## Interaction states
- Loading: not applicable to the static site; never show fake progress.
- Empty: workbench specimens use explicit `not observed` or `not connected` states rather than blank panels.
- Error: documentation examples state the missing evidence/provider instead of implying failure recovery happened.
- Success: observed states use icon, label, and text together.
- Disabled: prepared actions that require acceptance use real disabled semantics in specimens.
- Offline: all CSS, HTML, icons, and images are local; no external script or font is required.

## Content voice
- Tone: direct, concrete, calm, and technically honest.
- Headline rule: use literal product or capability names; place benefits in supporting copy.
- Terminology: Hermes-native orchestration, capability family, local contract, selected executor, prepared handoff, observed evidence, external provider, reviewed project memory.
- Claims: never turn registration, routing, preparation, or guidance into execution, review, CI, merge, publication, or outcome proof.
- README: stay short enough to scan; installation, six families, evidence boundary, and deeper links are the primary content.

## Implementation constraints
- Framework: static HTML and CSS under `site/`; no JavaScript or frontend build dependency.
- Token ownership: `site/styles.css` owns all public tokens and reusable primitives; pages do not use inline styles.
- Performance: zero script payload, explicit image dimensions, local assets, content visibility for long offscreen sections when safe.
- Compatibility: GitHub Pages static hosting and current evergreen browsers.
- Verification: HTML/link sanity, docs generation check, targeted repository tests, real-browser desktop/tablet/mobile screenshots, keyboard flow, console inspection, and Lighthouse when the available Chrome/CDP path supports it.

## Accepted debt
- Existing poster images retain their current raster formats until a separate asset-optimization goal can regenerate equivalent responsive formats.
- The long bilingual Hermes architecture article remains content-heavy; this redesign normalizes its shell and typography without rewriting its source-backed article.

## Open questions
- None blocking this redesign.
