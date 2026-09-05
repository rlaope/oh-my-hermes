# OMH Design Workspace — Apple-Inspired Web Example

Design specification for `examples/apple-design/index.html`, a self-contained,
static, Apple-inspired **design example** for the `omh-apple-design` skill.
It is sample material, not a product feature: every apparent run, finding, and
project in the page is deterministic sample data, and the page says so in the
UI ("Design example · Sample data · Not connected").

Guidance basis: `skills/omh-apple-design/SKILL.md` and its references
(`platform-foundations.md`, `materials-and-accessibility.md`,
`review-playbook.md`), `docs/APPLE-DESIGN.md`, and the frontend taste/token
discipline in `skills/omh-frontend/references/taste-foundations.md`. Apple
sources named below were checked on 2026-09-05 in those documents; this page
follows that verified guidance and does not claim a measured skill execution.

## 1. Direction

**Primary direction: operational.** A design workspace is a dense working
surface: source-list sidebar, compact metadata, evidence tables, restrained
color. One element is deliberately borrowed from the premium/soft direction:
layered depth on the visual specimen card and a translucent navigation layer,
because the subject of the page is Apple-style material and type craft, and the
specimen is the "generated result" the page exists to show.

Directions considered (per skill: 2–4 before visual work):

1. **Quiet operational** — chosen. Dense macOS-style source list + bright
   content plane; blue reserved for selection, links, and primary actions.
2. **Editorial marketing** — rejected: a workspace brief needs density and
   evidence tables, not whitespace-led long-form reading.
3. **Deep glass** — rejected: HIG Materials puts Liquid Glass on the controls
   and navigation layer, not on content cards; a glass-everywhere web page
   would misstate the guidance it demonstrates.

Explicitly avoided: generic SaaS AI template look (uniform card grid, huge
rounded gradients, emoji icons), fake macOS window chrome (no traffic-light
buttons), and any Apple asset (no Apple logo, no SF Symbols, no bundled SF
fonts).

## 2. Design tokens

All colors, sizes, spaces, radii, and shadows in `index.html` come from these
custom properties. No visual property is hardcoded outside the token blocks.
Every text/background pair below was checked with a WCAG relative-luminance
script on 2026-09-05; all listed pairs are ≥ 4.5:1 (AA normal text).

### 2.1 Color — light (default)

| Token | Value | Role | Contrast evidence |
| --- | --- | --- | --- |
| `--canvas` | `#f5f5f7` | Window/page ground | — |
| `--surface` | `#ffffff` | Content cards (opaque, never glass) | — |
| `--bar-tint` | `rgba(245,245,247,.78)` | Toolbar/sidebar translucency (blur layer only) | opaque fallback `#eff0f3` |
| `--line` | `#d9dade` | Hairline separators | decorative |
| `--line-strong` | `#c2c3ca` | Emphasized borders, high-contrast fallback | decorative |
| `--ink` | `#1c1d22` | Primary text | 16.82:1 on surface, 15.45:1 on canvas |
| `--ink-2` | `#4b4d57` | Secondary text | 8.41:1 on surface |
| `--ink-3` | `#6a6c75` | Tertiary text, captions | 5.23:1 surface, 4.80:1 canvas |
| `--accent` | `#0b5fd7` | Links, selection, primary action | 5.78:1 on surface; white on accent 5.78:1 |
| `--on-accent` | `#ffffff` | Text on accent | 5.78:1 |
| `--accent-tint` | `#e7effc` | Selected-row / chip tint | with `--accent-deep` 6.93:1 |
| `--accent-deep` | `#0a4ab0` | Text on accent tint | 6.93:1 |
| `--ok` / `--ok-tint` | `#177241` / `#e2f3e7` (text-on-tint `#155e33`) | Positive status | 5.97:1 / 6.79:1 |
| `--warn` / `--warn-tint` | `#6e4a00` / `#faf0da` | Caution status | 7.02:1 on tint |
| `--crit` / `--crit-tint` | `#b3273a` / `#fbe9ea` (text-on-tint `#a02532`) | High-severity status | 6.43:1 / 6.40:1 |

### 2.2 Color — dark (`prefers-color-scheme: dark`, or forced via switch)

