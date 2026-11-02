# Design Critique Rubric

The critique lane's question is never "is it correct?" — it is "does this
clear what a senior product designer at a top-tier product company — the Linear/Stripe/Supabase class — would sign off on?". **Technically clean but flat fails.** Judge each
axis explicitly; a PASS with no named evidence per axis is not a review.

## Axes

- **Hierarchy** — one glance names what leads, what supports, what recedes.
  FAIL: adjacent elements competing at equal weight; headings that do not
  organize scanning.
- **Type discipline** — a modular scale is in use; display and body behave
  differently on purpose. FAIL: arbitrary sizes, one step doing three jobs,
  broken CJK line-height.
- **Spacing rhythm** — values come from the scale; sibling gaps agree;
  sections breathe in proportion to their weight. FAIL: off-scale values,
  touching sections, arrhythmic padding, a logo or identity mark with less
  than one of its own text rows of clear space from the frame or window edge
  (an intentional crop is exempt).
- **Color system** — layered backgrounds, text hierarchy through color, a
  deliberate accent budget, semantic states. FAIL: one flood color plus
  gray; decorative gradients with no role; contrast under the floor.
  For a composed frame (promo, poster, slide, end card), judge harmony from
  a written hue-family list, not by eye: every family on screen with its hex
  values and where it appears (background, chrome, subject, logo, captions,
  accents). The captured product or brand palette is given and never
  repainted; the surrounding composition adds at most one accent family
  beyond it. Neutrals, semantic-state colors and data-series palettes are
  listed but not counted. Text contrast is at least 4.5:1, or 3:1 for large
  type, on the background it actually sits on. Run the list before render;
  after render it only confirms.
- **State coverage** — primitives show hover, focus-visible, active,
  disabled, loading, error, and empty. FAIL: any interactive element with
  only a default state.
- **Signature** — at least one deliberate element a template would not
  have. FAIL: nothing distinguishes this surface from its framework's
  example app.
- **Motion restraint** — animation communicates state or causality within
  duration tokens and respects reduced motion. FAIL: decorative motion,
  scroll hijacking, ignored `prefers-reduced-motion`.
- **CJK and localization fit** — when the audience needs it: fallback
  stacks, line-height, and truncation behave in the heavy script. FAIL:
  Latin-tuned metrics breaking CJK text.
- **Default-prior fit** — the surface does not silently inherit the model's
  own house aesthetic (cream ground, serif display, terracotta accent) where
  the brief is operational or data-dense. FAIL: an editorial prior applied to
  a dashboard, fintech, or developer-tool surface with no stated reason.
- **Chosen, not inherited** — framework blue, glass surfaces, gradient
  accents, the default UI typeface, per-surface shadows, uniform column
  grids, and decorative meta text (window title bars, dimension labels,
  invented paths) each carry a stated reason or are replaced. FAIL: a default present
  with no rationale, checked against the review prompts in
  `omh-frontend/references/taste-foundations.md`.
- **Material credibility** — for a composed frame that shows a physical
  product (a device, a package, hardware), the object reads as a lit model
  with real materials and a measured tonal range. FAIL: an object built from
  stacked flat layers, a surface whose measured bulk sits near white around a
  radial hotspot, or a brand title set in a generic face where the brand's own
  live typeface was available.
- **Short-clip discipline** — for a promo or social clip of 15 s or less:
  one hero scene held throughout, the official logo unboxed at 25% or more of
  the frame height in the opening, one key number smaller than the logo, and
  smooth dithered gradients with local light on the subject. FAIL: scene
  cuts or an end-card lockup, meta text (explanatory labels, subheads, IDs,
  URLs, footnotes), a second number or a giant extruded one, a small or boxed
  logo, slop UI (glass cards, pill or "LIVE" badges, stat boxes, terminal or
  dashboard capture), visible banding, or no still sheet reviewed before
  render.

## Scoring the axes

The axes produce the deductions; the number and the stopping rule live in
`omh-visual-qa/references/visual-verdict-contract.md`. Use them together —
each FAIL named here becomes one entry in that contract's `differences` list,
paired with the smallest change that would flip it, and the round carries an
integer score with its verdict. 90 is the pass line; under it the verdict is
REVISE and another edit-and-recapture round is owed, not a softer adjective.

## Verdict discipline

- Review content accuracy and hierarchy before visual polish; a beautiful
  wrong page fails first on content.
- Name the taste direction the work claims — the primary direction
  (operational, minimalist/editorial, premium/soft, or bold/expressive)
  declared per the frontend skill's
  `omh-frontend/references/taste-foundations.md` — then judge inside it: an
  operational tool is not failed for lacking gloss, and a premium surface
  is failed for it.
- Every FAIL names the axis, the evidence, and the smallest change that
  would flip it.
- A PASS requires fresh rendered evidence from the visual-QA owner across
  the declared pages, states, and viewports; the rubric never passes work
  from description alone.

## Attribution

The idea of pairing a design-system contract file with taste-direction
material and an evidence-bound critique lane adapts concepts from the
`frontend` skill of `code-yeongyu/oh-my-openagent@9c62b62` (Sustainable Use
License 1.0) and its permissively licensed design upstreams:
`Leonxlnx/taste-skill` (MIT), `nextlevelbuilder/ui-ux-pro-max-skill` (MIT),
`Owl-Listener/designpowers` (MIT), and `nexu-io/open-design` (Apache-2.0).
No upstream text is reproduced; the wording here is OMH's own, and OMH keeps
its deterministic no-render boundary. Product names appear as quality
analogies only; OMH is not affiliated with, endorsed by, or sponsored by any
named company.
