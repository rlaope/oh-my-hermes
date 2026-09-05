# Art direction — OMH 3D hero before/after

Complete scene spec so the render is reproducible from source. All numbers
below are the literal constants in `renderer.js`.

## Concept

One original industrial sculpture — **two interlocked rounded-square links**
— as a metaphor for linked workflows ("Work, in harmony."). The same
geometry, pose, camera, and scale appear in both panels; only material and
light change. That is the entire argument of the page: *same scene,
different craft.*

Apple art-direction references (references only, no assets or measurements
taken from them):

- MacBook Pro marketing — metal edge lighting: long soft speculars that wrap
  a machined edge → the AFTER key softbox + rim strip.
- AirPods Pro macro shots — generous white negative space around dense,
  curved product forms → composition and margins.
- Vision Pro — glass depth: cool transmission with bright Fresnel edges →
  the AFTER glass link.

Explicitly avoided: neon/rainbow blob renders, gray-diffuse "metal",
alpha-only "glass", UI cards/chrome around the render, Apple logos or
product look-alikes.

## Geometry (SDF, sculpture space)

One link = rounded-square ring: path is a 2D rounded box (half extent 0.62,
corner radius 0.34) in the local XY plane, extruded along local Z with a
beveled rectangular cross-section — in-plane half width 0.17, half depth
0.14, edge bevel 0.055 (`sdRBox2` of `(pathDist, p.z)`).

- Link 1: XY plane, center (−0.35, 0, 0) — the "upright" ring.
- Link 2: XZ plane (coordinates swizzled `.xzy`), center (+0.35, 0, 0) —
  the "flat" ring threading link 1's hole.

Center separation 0.70 gives ~0.10 of machined clearance where each link
passes through the other's opening (checked analytically: ring-2 tube outer
face at x = −0.10 vs ring-1 inner wall at x = +0.10). Total width ≈ 2.28
units.

Pose: `R = Ry(0.58) · Rx(0.24) · Rz(−0.08)` (the shader stores the inverse),
lifted +0.06; floor plane at y = −0.76 → a small grounded float with a soft
contact shadow, like a product still.

## Camera

Position (0, 0.42, 4.35), target (0, −0.14, 0), focal factor 2.65
(mildly telephoto, editorial compression). Static; identical in both panels.

## Lighting

Key direction `normalize(−0.5, 0.9, 0.45)` — large source above-left-front.

- **BEFORE environment:** silver-white gradient backdrop plus one very large,
  very soft dome box and a weak frontal fill — broad, fairly uniform,
  ordinary. Shadow penumbra k = 3.5 (wide, light).
- **AFTER environment:** slightly deeper backdrop, key softbox 3.4× at
  (−0.52, 0.78, 0.34) sized 0.70×0.42, narrow rim strip 1.5× at
  (0.86, 0.18, −0.12) sized 0.10×0.85, frontal fill 0.85×, and a darkened
  floor zone for reflection contrast. Shadow penumbra k = 7–9 (defined),
  plus a subtle floor reflection (single secondary ray, `exp` falloff) and a
  cool tint inside the glass link's shadow.

## Materials

- **BEFORE (both links):** blue satin polymer — albedo (0.155, 0.305, 0.615),
  wrap diffuse, hemispherical ambient, satin specular lobe (exp 44), faint
  environment sheen, mild Fresnel rim. Competent, not deliberately ugly.
- **AFTER link 1:** precision satin aluminum — tint (0.945, 0.950, 0.960),
  roughness 0.19 environment reflection, F = 0.55 + 0.45·Fresnel, key
  specular exp 120, floor-bounce and AO terms. Reads as machined metal, not
  gray diffuse.
- **AFTER link 2:** cool-blue optical glass — IOR 1.45 entry refraction,
  interior thickness march, exit refraction (TIR fallback), Beer–Lambert
  absorption `exp(−(0.55, 0.22, 0.06)·2.0·thickness)` (cool blue in thick
  chords), Fresnel-weighted mirror reflection, sharp key specular (exp 420),
  and a secondary trace so the aluminum link shows through the glass. Not
  claimed as physically full glass — see README limitations.

Tone mapping: soft highlight knee at 0.85 → gamma 2.2 → ±0.5/255 hash dither
(deterministic) against gradient banding.

## Page composition

- 1600×1050-first; full-bleed side-by-side panels separated by a 2 px
  page-ground seam; panels stack under 760 px.
- HTML overlay only (no text baked into the render): OMH wordmark (tiny
  inline-SVG interlocked-links glyph + letterspaced "OMH"), shared headline
  **Work, in harmony.**, kicker **Same scene. Different craft.**, per-panel
  BEFORE/AFTER tags with one-line material notes, disclaimer footer.
- Tokens follow the sibling workspace example (`--canvas #f4f4f6`, ink ramp
  `#1c1d22/#4b4d57/#6a6c75`, 0.25rem-based spacing scale, system font stack).

## Iteration log (what was tuned after real renders)

1. First render: pose/interlock correct; metal too flat, object floating too
   high, glass inner-march streaks. → raised floor (−0.88 → −0.76), lowered
   camera target, stronger key/rim boxes, finer glass march steps.
2. Second render: aluminum too graphite. → environment base 0.82×, frontal
   fill 0.85×, brighter cheap-shade for glass-behind-glass, +ambient term.
3. Third render: shipped look (proof at 1600×1050; 390×844 stacked, no
   horizontal overflow).
