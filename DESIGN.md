# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-06-25
- Primary product surfaces: GitHub Pages marketing site, documentation index, workflow detail pages, README-linked public assets.
- Evidence reviewed: `site/index.html`, `site/styles.css`, `site/docs/index.html`, `site/docs/hermes-agent-architecture/index.html`, `README.md`, `docs/DIRECTION.md`, `docs/ROADMAP.md`, `docs/CAPABILITIES.md`, `site/assets/*`.

## Brand
- Personality: precise, capable, chat-native, operator-grade, calm under pressure.
- Trust signals: deterministic contracts, local artifacts, visible evidence boundaries, Hermes-owned chat continuity, selected executor handoff.
- Avoid: generic CLI-product language, hidden-agent claims, oversized white card stacks, decorative gradients without product meaning, implying OMH runs code or platform bots by itself.

## Product goals
- Goals: make OMH understandable from the first viewport, show that Hermes remains the user-facing surface, make wrapper contracts and evidence boundaries feel tangible, keep installation and docs paths obvious.
- Non-goals: do not reposition OMH as a standalone bot, LLM router, Hermes core patch, network service, or hidden coding executor.
- Success signals: a new visitor can explain "Hermes chat in, renderable contract out"; the site highlights capabilities, plugin/wrapper status, handoff, and evidence without command memorization; screenshots remain readable on mobile and desktop.

## Personas and jobs
- Primary personas: Hermes users, wrapper or adapter builders, maintainers evaluating delegation-first coding flows, operators responsible for release trust.
- User jobs: understand what OMH adds, install or inspect it, choose the right workflow lane, see what is prepared versus observed, follow docs for deeper contracts.
- Key contexts of use: GitHub README click-through, GitHub Pages browsing, maintainer review, wrapper integration planning, product demo.

## Information architecture
- Primary navigation: Home, Docs, Hermes Deepdive, GitHub.
- Core routes/screens: homepage, docs index, workflow detail pages, architecture guide.
- Content hierarchy: thesis first, live-feeling contract example second, capability lanes third, evidence and architecture boundaries fourth, install path last.

## Design principles
- Principle 1: Show the product boundary as an interface, not as prose.
- Principle 2: Lead with natural-language Hermes usage before commands.
- Principle 3: Use dense but legible operator UI patterns instead of marketing fluff.
- Tradeoffs: keep enough narrative for trust, but compress repeated workflow lists into scannable modules and links.

## Visual language
- Color: preserve the existing teal, cyan, blue, and gold family; use deep ink backgrounds with warm off-white sections instead of plain white dominance.
- Typography: large confident headings, compact labels, generous line height for explanatory copy, tabular/mono styling only for contracts and commands.
- Spacing/layout rhythm: full-width bands with constrained inner grids; no nested decorative cards; compact repeated items.
- Shape/radius/elevation: 8px radius maximum for cards and tools, hairline borders, restrained shadows, glow only where it reinforces route/status states.
- Motion: subtle hover lift, route shimmer, console scan, and focus transitions; respect reduced motion.
- Imagery/iconography: use existing poster assets as real product artifacts; avoid decorative-only art.

## Components
- Existing components to reuse: `topbar`, `nav`, `button`, `footer`, command blocks, poster frames, state pills, route/evidence cards.
- New/changed components: homepage hero console, signal strip, contract pipeline, workflow matrix, proof cards, install terminal.
- Variants and states: hover, focus-visible, disabled/gated, ready/pending, mobile stacked layouts, reduced motion.
- Token/component ownership: `site/styles.css` owns static site tokens and components; HTML pages should not inline style decisions.

## Accessibility
- Target standard: WCAG 2.1 AA for contrast, focus, structure, and reduced motion.
- Keyboard/focus behavior: all links and command regions receive visible focus outlines; interactive-looking disabled controls must use real disabled semantics or non-button spans.
- Contrast/readability: avoid low-contrast cyan on white; dark hero overlays must keep text readable.
- Screen-reader semantics: keep landmark header/main/footer, aria labels for visual boards, real headings in order.
- Reduced motion and sensory considerations: animations must pause or flatten under `prefers-reduced-motion`.

## Responsive behavior
- Supported breakpoints/devices: mobile 360px+, tablet, laptop, desktop wide.
- Layout adaptations: hero and grids collapse to one column; nav wraps cleanly; command text and long code terms wrap without overflow.
- Touch/hover differences: hover effects are enhancements only; tap targets stay at least 40px high.

## Interaction states
- Loading: static site does not expose loading states.
- Empty: not applicable for homepage; docs can link to broader documentation.
- Error: not applicable for homepage.
- Success: ready/status pills and green evidence states communicate completion.
- Disabled: gated actions use muted visual language and clear labels without claiming availability.
- Offline/slow network, if applicable: local CSS and committed assets should render without external font or script dependencies.

## Content voice
- Tone: direct, confident, evidence-backed, product-operator language.
- Terminology: prefer "Hermes chat", "wrapper contract", "prepared versus observed", "selected executor", "local artifacts", "capability manifest".
- Microcopy rules: avoid unexplained command lists in primary copy; pair workflow names with the job they perform; never claim execution, review, CI, delivery, or plugin load unless observed.

## Implementation constraints
- Framework/styling system: static HTML and CSS under `site/`; no frontend build step.
- Design-token constraints: update CSS custom properties before introducing one-off colors.
- Performance constraints: keep assets committed and reuse existing images; avoid JavaScript unless a behavior cannot work accessibly in CSS.
- Compatibility constraints: GitHub Pages static hosting; docs pages share `site/styles.css`.
- Test/screenshot expectations: run static generation/check commands when available, HTML/CSS sanity checks, and responsive screenshot smoke tests for desktop and mobile.

## Open questions
- [ ] Whether the public homepage should include live release status from tags or remain static copy / maintainer / low impact.
- [ ] Whether future docs pages should adopt the same darker homepage system or stay more document-like / maintainer / medium impact.
