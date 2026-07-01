# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-06-25
- Primary product surfaces: GitHub Pages marketing site, documentation index, workflow detail pages, README-linked public assets.
- Evidence reviewed: `site/index.html`, `site/styles.css`, `site/docs/index.html`, `site/docs/hermes-agent-architecture/index.html`, `README.md`, `docs/DIRECTION.md`, `docs/ROADMAP.md`, `docs/CAPABILITIES.md`, `site/assets/*`, `https://omo.dev/ko`.

## Brand
- Personality: precise, capable, chat-native, operator-grade, calm under pressure.
- Trust signals: deterministic contracts, local artifacts, visible evidence boundaries, Hermes-owned chat continuity, selected executor handoff.
- Avoid: generic CLI-product language, hidden-agent claims, oversized white card stacks, decorative gradients without product meaning, command-catalog sprawl, implying OMH runs code or platform bots by itself.

## Product goals
- Goals: make OMH understandable from the first viewport, show that Hermes remains the user-facing surface, make wrapper contracts and evidence boundaries feel tangible, keep installation and docs paths obvious, and turn the README core values into the primary site structure.
- Non-goals: do not reposition OMH as a standalone bot, LLM router, Hermes core patch, network service, or hidden coding executor.
- Success signals: a new visitor first sees "Oh My Hermes", then understands "Install once, keep Hermes, make the next step safe"; the site highlights capabilities, plugin/wrapper status, handoff, and evidence without command memorization; screenshots remain readable on mobile and desktop.

## Personas and jobs
- Primary personas: Hermes users, wrapper or adapter builders, maintainers evaluating delegation-first coding flows, operators responsible for release trust.
- User jobs: understand what OMH adds, install or inspect it, choose the right workflow lane, see what is prepared versus observed, follow docs for deeper contracts.
- Key contexts of use: GitHub README click-through, GitHub Pages browsing, maintainer review, wrapper integration planning, product demo.

## Information architecture
- Primary navigation: Home, Docs, Hermes Deepdive, GitHub.
- Core routes/screens: homepage, docs index, workflow detail pages, architecture guide.
- Content hierarchy: brand first, README hero image and install path second, README core values third, live-feeling contract example fourth, situation lanes fifth, evidence and architecture boundaries sixth.
- Core value spine: install once; keep Hermes chat-first; pick the smallest safe next step; keep contracts local and deterministic; never blur prepared state with observed proof.
- Docs hierarchy: start by decision, not by command. The docs index answers "install", "choose a lane", "wire a wrapper", "verify evidence", and sends detailed reference work to deeper pages.

## Design principles
- Principle 1: Show the product boundary as an interface, not as prose.
- Principle 2: Lead with natural-language Hermes usage before commands.
- Principle 3: Use short, high-contrast modules before any long reference copy.
- Principle 4: Treat workflow names as proof labels, not as the main story.
- Tradeoffs: keep enough narrative for trust, but compress repeated workflow lists into scannable modules and links.

## Visual language
- Color: preserve the existing teal, cyan, blue, and gold family, but bias the public site toward crisp black/white contrast with accent color used as evidence and routing signals.
- Typography: large confident headings, compact labels, generous line height for explanatory copy, tabular/mono styling only for contracts and commands. Use a local humanist system stack; do not depend on external fonts.
- Spacing/layout rhythm: full-width bands with constrained inner grids; no nested decorative cards; compact repeated items.
- Shape/radius/elevation: 8px radius maximum for cards and tools, hairline borders, restrained shadows, glow only where it reinforces route/status states.
- Motion: subtle hover lift, route shimmer, console scan, and focus transitions; respect reduced motion.
- Imagery/iconography: use the README `assets/hermes-agent-hero.png` artwork as the homepage hero source, copied into `site/assets/` for GitHub Pages; avoid legacy hero variants and decorative-only art.

## Components
- Existing components to reuse: `topbar`, `nav`, `button`, `footer`, command blocks, poster frames, state pills, route/evidence cards.
- New/changed components: homepage README-image hero, top hero installer terminal, full install terminal, core-value ledger, natural-message routing board, situation lane strip, truth boundary stack, docs decision map, docs value rail.
- Variants and states: hover, focus-visible, disabled/gated, ready/pending, mobile stacked layouts, reduced motion.
- Token/component ownership: `site/styles.css` owns static site tokens and components; HTML pages should not inline style decisions.

## Accessibility
- Target standard: WCAG 2.1 AA for contrast, focus, structure, and reduced motion.
- Keyboard/focus behavior: all links and command regions receive visible focus outlines; interactive-looking disabled controls must use real disabled semantics or non-button spans.
- Contrast/readability: avoid low-contrast cyan on white; dark hero overlays must keep text readable; every key statement must be understandable when skimmed without adjacent paragraphs.
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
- Microcopy rules: avoid unexplained command lists in primary copy; keep the hero install block to `curl | sh` and `omh setup`; keep the full install block readable with Hermes tap/install commands preserved below the local installer; pair workflow names with the job they perform; never claim execution, review, CI, delivery, or plugin load unless observed; keep default public copy in English.

## Implementation constraints
- Framework/styling system: static HTML and CSS under `site/`; no frontend build step.
- Design-token constraints: update CSS custom properties before introducing one-off colors.
- Performance constraints: keep assets committed and reuse existing images; avoid JavaScript unless a behavior cannot work accessibly in CSS.
- Compatibility constraints: GitHub Pages static hosting; docs pages share `site/styles.css`.
- Test/screenshot expectations: run static generation/check commands when available, HTML/CSS sanity checks, and responsive screenshot smoke tests for desktop and mobile.

## Open questions
- [ ] Whether the public homepage should include live release status from tags or remain static copy / maintainer / low impact.
- [ ] Whether future docs pages should adopt the same darker homepage system or stay more document-like / maintainer / medium impact.