| Token | Value | Contrast evidence |
| --- | --- | --- |
| `--canvas` | `#101114` | — |
| `--surface` | `#1b1c20` | — |
| `--surface-raised` | `#222329` | — |
| `--bar-tint` | `rgba(23,24,28,.72)` (opaque fallback `#17181c`) | — |
| `--line` / `--line-strong` | `#2e2f36` / `#3c3d45` | decorative |
| `--ink` | `#f0f1f4` | 15.07:1 on surface |
| `--ink-2` | `#b4b7c0` | 8.49:1 on surface |
| `--ink-3` | `#969aa4` | 6.04:1 on surface |
| `--accent` | `#6ea6ff` | 6.94:1 on surface |
| `--on-accent` | `#071023` | 7.73:1 on accent |
| `--accent-tint` / `--accent-deep` | `#12233f` / `#a8c7ff` | 9.18:1 |
| `--ok` on `--ok-tint` | `#7fd6a0` on `#11291b` | 8.87:1 |
| `--warn` on `--warn-tint` | `#e5b567` on `#2b2110` | 8.39:1 |
| `--crit` on `--crit-tint` | `#f2919c` on `#341418` | 7.39:1 |

### 2.3 Typography

System stack only — no embedded or downloaded fonts, no claim of SF Pro:

- Text: `system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`
- Mono (identifiers, hex values): `ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace`

Scale (rem-based so browser zoom and text-size settings reflow; Dynamic Type
is an iOS/iPadOS API and is deliberately **not** claimed here):

| Token | Size | Weight | Line height | Tracking | Use |
| --- | --- | --- | --- | --- | --- |
| `--fs-display` | `clamp(1.85rem, 1.35rem + 2vw, 2.55rem)` | 700 | 1.12 | −0.022em | Page title |
| `--fs-title1` | `1.375rem` | 600 | 1.2 | −0.014em | Section titles |
| `--fs-title2` | `1.0625rem` | 600 | 1.3 | −0.006em | Card titles |
| `--fs-body` | `0.9375rem` | 400 | 1.55 | 0 | Body text |
| `--fs-foot` | `0.8125rem` | 400 | 1.45 | 0 | Metadata, footnotes |
| `--fs-cap` | `0.6875rem` | 600 | 1.3 | +0.06em, uppercase | Eyebrows, group labels |

The specimen card renders this exact ramp as the "generated result", including
one clearly-labeled Korean locale line (`lang="ko"`, system CJK fallback) to
show the stack under a non-Latin script. That line is a locale specimen, not a
translation of the UI.

### 2.4 Space, radius, elevation, focus

- Spacing (4px base): `--sp-1..--sp-8` = 4, 8, 12, 16, 24, 32, 48, 64 px.
- Radii: `--r-s: 6px` (chips, inputs), `--r-m: 10px` (cards, rows),
  `--r-l: 14px` (feature cards), `--r-pill: 999px`.
- Shadows: `--shadow-1: 0 1px 2px rgba(12,14,20,.06)`,
  `--shadow-2: 0 12px 32px rgba(12,14,20,.12)` (specimen/feature only).
- Focus: global `:focus-visible` ring, `2px solid var(--accent)`,
  `outline-offset: 2px`. Hidden radio patterns re-attach the ring to their
  visible label.

## 3. Layout

- Shell: sticky translucent toolbar (52px min) over a two-column grid —
  `232px` sidebar + `minmax(0,1fr)` content plane, content column capped at
  1120px. Only the toolbar and sidebar use the translucent bar material;
  **all content cards are opaque** per HIG Materials.
- Asymmetric hierarchy (anti card-grid-slop): brief/platform row is
  `1.55fr / 1fr`; review row is `1.6fr` findings against a `1fr` sources
  rail; the specimen card is full-width with an internal `1.35fr / 1fr`
  split (type ramp vs. color/material samples).
- Breakpoints (no horizontal scroll at 375 / 768 / 1280 / 1440):
  - `≤ 680px` — sidebar collapses to a wrapping chip nav above content; the
    static Library sample list and sidebar footer are hidden (their labels
    are duplicated in the toolbar badge).
  - `681–1099px` — 200px sidebar, single-column content sections.
  - `≥ 1100px` — full asymmetric grids.

