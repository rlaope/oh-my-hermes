# Web Production Library Decisions

## Source record

These are optional web-production references for an **explicit Apple
marketing/product visual** or explicit `apple-design` invocation. They are not
native Apple APIs, do not establish Liquid Glass equivalence, and do not route
generic GSAP, logo, or glass requests into this skill. Inspect the current
project's dependency, build, runtime, and license policy before the selected
coding owner integrates any of them; OMH does not install, vendor, or fetch
libraries at runtime.

- GSAP, reviewed at `13e2b790546426a1a2e0e9b409f3f8dc6d6611f2` on 2026-09-05:
  https://github.com/greensock/gsap — framework-agnostic animation with
  `gsap`, `gsap.context()`, `gsap.matchMedia()`, and optional ScrollTrigger.
  Its package declares the GreenSock Standard "no charge" license; do not call
  it an OSI license or assume every plugin has the same distribution posture.
- liquid-logo, reviewed at `689bb38a1e0d5a6a8baf2d34847635eefde19994` on
  2026-09-05: https://github.com/paper-design/liquid-logo — a private Next
  application under PolyForm Shield 1.0.0, not an npm package or reusable
  drop-in. Its dependencies include `@paper-design/shaders-react`; inspect
  `paper-logo.tsx` and `liquid-frag.ts` before applying any pattern. They show
  original-logo input and shader uniforms for edge, pattern blur/scale,
  refraction, liquid amount, and speed.
- liquid-glass-js, reviewed at `78cb6ccb0b9987bb60a88b14ccbd13a9e6e8ab2a`
  on 2026-09-05: https://github.com/dashersw/liquid-glass-js — MIT-licensed
  standalone browser files with `Container` and `Button` WebGL classes and an
  optional `html2canvas` page-capture path. Its visual effect is a web effect,
  not Apple native material.

## Selection and integration

**GSAP:** Select only when the existing project already permits GSAP and needs
a sequence, scroll response, or object/camera reveal that CSS cannot express
cleanly. The selected owner scopes animation with `gsap.context()` and uses
`gsap.matchMedia()` to add the motion branch and a `prefers-reduced-motion`
static or shortened branch. Register ScrollTrigger only when the existing
project already includes and needs it. Return cleanup through `context.revert()`
and `matchMedia.revert()`; do not leave timelines, ScrollTriggers, or listeners
alive after route/component teardown. Verify actual browser frames or video for
both branches after the last change.

**liquid-logo:** Select as link-only technical research for an original,
user-owned logo experiment when the owner has separately approved the license
and a project-specific implementation path. Do not import, copy, vendor, or
represent the application as a package. Its useful recipe is architectural:
keep source-logo input, shader parameters, resize handling, request-animation-
frame loop, and cancellation/resize cleanup as separate owned decisions. Supply
a static image or ordinary logo fallback when WebGL2, motion, or GPU budget is
unavailable; inspect the rendered result rather than calling a parameter change
an observed visual improvement.

**liquid-glass-js:** Select only for a deliberately web-only experimental
control layer when its MIT source and the existing project's asset/runtime
policy allow an owner-authored integration. Its `Container`/`Button` recipe
uses chosen shape, radius, tint, child nesting, and `updateSizeFromDOM()` as
project choices. Do not silently add its optional `html2canvas` dependency or
CDN script: if page capture is not already approved and available, prepare a
no-capture alternative or stop at the handoff. The owner must add lifecycle
teardown for canvases, listeners, animation loops, and WebGL resources around
the chosen integration because this source documents no `destroy` or `dispose`
API. Prove normal, reduced-motion, opaque/static, keyboard, capture, and CORS
states with actual browser evidence.

## Evidence boundary

A library selection, code recipe, license note, or prepared handoff is not an
installed dependency, native Apple behavior, rendered output, motion proof,
accessibility PASS, or visual QA. Record the actual project version, license
review result, cleanup evidence, and rendered states supplied by the selected
coding owner before making those claims.