## 4. Components and interactive states

| Component | Implementation | States |
| --- | --- | --- |
| Toolbar | translucent `backdrop-filter` bar; opaque under `prefers-reduced-transparency`, `prefers-contrast: more`, or missing `backdrop-filter` support | sticky; wraps at 375px |
| Sample badge | pill in toolbar: "Design example · Sample data · Not connected" | static, always visible |
| Appearance switch | 3 native radios (Auto/Light/Dark) styled as a segmented control; CSS-only via `:root:has(...:checked)` | checked, hover, `:focus-visible` ring on label; arrow-key group navigation is native |
| Sidebar nav | real in-page anchors with original inline-SVG glyphs; `aria-current="true"` on Overview with tint + leading-bar treatment (not color alone) | default, hover, current, focus-visible |
| Library list | static `<ul>` sample rows, explicitly labeled sample; not links (no dead controls) | none (static specimen) |
| Platform choice | 3 native radios (iOS / macOS / Web, Web preselected) as segmented control; the matching convention note is shown via `:has()`; without `:has()` support all three notes remain visible (safe fallback) | checked, focus-visible, note swap |
| Review notes | native `<details>`/`<summary>` per finding | closed (default), open, focus-visible; marker rotation suppressed under reduced motion |
| Buttons | anchors styled as buttons, all pointing at real in-page targets | default, hover, active, focus-visible |
| Status chips | tinted pills (`Prepared`, `not_observed`, `Sample`, severities) | static |
| Specimen card | opaque raised card: type ramp, token swatches (painted from live tokens, labeled with light+dark hex), material demo stage, control samples | swatches and material demo follow the active appearance |

Motion: hover/active transitions ≤ 160ms and one gentle section fade-rise on
load, both wrapped in `@media (prefers-reduced-motion: no-preference)`.

## 5. Accessibility and preference matrix

- Semantic landmarks: `header`, `nav`, `main`, `aside`, `footer`; skip link
  first in DOM; one `h1`; ordered heading levels.
- Keyboard: everything interactive is a native link, radio, or `<summary>`;
  visible focus ring everywhere; no positive `tabindex`.
- `prefers-color-scheme: dark` — auto dark token set; the switch can force
  Light/Dark; in browsers without `:has()` the switch degrades to Auto
  (documented limit, not a fake control — native radio state still toggles).
- `prefers-reduced-transparency: reduce` and `@supports not
  (backdrop-filter…)` — opaque bars.
- `prefers-contrast: more` — opaque bars, strong hairlines, tertiary text
  promoted to secondary color.
- `prefers-reduced-motion: reduce` — all transitions/animations disabled.
- Zoom/reflow: rem type scale + wrapping grids; this is the web analogue Apple
  typography guidance asks for — explicitly not Dynamic Type.

## 6. Evidence boundary

The page presents an `apple_design_brief/v1`-shaped sample and three sample
`apple_design_finding/v1`-shaped findings for a fictional "Aurora onboarding"
surface. Per the skill contract these are prepared artifacts: the page marks
`visual_status: not_observed`, claims no accessibility PASS, visual PASS,
Apple certification, or runtime execution, and invents no percentages, costs,
or live test results. Rendered evidence (screenshots under `previews/`) is
owned by the review lead's capture pass.

Sources named in-page (checked 2026-09-05 per `docs/APPLE-DESIGN.md`):
HIG Materials, HIG Typography, HIG Accessibility, "Adopting Liquid Glass",
and W3C WCAG for web applicability.

## 7. Verification plan (local, no server)

1. Token contrast script — all listed pairs ≥ 4.5:1 (run 2026-09-05, pass).
2. HTML structural check (tag balance, duplicate IDs, every `href="#…"`
   resolves, every `label[for]` resolves, no external asset references).
3. Open `index.html` via `file://` — no network, no JS, no console errors
   expected (page contains no scripts).
4. Browser screenshots at 375 / 768 / 1280 / 1440, light + dark — review
   lead's capture pass (`previews/desktop.png`, `previews/mobile.png`,
   `previews/dark.png`).
